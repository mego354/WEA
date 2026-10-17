from django.db import models
from django.contrib.auth.models import AbstractUser, Permission


class Role(models.Model):
    name = models.CharField(max_length=100, unique=True, verbose_name="اسم الدور البرمجي")
    display_name = models.CharField(max_length=150, verbose_name="المسمى الوظيفي")
    description = models.TextField(blank=True, verbose_name="الوصف")
    is_system = models.BooleanField(default=False, verbose_name="دور نظامي ثابت")
    is_sales_team = models.BooleanField(default=False, verbose_name="فريق مبيعات")
    is_area_manager = models.BooleanField(default=False, verbose_name="مدير منطقة")
    is_rep = models.BooleanField(default=False, verbose_name="مندوب ميداني")
    can_hold_vault = models.BooleanField(default=False, verbose_name="مخوّل بعهدة نقدية / خزنة")
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
    mobile = models.CharField(max_length=30, blank=True, verbose_name="رقم الهاتف")
    role = models.ForeignKey(Role, on_delete=models.SET_NULL, null=True, blank=True, related_name="users", verbose_name="الدور الوظيفي")
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
        return self.is_superuser or (self.role and self.role.name.lower() in ['superadmin', 'admin'])

    @property
    def can_bypass_location(self):
        return self.is_superuser or self.is_super_admin or self.bypass_location_verification

