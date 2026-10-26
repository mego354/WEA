from django.contrib import admin
from django.utils.html import format_html
from django.utils import timezone
from .models import PurchaseOrder, PurchaseOrderItem, PurchaseReturnOrder, PurchaseReturnOrderItem


class PurchaseOrderItemInline(admin.TabularInline):
    model = PurchaseOrderItem
    extra = 1
    fields = ('item_order', 'product', 'quantity', 'unit_price', 'discount_percentage', 'tax_percentage', 'subtotal', 'total_price')
    readonly_fields = ('subtotal', 'total_price')


class PurchaseReturnOrderItemInline(admin.TabularInline):
    model = PurchaseReturnOrderItem
    extra = 1
    fields = ('item_order', 'product', 'quantity', 'unit_price', 'tax_percentage', 'subtotal', 'total_price')
    readonly_fields = ('subtotal', 'total_price')


@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(admin.ModelAdmin):
    list_display = (
        'order_number', 'supplier', 'target_warehouse', 'order_date',
        'status_badge', 'grand_total_display', 'items_count',
        'created_by', 'approved_by', 'approved_at'
    )
    list_filter = ('status', 'target_warehouse', 'order_date', 'is_hold', 'is_canceled')
    search_fields = ('order_number', 'supplier__name', 'notes')
    date_hierarchy = 'order_date'
    inlines = [PurchaseOrderItemInline]
    readonly_fields = (
        'serial_num', 'order_number', 'items_count', 'items_quantity',
        'subtotal', 'items_discount_total', 'grand_total', 'created_at', 'updated_at'
    )
    actions = ['approve_selected_orders', 'mark_as_hold']

    fieldsets = (
        ('بيانات أمر الشراء', {
            'fields': ('serial_num', 'order_number', 'supplier', 'target_warehouse', 'order_date', 'expected_delivery_date', 'status', 'is_hold')
        }),
        ('التوصيل والاستلام', {
            'fields': ('delivery_address', 'delivery_agent', 'delivery_time', 'memo', 'stocked_at')
        }),
        ('القيم المالية والخصومات', {
            'fields': ('items_count', 'items_quantity', 'subtotal', 'items_discount_total', 'custom_discount_percentage', 'custom_discount_amount', 'tax_amount', 'shipping_fees', 'grand_total')
        }),
        ('الاعتماد والملاحظات', {
            'fields': ('approved_by', 'approved_at', 'rejection_reason', 'notes', 'created_by', 'updated_by', 'created_at', 'updated_at')
        }),
    )

    def status_badge(self, obj):
        mapping = {
            'approved': 'admin-pill-success',
            'picked': 'admin-pill-info',
            'settled': 'admin-pill-purple',
            'pending': 'admin-pill-warning',
            'rejected': 'admin-pill-danger',
            'cancelled': 'admin-pill-neutral',
        }
        cls = mapping.get(obj.status, 'admin-pill-neutral')
        return format_html('<span class="admin-pill {}">{}</span>', cls, obj.get_status_display())
    status_badge.short_description = "الحالة"

    def grand_total_display(self, obj):
        return f"{obj.grand_total:,.2f} ج.م"
    grand_total_display.short_description = "المبلغ الإجمالي"

    @admin.action(description="اعتماد أوامر الشراء المحددة")
    def approve_selected_orders(self, request, queryset):
        queryset.update(status='approved', approved_by=request.user, approved_at=timezone.now())

    @admin.action(description="تعليق أوامر الشراء المحددة (Hold)")
    def mark_as_hold(self, request, queryset):
        queryset.update(is_hold=True)


@admin.register(PurchaseOrderItem)
class PurchaseOrderItemAdmin(admin.ModelAdmin):
    list_display = ('order', 'product', 'quantity', 'unit_price', 'total_price', 'product_batch_number', 'product_expiry_date')
    list_filter = ('order__status', 'order__target_warehouse')
    search_fields = ('product__name', 'order__order_number', 'product_batch_number')


@admin.register(PurchaseReturnOrder)
class PurchaseReturnOrderAdmin(admin.ModelAdmin):
    list_display = ('order_number', 'supplier', 'warehouse', 'order_date', 'status_badge', 'grand_total_display', 'created_by')
    list_filter = ('status', 'warehouse', 'order_date')
    search_fields = ('order_number', 'supplier__name')
    date_hierarchy = 'order_date'
    inlines = [PurchaseReturnOrderItemInline]
    readonly_fields = ('serial_num', 'order_number', 'items_count', 'items_quantity', 'subtotal', 'grand_total', 'created_at', 'updated_at')

    def status_badge(self, obj):
        mapping = {
            'approved': 'admin-pill-success',
            'delivered': 'admin-pill-info',
            'settled': 'admin-pill-purple',
            'pending': 'admin-pill-warning',
            'cancelled': 'admin-pill-danger',
        }
        cls = mapping.get(obj.status, 'admin-pill-neutral')
        return format_html('<span class="admin-pill {}">{}</span>', cls, obj.get_status_display())
    status_badge.short_description = "الحالة"

    def grand_total_display(self, obj):
        return f"{obj.grand_total:,.2f} ج.م"
    grand_total_display.short_description = "إجمالي المرتجع"


@admin.register(PurchaseReturnOrderItem)
class PurchaseReturnOrderItemAdmin(admin.ModelAdmin):
    list_display = ('return_order', 'product', 'quantity', 'unit_price', 'total_price')
    search_fields = ('product__name', 'return_order__order_number')
