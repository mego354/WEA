import datetime
from decimal import Decimal
from django.db import models
from django.db.models import Sum, Count, Max, Min, Q, Avg, F, Case, When, Value, DecimalField, IntegerField
from django.utils import timezone
from django.http import HttpResponse

from accounts.permissions import get_scoped_queryset, get_visible_assignees_queryset
from accounts.scope_service import ScopeResolutionService
from contacts.models import Contact
from sales.models import SalesOrder, SalesOrderItem, SalesReturnOrder, SalesReturnOrderItem, Collection, CustomerAccount, CustomerTransaction
from purchases.models import PurchaseOrder, PurchaseOrderItem
from inventory.models import Warehouse, InventoryStock
from activities.models import Visit, PlannedVisitDay, PlannedVisitItem, Agreement, VisitSampleItem, VisitExpense
from reports.models import SalesTarget, CustomerCall, CoachingEvaluation
from master_data.models import Area
from master_data.date_filter_utils import PRESET_LABELS_AR, resolve_date_range
from master_data.services import SettingsService
from reports.visit_analytics import (
    ACTIVE_ELIGIBLE_ACCOUNT_Q,
    COMPLETED_VISIT_Q,
    PLANNED_COMPLETED_Q,
    PLANNED_INCOMPLETE_Q,
    UNLINKED_PLANNED_ITEM_Q,
    UNPLANNED_COMPLETED_Q,
    UNPLANNED_IN_PROGRESS_Q,
    UNCLASSIFIED_GROUP_CODE,
    UNCLASSIFIED_GROUP_NAME,
    VisitAnalyticsService,
    compute_prior_period,
    _apply_contact_filters,
    _build_rep_contacts_q,
)


def parse_date_range(period=None, start_date_str=None, end_date_str=None):
    """
    Unified date-range parser delegating to `master_data.date_filter_utils.resolve_date_range`
    (Africa/Cairo via `timezone.localdate()`, Saturday -> Friday weeks, full current month).
    Returns (start_date, end_date, prior_start_date, prior_end_date, period_label).
    """
    params = {}
    if period:
        params['period'] = str(period).strip()
    if start_date_str:
        params['start_date'] = str(start_date_str).strip()
    if end_date_str:
        params['end_date'] = str(end_date_str).strip()

    start_date, end_date, active_preset, start_s, end_s = resolve_date_range(
        params, default_preset='this_month'
    )
    if not start_date or not end_date:
        start_date, end_date, active_preset, start_s, end_s = resolve_date_range(
            {}, default_preset='this_month'
        )
    prior_start, prior_end = compute_prior_period(start_date, end_date, active_preset)
    if active_preset == 'custom':
        period_label = f"من {start_s} إلى {end_s}"
    else:
        period_label = PRESET_LABELS_AR.get(active_preset, 'الشهر الحالي')
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

def _normalize_legacy_filters(user, start_date, end_date, filters=None):
    """
    Normalize a legacy dict `filters` (or an already-resolved filter dict from
    `resolve_performance_filters`) into a strictly scope-validated filter dict.
    """
    filters = dict(filters or {})
    if 'unauthorized_filter' in filters and 'account_status' in filters:
        rf = dict(filters)
        rf['start_date'] = start_date
        rf['end_date'] = end_date
        return rf

    from accounts.models import User as AccUser
    unauthorized = False
    is_super = bool(user.is_superuser or getattr(user, 'is_super_admin', False))
    act_scope = 'all' if is_super else ScopeResolutionService.get_user_scope(user, 'activities', 'view')
    can_select_rep = is_super or act_scope in ('area', 'all')

    rep_id = None
    selected_rep = None
    raw_rep = filters.get('rep_id')
    if raw_rep not in (None, '', 'all'):
        try:
            pid = int(raw_rep)
        except (TypeError, ValueError):
            pid = None
        if pid is not None:
            allowed_ids = set(get_visible_assignees_queryset(user, module='activities').values_list('id', flat=True))
            allowed_ids.add(user.pk)
            if not can_select_rep and pid != user.pk:
                unauthorized = True
            elif pid in allowed_ids:
                rep_id = pid
                selected_rep = AccUser.objects.prefetch_related('assigned_areas').filter(pk=pid).first()
            else:
                unauthorized = True

    gov_act = ScopeResolutionService.get_scoped_choices(user, 'governorates', 'activities')
    gov_con = ScopeResolutionService.get_scoped_choices(user, 'governorates', 'contacts')
    auth_gov_ids = set(gov_act.values_list('id', flat=True)) | set(gov_con.values_list('id', flat=True))

    brick_act = ScopeResolutionService.get_scoped_choices(user, 'bricks', 'activities')
    brick_con = ScopeResolutionService.get_scoped_choices(user, 'bricks', 'contacts')
    auth_brick_ids = set(brick_act.values_list('id', flat=True)) | set(brick_con.values_list('id', flat=True))

    area_ids = []
    raw_areas = filters.get('area_ids') or ([filters['area_id']] if filters.get('area_id') else [])
    parsed_areas = []
    for a in raw_areas:
        try:
            parsed_areas.append(int(a))
        except (TypeError, ValueError):
            continue
    if parsed_areas:
        area_ids = [a for a in parsed_areas if a in auth_gov_ids]
        if not area_ids:
            unauthorized = True

    brick_ids = []
    raw_bricks = filters.get('brick_ids') or ([filters['brick_id']] if filters.get('brick_id') else [])
    parsed_bricks = []
    for b in raw_bricks:
        try:
            parsed_bricks.append(int(b))
        except (TypeError, ValueError):
            continue
    if parsed_bricks:
        brick_ids = [b for b in parsed_bricks if b in auth_brick_ids]
        if not brick_ids:
            unauthorized = True

    account_types = list(filters.get('account_types') or [])
    if filters.get('account_type') and filters['account_type'] not in account_types:
        account_types.append(str(filters['account_type']).strip())
    account_types = [t for t in account_types if t and t.lower() not in ('all', 'nan', 'none')]

    account_status = (filters.get('account_status') or 'all').strip().lower()
    if account_status not in ('all', 'customer', 'lead'):
        account_status = 'all'

    contact_id = None
    if filters.get('contact_id'):
        try:
            cid = int(filters['contact_id'])
        except (TypeError, ValueError):
            cid = None
        if cid is not None:
            if get_scoped_queryset(Contact.objects.filter(ACTIVE_ELIGIBLE_ACCOUNT_Q, pk=cid), user, 'contact').exists():
                contact_id = cid
            else:
                unauthorized = True

    return {
        'start_date': start_date,
        'end_date': end_date,
        'rep_id': rep_id,
        'selected_rep': selected_rep,
        'area_ids': area_ids,
        'brick_ids': brick_ids,
        'selected_group': filters.get('selected_group'),
        'selected_group_code': filters.get('selected_group_code', ''),
        'account_types': account_types,
        'account_status': account_status,
        'contact_id': contact_id,
        'unauthorized_filter': unauthorized,
        'active_groups': filters.get('active_groups') or SettingsService.get_account_type_report_groups(active_only=True),
    }


def get_performance_overview_data(user, start_date, end_date, prior_start, prior_end, filters=None):
    """
    Computes all Performance Overview KPIs, Visit Analytics Bundle (planned/unplanned,
    working days, avg visits/day, dynamic account-type groups, daily activity series,
    visited/unvisited accounts reconciliation), and commercial metrics.
    """
    rf_cur = _normalize_legacy_filters(user, start_date, end_date, filters)
    rf_prior = dict(rf_cur, start_date=prior_start, end_date=prior_end)

    cur_bundle = VisitAnalyticsService.get_analytics_bundle(user, rf_cur, include_daily_series=True)
    prior_bundle = VisitAnalyticsService.get_analytics_bundle(user, rf_prior, include_daily_series=False)

    # Commercial & Coaching scoped querysets
    if rf_cur.get('unauthorized_filter'):
        orders_qs = SalesOrder.objects.none()
        collections_qs = Collection.objects.none()
        expenses_qs = VisitExpense.objects.none()
        coaching_qs = CoachingEvaluation.objects.none()
        cur_completed_visits_qs = Visit.objects.none()
        prior_completed_visits_qs = Visit.objects.none()
    else:
        _, cur_period_visits, _, _ = VisitAnalyticsService.build_scoped_querysets(user, rf_cur)
        _, prior_period_visits, _, _ = VisitAnalyticsService.build_scoped_querysets(user, rf_prior)
        cur_completed_visits_qs = Visit.objects.filter(id__in=cur_period_visits.values('id')).filter(COMPLETED_VISIT_Q)
        prior_completed_visits_qs = Visit.objects.filter(id__in=prior_period_visits.values('id')).filter(COMPLETED_VISIT_Q)

        orders_qs = get_scoped_queryset(
            SalesOrder.objects.exclude(status__in=['cancelled', 'rejected']), user, 'salesorder'
        )
        collections_qs = get_scoped_queryset(Collection.objects.all(), user, 'collection')
        expenses_qs = get_scoped_queryset(VisitExpense.objects.all(), user, 'visitexpense')
        coaching_qs = get_scoped_queryset(CoachingEvaluation.objects.all(), user, 'coachingevaluation')

        if rf_cur.get('rep_id'):
            rid = rf_cur['rep_id']
            orders_qs = orders_qs.filter(created_by_id=rid)
            collections_qs = collections_qs.filter(created_by_id=rid)
            expenses_qs = expenses_qs.filter(visit__owner_id=rid)
            coaching_qs = coaching_qs.filter(rep_id=rid)
        if rf_cur.get('area_ids'):
            aids = rf_cur['area_ids']
            orders_qs = orders_qs.filter(Q(customer__area_id__in=aids) | Q(customer__brick__parent_id__in=aids))
            collections_qs = collections_qs.filter(Q(customer__area_id__in=aids) | Q(customer__brick__parent_id__in=aids))
            expenses_qs = expenses_qs.filter(Q(visit__contact__area_id__in=aids) | Q(visit__contact__brick__parent_id__in=aids))
        if rf_cur.get('brick_ids'):
            bids = rf_cur['brick_ids']
            orders_qs = orders_qs.filter(customer__brick_id__in=bids)
            collections_qs = collections_qs.filter(customer__brick_id__in=bids)
            expenses_qs = expenses_qs.filter(visit__contact__brick_id__in=bids)
        if rf_cur.get('contact_id'):
            cid = rf_cur['contact_id']
            orders_qs = orders_qs.filter(customer_id=cid)
            collections_qs = collections_qs.filter(customer_id=cid)
            expenses_qs = expenses_qs.filter(visit__contact_id=cid)

    def _build_period_dict(bundle, completed_v_qs, s_date, e_date):
        acc = bundle['accounts_summary']
        expected_days = calculate_expected_working_days(s_date, e_date)
        field_days = bundle['working_days']
        off_field_days = max(0, expected_days - field_days)

        det_agg = completed_v_qs.aggregate(
            det_cnt=Count('detailed_products'),
            det_vis=Count('id', filter=Q(detailed_products__isnull=False), distinct=True),
        )
        detailing_count = det_agg['det_cnt'] or 0
        visits_with_detailing = det_agg['det_vis'] or 0
        avg_detailing = safe_div(detailing_count, visits_with_detailing, 1)

        o_agg = orders_qs.filter(order_date__gte=s_date, order_date__lte=e_date).aggregate(
            cnt=Count('id', distinct=True), total=Sum('grand_total')
        )
        c_agg = collections_qs.filter(collection_date__gte=s_date, collection_date__lte=e_date).aggregate(
            cnt=Count('id', distinct=True), total=Sum('amount')
        )
        e_total = expenses_qs.filter(
            visit__date__gte=s_date, visit__date__lte=e_date, visit__status='finished'
        ).exclude(visit__approval_status='disapproved').aggregate(t=Sum('amount'))['t'] or Decimal('0.00')
        assessments_count = coaching_qs.filter(date__gte=s_date, date__lte=e_date).count()

        freq = acc['visit_frequency']
        daily_rate = bundle['avg_visits_per_working_day']

        return {
            'total_contacts': acc['eligible_accounts'],
            'visited_contacts': acc['visited_accounts'],
            'unvisited_contacts': acc['unvisited_accounts'],
            'coverage_pct': acc['coverage_pct'],
            'total_visits': bundle['total_completed_visits'],
            'frequency': freq,
            'frequency_ach_pct': safe_div(freq * 100, 2.0, 1),
            'expected_days': expected_days,
            'calendar_days': bundle['calendar_days'],
            'field_days': field_days,
            'off_field_days': off_field_days,
            'daily_rate': daily_rate,
            'avg_visits_per_calendar_day': bundle['avg_visits_per_calendar_day'],
            'daily_rate_ach_pct': safe_div(daily_rate * 100, 10.0, 1),
            'smart_daily_rate': bundle['avg_visits_per_calendar_day'],
            'avg_visit_duration_mins': bundle['avg_visit_duration_mins'],
            'avg_working_hours': bundle['avg_working_hours'],
            'detailing_count': detailing_count,
            'avg_detailing': avg_detailing,
            'planned_visits': bundle['planned_completed'],
            'planned_completed': bundle['planned_completed'],
            'planned_incomplete': bundle['planned_incomplete'],
            'planned_total': bundle['planned_total'],
            'unplanned_visits': bundle['unplanned_completed'],
            'unplanned_in_progress': bundle['unplanned_in_progress'],
            'planned_pct': bundle['planned_share_pct'],
            'unplanned_pct': bundle['unplanned_share_pct'],
            'plan_ach_pct': bundle['plan_completion_pct'],
            'double_visits': bundle['double_visits'],
            'double_visits_pct': bundle['double_visits_pct'],
            'assessments_count': assessments_count,
            'expenses_total': e_total,
            'sales_count': o_agg['cnt'] or 0,
            'sales_total': o_agg['total'] or Decimal('0.00'),
            'collections_count': c_agg['cnt'] or 0,
            'collections_total': c_agg['total'] or Decimal('0.00'),
        }

    current = _build_period_dict(cur_bundle, cur_completed_visits_qs, start_date, end_date)
    prior = _build_period_dict(prior_bundle, prior_completed_visits_qs, prior_start, prior_end)

    kpis = {
        'coverage': {
            'value': current['coverage_pct'],
            'unit': '%',
            'label': 'نسبة التغطية',
            'variance': calculate_variance(current['coverage_pct'], prior['coverage_pct']),
            'icon': 'pie_chart',
            'detail': f"{current['visited_contacts']} مزار / {current['total_contacts']} مستهدف",
        },
        'plan_ach': {
            'value': current['plan_ach_pct'],
            'unit': '%',
            'label': 'تحقيق خطة الزيارات',
            'variance': calculate_variance(current['plan_ach_pct'], prior['plan_ach_pct']),
            'icon': 'event_available',
            'detail': f"{current['planned_completed']} من {current['planned_total']} مخططة",
        },
        'field_days': {
            'value': current['field_days'],
            'unit': 'يوم',
            'label': 'أيام العمل الفعلية',
            'variance': calculate_variance(current['field_days'], prior['field_days']),
            'icon': 'work_history',
            'detail': f"من {current['calendar_days']} يوم تقويمي",
        },
        'daily_rate': {
            'value': current['daily_rate'],
            'unit': 'زيارة/يوم',
            'label': 'متوسط الزيارات / يوم عمل',
            'variance': calculate_variance(current['daily_rate'], prior['daily_rate']),
            'icon': 'speed',
            'detail': f"تقويمي: {current['avg_visits_per_calendar_day']} / يوم",
        },
        'total_visits': {
            'value': current['total_visits'],
            'unit': 'زيارة',
            'label': 'إجمالي الزيارات المكتملة',
            'variance': calculate_variance(current['total_visits'], prior['total_visits']),
            'icon': 'verified',
            'detail': f"مخططة: {current['planned_completed']} | غير مخططة: {current['unplanned_visits']}",
        },
        'frequency': {
            'value': current['frequency'],
            'unit': '',
            'label': 'معدل التكرار (Frequency)',
            'variance': calculate_variance(current['frequency'], prior['frequency']),
            'icon': 'sync',
            'detail': 'متوسط الزيارات لكل حساب مزار',
        },
        'avg_visit_duration': {
            'value': current['avg_visit_duration_mins'],
            'unit': 'دقيقة',
            'label': 'متوسط مدة الزيارة',
            'variance': calculate_variance(current['avg_visit_duration_mins'], prior['avg_visit_duration_mins']),
            'icon': 'timer',
            'detail': f"ساعات اليوم: {current['avg_working_hours']} س",
        },
        'detailing_count': {
            'value': current['detailing_count'],
            'unit': 'مرة',
            'label': 'شرح المنتجات (Detailing)',
            'variance': calculate_variance(current['detailing_count'], prior['detailing_count']),
            'icon': 'medical_services',
            'detail': f"متوسط: {current['avg_detailing']} بالزيارة",
        },
        'double_visits': {
            'value': current['double_visits'],
            'unit': 'زيارة',
            'label': 'الزيارات المزدوجة',
            'variance': calculate_variance(current['double_visits'], prior['double_visits']),
            'icon': 'groups',
            'detail': f"نسبة: {current['double_visits_pct']}% من المكتملة",
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

    # Top Detailed Products (qualifying completed visits only)
    top_products_raw = (
        cur_completed_visits_qs.filter(detailed_products__isnull=False)
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
        'analytics': cur_bundle,
        'prior_analytics': prior_bundle,
        'top_detailed_products': top_detailed_products,
    }


def _compute_rep_eligible_account_counts(scoped_contacts_qs, reps_list):
    """
    Compute per-rep eligible active account counts using constant batch queries
    (strictly within `scoped_contacts_qs`, avoiding per-rep SQL loops).
    """
    if not reps_list:
        return {}

    rep_ids = [r.id for r in reps_list]
    rep_bricks_map = {}
    rep_govs_map = {}
    all_brick_ids = set()
    all_gov_ids = set()

    for r in reps_list:
        b_ids = set()
        g_ids = set()
        for a in r.assigned_areas.all():
            if a.parent_id is not None:
                b_ids.add(a.id)
                all_brick_ids.add(a.id)
            else:
                g_ids.add(a.id)
                all_gov_ids.add(a.id)
        rep_bricks_map[r.id] = b_ids
        rep_govs_map[r.id] = g_ids

    # Batch fetch contact ownership/territory tuples within viewer's scoped active contacts
    base_contacts = scoped_contacts_qs.filter(ACTIVE_ELIGIBLE_ACCOUNT_Q)
    contact_rows = list(
        base_contacts.values_list('id', 'created_by_id', 'brick_id', 'area_id', 'brick__parent_id')
    )
    assigned_pairs = list(
        Contact.assigned_team.through.objects.filter(
            user_id__in=rep_ids,
            contact_id__in=base_contacts.values('id'),
        ).values_list('user_id', 'contact_id')
    )

    rep_contact_sets = {rid: set() for rid in rep_ids}
    for uid, cid in assigned_pairs:
        if uid in rep_contact_sets:
            rep_contact_sets[uid].add(cid)

    brick_to_reps = {}
    gov_to_reps = {}
    for rid in rep_ids:
        for bid in rep_bricks_map[rid]:
            brick_to_reps.setdefault(bid, []).append(rid)
        for gid in rep_govs_map[rid]:
            gov_to_reps.setdefault(gid, []).append(rid)

    for cid, created_by_id, brick_id, area_id, brick_parent_id in contact_rows:
        if created_by_id in rep_contact_sets:
            rep_contact_sets[created_by_id].add(cid)
        if brick_id in brick_to_reps:
            for rid in brick_to_reps[brick_id]:
                rep_contact_sets[rid].add(cid)
        if area_id in gov_to_reps:
            for rid in gov_to_reps[area_id]:
                rep_contact_sets[rid].add(cid)
        if brick_parent_id in gov_to_reps:
            for rid in gov_to_reps[brick_parent_id]:
                rep_contact_sets[rid].add(cid)

    return rep_contact_sets


def get_performance_analysis_data(user, start_date, end_date, filters=None):
    """
    Set-based (O(1) query complexity), strictly DataScope-enforced comparative analytics
    across authorized representatives.
    """
    rf = _normalize_legacy_filters(user, start_date, end_date, filters)
    if rf.get('unauthorized_filter'):
        return {
            'rep_summary_table': [],
            'charts': {
                'reps': [], 'coverage': [], 'plan_ach': [], 'coaching': [],
                'working_days': [], 'detailing': [], 'visits_volume': [],
                'total_duration': [], 'avg_duration': [],
            },
        }

    from accounts.models import User
    users_qs = get_scoped_queryset(User.objects.filter(is_active=True), user, 'user')
    reps_qs = users_qs.filter(
        Q(role__is_rep=True)
        | Q(role__is_sales_team=True)
        | Q(role__is_area_manager=True)
        | Q(role__name__in=['rep', 'medical_rep', 'manager'])
    ).prefetch_related('assigned_areas').distinct().order_by('name')

    if rf.get('rep_id'):
        reps_qs = reps_qs.filter(pk=rf['rep_id'])
    if rf.get('area_ids'):
        reps_qs = reps_qs.filter(
            Q(assigned_areas__id__in=rf['area_ids']) | Q(assigned_areas__parent_id__in=rf['area_ids'])
        ).distinct()
    if rf.get('brick_ids'):
        reps_qs = reps_qs.filter(assigned_areas__id__in=rf['brick_ids']).distinct()

    reps_list = list(reps_qs)
    rep_ids = [r.id for r in reps_list]
    if not rep_ids:
        return {
            'rep_summary_table': [],
            'charts': {
                'reps': [], 'coverage': [], 'plan_ach': [], 'coaching': [],
                'working_days': [], 'detailing': [], 'visits_volume': [],
                'total_duration': [], 'avg_duration': [],
            },
        }

    # Strictly scoped querysets (never raw Model.objects!)
    rf_team = dict(rf, rep_id=None, selected_rep=None)
    scoped_contacts_qs, scoped_visits_qs, scoped_unlinked_qs, _ = VisitAnalyticsService.build_scoped_querysets(user, rf_team)
    visits_clean = Visit.objects.filter(id__in=scoped_visits_qs.values('id'), owner_id__in=rep_ids)
    unlinked_clean = PlannedVisitItem.objects.filter(
        id__in=scoped_unlinked_qs.values('id'), plan_day__assignee_id__in=rep_ids
    )

    # Batch 1: Visit aggregates grouped by owner_id (1 SQL query)
    visit_stats = {}
    for row in visits_clean.values('owner_id').annotate(
        planned_completed=Count('id', filter=PLANNED_COMPLETED_Q),
        planned_incomplete=Count('id', filter=PLANNED_INCOMPLETE_Q),
        unplanned_completed=Count('id', filter=UNPLANNED_COMPLETED_Q),
        field_days=Count('date', filter=COMPLETED_VISIT_Q, distinct=True),
        total_duration_sec=Sum('duration', filter=COMPLETED_VISIT_Q),
        double_visits=Count('id', filter=COMPLETED_VISIT_Q & Q(doubled=True)),
    ):
        visit_stats[row['owner_id']] = row

    # Batch 2: Distinct completed visited contact IDs per owner_id (1 SQL query)
    visited_contacts_by_rep = {}
    for row in visits_clean.filter(COMPLETED_VISIT_Q).values_list('owner_id', 'contact_id').distinct():
        visited_contacts_by_rep.setdefault(row[0], set()).add(row[1])

    # Batch 3: Detailing count per owner_id (1 SQL query)
    detailing_by_rep = dict(
        visits_clean.filter(COMPLETED_VISIT_Q, detailed_products__isnull=False)
        .values('owner_id')
        .annotate(cnt=Count('detailed_products'))
        .values_list('owner_id', 'cnt')
    )

    # Batch 4: Unlinked planned incomplete items per assignee_id (1 SQL query)
    unlinked_by_rep = dict(
        unlinked_clean.values('plan_day__assignee_id')
        .annotate(cnt=Count('id'))
        .values_list('plan_day__assignee_id', 'cnt')
    )

    # Batch 5: Scoped SalesOrders, Collections, CoachingEvaluations grouped by rep (3 SQL queries)
    scoped_orders = get_scoped_queryset(
        SalesOrder.objects.filter(
            created_by_id__in=rep_ids, order_date__gte=start_date, order_date__lte=end_date
        ).exclude(status__in=['cancelled', 'rejected']),
        user,
        'salesorder',
    )
    scoped_cols = get_scoped_queryset(
        Collection.objects.filter(
            created_by_id__in=rep_ids, collection_date__gte=start_date, collection_date__lte=end_date
        ),
        user,
        'collection',
    )
    scoped_coaching = get_scoped_queryset(
        CoachingEvaluation.objects.filter(
            rep_id__in=rep_ids, date__gte=start_date, date__lte=end_date
        ),
        user,
        'coachingevaluation',
    )
    if rf.get('area_ids'):
        scoped_orders = scoped_orders.filter(
            Q(customer__area_id__in=rf['area_ids']) | Q(customer__brick__parent_id__in=rf['area_ids'])
        )
        scoped_cols = scoped_cols.filter(
            Q(customer__area_id__in=rf['area_ids']) | Q(customer__brick__parent_id__in=rf['area_ids'])
        )

    sales_by_rep = dict(
        scoped_orders.values('created_by_id').annotate(t=Sum('grand_total')).values_list('created_by_id', 't')
    )
    cols_by_rep = dict(
        scoped_cols.values('created_by_id').annotate(t=Sum('amount')).values_list('created_by_id', 't')
    )
    coaching_by_rep = dict(
        scoped_coaching.values('rep_id').annotate(c=Count('id')).values_list('rep_id', 'c')
    )

    # Batch 6: Eligible contacts per rep strictly within viewer's scoped active contacts (2 SQL queries)
    rep_eligible_sets = _compute_rep_eligible_account_counts(scoped_contacts_qs, reps_list)

    expected_days = calculate_expected_working_days(start_date, end_date)
    calendar_days = max(1, (end_date - start_date).days + 1)

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

    for rep in reps_list:
        vs = visit_stats.get(rep.id, {})
        planned_completed = vs.get('planned_completed') or 0
        planned_incomplete = (vs.get('planned_incomplete') or 0) + unlinked_by_rep.get(rep.id, 0)
        planned_total = planned_completed + planned_incomplete
        unplanned_completed = vs.get('unplanned_completed') or 0
        total_visits = planned_completed + unplanned_completed

        eligible_set = rep_eligible_sets.get(rep.id, set())
        assigned_contacts = len(eligible_set)
        visited_set = visited_contacts_by_rep.get(rep.id, set()) & eligible_set if eligible_set else set()
        visited_contacts = len(visited_set)
        unvisited_contacts = max(0, assigned_contacts - visited_contacts)
        coverage_pct = min(100.0, safe_div(visited_contacts * 100, assigned_contacts, 1))

        frequency = safe_div(total_visits, visited_contacts, 2)
        field_days = vs.get('field_days') or 0
        daily_rate = safe_div(total_visits, field_days, 1)
        calendar_daily_rate = safe_div(total_visits, calendar_days, 1)
        detailing_count = detailing_by_rep.get(rep.id, 0)

        total_duration_sec = vs.get('total_duration_sec') or 0
        total_duration_hours = safe_div(total_duration_sec / 3600.0, 1, 1)
        avg_duration_mins = safe_div(total_duration_sec / 60.0, total_visits, 1)

        sales_val = sales_by_rep.get(rep.id) or Decimal('0.00')
        col_val = cols_by_rep.get(rep.id) or Decimal('0.00')
        coaching_count = coaching_by_rep.get(rep.id, 0)
        double_visits_count = vs.get('double_visits') or 0
        plan_ach_pct = safe_div(planned_completed * 100, planned_total, 1)

        areas_all = list(rep.assigned_areas.all())
        gov_area = next((a for a in areas_all if a.parent_id is None), None)
        area_name_str = gov_area.name if gov_area else (areas_all[0].name if areas_all else 'غير محدد')

        rep_summary_table.append({
            'rep_id': rep.id,
            'name': rep.name or rep.username,
            'code': getattr(rep, 'code', None) or str(rep.id),
            'area_name': area_name_str,
            'assigned_contacts': assigned_contacts,
            'visited_contacts': visited_contacts,
            'unvisited_contacts': unvisited_contacts,
            'coverage_pct': coverage_pct,
            'total_visits': total_visits,
            'planned_visits': planned_completed,
            'planned_incomplete': planned_incomplete,
            'planned_total': planned_total,
            'unplanned_visits': unplanned_completed,
            'frequency': frequency,
            'field_days': field_days,
            'off_field_days': max(0, expected_days - field_days),
            'daily_rate': daily_rate,
            'calendar_daily_rate': calendar_daily_rate,
            'detailing_count': detailing_count,
            'sales_val': float(sales_val),
            'col_val': float(col_val),
            'total_duration_hours': total_duration_hours,
            'avg_duration_mins': avg_duration_mins,
            'coaching_count': coaching_count,
            'double_visits': double_visits_count,
            'plan_ach_pct': plan_ach_pct,
        })

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
        },
    }


def get_performance_daily_data(user, target_date, filters=None):
    """
    Set-based (O(1) query complexity), strictly DataScope-enforced daily performance summary,
    daily rep grid, and 8 daily drilldown tabs using canonical completed-visit rules.
    """
    rf = _normalize_legacy_filters(user, target_date, target_date, filters)
    yesterday = target_date - datetime.timedelta(days=1)

    if rf.get('unauthorized_filter'):
        empty_kpis = {
            'visits': {'today': 0, 'yesterday': 0, 'variance': 0.0},
            'active_reps': {'today': 0, 'yesterday': 0, 'variance': 0.0},
            'orders_val': {'today': 0.0, 'yesterday': 0.0, 'variance': 0.0},
            'collections_val': {'today': 0.0, 'yesterday': 0.0, 'variance': 0.0},
        }
        return {
            'target_date': target_date,
            'yesterday': yesterday,
            'daily_kpis': empty_kpis,
            'daily_rep_grid': [],
            'subtabs': {k: [] for k in ('visits', 'customers', 'calls', 'expenses', 'tasks', 'approvals', 'orders', 'collections')},
        }

    visits_qs = get_scoped_queryset(Visit.objects.all(), user, 'visit')
    orders_qs = get_scoped_queryset(SalesOrder.objects.exclude(status__in=['cancelled', 'rejected']), user, 'salesorder')
    collections_qs = get_scoped_queryset(Collection.objects.all(), user, 'collection')
    expenses_qs = get_scoped_queryset(VisitExpense.objects.all(), user, 'visitexpense')
    calls_qs = get_scoped_queryset(CustomerCall.objects.all(), user, 'customercall')
    contacts_qs = get_scoped_queryset(Contact.objects.filter(ACTIVE_ELIGIBLE_ACCOUNT_Q), user, 'contact')

    if rf.get('rep_id'):
        rid = rf['rep_id']
        visits_qs = visits_qs.filter(owner_id=rid)
        orders_qs = orders_qs.filter(created_by_id=rid)
        collections_qs = collections_qs.filter(created_by_id=rid)
        expenses_qs = expenses_qs.filter(visit__owner_id=rid)
        calls_qs = calls_qs.filter(performed_by_id=rid)
    if rf.get('area_ids'):
        visits_qs = _apply_contact_filters(visits_qs, rf, prefix='contact__')
        contacts_qs = _apply_contact_filters(contacts_qs, rf, prefix='')
        orders_qs = orders_qs.filter(Q(customer__area_id__in=rf['area_ids']) | Q(customer__brick__parent_id__in=rf['area_ids']))
        collections_qs = collections_qs.filter(Q(customer__area_id__in=rf['area_ids']) | Q(customer__brick__parent_id__in=rf['area_ids']))

    # Today vs Yesterday KPIs (qualifying completed visits only!)
    two_day_agg = visits_qs.filter(date__in=[target_date, yesterday]).aggregate(
        today_visits=Count('id', filter=Q(date=target_date) & COMPLETED_VISIT_Q, distinct=True),
        yesterday_visits=Count('id', filter=Q(date=yesterday) & COMPLETED_VISIT_Q, distinct=True),
        today_reps=Count('owner_id', filter=Q(date=target_date) & COMPLETED_VISIT_Q, distinct=True),
        yesterday_reps=Count('owner_id', filter=Q(date=yesterday) & COMPLETED_VISIT_Q, distinct=True),
        today_planned_incomplete=Count('id', filter=Q(date=target_date) & PLANNED_INCOMPLETE_Q, distinct=True),
    )
    today_visits_cnt = two_day_agg['today_visits'] or 0
    yesterday_visits_cnt = two_day_agg['yesterday_visits'] or 0
    today_reps_cnt = two_day_agg['today_reps'] or 0
    yesterday_reps_cnt = two_day_agg['yesterday_reps'] or 0

    orders_agg = orders_qs.filter(order_date__in=[target_date, yesterday]).aggregate(
        today_val=Sum('grand_total', filter=Q(order_date=target_date)),
        yesterday_val=Sum('grand_total', filter=Q(order_date=yesterday)),
    )
    cols_agg = collections_qs.filter(collection_date__in=[target_date, yesterday]).aggregate(
        today_val=Sum('amount', filter=Q(collection_date=target_date)),
        yesterday_val=Sum('amount', filter=Q(collection_date=yesterday)),
    )
    today_orders_val = orders_agg['today_val'] or Decimal('0.00')
    yesterday_orders_val = orders_agg['yesterday_val'] or Decimal('0.00')
    today_col_val = cols_agg['today_val'] or Decimal('0.00')
    yesterday_col_val = cols_agg['yesterday_val'] or Decimal('0.00')

    daily_kpis = {
        'visits': {
            'today': today_visits_cnt,
            'yesterday': yesterday_visits_cnt,
            'variance': calculate_variance(today_visits_cnt, yesterday_visits_cnt),
            'planned_incomplete': two_day_agg['today_planned_incomplete'] or 0,
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

    from accounts.models import User
    reps_qs = get_scoped_queryset(User.objects.filter(is_active=True), user, 'user').filter(
        Q(role__is_rep=True) | Q(role__is_sales_team=True) | Q(role__name__in=['rep', 'medical_rep'])
    ).prefetch_related('assigned_areas').distinct().order_by('name')
    if rf.get('rep_id'):
        reps_qs = reps_qs.filter(pk=rf['rep_id'])
    if rf.get('area_ids'):
        reps_qs = reps_qs.filter(
            Q(assigned_areas__id__in=rf['area_ids']) | Q(assigned_areas__parent_id__in=rf['area_ids'])
        ).distinct()

    reps_list = list(reps_qs)
    rep_ids = [r.id for r in reps_list]

    day_visits_clean = Visit.objects.filter(
        id__in=visits_qs.filter(date=target_date, owner_id__in=rep_ids).values('id')
    )

    # Batch aggregate all per-rep daily metrics in constant queries
    v_day_map = {}
    for row in day_visits_clean.values('owner_id').annotate(
        planned_completed=Count('id', filter=PLANNED_COMPLETED_Q),
        planned_incomplete=Count('id', filter=PLANNED_INCOMPLETE_Q),
        unplanned_completed=Count('id', filter=UNPLANNED_COMPLETED_Q),
        cancelled_cnt=Count('id', filter=Q(status='cancelled')),
        double_cnt=Count('id', filter=COMPLETED_VISIT_Q & Q(doubled=True)),
        total_sec=Sum('duration', filter=COMPLETED_VISIT_Q),
        in_range_cnt=Count('id', filter=COMPLETED_VISIT_Q & Q(requires_approval_due_to_distance=False, location_verified=True)),
        verified_cnt=Count('id', filter=COMPLETED_VISIT_Q & Q(location_verified=True)),
        first_started=Min('started_at', filter=COMPLETED_VISIT_Q | Q(status='started')),
        last_ended=Max('ended_at', filter=COMPLETED_VISIT_Q),
    ):
        v_day_map[row['owner_id']] = row

    det_day_map = dict(
        day_visits_clean.filter(COMPLETED_VISIT_Q, detailed_products__isnull=False)
        .values('owner_id')
        .annotate(c=Count('detailed_products'))
        .values_list('owner_id', 'c')
    )
    orders_day_map = {
        r['created_by_id']: r
        for r in orders_qs.filter(order_date=target_date, created_by_id__in=rep_ids)
        .values('created_by_id')
        .annotate(cnt=Count('id', distinct=True), val=Sum('grand_total'))
    }
    cols_day_map = dict(
        collections_qs.filter(collection_date=target_date, created_by_id__in=rep_ids)
        .values('created_by_id')
        .annotate(val=Sum('amount'))
        .values_list('created_by_id', 'val')
    )
    exp_day_map = dict(
        expenses_qs.filter(visit__date=target_date, visit__owner_id__in=rep_ids, visit__status='finished')
        .exclude(visit__approval_status='disapproved')
        .values('visit__owner_id')
        .annotate(val=Sum('amount'))
        .values_list('visit__owner_id', 'val')
    )

    daily_rep_grid = []
    for rep in reps_list:
        vm = v_day_map.get(rep.id, {})
        p_comp = vm.get('planned_completed') or 0
        p_inc = vm.get('planned_incomplete') or 0
        u_comp = vm.get('unplanned_completed') or 0
        completed_cnt = p_comp + u_comp
        planned_total = p_comp + p_inc

        first_dt = vm.get('first_started')
        last_dt = vm.get('last_ended')
        first_time = timezone.localtime(first_dt).strftime('%H:%M') if first_dt else '–'
        last_time = timezone.localtime(last_dt).strftime('%H:%M') if last_dt else '–'

        total_sec = vm.get('total_sec') or 0
        working_hours = safe_div(total_sec / 3600.0, 1, 1)
        in_range_cnt = vm.get('in_range_cnt') or 0
        verified_cnt = vm.get('verified_cnt') or 0
        in_range_pct = safe_div(in_range_cnt * 100, completed_cnt, 1)
        out_range_pct = safe_div((completed_cnt - in_range_cnt) * 100, completed_cnt, 1) if completed_cnt else 0.0
        verified_pct = safe_div(verified_cnt * 100, completed_cnt, 1)

        o_row = orders_day_map.get(rep.id, {})
        orders_cnt = o_row.get('cnt') or 0
        orders_val = o_row.get('val') or Decimal('0.00')
        cols_val = cols_day_map.get(rep.id) or Decimal('0.00')
        exp_val = exp_day_map.get(rep.id) or Decimal('0.00')

        status_label = 'نشط وميداني' if completed_cnt > 0 else ('مخطط بدون تنفيذ' if p_inc > 0 else 'بدون زيارات')
        status_color = 'emerald' if completed_cnt >= 5 else ('amber' if completed_cnt > 0 else 'slate')
        areas_all = list(rep.assigned_areas.all())
        area_str = areas_all[0].name if areas_all else 'غير محدد'

        daily_rep_grid.append({
            'rep_id': rep.id,
            'name': rep.name or rep.username,
            'area': area_str,
            'first_checkin': first_time,
            'last_checkout': last_time,
            'working_hours': working_hours,
            'planned_visits': planned_total,
            'planned_completed': p_comp,
            'planned_incomplete': p_inc,
            'completed_visits': completed_cnt,
            'unplanned_visits': u_comp,
            'cancelled_visits': vm.get('cancelled_cnt') or 0,
            'double_visits': vm.get('double_cnt') or 0,
            'detailing_count': det_day_map.get(rep.id, 0),
            'in_range_pct': in_range_pct,
            'out_range_pct': out_range_pct,
            'verified_pct': verified_pct,
            'photos_taken': 0,
            'orders_count': orders_cnt,
            'orders_val': float(orders_val),
            'cols_val': float(cols_val),
            'expenses_val': float(exp_val),
            'status': status_label,
            'status_color': status_color,
        })

    scoped_tasks_qs = get_scoped_queryset(
        PlannedVisitItem.objects.filter(plan_day__date=target_date, plan_day__assignee_id__in=rep_ids),
        user,
        'plannedvisititem',
    ).select_related('contact', 'plan_day__assignee')[:100]

    subtabs = {
        'visits': visits_qs.filter(date=target_date).exclude(status='cancelled').select_related('contact', 'owner').order_by('-id')[:100],
        'customers': contacts_qs.filter(visits__date=target_date, visits__status='finished').exclude(visits__approval_status='disapproved').distinct()[:100],
        'calls': calls_qs.filter(call_date=target_date).select_related('contact', 'performed_by')[:100],
        'expenses': expenses_qs.filter(visit__date=target_date).select_related('visit', 'visit__owner')[:100],
        'tasks': scoped_tasks_qs,
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
    Set-based (O(1) query complexity), strictly DataScope-enforced performance matrix
    using dynamically configured `AccountTypeReportGroup` columns (zero hardcoded types).
    """
    rf = _normalize_legacy_filters(user, start_date, end_date, filters)
    active_groups = rf.get('active_groups') or SettingsService.get_account_type_report_groups(active_only=True)

    group_columns = [
        {'id': g.id, 'code': g.code, 'name': g.name, 'icon': g.icon or 'category', 'is_unclassified': False}
        for g in active_groups
    ]
    type_to_code = {}
    for g in active_groups:
        for t in (g.account_types or []):
            low = str(t).strip().lower()
            if low and low not in type_to_code:
                type_to_code[low] = g.code

    if rf.get('unauthorized_filter'):
        return {
            'matrix_rows': [],
            'group_columns': group_columns,
            'has_unclassified': False,
            'coaching_logs': [],
        }

    from accounts.models import User
    reps_qs = get_scoped_queryset(User.objects.filter(is_active=True), user, 'user').filter(
        Q(role__is_rep=True) | Q(role__is_sales_team=True) | Q(role__name__in=['rep', 'medical_rep'])
    ).prefetch_related('assigned_areas').distinct().order_by('name')

    if rf.get('rep_id'):
        reps_qs = reps_qs.filter(pk=rf['rep_id'])
    if rf.get('area_ids'):
        reps_qs = reps_qs.filter(
            Q(assigned_areas__id__in=rf['area_ids']) | Q(assigned_areas__parent_id__in=rf['area_ids'])
        ).distinct()
    if rf.get('brick_ids'):
        reps_qs = reps_qs.filter(assigned_areas__id__in=rf['brick_ids']).distinct()

    reps_list = list(reps_qs)
    rep_ids = [r.id for r in reps_list]
    if not rep_ids:
        coaching_logs = get_scoped_queryset(
            CoachingEvaluation.objects.filter(date__gte=start_date, date__lte=end_date).select_related('rep', 'manager', 'customer'),
            user,
            'coachingevaluation',
        ).order_by('-date')[:50]
        return {
            'matrix_rows': [],
            'group_columns': group_columns,
            'has_unclassified': False,
            'coaching_logs': coaching_logs,
        }

    rf_team = dict(rf, rep_id=None, selected_rep=None)
    scoped_contacts_qs, scoped_visits_qs, scoped_unlinked_qs, _ = VisitAnalyticsService.build_scoped_querysets(user, rf_team)
    visits_clean = Visit.objects.filter(id__in=scoped_visits_qs.values('id'), owner_id__in=rep_ids)
    unlinked_clean = PlannedVisitItem.objects.filter(
        id__in=scoped_unlinked_qs.values('id'), plan_day__assignee_id__in=rep_ids
    )

    # Batch 1: Core visit stats per rep (1 query)
    v_rep_map = {
        r['owner_id']: r
        for r in visits_clean.values('owner_id').annotate(
            planned_completed=Count('id', filter=PLANNED_COMPLETED_Q),
            planned_incomplete=Count('id', filter=PLANNED_INCOMPLETE_Q),
            unplanned_completed=Count('id', filter=UNPLANNED_COMPLETED_Q),
            am_visits=Count('id', filter=COMPLETED_VISIT_Q & Q(contact__visit_timing='AM')),
            pm_visits=Count('id', filter=COMPLETED_VISIT_Q & Q(contact__visit_timing='PM')),
            total_sec=Sum('duration', filter=COMPLETED_VISIT_Q),
            in_range_cnt=Count('id', filter=COMPLETED_VISIT_Q & Q(requires_approval_due_to_distance=False, location_verified=True)),
            bypassed_cnt=Count('id', filter=COMPLETED_VISIT_Q & Q(bypassed_by__isnull=False)),
        )
    }

    # Batch 2: Unlinked planned items per rep (1 query)
    unlinked_rep_map = dict(
        unlinked_clean.values('plan_day__assignee_id').annotate(c=Count('id')).values_list('plan_day__assignee_id', 'c')
    )

    # Batch 3: Visits per (owner_id, contact__account_type) for dynamic group breakdowns (1 query)
    rep_group_visits = {rid: {} for rid in rep_ids}
    any_unclassified = False
    for row in visits_clean.values('owner_id', 'contact__account_type').annotate(
        p_comp=Count('id', filter=PLANNED_COMPLETED_Q),
        p_inc=Count('id', filter=PLANNED_INCOMPLETE_Q),
        u_comp=Count('id', filter=UNPLANNED_COMPLETED_Q),
    ):
        rid = row['owner_id']
        low = (row['contact__account_type'] or '').strip().lower()
        code = type_to_code.get(low, UNCLASSIFIED_GROUP_CODE)
        if code == UNCLASSIFIED_GROUP_CODE and ((row['p_comp'] or 0) + (row['p_inc'] or 0) + (row['u_comp'] or 0)) > 0:
            any_unclassified = True
        slot = rep_group_visits[rid].setdefault(code, {'completed': 0, 'planned_completed': 0, 'planned_incomplete': 0, 'unplanned': 0})
        slot['planned_completed'] += row['p_comp'] or 0
        slot['planned_incomplete'] += row['p_inc'] or 0
        slot['unplanned'] += row['u_comp'] or 0
        slot['completed'] += (row['p_comp'] or 0) + (row['u_comp'] or 0)

    # Batch 4: Eligible accounts per rep + their account_type & category (3 queries)
    rep_eligible_sets = _compute_rep_eligible_account_counts(scoped_contacts_qs, reps_list)
    contact_meta = {
        cid: ((at or '').strip().lower(), (cat or '').strip())
        for cid, at, cat in scoped_contacts_qs.filter(ACTIVE_ELIGIBLE_ACCOUNT_Q).values_list('id', 'account_type', 'customer_category')
    }
    visited_by_rep = {}
    for oid, cid in visits_clean.filter(COMPLETED_VISIT_Q).values_list('owner_id', 'contact_id').distinct():
        visited_by_rep.setdefault(oid, set()).add(cid)

    # Batch 5: Detailing, Samples, Sales, Collections (4 queries)
    det_map = dict(
        visits_clean.filter(COMPLETED_VISIT_Q, detailed_products__isnull=False)
        .values('owner_id').annotate(c=Count('detailed_products')).values_list('owner_id', 'c')
    )
    samples_map = dict(
        VisitSampleItem.objects.filter(visit__in=visits_clean.filter(COMPLETED_VISIT_Q))
        .values('visit__owner_id').annotate(s=Sum('quantity')).values_list('visit__owner_id', 's')
    )
    scoped_orders = get_scoped_queryset(
        SalesOrder.objects.filter(
            created_by_id__in=rep_ids, order_date__gte=start_date, order_date__lte=end_date
        ).exclude(status__in=['cancelled', 'rejected']),
        user,
        'salesorder',
    )
    scoped_cols = get_scoped_queryset(
        Collection.objects.filter(
            created_by_id__in=rep_ids, collection_date__gte=start_date, collection_date__lte=end_date
        ),
        user,
        'collection',
    )
    if rf.get('area_ids'):
        scoped_orders = scoped_orders.filter(
            Q(customer__area_id__in=rf['area_ids']) | Q(customer__brick__parent_id__in=rf['area_ids'])
        )
        scoped_cols = scoped_cols.filter(
            Q(customer__area_id__in=rf['area_ids']) | Q(customer__brick__parent_id__in=rf['area_ids'])
        )

    sales_map = {
        r['created_by_id']: r
        for r in scoped_orders.values('created_by_id').annotate(
            cnt=Count('id', distinct=True), gross=Sum('subtotal'), net=Sum('grand_total')
        )
    }
    cols_map = {
        r['created_by_id']: r
        for r in scoped_cols.values('created_by_id').annotate(
            cnt=Count('id', distinct=True), net=Sum('amount')
        )
    }

    # Check if any eligible account is unclassified
    for rid in rep_ids:
        for cid in rep_eligible_sets.get(rid, set()):
            at_low, _ = contact_meta.get(cid, ('', ''))
            if at_low not in type_to_code:
                any_unclassified = True
                break
        if any_unclassified:
            break

    if any_unclassified:
        group_columns.append({
            'id': None,
            'code': UNCLASSIFIED_GROUP_CODE,
            'name': UNCLASSIFIED_GROUP_NAME,
            'icon': 'more_horiz',
            'is_unclassified': True,
        })

    matrix_rows = []
    for rep in reps_list:
        vm = v_rep_map.get(rep.id, {})
        p_comp = vm.get('planned_completed') or 0
        p_inc = (vm.get('planned_incomplete') or 0) + unlinked_rep_map.get(rep.id, 0)
        u_comp = vm.get('unplanned_completed') or 0
        total_visits = p_comp + u_comp

        eligible_set = rep_eligible_sets.get(rep.id, set())
        visited_set = visited_by_rep.get(rep.id, set()) & eligible_set

        # Group account counts & class A/B/C coverage
        group_acc_counts = {}
        cls_totals = {'A': 0, 'B': 0, 'C': 0}
        cls_visited = {'A': 0, 'B': 0, 'C': 0}
        for cid in eligible_set:
            at_low, cat = contact_meta.get(cid, ('', ''))
            g_code = type_to_code.get(at_low, UNCLASSIFIED_GROUP_CODE)
            group_acc_counts[g_code] = group_acc_counts.get(g_code, 0) + 1
            if cat in cls_totals:
                cls_totals[cat] += 1
                if cid in visited_set:
                    cls_visited[cat] += 1

        group_cells = []
        for gc in group_columns:
            code = gc['code']
            gv = rep_group_visits.get(rep.id, {}).get(code, {})
            group_cells.append({
                'code': code,
                'name': gc['name'],
                'accounts': group_acc_counts.get(code, 0),
                'completed_visits': gv.get('completed', 0),
                'planned_completed': gv.get('planned_completed', 0),
                'planned_incomplete': gv.get('planned_incomplete', 0),
                'unplanned': gv.get('unplanned', 0),
            })

        am_visits = vm.get('am_visits') or 0
        pm_visits = vm.get('pm_visits') or 0
        na_visits = max(0, total_visits - (am_visits + pm_visits))
        total_sec = vm.get('total_sec') or 0
        avg_dur_mins = safe_div(total_sec / 60.0, total_visits, 1)
        in_range_cnt = vm.get('in_range_cnt') or 0
        out_range_cnt = max(0, total_visits - in_range_cnt)
        bypassed_cnt = vm.get('bypassed_cnt') or 0

        s_row = sales_map.get(rep.id, {})
        c_row = cols_map.get(rep.id, {})
        areas_all = list(rep.assigned_areas.all())
        gov_area = next((a for a in areas_all if a.parent_id is None), None)
        area_name = gov_area.name if gov_area else (areas_all[0].name if areas_all else 'غير محدد')

        matrix_rows.append({
            'rep_id': rep.id,
            'name': rep.name or rep.username,
            'code': getattr(rep, 'code', None) or str(rep.id),
            'area': area_name,
            'group_cells': group_cells,
            'eligible_accounts': len(eligible_set),
            'visited_accounts': len(visited_set),
            'unvisited_accounts': max(0, len(eligible_set) - len(visited_set)),
            'class_a_cov': safe_div(cls_visited['A'] * 100, cls_totals['A'], 1),
            'class_b_cov': safe_div(cls_visited['B'] * 100, cls_totals['B'], 1),
            'class_c_cov': safe_div(cls_visited['C'] * 100, cls_totals['C'], 1),
            'total_visits': total_visits,
            'planned_visits': p_comp,
            'planned_incomplete': p_inc,
            'planned_total': p_comp + p_inc,
            'unplanned_visits': u_comp,
            'am_visits': am_visits,
            'pm_visits': pm_visits,
            'na_visits': na_visits,
            'avg_duration': avg_dur_mins,
            'in_range_cnt': in_range_cnt,
            'out_range_cnt': out_range_cnt,
            'bypassed_cnt': bypassed_cnt,
            'detailing_cnt': det_map.get(rep.id, 0),
            'samples_cnt': samples_map.get(rep.id, 0),
            'sales_cnt': s_row.get('cnt') or 0,
            'sales_gross': float(s_row.get('gross') or Decimal('0.00')),
            'sales_net': float(s_row.get('net') or Decimal('0.00')),
            'cols_cnt': c_row.get('cnt') or 0,
            'cols_net': float(c_row.get('net') or Decimal('0.00')),
        })

    coaching_logs = get_scoped_queryset(
        CoachingEvaluation.objects.filter(
            date__gte=start_date, date__lte=end_date
        ).select_related('rep', 'manager', 'customer'),
        user,
        'coachingevaluation',
    ).order_by('-date')[:50]

    return {
        'matrix_rows': matrix_rows,
        'group_columns': group_columns,
        'has_unclassified': any_unclassified,
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
        accounts_qs = accounts_qs.filter(Q(customer__assigned_team__id=rep_id) | Q(customer__created_by_id=rep_id)).distinct()
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

    # Total credit sales in last 90 days for DSO (strictly scoped)
    ninety_days_ago = today - datetime.timedelta(days=90)
    dso_orders = get_scoped_queryset(
        SalesOrder.objects.filter(order_date__gte=ninety_days_ago).exclude(status__in=['cancelled', 'rejected']),
        user,
    )
    if area_id:
        dso_orders = dso_orders.filter(customer__area_id=area_id)
    if brick_id:
        dso_orders = dso_orders.filter(customer__brick_id=brick_id)
    if rep_id:
        dso_orders = dso_orders.filter(Q(customer__assigned_team__id=rep_id) | Q(customer__created_by_id=rep_id))
    total_sales_90d = dso_orders.aggregate(t=Sum('grand_total'))['t'] or Decimal('0.00')

    accounts_list = list(accounts_qs[:500])
    acc_ids = [a.id for a in accounts_list]
    from sales.models import CustomerTransaction
    txs_by_acc = {}
    if acc_ids:
        for tx in CustomerTransaction.objects.filter(
            account_id__in=acc_ids, transaction_type='debit'
        ).order_by('-transaction_date', '-id'):
            txs_by_acc.setdefault(tx.account_id, []).append(tx)

    for acc in accounts_list:
        c = acc.customer
        balance = acc.current_balance
        overdue = acc.overdue_balance

        # FIFO remaining balance allocation across newest-to-oldest debit invoices
        remaining = balance
        b_1_30 = Decimal('0.00')
        b_31_60 = Decimal('0.00')
        b_61_90 = Decimal('0.00')
        b_91_120 = Decimal('0.00')
        b_over_120 = Decimal('0.00')

        for tx in txs_by_acc.get(acc.id, []):
            if remaining <= 0:
                break
            unpaid_part = min(remaining, tx.debit or Decimal('0.00'))
            remaining -= unpaid_part
            if tx.due_date and tx.due_date < today:
                days = (today - tx.due_date).days
                if days <= 30:
                    b_1_30 += unpaid_part
                elif days <= 60:
                    b_31_60 += unpaid_part
                elif days <= 90:
                    b_61_90 += unpaid_part
                elif days <= 120:
                    b_91_120 += unpaid_part
                else:
                    b_over_120 += unpaid_part

        # Fallback if overdue exists without due_date transactions
        if overdue > 0 and (b_1_30 + b_31_60 + b_61_90 + b_91_120 + b_over_120) == 0:
            b_1_30 = min(overdue, balance)

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

    accounts_qs = get_scoped_queryset(CustomerAccount.objects.select_related('customer', 'customer__area', 'customer__brick'), user, 'customeraccount')
    if area_id:
        try:
            aid = int(area_id)
            accounts_qs = accounts_qs.filter(Q(customer__area_id=aid) | Q(customer__brick__parent_id=aid))
        except (TypeError, ValueError):
            pass
    if brick_id:
        try:
            bid = int(brick_id)
            accounts_qs = accounts_qs.filter(customer__brick_id=bid)
        except (TypeError, ValueError):
            pass

    rows = []
    tot_opening = Decimal('0.00')
    tot_debit = Decimal('0.00')
    tot_credit = Decimal('0.00')
    tot_closing = Decimal('0.00')

    accounts_list = list(accounts_qs[:500])
    acc_ids = [a.id for a in accounts_list]
    from sales.models import CustomerTransaction

    prior_map = {}
    curr_map = {}
    if acc_ids:
        for r in CustomerTransaction.objects.filter(
            account_id__in=acc_ids, transaction_date__lt=start_date
        ).values('account_id').annotate(deb=Sum('debit'), cr=Sum('credit')):
            prior_map[r['account_id']] = (r['deb'] or Decimal('0.00'), r['cr'] or Decimal('0.00'))
        for r in CustomerTransaction.objects.filter(
            account_id__in=acc_ids, transaction_date__gte=start_date, transaction_date__lte=end_date
        ).values('account_id').annotate(deb=Sum('debit'), cr=Sum('credit')):
            curr_map[r['account_id']] = (r['deb'] or Decimal('0.00'), r['cr'] or Decimal('0.00'))

    for acc in accounts_list:
        c = acc.customer
        opening_deb, opening_cr = prior_map.get(acc.id, (Decimal('0.00'), Decimal('0.00')))
        opening_bal = opening_deb - opening_cr
        curr_deb, curr_cr = curr_map.get(acc.id, (Decimal('0.00'), Decimal('0.00')))
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
    Only approved or completed agreements commit financial budget and participate in ROI calculations.
    """
    filters = filters or {}
    agreements_qs = get_scoped_queryset(
        Agreement.objects.select_related('customer', 'type', 'created_by'), user
    ).filter(date__gte=start_date, date__lte=end_date)

    if filters.get('status'):
        agreements_qs = agreements_qs.filter(status=filters['status'])
    else:
        agreements_qs = agreements_qs.filter(status__in=['approved', 'done'])

    rows = []
    tot_budget = Decimal('0.00')
    tot_actual_sales = Decimal('0.00')

    agreements_list = list(agreements_qs)
    agr_customer_ids = list({a.customer_id for a in agreements_list if a.customer_id})

    # Batch fetch relevant delivered/invoiced sales orders in 1 query (eliminates N+1 per agreement)
    orders_by_customer = {}
    if agr_customer_ids:
        min_agr_date = min(a.date for a in agreements_list if a.date)
        scoped_orders_base = get_scoped_queryset(
            SalesOrder.objects.filter(
                customer_id__in=agr_customer_ids,
                status__in=['delivered', 'invoiced'],
                order_date__gte=min_agr_date,
                order_date__lte=end_date,
            ),
            user,
            'salesorder',
        )
        for cid, o_date, g_total in scoped_orders_base.values_list('customer_id', 'order_date', 'grand_total'):
            orders_by_customer.setdefault(cid, []).append((o_date, g_total or Decimal('0.00')))

    for agr in agreements_list:
        actual_sales = sum(
            (gt for od, gt in orders_by_customer.get(agr.customer_id, []) if od >= agr.date),
            Decimal('0.00'),
        )
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


def get_customer_360_report_data(user, start_date, end_date, filters=None):
    """
    Report 5: Customer 360 Summary (ملخص العملاء 360).
    Exhaustive 22-column view merging visits, orders, discounts, returns, collections, and debts.
    """
    filters = filters or {}
    area_id = filters.get('area_id')
    brick_id = filters.get('brick_id')

    contacts_qs = get_scoped_queryset(
        Contact.objects.filter(ACTIVE_ELIGIBLE_ACCOUNT_Q).select_related('area', 'brick'), user, 'contact'
    )
    if area_id:
        try:
            aid = int(area_id)
            contacts_qs = contacts_qs.filter(Q(area_id=aid) | Q(brick__parent_id=aid))
        except (TypeError, ValueError):
            pass
    if brick_id:
        try:
            bid = int(brick_id)
            contacts_qs = contacts_qs.filter(brick_id=bid)
        except (TypeError, ValueError):
            pass

    rows = []
    tot_net_sales = Decimal('0.00')
    tot_collections = Decimal('0.00')
    tot_debt = Decimal('0.00')

    contacts_list = list(contacts_qs.select_related('customer_account', 'created_by').prefetch_related('assigned_team')[:300])
    contact_ids = [c.id for c in contacts_list]

    visits_map = {}
    last_visit_map = {}
    orders_map = {}
    returns_map = {}
    collections_map = {}

    if contact_ids:
        scoped_visits = get_scoped_queryset(
            Visit.objects.filter(contact_id__in=contact_ids).filter(COMPLETED_VISIT_Q),
            user,
            'visit',
        )
        scoped_orders = get_scoped_queryset(SalesOrder.objects.filter(customer_id__in=contact_ids), user, 'salesorder')
        scoped_returns = get_scoped_queryset(SalesReturnOrder.objects.filter(customer_id__in=contact_ids), user, 'salesreturnorder')
        scoped_collections = get_scoped_queryset(Collection.objects.filter(customer_id__in=contact_ids), user, 'collection')

        for r in scoped_visits.filter(
            date__gte=start_date, date__lte=end_date
        ).values('contact_id').annotate(cnt=Count('id')):
            visits_map[r['contact_id']] = r['cnt']
        for r in scoped_visits.values('contact_id').annotate(last_d=Max('date')):
            last_visit_map[r['contact_id']] = r['last_d']
        for r in scoped_orders.filter(
            order_date__gte=start_date, order_date__lte=end_date
        ).exclude(status__in=['cancelled', 'rejected']).values('customer_id').annotate(
            cnt=Count('id'),
            gross=Sum('subtotal'),
            i_disc=Sum('items_discount_total'),
            c_disc=Sum('custom_discount_amount'),
            net=Sum('grand_total'),
        ):
            orders_map[r['customer_id']] = r
        for r in scoped_returns.filter(
            order_date__gte=start_date, order_date__lte=end_date, status__in=['delivered', 'settled']
        ).values('customer_id').annotate(ret=Sum('grand_total')):
            returns_map[r['customer_id']] = r['ret'] or Decimal('0.00')
        for r in scoped_collections.filter(
            collection_date__gte=start_date, collection_date__lte=end_date
        ).values('customer_id').annotate(col=Sum('amount')):
            collections_map[r['customer_id']] = r['col'] or Decimal('0.00')

    for c in contacts_list:
        acc = getattr(c, 'customer_account', None)
        balance = acc.current_balance if acc else Decimal('0.00')
        overdue = acc.overdue_balance if acc else Decimal('0.00')
        c_limit = acc.credit_limit if acc else c.credit_limit

        visits_cnt = visits_map.get(c.id, 0)
        last_v_date = last_visit_map.get(c.id)

        o_data = orders_map.get(c.id, {})
        orders_cnt = o_data.get('cnt', 0)
        gross_sales = o_data.get('gross') or Decimal('0.00')
        item_disc = o_data.get('i_disc') or Decimal('0.00')
        custom_disc = o_data.get('c_disc') or Decimal('0.00')
        net_sales = o_data.get('net') or Decimal('0.00')

        ret_total = returns_map.get(c.id, Decimal('0.00'))
        col_total = collections_map.get(c.id, Decimal('0.00'))

        team_all = list(c.assigned_team.all())
        rep = team_all[0] if team_all else c.created_by
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


def get_delivery_stock_availability_report_data(user, filters=None):
    """
    Report 8: Delivery Status & Stock Availability (متابعة التسليمات وتوفر المخزون).
    Matches open unreserved sales orders (pending / manager_approval) with available warehouse stock,
    without double-counting 'preparing' orders already reflected in qty_reserved.
    """
    filters = filters or {}
    warehouse_id = filters.get('warehouse_id')

    open_qs = get_scoped_queryset(
        SalesOrderItem.objects.filter(
            order__status__in=['pending', 'manager_approval', 'preparing']
        ),
        user,
        'salesorderitem'
    )
    if warehouse_id and str(warehouse_id).isdigit():
        open_qs = open_qs.filter(order__source_warehouse_id=int(warehouse_id))

    # Separate unreserved demand (pending, manager_approval) from preparing (already in qty_reserved)
    open_items = list(
        open_qs.values('product_id', 'product__name', 'product__sku_code').annotate(
            unreserved_qty=Sum('quantity', filter=Q(order__status__in=['pending', 'manager_approval'])),
            preparing_qty=Sum('quantity', filter=Q(order__status='preparing')),
            orders_count=Count('order_id', distinct=True)
        )
    )

    scoped_stocks = get_scoped_queryset(InventoryStock.objects.all(), user, 'inventorystock')
    if warehouse_id:
        scoped_stocks = scoped_stocks.filter(warehouse_id=warehouse_id)

    prod_ids = [it['product_id'] for it in open_items]
    stock_map = {}
    if prod_ids:
        for s in scoped_stocks.filter(product_id__in=prod_ids).values('product_id').annotate(
            on_hand=Sum('qty_on_hand'),
            reserved=Sum('qty_reserved'),
        ):
            stock_map[s['product_id']] = (
                s['on_hand'] or Decimal('0.00'),
                s['reserved'] or Decimal('0.00'),
            )

    rows = []
    stockout_cnt = 0
    for item in open_items:
        prod_id = item['product_id']
        on_hand, reserved = stock_map.get(prod_id, (Decimal('0.00'), Decimal('0.00')))
        available = max(Decimal('0.00'), on_hand - reserved)
        unreserved_needed = item['unreserved_qty'] or Decimal('0.00')
        preparing_qty = item['preparing_qty'] or Decimal('0.00')
        # Only count preparing shortfall if reserved stock doesn't cover it
        extra_preparing = max(Decimal('0.00'), preparing_qty - reserved)
        needed = unreserved_needed + extra_preparing

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
            'ordered_qty': float(unreserved_needed + preparing_qty),
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
    Batched queries including return-only products and default_purchase_cost fallback.
    """
    sold_qs = get_scoped_queryset(
        SalesOrderItem.objects.filter(
            order__order_date__gte=start_date,
            order__order_date__lte=end_date,
            order__status__in=['delivered', 'invoiced']
        ),
        user,
        'salesorderitem'
    ).values(
        'product_id', 'product__name', 'product__sku_code', 'product__retail_price', 'product__default_purchase_cost'
    ).annotate(
        del_qty=Sum('quantity'),
        del_subtotal=Sum('subtotal'),
        del_disc=Sum('discount_amount'),
    )
    sold_map = {r['product_id']: r for r in sold_qs}

    ret_qs = get_scoped_queryset(
        SalesReturnOrderItem.objects.filter(
            order__order_date__gte=start_date,
            order__order_date__lte=end_date,
            order__status__in=['delivered', 'settled']
        ),
        user,
        'salesreturnorderitem'
    ).values(
        'product_id', 'product__name', 'product__sku_code', 'product__retail_price', 'product__default_purchase_cost'
    ).annotate(
        qty=Sum('quantity'),
        total=Sum('total'),
    )
    ret_map = {r['product_id']: r for r in ret_qs}

    all_prod_ids = list(set(sold_map.keys()) | set(ret_map.keys()))
    cost_map = {}
    if all_prod_ids:
        scoped_stocks = get_scoped_queryset(InventoryStock.objects.all(), user, 'inventorystock')
        for s in scoped_stocks.filter(product_id__in=all_prod_ids).values('product_id').annotate(c=Avg('product_cost')):
            if s['c'] is not None:
                cost_map[s['product_id']] = s['c']

    rows = []
    tot_gross = Decimal('0.00')
    tot_net = Decimal('0.00')
    tot_cogs = Decimal('0.00')
    tot_profit = Decimal('0.00')

    for prod_id in all_prod_ids:
        p = sold_map.get(prod_id)
        r = ret_map.get(prod_id)
        meta = p or r

        del_q = (p['del_qty'] or Decimal('0.00')) if p else Decimal('0.00')
        del_sub = (p['del_subtotal'] or Decimal('0.00')) if p else Decimal('0.00')
        del_d = (p['del_disc'] or Decimal('0.00')) if p else Decimal('0.00')
        net_del = max(Decimal('0.00'), del_sub - del_d)

        ret_q = (r['qty'] or Decimal('0.00')) if r else Decimal('0.00')
        ret_val = (r['total'] or Decimal('0.00')) if r else Decimal('0.00')

        final_qty = del_q - ret_q
        final_sales_val = net_del - ret_val

        avg_cost = cost_map.get(prod_id) or Decimal(str(meta['product__default_purchase_cost'] or '0.00'))
        cogs = (final_qty * avg_cost).quantize(Decimal('0.01'))
        gross_profit = final_sales_val - cogs
        margin_pct = safe_div(float(gross_profit) * 100, float(final_sales_val), 1) if final_sales_val > 0 else 0.0

        tot_gross += del_sub
        tot_net += final_sales_val
        tot_cogs += cogs
        tot_profit += gross_profit

        rows.append({
            'code': meta['product__sku_code'],
            'name': meta['product__name'],
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
            'retail_price': float(meta['product__retail_price'] or 0),
        })

    rows.sort(key=lambda x: x['net_sales'], reverse=True)
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
    Deducts delivered/settled purchase returns and batches stock queries.
    """
    from purchases.models import PurchaseReturnOrderItem

    p_items = list(
        get_scoped_queryset(
            PurchaseOrderItem.objects.filter(
                order__order_date__gte=start_date,
                order__order_date__lte=end_date,
                order__status__in=['approved', 'picked', 'settled']
            ),
            user,
            'purchaseorderitem'
        ).values(
            'product_id', 'product__name', 'product__sku_code', 'order__supplier_id', 'order__supplier__name'
        ).annotate(
            qty=Sum('quantity'),
            spend=Sum('total_price')
        )
    )

    pr_map = {}
    for pr in get_scoped_queryset(
        PurchaseReturnOrderItem.objects.filter(
            return_order__order_date__gte=start_date,
            return_order__order_date__lte=end_date,
            return_order__status__in=['delivered', 'settled']
        ),
        user,
        'purchasereturnorderitem'
    ).values('product_id', 'return_order__supplier_id').annotate(
        ret_qty=Sum('quantity'),
        ret_val=Sum('total_price')
    ):
        pr_map[(pr['product_id'], pr['return_order__supplier_id'])] = (
            pr['ret_qty'] or Decimal('0.00'),
            pr['ret_val'] or Decimal('0.00'),
        )

    prod_ids = [pi['product_id'] for pi in p_items]
    stock_map = {}
    if prod_ids:
        scoped_stocks = get_scoped_queryset(InventoryStock.objects.all(), user, 'inventorystock')
        for s in scoped_stocks.filter(product_id__in=prod_ids).values('product_id').annotate(t=Sum('qty_on_hand')):
            stock_map[s['product_id']] = s['t'] or Decimal('0.00')

    rows = []
    tot_spend = Decimal('0.00')
    for pi in p_items:
        prod_id = pi['product_id']
        sup_id = pi['order__supplier_id']
        ret_q, ret_v = pr_map.get((prod_id, sup_id), (Decimal('0.00'), Decimal('0.00')))
        qty = max(Decimal('0.00'), (pi['qty'] or Decimal('0.00')) - ret_q)
        spend = max(Decimal('0.00'), (pi['spend'] or Decimal('0.00')) - ret_v)
        avg_price = safe_div(float(spend), float(qty), 2) if qty > 0 else 0.0
        on_hand = stock_map.get(prod_id, Decimal('0.00'))

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
    Computes summary totals across all matching rows before applying display slice.
    """
    base_qs = get_scoped_queryset(
        SalesOrderItem.objects.filter(
            order__order_date__gte=start_date,
            order__order_date__lte=end_date,
            order__status__in=['delivered', 'invoiced']
        ),
        user,
        'salesorderitem'
    )
    agg_totals = base_qs.aggregate(
        total_sub=Sum('subtotal'),
        total_disc=Sum('discount_amount'),
    )
    full_tot_val = (agg_totals['total_sub'] or Decimal('0.00')) - (agg_totals['total_disc'] or Decimal('0.00'))

    grouped_qs = base_qs.values(
        'product__sku_code', 'product__name', 'order__customer__name', 'order__customer__area__name'
    ).annotate(
        qty=Sum('quantity'),
        net_val=Sum('subtotal') - Sum('discount_amount')
    ).order_by('product__name')

    total_count = grouped_qs.count()
    rows = []
    for item in grouped_qs[:300]:
        val = item['net_val'] or Decimal('0.00')
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
            'total_amount': float(full_tot_val),
            'count': total_count,
        }
    }


def export_to_excel_response(filename, sheet_title, headers, rows, summary_row=None):
    """Export report tabular data to an RTL-formatted XLSX download response."""
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = (sheet_title or "Report")[:31]
    ws.views.sheetView[0].rightToLeft = True

    header_fill = PatternFill(start_color="0F172A", end_color="0F172A", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF")
    ws.append(list(headers))
    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")

    from master_data.excel_utils import sanitize_excel_cell
    for r in rows:
        cleaned = [
            v.strftime("%Y-%m-%d") if isinstance(v, (datetime.date, datetime.datetime))
            else (sanitize_excel_cell(v) if isinstance(v, str) else v)
            for v in r
        ]
        ws.append(cleaned)

    if summary_row:
        ws.append(list(summary_row))
        for cell in ws[ws.max_row]:
            cell.font = Font(bold=True)

    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}.xlsx"'
    wb.save(response)
    return response
