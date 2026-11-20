from decimal import Decimal
from django.db import transaction, models
from django.db.models import Q


def is_representative(user) -> bool:
    """
    Returns True if user is any kind of representative recognized by the system.
    Evaluates:
    - role.is_rep
    - role.is_sales_team
    - role names containing rep, representative, sales_rep, medical_rep
    - role display names containing مندوب or دعاية
    """
    if not user or not user.is_authenticated:
        return False
    role = getattr(user, 'role', None)
    if not role or not role.is_active:
        return False
    # Managers and SuperAdmins are not representatives
    if (
        user.is_superuser or
        getattr(user, 'is_super_admin', False) or
        getattr(role, 'is_manager_role', False) or
        getattr(role, 'is_area_manager', False) or
        getattr(role, 'is_sub_area_manager', False) or
        getattr(role, 'is_super', False)
    ):
        return False
    name_l = (role.name or '').lower()
    disp_l = (role.display_name or '').lower()
    if any(k in name_l or k in disp_l for k in ['manager', 'director', 'supervisor', 'مدير', 'مشرف', 'رئيس']):
        return False
    if role.is_rep:
        return True
    rep_keywords = ['rep', 'representative', 'sales_rep', 'medical_rep', 'مندوب', 'دعاية']
    return any(k in name_l or k in disp_l for k in rep_keywords)


def get_representative_warehouse(user):
    """Returns the designated default warehouse for this representative."""
    if not user or not user.is_authenticated:
        return None
    return user.get_default_warehouse()


def get_representative_treasury(user):
    """Returns the designated default treasury (cash vault) for this representative."""
    if not user or not user.is_authenticated:
        return None
    return user.get_default_treasury()


@transaction.atomic
def ensure_representative_resources(user, create_warehouse=None, create_treasury=None):
    """
    Idempotent service ensuring that a representative user has their designated
    default Warehouse and Treasury (Vault) created and assigned.
    
    Reads policy from UserSettings:
    - auto_create_rep_warehouse
    - auto_create_rep_treasury
    
    Returns tuple: (warehouse, vault, created_wh, created_vault)
    """
    from master_data.services import SettingsService
    from inventory.models import Warehouse
    from treasury.models import Vault

    if not is_representative(user):
        return None, None, False, False

    settings = SettingsService.get_user_settings()
    if create_warehouse is None:
        create_warehouse = settings.auto_create_rep_warehouse
    if create_treasury is None:
        create_treasury = settings.auto_create_rep_treasury

    wh = None
    created_wh = False
    vault = None
    created_vault = False

    # 1. Ensure Warehouse
    if create_warehouse:
        wh = user.get_default_warehouse()
        if not wh:
            # Generate unique code
            base_code = f"WH-REP-{user.id:04d}" if user.id else f"WH-REP-{user.username[:10]}"
            code = base_code
            counter = 1
            while Warehouse.objects.filter(code=code).exists():
                code = f"{base_code}-{counter}"
                counter += 1

            # Generate unique name
            user_title = user.name.strip() if user.name else user.username
            base_name = f"مخزن عهدة - {user_title}"
            name = base_name
            counter = 1
            while Warehouse.objects.filter(name=name).exists():
                name = f"{base_name} ({counter})"
                counter += 1

            # Assign primary area if user is assigned to one
            primary_area = user.assigned_areas.first()

            wh = Warehouse.objects.create(
                name=name,
                code=code,
                assigned_user=user,
                manager=user,
                is_rep_warehouse=True,
                is_main=False,
                is_active=True,
                area=primary_area
            )
            created_wh = True

            AuditLogService.log(
                action_type='WAREHOUSE_CREATED',
                module='inventory',
                actor=None,
                target_user=user,
                record_id=wh.id,
                record_name=wh.name,
                description=f"إنشاء مخزن عهدة تلقائي للمندوب {user.name or user.username}: {wh.name} ({wh.code})",
                new_values={'name': wh.name, 'code': wh.code, 'assigned_user': user.username, 'is_rep_warehouse': True}
            )

    # 2. Ensure Treasury (Vault)
    if create_treasury:
        vault = user.get_default_treasury()
        if not vault:
            user_title = user.name.strip() if user.name else user.username
            base_name = f"خزنة عهدة - {user_title}"
            name = base_name
            counter = 1
            while Vault.objects.filter(name=name).exists():
                name = f"{base_name} ({counter})"
                counter += 1

            vault = Vault.objects.create(
                name=name,
                vault_type='cash',
                assigned_user=user,
                is_rep_vault=True,
                is_active=True,
                current_balance=Decimal('0.00')
            )
            created_vault = True

            AuditLogService.log(
                action_type='VAULT_CREATED',
                module='treasury',
                actor=None,
                target_user=user,
                record_id=vault.id,
                record_name=vault.name,
                description=f"إنشاء خزنة عهدة نقدية تلقائية للمندوب {user.name or user.username}: {vault.name}",
                new_values={'name': vault.name, 'vault_type': vault.vault_type, 'assigned_user': user.username, 'is_rep_vault': True}
            )

    return wh, vault, created_wh, created_vault


import logging
from accounts.models import SecurityAuditLog

logger = logging.getLogger(__name__)

REDACTED_KEYS = {
    'password', 'new_password', 'confirm_password', 'confirm_new_password',
    'password1', 'password2', 'secret', 'token', 'auth_token', 'api_key',
    'access_token', 'refresh_token', 'credit_card', 'cvv'
}


def redact_sensitive_data(data):
    """Recursively redacts passwords, tokens, and secrets from JSON/dicts and normalizes Decimals/dates."""
    from decimal import Decimal
    import datetime
    if isinstance(data, Decimal):
        return float(data)
    if isinstance(data, (datetime.date, datetime.datetime)):
        return data.isoformat()
    if not isinstance(data, dict):
        return data
    cleaned = {}
    for k, v in data.items():
        if any(rk in str(k).lower() for rk in REDACTED_KEYS):
            cleaned[k] = '[REDACTED]'
        elif isinstance(v, dict):
            cleaned[k] = redact_sensitive_data(v)
        elif isinstance(v, list):
            cleaned[k] = [redact_sensitive_data(item) for item in v]
        elif isinstance(v, Decimal):
            cleaned[k] = float(v)
        elif isinstance(v, (datetime.date, datetime.datetime)):
            cleaned[k] = v.isoformat()
        else:
            cleaned[k] = v
    return cleaned


class AuditLogService:
    @staticmethod
    def get_client_ip(request):
        """Extract remote client IP address from request, prioritizing X-Forwarded-For."""
        if not request:
            return None
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            return x_forwarded_for.split(',')[0].strip()
        return request.META.get('REMOTE_ADDR')

    @classmethod
    def log(cls, action_type: str = '', module: str = 'accounts', actor=None, description: str = '',
            record_id=None, record_name: str = '', previous_values=None, new_values=None,
            status: str = 'SUCCESS', reason: str = '', target_user=None, target_role=None,
            request=None, action=None, user=None, ip_address=None, user_agent=None, **kwargs):
        """
        Centralized, atomic, and reusable audit logging across all ERP modules.
        Automatically captures IP and User Agent from request, and redacts sensitive data.
        Supports both action/action_type and user/actor aliases.
        """
        try:
            from accounts.models import SecurityAuditLog

            action_val = action_type or action or 'action'
            actor_val = user or actor
            record_id_val = record_id if record_id is not None else kwargs.get('resource_id')
            record_name_val = record_name or kwargs.get('resource_name', '')
            description_val = description or kwargs.get('details', '')

            ip_val = ip_address
            ua_val = user_agent or ''
            if request:
                if not actor_val and hasattr(request, 'user') and request.user.is_authenticated:
                    actor_val = request.user
                if not ip_val:
                    ip_val = cls.get_client_ip(request)
                if not ua_val:
                    ua_val = request.META.get('HTTP_USER_AGENT', '')

            cleaned_prev = redact_sensitive_data(previous_values) if previous_values else None
            cleaned_new = redact_sensitive_data(new_values) if new_values else None

            from django.db import transaction
            with transaction.atomic():
                log_entry = SecurityAuditLog.objects.create(
                    actor=actor_val,
                    module=module,
                    action_type=action_val,
                    record_id=str(record_id_val) if record_id_val is not None else '',
                    record_name=str(record_name_val) if record_name_val else '',
                    target_user=target_user,
                    target_role=target_role,
                    description=description_val or f"[{module}] {action_val} {record_name_val or record_id_val or ''}".strip(),
                    previous_values=cleaned_prev,
                    new_values=cleaned_new,
                    status=status,
                    reason=reason or '',
                    ip_address=ip_val,
                    user_agent=ua_val or '',
                )
            return log_entry
        except Exception as e:
            logger.error(f"Failed to record audit log: {e}", exc_info=True)
            return None


def _get_or_create_archive_user():
    """Returns the inactive system archive account used to preserve historical attribution."""
    from django.contrib.auth import get_user_model
    UserModel = get_user_model()
    archive = UserModel.objects.filter(username='historical_archive@wea.com').first()
    if not archive:
        archive = UserModel.objects.filter(email='historical_archive@wea.com').first()
    if not archive:
        archive = UserModel.objects.create(
            username='historical_archive@wea.com',
            email='historical_archive@wea.com',
            name='أرشيف المستخدمين المحذوفين',
            is_active=False,
        )
        archive.set_unusable_password()
        archive.save(update_fields=['password'])
    elif archive.is_active:
        archive.is_active = False
        archive.save(update_fields=['is_active'])
    return archive


def revoke_user_sessions(user_id):
    """Deletes all active Django sessions belonging to the given user_id."""
    from django.contrib.sessions.models import Session
    from django.utils import timezone
    for session in Session.objects.filter(expire_date__gte=timezone.now()):
        try:
            data = session.get_decoded()
            if str(data.get('_auth_user_id')) == str(user_id):
                session.delete()
        except Exception:
            continue


@transaction.atomic
def delete_user_safely(target_user, actor, request=None):
    """
    Safely deletes a user account while strictly protecting financial, inventory,
    and field-activity history:
    1. Prevents self-deletion and unauthorized SuperAdmin/superuser deletion.
    2. Blocks deletion if custody warehouse has stock/reserved qty or custody vault has non-zero balance.
    3. Revokes all active sessions for the target user.
    4. If the user has zero historical records, hard-deletes the user and empty auto-provisioned resources.
    5. If the user has historical records (Visits, Orders, Collections, Transfers, Targets, Calls, Coaching),
       transfers ownership to the inactive archive account (`historical_archive@wea.com`) before deleting
       the user account, preserving complete financial/audit integrity and recording original identity in SecurityAuditLog.
    """
    from django.core.exceptions import ValidationError
    from django.contrib.auth import get_user_model
    from inventory.models import Warehouse, InventoryStock, InventoryMemo, ProductTransferRequest
    from treasury.models import Vault, VaultTransaction, VendorPayment, VendorPaymentRequest
    from sales.models import SalesOrder, SalesReturnOrder, Collection
    from purchases.models import PurchaseOrder, PurchaseReturnOrder
    from activities.models import Visit, VisitPlan, PlannedVisitDay, Agreement
    from reports.models import SalesTarget, CustomerCall, CoachingEvaluation

    UserModel = get_user_model()
    target_user = UserModel.objects.select_for_update().get(pk=target_user.pk)

    if target_user.pk == actor.pk:
        raise ValidationError("لا يمكنك حذف حسابك الشخصي.")

    if target_user.username == 'historical_archive@wea.com':
        raise ValidationError("لا يمكن حذف حساب الأرشيف النظامي.")

    actor_is_super = bool(actor.is_superuser or getattr(actor, 'is_super_admin', False))
    target_is_super = bool(target_user.is_superuser or getattr(target_user, 'is_super_admin', False))
    if target_is_super and not actor_is_super:
        raise ValidationError("لا تملك صلاحية حذف حساب مدير نظام أعلى (SuperAdmin).")

    if target_is_super:
        other_active_supers = UserModel.objects.filter(
            is_active=True
        ).filter(
            Q(is_superuser=True) | Q(role__is_super=True) | Q(role__name__iexact='superadmin')
        ).exclude(pk=target_user.pk).count()
        if other_active_supers == 0:
            raise ValidationError("لا يمكن حذف آخر مدير نظام أعلى نشط في النظام.")

    # Check custody warehouses & vaults
    custody_whs = Warehouse.objects.filter(assigned_user=target_user)
    if InventoryStock.objects.filter(warehouse__in=custody_whs).filter(Q(qty_on_hand__gt=0) | Q(qty_reserved__gt=0)).exists():
        raise ValidationError("لا يمكن حذف المستخدم لوجود أرصدة مخزنية أو كميات محجوزة في مخزن عهدته. يرجى تصفية أو تحويل المخزون أولاً.")

    if ProductTransferRequest.objects.filter(
        Q(source_warehouse__in=custody_whs) | Q(destination_warehouse__in=custody_whs),
        status__in=['pending', 'approved']
    ).exists():
        raise ValidationError("لا يمكن حذف المستخدم لوجود طلبات تحويل مخزني معلقة مرتبطة بمخزن عهدته.")

    custody_vaults = Vault.objects.filter(assigned_user=target_user)
    if custody_vaults.exclude(current_balance=Decimal('0.00')).exists():
        raise ValidationError("لا يمكن حذف المستخدم لوجود رصيد مالي غير صفري في خزنة عهدته. يرجى تصفية الرصيد أولاً.")

    # Revoke active sessions
    revoke_user_sessions(target_user.pk)

    # Count historical records
    visits_cnt = Visit.objects.filter(owner=target_user).count()
    plans_cnt = VisitPlan.objects.filter(assignee=target_user).count()
    days_cnt = PlannedVisitDay.objects.filter(assignee=target_user).count()
    transfers_cnt = ProductTransferRequest.objects.filter(requesting_user=target_user).count()
    sales_cnt = SalesOrder.objects.filter(created_by=target_user).count()
    purchases_cnt = PurchaseOrder.objects.filter(created_by=target_user).count()
    cols_cnt = Collection.objects.filter(created_by=target_user).count()
    calls_cnt = CustomerCall.objects.filter(performed_by=target_user).count()
    coaching_cnt = CoachingEvaluation.objects.filter(Q(rep=target_user) | Q(manager=target_user)).count()
    targets_cnt = SalesTarget.objects.filter(user=target_user).count()

    has_history = any([
        visits_cnt, plans_cnt, days_cnt, transfers_cnt, sales_cnt,
        purchases_cnt, cols_cnt, calls_cnt, coaching_cnt, targets_cnt,
        SalesReturnOrder.objects.filter(created_by=target_user).exists(),
        PurchaseReturnOrder.objects.filter(created_by=target_user).exists(),
        InventoryMemo.objects.filter(created_by=target_user).exists(),
        VaultTransaction.objects.filter(created_by=target_user).exists(),
        VendorPayment.objects.filter(created_by=target_user).exists(),
        VendorPaymentRequest.objects.filter(created_by=target_user).exists(),
        Agreement.objects.filter(created_by=target_user).exists(),
    ])

    orig_info = {
        'id': target_user.pk,
        'username': target_user.username,
        'name': target_user.name,
        'email': target_user.email,
        'role': target_user.role.name if target_user.role else None,
        'has_history': has_history,
        'reassigned_counts': {
            'visits': visits_cnt,
            'plans': plans_cnt,
            'transfers': transfers_cnt,
            'sales_orders': sales_cnt,
            'purchase_orders': purchases_cnt,
            'collections': cols_cnt,
        }
    }

    if has_history:
        archive_user = _get_or_create_archive_user()
        Visit.objects.filter(owner=target_user).update(owner=archive_user)
        VisitPlan.objects.filter(assignee=target_user).update(assignee=archive_user)
        for day in PlannedVisitDay.objects.filter(assignee=target_user):
            existing_day = PlannedVisitDay.objects.filter(assignee=archive_user, date=day.date).first()
            if existing_day:
                day.items.update(plan_day=existing_day)
                day.delete()
            else:
                day.assignee = archive_user
                day.save(update_fields=['assignee'])
        ProductTransferRequest.objects.filter(requesting_user=target_user).update(requesting_user=archive_user)
        CustomerCall.objects.filter(performed_by=target_user).update(performed_by=archive_user)
        CoachingEvaluation.objects.filter(manager=target_user).update(manager=archive_user)
        CoachingEvaluation.objects.filter(rep=target_user).update(rep=archive_user)
        for tgt in SalesTarget.objects.filter(user=target_user):
            if SalesTarget.objects.filter(user=archive_user, year=tgt.year, month=tgt.month).exists():
                tgt.delete()
            else:
                tgt.user = archive_user
                tgt.save(update_fields=['user'])
        # Unassign custody warehouses/vaults cleanly
        custody_whs.update(assigned_user=None, is_active=False)
        custody_vaults.update(assigned_user=None, is_active=False)
    else:
        # Cleanly remove empty auto-provisioned rep warehouses/vaults
        for wh in custody_whs:
            has_wh_links = (
                InventoryMemo.objects.filter(warehouse=wh).exists() or
                ProductTransferRequest.objects.filter(Q(source_warehouse=wh) | Q(destination_warehouse=wh)).exists() or
                SalesOrder.objects.filter(source_warehouse=wh).exists() or
                PurchaseOrder.objects.filter(target_warehouse=wh).exists()
            )
            if has_wh_links:
                wh.assigned_user = None
                wh.is_active = False
                wh.save(update_fields=['assigned_user', 'is_active'])
            else:
                wh.delete()
        for v in custody_vaults:
            has_v_links = (
                VaultTransaction.objects.filter(vault=v).exists() or
                Collection.objects.filter(vault=v).exists() or
                VendorPayment.objects.filter(vault=v).exists()
            )
            if has_v_links:
                v.assigned_user = None
                v.is_active = False
                v.save(update_fields=['assigned_user', 'is_active'])
            else:
                v.delete()

    target_label = f"{target_user.name or target_user.username} ({target_user.username})"
    target_id = target_user.pk
    target_user.delete()

    AuditLogService.log(
        action_type='USER_DELETED',
        module='accounts',
        actor=actor,
        record_id=target_id,
        record_name=target_label,
        description=f"حذف حساب المستخدم '{target_label}' مع الحفاظ على سلامة السجلات التاريخية والمالية.",
        previous_values=orig_info,
        request=request,
    )
    return orig_info


