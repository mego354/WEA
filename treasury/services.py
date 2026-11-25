from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError
from .models import (
    Vault, VendorAccount, VendorTransaction, VendorInstallment, VendorPayment,
    Settlement, VaultTransaction, VendorPaymentRequest
)
from contacts.models import Contact
from accounts.services import AuditLogService
from purchases.models import PurchaseOrder


class TreasuryService:

    @staticmethod
    @transaction.atomic
    def zero_vendor_balance(supplier: Contact, user, reason_note: str, adjustment_date=None, request=None):
        """
        Zeros a supplier's VendorAccount balance via a non-cash adjustment transaction.
        STRICT INVARIANTS:
        - Does NOT touch any Vault or create VaultTransaction / VendorPayment records.
        - Does NOT modify any individual PurchaseOrder.payment_status.
        - Preserves full VendorTransaction history and statements.
        - Writes SecurityAuditLog and emits notification on commit.
        """
        clean_reason = (reason_note or '').strip()
        if not clean_reason:
            raise ValidationError("يرجى إدخال سبب تصفير حساب المورد للتوثيق المحاسبي.")

        account = VendorAccount.get_or_create_for_supplier(supplier)
        account = VendorAccount.objects.select_for_update().get(pk=account.pk)
        previous_balance = account.current_balance or Decimal('0.00')
        if previous_balance == Decimal('0.00'):
            raise ValidationError("رصيد حساب المورد صفر بالفعل ولا يحتاج إلى تصفير.")

        tx_date = adjustment_date or timezone.now().date()
        if previous_balance > Decimal('0.00'):
            tx_type = 'debit'
            debit_amt = previous_balance
            credit_amt = Decimal('0.00')
        else:
            tx_type = 'credit'
            debit_amt = Decimal('0.00')
            credit_amt = abs(previous_balance)

        tx = VendorTransaction.objects.create(
            account=account,
            purchase_order=None,
            transaction_type=tx_type,
            reason='adjustment',
            transaction_date=tx_date,
            debit=debit_amt,
            credit=credit_amt,
            running_balance=Decimal('0.00'),
            description=f"تصفير رصيد حساب المورد (تسوية غير نقدية) - {clean_reason}"[:255],
            notes=clean_reason,
            created_by=user,
        )

        account.current_balance = Decimal('0.00')
        account.overdue_balance = Decimal('0.00')
        account.last_transaction_date = tx_date
        account.save(update_fields=['current_balance', 'overdue_balance', 'last_transaction_date', 'updated_at'])

        AuditLogService.log(
            action='update',
            action_type='VENDOR_BALANCE_ZEROED',
            module='treasury',
            actor=user,
            record_id=account.id,
            record_name=f"حساب المورد: {supplier.name}",
            description=(
                f"تصفير رصيد حساب المورد {supplier.name} من {previous_balance:,.2f} ج.م إلى 0.00 ج.م "
                f"(قيد تسوية #{tx.serial} - بدون تأثير على الخزن) - السبب: {clean_reason}"
            ),
            previous_values={'current_balance': str(previous_balance)},
            new_values={'current_balance': '0.00', 'transaction_serial': tx.serial, 'reason': clean_reason},
            reason=clean_reason,
            request=request,
        )

        try:
            from notifications.services import NotificationService
            from django.urls import reverse
            NotificationService.emit(
                event_code='treasury.vendor_balance_zeroed',
                target_obj=account,
                actor=user,
                title=f"تصفير رصيد حساب المورد {supplier.name}",
                body=f"تم تصفير الرصيد من {previous_balance:,.2f} ج.م إلى 0.00 ج.م (تسوية غير نقدية) - {clean_reason}",
                action_url=f"{reverse('vendor_transactions_list')}?vendor_id={supplier.id}",
                dedupe_key=f"treasury.vendor_balance_zeroed:{tx.serial}",
            )
        except Exception:
            pass

        return tx, previous_balance

    @staticmethod
    @transaction.atomic
    def record_vendor_settlement(
        supplier: Contact,
        amount: Decimal,
        direction: str,
        user,
        reason_note: str,
        settlement_date=None,
        reference: str = '',
        request=None,
    ):
        """
        Records a non-cash vendor account settlement / adjustment.
        STRICT INVARIANTS:
        - Affects VendorAccount.current_balance ONLY via VendorTransaction(reason='settlement').
        - direction='debit' reduces vendor payable (current_balance -= amount).
        - direction='credit' increases vendor payable (current_balance += amount).
        - Strictly ZERO Vault / VaultTransaction / VendorPayment / Inventory impact.
        - Never modifies PurchaseOrder.payment_status.
        - Writes SecurityAuditLog.
        """
        amount = Decimal(str(amount or '0.00')).quantize(Decimal('0.01'))
        if amount <= Decimal('0.00'):
            raise ValidationError("مبلغ التسوية يجب أن يكون أكبر من الصفر.")

        if direction not in ('debit', 'credit'):
            raise ValidationError("نوع التسوية يجب أن يكون مدين (تخفيض مستحق المورد) أو دائن (زيادة مستحق المورد).")

        clean_reason = (reason_note or '').strip()
        if not clean_reason:
            raise ValidationError("يرجى إدخال سبب التسوية للتوثيق المحاسبي.")

        clean_ref = (reference or '').strip()
        account = VendorAccount.get_or_create_for_supplier(supplier)
        account = VendorAccount.objects.select_for_update().get(pk=account.pk)
        previous_balance = account.current_balance or Decimal('0.00')

        if direction == 'debit':
            debit_amt = amount
            credit_amt = Decimal('0.00')
            new_balance = previous_balance - amount
        else:
            debit_amt = Decimal('0.00')
            credit_amt = amount
            new_balance = previous_balance + amount

        tx_date = settlement_date or timezone.now().date()
        ref_part = f" [مرجع: {clean_ref}]" if clean_ref else ""
        desc = f"تسوية حساب مورد (غير نقدية){ref_part} - {clean_reason}"[:255]

        tx = VendorTransaction.objects.create(
            account=account,
            purchase_order=None,
            transaction_type=direction,
            reason='settlement',
            transaction_date=tx_date,
            debit=debit_amt,
            credit=credit_amt,
            running_balance=new_balance,
            description=desc,
            notes=clean_reason,
            created_by=user,
        )

        account.current_balance = new_balance
        if new_balance <= Decimal('0.00'):
            account.overdue_balance = Decimal('0.00')
        elif (account.overdue_balance or Decimal('0.00')) > new_balance:
            account.overdue_balance = new_balance
        account.last_transaction_date = tx_date
        account.save(update_fields=['current_balance', 'overdue_balance', 'last_transaction_date', 'updated_at'])

        AuditLogService.log(
            action='create',
            action_type='VENDOR_SETTLEMENT_CREATED',
            module='treasury',
            actor=user,
            record_id=tx.id,
            record_name=f"تسوية حساب مورد #{tx.serial} ({supplier.name})",
            description=(
                f"تسجيل تسوية حساب غير نقدية للمورد {supplier.name} ({'مدين / تخفيض' if direction == 'debit' else 'دائن / زيادة'}) "
                f"بمبلغ {amount:,.2f} ج.م — الرصيد من {previous_balance:,.2f} إلى {new_balance:,.2f} ج.م (بدون تأثير على الخزن) - {clean_reason}"
            ),
            previous_values={'current_balance': str(previous_balance)},
            new_values={
                'current_balance': str(new_balance),
                'transaction_serial': tx.serial,
                'direction': direction,
                'amount': str(amount),
                'reference': clean_ref,
                'reason': clean_reason,
            },
            reason=clean_reason,
            request=request,
        )

        return tx, previous_balance

    @staticmethod
    @transaction.atomic
    def reverse_vendor_settlement(tx_id, user, reason_note: str = '', request=None):
        """
        Reverses a non-cash vendor settlement/adjustment transaction by posting an opposing entry.
        ZERO vault impact. Prevents double reversal.
        """
        tx = VendorTransaction.objects.select_for_update().select_related('account__supplier').get(pk=tx_id)
        if tx.reason not in ('settlement', 'adjustment'):
            raise ValidationError("يمكن عكس قيود التسويات والتعديلات الحسابية فقط.")
        if tx.is_reversed:
            raise ValidationError(f"قيد التسوية #{tx.serial} معكوس بالفعل.")

        account = VendorAccount.objects.select_for_update().get(pk=tx.account_id)
        previous_balance = account.current_balance or Decimal('0.00')
        amount = tx.debit if tx.transaction_type == 'debit' else tx.credit
        opp_type = 'credit' if tx.transaction_type == 'debit' else 'debit'
        if opp_type == 'credit':
            debit_amt, credit_amt = Decimal('0.00'), amount
            new_balance = previous_balance + amount
        else:
            debit_amt, credit_amt = amount, Decimal('0.00')
            new_balance = previous_balance - amount

        clean_reason = (reason_note or '').strip() or 'عكس قيد تسوية'
        tx_date = timezone.now().date()
        rev_tx = VendorTransaction.objects.create(
            account=account,
            purchase_order=None,
            transaction_type=opp_type,
            reason='settlement',
            transaction_date=tx_date,
            debit=debit_amt,
            credit=credit_amt,
            running_balance=new_balance,
            description=f"عكس تسوية #{tx.serial} - {clean_reason}"[:255],
            notes=clean_reason,
            created_by=user,
        )

        tx.is_reversed = True
        tx.reversal_transaction = rev_tx
        tx.save(update_fields=['is_reversed', 'reversal_transaction'])

        account.current_balance = new_balance
        account.last_transaction_date = tx_date
        account.save(update_fields=['current_balance', 'last_transaction_date', 'updated_at'])

        AuditLogService.log(
            action='update',
            action_type='VENDOR_SETTLEMENT_REVERSED',
            module='treasury',
            actor=user,
            record_id=tx.id,
            record_name=f"عكس تسوية مورد #{tx.serial}",
            description=(
                f"عكس تسوية حساب المورد {account.supplier.name} #{tx.serial} بمبلغ {amount:,.2f} ج.م "
                f"(قيد العكس #{rev_tx.serial} — بدون تأثير على الخزن)"
            ),
            previous_values={'current_balance': str(previous_balance), 'is_reversed': False},
            new_values={'current_balance': str(new_balance), 'is_reversed': True, 'reversal_serial': rev_tx.serial},
            reason=clean_reason,
            request=request,
        )

        return rev_tx

    @staticmethod
    @transaction.atomic
    def record_vendor_payment(supplier: Contact, vault: Vault, amount: Decimal, user,
                              purchase_order: PurchaseOrder = None, payment_date=None,
                              payment_method='cash', reference_number='', notes=''):
        """
        Executes a vendor payment:
        1. Checks sufficient vault balance using row-level locking (select_for_update).
        2. Deducts amount from Vault and records VaultTransaction (outflow).
        3. Debits VendorAccount and posts VendorTransaction (debit purchase_payments).
        4. Matches open VendorInstallment records or specific order installment and creates Settlement records.
        5. Updates supplier balance and purchase order paid balance.
        6. Logs audit event via AuditLogService.
        """
        amount = Decimal(str(amount))
        if amount <= Decimal('0.00'):
            raise ValidationError("مبلغ السداد يجب أن يكون أكبر من الصفر.")

        # Concurrency safety: Lock the vault record
        vault_locked = Vault.objects.select_for_update().get(id=vault.id)
        if not vault_locked.is_active:
            raise ValidationError(f"الخزنة ({vault_locked.name}) معطلة حالياً ولا يمكن الصرف منها.")
        if vault_locked.current_balance < amount:
            raise ValidationError(f"رصيد الخزنة ({vault_locked.name}: {vault_locked.current_balance:,.2f} ج.م) غير كافٍ لسداد {amount:,.2f} ج.م.")

        # If linked to a purchase order, lock and validate ownership/status (no per-order debt cap)
        if purchase_order:
            from purchases.models import PurchaseOrder
            purchase_order = PurchaseOrder.objects.select_for_update().get(pk=purchase_order.pk)
            if purchase_order.status == 'cancelled':
                raise ValidationError("لا يمكن تسجيل سداد لأمر شراء ملغى.")
            if purchase_order.supplier_id != supplier.id:
                raise ValidationError("أمر الشراء المحدد لا ينتمي إلى هذا المورد.")

        account = VendorAccount.get_or_create_for_supplier(supplier)
        account = VendorAccount.objects.select_for_update().get(pk=account.pk)
        p_date = payment_date or timezone.now().date()

        # 1. Deduct Vault Balance
        vault_locked.current_balance -= amount
        vault_locked.save(update_fields=['current_balance'])

        # 2. Record Vault Transaction
        vault_tx = VaultTransaction.objects.create(
            vault=vault_locked,
            transaction_type='outflow',
            amount=amount,
            running_balance=vault_locked.current_balance,
            reference_type='vendor_payment',
            description=f"سداد نقدي للمورد {supplier.name}" + (f" لأمر الشراء {purchase_order.order_number}" if purchase_order else ""),
            created_by=user
        )

        # 3. Post Vendor Debit Transaction
        new_vendor_balance = account.current_balance - amount
        vendor_tx = VendorTransaction.objects.create(
            account=account,
            purchase_order=purchase_order,
            transaction_type='debit',
            reason='purchase_payments',
            transaction_date=p_date,
            credit=Decimal('0.00'),
            debit=amount,
            running_balance=new_vendor_balance,
            description=f"سداد للمورد {supplier.name} من {vault_locked.name}" + (f" ({purchase_order.order_number})" if purchase_order else ""),
            notes=notes,
            created_by=user
        )

        # 4. Create Vendor Payment Record
        payment = VendorPayment.objects.create(
            purchase_order=purchase_order,
            supplier=supplier,
            vault=vault_locked,
            payment_date=p_date,
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

        # 5. Settlement matching: target purchase order installments first if linked, else FIFO
        remaining_to_allocate = amount
        if purchase_order:
            order_installments = VendorInstallment.objects.filter(
                transaction__purchase_order=purchase_order,
                is_settled=False
            ).order_by('due_date')
            for inst in order_installments:
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

        # Any remaining amount allocated to older open installments FIFO
        if remaining_to_allocate > Decimal('0.00'):
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
        account.last_transaction_date = p_date
        account.save(update_fields=['current_balance', 'last_transaction_date', 'updated_at'])

        # 7. Audit Logging
        AuditLogService.log(
            action_type='VENDOR_PAYMENT_CREATED',
            module='purchases',
            actor=user,
            record_id=payment.serial_num,
            record_name=f"سند صرف #{payment.serial_num} ({supplier.name})",
            description=f"تسجيل سند صرف للمورد {supplier.name} بمبلغ {amount:,.2f} ج.م من خزنة {vault_locked.name}" + (f" لأمر الشراء {purchase_order.order_number}" if purchase_order else ""),
            new_values={
                'serial_num': payment.serial_num,
                'supplier': supplier.name,
                'vault': vault_locked.name,
                'amount': str(amount),
                'purchase_order': purchase_order.order_number if purchase_order else None,
                'payment_method': payment_method,
                'payment_date': str(p_date),
                'new_vault_balance': str(vault_locked.current_balance),
                'new_supplier_balance': str(new_vendor_balance),
            }
        )

        return payment

    @staticmethod
    @transaction.atomic
    def transfer_funds(source_vault: Vault, destination_vault: Vault, amount: Decimal, user, notes: str = '', description: str = ''):
        """
        Executes an atomic funds transfer between two vaults:
        1. Validates amount and distinct vaults.
        2. Acquires row-level locks on both vaults in a fixed order (to prevent deadlocks).
        3. Validates source vault has sufficient balance.
        4. Deducts from source vault and records VaultTransaction (outflow).
        5. Adds to destination vault and records VaultTransaction (inflow).
        6. Logs security audit entry via AuditLogService.
        """
        transfer_desc = description or notes or "تحويل أموال بين الخزن"
        amount = Decimal(str(amount))
        if amount <= Decimal('0.00'):
            raise ValidationError("مبلغ التحويل يجب أن يكون أكبر من الصفر.")

        if source_vault.id == destination_vault.id:
            raise ValidationError("لا يمكن التحويل إلى نفس الخزنة.")

        # Deadlock prevention: lock in ascending ID order (evaluate queryset to acquire row locks!)
        v_ids = sorted([source_vault.id, destination_vault.id])
        locked_map = {
            v.id: v
            for v in Vault.objects.select_for_update().filter(id__in=v_ids).order_by('id')
        }
        src_locked = locked_map[source_vault.id]
        dst_locked = locked_map[destination_vault.id]

        if not src_locked.is_active:
            raise ValidationError(f"الخزنة المصدر ({src_locked.name}) معطلة حالياً.")
        if not dst_locked.is_active:
            raise ValidationError(f"الخزنة المحول إليها ({dst_locked.name}) معطلة حالياً.")

        if src_locked.current_balance < amount:
            raise ValidationError(
                f"رصيد الخزنة المصدر ({src_locked.name}: {src_locked.current_balance:,.2f} ج.م) غير كافٍ لتحويل {amount:,.2f} ج.م."
            )

        # 1. Deduct from source
        src_locked.current_balance -= amount
        src_locked.save(update_fields=['current_balance'])

        outflow_tx = VaultTransaction.objects.create(
            vault=src_locked,
            transaction_type='outflow',
            amount=amount,
            running_balance=src_locked.current_balance,
            reference_type='vault_transfer_out',
            reference_id=dst_locked.id,
            description=f"تحويل نقدي صادر إلى {dst_locked.name}" + (f" - {transfer_desc}" if transfer_desc != "تحويل أموال بين الخزن" else ""),
            created_by=user
        )

        # 2. Add to destination
        dst_locked.current_balance += amount
        dst_locked.save(update_fields=['current_balance'])

        inflow_tx = VaultTransaction.objects.create(
            vault=dst_locked,
            transaction_type='inflow',
            amount=amount,
            running_balance=dst_locked.current_balance,
            reference_type='vault_transfer_in',
            reference_id=src_locked.id,
            description=f"تحويل نقدي وارد من {src_locked.name}" + (f" - {transfer_desc}" if transfer_desc != "تحويل أموال بين الخزن" else ""),
            created_by=user
        )

        # 3. Audit log
        AuditLogService.log(
            action_type='VAULT_TRANSFER',
            module='treasury',
            actor=user,
            record_id=outflow_tx.id,
            record_name=f"تحويل نقدي #{outflow_tx.id}",
            description=f"تحويل مبلغ {amount:,.2f} ج.م من خزنة {src_locked.name} إلى خزنة {dst_locked.name}",
            new_values={
                'source_vault': src_locked.name,
                'destination_vault': dst_locked.name,
                'amount': str(amount),
                'source_new_balance': str(src_locked.current_balance),
                'destination_new_balance': str(dst_locked.current_balance),
                'outflow_tx_id': outflow_tx.id,
                'inflow_tx_id': inflow_tx.id,
            }
        )

        return outflow_tx, inflow_tx

    @staticmethod
    @transaction.atomic
    def reverse_vault_transaction(tx_id=None, user=None, reason: str = '', transaction=None, tx=None, **kwargs):
        """
        Reverses a posted VaultTransaction by executing an exact balancing entry.
        Preserves complete financial audit trail without destructive deletes.
        """
        if transaction is None:
            transaction = tx
        if transaction is not None:
            target_id = transaction.id if hasattr(transaction, 'id') else transaction
        elif hasattr(tx_id, 'id'):
            target_id = tx_id.id
        else:
            target_id = tx_id

        tx = VaultTransaction.objects.select_for_update().get(id=target_id)
        if tx.is_reversed:
            raise ValidationError(f"هذه الحركة (معرف #{tx.id}) معكوسة بالفعل مسبقاً.")

        if tx.reference_type == 'reversal':
            raise ValidationError("لا يمكن عكس حركة تسوية / عكس سابقة.")

        if tx.reference_type in ('vault_transfer_out', 'vault_transfer_in', 'vendor_payment', 'customer_collection'):
            raise ValidationError(
                "لا يمكن عكس حركة خزينة مرتبطة بعملية أخرى (تحويل بين خزن / سداد مورد / تحصيل عميل) بشكل منفرد حفاظاً على توازن القيد المزدوج."
            )

        vault_locked = Vault.objects.select_for_update().get(id=tx.vault_id)

        # Determine opposing direction
        if tx.transaction_type == 'inflow':
            # Reversing an inflow requires deducting the amount from vault
            if vault_locked.current_balance < tx.amount:
                raise ValidationError(
                    f"رصيد الخزنة الحالي ({vault_locked.current_balance:,.2f} ج.م) غير كافٍ لعكس هذا الإيداع بقيمة {tx.amount:,.2f} ج.م."
                )
            reversal_type = 'outflow'
            vault_locked.current_balance -= tx.amount
        else:
            # Reversing an outflow restores funds to vault
            reversal_type = 'inflow'
            vault_locked.current_balance += tx.amount

        vault_locked.save(update_fields=['current_balance'])

        reversal_tx = VaultTransaction.objects.create(
            vault=vault_locked,
            transaction_type=reversal_type,
            amount=tx.amount,
            running_balance=vault_locked.current_balance,
            reference_type='reversal',
            reference_id=tx.id,
            description=f"عكس حركة #{tx.id}: {tx.description}" + (f" [السبب: {reason}]" if reason else ""),
            created_by=user
        )

        tx.is_reversed = True
        tx.reversed_by = user
        tx.reversal_transaction = reversal_tx
        tx.save(update_fields=['is_reversed', 'reversed_by', 'reversal_transaction'])

        AuditLogService.log(
            action_type='VAULT_TRANSACTION_REVERSED',
            module='treasury',
            actor=user,
            record_id=tx.id,
            record_name=f"عكس حركة #{tx.id}",
            description=f"عكس حركة خزينة #{tx.id} ({tx.description}) بمبلغ {tx.amount:,.2f} ج.م. حركة العكس #{reversal_tx.id}",
            new_values={
                'original_tx_id': tx.id,
                'reversal_tx_id': reversal_tx.id,
                'vault': vault_locked.name,
                'amount': str(tx.amount),
                'new_balance': str(vault_locked.current_balance),
                'reason': reason
            }
        )

        return reversal_tx

    @staticmethod
    @transaction.atomic
    def record_vault_manual_transaction(vault: Vault, tx_type: str, amount: Decimal, user, description: str, notes: str = ''):
        """
        Records a manual deposit or expense into a Vault with concurrency locking.
        """
        amount = Decimal(str(amount))
        if amount <= Decimal('0.00'):
            raise ValidationError("مبلغ الحركة يجب أن يكون أكبر من الصفر.")

        if tx_type not in ['inflow', 'outflow']:
            raise ValidationError("نوع الحركة غير صالح (يجب أن يكون إيداع أو صرف).")

        vault_locked = Vault.objects.select_for_update().get(id=vault.id)

        if not vault_locked.is_active:
            raise ValidationError(f"الخزنة ({vault_locked.name}) معطلة ولا يمكن تنفيذ حركات عليها.")

        if tx_type == 'outflow' and vault_locked.current_balance < amount:
            raise ValidationError(
                f"رصيد الخزنة ({vault_locked.name}: {vault_locked.current_balance:,.2f} ج.م) غير كافٍ لصرف {amount:,.2f} ج.م."
            )

        if tx_type == 'inflow':
            vault_locked.current_balance += amount
        else:
            vault_locked.current_balance -= amount

        vault_locked.save(update_fields=['current_balance'])

        tx = VaultTransaction.objects.create(
            vault=vault_locked,
            transaction_type=tx_type,
            amount=amount,
            running_balance=vault_locked.current_balance,
            reference_type='manual_entry',
            description=description + (f" - {notes}" if notes else ""),
            created_by=user
        )

        AuditLogService.log(
            action_type='VAULT_MANUAL_TRANSACTION',
            module='treasury',
            actor=user,
            record_id=tx.id,
            record_name=f"حركة خزينة #{tx.id}",
            description=f"تسجيل حركة {tx.get_transaction_type_display()} بمبلغ {amount:,.2f} ج.م في خزنة {vault_locked.name}",
            new_values={
                'tx_id': tx.id,
                'vault': vault_locked.name,
                'type': tx_type,
                'amount': str(amount),
                'new_balance': str(vault_locked.current_balance),
                'description': description
            }
        )

        return tx

    @staticmethod
    @transaction.atomic
    def deposit_funds(vault: Vault, amount: Decimal, user, description: str, transaction_date=None, reference_number: str = '', notes: str = ''):
        """
        Executes a cash deposit into a vault:
        1. Validates positive amount and active vault status.
        2. Acquires row-level lock on the vault (select_for_update).
        3. Authoritatively updates vault current_balance.
        4. Records VaultTransaction (inflow) with running balance.
        5. Logs security audit trail via AuditLogService.
        """
        amount = Decimal(str(amount))
        if amount <= Decimal('0.00'):
            raise ValidationError("مبلغ الإيداع يجب أن يكون أكبر من الصفر.")

        vault_locked = Vault.objects.select_for_update().get(id=vault.id)
        if not vault_locked.is_active:
            raise ValidationError(f"الخزنة ({vault_locked.name}) معطلة حالياً ولا يمكن إيداع مبالغ بها.")

        vault_locked.current_balance += amount
        vault_locked.save(update_fields=['current_balance'])

        full_desc = description.strip()
        if reference_number:
            full_desc += f" (مرجع: {reference_number.strip()})"
        if notes:
            full_desc += f" - {notes.strip()}"

        tx = VaultTransaction.objects.create(
            vault=vault_locked,
            transaction_type='inflow',
            amount=amount,
            running_balance=vault_locked.current_balance,
            reference_type='deposit',
            description=full_desc,
            created_by=user
        )

        AuditLogService.log(
            action_type='VAULT_DEPOSIT',
            module='treasury',
            actor=user,
            record_id=tx.id,
            record_name=f"إيداع نقدي #{tx.id}",
            description=f"إيداع مبلغ {amount:,.2f} ج.م في خزنة {vault_locked.name} - {description}",
            new_values={
                'tx_id': tx.id,
                'vault': vault_locked.name,
                'amount': str(amount),
                'new_balance': str(vault_locked.current_balance),
                'reference_number': reference_number,
                'description': full_desc,
                'date': str(transaction_date or timezone.now().date())
            }
        )
        return tx

    @staticmethod
    @transaction.atomic
    def withdraw_funds(vault: Vault, amount: Decimal, user, description: str, transaction_date=None, reference_number: str = '', notes: str = ''):
        """
        Executes a cash withdrawal/expense from a vault:
        1. Validates positive amount and active vault status.
        2. Acquires row-level lock on the vault (select_for_update).
        3. Validates available balance; prevents overdrafts.
        4. Authoritatively updates vault current_balance.
        5. Records VaultTransaction (outflow) with running balance.
        6. Logs security audit trail via AuditLogService.
        """
        amount = Decimal(str(amount))
        if amount <= Decimal('0.00'):
            raise ValidationError("مبلغ الصرف / السحب يجب أن يكون أكبر من الصفر.")

        vault_locked = Vault.objects.select_for_update().get(id=vault.id)
        if not vault_locked.is_active:
            raise ValidationError(f"الخزنة ({vault_locked.name}) معطلة حالياً ولا يمكن صرف مبالغ منها.")

        if vault_locked.current_balance < amount:
            raise ValidationError(
                f"رصيد الخزنة ({vault_locked.name}: {vault_locked.current_balance:,.2f} ج.م) غير كافٍ لصرف {amount:,.2f} ج.م."
            )

        vault_locked.current_balance -= amount
        vault_locked.save(update_fields=['current_balance'])

        full_desc = description.strip()
        if reference_number:
            full_desc += f" (مرجع: {reference_number.strip()})"
        if notes:
            full_desc += f" - {notes.strip()}"

        tx = VaultTransaction.objects.create(
            vault=vault_locked,
            transaction_type='outflow',
            amount=amount,
            running_balance=vault_locked.current_balance,
            reference_type='withdrawal',
            description=full_desc,
            created_by=user
        )

        AuditLogService.log(
            action_type='VAULT_WITHDRAWAL',
            module='treasury',
            actor=user,
            record_id=tx.id,
            record_name=f"صرف نقدي #{tx.id}",
            description=f"صرف مبلغ {amount:,.2f} ج.م من خزنة {vault_locked.name} - {description}",
            new_values={
                'tx_id': tx.id,
                'vault': vault_locked.name,
                'amount': str(amount),
                'new_balance': str(vault_locked.current_balance),
                'reference_number': reference_number,
                'description': full_desc,
                'date': str(transaction_date or timezone.now().date())
            }
        )
        return tx


# Module-level convenience aliases
transfer_funds = TreasuryService.transfer_funds
reverse_vault_transaction = TreasuryService.reverse_vault_transaction
record_vault_manual_transaction = TreasuryService.record_vault_manual_transaction
deposit_funds = TreasuryService.deposit_funds
withdraw_funds = TreasuryService.withdraw_funds


class VendorPaymentRequestService:

    @classmethod
    @transaction.atomic
    def create_request(cls, supplier, amount, preferred_vault=None, purchase_order=None,
                       request_date=None, notes='', user=None):
        amount = Decimal(str(amount or '0.00'))
        if amount <= Decimal('0.00'):
            raise ValidationError("مبلغ طلب السداد يجب أن يكون أكبر من الصفر.")

        if purchase_order:
            if purchase_order.supplier_id != supplier.id:
                raise ValidationError("أمر الشراء المحدد لا ينتمي إلى هذا المورد.")
            if purchase_order.status == 'cancelled':
                raise ValidationError("لا يمكن إنشاء طلب سداد لأمر شراء ملغى.")

        req = VendorPaymentRequest.objects.create(
            supplier=supplier,
            purchase_order=purchase_order,
            amount=amount,
            preferred_vault=preferred_vault,
            request_date=request_date or timezone.now().date(),
            notes=notes,
            status='pending',
            created_by=user
        )

        from activities.models import ApprovalAuditLog
        ApprovalAuditLog.objects.create(
            record_type='payment_request',
            payment_request=req,
            action='submitted',
            actor=user,
            status_before='',
            status_after='pending',
            reason=f"إنشاء طلب سداد مورد بمبلغ {amount:,.2f} ج.م" + (f" لأمر الشراء {purchase_order.order_number}" if purchase_order else "")
        )

        AuditLogService.log(
            action_type='PAYMENT_REQUEST_CREATED',
            module='treasury',
            actor=user,
            record_id=req.id,
            record_name=req.request_number,
            description=f"إنشاء طلب سداد مورد {supplier.name} بمبلغ {amount:,.2f} ج.م",
            new_values={
                'request_number': req.request_number,
                'supplier': supplier.name,
                'amount': str(amount),
                'purchase_order': purchase_order.order_number if purchase_order else None
            }
        )
        return req

    @classmethod
    @transaction.atomic
    def approve_request(cls, payment_request, user, notes=''):
        req = VendorPaymentRequest.objects.select_for_update().get(pk=payment_request.pk)
        if req.status != 'pending':
            raise ValidationError(f"لا يمكن اعتماد طلب سداد بحالة '{req.status_display_ar}'.")

        if req.created_by_id == user.id and not (user.is_superuser or getattr(user, 'is_super_admin', False)):
            raise ValidationError("لا يمكنك اعتماد طلب سداد قمت بإنشائه بنفسك.")

        req.status = 'approved'
        req.approved_by = user
        req.approved_at = timezone.now()
        req.save(update_fields=['status', 'approved_by', 'approved_at', 'updated_at'])

        from activities.models import ApprovalAuditLog
        ApprovalAuditLog.objects.create(
            record_type='payment_request',
            payment_request=req,
            action='approved',
            actor=user,
            status_before='pending',
            status_after='approved',
            reason=notes or "اعتماد طلب سداد المورد"
        )

        AuditLogService.log(
            action_type='PAYMENT_REQUEST_APPROVED',
            module='treasury',
            actor=user,
            record_id=req.id,
            record_name=req.request_number,
            description=f"اعتماد طلب سداد مورد {req.request_number}",
            new_values={'status': 'approved', 'approved_by': user.username, 'notes': notes}
        )
        return req

    @classmethod
    @transaction.atomic
    def reject_request(cls, payment_request, user, reason=''):
        req = VendorPaymentRequest.objects.select_for_update().get(pk=payment_request.pk)
        if req.status != 'pending':
            raise ValidationError(f"لا يمكن رفض طلب سداد بحالة '{req.status_display_ar}'.")

        if req.created_by_id == user.id and not (user.is_superuser or getattr(user, 'is_super_admin', False)):
            raise ValidationError("لا يمكنك رفض طلب سداد قمت بإنشائه بنفسك.")

        req.status = 'rejected'
        req.rejection_reason = reason or "تم الرفض بواسطة الإدارة"
        req.save(update_fields=['status', 'rejection_reason', 'updated_at'])

        from activities.models import ApprovalAuditLog
        ApprovalAuditLog.objects.create(
            record_type='payment_request',
            payment_request=req,
            action='rejected',
            actor=user,
            status_before='pending',
            status_after='rejected',
            reason=reason or "رفض طلب سداد المورد"
        )

        AuditLogService.log(
            action_type='PAYMENT_REQUEST_REJECTED',
            module='treasury',
            actor=user,
            record_id=req.id,
            record_name=req.request_number,
            description=f"رفض طلب سداد مورد {req.request_number}: {reason}",
            new_values={'status': 'rejected', 'reason': reason}
        )
        return req

    @classmethod
    @transaction.atomic
    def execute_request(cls, payment_request, user, vault=None, payment_date=None,
                        payment_method='cash', reference_number='', notes=''):
        req = VendorPaymentRequest.objects.select_for_update().get(pk=payment_request.pk)
        if req.vendor_payment is not None or req.status == 'executed':
            serial_info = f" بموجب سند الصرف #{req.vendor_payment.serial_num}" if req.vendor_payment else ""
            raise ValidationError(f"تم صرف هذا الطلب مسبقاً{serial_info}.")

        if req.status != 'approved':
            raise ValidationError(f"لا يمكن تنفيذ وصرف طلب سداد بحالة '{req.status_display_ar}'. يجب اعتماده أولاً.")

        target_vault = vault or req.preferred_vault
        if not target_vault:
            raise ValidationError("يرجى تحديد خزنة الصرف لتنفيذ السداد.")

        payment = TreasuryService.record_vendor_payment(
            supplier=req.supplier,
            vault=target_vault,
            amount=req.amount,
            user=user,
            purchase_order=req.purchase_order,
            payment_date=payment_date or timezone.now().date(),
            payment_method=payment_method,
            reference_number=reference_number,
            notes=notes or req.notes
        )

        req.vendor_payment = payment
        req.status = 'executed'
        req.executed_by = user
        req.executed_at = timezone.now()
        req.save(update_fields=['vendor_payment', 'status', 'executed_by', 'executed_at', 'updated_at'])

        from activities.models import ApprovalAuditLog
        ApprovalAuditLog.objects.create(
            record_type='payment_request',
            payment_request=req,
            action='status_changed',
            actor=user,
            status_before='approved',
            status_after='executed',
            reason=f"تنفيذ وصرف المبلغ بموجب سند الصرف #{payment.serial_num} من {target_vault.name}"
        )

        AuditLogService.log(
            action_type='PAYMENT_REQUEST_EXECUTED',
            module='treasury',
            actor=user,
            record_id=req.id,
            record_name=req.request_number,
            description=f"تنفيذ صرف طلب السداد {req.request_number} وسند صرف #{payment.serial_num}",
            new_values={
                'status': 'executed',
                'payment_id': payment.id,
                'payment_serial': payment.serial_num,
                'vault': target_vault.name
            }
        )
        return req, payment

    @classmethod
    @transaction.atomic
    def cancel_request(cls, payment_request, user, reason=''):
        req = VendorPaymentRequest.objects.select_for_update().get(pk=payment_request.pk)
        if req.status not in ['pending', 'approved']:
            raise ValidationError(f"لا يمكن إلغاء طلب سداد بحالة '{req.status_display_ar}'.")

        prev_status = req.status
        req.status = 'cancelled'
        req.rejection_reason = reason or "تم الإلغاء"
        req.save(update_fields=['status', 'rejection_reason', 'updated_at'])

        from activities.models import ApprovalAuditLog
        ApprovalAuditLog.objects.create(
            record_type='payment_request',
            payment_request=req,
            action='cancelled',
            actor=user,
            status_before=prev_status,
            status_after='cancelled',
            reason=reason or "إلغاء طلب السداد"
        )
        AuditLogService.log(
            action_type='VENDOR_PAYMENT_REQUEST_CANCELLED',
            module='treasury',
            actor=user,
            record_id=req.id,
            record_name=req.request_number,
            description=f"إلغاء طلب سداد المورد {req.request_number}: {req.rejection_reason}",
            previous_values={'status': prev_status},
            new_values={'status': 'cancelled', 'reason': req.rejection_reason},
        )
        return req


def build_payment_request_timeline(req):
    events = []
    if req.created_at:
        events.append({
            'timestamp': req.created_at,
            'title': 'إنشاء طلب السداد',
            'badge': 'قيد الانتظار',
            'badge_class': 'bg-amber-100 text-amber-800 border border-amber-300',
            'dot_class': 'bg-amber-500',
            'user': req.created_by.get_full_name() or req.created_by.username if req.created_by else 'النظام',
            'notes': req.notes or f'تم إنشاء طلب صرف بمبلغ {req.amount:,.2f} ج.م'
        })
    if req.approved_at and req.approved_by:
        events.append({
            'timestamp': req.approved_at,
            'title': 'اعتماد طلب السداد',
            'badge': 'معتمد',
            'badge_class': 'bg-teal-100 text-teal-800 border border-teal-300',
            'dot_class': 'bg-teal-500',
            'user': req.approved_by.get_full_name() or req.approved_by.username,
            'notes': 'تم اعتماد الطلب من قبل الإدارة المالية'
        })
    if req.executed_at and req.executed_by:
        events.append({
            'timestamp': req.executed_at,
            'title': 'تنفيذ الصرف النقدي',
            'badge': 'تم الصرف',
            'badge_class': 'bg-emerald-100 text-emerald-800 border border-emerald-300',
            'dot_class': 'bg-emerald-500',
            'user': req.executed_by.get_full_name() or req.executed_by.username,
            'notes': f'تم صرف المبلغ وتوليد سند الصرف #{req.vendor_payment.serial_num}' if req.vendor_payment else 'تم تنفيذ السداد'
        })
    if req.status == 'rejected' and req.rejection_reason:
        events.append({
            'timestamp': req.updated_at,
            'title': 'رفض طلب السداد',
            'badge': 'مرفوض',
            'badge_class': 'bg-rose-100 text-rose-800 border border-rose-300',
            'dot_class': 'bg-rose-500',
            'user': 'الإدارة',
            'notes': req.rejection_reason
        })
    if req.status == 'cancelled':
        events.append({
            'timestamp': req.updated_at,
            'title': 'إلغاء الطلب',
            'badge': 'ملغي',
            'badge_class': 'bg-slate-100 text-slate-800 border border-slate-300',
            'dot_class': 'bg-slate-400',
            'user': 'المسؤول',
            'notes': req.rejection_reason or 'تم إلغاء الطلب'
        })

    from activities.models import ApprovalAuditLog
    approval_logs = ApprovalAuditLog.objects.filter(
        record_type='payment_request',
        payment_request=req
    ).select_related('actor').order_by('created_at')

    action_title_map = {
        'approved': ('اعتماد إداري', 'معتمد', 'bg-teal-100 text-teal-800 border border-teal-300', 'bg-teal-500'),
        'rejected': ('رفض الطلب', 'مرفوض', 'bg-rose-100 text-rose-800 border border-rose-300', 'bg-rose-500'),
        'status_changed': ('تنفيذ الصرف', 'منفذ', 'bg-emerald-100 text-emerald-800 border border-emerald-300', 'bg-emerald-500'),
        'executed': ('تنفيذ الصرف', 'منفذ', 'bg-emerald-100 text-emerald-800 border border-emerald-300', 'bg-emerald-500'),
        'cancelled': ('إلغاء الطلب', 'ملغي', 'bg-slate-100 text-slate-800 border border-slate-300', 'bg-slate-400'),
    }
    for log in approval_logs:
        if log.action in action_title_map:
            t, b, bc, dc = action_title_map[log.action]
            events.append({
                'timestamp': log.created_at,
                'title': t,
                'badge': b,
                'badge_class': bc,
                'dot_class': dc,
                'user': log.actor.get_full_name() or log.actor.username if log.actor else 'النظام',
                'notes': log.reason
            })

    events.sort(key=lambda x: x['timestamp'] if x.get('timestamp') else timezone.now())
    return events


class VaultService:
    """
    Enterprise service layer for Vault and Safe CRUD operations:
    - Atomic creation and initial opening balance setup
    - Custodian / User assignment and branch association
    - Strict financial transaction and balance integrity checks before deletion
    - Full SecurityAuditLog audit trails
    """

    @classmethod
    @transaction.atomic
    def create_vault(cls, data: dict, user, request=None):
        from master_data.models import Area
        from accounts.models import User

        name = data.get('name', '').strip()
        vault_type = data.get('vault_type', 'cash')
        is_rep_vault = data.get('is_rep_vault') in [True, 'on', 'true', 'True', '1', 1]
        is_active = data.get('is_active') in [True, 'on', 'true', 'True', '1', 1] if 'is_active' in data else True
        initial_balance_raw = (data.get('initial_balance') or data.get('current_balance') or '0.00')

        if not name:
            raise ValidationError("اسم الخزنة / الحساب حقل إلزامي.")

        if Vault.objects.filter(name__iexact=name).exists():
            raise ValidationError(f"توجد خزنة مسجلة مسبقاً بنفس الاسم ({name}).")

        assigned_user = None
        assigned_user_id = data.get('assigned_user')
        if assigned_user_id:
            assigned_user = User.objects.filter(id=assigned_user_id, is_active=True).first()

        area = None
        area_id = data.get('area')
        if area_id:
            area = Area.objects.filter(id=area_id).first()

        try:
            init_bal = Decimal(str(initial_balance_raw or '0.00'))
            if init_bal < Decimal('0.00'):
                raise ValidationError("الرصيد الافتتاحي لا يمكن أن يكون سالباً.")
        except Exception:
            raise ValidationError("قيمة الرصيد الافتتاحي غير صحيحة.")

        vault = Vault.objects.create(
            name=name,
            vault_type=vault_type,
            assigned_user=assigned_user,
            area=area,
            is_rep_vault=is_rep_vault,
            is_active=is_active,
            current_balance=init_bal
        )

        if init_bal > Decimal('0.00'):
            opening_tx = VaultTransaction.objects.create(
                vault=vault,
                transaction_type='inflow',
                amount=init_bal,
                running_balance=init_bal,
                reference_type='opening_balance',
                description=f"رصيد افتتاحي عند إنشاء الخزنة ({vault.name})",
                created_by=user
            )
            AuditLogService.log(
                action_type='VAULT_OPENING_BALANCE',
                module='treasury',
                actor=user,
                record_id=opening_tx.id,
                record_name=f"رصيد افتتاحي {vault.name}",
                description=f"تسجيل قيد رصيد افتتاحي بمبلغ {init_bal:,.2f} ج.م لخزنة {vault.name}",
                new_values={'vault': vault.name, 'amount': str(init_bal), 'tx_id': opening_tx.id},
                request=request
            )

        AuditLogService.log(
            action_type='VAULT_CREATED',
            module='treasury',
            actor=user,
            record_id=vault.id,
            record_name=vault.name,
            description=f"إنشاء خزنة جديدة: {vault.name} برقم مسلسل #{vault.serial_num} ورصيد افتتاحي {init_bal:,.2f} ج.م",
            new_values={
                'name': vault.name,
                'serial_num': vault.serial_num,
                'vault_type': vault.vault_type,
                'is_rep_vault': vault.is_rep_vault,
                'is_active': vault.is_active,
                'initial_balance': str(init_bal),
                'area': vault.area.name if vault.area else None,
                'assigned_user': vault.assigned_user.username if vault.assigned_user else None,
            },
            request=request
        )
        return vault

    @classmethod
    @transaction.atomic
    def update_vault(cls, vault: Vault, data: dict, user, request=None):
        from master_data.models import Area
        from accounts.models import User

        name = data.get('name', '').strip()
        vault_type = data.get('vault_type', vault.vault_type)
        is_rep_vault = data.get('is_rep_vault') in [True, 'on', 'true', 'True', '1', 1]
        is_active = data.get('is_active') in [True, 'on', 'true', 'True', '1', 1] if 'is_active' in data else True

        if not name:
            raise ValidationError("اسم الخزنة / الحساب حقل إلزامي.")

        if Vault.objects.filter(name__iexact=name).exclude(id=vault.id).exists():
            raise ValidationError(f"توجد خزنة أخرى مسجلة بنفس الاسم ({name}).")

        assigned_user = None
        assigned_user_id = data.get('assigned_user')
        if assigned_user_id:
            assigned_user = User.objects.filter(id=assigned_user_id, is_active=True).first()

        area = None
        area_id = data.get('area')
        if area_id:
            area = Area.objects.filter(id=area_id).first()

        prev_values = {
            'name': vault.name,
            'vault_type': vault.vault_type,
            'is_rep_vault': vault.is_rep_vault,
            'is_active': vault.is_active,
            'area': vault.area.name if vault.area else None,
            'assigned_user': vault.assigned_user.username if vault.assigned_user else None,
        }

        vault.name = name
        vault.vault_type = vault_type
        vault.assigned_user = assigned_user
        vault.area = area
        vault.is_rep_vault = is_rep_vault
        vault.is_active = is_active
        vault.save()

        new_values = {
            'name': vault.name,
            'vault_type': vault.vault_type,
            'is_rep_vault': vault.is_rep_vault,
            'is_active': vault.is_active,
            'area': vault.area.name if vault.area else None,
            'assigned_user': vault.assigned_user.username if vault.assigned_user else None,
        }

        AuditLogService.log(
            action_type='VAULT_UPDATED',
            module='treasury',
            actor=user,
            record_id=vault.id,
            record_name=vault.name,
            description=f"تحديث بيانات الخزنة: {vault.name} (#{vault.serial_num})",
            previous_values=prev_values,
            new_values=new_values,
            request=request
        )
        return vault

    @classmethod
    @transaction.atomic
    def delete_vault(cls, vault: Vault, user, request=None):
        # 1. Financial transactions check
        if VaultTransaction.objects.filter(vault=vault).exists():
            raise ValidationError("لا يمكن حذف الخزنة لوجود حركات مالية مسجلة عليها. يمكنك تعطيل الخزنة بدلاً من حذفها.")

        # 2. Balance check
        if vault.current_balance != Decimal('0.00'):
            raise ValidationError(f"لا يمكن حذف الخزنة لوجود رصيد حالي بها ({vault.current_balance:,.2f} ج.م). يجب تصفية الرصيد أولاً.")

        # 3. Vendor payments check
        if VendorPayment.objects.filter(vault=vault).exists():
            raise ValidationError("لا يمكن حذف الخزنة لوجود سندات صرف موردين مسجلة عليها.")

        # 4. Sales collections check
        from sales.models import Collection
        if Collection.objects.filter(vault=vault).exists():
            raise ValidationError("لا يمكن حذف الخزنة لوجود سندات تحصيل مبيعات مسجلة عليها.")

        v_id = vault.id
        v_name = vault.name
        v_serial = vault.serial_num

        vault.delete()

        AuditLogService.log(
            action_type='VAULT_DELETED',
            module='treasury',
            actor=user,
            record_id=v_id,
            record_name=v_name,
            description=f"حذف الخزنة: {v_name} (#{v_serial})",
            request=request
        )
        return True


