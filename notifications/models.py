from django.db import models
from django.conf import settings


class RoleNotificationRule(models.Model):
    """
    Role-level notification subscription & targeting policy configurable in Role Settings.
    """
    DELIVERY_MODE_CHOICES = [
        ('all_in_scope', 'كل المستخدمين ضمن النطاق المسموح'),
        ('record_owner_only', 'صاحب / منشئ السجل فقط'),
        ('approvers_only', 'المعتمدون المؤهلون فقط'),
        ('specific_users', 'مستخدمون محددون فقط'),
    ]

    role = models.ForeignKey(
        'accounts.Role',
        on_delete=models.CASCADE,
        related_name='notification_rules',
        verbose_name='الدور الوظيفي',
    )
    event_code = models.CharField(max_length=100, db_index=True, verbose_name='كود الحدث')
    is_enabled = models.BooleanField(default=True, verbose_name='مفعل')
    delivery_mode = models.CharField(
        max_length=30,
        choices=DELIVERY_MODE_CHOICES,
        default='all_in_scope',
        verbose_name='نمط الاستلام',
    )
    same_area_only = models.BooleanField(
        default=True,
        verbose_name='تقييد بنفس المنطقة الجغرافية',
    )
    include_record_owner = models.BooleanField(
        default=False,
        verbose_name='تضمين منشئ / صاحب السجل',
    )
    include_actor = models.BooleanField(
        default=False,
        verbose_name='تضمين منفذ العملية (الفاعل)',
    )
    specific_users = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name='targeted_notification_rules',
        verbose_name='مستخدمون محددون',
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'قاعدة إشعارات للدور'
        verbose_name_plural = 'قواعد إشعارات الأدوار'
        unique_together = ('role', 'event_code')
        ordering = ['role_id', 'event_code']

    def __str__(self):
        return f"{self.role.display_name} -> {self.event_code} ({'ON' if self.is_enabled else 'OFF'})"


class Notification(models.Model):
    """
    Persistent in-app notification record (source of truth for Web UI and Capacitor API clients).
    """
    SEVERITY_CHOICES = [
        ('info', 'معلومات'),
        ('success', 'نجاح'),
        ('warning', 'تنبيه'),
        ('danger', 'هام / تحذير'),
    ]

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notifications',
        verbose_name='المستلم',
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sent_notifications',
        verbose_name='المنفذ',
    )
    event_code = models.CharField(max_length=100, db_index=True, verbose_name='كود الحدث')
    module = models.CharField(max_length=40, db_index=True, verbose_name='الموديول')
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES, default='info', verbose_name='الأهمية')
    title = models.CharField(max_length=200, verbose_name='العنوان')
    body = models.TextField(blank=True, default='', verbose_name='التفاصيل')
    route_key = models.CharField(max_length=80, blank=True, default='', db_index=True, verbose_name='مفتاح الوجهة الداخلية')
    action_url = models.CharField(max_length=500, blank=True, default='', verbose_name='رابط الإجراء')
    target_model = models.CharField(max_length=80, blank=True, default='', verbose_name='نوع السجل')
    target_object_id = models.PositiveIntegerField(null=True, blank=True, verbose_name='معرف السجل')
    metadata = models.JSONField(default=dict, blank=True, verbose_name='بيانات إضافية')
    dedupe_key = models.CharField(max_length=180, blank=True, default='', db_index=True, verbose_name='مفتاح منع التكرار')
    is_read = models.BooleanField(default=False, db_index=True, verbose_name='مقروء')
    read_at = models.DateTimeField(null=True, blank=True, verbose_name='تاريخ القراءة')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, verbose_name='تاريخ الإنشاء')

    class Meta:
        verbose_name = 'إشعار'
        verbose_name_plural = 'الإشعارات'
        ordering = ['-created_at', '-id']
        indexes = [
            models.Index(fields=['recipient', 'is_read', '-created_at'], name='notif_recip_read_created_idx'),
            models.Index(fields=['recipient', '-created_at'], name='notif_recip_created_idx'),
            models.Index(fields=['recipient', 'dedupe_key'], name='notif_recip_dedupe_idx'),
        ]

    def __str__(self):
        return f"[{self.event_code}] -> {self.recipient} ({'مقروء' if self.is_read else 'جديد'})"


class NotificationDevice(models.Model):
    """
    Registered client devices for Native Push Notification delivery
    (Capacitor Android/iOS via FCM/APNs or Web Push).
    """
    PLATFORM_CHOICES = [
        ('web', 'Web Browser'),
        ('android', 'Capacitor Android'),
        ('ios', 'Capacitor iOS'),
    ]
    PROVIDER_CHOICES = [
        ('fcm', 'Firebase Cloud Messaging (FCM)'),
        ('apns', 'Apple Push Notification Service (APNs)'),
        ('webpush', 'Web Push'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notification_devices',
        verbose_name='المستخدم',
    )
    platform = models.CharField(max_length=20, choices=PLATFORM_CHOICES, default='android', verbose_name='المنصة')
    provider = models.CharField(max_length=20, choices=PROVIDER_CHOICES, default='fcm', verbose_name='مزود الإشعارات')
    device_uid = models.CharField(max_length=128, blank=True, default='', db_index=True, verbose_name='معرف تثبيت الجهاز')
    device_token = models.CharField(max_length=512, unique=True, verbose_name='رمز الجهاز (Token)')
    device_name = models.CharField(max_length=150, blank=True, default='', verbose_name='اسم الجهاز')
    app_version = models.CharField(max_length=40, blank=True, default='', verbose_name='إصدار التطبيق')
    app_id = models.CharField(max_length=120, blank=True, default='', verbose_name='معرف حزمة التطبيق')
    permission_status = models.CharField(max_length=30, blank=True, default='granted', verbose_name='حالة الصلاحية')
    is_active = models.BooleanField(default=True, db_index=True, verbose_name='نشط')
    last_seen_at = models.DateTimeField(auto_now=True, verbose_name='آخر ظهور')
    last_push_attempt_at = models.DateTimeField(null=True, blank=True, verbose_name='آخر محاولة إرسال')
    last_push_success_at = models.DateTimeField(null=True, blank=True, verbose_name='آخر إرسال ناجح')
    last_push_error = models.TextField(blank=True, default='', verbose_name='آخر خطأ من المزود')
    failure_count = models.PositiveIntegerField(default=0, verbose_name='عدد مرات الفشل المتتالية')
    deactivated_reason = models.CharField(max_length=150, blank=True, default='', verbose_name='سبب إلغاء التفعيل')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='تاريخ التسجيل')

    class Meta:
        verbose_name = 'جهاز إشعارات'
        verbose_name_plural = 'أجهزة الإشعارات (Capacitor / Push)'
        ordering = ['-last_seen_at']

    @property
    def masked_token(self) -> str:
        tok = (self.device_token or '').strip()
        if len(tok) <= 14:
            return f"{tok[:4]}...{tok[-2:]}" if len(tok) > 6 else "***"
        return f"{tok[:8]}...{tok[-6:]}"

    def __str__(self):
        return f"{self.user} ({self.platform}/{self.provider} - {self.masked_token})"


class PushDeliveryAttempt(models.Model):
    """
    Audit & diagnostic log for every native push notification delivery attempt to FCM/APNs.
    Never stores private keys or raw unmasked tokens in error logs.
    """
    STATUS_CHOICES = [
        ('sent', 'تم الإرسال للمزود (Sent)'),
        ('failed', 'فشل الإرسال (Failed)'),
        ('invalid_token', 'رمز جهاز غير صالح أو منتهي (Invalid Token)'),
        ('skipped', 'تم التخطي - المزود غير مفعل (Skipped)'),
    ]

    notification = models.ForeignKey(
        Notification,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='push_attempts',
        verbose_name='الإشعار',
    )
    device = models.ForeignKey(
        NotificationDevice,
        on_delete=models.CASCADE,
        related_name='delivery_attempts',
        verbose_name='الجهاز',
    )
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='push_delivery_attempts',
        verbose_name='المستلم',
    )
    provider = models.CharField(max_length=20, default='fcm', verbose_name='المزود')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, db_index=True, verbose_name='الحالة')
    target_url = models.CharField(max_length=500, blank=True, default='', verbose_name='الرابط المستهدف')
    provider_message_id = models.CharField(max_length=255, blank=True, default='', verbose_name='معرف رسالة المزود')
    error_code = models.CharField(max_length=100, blank=True, default='', verbose_name='كود الخطأ')
    error_message = models.TextField(blank=True, default='', verbose_name='تفاصيل الخطأ')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, verbose_name='وقت المحاولة')

    class Meta:
        verbose_name = 'سجل محاولة إرسال Push'
        verbose_name_plural = 'سجلات محاولات إرسال Push'
        ordering = ['-created_at', '-id']

    def __str__(self):
        return f"PushAttempt({self.status}) -> {self.recipient} [{self.provider}]"

