from django.contrib import admin
from django.utils.html import format_html
from django.utils import timezone
from .models import (
    AgreementType, Agreement, VisitTemplate,
    VisitTemplateQuestion, PlannedVisitDay, PlannedVisitItem,
    Visit, VisitSampleItem, VisitExpense,
    ApprovalAuditLog, AgendaTodo
)


@admin.register(AgreementType)
class AgreementTypeAdmin(admin.ModelAdmin):
    list_display = ('name', 'display_name_ar', 'agreements_count', 'is_active_badge')
    list_filter = ('is_active',)
    search_fields = ('name', 'display_name_ar')

    def agreements_count(self, obj):
        return obj.agreements.count()
    agreements_count.short_description = "عدد الاتفاقيات"

    def is_active_badge(self, obj):
        if obj.is_active:
            return format_html('<span style="color:#059669; font-weight:bold;">● نشط</span>')
        return format_html('<span style="color:#dc2626; font-weight:bold;">○ غير نشط</span>')
    is_active_badge.short_description = "الحالة"


@admin.register(Agreement)
class AgreementAdmin(admin.ModelAdmin):
    list_display = ('serial_num', 'title', 'type', 'customer', 'amount_display', 'status_badge', 'date', 'created_by')
    list_filter = ('status', 'type', 'date')
    search_fields = ('title', 'serial_num', 'customer__name', 'customer__code')
    date_hierarchy = 'date'
    actions = ['mark_as_approved', 'mark_as_done']

    def amount_display(self, obj):
        return f"{obj.amount:,.2f} ج.م"
    amount_display.short_description = "المبلغ"

    def status_badge(self, obj):
        colors = {
            'new': ('#0284c7', '#e0f2fe', 'جديد'),
            'approved': ('#059669', '#d1fae5', 'معتمد'),
            'disapproved': ('#dc2626', '#fee2e2', 'مرفوض'),
            'done': ('#475569', '#f1f5f9', 'منجز'),
        }
        text_color, bg_color, label = colors.get(obj.status, ('#475569', '#f1f5f9', obj.status))
        return format_html(
            '<span style="background-color:{}; color:{}; padding:3px 10px; border-radius:12px; font-weight:600; font-size:12px;">{}</span>',
            bg_color, text_color, label
        )
    status_badge.short_description = "الحالة"

    def mark_as_approved(self, request, queryset):
        updated = queryset.update(status='approved')
        self.message_user(request, f"تم اعتماد {updated} اتفاقية بنجاح.")
    mark_as_approved.short_description = "اعتماد الاتفاقيات المحددة"

    def mark_as_done(self, request, queryset):
        updated = queryset.update(status='done')
        self.message_user(request, f"تم إنجاز {updated} اتفاقية بنجاح.")
    mark_as_done.short_description = "إنجاز الاتفاقيات المحددة"


class VisitTemplateQuestionInline(admin.TabularInline):
    model = VisitTemplateQuestion
    extra = 0
    fields = ('order', 'text_ar', 'question_type', 'stage', 'is_required', 'is_active')
    ordering = ('order',)


@admin.register(VisitTemplate)
class VisitTemplateAdmin(admin.ModelAdmin):
    list_display = ('name', 'display_name_ar', 'questions_count', 'allow_unplanned', 'active_badge')
    list_filter = ('active', 'allow_unplanned', 'enable_product_detailing')
    search_fields = ('name', 'display_name_ar', 'display_name_en')
    filter_horizontal = ('restricted_roles', 'suggested_products')
    inlines = [VisitTemplateQuestionInline]

    def questions_count(self, obj):
        return obj.questions.count()
    questions_count.short_description = "عدد الأسئلة"

    def active_badge(self, obj):
        if obj.active:
            return format_html('<span style="color:#059669; font-weight:bold;">● نشط</span>')
        return format_html('<span style="color:#dc2626; font-weight:bold;">○ غير نشط</span>')
    active_badge.short_description = "الحالة"


@admin.register(VisitTemplateQuestion)
class VisitTemplateQuestionAdmin(admin.ModelAdmin):
    list_display = ('template', 'order', 'text_ar', 'question_type', 'stage', 'is_required', 'is_conditional', 'is_active')
    list_filter = ('template', 'question_type', 'stage', 'is_required', 'is_active')
    search_fields = ('text_ar', 'text_en', 'template__name', 'template__display_name_ar')
    ordering = ('template', 'order')


class PlannedVisitItemInline(admin.TabularInline):
    model = PlannedVisitItem
    extra = 0
    fields = ('order', 'contact', 'template', 'is_executed', 'visit', 'notes')
    readonly_fields = ('visit', 'is_executed')


@admin.register(PlannedVisitDay)
class PlannedVisitDayAdmin(admin.ModelAdmin):
    list_display = ('assignee', 'date', 'status_badge', 'items_count', 'created_by', 'created_at')
    list_filter = ('status', 'date', 'assignee')
    search_fields = ('assignee__username', 'assignee__first_name', 'assignee__last_name')
    date_hierarchy = 'date'
    inlines = [PlannedVisitItemInline]

    def items_count(self, obj):
        return obj.planned_items.count()
    items_count.short_description = "عدد الزيارات المخططة"

    def status_badge(self, obj):
        colors = {
            'new': ('#0284c7', '#e0f2fe', 'جديد'),
            'completed': ('#059669', '#d1fae5', 'مكتمل'),
            'cancelled': ('#dc2626', '#fee2e2', 'ملغي'),
        }
        text_color, bg_color, label = colors.get(obj.status, ('#475569', '#f1f5f9', obj.status))
        return format_html(
            '<span style="background-color:{}; color:{}; padding:3px 10px; border-radius:12px; font-weight:600; font-size:12px;">{}</span>',
            bg_color, text_color, label
        )
    status_badge.short_description = "الحالة"


@admin.register(PlannedVisitItem)
class PlannedVisitItemAdmin(admin.ModelAdmin):
    list_display = ('plan_day', 'order', 'contact', 'template', 'is_executed_badge', 'visit')
    list_filter = ('is_executed', 'plan_day__date', 'template')
    search_fields = ('contact__name', 'contact__code', 'plan_day__assignee__username')

    def is_executed_badge(self, obj):
        if obj.is_executed:
            return format_html('<span style="color:#059669; font-weight:bold;">✓ منفذة</span>')
        return format_html('<span style="color:#eab308; font-weight:bold;">⏳ قيد الانتظار</span>')
    is_executed_badge.short_description = "التنفيذ"


class VisitSampleItemInline(admin.TabularInline):
    model = VisitSampleItem
    extra = 0
    fields = ('product', 'quantity', 'notes')


class VisitExpenseInline(admin.TabularInline):
    model = VisitExpense
    extra = 0
    fields = ('expense_type', 'amount', 'notes')


@admin.register(Visit)
class VisitAdmin(admin.ModelAdmin):
    list_display = (
        'serial_num', 'contact', 'owner', 'template', 'date',
        'status_badge', 'approval_badge', 'location_status_badge',
        'is_successful', 'doubled'
    )
    list_filter = (
        'status', 'approval_status', 'is_planned', 'doubled',
        'is_successful', 'location_verified', 'template', 'date'
    )
    search_fields = (
        'serial_num', 'contact__name', 'contact__code',
        'owner__username', 'owner__first_name', 'owner__last_name'
    )
    date_hierarchy = 'date'
    filter_horizontal = ('detailed_products',)
    readonly_fields = (
        'created_at', 'updated_at', 'started_at', 'ended_at',
        'duration', 'customer_latitude_snapshot', 'customer_longitude_snapshot',
        'photo_preview'
    )
    inlines = [VisitSampleItemInline, VisitExpenseInline]
    actions = ['approve_selected_visits', 'disapprove_selected_visits']

    fieldsets = (
        ('معلومات الزيارة الأساسية', {
            'fields': (
                ('serial_num', 'date', 'visit_time'),
                ('contact', 'template', 'owner'),
                ('status', 'approval_status', 'is_planned'),
            )
        }),
        ('النتائج والاستبيان', {
            'fields': (
                ('is_successful', 'doubled', 'mode'),
                'visit_outcome',
                'feedback',
                'detailed_products',
                'questionnaire_answers',
            )
        }),
        ('التحقق والموقع الجغرافي', {
            'fields': (
                ('latitude', 'longitude'),
                ('device_accuracy', 'distance'),
                ('location_verified', 'location_status', 'verification_status'),
                ('customer_latitude_snapshot', 'customer_longitude_snapshot'),
                ('location_photo', 'photo_preview', 'photo_captured_at'),
            )
        }),
        ('التجاوز والاعتماد الإداري', {
            'fields': (
                ('bypassed_by', 'bypassed_at'),
                'bypass_reason',
                ('approved_by', 'approved_at'),
                'approval_notes',
            )
        }),
        ('أوقات النظام والتدقيق', {
            'classes': ('collapse',),
            'fields': (
                ('started_at', 'ended_at', 'duration'),
                ('created_by', 'created_at', 'updated_at'),
            )
        }),
    )

    def photo_preview(self, obj):
        if obj.location_photo:
            return format_html(
                '<a href="{}" target="_blank"><img src="{}" style="max-height:120px; border-radius:6px; border:1px solid #cbd5e1;"/></a>',
                obj.location_photo.url, obj.location_photo.url
            )
        return "لا توجد صورة مسجلة"
    photo_preview.short_description = "معاينة صورة الموقع"

    def status_badge(self, obj):
        colors = {
            'planned': ('#0284c7', '#e0f2fe', 'مخططة'),
            'started': ('#d97706', '#fef3c7', 'بدأت'),
            'finished': ('#059669', '#d1fae5', 'مكتملة'),
            'cancelled': ('#dc2626', '#fee2e2', 'ملغاة'),
        }
        text_color, bg_color, label = colors.get(obj.status, ('#475569', '#f1f5f9', obj.status))
        return format_html(
            '<span style="background-color:{}; color:{}; padding:3px 8px; border-radius:10px; font-weight:600; font-size:11px;">{}</span>',
            bg_color, text_color, label
        )
    status_badge.short_description = "الحالة"

    def approval_badge(self, obj):
        colors = {
            'pending': ('#d97706', '#fef3c7', 'قيد الانتظار'),
            'approved': ('#059669', '#d1fae5', 'معتمدة'),
            'disapproved': ('#dc2626', '#fee2e2', 'مرفوضة'),
        }
        text_color, bg_color, label = colors.get(obj.approval_status, ('#475569', '#f1f5f9', obj.approval_status))
        return format_html(
            '<span style="background-color:{}; color:{}; padding:3px 8px; border-radius:10px; font-weight:600; font-size:11px;">{}</span>',
            bg_color, text_color, label
        )
    approval_badge.short_description = "الاعتماد"

    def location_status_badge(self, obj):
        if obj.location_verified:
            return format_html('<span style="color:#059669; font-weight:bold;">✓ محقق</span>')
        return format_html('<span style="color:#dc2626; font-weight:bold;">⚠ غير محقق</span>')
    location_status_badge.short_description = "الموقع"

    def approve_selected_visits(self, request, queryset):
        updated = queryset.update(
            approval_status='approved',
            approved_by=request.user,
            approved_at=timezone.now()
        )
        self.message_user(request, f"تم اعتماد {updated} زيارة بنجاح.")
    approve_selected_visits.short_description = "اعتماد الزيارات المحددة"

    def disapprove_selected_visits(self, request, queryset):
        updated = queryset.update(
            approval_status='disapproved',
            approved_by=request.user,
            approved_at=timezone.now()
        )
        self.message_user(request, f"تم رفض {updated} زيارة.")
    disapprove_selected_visits.short_description = "رفض الزيارات المحددة"


@admin.register(ApprovalAuditLog)
class ApprovalAuditLogAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'record_type_badge', 'action_badge', 'actor', 'target_object', 'status_before', 'status_after', 'ip_address')
    list_filter = ('record_type', 'action', 'created_at')
    search_fields = ('actor__username', 'reason', 'ip_address', 'status_before', 'status_after')
    date_hierarchy = 'created_at'

    # Read-only audit log for security compliance
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def record_type_badge(self, obj):
        colors = {
            'visit': ('#2563eb', '#dbeafe', 'زيارة'),
            'sales_order': ('#059669', '#d1fae5', 'أمر بيع'),
            'purchase_order': ('#7c3aed', '#ede9fe', 'أمر شراء'),
        }
        text_color, bg_color, label = colors.get(obj.record_type, ('#475569', '#f1f5f9', obj.record_type))
        return format_html(
            '<span style="background-color:{}; color:{}; padding:2px 8px; border-radius:10px; font-weight:600; font-size:11px;">{}</span>',
            bg_color, text_color, label
        )
    record_type_badge.short_description = "نوع السجل"

    def action_badge(self, obj):
        colors = {
            'approved': ('#059669', '#d1fae5', 'اعتماد'),
            'rejected': ('#dc2626', '#fee2e2', 'رفض'),
            'submitted': ('#0284c7', '#e0f2fe', 'تقديم'),
            'resubmitted': ('#d97706', '#fef3c7', 'إعادة تقديم'),
            'status_changed': ('#475569', '#f1f5f9', 'تغيير حالة'),
            'sent_to_agenda': ('#0891b2', '#cffafe', 'إرسال للأجندة'),
        }
        text_color, bg_color, label = colors.get(obj.action, ('#475569', '#f1f5f9', obj.action))
        return format_html(
            '<span style="background-color:{}; color:{}; padding:2px 8px; border-radius:10px; font-weight:600; font-size:11px;">{}</span>',
            bg_color, text_color, label
        )
    action_badge.short_description = "الإجراء"

    def target_object(self, obj):
        if obj.visit:
            return f"زيارة #{obj.visit.serial_num}"
        if obj.sales_order:
            return f"أمر بيع #{obj.sales_order.order_number}"
        if obj.purchase_order:
            return f"أمر شراء #{obj.purchase_order.order_number}"
        return "-"
    target_object.short_description = "الهدف"


@admin.register(AgendaTodo)
class AgendaTodoAdmin(admin.ModelAdmin):
    list_display = ('title', 'user', 'date', 'is_completed_badge', 'created_at')
    list_filter = ('is_completed', 'date', 'user')
    search_fields = ('title', 'user__username', 'user__first_name')
    date_hierarchy = 'date'
    actions = ['mark_as_completed', 'mark_as_pending']

    def is_completed_badge(self, obj):
        if obj.is_completed:
            return format_html('<span style="color:#059669; font-weight:bold;">✓ مكتملة</span>')
        return format_html('<span style="color:#eab308; font-weight:bold;">⏳ قيد التنفيذ</span>')
    is_completed_badge.short_description = "الحالة"

    def mark_as_completed(self, request, queryset):
        updated = queryset.update(is_completed=True)
        self.message_user(request, f"تم تحديد {updated} مهمة كمكتملة.")
    mark_as_completed.short_description = "تحديد المهام المحددة كمكتملة"

    def mark_as_pending(self, request, queryset):
        updated = queryset.update(is_completed=False)
        self.message_user(request, f"تم تحديد {updated} مهمة كقيد التنفيذ.")
    mark_as_pending.short_description = "تحديد المهام المحددة كقيد التنفيذ"
