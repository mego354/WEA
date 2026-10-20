from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q
from django.core.exceptions import ValidationError

from django.core.paginator import Paginator
from master_data.pagination_utils import paginate_queryset
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

    qs = SalesOrder.objects.select_related('customer', 'customer__area', 'source_warehouse', 'created_by').all().order_by('-order_date', '-id')

    active_filters = []

    if status_filter != 'all':
        qs = qs.filter(status=status_filter)
        status_labels = dict(SalesOrder.STATUS_CHOICES)
        active_filters.append({'label': f'الحالة: {status_labels.get(status_filter, status_filter)}', 'param': 'status'})

    if customer_filter:
        qs = qs.filter(customer_id=customer_filter)
        c_obj = Contact.objects.filter(id=customer_filter).first()
        active_filters.append({'label': f'العميل: {c_obj.name if c_obj else customer_filter}', 'param': 'customer'})

    if search:
        qs = qs.filter(
            Q(order_number__icontains=search) |
            Q(serial_num__icontains=search) |
            Q(customer__name__icontains=search)
        )
        active_filters.append({'label': f'بحث: {search}', 'param': 'search'})

    paginator, page_obj = paginate_queryset(request, qs, default_per_page=25, max_per_page=100)

    # Scoped customer filter options (top 50 active)
    customers = Contact.objects.filter(is_customer=True).order_by('name')[:50]

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
    search = request.GET.get('search', '').strip()
    customer_id = request.GET.get('customer')
    vault_id = request.GET.get('vault')

    qs = Collection.objects.select_related('customer', 'vault', 'created_by').order_by('-serial_num')

    active_filters = []

    if customer_id:
        qs = qs.filter(customer_id=customer_id)
        c_obj = Contact.objects.filter(id=customer_id).first()
        active_filters.append({'label': f'العميل: {c_obj.name if c_obj else customer_id}', 'param': 'customer'})

    if vault_id:
        qs = qs.filter(vault_id=vault_id)
        v_obj = Vault.objects.filter(id=vault_id).first()
        active_filters.append({'label': f'الخزنة: {v_obj.name if v_obj else vault_id}', 'param': 'vault'})

    if search:
        qs = qs.filter(
            Q(serial_num__icontains=search) |
            Q(customer__name__icontains=search) |
            Q(notes__icontains=search)
        )
        active_filters.append({'label': f'بحث: {search}', 'param': 'search'})

    customers = Contact.objects.filter(is_customer=True).order_by('name')[:50]
    vaults = Vault.objects.filter(is_active=True).order_by('name')

    paginator, page_obj = paginate_queryset(request, qs, default_per_page=25, max_per_page=100)

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
    }
    return render(request, 'sales/collections_list.html', context)


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
    search = request.GET.get('search', '').strip()
    qs = CustomerAccount.objects.select_related('customer', 'customer__area').order_by('-current_balance')

    active_filters = []
    if search:
        qs = qs.filter(
            Q(customer__name__icontains=search) |
            Q(customer__code__icontains=search)
        )
        active_filters.append({'label': f'بحث: {search}', 'param': 'search'})

    paginator, page_obj = paginate_queryset(request, qs, default_per_page=25, max_per_page=100)

    context = {
        'accounts': page_obj.object_list,
        'page_obj': page_obj,
        'paginator': paginator,
        'search_query': search,
        'active_filters': active_filters,
        'total_count': paginator.count,
    }
    return render(request, 'sales/accounting_customers_list.html', context)


@login_required
def customer_transactions_list(request):
    """
    Customer Ledger Transactions (عمليات العملاء).
    """
    customer_id = request.GET.get('customer_id')
    search = request.GET.get('search', '').strip()

    qs = CustomerTransaction.objects.select_related('account', 'account__customer', 'created_by').order_by('-serial')

    active_filters = []

    if customer_id:
        qs = qs.filter(account__customer_id=customer_id)
        c_obj = Contact.objects.filter(id=customer_id).first()
        active_filters.append({'label': f'العميل: {c_obj.name if c_obj else customer_id}', 'param': 'customer_id'})

    if search:
        qs = qs.filter(
            Q(serial__icontains=search) |
            Q(description__icontains=search) |
            Q(account__customer__name__icontains=search)
        )
        active_filters.append({'label': f'بحث: {search}', 'param': 'search'})

    customers = Contact.objects.filter(is_customer=True).order_by('name')[:50]

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
    }
    return render(request, 'sales/customer_transactions_list.html', context)


from master_data.excel_utils import export_to_excel_response


@login_required
def sales_orders_export(request):
    status_filter = request.GET.get('status', 'all')
    customer_filter = request.GET.get('customer')
    search = request.GET.get('search', '').strip()

    qs = SalesOrder.objects.select_related('customer', 'customer__area', 'source_warehouse', 'created_by').all().order_by('-serial_num')

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


@login_required
def collections_export(request):
    customer_id = request.GET.get('customer')
    qs = Collection.objects.select_related('customer', 'vault', 'created_by').order_by('-serial_num')
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
