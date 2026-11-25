import re
from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError

from .models import SalesOrder, SalesOrderItem, CustomerAccount, CustomerTransaction, Collection
from contacts.models import Contact, ContactAddress
from catalog.models import Product
from inventory.models import Warehouse, InventoryStock, InventoryMemo, InventoryMemoItem
from treasury.models import Vault, VaultTransaction
from master_data.validation_utils import parse_positive_integer_quantity


def _build_order_token_regex(order_number: str, serial_num=None):
    tokens = []
    if order_number:
        clean = str(order_number).strip()
        tokens.append(re.escape(clean))
        if clean.startswith('#'):
            tokens.append(re.escape(clean.lstrip('#')))
    if serial_num is not None and str(serial_num).strip():
        s = str(serial_num).strip()
        if re.escape(s) not in tokens:
            tokens.append(re.escape(f"#{s}"))
    if not tokens:
        return None
    return re.compile(r'(^|[^\dA-Za-z])(' + '|'.join(tokens) + r')($|[^\dA-Za-z])')


def find_existing_sales_order_transaction(order: SalesOrder, account: CustomerAccount = None):
    """Finds an already-posted CustomerTransaction(reason='sales') matching this SalesOrder."""
    if account is None:
        account = CustomerAccount.objects.filter(customer=order.customer).first()
    if not account:
        return None
    pat = _build_order_token_regex(order.order_number, order.serial_num)
    if not pat:
        return None
    raw_key = (order.order_number or '').lstrip('#').strip()
    qs = CustomerTransaction.objects.filter(account=account, reason='sales')
    if raw_key:
        qs = qs.filter(description__icontains=raw_key)
    for tx in qs.order_by('id'):
        if pat.search(tx.description or ''):
            return tx
    return None


def find_existing_sales_return_transaction(return_order, account: CustomerAccount = None):
    """Finds an already-posted CustomerTransaction(reason='sales_return') matching this SalesReturnOrder."""
    if account is None:
        account = CustomerAccount.objects.filter(customer=return_order.customer).first()
    if not account:
        return None
    pat = _build_order_token_regex(return_order.order_number, return_order.serial_num)
    if not pat:
        return None
    raw_key = (return_order.order_number or '').lstrip('#').strip()
    qs = CustomerTransaction.objects.filter(account=account, reason='sales_return')
    if raw_key:
        qs = qs.filter(description__icontains=raw_key)
    for tx in qs.order_by('id'):
        if pat.search(tx.description or ''):
            return tx
    return None


class CustomerAccountService:
    """Service layer for safe non-cash customer account adjustments (e.g., تصفير الحساب)."""

    @classmethod
    @transaction.atomic
    def zero_balance(cls, customer: Contact, user, reason_note: str = '', adjustment_date=None, request=None):
        """
        Zeros a customer's account balance via a non-cash accounting adjustment transaction.
        STRICT INVARIANTS:
        - Does NOT touch any Vault or create VaultTransaction / Collection records.
        - Does NOT modify any individual SalesOrder.payment_status.
        - Preserves full CustomerTransaction history and statements.
        - Writes SecurityAuditLog and emits notification on commit.
        """
        clean_reason = (reason_note or '').strip()
        if not clean_reason:
            raise ValidationError("يرجى إدخال سبب تصفير الحساب للتوثيق المحاسبي.")

        account = CustomerAccount.get_or_create_for_customer(customer)
        account = CustomerAccount.objects.select_for_update().get(pk=account.pk)
        previous_balance = account.current_balance or Decimal('0.00')
        if previous_balance == Decimal('0.00'):
            raise ValidationError("رصيد حساب العميل صفر بالفعل ولا يحتاج إلى تصفير.")

        tx_date = adjustment_date or timezone.now().date()
        if previous_balance > Decimal('0.00'):
            tx_type = 'credit'
            debit_amt = Decimal('0.00')
            credit_amt = previous_balance
        else:
            tx_type = 'debit'
            debit_amt = abs(previous_balance)
            credit_amt = Decimal('0.00')

        tx = CustomerTransaction.objects.create(
            account=account,
            transaction_type=tx_type,
            reason='adjustment',
            transaction_date=tx_date,
            debit=debit_amt,
            credit=credit_amt,
            running_balance=Decimal('0.00'),
            description=f"تصفير رصيد الحساب (تسوية غير نقدية) - {clean_reason}"[:255],
            created_by=user,
        )

        account.current_balance = Decimal('0.00')
        account.overdue_balance = Decimal('0.00')
        account.due_this_month_balance = Decimal('0.00')
        account.last_transaction_date = tx_date
        account.save(update_fields=['current_balance', 'overdue_balance', 'due_this_month_balance', 'last_transaction_date', 'updated_at'])

        from accounts.services import AuditLogService
        AuditLogService.log(
            action='update',
            action_type='CUSTOMER_BALANCE_ZEROED',
            module='sales',
            actor=user,
            record_id=account.id,
            record_name=f"حساب العميل: {customer.name}",
            description=(
                f"تصفير رصيد حساب العميل {customer.name} من {previous_balance:,.2f} ج.م إلى 0.00 ج.م "
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
                event_code='sales.customer_balance_zeroed',
                target_obj=account,
                actor=user,
                title=f"تصفير رصيد حساب العميل {customer.name}",
                body=f"تم تصفير الرصيد من {previous_balance:,.2f} ج.م إلى 0.00 ج.م (تسوية غير نقدية) - {clean_reason}",
                action_url=f"{reverse('customer_transactions_list')}?customer_id={customer.id}",
                dedupe_key=f"sales.customer_balance_zeroed:{tx.serial}",
            )
        except Exception:
            pass

        return tx, previous_balance

    @classmethod
    @transaction.atomic
    def record_settlement(
        cls,
        customer: Contact,
        amount: Decimal,
        direction: str,
        user,
        reason_note: str,
        settlement_date=None,
        reference: str = '',
        request=None,
    ):
        """
        Records a non-cash customer account settlement / adjustment.
        STRICT INVARIANTS:
        - Affects CustomerAccount.current_balance ONLY via CustomerTransaction(reason='settlement').
        - direction='credit' reduces customer debt (current_balance -= amount).
        - direction='debit' increases customer debt (current_balance += amount).
        - Strictly ZERO Vault / VaultTransaction / Collection / Inventory impact.
        - Never modifies SalesOrder.payment_status or original orders/collections.
        - Writes SecurityAuditLog.
        """
        amount = Decimal(str(amount or '0.00')).quantize(Decimal('0.01'))
        if amount <= Decimal('0.00'):
            raise ValidationError("مبلغ التسوية يجب أن يكون أكبر من الصفر.")

        if direction not in ('credit', 'debit'):
            raise ValidationError("نوع التسوية يجب أن يكون دائن (تخفيض رصيد) أو مدين (زيادة رصيد).")

        clean_reason = (reason_note or '').strip()
        if not clean_reason:
            raise ValidationError("يرجى إدخال سبب التسوية للتوثيق المحاسبي.")

        clean_ref = (reference or '').strip()
        account = CustomerAccount.get_or_create_for_customer(customer)
        account = CustomerAccount.objects.select_for_update().get(pk=account.pk)
        previous_balance = account.current_balance or Decimal('0.00')

        if direction == 'credit':
            debit_amt = Decimal('0.00')
            credit_amt = amount
            new_balance = previous_balance - amount
        else:
            debit_amt = amount
            credit_amt = Decimal('0.00')
            new_balance = previous_balance + amount

        tx_date = settlement_date or timezone.now().date()
        ref_part = f" [مرجع: {clean_ref}]" if clean_ref else ""
        desc = f"تسوية حساب عميل (غير نقدية){ref_part} - {clean_reason}"[:255]

        tx = CustomerTransaction.objects.create(
            account=account,
            transaction_type=direction,
            reason='settlement',
            transaction_date=tx_date,
            debit=debit_amt,
            credit=credit_amt,
            running_balance=new_balance,
            description=desc,
            created_by=user,
        )

        account.current_balance = new_balance
        if new_balance <= Decimal('0.00'):
            account.overdue_balance = Decimal('0.00')
            account.due_this_month_balance = Decimal('0.00')
        else:
            if (account.overdue_balance or Decimal('0.00')) > new_balance:
                account.overdue_balance = new_balance
            if (account.due_this_month_balance or Decimal('0.00')) > new_balance:
                account.due_this_month_balance = new_balance
        account.last_transaction_date = tx_date
        account.save(update_fields=[
            'current_balance', 'overdue_balance', 'due_this_month_balance',
            'last_transaction_date', 'updated_at',
        ])

        from accounts.services import AuditLogService
        AuditLogService.log(
            action='create',
            action_type='CUSTOMER_SETTLEMENT_CREATED',
            module='sales',
            actor=user,
            record_id=tx.id,
            record_name=f"تسوية حساب عميل #{tx.serial} ({customer.name})",
            description=(
                f"تسجيل تسوية حساب غير نقدية للعميل {customer.name} ({'دائن / تخفيض' if direction == 'credit' else 'مدين / زيادة'}) "
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

    @classmethod
    @transaction.atomic
    def reverse_settlement(cls, tx_id, user, reason_note: str = '', request=None):
        """
        Reverses a non-cash customer settlement/adjustment transaction by posting an exact opposing entry.
        ZERO vault impact. Prevents double reversal.
        """
        tx = CustomerTransaction.objects.select_for_update().select_related('account__customer').get(pk=tx_id)
        if tx.reason not in ('settlement', 'adjustment'):
            raise ValidationError("يمكن عكس قيود التسويات والتعديلات الحسابية فقط.")
        if tx.is_reversed:
            raise ValidationError(f"قيد التسوية #{tx.serial} معكوس بالفعل.")

        account = CustomerAccount.objects.select_for_update().get(pk=tx.account_id)
        previous_balance = account.current_balance or Decimal('0.00')
        amount = tx.credit if tx.transaction_type == 'credit' else tx.debit
        opp_type = 'debit' if tx.transaction_type == 'credit' else 'credit'
        if opp_type == 'debit':
            debit_amt, credit_amt = amount, Decimal('0.00')
            new_balance = previous_balance + amount
        else:
            debit_amt, credit_amt = Decimal('0.00'), amount
            new_balance = previous_balance - amount

        clean_reason = (reason_note or '').strip() or 'عكس قيد تسوية'
        tx_date = timezone.now().date()
        rev_tx = CustomerTransaction.objects.create(
            account=account,
            transaction_type=opp_type,
            reason='settlement',
            transaction_date=tx_date,
            debit=debit_amt,
            credit=credit_amt,
            running_balance=new_balance,
            description=f"عكس تسوية #{tx.serial} - {clean_reason}"[:255],
            created_by=user,
        )

        tx.is_reversed = True
        tx.reversal_transaction = rev_tx
        tx.save(update_fields=['is_reversed', 'reversal_transaction'])

        account.current_balance = new_balance
        account.last_transaction_date = tx_date
        account.save(update_fields=['current_balance', 'last_transaction_date', 'updated_at'])

        from accounts.services import AuditLogService
        AuditLogService.log(
            action='update',
            action_type='CUSTOMER_SETTLEMENT_REVERSED',
            module='sales',
            actor=user,
            record_id=tx.id,
            record_name=f"عكس تسوية عميل #{tx.serial}",
            description=(
                f"عكس تسوية حساب العميل {account.customer.name} #{tx.serial} بمبلغ {amount:,.2f} ج.م "
                f"(قيد العكس #{rev_tx.serial} — بدون تأثير على الخزن)"
            ),
            previous_values={'current_balance': str(previous_balance), 'is_reversed': False},
            new_values={'current_balance': str(new_balance), 'is_reversed': True, 'reversal_serial': rev_tx.serial},
            reason=clean_reason,
            request=request,
        )

        return rev_tx


def has_historical_sales_activity(customer) -> bool:
    """Returns True if `customer` has any non-cancelled SalesOrder, non-zero CustomerAccount balance, or CustomerTransaction."""
    if not customer or not getattr(customer, 'pk', None):
        return False
    return (
        SalesOrder.objects.filter(customer_id=customer.pk).exclude(status='cancelled').exists()
        or CustomerAccount.objects.filter(customer_id=customer.pk).exclude(current_balance=Decimal('0.00')).exists()
        or CustomerTransaction.objects.filter(account__customer_id=customer.pk).exists()
    )


def validate_sales_customer_eligibility(customer, *, allow_existing_customer_id=None, allow_historical_lead=False, sales_order=None):
    """
    Enforces Customer-only eligibility across Sales workflows while preserving
    legitimate historical Lead workflows:
    - Always requires `customer` with `is_customer=True` and `status != 'inactive'`.
    - New Sales Orders strictly require `status == 'customer'`.
    - Editing an existing Sales Order allows keeping its current `lead` customer
      (`customer.pk == allow_existing_customer_id`), while rejecting switching to
      any other `lead` or `inactive` contact.
    - Collections (`allow_historical_lead=True`) allow `status == 'customer'`,
      and allow `status == 'lead'` when settling a linked `sales_order` or an
      existing historical order/account balance/ledger.
    """
    if not customer or not getattr(customer, 'is_customer', False):
        raise ValidationError("جهة الاتصال المحددة غير مصنفة كعميل.")
    if customer.status == 'inactive':
        raise ValidationError("لا يمكن إجراء عمليات بيع أو تحصيل لعميل غير نشط.")
    if customer.status == 'customer':
        return
    if allow_existing_customer_id is not None and customer.pk == allow_existing_customer_id:
        return
    if allow_historical_lead and customer.status == 'lead':
        if sales_order is not None and sales_order.customer_id == customer.pk:
            return
        if has_historical_sales_activity(customer):
            return
    raise ValidationError("يمكن اختيار العملاء المعتمدين فقط (حالة: عميل). لا يمكن اختيار عميل محتمل (Lead) لهذه العملية.")


class SalesOrderService:

    @classmethod
    @transaction.atomic
    def create_order(cls, customer, source_warehouse, order_date, items_data, user, delivery_address=None, delivery_date=None, due_date=None, custom_discount_percentage=Decimal('0.00'), shipping_fees=Decimal('0.00'), notes='', validate_stock=True):
        """
        Creates a new SalesOrder with line items, stock validation, and discount/grand_total computation.
        """
        validate_sales_customer_eligibility(customer)
        if not items_data:
            raise ValidationError("يجب إضافة صنف واحد على الأقل في أمر البيع.")

        # Ensure customer account exists
        CustomerAccount.get_or_create_for_customer(customer)

        # Resolve and validate source warehouse
        from accounts.services import is_representative, get_representative_warehouse
        from accounts.permissions import can_user_access_object
        rep_wh = get_representative_warehouse(user) if is_representative(user) else None
        if rep_wh and source_warehouse and source_warehouse.pk != rep_wh.pk and not (user.is_superuser or getattr(user, 'is_super_admin', False)):
            raise ValidationError(f"غير مصرح للمندوب بإجراء مبيعات من مخزن آخر ({source_warehouse.name}). يجب استخدام مخزن العهدة الخاص بك ({rep_wh.name}).")
        if not source_warehouse:
            if rep_wh:
                source_warehouse = rep_wh
            else:
                raise ValidationError("يرجى تحديد المخزن.")
        elif not can_user_access_object(user, source_warehouse, 'operate'):
            raise ValidationError(f"غير مصرح للمندوب بإجراء مبيعات من مخزن آخر ({source_warehouse.name}).")

        if not source_warehouse.is_active:
            raise ValidationError(f"مخزن الصرف المحدد ({source_warehouse.name}) غير نشط حالياً.")

        custom_disc_pct = Decimal(str(custom_discount_percentage or '0.00'))
        if custom_disc_pct < Decimal('0.00') or custom_disc_pct > Decimal('100.00'):
            raise ValidationError("نسبة الخصم الإضافي على أمر البيع يجب أن تكون بين 0% و 100%.")

        shipping = Decimal(str(shipping_fees or '0.00'))
        if shipping < Decimal('0.00'):
            raise ValidationError("مصاريف الشحن / التوصيل يجب أن تكون قيمة موجبة أو صفر.")

        # Pre-validate line items values and aggregated stock availability (prevents duplicate-line oversell)
        qty_by_product = {}
        prod_map = {}
        for item in items_data:
            product = item['product']
            qty = parse_positive_integer_quantity(item.get('quantity'), item_label=product.name)
            price = Decimal(str(item.get('unit_price', 0)))
            disc = Decimal(str(item.get('discount_percentage', 0)))

            if price < Decimal('0.00'):
                raise ValidationError(f"سعر البيع للصنف '{product.name}' لا يمكن أن يكون سالباً.")
            if disc < Decimal('0.00') or disc > Decimal('100.00'):
                raise ValidationError(f"نسبة الخصم للصنف '{product.name}' يجب أن تكون بين 0% و 100%.")

            qty_by_product[product.id] = qty_by_product.get(product.id, Decimal('0.00')) + qty
            prod_map[product.id] = product

        if validate_stock:
            for prod_id in sorted(qty_by_product.keys()):
                product = prod_map[prod_id]
                total_qty = qty_by_product[prod_id]
                stock, _ = InventoryStock.objects.select_for_update().get_or_create(
                    warehouse=source_warehouse,
                    product=product,
                    defaults={'qty_on_hand': Decimal('0.00'), 'qty_reserved': Decimal('0.00'), 'product_cost': product.default_purchase_cost}
                )
                qty_avail = stock.qty_available
                if qty_avail < total_qty:
                    raise ValidationError(
                        f"الرصيد المتاح من الصنف '{product.name}' في {source_warehouse.name} ({qty_avail:,.0f}) غير كافٍ للكمية المطلوبة ({total_qty:,.0f})."
                    )

        from master_data.models import SalesSettings
        sales_settings = SalesSettings.get_settings()
        is_super = user.is_superuser or getattr(user, 'is_super_admin', False)
        needs_approval = bool(getattr(sales_settings, 'require_manager_approval', False)) and not is_super

        order = SalesOrder(
            customer=customer,
            source_warehouse=source_warehouse,
            delivery_address=delivery_address,
            order_date=order_date or timezone.now().date(),
            delivery_date=delivery_date,
            due_date=due_date,
            custom_discount_percentage=custom_disc_pct,
            shipping_fees=shipping,
            status='pending' if needs_approval else 'invoiced',
            approved_by=None if needs_approval else user,
            approved_at=None if needs_approval else timezone.now(),
            notes=notes,
            created_by=user
        )
        order.save()

        for item in items_data:
            product = item['product']
            qty = Decimal(str(item['quantity']))
            price = Decimal(str(item['unit_price']))
            disc = Decimal(str(item.get('discount_percentage', 0)))

            SalesOrderItem.objects.create(
                order=order,
                product=product,
                quantity=qty,
                unit_price=price,
                discount_percentage=disc
            )

        order.recalculate_totals()

        if not needs_approval:
            cls._post_order_stock_and_ledger(order, user)

        from activities.models import ApprovalAuditLog
        ApprovalAuditLog.objects.create(
            record_type='sales_order',
            sales_order=order,
            action='submitted',
            actor=user,
            status_before='',
            status_after=order.status,
            reason=notes or ('إنشاء أمر بيع بانتظار اعتماد الإدارة' if needs_approval else 'إنشاء وتنفيذ أمر البيع تلقائياً')
        )

        from accounts.services import AuditLogService
        AuditLogService.log(
            action_type='SALES_ORDER_CREATED',
            module='sales',
            actor=user,
            record_id=order.id,
            record_name=f"Sales Order #{order.order_number}",
            description=f"إنشاء وتنفيذ أمر بيع رقم {order.order_number} للعميل {customer.name} بقيمة {order.grand_total}",
            new_values={
                'order_number': order.order_number,
                'customer': customer.name,
                'subtotal': str(order.subtotal),
                'items_discount_total': str(order.items_discount_total),
                'custom_discount_percentage': str(order.custom_discount_percentage),
                'shipping_fees': str(order.shipping_fees),
                'grand_total': str(order.grand_total),
                'status': order.status,
                'items_count': len(items_data),
                'due_date': str(order.due_date) if order.due_date else None,
            }
        )

        return order

    @classmethod
    @transaction.atomic
    def update_order(cls, order, customer, source_warehouse, order_date, items_data, user, delivery_address=None, delivery_date=None, due_date=None, custom_discount_percentage=Decimal('0.00'), shipping_fees=Decimal('0.00'), notes='', validate_stock=False):
        """
        Updates an editable sales order (pending/rejected/manager_approval before preparation),
        revalidates stock availability, replaces line items, recalculates totals, and logs audit record.
        """
        if order.status in ['preparing', 'delivered', 'invoiced', 'cancelled']:
            raise ValidationError(f"لا يمكن تعديل أمر البيع في حالته الحالية: {order.get_status_display()}.")

        validate_sales_customer_eligibility(customer, allow_existing_customer_id=order.customer_id)

        if not items_data:
            raise ValidationError("يجب إضافة صنف واحد على الأقل في أمر البيع.")

        # Resolve and validate source warehouse
        from accounts.services import is_representative, get_representative_warehouse
        from accounts.permissions import can_user_access_object
        rep_wh = get_representative_warehouse(user) if is_representative(user) else None
        if rep_wh and source_warehouse and source_warehouse.pk != rep_wh.pk and not (user.is_superuser or getattr(user, 'is_super_admin', False)):
            raise ValidationError(f"غير مصرح للمندوب بإجراء مبيعات من مخزن آخر ({source_warehouse.name}). يجب استخدام مخزن العهدة الخاص بك ({rep_wh.name}).")
        if not source_warehouse:
            if rep_wh:
                source_warehouse = rep_wh
            else:
                raise ValidationError("يرجى تحديد المخزن.")
        elif not can_user_access_object(user, source_warehouse, 'operate'):
            raise ValidationError(f"غير مصرح للمندوب بإجراء مبيعات من مخزن آخر ({source_warehouse.name}).")

        if not source_warehouse.is_active:
            raise ValidationError(f"مخزن الصرف المحدد ({source_warehouse.name}) غير نشط حالياً.")

        custom_disc_pct = Decimal(str(custom_discount_percentage or '0.00'))
        if custom_disc_pct < Decimal('0.00') or custom_disc_pct > Decimal('100.00'):
            raise ValidationError("نسبة الخصم الإضافي على أمر البيع يجب أن تكون بين 0% و 100%.")

        shipping = Decimal(str(shipping_fees or '0.00'))
        if shipping < Decimal('0.00'):
            raise ValidationError("مصاريف الشحن / التوصيل يجب أن تكون قيمة موجبة أو صفر.")

        # Validate line items and stock availability
        for item in items_data:
            product = item['product']
            qty = parse_positive_integer_quantity(item.get('quantity'), item_label=product.name)
            price = Decimal(str(item.get('unit_price', 0)))
            disc = Decimal(str(item.get('discount_percentage', 0)))

            if price < Decimal('0.00'):
                raise ValidationError(f"سعر البيع للصنف '{product.name}' لا يمكن أن يكون سالباً.")
            if disc < Decimal('0.00') or disc > Decimal('100.00'):
                raise ValidationError(f"نسبة الخصم للصنف '{product.name}' يجب أن تكون بين 0% و 100%.")

            if validate_stock:
                # Check stock in source warehouse (accounting for reservations)
                stock = InventoryStock.objects.filter(warehouse=source_warehouse, product=product).first()
                qty_avail = stock.qty_available if stock else Decimal('0.00')
                if qty_avail < qty:
                    raise ValidationError(
                        f"الرصيد المتاح من الصنف '{product.name}' في {source_warehouse.name} ({qty_avail:,.0f}) غير كافٍ للكمية المطلوبة ({qty:,.0f})."
                    )

        previous_values = {
            'customer': order.customer.name if order.customer else '',
            'source_warehouse': order.source_warehouse.name if order.source_warehouse else '',
            'subtotal': str(order.subtotal),
            'items_discount_total': str(order.items_discount_total),
            'custom_discount_percentage': str(order.custom_discount_percentage),
            'shipping_fees': str(order.shipping_fees),
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
        order.custom_discount_percentage = custom_disc_pct
        order.shipping_fees = shipping
        order.notes = notes
        order.save(update_fields=[
            'customer', 'source_warehouse', 'order_date', 'delivery_date',
            'due_date', 'delivery_address', 'custom_discount_percentage',
            'shipping_fees', 'notes', 'updated_at'
        ])

        # Replace line items
        order.items.all().delete()

        for item in items_data:
            product = item['product']
            qty = Decimal(str(item['quantity']))
            price = Decimal(str(item['unit_price']))
            disc = Decimal(str(item.get('discount_percentage', 0)))
            tax_pct = Decimal(str(item.get('tax_percentage', 0)))

            SalesOrderItem.objects.create(
                order=order,
                product=product,
                quantity=qty,
                unit_price=price,
                discount_percentage=disc,
                tax_percentage=tax_pct,
            )

        order.recalculate_totals()

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
                'subtotal': str(order.subtotal),
                'items_discount_total': str(order.items_discount_total),
                'custom_discount_percentage': str(order.custom_discount_percentage),
                'shipping_fees': str(order.shipping_fees),
                'grand_total': str(order.grand_total),
                'due_date': str(order.due_date) if order.due_date else None,
                'notes': order.notes,
                'items_count': len(items_data),
            }
        )
        return order

    @classmethod
    def _post_order_stock_and_ledger(cls, order: SalesOrder, user, release_reserved: bool = False):
        """
        Centralized, idempotent automatic posting for SalesOrder:
        1. Deducts stock & creates outward InventoryMemo ONLY if order.memo is None.
        2. Posts debit CustomerTransaction ONLY if no matching sales transaction already exists.
        Must be called inside @transaction.atomic with order locked.
        """
        memo = order.memo
        if not memo:
            memo_number = f"MEMO-OUT-{order.serial_num}"
            memo, created_memo = InventoryMemo.objects.get_or_create(
                memo_number=memo_number,
                defaults={
                    'memo_type': 'outward',
                    'warehouse': order.source_warehouse,
                    'statement': f"صرف أمر بيع رقم {order.order_number} للعميل {order.customer.name}",
                    'status': 'applied',
                    'applied_at': timezone.now(),
                    'notes': f"Generated from Sales Order #{order.order_number}",
                    'created_by': user,
                }
            )
            if created_memo:
                for item in order.items.select_related('product'):
                    InventoryMemoItem.objects.get_or_create(
                        memo=memo,
                        product=item.product,
                        defaults={
                            'quantity': item.quantity,
                            'unit_cost': item.product.default_purchase_cost,
                        }
                    )
                    stock, _ = InventoryStock.objects.select_for_update().get_or_create(
                        warehouse=order.source_warehouse,
                        product=item.product,
                        defaults={
                            'qty_on_hand': Decimal('0.00'),
                            'qty_reserved': Decimal('0.00'),
                            'product_cost': item.product.default_purchase_cost,
                        }
                    )
                    stock.qty_on_hand = max(Decimal('0.00'), stock.qty_on_hand - item.quantity)
                    if release_reserved:
                        stock.qty_reserved = max(Decimal('0.00'), stock.qty_reserved - item.quantity)
                    stock.save(update_fields=['qty_on_hand', 'qty_reserved', 'updated_at'])
            order.memo = memo
            order.save(update_fields=['memo'])

        account = CustomerAccount.get_or_create_for_customer(order.customer)
        account = CustomerAccount.objects.select_for_update().get(pk=account.pk)
        existing_tx = find_existing_sales_order_transaction(order, account=account)
        if not existing_tx:
            new_balance = account.current_balance + order.grand_total
            CustomerTransaction.objects.create(
                account=account,
                transaction_type='debit',
                reason='sales',
                transaction_date=timezone.now().date(),
                debit=order.grand_total,
                credit=Decimal('0.00'),
                running_balance=new_balance,
                description=f"فاتورة مبيعات أمر بيع #{order.order_number}",
                created_by=user,
            )
            account.current_balance = new_balance
            account.last_transaction_date = timezone.now().date()
            account.save(update_fields=['current_balance', 'last_transaction_date', 'updated_at'])
        return memo

    @classmethod
    @transaction.atomic
    def approve_order(cls, order, user, notes=''):
        """
        Approves the sales order by management with anti-self-approval and manager scoping.
        Automatically executes warehouse dispatch (InventoryMemo + stock deduction)
        and customer ledger invoicing (CustomerTransaction Debit), moving status directly to 'invoiced'.
        """
        order = SalesOrder.objects.select_for_update().get(pk=order.pk)
        if order.status not in ['pending', 'rejected', 'manager_approval']:
            raise ValidationError(f"لا يمكن اعتماد الطلب في حالته الحالية: {order.get_status_display()}.")

        from accounts.permissions import is_manager_eligible_for_user
        is_super = user.is_superuser or getattr(user, 'is_super_admin', False)
        if not is_super:
            if order.created_by_id == user.id:
                raise ValidationError("لا يمكن للمنشئ أو المندوب اعتماد أمر البيع الخاص به.")
            if order.created_by and not is_manager_eligible_for_user(user, order.created_by):
                raise ValidationError("غير مصرح لك باعتماد أمر البيع لمندوب خارج نطاق منطقتك الرئيسية.")

        status_before = order.status

        # 1. Authoritative atomic stock validation (only if stock hasn't already been deducted via memo)
        if not order.memo_id:
            for item in order.items.select_related('product'):
                stock, _ = InventoryStock.objects.select_for_update().get_or_create(
                    warehouse=order.source_warehouse,
                    product=item.product,
                    defaults={'qty_on_hand': Decimal('0.00'), 'qty_reserved': Decimal('0.00'), 'product_cost': item.product.default_purchase_cost}
                )
                effective_avail = stock.qty_available if status_before != 'preparing' else (stock.qty_available + item.quantity)
                if effective_avail < item.quantity:
                    raise ValidationError(
                        f"لا يمكن اعتماد أمر البيع لعدم توفر رصيد كافٍ من الصنف '{item.product.name}' في {order.source_warehouse.name}. "
                        f"الرصيد المتاح: {effective_avail:,.2f}، الكمية المطلوبة: {item.quantity:,.2f}."
                    )

        # 2 & 3. Centralized idempotent stock & ledger posting
        memo = cls._post_order_stock_and_ledger(order, user, release_reserved=(status_before == 'preparing'))

        order.status = 'invoiced'
        order.approved_by = user
        order.approved_at = timezone.now()
        order.rejection_reason = ''
        order.save(update_fields=['status', 'approved_by', 'approved_at', 'rejection_reason', 'memo', 'updated_at'])

        from activities.models import ApprovalAuditLog
        ApprovalAuditLog.objects.create(
            record_type='sales_order',
            sales_order=order,
            action='approved',
            actor=user,
            status_before=status_before,
            status_after='invoiced',
            reason=notes or 'اعتماد وصرف وفوترة تلقائية لأمر البيع'
        )

        from accounts.services import AuditLogService
        AuditLogService.log(
            action_type='SALES_ORDER_APPROVED',
            module='sales',
            actor=user,
            record_id=order.id,
            record_name=f"Sales Order #{order.order_number}",
            description=f"اعتماد وصرف وفوترة أمر بيع رقم {order.order_number} بواسطة {user.name or user.username}",
            previous_values={'status': status_before},
            new_values={'status': 'invoiced', 'approved_by': str(user), 'memo': memo.memo_number if memo else None}
        )
        return order

    @classmethod
    @transaction.atomic
    def update_payment_status(cls, order, new_status, user, notes=''):
        """
        Updates the operational payment classification of a sales order with audit trail.
        """
        valid_statuses = [c[0] for c in SalesOrder.PAYMENT_STATUS_CHOICES]
        if new_status not in valid_statuses:
            raise ValidationError(f"حالة سداد غير صالحة: {new_status}")

        old_status = order.payment_status
        if old_status == new_status:
            return order

        order.payment_status = new_status
        order.save(update_fields=['payment_status', 'updated_at'])

        from activities.models import ApprovalAuditLog
        ApprovalAuditLog.objects.create(
            record_type='sales_order',
            sales_order=order,
            action='payment_status_updated',
            actor=user,
            status_before=old_status,
            status_after=new_status,
            reason=notes or f"تغيير حالة السداد التجارية إلى {order.payment_status_display_ar}"
        )

        from accounts.services import AuditLogService
        AuditLogService.log(
            action_type='SALES_ORDER_PAYMENT_STATUS_UPDATED',
            module='sales',
            actor=user,
            record_id=order.id,
            record_name=f"Sales Order #{order.order_number}",
            description=f"تعديل حالة السداد لأمر بيع #{order.order_number} من {old_status} إلى {new_status}",
            previous_values={'payment_status': old_status},
            new_values={'payment_status': new_status, 'notes': notes}
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
        if order.status in ['preparing', 'delivered', 'invoiced']:
            return order
        if order.status != 'manager_approval':
            raise ValidationError(f"يجب اعتماد أمر البيع أولاً قبل تجهيزه بالمخزن.")

        # Check and reserve stock
        for item in order.items.select_related('product'):
            stock, _ = InventoryStock.objects.select_for_update().get_or_create(
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
        if order.status in ['delivered', 'invoiced']:
            return order
        if order.status not in ['preparing', 'manager_approval']:
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

            stock = InventoryStock.objects.select_for_update().get(
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
        Idempotent financial posting for a SalesOrder (auto-reconciles if already posted).
        """
        order = SalesOrder.objects.select_for_update().get(pk=order.pk)
        if order.status == 'invoiced':
            return order
        if order.status not in ['delivered', 'manager_approval', 'preparing']:
            raise ValidationError(f"يجب اعتماد أو تسليم الطلب قبل ترحيل الفاتورة للحسابات.")

        account = CustomerAccount.get_or_create_for_customer(order.customer)
        account = CustomerAccount.objects.select_for_update().get(pk=account.pk)
        existing_tx = find_existing_sales_order_transaction(order, account=account)
        if not existing_tx:
            new_balance = account.current_balance + order.grand_total
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
            account.save(update_fields=['current_balance', 'last_transaction_date', 'updated_at'])
        else:
            new_balance = account.current_balance

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
            new_values={'status': 'invoiced', 'customer_balance': str(new_balance), 'reused_existing_tx': bool(existing_tx)}
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

    @classmethod
    @transaction.atomic
    def delete_order(cls, order, user):
        """
        Deletes a sales order safely with financial and inventory reversal (Requirement B7):
        1. Checks no payments/collections are recorded against this order.
        2. Restores deducted stock to source warehouse.
        3. Creates credit reversal or deletes invoice transaction on customer account.
        4. Deletes outward inventory memo and order line items.
        5. Logs deletion to SecurityAuditLog.
        """
        import re
        order = SalesOrder.objects.select_for_update().get(pk=order.pk)

        if order.collections.exists() or (hasattr(order, 'collections_applied') and order.collections_applied.exists()):
            raise ValidationError("لا يمكن حذف أمر بيع مرتبط بمتحصلات مالية مسجلة. يرجى إلغاء أو حذف سندات التحصيل أولاً.")

        if order.return_orders.exclude(status='cancelled').exists():
            raise ValidationError("لا يمكن حذف أمر البيع لوجود مرتجعات مبيعات مسجلة عليه. يرجى حذف أو إلغاء المرتجعات أولاً.")

        was_stocked = bool(order.memo_id) or order.status in ('delivered', 'invoiced')
        was_invoiced = order.status == 'invoiced'

        # 1. Restore stock ONLY if stock was actually deducted
        if was_stocked and order.source_warehouse:
            for item in order.items.select_related('product'):
                stock, _ = InventoryStock.objects.select_for_update().get_or_create(
                    warehouse=order.source_warehouse,
                    product=item.product,
                    defaults={'qty_on_hand': Decimal('0.00'), 'qty_reserved': Decimal('0.00'), 'product_cost': item.product.default_purchase_cost}
                )
                stock.qty_on_hand += item.quantity
                stock.save(update_fields=['qty_on_hand', 'updated_at'])

        # 2. Revert Customer Account balance ONLY if invoiced (exact token match avoids SO-1 vs SO-10 collisions)
        if was_invoiced:
            account = CustomerAccount.get_or_create_for_customer(order.customer)
            account = CustomerAccount.objects.select_for_update().get(pk=account.pk)
            account.current_balance -= order.grand_total
            account.save(update_fields=['current_balance', 'updated_at'])

            token_pat = re.compile(r'(^|[^\dA-Za-z])' + re.escape(order.order_number) + r'($|[^\dA-Za-z])')
            candidate_txs = CustomerTransaction.objects.filter(
                account=account,
                reason='sales',
                description__contains=order.order_number
            )
            matched_ids = [t.id for t in candidate_txs if token_pat.search(t.description or '')]
            if matched_ids:
                CustomerTransaction.objects.filter(id__in=matched_ids).delete()

        # 3. Delete outward InventoryMemo if exists
        memo = order.memo
        if memo:
            order.memo = None
            order.save(update_fields=['memo'])
            memo.items.all().delete()
            memo.delete()

        serial = order.serial_num
        order_num = order.order_number
        customer_name = order.customer.name
        grand_total = str(order.grand_total)

        # 4. Audit Log
        from accounts.services import AuditLogService
        AuditLogService.log(
            action='delete',
            action_type='SALES_ORDER_DELETED',
            module='sales',
            actor=user,
            record_id=order.id,
            record_name=f"Sales Order #{order_num}",
            description=f"حذف أمر بيع رقم {order_num} للعميل {customer_name} وإعادة المخزون وعكس القيد المالي ({grand_total} ج.م)",
            status='SUCCESS'
        )

        order.items.all().delete()
        order.delete()


class CollectionService:

    @classmethod
    @transaction.atomic
    def record_collection(cls, customer, vault, amount, user, payment_method='cash', notes='', sales_order=None, collection_date=None, due_date=None):
        """
        Records customer cash/cheque/bank collection:
        1. Validates customer eligibility and optional SalesOrder ownership.
        2. Concurrency locks Vault and CustomerAccount.
        3. Deposits cash into ANY authorized active Vault chosen by the user.
        4. Posts Credit transaction in Customer Ledger and lowers CustomerAccount.current_balance.
        5. Never auto-modifies SalesOrder.payment_status and never caps by independent order debt.
        6. Records audit log.
        """
        validate_sales_customer_eligibility(
            customer,
            allow_historical_lead=True,
            sales_order=sales_order,
        )
        amount = Decimal(str(amount))
        if amount <= 0:
            raise ValidationError("قيمة التحصيل يجب أن تكون أكبر من الصفر.")

        if sales_order:
            if sales_order.customer_id != customer.id:
                raise ValidationError("أمر البيع المحدد لا ينتمي لهذا العميل.")
            if sales_order.status == 'cancelled':
                raise ValidationError("لا يمكن تحصيل مبالغ لأمر بيع ملغى.")

        # Concurrency lock on Vault and CustomerAccount
        vault = Vault.objects.select_for_update().get(id=vault.id)
        if not vault.is_active:
            raise ValidationError(f"الخزنة ({vault.name}) معطلة حالياً ولا يمكن الإيداع بها.")

        account = CustomerAccount.get_or_create_for_customer(customer)
        account = CustomerAccount.objects.select_for_update().get(pk=account.pk)
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


class SalesReturnOrderService:

    @classmethod
    @transaction.atomic
    def create_return_order(cls, sales_order, target_warehouse=None, order_date=None, items_data=None, user=None, notes="", **kwargs):
        """
        Creates a new SalesReturnOrder strictly referencing an eligible original order and its items.
        Enforces Returnable Quantity = Original Ordered Quantity - Previously Returned Quantity.
        """
        target_warehouse = target_warehouse or kwargs.get('destination_warehouse')
        notes = notes or kwargs.get('reason', '')
        if not items_data:
            raise ValidationError("يجب إضافة صنف واحد على الأقل في أمر إرجاع المبيعات.")

        if not sales_order:
            raise ValidationError("أمر البيع الأصلي إلزامي لإنشاء مرتجع مبيعات.")

        # Lock parent order to prevent concurrent over-returns
        parent_order = SalesOrder.objects.select_for_update().get(pk=sales_order.pk)
        if parent_order.status not in ['delivered', 'invoiced']:
            raise ValidationError(f"لا يمكن إنشاء مرتجع لأمر بيع بحالة '{parent_order.status_display_ar}'. يجب أن يكون أمر البيع مسلماً أو مفوتراً.")

        warehouse = target_warehouse or parent_order.source_warehouse
        if not warehouse:
            raise ValidationError("يرجى تحديد مخزن استلام المرتجع.")

        from .models import SalesReturnOrder, SalesReturnOrderItem
        from activities.models import ApprovalAuditLog

        return_order = SalesReturnOrder.objects.create(
            sales_order=parent_order,
            customer=parent_order.customer,
            target_warehouse=warehouse,
            order_date=order_date or timezone.now().date(),
            notes=notes,
            created_by=user,
            updated_by=user,
            status='pending'
        )

        for itm in items_data:
            orig_item_id = itm.get('original_item_id') or itm.get('sales_order_item_id') or getattr(itm.get('original_item'), 'id', None)
            if not orig_item_id:
                raise ValidationError("يجب تحديد بند أمر البيع الأصلي لكل صنف في المرتجع.")

            orig_item = parent_order.items.select_for_update().filter(id=orig_item_id).first()
            if not orig_item:
                raise ValidationError("الصنف المحدد غير موجود في بنود أمر البيع الأصلي.")

            qty = parse_positive_integer_quantity(itm.get('quantity'), item_label=orig_item.product.name)

            # Calculate previously returned quantity
            from django.db.models import Sum
            returned_so_far = SalesReturnOrderItem.objects.filter(
                order__sales_order=parent_order,
                original_item=orig_item
            ).exclude(order__status__in=['cancelled', 'rejected']).aggregate(s=Sum('quantity'))['s'] or Decimal('0.00')

            returnable_qty = orig_item.quantity - returned_so_far
            if qty > returnable_qty:
                raise ValidationError(
                    f"الكمية المرتجعة من الصنف '{orig_item.product.name}' ({qty:,.0f}) تتجاوز الكمية المتبقية القابلة للإرجاع ({returnable_qty:,.0f}). "
                    f"(الكمية الأصلية: {orig_item.quantity:,.0f}، المرتجع سابقاً: {returned_so_far:,.0f})"
                )

            unit_price = Decimal(str(itm.get('unit_price', orig_item.unit_price)))
            disc_pct = Decimal(str(itm.get('discount_percentage', orig_item.discount_percentage or 0)))
            tax_pct = Decimal(str(itm.get('tax_percentage', orig_item.tax_percentage or 0)))
            condition = itm.get('condition')
            if not condition:
                condition = 'damaged' if itm.get('is_damaged') else 'resalable'
            batch = itm.get('batch_number', '')
            expiry = itm.get('expiry_date') or None

            SalesReturnOrderItem.objects.create(
                order=return_order,
                original_item=orig_item,
                product=orig_item.product,
                condition=condition,
                quantity=qty,
                unit_price=unit_price,
                discount_percentage=disc_pct,
                tax_percentage=tax_pct,
                batch_number=batch,
                expiry_date=expiry
            )

        return_order.recalculate_totals()

        # Immediate warehouse execution: Inward InventoryMemo + stock increment (Requirement B2)
        memo_number = f"MEMO-IN-RET-{return_order.serial_num}"
        memo = InventoryMemo.objects.create(
            memo_number=memo_number,
            memo_type='inward',
            warehouse=return_order.target_warehouse,
            statement=f"استلام مرتجع مبيعات رقم {return_order.order_number} لأمر البيع {parent_order.order_number}",
            status='applied',
            applied_at=timezone.now(),
            notes=f"Generated from Sales Return #{return_order.order_number}",
            created_by=user
        )
        for itm in return_order.items.select_related('product'):
            InventoryMemoItem.objects.create(
                memo=memo,
                product=itm.product,
                quantity=itm.quantity,
                unit_cost=itm.product.default_purchase_cost
            )
            if itm.condition == 'resalable':
                stock, _ = InventoryStock.objects.select_for_update().get_or_create(
                    warehouse=return_order.target_warehouse,
                    product=itm.product,
                    defaults={'qty_on_hand': Decimal('0.00'), 'qty_reserved': Decimal('0.00'), 'product_cost': itm.product.default_purchase_cost}
                )
                stock.qty_on_hand += itm.quantity
                stock.save(update_fields=['qty_on_hand', 'updated_at'])

        return_order.memo = memo
        return_order.status = 'settled'
        return_order.stocked_at = timezone.now()
        return_order.settled_at = timezone.now()
        return_order.save(update_fields=['memo', 'status', 'stocked_at', 'settled_at'])

        # Immediate financial execution: Post credit note to CustomerAccount (allow negative balance = customer credit)
        account = CustomerAccount.get_or_create_for_customer(return_order.customer)
        account = CustomerAccount.objects.select_for_update().get(pk=account.pk)
        new_balance = account.current_balance - return_order.grand_total
        CustomerTransaction.objects.create(
            account=account,
            transaction_type='credit',
            reason='sales_return',
            transaction_date=timezone.now().date(),
            debit=Decimal('0.00'),
            credit=return_order.grand_total,
            running_balance=new_balance,
            description=f"إشعار دائن مرتجع مبيعات #{return_order.order_number}",
            created_by=user
        )
        account.current_balance = new_balance
        account.last_transaction_date = timezone.now().date()
        account.save(update_fields=['current_balance', 'last_transaction_date', 'updated_at'])

        ApprovalAuditLog.objects.create(
            record_type='sales_return',
            sales_return=return_order,
            action='created',
            actor=user,
            status_before='',
            status_after='settled',
            reason=f"إنشاء وتنفيذ إشعار مرتجع مبيعات لأمر البيع #{parent_order.order_number}",
            changes=[{'field': 'الحالة', 'old': '-', 'new': 'مرحل بالحسابات'}],
        )

        from accounts.services import AuditLogService
        AuditLogService.log(
            action_type='SALES_RETURN_CREATED',
            module='sales',
            actor=user,
            record_id=return_order.id,
            record_name=f"{return_order.order_number} ({return_order.customer.name})",
            description=f"إنشاء وتنفيذ مرتجع مبيعات {return_order.order_number} لأمر البيع {parent_order.order_number} بمبلغ {return_order.grand_total:,.2f} ج.م",
            new_values={
                'order_number': return_order.order_number,
                'sales_order': parent_order.order_number,
                'customer': return_order.customer.name,
                'warehouse': return_order.target_warehouse.name,
                'grand_total': str(return_order.grand_total)
            }
        )
        return return_order

    @classmethod
    @transaction.atomic
    def delete_return_order(cls, return_order, user):
        """
        Deletes a sales return order safely with financial and inventory reversal:
        1. Checks warehouse available stock is sufficient before deducting.
        2. Deducts returned stock from warehouse.
        3. Reverts Customer Account balance (restores debt).
        4. Deletes inward memo and return order.
        5. Logs deletion to SecurityAuditLog.
        """
        import re
        return_order = SalesReturnOrder.objects.select_for_update().get(pk=return_order.pk)
        was_stocked = bool(return_order.memo_id) or return_order.status in ('delivered', 'settled')
        was_settled = return_order.status == 'settled'

        if was_stocked and return_order.target_warehouse:
            resalable_items = [i for i in return_order.items.select_related('product') if i.condition == 'resalable']
            qty_by_prod = {}
            prod_names = {}
            for item in resalable_items:
                qty_by_prod[item.product_id] = qty_by_prod.get(item.product_id, Decimal('0.00')) + item.quantity
                prod_names[item.product_id] = item.product.name
            for prod_id, needed_qty in sorted(qty_by_prod.items()):
                stock = InventoryStock.objects.select_for_update().filter(
                    warehouse=return_order.target_warehouse,
                    product_id=prod_id,
                ).first()
                if not stock or stock.qty_available < needed_qty:
                    raise ValidationError(
                        f"لا يمكن حذف مرتجع المبيعات لأن رصيد الصنف '{prod_names[prod_id]}' المتاح في المخزن أقل من الكمية المرتجعة."
                    )
            for item in resalable_items:
                stock = InventoryStock.objects.select_for_update().get(
                    warehouse=return_order.target_warehouse,
                    product=item.product,
                )
                stock.qty_on_hand -= item.quantity
                stock.save(update_fields=['qty_on_hand', 'updated_at'])

        if was_settled:
            account = CustomerAccount.get_or_create_for_customer(return_order.customer)
            account = CustomerAccount.objects.select_for_update().get(pk=account.pk)
            account.current_balance += return_order.grand_total
            account.save(update_fields=['current_balance', 'updated_at'])

            token_pat = re.compile(r'(^|[^\dA-Za-z])' + re.escape(return_order.order_number) + r'($|[^\dA-Za-z])')
            candidate_txs = CustomerTransaction.objects.filter(
                account=account,
                reason='sales_return',
                description__contains=return_order.order_number
            )
            matched_ids = [t.id for t in candidate_txs if token_pat.search(t.description or '')]
            if matched_ids:
                CustomerTransaction.objects.filter(id__in=matched_ids).delete()

        memo = return_order.memo
        if memo:
            return_order.memo = None
            return_order.save(update_fields=['memo'])
            memo.items.all().delete()
            memo.delete()

        order_num = return_order.order_number
        customer_name = return_order.customer.name
        grand_total = str(return_order.grand_total)

        from accounts.services import AuditLogService
        AuditLogService.log(
            action='delete',
            action_type='SALES_RETURN_DELETED',
            module='sales',
            actor=user,
            record_id=return_order.id,
            record_name=f"Sales Return #{order_num}",
            description=f"حذف مرتجع مبيعات رقم {order_num} للعميل {customer_name} وعكس المخزون والقيد المالي ({grand_total} ج.م)",
            status='SUCCESS'
        )

        return_order.items.all().delete()
        return_order.delete()

    @classmethod
    def _post_return_stock_and_ledger(cls, locked_order, user):
        """Centralized idempotent stock receipt & customer credit posting for SalesReturnOrder."""
        from inventory.models import InventoryLot
        now_dt = timezone.now()
        if not locked_order.memo_id:
            memo_number = f"MEMO-IN-SRET-{locked_order.serial_num}"
            memo, created_memo = InventoryMemo.objects.get_or_create(
                memo_number=memo_number,
                defaults={
                    'memo_type': 'inward',
                    'warehouse': locked_order.target_warehouse,
                    'statement': f"إذن إضافة استلام مرتجع مبيعات {locked_order.order_number} من العميل {locked_order.customer.name}",
                    'status': 'applied',
                    'applied_at': now_dt,
                    'created_by': user,
                }
            )
            if created_memo:
                for item in locked_order.items.select_related('product'):
                    InventoryMemoItem.objects.create(
                        memo=memo,
                        product=item.product,
                        quantity=item.quantity,
                        unit_cost=item.unit_price,
                        batch_number=item.batch_number,
                        expiry_date=item.expiry_date,
                    )
                    if item.condition == 'resalable':
                        stock, _ = InventoryStock.objects.select_for_update().get_or_create(
                            warehouse=locked_order.target_warehouse,
                            product=item.product,
                            defaults={'qty_on_hand': Decimal('0.00'), 'qty_reserved': Decimal('0.00')}
                        )
                        stock.qty_on_hand += item.quantity
                        stock.save(update_fields=['qty_on_hand', 'updated_at'])
                        if item.batch_number:
                            lot, _ = InventoryLot.objects.get_or_create(
                                stock=stock,
                                batch_number=item.batch_number,
                                defaults={'quantity': Decimal('0.00'), 'expiry_date': item.expiry_date}
                            )
                            lot.quantity += item.quantity
                            if item.expiry_date and not lot.expiry_date:
                                lot.expiry_date = item.expiry_date
                            lot.save()
            locked_order.memo = memo
            locked_order.stocked_at = now_dt

        account = CustomerAccount.get_or_create_for_customer(locked_order.customer)
        account = CustomerAccount.objects.select_for_update().get(pk=account.pk)
        existing_tx = find_existing_sales_return_transaction(locked_order, account=account)
        if not existing_tx:
            new_balance = account.current_balance - locked_order.grand_total
            tx = CustomerTransaction.objects.create(
                account=account,
                transaction_type='credit',
                reason='sales_return',
                transaction_date=now_dt.date(),
                credit=locked_order.grand_total,
                debit=Decimal('0.00'),
                running_balance=new_balance,
                description=f"إشعار دائن مرتجع مبيعات {locked_order.order_number}" + (f" (أمر بيع #{locked_order.sales_order.order_number})" if locked_order.sales_order else ""),
                created_by=user,
            )
            account.current_balance = new_balance
            account.last_transaction_date = tx.transaction_date
            account.save(update_fields=['current_balance', 'last_transaction_date', 'updated_at'])
        else:
            tx = existing_tx
        locked_order.settled_at = locked_order.settled_at or now_dt
        locked_order.status = 'settled'
        return tx

    @classmethod
    @transaction.atomic
    def approve_return_order(cls, return_order, user, notes="", **kwargs):
        """
        Approves a pending SalesReturnOrder with anti-self-approval and
        automatically posts warehouse stock receipt and customer ledger credit ('settled').
        """
        from accounts.permissions import can_user_access_object
        from activities.models import ApprovalAuditLog
        from accounts.services import AuditLogService

        locked_order = return_order.__class__.objects.select_for_update().get(pk=return_order.pk)
        if locked_order.status != 'pending':
            raise ValidationError(f"لا يمكن اعتماد مرتجع بحالة: {locked_order.status_display_ar}")

        if not can_user_access_object(user, locked_order, 'approve'):
            raise ValidationError("لا يمكنك اعتماد أمر إرجاع قمت بإنشائه بنفسك (منع الاعتماد الذاتي).")

        status_before = locked_order.status
        locked_order.approved_by = user
        locked_order.approved_at = timezone.now()
        locked_order.updated_by = user
        tx = cls._post_return_stock_and_ledger(locked_order, user)
        locked_order.save()

        ApprovalAuditLog.objects.create(
            record_type='sales_return',
            sales_return=locked_order,
            action='approved',
            actor=user,
            status_before=status_before,
            status_after='settled',
            reason=notes or "اعتماد واستلام وترحيل تلقائي لمرتجع المبيعات",
            changes=[{'field': 'الحالة', 'old': 'قيد الانتظار', 'new': 'تم الترحيل للحسابات'}],
        )

        AuditLogService.log(
            action_type='SALES_RETURN_APPROVED',
            module='sales',
            actor=user,
            record_id=locked_order.id,
            record_name=f"{locked_order.order_number} ({locked_order.customer.name})",
            description=f"اعتماد وترحيل تلقائي لمرتجع مبيعات {locked_order.order_number}",
            previous_values={'status': status_before},
            new_values={'status': 'settled', 'transaction_serial': tx.serial if tx else None}
        )

        return locked_order

    @classmethod
    @transaction.atomic
    def reject_return_order(cls, return_order, user, rejection_reason="", reason="", **kwargs):
        """Rejects a pending sales return order."""
        rejection_reason = rejection_reason or reason or kwargs.get('notes', '')
        from activities.models import ApprovalAuditLog
        from accounts.services import AuditLogService

        locked_order = return_order.__class__.objects.select_for_update().get(pk=return_order.pk)
        if locked_order.status != 'pending':
            raise ValidationError(f"لا يمكن رفض مرتجع بحالة: {locked_order.status_display_ar}")

        status_before = locked_order.status
        locked_order.status = 'rejected'
        locked_order.rejection_reason = rejection_reason
        locked_order.approved_by = user
        locked_order.approved_at = timezone.now()
        locked_order.updated_by = user
        locked_order.save(update_fields=['status', 'rejection_reason', 'approved_by', 'approved_at', 'updated_by', 'updated_at'])

        ApprovalAuditLog.objects.create(
            record_type='sales_return',
            sales_return=locked_order,
            action='rejected',
            actor=user,
            status_before=status_before,
            status_after='rejected',
            reason=rejection_reason or "رفض مرتجع المبيعات",
            changes=[{'field': 'الحالة', 'old': 'قيد الانتظار', 'new': 'مرفوض'}],
        )

        AuditLogService.log(
            action_type='SALES_RETURN_REJECTED',
            module='sales',
            actor=user,
            record_id=locked_order.id,
            record_name=f"{locked_order.order_number} ({locked_order.customer.name})",
            description=f"رفض مرتجع مبيعات {locked_order.order_number}: {rejection_reason}",
            previous_values={'status': status_before},
            new_values={'status': 'rejected', 'rejection_reason': rejection_reason}
        )
        return locked_order

    @classmethod
    @transaction.atomic
    def deliver_return_order(cls, return_order, user):
        """
        Warehouse Receiving / Inward Memo:
        1. Resalable goods are added to InventoryStock and InventoryLot.
        2. Damaged goods are documented in memo without adding to usable InventoryStock.
        3. Transitions status to 'delivered'.
        """
        from activities.models import ApprovalAuditLog
        from accounts.services import AuditLogService
        from inventory.models import InventoryLot

        locked_order = return_order.__class__.objects.select_for_update().get(pk=return_order.pk)
        if locked_order.status in ['delivered', 'settled']:
            return locked_order
        if locked_order.status != 'approved':
            raise ValidationError(f"لا يمكن استلام بضاعة المرتجع بالمخزن إلا بعد الاعتماد الإداري (الحالة الحالية: {locked_order.status_display_ar}).")

        memo_number = f"MEMO-IN-SRET-{locked_order.serial_num}"
        memo = InventoryMemo.objects.create(
            memo_number=memo_number,
            memo_type='inward',
            warehouse=locked_order.target_warehouse,
            statement=f"إذن إضافة استلام مرتجع مبيعات {locked_order.order_number} من العميل {locked_order.customer.name}",
            status='applied',
            applied_at=timezone.now(),
            created_by=user
        )

        for item in locked_order.items.select_related('product'):
            InventoryMemoItem.objects.create(
                memo=memo,
                product=item.product,
                quantity=item.quantity,
                unit_cost=item.unit_price,
                batch_number=item.batch_number,
                expiry_date=item.expiry_date
            )

            # Only add to sellable inventory if condition is resalable
            if item.condition == 'resalable':
                stock, _ = InventoryStock.objects.select_for_update().get_or_create(
                    warehouse=locked_order.target_warehouse,
                    product=item.product,
                    defaults={'qty_on_hand': Decimal('0.00'), 'qty_reserved': Decimal('0.00')}
                )
                stock.qty_on_hand += item.quantity
                stock.save(update_fields=['qty_on_hand', 'updated_at'])

                if item.batch_number:
                    lot, _ = InventoryLot.objects.get_or_create(
                        stock=stock,
                        batch_number=item.batch_number,
                        defaults={'quantity': Decimal('0.00'), 'expiry_date': item.expiry_date}
                    )
                    lot.quantity += item.quantity
                    if item.expiry_date and not lot.expiry_date:
                        lot.expiry_date = item.expiry_date
                    lot.save()

        locked_order.memo = memo
        locked_order.stocked_at = timezone.now()
        locked_order.status = 'delivered'
        locked_order.updated_by = user
        locked_order.save(update_fields=['memo', 'stocked_at', 'status', 'updated_by', 'updated_at'])

        ApprovalAuditLog.objects.create(
            record_type='sales_return',
            sales_return=locked_order,
            action='status_changed',
            actor=user,
            status_before='approved',
            status_after='delivered',
            reason=f"استلام بضاعة المرتجع بالمخزن {locked_order.target_warehouse.name} (إذن إضافة {memo.memo_number})",
            changes=[{'field': 'الحالة', 'old': 'معتمد', 'new': 'مستلم بالمخزن'}],
        )

        AuditLogService.log(
            action_type='SALES_RETURN_DELIVERED',
            module='sales',
            actor=user,
            record_id=locked_order.id,
            record_name=f"{locked_order.order_number} ({locked_order.customer.name})",
            description=f"استلام مرتجع مبيعات {locked_order.order_number} في مخزن {locked_order.target_warehouse.name} (إذن إضافة {memo.memo_number})",
            previous_values={'status': 'approved'},
            new_values={'status': 'delivered', 'memo_number': memo.memo_number}
        )
        return locked_order

    @classmethod
    @transaction.atomic
    def settle_return_order(cls, return_order, user):
        """
        Financial Settlement / Credit Note:
        1. Ensures goods were physically received in warehouse (status='delivered').
        2. Posts Credit entry in CustomerTransaction.
        3. Decrements customer debt balance in CustomerAccount.
        4. Transitions status to 'settled'.
        """
        from activities.models import ApprovalAuditLog
        from accounts.services import AuditLogService

        locked_order = return_order.__class__.objects.select_for_update().get(pk=return_order.pk)
        if locked_order.status == 'settled':
            return locked_order
        if locked_order.status != 'delivered':
            raise ValidationError("يجب استلام بضاعة المرتجع بالمخزن أولاً (Delivered) قبل الترحيل للحسابات.")

        account = CustomerAccount.get_or_create_for_customer(locked_order.customer)
        account = CustomerAccount.objects.select_for_update().get(pk=account.pk)
        existing_tx = find_existing_sales_return_transaction(locked_order, account=account)
        if not existing_tx:
            new_balance = account.current_balance - locked_order.grand_total
            tx = CustomerTransaction.objects.create(
                account=account,
                transaction_type='credit',
                reason='sales_return',
                transaction_date=timezone.now().date(),
                credit=locked_order.grand_total,
                debit=Decimal('0.00'),
                running_balance=new_balance,
                description=f"إشعار دائن مرتجع مبيعات {locked_order.order_number}" + (f" (أمر بيع #{locked_order.sales_order.order_number})" if locked_order.sales_order else ""),
                created_by=user
            )
            account.current_balance = new_balance
            account.last_transaction_date = tx.transaction_date
            account.save(update_fields=['current_balance', 'last_transaction_date', 'updated_at'])
        else:
            tx = existing_tx
            new_balance = account.current_balance

        locked_order.settled_at = timezone.now()
        locked_order.status = 'settled'
        locked_order.updated_by = user
        locked_order.save(update_fields=['settled_at', 'status', 'updated_by', 'updated_at'])

        ApprovalAuditLog.objects.create(
            record_type='sales_return',
            sales_return=locked_order,
            action='status_changed',
            actor=user,
            status_before='delivered',
            status_after='settled',
            reason=f"ترحيل مرتجع المبيعات للحسابات (إشعار دائن #{tx.serial} بمبلغ {locked_order.grand_total:,.2f} ج.م)",
            changes=[{'field': 'الحالة', 'old': 'مستلم بالمخزن', 'new': 'تم الترحيل للحسابات'}],
        )

        AuditLogService.log(
            action_type='SALES_RETURN_SETTLED',
            module='sales',
            actor=user,
            record_id=locked_order.id,
            record_name=f"{locked_order.order_number} ({locked_order.customer.name})",
            description=f"ترحيل مرتجع مبيعات {locked_order.order_number} للحسابات (إشعار دائن #{tx.serial} بمبلغ {locked_order.grand_total:,.2f} ج.م)",
            previous_values={'status': 'delivered'},
            new_values={'status': 'settled', 'transaction_serial': tx.serial, 'customer_balance': str(new_balance)}
        )
        return locked_order

    @classmethod
    @transaction.atomic
    def cancel_return_order(cls, return_order, user, reason=''):
        """Cancels a pending or approved return order before warehouse receiving."""
        from activities.models import ApprovalAuditLog
        from accounts.services import AuditLogService

        locked_order = return_order.__class__.objects.select_for_update().get(pk=return_order.pk)
        if locked_order.status in ['delivered', 'settled']:
            raise ValidationError("لا يمكن إلغاء أمر مرتجع بعد استلام البضاعة في المخزن أو ترحيله للحسابات.")

        status_before = locked_order.status
        locked_order.status = 'cancelled'
        locked_order.updated_by = user
        locked_order.save(update_fields=['status', 'updated_by', 'updated_at'])

        ApprovalAuditLog.objects.create(
            record_type='sales_return',
            sales_return=locked_order,
            action='cancelled',
            actor=user,
            status_before=status_before,
            status_after='cancelled',
            reason="إلغاء أمر مرتجع المبيعات",
            changes=[{'field': 'الحالة', 'old': status_before, 'new': 'ملغي'}],
        )

        AuditLogService.log(
            action_type='SALES_RETURN_CANCELLED',
            module='sales',
            actor=user,
            record_id=locked_order.id,
            record_name=f"{locked_order.order_number} ({locked_order.customer.name})",
            description=f"إلغاء أمر مرتجع مبيعات {locked_order.order_number}",
            previous_values={'status': status_before},
            new_values={'status': 'cancelled'}
        )
        return locked_order


def build_sales_return_timeline(return_order):
    """Builds full chronological timeline for a sales return order."""
    from activities.models import ApprovalAuditLog
    from accounts.models import SecurityAuditLog

    events = []
    creator_name = (return_order.created_by.get_full_name() or return_order.created_by.username) if return_order.created_by else "النظام"

    events.append({
        'timestamp': return_order.created_at,
        'title': f"إنشاء مرتجع المبيعات {return_order.order_number}",
        'actor': creator_name,
        'icon': 'assignment_return',
        'color': 'teal',
        'details': f"تم تسجيل إشعار مرتجع مبيعات للعميل «{return_order.customer.name}» لأمر البيع #{return_order.sales_order.order_number if return_order.sales_order else '-'}.",
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
            title = 'اعتماد مرتجع المبيعات'
        elif log.action == 'rejected':
            icon = 'cancel'
            color = 'rose'
            title = 'رفض مرتجع المبيعات'
        elif log.action == 'status_changed':
            if log.status_after == 'delivered':
                icon = 'warehouse'
                color = 'sky'
                title = 'استلام البضاعة في المخزن'
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
            title = 'إلغاء مرتجع المبيعات'

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
