import datetime
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.utils import timezone

from accounts.permissions import require_permission, get_scoped_queryset
from accounts.models import User
from master_data.models import Area
from .services import (
    parse_date_range,
    get_performance_overview_data,
    get_performance_analysis_data,
    get_performance_daily_data,
    get_performance_detailed_matrix,
    export_to_excel_response,
)


@login_required
@require_permission('performance:overview/view')
def performance_overview(request):
    """
    Performance Overview dashboard featuring 22 KPI cards with prior-month comparisons,
    gauges, and the top detailed products table.
    """
    period = request.GET.get('period', 'this_month')
    start_str = request.GET.get('start_date')
    end_str = request.GET.get('end_date')
    rep_id = request.GET.get('rep')
    area_id = request.GET.get('area')
    account_type = request.GET.get('account_type')

    start_date, end_date, prior_start, prior_end, period_label = parse_date_range(period, start_str, end_str)

    filters = {
        'rep_id': rep_id,
        'area_id': area_id,
        'account_type': account_type,
    }

    data = get_performance_overview_data(request.user, start_date, end_date, prior_start, prior_end, filters)

    # Scoped dropdown choices
    reps = get_scoped_queryset(User.objects.filter(is_active=True), request.user).filter(
        role__is_sales_team=True
    ).order_by('name')
    areas = get_scoped_queryset(Area.objects.filter(parent__isnull=True), request.user)

    context = {
        'period': period,
        'period_label': period_label,
        'start_date': start_date.isoformat(),
        'end_date': end_date.isoformat(),
        'selected_rep': int(rep_id) if rep_id and rep_id.isdigit() else '',
        'selected_area': int(area_id) if area_id and area_id.isdigit() else '',
        'selected_account_type': account_type or '',
        'reps': reps,
        'areas': areas,
        'kpis': data['kpis'],
        'top_detailed_products': data['top_detailed_products'],
        'current': data['current'],
        'prior': data['prior'],
    }
    return render(request, 'performance/overview.html', context)


@login_required
@require_permission('performance:analysis/view')
def performance_analysis(request):
    """
    Performance Analytical view: 8 interactive charts + 11-column rep comparison table.
    """
    period = request.GET.get('period', 'this_month')
    start_str = request.GET.get('start_date')
    end_str = request.GET.get('end_date')
    area_id = request.GET.get('area')

    start_date, end_date, _, _, period_label = parse_date_range(period, start_str, end_str)
    filters = {'area_id': area_id}

    data = get_performance_analysis_data(request.user, start_date, end_date, filters)
    areas = get_scoped_queryset(Area.objects.filter(parent__isnull=True), request.user)

    context = {
        'period': period,
        'period_label': period_label,
        'start_date': start_date.isoformat(),
        'end_date': end_date.isoformat(),
        'selected_area': int(area_id) if area_id and area_id.isdigit() else '',
        'areas': areas,
        'rep_summary_table': data['rep_summary_table'],
        'rep_rows': data['rep_summary_table'],
        'charts': data['charts'],
        'chart_rep_sales': data['charts'],
        'chart_visits_mix': data['charts'],
    }
    return render(request, 'performance/analysis.html', context)


@login_required
@require_permission('performance:analysis/export')
def performance_analysis_export(request):
    """Excel export for the 11-column rep comparison table."""
    period = request.GET.get('period', 'this_month')
    start_str = request.GET.get('start_date')
    end_str = request.GET.get('end_date')
    area_id = request.GET.get('area')

    start_date, end_date, _, _, period_label = parse_date_range(period, start_str, end_str)
    data = get_performance_analysis_data(request.user, start_date, end_date, {'area_id': area_id})

    headers = [
        "اسم المندوب", "كود المندوب", "المنطقة / المحافظة", "إجمالي العملاء", "العملاء المزارون",
        "نسبة التغطية %", "إجمالي الزيارات", "المخططة", "خارج الخطة", "معدل التكرار",
        "أيام العمل الميدانية", "أيام بدون زيارات", "معدل الزيارات اليومي", "مرات الشرح الطبي",
        "إجمالي المبيعات (ج.م)", "إجمالي التحصيلات (ج.م)", "ساعات العمل الميدانية"
    ]
    rows = []
    tot_sales = 0
    tot_cols = 0
    tot_visits = 0

    for r in data['rep_summary_table']:
        tot_sales += r['sales_val']
        tot_cols += r['col_val']
        tot_visits += r['total_visits']
        rows.append([
            r['name'], r['code'], r['area_name'], r['assigned_contacts'], r['visited_contacts'],
            f"{r['coverage_pct']}%", r['total_visits'], r['planned_visits'], r['unplanned_visits'],
            r['frequency'], r['field_days'], r['off_field_days'], r['daily_rate'], r['detailing_count'],
            r['sales_val'], r['col_val'], r['total_duration_hours']
        ])

    summary_row = [
        "الإجمالي العام", "", "", "", "", "", tot_visits, "", "", "", "", "", "", "",
        tot_sales, tot_cols, ""
    ]

    filename = f"Performance_Analysis_{start_date}_{end_date}"
    return export_to_excel_response(filename, "تحليل أداء المناديب", headers, rows, summary_row)


@login_required
@require_permission('performance:daily/view')
def performance_daily(request):
    """
    Daily micro-dashboard: Day picker, daily KPIs vs yesterday, 20-column rep activity grid,
    and 8 daily drilldown tabs.
    """
    date_str = request.GET.get('date')
    today = timezone.now().date()
    try:
        target_date = datetime.date.fromisoformat(date_str) if date_str else today
    except Exception:
        target_date = today

    prev_date = target_date - datetime.timedelta(days=1)
    next_date = target_date + datetime.timedelta(days=1)

    data = get_performance_daily_data(request.user, target_date)

    context = {
        'target_date': target_date,
        'target_date_str': target_date.isoformat(),
        'prev_date_str': prev_date.isoformat(),
        'next_date_str': next_date.isoformat(),
        'is_today': target_date == today,
        'daily_kpis': data['daily_kpis'],
        'kpis': data['daily_kpis'],
        'daily_rep_grid': data['daily_rep_grid'],
        'rep_rows': data['daily_rep_grid'],
        'subtabs': data['subtabs'],
        'tab_visits': data['subtabs']['visits'],
    }
    return render(request, 'performance/daily.html', context)


@login_required
@require_permission('performance:daily/export')
def performance_daily_export(request):
    """Excel export for daily rep activity grid."""
    date_str = request.GET.get('date')
    try:
        target_date = datetime.date.fromisoformat(date_str) if date_str else timezone.now().date()
    except Exception:
        target_date = timezone.now().date()

    data = get_performance_daily_data(request.user, target_date)

    headers = [
        "اسم المندوب", "المنطقة", "أول تسجيل", "آخر تسجيل", "ساعات العمل",
        "المخططة", "المنفذة", "خارج الخطة", "الملغاة", "المزدوجة",
        "مرات الشرح", "نسبة دقة الموقع %", "نسبة التحقق %",
        "عدد الطلبيات", "قيمة المبيعات (ج.م)", "قيمة التحصيلات (ج.م)", "المصروفات (ج.م)", "حالة اليوم"
    ]
    rows = []
    tot_sales = 0
    tot_cols = 0
    tot_exp = 0

    for r in data['daily_rep_grid']:
        tot_sales += r['orders_val']
        tot_cols += r['cols_val']
        tot_exp += r['expenses_val']
        rows.append([
            r['name'], r['area'], r['first_checkin'], r['last_checkout'], r['working_hours'],
            r['planned_visits'], r['completed_visits'], r['unplanned_visits'], r['cancelled_visits'],
            r['double_visits'], r['detailing_count'], f"{r['in_range_pct']}%", f"{r['verified_pct']}%",
            r['orders_count'], r['orders_val'], r['cols_val'], r['expenses_val'], r['status']
        ])

    summary_row = [
        "الإجمالي", "", "", "", "", "", "", "", "", "", "", "", "", "",
        tot_sales, tot_cols, tot_exp, ""
    ]

    filename = f"Daily_Performance_{target_date}"
    return export_to_excel_response(filename, f"نشاط يوم {target_date}", headers, rows, summary_row)


@login_required
@require_permission('performance:detailed/view')
def performance_detailed(request):
    """
    Performance Detailed view: Mega 63-column matrix per rep and coaching logs.
    """
    period = request.GET.get('period', 'this_month')
    start_str = request.GET.get('start_date')
    end_str = request.GET.get('end_date')
    area_id = request.GET.get('area')

    start_date, end_date, _, _, period_label = parse_date_range(period, start_str, end_str)
    data = get_performance_detailed_matrix(request.user, start_date, end_date, {'area_id': area_id})

    areas = get_scoped_queryset(Area.objects.filter(parent__isnull=True), request.user)

    context = {
        'period': period,
        'period_label': period_label,
        'start_date': start_date.isoformat(),
        'end_date': end_date.isoformat(),
        'selected_area': int(area_id) if area_id and area_id.isdigit() else '',
        'areas': areas,
        'matrix_rows': data['matrix_rows'],
        'coaching_logs': data['coaching_logs'],
        'coaching_rows': data['coaching_logs'],
    }
    return render(request, 'performance/detailed.html', context)


@login_required
@require_permission('performance:detailed/export')
def performance_detailed_export(request):
    """Excel export for the 63-column mega performance matrix."""
    period = request.GET.get('period', 'this_month')
    start_str = request.GET.get('start_date')
    end_str = request.GET.get('end_date')
    area_id = request.GET.get('area')

    start_date, end_date, _, _, _ = parse_date_range(period, start_str, end_str)
    data = get_performance_detailed_matrix(request.user, start_date, end_date, {'area_id': area_id})

    headers = [
        "المندوب", "الكود", "المنطقة", "الأطباء", "الصيدليات", "المستشفيات", "المخازن",
        "تغطية A %", "تغطية B %", "تغطية C %", "إجمالي الزيارات", "المخططة", "خارج الخطة",
        "صباحية AM", "مسائية PM", "أخرى", "متوسط المدة (د)", "داخل النطاق", "خارج النطاق",
        "تجاوزات", "مرات الشرح", "العينات", "الطلبيات", "إجمالي المبيعات", "صافي المبيعات",
        "التحصيلات", "المحصل نقدياً"
    ]
    rows = []
    for r in data['matrix_rows']:
        rows.append([
            r['name'], r['code'], r['area'], r['total_doctors'], r['total_pharmacies'], r['total_hospitals'],
            r['total_stores'], f"{r['class_a_cov']}%", f"{r['class_b_cov']}%", f"{r['class_c_cov']}%",
            r['total_visits'], r['planned_visits'], r['unplanned_visits'], r['am_visits'], r['pm_visits'],
            r['na_visits'], r['avg_duration'], r['in_range_cnt'], r['out_range_cnt'], r['bypassed_cnt'],
            r['detailing_cnt'], r['samples_cnt'], r['sales_cnt'], r['sales_gross'], r['sales_net'],
            r['cols_cnt'], r['cols_net']
        ])

    filename = f"Detailed_Matrix_{start_date}_{end_date}"
    return export_to_excel_response(filename, "مصفوفة الأداء الكبرى", headers, rows)
