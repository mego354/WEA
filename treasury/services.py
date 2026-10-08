from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError
from .models import Vault, VendorAccount, VendorTransaction, VendorInstallment, VendorPayment, Settlement, VaultTransaction
from contacts.models import Contact


class TreasuryService:

    @staticmethod
    @transaction.atomic
    def record_vendor_payment(supplier: Contact, vault: Vault, amount: Decimal, user,
                              payment_method='cash', reference_number='', notes=''):
        """
        Executes a vendor payment:
        1. Checks sufficient vault balance.
        2. Deducts amount from Vault and records VaultTransaction (outflow).
        3. Debits VendorAccount and posts VendorTransaction (debit purchase_payments).
        4. Matches open VendorInstallment records FIFO and creates Settlement records.
        5. Updates supplier balance.
        """
        amount = Decimal(str(amount))
        if amount <= Decimal('0.00'):
            raise ValidationError("مبلغ السداد يجب أن يكون أكبر من الصفر.")

        if vault.current_balance < amount:
            raise ValidationError(f"رصيد الخزنة ({vault.name}: {vault.current_balance:,.2f} ج.م) غير كافٍ لسداد {amount:,.2f} ج.م.")

        account = VendorAccount.get_or_create_for_supplier(supplier)

        # 1. Deduct Vault Balance
        vault.current_balance -= amount
        vault.save(update_fields=['current_balance'])

        # 2. Record Vault Transaction
        vault_tx = VaultTransaction.objects.create(
            vault=vault,
            transaction_type='outflow',
            amount=amount,
            running_balance=vault.current_balance,
            reference_type='vendor_payment',
            description=f"سداد نقدي للمورد {supplier.name}",
            created_by=user
        )

        # 3. Post Vendor Debit Transaction
        new_vendor_balance = account.current_balance - amount
        vendor_tx = VendorTransaction.objects.create(
            account=account,
            transaction_type='debit',
            reason='purchase_payments',
            transaction_date=timezone.now().date(),
            credit=Decimal('0.00'),
            debit=amount,
            running_balance=new_vendor_balance,
            description=f"سداد للمورد {supplier.name} من {vault.name}",
            notes=notes,
            created_by=user
        )

        # 4. Create Vendor Payment Record
        payment = VendorPayment.objects.create(
            supplier=supplier,
            vault=vault,
            payment_date=timezone.now().date(),
            amount=amount,
            payment_method=payment_method,
            reference_number=reference_number,
            notes=notes,
            status='cleared',
            debit_transaction=vendor_tx,
            created_by=user
        )

        vault_tx.reference_id = payment.serial_num
        vault_tx.save(update_fields=['reference_id'])

        # 5. FIFO Matching of open invoice installments
        remaining_to_allocate = amount
        open_installments = VendorInstallment.objects.filter(
            transaction__account=account,
            is_settled=False
        ).order_by('due_date', 'transaction__serial')

        for inst in open_installments:
            if remaining_to_allocate <= Decimal('0.00'):
                break

            allocated = min(remaining_to_allocate, inst.open_amount)
            inst.closed_amount += allocated
            inst.open_amount -= allocated
            if inst.open_amount <= Decimal('0.00'):
                inst.is_settled = True
            inst.save(update_fields=['closed_amount', 'open_amount', 'is_settled'])

            Settlement.objects.create(
                payment_transaction=vendor_tx,
                target_installment=inst,
                amount=allocated,
                created_by=user
            )

            remaining_to_allocate -= allocated

        # 6. Update Account Balance
        account.current_balance = new_vendor_balance
        account.last_transaction_date = vendor_tx.transaction_date
        account.save(update_fields=['current_balance', 'last_transaction_date', 'updated_at'])

        return payment
