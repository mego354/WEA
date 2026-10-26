from django.contrib import admin
from django.utils.html import format_html
from .models import (
    Vault, VendorAccount, VendorTransaction, VendorInstallment,
    VendorPayment, Settlement, VaultTransaction
)


class VaultTransactionInline(admin.TabularInline):
    model = VaultTransaction
    extra = 0
    fields = ('transaction_type', 'amount', 'running_balance', 'reference_type', 'description', 'created_at')
    readonly_fields = ('transaction_type', 'amount', 'running_balance', 'reference_type', 'description', 'created_at')


class VendorInstallmentInline(admin.TabularInline):
    model = VendorInstallment
    extra = 0
    fields = ('total_amount', 'closed_amount', 'open_amount', 'due_date', 'is_settled')


@admin.register(Vault)
class VaultAdmin(admin.ModelAdmin):
    list_display = (
        'serial_num', 'name', 'vault_type_badge', 'assigned_user',
        'current_balance_display', 'is_active_badge', 'created_at'
    )
    list_filter = ('vault_type', 'is_active')
    search_fields = ('name', 'serial_num')
    inlines = [VaultTransactionInline]

    def vault_type_badge(self, obj):
        if obj.vault_type == 'cash':
            return format_html('<span class="admin-pill admin-pill-success">خزينة نقدية</span>')
        return format_html('<span class="admin-pill admin-pill-info">حساب بنكي</span>')
    vault_type_badge.short_description = "نوع الخزنة"

    def current_balance_display(self, obj):
        return f"{obj.current_balance:,.2f} ج.م"
    current_balance_display.short_description = "الرصيد الحالي"

    def is_active_badge(self, obj):
        if obj.is_active:
            return format_html('<span class="admin-pill admin-pill-success">مفعلة</span>')
        return format_html('<span class="admin-pill admin-pill-danger">معطلة</span>')
    is_active_badge.short_description = "الحالة"


@admin.register(VendorAccount)
class VendorAccountAdmin(admin.ModelAdmin):
    list_display = ('supplier', 'credit_limit_display', 'current_balance_display', 'overdue_balance_display', 'last_transaction_date')
    search_fields = ('supplier__name',)
    inlines = []

    def credit_limit_display(self, obj):
        return f"{obj.credit_limit:,.2f} ج.م"
    credit_limit_display.short_description = "حد الائتمان"

    def current_balance_display(self, obj):
        return f"{obj.current_balance:,.2f} ج.م"
    current_balance_display.short_description = "الرصيد المستحق"

    def overdue_balance_display(self, obj):
        return f"{obj.overdue_balance:,.2f} ج.م"
    overdue_balance_display.short_description = "المتأخرات"


@admin.register(VendorTransaction)
class VendorTransactionAdmin(admin.ModelAdmin):
    list_display = (
        'serial', 'account', 'transaction_type_badge', 'reason',
        'transaction_date', 'credit_display', 'debit_display', 'running_balance_display'
    )
    list_filter = ('transaction_type', 'reason', 'transaction_date')
    search_fields = ('account__supplier__name', 'serial', 'description')
    date_hierarchy = 'transaction_date'
    inlines = [VendorInstallmentInline]

    def transaction_type_badge(self, obj):
        if obj.transaction_type == 'credit':
            return format_html('<span class="admin-pill admin-pill-purple">دائن (استحقاق)</span>')
        return format_html('<span class="admin-pill admin-pill-success">مدين (سداد)</span>')
    transaction_type_badge.short_description = "نوع القيد"

    def credit_display(self, obj):
        return f"{obj.credit:,.2f} ج.م"
    credit_display.short_description = "دائن"

    def debit_display(self, obj):
        return f"{obj.debit:,.2f} ج.م"
    debit_display.short_description = "مدين"

    def running_balance_display(self, obj):
        return f"{obj.running_balance:,.2f} ج.م"
    running_balance_display.short_description = "الرصيد بعد القيد"


@admin.register(VendorInstallment)
class VendorInstallmentAdmin(admin.ModelAdmin):
    list_display = ('transaction', 'total_amount', 'closed_amount', 'open_amount', 'due_date', 'is_settled_badge')
    list_filter = ('is_settled', 'due_date')
    search_fields = ('transaction__account__supplier__name', 'transaction__serial')

    def is_settled_badge(self, obj):
        if obj.is_settled:
            return format_html('<span class="admin-pill admin-pill-success">مسددة بالكامل</span>')
        return format_html('<span class="admin-pill admin-pill-warning">مفتوحة</span>')
    is_settled_badge.short_description = "حالة السداد"


@admin.register(VendorPayment)
class VendorPaymentAdmin(admin.ModelAdmin):
    list_display = (
        'serial_num', 'supplier', 'vault', 'amount_display',
        'payment_date', 'payment_method_badge', 'status_badge', 'created_by'
    )
    list_filter = ('payment_method', 'status', 'vault', 'payment_date')
    search_fields = ('supplier__name', 'serial_num', 'reference_number')
    date_hierarchy = 'payment_date'

    def amount_display(self, obj):
        return f"{obj.amount:,.2f} ج.م"
    amount_display.short_description = "المبلغ"

    def payment_method_badge(self, obj):
        mapping = {
            'cash': ('admin-pill-success', 'نقدي'),
            'cheque': ('admin-pill-info', 'شيك بنكي'),
            'bank_transfer': ('admin-pill-purple', 'تحويل بنكي'),
        }
        cls, label = mapping.get(obj.payment_method, ('admin-pill-neutral', obj.payment_method))
        return format_html('<span class="admin-pill {}">{}</span>', cls, label)
    payment_method_badge.short_description = "طريقة السداد"

    def status_badge(self, obj):
        if obj.status == 'cleared':
            return format_html('<span class="admin-pill admin-pill-success">معتمد / منفذ</span>')
        return format_html('<span class="admin-pill admin-pill-warning">قيد التنفيذ</span>')
    status_badge.short_description = "الحالة"


@admin.register(Settlement)
class SettlementAdmin(admin.ModelAdmin):
    list_display = ('payment_transaction', 'target_installment', 'amount', 'settled_at', 'created_by')
    date_hierarchy = 'settled_at'


@admin.register(VaultTransaction)
class VaultTransactionAdmin(admin.ModelAdmin):
    list_display = ('vault', 'transaction_type_badge', 'amount_display', 'running_balance_display', 'reference_type', 'description', 'created_at')
    list_filter = ('transaction_type', 'vault', 'created_at')
    search_fields = ('description', 'vault__name')
    date_hierarchy = 'created_at'

    def transaction_type_badge(self, obj):
        if obj.transaction_type == 'inflow':
            return format_html('<span class="admin-pill admin-pill-success">إيداع نقدي (+)</span>')
        return format_html('<span class="admin-pill admin-pill-danger">صرف نقدي (-)</span>')
    transaction_type_badge.short_description = "نوع الحركة"

    def amount_display(self, obj):
        return f"{obj.amount:,.2f} ج.م"
    amount_display.short_description = "المبلغ"

    def running_balance_display(self, obj):
        return f"{obj.running_balance:,.2f} ج.م"
    running_balance_display.short_description = "الرصيد بعد الحركة"
