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

    now = timezone.now()
    vp_agg = qs.aggregate(
        total_count=Count('id'),
        total_amount=Sum('amount'),
        month_amount=Sum('amount', filter=Q(payment_date__year=now.year, payment_date__month=now.month)),
        cash_amount=Sum('amount', filter=Q(payment_method='cash')),
        bank_amount=Sum('amount', filter=Q(payment_method__in=['cheque', 'bank_transfer'])),
    )
    stats = {
        'total_count': vp_agg['total_count'] or 0,
        'total_amount': vp_agg['total_amount'] or Decimal('0.00'),
        'month_amount': vp_agg['month_amount'] or Decimal('0.00'),
        'cash_amount': vp_agg['cash_amount'] or Decimal('0.00'),
        'bank_amount': vp_agg['bank_amount'] or Decimal('0.00'),
    }

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

    active_filters = []
    if search:
        qs = qs.filter(
            Q(supplier__name__icontains=search) |
            Q(supplier__code__icontains=search)
        )
        active_filters.append({'label': f'بحث: {search}', 'param': 'search'})

    v_agg = qs.aggregate(
        total_suppliers=Count('id'),
        total_payable=Sum('current_balance'),
        total_overdue=Sum('overdue_balance'),
        total_credit_limit=Sum('credit_limit'),
    )
    stats = {
        'total_suppliers': v_agg['total_suppliers'] or 0,
        'total_payable': v_agg['total_payable'] or Decimal('0.00'),
        'total_overdue': v_agg['total_overdue'] or Decimal('0.00'),
        'total_credit_limit': v_agg['total_credit_limit'] or Decimal('0.00'),
    }

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

    vtx_agg = qs.aggregate(
        total_count=Count('id'),
        total_credit=Sum('credit'),
        total_debit=Sum('debit'),
    )
    total_credit = vtx_agg['total_credit'] or Decimal('0.00')
    total_debit = vtx_agg['total_debit'] or Decimal('0.00')
    stats = {
        'total_count': vtx_agg['total_count'] or 0,
        'total_credit': total_credit,
        'total_debit': total_debit,
        'net_balance': total_credit - total_debit,
    }

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

    active_filters = []
    if search:
        qs = qs.filter(
            Q(name__icontains=search) |
            Q(serial_num__icontains=search)
        )
        active_filters.append({'label': f'بحث: {search}', 'param': 'search'})

    # Dedicated Real Scoped Statistics Cards matching active filters
    vlt_agg = qs.aggregate(
        total_vaults=Count('id'),
        active_vaults=Count('id', filter=Q(is_active=True)),
        total_balance=Sum('current_balance', filter=Q(is_active=True)),
        cash_balance=Sum('current_balance', filter=Q(is_active=True, vault_type='cash')),
        bank_balance=Sum('current_balance', filter=Q(is_active=True, vault_type='bank')),
    )
    stats = {
        'total_vaults': vlt_agg['total_vaults'] or 0,
        'active_vaults': vlt_agg['active_vaults'] or 0,
        'total_balance': vlt_agg['total_balance'] or Decimal('0.00'),
        'cash_balance': vlt_agg['cash_balance'] or Decimal('0.00'),
        'bank_balance': vlt_agg['bank_balance'] or Decimal('0.00'),
    }

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


@require_permission(['treasury:vaults/view', 'treasury:vaults/manage'])
def vault_detail(request, pk):
    """
    Detailed dossier for a specific vault or bank account:
    Financial metrics, custodian details, and recent transactions.
    """
    vault = get_object_or_404(Vault.objects.select_related('assigned_user'), pk=pk)
    if not can_user_access_object(request.user, vault, 'view'):
        return render_forbidden_response(request, "ليس لديك صلاحية للوصول إلى بيانات هذه الخزنة.")

    tx_qs = VaultTransaction.objects.filter(vault=vault).select_related('created_by', 'reversal_transaction').order_by('-created_at')

    total_inflows = tx_qs.filter(transaction_type='inflow', is_reversed=False).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    total_outflows = tx_qs.filter(transaction_type='outflow', is_reversed=False).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    tx_count = tx_qs.count()

    stats = {
        'current_balance': vault.current_balance,
        'total_inflows': total_inflows,
        'total_outflows': total_outflows,
        'net_flow': total_inflows - total_outflows,
        'tx_count': tx_count,
    }

    can_transfer = has_perm_or_admin(request.user, 'treasury:vaults/transfer')
    can_create_tx = has_perm_or_admin(request.user, 'treasury:transactions/create')

    recent_transactions = tx_qs[:20]

    context = {
        'vault': vault,
        'stats': stats,
        'recent_transactions': recent_transactions,
        'can_transfer': can_transfer,
        'can_create_tx': can_create_tx,
    }
    return render(request, 'treasury/vault_detail.html', context)


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

    vtx2_agg = qs.aggregate(
        total_count=Count('id'),
        total_inflow=Sum('amount', filter=Q(transaction_type='inflow')),
        total_outflow=Sum('amount', filter=Q(transaction_type='outflow')),
    )
    total_inflow = vtx2_agg['total_inflow'] or Decimal('0.00')
    total_outflow = vtx2_agg['total_outflow'] or Decimal('0.00')
    stats = {
        'total_count': vtx2_agg['total_count'] or 0,
        'total_inflow': total_inflow,
        'total_outflow': total_outflow,
        'net_flow': total_inflow - total_outflow,
    }

    vaults = get_scoped_queryset(Vault.objects.filter(is_active=True), request.user, 'vault').order_by('name')
    can_reverse = has_perm_or_admin(request.user, 'treasury:transactions/reverse')
    can_create_tx = has_perm_or_admin(request.user, 'treasury:transactions/create')
    can_transfer = has_perm_or_admin(request.user, 'treasury:vaults/transfer')

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
        'can_create_tx': can_create_tx,
        'can_transfer': can_transfer,
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


@require_permission('treasury:transactions/create')
def vault_deposit(request):
    """
    Deposit cash/funds into an authorized vault.
    """
    preselected_vault_id = request.GET.get('vault') or request.POST.get('vault_id')
    available_vaults = get_scoped_queryset(Vault.objects.filter(is_active=True), request.user, 'vault').order_by('name')

    if request.method == 'POST':
        vault_id = request.POST.get('vault_id')
        amount_raw = request.POST.get('amount', '').strip()
        description = request.POST.get('description', '').strip()
        reference_number = request.POST.get('reference_number', '').strip()
        transaction_date = request.POST.get('transaction_date') or timezone.now().date()
        notes = request.POST.get('notes', '').strip()

        if not vault_id:
            messages.error(request, "يرجى تحديد الخزنة المراد الإيداع فيها.")
            return render(request, 'treasury/vault_deposit.html', {
                'vaults': available_vaults,
                'selected_vault_id': preselected_vault_id,
            })

        vault = get_object_or_404(Vault, pk=vault_id)
        if not can_user_access_object(request.user, vault, 'deposit'):
            return render_forbidden_response(request, "لا يمكنك إجراء إيداع في خزنة تقع خارج نطاق صلاحياتك.")

        if not description:
            messages.error(request, "يرجى كتابة سبب أو بيان الإيداع.")
            return render(request, 'treasury/vault_deposit.html', {
                'vaults': available_vaults,
                'selected_vault_id': int(vault_id) if str(vault_id).isdigit() else None,
                'vault': vault,
            })

        try:
            amount = Decimal(amount_raw)
            tx = TreasuryService.deposit_funds(
                vault=vault,
                amount=amount,
                user=request.user,
                description=description,
                transaction_date=transaction_date,
                reference_number=reference_number,
                notes=notes
            )
            messages.success(request, f"تم بنجاح إيداع {amount:,.2f} ج.م في خزنة ({vault.name}). رقم الحركة: #{tx.id}.")
            return redirect('vaults_list')
        except (ValidationError, Exception) as e:
            msg = str(e.message if hasattr(e, 'message') else e)
            messages.error(request, f"فشل الإيداع: {msg}")
            return render(request, 'treasury/vault_deposit.html', {
                'vaults': available_vaults,
                'selected_vault_id': int(vault_id) if str(vault_id).isdigit() else None,
                'vault': vault,
                'amount': amount_raw,
                'description': description,
                'reference_number': reference_number,
                'notes': notes,
            })

    selected_vault = None
    if preselected_vault_id and str(preselected_vault_id).isdigit():
        selected_vault = available_vaults.filter(id=int(preselected_vault_id)).first()

    return render(request, 'treasury/vault_deposit.html', {
        'vaults': available_vaults,
        'selected_vault': selected_vault,
        'selected_vault_id': int(preselected_vault_id) if preselected_vault_id and str(preselected_vault_id).isdigit() else None,
        'today': timezone.now().date(),
    })


@require_permission('treasury:transactions/create')
def vault_withdraw(request):
    """
    Withdraw cash/funds from an authorized vault.
    """
    preselected_vault_id = request.GET.get('vault') or request.POST.get('vault_id')
    available_vaults = get_scoped_queryset(Vault.objects.filter(is_active=True), request.user, 'vault').order_by('name')

    if request.method == 'POST':
        vault_id = request.POST.get('vault_id')
        amount_raw = request.POST.get('amount', '').strip()
        description = request.POST.get('description', '').strip()
        reference_number = request.POST.get('reference_number', '').strip()
        transaction_date = request.POST.get('transaction_date') or timezone.now().date()
        notes = request.POST.get('notes', '').strip()

        if not vault_id:
            messages.error(request, "يرجى تحديد الخزنة المراد الصرف / السحب منها.")
            return render(request, 'treasury/vault_withdraw.html', {
                'vaults': available_vaults,
                'selected_vault_id': preselected_vault_id,
            })

        vault = get_object_or_404(Vault, pk=vault_id)
        if not can_user_access_object(request.user, vault, 'withdraw'):
            return render_forbidden_response(request, "لا يمكنك إجراء صرف من خزنة تقع خارج نطاق صلاحياتك.")

        if not description:
            messages.error(request, "يرجى كتابة سبب أو بيان الصرف.")
            return render(request, 'treasury/vault_withdraw.html', {
                'vaults': available_vaults,
                'selected_vault_id': int(vault_id) if str(vault_id).isdigit() else None,
                'vault': vault,
            })

        try:
            amount = Decimal(amount_raw)
            tx = TreasuryService.withdraw_funds(
                vault=vault,
                amount=amount,
                user=request.user,
                description=description,
                transaction_date=transaction_date,
                reference_number=reference_number,
                notes=notes
            )
            messages.success(request, f"تم بنجاح صرف {amount:,.2f} ج.م من خزنة ({vault.name}). رقم الحركة: #{tx.id}.")
            return redirect('vaults_list')
        except (ValidationError, Exception) as e:
            msg = str(e.message if hasattr(e, 'message') else e)
            messages.error(request, f"فشل الصرف: {msg}")
            return render(request, 'treasury/vault_withdraw.html', {
                'vaults': available_vaults,
                'selected_vault_id': int(vault_id) if str(vault_id).isdigit() else None,
                'vault': vault,
                'amount': amount_raw,
                'description': description,
                'reference_number': reference_number,
                'notes': notes,
            })

    selected_vault = None
    if preselected_vault_id and str(preselected_vault_id).isdigit():
        selected_vault = available_vaults.filter(id=int(preselected_vault_id)).first()

    return render(request, 'treasury/vault_withdraw.html', {
        'vaults': available_vaults,
        'selected_vault': selected_vault,
        'selected_vault_id': int(preselected_vault_id) if preselected_vault_id and str(preselected_vault_id).isdigit() else None,
        'today': timezone.now().date(),
    })

