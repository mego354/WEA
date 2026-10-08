from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import ValidationError

from .models import Vault, VendorAccount, VendorTransaction, VendorPayment, VaultTransaction
from .services import TreasuryService
from contacts.models import Contact


@login_required
def vendor_payments_list(request):
    payments = VendorPayment.objects.select_related('supplier', 'vault', 'created_by').order_by('-serial_num')
    return render(request, 'treasury/vendor_payments_list.html', {'payments': payments})


@login_required
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

    suppliers = Contact.objects.filter(is_supplier=True)
    vaults = Vault.objects.filter(is_active=True)
    initial_supplier = request.GET.get('supplier_id')

    context = {
        'suppliers': suppliers,
        'vaults': vaults,
        'selected_supplier_id': initial_supplier,
    }
    return render(request, 'treasury/vendor_payment_create.html', context)


@login_required
def accounting_vendors_list(request):
    """
    Vendor Statements & Balances (حسابات الموردين).
    Columns matching reference ERP:
    ['اسم الحساب', 'حد الائتمان', 'مدة الائتمان', 'الرصيد', 'قيمة أقدم مديونية', 'قيمة المديونية المتأخرة', 'تاريخ اخر عملية']
    """
    accounts = VendorAccount.objects.select_related('supplier', 'supplier__area').order_by('-current_balance')
    return render(request, 'treasury/accounting_vendors_list.html', {'accounts': accounts})


@login_required
def vendor_transactions_list(request):
    """
    Vendor Ledger Transactions (عمليات الموردين).
    Columns matching reference ERP:
    ['رقم الحركة', 'اسم الحساب', 'التاريخ', 'توصيف', 'تاريخ الاستحقاق', 'دائن', 'مدين', 'الرصيد', 'انشئ بواسطة']
    """
    vendor_id = request.GET.get('vendor_id')
    qs = VendorTransaction.objects.select_related('account', 'account__supplier', 'created_by').order_by('-serial')

    if vendor_id:
        qs = qs.filter(account__supplier_id=vendor_id)

    suppliers = Contact.objects.filter(is_supplier=True)

    context = {
        'transactions': qs,
        'suppliers': suppliers,
        'selected_vendor_id': vendor_id,
    }
    return render(request, 'treasury/vendor_transactions_list.html', context)


@login_required
def vaults_list(request):
    vaults = Vault.objects.select_related('assigned_user').order_by('serial_num')
    return render(request, 'treasury/vaults_list.html', {'vaults': vaults})


@login_required
def vault_transactions_list(request):
    vault_id = request.GET.get('vault_id')
    qs = VaultTransaction.objects.select_related('vault', 'created_by').order_by('-created_at')
    if vault_id:
        qs = qs.filter(vault_id=vault_id)

    vaults = Vault.objects.all()

    context = {
        'transactions': qs,
        'vaults': vaults,
        'selected_vault_id': vault_id,
    }
    return render(request, 'treasury/vault_transactions_list.html', context)
