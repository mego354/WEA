from django.contrib import admin
from .models import SalesTarget, CustomerCall, CoachingEvaluation


@admin.register(SalesTarget)
class SalesTargetAdmin(admin.ModelAdmin):
    list_display = ('user', 'year', 'month', 'target_sales_amount', 'target_collections_amount', 'target_visits_count')
    list_filter = ('year', 'month', 'area')
    search_fields = ('user__name', 'user__username', 'area__name')


@admin.register(CustomerCall)
class CustomerCallAdmin(admin.ModelAdmin):
    list_display = ('contact', 'performed_by', 'call_date', 'purpose', 'outcome', 'duration_minutes')
    list_filter = ('purpose', 'outcome', 'call_date')
    search_fields = ('contact__name', 'performed_by__name', 'notes')


@admin.register(CoachingEvaluation)
class CoachingEvaluationAdmin(admin.ModelAdmin):
    list_display = ('rep', 'manager', 'customer', 'date', 'overall_score')
    list_filter = ('date', 'manager')
    search_fields = ('rep__name', 'customer__name', 'manager__name')
