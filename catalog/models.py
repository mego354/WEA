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
    barcode = models.CharField(max_length=100, blank=True, verbose_name="باركود")
    
    unit = models.CharField(max_length=30, default="عبوة (Pack)", verbose_name="وحدة القياس")
    thumbnail = models.ImageField(upload_to="products/thumbnails/", null=True, blank=True, verbose_name="صورة المنتج")
    
    sellable = models.BooleanField(default=True, verbose_name="قابل للبيع")
    is_active = models.BooleanField(default=True, verbose_name="نشط")

    # Advanced Packaging & Volume Discounts
    has_volume_discounts = models.BooleanField(default=False, verbose_name="تفعيل خصومات الكمية")
    packing_boxes = models.CharField(max_length=100, blank=True, verbose_name="تعبئة العلب")
    packing_cartons = models.CharField(max_length=100, blank=True, verbose_name="تعبئة الكراتين")

    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="المنشئ")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="تاريخ التحديث")

    class Meta:
        verbose_name = "منتج"
        verbose_name_plural = "المنتجات"
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.sku_code})"

    @property
    def price_display(self):
        return f"{self.retail_price:,.3f} جنيه"

    @classmethod
    def get_eligible_for_visits(cls):
        """
        Authoritative central query for visit operations:
        Only active products intended for sale (sellable=True) are eligible for new detailing.
        """
        return cls.objects.filter(is_active=True, sellable=True).order_by('name')


class ProductVolumeDiscountTier(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="volume_discounts", verbose_name="المنتج")
    min_quantity = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="الحد الأدنى للكمية")
    discount_percentage = models.DecimalField(max_digits=5, decimal_places=2, verbose_name="نسبة الخصم %")

    class Meta:
        verbose_name = "شريحة خصم كمية"
        verbose_name_plural = "شرائح خصومات الكمية"
        ordering = ['min_quantity']

    def __str__(self):
        return f"{self.product.name} >= {self.min_quantity}: {self.discount_percentage}%"


class ProductPriceList(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="price_lists", verbose_name="المنتج")
    name = models.CharField(max_length=150, verbose_name="اسم قائمة الأسعار")
    price = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="السعر المحدد (ج.م)")

    class Meta:
        verbose_name = "قائمة أسعار لمنتج"
        verbose_name_plural = "قوائم أسعار المنتجات"
        ordering = ['name']

    def __str__(self):
        return f"{self.name} - {self.product.name}: {self.price} ج.م"

