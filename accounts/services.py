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
    from accounts.models import UserSettings
    from inventory.models import Warehouse
    from treasury.models import Vault

    if not is_representative(user):
        return None, None, False, False

    settings = UserSettings.get_settings()
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

    return wh, vault, created_wh, created_vault


import logging
from accounts.models import SecurityAuditLog

logger = logging.getLogger(__name__)

import logging
logger = logging.getLogger(__name__)

REDACTED_KEYS = {
    'password', 'new_password', 'confirm_password', 'confirm_new_password',
    'password1', 'password2', 'secret', 'token', 'auth_token', 'api_key',
    'access_token', 'refresh_token', 'credit_card', 'cvv'
}


def redact_sensitive_data(data):
    """Recursively redacts passwords, tokens, and secrets from JSON/dicts."""
    if not isinstance(data, dict):
        return data
    cleaned = {}
    for k, v in data.items():
        if any(rk in str(k).lower() for rk in REDACTED_KEYS):
            cleaned[k] = '[REDACTED]'
        elif isinstance(v, dict):
            cleaned[k] = redact_sensitive_data(v)
        elif isinstance(v, list):
            cleaned[k] = [redact_sensitive_data(item) if isinstance(item, dict) else item for item in v]
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

            action_val = action or action_type or 'action'
            actor_val = user or actor

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

            log_entry = SecurityAuditLog.objects.create(
                actor=actor_val,
                module=module,
                action_type=action_val,
                record_id=str(record_id) if record_id is not None else '',
                record_name=str(record_name) if record_name else '',
                target_user=target_user,
                target_role=target_role,
                description=description or f"[{module}] {action_val} {record_name or record_id or ''}".strip(),
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

