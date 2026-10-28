from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.db.models import Max

from .models import (
    Warehouse, InventoryStock, InventoryMemo, InventoryMemoItem,
    ProductTransferRequest, ProductTransferRequestItem
)
from catalog.models import Product
from accounts.permissions import (
    is_accountant, is_manager_eligible_for_user, has_perm_or_admin
)


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
        """
        Creates a new ProductTransferRequest between two warehouses in the SAME MAIN AREA.
        
        items_data format:
        [
            {'product': product_obj_or_id, 'quantity': Decimal('10.00'), 'batch_number': '', 'expiry_date': None},
            ...
        ]
        """
        if not requesting_user or not requesting_user.is_authenticated:
            raise ValidationError("يجب تسجيل الدخول لإنشاء طلب تحويل مخزني.")

        if not destination_warehouse or not source_warehouse:
            raise ValidationError("يرجى تحديد مخزن الاستلام والمخزن المحول منه.")

        if destination_warehouse.pk == source_warehouse.pk:
            raise ValidationError("لا يمكن إنشاء طلب تحويل بين نفس المخزن.")

        if not destination_warehouse.is_active or not source_warehouse.is_active:
            raise ValidationError("أحد المخازن المحددة معطل حالياً في النظام.")

        # Canonical Main Area Validation:
        # Transfer is allowed if source and destination belong to the same root main area
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

        # Authorization check: user must be the representative assigned to destination warehouse,
        # an eligible manager for that representative, or superadmin
        if not is_super:
            rep = destination_warehouse.assigned_user
            if rep and rep.id != requesting_user.id:
                if not is_manager_eligible_for_user(requesting_user, rep):
                    raise ValidationError("غير مصرح لك بطلب تحويل لمخزن يتبع مندوباً آخر خارج نطاق إشرافك.")

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

            # Verify available stock in source warehouse
            stock = InventoryStock.objects.filter(
                warehouse=source_warehouse,
                product=product
            ).first()
            qty_avail = stock.qty_available if stock else Decimal('0.00')

            if qty_avail < qty:
                raise ValidationError(
                    f"الرصيد المتاح من الصنف '{product.name}' في المخزن المحول منه ({qty_avail}) "
                    f"غير كافٍ للكمية المطلوبة ({qty})."
                )

            ProductTransferRequestItem.objects.create(
                request=transfer_request,
                product=product,
                requested_quantity=qty,
                batch_number=item_entry.get('batch_number', ''),
                expiry_date=item_entry.get('expiry_date')
            )

        return transfer_request

    @classmethod
    @transaction.atomic
    def approve_request(cls, transfer_request, user, approved_quantities=None, notes=''):
        """
        Approves an inter-warehouse product request.
        Must be performed by an authorized SuperAdmin or Accountant before any transfer.
        """
        is_super = user.is_superuser or getattr(user, 'is_super_admin', False)
        can_approve = is_super or is_accountant(user) or has_perm_or_admin(user, 'inventory:transfers/approve')

        if not can_approve:
            raise ValidationError("صلاحية اعتماد طلبات التحويل المخزني مقصورة حصرياً على مدراء النظام الأعلى (SuperAdmin) والمحاسبين المعتمدين.")

        # Anti-self-approval
        if transfer_request.requesting_user_id == user.id and not is_super:
            raise ValidationError("لا يمكن لمقدم الطلب اعتماد طلبه الخاص.")

        if transfer_request.status != 'pending':
            raise ValidationError(f"لا يمكن اعتماد الطلب في حالته الحالية: {transfer_request.get_status_display()}.")

        # Revalidate stock and set approved quantities
        for item in transfer_request.items.select_related('product'):
            if approved_quantities and item.id in approved_quantities:
                qty_appr = Decimal(str(approved_quantities[item.id]))
            else:
                qty_appr = item.requested_quantity

            if qty_appr <= 0:
                raise ValidationError(f"الكمية المعتمدة للصنف '{item.product.name}' يجب أن تكون أكبر من الصفر.")

            if qty_appr > item.requested_quantity:
                raise ValidationError(f"الكمية المعتمدة للصنف '{item.product.name}' ({qty_appr}) لا يمكن أن تتجاوز الكمية المطلوبة ({item.requested_quantity}).")

            # Check stock in source warehouse
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

        return transfer_request

    @classmethod
    @transaction.atomic
    def reject_request(cls, transfer_request, user, reason=''):
        """
        Rejects an inter-warehouse product request with a mandatory reason.
        """
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

        return transfer_request

    @classmethod
    @transaction.atomic
    def cancel_request(cls, transfer_request, user, reason=''):
        """
        Cancels a pending or approved transfer request by the requester or SuperAdmin.
        """
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
        return transfer_request

    @classmethod
    @transaction.atomic
    def execute_transfer(cls, transfer_request, user):
        """
        Executes an approved transfer atomically:
        1. Verifies request status is 'approved' (prevents duplicate execution).
        2. Acquires row-level locks on source warehouse inventory stock.
        3. Deducts transferred quantity from source warehouse.
        4. Adds transferred quantity to destination warehouse.
        5. Creates linked outward InventoryMemo and inward InventoryMemo.
        6. Updates transferred quantities and marks request as 'transferred'.
        """
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

        # Create Outward Inventory Memo for source warehouse
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

        # Create Inward Inventory Memo for destination warehouse
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

            if not source_stock or source_stock.qty_on_hand < qty_to_move:
                avail = source_stock.qty_on_hand if source_stock else 0
                raise ValidationError(
                    f"الرصيد الفعلي الحالي من الصنف '{item.product.name}' في المخزن المحول منه ({avail}) "
                    f"غير كافٍ لإتمام التحويل للكمية ({qty_to_move})."
                )

            # Deduct from source warehouse
            source_stock.qty_on_hand = max(Decimal('0.00'), source_stock.qty_on_hand - qty_to_move)
            source_stock.save(update_fields=['qty_on_hand', 'updated_at'])

            # Add to destination warehouse (lock or get_or_create)
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

            # Create memo items
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

        return transfer_request
