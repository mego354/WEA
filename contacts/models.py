from decimal import Decimal
from django.db import models
from django.conf import settings
from master_data.models import Area


class Contact(models.Model):
    CONTACT_TYPES = [
        ('organization', 'مؤسسة'),
        ('person', 'شخص'),
    ]

    STATUS_CHOICES = [
        ('lead', 'Lead'),
        ('customer', 'Customer'),
        ('active', 'Active'),
        ('inactive', 'Inactive'),
    ]

    serial_num = models.PositiveIntegerField(unique=True, db_index=True, verbose_name="رقم المسلسل")
    name = models.CharField(max_length=255, db_index=True, verbose_name="الاسم / اسم المنشأة")
    contact_type = models.CharField(max_length=20, choices=CONTACT_TYPES, default='organization', verbose_name="نوع الحساب")
    
    # Business Relations
    is_supplier = models.BooleanField(default=False, db_index=True, verbose_name="مورد")
    is_customer = models.BooleanField(default=False, db_index=True, verbose_name="عميل")
    is_other = models.BooleanField(default=False, verbose_name="أخرى")

    # Customer Specific Fields (when is_customer=True)
    customer_category = models.CharField(max_length=10, blank=True, verbose_name="تصنيف العميل")
    specialty = models.CharField(max_length=150, blank=True, verbose_name="التخصص")
    account_type = models.CharField(max_length=100, blank=True, verbose_name="نوع الاكونت")

    mobile = models.CharField(max_length=30, blank=True, verbose_name="رقم الموبايل")
    phone = models.CharField(max_length=30, blank=True, verbose_name="الهاتف الأرضي")
    email = models.EmailField(blank=True, verbose_name="البريد الإلكتروني")
    website = models.CharField(max_length=255, blank=True, verbose_name="الموقع الإلكتروني")

    area = models.ForeignKey(Area, on_delete=models.SET_NULL, null=True, blank=True, related_name="contacts", verbose_name="المنطقة الجغرافية")
    tax_id = models.CharField(max_length=100, blank=True, verbose_name="المعرف الضريبي")
    tax_card = models.CharField(max_length=100, blank=True, verbose_name="البطاقة الضريبية")
    commercial_registry = models.CharField(max_length=100, blank=True, verbose_name="السجل التجاري")
    code = models.CharField(max_length=100, blank=True, verbose_name="الكود")

    # Other Information Fields
    contact_person = models.CharField(max_length=150, blank=True, verbose_name="اسم المسؤول")
    visit_timing = models.CharField(max_length=10, blank=True, choices=[('AM', 'AM'), ('PM', 'PM')], verbose_name="AM/PM")
    job_title = models.CharField(max_length=150, blank=True, verbose_name="المسمي الوظيفي")
    is_kol = models.BooleanField(default=False, verbose_name="KOL")

    credit_limit = models.DecimalField(max_digits=14, decimal_places=2, default=0.00, verbose_name="حد الائتمان (ج.م)")
    credit_period_days = models.PositiveIntegerField(default=30, verbose_name="فترة الائتمان (أيام)")

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='lead', verbose_name="الحالة")
    notes = models.TextField(blank=True, verbose_name="ملاحظات")
    custom_values = models.JSONField(default=dict, blank=True, verbose_name="القيم المخصصة")

    parent_org = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='branches', verbose_name="المؤسسة التابعة لها")
    assigned_team = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="assigned_contacts", verbose_name="المسئولين")

    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_contacts", verbose_name="المنشئ")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="تاريخ التحديث")

    class Meta:
        verbose_name = "جهة اتصال"
        verbose_name_plural = "جهات الاتصال"
        ordering = ['-serial_num']

    def __str__(self):
        return self.name

    def __init__(self, *args, **kwargs):
        temp_lat = kwargs.pop('latitude', None)
        temp_lng = kwargs.pop('longitude', None)
        super().__init__(*args, **kwargs)
        if temp_lat is not None:
            self._temp_lat = temp_lat
        if temp_lng is not None:
            self._temp_lng = temp_lng

    def save(self, *args, **kwargs):
        if not self.serial_num:
            max_serial = Contact.objects.aggregate(models.Max('serial_num'))['serial_num__max'] or 1000
            self.serial_num = max_serial + 1
        super().save(*args, **kwargs)
        if hasattr(self, '_temp_lat') or hasattr(self, '_temp_lng'):
            lat = getattr(self, '_temp_lat', None)
            lng = getattr(self, '_temp_lng', None)
            if lat is not None or lng is not None:
                self.set_location(lat, lng)
            if hasattr(self, '_temp_lat'):
                delattr(self, '_temp_lat')
            if hasattr(self, '_temp_lng'):
                delattr(self, '_temp_lng')

        if self.is_customer:
            try:
                from sales.models import CustomerAccount
                CustomerAccount.get_or_create_for_customer(self)
            except Exception:
                pass
        if self.is_supplier:
            try:
                from treasury.models import VendorAccount
                VendorAccount.get_or_create_for_supplier(self)
            except Exception:
                pass

    @property
    def formatted_number(self):
        return f"#{self.serial_num}"

    @property
    def display_tag(self):
        return self.name

    @property
    def initials(self):
        clean_name = self.name.strip().replace('(', '').replace(')', '').replace('[', '').replace(']', '')
        parts = clean_name.split()
        if len(parts) >= 2:
            return f"{parts[0][0]}{parts[1][0]}"
        elif parts:
            return parts[0][:2]
        return "–"

    @property
    def status_label(self):
        if self.status in ['customer', 'active']:
            return 'Customer'
        elif self.status == 'lead':
            return 'Lead'
        elif self.status == 'inactive':
            return 'Inactive'
        return self.status.capitalize()

    @property
    def relation_display(self):
        rels = []
        if self.is_customer:
            rels.append("عميل")
        if self.is_supplier:
            rels.append("مورد")
        if self.is_other:
            rels.append("أخرى")
        return " / ".join(rels) if rels else "غير محدد"

    @property
    def main_address(self):
        # Leverage prefetched addresses if available to prevent N+1 query explosion
        if hasattr(self, '_prefetched_objects_cache') and 'addresses' in self._prefetched_objects_cache:
            for a in self.addresses.all():
                if a.is_main:
                    return a
            addrs = list(self.addresses.all())
            return addrs[0] if addrs else None
        return self.addresses.filter(is_main=True).first() or self.addresses.first()

    @property
    def latitude(self):
        if hasattr(self, '_temp_lat'):
            return self._temp_lat
        addr = self.main_address
        return addr.latitude if addr else None

    @latitude.setter
    def latitude(self, value):
        if self.pk:
            self.set_location(value, self.longitude or 0)
        else:
            self._temp_lat = value

    @property
    def longitude(self):
        if hasattr(self, '_temp_lng'):
            return self._temp_lng
        addr = self.main_address
        return addr.longitude if addr else None

    @longitude.setter
    def longitude(self, value):
        if self.pk:
            self.set_location(self.latitude or 0, value)
        else:
            self._temp_lng = value

    @property
    def has_saved_location(self):
        return bool(self.latitude is not None and self.longitude is not None)

    def set_location(self, lat, lng):
        """Save or update the contact's GPS coordinates on its main address."""
        addr = self.main_address
        if not addr:
            addr = ContactAddress.objects.create(
                contact=self,
                title="العنوان الرئيسي",
                is_main=True,
                area=self.area,
                latitude=lat,
                longitude=lng
            )
        else:
            addr.latitude = lat
            addr.longitude = lng
            addr.save()
        return addr

    @property
    def total_outstanding_balance(self):
        """Sum of unpaid balances across active sales orders for this customer."""
        if not self.is_customer or not self.pk:
            return Decimal('0.00')
        active_orders = self.sales_orders.exclude(status='cancelled')
        return sum((order.outstanding_balance for order in active_orders), Decimal('0.00'))

    @property
    def is_credit_limit_exceeded(self):
        """Check if customer's outstanding balance exceeds their approved credit limit."""
        if not self.is_customer or not self.credit_limit:
            return False
        return self.total_outstanding_balance > self.credit_limit



class ContactAddress(models.Model):
    contact = models.ForeignKey(Contact, on_delete=models.CASCADE, related_name="addresses", verbose_name="جهة الاتصال")
    title = models.CharField(max_length=150, blank=True, default="", verbose_name="اسم العنوان")
    is_main = models.BooleanField(default=True, verbose_name="العنوان الرئيسي")
    street_address = models.TextField(blank=True, verbose_name="العنوان")
    area = models.ForeignKey(Area, on_delete=models.SET_NULL, null=True, blank=True, related_name="addresses", verbose_name="المنطقة")
    sub_area = models.CharField(max_length=150, blank=True, verbose_name="المنطقة الفرعية")
    latitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True, verbose_name="خط العرض")
    longitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True, verbose_name="خط الطول")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "عنوان جهة الاتصال"
        verbose_name_plural = "عناوين جهات الاتصال"

    def __str__(self):
        return f"{self.title} - {self.contact.name}"


class ContactComment(models.Model):
    contact = models.ForeignKey(Contact, on_delete=models.CASCADE, related_name="comments", verbose_name="جهة الاتصال")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="contact_comments", verbose_name="الكاتب")
    text = models.TextField(verbose_name="نص التعليق")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء")

    class Meta:
        verbose_name = "تعليق جهة الاتصال"
        verbose_name_plural = "تعليقات جهات الاتصال"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.contact.name} - {self.author} ({self.created_at})"


class ContactAttachment(models.Model):
    contact = models.ForeignKey(Contact, on_delete=models.CASCADE, related_name="attachments", verbose_name="جهة الاتصال")
    file = models.FileField(upload_to="contacts/attachments/", verbose_name="الملف")
    filename = models.CharField(max_length=255, blank=True, verbose_name="اسم الملف")
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="تم الرفع بواسطة")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الرفع")

    class Meta:
        verbose_name = "مرفق جهة الاتصال"
        verbose_name_plural = "مرفقات جهة الاتصال"
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        if not self.filename and self.file:
            self.filename = self.file.name.split('/')[-1]
        super().save(*args, **kwargs)


class ContactTodo(models.Model):
    contact = models.ForeignKey(Contact, on_delete=models.CASCADE, related_name="todos", verbose_name="جهة الاتصال")
    title = models.CharField(max_length=255, verbose_name="المهمة")
    is_completed = models.BooleanField(default=False, verbose_name="مكتملة")
    due_date = models.DateField(null=True, blank=True, verbose_name="تاريخ الاستحقاق")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="أنشئ بواسطة")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء")

    class Meta:
        verbose_name = "Todo"
        verbose_name_plural = "Todos"
        ordering = ['is_completed', '-created_at']

    def __str__(self):
        return f"{self.title} ({'مكتمل' if self.is_completed else 'معلق'})"


class ContactActivity(models.Model):
    ACTIVITY_TYPES = [
        ('visit', 'زيارة'),
        ('call', 'مكالمة'),
        ('agreement', 'اتفاقية'),
        ('todo', 'مهمة'),
        ('update', 'تحديث بيانات'),
        ('order', 'طلب بيع'),
        ('collection', 'تحصيل'),
    ]
    contact = models.ForeignKey(Contact, on_delete=models.CASCADE, related_name="activities", verbose_name="جهة الاتصال")
    activity_type = models.CharField(max_length=20, choices=ACTIVITY_TYPES, default='visit', verbose_name="نوع النشاط")
    title = models.CharField(max_length=255, verbose_name="العنوان")
    start_time = models.DateTimeField(null=True, blank=True, verbose_name="بدأ في")
    end_time = models.DateTimeField(null=True, blank=True, verbose_name="انتهى في")
    notes = models.TextField(blank=True, verbose_name="ملاحظات")
    performed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="المسؤول")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء")

    class Meta:
        verbose_name = "نشاط"
        verbose_name_plural = "الأنشطة"
        ordering = ['-created_at']
