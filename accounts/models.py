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
        if self.is_superuser:
            return True
        if self.role:
            if self.role.is_super or self.role.name.lower() in ['superadmin', 'admin']:
                return True
        return False

    @property
    def can_bypass_location(self):
        if self.is_superuser or self.is_super_admin or self.bypass_location_verification:
            return True
        if self.role and self.role.tags.filter(tag='customers:customers/bypassLocation').exists():
            return True
        return False

    def has_permission(self, perm_codename):
        """Backend authorization method with SuperAdmin override."""
        if not self.is_authenticated:
            return False
        if self.is_superuser or self.is_super_admin:
            return True
        if not self.is_active:
            return False
        if self.role and self.role.is_active:
            return self.role.permissions.filter(codename=perm_codename).exists()
        return False


