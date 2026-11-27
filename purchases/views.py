import csv
from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q, Sum, Count
from django.core.paginator import Paginator
from django.core.exceptions import ValidationError
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from master_data.excel_utils import export_to_excel_response
from master_data.pagination_utils import paginate_queryset

from .models import (
    PurchaseOrder, PurchaseOrderItem, PurchaseOrderAttachment, PurchaseOrderComment,
    PurchaseReturnOrder, PurchaseReturnOrderItem
)
from .services import PurchaseOrderService, PurchaseReturnOrderService

from contacts.models import Contact, ContactAddress
from catalog.models import Product
from inventory.models import Warehouse
from treasury.models import VendorTransaction
from accounts.permissions import require_permission, has_perm_or_admin, render_forbidden_response, can_user_access_object, get_scoped_queryset
from accounts.scope_service import ScopeResolutionService
from master_data.search_utils import (
    filter_by_arabic_search,
    parse_search_limit,
    get_bounded_select_options,
    serialize_contact_option,
    serialize_warehouse_option,
    serialize_vault_option,
)


@require_permission('purchases:orders/list')
def purchase_orders_list(request):
    from master_data.filter_utils import parse_multi_str, parse_single_int
    from master_data.date_filter_utils import resolve_date_range

    status_choices_dict = dict(PurchaseOrder.STATUS_CHOICES)
    payment_choices_dict = dict(PurchaseOrder.PAYMENT_STATUS_CHOICES)
    selected_statuses = [s for s in parse_multi_str(request.GET, 'status') if s in status_choices_dict]
    selected_payment_statuses = [p for p in parse_multi_str(request.GET, 'payment_status') if p in payment_choices_dict]
    payment_status_filter = selected_payment_statuses[0] if len(selected_payment_statuses) == 1 else 'all'

    supplier_id_int = parse_single_int(request.GET, 'supplier')
    supplier_filter = str(supplier_id_int) if supplier_id_int else ''
    search = request.GET.get('search', '').strip()
    parsed_from, parsed_to, active_preset, date_from, date_to = resolve_date_range(request, default_preset='all_time')
    total_min = request.GET.get('total_min', '').strip()
    total_max = request.GET.get('total_max', '').strip()
    remaining_min = request.GET.get('remaining_min', '').strip()
    remaining_max = request.GET.get('remaining_max', '').strip()

    qs = PurchaseOrder.objects.select_related(
        'supplier', 'supplier__area', 'target_warehouse', 'created_by'
    ).all().order_by('-serial_num')
    qs = get_scoped_queryset(qs, request.user, 'purchaseorder')
    qs = PurchaseOrder.with_payment_totals(qs)

    active_filters = []

    if selected_statuses:
        qs = qs.filter(status__in=selected_statuses)
        for s in selected_statuses:
            active_filters.append({'label': 'حالة الطلب', 'value': status_choices_dict.get(s, s), 'param': 'status', 'remove_value': s})

    if selected_payment_statuses:
        qs = qs.filter(payment_status__in=selected_payment_statuses)
        for ps in selected_payment_statuses:
            active_filters.append({'label': 'حالة السداد', 'value': payment_choices_dict.get(ps, ps), 'param': 'payment_status', 'remove_value': ps})

    if supplier_id_int:
        qs = qs.filter(supplier_id=supplier_id_int)
        s_obj = ScopeResolutionService.get_scoped_choices(request.user, 'suppliers', 'purchases').filter(id=supplier_id_int).first()
        active_filters.append({'label': 'المورد', 'value': s_obj.name if s_obj else supplier_filter, 'param': 'supplier'})

    if parsed_from:
        qs = qs.filter(order_date__gte=parsed_from)
        active_filters.append({'label': 'من تاريخ', 'value': date_from, 'param': 'date_from'})

    if parsed_to:
        qs = qs.filter(order_date__lte=parsed_to)
        active_filters.append({'label': 'إلى تاريخ', 'value': date_to, 'param': 'date_to'})

    # Financial Total Amount Range Filters (Requirement B1)
    if total_min:
        try:
            val_min = Decimal(total_min)
            qs = qs.filter(grand_total__gte=val_min)
            active_filters.append({'label': f'الحد الأدنى للقيمة: {val_min:,.2f} ج.م', 'param': 'total_min'})
        except Exception:
            total_min = ''

    if total_max:
        try:
            val_max = Decimal(total_max)
            qs = qs.filter(grand_total__lte=val_max)
            active_filters.append({'label': f'الحد الأقصى للقيمة: {val_max:,.2f} ج.م', 'param': 'total_max'})
        except Exception:
            total_max = ''

    # Remaining Outstanding Balance Range Filters (Requirement B1)
    from django.db.models import F
    if remaining_min:
        try:
            rem_min = Decimal(remaining_min)
            qs = qs.filter(grand_total__gte=F('_annotated_total_paid') + rem_min)
            active_filters.append({'label': f'الحد الأدنى للمتبقي: {rem_min:,.2f} ج.م', 'param': 'remaining_min'})
        except Exception:
            remaining_min = ''

    if remaining_max:
        try:
            rem_max = Decimal(remaining_max)
            qs = qs.filter(grand_total__lte=F('_annotated_total_paid') + rem_max)
            active_filters.append({'label': f'الحد الأقصى للمتبقي: {rem_max:,.2f} ج.م', 'param': 'remaining_max'})
        except Exception:
            remaining_max = ''

    if search:
        qs = filter_by_arabic_search(qs, search, ['order_number', 'serial_num', 'supplier__name', 'supplier__area__name'])
        active_filters.append({'label': f'بحث: {search}', 'param': 'search'})

    po_agg = qs.aggregate(
        total_orders=Count('id'),
        total_value=Sum('grand_total'),
        total_paid=Sum('_annotated_total_paid'),
    )
    tot_val = po_agg['total_value'] or Decimal('0.00')
    tot_paid = po_agg['total_paid'] or Decimal('0.00')
    tot_rem = max(Decimal('0.00'), tot_val - tot_paid)
    stats = {
        'total_orders': po_agg['total_orders'] or 0,
        'total_value': tot_val,
        'total_paid': tot_paid,
        'total_remaining': tot_rem,
    }

    suppliers = get_bounded_select_options(
        ScopeResolutionService.get_scoped_choices(request.user, 'suppliers', 'purchases'),
        selected_id=supplier_filter,
        limit=100,
    )

    # Bounded server-side pagination (default 25)
    paginator, page_obj = paginate_queryset(request, qs, default_per_page=25, max_per_page=100)

    po_status_options = [{'value': k, 'label': v} for k, v in PurchaseOrder.STATUS_CHOICES]
    selected_po_status_items = [o for o in po_status_options if o['value'] in selected_statuses]
    po_payment_options = [{'value': k, 'label': v} for k, v in PurchaseOrder.PAYMENT_STATUS_CHOICES]
    selected_po_payment_items = [o for o in po_payment_options if o['value'] in selected_payment_statuses]

    context = {
        'orders': page_obj.object_list,
        'page_obj': page_obj,
        'paginator': paginator,
        'current_payment_status': payment_status_filter,
        'payment_statuses': PurchaseOrder.PAYMENT_STATUS_CHOICES,
        'po_status_options': po_status_options,
        'selected_po_status_items': selected_po_status_items,
        'selected_statuses': selected_statuses,
        'po_payment_options': po_payment_options,
        'selected_po_payment_items': selected_po_payment_items,
        'selected_payment_statuses': selected_payment_statuses,
        'active_preset': active_preset,
        'selected_supplier': supplier_filter,
        'search_query': search,
        'selected_date_from': date_from,
        'selected_date_to': date_to,
        'selected_total_min': total_min,
        'selected_total_max': total_max,
        'selected_remaining_min': remaining_min,
        'selected_remaining_max': remaining_max,
        'date_from': date_from,
        'date_to': date_to,
        'suppliers': suppliers,
        'active_filters': active_filters,
        'active_filters_count': len(active_filters),
        'total_count': paginator.count,
        'stats': stats,
    }
    return render(request, 'purchases/purchase_orders_list.html', context)


@require_permission('purchases:orders/create')
def purchase_order_create(request):
    if request.method == 'POST':
        supplier_id = request.POST.get('supplier')
        warehouse_id = request.POST.get('warehouse')
        order_date = request.POST.get('order_date') or timezone.now().date()
        expected_delivery_date = request.POST.get('expected_delivery_date') or None
        due_date = request.POST.get('due_date') or None
        custom_discount_percentage = request.POST.get('custom_discount_percentage') or '0.00'
        shipping_fees = request.POST.get('shipping_fees') or '0.00'
        delivery_agent = request.POST.get('delivery_agent', '').strip()
        delivery_time = request.POST.get('delivery_time', '').strip()
        notes = request.POST.get('notes', '').strip()

        # Parse dynamic item rows
        product_ids = request.POST.getlist('product_id[]')
        quantities = request.POST.getlist('quantity[]')
        unit_prices = request.POST.getlist('unit_price[]')
        batch_numbers = request.POST.getlist('batch_number[]')
        expiry_dates = request.POST.getlist('expiry_date[]')
        discounts = request.POST.getlist('discount_percentage[]')

        items_data = []
        for i in range(len(product_ids)):
            p_id = product_ids[i]
            if not p_id:
                continue
            prod = Product.objects.filter(id=p_id).first()
            if not prod:
                continue
            qty = Decimal(quantities[i] or '1') if i < len(quantities) else Decimal('1')
            price = Decimal(unit_prices[i] or '0') if i < len(unit_prices) else Decimal('0')
            batch = batch_numbers[i] if i < len(batch_numbers) else ''
            exp = expiry_dates[i] if (i < len(expiry_dates) and expiry_dates[i]) else None
            disc = Decimal(discounts[i] or '0') if i < len(discounts) else Decimal('0')

            items_data.append({
                'product': prod,
                'quantity': qty,
                'unit_price': price,
                'batch_number': batch,
                'expiry_date': exp,
                'discount_percentage': disc
            })

        if not supplier_id or not warehouse_id:
            messages.error(request, "يرجى تحديد المورد والمخزن المستلم.")
            return redirect('purchase_order_create')

        supplier = get_object_or_404(Contact, id=supplier_id)
        if not ScopeResolutionService.can_user_access_supplier(request.user, supplier):
            return render_forbidden_response(request, "غير مصرح لك بإنشاء أمر شراء لمورد خارج نطاق منطقتك الجغرافية.")
        if not supplier.is_supplier or supplier.status == 'inactive':
            messages.error(request, "جهة الاتصال المحددة غير مصنفة كمورد نشط.")
            return redirect('purchase_order_create')
        warehouse = get_object_or_404(Warehouse, id=warehouse_id)
        if not can_user_access_object(request.user, warehouse, 'operate'):
            return render_forbidden_response(request, "غير مصرح لك باستخدام هذا المخزن المستلم.")

        try:
            order = PurchaseOrderService.create_order(
                supplier=supplier,
                target_warehouse=warehouse,
                order_date=order_date,
                expected_delivery_date=expected_delivery_date,
                due_date=due_date,
                items_data=items_data,
                user=request.user,
                custom_discount_percentage=Decimal(custom_discount_percentage),
                shipping_fees=Decimal(shipping_fees),
                notes=notes
            )
            if delivery_agent or delivery_time:
                order.delivery_agent = delivery_agent
                order.delivery_time = delivery_time
                order.save(update_fields=['delivery_agent', 'delivery_time'])
            if request.FILES.getlist('attachments'):
                from master_data.media_service import store_attachments_from_request
                store_attachments_from_request(order, request)

            messages.success(request, f"تم إنشاء أمر الشراء بنجاح ({order.order_number}) بإجمالي {order.grand_total:,.2f} ج.م.")
            return redirect('purchase_order_detail', pk=order.pk)
        except ValidationError as e:
            messages.error(request, str(e.message if hasattr(e, 'message') else e))
            return redirect('purchase_order_create')

    raw_selected_supplier = request.GET.get('supplier') or request.GET.get('supplier_id')
    suppliers = get_bounded_select_options(
        ScopeResolutionService.get_scoped_choices(request.user, 'suppliers', 'purchases'),
        selected_id=raw_selected_supplier,
        limit=100,
    )
    warehouses = ScopeResolutionService.get_scoped_choices(request.user, 'warehouses', 'purchases')
    products = Product.objects.filter(is_active=True).order_by('name')

    context = {
        'suppliers': suppliers,
        'warehouses': warehouses,
        'products': products,
        'selected_supplier_id': int(raw_selected_supplier) if raw_selected_supplier and str(raw_selected_supplier).isdigit() else None,
    }
    return render(request, 'purchases/purchase_order_create.html', context)


@require_permission('purchases:orders/edit')
def purchase_order_edit(request, pk):
    order = get_object_or_404(
        PurchaseOrder.objects.select_related('supplier', 'target_warehouse').prefetch_related('items__product'),
        pk=pk
    )
    if not can_user_access_object(request.user, order, 'edit'):
        return render_forbidden_response(request, "لا يمكنك تعديل هذا الطلب خارج نطاق منطقتك الجغرافية أو صلاحيتك.")

    if order.status in ['picked', 'settled', 'cancelled']:
        messages.error(request, f"لا يمكن تعديل أمر الشراء في حالته الحالية ({order.get_status_display()}).")
        return redirect('purchase_order_detail', pk=order.pk)

    if request.method == 'POST':
        supplier_id = request.POST.get('supplier')
        warehouse_id = request.POST.get('warehouse')
        order_date = request.POST.get('order_date') or order.order_date
        expected_delivery_date = request.POST.get('expected_delivery_date') or None
        due_date = request.POST.get('due_date') or None
        custom_discount_percentage = request.POST.get('custom_discount_percentage') or '0.00'
        shipping_fees = request.POST.get('shipping_fees') or '0.00'
        delivery_agent = request.POST.get('delivery_agent', '').strip()
        delivery_time = request.POST.get('delivery_time', '').strip()
        notes = request.POST.get('notes', '').strip()

        product_ids = request.POST.getlist('product_id[]')
        quantities = request.POST.getlist('quantity[]')
        unit_prices = request.POST.getlist('unit_price[]')
        batch_numbers = request.POST.getlist('batch_number[]')
        expiry_dates = request.POST.getlist('expiry_date[]')
        discounts = request.POST.getlist('discount_percentage[]')

        items_data = []
        for i in range(len(product_ids)):
            p_id = product_ids[i]
            if not p_id:
                continue
            prod = Product.objects.filter(id=p_id).first()
            if not prod:
                continue
            qty = Decimal(quantities[i] or '1') if i < len(quantities) else Decimal('1')
            price = Decimal(unit_prices[i] or '0') if i < len(unit_prices) else Decimal('0')
            batch = batch_numbers[i] if i < len(batch_numbers) else ''
            exp = expiry_dates[i] if (i < len(expiry_dates) and expiry_dates[i]) else None
            disc = Decimal(discounts[i] or '0') if i < len(discounts) else Decimal('0')

            items_data.append({
                'product': prod,
                'quantity': qty,
                'unit_price': price,
                'batch_number': batch,
                'expiry_date': exp,
                'discount_percentage': disc
            })

        if not supplier_id or not warehouse_id:
            messages.error(request, "يرجى تحديد المورد والمخزن المستلم.")
            return redirect('purchase_order_edit', pk=order.pk)

        supplier = get_object_or_404(Contact, id=supplier_id)
        if not ScopeResolutionService.can_user_access_supplier(request.user, supplier):
            return render_forbidden_response(request, "غير مصرح لك بإنشاء أمر شراء لمورد خارج نطاق منطقتك الجغرافية.")
        if not supplier.is_supplier or (supplier.pk != order.supplier_id and supplier.status == 'inactive'):
            messages.error(request, "جهة الاتصال المحددة غير مصنفة كمورد نشط.")
            return redirect('purchase_order_edit', pk=order.pk)
        warehouse = get_object_or_404(Warehouse, id=warehouse_id)
        if not can_user_access_object(request.user, warehouse, 'operate'):
            return render_forbidden_response(request, "غير مصرح لك باستخدام هذا المخزن المستلم.")

        try:
            order = PurchaseOrderService.update_order(
                order=order,
                supplier=supplier,
                target_warehouse=warehouse,
                order_date=order_date,
                expected_delivery_date=expected_delivery_date,
                due_date=due_date,
                items_data=items_data,
                user=request.user,
                custom_discount_percentage=Decimal(custom_discount_percentage),
                shipping_fees=Decimal(shipping_fees),
                notes=notes
            )
            if delivery_agent or delivery_time:
                order.delivery_agent = delivery_agent
                order.delivery_time = delivery_time
                order.save(update_fields=['delivery_agent', 'delivery_time'])
            if request.FILES.getlist('attachments'):
                from master_data.media_service import store_attachments_from_request
                store_attachments_from_request(order, request)

            messages.success(request, f"تم تعديل أمر الشراء بنجاح ({order.order_number}) بإجمالي {order.grand_total:,.2f} ج.م.")
            return redirect('purchase_order_detail', pk=order.pk)
        except ValidationError as e:
            messages.error(request, str(e.message if hasattr(e, 'message') else e))
            return redirect('purchase_order_edit', pk=order.pk)

    suppliers = get_bounded_select_options(
        ScopeResolutionService.get_scoped_choices(request.user, 'suppliers', 'purchases'),
        selected_id=order.supplier_id,
        limit=100,
    )
    warehouses = get_bounded_select_options(
        ScopeResolutionService.get_scoped_choices(request.user, 'warehouses', 'purchases'),
        selected_id=order.target_warehouse_id,
        limit=100,
    )
    products = Product.objects.filter(is_active=True).order_by('name')

    context = {
        'order': order,
        'suppliers': suppliers,
        'warehouses': warehouses,
        'products': products,
    }
    return render(request, 'purchases/purchase_order_edit.html', context)


@require_permission('purchases:orders/view')
def purchase_order_detail(request, pk):
    order = get_object_or_404(
        PurchaseOrder.objects.select_related(
            'supplier', 'supplier__area', 'target_warehouse', 'created_by', 'memo', 'memo__warehouse'
        ).prefetch_related('items__product', 'attachments', 'comments__author', 'vendor_payments__vault'),
        pk=pk
    )

    if not can_user_access_object(request.user, order, 'view'):
        return render_forbidden_response(request, "لا يمكنك عرض هذا الطلب خارج نطاق منطقتك الجغرافية أو صلاحيتك.")

    # Linked accounting transactions & settlements
    linked_tx = VendorTransaction.objects.filter(purchase_order=order).prefetch_related('installments__settlements').first()

    # Vendor financial summary
    if order.supplier:
        vendor_txs = VendorTransaction.objects.filter(account__supplier=order.supplier)
        total_debit = sum((t.debit for t in vendor_txs), Decimal('0.00'))
        total_credit = sum((t.credit for t in vendor_txs), Decimal('0.00'))
        current_vendor_balance = total_credit - total_debit
    else:
        total_debit = Decimal('0.00')
        total_credit = Decimal('0.00')
        current_vendor_balance = Decimal('0.00')

    is_super = request.user.is_superuser or getattr(request.user, 'is_super_admin', False)
    can_approve = has_perm_or_admin(request.user, 'purchases:orders/approve') and (is_super or order.created_by_id != request.user.id)
    can_edit = has_perm_or_admin(request.user, 'purchases:orders/edit') and can_user_access_object(request.user, order, 'edit')
    can_delete = has_perm_or_admin(request.user, 'purchases:orders/delete') and can_user_access_object(request.user, order, 'delete')
    can_manage_payment = has_perm_or_admin(request.user, 'purchases:orders/manage_payment_status')
    can_resubmit = (order.status == 'rejected') and (order.created_by_id == request.user.id or is_super)
    approval_history = order.approval_history.select_related('actor').order_by('-created_at')

    context = {
        'order': order,
        'linked_tx': linked_tx,
        'total_debit': total_debit,
        'total_credit': total_credit,
        'current_vendor_balance': current_vendor_balance,
        'status_choices': PurchaseOrder.STATUS_CHOICES,
        'payment_status_choices': PurchaseOrder.PAYMENT_STATUS_CHOICES,
        'can_approve': can_approve,
        'can_edit': can_edit,
        'can_delete': can_delete,
        'can_manage_payment': can_manage_payment,
        'can_resubmit': can_resubmit,
        'approval_history': approval_history,
    }
    return render(request, 'purchases/purchase_order_detail.html', context)


@require_permission('purchases:orders/delete')
def purchase_order_delete(request, pk):
    order = get_object_or_404(PurchaseOrder, pk=pk)
    if not can_user_access_object(request.user, order, 'delete'):
        return render_forbidden_response(request, "لا يمكنك حذف هذا الطلب خارج نطاق اختصاصك أو منطقتك الجغرافية.")

    if request.method != 'POST':
        messages.error(request, "طريقة طلب غير صالحة للحذف. يلزم استخدام POST.")
        return redirect('purchase_order_detail', pk=pk)

    try:
        PurchaseOrderService.delete_order(order, request.user)
        messages.success(request, f"تم حذف أمر المشتريات {order.order_number} بنجاح وعكس الحركات المخزنية والمالية.")
        return redirect('purchase_orders_list')
    except ValidationError as e:
        messages.error(request, str(e.message if hasattr(e, 'message') else e))
        return redirect('purchase_order_detail', pk=pk)


@require_permission('purchases:orders/manage_payment_status')
def purchase_order_update_payment_status(request, pk):
    order = get_object_or_404(PurchaseOrder, pk=pk)
    if not can_user_access_object(request.user, order, 'edit'):
        return render_forbidden_response(request, "لا يمكنك تحديث حالة السداد لأمر شراء خارج نطاق اختصاصك.")

    if request.method != 'POST':
        messages.error(request, "طريقة طلب غير صالحة. يلزم استخدام POST.")
        return redirect('purchase_order_detail', pk=pk)

    new_status = (request.POST.get('payment_status') or '').strip()
    notes = (request.POST.get('notes') or '').strip()

    try:
        PurchaseOrderService.update_payment_status(order, new_status, request.user, notes=notes)
        messages.success(request, f"تم تحديث حالة السداد لأمر الشراء {order.order_number} بنجاح إلى '{order.payment_status_display_ar}'.")
    except ValidationError as e:
        messages.error(request, str(e.message if hasattr(e, 'message') else e))

    return redirect('purchase_order_detail', pk=pk)


@login_required
def purchase_order_update_status_ajax(request, pk):
    order = get_object_or_404(PurchaseOrder, pk=pk)
    if not can_user_access_object(request.user, order, 'approve'):
        return render_forbidden_response(request, "لا يمكنك تغيير حالة هذا الطلب خارج نطاق منطقتك الجغرافية المصرح بها.")

    if request.method == 'POST':
        new_status = request.POST.get('status', '').strip().lower()
        valid_statuses = dict(PurchaseOrder.STATUS_CHOICES).keys()
        if new_status in valid_statuses:
            status_perm_map = {
                'approved': 'purchases:orders/approve',
                'picked': 'purchases:orders/stock',
                'settled': 'purchases:orders/invoice',
                'cancelled': 'purchases:orders/cancel',
            }
            needed_perm = status_perm_map.get(new_status, 'purchases:orders/edit')
            if not has_perm_or_admin(request.user, needed_perm):
                return render_forbidden_response(request, f"ليس لديك صلاحية لتنفيذ هذا الإجراء ({needed_perm})", perm_codename=needed_perm)

            try:
                if new_status == 'approved' and order.status == 'pending':
                    order = PurchaseOrderService.approve_order(order, request.user)
                elif new_status == 'picked' and order.status in ['pending', 'approved']:
                    if order.status == 'pending':
                        if not has_perm_or_admin(request.user, 'purchases:orders/approve'):
                            return render_forbidden_response(request, "ليس لديك صلاحية اعتماد أمر الشراء.", perm_codename='purchases:orders/approve')
                        order = PurchaseOrderService.approve_order(order, request.user)
                    order = PurchaseOrderService.stock_order(order, request.user)
                elif new_status == 'settled' and order.status != 'settled':
                    if order.status in ['pending', 'approved']:
                        if order.status == 'pending':
                            if not has_perm_or_admin(request.user, 'purchases:orders/approve'):
                                return render_forbidden_response(request, "ليس لديك صلاحية اعتماد أمر الشراء.", perm_codename='purchases:orders/approve')
                            order = PurchaseOrderService.approve_order(order, request.user)
                        if not has_perm_or_admin(request.user, 'purchases:orders/stock'):
                            return render_forbidden_response(request, "ليس لديك صلاحية استلام المخزون.", perm_codename='purchases:orders/stock')
                        order = PurchaseOrderService.stock_order(order, request.user)
                    order = PurchaseOrderService.invoice_order(order, request.user)
                elif new_status == 'cancelled':
                    order = PurchaseOrderService.cancel_order(order, request.user)
                else:
                    raise ValidationError(f"لا يمكن الانتقال من الحالة الحالية ({order.status_label_ar}) إلى ({new_status}) بشكل مباشر.")

                messages.success(request, f"تم تغيير حالة أمر الشراء إلى {order.status_label_ar}.")
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({'status': 'ok', 'new_status': order.status, 'label': order.status_label_en})
            except ValidationError as e:
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({'status': 'error', 'message': str(e.message if hasattr(e, 'message') else e)}, status=400)
                messages.error(request, str(e.message if hasattr(e, 'message') else e))

    return redirect('purchase_order_detail', pk=pk)


@require_permission('purchases:orders/edit')
def purchase_order_add_comment(request, pk):
    order = get_object_or_404(PurchaseOrder, pk=pk)
    if not can_user_access_object(request.user, order, 'view'):
        return render_forbidden_response(request, "لا يمكنك التعليق على هذا الطلب خارج نطاق منطقتك الجغرافية.")

    if request.method == 'POST':
        text = request.POST.get('comment', '').strip()
        if text:
            PurchaseOrderComment.objects.create(
                order=order,
                author=request.user,
                text=text
            )
            messages.success(request, "تمت إضافة التعليق بنجاح.")
        else:
            messages.warning(request, "لا يمكن إضافة تعليق فارغ.")
    return redirect('purchase_order_detail', pk=pk)


@require_permission('purchases:orders/edit')
def purchase_order_upload_attachment(request, pk):
    order = get_object_or_404(PurchaseOrder, pk=pk)
    if not can_user_access_object(request.user, order, 'edit'):
        return render_forbidden_response(request, "لا يمكنك رفع مرفقات لهذا الطلب خارج نطاق منطقتك الجغرافية.")

    if request.method == 'POST' and request.FILES.get('file'):
        f = request.FILES['file']
        title = request.POST.get('title') or f.name
        PurchaseOrderAttachment.objects.create(
            order=order,
            title=title,
            file=f,
            file_type=f.content_type,
            created_by=request.user
        )
        messages.success(request, f"تم رفع الملف '{f.name}' بنجاح.")
    return redirect('purchase_order_detail', pk=pk)


@login_required
def purchase_order_action(request, pk, action):
    action_perm_map = {
        'approve': 'purchases:orders/approve',
        'reject': 'purchases:orders/approve',
        'disapprove': 'purchases:orders/approve',
        'resubmit': 'purchases:orders/create',
        'stock': 'purchases:orders/stock',
        'invoice': 'purchases:orders/invoice',
        'undo_invoice': 'purchases:orders/undoInvoice',
        'cancel': 'purchases:orders/cancel',
    }
    needed_perm = action_perm_map.get(action, 'purchases:orders/edit')
    if not has_perm_or_admin(request.user, needed_perm):
        return render_forbidden_response(request, f"ليس لديك صلاحية لتنفيذ هذا الإجراء ({needed_perm})", perm_codename=needed_perm)

    order = get_object_or_404(PurchaseOrder, pk=pk)

    # Scoping and self-approval checks
    if not can_user_access_object(request.user, order, action):
        return render_forbidden_response(request, "لا يمكنك تنفيذ هذا الإجراء خارج نطاق منطقتك الجغرافية المصرح بها.")

    if action in ['approve', 'reject', 'disapprove']:
        if order.created_by_id == request.user.id and not (request.user.is_superuser or getattr(request.user, 'is_super_admin', False)):
            messages.error(request, "لا يمكن لمنشئ أمر الشراء اعتماده أو رفضه بنفسه (مبدأ الرقابة الثنائية).")
            return redirect('purchase_order_detail', pk=order.pk)

    is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'application/json' in request.headers.get('accept', '')

    try:
        if action == 'approve':
            notes = request.POST.get('approval_notes', '') or request.POST.get('notes', '')
            PurchaseOrderService.approve_order(order, request.user, notes=notes)
            msg = f"تم اعتماد أمر الشراء {order.order_number} بنجاح."
            if is_ajax:
                return JsonResponse({'success': True, 'message': msg, 'status': order.status})
            messages.success(request, msg)

        elif action in ['reject', 'disapprove']:
            reason = request.POST.get('rejection_reason', '') or request.POST.get('reason', '') or request.POST.get('approval_notes', '')
            if not (reason or '').strip():
                msg = "يرجى توضيح سبب رفض أمر الشراء لتوجيه مسؤول المشتريات."
                if is_ajax:
                    return JsonResponse({'success': False, 'message': msg}, status=400)
                messages.error(request, msg)
                return redirect('purchase_order_detail', pk=order.pk)

            PurchaseOrderService.reject_order(order, request.user, reason=reason)
            msg = f"تم رفض أمر الشراء {order.order_number}."
            if is_ajax:
                return JsonResponse({'success': True, 'message': msg, 'status': order.status})
            messages.error(request, msg)

        elif action == 'resubmit':
            PurchaseOrderService.resubmit_order(order, request.user)
            msg = f"تمت إعادة تقديم أمر الشراء {order.order_number} للاعتماد بنجاح."
            if is_ajax:
                return JsonResponse({'success': True, 'message': msg, 'status': order.status})
            messages.success(request, msg)

        elif action == 'stock':
            PurchaseOrderService.stock_order(order, request.user)
            messages.success(request, f"تم استلام بضاعة أمر الشراء في المخزن بنجاح ({order.order_number}) وتم توليد إذن إضافة مخزن.")
        elif action == 'invoice':
            PurchaseOrderService.invoice_order(order, request.user)
            messages.success(request, f"تم ترحيل الفاتورة للحسابات بنجاح ({order.order_number}) وإثبات مديونية المورد.")
        elif action == 'undo_invoice':
            PurchaseOrderService.undo_invoice(order, request.user)
            messages.warning(request, f"تم إلغاء فاتورة الحسابات لأمر الشراء {order.order_number} وإعادة الحالة إلى (Picked).")
        elif action == 'cancel':
            PurchaseOrderService.cancel_order(order, request.user)
            messages.error(request, f"تم إلغاء أمر الشراء {order.order_number}.")
        else:
            messages.error(request, "إجراء غير معروف.")
    except ValidationError as e:
        err_msg = str(e.message if hasattr(e, 'message') else e)
        if is_ajax:
            return JsonResponse({'success': False, 'message': err_msg}, status=400)
        messages.error(request, err_msg)

    return redirect('purchase_order_detail', pk=order.pk)


@require_permission('purchases:orders/view')
def purchase_order_print(request, pk):
    order = get_object_or_404(
        PurchaseOrder.objects.select_related('supplier', 'supplier__area', 'target_warehouse', 'created_by').prefetch_related('items__product'),
        pk=pk
    )
    if not can_user_access_object(request.user, order, 'view'):
        return render_forbidden_response(request, "غير مصرح لك باستعراض أو طباعة أمر الشراء هذا.")
    return render(request, 'purchases/purchase_order_print.html', {'order': order})


@require_permission('purchases:orders/export')
def purchase_orders_export(request):
    from master_data.filter_utils import parse_multi_str, parse_single_int
    from master_data.date_filter_utils import resolve_date_range

    status_choices_dict = dict(PurchaseOrder.STATUS_CHOICES)
    selected_statuses = [s for s in parse_multi_str(request.GET, 'status') if s in status_choices_dict]
    payment_status_filter = request.GET.get('payment_status', 'all')
    supplier_id_int = parse_single_int(request.GET, 'supplier')
    search = request.GET.get('search', '').strip()
    parsed_from, parsed_to, _, _, _ = resolve_date_range(request, default_preset='all_time')
    total_min = request.GET.get('total_min', '').strip()
    total_max = request.GET.get('total_max', '').strip()

    qs = PurchaseOrder.objects.select_related(
        'supplier', 'supplier__area', 'target_warehouse', 'created_by'
    ).all().order_by('-serial_num')
    qs = get_scoped_queryset(qs, request.user, 'purchaseorder')

    if selected_statuses:
        qs = qs.filter(status__in=selected_statuses)
    if payment_status_filter != 'all' and payment_status_filter in dict(PurchaseOrder.PAYMENT_STATUS_CHOICES):
        qs = qs.filter(payment_status=payment_status_filter)
    if supplier_id_int:
        qs = qs.filter(supplier_id=supplier_id_int)
    if parsed_from:
        qs = qs.filter(order_date__gte=parsed_from)
    if parsed_to:
        qs = qs.filter(order_date__lte=parsed_to)
    if total_min:
        try:
            qs = qs.filter(grand_total__gte=Decimal(total_min))
        except Exception:
            pass
    if total_max:
        try:
            qs = qs.filter(grand_total__lte=Decimal(total_max))
        except Exception:
            pass
    if search:
        qs = filter_by_arabic_search(qs, search, ['order_number', 'serial_num', 'supplier__name', 'supplier__area__name'])

    columns = [
        {'header': 'رقم الطلب', 'key': 'order_number', 'width': 16, 'align': 'center'},
        {'header': 'المورد', 'key': lambda o: o.supplier.name, 'width': 35, 'align': 'right'},
        {'header': 'المنطقة', 'key': lambda o: o.supplier.area.name if o.supplier.area else '', 'width': 22, 'align': 'right'},
        {'header': 'المخزن', 'key': lambda o: o.target_warehouse.name if o.target_warehouse else '', 'width': 22, 'align': 'right'},
        {'header': 'تاريخ الإنشاء', 'key': lambda o: o.created_at.strftime('%Y-%m-%d %H:%M') if o.created_at else '', 'width': 20, 'align': 'center'},
        {'header': 'المنشئ', 'key': lambda o: o.created_by.get_full_name() or o.created_by.username if o.created_by else '', 'width': 22, 'align': 'right'},
        {'header': 'الحالة', 'key': lambda o: o.status_label_en, 'width': 18, 'align': 'center'},
        {'header': 'إجمالي القيمة', 'key': lambda o: float(o.grand_total) if o.grand_total is not None else 0.0, 'format': '#,##0.00', 'width': 18, 'align': 'right'},
        {'header': 'مسئول التوصيل', 'key': lambda o: o.delivery_agent or '', 'width': 20, 'align': 'center'},
        {'header': 'وقت التوصيل', 'key': lambda o: o.delivery_time or '', 'width': 20, 'align': 'center'},
    ]

    return export_to_excel_response(
        qs,
        columns,
        filename="purchase_orders_export",
        sheet_title="طلبات الشراء",
        report_title="سجل طلبات وأوامر الشراء",
        user=request.user,
    )


@require_permission('purchases:orders/edit')
def purchase_order_split(request, pk):
    order = get_object_or_404(PurchaseOrder, pk=pk)
    if not can_user_access_object(request.user, order, 'edit'):
        return render_forbidden_response(request, "غير مصرح لك بتعديل أو فصل أمر الشراء هذا.")
    if request.method == 'POST':
        item_ids = request.POST.getlist('split_item_id[]')
        quantities = request.POST.getlist('split_qty[]')

        split_dict = {}
        for i_id, q_str in zip(item_ids, quantities):
            if i_id and q_str:
                try:
                    qty = Decimal(q_str)
                    if qty > Decimal('0.00'):
                        split_dict[int(i_id)] = qty
                except Exception:
                    pass

        try:
            child = PurchaseOrderService.split_order(order, split_dict, request.user)
            messages.success(request, f"تم فصل الطلب بنجاح وإنشاء أمر المشتريات الجديد {child.order_number}.")
            return redirect('purchase_order_detail', pk=child.pk)
        except ValidationError as e:
            messages.error(request, str(e.message if hasattr(e, 'message') else e))

    return redirect('purchase_order_detail', pk=pk)


@require_permission('purchases:returns/list')
def purchase_return_orders_list(request):
    """View matching /purchase-return-orders in reference ERP."""
    from master_data.filter_utils import parse_multi_str, parse_single_int
    from master_data.date_filter_utils import resolve_date_range

    supplier_id_int = parse_single_int(request.GET, 'supplier')
    supplier_filter = str(supplier_id_int) if supplier_id_int else ''
    status_choices_dict = dict(PurchaseReturnOrder.STATUS_CHOICES)
    selected_statuses = [s for s in parse_multi_str(request.GET, 'status') if s in status_choices_dict]
    search = request.GET.get('search', '').strip()
    parsed_from, parsed_to, active_preset, date_from, date_to = resolve_date_range(request, default_preset='all_time')
    total_min = request.GET.get('total_min', '').strip()
    total_max = request.GET.get('total_max', '').strip()

    qs = PurchaseReturnOrder.objects.select_related(
        'supplier', 'supplier__area', 'warehouse', 'created_by'
    ).all().order_by('-serial_num')
    qs = get_scoped_queryset(qs, request.user, 'purchasereturnorder')

    active_filters = []

    if selected_statuses:
        qs = qs.filter(status__in=selected_statuses)
        for s in selected_statuses:
            active_filters.append({'label': 'الحالة', 'value': status_choices_dict.get(s, s), 'param': 'status', 'remove_value': s})

    if supplier_id_int:
        qs = qs.filter(supplier_id=supplier_id_int)
        s_obj = ScopeResolutionService.get_scoped_choices(request.user, 'suppliers', 'purchases').filter(id=supplier_id_int).first()
        active_filters.append({'label': 'المورد', 'value': s_obj.name if s_obj else supplier_filter, 'param': 'supplier'})

    if parsed_from:
        qs = qs.filter(order_date__gte=parsed_from)
        active_filters.append({'label': 'من تاريخ', 'value': date_from, 'param': 'date_from'})

    if parsed_to:
        qs = qs.filter(order_date__lte=parsed_to)
        active_filters.append({'label': 'إلى تاريخ', 'value': date_to, 'param': 'date_to'})

    if total_min:
        try:
            val_min = Decimal(total_min)
            qs = qs.filter(grand_total__gte=val_min)
            active_filters.append({'label': f'الحد الأدنى للقيمة: {val_min:,.2f} ج.م', 'param': 'total_min'})
        except Exception:
            total_min = ''

    if total_max:
        try:
            val_max = Decimal(total_max)
            qs = qs.filter(grand_total__lte=val_max)
            active_filters.append({'label': f'الحد الأقصى للقيمة: {val_max:,.2f} ج.م', 'param': 'total_max'})
        except Exception:
            total_max = ''

    if search:
        qs = filter_by_arabic_search(qs, search, ['order_number', 'serial_num', 'supplier__name'])
        active_filters.append({'label': f'بحث: {search}', 'param': 'search'})

    suppliers = get_bounded_select_options(
        ScopeResolutionService.get_scoped_choices(request.user, 'suppliers', 'purchases'),
        selected_id=supplier_filter,
        limit=100,
    )

    # Scoped real statistics matching active filters
    ret_agg = qs.aggregate(
        total_orders=Count('id'),
        total_value=Sum('grand_total'),
        draft_count=Count('id', filter=Q(status='pending')),
        settled_count=Count('id', filter=Q(status='settled')),
    )
    return_stats = {
        'total_orders': ret_agg['total_orders'] or 0,
        'total_value': ret_agg['total_value'] or Decimal('0.00'),
        'draft_count': ret_agg['draft_count'] or 0,
        'settled_count': ret_agg['settled_count'] or 0,
    }

    # Bounded server-side pagination (default 25)
    paginator, page_obj = paginate_queryset(request, qs, default_per_page=25, max_per_page=100)

    ret_status_options = [{'value': k, 'label': v} for k, v in PurchaseReturnOrder.STATUS_CHOICES]
    selected_ret_status_items = [o for o in ret_status_options if o['value'] in selected_statuses]

    context = {
        'returns': page_obj.object_list,
        'page_obj': page_obj,
        'paginator': paginator,
        'ret_status_options': ret_status_options,
        'selected_ret_status_items': selected_ret_status_items,
        'selected_statuses': selected_statuses,
        'active_preset': active_preset,
        'selected_supplier': supplier_filter,
        'search_query': search,
        'selected_date_from': date_from,
        'selected_date_to': date_to,
        'selected_total_min': total_min,
        'selected_total_max': total_max,
        'date_from': date_from,
        'date_to': date_to,
        'suppliers': suppliers,
        'active_filters': active_filters,
        'active_filters_count': len(active_filters),
        'total_count': paginator.count,
        'stats': return_stats,
    }
    return render(request, 'purchases/purchase_return_orders.html', context)


@require_permission('purchases:returns/create')
def purchase_return_order_create(request):
    """Form to create a new purchase return order."""
    if request.method == 'POST':
        supplier_id = request.POST.get('supplier')
        warehouse_id = request.POST.get('warehouse')
        po_id = request.POST.get('purchase_order') or None
        order_date = request.POST.get('order_date') or timezone.now().date()
        delivery_agent = request.POST.get('delivery_agent', '').strip()
        delivery_time = request.POST.get('delivery_time', '').strip()
        notes = request.POST.get('notes', '').strip()

        product_ids = request.POST.getlist('product_id[]')
        quantities = request.POST.getlist('quantity[]')
        unit_prices = request.POST.getlist('unit_price[]')
        batch_numbers = request.POST.getlist('batch_number[]')
        expiry_dates = request.POST.getlist('expiry_date[]')

        items_data = []
        for i in range(len(product_ids)):
            p_id = product_ids[i]
            if not p_id:
                continue
            prod = Product.objects.filter(id=p_id).first()
            if not prod:
                continue
            qty = Decimal(quantities[i] or '1') if i < len(quantities) else Decimal('1')
            price = Decimal(unit_prices[i] or '0') if i < len(unit_prices) else Decimal('0')
            batch = batch_numbers[i] if i < len(batch_numbers) else ''
            exp = expiry_dates[i] if (i < len(expiry_dates) and expiry_dates[i]) else None

            items_data.append({
                'product': prod,
                'quantity': qty,
                'unit_price': price,
                'batch_number': batch,
                'expiry_date': exp,
            })

        def render_purchase_return_form_error(err_text):
            messages.error(request, err_text)
            sub_items = []
            for idx, p_id in enumerate(product_ids):
                if not p_id:
                    continue
                sub_items.append({
                    'product_id': p_id,
                    'quantity': quantities[idx] if idx < len(quantities) else '1',
                    'unit_price': unit_prices[idx] if idx < len(unit_prices) else '0.00',
                    'batch_number': batch_numbers[idx] if idx < len(batch_numbers) else '',
                    'expiry_date': expiry_dates[idx] if idx < len(expiry_dates) else '',
                })
            suppliers = get_bounded_select_options(
                ScopeResolutionService.get_scoped_choices(request.user, 'suppliers', 'purchases'),
                selected_id=supplier_id,
                limit=100,
            )
            warehouses = get_bounded_select_options(
                ScopeResolutionService.get_scoped_choices(request.user, 'warehouses', 'purchases'),
                selected_id=warehouse_id,
                limit=100,
            )
            products = Product.objects.filter(is_active=True).order_by('name')
            po_candidate = PurchaseOrder.objects.filter(id=po_id).first() if po_id else None
            ctx = {
                'suppliers': suppliers,
                'warehouses': warehouses,
                'products': products,
                'selected_po': po_candidate,
                'form_data': {
                    'supplier': supplier_id,
                    'warehouse': warehouse_id,
                    'purchase_order': po_id,
                    'order_date': order_date,
                    'delivery_agent': delivery_agent,
                    'delivery_time': delivery_time,
                    'notes': notes,
                },
                'submitted_items': sub_items,
            }
            return render(request, 'purchases/purchase_return_order_create.html', ctx)

        if not supplier_id or not warehouse_id:
            return render_purchase_return_form_error("يرجى تحديد المورد والمخزن المنصرف منه.")

        supplier = get_object_or_404(Contact, id=supplier_id)
        if not ScopeResolutionService.can_user_access_supplier(request.user, supplier):
            return render_forbidden_response(request, "غير مصرح لك بإنشاء أمر شراء لمورد خارج نطاق منطقتك الجغرافية.")
        if not supplier.is_supplier or supplier.status == 'inactive':
            return render_purchase_return_form_error("جهة الاتصال المحددة غير مصنفة كمورد نشط.")

        warehouse = get_object_or_404(Warehouse, id=warehouse_id)
        if not can_user_access_object(request.user, warehouse, 'operate'):
            return render_forbidden_response(request, "غير مصرح لك باستخدام هذا المخزن المستلم.")
        po = PurchaseOrder.objects.filter(id=po_id).first() if po_id else None
        if po and not can_user_access_object(request.user, po, 'view'):
            return render_forbidden_response(request, "غير مصرح لك بربط مرتجع بأمر شراء خارج نطاق صلاحياتك.")

        try:
            return_order = PurchaseReturnOrderService.create_return_order(
                supplier=supplier,
                warehouse=warehouse,
                order_date=order_date,
                items_data=items_data,
                user=request.user,
                purchase_order=po,
                delivery_agent=delivery_agent,
                delivery_time=delivery_time,
                notes=notes
            )
            if request.FILES.getlist('attachments'):
                from master_data.media_service import store_attachments_from_request
                store_attachments_from_request(return_order, request)
            messages.success(request, f"تم إنشاء أمر إرجاع المشتريات {return_order.order_number} بنجاح.")
            return redirect('purchase_return_order_detail', pk=return_order.pk)
        except ValidationError as e:
            return render_purchase_return_form_error(str(e.message if hasattr(e, 'message') else e))

    po_id = request.GET.get('po')
    selected_po = PurchaseOrder.objects.filter(id=po_id).first() if po_id else None
    if selected_po and not can_user_access_object(request.user, selected_po, 'view'):
        selected_po = None

    raw_selected_supplier = request.GET.get('supplier') or request.GET.get('supplier_id')
    selected_supplier_id = selected_po.supplier_id if selected_po else raw_selected_supplier
    suppliers = get_bounded_select_options(
        ScopeResolutionService.get_scoped_choices(request.user, 'suppliers', 'purchases'),
        selected_id=selected_supplier_id,
        limit=100,
    )
    warehouses = get_bounded_select_options(
        ScopeResolutionService.get_scoped_choices(request.user, 'warehouses', 'purchases'),
        selected_id=selected_po.target_warehouse_id if selected_po else None,
        limit=100,
    )
    products = Product.objects.filter(is_active=True).order_by('name')

    context = {
        'suppliers': suppliers,
        'warehouses': warehouses,
        'products': products,
        'selected_po': selected_po,
    }
    return render(request, 'purchases/purchase_return_order_create.html', context)


@require_permission('purchases:returns/view')
def purchase_return_order_detail(request, pk):
    return_order = get_object_or_404(
        PurchaseReturnOrder.objects.select_related(
            'supplier', 'supplier__area', 'warehouse', 'created_by', 'memo', 'purchase_order', 'approved_by'
        ).prefetch_related('items__product', 'items__original_item'),
        pk=pk
    )

    if not can_user_access_object(request.user, return_order, 'view'):
        return render_forbidden_response(request, "لا يمكنك عرض هذا المرتجع خارج نطاق منطقتك الجغرافية أو صلاحيتك.")

    # Linked debit transaction if settled
    linked_tx = VendorTransaction.objects.filter(
        account__supplier=return_order.supplier,
        reason='purchase_return',
        debit=return_order.grand_total
    ).first()

    from .services import build_purchase_return_timeline
    timeline_events = build_purchase_return_timeline(return_order)

    can_approve = has_perm_or_admin(request.user, 'purchases:returns/approve') and can_user_access_object(request.user, return_order, 'approve')
    can_deliver = has_perm_or_admin(request.user, 'purchases:returns/manage') and return_order.status == 'approved'
    can_settle = has_perm_or_admin(request.user, 'purchases:returns/manage') and return_order.status == 'delivered'
    can_cancel = has_perm_or_admin(request.user, 'purchases:returns/manage') and return_order.status in ['pending', 'approved']
    can_delete = has_perm_or_admin(request.user, 'purchases:returns/delete') and can_user_access_object(request.user, return_order, 'delete')

    context = {
        'return_order': return_order,
        'linked_tx': linked_tx,
        'status_choices': PurchaseReturnOrder.STATUS_CHOICES,
        'timeline_events': timeline_events,
        'can_approve': can_approve,
        'can_deliver': can_deliver,
        'can_settle': can_settle,
        'can_cancel': can_cancel,
        'can_delete': can_delete,
    }
    return render(request, 'purchases/purchase_return_order_detail.html', context)


@require_permission('purchases:returns/delete')
def purchase_return_order_delete(request, pk):
    return_order = get_object_or_404(PurchaseReturnOrder, pk=pk)
    if not can_user_access_object(request.user, return_order, 'delete'):
        return render_forbidden_response(request, "لا يمكنك حذف هذا المرتجع خارج نطاق اختصاصك أو منطقتك الجغرافية.")

    if request.method != 'POST':
        messages.error(request, "طريقة طلب غير صالحة للحذف. يلزم استخدام POST.")
        return redirect('purchase_return_order_detail', pk=pk)

    try:
        PurchaseReturnOrderService.delete_return_order(return_order, request.user)
        messages.success(request, f"تم حذف أمر إرجاع المشتريات {return_order.order_number} بنجاح وعكس الحركات المخزنية والمالية.")
        return redirect('purchase_return_orders_list')
    except ValidationError as e:
        messages.error(request, str(e.message if hasattr(e, 'message') else e))
        return redirect('purchase_return_order_detail', pk=pk)


@login_required
def purchase_return_order_action(request, pk, action):
    if request.method != 'POST':
        messages.error(request, "طريقة طلب غير صالحة. يلزم استخدام POST لتغيير الحالة.")
        return redirect('purchase_return_order_detail', pk=pk)

    return_order = get_object_or_404(PurchaseReturnOrder, pk=pk)

    if action in ['approve', 'reject']:
        if not has_perm_or_admin(request.user, 'purchases:returns/approve'):
            return render_forbidden_response(request, "لا تملك صلاحية اعتماد أو رفض أمر الإرجاع.", perm_codename='purchases:returns/approve')
        if not can_user_access_object(request.user, return_order, 'approve'):
            return render_forbidden_response(request, "لا يمكنك اعتماد أو رفض أمر إرجاع قمت بإنشائه بنفسك أو خارج نطاقك.")
    else:
        if not has_perm_or_admin(request.user, 'purchases:returns/manage'):
            return render_forbidden_response(request, "لا تملك صلاحية إدارة أوامر إرجاع المشتريات.", perm_codename='purchases:returns/manage')
        if not can_user_access_object(request.user, return_order, action):
            return render_forbidden_response(request, "لا يمكنك تنفيذ هذا الإجراء خارج نطاق منطقتك الجغرافية المصرح بها.")

    try:
        if action == 'approve':
            PurchaseReturnOrderService.approve_return_order(return_order, request.user)
            messages.success(request, f"تم اعتماد أمر الإرجاع {return_order.order_number} بنجاح.")
        elif action == 'reject':
            reason = request.POST.get('rejection_reason', '') or request.POST.get('reason', '')
            PurchaseReturnOrderService.reject_return_order(return_order, request.user, rejection_reason=reason)
            messages.error(request, f"تم رفض أمر الإرجاع {return_order.order_number}.")
        elif action == 'deliver':
            PurchaseReturnOrderService.deliver_return_order(return_order, request.user)
            messages.success(request, f"تم صرف بضاعة أمر الإرجاع من المخزن بنجاح ({return_order.order_number}) وتم توليد إذن صرف مخزن.")
        elif action == 'settle':
            PurchaseReturnOrderService.settle_return_order(return_order, request.user)
            messages.success(request, f"تم ترحيل إشعار الخصم للحسابات بنجاح ({return_order.order_number}) وخصم المديونية من حساب المورد.")
        elif action == 'cancel':
            PurchaseReturnOrderService.cancel_return_order(return_order, request.user)
            messages.error(request, f"تم إلغاء أمر الإرجاع {return_order.order_number}.")
        else:
            messages.error(request, "إجراء غير معروف.")
    except ValidationError as e:
        messages.error(request, str(e.message if hasattr(e, 'message') else e))

    return redirect('purchase_return_order_detail', pk=return_order.pk)


@require_permission('purchases:returns/view')
def purchase_return_order_print(request, pk):
    return_order = get_object_or_404(
        PurchaseReturnOrder.objects.select_related('supplier', 'supplier__area', 'warehouse', 'created_by').prefetch_related('items__product'),
        pk=pk
    )
    if not can_user_access_object(request.user, return_order, 'view'):
        return render_forbidden_response(request, "لا يمكنك طباعة هذا المرتجع خارج نطاق منطقتك الجغرافية أو صلاحيتك.")
    return render(request, 'purchases/purchase_return_order_print.html', {'return_order': return_order})


@require_permission('purchases:returns/export')
def purchase_return_orders_export(request):
    from master_data.filter_utils import parse_multi_str, parse_single_int
    from master_data.date_filter_utils import resolve_date_range
    status_choices_dict = dict(PurchaseReturnOrder.STATUS_CHOICES)
    selected_statuses = [s for s in parse_multi_str(request.GET, 'status') if s in status_choices_dict]
    supplier_filter = parse_single_int(request.GET, 'supplier')
    search = request.GET.get('search', '').strip()
    parsed_from, parsed_to, _, _, _ = resolve_date_range(request, default_preset='all_time')
    total_min = request.GET.get('total_min', '').strip()
    total_max = request.GET.get('total_max', '').strip()

    qs = PurchaseReturnOrder.objects.select_related(
        'supplier', 'supplier__area', 'warehouse', 'created_by'
    ).all().order_by('-serial_num')
    qs = get_scoped_queryset(qs, request.user, 'purchasereturnorder')

    if selected_statuses:
        qs = qs.filter(status__in=selected_statuses)
    if supplier_filter:
        qs = qs.filter(supplier_id=supplier_filter)
    if parsed_from:
        qs = qs.filter(order_date__gte=parsed_from)
    if parsed_to:
        qs = qs.filter(order_date__lte=parsed_to)
    if total_min:
        try:
            qs = qs.filter(grand_total__gte=Decimal(total_min))
        except Exception:
            pass
    if total_max:
        try:
            qs = qs.filter(grand_total__lte=Decimal(total_max))
        except Exception:
            pass
    if search:
        qs = filter_by_arabic_search(qs, search, ['order_number', 'serial_num', 'supplier__name'])

    columns = [
        {'header': 'رقم أمر الإرجاع', 'key': 'order_number', 'width': 18, 'align': 'center'},
        {'header': 'المورد', 'key': lambda r: r.supplier.name, 'width': 35, 'align': 'right'},
        {'header': 'المنطقة', 'key': lambda r: r.supplier.area.name if r.supplier.area else '', 'width': 22, 'align': 'right'},
        {'header': 'المخزن', 'key': lambda r: r.warehouse.name if r.warehouse else '', 'width': 22, 'align': 'right'},
        {'header': 'تاريخ الإنشاء', 'key': lambda r: r.created_at.strftime('%Y-%m-%d %H:%M') if r.created_at else '', 'width': 20, 'align': 'center'},
        {'header': 'المنشئ', 'key': lambda r: r.created_by.get_full_name() or r.created_by.username if r.created_by else '', 'width': 22, 'align': 'right'},
        {'header': 'الحالة', 'key': lambda r: r.status_label_en, 'width': 18, 'align': 'center'},
        {'header': 'إجمالي المرتجع', 'key': lambda r: float(r.grand_total) if r.grand_total is not None else 0.0, 'format': '#,##0.00', 'width': 18, 'align': 'right'},
        {'header': 'مسئول الاستلام', 'key': lambda r: r.delivery_agent or '', 'width': 20, 'align': 'center'},
        {'header': 'وقت الاستلام', 'key': lambda r: r.delivery_time or '', 'width': 20, 'align': 'center'},
    ]

    return export_to_excel_response(
        qs,
        columns,
        filename="purchase_returns_export",
        sheet_title="مرتجعات الشراء",
        report_title="سجل مرتجعات المشتريات",
        user=request.user,
    )


@require_permission([
    'purchases:orders/list',
    'purchases:orders/create',
    'purchases:orders/edit',
    'purchases:returns/list',
    'purchases:returns/create',
    'treasury:payments/list',
    'treasury:payments/create',
    'treasury:payment_requests/list',
    'treasury:payment_requests/create',
    'treasury:vendors/transactions',
    'treasury:vendors/accounting',
])
def purchases_suppliers_search_api(request):
    """Scoped Arabic-normalized smart-search API for Supplier selectors."""
    q = (request.GET.get('q') or request.GET.get('search') or '').strip()
    limit = parse_search_limit(request)

    qs = ScopeResolutionService.get_scoped_choices(request.user, 'suppliers', 'purchases')
    if q:
        qs = filter_by_arabic_search(
            qs,
            ['name', 'area__name', 'brick__name'],
            q,
            raw_fields=['code', 'mobile', 'serial_num'],
            numeric_id_field='serial_num',
        )

    results = [serialize_contact_option(s) for s in qs[:limit]]
    return JsonResponse({'results': results, 'count': len(results)})


@require_permission([
    'purchases:orders/list',
    'purchases:orders/create',
    'purchases:orders/edit',
    'purchases:returns/create',
])
def purchases_warehouses_search_api(request):
    """Scoped smart-search API for Purchases warehouse selectors."""
    q = (request.GET.get('q') or request.GET.get('search') or '').strip()
    limit = parse_search_limit(request)

    qs = ScopeResolutionService.get_scoped_choices(request.user, 'warehouses', 'purchases')
    if q:
        qs = filter_by_arabic_search(
            qs,
            ['name', 'area__name', 'assigned_user__name'],
            q,
            raw_fields=['code'],
        )

    results = [serialize_warehouse_option(wh) for wh in qs[:limit]]
    return JsonResponse({'results': results, 'count': len(results)})


@require_permission([
    'treasury:payments/list',
    'treasury:payments/create',
    'treasury:payment_requests/list',
    'treasury:payment_requests/create',
    'treasury:payment_requests/execute',
    'treasury:vaults/view',
    'treasury:vaults/transfer',
    'treasury:transactions/list',
    'treasury:transactions/create',
])
def purchases_vaults_search_api(request):
    """Scoped smart-search API for Purchases-adjacent Treasury vault selectors."""
    q = (request.GET.get('q') or request.GET.get('search') or '').strip()
    limit = parse_search_limit(request)

    qs = ScopeResolutionService.get_scoped_choices(request.user, 'vaults', 'treasury')
    if q:
        qs = filter_by_arabic_search(
            qs,
            ['name', 'assigned_user__name'],
            q,
            raw_fields=['serial_num', 'assigned_user__username'],
            numeric_id_field='serial_num',
        )

    total_count = qs.count()
    results = [serialize_vault_option(v) for v in qs[:limit]]
    return JsonResponse({'results': results, 'count': len(results), 'total_count': total_count})


@require_permission([
    'purchases:orders/list',
    'purchases:returns/create',
    'treasury:payments/create',
    'treasury:payment_requests/create',
])
def purchases_orders_search_api(request):
    """Scoped supplier-filtered smart-search API for PurchaseOrder dropdowns."""
    q = (request.GET.get('q') or request.GET.get('search') or '').strip()
    limit = parse_search_limit(request)
    supplier_id = request.GET.get('supplier_id') or request.GET.get('supplier')
    for_return = request.GET.get('for_return') == '1'
    unsettled = request.GET.get('unsettled') == '1'

    qs = get_scoped_queryset(
        PurchaseOrder.objects.select_related('supplier', 'target_warehouse').order_by('-order_date'),
        request.user,
        'purchaseorder',
    )
    if supplier_id and str(supplier_id).isdigit():
        qs = qs.filter(supplier_id=int(supplier_id))

    if for_return:
        qs = qs.filter(status__in=['picked', 'settled'])
    elif unsettled:
        qs = qs.filter(status__in=['approved', 'picked', 'received'])

    qs = PurchaseOrder.with_payment_totals(qs)

    if q:
        qs = filter_by_arabic_search(
            qs,
            ['supplier__name', 'target_warehouse__name'],
            q,
            raw_fields=['order_number', 'serial_num'],
            numeric_id_field='serial_num',
        )

    total_count = qs.count()
    results = []
    for o in qs[:limit]:
        out_bal = getattr(o, 'outstanding_balance', o.grand_total)
        results.append({
            'id': o.id,
            'order_number': o.order_number,
            'supplier_id': o.supplier_id,
            'grand_total': f"{o.grand_total:.2f}",
            'outstanding_balance': f"{out_bal:.2f}",
            'warehouse_id': o.target_warehouse_id,
            'text': f"{o.order_number} — {o.supplier.name} ({o.order_date.strftime('%Y-%m-%d') if o.order_date else ''})",
            'subtext': f"الإجمالي: {o.grand_total:,.2f} ج.م | المخزن: {o.target_warehouse.name if o.target_warehouse else '—'}" + (f" | متبقي: {out_bal:,.2f} ج.م" if unsettled else ""),
        })
    return JsonResponse({'results': results, 'count': len(results), 'total_count': total_count})


@require_permission('purchases:returns/create')
def purchases_order_return_details_api(request, order_id):
    """API returning items of a purchase order with remaining returnable quantity for auto-population."""
    from .models import PurchaseOrder, PurchaseReturnOrderItem
    order = get_object_or_404(PurchaseOrder.objects.select_related('supplier', 'target_warehouse'), id=order_id)
    if not can_user_access_object(request.user, order, 'view'):
        return JsonResponse({'error': 'غير مصرح لك بعرض تفاصيل هذا الطلب.'}, status=403)

    items_data = []
    for itm in order.items.select_related('product').all():
        ret_sum = PurchaseReturnOrderItem.objects.filter(
            return_order__purchase_order=order,
            original_item=itm
        ).exclude(return_order__status__in=['cancelled', 'rejected']).aggregate(s=Sum('quantity'))['s'] or Decimal('0.00')
        rem_qty = max(Decimal('0.00'), itm.quantity - ret_sum)
        items_data.append({
            'item_id': itm.id,
            'product_id': itm.product_id,
            'product_name': itm.product.name,
            'product_code': itm.product.sku_code,
            'unit_price': str(itm.unit_price),
            'tax_percentage': str(itm.tax_percentage or '0.00'),
            'original_quantity': str(itm.quantity),
            'returned_so_far': str(ret_sum),
            'remaining_returnable': str(rem_qty),
            'batch_number': itm.product_batch_number or '',
            'expiry_date': str(itm.product_expiry_date) if itm.product_expiry_date else '',
        })

    return JsonResponse({
        'order_id': order.id,
        'order_number': order.order_number,
        'supplier_name': order.supplier.name,
        'supplier_id': order.supplier_id,
        'warehouse_id': order.target_warehouse_id,
        'warehouse_name': order.target_warehouse.name if order.target_warehouse else '',
        'items': items_data
    })


