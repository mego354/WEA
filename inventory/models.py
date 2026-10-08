from decimal import Decimal
from django.db import models
from django.conf import settings
from catalog.models import Product


class Warehouse(models.Model):
    name = models.CharField(max_length=150, unique=True, verbose_name="اسم المخزن")
    code = models.CharField(max_length=50, unique=True, verbose_name="كود المخزن")
    is_main = models.BooleanField(default=False, verbose_name="المخزن الرئيسي")
    is_active = models.BooleanField(default=True, verbose_name="نشط")
    address = models.TextField(blank=True, verbose_name="عنوان المخزن")
    manager = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="أمين المخزن / المسئول")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء")

    class Meta:
        verbose_name = "مخزن"
        verbose_name_plural = "المخازن"
        ordering = ['-is_main', 'name']

    def __str__(self):
        return self.name


class InventoryStock(models.Model):
    warehouse = models.ForeignKey(Warehouse, on_delete=models.CASCADE, related_name="stocks", verbose_name="المخزن")
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="stocks", verbose_name="المنتج")
    qty_on_hand = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'), verbose_name="الكمية في المخزن")
    qty_reserved = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'), verbose_name="الكمية المحجوزة")
    product_cost = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'), verbose_name="متوسط تكلفة الوحدة (ج.م)")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="تاريخ آخر حركة")

    class Meta:
        verbose_name = "رصيد مخزون"
        verbose_name_plural = "أرصدة المخزون"
        unique_together = ('warehouse', 'product')
        ordering = ['warehouse', 'product']

    def __str__(self):
        return f"{self.product.name} @ {self.warehouse.name}"

    @property
    def qty_available(self):
        return max(Decimal('0.00'), Decimal(str(self.qty_on_hand)) - Decimal(str(self.qty_reserved)))

    @property
    def total_cost(self):
        return (Decimal(str(self.qty_on_hand)) * Decimal(str(self.product_cost))).quantize(Decimal('0.01'))

    @property
    def total_retail_value(self):
        return (Decimal(str(self.qty_on_hand)) * Decimal(str(self.product.retail_price))).quantize(Decimal('0.01'))


class InventoryLot(models.Model):
    stock = models.ForeignKey(InventoryStock, on_delete=models.CASCADE, related_name="lots", verbose_name="رصيد المخزون")
    batch_number = models.CharField(max_length=100, db_index=True, verbose_name="رقم التشغيل (Batch No)")
    expiry_date = models.DateField(null=True, blank=True, db_index=True, verbose_name="تاريخ الصلاحية")
    quantity = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'), verbose_name="الكمية")

    class Meta:
        verbose_name = "تشغيلة مخزون"
        verbose_name_plural = "تشغيلات وتواريخ صلاحية المخزون"
        ordering = ['expiry_date']

    def __str__(self):
        return f"تشغيلة {self.batch_number} (صلاحية: {self.expiry_date}) - {self.quantity}"


class InventoryMemo(models.Model):
    MEMO_TYPES = [
        ('inward', 'إذن إضافة مخزنية'),
        ('outward', 'إذن صرف / خصم مخزني'),
    ]

    STATUS_CHOICES = [
        ('draft', 'مسودة'),
        ('applied', 'منفّذ'),
        ('cancelled', 'ملغي'),
    ]

    memo_number = models.CharField(max_length=60, unique=True, verbose_name="رقم الإذن")
    memo_type = models.CharField(max_length=20, choices=MEMO_TYPES, verbose_name="نوع الإذن")
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="memos", verbose_name="المخزن")
    statement = models.CharField(max_length=255, verbose_name="البيان / سبب الإذن")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='applied', verbose_name="الحالة")
    applied_at = models.DateTimeField(null=True, blank=True, verbose_name="تاريخ التنفيذ")
    notes = models.TextField(blank=True, verbose_name="ملاحظات")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="المسئول")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء")

    class Meta:
        verbose_name = "إذن مخزن"
        verbose_name_plural = "أذونات المخازن"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.memo_number} - {self.get_memo_type_display()}"


class InventoryMemoItem(models.Model):
    memo = models.ForeignKey(InventoryMemo, on_delete=models.CASCADE, related_name="items", verbose_name="الإذن")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, verbose_name="المنتج")
    quantity = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="الكمية")
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0.00, verbose_name="تكلفة الوحدة")
    batch_number = models.CharField(max_length=100, blank=True, verbose_name="رقم التشغيل")
    expiry_date = models.DateField(null=True, blank=True, verbose_name="تاريخ الصلاحية")

    class Meta:
        verbose_name = "بند إذن مخزن"
        verbose_name_plural = "بنود أذونات المخازن"

    def __str__(self):
        return f"{self.product.name} ({self.quantity})"
