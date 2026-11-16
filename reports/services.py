import datetime
from decimal import Decimal
from django.db import models
from django.db.models import Sum, Count, Q, Avg, F, Case, When, Value, DecimalField, IntegerField
from django.utils import timezone
from django.http import HttpResponse

from accounts.permissions import get_scoped_queryset
from contacts.models import Contact
from sales.models import SalesOrder, SalesOrderItem, SalesReturnOrder, SalesReturnOrderItem, Collection, CustomerAccount, CustomerTransaction
from purchases.models import PurchaseOrder, PurchaseOrderItem
from inventory.models import Warehouse, InventoryStock
from activities.models import Visit, PlannedVisitDay, PlannedVisitItem, Agreement, VisitSampleItem, VisitExpense
from reports.models import SalesTarget, CustomerCall, CoachingEvaluation
from master_data.models import Area


def parse_date_range(period=None, start_date_str=None, end_date_str=None):
    """
    Parses and standardizes date ranges with prior period comparison dates.
    Returns (start_date, end_date, prior_start_date, prior_end_date, period_label)
    """
    today = timezone.now().date()
    
    if period == 'last_month':
        # First day of last month
        first_of_this_month = today.replace(day=1)
        end_date = first_of_this_month - datetime.timedelta(days=1)
        start_date = end_date.replace(day=1)
        # Prior month (2 months ago)
        prior_end = start_date - datetime.timedelta(days=1)
        prior_start = prior_end.replace(day=1)
        period_label = 'الشهر الماضي'
        
    elif period == 'quarter':
        start_date = today - datetime.timedelta(days=90)
        end_date = today
        prior_end = start_date - datetime.timedelta(days=1)
        prior_start = prior_end - datetime.timedelta(days=90)
        period_label = 'آخر 90 يوماً'
        
    elif period == 'year':
        start_date = today.replace(month=1, day=1)
        end_date = today
        prior_start = start_date.replace(year=start_date.year - 1)
        prior_end = end_date.replace(year=end_date.year - 1)
        period_label = 'العام الحالي'
        
    elif period == 'custom' and start_date_str and end_date_str:
        try:
            start_date = datetime.date.fromisoformat(start_date_str)
            end_date = datetime.date.fromisoformat(end_date_str)
            days = (end_date - start_date).days
            prior_end = start_date - datetime.timedelta(days=1)
            prior_start = prior_end - datetime.timedelta(days=max(1, days))
            period_label = f"من {start_date} إلى {end_date}"
        except Exception:
            start_date = today.replace(day=1)
            end_date = today
            prior_start = (start_date - datetime.timedelta(days=1)).replace(day=1)
            prior_end = start_date - datetime.timedelta(days=1)
            period_label = 'الشهر الحالي'
    else:
        # Default: this month
        start_date = today.replace(day=1)
        end_date = today
        # Prior month to same relative date
        prior_end_month = start_date - datetime.timedelta(days=1)
        prior_start = prior_end_month.replace(day=1)
        prior_day = min(today.day, prior_end_month.day)
        prior_end = prior_start.replace(day=prior_day)
        period_label = 'الشهر الحالي'
        
    return start_date, end_date, prior_start, prior_end, period_label


def calculate_variance(current, prior):
    """Safely calculates percentage change between current and prior metric."""
    c = float(current or 0)
    p = float(prior or 0)
    if p == 0:
        return 100.0 if c > 0 else 0.0
    return round(((c - p) / p) * 100.0, 1)


def safe_div(numerator, denominator, precision=2, default=0.0):
    """Safely performs division without ZeroDivisionError."""
    num = float(numerator or 0)
    den = float(denominator or 0)
    if den == 0:
        return default
    return round(num / den, precision)


def calculate_expected_working_days(start_date, end_date):
    """Calculates official business days in date range (excluding Fridays & Saturdays)."""
    cur = start_date
    working_days = 0
    while cur <= end_date:
        # In Egypt: Friday=4, Saturday=5 in Python weekday() (Monday=0)
        if cur.weekday() not in (4, 5):
            working_days += 1
        cur += datetime.timedelta(days=1)
    return max(1, working_days)


# ==============================================================================
# PERFORMANCE AGGREGATION SERVICES
# ==============================================================================

def get_performance_overview_data(user, start_date, end_date, prior_start, prior_end, filters=None):
    """
    Computes all 22 KPIs for the Performance Overview screen with prior-month comparison deltas.
    """
    filters = filters or {}
    rep_id = filters.get('rep_id')
    area_id = filters.get('area_id')
    account_type = filters.get('account_type')

    # Base scoped querysets
    visits_qs = get_scoped_queryset(Visit.objects.all(), user)
    contacts_qs = get_scoped_queryset(Contact.objects.filter(is_customer=True), user)
    orders_qs = get_scoped_queryset(SalesOrder.objects.exclude(status='cancelled'), user)
    collections_qs = get_scoped_queryset(Collection.objects.all(), user)
    expenses_qs = get_scoped_queryset(VisitExpense.objects.all(), user)
    coaching_qs = get_scoped_queryset(CoachingEvaluation.objects.all(), user)
    planned_items_qs = get_scoped_queryset(PlannedVisitItem.objects.all(), user)

    # Apply filters
    if rep_id:
        visits_qs = visits_qs.filter(owner_id=rep_id)
        orders_qs = orders_qs.filter(created_by_id=rep_id)
        collections_qs = collections_qs.filter(created_by_id=rep_id)
        expenses_qs = expenses_qs.filter(visit__owner_id=rep_id)
        coaching_qs = coaching_qs.filter(rep_id=rep_id)
        contacts_qs = contacts_qs.filter(Q(assigned_team__id=rep_id) | Q(created_by_id=rep_id))
        planned_items_qs = planned_items_qs.filter(plan_day__assignee_id=rep_id)

    if area_id:
        visits_qs = visits_qs.filter(Q(contact__area_id=area_id) | Q(contact__brick_id=area_id))
        orders_qs = orders_qs.filter(Q(customer__area_id=area_id) | Q(customer__brick_id=area_id))
        collections_qs = collections_qs.filter(Q(customer__area_id=area_id) | Q(customer__brick_id=area_id))
        contacts_qs = contacts_qs.filter(Q(area_id=area_id) | Q(brick_id=area_id))

    if account_type:
        visits_qs = visits_qs.filter(contact__account_type__iexact=account_type)
        contacts_qs = contacts_qs.filter(account_type__iexact=account_type)

    def _compute_period_stats(s_date, e_date):
        v_sub = visits_qs.filter(date__gte=s_date, date__lte=e_date)
        o_sub = orders_qs.filter(order_date__gte=s_date, order_date__lte=e_date)
        c_sub = collections_qs.filter(collection_date__gte=s_date, collection_date__lte=e_date)
        e_sub = expenses_qs.filter(visit__date__gte=s_date, visit__date__lte=e_date)
        p_sub = planned_items_qs.filter(plan_day__date__gte=s_date, plan_day__date__lte=e_date)
        coach_sub = coaching_qs.filter(date__gte=s_date, date__lte=e_date)

        total_contacts = contacts_qs.count()
        visited_contacts = v_sub.values('contact_id').distinct().count()
        coverage_pct = safe_div(visited_contacts * 100, total_contacts, 1)

        total_visits = v_sub.count()
        frequency = safe_div(total_visits, visited_contacts, 2)
        # Target frequency standard is 2 visits per contact per month
        target_frequency = 2.0
        frequency_ach_pct = safe_div(frequency * 100, target_frequency, 1)

        expected_days = calculate_expected_working_days(s_date, e_date)
        field_days = v_sub.values('date').distinct().count()
        off_field_days = max(0, expected_days - field_days)

        daily_rate = safe_div(total_visits, field_days, 1)
        target_daily_rate = 10.0
        daily_rate_ach_pct = safe_div(daily_rate * 100, target_daily_rate, 1)
        smart_daily_rate = safe_div(total_visits, max(1, expected_days), 1)

        # Durations & hours
        total_duration_sec = v_sub.aggregate(total=Sum('duration'))['total'] or 0
        avg_visit_duration_mins = safe_div(total_duration_sec / 60.0, total_visits, 1)
        avg_working_hours = safe_div(total_duration_sec / 3600.0, max(1, field_days), 1)

        # Detailing
        detailing_count = v_sub.aggregate(total=Count('detailed_products'))['total'] or 0
        visits_with_detailing = v_sub.filter(detailed_products__isnull=False).distinct().count()
        avg_detailing = safe_div(detailing_count, visits_with_detailing, 1)

        # Planned vs Unplanned
        planned_visits = v_sub.filter(is_planned=True).count()
        unplanned_visits = v_sub.filter(is_planned=False).count()
        planned_pct = safe_div(planned_visits * 100, total_visits, 1)
        unplanned_pct = safe_div(unplanned_visits * 100, total_visits, 1)

        total_planned_items = p_sub.count()
        executed_planned_items = p_sub.filter(is_executed=True).count()
        plan_ach_pct = safe_div(executed_planned_items * 100, total_planned_items, 1) if total_planned_items > 0 else (100.0 if planned_visits > 0 else 0.0)

        # Double visits & coaching
        double_visits = v_sub.filter(doubled=True).count()
        double_visits_pct = safe_div(double_visits * 100, total_visits, 1)
        assessments_count = coach_sub.count()

        # Financials
        expenses_total = e_sub.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        sales_count = o_sub.count()
        sales_total = o_sub.aggregate(total=Sum('grand_total'))['total'] or Decimal('0.00')
        collections_count = c_sub.count()
        collections_total = c_sub.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

        return {
            'total_contacts': total_contacts,
            'visited_contacts': visited_contacts,
            'coverage_pct': coverage_pct,
            'total_visits': total_visits,
            'frequency': frequency,
            'frequency_ach_pct': frequency_ach_pct,
            'expected_days': expected_days,
            'field_days': field_days,
            'off_field_days': off_field_days,
            'daily_rate': daily_rate,
            'daily_rate_ach_pct': daily_rate_ach_pct,
            'smart_daily_rate': smart_daily_rate,
            'avg_visit_duration_mins': avg_visit_duration_mins,
            'avg_working_hours': avg_working_hours,
            'detailing_count': detailing_count,
            'avg_detailing': avg_detailing,
            'planned_visits': planned_visits,
            'unplanned_visits': unplanned_visits,
            'planned_pct': planned_pct,
            'unplanned_pct': unplanned_pct,
            'plan_ach_pct': plan_ach_pct,
            'double_visits': double_visits,
            'double_visits_pct': double_visits_pct,
            'assessments_count': assessments_count,
            'expenses_total': expenses_total,
            'sales_count': sales_count,
            'sales_total': sales_total,
            'collections_count': collections_count,
            'collections_total': collections_total,
        }

    current = _compute_period_stats(start_date, end_date)
    prior = _compute_period_stats(prior_start, prior_end)

    # Build KPI list with variance
    kpis = {
        'coverage': {
            'value': current['coverage_pct'],
            'unit': '%',
            'label': 'نسبة التغطية',
            'variance': calculate_variance(current['coverage_pct'], prior['coverage_pct']),
            'icon': 'pie_chart',
            'detail': f"{current['visited_contacts']} من {current['total_contacts']} عميل",
        },
        'frequency_ach': {
            'value': current['frequency_ach_pct'],
            'unit': '%',
            'label': 'تحقيق التكرار',
            'variance': calculate_variance(current['frequency_ach_pct'], prior['frequency_ach_pct']),
            'icon': 'repeat',
            'detail': f"المعدل الفعلي: {current['frequency']}",
        },
        'daily_rate_ach': {
            'value': current['daily_rate_ach_pct'],
            'unit': '%',
            'label': 'تحقيق المعدل اليومي',
            'variance': calculate_variance(current['daily_rate_ach_pct'], prior['daily_rate_ach_pct']),
            'icon': 'speed',
            'detail': f"الفعلي: {current['daily_rate']} زيارة/يوم",
        },
        'plan_ach': {
            'value': current['plan_ach_pct'],
            'unit': '%',
            'label': 'تحقيق خطة الزيارات',
            'variance': calculate_variance(current['plan_ach_pct'], prior['plan_ach_pct']),
            'icon': 'event_available',
            'detail': f"{current['planned_visits']} زيارة مخططة",
        },
        'frequency': {
            'value': current['frequency'],
            'unit': '',
            'label': 'معدل التكرار (Frequency)',
            'variance': calculate_variance(current['frequency'], prior['frequency']),
            'icon': 'sync',
            'detail': 'متوسط الزيارات لكل عميل',
        },
        'daily_rate': {
            'value': current['daily_rate'],
            'unit': '',
            'label': 'معدل الزيارات اليومي',
            'variance': calculate_variance(current['daily_rate'], prior['daily_rate']),
            'icon': 'directions_walk',
            'detail': f"في {current['field_days']} يوم ميداني",
        },
        'smart_daily_rate': {
            'value': current['smart_daily_rate'],
            'unit': '',
            'label': 'المعدل اليومي الذكي',
            'variance': calculate_variance(current['smart_daily_rate'], prior['smart_daily_rate']),
            'icon': 'bolt',
            'detail': 'محسوب على إجمالي أيام العمل',
        },
        'expected_days': {
            'value': current['expected_days'],
            'unit': 'يوم',
            'label': 'أيام العمل المتوقعة',
            'variance': 0.0,
            'icon': 'calendar_today',
            'detail': 'بدون العطلات الأسبوعية',
        },
        'field_days': {
            'value': current['field_days'],
            'unit': 'يوم',
            'label': 'أيام العمل الميدانية',
            'variance': calculate_variance(current['field_days'], prior['field_days']),
            'icon': 'location_on',
            'detail': f"أيام غير ميدانية: {current['off_field_days']}",
        },
        'off_field_days': {
            'value': current['off_field_days'],
            'unit': 'يوم',
            'label': 'أيام بدون زيارات',
            'variance': calculate_variance(current['off_field_days'], prior['off_field_days']),
            'icon': 'event_busy',
            'detail': 'مكتبية أو إجازات',
        },
        'avg_working_hours': {
            'value': current['avg_working_hours'],
            'unit': 'ساعة',
            'label': 'متوسط ساعات العمل',
            'variance': calculate_variance(current['avg_working_hours'], prior['avg_working_hours']),
            'icon': 'schedule',
            'detail': 'لكل يوم ميداني',
        },
        'avg_visit_duration': {
            'value': current['avg_visit_duration_mins'],
            'unit': 'دقيقة',
            'label': 'متوسط مدة الزيارة',
            'variance': calculate_variance(current['avg_visit_duration_mins'], prior['avg_visit_duration_mins']),
            'icon': 'timer',
            'detail': 'مدة الزيارة الواحدة',
        },
        'detailing_count': {
            'value': current['detailing_count'],
            'unit': 'مرة',
            'label': 'شرح المنتجات (Detailing)',
            'variance': calculate_variance(current['detailing_count'], prior['detailing_count']),
            'icon': 'medical_services',
            'detail': f"متوسط: {current['avg_detailing']} بالزيارة",
        },
        'total_visits': {
            'value': current['total_visits'],
            'unit': 'زيارة',
            'label': 'إجمالي الزيارات المنفذة',
            'variance': calculate_variance(current['total_visits'], prior['total_visits']),
            'icon': 'pin_drop',
            'detail': f"مخطط {current['planned_pct']}% | خارج خطة {current['unplanned_pct']}%",
        },
        'double_visits': {
            'value': current['double_visits'],
            'unit': 'زيارة',
            'label': 'الزيارات المزدوجة',
            'variance': calculate_variance(current['double_visits'], prior['double_visits']),
            'icon': 'groups',
            'detail': f"نسبة: {current['double_visits_pct']}% من الإجمالي",
        },
        'assessments_count': {
            'value': current['assessments_count'],
            'unit': 'تقييم',
            'label': 'تقييمات الكوتشينج',
            'variance': calculate_variance(current['assessments_count'], prior['assessments_count']),
            'icon': 'rate_review',
            'detail': 'جلسات تقييم المشرفين',
        },
        'expenses_total': {
            'value': float(current['expenses_total']),
            'unit': 'ج.م',
            'label': 'المصروفات الميدانية',
            'variance': calculate_variance(current['expenses_total'], prior['expenses_total']),
            'icon': 'receipt_long',
            'detail': 'إجمالي نفقات الزيارات',
        },
        'sales_total': {
            'value': float(current['sales_total']),
            'unit': 'ج.م',
            'label': 'قيمة أوامر البيع',
            'variance': calculate_variance(current['sales_total'], prior['sales_total']),
            'icon': 'shopping_bag',
            'detail': f"{current['sales_count']} أمر بيع",
        },
        'collections_total': {
            'value': float(current['collections_total']),
            'unit': 'ج.م',
            'label': 'إجمالي التحصيلات',
            'variance': calculate_variance(current['collections_total'], prior['collections_total']),
            'icon': 'payments',
            'detail': f"{current['collections_count']} سند تحصيل",
        },
    }

    # Top Detailed Products
    cur_visits = visits_qs.filter(date__gte=start_date, date__lte=end_date)
    top_products_raw = (
        cur_visits.filter(detailed_products__isnull=False)
        .values('detailed_products__id', 'detailed_products__name', 'detailed_products__sku_code')
        .annotate(count=Count('detailed_products__id'))
        .order_by('-count')[:10]
    )
    total_det = current['detailing_count'] or 1
    top_detailed_products = [
        {
            'id': p['detailed_products__id'],
            'name': p['detailed_products__name'],
            'code': p['detailed_products__sku_code'],
            'count': p['count'],
            'share_pct': safe_div(p['count'] * 100, total_det, 1),
        }
        for p in top_products_raw if p['detailed_products__id']
    ]

    return {
        'kpis': kpis,
        'current': current,
        'prior': prior,
        'top_detailed_products': top_detailed_products,
    }


def get_performance_analysis_data(user, start_date, end_date, filters=None):
    """
    Computes comparative analytics across representatives, including the 8 comparison charts
    and the 11-column rep summary comparison table.
    """
    filters = filters or {}
    area_id = filters.get('area_id')

    # Get subordinates or reps
    from accounts.models import User
    users_qs = get_scoped_queryset(User.objects.filter(is_active=True), user)
    # Filter reps and managers
    reps = users_qs.filter(
        Q(role__is_rep=True) |
        Q(role__is_sales_team=True) |
        Q(role__is_area_manager=True) |
        Q(role__name__in=['rep', 'medical_rep', 'manager'])
    ).distinct().order_by('name')

    if area_id:
        reps = reps.filter(Q(assigned_areas__id=area_id) | Q(assigned_areas__parent_id=area_id)).distinct()

    rep_summary_table = []
    chart_reps = []
    chart_coverage = []
    chart_plan_ach = []
    chart_coaching = []
    chart_working_days = []
    chart_detailing = []
    chart_visits_volume = []
    chart_total_duration = []
    chart_avg_duration = []

    expected_days = calculate_expected_working_days(start_date, end_date)

    for rep in reps:
        v_qs = Visit.objects.filter(owner=rep, date__gte=start_date, date__lte=end_date)
        assigned_contacts = Contact.objects.filter(
            Q(assigned_team=rep) | Q(created_by=rep), is_customer=True
        ).distinct().count()
        if assigned_contacts == 0:
            # Fallback to contacts in rep's assigned bricks
            rep_bricks = rep.assigned_areas.filter(parent__isnull=False)
            if rep_bricks.exists():
                assigned_contacts = Contact.objects.filter(brick__in=rep_bricks, is_customer=True).count()

        visited_contacts = v_qs.values('contact_id').distinct().count()
        coverage_pct = safe_div(visited_contacts * 100, assigned_contacts, 1)

        total_visits = v_qs.count()
        planned_visits = v_qs.filter(is_planned=True).count()
        unplanned_visits = v_qs.filter(is_planned=False).count()
        frequency = safe_div(total_visits, visited_contacts, 2)

        field_days = v_qs.values('date').distinct().count()
        daily_rate = safe_div(total_visits, field_days, 1)
        detailing_count = v_qs.aggregate(t=Count('detailed_products'))['t'] or 0

        total_duration_sec = v_qs.aggregate(t=Sum('duration'))['t'] or 0
        total_duration_hours = safe_div(total_duration_sec / 3600.0, 1, 1)
        avg_duration_mins = safe_div(total_duration_sec / 60.0, total_visits, 1)

        sales_val = SalesOrder.objects.filter(
            created_by=rep, order_date__gte=start_date, order_date__lte=end_date
        ).exclude(status='cancelled').aggregate(t=Sum('grand_total'))['t'] or Decimal('0.00')

        col_val = Collection.objects.filter(
            created_by=rep, collection_date__gte=start_date, collection_date__lte=end_date
        ).aggregate(t=Sum('amount'))['t'] or Decimal('0.00')

        coaching_count = CoachingEvaluation.objects.filter(
            rep=rep, date__gte=start_date, date__lte=end_date
        ).count()
        double_visits_count = v_qs.filter(doubled=True).count()

        plan_ach_pct = safe_div(planned_visits * 100, max(1, planned_visits + unplanned_visits), 1)

        area_name = rep.assigned_areas.filter(parent__isnull=True).first()
        area_name_str = area_name.name if area_name else (rep.assigned_areas.first().name if rep.assigned_areas.exists() else 'غير محدد')

        rep_row = {
            'rep_id': rep.id,
            'name': rep.name or rep.username,
            'code': getattr(rep, 'code', None) or str(rep.id),
            'area_name': area_name_str,
            'assigned_contacts': assigned_contacts,
            'visited_contacts': visited_contacts,
            'coverage_pct': coverage_pct,
            'total_visits': total_visits,
            'planned_visits': planned_visits,
            'unplanned_visits': unplanned_visits,
            'frequency': frequency,
            'field_days': field_days,
            'off_field_days': max(0, expected_days - field_days),
            'daily_rate': daily_rate,
            'detailing_count': detailing_count,
            'sales_val': float(sales_val),
            'col_val': float(col_val),
            'total_duration_hours': total_duration_hours,
            'avg_duration_mins': avg_duration_mins,
            'coaching_count': coaching_count,
            'double_visits': double_visits_count,
            'plan_ach_pct': plan_ach_pct,
        }
        rep_summary_table.append(rep_row)

        # Append to chart datasets
        rep_label = (rep.name or rep.username).split()[0]
        chart_reps.append(rep_label)
        chart_coverage.append(coverage_pct)
        chart_plan_ach.append(plan_ach_pct)
        chart_coaching.append(coaching_count + double_visits_count)
        chart_working_days.append(field_days)
        chart_detailing.append(detailing_count)
        chart_visits_volume.append(total_visits)
        chart_total_duration.append(total_duration_hours)
        chart_avg_duration.append(avg_duration_mins)

    return {
        'rep_summary_table': rep_summary_table,
        'charts': {
            'reps': chart_reps,
            'coverage': chart_coverage,
            'plan_ach': chart_plan_ach,
            'coaching': chart_coaching,
            'working_days': chart_working_days,
            'detailing': chart_detailing,
            'visits_volume': chart_visits_volume,
            'total_duration': chart_total_duration,
            'avg_duration': chart_avg_duration,
        }
    }


def get_performance_daily_data(user, target_date, filters=None):
    """
    Computes daily performance summary, 20-column daily rep grid, and 8 daily drilldown tabs.
    """
    filters = filters or {}
    yesterday = target_date - datetime.timedelta(days=1)

    visits_qs = get_scoped_queryset(Visit.objects.all(), user)
    orders_qs = get_scoped_queryset(SalesOrder.objects.exclude(status='cancelled'), user)
    collections_qs = get_scoped_queryset(Collection.objects.all(), user)
    expenses_qs = get_scoped_queryset(VisitExpense.objects.all(), user)
    calls_qs = get_scoped_queryset(CustomerCall.objects.all(), user)
    contacts_qs = get_scoped_queryset(Contact.objects.all(), user)

    # Today vs Yesterday KPIs
    today_visits_cnt = visits_qs.filter(date=target_date).count()
    yesterday_visits_cnt = visits_qs.filter(date=yesterday).count()

    today_reps_cnt = visits_qs.filter(date=target_date).values('owner_id').distinct().count()
    yesterday_reps_cnt = visits_qs.filter(date=yesterday).values('owner_id').distinct().count()

    today_orders_val = orders_qs.filter(order_date=target_date).aggregate(t=Sum('grand_total'))['t'] or Decimal('0.00')
    yesterday_orders_val = orders_qs.filter(order_date=yesterday).aggregate(t=Sum('grand_total'))['t'] or Decimal('0.00')

    today_col_val = collections_qs.filter(collection_date=target_date).aggregate(t=Sum('amount'))['t'] or Decimal('0.00')
    yesterday_col_val = collections_qs.filter(collection_date=yesterday).aggregate(t=Sum('amount'))['t'] or Decimal('0.00')

    daily_kpis = {
        'visits': {
            'today': today_visits_cnt,
            'yesterday': yesterday_visits_cnt,
            'variance': calculate_variance(today_visits_cnt, yesterday_visits_cnt),
        },
        'active_reps': {
            'today': today_reps_cnt,
            'yesterday': yesterday_reps_cnt,
            'variance': calculate_variance(today_reps_cnt, yesterday_reps_cnt),
        },
        'orders_val': {
            'today': float(today_orders_val),
            'yesterday': float(yesterday_orders_val),
            'variance': calculate_variance(today_orders_val, yesterday_orders_val),
        },
        'collections_val': {
            'today': float(today_col_val),
            'yesterday': float(yesterday_col_val),
            'variance': calculate_variance(today_col_val, yesterday_col_val),
        },
    }

    # Daily Rep Grid (20 columns)
    from accounts.models import User
    reps = get_scoped_queryset(User.objects.filter(is_active=True), user).filter(
        Q(role__is_rep=True) | Q(role__is_sales_team=True) | Q(role__name__in=['rep', 'medical_rep'])
    ).distinct().order_by('name')

    daily_rep_grid = []
    for rep in reps:
        v_day = visits_qs.filter(owner=rep, date=target_date)
        total_v = v_day.count()
        first_v = v_day.order_by('started_at').first()
        last_v = v_day.order_by('-ended_at').first()

        first_time = first_v.started_at.strftime('%H:%M') if (first_v and first_v.started_at) else (first_v.time.strftime('%H:%M') if (first_v and first_v.time) else '–')
        last_time = last_v.ended_at.strftime('%H:%M') if (last_v and last_v.ended_at) else (last_v.time.strftime('%H:%M') if (last_v and last_v.time) else '–')

        total_sec = v_day.aggregate(t=Sum('duration'))['t'] or 0
        working_hours = safe_div(total_sec / 3600.0, 1, 1)

        planned_cnt = v_day.filter(is_planned=True).count()
        completed_cnt = v_day.filter(status='finished').count()
        unplanned_cnt = v_day.filter(is_planned=False).count()
        cancelled_cnt = v_day.filter(status='cancelled').count()
        double_cnt = v_day.filter(doubled=True).count()
        detailing_cnt = v_day.aggregate(t=Count('detailed_products'))['t'] or 0

        in_range_cnt = v_day.filter(requires_approval_due_to_distance=False, location_verified=True).count()
        in_range_pct = safe_div(in_range_cnt * 100, total_v, 1)
        out_range_pct = safe_div((total_v - in_range_cnt) * 100, total_v, 1)
        verified_pct = safe_div(v_day.filter(location_verified=True).count() * 100, total_v, 1)
        photos_taken = v_day.filter(location_photo__isnull=False).count()

        rep_orders = orders_qs.filter(created_by=rep, order_date=target_date)
        orders_cnt = rep_orders.count()
        orders_val = rep_orders.aggregate(t=Sum('grand_total'))['t'] or Decimal('0.00')

        rep_cols = collections_qs.filter(created_by=rep, collection_date=target_date)
        cols_val = rep_cols.aggregate(t=Sum('amount'))['t'] or Decimal('0.00')

        exp_val = expenses_qs.filter(visit__owner=rep, visit__date=target_date).aggregate(t=Sum('amount'))['t'] or Decimal('0.00')

        status_label = 'نشط وميداني' if total_v > 0 else 'بدون زيارات'
        status_color = 'emerald' if total_v >= 5 else ('amber' if total_v > 0 else 'slate')

        area_str = rep.assigned_areas.first().name if rep.assigned_areas.exists() else 'غير محدد'

        daily_rep_grid.append({
            'rep_id': rep.id,
            'name': rep.name or rep.username,
            'area': area_str,
            'first_checkin': first_time,
            'last_checkout': last_time,
            'working_hours': working_hours,
            'planned_visits': planned_cnt,
            'completed_visits': completed_cnt,
            'unplanned_visits': unplanned_cnt,
            'cancelled_visits': cancelled_cnt,
            'double_visits': double_cnt,
            'detailing_count': detailing_cnt,
            'in_range_pct': in_range_pct,
            'out_range_pct': out_range_pct,
            'verified_pct': verified_pct,
            'photos_taken': photos_taken,
            'orders_count': orders_cnt,
            'orders_val': float(orders_val),
            'cols_val': float(cols_val),
            'expenses_val': float(exp_val),
            'status': status_label,
            'status_color': status_color,
        })

    # 8 Daily Drilldown Sub-tabs
    subtabs = {
        'visits': visits_qs.filter(date=target_date).select_related('contact', 'owner').order_by('-id')[:100],
        'customers': contacts_qs.filter(visits__date=target_date).distinct()[:100],
        'calls': calls_qs.filter(call_date=target_date).select_related('contact', 'performed_by')[:100],
        'expenses': expenses_qs.filter(visit__date=target_date).select_related('visit', 'visit__owner')[:100],
        'tasks': PlannedVisitItem.objects.filter(plan_day__date=target_date).select_related('contact', 'plan_day__assignee')[:100],
        'approvals': visits_qs.filter(date=target_date, approval_status='pending').select_related('contact', 'owner')[:100],
        'orders': orders_qs.filter(order_date=target_date).select_related('customer', 'created_by')[:100],
        'collections': collections_qs.filter(collection_date=target_date).select_related('customer', 'created_by', 'vault')[:100],
    }

    return {
        'target_date': target_date,
        'yesterday': yesterday,
        'daily_kpis': daily_kpis,
        'daily_rep_grid': daily_rep_grid,
        'subtabs': subtabs,
    }


def get_performance_detailed_matrix(user, start_date, end_date, filters=None):
    """
    Computes the 63-column mega performance matrix per representative and coaching logs.
    """
    filters = filters or {}
    area_id = filters.get('area_id')

    from accounts.models import User
    reps = get_scoped_queryset(User.objects.filter(is_active=True), user).filter(
        Q(role__is_rep=True) | Q(role__is_sales_team=True) | Q(role__name__in=['rep', 'medical_rep'])
    ).distinct().order_by('name')

    if area_id:
        reps = reps.filter(Q(assigned_areas__id=area_id) | Q(assigned_areas__parent_id=area_id)).distinct()

    matrix_rows = []
    for rep in reps:
        v_qs = Visit.objects.filter(owner=rep, date__gte=start_date, date__lte=end_date)
        total_visits = v_qs.count()

        # Customer Scoping
        rep_bricks = rep.assigned_areas.filter(parent__isnull=False)
        cust_base = Contact.objects.filter(
            Q(assigned_team=rep) | Q(created_by=rep) | (Q(brick__in=rep_bricks) if rep_bricks.exists() else Q(pk=0)),
            is_customer=True
        ).distinct()

        doctors_count = cust_base.filter(Q(account_type__iexact='clinic') | Q(account_type__iexact='physician') | Q(name__icontains='د.')).count()
        pharmacies_count = cust_base.filter(Q(account_type__iexact='pharmacy') | Q(name__icontains='صيدلية')).count()
        hospitals_count = cust_base.filter(Q(account_type__iexact='hospital') | Q(name__icontains='مستشفى')).count()
        stores_count = cust_base.filter(Q(account_type__iexact='store') | Q(name__icontains='مخزن')).count()

        # Class coverage
        class_a_total = cust_base.filter(customer_category='A').count()
        class_a_vis = v_qs.filter(contact__customer_category='A').values('contact_id').distinct().count()
        class_a_cov = safe_div(class_a_vis * 100, class_a_total, 1)

        class_b_total = cust_base.filter(customer_category='B').count()
        class_b_vis = v_qs.filter(contact__customer_category='B').values('contact_id').distinct().count()
        class_b_cov = safe_div(class_b_vis * 100, class_b_total, 1)

        class_c_total = cust_base.filter(customer_category='C').count()
        class_c_vis = v_qs.filter(contact__customer_category='C').values('contact_id').distinct().count()
        class_c_cov = safe_div(class_c_vis * 100, class_c_total, 1)

        # Shifts
        am_visits = v_qs.filter(contact__visit_timing='AM').count()
        pm_visits = v_qs.filter(contact__visit_timing='PM').count()
        na_visits = total_visits - (am_visits + pm_visits)

        # Durations & Mileage
        total_sec = v_qs.aggregate(t=Sum('duration'))['t'] or 0
        avg_dur_mins = safe_div(total_sec / 60.0, total_visits, 1)

        # Compliance
        in_range_cnt = v_qs.filter(requires_approval_due_to_distance=False, location_verified=True).count()
        out_range_cnt = total_visits - in_range_cnt
        bypassed_cnt = v_qs.filter(bypassed_by__isnull=False).count()

        # Detailing & Samples
        det_cnt = v_qs.aggregate(t=Count('detailed_products'))['t'] or 0
        samples_cnt = VisitSampleItem.objects.filter(visit__in=v_qs).aggregate(t=Sum('quantity'))['t'] or 0

        # Commercial
        sales_qs = SalesOrder.objects.filter(created_by=rep, order_date__gte=start_date, order_date__lte=end_date).exclude(status='cancelled')
        sales_cnt = sales_qs.count()
        sales_gross = sales_qs.aggregate(t=Sum('subtotal'))['t'] or Decimal('0.00')
        sales_net = sales_qs.aggregate(t=Sum('grand_total'))['t'] or Decimal('0.00')

        cols_qs = Collection.objects.filter(created_by=rep, collection_date__gte=start_date, collection_date__lte=end_date)
        cols_cnt = cols_qs.count()
        cols_net = cols_qs.aggregate(t=Sum('amount'))['t'] or Decimal('0.00')

        area_obj = rep.assigned_areas.filter(parent__isnull=True).first()
        area_name = area_obj.name if area_obj else (rep.assigned_areas.first().name if rep.assigned_areas.exists() else 'غير محدد')

        matrix_rows.append({
            'rep_id': rep.id,
            'name': rep.name or rep.username,
            'code': getattr(rep, 'code', None) or str(rep.id),
            'area': area_name,
            'total_doctors': doctors_count,
            'total_pharmacies': pharmacies_count,
            'total_hospitals': hospitals_count,
            'total_stores': stores_count,
            'class_a_cov': class_a_cov,
            'class_b_cov': class_b_cov,
            'class_c_cov': class_c_cov,
            'total_visits': total_visits,
            'planned_visits': v_qs.filter(is_planned=True).count(),
            'unplanned_visits': v_qs.filter(is_planned=False).count(),
            'am_visits': am_visits,
            'pm_visits': pm_visits,
            'na_visits': na_visits,
            'avg_duration': avg_dur_mins,
            'in_range_cnt': in_range_cnt,
            'out_range_cnt': out_range_cnt,
            'bypassed_cnt': bypassed_cnt,
            'detailing_cnt': det_cnt,
            'samples_cnt': samples_cnt,
            'sales_cnt': sales_cnt,
            'sales_gross': float(sales_gross),
            'sales_net': float(sales_net),
            'cols_cnt': cols_cnt,
            'cols_net': float(cols_net),
        })

    coaching_logs = CoachingEvaluation.objects.filter(
        date__gte=start_date, date__lte=end_date
    ).select_related('rep', 'manager', 'customer').order_by('-date')[:50]

    return {
        'matrix_rows': matrix_rows,
        'coaching_logs': coaching_logs,
    }


# ==============================================================================
# REPORTS AGGREGATION SERVICES (THE 13 STANDALONE REPORTS)
# ==============================================================================

def get_ar_aging_report_data(user, filters=None):
    """
    Report 1: Accounts Receivable Aging (أعمار الديون).
    Categorizes outstanding debt into aging buckets (Current, 1-30, 31-60, 61-90, 91-120, >120) and computes DSO.
    """
    filters = filters or {}
    area_id = filters.get('area_id')
    brick_id = filters.get('brick_id')
    rep_id = filters.get('rep_id')
    overdue_only = filters.get('overdue_only')

    accounts_qs = get_scoped_queryset(CustomerAccount.objects.select_related('customer', 'customer__area', 'customer__brick'), user)

    if area_id:
        accounts_qs = accounts_qs.filter(customer__area_id=area_id)
    if brick_id:
        accounts_qs = accounts_qs.filter(customer__brick_id=brick_id)
    if rep_id:
        accounts_qs = accounts_qs.filter(Q(customer__assigned_team__id=rep_id) | Q(customer__created_by_id=rep_id))
    if overdue_only:
        accounts_qs = accounts_qs.filter(current_balance__gt=0, overdue_balance__gt=0)
    else:
        accounts_qs = accounts_qs.filter(current_balance__gt=0)

    today = timezone.now().date()
    rows = []
    tot_receivables = Decimal('0.00')
    tot_overdue = Decimal('0.00')
    tot_bucket_1_30 = Decimal('0.00')
    tot_bucket_31_60 = Decimal('0.00')
    tot_bucket_61_90 = Decimal('0.00')
    tot_bucket_91_120 = Decimal('0.00')
    tot_bucket_over_120 = Decimal('0.00')

    # Total credit sales in last 90 days for DSO
    ninety_days_ago = today - datetime.timedelta(days=90)
    total_sales_90d = SalesOrder.objects.filter(
        order_date__gte=ninety_days_ago
    ).exclude(status='cancelled').aggregate(t=Sum('grand_total'))['t'] or Decimal('0.00')

    for acc in accounts_qs[:500]:
        c = acc.customer
        balance = acc.current_balance
        overdue = acc.overdue_balance

        # Calculate aging buckets based on unpaid transactions with due_date
        txs = acc.transactions.filter(transaction_type='debit', due_date__isnull=False)
        b_1_30 = Decimal('0.00')
        b_31_60 = Decimal('0.00')
        b_61_90 = Decimal('0.00')
        b_91_120 = Decimal('0.00')
        b_over_120 = Decimal('0.00')

        for tx in txs:
            if tx.due_date and tx.due_date < today:
                days = (today - tx.due_date).days
                amt = tx.debit
                if days <= 30:
                    b_1_30 += amt
                elif days <= 60:
                    b_31_60 += amt
                elif days <= 90:
                    b_61_90 += amt
                elif days <= 120:
                    b_91_120 += amt
                else:
                    b_over_120 += amt

        # Normalization if transaction breakdown exceeds or doesn't sum to overdue
        if overdue > 0 and (b_1_30 + b_31_60 + b_61_90 + b_91_120 + b_over_120) == 0:
            b_1_30 = overdue  # fallback

        rep = c.assigned_team.first() or c.created_by
        rep_name = rep.name or rep.username if rep else '–'

        tot_receivables += balance
        tot_overdue += overdue
        tot_bucket_1_30 += b_1_30
        tot_bucket_31_60 += b_31_60
        tot_bucket_61_90 += b_61_90
        tot_bucket_91_120 += b_91_120
        tot_bucket_over_120 += b_over_120

        rows.append({
            'code': c.code or str(c.serial_num),
            'customer_name': c.name,
            'category': c.customer_category or '–',
            'brick': c.brick.name if c.brick else (c.area.name if c.area else '–'),
            'rep_name': rep_name,
            'credit_limit': float(acc.credit_limit),
            'current_balance': float(balance),
            'overdue_balance': float(overdue),
            'bucket_1_30': float(b_1_30),
            'bucket_31_60': float(b_31_60),
            'bucket_61_90': float(b_61_90),
            'bucket_91_120': float(b_91_120),
            'bucket_over_120': float(b_over_120),
            'last_tx_date': acc.last_transaction_date,
        })

    dso = safe_div(float(tot_receivables) * 90, float(total_sales_90d), 1) if total_sales_90d > 0 else 0.0

    return {
        'rows': rows,
        'summary': {
            'total_receivables': float(tot_receivables),
            'total_overdue': float(tot_overdue),
            'overdue_pct': safe_div(float(tot_overdue) * 100, float(tot_receivables), 1),
            'dso': dso,
            'bucket_1_30': float(tot_bucket_1_30),
            'bucket_31_60': float(tot_bucket_31_60),
            'bucket_61_90': float(tot_bucket_61_90),
            'bucket_91_120': float(tot_bucket_91_120),
            'bucket_over_120': float(tot_bucket_over_120),
            'accounts_count': len(rows),
        }
    }


def get_trial_balance_report_data(user, start_date, end_date, filters=None):
    """
    Report 2: Customers Trial Balance (ميزان المراجعة للعملاء).
    Calculates opening balance, debit movements (sales), credit movements (collections/returns), and closing balance.
    """
    filters = filters or {}
    area_id = filters.get('area_id')
    brick_id = filters.get('brick_id')

    accounts_qs = get_scoped_queryset(CustomerAccount.objects.select_related('customer', 'customer__area', 'customer__brick'), user)
    if area_id:
        accounts_qs = accounts_qs.filter(customer__area_id=area_id)
    if brick_id:
        accounts_qs = accounts_qs.filter(customer__brick_id=brick_id)

    rows = []
    tot_opening = Decimal('0.00')
    tot_debit = Decimal('0.00')
    tot_credit = Decimal('0.00')
    tot_closing = Decimal('0.00')

    for acc in accounts_qs[:500]:
        c = acc.customer
        # Opening balance before start_date
        prior_txs = acc.transactions.filter(transaction_date__lt=start_date).aggregate(
            deb=Sum('debit'), cr=Sum('credit')
        )
        opening_deb = prior_txs['deb'] or Decimal('0.00')
        opening_cr = prior_txs['cr'] or Decimal('0.00')
        opening_bal = opening_deb - opening_cr

        # Current period movements
        curr_txs = acc.transactions.filter(transaction_date__gte=start_date, transaction_date__lte=end_date).aggregate(
            deb=Sum('debit'), cr=Sum('credit')
        )
        curr_deb = curr_txs['deb'] or Decimal('0.00')
        curr_cr = curr_txs['cr'] or Decimal('0.00')

        closing_bal = opening_bal + curr_deb - curr_cr

        if opening_bal == 0 and curr_deb == 0 and curr_cr == 0 and closing_bal == 0:
            continue

        tot_opening += opening_bal
        tot_debit += curr_deb
        tot_credit += curr_cr
        tot_closing += closing_bal

        rows.append({
            'code': c.code or str(c.serial_num),
            'name': c.name,
            'category': c.customer_category or '–',
            'specialty': c.specialty or '–',
            'brick': c.brick.name if c.brick else (c.area.name if c.area else '–'),
            'opening_balance': float(opening_bal),
            'debit': float(curr_deb),
            'credit': float(curr_cr),
            'closing_balance': float(closing_bal),
        })

    return {
        'rows': rows,
        'summary': {
            'total_opening': float(tot_opening),
            'total_debit': float(tot_debit),
            'total_credit': float(tot_credit),
            'total_closing': float(tot_closing),
            'accounts_count': len(rows),
        }
    }


def get_agreements_roi_report_data(user, start_date, end_date, filters=None):
    """
    Report 3: Agreements Achievement & ROI (تحقيق الاتفاقيات وعائد الاستثمار).
    """
    filters = filters or {}
    agreements_qs = get_scoped_queryset(
        Agreement.objects.select_related('customer', 'type', 'created_by'), user
    ).filter(date__gte=start_date, date__lte=end_date)

    rows = []
    tot_budget = Decimal('0.00')
    tot_actual_sales = Decimal('0.00')

    for agr in agreements_qs:
        # Calculate actual sales delivered to customer during agreement date range
        c_orders = SalesOrder.objects.filter(
            customer=agr.customer,
            order_date__gte=agr.date,
            status__in=['delivered', 'invoiced']
        )
        actual_sales = c_orders.aggregate(t=Sum('grand_total'))['t'] or Decimal('0.00')
        budget = agr.amount or Decimal('0.00')
        ach_pct = safe_div(float(actual_sales) * 100, float(budget), 1) if budget > 0 else 0.0
        roi_pct = safe_div((float(actual_sales) - float(budget)) * 100, float(budget), 1) if budget > 0 else 0.0

        tot_budget += budget
        tot_actual_sales += actual_sales

        rows.append({
            'serial_num': agr.serial_num,
            'title': agr.title,
            'customer_name': agr.customer.name,
            'type_name': agr.type.display_name_ar if agr.type else 'عام',
            'rep_name': agr.created_by.name if agr.created_by else '–',
            'date': agr.date,
            'budget': float(budget),
            'actual_sales': float(actual_sales),
            'ach_pct': ach_pct,
            'roi_pct': roi_pct,
            'status': agr.get_status_display(),
            'status_badge': agr.status_badge_class,
        })

    overall_ach = safe_div(float(tot_actual_sales) * 100, float(tot_budget), 1) if tot_budget > 0 else 0.0
    overall_roi = safe_div((float(tot_actual_sales) - float(tot_budget)) * 100, float(tot_budget), 1) if tot_budget > 0 else 0.0

    return {
        'rows': rows,
        'summary': {
            'total_budget': float(tot_budget),
            'total_actual_sales': float(tot_actual_sales),
            'overall_ach_pct': overall_ach,
            'overall_roi_pct': overall_roi,
            'count': len(rows),
        }
    }


def get_calls_report_data(user, start_date, end_date, filters=None):
    """
    Report 4: Calls & Telesales Report (تقرير المكالمات والتواصل الهاتفي).
    """
    calls_qs = get_scoped_queryset(
        CustomerCall.objects.select_related('contact', 'performed_by', 'sales_order'), user
    ).filter(call_date__gte=start_date, call_date__lte=end_date)

    rows = []
    tot_duration = 0
    completed_cnt = 0

    for c in calls_qs:
        tot_duration += c.duration_minutes
        if c.outcome == 'completed':
            completed_cnt += 1
        rows.append({
            'date': c.call_date,
            'time': c.call_time.strftime('%H:%M') if c.call_time else '–',
            'customer_name': c.contact.name,
            'phone': c.contact.mobile or c.contact.phone or '–',
            'rep_name': c.performed_by.name or c.performed_by.username,
            'purpose': c.get_purpose_display(),
            'outcome': c.get_outcome_display(),
            'duration': c.duration_minutes,
            'notes': c.notes,
            'order_num': c.sales_order.order_number if c.sales_order else '–',
        })

    return {
        'rows': rows,
        'summary': {
            'total_calls': len(rows),
            'completed_calls': completed_cnt,
            'completed_pct': safe_div(completed_cnt * 100, len(rows), 1),
            'avg_duration': safe_div(tot_duration, len(rows), 1),
        }
    }


def get_customer_360_report_data(user, start_date, end_date, filters=None):
    """
    Report 5: Customer 360 Summary (ملخص العملاء 360).
    Exhaustive 22-column view merging visits, orders, discounts, returns, collections, and debts.
    """
    filters = filters or {}
    area_id = filters.get('area_id')
    brick_id = filters.get('brick_id')

    contacts_qs = get_scoped_queryset(
        Contact.objects.filter(is_customer=True).select_related('area', 'brick'), user
    )
    if area_id:
        contacts_qs = contacts_qs.filter(area_id=area_id)
    if brick_id:
        contacts_qs = contacts_qs.filter(brick_id=brick_id)

    rows = []
    tot_net_sales = Decimal('0.00')
    tot_collections = Decimal('0.00')
    tot_debt = Decimal('0.00')

    for c in contacts_qs[:300]:
        acc = getattr(c, 'customer_account', None)
        balance = acc.current_balance if acc else Decimal('0.00')
        overdue = acc.overdue_balance if acc else Decimal('0.00')
        c_limit = acc.credit_limit if acc else c.credit_limit

        v_sub = c.visits.filter(date__gte=start_date, date__lte=end_date)
        visits_cnt = v_sub.count()
        last_v = c.visits.order_by('-date').first()
        last_v_date = last_v.date if last_v else None

        o_sub = c.sales_orders.filter(order_date__gte=start_date, order_date__lte=end_date).exclude(status='cancelled')
        orders_cnt = o_sub.count()
        gross_sales = o_sub.aggregate(t=Sum('subtotal'))['t'] or Decimal('0.00')
        item_disc = o_sub.aggregate(t=Sum('items_discount_total'))['t'] or Decimal('0.00')
        custom_disc = o_sub.aggregate(t=Sum('custom_discount_amount'))['t'] or Decimal('0.00')
        net_sales = o_sub.aggregate(t=Sum('grand_total'))['t'] or Decimal('0.00')

        r_sub = c.sales_return_orders.filter(order_date__gte=start_date, order_date__lte=end_date, status__in=['delivered', 'settled'])
        ret_total = r_sub.aggregate(t=Sum('grand_total'))['t'] or Decimal('0.00')

        col_sub = c.collections.filter(collection_date__gte=start_date, collection_date__lte=end_date)
        col_total = col_sub.aggregate(t=Sum('amount'))['t'] or Decimal('0.00')

        rep = c.assigned_team.first() or c.created_by
        rep_name = rep.name or rep.username if rep else '–'
        util_pct = safe_div(float(balance) * 100, float(c_limit), 1) if c_limit > 0 else 0.0

        tot_net_sales += net_sales
        tot_collections += col_total
        tot_debt += balance

        rows.append({
            'code': c.code or str(c.serial_num),
            'name': c.name,
            'account_type': c.account_type or '–',
            'category': c.customer_category or '–',
            'specialty': c.specialty or '–',
            'governorate': c.area.name if c.area else '–',
            'brick': c.brick.name if c.brick else '–',
            'rep_name': rep_name,
            'visits_cnt': visits_cnt,
            'last_v_date': last_v_date,
            'orders_cnt': orders_cnt,
            'gross_sales': float(gross_sales),
            'items_disc': float(item_disc),
            'custom_disc': float(custom_disc),
            'net_sales': float(net_sales),
            'returns_total': float(ret_total),
            'collections_total': float(col_total),
            'balance': float(balance),
            'overdue': float(overdue),
            'credit_limit': float(c_limit),
            'util_pct': util_pct,
            'status': c.get_status_display(),
        })

    return {
        'rows': rows,
        'summary': {
            'total_customers': len(rows),
            'total_net_sales': float(tot_net_sales),
            'total_collections': float(tot_collections),
            'total_debt': float(tot_debt),
        }
    }


def get_promotions_report_data(user, start_date, end_date, filters=None):
    """
    Report 6: Bundles & Promotions Performance (أداء العروض والخصومات المركبة).
    """
    orders_qs = get_scoped_queryset(
        SalesOrder.objects.filter(
            order_date__gte=start_date, order_date__lte=end_date, custom_discount_amount__gt=0
        ).exclude(status='cancelled'), user
    )

    rows = []
    tot_orders = orders_qs.count()
    tot_discount = orders_qs.aggregate(t=Sum('custom_discount_amount'))['t'] or Decimal('0.00')
    tot_revenue = orders_qs.aggregate(t=Sum('grand_total'))['t'] or Decimal('0.00')

    for o in orders_qs[:100]:
        rows.append({
            'order_num': o.order_number,
            'order_date': o.order_date,
            'customer_name': o.customer.name,
            'subtotal': float(o.subtotal),
            'discount_pct': float(o.custom_discount_percentage),
            'discount_amount': float(o.custom_discount_amount),
            'grand_total': float(o.grand_total),
            'warehouse': o.source_warehouse.name if o.source_warehouse else '–',
        })

    return {
        'rows': rows,
        'summary': {
            'orders_count': tot_orders,
            'total_discount': float(tot_discount),
            'total_revenue': float(tot_revenue),
            'avg_discount_pct': safe_div(float(tot_discount) * 100, float(tot_revenue + tot_discount), 1),
        }
    }


def get_order_deliveries_report_data(user, start_date, end_date, filters=None):
    """
    Report 7: Order Deliveries & Dispatch Logistics (تسليمات الطلبات واللوجستيات).
    25 columns tracking fulfillment, delivery dates, drivers, GPS, and items.
    """
    orders_qs = get_scoped_queryset(
        SalesOrder.objects.filter(
            order_date__gte=start_date, order_date__lte=end_date
        ).select_related('customer', 'source_warehouse', 'customer__area', 'customer__brick'), user
    )

    rows = []
    delivered_cnt = 0
    pending_cnt = 0

    for o in orders_qs[:300]:
        is_del = o.status in ['delivered', 'invoiced']
        if is_del:
            delivered_cnt += 1
        else:
            pending_cnt += 1

        items_cnt = o.items.count()
        tot_qty = o.items.aggregate(t=Sum('quantity'))['t'] or Decimal('0.00')
        c = o.customer
        c_lat = float(c.latitude) if c.latitude else None
        c_lng = float(c.longitude) if c.longitude else None

        rows.append({
            'order_num': o.order_number,
            'order_date': o.order_date,
            'delivery_date': o.delivery_date or '–',
            'customer_name': c.name,
            'area': c.area.name if c.area else '–',
            'brick': c.brick.name if c.brick else '–',
            'warehouse': o.source_warehouse.name if o.source_warehouse else '–',
            'delivery_agent': o.created_by.name if o.created_by else 'مندوب التوزيع',
            'status': o.status_display_ar,
            'status_badge': o.status_badge_class,
            'items_count': items_cnt,
            'total_quantity': float(tot_qty),
            'subtotal': float(o.subtotal),
            'discount': float(o.items_discount_total + o.custom_discount_amount),
            'grand_total': float(o.grand_total),
            'latitude': c_lat,
            'longitude': c_lng,
            'confirmation_method': 'إيصال استلام موقع' if is_del else 'قيد التوصيل',
        })

    return {
        'rows': rows,
        'summary': {
            'total_orders': len(rows),
            'delivered_count': delivered_cnt,
            'pending_count': pending_cnt,
            'fulfillment_pct': safe_div(delivered_cnt * 100, len(rows), 1),
        }
    }


def get_delivery_stock_availability_report_data(user, filters=None):
    """
    Report 8: Delivery Status & Stock Availability (متابعة التسليمات وتوفر المخزون).
    Matches open sales orders pending dispatch with on-hand and free warehouse stock.
    """
    # Open sales order items
    open_items = SalesOrderItem.objects.filter(
        order__status__in=['pending', 'manager_approval', 'preparing']
    ).values('product_id', 'product__name', 'product__sku_code').annotate(
        ordered_qty=Sum('quantity'),
        orders_count=Count('order_id', distinct=True)
    )

    rows = []
    stockout_cnt = 0

    for item in open_items:
        prod_id = item['product_id']
        stocks = InventoryStock.objects.filter(product_id=prod_id)
        on_hand = stocks.aggregate(t=Sum('qty_on_hand'))['t'] or Decimal('0.00')
        reserved = stocks.aggregate(t=Sum('qty_reserved'))['t'] or Decimal('0.00')
        available = max(Decimal('0.00'), on_hand - reserved)
        needed = item['ordered_qty'] or Decimal('0.00')

        if available >= needed:
            status = 'متوفر بالكامل'
            color = 'emerald'
        elif available > 0:
            status = 'عجز جزئي'
            color = 'amber'
            stockout_cnt += 1
        else:
            status = 'غير متوفر (عجز)'
            color = 'rose'
            stockout_cnt += 1

        rows.append({
            'code': item['product__sku_code'],
            'name': item['product__name'],
            'ordered_qty': float(needed),
            'on_hand': float(on_hand),
            'reserved': float(reserved),
            'available': float(available),
            'status': status,
            'status_color': color,
            'impacted_orders': item['orders_count'],
        })

    return {
        'rows': rows,
        'summary': {
            'total_items': len(rows),
            'stockout_items': stockout_cnt,
            'healthy_items': len(rows) - stockout_cnt,
        }
    }


def get_net_sales_profitability_report_data(user, start_date, end_date, filters=None):
    """
    Report 9: Net Item Sales & Profitability (صافي مبيعات الأصناف وربحية المنتجات).
    21 columns computing COGS, gross profit, and profit margin % per product.
    """
    items_qs = SalesOrderItem.objects.filter(
        order__order_date__gte=start_date,
        order__order_date__lte=end_date,
        order__status__in=['delivered', 'invoiced']
    ).values('product_id', 'product__name', 'product__sku_code', 'product__retail_price').annotate(
        del_qty=Sum('quantity'),
        del_subtotal=Sum('subtotal'),
        del_disc=Sum('discount_amount'),
    )

    rows = []
    tot_gross = Decimal('0.00')
    tot_net = Decimal('0.00')
    tot_cogs = Decimal('0.00')
    tot_profit = Decimal('0.00')

    for p in items_qs:
        prod_id = p['product_id']
        del_q = p['del_qty'] or Decimal('0.00')
        del_sub = p['del_subtotal'] or Decimal('0.00')
        del_d = p['del_disc'] or Decimal('0.00')
        net_del = max(Decimal('0.00'), del_sub - del_d)

        # Returns for this product
        ret_qs = SalesReturnOrderItem.objects.filter(
            product_id=prod_id,
            order__order_date__gte=start_date,
            order__order_date__lte=end_date,
            order__status__in=['delivered', 'settled']
        ).aggregate(qty=Sum('quantity'), total=Sum('total'))
        ret_q = ret_qs['qty'] or Decimal('0.00')
        ret_val = ret_qs['total'] or Decimal('0.00')

        final_qty = max(Decimal('0.00'), del_q - ret_q)
        final_sales_val = max(Decimal('0.00'), net_del - ret_val)

        # Average unit cost from InventoryStock
        avg_cost = InventoryStock.objects.filter(product_id=prod_id).aggregate(c=Avg('product_cost'))['c'] or Decimal('0.00')
        cogs = (final_qty * avg_cost).quantize(Decimal('0.01'))
        gross_profit = final_sales_val - cogs
        margin_pct = safe_div(float(gross_profit) * 100, float(final_sales_val), 1) if final_sales_val > 0 else 0.0

        tot_gross += del_sub
        tot_net += final_sales_val
        tot_cogs += cogs
        tot_profit += gross_profit

        rows.append({
            'code': p['product__sku_code'],
            'name': p['product__name'],
            'delivered_qty': float(del_q),
            'delivered_sales': float(net_del),
            'return_qty': float(ret_q),
            'return_val': float(ret_val),
            'net_qty': float(final_qty),
            'net_sales': float(final_sales_val),
            'unit_cost': float(avg_cost),
            'cogs': float(cogs),
            'gross_profit': float(gross_profit),
            'margin_pct': margin_pct,
            'retail_price': float(p['product__retail_price']),
        })

    overall_margin = safe_div(float(tot_profit) * 100, float(tot_net), 1) if tot_net > 0 else 0.0

    return {
        'rows': rows,
        'summary': {
            'total_gross_sales': float(tot_gross),
            'total_net_sales': float(tot_net),
            'total_cogs': float(tot_cogs),
            'total_gross_profit': float(tot_profit),
            'overall_margin_pct': overall_margin,
            'products_count': len(rows),
        }
    }


def get_item_purchases_report_data(user, start_date, end_date, filters=None):
    """
    Report 10: Item Purchases & Vendor Analytics (مشتريات الأصناف وتحليلات الموردين).
    """
    p_items = PurchaseOrderItem.objects.filter(
        order__order_date__gte=start_date,
        order__order_date__lte=end_date,
        order__status__in=['approved', 'picked', 'settled']
    ).values(
        'product_id', 'product__name', 'product__sku_code', 'order__supplier__name'
    ).annotate(
        qty=Sum('quantity'),
        spend=Sum('total_price')
    )

    rows = []
    tot_spend = Decimal('0.00')

    for pi in p_items:
        prod_id = pi['product_id']
        qty = pi['qty'] or Decimal('0.00')
        spend = pi['spend'] or Decimal('0.00')
        avg_price = safe_div(float(spend), float(qty), 2) if qty > 0 else 0.0

        stocks = InventoryStock.objects.filter(product_id=prod_id)
        on_hand = stocks.aggregate(t=Sum('qty_on_hand'))['t'] or Decimal('0.00')

        tot_spend += spend
        rows.append({
            'code': pi['product__sku_code'],
            'name': pi['product__name'],
            'supplier_name': pi['order__supplier__name'] or '–',
            'quantity': float(qty),
            'spend': float(spend),
            'avg_cost': avg_price,
            'current_stock': float(on_hand),
        })

    return {
        'rows': rows,
        'summary': {
            'total_spend': float(tot_spend),
            'items_count': len(rows),
        }
    }


def get_item_sales_by_customer_report_data(user, start_date, end_date, filters=None):
    """
    Report 11: Item Sales by Customer (مبيعات الأصناف حسب العملاء).
    """
    sales_items = SalesOrderItem.objects.filter(
        order__order_date__gte=start_date,
        order__order_date__lte=end_date,
        order__status__in=['delivered', 'invoiced']
    ).values(
        'product__sku_code', 'product__name', 'order__customer__name', 'order__customer__area__name'
    ).annotate(
        qty=Sum('quantity'),
        net_val=Sum('subtotal') - Sum('discount_amount')
    ).order_by('product__name')[:300]

    rows = []
    tot_val = Decimal('0.00')

    for item in sales_items:
        val = item['net_val'] or Decimal('0.00')
        tot_val += val
        rows.append({
            'product_code': item['product__sku_code'],
            'product_name': item['product__name'],
            'customer_name': item['order__customer__name'],
            'area_name': item['order__customer__area__name'] or '–',
            'quantity': float(item['qty'] or 0),
            'net_amount': float(val),
        })

    return {
        'rows': rows,
        'summary': {
            'total_amount': float(tot_val),
            'count': len(rows),
        }
    }


def get_target_achievement_report_data(user, year, month, filters=None):
    """
    Report 12: Sales & Collection Target Achievement (تحقيق أهداف المبيعات والتحصيلات).
    """
    from accounts.models import User
    reps = get_scoped_queryset(User.objects.filter(is_active=True), user).filter(
        Q(role__is_rep=True) | Q(role__is_sales_team=True) | Q(role__name__in=['rep', 'medical_rep', 'manager'])
    ).distinct().order_by('name')

    rows = []
    tot_target_sales = Decimal('0.00')
    tot_actual_sales = Decimal('0.00')
    tot_target_cols = Decimal('0.00')
    tot_actual_cols = Decimal('0.00')

    # Start and end date of that year/month
    start_d = datetime.date(year, month, 1)
    if month == 12:
        end_d = datetime.date(year, 12, 31)
    else:
        end_d = datetime.date(year, month + 1, 1) - datetime.timedelta(days=1)

    for rep in reps:
        target = SalesTarget.objects.filter(user=rep, year=year, month=month).first()
        t_sales = target.target_sales_amount if target else Decimal('0.00')
        t_cols = target.target_collections_amount if target else Decimal('0.00')

        act_sales = SalesOrder.objects.filter(
            created_by=rep, order_date__gte=start_d, order_date__lte=end_d, status__in=['delivered', 'invoiced']
        ).aggregate(t=Sum('grand_total'))['t'] or Decimal('0.00')

        act_cols = Collection.objects.filter(
            created_by=rep, collection_date__gte=start_d, collection_date__lte=end_d
        ).aggregate(t=Sum('amount'))['t'] or Decimal('0.00')

        sales_ach = safe_div(float(act_sales) * 100, float(t_sales), 1) if t_sales > 0 else (100.0 if act_sales > 0 else 0.0)
        cols_ach = safe_div(float(act_cols) * 100, float(t_cols), 1) if t_cols > 0 else (100.0 if act_cols > 0 else 0.0)
        overall_index = round((sales_ach + cols_ach) / 2.0, 1)

        status_color = 'emerald' if overall_index >= 100 else ('amber' if overall_index >= 80 else 'rose')

        tot_target_sales += t_sales
        tot_actual_sales += act_sales
        tot_target_cols += t_cols
        tot_actual_cols += act_cols

        area_obj = rep.assigned_areas.first()
        area_str = area_obj.name if area_obj else '–'

        rows.append({
            'rep_id': rep.id,
            'rep_name': rep.name or rep.username,
            'area_name': area_str,
            'target_sales': float(t_sales),
            'actual_sales': float(act_sales),
            'sales_ach_pct': sales_ach,
            'target_cols': float(t_cols),
            'actual_cols': float(act_cols),
            'cols_ach_pct': cols_ach,
            'overall_index': overall_index,
            'status_color': status_color,
        })

    overall_sales_ach = safe_div(float(tot_actual_sales) * 100, float(tot_target_sales), 1) if tot_target_sales > 0 else 0.0
    overall_cols_ach = safe_div(float(tot_actual_cols) * 100, float(tot_target_cols), 1) if tot_target_cols > 0 else 0.0

    return {
        'rows': rows,
        'summary': {
            'total_target_sales': float(tot_target_sales),
            'total_actual_sales': float(tot_actual_sales),
            'sales_ach_pct': overall_sales_ach,
            'total_target_cols': float(tot_target_cols),
            'total_actual_cols': float(tot_actual_cols),
            'cols_ach_pct': overall_cols_ach,
            'reps_count': len(rows),
        }
    }


def get_samples_report_data(user, start_date, end_date, filters=None):
    """
    Report 13: Medical Samples Tracking (عينات المنتجات الطبية).
    16 columns tracking sample batches, costs, quantities, physicians, and visits.
    """
    samples_qs = get_scoped_queryset(
        VisitSampleItem.objects.filter(
            visit__date__gte=start_date, visit__date__lte=end_date
        ).select_related('visit', 'visit__owner', 'visit__contact', 'product', 'visit__contact__area', 'visit__contact__brick'), user
    )

    rows = []
    tot_qty = 0
    tot_cost = Decimal('0.00')

    for s in samples_qs[:300]:
        v = s.visit
        c = v.contact
        qty = s.quantity
        unit_cost = InventoryStock.objects.filter(product=s.product).aggregate(c=Avg('product_cost'))['c'] or Decimal('0.00')
        line_cost = (Decimal(str(qty)) * unit_cost).quantize(Decimal('0.01'))

        tot_qty += qty
        tot_cost += line_cost

        rows.append({
            'sample_id': s.id,
            'visit_num': v.serial_num,
            'visit_date': v.date,
            'rep_name': v.owner.name if v.owner else '–',
            'contact_name': c.name,
            'account_type': c.account_type or 'عيادة',
            'specialty': c.specialty or '–',
            'governorate': c.area.name if c.area else '–',
            'brick': c.brick.name if c.brick else '–',
            'product_name': s.product.name,
            'quantity': qty,
            'unit_cost': float(unit_cost),
            'total_cost': float(line_cost),
            'verified': v.location_verified,
        })

    return {
        'rows': rows,
        'summary': {
            'total_samples_count': tot_qty,
            'total_samples_cost': float(tot_cost),
            'visits_count': len(rows),
        }
    }


# ==============================================================================
# EXCEL EXPORT HELPER (OPENPYXL RTL ENGINE)
# ==============================================================================

def export_to_excel_response(filename, sheet_title, headers, rows, summary_row=None):
    """
    Generates an enterprise-formatted Excel file in Arabic RTL with styling, borders, and numbers.
    """
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_title[:31]
    ws.sheet_view.rightToLeft = True

    # Styling palette
    header_fill = PatternFill(start_color="27BEBE", end_color="27BEBE", fill_type="solid")
    header_font = Font(name="Cairo", size=11, bold=True, color="FFFFFF")
    data_font = Font(name="Cairo", size=10)
    summary_fill = PatternFill(start_color="E2F8F8", end_color="E2F8F8", fill_type="solid")
    summary_font = Font(name="Cairo", size=11, bold=True, color="0D5A5A")
    thin_border = Border(
        left=Side(style='thin', color='CBD5E1'),
        right=Side(style='thin', color='CBD5E1'),
        top=Side(style='thin', color='CBD5E1'),
        bottom=Side(style='thin', color='CBD5E1'),
    )

    # Write Headers
    for col_idx, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_idx, value=h)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = thin_border
    ws.row_dimensions[1].height = 28

    # Write Data Rows
    current_row = 2
    for r in rows:
        for col_idx, val in enumerate(r, 1):
            cell = ws.cell(row=current_row, column=col_idx, value=val)
            cell.font = data_font
            cell.border = thin_border
            if isinstance(val, (int, float, Decimal)):
                cell.alignment = Alignment(horizontal="right", vertical="center")
                if isinstance(val, float):
                    cell.number_format = '#,##0.00'
                elif isinstance(val, int):
                    cell.number_format = '#,##0'
            else:
                cell.alignment = Alignment(horizontal="center", vertical="center")
        ws.row_dimensions[current_row].height = 20
        current_row += 1

    # Optional Summary Row
    if summary_row:
        for col_idx, val in enumerate(summary_row, 1):
            cell = ws.cell(row=current_row, column=col_idx, value=val)
            cell.fill = summary_fill
            cell.font = summary_font
            cell.border = thin_border
            if isinstance(val, (int, float, Decimal)):
                cell.alignment = Alignment(horizontal="right", vertical="center")
                cell.number_format = '#,##0.00'
            else:
                cell.alignment = Alignment(horizontal="center", vertical="center")
        ws.row_dimensions[current_row].height = 24

    # Auto-adjust column widths
    for col in ws.columns:
        max_len = 0
        col_letter = get_column_letter(col[0].column)
        for cell in col:
            val_str = str(cell.value or '')
            if len(val_str) > max_len:
                max_len = len(val_str)
        ws.column_dimensions[col_letter].width = max(max_len + 3, 12)

    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}.xlsx"'
    wb.save(response)
    return response
