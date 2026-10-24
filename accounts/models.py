from django.db import models
from django.contrib.auth.models import AbstractUser, Permission


class RoleTag(models.Model):
    tag = models.CharField(max_length=150, unique=True, verbose_name="مفتاح العلامة")
    display_name = models.CharField(max_length=200, verbose_name="اسم العلامة")

    class Meta:
        verbose_name = "علامة وظيفية للدور"
        verbose_name_plural = "العلامات الوظيفية للأدوار"
        ordering = ['tag']

    def __str__(self):
        return self.display_name or self.tag


class Role(models.Model):
    name = models.CharField(max_length=100, unique=True, verbose_name="اسم الدور البرمجي")
    display_name = models.CharField(max_length=150, verbose_name="المسمى الوظيفي")
    description = models.TextField(blank=True, verbose_name="الوصف")
    is_system = models.BooleanField(default=False, verbose_name="دور نظامي ثابت")
    is_active = models.BooleanField(default=True, verbose_name="مفعل")

    # Reference ERP Attributes / Switches
    is_super = models.BooleanField(default=False, verbose_name="سوبر")
    is_sales_team = models.BooleanField(default=False, verbose_name="فريق مبيعات")
    is_area_manager = models.BooleanField(default=False, verbose_name="مدير لمنطقة رئيسية")
    is_sub_area_manager = models.BooleanField(default=False, verbose_name="مدير منطقة فرعية")
    is_rep = models.BooleanField(default=False, verbose_name="مندوب")
    can_hold_vault = models.BooleanField(default=False, verbose_name="مخوّل بعهدة نقدية / خزنة")
    has_sales_targets = models.BooleanField(default=False, verbose_name="له أهداف مبيعات")
    is_contact_manager = models.BooleanField(default=False, verbose_name="مسئول جهات الاتصال")
    is_main_area_bound = models.BooleanField(default=False, verbose_name="تابع لمنطقة رئيسية")
    is_sub_area_bound = models.BooleanField(default=False, verbose_name="تابع لمنطقة فرعية")

    tags = models.ManyToManyField(RoleTag, blank=True, related_name="roles", verbose_name="العلامات")
    permissions = models.ManyToManyField(Permission, blank=True, related_name="custom_roles", verbose_name="الصلاحيات")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="تاريخ التحديث")

    class Meta:
        verbose_name = "دور صلاحيات"
        verbose_name_plural = "الأدوار والصلاحيات"
        ordering = ['id']

    def __str__(self):
        return self.display_name or self.name

    @property
    def is_manager_role(self):
        return bool(
            self.is_super or
            self.is_area_manager or
            self.is_sub_area_manager or
            self.name in ['admin', 'manager', 'area_manager', 'sub_area_manager']
        )


class User(AbstractUser):
    name = models.CharField(max_length=200, verbose_name="الاسم الكامل")
    code = models.CharField(max_length=50, blank=True, verbose_name="الكود")
    mobile = models.CharField(max_length=30, blank=True, verbose_name="رقم الهاتف")
    role = models.ForeignKey(Role, on_delete=models.SET_NULL, null=True, blank=True, related_name="users", verbose_name="الدور الوظيفي")
    assigned_areas = models.ManyToManyField('master_data.Area', blank=True, related_name="assigned_users", verbose_name="المناطق المعينة")
    avatar = models.ImageField(upload_to="avatars/", null=True, blank=True, verbose_name="الصورة الشخصية")
    locale = models.CharField(max_length=10, default="ar", verbose_name="لغة الواجهة")
    bypass_location_verification = models.BooleanField(default=False, verbose_name="تجاوز التحقق من الموقع (خاص بالمدراء)")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ التسجيل")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="تاريخ التحديث")

    class Meta:
        verbose_name = "مستخدم"
        verbose_name_plural = "المستخدمون"
        ordering = ['-created_at']

    def __str__(self):
        return self.name or self.username

    @property
    def role_name(self):
        return self.role.display_name if self.role else ("مدير نظام" if self.is_superuser else "مستخدم")

    @property
    def is_super_admin(self):
        """
        Explicit SuperAdmin verification.
        Only a true superuser or an active user assigned the system-level 'SuperAdmin' role is authorized.
        Merely having a role named 'Admin' or arbitrary title does NOT grant superadmin privileges.
        """
        if not self.is_active:
            return False
        if self.is_superuser:
            return True
        if self.role and self.role.is_active and self.role.is_super and self.role.name == 'SuperAdmin':
            return True
        return False

    @property
    def can_bypass_location(self):
        if not self.is_active:
            return False
        if self.is_superuser or self.is_super_admin or self.bypass_location_verification:
            return True
        if self.role and self.role.tags.filter(tag='customers:customers/bypassLocation').exists():
            return True
        return False

    def clear_perm_cache(self):
        """Clears in-memory permission cache for this user instance."""
        if hasattr(self, '_cached_perm_codenames'):
            del self._cached_perm_codenames

    def get_effective_permission_codenames(self):
        """
        Returns a set of all effective permission codenames for this user.
        Cached per user instance for high-performance requests.
        """
        if hasattr(self, '_cached_perm_codenames'):
            return self._cached_perm_codenames

        if not self.is_authenticated or not self.is_active:
            self._cached_perm_codenames = set()
            return self._cached_perm_codenames

        if self.is_super_admin:
            from .permission_registry import get_all_registered_permissions
            all_codenames = {p['codename'] for p in get_all_registered_permissions()}
            self._cached_perm_codenames = all_codenames
            return self._cached_perm_codenames

        if not self.role or not self.role.is_active:
            self._cached_perm_codenames = set()
            return self._cached_perm_codenames

        # Get all permissions assigned to the role
        role_perms = set(self.role.permissions.values_list('codename', flat=True))
        
        # Enforce Module-Level Inheritance:
        # A child permission is effective IF AND ONLY IF its parent module root permission is enabled!
        from .permission_registry import get_module_for_permission
        effective = set()
        for codename in role_perms:
            if codename.startswith('module:'):
                effective.add(codename)
            else:
                mod_key = get_module_for_permission(codename)
                if mod_key:
                    mod_root = f"module:{mod_key}"
                    if mod_root in role_perms:
                        effective.add(codename)
                else:
                    # Non-module or ad-hoc custom permissions
                    effective.add(codename)

        self._cached_perm_codenames = effective
        return self._cached_perm_codenames

    def has_permission(self, perm_codename):
        """
        Backend authorization method enforcing:
        1. SuperAdmin override.
        2. Module-level permission inheritance (disabling a module disables child actions).
        3. Request-level caching for high performance.
        """
        if not self.is_authenticated or not self.is_active:
            return False
        if self.is_super_admin:
            return True

        if isinstance(perm_codename, (list, tuple, set)):
            return any(self.has_permission(p) for p in perm_codename)

        effective_perms = self.get_effective_permission_codenames()
        return perm_codename in effective_perms


class SecurityAuditLog(models.Model):
    """
    Audit log tracking all security-sensitive administrative operations:
    Role creations, modifications, deletions, user role assignments,
    status changes, password resets, and permission changes.
    """
    ACTION_CHOICES = [
        ('ROLE_CREATED', 'إنشاء دور صلاحيات'),
        ('ROLE_UPDATED', 'تعديل دور وصلاحيات'),
        ('ROLE_DELETED', 'حذف دور صلاحيات'),
        ('ROLE_DUPLICATED', 'استنساخ دور صلاحيات'),
        ('USER_CREATED', 'إنشاء حساب مستخدم جديد'),
        ('USER_UPDATED', 'تعديل بيانات أو دور المستخدم'),
        ('USER_ROLE_CHANGED', 'تغيير الدور الوظيفي للمستخدم'),
        ('USER_STATUS_TOGGLED', 'تفعيل/تعطيل حساب مستخدم'),
        ('USER_PASSWORD_RESET', 'إعادة تعيين كلمة المرور'),
        ('USER_BYPASS_LOCATION_TOGGLED', 'تعديل صلاحية تجاوز التحقق من الموقع'),
        ('PERMISSIONS_SEEDED', 'تهيئة وتحديث مصفوفة الصلاحيات'),
    ]

    actor = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='security_actions_performed', verbose_name="المسؤول المنفذ"
    )
    action_type = models.CharField(max_length=50, choices=ACTION_CHOICES, db_index=True, verbose_name="نوع العملية")
    target_user = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='security_events_targeted', verbose_name="المستخدم المستهدف"
    )
    target_role = models.ForeignKey(
        Role, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='audit_logs', verbose_name="الدور المستهدف"
    )
    description = models.TextField(verbose_name="تفاصيل العملية")
    ip_address = models.GenericIPAddressField(null=True, blank=True, verbose_name="عنوان IP")
    user_agent = models.TextField(blank=True, verbose_name="متصفح العميل")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, verbose_name="تاريخ ووقت العملية")

    class Meta:
        verbose_name = "سجل تدقيق أمني"
        verbose_name_plural = "سجلات التدقيق الأمني"
        ordering = ['-created_at']

    def __str__(self):
        actor_name = self.actor.name or self.actor.username if self.actor else "النظام"
        return f"[{self.get_action_type_display()}] بواسطة {actor_name} في {self.created_at.strftime('%Y-%m-%d %H:%M')}"



