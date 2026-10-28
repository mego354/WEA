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
    def create_order(cls, customer, source_warehouse, order_date, items_data, user, delivery_address=None, delivery_date=None, due_date=None, notes=''):
        """
        Creates a new SalesOrder with line items and subtotal/grand_total computation.
        """
        if not items_data:
            raise ValidationError("يجب إضافة صنف واحد على الأقل في أمر البيع.")

        # Ensure customer account exists
        CustomerAccount.get_or_create_for_customer(customer)

        # Resolve and enforce designated warehouse for representatives
        from accounts.services import is_representative, get_representative_warehouse
        if is_representative(user):
            rep_wh = get_representative_warehouse(user)
            if not rep_wh:
                raise ValidationError("لم يتم تعيين مخزن عهدة افتراضي لحساب المندوب الخاص بك. يرجى مراجعة إدارة النظام.")
            if source_warehouse.pk != rep_wh.pk and not (user.is_superuser or getattr(user, 'is_super_admin', False)):
                raise ValidationError(f"غير مصرح للمندوب بإجراء مبيعات من مخزن آخر ({source_warehouse.name}). يجب استخدام مخزن العهدة الخاص بك ({rep_wh.name}).")
            source_warehouse = rep_wh

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
            due_date=due_date,
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

        from accounts.services import AuditLogService
        AuditLogService.log(
            action_type='SALES_ORDER_CREATED',
            module='sales',
            actor=user,
            record_id=order.id,
            record_name=f"Sales Order #{order.order_number}",
            description=f"إنشاء أمر بيع رقم {order.order_number} للعميل {customer.name} بقيمة {order.grand_total}",
            new_values={
                'order_number': order.order_number,
                'customer': customer.name,
                'grand_total': str(order.grand_total),
                'status': order.status,
                'items_count': len(items_data),
                'due_date': str(order.due_date) if order.due_date else None,
            }
        )

        return order

    @classmethod
    @transaction.atomic
    def update_order(cls, order, customer, source_warehouse, order_date, items_data, user, delivery_address=None, delivery_date=None, due_date=None, notes=''):
        """
        Updates an editable sales order (pending/rejected/manager_approval before preparation),
        replaces line items, recalculates totals, and logs audit record.
        """
        if order.status in ['preparing', 'delivered', 'invoiced', 'cancelled']:
            raise ValidationError(f"لا يمكن تعديل أمر البيع في حالته الحالية: {order.get_status_display()}.")

        if not items_data:
            raise ValidationError("يجب إضافة صنف واحد على الأقل في أمر البيع.")

        # Resolve and enforce designated warehouse for representatives
        from accounts.services import is_representative, get_representative_warehouse
        if is_representative(user):
            rep_wh = get_representative_warehouse(user)
            if not rep_wh:
                raise ValidationError("لم يتم تعيين مخزن عهدة افتراضي لحساب المندوب الخاص بك. يرجى مراجعة إدارة النظام.")
            if source_warehouse.pk != rep_wh.pk and not (user.is_superuser or getattr(user, 'is_super_admin', False)):
                raise ValidationError(f"غير مصرح للمندوب بإجراء مبيعات من مخزن آخر ({source_warehouse.name}). يجب استخدام مخزن العهدة الخاص بك ({rep_wh.name}).")
            source_warehouse = rep_wh

        previous_values = {
            'customer': order.customer.name if order.customer else '',
            'source_warehouse': order.source_warehouse.name if order.source_warehouse else '',
            'grand_total': str(order.grand_total),
            'due_date': str(order.due_date) if order.due_date else None,
            'notes': order.notes,
            'items_count': order.items.count(),
        }

        order.customer = customer
        order.source_warehouse = source_warehouse
        order.order_date = order_date or order.order_date
        order.delivery_date = delivery_date
        order.due_date = due_date
        order.delivery_address = delivery_address
        order.notes = notes

        # Replace line items
        order.items.all().delete()
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
        order.save()

        from accounts.services import AuditLogService
        AuditLogService.log(
            action_type='SALES_ORDER_UPDATED',
            module='sales',
            actor=user,
            record_id=order.id,
            record_name=f"Sales Order #{order.order_number}",
            description=f"تعديل أمر بيع رقم {order.order_number} للعميل {customer.name} بإجمالي {order.grand_total}",
            previous_values=previous_values,
            new_values={
                'customer': customer.name,
                'source_warehouse': source_warehouse.name if source_warehouse else '',
                'grand_total': str(order.grand_total),
                'due_date': str(order.due_date) if order.due_date else None,
                'notes': order.notes,
                'items_count': len(items_data),
            }
        )
        return order

    @classmethod
    @transaction.atomic
    def approve_order(cls, order, user, notes=''):
        """
        Approves the sales order by management in the same main area.
        """
        if order.status not in ['pending', 'rejected']:
            raise ValidationError(f"لا يمكن اعتماد الطلب في حالته الحالية: {order.get_status_display()}.")

        from accounts.permissions import is_manager_eligible_for_user
        is_super = user.is_superuser or getattr(user, 'is_super_admin', False)
        if not is_super:
            if order.created_by_id == user.id:
                raise ValidationError("لا يمكن للمنشئ أو المندوب اعتماد أمر البيع الخاص به.")
            if order.created_by and not is_manager_eligible_for_user(user, order.created_by):
                raise ValidationError("غير مصرح لك باعتماد أمر البيع لمندوب خارج نطاق منطقتك الرئيسية.")

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

        from accounts.services import AuditLogService
        AuditLogService.log(
            action_type='SALES_ORDER_APPROVED',
            module='sales',
            actor=user,
            record_id=order.id,
            record_name=f"Sales Order #{order.order_number}",
            description=f"اعتماد أمر بيع رقم {order.order_number} بواسطة {user.name or user.username}",
            previous_values={'status': status_before},
            new_values={'status': 'manager_approval', 'approved_by': str(user)}
        )
        return order

    @classmethod
    @transaction.atomic
    def reject_order(cls, order, user, reason=''):
        """
        Rejects the sales order with a mandatory reason.
        """
        if order.status not in ['pending', 'manager_approval', 'preparing']:
            raise ValidationError(f"لا يمكن رفض الطلب في حالته الحالية: {order.get_status_display()}.")

        from accounts.permissions import is_manager_eligible_for_user
        is_super = user.is_superuser or getattr(user, 'is_super_admin', False)
        if not is_super:
            if order.created_by_id == user.id:
                raise ValidationError("لا يمكن للمنشئ أو المندوب رفض أمر البيع الخاص به.")
            if order.created_by and not is_manager_eligible_for_user(user, order.created_by):
                raise ValidationError("غير مصرح لك برفض أمر البيع لمندوب خارج نطاق منطقتك الرئيسية.")

        clean_reason = (reason or '').strip()
        if not clean_reason:
            raise ValidationError("يرجى كتابة سبب رفض أمر البيع.")

        # Release reserved stock if order was in preparing status
        if order.status == 'preparing':
            for item in order.items.select_related('product'):
                stock = InventoryStock.objects.filter(warehouse=order.source_warehouse, product=item.product).first()
                if stock:
                    stock.qty_reserved = max(Decimal('0.00'), stock.qty_reserved - item.quantity)
                    stock.save(update_fields=['qty_reserved'])

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

        from accounts.services import AuditLogService
        AuditLogService.log(
            action_type='SALES_ORDER_REJECTED',
            module='sales',
            actor=user,
            record_id=order.id,
            record_name=f"Sales Order #{order.order_number}",
            description=f"رفض أمر بيع رقم {order.order_number}: {clean_reason}",
            previous_values={'status': status_before},
            new_values={'status': 'rejected', 'rejection_reason': clean_reason}
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

        from accounts.services import AuditLogService
        AuditLogService.log(
            action_type='SALES_ORDER_UPDATED',
            module='sales',
            actor=user,
            record_id=order.id,
            record_name=f"Sales Order #{order.order_number}",
            description=f"إعادة تقديم أمر بيع رقم {order.order_number} للاعتماد",
            previous_values={'status': status_before},
            new_values={'status': 'pending'}
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

        from accounts.services import AuditLogService
        AuditLogService.log(
            action_type='SALES_ORDER_UPDATED',
            module='sales',
            actor=user,
            record_id=order.id,
            record_name=f"Sales Order #{order.order_number}",
            description=f"تسليم أمر بيع رقم {order.order_number} وإصدار إذن صرف مخزني {memo_number}",
            new_values={'status': 'delivered', 'memo': memo_number}
        )
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

        from accounts.services import AuditLogService
        AuditLogService.log(
            action_type='SALES_ORDER_INVOICED',
            module='sales',
            actor=user,
            record_id=order.id,
            record_name=f"Sales Order #{order.order_number}",
            description=f"ترحيل فاتورة مبيعات لأمر بيع رقم {order.order_number} بقيمة {order.grand_total}",
            new_values={'status': 'invoiced', 'customer_balance': str(new_balance)}
        )
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

        status_before = order.status
        order.status = 'cancelled'
        order.save(update_fields=['status', 'updated_at'])

        from accounts.services import AuditLogService
        AuditLogService.log(
            action_type='SALES_ORDER_CANCELLED',
            module='sales',
            actor=user,
            record_id=order.id,
            record_name=f"Sales Order #{order.order_number}",
            description=f"إلغاء أمر بيع رقم {order.order_number}",
            previous_values={'status': status_before},
            new_values={'status': 'cancelled'}
        )
        return order


class CollectionService:

    @classmethod
    @transaction.atomic
    def record_collection(cls, customer, vault, amount, user, payment_method='cash', notes='', sales_order=None, collection_date=None, due_date=None):
        """
        Records customer cash/cheque collection:
        1. Links to specific SalesOrder if provided.
        2. Prevents overpayment beyond order outstanding balance.
        3. Concurrency locks Vault.
        4. Deposits cash into Vault.
        5. Posts Credit transaction in Customer Ledger.
        6. Lowers Customer debt balance.
        7. Records audit log.
        """
        amount = Decimal(str(amount))
        if amount <= 0:
            raise ValidationError("قيمة التحصيل يجب أن تكون أكبر من الصفر.")

        if sales_order:
            if sales_order.customer_id != customer.id:
                raise ValidationError("أمر البيع المحدد لا ينتمي لهذا العميل.")
            if sales_order.status == 'cancelled':
                raise ValidationError("لا يمكن تحصيل مبالغ لأمر بيع ملغى.")
            # Check overpayment
            order_outstanding = sales_order.outstanding_balance
            if amount > order_outstanding:
                raise ValidationError(f"قيمة التحصيل ({amount}) تتجاوز المبلغ المتبقي على أمر البيع #{sales_order.order_number} وهو ({order_outstanding}).")

        # Concurrency lock on Vault
        vault = Vault.objects.select_for_update().get(id=vault.id)

        account = CustomerAccount.get_or_create_for_customer(customer)
        new_balance = account.current_balance - amount

        actual_date = collection_date or timezone.now().date()
        collection = Collection.objects.create(
            customer=customer,
            vault=vault,
            amount=amount,
            sales_order=sales_order,
            collection_date=actual_date,
            due_date=due_date or (sales_order.due_date if sales_order else None),
            payment_method=payment_method,
            notes=notes,
            created_by=user
        )

        # Deposit into Vault
        vault.current_balance += amount
        vault.save(update_fields=['current_balance'])

        desc = f"تحصيل نقدية سند رقم #{collection.serial_num} من العميل {customer.name}"
        if sales_order:
            desc += f" لأمر بيع #{sales_order.order_number}"

        VaultTransaction.objects.create(
            vault=vault,
            transaction_type='inflow',
            amount=amount,
            running_balance=vault.current_balance,
            reference_type='customer_collection',
            reference_id=collection.serial_num,
            description=desc,
            created_by=user
        )

        # Customer ledger credit
        CustomerTransaction.objects.create(
            account=account,
            transaction_type='credit',
            reason='collection',
            transaction_date=actual_date,
            debit=Decimal('0.00'),
            credit=amount,
            running_balance=new_balance,
            description=f"سند تحصيل نقدية #{collection.serial_num}" + (f" (أمر بيع #{sales_order.order_number})" if sales_order else ""),
            created_by=user
        )

        account.current_balance = new_balance
        account.last_transaction_date = actual_date
        account.save(update_fields=['current_balance', 'last_transaction_date'])

        from accounts.services import AuditLogService
        AuditLogService.log(
            action_type='COLLECTION_CREATED',
            module='sales',
            actor=user,
            record_id=collection.id,
            record_name=f"Collection #{collection.serial_num}",
            description=f"تسجيل سند تحصيل نقدية رقم {collection.serial_num} بقيمة {amount} من العميل {customer.name}" + (f" لأمر بيع #{sales_order.order_number}" if sales_order else ""),
            new_values={
                'serial_num': collection.serial_num,
                'customer': customer.name,
                'amount': str(amount),
                'vault': vault.name,
                'sales_order': sales_order.order_number if sales_order else None,
                'collection_date': str(actual_date),
                'payment_method': payment_method,
            }
        )

        return collection
