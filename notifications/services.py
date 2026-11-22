"""
Centralized Notification Service with:
- transaction.on_commit() safety (never creates notifications for rolled-back transactions)
- 4-layer ScopeResolutionService enforcement (Role rule + RBAC + DataScope/Area + Actor exclusion)
- Deduplication, bulk persistence, failure isolation, 90-day retention, and Capacitor API helpers.
"""

import logging
from datetime import timedelta
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from accounts.models import Role
from accounts.permissions import has_perm_or_admin
from accounts.scope_service import ScopeResolutionService

from .channels import ACTIVE_CHANNELS
from .models import Notification, NotificationDevice, RoleNotificationRule
from .registry import (
    NOTIFICATION_EVENTS_CATALOG,
    get_event_definition,
)

logger = logging.getLogger(__name__)
User = get_user_model()


def _extract_record_owner_ids(target_obj) -> Set[int]:
    """Extracts canonical creator / owner / assignee user IDs from a target model instance."""
    owner_ids: Set[int] = set()
    if target_obj is None:
        return owner_ids
    for attr in ('owner_id', 'created_by_id', 'assignee_id', 'requesting_user_id', 'assigned_user_id', 'user_id', 'rep_id'):
        val = getattr(target_obj, attr, None)
        if val:
            owner_ids.add(int(val))
    if target_obj.__class__.__name__.lower() == 'user' and getattr(target_obj, 'pk', None):
        owner_ids.add(int(target_obj.pk))
    return owner_ids


def _extract_target_main_area_ids(target_obj) -> Set[int]:
    """Resolves canonical root governorate/main-area IDs associated with target_obj (if any)."""
    if target_obj is None:
        return set()
    areas = []
    # Direct area / brick
    for attr in ('area', 'brick'):
        a = getattr(target_obj, attr, None)
        if a is not None:
            areas.append(a)
    # Related customer / supplier / contact
    for rel_attr in ('customer', 'supplier', 'contact'):
        rel = getattr(target_obj, rel_attr, None)
        if rel is not None:
            if getattr(rel, 'area', None):
                areas.append(rel.area)
            if getattr(rel, 'brick', None):
                areas.append(rel.brick)
    # Related account
    acc = getattr(target_obj, 'account', None)
    if acc is not None:
        for rel_attr in ('customer', 'supplier'):
            rel = getattr(acc, rel_attr, None)
            if rel is not None:
                if getattr(rel, 'area', None):
                    areas.append(rel.area)
                if getattr(rel, 'brick', None):
                    areas.append(rel.brick)
    # Related warehouse / vault
    for rel_attr in ('source_warehouse', 'target_warehouse', 'warehouse', 'vault'):
        rel = getattr(target_obj, rel_attr, None)
        if rel is not None and getattr(rel, 'area', None):
            areas.append(rel.area)

    main_ids: Set[int] = set()
    for a in areas:
        root = ScopeResolutionService.get_main_area(a)
        if root is not None:
            main_ids.add(root.id)
    return main_ids


class NotificationService:

    @classmethod
    def emit(
        cls,
        event_code: str,
        target_obj=None,
        actor=None,
        title: str = '',
        body: str = '',
        action_url: str = '',
        severity: Optional[str] = None,
        dedupe_key: str = '',
        metadata: Optional[Dict[str, Any]] = None,
        exclude_actor: Optional[bool] = None,
        extra_owner_ids: Optional[Iterable[int]] = None,
        sync: bool = False,
    ) -> int:
        """
        Centralized entry point for all ERP notification events.
        Schedules delivery inside transaction.on_commit() so rolled-back transactions
        NEVER persist notifications. Never raises into business transactions.
        """
        ev_def = get_event_definition(event_code)
        if not ev_def:
            logger.warning("NotificationService.emit called with unregistered event_code=%s", event_code)
            return 0

        final_title = (title or ev_def['name_ar'])[:200]
        final_body = (body or '')[:2000]
        final_severity = severity or ev_def.get('default_severity', 'info')
        final_module = ev_def['module']
        final_metadata = dict(metadata or {})
        actor_id = getattr(actor, 'pk', None) if actor else None

        target_model_name = ''
        target_pk = None
        if target_obj is not None:
            target_model_name = target_obj.__class__.__name__.lower()
            target_pk = getattr(target_obj, 'pk', None)

        owner_ids = _extract_record_owner_ids(target_obj)
        if extra_owner_ids:
            owner_ids.update(int(uid) for uid in extra_owner_ids if uid)
        target_main_area_ids = _extract_target_main_area_ids(target_obj)

        def _dispatch():
            try:
                return cls._dispatch_now(
                    ev_def=ev_def,
                    event_code=event_code,
                    target_obj=target_obj,
                    target_model_name=target_model_name,
                    target_pk=target_pk,
                    actor_id=actor_id,
                    owner_ids=owner_ids,
                    target_main_area_ids=target_main_area_ids,
                    title=final_title,
                    body=final_body,
                    action_url=action_url or '',
                    severity=final_severity,
                    module=final_module,
                    dedupe_key=dedupe_key or '',
                    metadata=final_metadata,
                    exclude_actor=exclude_actor,
                )
            except Exception:
                logger.exception("Notification dispatch failed cleanly for event_code=%s", event_code)
                return 0

        if sync:
            return _dispatch()

        transaction.on_commit(_dispatch)
        return 0

    @classmethod
    def resolve_recipients(
        cls,
        ev_def: Dict[str, Any],
        target_obj=None,
        actor_id: Optional[int] = None,
        owner_ids: Optional[Set[int]] = None,
        target_main_area_ids: Optional[Set[int]] = None,
        exclude_actor: Optional[bool] = None,
    ) -> List[User]:
        """
        Four-layer strict DataScope & RBAC recipient resolution:
        Layer 1: Active users with enabled RoleNotificationRule for event_code.
        Layer 2: RBAC permission gate (required_permission & approval_permission).
        Layer 3: ScopeResolutionService object-level validation (view/approve) + same_area_only check.
        Layer 4: Delivery mode (all_in_scope / record_owner_only / approvers_only / specific_users)
                 + actor exclusion (respecting rule.include_actor).
        """
        event_code = ev_def['code']
        owner_ids = owner_ids or set()
        target_main_area_ids = target_main_area_ids if target_main_area_ids is not None else _extract_target_main_area_ids(target_obj)

        rules = list(
            RoleNotificationRule.objects.filter(
                event_code=event_code,
                is_enabled=True,
                role__is_active=True,
            ).select_related('role').prefetch_related('specific_users')
        )
        if not rules:
            return []

        role_ids = [r.role_id for r in rules]
        rule_by_role = {r.role_id: r for r in rules}
        specific_user_ids_by_role = {
            r.role_id: set(r.specific_users.values_list('id', flat=True))
            for r in rules
        }

        candidates = list(
            User.objects.filter(is_active=True)
            .filter(Q(role_id__in=role_ids) | Q(is_superuser=True))
            .select_related('role')
            .prefetch_related('assigned_areas')
            .distinct()
        )

        # Ensure superusers without an explicit role still honor superadmin rule if configured
        super_rule = next((r for r in rules if r.role.is_super or (r.role.name or '').lower() == 'superadmin'), None)

        req_perm = ev_def.get('required_permission')
        approve_perm = ev_def.get('approval_permission')
        actor_user = User.objects.filter(pk=actor_id).select_related('role').first() if actor_id else None
        actor_main_area_ids = (
            set(ScopeResolutionService.get_user_main_areas(actor_user).values_list('id', flat=True))
            if actor_user and not (actor_user.is_superuser or getattr(actor_user, 'is_super_admin', False))
            else set()
        )

        resolved: List[User] = []
        seen_ids: Set[int] = set()

        for recipient in candidates:
            if recipient.id in seen_ids:
                continue

            rule = rule_by_role.get(recipient.role_id)
            if rule is None:
                if recipient.is_superuser and super_rule is not None:
                    rule = super_rule
                else:
                    continue

            # Layer 4a: Actor inclusion/exclusion
            must_exclude_actor = (not rule.include_actor) if exclude_actor is None else exclude_actor
            if actor_id and recipient.id == actor_id and must_exclude_actor:
                continue

            is_super = bool(recipient.is_superuser or getattr(recipient, 'is_super_admin', False))

            # Layer 2: RBAC permission gate
            if not is_super:
                if req_perm and not has_perm_or_admin(recipient, req_perm):
                    continue
                if rule.delivery_mode == 'approvers_only' and approve_perm:
                    if not has_perm_or_admin(recipient, approve_perm):
                        continue

            # Layer 4b: Delivery mode targeting
            is_owner = recipient.id in owner_ids
            if rule.delivery_mode == 'record_owner_only':
                if not is_owner:
                    continue
            elif rule.delivery_mode == 'specific_users':
                allowed_ids = specific_user_ids_by_role.get(rule.role_id, set())
                if recipient.id not in allowed_ids and not (rule.include_record_owner and is_owner):
                    continue
            elif rule.delivery_mode == 'approvers_only':
                # Anti-self-approval: creator/actor cannot be notified as approver
                if is_owner and not is_super and not rule.include_record_owner:
                    continue

            # Layer 3: Strict DataScope validation via ScopeResolutionService
            if not is_super and target_obj is not None:
                # Only run ScopeResolutionService on models handled by it
                m_name = target_obj.__class__.__name__.lower()
                scope_action = 'approve' if rule.delivery_mode == 'approvers_only' else 'view'
                if m_name in ScopeResolutionService.MODEL_MODULE_MAP or m_name in (
                    'contact', 'salesorder', 'salesreturnorder', 'collection', 'customeraccount',
                    'customertransaction', 'purchaseorder', 'purchasereturnorder', 'vendorpayment',
                    'vendorpaymentrequest', 'vendoraccount', 'vendortransaction', 'warehouse',
                    'inventorystock', 'inventorymemo', 'producttransferrequest', 'vault',
                    'vaulttransaction', 'visit', 'visitplan', 'plannedvisitday', 'agreement',
                    'salestarget', 'customercall', 'coachingevaluation', 'user', 'area',
                ):
                    if not (rule.include_record_owner and is_owner):
                        if not ScopeResolutionService.can_user_access_object(recipient, target_obj, scope_action):
                            continue

                # Optional territorial same_area_only check for non-ALL-scoped users
                if rule.same_area_only and not (rule.include_record_owner and is_owner):
                    mod_key = ScopeResolutionService.MODEL_MODULE_MAP.get(m_name, ev_def['module'])
                    rec_scope = ScopeResolutionService.get_user_scope(recipient, mod_key, 'view')
                    if rec_scope != 'all':
                        effective_target_areas = target_main_area_ids or actor_main_area_ids
                        if effective_target_areas:
                            rec_main_areas = set(ScopeResolutionService.get_user_main_areas(recipient).values_list('id', flat=True))
                            if not (rec_main_areas & effective_target_areas):
                                continue

            seen_ids.add(recipient.id)
            resolved.append(recipient)

        return resolved

    @classmethod
    def _dispatch_now(
        cls,
        ev_def: Dict[str, Any],
        event_code: str,
        target_obj,
        target_model_name: str,
        target_pk: Optional[int],
        actor_id: Optional[int],
        owner_ids: Set[int],
        target_main_area_ids: Set[int],
        title: str,
        body: str,
        action_url: str,
        severity: str,
        module: str,
        dedupe_key: str,
        metadata: Dict[str, Any],
        exclude_actor: Optional[bool],
    ) -> int:
        recipients = cls.resolve_recipients(
            ev_def=ev_def,
            target_obj=target_obj,
            actor_id=actor_id,
            owner_ids=owner_ids,
            target_main_area_ids=target_main_area_ids,
            exclude_actor=exclude_actor,
        )
        if not recipients:
            return 0

        # Duplicate prevention per recipient
        already_notified_ids: Set[int] = set()
        if dedupe_key:
            already_notified_ids = set(
                Notification.objects.filter(
                    recipient_id__in=[u.id for u in recipients],
                    dedupe_key=dedupe_key,
                ).values_list('recipient_id', flat=True)
            )

        to_create: List[Notification] = []
        for u in recipients:
            if u.id in already_notified_ids:
                continue
            to_create.append(
                Notification(
                    recipient=u,
                    actor_id=actor_id,
                    event_code=event_code,
                    module=module,
                    severity=severity,
                    title=title,
                    body=body,
                    action_url=action_url,
                    target_model=target_model_name,
                    target_object_id=target_pk,
                    metadata=metadata,
                    dedupe_key=dedupe_key,
                )
            )

        if not to_create:
            return 0

        delivered_count = 0
        for channel in ACTIVE_CHANNELS:
            if channel.is_enabled:
                delivered_count += channel.deliver(to_create)
        return delivered_count

    @classmethod
    def get_unread_count(cls, user) -> int:
        if not user or not user.is_authenticated or not user.is_active:
            return 0
        return Notification.objects.filter(recipient=user, is_read=False).count()

    @classmethod
    def serialize_notification(cls, n: Notification) -> Dict[str, Any]:
        return {
            'id': n.id,
            'event_code': n.event_code,
            'module': n.module,
            'severity': n.severity,
            'title': n.title,
            'body': n.body,
            'action_url': n.action_url,
            'open_url': f"/notifications/{n.id}/open/",
            'target_model': n.target_model,
            'target_object_id': n.target_object_id,
            'metadata': n.metadata or {},
            'is_read': n.is_read,
            'read_at': n.read_at.isoformat() if n.read_at else None,
            'created_at': n.created_at.isoformat() if n.created_at else None,
            'actor_name': (n.actor.name or n.actor.username) if n.actor else None,
        }

    @classmethod
    def mark_as_read(cls, user, notification_id: int) -> Optional[Notification]:
        n = Notification.objects.filter(pk=notification_id, recipient=user).first()
        if not n:
            return None
        if not n.is_read:
            n.is_read = True
            n.read_at = timezone.now()
            n.save(update_fields=['is_read', 'read_at'])
        return n

    @classmethod
    def mark_all_as_read(cls, user, module: str = '', ids: Optional[List[int]] = None) -> int:
        qs = Notification.objects.filter(recipient=user, is_read=False)
        if module:
            qs = qs.filter(module=module)
        if ids:
            qs = qs.filter(id__in=ids)
        return qs.update(is_read=True, read_at=timezone.now())

    @classmethod
    def register_device(cls, user, device_token: str, platform: str = 'android', provider: str = 'fcm', device_name: str = '', app_version: str = '') -> NotificationDevice:
        token = (device_token or '').strip()
        if not token:
            raise ValueError("device_token is required.")
        valid_platforms = {c[0] for c in NotificationDevice.PLATFORM_CHOICES}
        valid_providers = {c[0] for c in NotificationDevice.PROVIDER_CHOICES}
        platform = platform if platform in valid_platforms else 'android'
        provider = provider if provider in valid_providers else 'fcm'
        device, _ = NotificationDevice.objects.update_or_create(
            device_token=token,
            defaults={
                'user': user,
                'platform': platform,
                'provider': provider,
                'device_name': (device_name or '')[:150],
                'app_version': (app_version or '')[:40],
                'is_active': True,
            },
        )
        return device

    @classmethod
    def unregister_device(cls, user, device_token: str) -> int:
        token = (device_token or '').strip()
        if not token:
            return 0
        return NotificationDevice.objects.filter(user=user, device_token=token).update(is_active=False)

    @classmethod
    def prune_old_notifications(cls, days: int = 90) -> int:
        cutoff = timezone.now() - timedelta(days=max(1, int(days)))
        deleted_count, _ = Notification.objects.filter(created_at__lt=cutoff).delete()
        return deleted_count

    @classmethod
    def seed_default_rules(cls, overwrite: bool = False) -> int:
        """Seeds sensible default RoleNotificationRule rows for all existing active roles."""
        roles = list(Role.objects.all())
        created = 0
        for role in roles:
            r_name = (role.name or '').strip().lower()
            is_super = bool(role.is_super or r_name == 'superadmin')
            for ev in NOTIFICATION_EVENTS_CATALOG:
                default_roles = [x.lower() for x in ev.get('default_roles', [])]
                enabled = is_super or (r_name in default_roles)
                mode = ev.get('default_delivery_mode', 'all_in_scope')
                if is_super and mode == 'record_owner_only':
                    mode = 'all_in_scope'
                defaults = {
                    'is_enabled': enabled,
                    'delivery_mode': mode,
                    'same_area_only': not is_super and r_name != 'accountant',
                    'include_record_owner': mode == 'record_owner_only',
                    'include_actor': False,
                }
                if overwrite:
                    _, was_created = RoleNotificationRule.objects.update_or_create(
                        role=role,
                        event_code=ev['code'],
                        defaults=defaults,
                    )
                else:
                    _, was_created = RoleNotificationRule.objects.get_or_create(
                        role=role,
                        event_code=ev['code'],
                        defaults=defaults,
                    )
                if was_created:
                    created += 1
        return created
