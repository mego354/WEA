"""
Pluggable Notification Delivery Channels.
- InAppDatabaseChannel: Active primary channel (persists Notification rows in DB).
- ExternalPushChannelAdapter: Clean extension point for future FCM / APNs / Capacitor push.
  Intentionally inactive until real provider credentials & native push configuration exist.
"""

import logging
from typing import Iterable, List
from django.db import transaction

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
    Extension hook for future Capacitor FCM / APNs push delivery.
    Does NOT fake push delivery; returns 0 cleanly until provider settings are enabled.
    """
    channel_name = 'external_push'
    is_enabled = False

    def deliver(self, notifications: List) -> int:
        # Hook for future FCM/APNs integration reading active NotificationDevice rows.
        return 0


ACTIVE_CHANNELS: List[BaseNotificationChannel] = [
    InAppDatabaseChannel(),
    ExternalPushChannelAdapter(),
]
