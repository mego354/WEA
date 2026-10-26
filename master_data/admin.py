from django.contrib import admin
from django.utils.html import format_html
from .models import (
    Area, CompanyProfile, LocationSettings, SalesSettings,
    PurchaseSettings, ExpenseType, TicketType, ApprovalRequestType,
    AgreementType, ContactFieldSetting, DataSyncConfig
)


@admin.register(Area)
class AreaAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'area_type_badge', 'parent', 'assigned_users_count', 'contacts_count', 'created_at')
    list_filter = ('area_type',)
    search_fields = ('code', 'name')
    ordering = ('code',)

    def area_type_badge(self, obj):
        if obj.area_type == 'governorate':
            return format_html('<span class="admin-pill admin-pill-info">محافظة</span>')
        return format_html('<span class="admin-pill admin-pill-neutral">منطقة فرعية</span>')
    area_type_badge.short_description = "نوع المنطقة"

    def assigned_users_count(self, obj):
        return obj.assigned_users.count()
    assigned_users_count.short_description = "المستخدمين"

    def contacts_count(self, obj):
        return obj.contacts.count()
    contacts_count.short_description = "جهات الاتصال"


@admin.register(CompanyProfile)
class CompanyProfileAdmin(admin.ModelAdmin):
    list_display = ('company_name', 'phone', 'email', 'commercial_registry', 'tax_id', 'currency', 'use_batch_number', 'use_expiry_date')

    def has_add_permission(self, request):
        return not CompanyProfile.objects.exists()


@admin.register(LocationSettings)
class LocationSettingsAdmin(admin.ModelAdmin):
    list_display = (
        'tolerance_display', 'max_verified_accuracy', 'verify_visits_badge',
        'require_manager_approval_for_visits', 'allow_all_users_to_create_visits',
        'enable_product_suggestions', 'suggested_products_count'
    )
    filter_horizontal = ('suggested_products',)

    def tolerance_display(self, obj):
        return f"{obj.tolerance} متر"
    tolerance_display.short_description = "نطاق السماحية الجغرافية"

    def verify_visits_badge(self, obj):
        if obj.verify_visits:
            return format_html('<span class="admin-pill admin-pill-success">مفعل</span>')
        return format_html('<span class="admin-pill admin-pill-neutral">معطل</span>')
    verify_visits_badge.short_description = "التحقق الجغرافي"

    def suggested_products_count(self, obj):
        return obj.suggested_products.count()
    suggested_products_count.short_description = "المنتجات المقترحة"

    def has_add_permission(self, request):
        return not LocationSettings.objects.exists()


@admin.register(SalesSettings)
class SalesSettingsAdmin(admin.ModelAdmin):
    list_display = (
        'tax_mode', 'default_packaging_unit', 'auto_invoice_on_dispatch',
        'allow_all_users_to_create', 'require_manager_approval'
    )

    def has_add_permission(self, request):
        return not SalesSettings.objects.exists()


@admin.register(PurchaseSettings)
class PurchaseSettingsAdmin(admin.ModelAdmin):
    list_display = (
        'tax_mode', 'default_packaging_unit', 'auto_invoice_on_dispatch',
        'allow_all_users_to_create', 'require_manager_approval'
    )

    def has_add_permission(self, request):
        return not PurchaseSettings.objects.exists()


@admin.register(ExpenseType)
class ExpenseTypeAdmin(admin.ModelAdmin):
    list_display = ('name', 'name_en', 'category_badge', 'unit', 'is_active_badge')
    list_filter = ('category', 'is_active')
    search_fields = ('name', 'name_en')

    def category_badge(self, obj):
        if obj.category == 'visit':
            return format_html('<span class="admin-pill admin-pill-purple">زيارات ميدانية</span>')
        return format_html('<span class="admin-pill admin-pill-neutral">مصروفات عامة</span>')
    category_badge.short_description = "تصنيف المصروف"

    def is_active_badge(self, obj):
        if obj.is_active:
            return format_html('<span class="admin-pill admin-pill-success">نشط</span>')
        return format_html('<span class="admin-pill admin-pill-danger">معطل</span>')
    is_active_badge.short_description = "الحالة"


@admin.register(TicketType)
class TicketTypeAdmin(admin.ModelAdmin):
    list_display = ('name', 'is_default', 'is_active')
    list_filter = ('is_default', 'is_active')
    search_fields = ('name',)


@admin.register(ApprovalRequestType)
class ApprovalRequestTypeAdmin(admin.ModelAdmin):
    list_display = ('name', 'is_default', 'is_active')
    list_filter = ('is_default', 'is_active')
    search_fields = ('name',)


@admin.register(AgreementType)
class AgreementTypeAdmin(admin.ModelAdmin):
    list_display = ('name', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('name',)


@admin.register(ContactFieldSetting)
class ContactFieldSettingAdmin(admin.ModelAdmin):
    list_display = ('field_key', 'display_name', 'section', 'is_required', 'is_locked', 'is_filterable', 'order')
    list_filter = ('section', 'is_required', 'is_locked', 'is_filterable')
    search_fields = ('field_key', 'display_name')
    ordering = ('section', 'order')


@admin.register(DataSyncConfig)
class DataSyncConfigAdmin(admin.ModelAdmin):
    list_display = ('title', 'sync_type', 'status', 'last_synced_at')
    list_filter = ('sync_type', 'status')
    search_fields = ('title', 'service_account_email')
