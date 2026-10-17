from django.db import models
from django.conf import settings
from django.utils import timezone


class AgreementType(models.Model):
    name = models.CharField(max_length=100, unique=True, verbose_name="نوع الاتفاقية")
    display_name_ar = models.CharField(max_length=150, blank=True, verbose_name="الاسم بالعربية")
    is_active = models.BooleanField(default=True, verbose_name="نشط")

    class Meta:
        verbose_name = "نوع اتفاقية"
        verbose_name_plural = "أنواع الاتفاقيات"
        ordering = ['name']

    def __str__(self):
        return self.display_name_ar or self.name


class Agreement(models.Model):
    STATUS_CHOICES = [
        ('new', 'New'),
        ('approved', 'Approved'),
        ('disapproved', 'Disapproved'),
        ('done', 'Done'),
    ]

    serial_num = models.IntegerField(unique=True, db_index=True, verbose_name="الرقم التعريفي")
    title = models.CharField(max_length=255, verbose_name="العنوان")
    description = models.TextField(blank=True, default='', verbose_name="الوصف والشروط")
    type = models.ForeignKey(AgreementType, on_delete=models.PROTECT, related_name='agreements', verbose_name="النوع")
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00, verbose_name="المبلغ")
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='new', db_index=True, verbose_name="الحالة")
    customer = models.ForeignKey('contacts.Contact', on_delete=models.CASCADE, related_name='agreements', verbose_name="العميل")
    date = models.DateField(default=timezone.now, db_index=True, verbose_name="التاريخ")
    
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='agreements_created', verbose_name="المنشئ")
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='agreements_updated', verbose_name="محدث بواسطة")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="تاريخ التحديث")

    class Meta:
        verbose_name = "اتفاقية"
        verbose_name_plural = "الاتفاقيات"
        ordering = ['-serial_num']

    def __str__(self):
        return f"#{self.serial_num} - {self.title}"

    def save(self, *args, **kwargs):
        if not self.serial_num:
            max_serial = Agreement.objects.aggregate(models.Max('serial_num'))['serial_num__max']
            self.serial_num = (max_serial or 222) + 1
        super().save(*args, **kwargs)

    @property
    def status_display_ar(self):
        mapping = {
            'new': 'جديد',
            'approved': 'معتمد',
            'disapproved': 'مرفوض',
            'done': 'منجز',
        }
        return mapping.get(self.status, self.status)

    @property
    def status_badge_class(self):
        mapping = {
            'new': 'bg-sky-100 text-sky-800 border-sky-300',
            'approved': 'bg-emerald-100 text-emerald-800 border-emerald-300',
            'disapproved': 'bg-rose-100 text-rose-800 border-rose-300',
            'done': 'bg-slate-100 text-slate-800 border-slate-300',
        }
        return mapping.get(self.status, 'bg-gray-100 text-gray-800 border-gray-300')


class VisitTemplate(models.Model):
    name = models.CharField(max_length=100, unique=True, verbose_name="اسم القالب الداخلي")
    display_name_ar = models.CharField(max_length=150, verbose_name="الاسم بالعربية")
    display_name_en = models.CharField(max_length=150, blank=True, verbose_name="الاسم بالإنجليزية")
    active = models.BooleanField(default=True, verbose_name="نشط")
    restrict_account_types = models.JSONField(default=list, blank=True, verbose_name="نوع الحساب المستهدف")
    questionnaire = models.JSONField(default=dict, blank=True, verbose_name="أسئلة الاستبيان")

    class Meta:
        verbose_name = "قالب زيارة"
        verbose_name_plural = "قوالب الزيارات"
        ordering = ['display_name_ar']

    def __str__(self):
        return self.display_name_ar or self.name


class PlannedVisitDay(models.Model):
    STATUS_CHOICES = [
        ('new', 'New'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ]

    assignee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='planned_visit_days', verbose_name="المسئول")
    date = models.DateField(db_index=True, verbose_name="تاريخ اليوم")
    status = models.CharField(max_length=30, default='new', choices=STATUS_CHOICES, verbose_name="حالة اليوم")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="أنشئ بواسطة")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "خطة يوم زيارات"
        verbose_name_plural = "خطط أيام الزيارات"
        unique_together = ('assignee', 'date')
        ordering = ['date']

    def __str__(self):
        return f"{self.assignee} - {self.date}"


class Visit(models.Model):
    STATUS_CHOICES = [
        ('planned', 'Planned'),
        ('started', 'Started'),
        ('finished', 'Finished'),
    ]

    APPROVAL_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('disapproved', 'Disapproved'),
    ]

    serial_num = models.IntegerField(unique=True, db_index=True, verbose_name="رقم الزيارة")
    contact = models.ForeignKey('contacts.Contact', on_delete=models.CASCADE, related_name='visits', verbose_name="جهة الاتصال")
    template = models.ForeignKey(VisitTemplate, on_delete=models.SET_NULL, null=True, blank=True, related_name='visits', verbose_name="قالب الزيارة")
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='visits_conducted', verbose_name="المسؤول")
    is_planned = models.BooleanField(default=False, db_index=True, verbose_name="مخططة")
    
    date = models.DateField(default=timezone.now, db_index=True, verbose_name="تاريخ الزيارة")
    visit_time = models.DateTimeField(default=timezone.now, verbose_name="وقت الزيارة")
    started_at = models.DateTimeField(null=True, blank=True, verbose_name="بدأ في")
    ended_at = models.DateTimeField(null=True, blank=True, verbose_name="انتهى في")
    duration = models.IntegerField(default=0, help_text="المدة بالثواني أو ميلي ثانية", verbose_name="المدة")
    
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='finished', db_index=True, verbose_name="الحالة")
    approval_status = models.CharField(max_length=30, choices=APPROVAL_CHOICES, default='pending', db_index=True, verbose_name="حالة الاعتماد")
    
    is_successful = models.BooleanField(default=True, verbose_name="زيارة ناجحة")
    doubled = models.BooleanField(default=False, verbose_name="زيارة مزدوجة")
    mode = models.CharField(max_length=50, default='checkin_checkout', verbose_name="الوضع")
    
    feedback = models.TextField(blank=True, default='', verbose_name="الملاحظات والنتائج")
    questionnaire_answers = models.JSONField(default=dict, blank=True, verbose_name="إجابات الاستبيان")
    
    latitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True, verbose_name="خط العرض المسجل")
    longitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True, verbose_name="خط الطول المسجل")
    device_accuracy = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True, verbose_name="دقة الجهاز (متر)")
    distance = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name="المسافة المحسوبة (متر)")
    location_verified = models.BooleanField(default=True, verbose_name="الموقع محقق")
    location_status = models.CharField(max_length=150, blank=True, default='', verbose_name="حالة الموقع")
    verification_status = models.CharField(max_length=50, default='verified', verbose_name="حالة الاستكمال")
    customer_latitude_snapshot = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True, verbose_name="خط عرض العميل")
    customer_longitude_snapshot = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True, verbose_name="خط طول العميل")
    
    approval_notes = models.TextField(blank=True, default='', verbose_name="ملاحظات الاعتماد / الرفض")
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='visits_approved', verbose_name="معتمد بواسطة")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='visits_created', verbose_name="أنشئ بواسطة")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


    class Meta:
        verbose_name = "زيارة"
        verbose_name_plural = "الزيارات"
        ordering = ['-date', '-serial_num']

    def __str__(self):
        return f"Visit #{self.serial_num} - {self.contact.name}"

    def save(self, *args, **kwargs):
        if not self.serial_num:
            max_serial = Visit.objects.aggregate(models.Max('serial_num'))['serial_num__max']
            self.serial_num = (max_serial or 1000) + 1
        super().save(*args, **kwargs)

    @property
    def status_display_ar(self):
        mapping = {
            'planned': 'مخططة',
            'started': 'جارية',
            'finished': 'منتهية',
        }
        return mapping.get(self.status, self.status)

    @property
    def approval_display_ar(self):
        mapping = {
            'pending': 'قيد الاعتماد',
            'approved': 'معتمدة',
            'disapproved': 'مرفوضة',
        }
        return mapping.get(self.approval_status, self.approval_status)

    @property
    def approval_badge_class(self):
        mapping = {
            'pending': 'bg-amber-100 text-amber-800 border-amber-300',
            'approved': 'bg-emerald-100 text-emerald-800 border-emerald-300',
            'disapproved': 'bg-rose-100 text-rose-800 border-rose-300',
        }
        return mapping.get(self.approval_status, 'bg-gray-100 text-gray-800 border-gray-300')

    @property
    def verification_badge_icon(self):
        if self.verification_status == 'verified' and self.location_verified:
            return 'gpp_good'
        elif self.verification_status == 'force_bypassed':
            return 'gpp_maybe'
        return 'gpp_maybe' if not self.location_verified else 'gpp_good'

    @property
    def verification_badge_color(self):
        if self.verification_status == 'verified' and self.location_verified:
            return 'text-emerald-600 bg-emerald-50 border-emerald-200'
        elif self.verification_status == 'force_bypassed':
            return 'text-amber-600 bg-amber-50 border-amber-200'
        return 'text-rose-600 bg-rose-50 border-rose-200'

    @property
    def distance_formatted(self):
        if self.distance is not None:
            return f"{float(self.distance):.2f} m"
        return "غير محدد"

    @property
    def verification_status_display_ar(self):
        mapping = {
            'verified': 'تم التحقق بنجاح',
            'force_bypassed': 'تم تجاهل التحقق بالقوة',
            'unverified': 'غير محقق',
        }
        return mapping.get(self.verification_status, self.verification_status)


class PlannedVisitItem(models.Model):
    plan_day = models.ForeignKey(PlannedVisitDay, on_delete=models.CASCADE, related_name='items', verbose_name="خطة اليوم")
    order = models.PositiveIntegerField(default=1, verbose_name="الترتيب")
    contact = models.ForeignKey('contacts.Contact', on_delete=models.CASCADE, related_name='planned_visit_items', verbose_name="العميل")
    template = models.ForeignKey(VisitTemplate, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="القالب")
    is_executed = models.BooleanField(default=False, verbose_name="تم التنفيذ")
    visit = models.OneToOneField(Visit, on_delete=models.SET_NULL, null=True, blank=True, related_name='planned_source_item', verbose_name="الزيارة المنفذة")
    notes = models.TextField(blank=True, default='', verbose_name="ملاحظات التخطيط")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "عنصر زيارة مخططة"
        verbose_name_plural = "عناصر الزيارات المخططة"
        ordering = ['order', 'id']

    def __str__(self):
        return f"{self.plan_day.date} - #{self.order} {self.contact.name}"


class VisitSampleItem(models.Model):
    visit = models.ForeignKey(Visit, on_delete=models.CASCADE, related_name='samples', verbose_name="الزيارة")
    product = models.ForeignKey('catalog.Product', on_delete=models.CASCADE, related_name='visit_samples', verbose_name="المنتج/العينة")
    quantity = models.PositiveIntegerField(default=1, verbose_name="الكمية الموزعة")
    notes = models.CharField(max_length=255, blank=True, default='', verbose_name="ملاحظات")

    class Meta:
        verbose_name = "عينة زيارة"
        verbose_name_plural = "عينات الزيارات"

    def __str__(self):
        return f"{self.product.name} ({self.quantity})"


class VisitExpense(models.Model):
    visit = models.ForeignKey(Visit, on_delete=models.CASCADE, related_name='expenses', verbose_name="الزيارة")
    expense_type = models.CharField(max_length=100, verbose_name="نوع المصروف")
    amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, verbose_name="المبلغ")
    notes = models.TextField(blank=True, default='', verbose_name="ملاحظات")

    class Meta:
        verbose_name = "مصروف زيارة"
        verbose_name_plural = "مصروفات الزيارات"

    def __str__(self):
        return f"{self.expense_type} - {self.amount}"

