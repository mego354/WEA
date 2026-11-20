from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError
from .models import PurchaseOrder, PurchaseOrderItem, PurchaseReturnOrder, PurchaseReturnOrderItem
from inventory.models import InventoryMemo, InventoryMemoItem, InventoryStock, InventoryLot
from treasury.models import VendorAccount, VendorTransaction, VendorInstallment
from accounts.services import AuditLogService
from master_data.validation_utils import parse_positive_integer_quantity



class PurchaseOrderService:

    @staticmethod
    @transaction.atomic
    def create_order(supplier, target_warehouse, order_date, items_data, user, 
                     delivery_address=None, expected_delivery_date=None, due_date=None,
                     custom_discount_percentage=Decimal('0.00'), shipping_fees=Decimal('0.00'), notes=""):
        """
        Creates a new purchase order with validated line items and audit log.
        """
        if not items_data:
            raise ValidationError("يجب إضافة صنف واحد على الأقل في أمر الشراء.")

        if not target_warehouse or not target_warehouse.is_active:
            raise ValidationError("مخزن الاستلام المحدد غير صالح أو معطل.")

        if not supplier:
            raise ValidationError("يجب تحديد المورد.")

        custom_discount_percentage = Decimal(str(custom_discount_percentage or 0))
        if custom_discount_percentage < 0 or custom_discount_percentage > 100:
            raise ValidationError("نسبة الخصم الإضافي على أمر الشراء يجب أن تكون بين 0% و 100%.")

        shipping_fees = Decimal(str(shipping_fees or 0))
        if shipping_fees < 0:
            raise ValidationError("مصاريف الشحن لا يمكن أن تكون سالبة.")

        for idx, itm in enumerate(items_data, start=1):
            prod_obj = itm.get('product')
            prod_label = getattr(prod_obj, 'name', '') or f"البند #{idx}"
            qty = parse_positive_integer_quantity(itm.get('quantity'), item_label=prod_label)
            itm['quantity'] = qty
            price = Decimal(str(itm.get('unit_price', 0)))
            if price < 0:
                raise ValidationError(f"سعر الوحدة في البند #{idx} لا يمكن أن يكون سالباً.")
            disc = Decimal(str(itm.get('discount_percentage', 0)))
            if disc < 0 or disc > 100:
                raise ValidationError(f"نسبة الخصم في البند #{idx} يجب أن تكون بين 0% و 100%.")

        # Financial credit limit check on supplier (Requirement B5)
        account = VendorAccount.get_or_create_for_supplier(supplier)
        subtotal = Decimal('0.00')
        items_disc = Decimal('0.00')
        items_tax = Decimal('0.00')
        for itm in items_data:
            q = Decimal(str(itm['quantity']))
            p = Decimal(str(itm['unit_price']))
            sub = (q * p).quantize(Decimal('0.01'))
            dp = Decimal(str(itm.get('discount_percentage', 0)))
            da = (sub * (dp / Decimal('100.0'))).quantize(Decimal('0.01'))
            tp = Decimal(str(itm.get('tax_percentage', 0)))
            ta = ((sub - da) * (tp / Decimal('100.0'))).quantize(Decimal('0.01'))
            subtotal += sub
            items_disc += da
            items_tax += ta

        after_items_disc = subtotal - items_disc
        custom_disc_amt = (after_items_disc * (custom_discount_percentage / Decimal('100.0'))).quantize(Decimal('0.01')) if custom_discount_percentage > 0 else Decimal('0.00')
        est_grand_total = max(Decimal('0.00'), after_items_disc - custom_disc_amt) + items_tax + shipping_fees

        if account.credit_limit and account.credit_limit > Decimal('0.00'):
            if (account.current_balance + est_grand_total) > account.credit_limit:
                raise ValidationError(
                    f"لا يمكن إنشاء أمر الشراء لتجاوز حد الائتمان المسموح للمورد ({account.credit_limit:,.2f} ج.م). "
                    f"الرصيد الحالي: {account.current_balance:,.2f} ج.م، وقيمة الطلب: {est_grand_total:,.2f} ج.م."
                )

        # Immediate order execution: set status to settled and approved directly (Requirement B2)
        now_dt = timezone.now()
        order = PurchaseOrder.objects.create(
            supplier=supplier,
            target_warehouse=target_warehouse,
            delivery_address=delivery_address,
            order_date=order_date or now_dt.date(),
            expected_delivery_date=expected_delivery_date,
            due_date=due_date,
            custom_discount_percentage=Decimal(str(custom_discount_percentage or 0)),
            shipping_fees=Decimal(str(shipping_fees or 0)),
            notes=notes,
            created_by=user,
            updated_by=user,
            status='settled',
            payment_status='credit',
            approved_by=user,
            approved_at=now_dt,
            stocked_at=now_dt,
            invoiced_at=now_dt,
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

        # Immediate warehouse stocking: generate inward InventoryMemo and increment stock (Requirement B2)
        memo_number = f"MEMO-IN-{order.serial_num}"
        memo = InventoryMemo.objects.create(
            memo_number=memo_number,
            memo_type='inward',
            warehouse=order.target_warehouse,
            statement=f"إذن إضافة استلام أمر مشتريات #{order.order_number}",
            status='applied',
            applied_at=now_dt,
            created_by=user
        )

        for item in order.items.select_related('product'):
            InventoryMemoItem.objects.create(
                memo=memo,
                product=item.product,
                quantity=item.quantity,
                unit_cost=item.unit_price,
                batch_number=item.product_batch_number,
                expiry_date=item.product_expiry_date
            )

            stock, _ = InventoryStock.objects.select_for_update().get_or_create(
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
        order.save(update_fields=['memo'])

        # Immediate financial execution: post credit to VendorTransaction & update VendorAccount (Requirement B2)
        new_balance = account.current_balance + order.grand_total
        tx = VendorTransaction.objects.create(
            account=account,
            purchase_order=order,
            transaction_type='credit',
            reason='purchase',
            transaction_date=order.order_date or now_dt.date(),
            due_date=order.due_date or (now_dt.date() + timezone.timedelta(days=account.credit_period_days)),
            credit=order.grand_total,
            debit=Decimal('0.00'),
            running_balance=new_balance,
            description=f"فاتورة مشتريات لأمر توريد #{order.order_number}",
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

        from activities.models import ApprovalAuditLog
        ApprovalAuditLog.objects.create(
            record_type='purchase_order',
            purchase_order=order,
            action='submitted',
            actor=user,
            status_before='',
            status_after='settled',
            reason="إنشاء وتنفيذ أمر الشراء مباشرة في المخزن والحسابات"
        )

        # Audit Logging
        AuditLogService.log(
            action_type='PURCHASE_ORDER_CREATED',
            module='purchases',
            actor=user,
            record_id=order.id,
            record_name=f"{order.order_number} ({order.supplier.name})",
            description=f"إنشاء أمر مشتريات {order.order_number} للمورد {order.supplier.name} بإجمالي {order.grand_total:,.2f} ج.م",
            new_values={
                'order_number': order.order_number,
                'supplier': order.supplier.name,
                'target_warehouse': order.target_warehouse.name,
                'items_count': order.items_count,
                'items_quantity': str(order.items_quantity),
                'subtotal': str(order.subtotal),
                'grand_total': str(order.grand_total),
                'due_date': str(order.due_date) if order.due_date else None,
                'status': order.status,
            }
        )
        return order

    @staticmethod
    @transaction.atomic
    def update_order(order: PurchaseOrder, supplier, target_warehouse, order_date, items_data, user,
                     delivery_address=None, expected_delivery_date=None, due_date=None,
                     custom_discount_percentage=Decimal('0.00'), shipping_fees=Decimal('0.00'),
                     delivery_agent="", delivery_time="", notes=""):
        """
        Updates an editable purchase order with safe inventory and ledger reconciliation (Requirement B7).
        """
        if order.status == 'cancelled':
            raise ValidationError("لا يمكن تعديل أمر شراء ملغي.")

        if order.vendor_payments.exists():
            raise ValidationError("لا يمكن تعديل أمر شراء مرتبط بسندات صرف مسجلة. يرجى إلغاء سندات الصرف أولاً.")

        if VendorInstallment.objects.filter(transaction__purchase_order=order, closed_amount__gt=Decimal('0.00')).exists():
            raise ValidationError("لا يمكن تعديل أمر شراء مرتبط بدفعات مسددة أو تسويات مالية.")

        if order.return_orders.exclude(status='cancelled').exists():
            raise ValidationError("لا يمكن تعديل أمر شراء مرتبط بمرتجعات مشتريات مسجلة.")

        if not items_data:
            raise ValidationError("يجب إضافة صنف واحد على الأقل في أمر الشراء.")

        if not target_warehouse or not target_warehouse.is_active:
            raise ValidationError("مخزن الاستلام المحدد غير صالح أو معطل.")

        if not supplier:
            raise ValidationError("يجب تحديد المورد.")

        custom_discount_percentage = Decimal(str(custom_discount_percentage or 0))
        if custom_discount_percentage < 0 or custom_discount_percentage > 100:
            raise ValidationError("نسبة الخصم الإضافي على أمر الشراء يجب أن تكون بين 0% و 100%.")

        shipping_fees = Decimal(str(shipping_fees or 0))
        if shipping_fees < 0:
            raise ValidationError("مصاريف الشحن لا يمكن أن تكون سالبة.")

        for idx, itm in enumerate(items_data, start=1):
            prod_obj = itm.get('product')
            prod_label = getattr(prod_obj, 'name', '') or f"البند #{idx}"
            qty = parse_positive_integer_quantity(itm.get('quantity'), item_label=prod_label)
            itm['quantity'] = qty
            price = Decimal(str(itm.get('unit_price', 0)))
            if price < 0:
                raise ValidationError(f"سعر الوحدة في البند #{idx} لا يمكن أن يكون سالباً.")
            disc = Decimal(str(itm.get('discount_percentage', 0)))
            if disc < 0 or disc > 100:
                raise ValidationError(f"نسبة الخصم في البند #{idx} يجب أن تكون بين 0% و 100%.")

        order = PurchaseOrder.objects.select_for_update().get(pk=order.pk)
        if order.status == 'cancelled':
            raise ValidationError("لا يمكن تعديل أمر شراء ملغى.")

        old_supplier = order.supplier
        old_grand_total = order.grand_total
        was_stocked = bool(order.memo_id) or order.status in ('picked', 'settled')
        was_invoiced = order.vendor_transactions.exists() or order.status == 'settled'

        prev_values = {
            'supplier': order.supplier.name,
            'target_warehouse': order.target_warehouse.name,
            'items_count': order.items_count,
            'items_quantity': str(order.items_quantity),
            'grand_total': str(order.grand_total),
            'due_date': str(order.due_date) if order.due_date else None,
        }

        # 1. Reverse previous stock impact ONLY if stock was actually posted
        old_wh = order.target_warehouse
        if was_stocked and old_wh:
            old_items = list(order.items.select_related('product'))
            qty_by_prod = {}
            for old_item in old_items:
                qty_by_prod[old_item.product_id] = qty_by_prod.get(old_item.product_id, Decimal('0.00')) + old_item.quantity
            for prod_id, needed_qty in sorted(qty_by_prod.items()):
                st = InventoryStock.objects.select_for_update().filter(warehouse=old_wh, product_id=prod_id).first()
                if not st or st.qty_available < needed_qty:
                    avail = st.qty_available if st else Decimal('0.00')
                    raise ValidationError(
                        f"لا يمكن تعديل أمر الشراء لأن الكمية المتاحة بالمخزن ({avail:,.2f}) أقل من الكمية السابقة بالطلب ({needed_qty:,.2f})."
                    )
            for old_item in old_items:
                st = InventoryStock.objects.select_for_update().get(warehouse=old_wh, product=old_item.product)
                st.qty_on_hand = st.qty_on_hand - old_item.quantity
                st.save(update_fields=['qty_on_hand', 'updated_at'])
                if old_item.product_batch_number or old_item.product_expiry_date:
                    lot = InventoryLot.objects.select_for_update().filter(
                        stock=st, batch_number=old_item.product_batch_number or "DEFAULT"
                    ).first()
                    if lot:
                        lot.quantity = max(Decimal('0.00'), lot.quantity - old_item.quantity)
                        lot.save(update_fields=['quantity'])

        order.supplier = supplier
        order.target_warehouse = target_warehouse
        order.delivery_address = delivery_address
        order.order_date = order_date or order.order_date
        order.expected_delivery_date = expected_delivery_date
        order.due_date = due_date
        order.custom_discount_percentage = Decimal(str(custom_discount_percentage or 0))
        order.shipping_fees = Decimal(str(shipping_fees or 0))
        if delivery_agent:
            order.delivery_agent = delivery_agent
        if delivery_time:
            order.delivery_time = delivery_time
        order.notes = notes
        order.updated_by = user
        order.save(update_fields=[
            'supplier', 'target_warehouse', 'delivery_address', 'order_date',
            'expected_delivery_date', 'due_date', 'custom_discount_percentage',
            'shipping_fees', 'delivery_agent', 'delivery_time', 'notes', 'updated_by', 'updated_at'
        ])

        # Replace line items
        order.items.all().delete()
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

        # 2. Add new items to target warehouse stock ONLY if previously stocked
        new_wh = order.target_warehouse
        if was_stocked and new_wh:
            for new_item in order.items.select_related('product'):
                st, _ = InventoryStock.objects.select_for_update().get_or_create(
                    warehouse=new_wh,
                    product=new_item.product,
                    defaults={'product_cost': new_item.unit_price, 'qty_on_hand': Decimal('0.00'), 'qty_reserved': Decimal('0.00')}
                )
                stock_qty = Decimal(str(st.qty_on_hand or '0'))
                stock_cost = Decimal(str(st.product_cost or '0'))
                item_qty = Decimal(str(new_item.quantity))
                item_price = Decimal(str(new_item.unit_price))
                new_total_qty = stock_qty + item_qty
                if new_total_qty > 0:
                    weighted_avg_cost = (stock_qty * stock_cost + item_qty * item_price) / new_total_qty
                    st.product_cost = weighted_avg_cost.quantize(Decimal('0.01'))
                st.qty_on_hand = new_total_qty
                st.save(update_fields=['qty_on_hand', 'product_cost', 'updated_at'])
                if new_item.product_batch_number or new_item.product_expiry_date:
                    lot, _ = InventoryLot.objects.select_for_update().get_or_create(
                        stock=st,
                        batch_number=new_item.product_batch_number or "DEFAULT",
                        expiry_date=new_item.product_expiry_date,
                        defaults={'quantity': Decimal('0.00')}
                    )
                    lot.quantity += new_item.quantity
                    lot.save(update_fields=['quantity'])

        # 3. Update InventoryMemo items
        if order.memo:
            order.memo.items.all().delete()
            order.memo.warehouse = new_wh
            order.memo.save(update_fields=['warehouse'])
            for itm in order.items.select_related('product'):
                InventoryMemoItem.objects.create(
                    memo=order.memo,
                    product=itm.product,
                    quantity=itm.quantity,
                    unit_cost=itm.unit_price,
                    batch_number=itm.product_batch_number,
                    expiry_date=itm.product_expiry_date
                )

        # 4. Reconcile Vendor Account & Transactions ONLY if previously invoiced
        if was_invoiced:
            if old_supplier.id != order.supplier.id:
                old_acc = VendorAccount.get_or_create_for_supplier(old_supplier)
                old_acc = VendorAccount.objects.select_for_update().get(pk=old_acc.pk)
                old_acc.current_balance -= old_grand_total
                old_acc.save(update_fields=['current_balance', 'updated_at'])

                new_acc = VendorAccount.get_or_create_for_supplier(order.supplier)
                new_acc = VendorAccount.objects.select_for_update().get(pk=new_acc.pk)
                if new_acc.credit_limit > Decimal('0.00') and (new_acc.current_balance + order.grand_total) > new_acc.credit_limit:
                    raise ValidationError("تجاوز الحد الائتماني المسموح به للمورد الجديد.")
                new_acc.current_balance += order.grand_total
                new_acc.save(update_fields=['current_balance', 'updated_at'])
                account = new_acc
            else:
                account = VendorAccount.get_or_create_for_supplier(order.supplier)
                account = VendorAccount.objects.select_for_update().get(pk=account.pk)
                delta = order.grand_total - old_grand_total
                if delta > Decimal('0.00') and account.credit_limit > Decimal('0.00') and (account.current_balance + delta) > account.credit_limit:
                    raise ValidationError("تجاوز الحد الائتماني المسموح به لهذا المورد.")
                account.current_balance += delta
                account.save(update_fields=['current_balance', 'updated_at'])

            tx = order.vendor_transactions.first()
            if tx:
                tx.account = account
                tx.credit = order.grand_total
                tx.running_balance = account.current_balance
                tx.save(update_fields=['account', 'credit', 'running_balance'])
                inst = tx.installments.first()
                if inst:
                    inst.total_amount = order.grand_total
                    inst.open_amount = max(Decimal('0.00'), order.grand_total - inst.closed_amount)
                    inst.save(update_fields=['total_amount', 'open_amount'])

        new_values = {
            'supplier': order.supplier.name,
            'target_warehouse': order.target_warehouse.name,
            'items_count': order.items_count,
            'items_quantity': str(order.items_quantity),
            'grand_total': str(order.grand_total),
            'due_date': str(order.due_date) if order.due_date else None,
        }

        AuditLogService.log(
            action_type='PURCHASE_ORDER_UPDATED',
            module='purchases',
            actor=user,
            record_id=order.id,
            record_name=f"{order.order_number} ({order.supplier.name})",
            description=f"تعديل بيانات وبنود أمر المشتريات {order.order_number} (الإجمالي الجديد: {order.grand_total:,.2f} ج.م)",
            previous_values=prev_values,
            new_values=new_values
        )
        return order

    @classmethod
    @transaction.atomic
    def delete_order(cls, order: PurchaseOrder, user):
        """
        Deletes a purchase order safely with financial and inventory reversal (Requirement B7):
        1. Checks no payments or settlements exist.
        2. Checks no active return orders exist.
        3. Verifies warehouse stock availability and reverses added stock and lots.
        4. Reverses vendor ledger balance and deletes transactions/installments.
        5. Deletes inventory memo and purchase order.
        6. Logs deletion to SecurityAuditLog.
        """
        order = PurchaseOrder.objects.select_for_update().get(pk=order.pk)

        if order.vendor_payments.exists():
            raise ValidationError("لا يمكن حذف أمر شراء مرتبط بسندات صرف مسجلة. يرجى إلغاء سندات الصرف أولاً.")

        if VendorInstallment.objects.filter(transaction__purchase_order=order, closed_amount__gt=Decimal('0.00')).exists():
            raise ValidationError("لا يمكن حذف أمر شراء مرتبط بدفعات مسددة أو تسويات مالية.")

        if order.return_orders.exclude(status='cancelled').exists():
            raise ValidationError("لا يمكن حذف أمر الشراء لوجود أوامر إرجاع مسجلة عليه. يجب حذف أو إلغاء المرتجعات أولاً.")

        was_stocked = bool(order.memo_id) or order.status in ('picked', 'settled')
        was_invoiced = order.vendor_transactions.exists() or order.status == 'settled'

        # 1. Verify warehouse stock (aggregated per product, using qty_available) and reverse ONLY if posted
        if was_stocked and order.target_warehouse:
            order_items = list(order.items.select_related('product'))
            qty_by_prod = {}
            prod_names = {}
            for item in order_items:
                qty_by_prod[item.product_id] = qty_by_prod.get(item.product_id, Decimal('0.00')) + item.quantity
                prod_names[item.product_id] = item.product.name

            for prod_id, needed_qty in sorted(qty_by_prod.items()):
                stock = InventoryStock.objects.select_for_update().filter(
                    warehouse=order.target_warehouse,
                    product_id=prod_id
                ).first()
                if not stock or stock.qty_available < needed_qty:
                    avail = stock.qty_available if stock else Decimal('0.00')
                    raise ValidationError(
                        f"لا يمكن حذف أمر الشراء لأن الرصيد المتاح بالمخزن من الصنف '{prod_names[prod_id]}' ({avail:,.2f}) أقل من الكمية المضافة بالطلب ({needed_qty:,.2f})."
                    )

            for item in order_items:
                stock = InventoryStock.objects.select_for_update().get(
                    warehouse=order.target_warehouse,
                    product=item.product
                )
                stock.qty_on_hand = max(Decimal('0.00'), stock.qty_on_hand - item.quantity)
                stock.save(update_fields=['qty_on_hand', 'updated_at'])
                if item.product_batch_number or item.product_expiry_date:
                    lot = InventoryLot.objects.select_for_update().filter(
                        stock=stock,
                        batch_number=item.product_batch_number or "DEFAULT"
                    ).first()
                    if lot:
                        lot.quantity = max(Decimal('0.00'), lot.quantity - item.quantity)
                        lot.save(update_fields=['quantity'])

        # 2. Reverse vendor financial balance ONLY if invoiced
        if was_invoiced:
            account = VendorAccount.get_or_create_for_supplier(order.supplier)
            account = VendorAccount.objects.select_for_update().get(pk=account.pk)
            account.current_balance -= order.grand_total
            account.save(update_fields=['current_balance', 'updated_at'])

            # 3. Delete installments & vendor transactions
            VendorInstallment.objects.filter(transaction__purchase_order=order).delete()
            order.vendor_transactions.all().delete()

        # 4. Delete inventory memo
        if order.memo:
            memo = order.memo
            order.memo = None
            order.save(update_fields=['memo'])
            memo.items.all().delete()
            memo.delete()

        # 5. Audit log
        AuditLogService.log(
            action_type='PURCHASE_ORDER_DELETED',
            module='purchases',
            actor=user,
            record_id=order.id,
            record_name=f"{order.order_number} ({order.supplier.name})",
            description=f"حذف أمر مشتريات رقم {order.order_number} للمورد {order.supplier.name} بقيمة {order.grand_total:,.2f} ج.م وعكس الحركات المخزنية والمالية",
            previous_values={'order_number': order.order_number, 'grand_total': str(order.grand_total)}
        )

        order.delete()
        return True

    @classmethod
    @transaction.atomic
    def update_payment_status(cls, order: PurchaseOrder, new_status: str, user, notes=''):
        """
        Manually updates commercial payment status with validation and audit trail (Requirement B3).
        """
        valid_statuses = dict(PurchaseOrder.PAYMENT_STATUS_CHOICES)
        if new_status not in valid_statuses:
            raise ValidationError(f"حالة السداد غير صالحة: '{new_status}'.")

        old_status = order.payment_status
        order.payment_status = new_status
        order.save(update_fields=['payment_status', 'updated_at'])

        from activities.models import ApprovalAuditLog
        ApprovalAuditLog.objects.create(
            record_type='purchase_order',
            purchase_order=order,
            action='payment_status_updated',
            actor=user,
            status_before=old_status,
            status_after=new_status,
            reason=notes or f"تغيير حالة السداد التجارية إلى {order.payment_status_display_ar}"
        )

        AuditLogService.log(
            action_type='PURCHASE_ORDER_UPDATED',
            module='purchases',
            actor=user,
            record_id=order.id,
            record_name=f"{order.order_number} ({order.supplier.name})",
            description=f"تحديث حالة السداد التجارية لأمر الشراء {order.order_number} إلى '{order.payment_status_display_ar}'",
            previous_values={'payment_status': old_status},
            new_values={'payment_status': new_status, 'notes': notes}
        )
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

        AuditLogService.log(
            action_type='PURCHASE_ORDER_APPROVED',
            module='purchases',
            actor=user,
            record_id=order.id,
            record_name=f"{order.order_number} ({order.supplier.name})",
            description=f"اعتماد أمر مشتريات {order.order_number} للمورد {order.supplier.name}",
            previous_values={'status': status_before},
            new_values={'status': 'approved', 'approved_by': user.username},
            reason=notes or ''
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
        AuditLogService.log(
            action_type='PURCHASE_ORDER_REJECTED',
            module='purchases',
            actor=user,
            record_id=order.id,
            record_name=f"{order.order_number} ({order.supplier.name})",
            description=f"رفض أمر مشتريات {order.order_number} للمورد {order.supplier.name}: {reason}",
            previous_values={'status': status_before},
            new_values={'status': 'rejected', 'rejection_reason': reason},
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

        AuditLogService.log(
            action_type='PURCHASE_ORDER_UPDATED',
            module='purchases',
            actor=user,
            record_id=order.id,
            record_name=f"{order.order_number} ({order.supplier.name})",
            description=f"إعادة تقديم أمر مشتريات {order.order_number} للاعتماد",
            previous_values={'status': status_before},
            new_values={'status': 'pending'}
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

            # Update warehouse stock with row lock
            stock, _ = InventoryStock.objects.select_for_update().get_or_create(
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

        AuditLogService.log(
            action_type='PURCHASE_ORDER_PICKED',
            module='purchases',
            actor=user,
            record_id=order.id,
            record_name=f"{order.order_number} ({order.supplier.name})",
            description=f"استلام بضاعة أمر مشتريات {order.order_number} بمخزن {order.target_warehouse.name} (إذن إضافة {memo.memo_number})",
            previous_values={'status': 'approved'},
            new_values={'status': 'picked', 'memo_number': memo.memo_number, 'warehouse': order.target_warehouse.name}
        )
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
            due_date=order.due_date or (timezone.now().date() + timezone.timedelta(days=account.credit_period_days)),
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

        AuditLogService.log(
            action_type='PURCHASE_ORDER_SETTLED',
            module='purchases',
            actor=user,
            record_id=order.id,
            record_name=f"{order.order_number} ({order.supplier.name})",
            description=f"ترحيل أمر مشتريات {order.order_number} للحسابات (قيد رقم #{tx.serial} بمبلغ {order.grand_total:,.2f} ج.م)",
            previous_values={'status': 'picked'},
            new_values={'status': 'settled', 'transaction_serial': tx.serial, 'supplier_balance': str(new_balance), 'due_date': str(tx.due_date)}
        )
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

        AuditLogService.log(
            action_type='PURCHASE_ORDER_UPDATED',
            module='purchases',
            actor=user,
            record_id=order.id,
            record_name=f"{order.order_number} ({order.supplier.name})",
            description=f"إلغاء فوترة أمر مشتريات {order.order_number} وإعادة الحالة إلى استلام المخزن (Picked)",
            previous_values={'status': 'settled'},
            new_values={'status': 'picked'}
        )
        return order

    @staticmethod
    @transaction.atomic
    def cancel_order(order: PurchaseOrder, user):
        """Cancels a pending or approved order before stocking."""
        if order.status in ['picked', 'settled']:
            raise ValidationError("لا يمكن إلغاء طلب تم استلامه أو فوترته. يجب استخدام أمر المرتجعات.")
        status_before = order.status
        order.status = 'cancelled'
        order.updated_by = user
        order.save(update_fields=['status', 'updated_by', 'updated_at'])

        AuditLogService.log(
            action_type='PURCHASE_ORDER_CANCELLED',
            module='purchases',
            actor=user,
            record_id=order.id,
            record_name=f"{order.order_number} ({order.supplier.name})",
            description=f"إلغاء أمر مشتريات {order.order_number}",
            previous_values={'status': status_before},
            new_values={'status': 'cancelled'}
        )
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
            due_date=order.due_date,
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

        AuditLogService.log(
            action_type='PURCHASE_ORDER_SPLIT',
            module='purchases',
            actor=user,
            record_id=order.id,
            record_name=f"{order.order_number} -> {child_order.order_number}",
            description=f"تقسيم أمر مشتريات {order.order_number} وإنشاء أمر مشتريات فرعي {child_order.order_number}",
            new_values={'child_order': child_order.order_number, 'child_grand_total': str(child_order.grand_total)}
        )
        return child_order


class PurchaseReturnOrderService:

    @staticmethod
    @transaction.atomic
    def create_return_order(supplier=None, warehouse=None, order_date=None, items_data=None, user=None,
                            purchase_order=None, delivery_agent="", delivery_time="", notes="", **kwargs):
        """
        Creates a new purchase return order with line items.
        If linked to a purchase order, strictly validates eligible status and Returnable Quantity = Original Ordered Quantity - Previously Returned Quantity.
        """
        supplier = supplier or kwargs.get('vendor')
        warehouse = warehouse or kwargs.get('target_warehouse')
        if not items_data:
            raise ValidationError("يجب إضافة صنف واحد على الأقل في أمر إرجاع المشتريات.")

        if purchase_order:
            parent_order = PurchaseOrder.objects.select_for_update().get(pk=purchase_order.pk)
            if parent_order.status not in ['approved', 'picked', 'settled']:
                raise ValidationError(f"لا يمكن إنشاء مرتجع لأمر شراء بحالة '{parent_order.get_status_display()}'.")
            if supplier and supplier.pk != parent_order.supplier_id:
                raise ValidationError("المورد لا يطابق مورد أمر الشراء الأصلي.")
            supplier = parent_order.supplier
            if not warehouse:
                warehouse = parent_order.target_warehouse
        else:
            parent_order = None

        if not warehouse or not warehouse.is_active:
            raise ValidationError("مخزن الصرف للإرجاع المحدد غير صالح أو معطل.")

        # Backend stock availability verification with select_for_update (Requirement B4)
        for itm in items_data:
            p = itm['product']
            q = parse_positive_integer_quantity(itm.get('quantity'), item_label=p.name)
            itm['quantity'] = q
            stock = InventoryStock.objects.select_for_update().filter(warehouse=warehouse, product=p).first()
            avail = stock.qty_available if stock else Decimal('0.00')
            if avail < q:
                raise ValidationError(
                    f"الرصيد المتاح من الصنف '{p.name}' في مخزن '{warehouse.name}' غير كافٍ للإرجاع ({avail:,.0f} متاح / {q:,.0f} مطلوب)."
                )

        now_dt = timezone.now()
        return_order = PurchaseReturnOrder.objects.create(
            supplier=supplier,
            warehouse=warehouse,
            purchase_order=parent_order,
            order_date=order_date or now_dt.date(),
            delivery_agent=delivery_agent,
            delivery_time=delivery_time,
            notes=notes,
            created_by=user,
            updated_by=user,
            status='settled',
            dispatched_at=now_dt
        )

        for idx, itm in enumerate(items_data, start=1):
            qty = Decimal(str(itm['quantity']))
            if qty <= Decimal('0.00'):
                raise ValidationError("الكمية المرتجعة يجب أن تكون أكبر من الصفر.")

            orig_item = None
            if parent_order:
                orig_item_id = itm.get('original_item_id') or getattr(itm.get('original_item'), 'id', None)
                if orig_item_id:
                    orig_item = parent_order.items.select_for_update().filter(id=orig_item_id).first()
                if not orig_item:
                    orig_item = parent_order.items.select_for_update().filter(product=itm['product']).first()

                if orig_item:
                    from django.db.models import Sum
                    returned_so_far = PurchaseReturnOrderItem.objects.filter(
                        return_order__purchase_order=parent_order,
                        original_item=orig_item
                    ).exclude(return_order__status__in=['cancelled', 'rejected']).aggregate(s=Sum('quantity'))['s'] or Decimal('0.00')

                    returnable_qty = orig_item.quantity - returned_so_far
                    if qty > returnable_qty:
                        raise ValidationError(
                            f"الكمية المرتجعة للصنف '{orig_item.product.name}' ({qty:,.0f}) تتجاوز الكمية المتاحة للإرجاع ({returnable_qty:,.0f}). "
                            f"(الكمية الأصلية: {orig_item.quantity:,.0f}، المرتجع سابقاً: {returned_so_far:,.0f})"
                        )

            PurchaseReturnOrderItem.objects.create(
                return_order=return_order,
                original_item=orig_item,
                item_order=idx,
                product=itm['product'],
                quantity=qty,
                unit_price=Decimal(str(itm['unit_price'])),
                product_batch_number=itm.get('batch_number', ''),
                product_expiry_date=itm.get('expiry_date') or None,
                tax_percentage=Decimal(str(itm.get('tax_percentage', 0)))
            )

        return_order.recalculate_totals()

        # Immediate warehouse dispatch: Outward InventoryMemo & decrement stock (Requirement B2, B4)
        memo_number = f"MEMO-OUT-RO-{return_order.serial_num}"
        memo = InventoryMemo.objects.create(
            memo_number=memo_number,
            memo_type='outward',
            warehouse=return_order.warehouse,
            statement=f"إذن صرف إرجاع مشتريات #{return_order.order_number} للمورد {return_order.supplier.name}",
            status='applied',
            applied_at=now_dt,
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

            stock = InventoryStock.objects.select_for_update().get(warehouse=return_order.warehouse, product=item.product)
            stock.qty_on_hand = max(Decimal('0.00'), stock.qty_on_hand - item.quantity)
            stock.save(update_fields=['qty_on_hand', 'updated_at'])

            if item.product_batch_number:
                lot = InventoryLot.objects.filter(stock=stock, batch_number=item.product_batch_number).first()
                if lot:
                    lot.quantity = max(Decimal('0.00'), lot.quantity - item.quantity)
                    lot.save(update_fields=['quantity'])

        return_order.memo = memo
        return_order.save(update_fields=['memo'])

        # Immediate financial execution: debit note on VendorAccount & VendorTransaction (Requirement B2)
        account = VendorAccount.get_or_create_for_supplier(return_order.supplier)
        new_balance = account.current_balance - return_order.grand_total

        tx = VendorTransaction.objects.create(
            account=account,
            purchase_order=parent_order,
            transaction_type='debit',
            reason='purchase_return',
            transaction_date=return_order.order_date or now_dt.date(),
            credit=Decimal('0.00'),
            debit=return_order.grand_total,
            running_balance=new_balance,
            description=f"إشعار خصم مرتجع مشتريات #{return_order.order_number} ({return_order.supplier.name})",
            created_by=user
        )

        account.current_balance = new_balance
        account.last_transaction_date = tx.transaction_date
        account.save(update_fields=['current_balance', 'last_transaction_date', 'updated_at'])

        if parent_order:
            remaining_to_deduct = return_order.grand_total
            for inst in VendorInstallment.objects.filter(transaction__purchase_order=parent_order, is_settled=False).order_by('due_date'):
                if remaining_to_deduct <= Decimal('0.00'):
                    break
                inst_rem = inst.open_amount
                if remaining_to_deduct >= inst_rem:
                    inst.closed_amount = inst.total_amount
                    inst.open_amount = Decimal('0.00')
                    inst.is_settled = True
                    remaining_to_deduct -= inst_rem
                else:
                    inst.closed_amount += remaining_to_deduct
                    inst.open_amount = max(Decimal('0.00'), inst.total_amount - inst.closed_amount)
                    remaining_to_deduct = Decimal('0.00')
                inst.save(update_fields=['closed_amount', 'open_amount', 'is_settled'])

        from activities.models import ApprovalAuditLog
        ApprovalAuditLog.objects.create(
            record_type='purchase_return',
            purchase_return=return_order,
            action='submitted',
            actor=user,
            status_before='',
            status_after='settled',
            reason="إنشاء وتنفيذ مرتجع المشتريات مباشرة في المخزن والحسابات"
        )

        AuditLogService.log(
            action_type='PURCHASE_RETURN_CREATED',
            module='purchases',
            actor=user,
            record_id=return_order.id,
            record_name=f"{return_order.order_number} ({return_order.supplier.name})",
            description=f"إنشاء أمر إرجاع مشتريات {return_order.order_number} للمورد {return_order.supplier.name} بقيمة {return_order.grand_total:,.2f} ج.م",
            new_values={
                'order_number': return_order.order_number,
                'supplier': return_order.supplier.name,
                'warehouse': return_order.warehouse.name,
                'grand_total': str(return_order.grand_total)
            }
        )
        return return_order

    @staticmethod
    @transaction.atomic
    def approve_return_order(return_order: PurchaseReturnOrder, user):
        """Transitions status from pending to approved with anti-self-approval."""
        from accounts.permissions import can_user_access_object
        from activities.models import ApprovalAuditLog

        locked_order = return_order.__class__.objects.select_for_update().get(pk=return_order.pk)
        if locked_order.status != 'pending':
            raise ValidationError(f"لا يمكن اعتماد مرتجع بحالة: {locked_order.get_status_display()}")

        if not can_user_access_object(user, locked_order, 'approve'):
            raise ValidationError("لا يمكنك اعتماد أمر إرجاع قمت بإنشائه بنفسك (منع الاعتماد الذاتي).")

        status_before = locked_order.status
        locked_order.status = 'approved'
        locked_order.approved_by = user
        locked_order.approved_at = timezone.now()
        locked_order.updated_by = user
        locked_order.save(update_fields=['status', 'approved_by', 'approved_at', 'updated_by', 'updated_at'])

        ApprovalAuditLog.objects.create(
            record_type='purchase_return',
            purchase_return=locked_order,
            action='approved',
            actor=user,
            status_before=status_before,
            status_after='approved',
            reason="اعتماد أمر إرجاع المشتريات من قبل الإدارة",
            changes=[{'field': 'الحالة', 'old': 'قيد الانتظار', 'new': 'معتمد'}],
        )

        AuditLogService.log(
            action_type='PURCHASE_RETURN_APPROVED',
            module='purchases',
            actor=user,
            record_id=locked_order.id,
            record_name=f"{locked_order.order_number} ({locked_order.supplier.name})",
            description=f"اعتماد أمر إرجاع مشتريات {locked_order.order_number}",
            previous_values={'status': status_before},
            new_values={'status': 'approved'}
        )
        return locked_order

    @staticmethod
    @transaction.atomic
    def reject_return_order(return_order: PurchaseReturnOrder, user, rejection_reason=""):
        """Rejects a pending purchase return order."""
        from activities.models import ApprovalAuditLog

        locked_order = return_order.__class__.objects.select_for_update().get(pk=return_order.pk)
        if locked_order.status != 'pending':
            raise ValidationError(f"لا يمكن رفض مرتجع بحالة: {locked_order.get_status_display()}")

        status_before = locked_order.status
        locked_order.status = 'rejected'
        locked_order.rejection_reason = rejection_reason
        locked_order.approved_by = user
        locked_order.approved_at = timezone.now()
        locked_order.updated_by = user
        locked_order.save(update_fields=['status', 'rejection_reason', 'approved_by', 'approved_at', 'updated_by', 'updated_at'])

        ApprovalAuditLog.objects.create(
            record_type='purchase_return',
            purchase_return=locked_order,
            action='rejected',
            actor=user,
            status_before=status_before,
            status_after='rejected',
            reason=rejection_reason or "رفض أمر إرجاع المشتريات",
            changes=[{'field': 'الحالة', 'old': 'قيد الانتظار', 'new': 'مرفوض'}],
        )

        AuditLogService.log(
            action_type='PURCHASE_RETURN_REJECTED',
            module='purchases',
            actor=user,
            record_id=locked_order.id,
            record_name=f"{locked_order.order_number} ({locked_order.supplier.name})",
            description=f"رفض أمر إرجاع مشتريات {locked_order.order_number}: {rejection_reason}",
            previous_values={'status': status_before},
            new_values={'status': 'rejected', 'rejection_reason': rejection_reason}
        )
        return locked_order

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

        # Verify sufficient stock (accounting for reserved quantities)
        for item in return_order.items.select_related('product'):
            stock = InventoryStock.objects.select_for_update().filter(warehouse=return_order.warehouse, product=item.product).first()
            available = stock.qty_available if stock else Decimal('0.00')
            if available < item.quantity:
                raise ValidationError(
                    f"الرصيد المتاح من الصنف '{item.product.name}' في مخزن '{return_order.warehouse.name}' غير كافٍ للإرجاع ({available:,.2f} متاح / {item.quantity:,.2f} مطلوب). (الكميات المحجوزة مستثناة من الرصيد المتاح)"
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

        from activities.models import ApprovalAuditLog
        ApprovalAuditLog.objects.create(
            record_type='purchase_return',
            purchase_return=return_order,
            action='status_changed',
            actor=user,
            status_before='approved',
            status_after='delivered',
            reason=f"صرف بضاعة المرتجع من مخزن {return_order.warehouse.name} (إذن صرف {memo.memo_number})",
            changes=[{'field': 'الحالة', 'old': 'معتمد', 'new': 'خرج من المخزن'}],
        )

        AuditLogService.log(
            action_type='PURCHASE_RETURN_DELIVERED',
            module='purchases',
            actor=user,
            record_id=return_order.id,
            record_name=f"{return_order.order_number} ({return_order.supplier.name})",
            description=f"صرف مرتجع مشتريات {return_order.order_number} من مخزن {return_order.warehouse.name} (إذن صرف {memo.memo_number})",
            previous_values={'status': 'approved'},
            new_values={'status': 'delivered', 'memo_number': memo.memo_number}
        )
        return return_order

    @staticmethod
    @transaction.atomic
    def settle_return_order(return_order: PurchaseReturnOrder, user):
        """
        Financial Settlement / Debit Note:
        1. Ensures goods were physically dispatched (status='delivered').
        2. Posts a double-entry Debit Note in VendorTransaction.
        3. Decrements supplier payable debt balance in VendorAccount.
        4. Reconciles open vendor installments if parent order is linked.
        5. Transitions status to settled.
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

        # Reconcile unpaid installments FIFO if purchase_order is linked
        if return_order.purchase_order:
            remaining_to_deduct = return_order.grand_total
            for inst in VendorInstallment.objects.filter(transaction__purchase_order=return_order.purchase_order, is_settled=False).order_by('due_date'):
                if remaining_to_deduct <= Decimal('0.00'):
                    break
                inst_rem = inst.open_amount
                if remaining_to_deduct >= inst_rem:
                    inst.closed_amount = inst.total_amount
                    inst.open_amount = Decimal('0.00')
                    inst.is_settled = True
                    remaining_to_deduct -= inst_rem
                else:
                    inst.closed_amount += remaining_to_deduct
                    inst.open_amount -= remaining_to_deduct
                    remaining_to_deduct = Decimal('0.00')
                inst.save(update_fields=['closed_amount', 'open_amount', 'is_settled'])

        return_order.settled_at = timezone.now()
        return_order.status = 'settled'
        return_order.updated_by = user
        return_order.save(update_fields=['settled_at', 'status', 'updated_by', 'updated_at'])

        from activities.models import ApprovalAuditLog
        ApprovalAuditLog.objects.create(
            record_type='purchase_return',
            purchase_return=return_order,
            action='status_changed',
            actor=user,
            status_before='delivered',
            status_after='settled',
            reason=f"ترحيل مرتجع المشتريات للحسابات (إشعار خصم #{tx.serial} بمبلغ {return_order.grand_total:,.2f} ج.م)",
            changes=[{'field': 'الحالة', 'old': 'خرج من المخزن', 'new': 'تم الترحيل للحسابات'}],
        )

        AuditLogService.log(
            action_type='PURCHASE_RETURN_SETTLED',
            module='purchases',
            actor=user,
            record_id=return_order.id,
            record_name=f"{return_order.order_number} ({return_order.supplier.name})",
            description=f"ترحيل مرتجع مشتريات {return_order.order_number} للحسابات (إشعار خصم #{tx.serial} بمبلغ {return_order.grand_total:,.2f} ج.م)",
            previous_values={'status': 'delivered'},
            new_values={'status': 'settled', 'transaction_serial': tx.serial, 'supplier_balance': str(new_balance)}
        )
        return return_order

    @staticmethod
    @transaction.atomic
    def cancel_return_order(return_order: PurchaseReturnOrder, user):
        """Cancels a pending or approved return order before unstocking."""
        if return_order.status in ['delivered', 'settled']:
            raise ValidationError("لا يمكن إلغاء أمر مرتجع بعد خروج البضاعة من المخزن أو ترحيله للحسابات.")
        status_before = return_order.status
        return_order.status = 'cancelled'
        return_order.updated_by = user
        return_order.save(update_fields=['status', 'updated_by', 'updated_at'])

        from activities.models import ApprovalAuditLog
        ApprovalAuditLog.objects.create(
            record_type='purchase_return',
            purchase_return=return_order,
            action='cancelled',
            actor=user,
            status_before=status_before,
            status_after='cancelled',
            reason="إلغاء أمر إرجاع المشتريات",
            changes=[{'field': 'الحالة', 'old': status_before, 'new': 'ملغي'}],
        )

        AuditLogService.log(
            action_type='PURCHASE_RETURN_CANCELLED',
            module='purchases',
            actor=user,
            record_id=return_order.id,
            record_name=f"{return_order.order_number} ({return_order.supplier.name})",
            description=f"إلغاء أمر إرجاع مشتريات {return_order.order_number}",
            previous_values={'status': status_before},
            new_values={'status': 'cancelled'}
        )
        return return_order

    @classmethod
    @transaction.atomic
    def delete_return_order(cls, return_order: PurchaseReturnOrder, user):
        """
        Deletes a purchase return order safely with financial and inventory reversal (Requirement B7):
        1. Restores deducted stock to warehouse.
        2. Restores lots.
        3. Reverts vendor ledger debt balance.
        4. Deletes outward memo and return order.
        5. Logs deletion to SecurityAuditLog.
        """
        import re
        return_order = PurchaseReturnOrder.objects.select_for_update().get(pk=return_order.pk)
        was_stocked = bool(return_order.memo_id) or return_order.status in ('delivered', 'settled')
        was_settled = return_order.status == 'settled'

        # 1. Restore stock to warehouse ONLY if stock was deducted
        if was_stocked and return_order.warehouse:
            for item in return_order.items.select_related('product'):
                stock, _ = InventoryStock.objects.select_for_update().get_or_create(
                    warehouse=return_order.warehouse,
                    product=item.product,
                    defaults={'product_cost': item.unit_price, 'qty_on_hand': Decimal('0.00'), 'qty_reserved': Decimal('0.00')}
                )
                stock.qty_on_hand += item.quantity
                stock.save(update_fields=['qty_on_hand', 'updated_at'])
                if item.product_batch_number:
                    lot = InventoryLot.objects.select_for_update().filter(
                        stock=stock, batch_number=item.product_batch_number
                    ).first()
                    if lot:
                        lot.quantity += item.quantity
                        lot.save(update_fields=['quantity'])

        # 2. Reverse vendor financial balance ONLY if settled (exact order_number token match to avoid prefix collisions)
        if was_settled:
            account = VendorAccount.get_or_create_for_supplier(return_order.supplier)
            account = VendorAccount.objects.select_for_update().get(pk=account.pk)
            account.current_balance += return_order.grand_total
            account.save(update_fields=['current_balance', 'updated_at'])

            token_pat = re.compile(r'(^|[^\dA-Za-z])' + re.escape(return_order.order_number) + r'($|[^\dA-Za-z])')
            candidate_txs = VendorTransaction.objects.filter(
                account=account,
                reason__in=['purchase_return', 'purchase_returns'],
                description__contains=return_order.order_number
            )
            matched_ids = [t.id for t in candidate_txs if token_pat.search(t.description or '')]
            if matched_ids:
                VendorTransaction.objects.filter(id__in=matched_ids).delete()

        # 4. Delete outward inventory memo
        if return_order.memo:
            memo = return_order.memo
            return_order.memo = None
            return_order.save(update_fields=['memo'])
            memo.items.all().delete()
            memo.delete()

        # 5. Audit log
        AuditLogService.log(
            action_type='PURCHASE_RETURN_DELETED',
            module='purchases',
            actor=user,
            record_id=return_order.id,
            record_name=f"{return_order.order_number} ({return_order.supplier.name})",
            description=f"حذف أمر إرجاع مشتريات رقم {return_order.order_number} للمورد {return_order.supplier.name} بقيمة {return_order.grand_total:,.2f} ج.م وعكس الحركات المخزنية والمالية",
            previous_values={'order_number': return_order.order_number, 'grand_total': str(return_order.grand_total)}
        )

        return_order.delete()
        return True


def build_purchase_return_timeline(return_order):
    """Builds full chronological timeline for a purchase return order."""
    events = []
    creator_name = (return_order.created_by.get_full_name() or return_order.created_by.username) if return_order.created_by else "النظام"

    events.append({
        'timestamp': return_order.created_at,
        'title': f"إنشاء أمر إرجاع المشتريات {return_order.order_number}",
        'actor': creator_name,
        'icon': 'assignment_return',
        'color': 'teal',
        'details': f"تم تسجيل إرجاع مشتريات للمورد «{return_order.supplier.name}»" + (f" لأمر الشراء #{return_order.purchase_order.order_number}" if return_order.purchase_order else "") + f" بقيمة {return_order.grand_total:,.2f} ج.م.",
        'changes': None,
        'approval_required': False,
    })

    for log in return_order.approval_history.select_related('actor').order_by('created_at', 'id'):
        if log.action == 'created':
            continue
        actor_str = (log.actor.get_full_name() or log.actor.username) if log.actor else "النظام"
        icon = 'history'
        color = 'slate'
        title = log.get_action_display()

        if log.action == 'approved':
            icon = 'check_circle'
            color = 'emerald'
            title = 'اعتماد أمر الإرجاع'
        elif log.action == 'rejected':
            icon = 'cancel'
            color = 'rose'
            title = 'رفض أمر الإرجاع'
        elif log.action == 'status_changed':
            if log.status_after == 'delivered':
                icon = 'warehouse'
                color = 'sky'
                title = 'صرف البضاعة من المخزن'
            elif log.status_after == 'settled':
                icon = 'account_balance'
                color = 'emerald'
                title = 'الترحيل للحسابات'
            else:
                icon = 'tune'
                color = 'purple'
                title = 'تغيير الحالة'
        elif log.action == 'cancelled':
            icon = 'block'
            color = 'rose'
            title = 'إلغاء أمر الإرجاع'

        events.append({
            'timestamp': log.created_at,
            'title': title,
            'actor': actor_str,
            'icon': icon,
            'color': color,
            'details': log.reason or '',
            'changes': log.changes if log.changes else None,
            'approval_required': False,
        })

    events.sort(key=lambda x: x['timestamp'] or timezone.now())
    return events


