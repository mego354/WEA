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

    class Meta:
        verbose_name = "إعدادات الموقع"
        verbose_name_plural = "إعدادات الموقع"

    def __str__(self):
        return f"Location Settings (Tolerance: {self.tolerance}m)"

    @classmethod
    def get_settings(cls):
        obj, _ = cls.objects.get_or_create(id=1)
        return obj

