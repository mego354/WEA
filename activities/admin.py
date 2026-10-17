from django.contrib import admin
from .models import (
    AgreementType, Agreement, VisitTemplate,
    PlannedVisitDay, PlannedVisitItem, Visit,
    VisitSampleItem, VisitExpense
)


@admin.register(AgreementType)
class AgreementTypeAdmin(admin.ModelAdmin):
    list_display = ('name', 'display_name_ar', 'is_active')
    search_fields = ('name', 'display_name_ar')


@admin.register(Agreement)
class AgreementAdmin(admin.ModelAdmin):
    list_display = ('serial_num', 'title', 'type', 'amount', 'customer', 'status', 'date', 'created_by')
    list_filter = ('status', 'type', 'date')
    search_fields = ('title', 'serial_num', 'customer__name', 'customer__code')


@admin.register(VisitTemplate)
class VisitTemplateAdmin(admin.ModelAdmin):
    list_display = ('name', 'display_name_ar', 'active')
    search_fields = ('name', 'display_name_ar')


class PlannedVisitItemInline(admin.TabularInline):
    model = PlannedVisitItem
    extra = 1


@admin.register(PlannedVisitDay)
class PlannedVisitDayAdmin(admin.ModelAdmin):
    list_display = ('assignee', 'date', 'status', 'created_by')
    list_filter = ('date', 'status')
    inlines = [PlannedVisitItemInline]


class VisitSampleItemInline(admin.TabularInline):
    model = VisitSampleItem
    extra = 1


class VisitExpenseInline(admin.TabularInline):
    model = VisitExpense
    extra = 1


@admin.register(Visit)
class VisitAdmin(admin.ModelAdmin):
    list_display = ('serial_num', 'contact', 'owner', 'template', 'date', 'status', 'approval_status', 'is_successful', 'doubled')
    list_filter = ('status', 'approval_status', 'is_planned', 'doubled', 'is_successful', 'date')
    search_fields = ('serial_num', 'contact__name', 'contact__code', 'owner__username', 'owner__first_name')
    inlines = [VisitSampleItemInline, VisitExpenseInline]

