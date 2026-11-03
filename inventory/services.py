from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.db.models import Max

from .models import (
    Warehouse, InventoryStock, InventoryLot, InventoryMemo, InventoryMemoItem,
    ProductTransferRequest, ProductTransferRequestItem
)
from catalog.models import Product
from accounts.permissions import (
    is_accountant, is_manager_eligible_for_user, has_perm_or_admin,
    can_user_perform_stock_in, can_user_perform_stock_out, can_user_perform_transfer
)
from accounts.services import AuditLogService


class InventoryMemoService:
    """
    Enterprise service for Warehouse Stock Operations:
    - Stock In (إذن إضافة): Adds stock, updates lots, recalculates weighted average cost
    - Stock Out (إذن صرف): Validates real available stock (excluding reserved stock), deducts stock
    - Strict role permissions and audit logging
    """

    @classmethod
    @transaction.atomic
    def create_memo(cls, warehouse, memo_type, statement, items_data, user, notes=''):
        if not user or not user.is_authenticated:
            raise ValidationError("يجب تسجيل الدخول لإجراء حركة مخزنية.")

        if not warehouse or not warehouse.is_active:
            raise ValidationError("المخزن المحدد غير صالح أو معطل حالياً.")

        if memo_type == 'inward':
            if not can_user_perform_stock_in(user, warehouse):
                raise ValidationError("غير مصرح لك بإنشاء إذن إضافة لهذا المخزن.")
        elif memo_type == 'outward':
            if not can_user_perform_stock_out(user, warehouse):
                raise ValidationError("غير مصرح لك بإنشاء إذن صرف من هذا المخزن.")
        else:
            raise ValidationError(f"نوع إذن غير معروف: {memo_type}")

        if not items_data:
            raise ValidationError("يجب إضافة صنف واحد على الأقل في الإذن المخزني.")

        from master_data.models import CompanyProfile
        profile = CompanyProfile.get_settings()
        now = timezone.now()

        prefix = "MEMO-IN" if memo_type == 'inward' else "MEMO-OUT"
        max_id = InventoryMemo.objects.filter(memo_type=memo_type).aggregate(Max('id'))['id__max'] or 0
        memo_number = f"{prefix}-{now.strftime('%y%m%d')}-{max_id + 1:04d}"

        memo = InventoryMemo.objects.create(
            memo_number=memo_number,
            memo_type=memo_type,
            warehouse=warehouse,
            statement=statement or ("إذن إضافة مخزنية" if memo_type == 'inward' else "إذن صرف مخزني"),
            status='applied',
            applied_at=now,
            notes=notes,
            created_by=user
        )

        for item_entry in items_data:
            product = item_entry['product']
            if isinstance(product, (int, str)):
                product = Product.objects.get(id=int(product))

            qty = Decimal(str(item_entry.get('quantity', 0)))
            if qty <= 0:
                raise ValidationError(f"الكمية للصنف '{product.name}' يجب أن تكون أكبر من الصفر.")

            batch = (item_entry.get('batch_number') or '').strip()
            expiry = item_entry.get('expiry_date') or None

            if profile.is_batch_mandatory and not batch:
                raise ValidationError(f"رقم التشغيل إلزامي للصنف '{product.name}'.")
            if profile.is_expiry_mandatory and not expiry:
                raise ValidationError(f"تاريخ الصلاحية إلزامي للصنف '{product.name}'.")

            # Acquire row-level lock on inventory stock record
            stock, _ = InventoryStock.objects.select_for_update().get_or_create(
                warehouse=warehouse,
                product=product,
                defaults={
                    'qty_on_hand': Decimal('0.00'),
                    'qty_reserved': Decimal('0.00'),
                    'product_cost': product.default_purchase_cost or Decimal('0.00'),
                }
            )

            if memo_type == 'inward':
                unit_cost = Decimal(str(item_entry.get('unit_cost', stock.product_cost or 0)))
                if unit_cost < 0:
                    raise ValidationError(f"سعر التكلفة للصنف '{product.name}' لا يمكن أن يكون سالباً.")

                old_qty = stock.qty_on_hand
                new_qty = old_qty + qty
                if new_qty > 0 and unit_cost > 0:
                    old_cost = stock.product_cost or Decimal('0.00')
                    stock.product_cost = ((old_qty * old_cost) + (qty * unit_cost)) / new_qty

                stock.qty_on_hand += qty
                stock.save(update_fields=['qty_on_hand', 'product_cost', 'updated_at'])

                if batch or expiry:
                    lot, _ = InventoryLot.objects.get_or_create(
                        stock=stock,
                        batch_number=batch or 'DEFAULT',
                        defaults={'expiry_date': expiry, 'quantity': Decimal('0.00')}
                    )
                    lot.quantity += qty
                    if expiry:
                        lot.expiry_date = expiry
                    lot.save()

            else:  # outward
                unit_cost = stock.product_cost
                # Available stock validation (strictly excludes reserved stock)
                if stock.qty_available < qty:
                    raise ValidationError(
                        f"الرصيد المتاح من الصنف '{product.name}' في المخزن ({stock.qty_available:,.2f}) "
                        f"غير كافٍ لصرف الكمية المطلوبة ({qty:,.2f})."
                    )

                stock.qty_on_hand = max(Decimal('0.00'), stock.qty_on_hand - qty)
                stock.save(update_fields=['qty_on_hand', 'updated_at'])

                if batch:
                    lot = InventoryLot.objects.filter(stock=stock, batch_number=batch).first()
                    if lot:
                        lot.quantity = max(Decimal('0.00'), lot.quantity - qty)
                        lot.save()

            InventoryMemoItem.objects.create(
                memo=memo,
                product=product,
                quantity=qty,
                unit_cost=unit_cost,
                batch_number=batch,
                expiry_date=expiry
            )

        AuditLogService.log(
            user=user,
            action='STOCK_IN' if memo_type == 'inward' else 'STOCK_OUT',
            resource_type='InventoryMemo',
            resource_id=str(memo.id),
            resource_name=memo.memo_number,
            details={
                'warehouse': warehouse.name,
                'memo_type': memo_type,
                'items_count': len(items_data),
                'statement': memo.statement
            }
        )

        return memo


class ProductTransferService:
    """
    Enterprise service managing the complete lifecycle of inter-warehouse product requests:
    1. Same main area validation (canonical root area traversal)
    2. Stock verification before request creation
    3. Mandatory SuperAdmin / Accountant approval before any stock movement
    4. Atomic transfer execution with concurrency locks and linked InventoryMemos
    5. Anti-tampering, duplicate execution prevention, and audit history
    """

    @classmethod
    @transaction.atomic
    def create_request(cls, requesting_user, destination_warehouse, source_warehouse, items_data, notes=''):
        if not requesting_user or not requesting_user.is_authenticated:
            raise ValidationError("يجب تسجيل الدخول لإنشاء طلب تحويل مخزني.")

        if not destination_warehouse or not source_warehouse:
            raise ValidationError("يرجى تحديد مخزن الاستلام والمخزن المحول منه.")

        if destination_warehouse.pk == source_warehouse.pk:
            raise ValidationError("لا يمكن إنشاء طلب تحويل بين نفس المخزن.")

        if not destination_warehouse.is_active or not source_warehouse.is_active:
            raise ValidationError("أحد المخازن المحددة معطل حالياً في النظام.")

        dest_main = destination_warehouse.main_area
        src_main = source_warehouse.main_area

        is_super = requesting_user.is_superuser or getattr(requesting_user, 'is_super_admin', False)

        if not (dest_main and src_main and dest_main.id == src_main.id):
            if not is_super:
                dest_name = dest_main.name if dest_main else 'غير محدد'
                src_name = src_main.name if src_main else 'غير محدد'
                raise ValidationError(
                    f"غير مصرح بالتحويل المخزني عبر مناطق رئيسية مختلفة ({src_name} -> {dest_name}). "
                    f"التحويل متاح حصرياً بين المخازن التابعة لنفس المنطقة الرئيسية."
                )

        if not is_super:
            rep = destination_warehouse.assigned_user
            if rep and rep.id != requesting_user.id:
                if not is_manager_eligible_for_user(requesting_user, rep):
                    raise ValidationError("غير مصرح لك بطلب تحويل لمخزن يتبع مندوباً آخر خارج نطاق إشرافك.")

        # Check configurable transfer permissions
        if not can_user_perform_transfer(requesting_user, source_warehouse, destination_warehouse):
            raise ValidationError("غير مصرح لك بإجراء تحويل بين هذه المخازن.")

        if not items_data:
            raise ValidationError("يجب إضافة صنف واحد على الأقل في طلب التحويل.")

        transfer_request = ProductTransferRequest.objects.create(
            requesting_user=requesting_user,
            destination_warehouse=destination_warehouse,
            source_warehouse=source_warehouse,
            status='pending',
            notes=notes
        )

        for item_entry in items_data:
            product = item_entry['product']
            if isinstance(product, (int, str)):
                product = Product.objects.get(id=int(product))

            qty = Decimal(str(item_entry.get('quantity', 0)))
            if qty <= 0:
                raise ValidationError(f"الكمية المطلوبة للصنف '{product.name}' يجب أن تكون أكبر من الصفر.")

            stock = InventoryStock.objects.filter(
                warehouse=source_warehouse,
                product=product
            ).first()
            qty_avail = stock.qty_available if stock else Decimal('0.00')

            if qty_avail < qty:
                raise ValidationError(
                    f"الرصيد المتاح من الصنف '{product.name}' في المخزن المحول منه ({qty_avail}) "
                    f"غير كافٍ للكمية المطلوبة ({qty}). (الكميات المحجوزة مستثناة من الرصيد المتاح)"
                )

            ProductTransferRequestItem.objects.create(
                request=transfer_request,
                product=product,
                requested_quantity=qty,
                batch_number=item_entry.get('batch_number', ''),
                expiry_date=item_entry.get('expiry_date')
            )

        AuditLogService.log(
            user=requesting_user,
            action='TRANSFER_REQUEST_CREATED',
            resource_type='ProductTransferRequest',
            resource_id=str(transfer_request.id),
            resource_name=transfer_request.reference_number,
            details={
                'source_warehouse': source_warehouse.name,
                'destination_warehouse': destination_warehouse.name,
                'items_count': len(items_data)
            }
        )

        return transfer_request

    @classmethod
    @transaction.atomic
    def approve_request(cls, transfer_request, user, approved_quantities=None, notes=''):
        is_super = user.is_superuser or getattr(user, 'is_super_admin', False)
        can_approve = is_super or is_accountant(user) or has_perm_or_admin(user, 'inventory:transfers/approve')

        if not can_approve:
            raise ValidationError("صلاحية اعتماد طلبات التحويل المخزني مقصورة حصرياً على مدراء النظام الأعلى (SuperAdmin) والمحاسبين المعتمدين.")

        if transfer_request.requesting_user_id == user.id and not is_super:
            raise ValidationError("لا يمكن لمقدم الطلب اعتماد طلبه الخاص.")

        if transfer_request.status != 'pending':
            raise ValidationError(f"لا يمكن اعتماد الطلب في حالته الحالية: {transfer_request.get_status_display()}.")

        for item in transfer_request.items.select_related('product'):
            if approved_quantities and item.id in approved_quantities:
                qty_appr = Decimal(str(approved_quantities[item.id]))
            else:
                qty_appr = item.requested_quantity

            if qty_appr <= 0:
                raise ValidationError(f"الكمية المعتمدة للصنف '{item.product.name}' يجب أن تكون أكبر من الصفر.")

            if qty_appr > item.requested_quantity:
                raise ValidationError(f"الكمية المعتمدة للصنف '{item.product.name}' ({qty_appr}) لا يمكن أن تتجاوز الكمية المطلوبة ({item.requested_quantity}).")

            stock = InventoryStock.objects.filter(
                warehouse=transfer_request.source_warehouse,
                product=item.product
            ).first()
            qty_avail = stock.qty_available if stock else Decimal('0.00')

            if qty_avail < qty_appr:
                raise ValidationError(
                    f"الرصيد المتاح حالياً من الصنف '{item.product.name}' في المخزن المحول منه ({qty_avail}) "
                    f"غير كافٍ لاعتماد كمية {qty_appr}."
                )

            item.approved_quantity = qty_appr
            item.save(update_fields=['approved_quantity'])

        transfer_request.status = 'approved'
        transfer_request.approved_by = user
        transfer_request.approved_at = timezone.now()
        transfer_request.approval_notes = notes
        transfer_request.save(update_fields=['status', 'approved_by', 'approved_at', 'approval_notes', 'updated_at'])

        AuditLogService.log(
            user=user,
            action='TRANSFER_REQUEST_APPROVED',
            resource_type='ProductTransferRequest',
            resource_id=str(transfer_request.id),
            resource_name=transfer_request.reference_number,
            details={'notes': notes}
        )

        return transfer_request

    @classmethod
    @transaction.atomic
    def reject_request(cls, transfer_request, user, reason=''):
        is_super = user.is_superuser or getattr(user, 'is_super_admin', False)
        can_reject = is_super or is_accountant(user) or has_perm_or_admin(user, 'inventory:transfers/approve')

        if not can_reject:
            raise ValidationError("صلاحية رفض طلبات التحويل المخزني مقصورة على مدراء النظام الأعلى (SuperAdmin) والمحاسبين المعتمدين.")

        if transfer_request.status not in ['pending', 'approved']:
            raise ValidationError(f"لا يمكن رفض الطلب في حالته الحالية: {transfer_request.get_status_display()}.")

        clean_reason = (reason or '').strip()
        if not clean_reason:
            raise ValidationError("يرجى توضيح سبب رفض طلب التحويل المخزني.")

        transfer_request.status = 'rejected'
        transfer_request.approved_by = user
        transfer_request.approved_at = timezone.now()
        transfer_request.approval_notes = clean_reason
        transfer_request.save(update_fields=['status', 'approved_by', 'approved_at', 'approval_notes', 'updated_at'])

        AuditLogService.log(
            user=user,
            action='TRANSFER_REQUEST_REJECTED',
            resource_type='ProductTransferRequest',
            resource_id=str(transfer_request.id),
            resource_name=transfer_request.reference_number,
            details={'reason': clean_reason}
        )

        return transfer_request

    @classmethod
    @transaction.atomic
    def cancel_request(cls, transfer_request, user, reason=''):
        is_super = user.is_superuser or getattr(user, 'is_super_admin', False)
        is_requester = (transfer_request.requesting_user_id == user.id)

        if not (is_super or is_requester):
            raise ValidationError("يمكن لمقدم الطلب أو مدير النظام فقط إلغاء هذا الطلب.")

        if transfer_request.status not in ['pending', 'approved']:
            raise ValidationError(f"لا يمكن إلغاء الطلب في حالته الحالية: {transfer_request.get_status_display()}.")

        transfer_request.status = 'cancelled'
        if reason:
            transfer_request.notes = f"{transfer_request.notes}\n[سبب الإلغاء: {reason}]".strip()
        transfer_request.save(update_fields=['status', 'notes', 'updated_at'])

        AuditLogService.log(
            user=user,
            action='TRANSFER_REQUEST_CANCELLED',
            resource_type='ProductTransferRequest',
            resource_id=str(transfer_request.id),
            resource_name=transfer_request.reference_number,
            details={'reason': reason}
        )

        return transfer_request

    @classmethod
    @transaction.atomic
    def execute_transfer(cls, transfer_request, user):
        is_super = user.is_superuser or getattr(user, 'is_super_admin', False)
        can_execute = is_super or is_accountant(user) or has_perm_or_admin(user, 'inventory:transfers/approve')

        if not can_execute:
            raise ValidationError("صلاحية تنفيذ التحويل المخزني مقصورة على مدراء النظام الأعلى (SuperAdmin) والمحاسبين المعتمدين.")

        if transfer_request.status == 'transferred':
            raise ValidationError("تم تنفيذ هذا التحويل مسبقاً بالفعل. لا يمكن تكرار تنفيذ التحويل.")

        if transfer_request.status != 'approved':
            raise ValidationError(f"يجب اعتماد طلب التحويل أولاً قبل التنفيذ. الحالة الحالية: {transfer_request.get_status_display()}.")

        items = list(transfer_request.items.select_related('product'))
        if not items:
            raise ValidationError("طلب التحويل لا يحتوي على أي بنود.")

        now = timezone.now()

        memo_out = InventoryMemo.objects.create(
            memo_number=f"MEMO-OUT-{transfer_request.reference_number}",
            memo_type='outward',
            warehouse=transfer_request.source_warehouse,
            statement=f"تحويل مخزني صادر إلى {transfer_request.destination_warehouse.name} بموجب الطلب {transfer_request.reference_number}",
            status='applied',
            applied_at=now,
            notes=f"Inter-warehouse transfer {transfer_request.reference_number}",
            created_by=user
        )

        memo_in = InventoryMemo.objects.create(
            memo_number=f"MEMO-IN-{transfer_request.reference_number}",
            memo_type='inward',
            warehouse=transfer_request.destination_warehouse,
            statement=f"تحويل مخزني وارد من {transfer_request.source_warehouse.name} بموجب الطلب {transfer_request.reference_number}",
            status='applied',
            applied_at=now,
            notes=f"Inter-warehouse transfer {transfer_request.reference_number}",
            created_by=user
        )

        for item in items:
            qty_to_move = item.approved_quantity or item.requested_quantity
            if qty_to_move <= 0:
                continue

            # Lock source stock record
            source_stock = InventoryStock.objects.select_for_update().filter(
                warehouse=transfer_request.source_warehouse,
                product=item.product
            ).first()

            # Strictly validate qty_available (excludes reserved stock)
            if not source_stock or source_stock.qty_available < qty_to_move:
                avail = source_stock.qty_available if source_stock else 0
                raise ValidationError(
                    f"الرصيد المتاح الحالي من الصنف '{item.product.name}' في المخزن المحول منه ({avail}) "
                    f"غير كافٍ لإتمام التحويل للكمية ({qty_to_move}). (الرصيد المحجوز مستثنى من المتاح)"
                )

            # Deduct from source warehouse
            source_stock.qty_on_hand = max(Decimal('0.00'), source_stock.qty_on_hand - qty_to_move)
            source_stock.save(update_fields=['qty_on_hand', 'updated_at'])

            # Add to destination warehouse
            dest_stock, _ = InventoryStock.objects.select_for_update().get_or_create(
                warehouse=transfer_request.destination_warehouse,
                product=item.product,
                defaults={
                    'qty_on_hand': Decimal('0.00'),
                    'qty_reserved': Decimal('0.00'),
                    'product_cost': source_stock.product_cost
                }
            )
            dest_stock.qty_on_hand += qty_to_move
            dest_stock.save(update_fields=['qty_on_hand', 'updated_at'])

            InventoryMemoItem.objects.create(
                memo=memo_out,
                product=item.product,
                quantity=qty_to_move,
                unit_cost=source_stock.product_cost,
                batch_number=item.batch_number or '',
                expiry_date=item.expiry_date
            )

            InventoryMemoItem.objects.create(
                memo=memo_in,
                product=item.product,
                quantity=qty_to_move,
                unit_cost=dest_stock.product_cost,
                batch_number=item.batch_number or '',
                expiry_date=item.expiry_date
            )

            item.transferred_quantity = qty_to_move
            item.save(update_fields=['transferred_quantity'])

        transfer_request.outward_memo = memo_out
        transfer_request.inward_memo = memo_in
        transfer_request.executed_by = user
        transfer_request.executed_at = now
        transfer_request.status = 'transferred'
        transfer_request.save(update_fields=[
            'outward_memo', 'inward_memo', 'executed_by', 'executed_at', 'status', 'updated_at'
        ])

        AuditLogService.log(
            user=user,
            action='TRANSFER_EXECUTED',
            resource_type='ProductTransferRequest',
            resource_id=str(transfer_request.id),
            resource_name=transfer_request.reference_number,
            details={
                'source_warehouse': transfer_request.source_warehouse.name,
                'destination_warehouse': transfer_request.destination_warehouse.name,
                'items_count': len(items)
            }
        )

        return transfer_request