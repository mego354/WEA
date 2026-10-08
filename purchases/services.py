from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError
from .models import PurchaseOrder, PurchaseOrderItem
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
            status='pending'
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
    def approve_order(order: PurchaseOrder, user):
        """Transitions status from pending to approved."""
        if order.status != 'pending':
            raise ValidationError(f"لا يمكن اعتماد طلب بحالة: {order.get_status_display()}")
        order.status = 'approved'
        order.updated_by = user
        order.save(update_fields=['status', 'updated_by', 'updated_at'])
        return order

    @staticmethod
    @transaction.atomic
    def stock_order(order: PurchaseOrder, user):
        """
        Physical Goods Receipt:
        1. Generates an inward Warehouse Memo (إذن إضافة مخزنية).
        2. Increments InventoryStock qty_on_hand and recalculates weighted average cost.
        3. Updates lot batch numbers and expiration dates.
        4. Transitions status from approved to picked.
        """
        if order.status not in ['approved', 'pending']:
            raise ValidationError(f"لا يمكن استلام بضاعة لطلب بحالة: {order.get_status_display()}")

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
