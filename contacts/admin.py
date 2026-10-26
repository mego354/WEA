from django.contrib import admin
from django.utils.html import format_html
from .models import (
    Contact, ContactAddress, ContactComment,
    ContactAttachment, ContactTodo, ContactActivity
)


class ContactAddressInline(admin.TabularInline):
    model = ContactAddress
    extra = 1
    fields = ('title', 'is_main', 'area', 'sub_area', 'street_address', 'latitude', 'longitude')


class ContactCommentInline(admin.TabularInline):
    model = ContactComment
    extra = 0
    fields = ('author', 'text', 'created_at')
    readonly_fields = ('created_at',)


class ContactTodoInline(admin.TabularInline):
    model = ContactTodo
    extra = 0
    fields = ('title', 'is_completed', 'due_date', 'created_by')


@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
    list_display = (
        'serial_num', 'name', 'contact_type_badge', 'business_relation_badges',
        'account_type', 'area', 'mobile', 'credit_limit_display',
        'status_badge', 'created_at'
    )
    list_filter = ('contact_type', 'is_customer', 'is_supplier', 'status', 'area', 'account_type', 'is_kol')
    search_fields = ('name', 'serial_num', 'code', 'mobile', 'phone', 'email', 'tax_id', 'contact_person')
    filter_horizontal = ('assigned_team',)
    inlines = [ContactAddressInline, ContactCommentInline, ContactTodoInline]
    date_hierarchy = 'created_at'
    actions = ['mark_active', 'mark_inactive']

    fieldsets = (
        ('المعلومات الأساسية', {
            'fields': ('serial_num', 'name', 'contact_type', 'is_customer', 'is_supplier', 'is_other', 'status', 'area', 'code')
        }),
        ('بيانات التواصل', {
            'fields': ('mobile', 'phone', 'email', 'website', 'contact_person', 'job_title', 'visit_timing')
        }),
        ('بيانات تصنيف العميل والحد الائتماني', {
            'fields': ('account_type', 'customer_category', 'specialty', 'is_kol', 'credit_limit', 'credit_period_days')
        }),
        ('البيانات الضريبية والتجارية', {
            'fields': ('tax_id', 'tax_card', 'commercial_registry')
        }),
        ('فريق العمل والمؤسسة التابعة', {
            'fields': ('parent_org', 'assigned_team', 'created_by', 'notes')
        }),
    )
    readonly_fields = ('serial_num',)

    def contact_type_badge(self, obj):
        if obj.contact_type == 'organization':
            return format_html('<span class="admin-pill admin-pill-info">منشأة / صيدلية</span>')
        return format_html('<span class="admin-pill admin-pill-neutral">فرد / طبيب</span>')
    contact_type_badge.short_description = "نوع الحساب"

    def business_relation_badges(self, obj):
        badges = []
        if obj.is_customer:
            badges.append('<span class="admin-pill admin-pill-success">عميل</span>')
        if obj.is_supplier:
            badges.append('<span class="admin-pill admin-pill-purple">مورد</span>')
        if not badges:
            badges.append('<span class="admin-pill admin-pill-neutral">أخرى</span>')
        return format_html(" ".join(badges))
    business_relation_badges.short_description = "العلاقة التجارية"

    def status_badge(self, obj):
        mapping = {
            'customer': 'admin-pill-success',
            'active': 'admin-pill-info',
            'lead': 'admin-pill-warning',
            'inactive': 'admin-pill-danger',
        }
        cls = mapping.get(obj.status, 'admin-pill-neutral')
        return format_html('<span class="admin-pill {}">{}</span>', cls, obj.get_status_display())
    status_badge.short_description = "الحالة"

    def credit_limit_display(self, obj):
        return f"{obj.credit_limit:,.2f} ج.م"
    credit_limit_display.short_description = "حد الائتمان"

    @admin.action(description="تفعيل جهات الاتصال المحددة")
    def mark_active(self, request, queryset):
        queryset.update(status='active')

    @admin.action(description="تعطيل جهات الاتصال المحددة")
    def mark_inactive(self, request, queryset):
        queryset.update(status='inactive')


@admin.register(ContactAddress)
class ContactAddressAdmin(admin.ModelAdmin):
    list_display = ('title', 'contact', 'is_main', 'area', 'sub_area', 'latitude', 'longitude')
    list_filter = ('is_main', 'area')
    search_fields = ('title', 'contact__name', 'street_address')


@admin.register(ContactComment)
class ContactCommentAdmin(admin.ModelAdmin):
    list_display = ('contact', 'author', 'text_short', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('text', 'contact__name', 'author__username')

    def text_short(self, obj):
        return obj.text[:50] + "..." if len(obj.text) > 50 else obj.text
    text_short.short_description = "التعليق"


@admin.register(ContactAttachment)
class ContactAttachmentAdmin(admin.ModelAdmin):
    list_display = ('filename', 'contact', 'uploaded_by', 'created_at')
    search_fields = ('filename', 'contact__name')


@admin.register(ContactTodo)
class ContactTodoAdmin(admin.ModelAdmin):
    list_display = ('title', 'contact', 'is_completed_badge', 'due_date', 'created_by')
    list_filter = ('is_completed', 'due_date')
    search_fields = ('title', 'contact__name')

    def is_completed_badge(self, obj):
        if obj.is_completed:
            return format_html('<span class="admin-pill admin-pill-success">مكتملة</span>')
        return format_html('<span class="admin-pill admin-pill-warning">معلقة</span>')
    is_completed_badge.short_description = "الحالة"


@admin.register(ContactActivity)
class ContactActivityAdmin(admin.ModelAdmin):
    list_display = ('title', 'contact', 'activity_type', 'performed_by', 'start_time', 'created_at')
    list_filter = ('activity_type', 'created_at')
    search_fields = ('title', 'contact__name', 'notes')
