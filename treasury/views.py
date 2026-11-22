from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from django.contrib import messages
from django.db.models import Q, Sum, Count
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.utils import timezone

from .models import Vault, VendorAccount, VendorTransaction, VendorPayment, VaultTransaction, VendorPaymentRequest
from .services import TreasuryService, VendorPaymentRequestService, build_payment_request_timeline, VaultService
from master_data.search_utils import filter_by_arabic_search, get_bounded_select_options
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
    get_visible_assignees_queryset,
)
from accounts.scope_service import ScopeResolutionService

User = get_user_model()


@require_permission('treasury:payments/list')
def vendor_payments_list(request):
    from master_data.filter_utils import parse_single_int
    from master_data.date_filter_utils import resolve_date_range
    search = request.GET.get('search', '').strip()
    supplier_id_int = parse_single_int(request.GET, 'supplier')
    supplier_id = str(supplier_id_int) if supplier_id_int else ''
    vault_id_int = parse_single_int(request.GET, 'vault')
    vault_id = str(vault_id_int) if vault_id_int else ''
    payment_method = request.GET.get('payment_method')
    parsed_from, parsed_to, active_preset, date_from, date_to = resolve_date_range(request, default_preset='all_time')

    qs = VendorPayment.objects.select_related('supplier', 'vault', 'created_by', 'purchase_order').order_by('-serial_num')
    qs = get_scoped_queryset(qs, request.user, 'vendorpayment')

    active_filters = []

    if supplier_id:
        qs = qs.filter(supplier_id=supplier_id)
        s_obj = ScopeResolutionService.get_scoped_choices(request.user, 'suppliers', 'treasury').filter(id=supplier_id).first()
        active_filters.append({'label': 'المورد', 'value': s_obj.name if s_obj else supplier_id, 'param': 'supplier'})

    if vault_id:
        qs = qs.filter(vault_id=vault_id)
        v_obj = ScopeResolutionService.get_scoped_choices(request.user, 'vaults', 'treasury').filter(id=vault_id).first()
        active_filters.append({'label': 'الخزنة', 'value': v_obj.name if v_obj else vault_id, 'param': 'vault'})

    if payment_method:
        qs = qs.filter(payment_method=payment_method)
        method_labels = dict(VendorPayment.PAYMENT_METHODS)
        active_filters.append({'label': 'طريقة الدفع', 'value': method_labels.get(payment_method, payment_method), 'param': 'payment_method'})

    if parsed_from:
        qs = qs.filter(payment_date__gte=parsed_from)
        active_filters.append({'label': 'من تاريخ', 'value': date_from, 'param': 'date_from'})

    if parsed_to:
        qs = qs.filter(payment_date__lte=parsed_to)
        active_filters.append({'label': 'إلى تاريخ', 'value': date_to, 'param': 'date_to'})

    if search:
        qs = filter_by_arabic_search(qs, search, ['serial_num', 'supplier__name', 'reference_number', 'notes'])
        active_filters.append({'label': 'بحث', 'value': search, 'param': 'search'})

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

    suppliers = get_bounded_select_options(
        ScopeResolutionService.get_scoped_choices(request.user, 'suppliers', 'treasury'),
        selected_id=supplier_id,
        limit=100,
    )
    vaults = get_bounded_select_options(
        ScopeResolutionService.get_scoped_choices(request.user, 'vaults', 'treasury'),
        selected_id=vault_id,
        limit=100,
    )

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
        'active_preset': active_preset,
        'selected_date_from': date_from,
        'selected_date_to': date_to,
        'date_from': date_from,
        'date_to': date_to,
        'payment_methods': VendorPayment.PAYMENT_METHODS,
        'active_filters': active_filters,
        'active_filters_count': len(active_filters),
        'total_count': paginator.count,
        'stats': stats,
    }
    return render(request, 'treasury/vendor_payments_list.html', context)


@require_permission('treasury:payments/export')
def vendor_payments_export(request):
    from master_data.date_filter_utils import resolve_date_range
    supplier_id = request.GET.get('supplier')
    vault_id = request.GET.get('vault') or request.GET.get('vault_id')
    payment_method = request.GET.get('payment_method')
    parsed_from, parsed_to, _, _, _ = resolve_date_range(request, default_preset='all_time')
    search = request.GET.get('search', '').strip()

    qs = VendorPayment.objects.select_related('supplier', 'vault', 'created_by', 'purchase_order').order_by('-serial_num')
    qs = get_scoped_queryset(qs, request.user, 'vendorpayment')
    if supplier_id:
        qs = qs.filter(supplier_id=supplier_id)
    if vault_id:
        qs = qs.filter(vault_id=vault_id)
    if payment_method:
        qs = qs.filter(payment_method=payment_method)
    if parsed_from:
        qs = qs.filter(payment_date__gte=parsed_from)
    if parsed_to:
        qs = qs.filter(payment_date__lte=parsed_to)
    if search:
        qs = filter_by_arabic_search(qs, search, ['serial_num', 'supplier__name', 'reference_number', 'notes'])

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

    return export_to_excel_response(
        qs,
        columns,
        filename="vendor_payments_export",
        sheet_title="مدفوعات الموردين",
        report_title="سجل مدفوعات وسندات صرف الموردين",
        user=request.user,
    )


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

        if not ScopeResolutionService.can_user_access_supplier(request.user, supplier):
            return render_forbidden_response(request, "لا يمكنك تسجيل سداد لمورد خارج نطاقك الجغرافي أو صلاحياتك.")
        if not supplier.is_supplier or supplier.status == 'inactive':
            messages.error(request, "جهة الاتصال المحددة غير مصنفة كمورد نشط.")
            return redirect('vendor_payment_create')
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
            if request.FILES.getlist('attachments'):
                from master_data.media_service import store_attachments_from_request
                store_attachments_from_request(payment, request)
            po_info = f" لأمر الشراء {purchase_order.order_number}" if purchase_order else ""
            messages.success(request, f"تم تسجيل سند الصرف #{payment.serial_num} بنجاح بمبلغ {payment.amount:,.2f} ج.م للمورد {supplier.name}{po_info}.")
            return redirect('vendor_payments_list')
        except ValidationError as e:
            messages.error(request, str(e.message if hasattr(e, 'message') else e))
            return redirect('vendor_payment_create')

    initial_supplier = request.GET.get('supplier_id') or request.GET.get('supplier')
    initial_order = request.GET.get('order_id') or request.GET.get('po')

    if initial_order and not initial_supplier:
        po_obj = PurchaseOrder.objects.filter(id=initial_order).first()
        if po_obj and can_user_access_object(request.user, po_obj, 'view'):
            initial_supplier = po_obj.supplier_id

    suppliers = get_bounded_select_options(
        ScopeResolutionService.get_scoped_choices(request.user, 'suppliers', 'treasury'),
        selected_id=initial_supplier,
        limit=100,
    )
    vaults = ScopeResolutionService.get_scoped_choices(request.user, 'vaults', 'treasury')

    # Open purchase orders for dropdown linking (SQL-annotated paid totals to avoid N+1)
    orders_qs = PurchaseOrder.with_payment_totals(
        PurchaseOrder.objects.exclude(status='cancelled').select_related('supplier').order_by('-order_date', '-id')
    )
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
        qs = filter_by_arabic_search(qs, search, ['supplier__name', 'supplier__code'])
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


@require_permission('treasury:vendors/accounting_export')
def accounting_vendors_export(request):
    """Export filtered and scoped vendor accounts to Excel."""
    search = request.GET.get('search', '').strip()
    qs = VendorAccount.objects.select_related('supplier', 'supplier__area').order_by('-current_balance')
    scoped_suppliers = get_scoped_queryset(Contact.objects.filter(is_supplier=True), request.user, 'contact')
    qs = qs.filter(supplier__in=scoped_suppliers)
    if search:
        qs = filter_by_arabic_search(qs, search, ['supplier__name', 'supplier__code'])

    columns = [
        {'header': 'كود المورد', 'key': lambda a: a.supplier.code or '', 'width': 16, 'align': 'center'},
        {'header': 'اسم المورد', 'key': lambda a: a.supplier.name, 'width': 32, 'align': 'right'},
        {'header': 'المنطقة', 'key': lambda a: a.supplier.area.name if a.supplier.area else '', 'width': 20, 'align': 'right'},
        {'header': 'الرصيد المستحق (ج.م)', 'key': lambda a: float(a.current_balance or 0), 'format': '#,##0.00', 'width': 20, 'align': 'right'},
        {'header': 'المتأخرات (ج.م)', 'key': lambda a: float(a.overdue_balance or 0), 'format': '#,##0.00', 'width': 18, 'align': 'right'},
        {'header': 'الحد الائتماني (ج.م)', 'key': lambda a: float(a.credit_limit or 0), 'format': '#,##0.00', 'width': 20, 'align': 'right'},
    ]
    return export_to_excel_response(
        qs,
        columns,
        filename="accounting_vendors_export",
        sheet_title="حسابات الموردين",
        report_title="كشف أرصدة وحسابات الموردين",
        user=request.user,
    )


@require_permission('treasury:vendors/zero_balance')
def accounting_vendor_zero_balance(request, pk):
    """Non-cash account zeroing (تصفير الحساب) for VendorAccount — zero vault impact, preserves order payment_status."""
    if request.method != 'POST':
        return redirect('accounting_vendors_list')

    account = get_object_or_404(VendorAccount.objects.select_related('supplier'), pk=pk)
    if not (can_user_access_object(request.user, account, 'manage') or ScopeResolutionService.can_user_access_supplier(request.user, account.supplier)):
        return render_forbidden_response(request, "غير مصرح لك بتصفير رصيد حساب مورد خارج نطاق اختصاصك.")

    reason_note = (request.POST.get('reason') or '').strip()
    is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'application/json' in request.headers.get('accept', '')

    try:
        tx, prev_bal = TreasuryService.zero_vendor_balance(
            supplier=account.supplier,
            user=request.user,
            reason_note=reason_note,
            request=request,
        )
        msg = f"تم تصفير رصيد حساب المورد {account.supplier.name} (من {prev_bal:,.2f} ج.م إلى 0.00 ج.م) بدون التأثير على أي خزنة."
        if is_ajax:
            return JsonResponse({'success': True, 'message': msg, 'new_balance': '0.00', 'transaction_serial': tx.serial})
        messages.success(request, msg)
    except ValidationError as e:
        err_msg = str(e.message if hasattr(e, 'message') else e)
        if is_ajax:
            return JsonResponse({'success': False, 'message': err_msg}, status=400)
        messages.error(request, err_msg)

    return redirect('accounting_vendors_list')


@require_permission('treasury:vendors/transactions')
def vendor_transactions_list(request):
    """
    Vendor Ledger Transactions (عمليات الموردين).
    """
    from master_data.date_filter_utils import resolve_date_range
    vendor_id = request.GET.get('vendor_id') or request.GET.get('supplier')
    tx_type = request.GET.get('type')
    parsed_from, parsed_to, active_preset, date_from, date_to = resolve_date_range(request, default_preset='all_time')
    search = request.GET.get('search', '').strip()

    qs = VendorTransaction.objects.select_related('account', 'account__supplier', 'created_by', 'purchase_order').order_by('-serial')
    scoped_suppliers = get_scoped_queryset(Contact.objects.filter(is_supplier=True), request.user, 'contact')
    qs = qs.filter(account__supplier__in=scoped_suppliers)

    active_filters = []

    if vendor_id:
        qs = qs.filter(account__supplier_id=vendor_id)
        v_obj = scoped_suppliers.filter(id=vendor_id).first()
        active_filters.append({'label': 'المورد', 'value': v_obj.name if v_obj else vendor_id, 'param': 'vendor_id'})

    if tx_type in ['credit', 'debit']:
        qs = qs.filter(transaction_type=tx_type)
        tx_label = 'دائن (فاتورة مشتريات)' if tx_type == 'credit' else 'مدين (سداد / مردودات)'
        active_filters.append({'label': 'النوع', 'value': tx_label, 'param': 'type'})

    if parsed_from:
        qs = qs.filter(transaction_date__gte=parsed_from)
        active_filters.append({'label': 'من تاريخ', 'value': date_from, 'param': 'date_from'})

    if parsed_to:
        qs = qs.filter(transaction_date__lte=parsed_to)
        active_filters.append({'label': 'إلى تاريخ', 'value': date_to, 'param': 'date_to'})

    if search:
        qs = filter_by_arabic_search(qs, search, ['serial', 'description', 'account__supplier__name'])
        active_filters.append({'label': 'بحث', 'value': search, 'param': 'search'})

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

    suppliers = get_bounded_select_options(
        ScopeResolutionService.get_scoped_choices(request.user, 'suppliers', 'treasury'),
        selected_id=vendor_id,
        limit=100,
    )

    paginator, page_obj = paginate_queryset(request, qs, default_per_page=25, max_per_page=100)

    context = {
        'transactions': page_obj.object_list,
        'page_obj': page_obj,
        'paginator': paginator,
        'suppliers': suppliers,
        'selected_vendor_id': vendor_id,
        'selected_type': tx_type,
        'active_preset': active_preset,
        'selected_date_from': date_from,
        'selected_date_to': date_to,
        'date_from': date_from,
        'date_to': date_to,
        'search_query': search,
        'active_filters': active_filters,
        'active_filters_count': len(active_filters),
        'total_count': paginator.count,
        'stats': stats,
    }
    return render(request, 'treasury/vendor_transactions_list.html', context)


@require_permission('treasury:vendors/transactions_export')
def vendor_transactions_export(request):
    """Export filtered and scoped vendor ledger transactions to Excel."""
    from master_data.date_filter_utils import resolve_date_range
    vendor_id = request.GET.get('vendor_id') or request.GET.get('supplier')
    tx_type = request.GET.get('type')
    parsed_from, parsed_to, _, _, _ = resolve_date_range(request, default_preset='all_time')
    search = request.GET.get('search', '').strip()

    qs = VendorTransaction.objects.select_related('account', 'account__supplier', 'created_by', 'purchase_order').order_by('-serial')
    scoped_suppliers = get_scoped_queryset(Contact.objects.filter(is_supplier=True), request.user, 'contact')
    qs = qs.filter(account__supplier__in=scoped_suppliers)
    if vendor_id:
        qs = qs.filter(account__supplier_id=vendor_id)
    if tx_type in ['credit', 'debit']:
        qs = qs.filter(transaction_type=tx_type)
    if parsed_from:
        qs = qs.filter(transaction_date__gte=parsed_from)
    if parsed_to:
        qs = qs.filter(transaction_date__lte=parsed_to)
    if search:
        qs = filter_by_arabic_search(qs, search, ['serial', 'description', 'account__supplier__name'])

    columns = [
        {'header': 'رقم القيد', 'key': lambda t: f"#{t.serial}", 'width': 14, 'align': 'center'},
        {'header': 'المورد / الحساب', 'key': lambda t: t.account.supplier.name, 'width': 28, 'align': 'right'},
        {'header': 'تاريخ المعاملة', 'key': lambda t: t.transaction_date.strftime('%Y-%m-%d') if t.transaction_date else '', 'width': 16, 'align': 'center'},
        {'header': 'البيان والتوصيف', 'key': lambda t: t.description or '', 'width': 34, 'align': 'right'},
        {'header': 'تاريخ الاستحقاق', 'key': lambda t: t.due_date.strftime('%Y-%m-%d') if t.due_date else '', 'width': 16, 'align': 'center'},
        {'header': 'دائن / فاتورة (+)', 'key': lambda t: float(t.credit or 0), 'format': '#,##0.00', 'width': 18, 'align': 'right'},
        {'header': 'مدين / سداد (-)', 'key': lambda t: float(t.debit or 0), 'format': '#,##0.00', 'width': 18, 'align': 'right'},
        {'header': 'الرصيد المستحق', 'key': lambda t: float(t.running_balance or 0), 'format': '#,##0.00', 'width': 18, 'align': 'right'},
        {'header': 'المسئول', 'key': lambda t: (t.created_by.name or t.created_by.username) if t.created_by else '', 'width': 22, 'align': 'right'},
    ]
    return export_to_excel_response(
        qs,
        columns,
        filename="vendor_transactions_export",
        sheet_title="قيود الموردين",
        report_title="سجل القيود اليومية وحركات الموردين",
        user=request.user,
    )


@require_permission(['treasury:vaults/view', 'treasury:treasury/view'])
def vaults_list(request):
    """
    Vaults & Cash Safes Listing with Dedicated Scoped Statistics Cards and Advanced Filter Drawer.
    """
    from master_data.filter_utils import parse_multi_str, parse_single_int, resolve_scoped_area_brick_filters
    search = request.GET.get('search', '').strip()
    selected_vault_types = [v for v in parse_multi_str(request.GET, 'vault_type') if v in ('cash', 'bank')]
    vault_type = selected_vault_types[0] if len(selected_vault_types) == 1 else ''
    custody_type = request.GET.get('custody_type', '').strip()
    status = request.GET.get('status', '').strip()
    main_area_ids, brick_ids, selected_main_areas_chips, selected_bricks_chips = resolve_scoped_area_brick_filters(
        request, 'treasury',
        area_params=('main_area', 'area', 'area_id', 'governorate'),
        brick_params=('brick', 'brick_id'),
    )
    area_id = str(main_area_ids[0]) if len(main_area_ids) == 1 else ''
    assigned_user_int = parse_single_int(request.GET, 'assigned_user')
    assigned_user_id = str(assigned_user_int) if assigned_user_int else ''
    balance_min = request.GET.get('balance_min', '').strip()
    balance_max = request.GET.get('balance_max', '').strip()

    qs = Vault.objects.select_related('assigned_user', 'area').order_by('serial_num')
    qs = get_scoped_queryset(qs, request.user, 'vault')

    active_filters = []
    if search:
        qs = filter_by_arabic_search(qs, search, ['name', 'serial_num'])
        active_filters.append({'label': 'بحث', 'value': search, 'param': 'search'})

    if selected_vault_types:
        qs = qs.filter(vault_type__in=selected_vault_types)
        vt_map = {'cash': 'خزينة نقدية', 'bank': 'حساب بنكي'}
        for vt in selected_vault_types:
            active_filters.append({'label': 'نوع الخزنة', 'value': vt_map.get(vt, vt), 'param': 'vault_type', 'remove_value': vt})

    if custody_type == 'rep':
        qs = qs.filter(is_rep_vault=True)
        active_filters.append({'label': 'التبعية', 'value': 'عهدة مندوب', 'param': 'custody_type'})
    elif custody_type == 'central':
        qs = qs.filter(is_rep_vault=False)
        active_filters.append({'label': 'التبعية', 'value': 'خزينة عامة / فرع', 'param': 'custody_type'})

    if status == 'active':
        qs = qs.filter(is_active=True)
        active_filters.append({'label': 'الحالة', 'value': 'مفعلة', 'param': 'status'})
    elif status == 'inactive':
        qs = qs.filter(is_active=False)
        active_filters.append({'label': 'الحالة', 'value': 'معطلة', 'param': 'status'})

    from master_data.models import Area
    if main_area_ids:
        qs = qs.filter(Q(area_id__in=main_area_ids) | Q(area__parent_id__in=main_area_ids))
        for a_chip in selected_main_areas_chips:
            active_filters.append({'label': 'المنطقة', 'value': a_chip['name'], 'param': 'main_area', 'remove_value': str(a_chip['id'])})
    if brick_ids:
        qs = qs.filter(area_id__in=brick_ids)
        for b_chip in selected_bricks_chips:
            active_filters.append({'label': 'الخط الجغرافي / Brick', 'value': b_chip['name'], 'param': 'brick', 'remove_value': str(b_chip['id'])})

    assignees = get_visible_assignees_queryset(request.user, 'treasury')
    if assigned_user_id:
        qs = qs.filter(assigned_user_id=assigned_user_id)
        u_obj = assignees.filter(id=assigned_user_id).first()
        active_filters.append({'label': 'المسؤول', 'value': u_obj.get_full_name() or u_obj.username if u_obj else assigned_user_id, 'param': 'assigned_user'})

    if balance_min:
        try:
            b_min = Decimal(balance_min)
            qs = qs.filter(current_balance__gte=b_min)
            active_filters.append({'label': 'الحد الأدنى للرصيد', 'value': f'{b_min:,.2f} ج.م', 'param': 'balance_min'})
        except Exception:
            pass

    if balance_max:
        try:
            b_max = Decimal(balance_max)
            qs = qs.filter(current_balance__lte=b_max)
            active_filters.append({'label': 'الحد الأقصى للرصيد', 'value': f'{b_max:,.2f} ج.م', 'param': 'balance_max'})
        except Exception:
            pass

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

    areas = ScopeResolutionService.get_scoped_choices(request.user, 'governorates', 'treasury')

    vault_type_options = [{'value': 'cash', 'label': 'خزينة نقدية (Cash Safe)'}, {'value': 'bank', 'label': 'حساب بنكي (Bank Account)'}]
    selected_vault_type_items = [o for o in vault_type_options if o['value'] in selected_vault_types]

    context = {
        'vaults': page_obj.object_list,
        'page_obj': page_obj,
        'paginator': paginator,
        'search_query': search,
        'vault_type_options': vault_type_options,
        'selected_vault_type_items': selected_vault_type_items,
        'selected_vault_types': selected_vault_types,
        'selected_main_areas_chips': selected_main_areas_chips,
        'selected_bricks_chips': selected_bricks_chips,
        'selected_vault_type': vault_type,
        'selected_custody_type': custody_type,
        'selected_status': status,
        'selected_area': area_id,
        'selected_assigned_user': assigned_user_id,
        'selected_balance_min': balance_min,
        'selected_balance_max': balance_max,
        'active_filters': active_filters,
        'total_count': paginator.count,
        'stats': stats,
        'areas': areas,
        'assignees': assignees,
        'can_transfer': can_transfer,
        'can_manage': can_manage,
        'can_create_tx': can_create_tx,
    }
    return render(request, 'treasury/vaults_list.html', context)


@require_permission('treasury:vaults/export')
def vaults_export(request):
    """Export filtered and scoped vaults to Excel."""
    from master_data.filter_utils import parse_multi_str, parse_single_int, resolve_scoped_area_brick_filters
    search = request.GET.get('search', '').strip()
    selected_vault_types = [v for v in parse_multi_str(request.GET, 'vault_type') if v in ('cash', 'bank')]
    vault_type = selected_vault_types[0] if len(selected_vault_types) == 1 else ''
    custody_type = request.GET.get('custody_type', '').strip()
    status = request.GET.get('status', '').strip()
    main_area_ids, brick_ids, selected_main_areas_chips, selected_bricks_chips = resolve_scoped_area_brick_filters(
        request, 'treasury',
        area_params=('main_area', 'area', 'area_id', 'governorate'),
        brick_params=('brick', 'brick_id'),
    )
    area_id = str(main_area_ids[0]) if len(main_area_ids) == 1 else ''
    assigned_user_int = parse_single_int(request.GET, 'assigned_user')
    assigned_user_id = str(assigned_user_int) if assigned_user_int else ''
    balance_min = request.GET.get('balance_min', '').strip()
    balance_max = request.GET.get('balance_max', '').strip()

    qs = Vault.objects.select_related('assigned_user', 'area').order_by('serial_num')
    qs = get_scoped_queryset(qs, request.user, 'vault')
    if search:
        qs = filter_by_arabic_search(qs, search, ['name', 'serial_num'])
    if vault_type in ['cash', 'bank']:
        qs = qs.filter(vault_type=vault_type)
    if custody_type == 'rep':
        qs = qs.filter(is_rep_vault=True)
    elif custody_type == 'central':
        qs = qs.filter(is_rep_vault=False)
    if status == 'active':
        qs = qs.filter(is_active=True)
    elif status == 'inactive':
        qs = qs.filter(is_active=False)
    if area_id:
        qs = qs.filter(Q(area_id=area_id) | Q(area__parent_id=area_id))
    if assigned_user_id:
        qs = qs.filter(assigned_user_id=assigned_user_id)
    if balance_min:
        try:
            qs = qs.filter(current_balance__gte=Decimal(balance_min))
        except Exception:
            pass
    if balance_max:
        try:
            qs = qs.filter(current_balance__lte=Decimal(balance_max))
        except Exception:
            pass

    columns = [
        {'header': 'الرقم المسلسل', 'key': 'serial_num', 'width': 16, 'align': 'center'},
        {'header': 'اسم الخزنة / الحساب', 'key': 'name', 'width': 28, 'align': 'right'},
        {'header': 'النوع', 'key': lambda v: 'خزينة نقدية' if v.vault_type == 'cash' else 'حساب بنكي', 'width': 16, 'align': 'center'},
        {'header': 'التبعية', 'key': lambda v: 'عهدة مندوب' if v.is_rep_vault else 'خزينة عامة / فرع', 'width': 18, 'align': 'center'},
        {'header': 'المنطقة', 'key': lambda v: v.area.name if v.area else '', 'width': 20, 'align': 'right'},
        {'header': 'المسؤول', 'key': lambda v: (v.assigned_user.name or v.assigned_user.username) if v.assigned_user else '', 'width': 22, 'align': 'right'},
        {'header': 'الرصيد الحالي (ج.م)', 'key': lambda v: float(v.current_balance or 0), 'format': '#,##0.00', 'width': 20, 'align': 'right'},
        {'header': 'الحالة', 'key': lambda v: 'مفعلة' if v.is_active else 'معطلة', 'width': 12, 'align': 'center'},
    ]
    return export_to_excel_response(
        qs,
        columns,
        filename="vaults_export",
        sheet_title="الخزن النقدية",
        report_title="دليل الخزن النقدية وحسابات العهد",
        user=request.user,
    )


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

    total_inflows = tx_qs.filter(transaction_type='inflow').aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    total_outflows = tx_qs.filter(transaction_type='outflow').aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
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
    can_manage = has_perm_or_admin(request.user, 'treasury:vaults/manage') and can_user_access_object(request.user, vault, 'edit')
    can_delete = (has_perm_or_admin(request.user, 'treasury:vaults/manage') or has_perm_or_admin(request.user, 'treasury:vaults/delete')) and can_user_access_object(request.user, vault, 'delete')

    recent_transactions = tx_qs[:20]

    context = {
        'vault': vault,
        'stats': stats,
        'recent_transactions': recent_transactions,
        'can_transfer': can_transfer,
        'can_create_tx': can_create_tx,
        'can_manage': can_manage,
        'can_delete': can_delete,
    }
    return render(request, 'treasury/vault_detail.html', context)


@require_permission(['treasury:transactions/list', 'treasury:vaults/view'])
def vault_transactions_list(request):
    """
    Historical Vault Transactions with Dedicated Scoped Statistics Cards.
    """
    from master_data.date_filter_utils import resolve_date_range
    vault_id = request.GET.get('vault_id')
    tx_type = request.GET.get('type')
    parsed_from, parsed_to, active_preset, date_from, date_to = resolve_date_range(request, default_preset='all_time')
    search = request.GET.get('search', '').strip()

    qs = VaultTransaction.objects.select_related('vault', 'created_by', 'reversal_transaction').order_by('-created_at')
    qs = get_scoped_queryset(qs, request.user, 'vaulttransaction')

    active_filters = []

    if vault_id:
        qs = qs.filter(vault_id=vault_id)
        v_obj = ScopeResolutionService.get_scoped_choices(request.user, 'vaults', 'treasury').filter(id=vault_id).first()
        active_filters.append({'label': 'الخزنة', 'value': v_obj.name if v_obj else vault_id, 'param': 'vault_id'})

    if tx_type in ['inflow', 'outflow']:
        qs = qs.filter(transaction_type=tx_type)
        type_label = 'إيداع' if tx_type == 'inflow' else 'صرف'
        active_filters.append({'label': 'نوع الحركة', 'value': type_label, 'param': 'type'})

    if parsed_from:
        qs = qs.filter(created_at__date__gte=parsed_from)
        active_filters.append({'label': 'من تاريخ', 'value': date_from, 'param': 'date_from'})

    if parsed_to:
        qs = qs.filter(created_at__date__lte=parsed_to)
        active_filters.append({'label': 'إلى تاريخ', 'value': date_to, 'param': 'date_to'})

    if search:
        qs = filter_by_arabic_search(qs, search, ['description', 'vault__name'])
        active_filters.append({'label': 'بحث', 'value': search, 'param': 'search'})

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

    vaults = get_bounded_select_options(
        ScopeResolutionService.get_scoped_choices(request.user, 'vaults', 'treasury'),
        selected_id=vault_id,
        limit=100,
    )
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
        'active_preset': active_preset,
        'selected_date_from': date_from,
        'selected_date_to': date_to,
        'date_from': date_from,
        'date_to': date_to,
        'search_query': search,
        'active_filters': active_filters,
        'active_filters_count': len(active_filters),
        'total_count': paginator.count,
        'stats': stats,
        'can_reverse': can_reverse,
        'can_create_tx': can_create_tx,
        'can_transfer': can_transfer,
    }
    return render(request, 'treasury/vault_transactions_list.html', context)


@require_permission('treasury:transactions/export')
def vault_transactions_export(request):
    """Export filtered and scoped vault transactions to Excel."""
    from master_data.date_filter_utils import resolve_date_range
    vault_id = request.GET.get('vault_id')
    tx_type = request.GET.get('type')
    parsed_from, parsed_to, _, _, _ = resolve_date_range(request, default_preset='all_time')
    search = request.GET.get('search', '').strip()

    qs = VaultTransaction.objects.select_related('vault', 'created_by', 'reversal_transaction').order_by('-created_at')
    qs = get_scoped_queryset(qs, request.user, 'vaulttransaction')
    if vault_id:
        qs = qs.filter(vault_id=vault_id)
    if tx_type in ['inflow', 'outflow']:
        qs = qs.filter(transaction_type=tx_type)
    if parsed_from:
        qs = qs.filter(created_at__date__gte=parsed_from)
    if parsed_to:
        qs = qs.filter(created_at__date__lte=parsed_to)
    if search:
        qs = filter_by_arabic_search(qs, search, ['description', 'vault__name'])

    columns = [
        {'header': 'التاريخ والوقت', 'key': lambda t: t.created_at.strftime('%Y-%m-%d %H:%M') if t.created_at else '', 'width': 20, 'align': 'center'},
        {'header': 'الخزنة', 'key': lambda t: t.vault.name if t.vault else '', 'width': 24, 'align': 'right'},
        {'header': 'نوع الحركة', 'key': lambda t: 'إيداع (Inflow)' if t.transaction_type == 'inflow' else 'صرف (Outflow)', 'width': 18, 'align': 'center'},
        {'header': 'المبلغ (ج.م)', 'key': lambda t: float(t.amount or 0), 'format': '#,##0.00', 'width': 18, 'align': 'right'},
        {'header': 'البيان', 'key': lambda t: t.description or '', 'width': 36, 'align': 'right'},
        {'header': 'المسئول', 'key': lambda t: (t.created_by.name or t.created_by.username) if t.created_by else '', 'width': 22, 'align': 'right'},
    ]
    return export_to_excel_response(
        qs,
        columns,
        filename="vault_transactions_export",
        sheet_title="حركات الخزن",
        report_title="سجل حركات وسندات الخزن النقدية",
        user=request.user,
    )


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
        if not can_user_access_object(request.user, dest_vault, 'transfer'):
            return render_forbidden_response(request, "لا تمتلك صلاحية التحويل إلى هذه الخزنة المستلمة.")

        try:
            out_tx, in_tx = TreasuryService.transfer_funds(
                source_vault=source_vault,
                destination_vault=dest_vault,
                amount=Decimal(amount),
                user=request.user,
                notes=notes
            )
            if request.FILES.getlist('attachments'):
                from master_data.media_service import store_attachments_from_request
                store_attachments_from_request(out_tx, request)
            messages.success(request, f"تم التحويل بنجاح بقيمة {Decimal(amount):,.2f} ج.م من {source_vault.name} إلى {dest_vault.name}.")
            return redirect('vaults_list')
        except (ValidationError, Exception) as e:
            messages.error(request, str(e.message if hasattr(e, 'message') else e))
            return redirect('vaults_list')

    source_vaults = ScopeResolutionService.get_scoped_choices(request.user, 'vaults', 'treasury')
    dest_vaults = source_vaults
    raw_source_vault = request.GET.get('source_vault') or request.GET.get('vault_id')
    selected_source_vault_id = int(raw_source_vault) if raw_source_vault and str(raw_source_vault).isdigit() else None

    context = {
        'source_vaults': source_vaults,
        'destination_vaults': dest_vaults,
        'selected_source_vault_id': selected_source_vault_id,
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
    if not can_user_access_object(request.user, tx.vault, 'withdraw'):
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
    Create a new Vault (Cash Safe or Bank Account) using VaultService.
    """
    from accounts.scope_service import ScopeResolutionService
    if request.method == 'POST':
        data = {
            'name': request.POST.get('name', '').strip(),
            'vault_type': request.POST.get('vault_type', 'cash'),
            'assigned_user': request.POST.get('assigned_user') or None,
            'area': request.POST.get('area') or None,
            'is_rep_vault': request.POST.get('is_rep_vault') == 'on',
            'is_active': request.POST.get('is_active', 'on') == 'on',
            'initial_balance': request.POST.get('initial_balance') or request.POST.get('current_balance') or '0.00',
        }
        try:
            vault = VaultService.create_vault(data, request.user, request=request)
            messages.success(request, f"تم إنشاء الخزنة ({vault.name}) بنجاح برقم مسلسل #{vault.serial_num}.")
            return redirect('vaults_list')
        except ValidationError as e:
            messages.error(request, str(e.message if hasattr(e, 'message') else e))
        except Exception as e:
            messages.error(request, f"خطأ أثناء إنشاء الخزنة: {e}")

    areas = ScopeResolutionService.get_scoped_choices(request.user, 'governorates', 'treasury')
    assignees = get_visible_assignees_queryset(request.user, 'treasury')
    return render(request, 'treasury/vault_form.html', {
        'is_create': True,
        'areas': areas,
        'users': assignees,
    })


@require_permission('treasury:vaults/manage')
def vault_edit(request, pk):
    """
    Edit Vault details, custodian, branch, and status using VaultService.
    """
    from accounts.scope_service import ScopeResolutionService
    vault = get_object_or_404(Vault, pk=pk)
    if not can_user_access_object(request.user, vault, 'edit'):
        return render_forbidden_response(request, "لا تملك صلاحية تعديل بيانات هذه الخزنة.")

    if request.method == 'POST':
        data = {
            'name': request.POST.get('name', '').strip(),
            'vault_type': request.POST.get('vault_type', vault.vault_type),
            'assigned_user': request.POST.get('assigned_user') or None,
            'area': request.POST.get('area') or None,
            'is_rep_vault': request.POST.get('is_rep_vault') == 'on',
            'is_active': request.POST.get('is_active') == 'on',
        }
        try:
            vault = VaultService.update_vault(vault, data, request.user, request=request)
            messages.success(request, f"تم تحديث بيانات الخزنة ({vault.name}) بنجاح.")
            return redirect('vault_detail', pk=vault.pk)
        except ValidationError as e:
            messages.error(request, str(e.message if hasattr(e, 'message') else e))
        except Exception as e:
            messages.error(request, f"خطأ أثناء تحديث الخزنة: {e}")

    areas = ScopeResolutionService.get_scoped_choices(request.user, 'governorates', 'treasury')
    assignees = get_visible_assignees_queryset(request.user, 'treasury')
    return render(request, 'treasury/vault_form.html', {
        'is_create': False,
        'vault': vault,
        'areas': areas,
        'users': assignees,
    })


@require_permission(['treasury:vaults/manage', 'treasury:vaults/delete'])
def vault_delete(request, pk):
    """
    Safely delete an empty vault with zero balance and no transaction history.
    """
    if request.method != 'POST':
        return render_forbidden_response(request, "طريقة الطلب غير مسموح بها.")

    vault = get_object_or_404(Vault, pk=pk)
    if not can_user_access_object(request.user, vault, 'delete'):
        return render_forbidden_response(request, "لا تملك صلاحية حذف هذه الخزنة.")

    try:
        VaultService.delete_vault(vault, request.user, request=request)
        messages.success(request, "تم حذف الخزنة بنجاح.")
    except ValidationError as e:
        messages.error(request, str(e.message if hasattr(e, 'message') else e))
    except Exception as e:
        messages.error(request, f"تعذر حذف الخزنة: {e}")

    return redirect('vaults_list')


@require_permission(['treasury:payment_requests/list', 'treasury:payments/requests'])
def vendor_payment_requests_list(request):
    from master_data.filter_utils import parse_multi_str, parse_single_int
    from master_data.date_filter_utils import resolve_date_range

    status_labels = dict(VendorPaymentRequest.STATUS_CHOICES)
    selected_statuses = [s for s in parse_multi_str(request.GET, 'status') if s in status_labels]
    status_filter = selected_statuses[0] if len(selected_statuses) == 1 else 'all'
    supplier_id_int = parse_single_int(request.GET, 'supplier')
    supplier_filter = str(supplier_id_int) if supplier_id_int else ''
    search = request.GET.get('search', '').strip()
    parsed_from, parsed_to, active_preset, date_from, date_to = resolve_date_range(request, default_preset='all_time')

    qs = VendorPaymentRequest.objects.select_related(
        'supplier', 'purchase_order', 'preferred_vault', 'created_by', 'vendor_payment'
    ).all().order_by('-serial_num')
    qs = get_scoped_queryset(qs, request.user, 'vendorpaymentrequest')

    active_filters = []

    if selected_statuses:
        qs = qs.filter(status__in=selected_statuses)
        for st in selected_statuses:
            active_filters.append({'label': 'الحالة', 'value': status_labels.get(st, st), 'param': 'status', 'remove_value': st})

    if supplier_id_int:
        qs = qs.filter(supplier_id=supplier_id_int)
        s_obj = ScopeResolutionService.get_scoped_choices(request.user, 'suppliers', 'treasury').filter(id=supplier_id_int).first()
        active_filters.append({'label': 'المورد', 'value': s_obj.name if s_obj else supplier_filter, 'param': 'supplier'})

    if parsed_from:
        qs = qs.filter(request_date__gte=parsed_from)
        active_filters.append({'label': 'من تاريخ', 'value': date_from, 'param': 'date_from'})

    if parsed_to:
        qs = qs.filter(request_date__lte=parsed_to)
        active_filters.append({'label': 'إلى تاريخ', 'value': date_to, 'param': 'date_to'})

    if search:
        qs = filter_by_arabic_search(qs, search, ['request_number', 'supplier__name', 'purchase_order__order_number'])
        active_filters.append({'label': 'بحث', 'value': search, 'param': 'search'})

    suppliers = get_bounded_select_options(
        ScopeResolutionService.get_scoped_choices(request.user, 'suppliers', 'treasury'),
        selected_id=supplier_filter,
        limit=100,
    )

    agg = qs.aggregate(
        total_requests=Count('id'),
        total_amount=Sum('amount'),
        pending_count=Count('id', filter=Q(status='pending')),
        executed_count=Count('id', filter=Q(status='executed')),
    )
    stats = {
        'total_requests': agg['total_requests'] or 0,
        'total_amount': agg['total_amount'] or Decimal('0.00'),
        'pending_count': agg['pending_count'] or 0,
        'executed_count': agg['executed_count'] or 0,
    }

    paginator, page_obj = paginate_queryset(request, qs, default_per_page=25, max_per_page=100)

    vpr_status_options = [{'value': k, 'label': v} for k, v in VendorPaymentRequest.STATUS_CHOICES]
    selected_vpr_status_items = [o for o in vpr_status_options if o['value'] in selected_statuses]

    context = {
        'requests': page_obj.object_list,
        'page_obj': page_obj,
        'paginator': paginator,
        'vpr_status_options': vpr_status_options,
        'selected_vpr_status_items': selected_vpr_status_items,
        'selected_statuses': selected_statuses,
        'active_preset': active_preset,
        'current_status': status_filter,
        'selected_supplier': supplier_filter,
        'search_query': search,
        'date_from': date_from,
        'date_to': date_to,
        'suppliers': suppliers,
        'active_filters': active_filters,
        'active_filters_count': len(active_filters),
        'total_count': paginator.count,
        'stats': stats,
    }
    return render(request, 'treasury/vendor_payment_requests_list.html', context)


@require_permission(['treasury:payment_requests/create', 'treasury:payments/create'])
def vendor_payment_request_create(request):
    """
    Requirement B6: Remove payment-requests/create/ completely; all payment creation
    routes use treasury/payments/create/. Redirect directly to vendor_payment_create,
    preserving query parameters (e.g. ?po=... or ?supplier=...).
    """
    query_str = request.META.get('QUERY_STRING', '')
    url = reverse('vendor_payment_create')
    if query_str:
        url = f"{url}?{query_str}"
    return redirect(url)


@require_permission(['treasury:payment_requests/list', 'treasury:payments/requests'])
def vendor_payment_request_detail(request, pk):
    req_obj = get_object_or_404(
        VendorPaymentRequest.objects.select_related(
            'supplier', 'supplier__area', 'purchase_order', 'preferred_vault', 'vendor_payment',
            'created_by', 'approved_by', 'executed_by'
        ),
        pk=pk
    )

    if not can_user_access_object(request.user, req_obj, 'view'):
        return render_forbidden_response(request, "غير مصرح لك بعرض هذا الطلب خارج نطاقك الجغرافي.")

    can_approve = (
        has_perm_or_admin(request.user, ['treasury:payment_requests/approve', 'treasury:payments/approve']) and
        can_user_access_object(request.user, req_obj, 'approve') and
        req_obj.status == 'pending'
    )
    can_execute = (
        has_perm_or_admin(request.user, ['treasury:payment_requests/execute', 'treasury:payments/create']) and
        req_obj.status == 'approved' and req_obj.vendor_payment is None
    )
    can_cancel = (
        (has_perm_or_admin(request.user, 'treasury:payment_requests/delete') or req_obj.created_by_id == request.user.id) and
        req_obj.status in ['pending', 'approved']
    )

    vaults = ScopeResolutionService.get_scoped_choices(request.user, 'vaults', 'treasury')
    timeline_events = build_payment_request_timeline(req_obj)

    context = {
        'request_obj': req_obj,
        'can_approve': can_approve,
        'can_execute': can_execute,
        'can_cancel': can_cancel,
        'vaults': vaults,
        'timeline_events': timeline_events,
    }
    return render(request, 'treasury/vendor_payment_request_detail.html', context)


@login_required
def vendor_payment_request_action(request, pk, action):
    if request.method != 'POST':
        messages.error(request, "طريقة الطلب غير صالحة. يلزم استخدام طلب آمن (POST).")
        return redirect('vendor_payment_request_detail', pk=pk)

    req_obj = get_object_or_404(VendorPaymentRequest, pk=pk)

    try:
        if action == 'approve':
            if not has_perm_or_admin(request.user, ['treasury:payment_requests/approve', 'treasury:payments/approve']):
                return render_forbidden_response(request, "ليس لديك صلاحية اعتماد طلبات الصرف للموردين.")
            if not can_user_access_object(request.user, req_obj, 'approve'):
                messages.error(request, "لا يمكنك اعتماد طلب صرف قمت بإنشائه بنفسك أو يقع خارج نطاق إدارتك.")
                return redirect('vendor_payment_request_detail', pk=pk)

            notes = request.POST.get('approval_notes', '')
            VendorPaymentRequestService.approve_request(req_obj, request.user, notes=notes)
            messages.success(request, f"تم اعتماد طلب الصرف {req_obj.request_number} بنجاح.")

        elif action == 'reject':
            if not has_perm_or_admin(request.user, ['treasury:payment_requests/approve', 'treasury:payments/approve']):
                return render_forbidden_response(request, "ليس لديك صلاحية رفض طلبات الصرف للموردين.")
            if not can_user_access_object(request.user, req_obj, 'reject'):
                messages.error(request, "لا يمكنك رفض طلب صرف قمت بإنشائه بنفسك أو يقع خارج نطاق إدارتك.")
                return redirect('vendor_payment_request_detail', pk=pk)

            reason = request.POST.get('rejection_reason', '').strip()
            if not reason:
                messages.error(request, "يرجى كتابة سبب رفض طلب الصرف.")
                return redirect('vendor_payment_request_detail', pk=pk)

            VendorPaymentRequestService.reject_request(req_obj, request.user, reason=reason)
            messages.warning(request, f"تم رفض طلب الصرف {req_obj.request_number}.")

        elif action == 'execute':
            if not has_perm_or_admin(request.user, ['treasury:payment_requests/execute', 'treasury:payments/create']):
                return render_forbidden_response(request, "ليس لديك صلاحية تنفيذ وصرف طلبات سداد الموردين.")
            if not can_user_access_object(request.user, req_obj, 'execute'):
                return render_forbidden_response(request, "غير مصرح لك بتنفيذ طلب صرف خارج نطاقك.")

            vault_id = request.POST.get('vault') or getattr(req_obj.preferred_vault, 'id', None)
            if not vault_id:
                messages.error(request, "يرجى تحديد الخزنة المصروف منها.")
                return redirect('vendor_payment_request_detail', pk=pk)

            vault = get_object_or_404(Vault, id=vault_id)
            if not can_user_access_object(request.user, vault, 'transfer'):
                return render_forbidden_response(request, "غير مصرح لك بالصرف من هذه الخزنة.")

            payment_method = request.POST.get('payment_method', 'cash')
            reference_number = request.POST.get('reference_number', '').strip()
            notes = request.POST.get('notes', '').strip()

            _, payment = VendorPaymentRequestService.execute_request(
                req_obj,
                user=request.user,
                vault=vault,
                payment_method=payment_method,
                reference_number=reference_number,
                notes=notes
            )
            messages.success(request, f"تم صرف طلب السداد بنجاح وتوليد سند الصرف #{payment.serial_num}.")

        elif action == 'cancel':
            is_creator = (req_obj.created_by_id == request.user.id)
            can_cancel = is_creator or (
                has_perm_or_admin(request.user, 'treasury:payment_requests/delete')
                and can_user_access_object(request.user, req_obj, 'delete')
            )
            if not can_cancel:
                return render_forbidden_response(request, "غير مصرح لك بإلغاء هذا الطلب.")
            reason = request.POST.get('rejection_reason', '') or request.POST.get('reason', 'إلغاء يدوي')
            VendorPaymentRequestService.cancel_request(req_obj, request.user, reason=reason)
            messages.warning(request, f"تم إلغاء طلب الصرف {req_obj.request_number}.")

        else:
            messages.error(request, "إجراء غير معروف.")
    except ValidationError as e:
        messages.error(request, str(e.message if hasattr(e, 'message') else e))

    return redirect('vendor_payment_request_detail', pk=pk)


@require_permission('treasury:payment_requests/export')
def vendor_payment_requests_export(request):
    from master_data.date_filter_utils import resolve_date_range

    status_filter = request.GET.get('status', 'all')
    supplier_filter = request.GET.get('supplier')
    search = request.GET.get('search', '').strip()
    date_from, date_to, _, _, _ = resolve_date_range(request, default_preset='all_time')

    qs = VendorPaymentRequest.objects.select_related('supplier', 'purchase_order', 'preferred_vault', 'created_by').order_by('-serial_num')
    qs = get_scoped_queryset(qs, request.user, 'vendorpaymentrequest')

    if status_filter != 'all':
        qs = qs.filter(status=status_filter)
    if supplier_filter:
        qs = qs.filter(supplier_id=supplier_filter)
    if date_from:
        qs = qs.filter(request_date__gte=date_from)
    if date_to:
        qs = qs.filter(request_date__lte=date_to)
    if search:
        qs = filter_by_arabic_search(qs, search, ['request_number', 'supplier__name', 'purchase_order__order_number'])

    columns = [
        {'header': 'رقم الطلب', 'key': 'request_number', 'width': 18, 'align': 'center'},
        {'header': 'المورد', 'key': lambda r: r.supplier.name, 'width': 35, 'align': 'right'},
        {'header': 'أمر الشراء المرتبط', 'key': lambda r: r.purchase_order.order_number if r.purchase_order else '-', 'width': 20, 'align': 'center'},
        {'header': 'المبلغ المطلوب (ج.م)', 'key': lambda r: float(r.amount) if r.amount is not None else 0.0, 'format': '#,##0.00', 'width': 18, 'align': 'right'},
        {'header': 'الخزنة المقترحة', 'key': lambda r: r.preferred_vault.name if r.preferred_vault else '-', 'width': 22, 'align': 'right'},
        {'header': 'تاريخ الطلب', 'key': lambda r: r.request_date.strftime('%Y-%m-%d') if r.request_date else '', 'width': 16, 'align': 'center'},
        {'header': 'الحالة', 'key': lambda r: r.status_display_ar, 'width': 18, 'align': 'center'},
        {'header': 'المنشئ', 'key': lambda r: r.created_by.get_full_name() or r.created_by.username if r.created_by else '', 'width': 22, 'align': 'right'},
        {'header': 'ملاحظات', 'key': lambda r: r.notes or '', 'width': 30, 'align': 'right'},
    ]

    return export_to_excel_response(qs, columns, filename="vendor_payment_requests_export", sheet_title="طلبات صرف الموردين")


@require_permission('treasury:transactions/create')
def vault_deposit(request):
    """
    Deposit cash/funds into an authorized vault.
    """
    preselected_vault_id = request.GET.get('vault') or request.POST.get('vault_id')
    available_vaults = ScopeResolutionService.get_scoped_choices(request.user, 'vaults', 'treasury')

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
            if request.FILES.getlist('attachments'):
                from master_data.media_service import store_attachments_from_request
                store_attachments_from_request(tx, request)
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
    available_vaults = ScopeResolutionService.get_scoped_choices(request.user, 'vaults', 'treasury')

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
            if request.FILES.getlist('attachments'):
                from master_data.media_service import store_attachments_from_request
                store_attachments_from_request(tx, request)
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

