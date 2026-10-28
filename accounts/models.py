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
    # The 5 Canonical Supported Business Roles
    ROLE_SUPERADMIN = 'superadmin'
    ROLE_MANAGER = 'manager'
    ROLE_ACCOUNTANT = 'accountant'
    ROLE_REP = 'rep'
    ROLE_MEDICAL_REP = 'medical_rep'

    CANONICAL_ROLE_KEYS = [
        ROLE_SUPERADMIN,
        ROLE_MANAGER,
        ROLE_ACCOUNTANT,
        ROLE_REP,
        ROLE_MEDICAL_REP,
    ]

    CANONICAL_ROLES = [
        (ROLE_SUPERADMIN, 'مدير النظام الأعلى'),
        (ROLE_MANAGER, 'مدير'),
        (ROLE_ACCOUNTANT, 'محاسب'),
        (ROLE_REP, 'مندوب مبيعات'),
        (ROLE_MEDICAL_REP, 'مندوب دعاية طبية'),
    ]

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

    @classmethod
    def get_supported_roles(cls):
        """Returns queryset of the 5 canonical supported roles."""
        return cls.objects.filter(name__in=cls.CANONICAL_ROLE_KEYS, is_active=True).order_by('id')

    @property
    def is_manager_role(self):
        name_l = (self.name or '').lower()
        return bool(
            self.is_super or
            self.is_area_manager or
            self.is_sub_area_manager or
            name_l in ['superadmin', 'admin', 'ceo', 'manager', 'areamanager', 'area_manager', 'sub_area_manager', 'purchasingmanager']
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
        Authorized if user is a true superuser or assigned an active canonical 'superadmin' / 'SuperAdmin' role.
        """
        if not self.is_active:
            return False
        if self.is_superuser:
            return True
        if self.role and self.role.is_active:
            if self.role.is_super or (self.role.name and self.role.name.lower() == 'superadmin'):
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

    def get_default_warehouse(self):
        """
        Returns the designated default warehouse for this representative.
        Prefers an active rep warehouse assigned to this user, then any assigned warehouse,
        then any warehouse where user is manager.
        """
        from inventory.models import Warehouse
        wh = Warehouse.objects.filter(assigned_user=self, is_rep_warehouse=True, is_active=True).first()
        if not wh:
            wh = Warehouse.objects.filter(assigned_user=self, is_active=True).first()
        if not wh:
            wh = Warehouse.objects.filter(manager=self, is_active=True).first()
        if wh and not wh.area_id and self.assigned_areas.exists():
            wh.area = self.assigned_areas.first()
            wh.save(update_fields=['area'])
        return wh

    def get_default_treasury(self):
        """
        Returns the designated default cash treasury / vault for this representative.
        """
        from treasury.models import Vault
        v = Vault.objects.filter(assigned_user=self, is_rep_vault=True, is_active=True).first()
        if v:
            return v
        v = Vault.objects.filter(assigned_user=self, is_active=True, vault_type='cash').first()
        if v:
            return v
        return Vault.objects.filter(assigned_user=self, is_active=True).first()

    def get_main_areas(self):
        """
        Returns QuerySet of root/main areas (governorates) for this user.
        """
        from master_data.models import Area
        from accounts.permissions import get_user_main_areas
        return get_user_main_areas(self)

    def clear_perm_cache(self):
        """Clears in-memory permission cache for this user instance."""
        if hasattr(self, '_cached_perm_codenames'):
            del self._cached_perm_codenames

    def get_effective_permission_codenames(self):
        """
        Returns a set of all effective permission codenames for this user.
        Merges role permissions and direct user_permissions with module-level inheritance.
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

        # Get all permissions assigned to the role plus any direct user permissions
        role_perms = set(self.role.permissions.values_list('codename', flat=True)) if (self.role and self.role.is_active) else set()
        user_perms = set(self.user_permissions.values_list('codename', flat=True))
        all_assigned = role_perms | user_perms
        
        # Enforce Module-Level Inheritance:
        # A child permission is effective IF AND ONLY IF its parent module root permission is enabled!
        from .permission_registry import get_module_for_permission
        effective = set()
        for codename in all_assigned:
            if codename.startswith('module:'):
                effective.add(codename)
            else:
                mod_key = get_module_for_permission(codename)
                if mod_key:
                    mod_root = f"module:{mod_key}"
                    if mod_root in all_assigned:
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
    Comprehensive Audit log tracking all security, operational, and financial events across the ERP:
    User/Role/Perm operations, Contacts, UDF, Todos, Activities/Visits, Visit Templates,
    Catalog, Inventory/Warehouses, Transfers, Sales Orders/Approvals, Purchases,
    Treasury, Areas, Settings, Imports/Exports.
    """
    MODULE_CHOICES = [
        ('auth', 'المصادقة والأمان'),
        ('accounts', 'المستخدمين والأدوار'),
        ('contacts', 'جهات الاتصال'),
        ('custom_fields', 'الحقول المخصصة (UDF)'),
        ('todos', 'المهام (Todos)'),
        ('timeline', 'الأنشطة والجدول الزمني'),
        ('visits', 'الزيارات الميدانية'),
        ('templates', 'قوالب الزيارات'),
        ('catalog', 'المنتجات والكتالوج'),
        ('inventory', 'المخازن والمخزون'),
        ('sales', 'المبيعات والطلبات'),
        ('purchases', 'المشتريات والتوريدات'),
        ('treasury', 'الخزينة والمالية'),
        ('areas', 'المناطق الجغرافية'),
        ('settings', 'الإعدادات العامة'),
    ]

    STATUS_CHOICES = [
        ('SUCCESS', 'ناجح'),
        ('FAILURE', 'فاشل'),
        ('WARNING', 'تحذير'),
    ]

    ACTION_LABELS = {
        # Auth & Security
        'LOGIN': {'ar': 'تسجيل دخول ناجح', 'en': 'Successful Login'},
        'LOGOUT': {'ar': 'تسجيل خروج', 'en': 'Logout'},
        'LOGIN_FAILED': {'ar': 'فشل تسجيل الدخول', 'en': 'Failed Login'},
        'login': {'ar': 'تسجيل دخول ناجح', 'en': 'Successful Login'},
        'logout': {'ar': 'تسجيل خروج', 'en': 'Logout'},
        'login_failed': {'ar': 'فشل تسجيل الدخول', 'en': 'Failed Login'},

        # Roles & Permissions
        'ROLE_CREATED': {'ar': 'إنشاء دور صلاحيات', 'en': 'Role Created'},
        'ROLE_UPDATED': {'ar': 'تعديل دور وصلاحيات', 'en': 'Role Updated'},
        'ROLE_DELETED': {'ar': 'حذف دور صلاحيات', 'en': 'Role Deleted'},
        'ROLE_DUPLICATED': {'ar': 'استنساخ دور صلاحيات', 'en': 'Role Duplicated'},
        'PERMISSIONS_SEEDED': {'ar': 'تهيئة وتحديث الصلاحيات', 'en': 'Permissions Seeded'},

        # Users
        'USER_CREATED': {'ar': 'إنشاء حساب مستخدم', 'en': 'User Created'},
        'USER_UPDATED': {'ar': 'تعديل بيانات المستخدم', 'en': 'User Updated'},
        'USER_ROLE_CHANGED': {'ar': 'تغيير الدور الوظيفي', 'en': 'User Role Changed'},
        'USER_STATUS_TOGGLED': {'ar': 'تفعيل/تعطيل حساب مستخدم', 'en': 'User Status Toggled'},
        'USER_PASSWORD_RESET': {'ar': 'إعادة تعيين كلمة المرور', 'en': 'Password Reset'},
        'USER_BYPASS_LOCATION_TOGGLED': {'ar': 'تعديل تجاوز التحقق من الموقع', 'en': 'Location Bypass Toggled'},

        # Contacts
        'CONTACT_CREATED': {'ar': 'إنشاء جهة اتصال', 'en': 'Contact Created'},
        'CONTACT_UPDATED': {'ar': 'تعديل بيانات جهة الاتصال', 'en': 'Contact Updated'},
        'CONTACT_DELETED': {'ar': 'حذف جهة اتصال', 'en': 'Contact Deleted'},
        'CONTACT_UDF_UPDATED': {'ar': 'تعديل الحقول المخصصة', 'en': 'Custom Fields Updated'},

        # Todos
        'TODO_CREATED': {'ar': 'إنشاء مهمة (Todo)', 'en': 'Todo Created'},
        'TODO_TOGGLED': {'ar': 'تغيير حالة مهمة (Todo)', 'en': 'Todo Toggled'},
        'TODO_DELETED': {'ar': 'حذف مهمة (Todo)', 'en': 'Todo Deleted'},

        # Timeline & Activities
        'ACTIVITY_LOGGED': {'ar': 'تسجيل نشاط جديد', 'en': 'Activity Logged'},

        # Visits & Templates
        'VISIT_CREATED': {'ar': 'إنشاء زيارة ميدانية', 'en': 'Visit Created'},
        'VISIT_APPROVED': {'ar': 'اعتماد زيارة ميدانية', 'en': 'Visit Approved'},
        'VISIT_REJECTED': {'ar': 'رفض زيارة ميدانية', 'en': 'Visit Rejected'},
        'VISIT_STARTED': {'ar': 'بدء الزيارة (Check-in)', 'en': 'Visit Started'},
        'VISIT_COMPLETED': {'ar': 'إنهاء الزيارة (Check-out)', 'en': 'Visit Completed'},
        'VISIT_ANSWERS_SAVED': {'ar': 'حفظ استبيان الزيارة', 'en': 'Visit Answers Saved'},
        'TEMPLATE_CREATED': {'ar': 'إنشاء قالب زيارة', 'en': 'Visit Template Created'},
        'TEMPLATE_UPDATED': {'ar': 'تعديل قالب زيارة', 'en': 'Visit Template Updated'},
        'TEMPLATE_DELETED': {'ar': 'حذف قالب زيارة', 'en': 'Visit Template Deleted'},

        # Products & Catalog
        'PRODUCT_CREATED': {'ar': 'إنشاء منتج جديد', 'en': 'Product Created'},
        'PRODUCT_UPDATED': {'ar': 'تعديل بيانات منتج', 'en': 'Product Updated'},

        # Inventory & Transfers
        'STOCK_ADJUSTMENT': {'ar': 'تسوية مخزنية', 'en': 'Stock Adjustment'},
        'STOCK_TRANSFER_REQUEST': {'ar': 'طلب تحويل مخزني', 'en': 'Stock Transfer Requested'},
        'STOCK_TRANSFER_APPROVED': {'ar': 'اعتماد تحويل مخزني', 'en': 'Stock Transfer Approved'},
        'STOCK_TRANSFER_REJECTED': {'ar': 'رفض تحويل مخزني', 'en': 'Stock Transfer Rejected'},

        # Sales
        'SALES_ORDER_CREATED': {'ar': 'إنشاء أمر بيع', 'en': 'Sales Order Created'},
        'SALES_ORDER_UPDATED': {'ar': 'تعديل أمر بيع', 'en': 'Sales Order Updated'},
        'SALES_ORDER_APPROVED': {'ar': 'اعتماد أمر بيع', 'en': 'Sales Order Approved'},
        'SALES_ORDER_REJECTED': {'ar': 'رفض أمر بيع', 'en': 'Sales Order Rejected'},
        'SALES_ORDER_INVOICED': {'ar': 'إصدار فاتورة أمر بيع', 'en': 'Sales Order Invoiced'},
        'SALES_ORDER_CANCELLED': {'ar': 'إلغاء أمر بيع', 'en': 'Sales Order Cancelled'},

        # Purchases
        'PURCHASE_ORDER_CREATED': {'ar': 'إنشاء أمر مشتريات', 'en': 'Purchase Order Created'},
        'PURCHASE_ORDER_UPDATED': {'ar': 'تعديل أمر مشتريات', 'en': 'Purchase Order Updated'},
        'PURCHASE_ORDER_APPROVED': {'ar': 'اعتماد أمر مشتريات', 'en': 'Purchase Order Approved'},
        'PURCHASE_ORDER_REJECTED': {'ar': 'رفض أمر مشتريات', 'en': 'Purchase Order Rejected'},
        'PURCHASE_ORDER_PICKED': {'ar': 'استلام بضاعة أمر مشتريات بالمخزن', 'en': 'Purchase Goods Received'},
        'PURCHASE_ORDER_SETTLED': {'ar': 'ترحيل أمر مشتريات للحسابات (الفوترة)', 'en': 'Purchase Order Invoiced'},
        'PURCHASE_ORDER_CANCELLED': {'ar': 'إلغاء أمر مشتريات', 'en': 'Purchase Order Cancelled'},
        'PURCHASE_ORDER_SPLIT': {'ar': 'تقسيم أمر مشتريات', 'en': 'Purchase Order Split'},
        'PURCHASE_RETURN_CREATED': {'ar': 'إنشاء مرتجع مشتريات', 'en': 'Purchase Return Created'},
        'PURCHASE_RETURN_APPROVED': {'ar': 'اعتماد مرتجع مشتريات', 'en': 'Purchase Return Approved'},
        'PURCHASE_RETURN_DELIVERED': {'ar': 'صرف مرتجع مشتريات من المخزن', 'en': 'Purchase Return Dispatched'},
        'PURCHASE_RETURN_SETTLED': {'ar': 'ترحيل مرتجع مشتريات للحسابات', 'en': 'Purchase Return Settled'},
        'PURCHASE_RETURN_CANCELLED': {'ar': 'إلغاء مرتجع مشتريات', 'en': 'Purchase Return Cancelled'},

        # Treasury & Finance
        'TREASURY_RECEIPT': {'ar': 'سند قبض / تحصيل نقدية', 'en': 'Treasury Receipt'},
        'TREASURY_PAYMENT': {'ar': 'سند صرف نقدية', 'en': 'Treasury Payment'},
        'VENDOR_PAYMENT_CREATED': {'ar': 'تسجيل سند صرف لمورد', 'en': 'Vendor Payment Created'},
        'COLLECTION_CREATED': {'ar': 'تسجيل سند تحصيل من عميل', 'en': 'Customer Collection Created'},
        'TREASURY_TRANSFER': {'ar': 'تحويل بين الخزن', 'en': 'Treasury Transfer'},

        # Areas
        'AREA_CREATED': {'ar': 'إنشاء منطقة جغرافية', 'en': 'Area Created'},
        'AREA_UPDATED': {'ar': 'تعديل منطقة جغرافية', 'en': 'Area Updated'},
        'AREA_DELETED': {'ar': 'حذف منطقة جغرافية', 'en': 'Area Deleted'},

        # Settings & Data Operations
        'SETTINGS_UPDATED': {'ar': 'تحديث إعدادات النظام', 'en': 'Settings Updated'},
        'BULK_IMPORT': {'ar': 'عملية استيراد جماعي', 'en': 'Bulk Import'},
        'BULK_EXPORT': {'ar': 'عملية تصدير بيانات', 'en': 'Bulk Export'},

        # Generic & Legacy Action Codes
        'create': {'ar': 'إنشاء سجل', 'en': 'Create'},
        'CREATE': {'ar': 'إنشاء سجل', 'en': 'Create'},
        'update': {'ar': 'تعديل سجل', 'en': 'Update'},
        'UPDATE': {'ar': 'تعديل سجل', 'en': 'Update'},
        'edit': {'ar': 'تعديل سجل', 'en': 'Edit'},
        'EDIT': {'ar': 'تعديل سجل', 'en': 'Edit'},
        'delete': {'ar': 'حذف سجل', 'en': 'Delete'},
        'DELETE': {'ar': 'حذف سجل', 'en': 'Delete'},
        'toggle': {'ar': 'تغيير حالة', 'en': 'Toggle Status'},
        'TOGGLE': {'ar': 'تغيير حالة', 'en': 'Toggle Status'},
        'approve': {'ar': 'اعتماد وموافقة', 'en': 'Approve'},
        'APPROVE': {'ar': 'اعتماد وموافقة', 'en': 'Approve'},
        'reject': {'ar': 'رفض', 'en': 'Reject'},
        'REJECT': {'ar': 'رفض', 'en': 'Reject'},
    }

    ACTION_CHOICES = [
        ('LOGIN', 'تسجيل دخول ناجح'),
        ('LOGOUT', 'تسجيل خروج'),
        ('LOGIN_FAILED', 'فشل تسجيل الدخول'),
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
        ('CONTACT_CREATED', 'إنشاء جهة اتصال جديدة'),
        ('CONTACT_UPDATED', 'تعديل بيانات جهة الاتصال'),
        ('CONTACT_DELETED', 'حذف جهة اتصال'),
        ('CONTACT_UDF_UPDATED', 'تعديل الحقول المخصصة (UDF)'),
        ('TODO_CREATED', 'إنشاء مهمة (Todo)'),
        ('TODO_TOGGLED', 'تغيير حالة مهمة (Todo)'),
        ('TODO_DELETED', 'حذف مهمة (Todo)'),
        ('ACTIVITY_LOGGED', 'تسجيل نشاط جهة اتصال'),
        ('VISIT_CREATED', 'إنشاء زيارة ميدانية'),
        ('VISIT_APPROVED', 'اعتماد زيارة ميدانية'),
        ('VISIT_REJECTED', 'رفض زيارة ميدانية'),
        ('VISIT_STARTED', 'بدء الزيارة (Check-in)'),
        ('VISIT_COMPLETED', 'إنهاء الزيارة (Check-out)'),
        ('VISIT_ANSWERS_SAVED', 'حفظ إجابات استبيان الزيارة'),
        ('TEMPLATE_CREATED', 'إنشاء قالب زيارة'),
        ('TEMPLATE_UPDATED', 'تعديل قالب زيارة'),
        ('TEMPLATE_DELETED', 'حذف قالب زيارة'),
        ('PRODUCT_CREATED', 'إنشاء منتج جديد'),
        ('PRODUCT_UPDATED', 'تعديل بيانات المنتج'),
        ('STOCK_ADJUSTMENT', 'تسوية مخزنية'),
        ('STOCK_TRANSFER_REQUEST', 'طلب تحويل مخزني'),
        ('STOCK_TRANSFER_APPROVED', 'اعتماد تحويل مخزني'),
        ('SALES_ORDER_CREATED', 'إنشاء أمر بيع'),
        ('SALES_ORDER_UPDATED', 'تعديل أمر بيع'),
        ('SALES_ORDER_APPROVED', 'اعتماد أمر بيع'),
        ('SALES_ORDER_REJECTED', 'رفض أمر بيع'),
        ('SALES_ORDER_INVOICED', 'إصدار فاتورة أمر بيع'),
        ('SALES_ORDER_CANCELLED', 'إلغاء أمر بيع'),
        ('PURCHASE_ORDER_CREATED', 'إنشاء أمر مشتريات'),
        ('PURCHASE_ORDER_UPDATED', 'تعديل أمر مشتريات'),
        ('PURCHASE_ORDER_APPROVED', 'اعتماد أمر مشتريات'),
        ('PURCHASE_ORDER_REJECTED', 'رفض أمر مشتريات'),
        ('PURCHASE_ORDER_PICKED', 'استلام بضاعة أمر مشتريات بالمخزن'),
        ('PURCHASE_ORDER_SETTLED', 'ترحيل أمر مشتريات للحسابات (الفوترة)'),
        ('PURCHASE_ORDER_CANCELLED', 'إلغاء أمر مشتريات'),
        ('PURCHASE_ORDER_SPLIT', 'تقسيم أمر مشتريات'),
        ('PURCHASE_RETURN_CREATED', 'إنشاء مرتجع مشتريات'),
        ('PURCHASE_RETURN_APPROVED', 'اعتماد مرتجع مشتريات'),
        ('PURCHASE_RETURN_DELIVERED', 'صرف مرتجع مشتريات من المخزن'),
        ('PURCHASE_RETURN_SETTLED', 'ترحيل مرتجع مشتريات للحسابات'),
        ('PURCHASE_RETURN_CANCELLED', 'إلغاء مرتجع مشتريات'),
        ('TREASURY_RECEIPT', 'سند قبض / تحصيل نقدية'),
        ('TREASURY_PAYMENT', 'سند صرف نقدية'),
        ('VENDOR_PAYMENT_CREATED', 'تسجيل سند صرف لمورد'),
        ('COLLECTION_CREATED', 'تسجيل سند تحصيل من عميل'),
        ('TREASURY_TRANSFER', 'تحويل بين الخزن'),
        ('AREA_CREATED', 'إنشاء منطقة جغرافية'),
        ('AREA_UPDATED', 'تعديل منطقة جغرافية'),
        ('AREA_DELETED', 'حذف منطقة جغرافية'),
        ('SETTINGS_UPDATED', 'تحديث إعدادات النظام'),
        ('BULK_IMPORT', 'عملية استيراد جماعي'),
        ('BULK_EXPORT', 'عملية تصدير بيانات'),
    ]

    actor = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='security_actions_performed', verbose_name="المسؤول المنفذ"
    )
    module = models.CharField(max_length=50, default='accounts', choices=MODULE_CHOICES, db_index=True, verbose_name="الموديول / النظام")
    action_type = models.CharField(max_length=100, db_index=True, verbose_name="نوع العملية")
    record_id = models.CharField(max_length=100, blank=True, db_index=True, verbose_name="معرف السجل")
    record_name = models.CharField(max_length=255, blank=True, verbose_name="اسم السجل / المرجع")
    target_user = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='security_events_targeted', verbose_name="المستخدم المستهدف"
    )
    target_role = models.ForeignKey(
        Role, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='audit_logs', verbose_name="الدور المستهدف"
    )
    description = models.TextField(verbose_name="تفاصيل العملية")
    previous_values = models.JSONField(null=True, blank=True, verbose_name="القيم السابقة")
    new_values = models.JSONField(null=True, blank=True, verbose_name="القيم الجديدة")
    status = models.CharField(max_length=20, default='SUCCESS', choices=STATUS_CHOICES, db_index=True, verbose_name="الحالة")
    reason = models.TextField(blank=True, verbose_name="السبب / الملاحظات")
    ip_address = models.GenericIPAddressField(null=True, blank=True, verbose_name="عنوان IP")
    user_agent = models.TextField(blank=True, verbose_name="متصفح العميل")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, verbose_name="تاريخ ووقت العملية")

    class Meta:
        verbose_name = "سجل تدقيق أمني وعملياتي"
        verbose_name_plural = "سجلات التدقيق الشامل"
        ordering = ['-created_at']

    def __str__(self):
        actor_name = self.actor.name or self.actor.username if self.actor else "النظام"
        return f"[{self.get_module_display()} - {self.action_type}] بواسطة {actor_name} في {self.created_at.strftime('%Y-%m-%d %H:%M')}"

    @property
    def action(self):
        return self.action_type

    @property
    def user(self):
        return self.actor

    @classmethod
    def get_label_for_action(cls, code, lang='ar'):
        """Classmethod returning human-readable label for any action code with clean fallback."""
        if not code:
            return 'عملية غير محددة' if lang == 'ar' else 'Unspecified Operation'
        c = str(code).strip()
        match = cls.ACTION_LABELS.get(c) or cls.ACTION_LABELS.get(c.upper()) or cls.ACTION_LABELS.get(c.lower())
        if match:
            return match.get(lang, match.get('ar', c))
        # Formatted fallback for unknown codes
        clean = c.replace('_', ' ').strip().title()
        return f"عملية ({clean})" if lang == 'ar' else clean

    def get_action_type_display(self, lang='ar'):
        """
        Instance method returning localized human-readable label.
        Ensures template tags {{ log.get_action_type_display }} always produce clear text.
        """
        return self.get_label_for_action(self.action_type, lang=lang)

    @property
    def action_type_display(self):
        return self.get_action_type_display('ar')

    @property
    def action_type_display_en(self):
        return self.get_action_type_display('en')


class UserSettings(models.Model):
    """
    Global configuration for user provisioning and representative resources.
    Controls automatic creation of default warehouses and treasuries for representatives.
    """
    auto_create_rep_warehouse = models.BooleanField(
        default=True,
        verbose_name="إنشاء مخزن تلقائياً لكل مندوب عند التسجيل"
    )
    auto_create_rep_treasury = models.BooleanField(
        default=True,
        verbose_name="إنشاء خزنة / عهدة نقدية تلقائياً لكل مندوب عند التسجيل"
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="تاريخ التحديث")

    class Meta:
        verbose_name = "إعدادات المستخدمين"
        verbose_name_plural = "إعدادات المستخدمين"

    def __str__(self):
        return "إعدادات المستخدمين"

    @classmethod
    def get_settings(cls):
        obj, _ = cls.objects.get_or_create(id=1)
        return obj




