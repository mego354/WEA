from decimal import Decimal
from django.db import models
from django.conf import settings
from django.utils import timezone
from contacts.models import Contact, ContactAddress
from catalog.models import Product
from inventory.models import Warehouse, InventoryMemo


class PurchaseOrder(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending / قيد الانتظار'),
        ('approved', 'Approved / معتمد'),
        ('picked', 'Picked / دخل المخزن'),
        ('settled', 'Settled / تم الترحيل للحسابات'),
        ('rejected', 'Rejected / مرفوض'),
        ('split', 'Split / مقسم'),
        ('cancelled', 'Cancelled / ملغي'),
    ]

    serial_num = models.PositiveIntegerField(unique=True, db_index=True, verbose_name="رقم المسلسل")
    order_number = models.CharField(max_length=50, unique=True, verbose_name="رقم الأمر")
    
    supplier = models.ForeignKey(Contact, on_delete=models.PROTECT, related_name="purchase_orders", verbose_name="المورد")
    delivery_address = models.ForeignKey(ContactAddress, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="عنوان التوصيل / الاستلام")
    target_warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="purchase_orders", verbose_name="مخزن الاستلام")
    
    order_date = models.DateField(default=timezone.now, verbose_name="تاريخ الطلب")
    expected_delivery_date = models.DateField(null=True, blank=True, verbose_name="تاريخ الاستلام المتوقع")
    due_date = models.DateField(null=True, blank=True, db_index=True, verbose_name="تاريخ الاستحقاق")
    
    delivery_agent = models.CharField(max_length=150, blank=True, verbose_name="مسئول التوصيل")
    delivery_time = models.CharField(max_length=100, blank=True, verbose_name="وقت التوصيل")

    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='pending', db_index=True, verbose_name="حالة الطلب")
    is_hold = models.BooleanField(default=False, verbose_name="معلق مؤقتاً (Hold)")
    is_canceled = models.BooleanField(default=False, verbose_name="ملغي")
    is_split = models.BooleanField(default=False, verbose_name="مقسم")
    parent_order = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name="split_orders", verbose_name="الطلب الأصلي المنفصل عنه")
    
    # Inventory & Accounting Linkage
    memo = models.OneToOneField(InventoryMemo, on_delete=models.SET_NULL, null=True, blank=True, related_name="purchase_order", verbose_name="إذن إضافة المخزن")

    stocked_at = models.DateTimeField(null=True, blank=True, verbose_name="تاريخ استلام البضاعة في المخزن")
    invoiced_at = models.DateTimeField(null=True, blank=True, verbose_name="تاريخ الترحيل للحسابات (الفوترة)")
    
    # Financial Totals & Calculations
    items_count = models.PositiveIntegerField(default=0, verbose_name="عدد الأصناف")
    items_quantity = models.DecimalField(max_digits=12, decimal_places=2, default=0.00, verbose_name="إجمالي الكميات")
    subtotal = models.DecimalField(max_digits=14, decimal_places=2, default=0.00, verbose_name="إجمالي الأصناف قبل الخصم (ج.م)")
    items_discount_total = models.DecimalField(max_digits=14, decimal_places=2, default=0.00, verbose_name="إجمالي خصومات الأصناف (ج.م)")
    custom_discount_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0.00, verbose_name="خصم إضافي %")
    custom_discount_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0.00, verbose_name="خصم إضافي (ج.م)")
    tax_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0.00, verbose_name="إجمالي الضريبة (ج.م)")
    shipping_fees = models.DecimalField(max_digits=14, decimal_places=2, default=0.00, verbose_name="مصاريف الشحن / التوصيل (ج.م)")
    grand_total = models.DecimalField(max_digits=14, decimal_places=2, default=0.00, verbose_name="المبلغ الإجمالي النهائي (ج.م)")

    notes = models.TextField(blank=True, verbose_name="ملاحظات")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_purchase_orders", verbose_name="المنشئ")
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="updated_purchase_orders", verbose_name="آخر تعديل بواسطة")
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="approved_purchase_orders", verbose_name="المعتمد")
    approved_at = models.DateTimeField(null=True, blank=True, verbose_name="تاريخ الاعتماد")
    rejection_reason = models.TextField(blank=True, default="", verbose_name="سبب الرفض")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="تاريخ التحديث")

    class Meta:
        verbose_name = "أمر مشتريات"
        verbose_name_plural = "أوامر المشتريات"
        ordering = ['-serial_num']

    def __str__(self):
        return f"{self.order_number} - {self.supplier.name}"

    def save(self, *args, **kwargs):
        if not self.serial_num:
            max_serial = PurchaseOrder.objects.aggregate(models.Max('serial_num'))['serial_num__max'] or 0
            self.serial_num = max_serial + 1
            self.order_number = f"#{self.serial_num}"
        super().save(*args, **kwargs)

    def recalculate_totals(self):
        """Calculates accurate financial breakdown from line items and discounts."""
        items = self.items.all()
        self.items_count = items.count()
        self.items_quantity = sum((item.quantity for item in items), Decimal('0.00'))
        
        raw_subtotal = sum((item.subtotal for item in items), Decimal('0.00'))
        items_disc = sum((item.discount_amount for item in items), Decimal('0.00'))
        items_tax = sum((item.tax_amount for item in items), Decimal('0.00'))

        self.subtotal = raw_subtotal
        self.items_discount_total = items_disc
        
        # After line item discounts
        after_items_disc = raw_subtotal - items_disc
        
        custom_disc_pct = Decimal(str(self.custom_discount_percentage or '0'))
        custom_disc_amt = Decimal(str(self.custom_discount_amount or '0'))
        shipping = Decimal(str(self.shipping_fees or '0'))

        # Order-level custom discount
        if custom_disc_pct > 0:
            custom_disc_amt = (after_items_disc * (custom_disc_pct / Decimal('100.0'))).quantize(Decimal('0.01'))
        
        self.custom_discount_amount = custom_disc_amt
        after_all_disc = max(Decimal('0.00'), after_items_disc - custom_disc_amt)
        self.tax_amount = items_tax
        self.grand_total = after_all_disc + self.tax_amount + shipping
        self.save(update_fields=[
            'items_count', 'items_quantity', 'subtotal', 'items_discount_total',
            'custom_discount_amount', 'tax_amount', 'shipping_fees', 'grand_total'
        ])

    @property
    def status_label_en(self):
        labels = {
            'pending': 'Pending',
            'approved': 'Approved',
            'picked': 'Picked',
            'settled': 'Settled',
            'rejected': 'Rejected',
            'split': 'Split',
            'cancelled': 'Cancelled'
        }
        return labels.get(self.status, self.status.capitalize())

    @property
    def status_label_ar(self):
        labels = {
            'pending': 'قيد الانتظار',
            'approved': 'معتمد',
            'picked': 'دخل المخزن',
            'settled': 'تم الترحيل للحسابات',
            'rejected': 'مرفوض',
            'split': 'مقسم',
            'cancelled': 'ملغي'
        }
        return labels.get(self.status, self.status)

    @property
    def status_badge_class(self):
        mapping = {
            'settled': 'bg-emerald-50 text-emerald-700 border border-emerald-200',
            'picked': 'bg-blue-50 text-blue-700 border border-blue-200',
            'approved': 'bg-green-50 text-green-700 border border-green-200',
            'pending': 'bg-amber-50 text-amber-700 border border-amber-200',
            'rejected': 'bg-red-50 text-red-700 border border-red-200',
            'cancelled': 'bg-slate-100 text-slate-700 border border-slate-300',
            'split': 'bg-purple-50 text-purple-700 border border-purple-200',
        }
        return mapping.get(self.status, 'bg-slate-50 text-slate-600 border border-slate-200')

    @property
    def total_paid(self):
        """Total settled/cleared vendor payments explicitly linked to this purchase order."""
        res = self.vendor_payments.filter(status='cleared').aggregate(total=models.Sum('amount'))['total']
        return res or Decimal('0.00')

    @property
    def outstanding_balance(self):
        """Remaining unpaid balance on this purchase order."""
        return max(Decimal('0.00'), self.grand_total - self.total_paid)

    @property
    def is_paid(self):
        return self.grand_total > Decimal('0.00') and self.outstanding_balance <= Decimal('0.00')

    @property
    def is_overdue(self):
        if not self.due_date:
            return False
        return self.due_date < timezone.now().date() and self.outstanding_balance > Decimal('0.00')


class PurchaseOrderItem(models.Model):
    order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name="items", verbose_name="أمر الشراء")
    item_order = models.PositiveSmallIntegerField(default=1, verbose_name="ترتيب البند")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="purchase_order_items", verbose_name="المنتج")
    
    quantity = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="الكمية")
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="سعر تكلفة الوحدة (ج.م)")
    
    product_batch_number = models.CharField(max_length=100, blank=True, verbose_name="رقم التشغيل (Batch No)")
    product_expiry_date = models.DateField(null=True, blank=True, verbose_name="تاريخ الصلاحية")
    
    discount_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0.00, verbose_name="خصم الصنف %")
    discount_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0.00, verbose_name="قيمة خصم الصنف")
    
    tax_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0.00, verbose_name="الضريبة %")
    tax_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0.00, verbose_name="قيمة الضريبة")
    
    subtotal = models.DecimalField(max_digits=14, decimal_places=2, default=0.00, verbose_name="المجموع قبل الخصم")
    total_price = models.DecimalField(max_digits=14, decimal_places=2, default=0.00, verbose_name="الصافي الإجمالي")

    class Meta:
        verbose_name = "بند أمر شراء"
        verbose_name_plural = "بنود أوامر الشراء"
        ordering = ['item_order']

    def save(self, *args, **kwargs):
        self.subtotal = (Decimal(str(self.quantity)) * Decimal(str(self.unit_price))).quantize(Decimal('0.01'))
        disc_pct = Decimal(str(self.discount_percentage or '0'))
        disc_amt = Decimal(str(self.discount_amount or '0'))
        tax_pct = Decimal(str(self.tax_percentage or '0'))

        if disc_pct > 0 and disc_amt == Decimal('0.00'):
            disc_amt = (self.subtotal * (disc_pct / Decimal('100.0'))).quantize(Decimal('0.01'))

        self.discount_amount = disc_amt
        after_disc = max(Decimal('0.00'), self.subtotal - disc_amt)

        if tax_pct > 0:
            self.tax_amount = (after_disc * (tax_pct / Decimal('100.0'))).quantize(Decimal('0.01'))
        else:
            self.tax_amount = Decimal('0.00')

        self.total_price = after_disc + self.tax_amount
        super().save(*args, **kwargs)


class PurchaseOrderAttachment(models.Model):
    order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name="attachments", verbose_name="أمر الشراء")
    title = models.CharField(max_length=200, verbose_name="عنوان المرفق")
    file = models.FileField(upload_to="purchase_orders/attachments/%Y/%m/", verbose_name="الملف")
    file_type = models.CharField(max_length=50, blank=True, verbose_name="نوع الملف")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "مرفق أمر شراء"
        verbose_name_plural = "مرفقات أوامر الشراء"


class PurchaseOrderComment(models.Model):
    order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name="comments", verbose_name="أمر الشراء")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="po_comments", verbose_name="الكاتب")
    text = models.TextField(verbose_name="نص التعليق")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء")

    class Meta:
        verbose_name = "تعليق أمر شراء"
        verbose_name_plural = "تعليقات أوامر الشراء"
        ordering = ['-created_at']


class PurchaseReturnOrder(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending / قيد الانتظار'),
        ('approved', 'Approved / معتمد'),
        ('delivered', 'Delivered / خرج من المخزن'),
        ('settled', 'Settled / تم الترحيل للحسابات'),
        ('cancelled', 'Cancelled / ملغي'),
    ]

    serial_num = models.PositiveIntegerField(unique=True, db_index=True, verbose_name="رقم المسلسل")
    order_number = models.CharField(max_length=50, unique=True, verbose_name="رقم أمر الإرجاع")

    purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.SET_NULL, null=True, blank=True, related_name="return_orders", verbose_name="أمر الشراء الأصلي")
    supplier = models.ForeignKey(Contact, on_delete=models.PROTECT, related_name="purchase_return_orders", verbose_name="المورد")
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="purchase_return_orders", verbose_name="مخزن الإرجاع")

    order_date = models.DateField(default=timezone.now, verbose_name="تاريخ الإرجاع")
    delivery_agent = models.CharField(max_length=150, blank=True, verbose_name="مسئول الاستلام / الشحن")
    delivery_time = models.CharField(max_length=100, blank=True, verbose_name="وقت الاستلام")

    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='pending', db_index=True, verbose_name="حالة المرتجع")

    memo = models.OneToOneField(InventoryMemo, on_delete=models.SET_NULL, null=True, blank=True, related_name="purchase_return_order", verbose_name="إذن صرف المخزن")
    dispatched_at = models.DateTimeField(null=True, blank=True, verbose_name="تاريخ خروج البضاعة من المخزن")
    settled_at = models.DateTimeField(null=True, blank=True, verbose_name="تاريخ الترحيل للحسابات (إثبات إشعار الخصم)")

    items_count = models.PositiveIntegerField(default=0, verbose_name="عدد الأصناف")
    items_quantity = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'), verbose_name="إجمالي الكميات المرتجعة")
    subtotal = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'), verbose_name="المجموع قبل الضريبة (ج.م)")
    tax_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'), verbose_name="قيمة الضريبة (ج.م)")
    grand_total = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'), verbose_name="إجمالي قيمة المرتجع (ج.م)")

    notes = models.TextField(blank=True, verbose_name="ملاحظات وأسباب الإرجاع")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_purchase_returns", verbose_name="المنشئ")
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="updated_purchase_returns", verbose_name="آخر تعديل بواسطة")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="تاريخ التحديث")

    class Meta:
        verbose_name = "أمر إرجاع مشتريات"
        verbose_name_plural = "أوامر إرجاع المشتريات"
        ordering = ['-serial_num']

    def __str__(self):
        return f"{self.order_number} - {self.supplier.name}"

    def save(self, *args, **kwargs):
        if not self.serial_num:
            max_serial = PurchaseReturnOrder.objects.aggregate(models.Max('serial_num'))['serial_num__max'] or 0
            self.serial_num = max_serial + 1
            self.order_number = f"#RO-{self.serial_num}"
        super().save(*args, **kwargs)

    def recalculate_totals(self):
        items = self.items.all()
        self.items_count = items.count()
        self.items_quantity = sum((item.quantity for item in items), Decimal('0.00'))
        self.subtotal = sum((item.subtotal for item in items), Decimal('0.00'))
        self.tax_amount = sum((item.tax_amount for item in items), Decimal('0.00'))
        self.grand_total = sum((item.total_price for item in items), Decimal('0.00'))
        self.save(update_fields=['items_count', 'items_quantity', 'subtotal', 'tax_amount', 'grand_total'])

    @property
    def status_label_en(self):
        labels = {
            'pending': 'Pending',
            'approved': 'Approved',
            'delivered': 'Delivered',
            'settled': 'Settled',
            'cancelled': 'Cancelled'
        }
        return labels.get(self.status, self.status.capitalize())

    @property
    def status_label_ar(self):
        labels = {
            'pending': 'قيد الانتظار',
            'approved': 'معتمد',
            'delivered': 'خرج من المخزن',
            'settled': 'تم الترحيل للحسابات',
            'cancelled': 'ملغي'
        }
        return labels.get(self.status, self.status)

    @property
    def status_badge_class(self):
        mapping = {
            'settled': 'bg-emerald-50 text-emerald-700 border border-emerald-200',
            'delivered': 'bg-blue-50 text-blue-700 border border-blue-200',
            'approved': 'bg-green-50 text-green-700 border border-green-200',
            'pending': 'bg-amber-50 text-amber-700 border border-amber-200',
            'cancelled': 'bg-slate-100 text-slate-700 border border-slate-300',
        }
        return mapping.get(self.status, 'bg-slate-50 text-slate-600 border border-slate-200')


class PurchaseReturnOrderItem(models.Model):
    return_order = models.ForeignKey(PurchaseReturnOrder, on_delete=models.CASCADE, related_name="items", verbose_name="أمر الإرجاع")
    item_order = models.PositiveSmallIntegerField(default=1, verbose_name="ترتيب البند")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="purchase_return_items", verbose_name="المنتج")

    quantity = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="الكمية المرتجعة")
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="سعر التكلفة المرتجع (ج.م)")

    product_batch_number = models.CharField(max_length=100, blank=True, verbose_name="رقم التشغيل (Batch No)")
    product_expiry_date = models.DateField(null=True, blank=True, verbose_name="تاريخ الصلاحية")

    tax_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0.00, verbose_name="الضريبة %")
    tax_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0.00, verbose_name="قيمة الضريبة")

    subtotal = models.DecimalField(max_digits=14, decimal_places=2, default=0.00, verbose_name="المجموع قبل الضريبة")
    total_price = models.DecimalField(max_digits=14, decimal_places=2, default=0.00, verbose_name="الصافي الإجمالي")

    class Meta:
        verbose_name = "بند أمر إرجاع مشتريات"
        verbose_name_plural = "بنود أوامر إرجاع المشتريات"
        ordering = ['item_order']

    def save(self, *args, **kwargs):
        self.subtotal = (Decimal(str(self.quantity)) * Decimal(str(self.unit_price))).quantize(Decimal('0.01'))
        tax_pct = Decimal(str(self.tax_percentage or '0'))
        if tax_pct > 0:
            self.tax_amount = (self.subtotal * (tax_pct / Decimal('100.0'))).quantize(Decimal('0.01'))
        else:
            self.tax_amount = Decimal('0.00')
        self.total_price = self.subtotal + self.tax_amount
        super().save(*args, **kwargs)

