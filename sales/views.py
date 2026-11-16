from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q, Sum, Count
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.http import JsonResponse
from django.urls import reverse

from django.core.paginator import Paginator
from master_data.pagination_utils import paginate_queryset
from master_data.models import Area
from contacts.constants import CUSTOMER_CATEGORIES
from contacts.views import contact_detail, contact_create, contact_edit
from .models import (
    SalesOrder, SalesOrderItem, CustomerAccount, CustomerTransaction, Collection,
    SalesReturnOrder, SalesReturnOrderItem
)
from .services import (
    SalesOrderService, CollectionService,
    SalesReturnOrderService, build_sales_return_timeline
)
from master_data.search_utils import (
    filter_by_arabic_search,
    parse_search_limit,
    get_bounded_select_options,
    serialize_contact_option,
    serialize_warehouse_option,
    serialize_vault_option,
)
from contacts.models import Contact
from catalog.models import Product
from inventory.models import Warehouse
from treasury.models import Vault
from accounts.permissions import (
    require_permission, has_perm_or_admin, render_forbidden_response,
    get_scoped_queryset, can_user_access_object
)
from accounts.scope_service import ScopeResolutionService


@require_permission('sales:orders/list')
def sales_orders_list(request):
    status_filter = request.GET.get('status', 'all')
    customer_filter = request.GET.get('customer')
    search = request.GET.get('search', '').strip()

    qs = SalesOrder.objects.select_related('customer', 'customer__area', 'source_warehouse', 'created_by').all().order_by('-order_date', '-id')
    qs = get_scoped_queryset(qs, request.user, 'salesorder')

    active_filters = []

    if status_filter != 'all':
        if status_filter in ['manager_approval', 'approved']:
            qs = qs.filter(status__in=['manager_approval', 'approved'])
        else:
            qs = qs.filter(status=status_filter)
        status_labels = dict(SalesOrder.STATUS_CHOICES)
        active_filters.append({'label': f'الحالة: {status_labels.get(status_filter, status_filter)}', 'param': 'status'})

    if customer_filter:
        qs = qs.filter(customer_id=customer_filter)
        c_obj = ScopeResolutionService.get_scoped_choices(request.user, 'customers', 'sales').filter(id=customer_filter).first()
        active_filters.append({'label': f'العميل: {c_obj.name if c_obj else customer_filter}', 'param': 'customer'})

    if search:
        qs = filter_by_arabic_search(qs, search, ['order_number', 'serial_num', 'customer__name'])
        active_filters.append({'label': f'بحث: {search}', 'param': 'search'})

    paginator, page_obj = paginate_queryset(request, qs, default_per_page=25, max_per_page=100)

    # Scoped bounded customer filter options (selected customer preserved for smart search)
    customers = get_bounded_select_options(
        ScopeResolutionService.get_scoped_choices(request.user, 'customers', 'sales'),
        selected_id=customer_filter,
        limit=100,
    )

    # Dedicated real scoped statistics cards matching filtered queryset
    stats_qs = qs if status_filter == 'rejected' else qs.exclude(status='rejected')
    agg = stats_qs.aggregate(
        total_orders=Count('id'),
        total_value=Sum('grand_total'),
        invoiced_value=Sum('grand_total', filter=Q(status='invoiced')),
        pending_count=Count('id', filter=Q(status__in=['pending', 'manager_approval'])),
    )
    stats = {
        'total_orders': agg['total_orders'] or 0,
        'total_value': agg['total_value'] or Decimal('0.00'),
        'invoiced_value': agg['invoiced_value'] or Decimal('0.00'),
        'pending_count': agg['pending_count'] or 0,
    }

    context = {
        'orders': page_obj.object_list,
        'page_obj': page_obj,
        'paginator': paginator,
        'current_status': status_filter,
        'selected_customer': customer_filter,
        'search_query': search,
        'customers': customers,
        'active_filters': active_filters,
        'total_count': paginator.count,
        'stats': stats,
    }
    return render(request, 'sales/sales_orders_list.html', context)


@require_permission('sales:orders/create')
def sales_order_create(request):
    if request.method == 'POST':
        customer_id = request.POST.get('customer')
        warehouse_id = request.POST.get('warehouse')
        order_date = request.POST.get('order_date')
        delivery_date = request.POST.get('delivery_date') or None
        due_date = request.POST.get('due_date') or None
        custom_discount_percentage = request.POST.get('custom_discount_percentage') or '0.00'
        shipping_fees = request.POST.get('shipping_fees') or '0.00'
        notes = request.POST.get('notes', '').strip()

        # Parse item rows
        product_ids = request.POST.getlist('product_id[]')
        quantities = request.POST.getlist('quantity[]')
        unit_prices = request.POST.getlist('unit_price[]')
        discounts = request.POST.getlist('discount_percentage[]')

        items_data = []
        for i in range(len(product_ids)):
            p_id = product_ids[i]
            if not p_id:
                continue
            prod = Product.objects.filter(id=p_id).first()
            if not prod:
                continue
            qty = Decimal(quantities[i] or '1')
            price = Decimal(unit_prices[i] or '0')
            disc = Decimal(discounts[i] or '0') if i < len(discounts) else Decimal('0')

            items_data.append({
                'product': prod,
                'quantity': qty,
                'unit_price': price,
                'discount_percentage': disc,
            })

        from accounts.services import get_representative_warehouse
        rep_wh = get_representative_warehouse(request.user)

        if rep_wh:
            if warehouse_id and str(warehouse_id) != str(rep_wh.id):
                forged_wh = get_object_or_404(Warehouse, id=warehouse_id)
                if not can_user_access_object(request.user, forged_wh, 'operate'):
                    return render_forbidden_response(request, "لا يمكنك إجراء مبيعات من مخزن خارج نطاق صلاحيتك.")
            warehouse = rep_wh
        elif warehouse_id:
            warehouse = get_object_or_404(Warehouse, id=warehouse_id)
            if not can_user_access_object(request.user, warehouse, 'operate'):
                return render_forbidden_response(request, "لا يمكنك إجراء مبيعات من مخزن خارج نطاق صلاحيتك.")
        else:
            messages.error(request, "يرجى تحديد المخزن.")
            return redirect('sales_order_create')

        if not customer_id:
            messages.error(request, "يرجى تحديد العميل.")
            return redirect('sales_order_create')

        customer = get_object_or_404(Contact, id=customer_id)
        if not can_user_access_object(request.user, customer, 'view'):
            return render_forbidden_response(request, "غير مصرح لك بإنشاء أمر بيع لعميل خارج نطاق منطقتك الجغرافية.")
        if not customer.is_customer or customer.status == 'inactive':
            messages.error(request, "جهة الاتصال المحددة غير مصنفة كعميل نشط.")
            return redirect('sales_order_create')

        try:
            order = SalesOrderService.create_order(
                customer=customer,
                source_warehouse=warehouse,
                order_date=order_date,
                items_data=items_data,
                user=request.user,
                delivery_date=delivery_date,
                due_date=due_date,
                custom_discount_percentage=Decimal(custom_discount_percentage),
                shipping_fees=Decimal(shipping_fees),
                notes=notes
            )
            messages.success(request, f"تم إنشاء أمر البيع بنجاح ({order.order_number}) بإجمالي {order.grand_total:,.2f} ج.م.")
            return redirect('sales_order_detail', pk=order.pk)
        except ValidationError as e:
            messages.error(request, str(e.message if hasattr(e, 'message') else e))
            return redirect('sales_order_create')

    from accounts.services import is_representative, get_representative_warehouse
    is_rep = is_representative(request.user)
    user_rep_wh = get_representative_warehouse(request.user) if is_rep else None

    raw_selected_customer = request.GET.get('customer') or request.GET.get('customer_id')
    customers_qs = ScopeResolutionService.get_scoped_choices(request.user, 'customers', 'sales')
    customers = get_bounded_select_options(customers_qs, selected_id=raw_selected_customer, limit=100)
    selected_customer_id = None
    if raw_selected_customer and str(raw_selected_customer).isdigit():
        candidate_cid = int(raw_selected_customer)
        if any(c.id == candidate_cid for c in customers):
            selected_customer_id = candidate_cid
    warehouses = ScopeResolutionService.get_scoped_choices(request.user, 'warehouses', 'sales')
    products = Product.objects.filter(is_active=True, sellable=True)

    context = {
        'customers': customers,
        'selected_customer_id': selected_customer_id,
        'warehouses': warehouses,
        'user_rep_wh': user_rep_wh,
        'is_rep': is_rep,
        'products': products,
    }
    return render(request, 'sales/sales_order_create.html', context)


@require_permission('sales:orders/edit')
def sales_order_edit(request, pk):
    order = get_object_or_404(
        SalesOrder.objects.select_related('customer', 'source_warehouse').prefetch_related('items__product'),
        pk=pk
    )
    if not can_user_access_object(request.user, order, 'edit'):
        return render_forbidden_response(request, "لا يمكنك تعديل هذا الطلب خارج نطاق منطقتك الجغرافية أو صلاحياتك.")

    if order.status in ['preparing', 'delivered', 'invoiced', 'cancelled']:
        messages.error(request, f"لا يمكن تعديل أمر البيع في حالته الحالية ({order.get_status_display()}).")
        return redirect('sales_order_detail', pk=order.pk)

    if request.method == 'POST':
        customer_id = request.POST.get('customer')
        warehouse_id = request.POST.get('warehouse')
        order_date = request.POST.get('order_date')
        delivery_date = request.POST.get('delivery_date') or None
        due_date = request.POST.get('due_date') or None
        custom_discount_percentage = request.POST.get('custom_discount_percentage') or '0.00'
        shipping_fees = request.POST.get('shipping_fees') or '0.00'
        notes = request.POST.get('notes', '').strip()

        product_ids = request.POST.getlist('product_id[]')
        quantities = request.POST.getlist('quantity[]')
        unit_prices = request.POST.getlist('unit_price[]')
        discounts = request.POST.getlist('discount_percentage[]')

        items_data = []
        for i in range(len(product_ids)):
            p_id = product_ids[i]
            if not p_id:
                continue
            prod = Product.objects.filter(id=p_id).first()
            if not prod:
                continue
            qty = Decimal(quantities[i] or '1')
            price = Decimal(unit_prices[i] or '0')
            disc = Decimal(discounts[i] or '0') if i < len(discounts) else Decimal('0')

            items_data.append({
                'product': prod,
                'quantity': qty,
                'unit_price': price,
                'discount_percentage': disc,
            })

        from accounts.services import get_representative_warehouse
        rep_wh = get_representative_warehouse(request.user)

        if warehouse_id:
            warehouse = get_object_or_404(Warehouse, id=warehouse_id)
            if not can_user_access_object(request.user, warehouse, 'operate'):
                return render_forbidden_response(request, "لا يمكنك إجراء مبيعات من مخزن خارج نطاق صلاحيتك.")
        elif rep_wh:
            warehouse = rep_wh
        else:
            warehouse = order.source_warehouse

        if not customer_id:
            messages.error(request, "يرجى تحديد العميل.")
            return redirect('sales_order_edit', pk=order.pk)

        customer = get_object_or_404(Contact, id=customer_id)
        if not can_user_access_object(request.user, customer, 'view'):
            return render_forbidden_response(request, "غير مصرح لك بإنشاء أمر بيع لعميل خارج نطاق منطقتك الجغرافية.")
        if not customer.is_customer or (customer.pk != order.customer_id and customer.status == 'inactive'):
            messages.error(request, "جهة الاتصال المحددة غير مصنفة كعميل نشط.")
            return redirect('sales_order_edit', pk=order.pk)

        try:
            order = SalesOrderService.update_order(
                order=order,
                customer=customer,
                source_warehouse=warehouse,
                order_date=order_date,
                items_data=items_data,
                user=request.user,
                delivery_date=delivery_date,
                due_date=due_date,
                custom_discount_percentage=Decimal(custom_discount_percentage),
                shipping_fees=Decimal(shipping_fees),
                notes=notes
            )
            messages.success(request, f"تم تعديل أمر البيع بنجاح ({order.order_number}) بإجمالي {order.grand_total:,.2f} ج.م.")
            return redirect('sales_order_detail', pk=order.pk)
        except ValidationError as e:
            messages.error(request, str(e.message if hasattr(e, 'message') else e))
            return redirect('sales_order_edit', pk=order.pk)

    from accounts.services import is_representative, get_representative_warehouse
    is_rep = is_representative(request.user)
    user_rep_wh = get_representative_warehouse(request.user) if is_rep else None

    customers = get_bounded_select_options(
        ScopeResolutionService.get_scoped_choices(request.user, 'customers', 'sales'),
        selected_id=order.customer_id,
        limit=100,
    )
    warehouses = get_bounded_select_options(
        ScopeResolutionService.get_scoped_choices(request.user, 'warehouses', 'sales'),
        selected_id=order.source_warehouse_id,
        limit=100,
    )
    products = Product.objects.filter(is_active=True)

    context = {
        'order': order,
        'customers': customers,
        'warehouses': warehouses,
        'user_rep_wh': user_rep_wh,
        'is_rep': is_rep,
        'products': products,
    }
    return render(request, 'sales/sales_order_edit.html', context)


@require_permission('sales:orders/view')
def sales_order_detail(request, pk):
    order = get_object_or_404(
        SalesOrder.objects.select_related(
            'customer', 'customer__area', 'source_warehouse', 'created_by', 'approved_by', 'memo'
        ).prefetch_related('items__product'),
        pk=pk
    )
    if not can_user_access_object(request.user, order, 'view'):
        return render_forbidden_response(request, "لا يمكنك عرض هذا الطلب خارج نطاق منطقتك الجغرافية أو صلاحيتك.")

    can_approve = has_perm_or_admin(request.user, 'sales:orders/approve') and can_user_access_object(request.user, order, 'approve')
    can_edit = has_perm_or_admin(request.user, 'sales:orders/edit') and can_user_access_object(request.user, order, 'edit')
    is_owner = (order.created_by_id == request.user.id)
    can_resubmit = is_owner and order.status == 'rejected'

    approval_history = order.approval_history.select_related('actor').order_by('-created_at')

    return render(request, 'sales/sales_order_detail.html', {
        'order': order,
        'can_approve': can_approve,
        'can_edit': can_edit,
        'can_resubmit': can_resubmit,
        'approval_history': approval_history,
    })


@login_required
def sales_order_action(request, pk, action):
    action_perm_map = {
        'approve': 'sales:orders/approve',
        'reject': 'sales:orders/approve',
        'disapprove': 'sales:orders/approve',
        'resubmit': 'sales:orders/create',
        'prepare': 'sales:orders/unstock',
        'deliver': 'sales:orders/unstock',
        'invoice': 'sales:orders/invoice',
        'cancel': 'sales:orders/cancel',
    }
    needed_perm = action_perm_map.get(action, 'sales:orders/edit')
    if not has_perm_or_admin(request.user, needed_perm):
        return render_forbidden_response(request, f"ليس لديك صلاحية لتنفيذ هذا الإجراء ({needed_perm})", perm_codename=needed_perm)

    order = get_object_or_404(SalesOrder, pk=pk)

    # Scoping and self-approval checks
    if action in ['approve', 'reject', 'disapprove']:
        if not can_user_access_object(request.user, order, action):
            if order.created_by_id == request.user.id and not (request.user.is_superuser or getattr(request.user, 'is_super_admin', False)):
                messages.error(request, "لا يمكن للمندوب اعتماد أو رفض أمر البيع الخاص به كمنشئ أو مسؤول.")
                return redirect('sales_order_detail', pk=order.pk)
            return render_forbidden_response(request, "لا يمكنك اعتماد أو رفض هذا الطلب خارج نطاق منطقتك الجغرافية أو صلاحيتك.")
    else:
        if not can_user_access_object(request.user, order, 'edit'):
            return render_forbidden_response(request, "لا يمكنك تعديل هذا الطلب خارج نطاق منطقتك الجغرافية أو صلاحيتك.")

    is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'application/json' in request.headers.get('accept', '')

    try:
        if action == 'approve':
            notes = request.POST.get('approval_notes', '') or request.POST.get('notes', '')
            SalesOrderService.approve_order(order, request.user, notes=notes)
            msg = f"تم اعتماد أمر البيع {order.order_number} بنجاح."
            if is_ajax:
                return JsonResponse({'success': True, 'message': msg, 'status': order.status})
            messages.success(request, msg)

        elif action in ['reject', 'disapprove']:
            reason = request.POST.get('rejection_reason', '') or request.POST.get('reason', '') or request.POST.get('approval_notes', '')
            if not (reason or '').strip():
                msg = "يرجى توضيح سبب رفض أمر البيع."
                if is_ajax:
                    return JsonResponse({'success': False, 'message': msg}, status=400)
                messages.error(request, msg)
                return redirect(request.META.get('HTTP_REFERER', f'/sales/{order.pk}/'))

            SalesOrderService.reject_order(order, request.user, reason=reason)
            msg = f"تم رفض أمر البيع {order.order_number}."
            if is_ajax:
                return JsonResponse({'success': True, 'message': msg, 'status': order.status})
            messages.error(request, msg)

        elif action == 'resubmit':
            SalesOrderService.resubmit_order(order, request.user)
            msg = f"تمت إعادة تقديم أمر البيع {order.order_number} للاعتماد بنجاح."
            if is_ajax:
                return JsonResponse({'success': True, 'message': msg, 'status': order.status})
            messages.success(request, msg)

        elif action == 'prepare':
            SalesOrderService.prepare_order(order, request.user)
            messages.success(request, f"تم حجز البضاعة بالمخزن وتغيير حالة الطلب إلى (جاري التجهيز).")
        elif action == 'deliver':
            SalesOrderService.deliver_order(order, request.user)
            messages.success(request, f"تم تسليم أمر البيع {order.order_number} وتوليد إذن صرف المخزن بنجاح.")
        elif action == 'invoice':
            SalesOrderService.invoice_order(order, request.user)
            messages.success(request, f"تم ترحيل فاتورة المبيعات للحسابات وإثبات مديونية العميل {order.customer.name}.")
        elif action == 'cancel':
            SalesOrderService.cancel_order(order, request.user)
            messages.warning(request, f"تم إلغاء أمر البيع {order.order_number}.")
        else:
            messages.error(request, "إجراء غير معروف.")
    except ValidationError as e:
        err_msg = str(e.message if hasattr(e, 'message') else e)
        if is_ajax:
            return JsonResponse({'success': False, 'message': err_msg}, status=400)
        messages.error(request, err_msg)

    return redirect(request.META.get('HTTP_REFERER', f'/sales/{order.pk}/'))


@require_permission('sales:collections/list')
def collections_list(request):
    search = request.GET.get('search', '').strip()
    customer_id = request.GET.get('customer')
    vault_id = request.GET.get('vault')

    qs = Collection.objects.select_related('customer', 'vault', 'created_by').order_by('-serial_num')
    qs = get_scoped_queryset(qs, request.user, 'collection')

    active_filters = []

    if customer_id:
        qs = qs.filter(customer_id=customer_id)
        c_obj = ScopeResolutionService.get_scoped_choices(request.user, 'customers', 'sales').filter(id=customer_id).first()
        active_filters.append({'label': f'العميل: {c_obj.name if c_obj else customer_id}', 'param': 'customer'})

    if vault_id:
        qs = qs.filter(vault_id=vault_id)
        v_obj = ScopeResolutionService.get_scoped_choices(request.user, 'vaults', 'sales').filter(id=vault_id).first()
        active_filters.append({'label': f'الخزنة: {v_obj.name if v_obj else vault_id}', 'param': 'vault'})

    if search:
        qs = filter_by_arabic_search(qs, search, ['serial_num', 'customer__name', 'notes'])
        active_filters.append({'label': f'بحث: {search}', 'param': 'search'})

    customers = get_bounded_select_options(
        ScopeResolutionService.get_scoped_choices(request.user, 'customers', 'sales'),
        selected_id=customer_id,
        limit=100,
    )
    vaults = ScopeResolutionService.get_scoped_choices(request.user, 'vaults', 'sales')

    paginator, page_obj = paginate_queryset(request, qs, default_per_page=25, max_per_page=100)

    # Dedicated real scoped statistics cards matching active filters
    now = timezone.now()
    col_agg = qs.aggregate(
        total_count=Count('id'),
        total_amount=Sum('amount'),
        month_amount=Sum('amount', filter=Q(collection_date__year=now.year, collection_date__month=now.month)),
        vaults_count=Count('vault', distinct=True),
    )
    stats = {
        'total_count': col_agg['total_count'] or 0,
        'total_amount': col_agg['total_amount'] or Decimal('0.00'),
        'month_amount': col_agg['month_amount'] or Decimal('0.00'),
        'vaults_count': col_agg['vaults_count'] or 0,
    }

    context = {
        'collections': page_obj.object_list,
        'page_obj': page_obj,
        'paginator': paginator,
        'customers': customers,
        'vaults': vaults,
        'search_query': search,
        'selected_customer_id': customer_id,
        'selected_vault_id': vault_id,
        'active_filters': active_filters,
        'total_count': paginator.count,
        'stats': stats,
    }
    return render(request, 'sales/collections_list.html', context)


@require_permission('sales:collections/create')
def collection_create(request):
    if request.method == 'POST':
        customer_id = request.POST.get('customer')
        vault_id = request.POST.get('vault')
        amount = request.POST.get('amount')
        sales_order_id = request.POST.get('sales_order')
        collection_date = request.POST.get('collection_date') or None
        due_date = request.POST.get('due_date') or None
        payment_method = request.POST.get('payment_method', 'cash')
        notes = request.POST.get('notes', '').strip()

        if not customer_id or not vault_id or not amount:
            messages.error(request, "يرجى ملء جميع الحقول المطلوبة (العميل، الخزنة، والمبلغ).")
            return redirect('collection_create')

        customer = get_object_or_404(Contact, id=customer_id)
        vault = get_object_or_404(Vault, id=vault_id)

        if not can_user_access_object(request.user, customer, 'view'):
            return render_forbidden_response(request, "لا يمكنك تسجيل تحصيل لعميل خارج نطاقك الجغرافي أو صلاحياتك.")
        if not customer.is_customer or customer.status == 'inactive':
            messages.error(request, "جهة الاتصال المحددة غير مصنفة كعميل نشط.")
            return redirect('collection_create')
        if not can_user_access_object(request.user, vault, 'deposit'):
            return render_forbidden_response(request, "لا يمكنك الإيداع في خزنة غير مخصصة لك.")

        sales_order = None
        if sales_order_id:
            sales_order = get_object_or_404(SalesOrder, id=sales_order_id)
            if not can_user_access_object(request.user, sales_order, 'view'):
                return render_forbidden_response(request, "لا يمكنك تسجيل تحصيل لأمر بيع خارج نطاق صلاحياتك.")

        try:
            col = CollectionService.record_collection(
                customer=customer,
                vault=vault,
                amount=Decimal(amount),
                user=request.user,
                payment_method=payment_method,
                notes=notes,
                sales_order=sales_order,
                collection_date=collection_date,
                due_date=due_date
            )
            order_info = f" لأمر بيع {sales_order.order_number}" if sales_order else ""
            messages.success(request, f"تم تسجيل سند التحصيل #{col.serial_num} بنجاح بمبلغ {col.amount:,.2f} ج.م من العميل {customer.name}{order_info}.")
            return redirect('collections_list')
        except ValidationError as e:
            messages.error(request, str(e.message if hasattr(e, 'message') else e))
            return redirect('collection_create')

    initial_customer = request.GET.get('customer_id') or request.GET.get('customer')
    initial_order = request.GET.get('order_id')

    if initial_order and not initial_customer:
        ord_obj = SalesOrder.objects.filter(id=initial_order).first()
        if ord_obj and can_user_access_object(request.user, ord_obj, 'view'):
            initial_customer = ord_obj.customer_id

    customers = get_bounded_select_options(
        ScopeResolutionService.get_scoped_choices(request.user, 'customers', 'sales'),
        selected_id=initial_customer,
        limit=100,
    )
    vaults = ScopeResolutionService.get_scoped_choices(request.user, 'vaults', 'sales')

    # Open sales orders for dropdown linking
    orders_qs = SalesOrder.objects.exclude(status='cancelled').select_related('customer').order_by('-order_date')
    orders_qs = get_scoped_queryset(orders_qs, request.user, 'salesorder')

    context = {
        'customers': customers,
        'vaults': vaults,
        'orders': orders_qs,
        'selected_customer_id': int(initial_customer) if initial_customer and str(initial_customer).isdigit() else None,
        'selected_order_id': int(initial_order) if initial_order and str(initial_order).isdigit() else None,
    }
    return render(request, 'sales/collection_create.html', context)


@require_permission(['contacts:contacts/list', 'sales:orders/list', 'sales:customers/accounting'])
def sales_customers_list(request):
    """
    Sales Customer Directory & Profiles (دليل وبيانات العملاء).
    Fully scoped by user role and geographic territory.
    """
    search = request.GET.get('search', '').strip() or request.GET.get('q', '').strip()
    status = request.GET.get('status', 'all').strip()
    area_id = request.GET.get('area_id', '').strip()
    category = request.GET.get('category', 'all').strip()

    qs = Contact.objects.filter(is_customer=True).select_related('area', 'customer_account', 'created_by').prefetch_related('addresses__area')
    qs = get_scoped_queryset(qs, request.user, 'contact')

    if status and status != 'all':
        qs = qs.filter(status=status)
    if area_id:
        qs = qs.filter(Q(area_id=area_id) | Q(addresses__area_id=area_id)).distinct()
    if category and category != 'all':
        qs = qs.filter(customer_category=category)

    if search:
        qs = filter_by_arabic_search(
            qs, search,
            ['name', 'serial_num', 'mobile', 'phone', 'code', 'contact_person', 'tax_id']
        ).distinct()

    qs = qs.order_by('name')

    # Dedicated scoped statistics matching active filters
    cust_agg = qs.aggregate(
        total_customers=Count('id', distinct=True),
        active_customers=Count('id', filter=Q(status__in=['active', 'customer']), distinct=True),
        lead_customers=Count('id', filter=Q(status='lead'), distinct=True),
    )
    stats = {
        'total_customers': cust_agg['total_customers'] or 0,
        'active_customers': cust_agg['active_customers'] or 0,
        'lead_customers': cust_agg['lead_customers'] or 0,
        'total_receivable': CustomerAccount.objects.filter(customer__in=qs, current_balance__gt=0).aggregate(tot=Sum('current_balance'))['tot'] or Decimal('0.00'),
    }

    paginator, page_obj = paginate_queryset(request, qs, default_per_page=25)

    governorates = ScopeResolutionService.get_scoped_choices(request.user, 'governorates', 'sales')

    categories = [c[0] if isinstance(c, (list, tuple)) else c for c in CUSTOMER_CATEGORIES]

    context = {
        'customers': page_obj.object_list,
        'page_obj': page_obj,
        'paginator': paginator,
        'total_count': paginator.count,
        'stats': stats,
        'search_query': search,
        'current_status': status,
        'current_area_id': area_id,
        'current_category': category,
        'governorates': governorates,
        'categories': categories,
    }
    return render(request, 'sales/customers_list.html', context)


@require_permission(['contacts:contacts/create', 'sales:orders/create'])
def sales_customer_create(request):
    """
    Create a new customer in sales context.
    """
    if request.method == 'GET' and 'relation' not in request.GET:
        get_copy = request.GET.copy()
        get_copy['relation'] = 'customer'
        request.GET = get_copy
    return contact_create(request)


@require_permission(['contacts:contacts/view', 'sales:orders/list', 'sales:customers/accounting'])
def sales_customer_detail(request, pk):
    """
    View customer profile with full detail, tabs, balances, and history.
    """
    return contact_detail(request, pk=pk)


@require_permission(['contacts:contacts/edit', 'sales:orders/create'])
def sales_customer_edit(request, pk):
    """
    Edit existing customer record with authorization checks and audit logging.
    """
    return contact_edit(request, pk=pk)


@require_permission('sales:customers/accounting')
def accounting_customers_list(request):
    """
    Customer Statements & Balances (حسابات العملاء).
    """
    search = request.GET.get('search', '').strip()
    qs = CustomerAccount.objects.select_related('customer', 'customer__area').order_by('-current_balance')
    qs = get_scoped_queryset(qs, request.user, 'customeraccount')

    active_filters = []
    if search:
        qs = filter_by_arabic_search(qs, search, ['customer__name', 'customer__code'])
        active_filters.append({'label': f'بحث: {search}', 'param': 'search'})

    acc_agg = qs.aggregate(
        total_customers=Count('id'),
        total_receivable=Sum('current_balance', filter=Q(current_balance__gt=0)),
        total_overdue=Sum('overdue_balance', filter=Q(overdue_balance__gt=0)),
        total_credit_limit=Sum('credit_limit'),
    )
    account_stats = {
        'total_customers': acc_agg['total_customers'] or 0,
        'total_receivable': acc_agg['total_receivable'] or Decimal('0.00'),
        'total_overdue': acc_agg['total_overdue'] or Decimal('0.00'),
        'total_credit_limit': acc_agg['total_credit_limit'] or Decimal('0.00'),
    }

    paginator, page_obj = paginate_queryset(request, qs, default_per_page=25, max_per_page=100)

    context = {
        'accounts': page_obj.object_list,
        'page_obj': page_obj,
        'paginator': paginator,
        'search_query': search,
        'active_filters': active_filters,
        'total_count': paginator.count,
        'stats': account_stats,
    }
    return render(request, 'sales/accounting_customers_list.html', context)


@require_permission('sales:customers/transactions')
def customer_transactions_list(request):
    """
    Customer Ledger Transactions (عمليات العملاء).
    """
    customer_id = request.GET.get('customer_id')
    search = request.GET.get('search', '').strip()

    qs = CustomerTransaction.objects.select_related('account', 'account__customer', 'created_by').order_by('-serial')
    scoped_contacts = get_scoped_queryset(Contact.objects.all(), request.user, 'contact')
    qs = qs.filter(account__customer__in=scoped_contacts)

    active_filters = []

    if customer_id:
        qs = qs.filter(account__customer_id=customer_id)
        c_obj = scoped_contacts.filter(id=customer_id).first()
        active_filters.append({'label': f'العميل: {c_obj.name if c_obj else customer_id}', 'param': 'customer_id'})

    if search:
        qs = filter_by_arabic_search(qs, search, ['serial', 'description', 'account__customer__name'])
        active_filters.append({'label': f'بحث: {search}', 'param': 'search'})

    customers = get_bounded_select_options(
        ScopeResolutionService.get_scoped_choices(request.user, 'customers', 'sales'),
        selected_id=customer_id,
        limit=100,
    )

    tx_agg = qs.aggregate(
        total_count=Count('id'),
        total_debit=Sum('debit'),
        total_credit=Sum('credit'),
    )
    tx_stats = {
        'total_count': tx_agg['total_count'] or 0,
        'total_debit': tx_agg['total_debit'] or Decimal('0.00'),
        'total_credit': tx_agg['total_credit'] or Decimal('0.00'),
    }
    tx_stats['net_balance'] = tx_stats['total_debit'] - tx_stats['total_credit']

    paginator, page_obj = paginate_queryset(request, qs, default_per_page=25, max_per_page=100)

    context = {
        'transactions': page_obj.object_list,
        'page_obj': page_obj,
        'paginator': paginator,
        'customers': customers,
        'selected_customer_id': customer_id,
        'search_query': search,
        'active_filters': active_filters,
        'total_count': paginator.count,
        'stats': tx_stats,
    }
    return render(request, 'sales/customer_transactions_list.html', context)


from master_data.excel_utils import export_to_excel_response


@require_permission('sales:orders/export')
def sales_orders_export(request):
    status_filter = request.GET.get('status', 'all')
    customer_filter = request.GET.get('customer')
    search = request.GET.get('search', '').strip()

    qs = SalesOrder.objects.select_related('customer', 'customer__area', 'source_warehouse', 'created_by').all().order_by('-serial_num')
    qs = get_scoped_queryset(qs, request.user, 'salesorder')

    if status_filter != 'all':
        qs = qs.filter(status=status_filter)
    if customer_filter:
        qs = qs.filter(customer_id=customer_filter)
    if search:
        qs = qs.filter(
            Q(order_number__icontains=search) |
            Q(serial_num__icontains=search) |
            Q(customer__name__icontains=search)
        )

    columns = [
        {'header': 'رقم أمر البيع', 'key': 'order_number', 'width': 18, 'align': 'center'},
        {'header': 'العميل', 'key': lambda o: o.customer.name, 'width': 35, 'align': 'right'},
        {'header': 'المنطقة', 'key': lambda o: o.customer.area.name if o.customer.area else '', 'width': 20, 'align': 'right'},
        {'header': 'المخزن المنصرف منه', 'key': lambda o: o.source_warehouse.name if o.source_warehouse else '', 'width': 22, 'align': 'right'},
        {'header': 'تاريخ الطلب', 'key': lambda o: o.order_date.strftime('%Y-%m-%d') if o.order_date else '', 'width': 16, 'align': 'center'},
        {'header': 'الحالة', 'key': lambda o: o.get_status_display(), 'width': 18, 'align': 'center'},
        {'header': 'إجمالي القيمة', 'key': lambda o: float(o.grand_total) if o.grand_total is not None else 0.0, 'format': '#,##0.00', 'width': 18, 'align': 'right'},
        {'header': 'المنشئ', 'key': lambda o: o.created_by.get_full_name() or o.created_by.username if o.created_by else '', 'width': 22, 'align': 'right'},
        {'header': 'ملاحظات', 'key': lambda o: o.notes or '', 'width': 30, 'align': 'right'},
    ]

    return export_to_excel_response(qs, columns, filename="sales_orders_export", sheet_title="أوامر البيع")


@require_permission('sales:collections/export')
def collections_export(request):
    customer_id = request.GET.get('customer')
    qs = Collection.objects.select_related('customer', 'vault', 'created_by').order_by('-serial_num')
    qs = get_scoped_queryset(qs, request.user, 'collection')
    if customer_id:
        qs = qs.filter(customer_id=customer_id)

    columns = [
        {'header': 'رقم السند', 'key': lambda c: f"#{c.serial_num}", 'width': 14, 'align': 'center'},
        {'header': 'العميل', 'key': lambda c: c.customer.name, 'width': 35, 'align': 'right'},
        {'header': 'الخزنة / الحساب', 'key': lambda c: c.vault.name, 'width': 25, 'align': 'right'},
        {'header': 'المبلغ المحصل', 'key': lambda c: float(c.amount) if c.amount is not None else 0.0, 'format': '#,##0.00', 'width': 18, 'align': 'right'},
        {'header': 'طريقة الدفع', 'key': lambda c: c.get_payment_method_display(), 'width': 16, 'align': 'center'},
        {'header': 'تاريخ وساعة السند', 'key': lambda c: c.created_at.strftime('%Y-%m-%d %H:%M') if c.created_at else '', 'width': 20, 'align': 'center'},
        {'header': 'المحصل', 'key': lambda c: c.created_by.get_full_name() or c.created_by.username if c.created_by else '', 'width': 22, 'align': 'right'},
        {'header': 'ملاحظات', 'key': lambda c: c.notes or '', 'width': 30, 'align': 'right'},
    ]

    return export_to_excel_response(qs, columns, filename="collections_export", sheet_title="التحصيلات النقدية")


@require_permission('sales:returns/list')
def sales_return_orders_list(request):
    status_filter = request.GET.get('status', 'all')
    customer_filter = request.GET.get('customer')
    search = request.GET.get('search', '').strip()
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')

    qs = SalesReturnOrder.objects.select_related(
        'customer', 'customer__area', 'sales_order', 'target_warehouse', 'created_by'
    ).all().order_by('-serial_num')
    qs = get_scoped_queryset(qs, request.user, 'salesreturnorder')

    active_filters = []

    if status_filter != 'all':
        qs = qs.filter(status=status_filter)
        status_labels = dict(SalesReturnOrder.STATUS_CHOICES)
        active_filters.append({'label': f'الحالة: {status_labels.get(status_filter, status_filter)}', 'param': 'status'})

    if customer_filter:
        qs = qs.filter(customer_id=customer_filter)
        c_obj = ScopeResolutionService.get_scoped_choices(request.user, 'customers', 'sales').filter(id=customer_filter).first()
        active_filters.append({'label': f'العميل: {c_obj.name if c_obj else customer_filter}', 'param': 'customer'})

    if date_from:
        qs = qs.filter(order_date__gte=date_from)
        active_filters.append({'label': f'من تاريخ: {date_from}', 'param': 'date_from'})

    if date_to:
        qs = qs.filter(order_date__lte=date_to)
        active_filters.append({'label': f'إلى تاريخ: {date_to}', 'param': 'date_to'})

    if search:
        qs = filter_by_arabic_search(qs, search, ['order_number', 'serial_num', 'customer__name', 'sales_order__order_number'])
        active_filters.append({'label': f'بحث: {search}', 'param': 'search'})

    customers = get_bounded_select_options(
        ScopeResolutionService.get_scoped_choices(request.user, 'customers', 'sales'),
        selected_id=customer_filter,
        limit=100,
    )

    ret_agg = qs.aggregate(
        total_orders=Count('id'),
        total_value=Sum('grand_total'),
        pending_count=Count('id', filter=Q(status='pending')),
        settled_count=Count('id', filter=Q(status='settled')),
    )
    return_stats = {
        'total_orders': ret_agg['total_orders'] or 0,
        'total_value': ret_agg['total_value'] or Decimal('0.00'),
        'pending_count': ret_agg['pending_count'] or 0,
        'settled_count': ret_agg['settled_count'] or 0,
    }

    paginator, page_obj = paginate_queryset(request, qs, default_per_page=25, max_per_page=100)

    context = {
        'returns': page_obj.object_list,
        'page_obj': page_obj,
        'paginator': paginator,
        'current_status': status_filter,
        'selected_customer': customer_filter,
        'search_query': search,
        'date_from': date_from,
        'date_to': date_to,
        'customers': customers,
        'active_filters': active_filters,
        'active_filters_count': len(active_filters),
        'total_count': paginator.count,
        'stats': return_stats,
    }
    return render(request, 'sales/sales_return_orders_list.html', context)


@require_permission('sales:returns/create')
def sales_return_order_create(request):
    if request.method == 'POST':
        order_id = request.POST.get('sales_order')
        warehouse_id = request.POST.get('warehouse')
        order_date = request.POST.get('order_date') or timezone.now().date()
        notes = request.POST.get('notes', '').strip()

        if not order_id:
            messages.error(request, "يرجى تحديد أمر البيع المراد عمل مرتجع له.")
            return redirect('sales_return_order_create')

        sales_order = get_object_or_404(SalesOrder, id=order_id)
        if not can_user_access_object(request.user, sales_order, 'view'):
            return render_forbidden_response(request, "غير مصرح لك بعمل مرتجع لأمر بيع خارج نطاقك الجغرافي.")

        warehouse = None
        if warehouse_id:
            warehouse = get_object_or_404(Warehouse, id=warehouse_id)
            if not can_user_access_object(request.user, warehouse, 'operate'):
                return render_forbidden_response(request, "غير مصرح لك بالاستلام في هذا المخزن.")

        orig_item_ids = request.POST.getlist('original_item_id[]')
        quantities = request.POST.getlist('quantity[]')
        conditions = request.POST.getlist('condition[]')
        batch_numbers = request.POST.getlist('batch_number[]')
        expiry_dates = request.POST.getlist('expiry_date[]')

        items_data = []
        for i in range(len(orig_item_ids)):
            item_id = orig_item_ids[i]
            if not item_id:
                continue
            qty_str = quantities[i] if i < len(quantities) else '0'
            try:
                qty = Decimal(qty_str)
            except Exception:
                continue
            if qty <= Decimal('0.00'):
                continue

            cond = conditions[i] if i < len(conditions) else 'resalable'
            batch = batch_numbers[i] if i < len(batch_numbers) else ''
            exp = expiry_dates[i] if (i < len(expiry_dates) and expiry_dates[i]) else None

            items_data.append({
                'original_item_id': item_id,
                'quantity': qty,
                'condition': cond,
                'batch_number': batch,
                'expiry_date': exp,
            })

        if not items_data:
            messages.error(request, "يرجى تحديد صنف واحد على الأقل بكمية صالحة للإرجاع.")
            return redirect(f"{reverse('sales_return_order_create')}?order_id={sales_order.id}")

        try:
            return_order = SalesReturnOrderService.create_return_order(
                sales_order=sales_order,
                target_warehouse=warehouse,
                order_date=order_date,
                items_data=items_data,
                user=request.user,
                notes=notes
            )
            messages.success(request, f"تم إنشاء إشعار مرتجع المبيعات {return_order.order_number} بنجاح وهو بانتظار الاعتماد.")
            return redirect('sales_return_order_detail', pk=return_order.pk)
        except ValidationError as e:
            messages.error(request, str(e.message if hasattr(e, 'message') else e))
            return redirect(f"{reverse('sales_return_order_create')}?order_id={sales_order.id}")

    # GET request
    order_id = request.GET.get('order_id')
    selected_order = None
    order_items_payload = []
    if order_id:
        selected_order = SalesOrder.objects.filter(id=order_id, status__in=['delivered', 'invoiced']).first()
        if selected_order and can_user_access_object(request.user, selected_order, 'view'):
            for item in selected_order.items.select_related('product').all():
                ret_sum = SalesReturnOrderItem.objects.filter(
                    order__sales_order=selected_order,
                    original_item=item
                ).exclude(order__status__in=['cancelled', 'rejected']).aggregate(s=Sum('quantity'))['s'] or Decimal('0.00')
                rem_qty = max(Decimal('0.00'), item.quantity - ret_sum)
                order_items_payload.append({
                    'item': item,
                    'returned_so_far': ret_sum,
                    'remaining_returnable': rem_qty,
                })

    eligible_orders_qs = get_scoped_queryset(
        SalesOrder.objects.filter(status__in=['delivered', 'invoiced']).select_related('customer').order_by('-order_date'),
        request.user,
        'salesorder',
    )
    eligible_orders = get_bounded_select_options(
        eligible_orders_qs,
        selected_id=selected_order.id if selected_order else None,
        limit=50,
    )
    warehouses = ScopeResolutionService.get_scoped_choices(request.user, 'warehouses', 'sales')

    context = {
        'selected_order': selected_order,
        'order_items_payload': order_items_payload,
        'eligible_orders': eligible_orders,
        'warehouses': warehouses,
    }
    return render(request, 'sales/sales_return_order_create.html', context)


@require_permission('sales:returns/view')
def sales_return_order_detail(request, pk):
    return_order = get_object_or_404(
        SalesReturnOrder.objects.select_related(
            'customer', 'customer__area', 'sales_order', 'target_warehouse', 'created_by', 'approved_by', 'memo'
        ).prefetch_related('items__product', 'items__original_item'),
        pk=pk
    )
    if not can_user_access_object(request.user, return_order, 'view'):
        return render_forbidden_response(request, "غير مصرح لك بعرض هذا المرتجع خارج نطاقك الجغرافي.")

    role_name = getattr(request.user.role, 'name', '') if hasattr(request.user, 'role') and request.user.role else ''

    can_approve = (
        has_perm_or_admin(request.user, 'sales:returns/approve') and
        can_user_access_object(request.user, return_order, 'approve') and
        return_order.status == 'pending'
    )
    can_deliver = (
        has_perm_or_admin(request.user, 'inventory:transfers/approve') and
        can_user_access_object(request.user, return_order, 'operate') and
        return_order.status == 'approved'
    )
    can_settle = (
        (has_perm_or_admin(request.user, 'sales:orders/manage') or role_name in ['superadmin', 'accountant']) and
        return_order.status == 'delivered'
    )
    can_cancel = (
        (has_perm_or_admin(request.user, 'sales:returns/delete') or return_order.created_by_id == request.user.id) and
        return_order.status in ['pending', 'approved']
    )

    timeline_events = build_sales_return_timeline(return_order)

    context = {
        'return_order': return_order,
        'items': return_order.items.all(),
        'can_approve': can_approve,
        'can_deliver': can_deliver,
        'can_settle': can_settle,
        'can_cancel': can_cancel,
        'timeline_events': timeline_events,
    }
    return render(request, 'sales/sales_return_order_detail.html', context)


@login_required
def sales_return_order_action(request, pk, action):
    if request.method != 'POST':
        messages.error(request, "طريقة الطلب غير صالحة. يجب إرسال الإجراءات عبر طلب آمن (POST).")
        return redirect('sales_return_order_detail', pk=pk)

    return_order = get_object_or_404(SalesReturnOrder, pk=pk)

    try:
        if action == 'approve':
            if not has_perm_or_admin(request.user, 'sales:returns/approve'):
                return render_forbidden_response(request, "ليس لديك صلاحية اعتماد مرتجعات المبيعات.", perm_codename='sales:returns/approve')
            if not can_user_access_object(request.user, return_order, 'approve'):
                messages.error(request, "لا يمكنك اعتماد مرتجع مبيعات قمت بإنشائه بنفسك أو يقع خارج نطاق إدارتك.")
                return redirect('sales_return_order_detail', pk=pk)
            notes = request.POST.get('approval_notes', '')
            SalesReturnOrderService.approve_return_order(return_order, request.user, notes=notes)
            messages.success(request, f"تم اعتماد مرتجع المبيعات {return_order.order_number} بنجاح.")

        elif action == 'reject':
            if not has_perm_or_admin(request.user, 'sales:returns/approve'):
                return render_forbidden_response(request, "ليس لديك صلاحية رفض مرتجعات المبيعات.", perm_codename='sales:returns/approve')
            if not can_user_access_object(request.user, return_order, 'reject'):
                messages.error(request, "لا يمكنك رفض مرتجع مبيعات قمت بإنشائه بنفسك أو يقع خارج نطاق إدارتك.")
                return redirect('sales_return_order_detail', pk=pk)
            reason = request.POST.get('rejection_reason', '').strip()
            if not reason:
                messages.error(request, "يرجى كتابة سبب رفض المرتجع.")
                return redirect('sales_return_order_detail', pk=pk)
            SalesReturnOrderService.reject_return_order(return_order, request.user, reason=reason)
            messages.warning(request, f"تم رفض مرتجع المبيعات {return_order.order_number}.")

        elif action == 'deliver':
            if not has_perm_or_admin(request.user, 'inventory:transfers/approve'):
                return render_forbidden_response(request, "ليس لديك صلاحية استلام بضاعة المرتجع بالمخزن.", perm_codename='inventory:transfers/approve')
            SalesReturnOrderService.deliver_return_order(return_order, request.user)
            messages.success(request, f"تم استلام بضاعة المرتجع بالمخزن وتوليد إذن الإضافة المخزني بنجاح.")

        elif action == 'settle':
            role_name = getattr(request.user.role, 'name', '') if hasattr(request.user, 'role') and request.user.role else ''
            if not (has_perm_or_admin(request.user, 'sales:orders/manage') or role_name in ['superadmin', 'accountant']):
                return render_forbidden_response(request, "ليس لديك صلاحية ترحيل إشعار دائن المرتجع بالحسابات.", perm_codename='sales:orders/manage')
            SalesReturnOrderService.settle_return_order(return_order, request.user)
            messages.success(request, f"تم ترحيل إشعار الدائن للحسابات وتخفيض مديونية العميل {return_order.customer.name} بنجاح.")

        elif action == 'cancel':
            can_cancel = (has_perm_or_admin(request.user, 'sales:returns/delete') or return_order.created_by_id == request.user.id)
            if not can_cancel:
                return render_forbidden_response(request, "ليس لديك صلاحية إلغاء هذا المرتجع.", perm_codename='sales:returns/delete')
            reason = request.POST.get('rejection_reason', '') or request.POST.get('reason', 'إلغاء يدوي')
            SalesReturnOrderService.cancel_return_order(return_order, request.user, reason=reason)
            messages.warning(request, f"تم إلغاء مرتجع المبيعات {return_order.order_number}.")

        else:
            messages.error(request, "إجراء غير معروف.")
    except ValidationError as e:
        messages.error(request, str(e.message if hasattr(e, 'message') else e))

    return redirect('sales_return_order_detail', pk=pk)


@require_permission('sales:returns/export')
def sales_return_orders_export(request):
    status_filter = request.GET.get('status', 'all')
    customer_filter = request.GET.get('customer')
    search = request.GET.get('search', '').strip()

    qs = SalesReturnOrder.objects.select_related('customer', 'customer__area', 'sales_order', 'target_warehouse', 'created_by').order_by('-serial_num')
    qs = get_scoped_queryset(qs, request.user, 'salesreturnorder')

    if status_filter != 'all':
        qs = qs.filter(status=status_filter)
    if customer_filter:
        qs = qs.filter(customer_id=customer_filter)
    if search:
        qs = filter_by_arabic_search(qs, search, ['order_number', 'serial_num', 'customer__name', 'sales_order__order_number'])

    columns = [
        {'header': 'رقم المرتجع', 'key': 'order_number', 'width': 18, 'align': 'center'},
        {'header': 'أمر البيع الأصلي', 'key': lambda r: r.sales_order.order_number if r.sales_order else '-', 'width': 18, 'align': 'center'},
        {'header': 'العميل', 'key': lambda r: r.customer.name, 'width': 35, 'align': 'right'},
        {'header': 'مخزن الاستلام', 'key': lambda r: r.target_warehouse.name if r.target_warehouse else '-', 'width': 22, 'align': 'right'},
        {'header': 'تاريخ المرتجع', 'key': lambda r: r.order_date.strftime('%Y-%m-%d') if r.order_date else '', 'width': 16, 'align': 'center'},
        {'header': 'الحالة', 'key': lambda r: r.status_display_ar, 'width': 20, 'align': 'center'},
        {'header': 'عدد الأصناف', 'key': 'items_count', 'width': 14, 'align': 'center'},
        {'header': 'إجمالي المرتجع (ج.م)', 'key': lambda r: float(r.grand_total) if r.grand_total is not None else 0.0, 'format': '#,##0.00', 'width': 18, 'align': 'right'},
        {'header': 'المنشئ', 'key': lambda r: r.created_by.get_full_name() or r.created_by.username if r.created_by else '', 'width': 22, 'align': 'right'},
        {'header': 'ملاحظات', 'key': lambda r: r.notes or '', 'width': 30, 'align': 'right'},
    ]

    return export_to_excel_response(qs, columns, filename="sales_returns_export", sheet_title="مرتجعات المبيعات")


@require_permission('sales:returns/view')
def sales_return_order_print(request, pk):
    return_order = get_object_or_404(
        SalesReturnOrder.objects.select_related(
            'customer', 'customer__area', 'sales_order', 'target_warehouse', 'created_by', 'approved_by'
        ).prefetch_related('items__product', 'items__original_item'),
        pk=pk
    )
    if not can_user_access_object(request.user, return_order, 'view'):
        return render_forbidden_response(request, "غير مصرح لك بطباعة هذا المرتجع خارج نطاقك الجغرافي.")
    return render(request, 'sales/sales_return_order_print.html', {'return_order': return_order})


@login_required
def sales_eligible_orders_api(request):
    search = request.GET.get('q', '').strip()
    customer_id = request.GET.get('customer_id')

    qs = SalesOrder.objects.filter(status__in=['delivered', 'invoiced']).select_related('customer', 'source_warehouse')
    qs = get_scoped_queryset(qs, request.user, 'salesorder')

    if customer_id:
        qs = qs.filter(customer_id=customer_id)

    if search:
        qs = filter_by_arabic_search(qs, search, ['order_number', 'customer__name'])

    results = []
    for order in qs[:30]:
        results.append({
            'id': order.id,
            'order_number': order.order_number,
            'customer_name': order.customer.name,
            'customer_id': order.customer_id,
            'warehouse_id': order.source_warehouse_id,
            'warehouse_name': order.source_warehouse.name if order.source_warehouse else '',
            'order_date': str(order.order_date),
            'grand_total': str(order.grand_total),
        })
    return JsonResponse({'orders': results})


@login_required
def sales_order_return_details_api(request, order_id):
    order = get_object_or_404(SalesOrder.objects.select_related('customer', 'source_warehouse'), id=order_id)
    if not can_user_access_object(request.user, order, 'view'):
        return JsonResponse({'error': 'غير مصرح لك بعرض تفاصيل هذا الطلب.'}, status=403)

    items_data = []
    for itm in order.items.select_related('product').all():
        ret_sum = SalesReturnOrderItem.objects.filter(
            order__sales_order=order,
            original_item=itm
        ).exclude(order__status__in=['cancelled', 'rejected']).aggregate(s=Sum('quantity'))['s'] or Decimal('0.00')
        rem_qty = max(Decimal('0.00'), itm.quantity - ret_sum)
        items_data.append({
            'item_id': itm.id,
            'product_id': itm.product_id,
            'product_name': itm.product.name,
            'product_code': itm.product.code,
            'unit_price': str(itm.unit_price),
            'discount_percentage': str(itm.discount_percentage),
            'tax_percentage': str(itm.tax_percentage),
            'original_quantity': str(itm.quantity),
            'returned_so_far': str(ret_sum),
            'remaining_returnable': str(rem_qty),
            'batch_number': itm.batch_number or '',
            'expiry_date': str(itm.expiry_date) if itm.expiry_date else '',
        })

    return JsonResponse({
        'order_id': order.id,
        'order_number': order.order_number,
        'customer_name': order.customer.name,
        'customer_id': order.customer_id,
        'warehouse_id': order.source_warehouse_id,
        'warehouse_name': order.source_warehouse.name if order.source_warehouse else '',
        'items': items_data
    })


@require_permission([
    'sales:orders/list',
    'sales:orders/create',
    'sales:orders/edit',
    'sales:collections/list',
    'sales:collections/create',
    'sales:returns/list',
    'sales:customers/transactions',
    'sales:customers/accounting',
])
def sales_customers_search_api(request):
    """Scoped Arabic-normalized smart-search API for Sales customer selectors."""
    q = (request.GET.get('q') or request.GET.get('search') or '').strip()
    limit = parse_search_limit(request)

    qs = ScopeResolutionService.get_scoped_choices(request.user, 'customers', 'sales')
    if q:
        qs = filter_by_arabic_search(
            qs,
            ['name', 'area__name', 'brick__name'],
            q,
            raw_fields=['code', 'mobile', 'serial_num'],
            numeric_id_field='serial_num',
        )

    results = [serialize_contact_option(c) for c in qs[:limit]]
    return JsonResponse({'results': results, 'count': len(results)})


@require_permission([
    'sales:orders/list',
    'sales:orders/create',
    'sales:orders/edit',
    'sales:returns/create',
])
def sales_warehouses_search_api(request):
    """Scoped smart-search API for Sales warehouse selectors."""
    q = (request.GET.get('q') or request.GET.get('search') or '').strip()
    limit = parse_search_limit(request)

    qs = ScopeResolutionService.get_scoped_choices(request.user, 'warehouses', 'sales')
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
    'sales:collections/list',
    'sales:collections/create',
])
def sales_vaults_search_api(request):
    """Scoped smart-search API for Sales vault selectors."""
    q = (request.GET.get('q') or request.GET.get('search') or '').strip()
    limit = parse_search_limit(request)

    qs = ScopeResolutionService.get_scoped_choices(request.user, 'vaults', 'sales')
    if q:
        qs = filter_by_arabic_search(
            qs,
            ['name', 'assigned_user__name'],
            q,
            raw_fields=['serial_num', 'assigned_user__username'],
            numeric_id_field='serial_num',
        )

    results = [serialize_vault_option(v) for v in qs[:limit]]
    return JsonResponse({'results': results, 'count': len(results)})



