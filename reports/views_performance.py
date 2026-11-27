import datetime
import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from accounts.permissions import get_scoped_queryset, has_perm_or_admin, require_permission
from accounts.services import AuditLogService
from contacts.models import Contact
from master_data.excel_utils import export_multisheet_excel_response
from master_data.pagination_utils import paginate_queryset
from reports.services import (
    get_performance_analysis_data,
    get_performance_daily_data,
    get_performance_detailed_matrix,
    get_performance_overview_data,
)
from reports.visit_analytics import (
    ACTIVE_ELIGIBLE_ACCOUNT_Q,
    VisitAnalyticsService,
    resolve_performance_filters,
)


MAX_EXPORT_RANGE_DAYS = 732

EXPORT_SECTION_CHOICES = [
    ('summary', 'ملخص مؤشرات الأداء والزيارات'),
    ('planned_unplanned', 'الزيارات المخططة مقابل غير المخططة'),
    ('groups', 'إحصائيات مجموعات أنواع الحسابات'),
    ('daily', 'النشاط اليومي للزيارات'),
    ('visited_accounts', 'قائمة الحسابات المزارة'),
    ('unvisited_accounts', 'قائمة الحسابات غير المزارة'),
    ('visit_details', 'تفاصيل الزيارات على مستوى الحساب'),
]
DEFAULT_EXPORT_SECTIONS = [
    'summary',
    'planned_unplanned',
    'groups',
    'daily',
    'visited_accounts',
    'unvisited_accounts',
]
VALID_EXPORT_SECTIONS = {k for k, _ in EXPORT_SECTION_CHOICES}


def _serialize_account_row(c):
    team_all = list(c.assigned_team.all())
    rep = team_all[0] if team_all else c.created_by
    rep_name = (rep.name or rep.username) if rep else '–'
    area_name = c.area.name if c.area else (c.brick.parent.name if (c.brick and c.brick.parent) else '–')
    brick_name = c.brick.name if c.brick else '–'
    last_d = getattr(c, 'last_qualifying_visit_date', None)
    status_ar = 'عميل فعلي' if c.status == 'customer' else ('عميل محتمل' if c.status == 'lead' else c.status_label)
    return {
        'id': c.id,
        'serial_num': c.serial_num,
        'code': c.code or f"#{c.serial_num}",
        'name': c.name,
        'detail_url': reverse('contact_detail', args=[c.pk]),
        'account_type': c.account_type or 'غير مصنف',
        'status': c.status,
        'status_ar': status_ar,
        'area_name': area_name,
        'brick_name': brick_name,
        'rep_name': rep_name,
        'completed_visits': int(getattr(c, 'period_completed_visits', 0) or 0),
        'incomplete_planned': int(getattr(c, 'period_incomplete_planned', 0) or 0),
        'last_visit_date': last_d.isoformat() if last_d else '—',
    }


@login_required
@require_permission('performance:overview/view')
def performance_overview(request):
    """
    Unified Field Performance & Visit Analytics workspace:
    - Confirmed KPI cards (Working Days, Completed/Planned/Incomplete/Unplanned Visits, Avg/Day, Coverage)
    - Configurable Account-Type Group cards (+ trailing unclassified reconciliation)
    - Bundled ECharts daily visit activity timeline across every calendar day in range
    - AJAX-paginated Visited / Unvisited / All Eligible accounts drill-down
    - Combinable scoped filters + Selective multi-section Excel export
    """
    rf = resolve_performance_filters(request, default_preset='this_month')
    data = get_performance_overview_data(
        request.user,
        rf['start_date'],
        rf['end_date'],
        rf['prior_start'],
        rf['prior_end'],
        filters=rf,
    )
    analytics = data['analytics']

    # Initial page of visited accounts for instant first paint (AJAX handles tab/page/search)
    initial_tab = (request.GET.get('accounts_tab') or 'visited').strip().lower()
    if initial_tab not in ('visited', 'unvisited', 'all'):
        initial_tab = 'visited'
    initial_accounts_qs = VisitAnalyticsService.get_accounts_drilldown_queryset(
        request.user, rf, tab=initial_tab
    )
    acc_paginator, acc_page = paginate_queryset(request, initial_accounts_qs, default_per_page=15, max_per_page=100)
    initial_accounts = [_serialize_account_row(c) for c in acc_page.object_list]

    can_view_sales = has_perm_or_admin(request.user, 'sales:orders/list') or has_perm_or_admin(request.user, 'sales:collections/list')
    can_export_overview = has_perm_or_admin(request.user, 'performance:overview/export')
    can_manage_report_groups = has_perm_or_admin(request.user, 'settings:reportGroups/manage')

    chart_payload = {
        'daily_series': analytics['daily_series'],
        'avg_working_day': analytics['avg_visits_per_working_day'],
        'calendar_days': analytics['calendar_days'],
        'start_date': rf['start_date_str'],
        'end_date': rf['end_date_str'],
    }

    context = {
        'rf': rf,
        'period': rf['period'],
        'period_label': rf['period_label'],
        'start_date': rf['start_date_str'],
        'end_date': rf['end_date_str'],
        'selected_rep': rf['rep_id'] or '',
        'selected_area': rf['area_ids'][0] if len(rf['area_ids']) == 1 else '',
        'selected_area_ids': rf['area_ids'],
        'selected_brick_ids': rf['brick_ids'],
        'selected_group_code': rf['selected_group_code'],
        'selected_account_types': rf['account_types'],
        'selected_account_type': rf['account_types'][0] if rf['account_types'] else '',
        'selected_account_status': rf['account_status'],
        'selected_contact': rf['selected_contact'],
        'can_select_rep': rf['can_select_rep'],
        'reps': rf['reps_qs'],
        'areas': rf['areas_qs'],
        'bricks': rf['bricks_qs'],
        'active_groups': rf['active_groups'],
        'available_account_types': rf['available_account_types'],
        'active_filters': rf['active_filters'],
        'active_filters_count': len(rf['active_filters']),
        'kpis': data['kpis'],
        'current': data['current'],
        'prior': data['prior'],
        'analytics': analytics,
        'top_detailed_products': data['top_detailed_products'],
        'chart_payload_json': json.dumps(chart_payload, ensure_ascii=False),
        'initial_tab': initial_tab,
        'initial_accounts': initial_accounts,
        'initial_accounts_total': acc_paginator.count,
        'initial_accounts_pages': acc_paginator.num_pages,
        'export_section_choices': EXPORT_SECTION_CHOICES,
        'default_export_sections': DEFAULT_EXPORT_SECTIONS,
        'can_view_sales': can_view_sales,
        'can_export_overview': can_export_overview,
        'can_manage_report_groups': can_manage_report_groups,
    }
    return render(request, 'performance/overview.html', context)


@login_required
@require_permission('performance:overview/view')
def performance_overview_accounts_api(request):
    """
    Strictly scoped AJAX endpoint powering the Visited / Unvisited / All Eligible
    accounts drill-down table with server-side pagination, search, and sorting.
    """
    rf = resolve_performance_filters(request, default_preset='this_month')
    tab = (request.GET.get('tab') or 'visited').strip().lower()
    if tab not in ('visited', 'unvisited', 'all'):
        tab = 'visited'
    search_q = (request.GET.get('q') or '').strip()
    sort_by = (request.GET.get('sort') or '').strip()

    qs = VisitAnalyticsService.get_accounts_drilldown_queryset(
        request.user, rf, tab=tab, search_q=search_q, sort_by=sort_by
    )
    paginator, page_obj = paginate_queryset(request, qs, default_per_page=15, max_per_page=100)
    rows = [_serialize_account_row(c) for c in page_obj.object_list]

    return JsonResponse({
        'success': True,
        'tab': tab,
        'page': page_obj.number,
        'num_pages': paginator.num_pages,
        'per_page': paginator.per_page,
        'total_count': paginator.count,
        'has_previous': page_obj.has_previous(),
        'has_next': page_obj.has_next(),
        'rows': rows,
    })


@login_required
@require_permission('performance:overview/view')
def performance_contacts_search_api(request):
    """
    Scoped live account search for the Performance Specific-Account filter.
    Never exposes inactive or out-of-scope contacts.
    """
    q = (request.GET.get('q') or '').strip()
    qs = get_scoped_queryset(
        Contact.objects.filter(ACTIVE_ELIGIBLE_ACCOUNT_Q).select_related('area', 'brick'),
        request.user,
        'contact',
    )
    if q:
        from master_data.search_utils import filter_by_arabic_search
        qs = filter_by_arabic_search(
            qs,
            ['name', 'code', 'mobile', 'account_type'],
            q,
            raw_fields=['code', 'mobile'],
            numeric_id_field='serial_num',
        ).distinct()
    results = []
    for c in qs.order_by('name')[:30]:
        loc = c.brick.name if c.brick else (c.area.name if c.area else '')
        results.append({
            'id': c.id,
            'name': c.name,
            'code': c.code or f"#{c.serial_num}",
            'account_type': c.account_type or '',
            'status': c.status,
            'location': loc,
        })
    return JsonResponse({'results': results})


@login_required
@require_permission('performance:overview/export')
def performance_overview_export(request):
    """
    Selective multi-section RTL Excel (.xlsx) export for Performance Overview & Visit Reports.
    Enforces identical DataScope & filters, formula-injection sanitization, date-range safeguard,
    and SecurityAuditLog recording.
    """
    rf = resolve_performance_filters(request, default_preset='this_month')
    span_days = (rf['end_date'] - rf['start_date']).days + 1
    if span_days > MAX_EXPORT_RANGE_DAYS:
        msg = f"لا يمكن تصدير فترة تزيد عن {MAX_EXPORT_RANGE_DAYS} يوماً في ملف واحد. يرجى تضييق النطاق الزمني."
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'message': msg}, status=400)
        messages.error(request, msg)
        return redirect('performance_overview')

    raw_sections = request.GET.getlist('sections')
    if not raw_sections and request.GET.get('sections'):
        raw_sections = [s.strip() for s in request.GET.get('sections', '').split(',') if s.strip()]
    else:
        expanded = []
        for s in raw_sections:
            for part in str(s).split(','):
                part = part.strip()
                if part:
                    expanded.append(part)
        raw_sections = expanded

    selective_mode = request.GET.get('selective') in ('1', 'true', 'yes')
    selected_sections = [s for s in raw_sections if s in VALID_EXPORT_SECTIONS]
    # Preserve unique selection order
    seen_s = set()
    ordered_sections = []
    for s in selected_sections:
        if s not in seen_s:
            seen_s.add(s)
            ordered_sections.append(s)

    if selective_mode and not ordered_sections:
        msg = "يرجى اختيار قسم واحد على الأقل للتصدير."
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'message': msg}, status=400)
        messages.error(request, msg)
        return redirect('performance_overview')

    if not ordered_sections:
        ordered_sections = list(DEFAULT_EXPORT_SECTIONS)

    data = get_performance_overview_data(
        request.user,
        rf['start_date'],
        rf['end_date'],
        rf['prior_start'],
        rf['prior_end'],
        filters=rf,
    )
    analytics = data['analytics']
    cur = data['current']
    prior = data['prior']
    acc_sum = analytics['accounts_summary']

    sheets_spec = []

    if 'summary' in ordered_sections:
        from reports.services import calculate_variance
        prior_an = data.get('prior_analytics') or {}
        prior_acc = prior_an.get('accounts_summary') or {}

        def _srow(metric, cur_v, pri_v, note):
            var = calculate_variance(cur_v, pri_v)
            return {'metric': metric, 'val': cur_v, 'prior': pri_v, 'variance': f"{var}%", 'note': note}

        summary_rows = [
            _srow('أيام العمل الفعلية', analytics['working_days'], prior_an.get('working_days', 0), f"من {analytics['calendar_days']} يوم تقويمي"),
            _srow('إجمالي الزيارات المكتملة', analytics['total_completed_visits'], prior_an.get('total_completed_visits', 0), f"مخططة: {analytics['planned_completed']} | غير مخططة: {analytics['unplanned_completed']}"),
            _srow('الزيارات المخططة المكتملة', analytics['planned_completed'], prior_an.get('planned_completed', 0), f"نسبة تحقيق الخطة: {analytics['plan_completion_pct']}%"),
            _srow('الزيارات المخططة غير المكتملة', analytics['planned_incomplete'], prior_an.get('planned_incomplete', 0), 'تشمل المخططة غير المبدوءة والجارية غير المنتهية'),
            _srow('إجمالي الزيارات المخططة', analytics['planned_total'], prior_an.get('planned_total', 0), 'مكتملة + غير مكتملة'),
            _srow('الزيارات غير المخططة (المكتملة)', analytics['unplanned_completed'], prior_an.get('unplanned_completed', 0), f"جارية الآن: {analytics['unplanned_in_progress']}"),
            _srow('متوسط الزيارات / يوم عمل', analytics['avg_visits_per_working_day'], prior_an.get('avg_visits_per_working_day', 0.0), 'المكتملة ÷ أيام العمل الفعلية'),
            _srow('متوسط الزيارات / يوم تقويمي', analytics['avg_visits_per_calendar_day'], prior_an.get('avg_visits_per_calendar_day', 0.0), 'المكتملة ÷ أيام الفترة'),
            _srow('إجمالي الحسابات المستهدفة', acc_sum['eligible_accounts'], prior_acc.get('eligible_accounts', 0), 'الحسابات النشطة ضمن النطاق والفلاتر'),
            _srow('الحسابات المزارة', acc_sum['visited_accounts'], prior_acc.get('visited_accounts', 0), f"نسبة التغطية: {acc_sum['coverage_pct']}%"),
            _srow('الحسابات غير المزارة', acc_sum['unvisited_accounts'], prior_acc.get('unvisited_accounts', 0), 'المستهدفة − المزارة'),
            _srow('معدل التكرار (Frequency)', acc_sum['visit_frequency'], prior_acc.get('visit_frequency', 0.0), 'متوسط الزيارات لكل حساب مزار'),
            _srow('متوسط مدة الزيارة (دقيقة)', analytics['avg_visit_duration_mins'], prior_an.get('avg_visit_duration_mins', 0.0), f"متوسط ساعات اليوم: {analytics['avg_working_hours']} س"),
            _srow('الزيارات المزدوجة', analytics['double_visits'], prior_an.get('double_visits', 0), f"{analytics['double_visits_pct']}%"),
            _srow('مرات شرح المنتجات (Detailing)', cur['detailing_count'], prior['detailing_count'], f"متوسط: {cur['avg_detailing']}"),
            _srow('المصروفات الميدانية (ج.م)', float(cur['expenses_total']), float(prior['expenses_total']), 'إجمالي نفقات الزيارات'),
        ]
        if has_perm_or_admin(request.user, 'sales:orders/list'):
            summary_rows.append(_srow('قيمة أوامر البيع (ج.م)', float(cur['sales_total']), float(prior['sales_total']), f"{cur['sales_count']} أمر بيع"))
        if has_perm_or_admin(request.user, 'sales:collections/list'):
            summary_rows.append(_srow('إجمالي التحصيلات (ج.م)', float(cur['collections_total']), float(prior['collections_total']), f"{cur['collections_count']} سند تحصيل"))

        sheets_spec.append({
            'sheet_title': 'ملخص الأداء',
            'section_title': 'ملخص مؤشرات الأداء والزيارات',
            'columns': [
                {'header': 'المؤشر', 'key': 'metric', 'width': 32, 'align': 'right'},
                {'header': 'الفترة الحالية', 'key': 'val', 'width': 16, 'align': 'center'},
                {'header': 'الفترة السابقة', 'key': 'prior', 'width': 16, 'align': 'center'},
                {'header': 'نسبة التغير %', 'key': 'variance', 'width': 15, 'align': 'center'},
                {'header': 'التفاصيل / الملاحظة', 'key': 'note', 'width': 42, 'align': 'right'},
            ],
            'rows': summary_rows,
        })

    if 'planned_unplanned' in ordered_sections:
        pu_rows = [
            {'cat': 'الزيارات المخططة', 'sub': 'مخططة مكتملة', 'cnt': analytics['planned_completed'], 'pct': f"{analytics['plan_completion_pct']}% من المخطط"},
            {'cat': 'الزيارات المخططة', 'sub': 'مخططة غير مكتملة', 'cnt': analytics['planned_incomplete'], 'pct': f"{round(100.0 - analytics['plan_completion_pct'], 1) if analytics['planned_total'] else 0.0}% من المخطط"},
            {'cat': 'الزيارات المخططة', 'sub': 'إجمالي الزيارات المخططة', 'cnt': analytics['planned_total'], 'pct': '100%'},
            {'cat': 'الزيارات غير المخططة', 'sub': 'غير مخططة مكتملة', 'cnt': analytics['unplanned_completed'], 'pct': f"{analytics['unplanned_share_pct']}% من المكتملة"},
            {'cat': 'الزيارات غير المخططة', 'sub': 'غير مخططة جارية الآن', 'cnt': analytics['unplanned_in_progress'], 'pct': 'خارج إجمالي المكتملة'},
            {'cat': 'الإجمالي العام', 'sub': 'إجمالي الزيارات المكتملة (مخططة + غير مخططة)', 'cnt': analytics['total_completed_visits'], 'pct': '100%'},
        ]
        sheets_spec.append({
            'sheet_title': 'المخطط وغير المخطط',
            'section_title': 'تحليل الزيارات المخططة مقابل غير المخططة',
            'columns': [
                {'header': 'التصنيف', 'key': 'cat', 'width': 24, 'align': 'right'},
                {'header': 'البند', 'key': 'sub', 'width': 38, 'align': 'right'},
                {'header': 'العدد', 'key': 'cnt', 'width': 14, 'align': 'center'},
                {'header': 'النسبة / الملاحظة', 'key': 'pct', 'width': 26, 'align': 'center'},
            ],
            'rows': pu_rows,
        })

    if 'groups' in ordered_sections:
        grp_rows = []
        for g in analytics['all_group_rows']:
            grp_rows.append({
                'name': g['name'],
                'types': '، '.join(g['account_types']) if g['account_types'] else 'غير محدد',
                'planned_completed': g['planned_completed'],
                'planned_incomplete': g['planned_incomplete'],
                'planned_total': g['planned_total'],
                'plan_pct': g['plan_completion_pct'],
                'unplanned_completed': g['unplanned_completed'],
                'total_completed': g['total_completed'],
                'eligible': g['eligible_accounts'],
                'visited': g['visited_accounts'],
                'unvisited': g['unvisited_accounts'],
                'cov_pct': g['coverage_pct'],
            })
        sheets_spec.append({
            'sheet_title': 'مجموعات الحسابات',
            'section_title': 'إحصائيات مجموعات أنواع الحسابات',
            'columns': [
                {'header': 'المجموعة', 'key': 'name', 'width': 24, 'align': 'right'},
                {'header': 'الأنواع المشمولة', 'key': 'types', 'width': 28, 'align': 'right'},
                {'header': 'مخطط مكتمل', 'key': 'planned_completed', 'width': 14, 'align': 'center'},
                {'header': 'مخطط غير مكتمل', 'key': 'planned_incomplete', 'width': 16, 'align': 'center'},
                {'header': 'إجمالي المخطط', 'key': 'planned_total', 'width': 14, 'align': 'center'},
                {'header': 'تحقيق الخطة %', 'key': 'plan_pct', 'width': 14, 'align': 'center', 'format': '0.0'},
                {'header': 'غير مخطط', 'key': 'unplanned_completed', 'width': 13, 'align': 'center'},
                {'header': 'إجمالي المكتملة', 'key': 'total_completed', 'width': 15, 'align': 'center'},
                {'header': 'الحسابات المستهدفة', 'key': 'eligible', 'width': 16, 'align': 'center'},
                {'header': 'المزارة', 'key': 'visited', 'width': 12, 'align': 'center'},
                {'header': 'غير المزارة', 'key': 'unvisited', 'width': 13, 'align': 'center'},
                {'header': 'التغطية %', 'key': 'cov_pct', 'width': 12, 'align': 'center', 'format': '0.0'},
            ],
            'rows': grp_rows,
        })

    if 'daily' in ordered_sections:
        sheets_spec.append({
            'sheet_title': 'النشاط اليومي',
            'section_title': 'النشاط اليومي للزيارات خلال الفترة المحددة',
            'columns': [
                {'header': 'التاريخ', 'key': 'date', 'width': 14, 'align': 'center'},
                {'header': 'اليوم', 'key': 'weekday_ar', 'width': 14, 'align': 'center'},
                {'header': 'مخططة مكتملة', 'key': 'planned_completed', 'width': 16, 'align': 'center'},
                {'header': 'غير مخططة مكتملة', 'key': 'unplanned_completed', 'width': 18, 'align': 'center'},
                {'header': 'إجمالي المكتملة', 'key': 'total_completed', 'width': 16, 'align': 'center'},
                {'header': 'مخططة غير مكتملة', 'key': 'planned_incomplete', 'width': 18, 'align': 'center'},
                {'header': 'إجمالي المخططة', 'key': 'total_planned', 'width': 15, 'align': 'center'},
            ],
            'rows': analytics['daily_series'],
        })

    account_cols = [
        {'header': 'الكود', 'key': 'code', 'width': 14, 'align': 'center'},
        {'header': 'اسم الحساب', 'key': 'name', 'width': 32, 'align': 'right'},
        {'header': 'نوع الحساب', 'key': 'account_type', 'width': 18, 'align': 'center'},
        {'header': 'الحالة', 'key': 'status_ar', 'width': 14, 'align': 'center'},
        {'header': 'المحافظة', 'key': 'area_name', 'width': 18, 'align': 'right'},
        {'header': 'الخط الجغرافي', 'key': 'brick_name', 'width': 18, 'align': 'right'},
        {'header': 'المندوب', 'key': 'rep_name', 'width': 22, 'align': 'right'},
        {'header': 'الزيارات المكتملة بالفترة', 'key': 'completed_visits', 'width': 20, 'align': 'center'},
        {'header': 'مخططة غير مكتملة', 'key': 'incomplete_planned', 'width': 18, 'align': 'center'},
        {'header': 'آخر زيارة مكتملة', 'key': 'last_visit_date', 'width': 16, 'align': 'center'},
    ]

    if 'visited_accounts' in ordered_sections:
        visited_qs = VisitAnalyticsService.get_accounts_drilldown_queryset(request.user, rf, tab='visited')
        sheets_spec.append({
            'sheet_title': 'الحسابات المزارة',
            'section_title': f"الحسابات المزارة ({acc_sum['visited_accounts']})",
            'columns': account_cols,
            'rows': (_serialize_account_row(c) for c in visited_qs.iterator(chunk_size=500)),
        })

    if 'unvisited_accounts' in ordered_sections:
        unvisited_qs = VisitAnalyticsService.get_accounts_drilldown_queryset(request.user, rf, tab='unvisited')
        sheets_spec.append({
            'sheet_title': 'الحسابات غير المزارة',
            'section_title': f"الحسابات غير المزارة ({acc_sum['unvisited_accounts']})",
            'columns': account_cols,
            'rows': (_serialize_account_row(c) for c in unvisited_qs.iterator(chunk_size=500)),
        })

    if 'visit_details' in ordered_sections:
        details_qs = VisitAnalyticsService.get_account_visit_details_queryset(request.user, rf)
        sheets_spec.append({
            'sheet_title': 'تفاصيل الزيارات',
            'section_title': 'سجل الزيارات التفصيلي على مستوى الحساب',
            'columns': [
                {'header': 'رقم الزيارة', 'key': lambda v: f"#{v.serial_num}", 'width': 14, 'align': 'center'},
                {'header': 'التاريخ', 'key': 'date', 'width': 14, 'align': 'center'},
                {'header': 'اسم الحساب', 'key': lambda v: v.contact.name if v.contact else '', 'width': 30, 'align': 'right'},
                {'header': 'نوع الحساب', 'key': lambda v: (v.contact.account_type or 'غير مصنف') if v.contact else '', 'width': 16, 'align': 'center'},
                {'header': 'حالة الحساب', 'key': lambda v: ('عميل فعلي' if v.contact.status == 'customer' else 'عميل محتمل') if v.contact else '', 'width': 14, 'align': 'center'},
                {'header': 'المحافظة', 'key': lambda v: v.contact.area.name if (v.contact and v.contact.area) else '–', 'width': 18, 'align': 'right'},
                {'header': 'الخط الجغرافي', 'key': lambda v: v.contact.brick.name if (v.contact and v.contact.brick) else '–', 'width': 18, 'align': 'right'},
                {'header': 'المندوب', 'key': lambda v: (v.owner.name or v.owner.username) if v.owner else '–', 'width': 22, 'align': 'right'},
                {'header': 'نوع التخطيط', 'key': lambda v: 'مخططة' if v.is_planned else 'غير مخططة', 'width': 14, 'align': 'center'},
                {'header': 'حالة التنفيذ', 'key': lambda v: v.status_display_ar, 'width': 14, 'align': 'center'},
                {'header': 'حالة الاعتماد', 'key': lambda v: v.approval_display_ar, 'width': 14, 'align': 'center'},
                {'header': 'المدة', 'key': lambda v: v.duration_formatted, 'width': 16, 'align': 'center'},
            ],
            'rows': details_qs.iterator(chunk_size=500),
        })

    AuditLogService.log(
        action_type='REPORT_EXPORTED',
        module='performance',
        actor=request.user,
        record_name='تقرير الأداء والزيارات الميدانية',
        new_values={
            'report': 'performance_overview',
            'sections': ordered_sections,
            'start_date': rf['start_date_str'],
            'end_date': rf['end_date_str'],
            'rep_id': rf['rep_id'],
            'area_ids': rf['area_ids'],
            'brick_ids': rf['brick_ids'],
            'account_status': rf['account_status'],
        },
        description=f"تصدير تقرير الأداء والزيارات ({len(ordered_sections)} أقسام) للفترة {rf['start_date_str']} إلى {rf['end_date_str']}",
        status='SUCCESS',
        request=request,
    )

    filename = f"Performance_Visit_Report_{rf['start_date_str']}_{rf['end_date_str']}"
    return export_multisheet_excel_response(
        sheets_spec,
        filename=filename,
        report_title="تقرير الأداء والزيارات الميدانية",
        filter_summary=rf['filter_summary'],
        user=request.user,
    )


@login_required
@require_permission('performance:analysis/view')
def performance_analysis(request):
    """
    Performance Analytical view: comparative rep analytics & charts using centralized rules.
    """
    rf = resolve_performance_filters(request, default_preset='this_month')
    data = get_performance_analysis_data(request.user, rf['start_date'], rf['end_date'], filters=rf)

    context = {
        'rf': rf,
        'period': rf['period'],
        'period_label': rf['period_label'],
        'start_date': rf['start_date_str'],
        'end_date': rf['end_date_str'],
        'selected_area': rf['area_ids'][0] if len(rf['area_ids']) == 1 else '',
        'selected_rep': rf['rep_id'] or '',
        'areas': rf['areas_qs'],
        'reps': rf['reps_qs'],
        'can_select_rep': rf['can_select_rep'],
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
    """Branded Excel export for the rep comparison table."""
    rf = resolve_performance_filters(request, default_preset='this_month')
    data = get_performance_analysis_data(request.user, rf['start_date'], rf['end_date'], filters=rf)

    rows = data['rep_summary_table']
    columns = [
        {'header': 'اسم المندوب', 'key': 'name', 'width': 24, 'align': 'right'},
        {'header': 'الكود', 'key': 'code', 'width': 12, 'align': 'center'},
        {'header': 'المنطقة / المحافظة', 'key': 'area_name', 'width': 20, 'align': 'right'},
        {'header': 'الحسابات المستهدفة', 'key': 'assigned_contacts', 'width': 16, 'align': 'center'},
        {'header': 'المزارة', 'key': 'visited_contacts', 'width': 12, 'align': 'center'},
        {'header': 'غير المزارة', 'key': 'unvisited_contacts', 'width': 13, 'align': 'center'},
        {'header': 'نسبة التغطية %', 'key': 'coverage_pct', 'width': 14, 'align': 'center', 'format': '0.0'},
        {'header': 'إجمالي المكتملة', 'key': 'total_visits', 'width': 15, 'align': 'center'},
        {'header': 'مخطط مكتمل', 'key': 'planned_visits', 'width': 14, 'align': 'center'},
        {'header': 'مخطط غير مكتمل', 'key': 'planned_incomplete', 'width': 16, 'align': 'center'},
        {'header': 'غير مخطط', 'key': 'unplanned_visits', 'width': 13, 'align': 'center'},
        {'header': 'تحقيق الخطة %', 'key': 'plan_ach_pct', 'width': 14, 'align': 'center', 'format': '0.0'},
        {'header': 'معدل التكرار', 'key': 'frequency', 'width': 13, 'align': 'center', 'format': '0.00'},
        {'header': 'أيام العمل', 'key': 'field_days', 'width': 13, 'align': 'center'},
        {'header': 'معدل/يوم عمل', 'key': 'daily_rate', 'width': 14, 'align': 'center', 'format': '0.0'},
        {'header': 'مرات الشرح', 'key': 'detailing_count', 'width': 13, 'align': 'center'},
        {'header': 'المبيعات (ج.م)', 'key': 'sales_val', 'width': 16, 'align': 'right', 'format': '#,##0.00'},
        {'header': 'التحصيلات (ج.م)', 'key': 'col_val', 'width': 16, 'align': 'right', 'format': '#,##0.00'},
    ]

    AuditLogService.log(
        action_type='REPORT_EXPORTED',
        module='performance',
        actor=request.user,
        record_name='تحليل أداء المناديب',
        new_values={'report': 'performance_analysis', 'start_date': rf['start_date_str'], 'end_date': rf['end_date_str']},
        description=f"تصدير تحليل أداء المناديب للفترة {rf['start_date_str']} إلى {rf['end_date_str']}",
        status='SUCCESS',
        request=request,
    )

    return export_multisheet_excel_response(
        [{'sheet_title': 'تحليل أداء المناديب', 'section_title': 'مقارنة أداء المناديب', 'columns': columns, 'rows': rows}],
        filename=f"Performance_Analysis_{rf['start_date_str']}_{rf['end_date_str']}",
        report_title="تقرير تحليل أداء المناديب",
        filter_summary=rf['filter_summary'],
        user=request.user,
    )


@login_required
@require_permission('performance:daily/view')
def performance_daily(request):
    """
    Daily micro-dashboard: Day picker (Africa/Cairo), daily KPIs vs yesterday,
    set-based rep activity grid, and 8 daily drilldown tabs.
    """
    date_str = (request.GET.get('date') or '').strip()
    today = timezone.localdate()
    try:
        target_date = datetime.date.fromisoformat(date_str) if date_str else today
    except Exception:
        target_date = today

    prev_date = target_date - datetime.timedelta(days=1)
    next_date = target_date + datetime.timedelta(days=1)

    rf = resolve_performance_filters(request, default_preset='today')
    rf['start_date'] = target_date
    rf['end_date'] = target_date
    data = get_performance_daily_data(request.user, target_date, filters=rf)

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
    """Branded Excel export for daily rep activity grid."""
    date_str = (request.GET.get('date') or '').strip()
    today = timezone.localdate()
    try:
        target_date = datetime.date.fromisoformat(date_str) if date_str else today
    except Exception:
        target_date = today

    rf = resolve_performance_filters(request, default_preset='today')
    rf['start_date'] = target_date
    rf['end_date'] = target_date
    data = get_performance_daily_data(request.user, target_date, filters=rf)

    columns = [
        {'header': 'اسم المندوب', 'key': 'name', 'width': 24, 'align': 'right'},
        {'header': 'المنطقة', 'key': 'area', 'width': 18, 'align': 'right'},
        {'header': 'أول تسجيل', 'key': 'first_checkin', 'width': 12, 'align': 'center'},
        {'header': 'آخر تسجيل', 'key': 'last_checkout', 'width': 12, 'align': 'center'},
        {'header': 'ساعات العمل', 'key': 'working_hours', 'width': 13, 'align': 'center'},
        {'header': 'مخططة مكتملة', 'key': 'planned_completed', 'width': 14, 'align': 'center'},
        {'header': 'مخططة غير مكتملة', 'key': 'planned_incomplete', 'width': 16, 'align': 'center'},
        {'header': 'غير مخططة', 'key': 'unplanned_visits', 'width': 13, 'align': 'center'},
        {'header': 'إجمالي المكتملة', 'key': 'completed_visits', 'width': 15, 'align': 'center'},
        {'header': 'الملغاة', 'key': 'cancelled_visits', 'width': 11, 'align': 'center'},
        {'header': 'المزدوجة', 'key': 'double_visits', 'width': 11, 'align': 'center'},
        {'header': 'مرات الشرح', 'key': 'detailing_count', 'width': 12, 'align': 'center'},
        {'header': 'دقة الموقع %', 'key': 'in_range_pct', 'width': 13, 'align': 'center', 'format': '0.0'},
        {'header': 'الطلبيات', 'key': 'orders_count', 'width': 11, 'align': 'center'},
        {'header': 'المبيعات (ج.م)', 'key': 'orders_val', 'width': 15, 'align': 'right', 'format': '#,##0.00'},
        {'header': 'التحصيلات (ج.م)', 'key': 'cols_val', 'width': 15, 'align': 'right', 'format': '#,##0.00'},
        {'header': 'المصروفات (ج.م)', 'key': 'expenses_val', 'width': 15, 'align': 'right', 'format': '#,##0.00'},
        {'header': 'حالة اليوم', 'key': 'status', 'width': 16, 'align': 'center'},
    ]

    AuditLogService.log(
        action_type='REPORT_EXPORTED',
        module='performance',
        actor=request.user,
        record_name=f"نشاط يوم {target_date}",
        new_values={'report': 'performance_daily', 'date': target_date.isoformat()},
        description=f"تصدير كشف النشاط اليومي لتاريخ {target_date.isoformat()}",
        status='SUCCESS',
        request=request,
    )

    return export_multisheet_excel_response(
        [{'sheet_title': f"نشاط {target_date}", 'section_title': f"النشاط الميداني ليوم {target_date}", 'columns': columns, 'rows': data['daily_rep_grid']}],
        filename=f"Daily_Performance_{target_date}",
        report_title="تقرير النشاط الميداني اليومي",
        filter_summary=f"التاريخ: {target_date.isoformat()}",
        user=request.user,
    )


@login_required
@require_permission('performance:detailed/view')
def performance_detailed(request):
    """
    Performance Detailed view: Set-based matrix with dynamically configured
    AccountTypeReportGroup columns + coaching logs.
    """
    rf = resolve_performance_filters(request, default_preset='this_month')
    data = get_performance_detailed_matrix(request.user, rf['start_date'], rf['end_date'], filters=rf)

    context = {
        'rf': rf,
        'period': rf['period'],
        'period_label': rf['period_label'],
        'start_date': rf['start_date_str'],
        'end_date': rf['end_date_str'],
        'selected_area': rf['area_ids'][0] if len(rf['area_ids']) == 1 else '',
        'selected_rep': rf['rep_id'] or '',
        'areas': rf['areas_qs'],
        'reps': rf['reps_qs'],
        'can_select_rep': rf['can_select_rep'],
        'group_columns': data['group_columns'],
        'matrix_rows': data['matrix_rows'],
        'coaching_logs': data['coaching_logs'],
        'coaching_rows': data['coaching_logs'],
    }
    return render(request, 'performance/detailed.html', context)


@login_required
@require_permission('performance:detailed/export')
def performance_detailed_export(request):
    """Branded Excel export for the detailed matrix with dynamic AccountTypeReportGroup columns."""
    rf = resolve_performance_filters(request, default_preset='this_month')
    data = get_performance_detailed_matrix(request.user, rf['start_date'], rf['end_date'], filters=rf)
    group_columns = data['group_columns']

    columns = [
        {'header': 'المندوب', 'key': 'name', 'width': 24, 'align': 'right'},
        {'header': 'الكود', 'key': 'code', 'width': 12, 'align': 'center'},
        {'header': 'المنطقة', 'key': 'area', 'width': 18, 'align': 'right'},
    ]
    for idx, gc in enumerate(group_columns):
        columns.append({
            'header': f"{gc['name']} (حسابات / زيارات)",
            'key': (lambda i: lambda r: f"{r['group_cells'][i]['accounts']} / {r['group_cells'][i]['completed_visits']}")(idx),
            'width': 22,
            'align': 'center',
        })
    columns.extend([
        {'header': 'تغطية A %', 'key': 'class_a_cov', 'width': 12, 'align': 'center', 'format': '0.0'},
        {'header': 'تغطية B %', 'key': 'class_b_cov', 'width': 12, 'align': 'center', 'format': '0.0'},
        {'header': 'تغطية C %', 'key': 'class_c_cov', 'width': 12, 'align': 'center', 'format': '0.0'},
        {'header': 'إجمالي المكتملة', 'key': 'total_visits', 'width': 15, 'align': 'center'},
        {'header': 'مخططة مكتملة', 'key': 'planned_visits', 'width': 14, 'align': 'center'},
        {'header': 'مخططة غير مكتملة', 'key': 'planned_incomplete', 'width': 16, 'align': 'center'},
        {'header': 'غير مخططة', 'key': 'unplanned_visits', 'width': 13, 'align': 'center'},
        {'header': 'صباحية AM', 'key': 'am_visits', 'width': 12, 'align': 'center'},
        {'header': 'مسائية PM', 'key': 'pm_visits', 'width': 12, 'align': 'center'},
        {'header': 'متوسط المدة (د)', 'key': 'avg_duration', 'width': 14, 'align': 'center', 'format': '0.0'},
        {'header': 'داخل النطاق', 'key': 'in_range_cnt', 'width': 13, 'align': 'center'},
        {'header': 'خارج النطاق', 'key': 'out_range_cnt', 'width': 13, 'align': 'center'},
        {'header': 'تجاوزات', 'key': 'bypassed_cnt', 'width': 11, 'align': 'center'},
        {'header': 'مرات الشرح', 'key': 'detailing_cnt', 'width': 12, 'align': 'center'},
        {'header': 'العينات', 'key': 'samples_cnt', 'width': 11, 'align': 'center'},
        {'header': 'الطلبيات', 'key': 'sales_cnt', 'width': 11, 'align': 'center'},
        {'header': 'إجمالي المبيعات', 'key': 'sales_gross', 'width': 16, 'align': 'right', 'format': '#,##0.00'},
        {'header': 'صافي المبيعات', 'key': 'sales_net', 'width': 16, 'align': 'right', 'format': '#,##0.00'},
        {'header': 'التحصيلات', 'key': 'cols_net', 'width': 16, 'align': 'right', 'format': '#,##0.00'},
    ])

    AuditLogService.log(
        action_type='REPORT_EXPORTED',
        module='performance',
        actor=request.user,
        record_name='مصفوفة الأداء المفصلة',
        new_values={'report': 'performance_detailed', 'start_date': rf['start_date_str'], 'end_date': rf['end_date_str']},
        description=f"تصدير مصفوفة الأداء المفصلة للفترة {rf['start_date_str']} إلى {rf['end_date_str']}",
        status='SUCCESS',
        request=request,
    )

    return export_multisheet_excel_response(
        [{'sheet_title': 'مصفوفة الأداء', 'section_title': 'مصفوفة الأداء الميداني المفصلة', 'columns': columns, 'rows': data['matrix_rows']}],
        filename=f"Detailed_Matrix_{rf['start_date_str']}_{rf['end_date_str']}",
        report_title="مصفوفة الأداء الميداني المفصلة",
        filter_summary=rf['filter_summary'],
        user=request.user,
    )
