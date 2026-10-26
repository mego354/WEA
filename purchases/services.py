from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError
from .models import PurchaseOrder, PurchaseOrderItem, PurchaseReturnOrder, PurchaseReturnOrderItem
from inventory.models import InventoryMemo, InventoryMemoItem, InventoryStock, InventoryLot
from treasury.models import VendorAccount, VendorTransaction, VendorInstallment



class PurchaseOrderService:

    @staticmethod
    @transaction.atomic
    def create_order(supplier, target_warehouse, order_date, items_data, user, 
                     delivery_address=None, expected_delivery_date=None,
                     custom_discount_percentage=Decimal('0.00'), shipping_fees=Decimal('0.00'), notes=""):
        """
        Creates a new purchase order with validated line items.
        """
        if not items_data:
            raise ValidationError("يجب إضافة صنف واحد على الأقل في أمر الشراء.")

        from master_data.models import PurchaseSettings
        from accounts.permissions import is_manager_or_higher
        purchase_settings = PurchaseSettings.get_settings()

        initial_status = 'pending'
        approved_by = None
        approved_at = None
        if not purchase_settings.require_manager_approval or is_manager_or_higher(user):
            initial_status = 'approved'
            approved_by = user
            approved_at = timezone.now()

        order = PurchaseOrder.objects.create(
            supplier=supplier,
            target_warehouse=target_warehouse,
            delivery_address=delivery_address,
            order_date=order_date or timezone.now().date(),
            expected_delivery_date=expected_delivery_date,
            custom_discount_percentage=Decimal(str(custom_discount_percentage or 0)),
            shipping_fees=Decimal(str(shipping_fees or 0)),
            notes=notes,
            created_by=user,
            updated_by=user,
            status=initial_status,
            approved_by=approved_by,
            approved_at=approved_at
        )

        for idx, itm in enumerate(items_data, start=1):
            PurchaseOrderItem.objects.create(
                order=order,
                item_order=idx,
                product=itm['product'],
                quantity=Decimal(str(itm['quantity'])),
                unit_price=Decimal(str(itm['unit_price'])),
                product_batch_number=itm.get('batch_number', ''),
                product_expiry_date=itm.get('expiry_date') or None,
                discount_percentage=Decimal(str(itm.get('discount_percentage', 0))),
                tax_percentage=Decimal(str(itm.get('tax_percentage', 0)))
            )

        order.recalculate_totals()
        return order

    @staticmethod
    @transaction.atomic
    def approve_order(order: PurchaseOrder, user, notes=""):
        """Transitions status to approved with self-approval check and audit trail."""
        if order.status not in ['pending', 'rejected']:
            raise ValidationError(f"لا يمكن اعتماد طلب بحالة: {order.status_label_ar}")

        # Self-approval prevention (dual-control principle)
        if order.created_by_id == user.id and not (user.is_superuser or getattr(user, 'is_super_admin', False)):
            raise ValidationError("لا يمكن لمنشئ أمر الشراء اعتماده بنفسه (مبدأ الرقابة الثنائية).")

        status_before = order.status
        order.status = 'approved'
        order.approved_by = user
        order.approved_at = timezone.now()
        order.rejection_reason = ""
        order.updated_by = user
        order.save(update_fields=['status', 'approved_by', 'approved_at', 'rejection_reason', 'updated_by', 'updated_at'])

        from activities.models import ApprovalAuditLog
        ApprovalAuditLog.objects.create(
            record_type='purchase_order',
            purchase_order=order,
            action='approved',
            actor=user,
            status_before=status_before,
            status_after='approved',
            reason=notes or 'تم اعتماد أمر الشراء'
        )
        return order

    @staticmethod
    @transaction.atomic
    def reject_order(order: PurchaseOrder, user, reason=""):
        """Rejects purchase order with mandatory rejection reason and audit trail."""
        reason = (reason or '').strip()
        if not reason:
            raise ValidationError("يرجى توضيح سبب رفض أمر الشراء لتوجيه مسؤول المشتريات.")

        if order.created_by_id == user.id and not (user.is_superuser or getattr(user, 'is_super_admin', False)):
            raise ValidationError("لا يمكن لمنشئ أمر الشراء رفض طلبه بنفسه.")

        status_before = order.status
        order.status = 'rejected'
        order.rejection_reason = reason
        order.approved_by = user
        order.approved_at = timezone.now()
        order.updated_by = user
        order.save(update_fields=['status', 'rejection_reason', 'approved_by', 'approved_at', 'updated_by', 'updated_at'])

        from activities.models import ApprovalAuditLog
        ApprovalAuditLog.objects.create(
            record_type='purchase_order',
            purchase_order=order,
            action='rejected',
            actor=user,
            status_before=status_before,
            status_after='rejected',
            reason=reason
        )
        return order

    @staticmethod
    @transaction.atomic
    def resubmit_order(order: PurchaseOrder, user):
        """Allows purchaser to resubmit rejected order for approval."""
        if order.status != 'rejected':
            raise ValidationError("لا يمكن إعادة تقديم أمر الشراء إلا إذا كان في حالة مرفوض.")

        status_before = order.status
        order.status = 'pending'
        order.rejection_reason = ""
        order.updated_by = user
        order.save(update_fields=['status', 'rejection_reason', 'updated_by', 'updated_at'])

        from activities.models import ApprovalAuditLog
        ApprovalAuditLog.objects.create(
            record_type='purchase_order',
            purchase_order=order,
            action='resubmitted',
            actor=user,
            status_before=status_before,
            status_after='pending',
            reason="إعادة تقديم أمر الشراء للاعتماد بعد المراجعة والتعديل"
        )
        return order

    @staticmethod
    @transaction.atomic
    def stock_order(order: PurchaseOrder, user):
        """
        Physical Goods Receipt:
        1. Strictly requires order to be approved (downstream enforcement).
        2. Generates an inward Warehouse Memo (إذن إضافة مخزنية).
        3. Increments InventoryStock qty_on_hand and recalculates weighted average cost.
        4. Updates lot batch numbers and expiration dates.
        5. Transitions status from approved to picked.
        """
        if order.status != 'approved':
            raise ValidationError(f"لا يمكن استلام البضاعة في المخزن قبل اعتماد أمر الشراء من الإدارة (الحالة الحالية: {order.status_label_ar}).")

        memo_number = f"MEMO-IN-{order.serial_num}"
        memo = InventoryMemo.objects.create(
            memo_number=memo_number,
            memo_type='inward',
            warehouse=order.target_warehouse,
            statement=f"إذن إضافة استلام أمر مشتريات {order.order_number}",
            status='applied',
            applied_at=timezone.now(),
            created_by=user
        )

        for item in order.items.select_related('product'):
            # Record memo item
            InventoryMemoItem.objects.create(
                memo=memo,
                product=item.product,
                quantity=item.quantity,
                unit_cost=item.unit_price,
                batch_number=item.product_batch_number,
                expiry_date=item.product_expiry_date
            )

            # Update warehouse stock
            stock, _ = InventoryStock.objects.get_or_create(
                warehouse=order.target_warehouse,
                product=item.product,
                defaults={'product_cost': item.unit_price, 'qty_on_hand': Decimal('0.00'), 'qty_reserved': Decimal('0.00')}
            )

            stock_qty = Decimal(str(stock.qty_on_hand or '0'))
            stock_cost = Decimal(str(stock.product_cost or '0'))
            item_qty = Decimal(str(item.quantity))
            item_price = Decimal(str(item.unit_price))

            old_total_cost = stock_qty * stock_cost
            new_item_cost = item_qty * item_price
            new_total_qty = stock_qty + item_qty

            if new_total_qty > 0:
                weighted_avg_cost = (old_total_cost + new_item_cost) / new_total_qty
                stock.product_cost = weighted_avg_cost.quantize(Decimal('0.01'))

            stock.qty_on_hand = new_total_qty
            stock.save(update_fields=['qty_on_hand', 'product_cost', 'updated_at'])

            # Record batch/lot if provided
            if item.product_batch_number or item.product_expiry_date:
                lot, _ = InventoryLot.objects.get_or_create(
                    stock=stock,
                    batch_number=item.product_batch_number or "DEFAULT",
                    expiry_date=item.product_expiry_date,
                    defaults={'quantity': Decimal('0.00')}
                )
                lot.quantity += item.quantity
                lot.save(update_fields=['quantity'])

        order.memo = memo
        order.stocked_at = timezone.now()
        order.status = 'picked'
        order.updated_by = user
        order.save(update_fields=['memo', 'stocked_at', 'status', 'updated_by', 'updated_at'])
        return order

    @staticmethod
    @transaction.atomic
    def invoice_order(order: PurchaseOrder, user):
        """
        Financial Invoicing:
        1. Ensures order is picked (goods physically received).
        2. Posts a credit transaction to the supplier's double-entry ledger.
        3. Updates supplier account balance.
        4. Creates an installment for payment tracking.
        5. Transitions status to settled.
        """
        if order.status != 'picked':
            raise ValidationError("يجب استلام البضاعة في المخزن أولاً (Picked) قبل الفوترة في الحسابات.")

        account = VendorAccount.get_or_create_for_supplier(order.supplier)
        new_balance = account.current_balance + order.grand_total

        tx = VendorTransaction.objects.create(
            account=account,
            purchase_order=order,
            transaction_type='credit',
            reason='purchase',
            transaction_date=timezone.now().date(),
            due_date=timezone.now().date() + timezone.timedelta(days=account.credit_period_days),
            credit=order.grand_total,
            debit=Decimal('0.00'),
            running_balance=new_balance,
            description=f"فاتورة مشتريات {order.order_number} ({order.supplier.name})",
            created_by=user
        )

        VendorInstallment.objects.create(
            transaction=tx,
            total_amount=order.grand_total,
            closed_amount=Decimal('0.00'),
            open_amount=order.grand_total,
            due_date=tx.due_date,
            is_settled=False
        )

        account.current_balance = new_balance
        account.last_transaction_date = tx.transaction_date
        account.save(update_fields=['current_balance', 'last_transaction_date', 'updated_at'])

        order.invoiced_at = timezone.now()
        order.status = 'settled'
        order.updated_by = user
        order.save(update_fields=['invoiced_at', 'status', 'updated_by', 'updated_at'])
        return order

    @staticmethod
    @transaction.atomic
    def undo_invoice(order: PurchaseOrder, user):
        """
        Reverts settled invoice:
        1. Verifies order is settled.
        2. Cancels or offsets vendor ledger transaction.
        3. Reverts supplier balance.
        4. Reverts order status to picked.
        """
        if order.status != 'settled':
            raise ValidationError("لا يمكن إلغاء فاتورة لطلب غير مكتمل الفوترة (Settled).")

        account = VendorAccount.get_or_create_for_supplier(order.supplier)
        
        # Check if installments were settled by payments
        tx = VendorTransaction.objects.filter(purchase_order=order, transaction_type='credit').first()
        if tx:
            inst = tx.installments.first()
            if inst and inst.closed_amount > Decimal('0.00'):
                raise ValidationError("لا يمكن إلغاء الفاتورة لوجود مدفوعات مسجلة ومخصصة لها. يرجى إلغاء تسوية المدفوعات أولاً.")

            # Create reversing debit transaction
            reversal_balance = account.current_balance - order.grand_total
            VendorTransaction.objects.create(
                account=account,
                purchase_order=order,
                transaction_type='debit',
                reason='adjustment',
                transaction_date=timezone.now().date(),
                credit=Decimal('0.00'),
                debit=order.grand_total,
                running_balance=reversal_balance,
                description=f"إلغاء فاتورة مشتريات {order.order_number}",
                created_by=user
            )

            account.current_balance = reversal_balance
            account.save(update_fields=['current_balance', 'updated_at'])

        order.status = 'picked'
        order.invoiced_at = None
        order.updated_by = user
        order.save(update_fields=['status', 'invoiced_at', 'updated_by', 'updated_at'])
        return order

    @staticmethod
    @transaction.atomic
    def cancel_order(order: PurchaseOrder, user):
        """Cancels a pending or approved order before stocking."""
        if order.status in ['picked', 'settled']:
            raise ValidationError("لا يمكن إلغاء طلب تم استلامه أو فوترته. يجب استخدام أمر المرتجعات.")
        order.status = 'cancelled'
        order.updated_by = user
        order.save(update_fields=['status', 'updated_by', 'updated_at'])
        return order

    @staticmethod
    @transaction.atomic
    def split_order(order: PurchaseOrder, split_item_ids_with_qty, user):
        """
        Splits selected items or quantities from an existing order into a new child order.
        split_item_ids_with_qty: dict of {item_id: split_qty}
        """
        if order.status in ['settled', 'cancelled']:
            raise ValidationError("لا يمكن فصل طلب تم ترحيله للحسابات أو ملغي.")

        if not split_item_ids_with_qty:
            raise ValidationError("يرجى تحديد الأصناف المراد فصلها.")

        # Create child order
        child_order = PurchaseOrder.objects.create(
            supplier=order.supplier,
            target_warehouse=order.target_warehouse,
            delivery_address=order.delivery_address,
            order_date=order.order_date,
            expected_delivery_date=order.expected_delivery_date,
            delivery_agent=order.delivery_agent,
            delivery_time=order.delivery_time,
            custom_discount_percentage=order.custom_discount_percentage,
            shipping_fees=Decimal('0.00'),
            notes=f"أمر مشتريات منفصل عن الطلب الأصلي {order.order_number}",
            status=order.status if order.status in ['pending', 'approved'] else 'pending',
            is_split=True,
            parent_order=order,
            created_by=user,
            updated_by=user
        )

        child_item_idx = 1
        for item_id, split_qty in split_item_ids_with_qty.items():
            split_qty = Decimal(str(split_qty))
            item = order.items.filter(id=item_id).first()
            if not item or split_qty <= Decimal('0.00'):
                continue

            if split_qty > item.quantity:
                raise ValidationError(f"الكمية المراد فصلها للصنف {item.product.name} أكبر من الكمية المسجلة.")

            # Create line in child order
            PurchaseOrderItem.objects.create(
                order=child_order,
                item_order=child_item_idx,
                product=item.product,
                quantity=split_qty,
                unit_price=item.unit_price,
                product_batch_number=item.product_batch_number,
                product_expiry_date=item.product_expiry_date,
                discount_percentage=item.discount_percentage,
                tax_percentage=item.tax_percentage
            )
            child_item_idx += 1

            # Adjust or remove from parent order
            remaining_qty = item.quantity - split_qty
            if remaining_qty <= Decimal('0.00'):
                item.delete()
            else:
                item.quantity = remaining_qty
                item.save()

        order.is_split = True
        order.save(update_fields=['is_split', 'updated_at'])
        order.recalculate_totals()
        child_order.recalculate_totals()
        return child_order


class PurchaseReturnOrderService:

    @staticmethod
    @transaction.atomic
    def create_return_order(supplier, warehouse, order_date, items_data, user,
                            purchase_order=None, delivery_agent="", delivery_time="", notes=""):
        """
        Creates a new purchase return order with line items.
        """
        if not items_data:
            raise ValidationError("يجب إضافة صنف واحد على الأقل في أمر إرجاع المشتريات.")

        return_order = PurchaseReturnOrder.objects.create(
            supplier=supplier,
            warehouse=warehouse,
            purchase_order=purchase_order,
            order_date=order_date or timezone.now().date(),
            delivery_agent=delivery_agent,
            delivery_time=delivery_time,
            notes=notes,
            created_by=user,
            updated_by=user,
            status='pending'
        )

        for idx, itm in enumerate(items_data, start=1):
            PurchaseReturnOrderItem.objects.create(
                return_order=return_order,
                item_order=idx,
                product=itm['product'],
                quantity=Decimal(str(itm['quantity'])),
                unit_price=Decimal(str(itm['unit_price'])),
                product_batch_number=itm.get('batch_number', ''),
                product_expiry_date=itm.get('expiry_date') or None,
                tax_percentage=Decimal(str(itm.get('tax_percentage', 0)))
            )

        return_order.recalculate_totals()
        return return_order

    @staticmethod
    @transaction.atomic
    def approve_return_order(return_order: PurchaseReturnOrder, user):
        """Transitions status from pending to approved."""
        if return_order.status != 'pending':
            raise ValidationError(f"لا يمكن اعتماد مرتجع بحالة: {return_order.get_status_display()}")
        return_order.status = 'approved'
        return_order.updated_by = user
        return_order.save(update_fields=['status', 'updated_by', 'updated_at'])
        return return_order

    @staticmethod
    @transaction.atomic
    def deliver_return_order(return_order: PurchaseReturnOrder, user):
        """
        Physical Dispatch / Unstocking from warehouse:
        1. Verifies that warehouse holds sufficient stock on hand.
        2. Generates an outward Warehouse Memo (إذن صرف مخزن).
        3. Decrements InventoryStock qty_on_hand.
        4. Decrements InventoryLot batch if tracked.
        5. Transitions status to delivered (خرج من المخزن).
        """
        if return_order.status not in ['approved', 'pending']:
            raise ValidationError(f"لا يمكن صرف بضاعة لمرتجع بحالة: {return_order.get_status_display()}")

        # Verify sufficient stock
        for item in return_order.items.select_related('product'):
            stock = InventoryStock.objects.filter(warehouse=return_order.warehouse, product=item.product).first()
            available = stock.qty_on_hand if stock else Decimal('0.00')
            if available < item.quantity:
                raise ValidationError(
                    f"الرصيد المتاح من الصنف '{item.product.name}' في مخزن '{return_order.warehouse.name}' غير كافٍ للإرجاع ({available:,.2f} متوفر / {item.quantity:,.2f} مطلوب)."
                )

        memo_number = f"MEMO-OUT-RO-{return_order.serial_num}"
        memo = InventoryMemo.objects.create(
            memo_number=memo_number,
            memo_type='outward',
            warehouse=return_order.warehouse,
            statement=f"إذن صرف إرجاع مشتريات {return_order.order_number} للمورد {return_order.supplier.name}",
            status='applied',
            applied_at=timezone.now(),
            created_by=user
        )

        for item in return_order.items.select_related('product'):
            InventoryMemoItem.objects.create(
                memo=memo,
                product=item.product,
                quantity=item.quantity,
                unit_cost=item.unit_price,
                batch_number=item.product_batch_number,
                expiry_date=item.product_expiry_date
            )

            stock = InventoryStock.objects.get(warehouse=return_order.warehouse, product=item.product)
            stock.qty_on_hand = max(Decimal('0.00'), stock.qty_on_hand - item.quantity)
            stock.save(update_fields=['qty_on_hand', 'updated_at'])

            # Decrement batch lot if tracked
            if item.product_batch_number:
                lot = InventoryLot.objects.filter(stock=stock, batch_number=item.product_batch_number).first()
                if lot:
                    lot.quantity = max(Decimal('0.00'), lot.quantity - item.quantity)
                    lot.save(update_fields=['quantity'])

        return_order.memo = memo
        return_order.dispatched_at = timezone.now()
        return_order.status = 'delivered'
        return_order.updated_by = user
        return_order.save(update_fields=['memo', 'dispatched_at', 'status', 'updated_by', 'updated_at'])
        return return_order

    @staticmethod
    @transaction.atomic
    def settle_return_order(return_order: PurchaseReturnOrder, user):
        """
        Financial Settlement / Debit Note:
        1. Ensures goods were physically dispatched (status='delivered').
        2. Posts a double-entry Debit Note in VendorTransaction.
        3. Decrements supplier payable debt balance in VendorAccount.
        4. Transitions status to settled.
        """
        if return_order.status != 'delivered':
            raise ValidationError("يجب صرف البضاعة من المخزن أولاً (Delivered) قبل الترحيل للحسابات.")

        account = VendorAccount.get_or_create_for_supplier(return_order.supplier)
        new_balance = account.current_balance - return_order.grand_total

        tx = VendorTransaction.objects.create(
            account=account,
            transaction_type='debit',
            reason='purchase_return',
            transaction_date=timezone.now().date(),
            credit=Decimal('0.00'),
            debit=return_order.grand_total,
            running_balance=new_balance,
            description=f"إشعار خصم مرتجع مشتريات {return_order.order_number} ({return_order.supplier.name})",
            created_by=user
        )

        account.current_balance = new_balance
        account.last_transaction_date = tx.transaction_date
        account.save(update_fields=['current_balance', 'last_transaction_date', 'updated_at'])

        return_order.settled_at = timezone.now()
        return_order.status = 'settled'
        return_order.updated_by = user
        return_order.save(update_fields=['settled_at', 'status', 'updated_by', 'updated_at'])
        return return_order

    @staticmethod
    @transaction.atomic
    def cancel_return_order(return_order: PurchaseReturnOrder, user):
        """Cancels a pending or approved return order before unstocking."""
        if return_order.status in ['delivered', 'settled']:
            raise ValidationError("لا يمكن إلغاء أمر مرتجع بعد خروج البضاعة من المخزن أو ترحيله للحسابات.")
        return_order.status = 'cancelled'
        return_order.updated_by = user
        return_order.save(update_fields=['status', 'updated_by', 'updated_at'])
        return return_order

