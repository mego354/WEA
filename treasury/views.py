from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q
from django.core.exceptions import ValidationError

from .models import Vault, VendorAccount, VendorTransaction, VendorPayment, VaultTransaction
from .services import TreasuryService
from contacts.models import Contact
from master_data.excel_utils import export_to_excel_response
from master_data.pagination_utils import paginate_queryset
from accounts.permissions import require_permission, get_scoped_queryset


@require_permission('treasury:payments/list')
def vendor_payments_list(request):
    search = request.GET.get('search', '').strip()
    supplier_id = request.GET.get('supplier')
    vault_id = request.GET.get('vault')
    payment_method = request.GET.get('payment_method')

    qs = VendorPayment.objects.select_related('supplier', 'vault', 'created_by').order_by('-serial_num')

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
        method_labels = dict(VendorPayment.PAYMENT_METHOD_CHOICES)
        active_filters.append({'label': f'طريقة الدفع: {method_labels.get(payment_method, payment_method)}', 'param': 'payment_method'})

    if search:
        qs = qs.filter(
            Q(serial_num__icontains=search) |
            Q(supplier__name__icontains=search) |
            Q(reference_number__icontains=search) |
            Q(notes__icontains=search)
        )
        active_filters.append({'label': f'بحث: {search}', 'param': 'search'})

    suppliers = Contact.objects.filter(is_supplier=True).order_by('name')
    vaults = Vault.objects.filter(is_active=True).order_by('name')

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
    }
    return render(request, 'treasury/vendor_payments_list.html', context)


@require_permission('treasury:payments/export')
def vendor_payments_export(request):
    supplier_id = request.GET.get('supplier')
    qs = VendorPayment.objects.select_related('supplier', 'vault', 'created_by').order_by('-serial_num')
    if supplier_id:
        qs = qs.filter(supplier_id=supplier_id)

    columns = [
        {'header': 'رقم سند الصرف', 'key': lambda p: f"#{p.serial_num}", 'width': 16, 'align': 'center'},
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
        payment_method = request.POST.get('payment_method', 'cash')
        reference_number = request.POST.get('reference_number', '').strip()
        notes = request.POST.get('notes', '').strip()

        if not supplier_id or not vault_id or not amount:
            messages.error(request, "يرجى ملء جميع الحقول المطلوبة (المورد، الخزنة، والمبلغ).")
            return redirect('vendor_payment_create')

        supplier = get_object_or_404(Contact, id=supplier_id)
        vault = get_object_or_404(Vault, id=vault_id)

        try:
            payment = TreasuryService.record_vendor_payment(
                supplier=supplier,
                vault=vault,
                amount=Decimal(amount),
                user=request.user,
                payment_method=payment_method,
                reference_number=reference_number,
                notes=notes
            )
            messages.success(request, f"تم تسجيل سند الصرف #{payment.serial_num} بنجاح بمبلغ {payment.amount:,.2f} ج.م للمورد {supplier.name}.")
            return redirect('vendor_payments_list')
        except ValidationError as e:
            messages.error(request, str(e.message if hasattr(e, 'message') else e))
            return redirect('vendor_payment_create')

    suppliers = Contact.objects.filter(is_supplier=True).order_by('name')
    vaults = Vault.objects.filter(is_active=True).order_by('name')
    initial_supplier = request.GET.get('supplier_id')

    context = {
        'suppliers': suppliers,
        'vaults': vaults,
        'selected_supplier_id': initial_supplier,
    }
    return render(request, 'treasury/vendor_payment_create.html', context)


@require_permission('treasury:vendors/accounting')
def accounting_vendors_list(request):
    """
    Vendor Statements & Balances (حسابات الموردين).
    """
    search = request.GET.get('search', '').strip()
    qs = VendorAccount.objects.select_related('supplier', 'supplier__area').order_by('-current_balance')

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

    suppliers = Contact.objects.filter(is_supplier=True).order_by('name')

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
    }
    return render(request, 'treasury/vendor_transactions_list.html', context)


@require_permission('treasury:vaults/view')
def vaults_list(request):
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

    paginator, page_obj = paginate_queryset(request, qs, default_per_page=25, max_per_page=100)

    context = {
        'vaults': page_obj.object_list,
        'page_obj': page_obj,
        'paginator': paginator,
        'search_query': search,
        'active_filters': active_filters,
        'total_count': paginator.count,
    }
    return render(request, 'treasury/vaults_list.html', context)


@require_permission('treasury:vaults/transactions')
def vault_transactions_list(request):
    vault_id = request.GET.get('vault_id')
    tx_type = request.GET.get('type')
    search = request.GET.get('search', '').strip()

    qs = VaultTransaction.objects.select_related('vault', 'created_by').order_by('-created_at')

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
            Q(statement__icontains=search) |
            Q(vault__name__icontains=search)
        )
        active_filters.append({'label': f'بحث: {search}', 'param': 'search'})

    vaults = Vault.objects.filter(is_active=True).order_by('name')

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
    }
    return render(request, 'treasury/vault_transactions_list.html', context)


@require_permission('treasury:payments/requests')
def vendor_payment_requests_list(request):
    """View matching /vendor-payment-requests in reference ERP."""
    return render(request, 'treasury/vendor_payment_requests_list.html')
