from django.contrib import admin
from django.utils.html import format_html
from .models import Warehouse, InventoryStock, InventoryLot, InventoryMemo, InventoryMemoItem


class InventoryLotInline(admin.TabularInline):
    model = InventoryLot
    extra = 1


class InventoryMemoItemInline(admin.TabularInline):
    model = InventoryMemoItem
    extra = 1


@admin.register(Warehouse)
class WarehouseAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'is_main_badge', 'manager', 'is_active_badge', 'stocks_count', 'created_at')
    list_filter = ('is_main', 'is_active')
    search_fields = ('name', 'code', 'address')

    def is_main_badge(self, obj):
        if obj.is_main:
            return format_html('<span class="admin-pill admin-pill-purple">رئيسي</span>')
        return format_html('<span class="admin-pill admin-pill-neutral">فرعي</span>')
    is_main_badge.short_description = "نوع المخزن"

    def is_active_badge(self, obj):
        if obj.is_active:
            return format_html('<span class="admin-pill admin-pill-success">نشط</span>')
        return format_html('<span class="admin-pill admin-pill-danger">معطل</span>')
    is_active_badge.short_description = "الحالة"

    def stocks_count(self, obj):
        return obj.stocks.count()
    stocks_count.short_description = "عدد الأصناف"


@admin.register(InventoryStock)
class InventoryStockAdmin(admin.ModelAdmin):
    list_display = (
        'product', 'warehouse', 'qty_on_hand', 'qty_reserved',
        'qty_available_display', 'product_cost_display', 'total_cost_display', 'updated_at'
    )
    list_filter = ('warehouse', 'product__category')
    search_fields = ('product__name', 'product__sku_code', 'warehouse__name')
    inlines = [InventoryLotInline]

    def qty_available_display(self, obj):
        return f"{obj.qty_available:,.2f}"
    qty_available_display.short_description = "الكمية المتاحة"

    def product_cost_display(self, obj):
        return f"{obj.product_cost:,.2f} ج.م"
    product_cost_display.short_description = "متوسط التكلفة"

    def total_cost_display(self, obj):
        return f"{obj.total_cost:,.2f} ج.م"
    total_cost_display.short_description = "إجمالي القيمة"


@admin.register(InventoryLot)
class InventoryLotAdmin(admin.ModelAdmin):
    list_display = ('stock', 'batch_number', 'expiry_date', 'quantity')
    list_filter = ('expiry_date', 'stock__warehouse')
    search_fields = ('batch_number', 'stock__product__name')


@admin.register(InventoryMemo)
class InventoryMemoAdmin(admin.ModelAdmin):
    list_display = ('memo_number', 'memo_type_badge', 'warehouse', 'statement', 'status_badge', 'applied_at', 'created_by')
    list_filter = ('memo_type', 'status', 'warehouse')
    search_fields = ('memo_number', 'statement', 'notes')
    inlines = [InventoryMemoItemInline]
    date_hierarchy = 'created_at'

    def memo_type_badge(self, obj):
        if obj.memo_type == 'inward':
            return format_html('<span class="admin-pill admin-pill-success">إذن إضافة</span>')
        return format_html('<span class="admin-pill admin-pill-danger">إذن صرف</span>')
    memo_type_badge.short_description = "نوع الإذن"

    def status_badge(self, obj):
        mapping = {
            'applied': 'admin-pill-success',
            'draft': 'admin-pill-warning',
            'cancelled': 'admin-pill-danger',
        }
        cls = mapping.get(obj.status, 'admin-pill-neutral')
        return format_html('<span class="admin-pill {}">{}</span>', cls, obj.get_status_display())
    status_badge.short_description = "الحالة"


@admin.register(InventoryMemoItem)
class InventoryMemoItemAdmin(admin.ModelAdmin):
    list_display = ('memo', 'product', 'quantity', 'unit_cost', 'batch_number', 'expiry_date')
    list_filter = ('memo__memo_type', 'memo__warehouse')
    search_fields = ('product__name', 'memo__memo_number', 'batch_number')
