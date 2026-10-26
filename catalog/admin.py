from django.contrib import admin
from django.utils.html import format_html
from .models import ProductCategory, Product, ProductVolumeDiscountTier, ProductPriceList


class ProductVolumeDiscountTierInline(admin.TabularInline):
    model = ProductVolumeDiscountTier
    extra = 1


class ProductPriceListInline(admin.TabularInline):
    model = ProductPriceList
    extra = 1


@admin.register(ProductCategory)
class ProductCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'products_count', 'created_at')
    search_fields = ('name', 'code', 'description')

    def products_count(self, obj):
        return obj.products.count()
    products_count.short_description = "عدد المنتجات"


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        'sku_code', 'name', 'category', 'retail_price_display',
        'default_purchase_cost_display', 'unit', 'sellable_badge',
        'is_active_badge', 'barcode'
    )
    list_filter = ('category', 'sellable', 'is_active', 'has_volume_discounts')
    search_fields = ('name', 'sku_code', 'barcode', 'description')
    inlines = [ProductVolumeDiscountTierInline, ProductPriceListInline]
    actions = ['mark_sellable', 'mark_unsellable', 'mark_active', 'mark_inactive']

    fieldsets = (
        ('بيانات المنتج الأساسية', {
            'fields': ('category', 'sku_code', 'name', 'description', 'unit', 'barcode', 'thumbnail')
        }),
        ('التسعير والتكلفة والضريبة', {
            'fields': ('retail_price', 'default_purchase_cost', 'tax_percentage')
        }),
        ('حالة التداول والبيع والتعبئة', {
            'fields': ('sellable', 'is_active', 'has_volume_discounts', 'packing_boxes', 'packing_cartons', 'created_by')
        }),
    )

    def retail_price_display(self, obj):
        return f"{obj.retail_price:,.2f} ج.م"
    retail_price_display.short_description = "سعر البيع"

    def default_purchase_cost_display(self, obj):
        return f"{obj.default_purchase_cost:,.2f} ج.م"
    default_purchase_cost_display.short_description = "سعر التكلفة"

    def sellable_badge(self, obj):
        if obj.sellable:
            return format_html('<span class="admin-pill admin-pill-success">معروض للبيع</span>')
        return format_html('<span class="admin-pill admin-pill-warning">غير مخصص للبيع</span>')
    sellable_badge.short_description = "قابلية البيع"

    def is_active_badge(self, obj):
        if obj.is_active:
            return format_html('<span class="admin-pill admin-pill-info">نشط</span>')
        return format_html('<span class="admin-pill admin-pill-danger">معطل</span>')
    is_active_badge.short_description = "الحالة"

    @admin.action(description="تحديد الأصناف كمعروضة للبيع")
    def mark_sellable(self, request, queryset):
        queryset.update(sellable=True)

    @admin.action(description="استبعاد الأصناف من البيع")
    def mark_unsellable(self, request, queryset):
        queryset.update(sellable=False)

    @admin.action(description="تفعيل الأصناف المحددة")
    def mark_active(self, request, queryset):
        queryset.update(is_active=True)

    @admin.action(description="تعطيل الأصناف المحددة")
    def mark_inactive(self, request, queryset):
        queryset.update(is_active=False)


@admin.register(ProductVolumeDiscountTier)
class ProductVolumeDiscountTierAdmin(admin.ModelAdmin):
    list_display = ('product', 'min_quantity', 'discount_percentage')
    list_filter = ('product__category',)
    search_fields = ('product__name', 'product__sku_code')


@admin.register(ProductPriceList)
class ProductPriceListAdmin(admin.ModelAdmin):
    list_display = ('name', 'product', 'price')
    list_filter = ('name',)
    search_fields = ('name', 'product__name')
