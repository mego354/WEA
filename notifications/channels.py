"""
Pluggable Notification Delivery Channels.
- InAppDatabaseChannel: Active primary channel (persists Notification rows in DB).
- ExternalPushChannelAdapter: Active FCM HTTP v1 / APNs push delivery channel for registered
  Capacitor Android & iOS devices (NotificationDevice).
"""

import logging
from typing import Dict, List

from .fcm_provider import FCMProvider

logger = logging.getLogger(__name__)


class BaseNotificationChannel:
    channel_name: str = 'base'
    is_enabled: bool = False

    def deliver(self, notifications: List) -> int:
        raise NotImplementedError


class InAppDatabaseChannel(BaseNotificationChannel):
    channel_name = 'in_app_db'
    is_enabled = True

    def deliver(self, notifications: List) -> int:
        from .models import Notification
        if not notifications:
            return 0
        created = Notification.objects.bulk_create(notifications, batch_size=200)
        return len(created)


class ExternalPushChannelAdapter(BaseNotificationChannel):
    """
    Capacitor FCM HTTP v1 / APNs native push delivery channel.
    Reads active NotificationDevice rows for all recipients, sends structured deep-link payloads,
    handles invalid/expired tokens automatically, and records PushDeliveryAttempt rows.
    Never reports a notification as pushed if the provider skipped or rejected it.
    """
    channel_name = 'external_push'
    is_enabled = True

    def deliver(self, notifications: List) -> int:
        from .models import NotificationDevice

        if not notifications:
            return 0

        recipient_ids = list({n.recipient_id for n in notifications if getattr(n, 'recipient_id', None)})
        if not recipient_ids:
            return 0

        active_devices = list(
            NotificationDevice.objects.filter(
                user_id__in=recipient_ids,
                is_active=True,
                platform__in=('android', 'ios'),
            ).select_related('user')
        )
        if not active_devices:
            return 0

        devices_by_user: Dict[int, List[NotificationDevice]] = {}
        for dev in active_devices:
            devices_by_user.setdefault(dev.user_id, []).append(dev)

        pushed_count = 0
        # Deduplicate within the same batch per (device_id, dedupe_key or notification_id)
        seen_dispatches = set()

        for notif in notifications:
            user_devices = devices_by_user.get(notif.recipient_id)
            if not user_devices:
                continue

            notif_id_str = str(notif.pk or '')
            target_url = (notif.action_url or '').strip()
            if not target_url:
                target_url = f"/notifications/{notif_id_str}/open/" if notif_id_str else '/notifications/'

            for device in user_devices:
                dispatch_key = (device.id, notif.dedupe_key or notif_id_str or notif.title)
                if dispatch_key in seen_dispatches:
                    continue
                seen_dispatches.add(dispatch_key)

                result = FCMProvider.send_to_device(
                    device=device,
                    title=notif.title,
                    body=notif.body,
                    notification_obj=notif if notif.pk else None,
                    notification_id=notif_id_str,
                    event_type=notif.event_code,
                    object_type=notif.target_model or '',
                    object_id=str(notif.target_object_id or ''),
                    target_url=target_url,
                    module=notif.module or 'general',
                    severity=notif.severity or 'info',
                    extra_data=notif.metadata if isinstance(notif.metadata, dict) else None,
                )
                if result.get('success'):
                    pushed_count += 1

        return pushed_count


ACTIVE_CHANNELS: List[BaseNotificationChannel] = [
    InAppDatabaseChannel(),
    ExternalPushChannelAdapter(),
]
