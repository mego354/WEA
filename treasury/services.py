from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError
from .models import Vault, VendorAccount, VendorTransaction, VendorInstallment, VendorPayment, Settlement, VaultTransaction
from contacts.models import Contact
from accounts.services import AuditLogService
from purchases.models import PurchaseOrder


class TreasuryService:

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
        if vault_locked.current_balance < amount:
            raise ValidationError(f"رصيد الخزنة ({vault_locked.name}: {vault_locked.current_balance:,.2f} ج.م) غير كافٍ لسداد {amount:,.2f} ج.م.")

        # If linked to a purchase order, validate
        if purchase_order:
            if purchase_order.supplier_id != supplier.id:
                raise ValidationError("أمر الشراء المحدد لا ينتمي إلى هذا المورد.")
            if amount > purchase_order.outstanding_balance:
                raise ValidationError(
                    f"مبلغ السداد ({amount:,.2f} ج.م) يتجاوز الرصيد المستحق على أمر الشراء ({purchase_order.outstanding_balance:,.2f} ج.م)."
                )

        account = VendorAccount.get_or_create_for_supplier(supplier)
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

        # Deadlock prevention: lock in ascending ID order
        v_ids = sorted([source_vault.id, destination_vault.id])
        Vault.objects.select_for_update().filter(id__in=v_ids)

        src_locked = Vault.objects.get(id=source_vault.id)
        dst_locked = Vault.objects.get(id=destination_vault.id)

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
    def reverse_vault_transaction(tx_id=None, user=None, reason: str = '', transaction=None):
        """
        Reverses a posted VaultTransaction by executing an exact balancing entry.
        Preserves complete financial audit trail without destructive deletes.
        """
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

