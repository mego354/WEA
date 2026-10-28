from decimal import Decimal
from django.db import models
from django.conf import settings
from django.utils import timezone
from contacts.models import Contact, ContactAddress
from catalog.models import Product
from inventory.models import Warehouse, InventoryMemo
from treasury.models import Vault


class CustomerAccount(models.Model):
    customer = models.OneToOneField(Contact, on_delete=models.CASCADE, related_name="customer_account", verbose_name="العميل")
    credit_limit = models.DecimalField(max_digits=14, decimal_places=2, default=0.00, verbose_name="حد الائتمان (ج.م)")
    credit_period_days = models.PositiveIntegerField(default=30, verbose_name="فترة الائتمان (أيام)")
    current_balance = models.DecimalField(max_digits=14, decimal_places=2, default=0.00, verbose_name="الرصيد المدين المستحق (ج.م)")
    last_transaction_date = models.DateField(null=True, blank=True, verbose_name="تاريخ آخر معاملة")
    overdue_balance = models.DecimalField(max_digits=14, decimal_places=2, default=0.00, verbose_name="المديونية المتأخرة (ج.م)")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "حساب عميل"
        verbose_name_plural = "حسابات العملاء"
        ordering = ['-current_balance']

    def __str__(self):
        return f"{self.customer.name} (مديونية: {self.current_balance:,.2f} ج.م)"

    @classmethod
    def get_or_create_for_customer(cls, customer):
        obj, _ = cls.objects.get_or_create(customer=customer, defaults={
            'credit_limit': customer.credit_limit,
            'credit_period_days': customer.credit_period_days,
        })
        return obj


class CustomerTransaction(models.Model):
    TX_TYPES = [
        ('debit', 'مدين / Debit (فاتورة مبيعات)'),
        ('credit', 'دائن / Credit (تحصيل نقدية أو مردودات)'),
    ]

    serial = models.PositiveIntegerField(unique=True, db_index=True, verbose_name="رقم الحركة")
    account = models.ForeignKey(CustomerAccount, on_delete=models.CASCADE, related_name="transactions", verbose_name="حساب العميل")
    transaction_type = models.CharField(max_length=10, choices=TX_TYPES, verbose_name="نوع القيد")
    reason = models.CharField(max_length=30, choices=[('sales', 'فاتورة بيع'), ('collection', 'تحصيل نقدية'), ('sales_return', 'مرتجع')], default='sales')
    transaction_date = models.DateField(default=timezone.now, db_index=True, verbose_name="تاريخ القيد")
    due_date = models.DateField(null=True, blank=True, verbose_name="تاريخ الاستحقاق")
    
    debit = models.DecimalField(max_digits=14, decimal_places=2, default=0.00, verbose_name="مدين (ج.م)")
    credit = models.DecimalField(max_digits=14, decimal_places=2, default=0.00, verbose_name="دائن (ج.م)")
    running_balance = models.DecimalField(max_digits=14, decimal_places=2, default=0.00, verbose_name="الرصيد بعد الحركة (ج.م)")
    
    description = models.CharField(max_length=255, verbose_name="التوصيف")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "حركة حساب عميل"
        verbose_name_plural = "عمليات وحركات العملاء"
        ordering = ['-serial']

    def save(self, *args, **kwargs):
        if not self.serial:
            max_s = CustomerTransaction.objects.aggregate(models.Max('serial'))['serial__max'] or 20000
            self.serial = max_s + 1
        super().save(*args, **kwargs)


class SalesOrder(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending / قيد المراجعة'),
        ('manager_approval', 'Manager Approval / معتمد من الإدارة'),
        ('rejected', 'Rejected / مرفوض'),
        ('preparing', 'Preparing / جاري التجهيز بالمخزن'),
        ('delivered', 'Delivered / تم التسليم'),
        ('invoiced', 'Invoiced / تمت الفوترة'),
        ('cancelled', 'Cancelled / ملغي'),
    ]

    serial_num = models.PositiveIntegerField(unique=True, db_index=True, verbose_name="رقم المسلسل")
    order_number = models.CharField(max_length=50, unique=True, verbose_name="رقم أمر البيع")
    customer = models.ForeignKey(Contact, on_delete=models.PROTECT, related_name="sales_orders", verbose_name="العميل")
    delivery_address = models.ForeignKey(ContactAddress, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="عنوان التوصيل")
    source_warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="sales_orders", verbose_name="مخزن الصرف")
    
    order_date = models.DateField(default=timezone.now, verbose_name="تاريخ الطلب")
    delivery_date = models.DateField(null=True, blank=True, verbose_name="تاريخ التسليم")
    due_date = models.DateField(null=True, blank=True, db_index=True, verbose_name="تاريخ الاستحقاق")
    
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='pending', db_index=True, verbose_name="الحالة")
    memo = models.OneToOneField(InventoryMemo, on_delete=models.SET_NULL, null=True, blank=True, related_name="sales_order", verbose_name="إذن صرف المخزن")
    
    grand_total = models.DecimalField(max_digits=14, decimal_places=2, default=0.00, verbose_name="إجمالي القيمة (ج.م)")
    notes = models.TextField(blank=True, verbose_name="ملاحظات")
    rejection_reason = models.TextField(blank=True, default='', verbose_name="سبب الرفض")
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="approved_sales_orders", verbose_name="معتمد بواسطة")
    approved_at = models.DateTimeField(null=True, blank=True, verbose_name="تاريخ الاعتماد")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_sales_orders", verbose_name="المندوب / المنشئ")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "أمر بيع"
        verbose_name_plural = "أوامر البيع"
        ordering = ['-serial_num']

    @property
    def status_display_ar(self):
        mapping = {
            'pending': 'قيد المراجعة والاعتماد',
            'manager_approval': 'معتمد من الإدارة',
            'rejected': 'مرفوض',
            'preparing': 'جاري التجهيز بالمخزن',
            'delivered': 'تم التسليم',
            'invoiced': 'تمت الفوترة',
            'cancelled': 'ملغي',
        }
        return mapping.get(self.status, self.get_status_display())

    @property
    def status_badge_class(self):
        mapping = {
            'pending': 'bg-amber-100 text-amber-800 border-amber-300',
            'manager_approval': 'bg-teal-100 text-teal-800 border-teal-300',
            'rejected': 'bg-rose-100 text-rose-800 border-rose-300',
            'preparing': 'bg-sky-100 text-sky-800 border-sky-300',
            'delivered': 'bg-emerald-100 text-emerald-800 border-emerald-300',
            'invoiced': 'bg-purple-100 text-purple-800 border-purple-300',
            'cancelled': 'bg-slate-100 text-slate-800 border-slate-300',
        }
        return mapping.get(self.status, 'bg-gray-100 text-gray-800 border-gray-300')

    @property
    def total_paid(self):
        """Total payments collected and linked to this sales order."""
        res = self.collections.all().aggregate(total=models.Sum('amount'))['total']
        return res or Decimal('0.00')

    @property
    def outstanding_balance(self):
        """Remaining unpaid balance on this sales order."""
        return max(Decimal('0.00'), self.grand_total - self.total_paid)

    @property
    def is_paid(self):
        return self.grand_total > Decimal('0.00') and self.outstanding_balance <= Decimal('0.00')

    @property
    def is_overdue(self):
        if not self.due_date:
            return False
        return self.due_date < timezone.now().date() and self.outstanding_balance > Decimal('0.00')

    def save(self, *args, **kwargs):
        if not self.serial_num:
            max_s = SalesOrder.objects.aggregate(models.Max('serial_num'))['serial_num__max'] or 500
            self.serial_num = max_s + 1
            self.order_number = f"SO-{self.serial_num}"
        super().save(*args, **kwargs)


class SalesOrderItem(models.Model):
    order = models.ForeignKey(SalesOrder, on_delete=models.CASCADE, related_name="items", verbose_name="أمر البيع")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, verbose_name="المنتج")
    quantity = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="الكمية")
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="سعر البيع للوحدة")
    subtotal = models.DecimalField(max_digits=14, decimal_places=2, default=0.00, verbose_name="المجموع")

    class Meta:
        verbose_name = "بند أمر بيع"
        verbose_name_plural = "بنود أمر البيع"


class Collection(models.Model):
    serial_num = models.PositiveIntegerField(unique=True, db_index=True, verbose_name="رقم التحصيل")
    sales_order = models.ForeignKey(SalesOrder, on_delete=models.SET_NULL, null=True, blank=True, related_name="collections", verbose_name="أمر البيع المرتبط")
    customer = models.ForeignKey(Contact, on_delete=models.PROTECT, related_name="collections", verbose_name="العميل")
    vault = models.ForeignKey(Vault, on_delete=models.PROTECT, related_name="collections", verbose_name="الخزنة المودع بها")
    amount = models.DecimalField(max_digits=14, decimal_places=2, verbose_name="المبلغ المحصل (ج.م)")
    collection_date = models.DateField(default=timezone.now, verbose_name="تاريخ التحصيل")
    due_date = models.DateField(null=True, blank=True, verbose_name="تاريخ الاستحقاق")
    payment_method = models.CharField(max_length=20, default='cash', choices=[('cash', 'نقدي'), ('cheque', 'شيك')])
    notes = models.TextField(blank=True, verbose_name="ملاحظات")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="المحصل")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "سند تحصيل"
        verbose_name_plural = "التحصيلات"
        ordering = ['-serial_num']

    def save(self, *args, **kwargs):
        if not self.serial_num:
            max_s = Collection.objects.aggregate(models.Max('serial_num'))['serial_num__max'] or 3000
            self.serial_num = max_s + 1
        super().save(*args, **kwargs)


class SalesReturnOrder(models.Model):
    STATUS_CHOICES = [
        ('pending', 'قيد الانتظار'),
        ('approved', 'معتمد'),
        ('delivered', 'مستلم بالمخزن'),
        ('settled', 'مرحل بالحسابات'),
        ('cancelled', 'ملغي'),
    ]

    serial_num = models.PositiveIntegerField(unique=True, db_index=True, verbose_name="رقم المسلسل")
    order_number = models.CharField(max_length=50, unique=True, verbose_name="رقم إشعار المرتجع")
    customer = models.ForeignKey(Contact, on_delete=models.PROTECT, related_name="sales_return_orders", verbose_name="العميل")
    target_warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, null=True, blank=True, related_name="sales_return_orders", verbose_name="مخزن الاستلام")
    order_date = models.DateField(default=timezone.now, verbose_name="تاريخ المرتجع")
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='pending', db_index=True, verbose_name="الحالة")
    grand_total = models.DecimalField(max_digits=14, decimal_places=2, default=0.00, verbose_name="إجمالي القيمة (ج.م)")
    notes = models.TextField(blank=True, verbose_name="ملاحظات")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="المنشئ")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "مرتجع مبيعات"
        verbose_name_plural = "مرتجعات المبيعات"
        ordering = ['-serial_num']

    def __str__(self):
        return f"{self.order_number} ({self.customer.name})"


class SalesReturnOrderItem(models.Model):
    order = models.ForeignKey(SalesReturnOrder, on_delete=models.CASCADE, related_name="items", verbose_name="مرتجع المبيعات")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, verbose_name="المنتج")
    quantity = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="الكمية المرتجعة")
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="سعر الوحدة")
    subtotal = models.DecimalField(max_digits=14, decimal_places=2, default=0.00, verbose_name="الإجمالي")
    batch_number = models.CharField(max_length=100, blank=True, verbose_name="رقم التشغيل")
    expiry_date = models.DateField(null=True, blank=True, verbose_name="تاريخ الصلاحية")

    class Meta:
        verbose_name = "بند مرتجع مبيعات"
        verbose_name_plural = "بنود مرتجع المبيعات"

