from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from django.contrib import messages
from django.db.models import Q, Sum, Count
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.utils import timezone

from .models import Vault, VendorAccount, VendorTransaction, VendorPayment, VaultTransaction
from .services import TreasuryService
from contacts.models import Contact
from purchases.models import PurchaseOrder
from master_data.excel_utils import export_to_excel_response
from master_data.pagination_utils import paginate_queryset
from accounts.permissions import (
    require_permission,
    get_scoped_queryset,
    can_user_access_object,
    render_forbidden_response,
    has_perm_or_admin,
)

User = get_user_model()


@require_permission('treasury:payments/list')
def vendor_payments_list(request):
    search = request.GET.get('search', '').strip()
    supplier_id = request.GET.get('supplier')
    vault_id = request.GET.get('vault')
    payment_method = request.GET.get('payment_method')

    qs = VendorPayment.objects.select_related('supplier', 'vault', 'created_by', 'purchase_order').order_by('-serial_num')
    qs = get_scoped_queryset(qs, request.user, 'vendorpayment')

    # Dedicated, real scoped statistics cards calculations (calculated before page-specific filter narrowing)
    scoped_all = get_scoped_queryset(VendorPayment.objects.all(), request.user, 'vendorpayment')
    now = timezone.now()
    stats = {
        'total_count': scoped_all.count(),
        'total_amount': scoped_all.aggregate(total=Sum('amount'))['total'] or Decimal('0.00'),
        'month_amount': scoped_all.filter(payment_date__year=now.year, payment_date__month=now.month).aggregate(total=Sum('amount'))['total'] or Decimal('0.00'),
        'cash_amount': scoped_all.filter(payment_method='cash').aggregate(total=Sum('amount'))['total'] or Decimal('0.00'),
        'bank_amount': scoped_all.filter(payment_method__in=['cheque', 'bank_transfer']).aggregate(total=Sum('amount'))['total'] or Decimal('0.00'),
    }

    active_filters = []

    if supplier_id:
        qs = qs.filter(supplier_id=supplier_id)
        s_obj = Contact.objects.filter(id=supplier_id).first()
        active_filters.append({'label': f'المورد: {s_obj.name if s_obj else supplier_id}', 'param': 'supplier'})

    if vault_id:
        qs = qs.filter(vault_id=vault_id)
        v_obj = Vault.objects.filter(id=vault_id).first()
        active_filters.append({'label': f'الخزنة: {v_obj.name if v_obj else vault_id}', 'param': 'vault'})

    if payment_method:
        qs = qs.filter(payment_method=payment_method)
        method_labels = dict(VendorPayment.PAYMENT_METHODS)
        active_filters.append({'label': f'طريقة الدفع: {method_labels.get(payment_method, payment_method)}', 'param': 'payment_method'})

    if search:
        qs = qs.filter(
            Q(serial_num__icontains=search) |
            Q(supplier__name__icontains=search) |
            Q(reference_number__icontains=search) |
            Q(notes__icontains=search)
        )
        active_filters.append({'label': f'بحث: {search}', 'param': 'search'})

    suppliers = get_scoped_queryset(Contact.objects.filter(is_supplier=True), request.user, 'contact').order_by('name')
    vaults = get_scoped_queryset(Vault.objects.filter(is_active=True), request.user, 'vault').order_by('name')

    paginator, page_obj = paginate_queryset(request, qs, default_per_page=25, max_per_page=100)

    context = {
        'payments': page_obj.object_list,
        'page_obj': page_obj,
        'paginator': paginator,
        'suppliers': suppliers,
        'vaults': vaults,
        'search_query': search,
        'selected_supplier_id': supplier_id,
        'selected_vault_id': vault_id,
        'selected_payment_method': payment_method,
        'active_filters': active_filters,
        'total_count': paginator.count,
        'stats': stats,
    }
    return render(request, 'treasury/vendor_payments_list.html', context)


@require_permission('treasury:payments/export')
def vendor_payments_export(request):
    supplier_id = request.GET.get('supplier')
    qs = VendorPayment.objects.select_related('supplier', 'vault', 'created_by', 'purchase_order').order_by('-serial_num')
    qs = get_scoped_queryset(qs, request.user, 'vendorpayment')
    if supplier_id:
        qs = qs.filter(supplier_id=supplier_id)

    columns = [
        {'header': 'رقم سند الصرف', 'key': lambda p: f"#{p.serial_num}", 'width': 16, 'align': 'center'},
        {'header': 'أمر الشراء المرتبط', 'key': lambda p: p.purchase_order.order_number if p.purchase_order else '—', 'width': 18, 'align': 'center'},
        {'header': 'المورد', 'key': lambda p: p.supplier.name, 'width': 35, 'align': 'right'},
        {'header': 'الخزنة / الحساب', 'key': lambda p: p.vault.name, 'width': 25, 'align': 'right'},
        {'header': 'المبلغ المدفوع', 'key': lambda p: float(p.amount) if p.amount is not None else 0.0, 'format': '#,##0.00', 'width': 18, 'align': 'right'},
        {'header': 'طريقة السداد', 'key': lambda p: p.get_payment_method_display(), 'width': 16, 'align': 'center'},
        {'header': 'رقم الشيك / المرجع', 'key': lambda p: p.reference_number or '', 'width': 20, 'align': 'center'},
        {'header': 'تاريخ وساعة الصرف', 'key': lambda p: p.created_at.strftime('%Y-%m-%d %H:%M') if p.created_at else '', 'width': 20, 'align': 'center'},
        {'header': 'المسئول', 'key': lambda p: p.created_by.get_full_name() or p.created_by.username if p.created_by else '', 'width': 22, 'align': 'right'},
        {'header': 'ملاحظات', 'key': lambda p: p.notes or '', 'width': 30, 'align': 'right'},
    ]

    return export_to_excel_response(qs, columns, filename="vendor_payments_export", sheet_title="مدفوعات الموردين")


@require_permission('treasury:payments/create')
def vendor_payment_create(request):
    if request.method == 'POST':
        supplier_id = request.POST.get('supplier')
        vault_id = request.POST.get('vault')
        amount = request.POST.get('amount')
        purchase_order_id = request.POST.get('purchase_order')
        payment_date = request.POST.get('payment_date') or None
        payment_method = request.POST.get('payment_method', 'cash')
        reference_number = request.POST.get('reference_number', '').strip()
        notes = request.POST.get('notes', '').strip()

        if not supplier_id or not vault_id or not amount:
            messages.error(request, "يرجى ملء جميع الحقول المطلوبة (المورد، الخزنة، والمبلغ).")
            return redirect('vendor_payment_create')

        supplier = get_object_or_404(Contact, id=supplier_id)
        vault = get_object_or_404(Vault, id=vault_id)

        if not can_user_access_object(request.user, supplier, 'view'):
            return render_forbidden_response(request, "لا يمكنك تسجيل سداد لمورد خارج نطاقك الجغرافي أو صلاحياتك.")
        if not can_user_access_object(request.user, vault, 'withdraw'):
            return render_forbidden_response(request, "لا يمكنك الصرف من خزنة غير مخصصة لك أو بدون صلاحية صرف.")

        purchase_order = None
        if purchase_order_id:
            purchase_order = get_object_or_404(PurchaseOrder, id=purchase_order_id)
            if not can_user_access_object(request.user, purchase_order, 'view'):
                return render_forbidden_response(request, "لا يمكنك تسجيل سداد لأمر شراء خارج نطاق صلاحياتك.")

        try:
            payment = TreasuryService.record_vendor_payment(
                supplier=supplier,
                vault=vault,
                amount=Decimal(amount),
                user=request.user,
                purchase_order=purchase_order,
                payment_date=payment_date,
                payment_method=payment_method,
                reference_number=reference_number,
                notes=notes
            )
            po_info = f" لأمر الشراء {purchase_order.order_number}" if purchase_order else ""
            messages.success(request, f"تم تسجيل سند الصرف #{payment.serial_num} بنجاح بمبلغ {payment.amount:,.2f} ج.م للمورد {supplier.name}{po_info}.")
            return redirect('vendor_payments_list')
        except ValidationError as e:
            messages.error(request, str(e.message if hasattr(e, 'message') else e))
            return redirect('vendor_payment_create')

    suppliers = get_scoped_queryset(Contact.objects.filter(is_supplier=True), request.user, 'contact').order_by('name')
    vaults = get_scoped_queryset(Vault.objects.filter(is_active=True), request.user, 'vault').order_by('name')
    initial_supplier = request.GET.get('supplier_id')
    initial_order = request.GET.get('order_id')

    if initial_order and not initial_supplier:
        po_obj = PurchaseOrder.objects.filter(id=initial_order).first()
        if po_obj:
            initial_supplier = po_obj.supplier_id

    # Open purchase orders for dropdown linking
    orders_qs = PurchaseOrder.objects.exclude(status='cancelled').select_related('supplier').order_by('-order_date')
    orders_qs = get_scoped_queryset(orders_qs, request.user, 'purchaseorder')

    context = {
        'suppliers': suppliers,
        'vaults': vaults,
        'orders': orders_qs,
        'selected_supplier_id': int(initial_supplier) if initial_supplier and str(initial_supplier).isdigit() else None,
        'selected_order_id': int(initial_order) if initial_order and str(initial_order).isdigit() else None,
    }
    return render(request, 'treasury/vendor_payment_create.html', context)


@require_permission('treasury:vendors/accounting')
def accounting_vendors_list(request):
    """
    Vendor Statements & Balances (حسابات الموردين).
    """
    search = request.GET.get('search', '').strip()
    qs = VendorAccount.objects.select_related('supplier', 'supplier__area').order_by('-current_balance')
    scoped_suppliers = get_scoped_queryset(Contact.objects.filter(is_supplier=True), request.user, 'contact')
    qs = qs.filter(supplier__in=scoped_suppliers)

    # Real scoped statistics cards
    stats = {
        'total_suppliers': qs.count(),
        'total_payable': qs.aggregate(total=Sum('current_balance'))['total'] or Decimal('0.00'),
        'total_overdue': qs.aggregate(total=Sum('overdue_balance'))['total'] or Decimal('0.00'),
        'total_credit_limit': qs.aggregate(total=Sum('credit_limit'))['total'] or Decimal('0.00'),
    }

    active_filters = []
    if search:
        qs = qs.filter(
            Q(supplier__name__icontains=search) |
            Q(supplier__code__icontains=search)
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
        'stats': stats,
    }
    return render(request, 'treasury/accounting_vendors_list.html', context)


@require_permission('treasury:vendors/transactions')
def vendor_transactions_list(request):
    """
    Vendor Ledger Transactions (عمليات الموردين).
    """
    vendor_id = request.GET.get('vendor_id')
    search = request.GET.get('search', '').strip()

    qs = VendorTransaction.objects.select_related('account', 'account__supplier', 'created_by', 'purchase_order').order_by('-serial')
    scoped_suppliers = get_scoped_queryset(Contact.objects.filter(is_supplier=True), request.user, 'contact')
    qs = qs.filter(account__supplier__in=scoped_suppliers)

    # Real scoped statistics cards
    total_credit = qs.aggregate(total=Sum('credit'))['total'] or Decimal('0.00')
    total_debit = qs.aggregate(total=Sum('debit'))['total'] or Decimal('0.00')
    stats = {
        'total_count': qs.count(),
        'total_credit': total_credit,
        'total_debit': total_debit,
        'net_balance': total_credit - total_debit,
    }

    active_filters = []

    if vendor_id:
        qs = qs.filter(account__supplier_id=vendor_id)
        v_obj = Contact.objects.filter(id=vendor_id).first()
        active_filters.append({'label': f'المورد: {v_obj.name if v_obj else vendor_id}', 'param': 'vendor_id'})

    if search:
        qs = qs.filter(
            Q(serial__icontains=search) |
            Q(description__icontains=search) |
            Q(account__supplier__name__icontains=search)
        )
        active_filters.append({'label': f'بحث: {search}', 'param': 'search'})

    suppliers = scoped_suppliers.order_by('name')

    paginator, page_obj = paginate_queryset(request, qs, default_per_page=25, max_per_page=100)

    context = {
        'transactions': page_obj.object_list,
        'page_obj': page_obj,
        'paginator': paginator,
        'suppliers': suppliers,
        'selected_vendor_id': vendor_id,
        'search_query': search,
        'active_filters': active_filters,
        'total_count': paginator.count,
        'stats': stats,
    }
    return render(request, 'treasury/vendor_transactions_list.html', context)


@require_permission(['treasury:vaults/view', 'treasury:treasury/view'])
def vaults_list(request):
    """
    Vaults & Cash Safes Listing with Dedicated Scoped Statistics Cards.
    """
    search = request.GET.get('search', '').strip()
    qs = Vault.objects.select_related('assigned_user').order_by('serial_num')
    qs = get_scoped_queryset(qs, request.user, 'vault')

    # Dedicated Real Scoped Statistics Cards
    stats_qs = qs
    stats = {
        'total_vaults': stats_qs.count(),
        'active_vaults': stats_qs.filter(is_active=True).count(),
        'total_balance': stats_qs.filter(is_active=True).aggregate(total=Sum('current_balance'))['total'] or Decimal('0.00'),
        'cash_balance': stats_qs.filter(is_active=True, vault_type='cash').aggregate(total=Sum('current_balance'))['total'] or Decimal('0.00'),
        'bank_balance': stats_qs.filter(is_active=True, vault_type='bank').aggregate(total=Sum('current_balance'))['total'] or Decimal('0.00'),
    }

    active_filters = []
    if search:
        qs = qs.filter(
            Q(name__icontains=search) |
            Q(serial_num__icontains=search)
        )
        active_filters.append({'label': f'بحث: {search}', 'param': 'search'})

    can_transfer = has_perm_or_admin(request.user, 'treasury:vaults/transfer')
    can_manage = has_perm_or_admin(request.user, 'treasury:vaults/manage')
    can_create_tx = has_perm_or_admin(request.user, 'treasury:transactions/create')

    paginator, page_obj = paginate_queryset(request, qs, default_per_page=25, max_per_page=100)

    context = {
        'vaults': page_obj.object_list,
        'page_obj': page_obj,
        'paginator': paginator,
        'search_query': search,
        'active_filters': active_filters,
        'total_count': paginator.count,
        'stats': stats,
        'can_transfer': can_transfer,
        'can_manage': can_manage,
        'can_create_tx': can_create_tx,
    }
    return render(request, 'treasury/vaults_list.html', context)


@require_permission(['treasury:transactions/list', 'treasury:vaults/view'])
def vault_transactions_list(request):
    """
    Historical Vault Transactions with Dedicated Scoped Statistics Cards.
    """
    vault_id = request.GET.get('vault_id')
    tx_type = request.GET.get('type')
    search = request.GET.get('search', '').strip()

    qs = VaultTransaction.objects.select_related('vault', 'created_by', 'reversal_transaction').order_by('-created_at')
    qs = get_scoped_queryset(qs, request.user, 'vaulttransaction')

    # Dedicated Real Scoped Statistics Cards
    scoped_all = qs
    total_inflow = scoped_all.filter(transaction_type='inflow').aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    total_outflow = scoped_all.filter(transaction_type='outflow').aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    stats = {
        'total_count': scoped_all.count(),
        'total_inflow': total_inflow,
        'total_outflow': total_outflow,
        'net_flow': total_inflow - total_outflow,
    }

    active_filters = []

    if vault_id:
        qs = qs.filter(vault_id=vault_id)
        v_obj = Vault.objects.filter(id=vault_id).first()
        active_filters.append({'label': f'الخزنة: {v_obj.name if v_obj else vault_id}', 'param': 'vault_id'})

    if tx_type in ['inflow', 'outflow']:
        qs = qs.filter(transaction_type=tx_type)
        type_label = 'إيداع (Inflow)' if tx_type == 'inflow' else 'صرف (Outflow)'
        active_filters.append({'label': f'نوع الحركة: {type_label}', 'param': 'type'})

    if search:
        qs = qs.filter(
            Q(description__icontains=search) |
            Q(vault__name__icontains=search)
        )
        active_filters.append({'label': f'بحث: {search}', 'param': 'search'})

    vaults = get_scoped_queryset(Vault.objects.filter(is_active=True), request.user, 'vault').order_by('name')
    can_reverse = has_perm_or_admin(request.user, 'treasury:transactions/reverse')

    paginator, page_obj = paginate_queryset(request, qs, default_per_page=25, max_per_page=100)

    context = {
        'transactions': page_obj.object_list,
        'page_obj': page_obj,
        'paginator': paginator,
        'vaults': vaults,
        'selected_vault_id': vault_id,
        'selected_tx_type': tx_type,
        'search_query': search,
        'active_filters': active_filters,
        'total_count': paginator.count,
        'stats': stats,
        'can_reverse': can_reverse,
    }
    return render(request, 'treasury/vault_transactions_list.html', context)


@require_permission('treasury:vaults/transfer')
def vault_transfer(request):
    """
    Transfer funds between authorized vaults.
    """
    if request.method == 'POST':
        source_id = request.POST.get('source_vault')
        dest_id = request.POST.get('destination_vault')
        amount = request.POST.get('amount')
        notes = request.POST.get('notes', '').strip()

        if not source_id or not dest_id or not amount:
            messages.error(request, "يرجى تحديد الخزنة المصدر، الخزنة المستلمة، ومبلغ التحويل.")
            return redirect('vaults_list')

        source_vault = get_object_or_404(Vault, id=source_id)
        dest_vault = get_object_or_404(Vault, id=dest_id)

        if not can_user_access_object(request.user, source_vault, 'transfer'):
            return render_forbidden_response(request, "لا تمتلك صلاحية التحويل من هذه الخزنة المصدر.")

        try:
            out_tx, in_tx = TreasuryService.transfer_funds(
                source_vault=source_vault,
                destination_vault=dest_vault,
                amount=Decimal(amount),
                user=request.user,
                notes=notes
            )
            messages.success(request, f"تم التحويل بنجاح بقيمة {Decimal(amount):,.2f} ج.م من {source_vault.name} إلى {dest_vault.name}.")
            return redirect('vaults_list')
        except (ValidationError, Exception) as e:
            messages.error(request, str(e.message if hasattr(e, 'message') else e))
            return redirect('vaults_list')

    source_vaults = get_scoped_queryset(Vault.objects.filter(is_active=True), request.user, 'vault').order_by('name')
    dest_vaults = Vault.objects.filter(is_active=True).order_by('name')

    context = {
        'source_vaults': source_vaults,
        'destination_vaults': dest_vaults,
    }
    return render(request, 'treasury/vault_transfer.html', context)


@require_permission('treasury:transactions/reverse')
def vault_transaction_reverse(request, pk):
    """
    Reverse an eligible vault transaction using financial reversal entry.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'MethodNotAllowed', 'detail': 'يجب استخدام طلب POST.'}, status=405)

    tx = get_object_or_404(VaultTransaction, pk=pk)
    if not can_user_access_object(request.user, tx.vault, 'view'):
        return render_forbidden_response(request, "لا يمكنك إجراء عكس لحركة خزنة خارج نطاق صلاحياتك.")

    reason = request.POST.get('reason', '').strip() or 'عكس حركة خاطئة من قبل الإدارة'

    try:
        reversal = TreasuryService.reverse_vault_transaction(tx_id=tx.id, user=request.user, reason=reason)
        messages.success(request, f"تم عكس الحركة #{tx.id} بنجاح بحركة تسوية عكسية #{reversal.id}.")
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'success': True, 'reversal_id': reversal.id})
        return redirect('vault_transactions_list')
    except (ValidationError, Exception) as e:
        msg = str(e.message if hasattr(e, 'message') else e)
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'error': 'ValidationError', 'detail': msg}, status=400)
        messages.error(request, msg)
        return redirect('vault_transactions_list')


@require_permission('treasury:vaults/manage')
def vault_create(request):
    """
    Create a new Vault (Cash Safe or Bank Account).
    """
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        vault_type = request.POST.get('vault_type', 'cash')
        assigned_user_id = request.POST.get('assigned_user') or None
        is_rep_vault = request.POST.get('is_rep_vault') == 'on'
        is_active = request.POST.get('is_active', 'on') == 'on'
        initial_balance = request.POST.get('initial_balance', '0.00').strip()

        if not name:
            messages.error(request, "يرجى إدخال اسم الخزنة.")
            return redirect('vaults_list')

        assigned_user = None
        if assigned_user_id:
            assigned_user = get_object_or_404(User, id=assigned_user_id)

        try:
            init_bal = Decimal(initial_balance)
            vault = Vault.objects.create(
                name=name,
                vault_type=vault_type,
                assigned_user=assigned_user,
                is_rep_vault=is_rep_vault,
                is_active=is_active,
                current_balance=init_bal
            )
            messages.success(request, f"تم إنشاء الخزنة ({vault.name}) بنجاح برقم مسلسل #{vault.serial_num}.")
            return redirect('vaults_list')
        except Exception as e:
            messages.error(request, f"خطأ أثناء إنشاء الخزنة: {e}")
            return redirect('vaults_list')

    users = User.objects.filter(is_active=True).order_by('username')
    return render(request, 'treasury/vault_form.html', {'is_create': True, 'users': users})


@require_permission('treasury:payments/requests')
def vendor_payment_requests_list(request):
    """View matching /vendor-payment-requests in reference ERP."""
    return render(request, 'treasury/vendor_payment_requests_list.html')
