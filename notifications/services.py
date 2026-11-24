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

    # Fallback to user/assignee/owner areas (e.g. VisitPlan has assignee without direct contact/area)
    if not areas:
        for user_attr in ('assignee', 'owner', 'created_by'):
            u = getattr(target_obj, user_attr, None)
            if u is not None and hasattr(u, 'assigned_areas'):
                areas.extend(list(u.assigned_areas.all()))
                break

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
        route_key: str = '',
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
        from .formatters import get_default_route_key, resolve_destination_url

        ev_def = get_event_definition(event_code)
        if not ev_def:
            logger.warning("NotificationService.emit called with unregistered event_code=%s", event_code)
            return 0

        final_title = (title or ev_def['name_ar'])[:200]
        final_body = (body or '')[:2000]
        final_severity = severity or ev_def.get('default_severity', 'info')
        final_module = ev_def['module']
        final_route_key = (route_key or '').strip() or get_default_route_key(event_code)
        final_metadata = dict(metadata or {})
        actor_id = getattr(actor, 'pk', None) if actor else None

        target_model_name = ''
        target_pk = None
        if target_obj is not None:
            target_model_name = target_obj.__class__.__name__.lower()
            target_pk = getattr(target_obj, 'pk', None)

        final_action_url = (action_url or '').strip()
        if not final_action_url and final_route_key:
            final_action_url = resolve_destination_url(
                route_key=final_route_key,
                record_id=target_pk,
                target_obj=target_obj,
            )

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
                    route_key=final_route_key,
                    action_url=final_action_url,
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
        route_key: str,
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
                    route_key=route_key,
                    action_url=action_url,
                    target_model=target_model_name,
                    target_object_id=target_pk,
                    metadata=metadata,
                    dedupe_key=dedupe_key,
                )
            )

        if not to_create:
            return 0

        in_app_count = 0
        for channel in ACTIVE_CHANNELS:
            if channel.is_enabled:
                try:
                    count = channel.deliver(to_create)
                    if channel.channel_name == 'in_app_db':
                        in_app_count = count
                except Exception:
                    logger.exception("Channel %s failed cleanly during notification delivery", channel.channel_name)
        return in_app_count

    @classmethod
    def get_unread_count(cls, user) -> int:
        if not user or not user.is_authenticated or not user.is_active:
            return 0
        return Notification.objects.filter(recipient=user, is_read=False).count()

    @classmethod
    def serialize_notification(cls, n: Notification) -> Dict[str, Any]:
        from .formatters import (
            get_default_route_key,
            get_module_label_ar,
            get_severity_label_ar,
        )

        ev_def = get_event_definition(n.event_code) or {}
        resolved_route_key = (n.route_key or '').strip() or get_default_route_key(n.event_code)
        open_url = f"/notifications/{n.id}/open/"
        return {
            'id': n.id,
            'event_code': n.event_code,
            'event_label_ar': ev_def.get('name_ar') or n.title,
            'module': n.module,
            'module_label_ar': get_module_label_ar(n.module),
            'severity': n.severity,
            'severity_label_ar': get_severity_label_ar(n.severity),
            'title': n.title,
            'body': n.body,
            'route_key': resolved_route_key,
            'destination': {
                'route_key': resolved_route_key,
                'record_type': n.target_model or '',
                'record_id': n.target_object_id,
                'open_url': open_url,
                'fallback_url': '/notifications/',
            },
            'action_url': n.action_url,
            'open_url': open_url,
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
    def register_device(
        cls,
        user,
        device_token: str,
        platform: str = 'android',
        provider: str = 'fcm',
        device_name: str = '',
        app_version: str = '',
        app_id: str = '',
        permission_status: str = 'granted',
        device_uid: str = '',
    ) -> NotificationDevice:
        from .fcm_provider import is_Likely_webpush_or_invalid_native_token, mask_token

        token = (device_token or '').strip()
        if not token:
            raise ValueError("رمز الجهاز (device_token) مطلوب.")

        valid_platforms = {c[0] for c in NotificationDevice.PLATFORM_CHOICES}
        valid_providers = {c[0] for c in NotificationDevice.PROVIDER_CHOICES}
        platform = (platform or 'android').lower().strip()
        # Both Android and iOS use FCM tokens (APNs bridged to FCM via Firebase Messaging)
        provider = (provider or 'fcm').lower().strip()
        platform = platform if platform in valid_platforms else 'android'
        provider = provider if provider in valid_providers else 'fcm'
        clean_uid = (device_uid or '').strip()[:128]

        if platform in ('android', 'ios') and provider == 'webpush':
            raise ValueError("لا يمكن استخدام مزود Web Push لتسجيل أجهزة تطبيقات الموبايل الأصلية.")

        is_bad, bad_reason = is_Likely_webpush_or_invalid_native_token(token, platform)
        if is_bad:
            raise ValueError(bad_reason)

        clean_perm = (permission_status or 'granted')[:30]

        # Read-only fast path: if this exact device token is already active for this user
        # with unchanged metadata and was seen recently, avoid unnecessary SQLite writes
        # on every page load or concurrent multi-device session.
        existing = NotificationDevice.objects.filter(device_token=token).first()
        if (
            existing is not None
            and existing.user_id == user.pk
            and existing.is_active
            and existing.platform == platform
            and existing.provider == provider
            and existing.permission_status == clean_perm
            and existing.failure_count == 0
            and (not clean_uid or existing.device_uid == clean_uid)
            and existing.last_seen_at
            and (timezone.now() - existing.last_seen_at) < timedelta(hours=1)
        ):
            return existing

        defaults = {
            'user': user,
            'platform': platform,
            'provider': provider,
            'device_name': (device_name or '')[:150],
            'app_version': (app_version or '')[:40],
            'app_id': (app_id or '')[:120],
            'permission_status': clean_perm,
            'is_active': True,
            'deactivated_reason': '',
            'failure_count': 0,
        }
        if clean_uid:
            defaults['device_uid'] = clean_uid

        with transaction.atomic():
            device, created = NotificationDevice.objects.update_or_create(
                device_token=token,
                defaults=defaults,
            )

            # Safe token rotation: if device_uid is supplied, deactivate ONLY previous tokens
            # belonging to the SAME physical installation (user + platform + device_uid),
            # never touching other devices owned by the user.
            if clean_uid:
                rotated = NotificationDevice.objects.filter(
                    user=user,
                    platform=platform,
                    device_uid=clean_uid,
                    is_active=True,
                ).exclude(pk=device.pk).update(
                    is_active=False,
                    deactivated_reason='token_rotated',
                )
                if rotated:
                    logger.info(
                        "[NotificationService] Rotated %s old token(s) for user=%s device_uid=%s",
                        rotated, user.pk, clean_uid[:16],
                    )

        logger.info(
            "[NotificationService] Device %s: id=%s user=%s platform=%s provider=%s token=%s app_id=%s",
            'created' if created else 'updated',
            device.id,
            user.pk,
            platform,
            provider,
            mask_token(token),
            app_id or '-',
        )
        return device

    @classmethod
    def unregister_device(cls, user, device_token: str) -> int:
        from .fcm_provider import mask_token

        token = (device_token or '').strip()
        if not token:
            return 0
        updated = NotificationDevice.objects.filter(user=user, device_token=token).update(
            is_active=False,
            deactivated_reason='user_logout_or_unregister',
        )
        logger.info(
            "[NotificationService] Device unregistered: user=%s token=%s count=%s",
            getattr(user, 'pk', None),
            mask_token(token),
            updated,
        )
        return updated

    @classmethod
    def send_test_push_to_user(
        cls,
        user,
        title: str = '',
        body: str = '',
        target_url: str = '/notifications/',
        device_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Creates an in-app test notification for the authenticated user and dispatches
        a real native push notification via FCMProvider to the user's active registered device(s).
        """
        from .fcm_provider import FCMProvider

        final_title = (title or 'إشعار تجريبي من نظام WEA Pharma').strip()[:200]
        final_body = (body or 'اضغط على هذا الإشعار لفتح الصفحة المرتبطة مباشرة داخل التطبيق.').strip()[:1000]
        final_target = (target_url or '/notifications/').strip()
        if not final_target.startswith('/'):
            final_target = '/notifications/'

        # Persist in-app notification record so tapping it can also open or mark read
        notif = Notification.objects.create(
            recipient=user,
            actor=user,
            event_code='system.test_push',
            module='master_data',
            severity='info',
            title=final_title,
            body=final_body,
            route_key='notifications.inbox',
            action_url=final_target,
            target_model='notification',
            metadata={'is_test_push': True, 'target_url': final_target},
        )

        qs = NotificationDevice.objects.filter(user=user, is_active=True)
        if device_id:
            qs = qs.filter(pk=device_id)
        devices = list(qs.order_by('-last_seen_at'))

        fcm_status = FCMProvider.get_config_status()
        if not devices:
            return {
                'status': 'no_devices',
                'success': False,
                'notification_id': notif.id,
                'target_url': final_target,
                'delivered_count': 0,
                'failed_count': 0,
                'fcm_configured': fcm_status['fcm_configured'],
                'firebase_project_id': fcm_status['firebase_project_id'],
                'message': 'لا توجد أجهزة موبايل نشطة مسجلة لحسابك حالياً. افتح تطبيق الموبايل وسجل الدخول لتسجيل الجهاز تلقائياً.',
                'attempts': [],
            }

        attempts = []
        delivered_count = 0
        failed_count = 0
        for dev in devices:
            res = FCMProvider.send_to_device(
                device=dev,
                title=final_title,
                body=final_body,
                notification_obj=notif,
                notification_id=str(notif.id),
                event_type='system.test_push',
                route_key='notifications.inbox',
                object_type='notification',
                object_id=str(notif.id),
                target_url=final_target,
                module='master_data',
                severity='info',
            )
            attempts.append(res)
            if res.get('success'):
                delivered_count += 1
            else:
                failed_count += 1

        overall_ok = delivered_count > 0
        if overall_ok:
            msg = f"تم إرسال الإشعار التجريبي بنجاح إلى {delivered_count} جهاز."
        elif not fcm_status['fcm_configured']:
            msg = "تم حفظ الإشعار داخلياً، ولكن لم يتم إرسال Push خارجي لأن بيانات خدمة Firebase (Service Account) غير مضبوطة على الخادم."
        else:
            first_err = attempts[0].get('error_message') if attempts else 'Unknown error'
            msg = f"فشل إرسال الإشعار عبر مزود FCM: {first_err}"

        return {
            'status': 'ok' if overall_ok else 'provider_error',
            'success': overall_ok,
            'notification_id': notif.id,
            'target_url': final_target,
            'delivered_count': delivered_count,
            'failed_count': failed_count,
            'fcm_configured': fcm_status['fcm_configured'],
            'firebase_project_id': fcm_status['firebase_project_id'],
            'message': msg,
            'attempts': attempts,
        }

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
