import csv
from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q
from django.core.paginator import Paginator
from django.core.exceptions import ValidationError
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from master_data.excel_utils import export_to_excel_response

from .models import (
    PurchaseOrder, PurchaseOrderItem, PurchaseOrderAttachment, PurchaseOrderComment,
    PurchaseReturnOrder, PurchaseReturnOrderItem
)
from .services import PurchaseOrderService, PurchaseReturnOrderService

from contacts.models import Contact, ContactAddress
from catalog.models import Product
from inventory.models import Warehouse
from treasury.models import VendorTransaction


@login_required
def purchase_orders_list(request):
    status_filter = request.GET.get('status', 'all')
    supplier_filter = request.GET.get('supplier')
    search = request.GET.get('search', '').strip()
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')

    qs = PurchaseOrder.objects.select_related(
        'supplier', 'supplier__area', 'target_warehouse', 'created_by'
    ).all().order_by('-serial_num')

    active_filters_count = 3  # Default 3 active filters matching reference sfql

    if status_filter != 'all':
        qs = qs.filter(status=status_filter)
        active_filters_count += 1

    if supplier_filter:
        qs = qs.filter(supplier_id=supplier_filter)
        active_filters_count += 1

    if date_from:
        qs = qs.filter(order_date__gte=date_from)
        active_filters_count += 1

    if date_to:
        qs = qs.filter(order_date__lte=date_to)
        active_filters_count += 1

    if search:
        qs = qs.filter(
            Q(order_number__icontains=search) |
            Q(serial_num__icontains=search) |
            Q(supplier__name__icontains=search) |
            Q(supplier__area__name__icontains=search)
        )

    suppliers = Contact.objects.filter(is_supplier=True).order_by('name')

    # Pagination: 40 per page matching reference ERP
    page_size = int(request.GET.get('page_size', 40))
    paginator = Paginator(qs, page_size)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    context = {
        'orders': page_obj.object_list,
        'page_obj': page_obj,
        'paginator': paginator,
        'current_status': status_filter,
        'selected_supplier': supplier_filter,
        'search_query': search,
        'date_from': date_from,
        'date_to': date_to,
        'suppliers': suppliers,
        'active_filters_count': active_filters_count,
        'total_count': qs.count(),
    }
    return render(request, 'purchases/purchase_orders_list.html', context)


@login_required
def purchase_order_create(request):
    if request.method == 'POST':
        supplier_id = request.POST.get('supplier')
        warehouse_id = request.POST.get('warehouse')
        order_date = request.POST.get('order_date') or timezone.now().date()
        expected_delivery_date = request.POST.get('expected_delivery_date') or None
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
            qty = Decimal(quantities[i] or '1')
            price = Decimal(unit_prices[i] or '0')
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
        warehouse = get_object_or_404(Warehouse, id=warehouse_id)

        try:
            order = PurchaseOrderService.create_order(
                supplier=supplier,
                target_warehouse=warehouse,
                order_date=order_date,
                expected_delivery_date=expected_delivery_date,
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

            messages.success(request, f"تم إنشاء أمر الشراء بنجاح ({order.order_number}) بإجمالي {order.grand_total:,.2f} ج.م.")
            return redirect('purchase_order_detail', pk=order.pk)
        except ValidationError as e:
            messages.error(request, str(e.message if hasattr(e, 'message') else e))
            return redirect('purchase_order_create')

    suppliers = Contact.objects.filter(is_supplier=True).order_by('name')
    warehouses = Warehouse.objects.filter(is_active=True).order_by('name')
    products = Product.objects.filter(is_active=True).order_by('name')

    context = {
        'suppliers': suppliers,
        'warehouses': warehouses,
        'products': products,
    }
    return render(request, 'purchases/purchase_order_create.html', context)


@login_required
def purchase_order_detail(request, pk):
    order = get_object_or_404(
        PurchaseOrder.objects.select_related(
            'supplier', 'supplier__area', 'target_warehouse', 'created_by', 'memo', 'memo__warehouse'
        ).prefetch_related('items__product', 'attachments', 'comments__author'),
        pk=pk
    )

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

    context = {
        'order': order,
        'linked_tx': linked_tx,
        'total_debit': total_debit,
        'total_credit': total_credit,
        'current_vendor_balance': current_vendor_balance,
        'status_choices': PurchaseOrder.STATUS_CHOICES,
    }
    return render(request, 'purchases/purchase_order_detail.html', context)


@login_required
def purchase_order_update_status_ajax(request, pk):
    order = get_object_or_404(PurchaseOrder, pk=pk)
    if request.method == 'POST':
        new_status = request.POST.get('status', '').strip().lower()
        valid_statuses = dict(PurchaseOrder.STATUS_CHOICES).keys()
        if new_status in valid_statuses:
            try:
                if new_status == 'approved' and order.status == 'pending':
                    PurchaseOrderService.approve_order(order, request.user)
                elif new_status == 'picked' and order.status in ['pending', 'approved']:
                    if order.status == 'pending':
                        PurchaseOrderService.approve_order(order, request.user)
                    PurchaseOrderService.stock_order(order, request.user)
                elif new_status == 'settled' and order.status != 'settled':
                    if order.status in ['pending', 'approved']:
                        if order.status == 'pending':
                            PurchaseOrderService.approve_order(order, request.user)
                        PurchaseOrderService.stock_order(order, request.user)
                    PurchaseOrderService.invoice_order(order, request.user)
                elif new_status == 'cancelled':
                    PurchaseOrderService.cancel_order(order, request.user)
                else:
                    order.status = new_status
                    order.save(update_fields=['status'])

                messages.success(request, f"تم تغيير حالة أمر الشراء إلى {order.status_label_ar}.")
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({'status': 'ok', 'new_status': order.status, 'label': order.status_label_en})
            except ValidationError as e:
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({'status': 'error', 'message': str(e.message if hasattr(e, 'message') else e)}, status=400)
                messages.error(request, str(e.message if hasattr(e, 'message') else e))

    return redirect('purchase_order_detail', pk=pk)


@login_required
def purchase_order_add_comment(request, pk):
    order = get_object_or_404(PurchaseOrder, pk=pk)
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


@login_required
def purchase_order_upload_attachment(request, pk):
    order = get_object_or_404(PurchaseOrder, pk=pk)
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
    order = get_object_or_404(PurchaseOrder, pk=pk)

    try:
        if action == 'approve':
            PurchaseOrderService.approve_order(order, request.user)
            messages.success(request, f"تم اعتماد أمر الشراء {order.order_number} بنجاح.")
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
        messages.error(request, str(e.message if hasattr(e, 'message') else e))

    return redirect('purchase_order_detail', pk=order.pk)


@login_required
def purchase_order_print(request, pk):
    order = get_object_or_404(
        PurchaseOrder.objects.select_related('supplier', 'supplier__area', 'target_warehouse', 'created_by').prefetch_related('items__product'),
        pk=pk
    )
    return render(request, 'purchases/purchase_order_print.html', {'order': order})


@login_required
def purchase_orders_export(request):
    status_filter = request.GET.get('status', 'all')
    supplier_filter = request.GET.get('supplier')
    search = request.GET.get('search', '').strip()

    qs = PurchaseOrder.objects.select_related(
        'supplier', 'supplier__area', 'target_warehouse', 'created_by'
    ).all().order_by('-serial_num')

    if status_filter != 'all':
        qs = qs.filter(status=status_filter)
    if supplier_filter:
        qs = qs.filter(supplier_id=supplier_filter)
    if search:
        qs = qs.filter(
            Q(order_number__icontains=search) |
            Q(supplier__name__icontains=search)
        )

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

    return export_to_excel_response(qs, columns, filename="purchase_orders_export", sheet_title="طلبات الشراء")


@login_required
def purchase_order_split(request, pk):
    order = get_object_or_404(PurchaseOrder, pk=pk)
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


@login_required
def purchase_return_orders_list(request):
    """View matching /purchase-return-orders in reference ERP."""
    status_filter = request.GET.get('status', 'all')
    supplier_filter = request.GET.get('supplier')
    search = request.GET.get('search', '').strip()
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')

    qs = PurchaseReturnOrder.objects.select_related(
        'supplier', 'supplier__area', 'warehouse', 'created_by'
    ).all().order_by('-serial_num')

    active_filters_count = 0

    if status_filter != 'all':
        qs = qs.filter(status=status_filter)
        active_filters_count += 1

    if supplier_filter:
        qs = qs.filter(supplier_id=supplier_filter)
        active_filters_count += 1

    if date_from:
        qs = qs.filter(order_date__gte=date_from)
        active_filters_count += 1

    if date_to:
        qs = qs.filter(order_date__lte=date_to)
        active_filters_count += 1

    if search:
        qs = qs.filter(
            Q(order_number__icontains=search) |
            Q(serial_num__icontains=search) |
            Q(supplier__name__icontains=search)
        )

    suppliers = Contact.objects.filter(is_supplier=True).order_by('name')

    page_size = int(request.GET.get('page_size', 40))
    paginator = Paginator(qs, page_size)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    context = {
        'returns': page_obj.object_list,
        'page_obj': page_obj,
        'paginator': paginator,
        'current_status': status_filter,
        'selected_supplier': supplier_filter,
        'search_query': search,
        'date_from': date_from,
        'date_to': date_to,
        'suppliers': suppliers,
        'active_filters_count': active_filters_count,
        'total_count': qs.count(),
    }
    return render(request, 'purchases/purchase_return_orders.html', context)


@login_required
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
            qty = Decimal(quantities[i] or '1')
            price = Decimal(unit_prices[i] or '0')
            batch = batch_numbers[i] if i < len(batch_numbers) else ''
            exp = expiry_dates[i] if (i < len(expiry_dates) and expiry_dates[i]) else None

            items_data.append({
                'product': prod,
                'quantity': qty,
                'unit_price': price,
                'batch_number': batch,
                'expiry_date': exp,
            })

        if not supplier_id or not warehouse_id:
            messages.error(request, "يرجى تحديد المورد والمخزن المنصرف منه.")
            return redirect('purchase_return_order_create')

        supplier = get_object_or_404(Contact, id=supplier_id)
        warehouse = get_object_or_404(Warehouse, id=warehouse_id)
        po = PurchaseOrder.objects.filter(id=po_id).first() if po_id else None

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
            messages.success(request, f"تم إنشاء أمر إرجاع المشتريات {return_order.order_number} بنجاح.")
            return redirect('purchase_return_order_detail', pk=return_order.pk)
        except ValidationError as e:
            messages.error(request, str(e.message if hasattr(e, 'message') else e))
            return redirect('purchase_return_order_create')

    suppliers = Contact.objects.filter(is_supplier=True).order_by('name')
    warehouses = Warehouse.objects.filter(is_active=True).order_by('name')
    products = Product.objects.filter(is_active=True).order_by('name')
    po_id = request.GET.get('po')
    selected_po = PurchaseOrder.objects.filter(id=po_id).first() if po_id else None

    context = {
        'suppliers': suppliers,
        'warehouses': warehouses,
        'products': products,
        'selected_po': selected_po,
    }
    return render(request, 'purchases/purchase_return_order_create.html', context)


@login_required
def purchase_return_order_detail(request, pk):
    return_order = get_object_or_404(
        PurchaseReturnOrder.objects.select_related(
            'supplier', 'supplier__area', 'warehouse', 'created_by', 'memo', 'purchase_order'
        ).prefetch_related('items__product'),
        pk=pk
    )

    # Linked debit transaction if settled
    linked_tx = VendorTransaction.objects.filter(
        account__supplier=return_order.supplier,
        reason='purchase_return',
        debit=return_order.grand_total
    ).first()

    context = {
        'return_order': return_order,
        'linked_tx': linked_tx,
        'status_choices': PurchaseReturnOrder.STATUS_CHOICES,
    }
    return render(request, 'purchases/purchase_return_order_detail.html', context)


@login_required
def purchase_return_order_action(request, pk, action):
    return_order = get_object_or_404(PurchaseReturnOrder, pk=pk)

    try:
        if action == 'approve':
            PurchaseReturnOrderService.approve_return_order(return_order, request.user)
            messages.success(request, f"تم اعتماد أمر الإرجاع {return_order.order_number} بنجاح.")
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


@login_required
def purchase_return_order_print(request, pk):
    return_order = get_object_or_404(
        PurchaseReturnOrder.objects.select_related('supplier', 'supplier__area', 'warehouse', 'created_by').prefetch_related('items__product'),
        pk=pk
    )
    return render(request, 'purchases/purchase_return_order_print.html', {'return_order': return_order})


@login_required
def purchase_return_orders_export(request):
    status_filter = request.GET.get('status', 'all')
    supplier_filter = request.GET.get('supplier')
    search = request.GET.get('search', '').strip()

    qs = PurchaseReturnOrder.objects.select_related(
        'supplier', 'supplier__area', 'warehouse', 'created_by'
    ).all().order_by('-serial_num')

    if status_filter != 'all':
        qs = qs.filter(status=status_filter)
    if supplier_filter:
        qs = qs.filter(supplier_id=supplier_filter)
    if search:
        qs = qs.filter(
            Q(order_number__icontains=search) |
            Q(supplier__name__icontains=search)
        )

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

    return export_to_excel_response(qs, columns, filename="purchase_returns_export", sheet_title="مرتجعات الشراء")

