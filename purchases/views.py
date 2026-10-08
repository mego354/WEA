from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q
from django.core.exceptions import ValidationError
from django.http import HttpResponse

from .models import PurchaseOrder, PurchaseOrderItem
from .services import PurchaseOrderService
from contacts.models import Contact
from catalog.models import Product
from inventory.models import Warehouse
from treasury.models import VendorTransaction


@login_required
def purchase_orders_list(request):
    status_filter = request.GET.get('status', 'all')
    supplier_filter = request.GET.get('supplier')
    search = request.GET.get('search', '').strip()

    qs = PurchaseOrder.objects.select_related('supplier', 'supplier__area', 'target_warehouse', 'created_by').all()

    if status_filter != 'all':
        qs = qs.filter(status=status_filter)

    if supplier_filter:
        qs = qs.filter(supplier_id=supplier_filter)

    if search:
        qs = qs.filter(
            Q(order_number__icontains=search) |
            Q(serial_num__icontains=search) |
            Q(supplier__name__icontains=search) |
            Q(supplier__area__name__icontains=search)
        )

    suppliers = Contact.objects.filter(is_supplier=True)

    context = {
        'orders': qs,
        'current_status': status_filter,
        'selected_supplier': supplier_filter,
        'search_query': search,
        'suppliers': suppliers,
        'total_count': qs.count(),
    }
    return render(request, 'purchases/purchase_orders_list.html', context)


@login_required
def purchase_order_create(request):
    if request.method == 'POST':
        supplier_id = request.POST.get('supplier')
        warehouse_id = request.POST.get('warehouse')
        order_date = request.POST.get('order_date')
        expected_delivery_date = request.POST.get('expected_delivery_date') or None
        custom_discount_percentage = request.POST.get('custom_discount_percentage') or '0.00'
        shipping_fees = request.POST.get('shipping_fees') or '0.00'
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
            messages.success(request, f"تم إنشاء أمر الشراء بنجاح ({order.order_number}) بإجمالي {order.grand_total:,.2f} ج.م.")
            return redirect('purchase_order_detail', pk=order.pk)
        except ValidationError as e:
            messages.error(request, str(e.message if hasattr(e, 'message') else e))
            return redirect('purchase_order_create')

    suppliers = Contact.objects.filter(is_supplier=True)
    warehouses = Warehouse.objects.filter(is_active=True)
    products = Product.objects.filter(is_active=True)

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
        ).prefetch_related('items__product', 'attachments'),
        pk=pk
    )

    # Linked accounting transactions
    linked_tx = VendorTransaction.objects.filter(purchase_order=order).prefetch_related('installments__settlements').first()

    context = {
        'order': order,
        'linked_tx': linked_tx,
    }
    return render(request, 'purchases/purchase_order_detail.html', context)


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
