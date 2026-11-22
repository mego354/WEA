from django.contrib import admin
from master_data.admin_mixins import SafeCascadeAdminMixin
from .models import RoleNotificationRule, Notification, NotificationDevice, PushDeliveryAttempt


@admin.register(RoleNotificationRule)
class RoleNotificationRuleAdmin(SafeCascadeAdminMixin, admin.ModelAdmin):
    list_display = ('role', 'event_code', 'is_enabled', 'delivery_mode', 'same_area_only', 'include_record_owner', 'include_actor', 'updated_at')
    list_filter = ('role', 'is_enabled', 'delivery_mode', 'same_area_only')
    search_fields = ('event_code', 'role__display_name', 'role__name')
    filter_horizontal = ('specific_users',)


@admin.register(Notification)
class NotificationAdmin(SafeCascadeAdminMixin, admin.ModelAdmin):
    list_display = ('id', 'recipient', 'event_code', 'module', 'severity', 'route_key', 'title', 'is_read', 'created_at')
    list_filter = ('module', 'severity', 'is_read', 'created_at')
    search_fields = ('title', 'body', 'event_code', 'route_key', 'recipient__username', 'recipient__name')
    readonly_fields = ('created_at', 'read_at')
    date_hierarchy = 'created_at'


@admin.register(NotificationDevice)
class NotificationDeviceAdmin(SafeCascadeAdminMixin, admin.ModelAdmin):
    list_display = ('user', 'platform', 'provider', 'device_uid', 'device_name', 'app_id', 'is_active', 'last_seen_at', 'last_push_attempt_at')
    list_filter = ('platform', 'provider', 'is_active')
    search_fields = ('user__username', 'user__name', 'device_uid', 'device_name', 'app_id')
    readonly_fields = ('last_seen_at', 'created_at', 'last_push_attempt_at', 'last_push_success_at')


@admin.register(PushDeliveryAttempt)
class PushDeliveryAttemptAdmin(SafeCascadeAdminMixin, admin.ModelAdmin):
    list_display = ('id', 'recipient', 'device', 'provider', 'status', 'target_url', 'error_code', 'created_at')
    list_filter = ('status', 'provider', 'created_at')
    search_fields = ('recipient__username', 'recipient__name', 'target_url', 'error_code', 'provider_message_id')
    readonly_fields = ('created_at',)

