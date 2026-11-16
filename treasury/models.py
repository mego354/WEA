from decimal import Decimal
from django.db import models
from django.conf import settings
from django.utils import timezone
from contacts.models import Contact
from purchases.models import PurchaseOrder


class Vault(models.Model):
    VAULT_TYPES = [
        ('cash', 'خزينة نقدية (Cash Safe)'),
        ('bank', 'حساب بنكي (Bank Account)'),
    ]

    serial_num = models.PositiveIntegerField(unique=True, verbose_name="رقم الخزنة")
    name = models.CharField(max_length=150, unique=True, verbose_name="اسم الخزنة / الحساب")
    vault_type = models.CharField(max_length=20, choices=VAULT_TYPES, default='cash', verbose_name="نوع الخزنة")
    assigned_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="assigned_vaults", verbose_name="المسئول / المندوب الحائز للعهدة")
    is_rep_vault = models.BooleanField(default=False, verbose_name="خزنة عهدة مندوب")
    area = models.ForeignKey('master_data.Area', on_delete=models.SET_NULL, null=True, blank=True, related_name="vaults", verbose_name="المنطقة الجغرافية / الفرع")
    is_active = models.BooleanField(default=True, verbose_name="مفعلة")
    current_balance = models.DecimalField(max_digits=14, decimal_places=2, default=0.00, verbose_name="الرصيد الحالي (ج.م)")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء")

    class Meta:
        verbose_name = "خزنة نقدية"
        verbose_name_plural = "الخزن والحسابات النقدية"
        ordering = ['serial_num']

    def __str__(self):
        return f"{self.name} (رصيد: {self.current_balance:,.2f} ج.م)"

    def save(self, *args, **kwargs):
        if not self.serial_num:
            max_serial = Vault.objects.aggregate(models.Max('serial_num'))['serial_num__max'] or 1000
            self.serial_num = max_serial + 1
        super().save(*args, **kwargs)


class VendorAccount(models.Model):
    supplier = models.OneToOneField(Contact, on_delete=models.CASCADE, related_name="vendor_account", verbose_name="المورد")
    credit_limit = models.DecimalField(max_digits=14, decimal_places=2, default=0.00, verbose_name="حد الائتمان (ج.م)")
    credit_period_days = models.PositiveIntegerField(default=30, verbose_name="فترة الائتمان (أيام)")
    current_balance = models.DecimalField(max_digits=14, decimal_places=2, default=0.00, verbose_name="الرصيد الحالي المستحق (ج.م)")
    last_transaction_date = models.DateField(null=True, blank=True, verbose_name="تاريخ آخر معاملة")
    overdue_balance = models.DecimalField(max_digits=14, decimal_places=2, default=0.00, verbose_name="المديونية المتأخرة (ج.م)")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="تاريخ التحديث")

    class Meta:
        verbose_name = "حساب مورد"
        verbose_name_plural = "حسابات الموردين"
        ordering = ['-current_balance']

    def __str__(self):
        return f"حساب: {self.supplier.name} - مستحق: {self.current_balance:,.2f} ج.م"

    @classmethod
    def get_or_create_for_supplier(cls, supplier):
        obj, _ = cls.objects.get_or_create(supplier=supplier, defaults={
            'credit_limit': supplier.credit_limit,
            'credit_period_days': supplier.credit_period_days,
        })
        return obj


class VendorTransaction(models.Model):
    TX_TYPES = [
        ('credit', 'دائن / Credit (فاتورة استحقاق للمورد)'),
        ('debit', 'مدين / Debit (سداد أو مردودات من المورد)'),
    ]

    REASONS = [
        ('purchase', 'فاتورة مشتريات'),
        ('purchase_payments', 'سداد نقدي للمورد'),
        ('purchase_returns', 'مردودات مشتريات'),
        ('adjustment', 'تسوية رصيد'),
    ]

    serial = models.PositiveIntegerField(unique=True, db_index=True, verbose_name="رقم الحركة")
    account = models.ForeignKey(VendorAccount, on_delete=models.CASCADE, related_name="transactions", verbose_name="حساب المورد")
    purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.SET_NULL, null=True, blank=True, related_name="vendor_transactions", verbose_name="أمر الشراء المرتبط")
    
    transaction_type = models.CharField(max_length=10, choices=TX_TYPES, verbose_name="نوع القيد")
    reason = models.CharField(max_length=30, choices=REASONS, default='purchase', verbose_name="البيان")
    transaction_date = models.DateField(default=timezone.now, db_index=True, verbose_name="تاريخ القيد")
    due_date = models.DateField(null=True, blank=True, db_index=True, verbose_name="تاريخ الاستحقاق")
    
    credit = models.DecimalField(max_digits=14, decimal_places=2, default=0.00, verbose_name="دائن (ج.م)")
    debit = models.DecimalField(max_digits=14, decimal_places=2, default=0.00, verbose_name="مدين (ج.م)")
    running_balance = models.DecimalField(max_digits=14, decimal_places=2, default=0.00, verbose_name="الرصيد بعد الحركة (ج.م)")
    
    description = models.CharField(max_length=255, verbose_name="التوصيف")
    notes = models.TextField(blank=True, verbose_name="ملاحظات")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="المسئول")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء")

    class Meta:
        verbose_name = "حركة حساب مورد"
        verbose_name_plural = "عمليات وحركات الموردين"
        ordering = ['-serial']

    def __str__(self):
        return f"حركة #{self.serial} - {self.description} ({self.account.supplier.name})"

    def save(self, *args, **kwargs):
        if not self.serial:
            max_s = VendorTransaction.objects.aggregate(models.Max('serial'))['serial__max'] or 50000
            self.serial = max_s + 1
        super().save(*args, **kwargs)


class VendorInstallment(models.Model):
    transaction = models.ForeignKey(VendorTransaction, on_delete=models.CASCADE, related_name="installments", verbose_name="حركة الفاتورة")
    total_amount = models.DecimalField(max_digits=14, decimal_places=2, verbose_name="إجمالي قيمة الفاتورة")
    closed_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0.00, verbose_name="المسدد")
    open_amount = models.DecimalField(max_digits=14, decimal_places=2, verbose_name="المتبقي المفتوح")
    due_date = models.DateField(verbose_name="تاريخ الاستحقاق")
    is_settled = models.BooleanField(default=False, db_index=True, verbose_name="مسددة بالكامل")

    class Meta:
        verbose_name = "مستحق فاتورة مورد"
        verbose_name_plural = "مستحقات فواتير الموردين"
        ordering = ['due_date']

    def __str__(self):
        return f"فاتورة #{self.transaction.serial} - متبقي: {self.open_amount:,.2f} ج.م"


class VendorPayment(models.Model):
    PAYMENT_METHODS = [
        ('cash', 'نقدي (Cash)'),
        ('cheque', 'شيك بنكي (Cheque)'),
        ('bank_transfer', 'تحويل بنكي (Bank Transfer)'),
    ]

    serial_num = models.PositiveIntegerField(unique=True, db_index=True, verbose_name="رقم سند الصرف")
    purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.SET_NULL, null=True, blank=True, related_name="vendor_payments", verbose_name="أمر الشراء المرتبط")
    supplier = models.ForeignKey(Contact, on_delete=models.PROTECT, related_name="vendor_payments", verbose_name="المورد")
    vault = models.ForeignKey(Vault, on_delete=models.PROTECT, related_name="vendor_payments", verbose_name="خزنة الصرف")
    payment_date = models.DateField(default=timezone.now, verbose_name="تاريخ الصرف")
    amount = models.DecimalField(max_digits=14, decimal_places=2, verbose_name="المبلغ المسدد (ج.م)")
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHODS, default='cash', verbose_name="طريقة السداد")
    reference_number = models.CharField(max_length=100, blank=True, verbose_name="رقم الشيك / التحويل / المرجع")
    notes = models.TextField(blank=True, verbose_name="ملاحظات")
    status = models.CharField(max_length=20, choices=[('pending', 'قيد التنفيذ'), ('cleared', 'معتمد / منفّذ')], default='cleared', verbose_name="الحالة")
    debit_transaction = models.OneToOneField(VendorTransaction, on_delete=models.SET_NULL, null=True, blank=True, related_name="vendor_payment", verbose_name="قيد المدين بالحسابات")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="المسئول")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء")

    class Meta:
        verbose_name = "سند صرف مورد"
        verbose_name_plural = "مدفوعات وسندات صرف الموردين"
        ordering = ['-serial_num']

    def __str__(self):
        return f"سند صرف #{self.serial_num} - {self.supplier.name} ({self.amount:,.2f} ج.م)"

    def save(self, *args, **kwargs):
        if not self.serial_num:
            max_s = VendorPayment.objects.aggregate(models.Max('serial_num'))['serial_num__max'] or 10000
            self.serial_num = max_s + 1
        super().save(*args, **kwargs)


class Settlement(models.Model):
    payment_transaction = models.ForeignKey(VendorTransaction, on_delete=models.CASCADE, related_name="outward_settlements", verbose_name="حركة السداد")
    target_installment = models.ForeignKey(VendorInstallment, on_delete=models.CASCADE, related_name="settlements", verbose_name="فاتورة المورد المسددة")
    amount = models.DecimalField(max_digits=14, decimal_places=2, verbose_name="المبلغ المخصص (ج.م)")
    settled_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ التسوية")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        verbose_name = "تسوية سداد فاتورة"
        verbose_name_plural = "تسويات سداد الفواتير"


class VaultTransaction(models.Model):
    TX_TYPES = [
        ('inflow', 'إيداع نقدي (Inflow)'),
        ('outflow', 'صرف نقدي (Outflow)'),
    ]

    vault = models.ForeignKey(Vault, on_delete=models.CASCADE, related_name="transactions", verbose_name="الخزنة")
    transaction_type = models.CharField(max_length=15, choices=TX_TYPES, verbose_name="نوع الحركة")
    amount = models.DecimalField(max_digits=14, decimal_places=2, verbose_name="المبلغ (ج.م)")
    running_balance = models.DecimalField(max_digits=14, decimal_places=2, verbose_name="الرصيد بعد الحركة (ج.م)")
    reference_type = models.CharField(max_length=50, verbose_name="نوع العملية المرجعية")
    reference_id = models.PositiveIntegerField(null=True, blank=True, verbose_name="معرف العملية المرجعية")
    description = models.CharField(max_length=255, verbose_name="البيان")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="المسئول")
    is_reversed = models.BooleanField(default=False, verbose_name="حركة معكوسة")
    reversed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="reversed_vault_transactions", verbose_name="المسئول عن العكس")
    reversal_transaction = models.OneToOneField('self', on_delete=models.SET_NULL, null=True, blank=True, related_name="original_transaction", verbose_name="حركة العكس المرتبطة")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الحركة")

    class Meta:
        verbose_name = "حركة خزينة"
        verbose_name_plural = "حركات الخزن والنقدية"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.vault.name} - {self.get_transaction_type_display()} {self.amount:,.2f} ج.م"


class VendorPaymentRequest(models.Model):
    STATUS_CHOICES = [
        ('pending', 'قيد الانتظار والمراجعة'),
        ('approved', 'معتمد للصرف'),
        ('rejected', 'مرفوض'),
        ('executed', 'تم الصرف والسداد'),
        ('cancelled', 'ملغي'),
    ]

    serial_num = models.PositiveIntegerField(unique=True, db_index=True, verbose_name="رقم المسلسل")
    request_number = models.CharField(max_length=50, unique=True, verbose_name="رقم طلب الصرف")
    purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.SET_NULL, null=True, blank=True, related_name="payment_requests", verbose_name="أمر الشراء المرتبط")
    supplier = models.ForeignKey(Contact, on_delete=models.PROTECT, related_name="payment_requests", verbose_name="المورد")
    amount = models.DecimalField(max_digits=14, decimal_places=2, verbose_name="المبلغ المطلوب صرفه (ج.م)")
    preferred_vault = models.ForeignKey(Vault, on_delete=models.SET_NULL, null=True, blank=True, related_name="payment_requests", verbose_name="الخزنة المقترحة")
    request_date = models.DateField(default=timezone.now, verbose_name="تاريخ الطلب")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', db_index=True, verbose_name="الحالة")
    
    notes = models.TextField(blank=True, verbose_name="ملاحظات وأسباب الصرف")
    rejection_reason = models.TextField(blank=True, default="", verbose_name="سبب الرفض")

    vendor_payment = models.OneToOneField(
        VendorPayment, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="payment_request", verbose_name="سند الصرف المنفذ"
    )

    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_payment_requests", verbose_name="المنشئ")
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="approved_payment_requests", verbose_name="المعتمد")
    approved_at = models.DateTimeField(null=True, blank=True, verbose_name="تاريخ الاعتماد")
    executed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="executed_payment_requests", verbose_name="المنفذ")
    executed_at = models.DateTimeField(null=True, blank=True, verbose_name="تاريخ التنفيذ والصرف")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="تاريخ التحديث")

    class Meta:
        verbose_name = "طلب صرف لمورد"
        verbose_name_plural = "طلبات صرف الموردين"
        ordering = ['-serial_num']

    def __str__(self):
        return f"{self.request_number} - {self.supplier.name} ({self.amount:,.2f} ج.م)"

    def save(self, *args, **kwargs):
        if not self.serial_num:
            max_s = VendorPaymentRequest.objects.aggregate(models.Max('serial_num'))['serial_num__max'] or 100
            self.serial_num = max_s + 1
            self.request_number = f"VPR-{timezone.now().year}-{self.serial_num:04d}"
        super().save(*args, **kwargs)

    @property
    def status_display_ar(self):
        mapping = dict(self.STATUS_CHOICES)
        return mapping.get(self.status, self.get_status_display())

    @property
    def status_badge_class(self):
        mapping = {
            'pending': 'bg-amber-100 text-amber-800 border-amber-300',
            'approved': 'bg-teal-100 text-teal-800 border-teal-300',
            'executed': 'bg-emerald-100 text-emerald-800 border-emerald-300',
            'rejected': 'bg-rose-100 text-rose-800 border-rose-300',
            'cancelled': 'bg-slate-100 text-slate-800 border-slate-300',
        }
        return mapping.get(self.status, 'bg-gray-100 text-gray-800 border-gray-300')

