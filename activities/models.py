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

    # Settings
    allow_unplanned = models.BooleanField(default=True, verbose_name="تفعيل تسجيل زيارات خارج خطة الزيارات")
    enable_product_detailing = models.BooleanField(default=True, verbose_name="تفعيل شرح المنتجات")
    enable_double_visit_assessment_only = models.BooleanField(default=False, verbose_name="تفعيل التقييمات للزيارات المزدوجة فقط")

    # Location
    has_special_location_settings = models.BooleanField(default=False, verbose_name="اعدادات خاصة للتحقق من الموقع")
    special_tolerance = models.PositiveIntegerField(default=300, verbose_name="سماحية الموقع الخاصة (متر)")

    # Constraints
    restricted_roles = models.ManyToManyField('accounts.Role', blank=True, related_name='visit_templates', verbose_name="تقييد على أدوار المستخدمين")
    business_relationship = models.CharField(max_length=50, blank=True, default='', verbose_name="علاقة العمل")
    contact_type = models.CharField(max_length=50, blank=True, default='', verbose_name="نوع جهة الاتصال")
    restrict_account_types = models.JSONField(default=list, blank=True, verbose_name="نوع الحساب المستهدف")
    customer_classifications = models.JSONField(default=list, blank=True, verbose_name="تصنيفات العملاء")
    specialties = models.JSONField(default=list, blank=True, verbose_name="التخصصات المستهدفة")
    customer_status = models.CharField(max_length=50, blank=True, default='', verbose_name="حالة العميل")

    questionnaire = models.JSONField(default=dict, blank=True, verbose_name="أسئلة الاستبيان (نسخة احتياطية)")
    suggested_products = models.ManyToManyField(
        'catalog.Product',
        blank=True,
        related_name='template_suggested_products',
        limit_choices_to={'is_active': True, 'sellable': True},
        verbose_name="المنتجات المقترحة لهذا القالب"
    )
    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True, verbose_name="تاريخ الإنشاء")
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True, verbose_name="تاريخ التحديث")

    def get_eligible_suggested_products(self):
        """Returns suggested products for this template filtered strictly to active sellable products."""
        return self.suggested_products.filter(is_active=True, sellable=True).order_by('name')

    class Meta:
        verbose_name = "قالب زيارة"
        verbose_name_plural = "قوالب الزيارات"
        ordering = ['id']

    def __str__(self):
        return self.display_name_ar or self.name

    @property
    def questions_count(self):
        return self.questions.filter(is_active=True).count()

    def is_user_eligible(self, user):
        """
        Check if a given user is eligible to use this template based on role restrictions.
        Superusers / SuperAdmins are always eligible.
        If restricted_roles is empty, all active roles are eligible.
        """
        if not user or not user.is_authenticated:
            return False
        if getattr(user, 'is_super_admin', False) or user.is_superuser:
            return True
        if not self.restricted_roles.exists():
            return True
        if not getattr(user, 'role', None) or not user.role.is_active:
            return False
        return self.restricted_roles.filter(id=user.role.id, is_active=True).exists()

    def is_contact_eligible(self, contact, user=None):
        """
        Business Rule (Requirement 1 & 2):
        Checks if a contact is eligible for this template based on:
        1. Contact type ('person' vs 'organization') if configured on template.
        2. Account type / customer category (Pharmacy, Clinic, Hospital, Store, etc.).
        3. Customer classifications (if configured).
        4. User role permissions (if user provided).
        Comparison is case-insensitive, trimmed, and supports canonical names and aliases.
        """
        if user and not self.is_user_eligible(user):
            return False

        if not contact:
            return False

        # 1. Contact type restriction ('person' vs 'organization')
        if self.contact_type:
            tmpl_c_type = str(self.contact_type).strip().lower()
            cont_c_type = str(getattr(contact, 'contact_type', '') or '').strip().lower()
            if cont_c_type and tmpl_c_type != cont_c_type:
                return False

        # 2. Customer classifications restriction
        if self.customer_classifications:
            allowed_classes = {str(c).strip().lower() for c in self.customer_classifications if c}
            if allowed_classes:
                cont_cat = str(getattr(contact, 'customer_category', '') or '').strip().lower()
                if cont_cat and cont_cat not in allowed_classes:
                    return False

        # 3. Account type restriction
        if not self.restrict_account_types:
            return True

        allowed = {str(t).strip().lower() for t in self.restrict_account_types if t}
        if not allowed:
            return True

        contact_type = (getattr(contact, 'account_type', '') or '').strip().lower()
        if not contact_type:
            name_l = (getattr(contact, 'name', '') or '').lower()
            if getattr(contact, 'specialty', None) or any(d in name_l for d in ['د.', 'دكتور', 'طبيب', 'dr.', 'dr ']):
                contact_type = 'clinic'
            elif any(p in name_l for p in ['صيدلية', 'صيدليه', 'pharmacy']):
                contact_type = 'pharmacy'
            elif any(h in name_l for h in ['مستشفى', 'hospital']):
                contact_type = 'hospital'
            elif any(s in name_l for s in ['مخزن', 'store']):
                contact_type = 'store'
            elif any(c in name_l for c in ['مركز', 'عيادة', clinic]):
                contact_type = 'clinic'
            else:
                # If account type cannot be determined, allow the rep to proceed
                return True

        if contact_type and contact_type in allowed:
            return True

        alias_map = {
            'store': ['drug store', 'store', 'warehouse'],
            'drug store': ['drug store', 'store'],
            'clinic': ['clinic', 'physician', 'doctor'],
            'pharmacy': ['pharmacy', 'pharmacist'],
            'center': ['center', 'medical center'],
            'polyclinic': ['polyclinic'],
            'hospital': ['hospital'],
            'distributor': ['distributor'],
            'health unit': ['health unit'],
            'dispensary': ['dispensary'],
            'physician': ['clinic', 'physician', 'doctor'],
            'pharmacist': ['pharmacy', 'pharmacist'],
        }
        for al in allowed:
            aliases = alias_map.get(al, [al])
            if contact_type in aliases:
                return True

        # Fallback to customer_category if account_type matches
        cust_cat = (getattr(contact, 'customer_category', '') or '').strip().lower()
        if cust_cat and (cust_cat in allowed or any(cust_cat in alias_map.get(al, [al]) for al in allowed)):
            return True

        return False

    def is_account_type_eligible(self, account_type):
        """Check whether an account type string is eligible."""
        if not self.restrict_account_types:
            return True
        allowed = {str(t).strip().lower() for t in self.restrict_account_types if t}
        if not allowed:
            return True
        if not account_type:
            return True
        clean_type = str(account_type).strip().lower()
        if clean_type in allowed:
            return True
        alias_map = {
            'store': ['drug store', 'store', 'warehouse'],
            'drug store': ['drug store', 'store'],
            'clinic': ['clinic', 'physician'],
            'pharmacy': ['pharmacy', 'pharmacist'],
            'center': ['center', 'medical center'],
            'polyclinic': ['polyclinic'],
            'hospital': ['hospital'],
            'distributor': ['distributor'],
            'health unit': ['health unit'],
            'dispensary': ['dispensary'],
            'physician': ['clinic', 'physician'],
            'pharmacist': ['pharmacy', 'pharmacist'],
        }
        for al in allowed:
            aliases = alias_map.get(al, [al])
            if clean_type in aliases:
                return True
        return False

    def is_product_detailing_supported(self):
        """
        Business Rule (Requirement 8):
        The 'المنتجات المشروحة' field or section must appear only in these visit templates:
        1. single visit — doctor/DR visit
        2. single visit — pharmacy visit
        3. healthy day
        """
        norm_name = (self.name or '').strip().lower()
        norm_ar = (self.display_name_ar or '').strip().lower()
        norm_en = (self.display_name_en or '').strip().lower()

        # Doctor / DR single visit
        is_dr_single = (
            ('single' in norm_name or 'فردية' in norm_ar) and 
            ('dr' in norm_name or 'dr' in norm_en or 'doctor' in norm_name or 'طبيب' in norm_ar)
        ) or norm_name in ['single_visit_dr', 'single visit (dr)', 'single_visit_doctor']

        # Pharmacy single visit
        is_pharm_single = (
            ('single' in norm_name or 'فردية' in norm_ar) and 
            ('pharmacy' in norm_name or 'pharmacy' in norm_en or 'صيدلية' in norm_ar)
        ) or norm_name in ['single_visit_pharmacy', 'single visit (pharmacy)']

        # Healthy day
        is_healthy_day = (
            'healthy' in norm_name or 'healthy' in norm_en or 'صحي' in norm_ar
        ) or norm_name in ['healthy_day', 'healthy day']

        # Explicit exclusion: Coaching visits are NOT single visits
        if 'coach' in norm_name or 'تدريب' in norm_ar or 'مزدوج' in norm_ar or 'مرافقة' in norm_ar or 'coaching' in norm_en:
            return False

        # Explicit exclusion: Store & Distributor visits
        if 'store' in norm_name or 'distributor' in norm_name or 'مخزن' in norm_ar or 'موزع' in norm_ar:
            return False

        return bool(is_dr_single or is_pharm_single or is_healthy_day)

    @property
    def supports_product_detailing(self):
        return self.is_product_detailing_supported()

    def get_active_questions(self):
        """
        Returns active questions for the template, excluding any duplicate outcome questions
        (e.g. 'هل كان يوم ناجح ؟') from active workflows while preserving historical audit data.
        """
        return self.questions.filter(is_active=True).exclude(
            models.Q(text_ar__icontains='هل كان يوم ناجح') | models.Q(text_en__icontains='Was it a successful day')
        ).order_by('order', 'id')


class VisitTemplateQuestion(models.Model):
    QUESTION_TYPES = [
        ('single_choice', 'اختيار واحد من متعدد'),
        ('multiple_choice', 'اختيار متعدد'),
        ('text', 'نص قصير'),
        ('textarea', 'نص طويل'),
        ('number', 'رقم'),
        ('date', 'تاريخ'),
        ('rating', 'تقييم'),
    ]

    STAGES = [
        ('all', 'كامل الزيارة'),
        ('start_only', 'البدء فقط ▶'),
        ('end_only', 'الإنهاء فقط ■'),
    ]

    template = models.ForeignKey(VisitTemplate, on_delete=models.CASCADE, related_name='questions', verbose_name="القالب")
    text_ar = models.CharField(max_length=255, verbose_name="العنوان (ar)")
    text_en = models.CharField(max_length=255, blank=True, default='', verbose_name="العنوان (en)")
    question_type = models.CharField(max_length=50, choices=QUESTION_TYPES, default='single_choice', verbose_name="نوع السؤال")
    options = models.JSONField(default=list, blank=True, help_text="قائمة الخيارات: [{'text_ar': ..., 'text_en': ..., 'value': ...}]", verbose_name="الخيارات")
    is_required = models.BooleanField(default=True, verbose_name="مطلوب")
    is_conditional = models.BooleanField(default=False, verbose_name="مشروط")
    conditional_parent = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='conditional_dependents', verbose_name="السؤال الشرطي الأب")
    conditional_trigger_value = models.CharField(max_length=255, blank=True, default='', verbose_name="قيمة الإجابة المشروطة")
    stage = models.CharField(max_length=50, choices=STAGES, default='all', verbose_name="مرحلة السؤال")
    order = models.PositiveIntegerField(default=1, verbose_name="الترتيب")
    is_active = models.BooleanField(default=True, verbose_name="نشط")

    class Meta:
        verbose_name = "سؤال استبيان الزيارة"
        verbose_name_plural = "أسئلة استبيانات الزيارات"
        ordering = ['order', 'id']

    def __str__(self):
        return f"{self.template.display_name_ar} - {self.text_ar}"


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
        ('cancelled', 'Cancelled'),
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
    detailed_products = models.ManyToManyField('catalog.Product', blank=True, related_name='detailed_in_visits', verbose_name="المنتجات المشروحة")
    visit_outcome = models.CharField(max_length=50, blank=True, default='', verbose_name="نتيجة الزيارة")
    
    latitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True, verbose_name="خط العرض المسجل")
    longitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True, verbose_name="خط الطول المسجل")
    device_accuracy = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True, verbose_name="دقة الجهاز (متر)")
    distance = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name="المسافة المحسوبة (متر)")
    location_verified = models.BooleanField(default=True, verbose_name="الموقع محقق")
    location_status = models.CharField(max_length=150, blank=True, default='', verbose_name="حالة الموقع")
    verification_status = models.CharField(max_length=50, default='verified', verbose_name="حالة الاستكمال")
    customer_latitude_snapshot = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True, verbose_name="خط عرض العميل")
    customer_longitude_snapshot = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True, verbose_name="خط طول العميل")
    
    # Location Photo & Superuser Bypass Evidence Fields
    location_photo = models.ImageField(upload_to='visits/evidence/%Y/%m/', null=True, blank=True, verbose_name="صورة إثبات الموقع")
    photo_captured_at = models.DateTimeField(null=True, blank=True, verbose_name="وقت التقاط الصورة")
    bypassed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='visits_bypassed', verbose_name="تم التجاوز بواسطة")
    bypassed_at = models.DateTimeField(null=True, blank=True, verbose_name="تاريخ ووقت التجاوز")
    bypass_reason = models.CharField(max_length=255, blank=True, default='', verbose_name="سبب التجاوز")

    approval_notes = models.TextField(blank=True, default='', verbose_name="ملاحظات الاعتماد / الرفض")
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='visits_approved', verbose_name="معتمد بواسطة")
    approved_at = models.DateTimeField(null=True, blank=True, verbose_name="تاريخ ووقت الاعتماد / الرفض")
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
    def plan_type_display_ar(self):
        return "زيارة مخططة" if self.is_planned else "زيارة خارج الخطة"

    @property
    def plan_type_badge_class(self):
        if self.is_planned:
            return "bg-blue-50 text-blue-700 border-blue-200"
        return "bg-purple-50 text-purple-700 border-purple-200"

    @property
    def has_photo_evidence(self):
        return bool(self.location_photo)

    @property
    def status_display_ar(self):
        mapping = {
            'planned': 'مخططة',
            'started': 'جارية',
            'finished': 'منتهية',
            'cancelled': 'ملغاة',
        }
        return mapping.get(self.status, self.status)

    @property
    def status_badge_class(self):
        mapping = {
            'started': 'bg-amber-100 text-amber-800 border-amber-300',
            'finished': 'bg-emerald-100 text-emerald-800 border-emerald-300',
            'planned': 'bg-sky-100 text-sky-800 border-sky-300',
            'cancelled': 'bg-rose-100 text-rose-800 border-rose-300',
        }
        return mapping.get(self.status, 'bg-gray-100 text-gray-800 border-gray-300')

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
    def duration_formatted(self):
        """
        Calculates and formats visit duration nicely in Arabic.
        If duration is 0 but started_at and ended_at exist, computes duration dynamically.
        """
        secs = self.duration
        if (not secs or secs == 0) and self.started_at and self.ended_at:
            secs = max(1, int((self.ended_at - self.started_at).total_seconds()))

        if not secs or secs <= 0:
            return "0 دقيقة"

        if secs < 60:
            return f"{secs} ثانية"

        mins = secs // 60
        remaining_secs = secs % 60
        if mins < 60:
            if remaining_secs > 0:
                return f"{mins} دقيقة و {remaining_secs} ثانية"
            return f"{mins} دقيقة"

        hours = mins // 60
        rem_mins = mins % 60
        if rem_mins > 0:
            return f"{hours} ساعة و {rem_mins} دقيقة"
        return f"{hours} ساعة"

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


class ApprovalAuditLog(models.Model):
    RECORD_TYPES = [
        ('visit', 'زيارة ميدانية'),
        ('sales_order', 'أمر بيع'),
        ('purchase_order', 'أمر شراء'),
    ]
    ACTION_CHOICES = [
        ('submitted', 'تقديم للاعتماد'),
        ('approved', 'اعتماد'),
        ('rejected', 'رفض'),
        ('resubmitted', 'إعادة تقديم بعد التعديل'),
        ('status_changed', 'تغيير الحالة'),
        ('sent_to_agenda', 'إرسال لجدول الأعمال'),
    ]

    record_type = models.CharField(max_length=20, choices=RECORD_TYPES, db_index=True, verbose_name="نوع السجل")
    visit = models.ForeignKey(Visit, on_delete=models.CASCADE, null=True, blank=True, related_name='approval_history', verbose_name="الزيارة")
    sales_order = models.ForeignKey('sales.SalesOrder', on_delete=models.CASCADE, null=True, blank=True, related_name='approval_history', verbose_name="أمر البيع")
    purchase_order = models.ForeignKey('purchases.PurchaseOrder', on_delete=models.CASCADE, null=True, blank=True, related_name='approval_history', verbose_name="أمر الشراء")
    action = models.CharField(max_length=30, choices=ACTION_CHOICES, db_index=True, verbose_name="نوع الإجراء")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='approval_actions_logged', verbose_name="المستخدم المنفذ")
    status_before = models.CharField(max_length=50, blank=True, verbose_name="الحالة السابقة")
    status_after = models.CharField(max_length=50, blank=True, verbose_name="الحالة الجديدة")
    reason = models.TextField(blank=True, default='', verbose_name="السبب / الملاحظات")
    ip_address = models.GenericIPAddressField(null=True, blank=True, verbose_name="عنوان IP")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, verbose_name="تاريخ ووقت الإجراء")

    class Meta:
        verbose_name = "سجل تدقيق الاعتماد"
        verbose_name_plural = "سجلات تدقيق الاعتمادات"
        ordering = ['-created_at']

    def __str__(self):
        target = f"Visit #{self.visit.serial_num}" if self.visit else (f"Sales Order #{self.sales_order.order_number}" if self.sales_order else (f"Purchase Order #{self.purchase_order.order_number}" if self.purchase_order else "Record"))
        return f"[{self.get_action_display()}] {target} by {self.actor} at {self.created_at.strftime('%Y-%m-%d %H:%M')}"


class AgendaTodo(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='agenda_todos', verbose_name="المستخدم")
    date = models.DateField(db_index=True, verbose_name="تاريخ المهمة")
    title = models.CharField(max_length=255, verbose_name="العنوان")
    is_completed = models.BooleanField(default=False, verbose_name="مكتمل")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "مهمة جدول الأعمال"
        verbose_name_plural = "مهام جدول الأعمال"
        ordering = ['is_completed', '-created_at']

    def __str__(self):
        return f"{self.user} - {self.date}: {self.title}"

