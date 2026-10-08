from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q
from django.core.exceptions import ValidationError

from .models import SalesOrder, SalesOrderItem, CustomerAccount, CustomerTransaction, Collection
from .services import SalesOrderService, CollectionService
from contacts.models import Contact
from catalog.models import Product
from inventory.models import Warehouse
from treasury.models import Vault


@login_required
def sales_orders_list(request):
    status_filter = request.GET.get('status', 'all')
    customer_filter = request.GET.get('customer')
    search = request.GET.get('search', '').strip()

    qs = SalesOrder.objects.select_related('customer', 'customer__area', 'source_warehouse', 'created_by').all()

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

    customers = Contact.objects.filter(is_customer=True)

    context = {
        'orders': qs,
        'current_status': status_filter,
        'selected_customer': customer_filter,
        'search_query': search,
        'customers': customers,
        'total_count': qs.count(),
    }
    return render(request, 'sales/sales_orders_list.html', context)


@login_required
def sales_order_create(request):
    if request.method == 'POST':
        customer_id = request.POST.get('customer')
        warehouse_id = request.POST.get('warehouse')
        order_date = request.POST.get('order_date')
        delivery_date = request.POST.get('delivery_date') or None
        notes = request.POST.get('notes', '').strip()

        # Parse item rows
        product_ids = request.POST.getlist('product_id[]')
        quantities = request.POST.getlist('quantity[]')
        unit_prices = request.POST.getlist('unit_price[]')

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

            items_data.append({
                'product': prod,
                'quantity': qty,
                'unit_price': price,
            })

        if not customer_id or not warehouse_id:
            messages.error(request, "يرجى تحديد العميل والمخزن.")
            return redirect('sales_order_create')

        customer = get_object_or_404(Contact, id=customer_id)
        warehouse = get_object_or_404(Warehouse, id=warehouse_id)

        try:
            order = SalesOrderService.create_order(
                customer=customer,
                source_warehouse=warehouse,
                order_date=order_date,
                items_data=items_data,
                user=request.user,
                delivery_date=delivery_date,
                notes=notes
            )
            messages.success(request, f"تم إنشاء أمر البيع بنجاح ({order.order_number}) بإجمالي {order.grand_total:,.2f} ج.م.")
            return redirect('sales_order_detail', pk=order.pk)
        except ValidationError as e:
            messages.error(request, str(e.message if hasattr(e, 'message') else e))
            return redirect('sales_order_create')

    customers = Contact.objects.filter(is_customer=True)
    warehouses = Warehouse.objects.filter(is_active=True)
    products = Product.objects.filter(is_active=True)

    context = {
        'customers': customers,
        'warehouses': warehouses,
        'products': products,
    }
    return render(request, 'sales/sales_order_create.html', context)


@login_required
def sales_order_detail(request, pk):
    order = get_object_or_404(
        SalesOrder.objects.select_related(
            'customer', 'customer__area', 'source_warehouse', 'created_by', 'memo'
        ).prefetch_related('items__product'),
        pk=pk
    )
    return render(request, 'sales/sales_order_detail.html', {'order': order})


@login_required
def sales_order_action(request, pk, action):
    order = get_object_or_404(SalesOrder, pk=pk)

    try:
        if action == 'approve':
            SalesOrderService.approve_order(order, request.user)
            messages.success(request, f"تم اعتماد أمر البيع {order.order_number} بنجاح.")
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
        messages.error(request, str(e.message if hasattr(e, 'message') else e))

    return redirect('sales_order_detail', pk=order.pk)


@login_required
def collections_list(request):
    collections = Collection.objects.select_related('customer', 'vault', 'created_by').order_by('-serial_num')
    return render(request, 'sales/collections_list.html', {'collections': collections})


@login_required
def collection_create(request):
    if request.method == 'POST':
        customer_id = request.POST.get('customer')
        vault_id = request.POST.get('vault')
        amount = request.POST.get('amount')
        payment_method = request.POST.get('payment_method', 'cash')
        notes = request.POST.get('notes', '').strip()

        if not customer_id or not vault_id or not amount:
            messages.error(request, "يرجى ملء جميع الحقول المطلوبة (العميل، الخزنة، والمبلغ).")
            return redirect('collection_create')

        customer = get_object_or_404(Contact, id=customer_id)
        vault = get_object_or_404(Vault, id=vault_id)

        try:
            col = CollectionService.record_collection(
                customer=customer,
                vault=vault,
                amount=Decimal(amount),
                user=request.user,
                payment_method=payment_method,
                notes=notes
            )
            messages.success(request, f"تم تسجيل سند التحصيل #{col.serial_num} بنجاح بمبلغ {col.amount:,.2f} ج.م من العميل {customer.name}.")
            return redirect('collections_list')
        except ValidationError as e:
            messages.error(request, str(e.message if hasattr(e, 'message') else e))
            return redirect('collection_create')

    customers = Contact.objects.filter(is_customer=True)
    vaults = Vault.objects.filter(is_active=True)
    initial_customer = request.GET.get('customer_id')

    context = {
        'customers': customers,
        'vaults': vaults,
        'selected_customer_id': initial_customer,
    }
    return render(request, 'sales/collection_create.html', context)


@login_required
def accounting_customers_list(request):
    """
    Customer Statements & Balances (حسابات العملاء).
    """
    accounts = CustomerAccount.objects.select_related('customer', 'customer__area').order_by('-current_balance')
    return render(request, 'sales/accounting_customers_list.html', {'accounts': accounts})


@login_required
def customer_transactions_list(request):
    """
    Customer Ledger Transactions (عمليات العملاء).
    """
    customer_id = request.GET.get('customer_id')
    qs = CustomerTransaction.objects.select_related('account', 'account__customer', 'created_by').order_by('-serial')

    if customer_id:
        qs = qs.filter(account__customer_id=customer_id)

    customers = Contact.objects.filter(is_customer=True)

    context = {
        'transactions': qs,
        'customers': customers,
        'selected_customer_id': customer_id,
    }
    return render(request, 'sales/customer_transactions_list.html', context)
