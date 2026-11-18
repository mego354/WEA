from decimal import Decimal
from django.db import models
from django.conf import settings
from django.utils import timezone


class SalesTarget(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='sales_targets',
        verbose_name="المندوب / المسؤول"
    )
    area = models.ForeignKey(
        'master_data.Area',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sales_targets',
        verbose_name="المنطقة الجغرافية / المحافظة"
    )
    year = models.PositiveSmallIntegerField(verbose_name="السنة")
    month = models.PositiveSmallIntegerField(verbose_name="الشهر (1-12)")
    
    target_sales_amount = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal('0.00'), verbose_name="تارجت المبيعات (ج.م)"
    )
    target_collections_amount = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal('0.00'), verbose_name="تارجت التحصيلات (ج.م)"
    )
    target_visits_count = models.PositiveIntegerField(
        default=0, verbose_name="تارجت الزيارات الميدانية"
    )
    notes = models.CharField(max_length=255, blank=True, default='', verbose_name="ملاحظات")
    
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_sales_targets',
        verbose_name="أنشئ بواسطة"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "هدف بيعي ومستهدف تحصيل"
        verbose_name_plural = "أهداف المبيعات والتحصيلات (Targets)"
        unique_together = ('user', 'year', 'month')
        ordering = ['-year', '-month', 'user']

    def __str__(self):
        return f"{self.user} - {self.month}/{self.year}: مبيعات {self.target_sales_amount:,.0f} ج.م"


class CustomerCall(models.Model):
    PURPOSE_CHOICES = [
        ('follow_up', 'متابعة دورية'),
        ('order_taking', 'طلب أوردر / مبيعات'),
        ('collection', 'متابعة تحصيل'),
        ('detailing', 'شرح منتجات عن بعد (Tele-detailing)'),
        ('customer_service', 'خدمة عملاء ودعم'),
        ('complaint', 'شكوى واستفسار'),
    ]
    
    OUTCOME_CHOICES = [
        ('completed', 'تمت بنجاح وتواصل'),
        ('no_answer', 'لم يرد'),
        ('busy', 'مشغول'),
        ('rescheduled', 'إعادة جدولة'),
        ('cancelled', 'ملغاة'),
    ]

    contact = models.ForeignKey(
        'contacts.Contact',
        on_delete=models.CASCADE,
        related_name='customer_calls',
        verbose_name="العميل / جهة الاتصال"
    )
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='conducted_calls',
        verbose_name="المندوب / المسؤول"
    )
    call_date = models.DateField(default=timezone.now, db_index=True, verbose_name="تاريخ المكالمة")
    call_time = models.TimeField(null=True, blank=True, verbose_name="وقت المكالمة")
    duration_minutes = models.PositiveIntegerField(default=5, verbose_name="مدة المكالمة (بالدقائق)")
    
    purpose = models.CharField(max_length=30, choices=PURPOSE_CHOICES, default='follow_up', verbose_name="الغرض من المكالمة")
    outcome = models.CharField(max_length=30, choices=OUTCOME_CHOICES, default='completed', verbose_name="نتيجة المكالمة")
    
    notes = models.TextField(blank=True, default='', verbose_name="الملاحظات والتفاصيل")
    sales_order = models.ForeignKey(
        'sales.SalesOrder',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='originating_calls',
        verbose_name="أمر البيع الناتج (إن وجد)"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "مكالمة وتواصل هاتفي"
        verbose_name_plural = "المكالمات والتواصل الهاتفي (Calls)"
        ordering = ['-call_date', '-created_at']

    def __str__(self):
        return f"مكالمة {self.contact.name} بواسطة {self.performed_by} ({self.call_date})"


class CoachingEvaluation(models.Model):
    visit = models.ForeignKey(
        'activities.Visit',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='coaching_evaluations',
        verbose_name="الزيارة المزدوجة المرتبطة"
    )
    manager = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='given_coaching_evaluations',
        verbose_name="المدير / المشرف المقيم"
    )
    rep = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='received_coaching_evaluations',
        verbose_name="المندوب المتدرب"
    )
    customer = models.ForeignKey(
        'contacts.Contact',
        on_delete=models.CASCADE,
        related_name='coaching_evaluations',
        verbose_name="العميل / الطبيب المزار"
    )
    date = models.DateField(default=timezone.now, db_index=True, verbose_name="تاريخ التقييم")
    
    product_knowledge_score = models.PositiveSmallIntegerField(default=8, verbose_name="المعرفة بالمنتجات (1-10)")
    selling_skills_score = models.PositiveSmallIntegerField(default=7, verbose_name="مهارات البيع والإقناع (1-10)")
    detailing_clarity_score = models.PositiveSmallIntegerField(default=8, verbose_name="وضوح الرسالة الترويجية (1-10)")
    objection_handling_score = models.PositiveSmallIntegerField(default=7, verbose_name="التعامل مع الاعتراضات (1-10)")
    overall_score = models.DecimalField(max_digits=4, decimal_places=1, default=7.5, verbose_name="التقييم الإجمالي")
    
    action_items = models.TextField(blank=True, default='', verbose_name="النقاط المتفق على تطويرها")
    notes = models.TextField(blank=True, default='', verbose_name="ملاحظات المشرف")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "تقييم كوتشينج وزيارة مزدوجة"
        verbose_name_plural = "تقييمات الكوتشينج والزيارات المزدوجة"
        ordering = ['-date', '-created_at']

    def __str__(self):
        return f"تقييم {self.rep} بواسطة {self.manager} ({self.date})"
