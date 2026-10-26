from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError

from .models import SalesOrder, SalesOrderItem, CustomerAccount, CustomerTransaction, Collection
from contacts.models import Contact, ContactAddress
from catalog.models import Product
from inventory.models import Warehouse, InventoryStock, InventoryMemo, InventoryMemoItem
from treasury.models import Vault, VaultTransaction


class SalesOrderService:

    @classmethod
    @transaction.atomic
    def create_order(cls, customer, source_warehouse, order_date, items_data, user, delivery_address=None, delivery_date=None, notes=''):
        """
        Creates a new SalesOrder with line items and subtotal/grand_total computation.
        """
        if not items_data:
            raise ValidationError("يجب إضافة صنف واحد على الأقل في أمر البيع.")

        # Ensure customer account exists
        CustomerAccount.get_or_create_for_customer(customer)

        from master_data.models import SalesSettings
        from accounts.permissions import is_manager_or_higher
        sales_settings = SalesSettings.get_settings()

        initial_status = 'pending'
        approved_by = None
        approved_at = None
        if not sales_settings.require_manager_approval or is_manager_or_higher(user):
            initial_status = 'manager_approval'
            approved_by = user
            approved_at = timezone.now()

        order = SalesOrder(
            customer=customer,
            source_warehouse=source_warehouse,
            delivery_address=delivery_address,
            order_date=order_date or timezone.now().date(),
            delivery_date=delivery_date,
            status=initial_status,
            approved_by=approved_by,
            approved_at=approved_at,
            notes=notes,
            created_by=user
        )
        order.save()

        running_total = Decimal('0.00')

        for item in items_data:
            product = item['product']
            qty = Decimal(str(item['quantity']))
            price = Decimal(str(item['unit_price']))

            if qty <= 0:
                raise ValidationError(f"الكمية غير صالحة للصنف {product.name}.")

            subtotal = (qty * price).quantize(Decimal('0.01'))
            running_total += subtotal

            SalesOrderItem.objects.create(
                order=order,
                product=product,
                quantity=qty,
                unit_price=price,
                subtotal=subtotal
            )

        order.grand_total = running_total
        order.save(update_fields=['grand_total'])

        from activities.models import ApprovalAuditLog
        ApprovalAuditLog.objects.create(
            record_type='sales_order',
            sales_order=order,
            action='submitted' if order.status == 'pending' else 'auto_approved',
            actor=user,
            status_before='',
            status_after=order.status,
            reason=notes or ('إنشاء وتقديم أمر البيع للاعتماد' if order.status == 'pending' else 'إنشاء أمر البيع واعتماده تلقائياً')
        )
        return order

    @classmethod
    @transaction.atomic
    def approve_order(cls, order, user, notes=''):
        """
        Approves the sales order by management.
        """
        if order.status not in ['pending', 'rejected']:
            raise ValidationError(f"لا يمكن اعتماد الطلب في حالته الحالية: {order.get_status_display()}.")

        status_before = order.status
        order.status = 'manager_approval'
        order.approved_by = user
        order.approved_at = timezone.now()
        order.rejection_reason = ''
        order.save(update_fields=['status', 'approved_by', 'approved_at', 'rejection_reason', 'updated_at'])

        from activities.models import ApprovalAuditLog
        ApprovalAuditLog.objects.create(
            record_type='sales_order',
            sales_order=order,
            action='approved',
            actor=user,
            status_before=status_before,
            status_after='manager_approval',
            reason=notes or 'تم اعتماد أمر البيع من الإدارة'
        )
        return order

    @classmethod
    @transaction.atomic
    def reject_order(cls, order, user, reason=''):
        """
        Rejects the sales order with a mandatory reason.
        """
        if order.status not in ['pending', 'manager_approval']:
            raise ValidationError(f"لا يمكن رفض الطلب في حالته الحالية: {order.get_status_display()}.")

        clean_reason = (reason or '').strip()
        if not clean_reason:
            raise ValidationError("يرجى كتابة سبب رفض أمر البيع.")

        status_before = order.status
        order.status = 'rejected'
        order.rejection_reason = clean_reason
        order.approved_by = user
        order.approved_at = timezone.now()
        order.save(update_fields=['status', 'rejection_reason', 'approved_by', 'approved_at', 'updated_at'])

        from activities.models import ApprovalAuditLog
        ApprovalAuditLog.objects.create(
            record_type='sales_order',
            sales_order=order,
            action='rejected',
            actor=user,
            status_before=status_before,
            status_after='rejected',
            reason=clean_reason
        )
        return order

    @classmethod
    @transaction.atomic
    def resubmit_order(cls, order, user):
        """
        Resubmits a rejected sales order after correction.
        """
        if order.status != 'rejected':
            raise ValidationError("لا يمكن إعادة تقديم إلا الطلبات المرفوضة.")

        status_before = order.status
        order.status = 'pending'
        order.rejection_reason = ''
        order.save(update_fields=['status', 'rejection_reason', 'updated_at'])

        from activities.models import ApprovalAuditLog
        ApprovalAuditLog.objects.create(
            record_type='sales_order',
            sales_order=order,
            action='resubmitted',
            actor=user,
            status_before=status_before,
            status_after='pending',
            reason='إعادة تقديم أمر البيع للاعتماد بعد التعديل والتصحيح'
        )
        return order

    @classmethod
    @transaction.atomic
    def prepare_order(cls, order, user):
        """
        Moves order to 'preparing' and reserves stock in warehouse.
        """
        if order.status != 'manager_approval':
            raise ValidationError(f"يجب اعتماد أمر البيع أولاً قبل تجهيزه بالمخزن.")

        # Check and reserve stock
        for item in order.items.select_related('product'):
            stock, _ = InventoryStock.objects.get_or_create(
                warehouse=order.source_warehouse,
                product=item.product,
                defaults={'qty_on_hand': Decimal('0.00'), 'qty_reserved': Decimal('0.00'), 'product_cost': item.product.default_purchase_cost}
            )
            if stock.qty_available < item.quantity:
                raise ValidationError(f"الكمية المتاحة من المنتج '{item.product.name}' في {order.source_warehouse.name} غير كافية. المتاح: {stock.qty_available}، المطلوب: {item.quantity}")

            stock.qty_reserved += item.quantity
            stock.save(update_fields=['qty_reserved'])

        order.status = 'preparing'
        order.save(update_fields=['status', 'updated_at'])
        return order

    @classmethod
    @transaction.atomic
    def deliver_order(cls, order, user):
        """
        Marks order as delivered, generates outward InventoryMemo, and decrements stock.
        """
        if order.status != 'preparing':
            raise ValidationError(f"يجب أن يكون الطلب في مرحلة التجهيز (Preparing) قبل تسليمه.")

        # Create Outward Inventory Memo
        memo_number = f"MEMO-OUT-{order.serial_num}"
        memo = InventoryMemo.objects.create(
            memo_number=memo_number,
            memo_type='outward',
            warehouse=order.source_warehouse,
            statement=f"صرف أمر بيع رقم {order.order_number} للعميل {order.customer.name}",
            status='applied',
            applied_at=timezone.now(),
            notes=f"Generated from Sales Order #{order.order_number}",
            created_by=user
        )

        for item in order.items.select_related('product'):
            InventoryMemoItem.objects.create(
                memo=memo,
                product=item.product,
                quantity=item.quantity,
                unit_cost=item.product.default_purchase_cost
            )

            stock = InventoryStock.objects.get(
                warehouse=order.source_warehouse,
                product=item.product
            )
            stock.qty_on_hand = max(Decimal('0.00'), stock.qty_on_hand - item.quantity)
            stock.qty_reserved = max(Decimal('0.00'), stock.qty_reserved - item.quantity)
            stock.save(update_fields=['qty_on_hand', 'qty_reserved'])

        order.memo = memo
        order.status = 'delivered'
        order.save(update_fields=['memo', 'status', 'updated_at'])
        return order

    @classmethod
    @transaction.atomic
    def invoice_order(cls, order, user):
        """
        Invoices the delivered sales order and posts debit to customer's ledger.
        """
        if order.status != 'delivered':
            raise ValidationError(f"يجب تسليم الطلب (Delivered) قبل ترحيل الفاتورة للحسابات.")

        account = CustomerAccount.get_or_create_for_customer(order.customer)
        new_balance = account.current_balance + order.grand_total

        # Create Customer Transaction (Debit)
        CustomerTransaction.objects.create(
            account=account,
            transaction_type='debit',
            reason='sales',
            transaction_date=timezone.now().date(),
            debit=order.grand_total,
            credit=Decimal('0.00'),
            running_balance=new_balance,
            description=f"فاتورة مبيعات أمر بيع #{order.order_number}",
            created_by=user
        )

        account.current_balance = new_balance
        account.last_transaction_date = timezone.now().date()
        account.save(update_fields=['current_balance', 'last_transaction_date'])

        order.status = 'invoiced'
        order.save(update_fields=['status', 'updated_at'])
        return order

    @classmethod
    @transaction.atomic
    def cancel_order(cls, order, user):
        """
        Cancels the order if not yet delivered.
        """
        if order.status in ['delivered', 'invoiced']:
            raise ValidationError("لا يمكن إلغاء أمر بيع تم تسليمه أو فوترته.")

        if order.status == 'preparing':
            # Release reserved stock
            for item in order.items.select_related('product'):
                stock = InventoryStock.objects.filter(warehouse=order.source_warehouse, product=item.product).first()
                if stock:
                    stock.qty_reserved = max(Decimal('0.00'), stock.qty_reserved - item.quantity)
                    stock.save(update_fields=['qty_reserved'])

        order.status = 'cancelled'
        order.save(update_fields=['status', 'updated_at'])
        return order


class CollectionService:

    @classmethod
    @transaction.atomic
    def record_collection(cls, customer, vault, amount, user, payment_method='cash', notes=''):
        """
        Records customer cash/cheque collection:
        1. Deposits cash into Vault.
        2. Posts Credit transaction in Customer Ledger.
        3. Lowers Customer debt balance.
        """
        amount = Decimal(str(amount))
        if amount <= 0:
            raise ValidationError("قيمة التحصيل يجب أن تكون أكبر من الصفر.")

        account = CustomerAccount.get_or_create_for_customer(customer)
        new_balance = account.current_balance - amount

        collection = Collection.objects.create(
            customer=customer,
            vault=vault,
            amount=amount,
            collection_date=timezone.now().date(),
            payment_method=payment_method,
            notes=notes,
            created_by=user
        )

        # Deposit into Vault
        vault.current_balance += amount
        vault.save(update_fields=['current_balance'])

        VaultTransaction.objects.create(
            vault=vault,
            transaction_type='inflow',
            amount=amount,
            running_balance=vault.current_balance,
            reference_type='customer_collection',
            reference_id=collection.serial_num,
            description=f"تحصيل نقدية سند رقم #{collection.serial_num} من العميل {customer.name}",
            created_by=user
        )

        # Customer ledger credit
        CustomerTransaction.objects.create(
            account=account,
            transaction_type='credit',
            reason='collection',
            transaction_date=timezone.now().date(),
            debit=Decimal('0.00'),
            credit=amount,
            running_balance=new_balance,
            description=f"سند تحصيل نقدية #{collection.serial_num}",
            created_by=user
        )

        account.current_balance = new_balance
        account.last_transaction_date = timezone.now().date()
        account.save(update_fields=['current_balance', 'last_transaction_date'])

        return collection
