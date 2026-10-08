from django.db import models
from django.conf import settings


class ProductCategory(models.Model):
    name = models.CharField(max_length=150, unique=True, verbose_name="اسم التصنيف")
    code = models.CharField(max_length=50, unique=True, verbose_name="كود التصنيف")
    description = models.TextField(blank=True, verbose_name="الوصف")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء")

    class Meta:
        verbose_name = "تصنيف المنتجات"
        verbose_name_plural = "تصنيفات المنتجات"
        ordering = ['name']

    def __str__(self):
        return self.name


class Product(models.Model):
    category = models.ForeignKey(ProductCategory, on_delete=models.PROTECT, related_name="products", verbose_name="التصنيف")
    sku_code = models.CharField(max_length=60, unique=True, db_index=True, verbose_name="كود المنتج (SKU)")
    name = models.CharField(max_length=255, db_index=True, verbose_name="اسم المنتج")
    description = models.TextField(blank=True, verbose_name="الوصف الدوائي / التجاري")
    
    retail_price = models.DecimalField(max_digits=12, decimal_places=2, default=0.00, verbose_name="سعر البيع للجمهور (ج.م)")
    default_purchase_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0.00, verbose_name="سعر تكلفة الشراء الافتراضي (ج.م)")
    tax_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0.00, verbose_name="نسبة الضريبة %")
    
    unit = models.CharField(max_length=30, default="عبوة (Pack)", verbose_name="وحدة القياس")
    thumbnail = models.ImageField(upload_to="products/thumbnails/", null=True, blank=True, verbose_name="صورة المنتج")
    
    sellable = models.BooleanField(default=True, verbose_name="قابل للبيع")
    is_active = models.BooleanField(default=True, verbose_name="نشط")

    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="المنشئ")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="تاريخ التحديث")

    class Meta:
        verbose_name = "منتج"
        verbose_name_plural = "المنتجات"
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.sku_code})"
