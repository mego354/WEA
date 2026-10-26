from django.contrib import admin
from django.utils.html import format_html
from django.utils import timezone
from .models import (
    CustomerAccount, CustomerTransaction, SalesOrder,
    SalesOrderItem, Collection, SalesReturnOrder, SalesReturnOrderItem
)


class SalesOrderItemInline(admin.TabularInline):
    model = SalesOrderItem
    extra = 1
    fields = ('product', 'quantity', 'unit_price', 'subtotal')
    readonly_fields = ('subtotal',)


class SalesReturnOrderItemInline(admin.TabularInline):
    model = SalesReturnOrderItem
    extra = 1
    fields = ('product', 'quantity', 'unit_price', 'subtotal', 'batch_number', 'expiry_date')
    readonly_fields = ('subtotal',)


@admin.register(SalesOrder)
class SalesOrderAdmin(admin.ModelAdmin):
    list_display = (
        'order_number', 'customer', 'source_warehouse', 'order_date',
        'status_badge', 'grand_total_display', 'created_by',
        'approved_by', 'approved_at'
    )
    list_filter = ('status', 'source_warehouse', 'order_date')
    search_fields = ('order_number', 'customer__name', 'notes')
    date_hierarchy = 'order_date'
    inlines = [SalesOrderItemInline]
    readonly_fields = ('serial_num', 'order_number', 'created_at', 'updated_at')
    actions = ['approve_selected_orders']

    fieldsets = (
        ('معلومات أمر البيع', {
            'fields': ('serial_num', 'order_number', 'customer', 'delivery_address', 'source_warehouse', 'order_date', 'delivery_date', 'status')
        }),
        ('الربط المخزني والمالي', {
            'fields': ('memo', 'grand_total')
        }),
        ('الاعتماد والملاحظات', {
            'fields': ('approved_by', 'approved_at', 'rejection_reason', 'notes', 'created_by', 'created_at', 'updated_at')
        }),
    )

    def status_badge(self, obj):
        mapping = {
            'approved': 'admin-pill-success',
            'manager_approval': 'admin-pill-success',
            'delivered': 'admin-pill-info',
            'invoiced': 'admin-pill-purple',
            'preparing': 'admin-pill-info',
            'pending': 'admin-pill-warning',
            'rejected': 'admin-pill-danger',
            'cancelled': 'admin-pill-neutral',
        }
        cls = mapping.get(obj.status, 'admin-pill-neutral')
        return format_html('<span class="admin-pill {}">{}</span>', cls, obj.status_display_ar)
    status_badge.short_description = "الحالة"

    def grand_total_display(self, obj):
        return f"{obj.grand_total:,.2f} ج.م"
    grand_total_display.short_description = "إجمالي القيمة"

    @admin.action(description="اعتماد أوامر البيع المحددة")
    def approve_selected_orders(self, request, queryset):
        queryset.update(status='approved', approved_by=request.user, approved_at=timezone.now())


@admin.register(SalesOrderItem)
class SalesOrderItemAdmin(admin.ModelAdmin):
    list_display = ('order', 'product', 'quantity', 'unit_price', 'subtotal')
    list_filter = ('order__status', 'order__source_warehouse')
    search_fields = ('product__name', 'order__order_number')


@admin.register(Collection)
class CollectionAdmin(admin.ModelAdmin):
    list_display = ('serial_num', 'customer', 'vault', 'amount_display', 'collection_date', 'payment_method_badge', 'created_by')
    list_filter = ('payment_method', 'vault', 'collection_date')
    search_fields = ('customer__name', 'serial_num')
    date_hierarchy = 'collection_date'

    def amount_display(self, obj):
        return f"{obj.amount:,.2f} ج.م"
    amount_display.short_description = "المبلغ المحصل"

    def payment_method_badge(self, obj):
        if obj.payment_method == 'cash':
            return format_html('<span class="admin-pill admin-pill-success">نقدي</span>')
        return format_html('<span class="admin-pill admin-pill-info">شيك</span>')
    payment_method_badge.short_description = "طريقة الدفع"


@admin.register(CustomerAccount)
class CustomerAccountAdmin(admin.ModelAdmin):
    list_display = ('customer', 'credit_limit_display', 'current_balance_display', 'overdue_balance_display', 'last_transaction_date')
    search_fields = ('customer__name', 'customer__code')

    def credit_limit_display(self, obj):
        return f"{obj.credit_limit:,.2f} ج.م"
    credit_limit_display.short_description = "حد الائتمان"

    def current_balance_display(self, obj):
        return f"{obj.current_balance:,.2f} ج.م"
    current_balance_display.short_description = "الرصيد المستحق"

    def overdue_balance_display(self, obj):
        return f"{obj.overdue_balance:,.2f} ج.م"
    overdue_balance_display.short_description = "المتأخرات"


@admin.register(CustomerTransaction)
class CustomerTransactionAdmin(admin.ModelAdmin):
    list_display = (
        'serial', 'account', 'transaction_type_badge', 'reason',
        'transaction_date', 'debit_display', 'credit_display', 'running_balance_display'
    )
    list_filter = ('transaction_type', 'reason', 'transaction_date')
    search_fields = ('account__customer__name', 'serial', 'description')
    date_hierarchy = 'transaction_date'

    def transaction_type_badge(self, obj):
        if obj.transaction_type == 'debit':
            return format_html('<span class="admin-pill admin-pill-danger">مدين (فاتورة)</span>')
        return format_html('<span class="admin-pill admin-pill-success">دائن (سداد)</span>')
    transaction_type_badge.short_description = "نوع القيد"

    def debit_display(self, obj):
        return f"{obj.debit:,.2f} ج.م"
    debit_display.short_description = "مدين"

    def credit_display(self, obj):
        return f"{obj.credit:,.2f} ج.م"
    credit_display.short_description = "دائن"

    def running_balance_display(self, obj):
        return f"{obj.running_balance:,.2f} ج.م"
    running_balance_display.short_description = "الرصيد بعد القيد"


@admin.register(SalesReturnOrder)
class SalesReturnOrderAdmin(admin.ModelAdmin):
    list_display = ('order_number', 'customer', 'target_warehouse', 'order_date', 'status', 'grand_total', 'created_by')
    list_filter = ('status', 'target_warehouse', 'order_date')
    search_fields = ('order_number', 'customer__name')
    date_hierarchy = 'order_date'
    inlines = [SalesReturnOrderItemInline]


@admin.register(SalesReturnOrderItem)
class SalesReturnOrderItemAdmin(admin.ModelAdmin):
    list_display = ('order', 'product', 'quantity', 'unit_price', 'subtotal')
    search_fields = ('product__name', 'order__order_number')
