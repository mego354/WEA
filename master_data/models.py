from django.db import models


class Area(models.Model):
    AREA_TYPES = [
        ('governorate', 'محافظة'),
        ('subarea', 'منطقة / مركز'),
    ]

    code = models.CharField(max_length=20, unique=True, verbose_name="كود المنطقة")
    name = models.CharField(max_length=150, verbose_name="اسم المنطقة")
    area_type = models.CharField(max_length=20, choices=AREA_TYPES, default='subarea', verbose_name="نوع المنطقة")
    parent = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='subareas', verbose_name="المنطقة الأب / المحافظة")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء")

    class Meta:
        verbose_name = "منطقة جغرافية"
        verbose_name_plural = "المناطق الجغرافية"
        ordering = ['code']

    def __str__(self):
        if self.parent:
            return f"{self.name} ({self.parent.name})"
        return self.name


class CompanyProfile(models.Model):
    company_name = models.CharField(max_length=200, default="WEA Pharma", verbose_name="اسم الشركة")
    logo = models.ImageField(upload_to="branding/", null=True, blank=True, verbose_name="شعار الشركة")
    commercial_registry = models.CharField(max_length=100, default="سجل تجاري 184791", verbose_name="السجل التجاري")
    tax_id = models.CharField(max_length=100, default="بطاقة ضريبية 978-339-684", verbose_name="البطاقة الضريبية")
    phone = models.CharField(max_length=100, default="01111787179 - 01024070412", verbose_name="أرقام الهاتف")
    address = models.TextField(default="173 ز - البوابة الأولى- حدائق الأهرام", verbose_name="العنوان الرئيسي")
    email = models.EmailField(default="wea.pharm2020@gmail.com", verbose_name="البريد الإلكتروني الرسمي")
    currency = models.CharField(max_length=10, default="EGP", verbose_name="العملة الرسمية")
    
    # Global Inventory & Purchasing Policies
    use_batch_number = models.BooleanField(default=True, verbose_name="تفعيل أرقام التشغيل (Batches)")
    use_expiry_date = models.BooleanField(default=True, verbose_name="تفعيل تواريخ الصلاحية (Expiry)")
    is_batch_mandatory = models.BooleanField(default=False, verbose_name="رقم التشغيل إلزامي")
    is_expiry_mandatory = models.BooleanField(default=False, verbose_name="تاريخ الصلاحية إلزامي")

    class Meta:
        verbose_name = "بيانات وإعدادات الشركة"
        verbose_name_plural = "بيانات وإعدادات الشركة"

    def __str__(self):
        return self.company_name

    @classmethod
    def get_settings(cls):
        profile, _ = cls.objects.get_or_create(id=1)
        return profile


class LocationSettings(models.Model):
    tolerance = models.PositiveIntegerField(default=300, verbose_name="سماحية الموقع (متر)")
    max_verified_accuracy = models.PositiveIntegerField(default=50, verbose_name="الحد الأقصى للدقة المحققة (متر)")
    max_verified_warn_accuracy = models.PositiveIntegerField(default=100, verbose_name="الحد الأقصى للدقة المحققة مع التحذير (متر)")
    auto_start_location_tracking_service = models.BooleanField(default=True, verbose_name="تشغيل تلقائي لمتابعة الموقع")
    auto_set_customer_location_in_visit = models.BooleanField(default=True, verbose_name="حفظ موقع العميل بشكل تلقائي مع أول زيارة")
    
    # Workflow verification settings matching reference ERP
    verify_visits = models.BooleanField(default=True, verbose_name="التحقق من موقع الزيارات")
    verify_sales_orders = models.BooleanField(default=False, verbose_name="التحقق من موقع أوامر البيع")
    verify_sales_returns = models.BooleanField(default=False, verbose_name="التحقق من موقع المرتجعات")
    verify_collections = models.BooleanField(default=False, verbose_name="التحقق من موقع التحصيلات")
    verify_purchase_orders = models.BooleanField(default=False, verbose_name="التحقق من موقع أوامر الشراء")
    verify_purchase_returns = models.BooleanField(default=False, verbose_name="التحقق من موقع أوامر إرجاع الشراء")

    # User creation and approval controls
    allow_all_users_to_create_visits = models.BooleanField(
        default=False,
        verbose_name="السماح لجميع المستخدمين بإنشاء الزيارات (مخططة أو غير مخططة)"
    )
    require_manager_approval_for_visits = models.BooleanField(
        default=True,
        verbose_name="طلب موافقة المدير للزيارات لغير المدراء"
    )
    allow_all_users_to_create_agreements = models.BooleanField(
        default=False,
        verbose_name="السماح لجميع المستخدمين بإنشاء الاتفاقيات"
    )
    require_manager_approval_for_agreements = models.BooleanField(
        default=True,
        verbose_name="طلب موافقة المدير للاتفاقيات لغير المدراء"
    )

    # Configurable Product Suggestions (Requirement)
    enable_product_suggestions = models.BooleanField(
        default=True,
        verbose_name="تفعيل اقتراح المنتجات في الزيارات"
    )
    suggested_products = models.ManyToManyField(
        'catalog.Product',
        blank=True,
        related_name='location_suggested_products',
        limit_choices_to={'is_active': True, 'sellable': True},
        verbose_name="المنتجات المقترحة للزيارات"
    )

    def get_eligible_suggested_products(self):
        """Returns suggested products strictly filtered to active, sellable products."""
        if not self.enable_product_suggestions:
            from catalog.models import Product
            return Product.objects.none()
        return self.suggested_products.filter(is_active=True, sellable=True).order_by('name')

    class Meta:
        verbose_name = "إعدادات الموقع والزيارات"
        verbose_name_plural = "إعدادات الموقع والزيارات"

    def __str__(self):
        return f"Location Settings (Tolerance: {self.tolerance}m)"

    @classmethod
    def get_settings(cls):
        obj, _ = cls.objects.get_or_create(id=1)
        return obj


class ExpenseType(models.Model):
    EXPENSE_CATEGORIES = [
        ('general', 'مصروفات عامة'),
        ('visit', 'مصروفات للزيارات فقط'),
    ]

    name = models.CharField(max_length=150, verbose_name="الاسم بالعربية")
    name_en = models.CharField(max_length=150, blank=True, verbose_name="الاسم بالإنجليزية")
    category = models.CharField(max_length=20, choices=EXPENSE_CATEGORIES, default='general', verbose_name="نوع المصروف")
    unit = models.CharField(max_length=50, blank=True, default='الوحدة', verbose_name="الوحدة")
    is_active = models.BooleanField(default=True, verbose_name="مفعل")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء")

    class Meta:
        verbose_name = "نوع مصروف"
        verbose_name_plural = "انواع المصروفات"
        ordering = ['id']

    def __str__(self):
        if self.name_en:
            return f"{self.name} {self.name_en}"
        return self.name


class TicketType(models.Model):
    name = models.CharField(max_length=100, verbose_name="نوع المهمة")
    is_default = models.BooleanField(default=False, verbose_name="افتراضي")
    is_active = models.BooleanField(default=True, verbose_name="مفعل")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء")

    class Meta:
        verbose_name = "نوع مهمة"
        verbose_name_plural = "انواع المهام"
        ordering = ['-is_default', 'id']

    def __str__(self):
        return self.name


class ApprovalRequestType(models.Model):
    name = models.CharField(max_length=100, verbose_name="نوع الموافقة")
    is_default = models.BooleanField(default=False, verbose_name="افتراضي")
    is_active = models.BooleanField(default=True, verbose_name="مفعل")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء")

    class Meta:
        verbose_name = "نوع موافقة"
        verbose_name_plural = "انواع الموافقات"
        ordering = ['-is_default', 'id']

    def __str__(self):
        return self.name


class AgreementType(models.Model):
    name = models.CharField(max_length=100, verbose_name="نوع الاتفاقية")
    is_active = models.BooleanField(default=True, verbose_name="مفعل")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء")

    class Meta:
        verbose_name = "نوع اتفاقية"
        verbose_name_plural = "انواع الاتفاقيات"
        ordering = ['id']

    def __str__(self):
        return self.name


class SalesSettings(models.Model):
    TAX_MODES = [
        ('optional', 'اختياري'),
        ('mandatory', 'إلزامي'),
        ('exempt', 'معفى'),
    ]

    PACKAGING_UNITS = [
        ('box', 'علبة'),
        ('strip', 'شريط'),
        ('piece', 'قطعة'),
        ('carton', 'كرتونة'),
    ]

    require_verification_manager = models.BooleanField(default=False, verbose_name="مسؤول التحقيق مطلوب في أمر البيع")
    auto_invoice_on_dispatch = models.BooleanField(default=True, verbose_name="عمل فاتورة بشكل تلقائي عند الاخراج من المخزن")
    auto_invoice_on_return = models.BooleanField(default=True, verbose_name="عمل فاتورة بشكل تلقائي عند الارجاع الى المخزن")
    collect_payment_on_invoicing = models.BooleanField(default=True, verbose_name="تحصيل الدفعة عند فوترة الطلب")
    auto_link_accounting_on_collection = models.BooleanField(default=True, verbose_name="ربط بالحسابات تلقائي عند إنشاء التحصيل")
    use_receipt_books = models.BooleanField(default=False, verbose_name="استخدم دفاتر إيصالات التحصيلات")
    auto_close_cash_collection = models.BooleanField(default=True, verbose_name="غلق تلقائي لطلب التحصيل النقدي")
    auto_close_collection_on_full_payment = models.BooleanField(default=True, verbose_name="غلق تلقائي لطلب التحصيل عند السداد كاملا")

    tax_mode = models.CharField(max_length=20, choices=TAX_MODES, default='optional', verbose_name="نمط الضريبة")
    default_packaging_unit = models.CharField(max_length=20, choices=PACKAGING_UNITS, default='box', verbose_name="حجم التعبئة الافتراضي")
    print_template = models.CharField(max_length=100, default='standard', verbose_name="قالب الطباعة")

    # User creation and approval controls
    allow_all_users_to_create = models.BooleanField(
        default=False,
        verbose_name="السماح لجميع المستخدمين بإنشاء أوامر البيع"
    )
    require_manager_approval = models.BooleanField(
        default=True,
        verbose_name="طلب موافقة المدير إذا لم يكن المنشئ مديراً أو أعلى"
    )

    class Meta:
        verbose_name = "إعدادات المبيعات"
        verbose_name_plural = "إعدادات المبيعات"

    def __str__(self):
        return "إعدادات المبيعات"

    @classmethod
    def get_settings(cls):
        obj, _ = cls.objects.get_or_create(id=1)
        return obj


class PurchaseSettings(models.Model):
    TAX_MODES = [
        ('optional', 'اختياري'),
        ('mandatory', 'إلزامي'),
        ('exempt', 'معفى'),
    ]

    PACKAGING_UNITS = [
        ('piece', 'قطعة'),
        ('box', 'علبة'),
        ('carton', 'كرتونة'),
    ]

    auto_invoice_on_dispatch = models.BooleanField(default=True, verbose_name="عمل فاتورة بشكل تلقائى عند الاخراج من المخزن")
    auto_invoice_on_return = models.BooleanField(default=True, verbose_name="عمل فاتورة بشكل تلقائى عند الارجاع الى المخزن")
    collect_payment_on_invoicing = models.BooleanField(default=False, verbose_name="تحصيل الدفعة عند فوترة الطلب")
    auto_link_accounting_on_payment = models.BooleanField(default=True, verbose_name="ربط بالحسابات تلقائى عند إنشاء المدفوعات")
    auto_close_cash_payment = models.BooleanField(default=True, verbose_name="إغلاق تلقائي لطلبات الدفع النقدي")
    auto_close_payment_on_full_settlement = models.BooleanField(default=True, verbose_name="إغلاق تلقائي لطلبات الدفع عند السداد كاملا")

    tax_mode = models.CharField(max_length=20, choices=TAX_MODES, default='optional', verbose_name="نمط الضريبة")
    default_packaging_unit = models.CharField(max_length=20, choices=PACKAGING_UNITS, default='piece', verbose_name="حجم التعبئة الافتراضي")

    # User creation and approval controls
    allow_all_users_to_create = models.BooleanField(
        default=False,
        verbose_name="السماح لجميع المستخدمين بإنشاء أوامر الشراء"
    )
    require_manager_approval = models.BooleanField(
        default=True,
        verbose_name="طلب موافقة المدير إذا لم يكن المنشئ مديراً أو أعلى"
    )

    class Meta:
        verbose_name = "إعدادات المشتريات"
        verbose_name_plural = "إعدادات المشتريات"

    def __str__(self):
        return "إعدادات المشتريات"

    @classmethod
    def get_settings(cls):
        obj, _ = cls.objects.get_or_create(id=1)
        return obj


class ContactFieldSetting(models.Model):
    SECTIONS = [
        ('header', 'Info card header'),
        ('subheader', 'Info card subheader'),
        ('basic', 'المعلومات الأساسية'),
    ]

    field_key = models.CharField(max_length=50, unique=True, verbose_name="مفتاح الحقل")
    display_name = models.CharField(max_length=100, verbose_name="اسم الحقل")
    section = models.CharField(max_length=50, choices=SECTIONS, verbose_name="القسم")
    is_locked = models.BooleanField(default=False, verbose_name="مغلق")
    is_required = models.BooleanField(default=False, verbose_name="مطلوب")
    is_builtin = models.BooleanField(default=True, verbose_name="مدمج")
    is_core = models.BooleanField(default=False, verbose_name="اساسي")
    is_filterable = models.BooleanField(default=False, verbose_name="قابلة للتصفية")
    order = models.PositiveIntegerField(default=0, verbose_name="الترتيب")

    class Meta:
        verbose_name = "تخصيص حقل جهات الاتصال"
        verbose_name_plural = "تخصيص حقول جهات الاتصال"
        ordering = ['section', 'order']

    def __str__(self):
        return f"{self.display_name} ({self.field_key})"


class DataSyncConfig(models.Model):
    SYNC_TYPES = [
        ('contacts', 'إستيراد جهات الاتصال'),
        ('products', 'إستيراد المنتجات'),
        ('areas', 'مزامنة المناطق'),
    ]

    sync_type = models.CharField(max_length=50, unique=True, choices=SYNC_TYPES, verbose_name="نوع المزامنة")
    title = models.CharField(max_length=100, verbose_name="العنوان")
    google_sheet_url = models.URLField(blank=True, verbose_name="رابط جدول جوجل")
    service_account_email = models.CharField(max_length=200, default='gsheets-sync@mandoby-app.iam.gserviceaccount.com', verbose_name="البريد الإلكتروني للخدمة")
    last_synced_at = models.DateTimeField(null=True, blank=True, verbose_name="آخر مزامنة")
    status = models.CharField(max_length=50, default='idle', verbose_name="الحالة")

    class Meta:
        verbose_name = "إعداد مزامنة بيانات"
        verbose_name_plural = "إعدادات مزامنة البيانات"

    def __str__(self):
        return self.title


