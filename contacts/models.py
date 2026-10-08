from django.db import models
from django.conf import settings
from master_data.models import Area


class Contact(models.Model):
    CONTACT_TYPES = [
        ('company', 'شركة / منشأة'),
        ('individual', 'فرد'),
    ]

    STATUS_CHOICES = [
        ('lead', 'محتمل (Lead)'),
        ('active', 'نشط (Active)'),
        ('inactive', 'غير نشط (Inactive)'),
    ]

    serial_num = models.PositiveIntegerField(unique=True, db_index=True, verbose_name="رقم المسلسل")
    name = models.CharField(max_length=255, db_index=True, verbose_name="الاسم / اسم المنشأة")
    contact_type = models.CharField(max_length=20, choices=CONTACT_TYPES, default='company', verbose_name="نوع الحساب")
    
    # Business Relations
    is_supplier = models.BooleanField(default=False, db_index=True, verbose_name="مورد")
    is_customer = models.BooleanField(default=False, db_index=True, verbose_name="عميل")

    mobile = models.CharField(max_length=30, blank=True, verbose_name="رقم الموبايل")
    phone = models.CharField(max_length=30, blank=True, verbose_name="الهاتف الأرضي")
    email = models.EmailField(blank=True, verbose_name="البريد الإلكتروني")

    area = models.ForeignKey(Area, on_delete=models.SET_NULL, null=True, blank=True, related_name="contacts", verbose_name="المنطقة الجغرافية")
    tax_card = models.CharField(max_length=100, blank=True, verbose_name="البطاقة الضريبية")
    commercial_registry = models.CharField(max_length=100, blank=True, verbose_name="السجل التجاري")

    credit_limit = models.DecimalField(max_digits=14, decimal_places=2, default=0.00, verbose_name="حد الائتمان (ج.م)")
    credit_period_days = models.PositiveIntegerField(default=30, verbose_name="فترة الائتمان (أيام)")

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active', verbose_name="الحالة")
    notes = models.TextField(blank=True, verbose_name="ملاحظات")

    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_contacts", verbose_name="المنشئ")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="تاريخ التحديث")

    class Meta:
        verbose_name = "جهة اتصال"
        verbose_name_plural = "جهات الاتصال"
        ordering = ['-serial_num']

    def __str__(self):
        return f"{self.name} (#{self.serial_num})"

    def save(self, *args, **kwargs):
        if not self.serial_num:
            max_serial = Contact.objects.aggregate(models.Max('serial_num'))['serial_num__max'] or 1000
            self.serial_num = max_serial + 1
        super().save(*args, **kwargs)

    @property
    def formatted_number(self):
        return f"#{self.serial_num}"

    @property
    def relation_display(self):
        rels = []
        if self.is_supplier:
            rels.append("مورد")
        if self.is_customer:
            rels.append("عميل")
        return " / ".join(rels) if rels else "غير محدد"


class ContactAddress(models.Model):
    contact = models.ForeignKey(Contact, on_delete=models.CASCADE, related_name="addresses", verbose_name="جهة الاتصال")
    title = models.CharField(max_length=100, default="العنوان الرئيسي", verbose_name="وصف العنوان")
    is_main = models.BooleanField(default=True, verbose_name="العنوان الرئيسي")
    street_address = models.TextField(verbose_name="العنوان التفصيلي")
    area = models.ForeignKey(Area, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="المنطقة")
    latitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True, verbose_name="خط العرض")
    longitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True, verbose_name="خط الطول")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "عنوان جهة الاتصال"
        verbose_name_plural = "عناوين جهات الاتصال"

    def __str__(self):
        return f"{self.title} - {self.contact.name}"
