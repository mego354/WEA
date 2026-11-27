"""
Centralized Visit & Field Performance Analytics Engine for WEA Pharma ERP.

Single source of truth for:
- Confirmed business rules (qualifying completed visits, planned/unplanned splits,
  working days, average visits/day, eligible/visited/unvisited accounts, dynamic
  configurable AccountTypeReportGroup rollups, continuous daily activity series).
- Strict RBAC/ABAC DataScope enforcement via `ScopeResolutionService` and
  `get_scoped_queryset` (zero unscoped queries, zero cross-area leaks, zero IDOR).
- Set-based SQL aggregations eliminating per-representative N+1 query loops.
"""

import calendar
import datetime
from collections import defaultdict
from decimal import Decimal

from django.db.models import (
    Count,
    Exists,
    IntegerField,
    Max,
    Min,
    OuterRef,
    Q,
    Subquery,
    Sum,
    Value,
)
from django.db.models.functions import Coalesce
from django.utils import timezone

from accounts.models import User
from accounts.permissions import (
    get_scoped_queryset,
    get_visible_assignees_queryset,
)
from accounts.scope_service import ScopeResolutionService
from activities.models import PlannedVisitItem, Visit
from contacts.models import Contact
from master_data.date_filter_utils import (
    PRESET_LABELS_AR,
    resolve_date_range,
)
from master_data.filter_utils import (
    parse_multi_int,
    parse_multi_str,
    parse_single_int,
)
from master_data.models import AccountTypeReportGroup, Area
from master_data.services import SettingsService


# ==============================================================================
# CANONICAL CONFIRMED BUSINESS-RULE PREDICATES
# ==============================================================================

# 2.1 Qualifying Completed Visit: status='finished' and approval_status != 'disapproved'
COMPLETED_VISIT_Q = Q(status='finished') & ~Q(approval_status='disapproved')

# 2.2 Planned Visits
PLANNED_COMPLETED_Q = Q(is_planned=True, status='finished') & ~Q(approval_status='disapproved')
PLANNED_INCOMPLETE_Q = Q(is_planned=True, status__in=['planned', 'started']) & ~Q(approval_status='disapproved')

# 2.3 Unplanned Visits
UNPLANNED_COMPLETED_Q = Q(is_planned=False, status='finished') & ~Q(approval_status='disapproved')
UNPLANNED_IN_PROGRESS_Q = Q(is_planned=False, status='started') & ~Q(approval_status='disapproved')

# Legacy unlinked PlannedVisitItem (prevents double-counting items already linked to a Visit)
UNLINKED_PLANNED_ITEM_Q = (
    Q(visit__isnull=True, is_executed=False)
    & (Q(plan__isnull=True) | ~Q(plan__approval_status='disapproved'))
)

# 2.8 Eligible Accounts: active customers & leads (excluding inactive)
ACTIVE_ELIGIBLE_ACCOUNT_Q = Q(is_customer=True) & ~Q(status='inactive')

ARABIC_WEEKDAYS = ['الاثنين', 'الثلاثاء', 'الأربعاء', 'الخميس', 'الجمعة', 'السبت', 'الأحد']
UNCLASSIFIED_GROUP_CODE = 'unclassified'
UNCLASSIFIED_GROUP_NAME = 'أنواع أخرى غير مصنفة'


def safe_div(numerator, denominator, precision=2, default=0.0):
    num = float(numerator or 0)
    den = float(denominator or 0)
    if den == 0:
        return default
    return round(num / den, precision)


def compute_prior_period(start_date, end_date, preset):
    """Compute a deterministic prior comparison window matching the selected period."""
    if not start_date or not end_date:
        return start_date, end_date
    if preset in ('this_month', 'last_month'):
        prev_end = start_date - datetime.timedelta(days=1)
        prev_start = prev_end.replace(day=1)
        return prev_start, prev_end
    if preset in ('year', 'this_year'):
        try:
            return start_date.replace(year=start_date.year - 1), end_date.replace(year=end_date.year - 1)
        except ValueError:
            return start_date.replace(year=start_date.year - 1), end_date.replace(year=end_date.year - 1, day=28)
    span_days = max(0, (end_date - start_date).days)
    prev_end = start_date - datetime.timedelta(days=1)
    prev_start = prev_end - datetime.timedelta(days=span_days)
    return prev_start, prev_end


def _authorized_geo_sets(user):
    """Return authorized governorate IDs and brick ID->parent_id map across activities & contacts."""
    gov_act = ScopeResolutionService.get_scoped_choices(user, 'governorates', 'activities')
    gov_con = ScopeResolutionService.get_scoped_choices(user, 'governorates', 'contacts')
    auth_gov_ids = set(gov_act.values_list('id', flat=True)) | set(gov_con.values_list('id', flat=True))

    brick_act = ScopeResolutionService.get_scoped_choices(user, 'bricks', 'activities')
    brick_con = ScopeResolutionService.get_scoped_choices(user, 'bricks', 'contacts')
    auth_bricks = dict(brick_act.values_list('id', 'parent_id'))
    auth_bricks.update(dict(brick_con.values_list('id', 'parent_id')))
    return auth_gov_ids, auth_bricks


def _build_rep_contacts_q(rep_user):
    """
    Build the Q filter identifying active accounts belonging to `rep_user`'s portfolio:
    direct assignment (`assigned_team`), creator (`created_by`), or assigned territory
    (assigned bricks / assigned governorates).
    """
    q = Q(assigned_team__id=rep_user.id) | Q(created_by_id=rep_user.id)
    area_rows = list(rep_user.assigned_areas.values_list('id', 'parent_id'))
    brick_ids = [aid for aid, pid in area_rows if pid is not None]
    gov_ids = [aid for aid, pid in area_rows if pid is None]
    if brick_ids:
        q |= Q(brick_id__in=brick_ids) | Q(addresses__brick_id__in=brick_ids)
    if gov_ids:
        q |= Q(area_id__in=gov_ids) | Q(brick__parent_id__in=gov_ids) | Q(addresses__area_id__in=gov_ids)
    return q


def resolve_performance_filters(request, default_preset='this_month'):
    """
    Unified, strictly server-validated filter resolver for performance & visit reports.
    Safely parses all query parameters, enforces DataScope boundaries, never raises HTTP 500
    on malformed inputs, and returns structured resolved filters + UI choices + chips.
    """
    user = request.user
    params = request.GET

    start_date, end_date, active_preset, start_str, end_str = resolve_date_range(
        request, default_preset=default_preset
    )
    if not start_date or not end_date:
        today = timezone.localdate()
        last_day = calendar.monthrange(today.year, today.month)[1]
        start_date = today.replace(day=1)
        end_date = today.replace(day=last_day)
        active_preset = 'this_month'
        start_str = start_date.isoformat()
        end_str = end_date.isoformat()

    prior_start, prior_end = compute_prior_period(start_date, end_date, active_preset)
    period_label = PRESET_LABELS_AR.get(active_preset, f"من {start_str} إلى {end_str}")
    if active_preset == 'custom':
        period_label = f"من {start_str} إلى {end_str}"

    unauthorized_filter = False

    # 1. Scoped Representatives / Users
    is_super = bool(user.is_superuser or getattr(user, 'is_super_admin', False))
    act_view_scope = 'all' if is_super else ScopeResolutionService.get_user_scope(user, 'activities', 'view')
    can_select_rep = is_super or act_view_scope in ('area', 'all')

    allowed_reps_qs = get_visible_assignees_queryset(user, module='activities')
    if not allowed_reps_qs.filter(pk=user.pk).exists() and user.is_active:
        allowed_reps_qs = User.objects.filter(
            Q(pk__in=allowed_reps_qs.values_list('pk', flat=True)) | Q(pk=user.pk)
        ).select_related('role').order_by('name')
    allowed_rep_ids = set(allowed_reps_qs.values_list('id', flat=True))

    raw_rep_token = (params.get('rep') or params.get('rep_id') or params.get('user_id') or '').strip()
    parsed_rep_id = parse_single_int(params, 'rep', 'rep_id', 'user_id')
    selected_rep = None
    rep_id = None
    if raw_rep_token and raw_rep_token.lower() not in ('all', ''):
        if parsed_rep_id is None:
            # Malformed non-numeric rep token -> safely ignore
            pass
        elif not can_select_rep:
            if parsed_rep_id == user.pk:
                rep_id = user.pk
                selected_rep = user
            else:
                unauthorized_filter = True
        elif parsed_rep_id in allowed_rep_ids:
            rep_id = parsed_rep_id
            selected_rep = User.objects.prefetch_related('assigned_areas').filter(pk=rep_id).first()
        else:
            unauthorized_filter = True

    # 2. Scoped Governorates (Main Areas) & Bricks
    auth_gov_ids, auth_brick_parent_map = _authorized_geo_sets(user)
    raw_area_ids = parse_multi_int(params, 'main_area', 'area', 'area_id')
    raw_brick_ids = parse_multi_int(params, 'brick', 'brick_id')

    area_ids = [aid for aid in raw_area_ids if aid in auth_gov_ids]
    if raw_area_ids and not area_ids:
        unauthorized_filter = True

    brick_ids = [
        bid for bid in raw_brick_ids
        if bid in auth_brick_parent_map and (not area_ids or auth_brick_parent_map[bid] in area_ids)
    ]
    if raw_brick_ids and not brick_ids:
        unauthorized_filter = True

    # 3. Account-Type Groups & Individual Account Types
    active_groups = SettingsService.get_account_type_report_groups(active_only=True, request=request)
    raw_group = (params.get('group') or params.get('report_group') or '').strip()
    selected_group = None
    selected_group_code = ''
    if raw_group:
        if raw_group == UNCLASSIFIED_GROUP_CODE:
            selected_group_code = UNCLASSIFIED_GROUP_CODE
        elif raw_group.isdigit():
            gid = int(raw_group)
            selected_group = next((g for g in active_groups if g.id == gid), None)
            if selected_group:
                selected_group_code = str(selected_group.id)
        else:
            selected_group = next((g for g in active_groups if g.code == raw_group), None)
            if selected_group:
                selected_group_code = str(selected_group.id)

    account_types = parse_multi_str(params, 'account_type', 'account_types')
    account_types = [t for t in account_types if t.lower() not in ('all', 'nan', 'none')]

    # 4. Account Status (default: 'all' = active customer + lead, excluding inactive)
    raw_status = (params.get('account_status') or params.get('contact_status') or 'all').strip().lower()
    if raw_status in ('customer', 'lead'):
        account_status = raw_status
    else:
        account_status = 'all'

    # 5. Specific Account (Contact ID — strictly scoped)
    raw_contact_token = (params.get('contact_id') or params.get('account_id') or '').strip()
    parsed_contact_id = parse_single_int(params, 'contact_id', 'account_id')
    selected_contact = None
    contact_id = None
    if raw_contact_token:
        if parsed_contact_id is not None:
            scoped_c = get_scoped_queryset(
                Contact.objects.filter(ACTIVE_ELIGIBLE_ACCOUNT_Q, pk=parsed_contact_id),
                user,
                'contact',
            ).first()
            if scoped_c:
                contact_id = scoped_c.pk
                selected_contact = scoped_c
            else:
                unauthorized_filter = True

    # Build UI dropdown options (strictly scoped)
    areas_qs = Area.objects.filter(id__in=auth_gov_ids, parent__isnull=True).order_by('name')
    bricks_qs = Area.objects.filter(id__in=auth_brick_parent_map.keys(), parent__isnull=False)
    if area_ids:
        bricks_qs = bricks_qs.filter(parent_id__in=area_ids)
    bricks_qs = bricks_qs.select_related('parent').order_by('name')

    available_account_types = AccountTypeReportGroup.get_available_account_types()

    # Build active filter chips & export filter summary
    active_filters = []
    filter_summary = [f"الفترة: {period_label} ({start_str} إلى {end_str})"]

    if selected_rep:
        r_name = selected_rep.name or selected_rep.username
        active_filters.append({'label': 'المندوب', 'value': r_name, 'param': 'rep'})
        filter_summary.append(f"المندوب: {r_name}")

    if area_ids:
        for a_obj in Area.objects.filter(id__in=area_ids).order_by('name'):
            active_filters.append({'label': 'المحافظة', 'value': a_obj.name, 'param': 'area', 'remove_value': str(a_obj.id)})
            filter_summary.append(f"المحافظة: {a_obj.name}")

    if brick_ids:
        for b_obj in Area.objects.filter(id__in=brick_ids).order_by('name'):
            active_filters.append({'label': 'الخط الجغرافي', 'value': b_obj.name, 'param': 'brick', 'remove_value': str(b_obj.id)})
            filter_summary.append(f"الخط: {b_obj.name}")

    if selected_group:
        active_filters.append({'label': 'المجموعة', 'value': selected_group.name, 'param': 'group'})
        filter_summary.append(f"المجموعة: {selected_group.name}")
    elif selected_group_code == UNCLASSIFIED_GROUP_CODE:
        active_filters.append({'label': 'المجموعة', 'value': UNCLASSIFIED_GROUP_NAME, 'param': 'group'})
        filter_summary.append(f"المجموعة: {UNCLASSIFIED_GROUP_NAME}")

    for at in account_types:
        active_filters.append({'label': 'نوع الحساب', 'value': at, 'param': 'account_type', 'remove_value': at})
    if account_types:
        filter_summary.append("نوع الحساب: " + "، ".join(account_types))

    if account_status != 'all':
        st_lbl = 'عميل فعلي (Customer)' if account_status == 'customer' else 'عميل محتمل (Lead)'
        active_filters.append({'label': 'حالة الحساب', 'value': st_lbl, 'param': 'account_status'})
        filter_summary.append(f"حالة الحساب: {st_lbl}")

    if selected_contact:
        active_filters.append({'label': 'الحساب', 'value': selected_contact.name, 'param': 'contact_id'})
        filter_summary.append(f"الحساب: {selected_contact.name}")

    return {
        'start_date': start_date,
        'end_date': end_date,
        'start_date_str': start_str,
        'end_date_str': end_str,
        'prior_start': prior_start,
        'prior_end': prior_end,
        'period': active_preset,
        'period_label': period_label,
        'rep_id': rep_id,
        'selected_rep': selected_rep,
        'can_select_rep': can_select_rep,
        'area_ids': area_ids,
        'brick_ids': brick_ids,
        'group_id': selected_group.id if selected_group else None,
        'selected_group': selected_group,
        'selected_group_code': selected_group_code,
        'account_types': account_types,
        'account_status': account_status,
        'contact_id': contact_id,
        'selected_contact': selected_contact,
        'unauthorized_filter': unauthorized_filter,
        'active_groups': active_groups,
        'reps_qs': allowed_reps_qs if can_select_rep else User.objects.filter(pk=user.pk),
        'areas_qs': areas_qs,
        'bricks_qs': bricks_qs,
        'available_account_types': available_account_types,
        'active_filters': active_filters,
        'filter_summary': " | ".join(filter_summary),
    }


def _apply_contact_filters(qs, rf, prefix='', active_groups=None):
    """
    Apply shared contact-level filters (status, area, brick, group, account_types, contact_id)
    to either Contact queryset (`prefix=''`) or Visit/PlannedVisitItem queryset (`prefix='contact__'`).
    """
    p = prefix

    # Account status (inactive is always excluded from eligible contacts)
    status = rf.get('account_status', 'all')
    if status in ('customer', 'lead'):
        qs = qs.filter(**{f'{p}status': status})
    elif not p:
        qs = qs.exclude(status='inactive')

    area_ids = rf.get('area_ids') or []
    if area_ids:
        qs = qs.filter(
            Q(**{f'{p}area_id__in': area_ids})
            | Q(**{f'{p}brick__parent_id__in': area_ids})
            | Q(**{f'{p}addresses__area_id__in': area_ids})
            | Q(**{f'{p}addresses__brick__parent_id__in': area_ids})
        )

    brick_ids = rf.get('brick_ids') or []
    if brick_ids:
        qs = qs.filter(
            Q(**{f'{p}brick_id__in': brick_ids})
            | Q(**{f'{p}addresses__brick_id__in': brick_ids})
        )

    # Configurable Account-Type Group filter
    selected_group = rf.get('selected_group')
    selected_group_code = rf.get('selected_group_code')
    if selected_group:
        grp_q = Q()
        for t in (selected_group.account_types or []):
            grp_q |= Q(**{f'{p}account_type__iexact': t})
        if grp_q:
            qs = qs.filter(grp_q)
        else:
            qs = qs.none()
    elif selected_group_code == UNCLASSIFIED_GROUP_CODE:
        groups_list = active_groups if active_groups is not None else SettingsService.get_account_type_report_groups(active_only=True)
        assigned_q = Q()
        for g in groups_list:
            for t in (g.account_types or []):
                assigned_q |= Q(**{f'{p}account_type__iexact': t})
        if assigned_q:
            qs = qs.exclude(assigned_q)

    # Individual account_types filter
    account_types = rf.get('account_types') or []
    if account_types:
        at_q = Q()
        for t in account_types:
            at_q |= Q(**{f'{p}account_type__iexact': t})
        qs = qs.filter(at_q)

    contact_id = rf.get('contact_id')
    if contact_id:
        id_field = f'{p}id' if p else 'id'
        qs = qs.filter(**{id_field: contact_id})

    return qs


class VisitAnalyticsService:
    """
    Centralized set-based Visit & Account Analytics Service.
    """

    @classmethod
    def build_scoped_querysets(cls, user, rf):
        """
        Return strictly scoped & filtered querysets:
        - `eligible_accounts_qs`: active customer/lead Contact queryset
        - `period_visits_qs`: scoped Visit queryset within [start_date, end_date]
        - `period_unlinked_planned_qs`: scoped unlinked PlannedVisitItem queryset within [start_date, end_date]
        - `all_completed_visits_qs`: scoped qualifying completed Visits (all time, for last visit date)
        """
        if rf.get('unauthorized_filter'):
            return (
                Contact.objects.none(),
                Visit.objects.none(),
                PlannedVisitItem.objects.none(),
                Visit.objects.none(),
            )

        start_date = rf['start_date']
        end_date = rf['end_date']
        active_groups = rf.get('active_groups')
        if active_groups is None:
            active_groups = SettingsService.get_account_type_report_groups(active_only=True)

        # 1. Eligible Accounts (active customer + lead, excluding inactive)
        eligible_qs = get_scoped_queryset(
            Contact.objects.filter(ACTIVE_ELIGIBLE_ACCOUNT_Q),
            user,
            'contact',
        )
        eligible_qs = _apply_contact_filters(eligible_qs, rf, prefix='', active_groups=active_groups)

        selected_rep = rf.get('selected_rep')
        if selected_rep is not None:
            eligible_qs = eligible_qs.filter(_build_rep_contacts_q(selected_rep))
        elif rf.get('rep_id'):
            rep_obj = User.objects.prefetch_related('assigned_areas').filter(pk=rf['rep_id']).first()
            if rep_obj:
                eligible_qs = eligible_qs.filter(_build_rep_contacts_q(rep_obj))
            else:
                eligible_qs = Contact.objects.none()

        eligible_qs = eligible_qs.distinct()

        # 2. Visits in Period (strictly scoped via activities module + contact filters)
        base_visits = get_scoped_queryset(Visit.objects.all(), user, 'visit')
        if rf.get('rep_id'):
            base_visits = base_visits.filter(owner_id=rf['rep_id'])
        base_visits = _apply_contact_filters(base_visits, rf, prefix='contact__', active_groups=active_groups)
        base_visits = base_visits.filter(contact__is_customer=True).exclude(contact__status='inactive')

        period_visits_qs = base_visits.filter(date__gte=start_date, date__lte=end_date).distinct()
        all_completed_visits_qs = base_visits.filter(COMPLETED_VISIT_Q)

        # 3. Legacy unlinked PlannedVisitItems in Period (zero double-counting with Visit)
        unlinked_planned_qs = get_scoped_queryset(
            PlannedVisitItem.objects.filter(UNLINKED_PLANNED_ITEM_Q),
            user,
            'plannedvisititem',
        )
        if rf.get('rep_id'):
            unlinked_planned_qs = unlinked_planned_qs.filter(plan_day__assignee_id=rf['rep_id'])
        unlinked_planned_qs = _apply_contact_filters(
            unlinked_planned_qs, rf, prefix='contact__', active_groups=active_groups
        )
        unlinked_planned_qs = unlinked_planned_qs.filter(
            contact__is_customer=True,
            plan_day__date__gte=start_date,
            plan_day__date__lte=end_date,
        ).exclude(contact__status='inactive').distinct()

        return eligible_qs, period_visits_qs, unlinked_planned_qs, all_completed_visits_qs

    @classmethod
    def get_analytics_bundle(cls, user, rf, include_daily_series=True):
        """
        Compute the complete visit & account analytics bundle in constant SQL queries:
        - Summary & Planned/Unplanned KPIs
        - Working Days & Average Visits per Working/Calendar Day
        - Eligible / Visited / Unvisited Account reconciliation
        - Configurable Account-Type Group breakdown + Unclassified reconciliation
        - Continuous daily activity series (every calendar day in [start_date, end_date])
        """
        start_date = rf['start_date']
        end_date = rf['end_date']
        active_groups = rf.get('active_groups')
        if active_groups is None:
            active_groups = SettingsService.get_account_type_report_groups(active_only=True)

        eligible_qs, period_visits_qs, unlinked_planned_qs, _ = cls.build_scoped_querysets(user, rf)

        # Normalize to flat ID-deduplicated querysets when area/brick M2M joins were added
        has_geo_join = bool(rf.get('area_ids') or rf.get('brick_ids') or rf.get('rep_id'))
        if has_geo_join:
            visit_ids_subq = period_visits_qs.values('id')
            visits_clean_qs = Visit.objects.filter(id__in=visit_ids_subq)
            eligible_ids_subq = eligible_qs.values('id')
            eligible_clean_qs = Contact.objects.filter(id__in=eligible_ids_subq)
            unlinked_ids_subq = unlinked_planned_qs.values('id')
            unlinked_clean_qs = PlannedVisitItem.objects.filter(id__in=unlinked_ids_subq)
        else:
            visits_clean_qs = period_visits_qs
            eligible_clean_qs = eligible_qs
            unlinked_clean_qs = unlinked_planned_qs

        # 1. Core Visit Summary (1 SQL query + 1 unlinked count query)
        v_agg = visits_clean_qs.aggregate(
            planned_completed=Count('id', filter=PLANNED_COMPLETED_Q),
            planned_incomplete_visits=Count('id', filter=PLANNED_INCOMPLETE_Q),
            unplanned_completed=Count('id', filter=UNPLANNED_COMPLETED_Q),
            unplanned_in_progress=Count('id', filter=UNPLANNED_IN_PROGRESS_Q),
            working_days=Count('date', filter=COMPLETED_VISIT_Q, distinct=True),
            total_duration_sec=Sum('duration', filter=COMPLETED_VISIT_Q),
            double_visits=Count('id', filter=COMPLETED_VISIT_Q & Q(doubled=True)),
            in_range_visits=Count(
                'id',
                filter=COMPLETED_VISIT_Q & Q(requires_approval_due_to_distance=False, location_verified=True),
            ),
            bypassed_visits=Count('id', filter=COMPLETED_VISIT_Q & Q(bypassed_by__isnull=False)),
        )
        unlinked_incomplete = unlinked_clean_qs.count()

        planned_completed = v_agg['planned_completed'] or 0
        planned_incomplete = (v_agg['planned_incomplete_visits'] or 0) + unlinked_incomplete
        planned_total = planned_completed + planned_incomplete
        plan_completion_pct = safe_div(planned_completed * 100, planned_total, 1)

        unplanned_completed = v_agg['unplanned_completed'] or 0
        unplanned_in_progress = v_agg['unplanned_in_progress'] or 0
        total_completed_visits = planned_completed + unplanned_completed

        working_days = v_agg['working_days'] or 0
        calendar_days = max(1, (end_date - start_date).days + 1)

        avg_visits_per_working_day = safe_div(total_completed_visits, working_days, 1)
        avg_visits_per_calendar_day = safe_div(total_completed_visits, calendar_days, 1)

        total_duration_sec = v_agg['total_duration_sec'] or 0
        avg_visit_duration_mins = safe_div(total_duration_sec / 60.0, total_completed_visits, 1)
        avg_working_hours = safe_div(total_duration_sec / 3600.0, working_days, 1)

        # 2. Eligible / Visited / Unvisited Accounts (1 SQL query via Exists)
        completed_for_contact_sq = visits_clean_qs.filter(COMPLETED_VISIT_Q, contact_id=OuterRef('pk'))
        acc_agg = eligible_clean_qs.annotate(
            is_visited=Exists(completed_for_contact_sq)
        ).aggregate(
            eligible_accounts=Count('id'),
            visited_accounts=Count('id', filter=Q(is_visited=True)),
        )
        eligible_accounts = acc_agg['eligible_accounts'] or 0
        visited_accounts = acc_agg['visited_accounts'] or 0
        unvisited_accounts = max(0, eligible_accounts - visited_accounts)
        coverage_pct = min(100.0, safe_div(visited_accounts * 100, eligible_accounts, 1))

        # Completed visits strictly against eligible accounts for visit frequency
        completed_on_eligible = visits_clean_qs.filter(
            COMPLETED_VISIT_Q, contact_id__in=eligible_clean_qs.values('id')
        ).count()
        visit_frequency = safe_div(completed_on_eligible, visited_accounts, 2)

        # 3. Configurable Account-Type Groups (3 constant SQL queries total)
        type_to_group_key = {}
        group_buckets = {}
        ordered_group_keys = []

        for grp in active_groups:
            g_key = str(grp.id)
            ordered_group_keys.append(g_key)
            group_buckets[g_key] = {
                'id': grp.id,
                'code': grp.code,
                'name': grp.name,
                'icon': grp.icon or 'category',
                'display_order': grp.display_order,
                'account_types': list(grp.account_types or []),
                'is_unclassified': False,
                'planned_completed': 0,
                'planned_incomplete': 0,
                'planned_total': 0,
                'plan_completion_pct': 0.0,
                'unplanned_completed': 0,
                'unplanned_in_progress': 0,
                'total_completed': 0,
                'eligible_accounts': 0,
                'visited_accounts': 0,
                'unvisited_accounts': 0,
                'coverage_pct': 0.0,
            }
            for t in (grp.account_types or []):
                t_low = str(t).strip().lower()
                if t_low and t_low not in type_to_group_key:
                    type_to_group_key[t_low] = g_key

        unclassified_bucket = {
            'id': None,
            'code': UNCLASSIFIED_GROUP_CODE,
            'name': UNCLASSIFIED_GROUP_NAME,
            'icon': 'more_horiz',
            'display_order': 9999,
            'account_types': [],
            'is_unclassified': True,
            'planned_completed': 0,
            'planned_incomplete': 0,
            'planned_total': 0,
            'plan_completion_pct': 0.0,
            'unplanned_completed': 0,
            'unplanned_in_progress': 0,
            'total_completed': 0,
            'eligible_accounts': 0,
            'visited_accounts': 0,
            'unvisited_accounts': 0,
            'coverage_pct': 0.0,
        }
        unclassified_seen_types = set()

        def _get_bucket(raw_type):
            val = (raw_type or '').strip()
            low = val.lower()
            g_key = type_to_group_key.get(low)
            if g_key is not None:
                return group_buckets[g_key]
            if val and low not in unclassified_seen_types:
                unclassified_seen_types.add(low)
                unclassified_bucket['account_types'].append(val)
            return unclassified_bucket

        # 3a. Visits grouped by contact__account_type
        for row in visits_clean_qs.values('contact__account_type').annotate(
            p_comp=Count('id', filter=PLANNED_COMPLETED_Q),
            p_inc=Count('id', filter=PLANNED_INCOMPLETE_Q),
            u_comp=Count('id', filter=UNPLANNED_COMPLETED_Q),
            u_prog=Count('id', filter=UNPLANNED_IN_PROGRESS_Q),
        ):
            b = _get_bucket(row['contact__account_type'])
            b['planned_completed'] += row['p_comp'] or 0
            b['planned_incomplete'] += row['p_inc'] or 0
            b['unplanned_completed'] += row['u_comp'] or 0
            b['unplanned_in_progress'] += row['u_prog'] or 0

        # 3b. Unlinked planned items grouped by contact__account_type
        if unlinked_incomplete:
            for row in unlinked_clean_qs.values('contact__account_type').annotate(cnt=Count('id')):
                b = _get_bucket(row['contact__account_type'])
                b['planned_incomplete'] += row['cnt'] or 0

        # 3c. Eligible & visited accounts grouped by account_type
        for row in eligible_clean_qs.annotate(
            is_visited=Exists(completed_for_contact_sq)
        ).values('account_type').annotate(
            elig=Count('id'),
            vis=Count('id', filter=Q(is_visited=True)),
        ):
            b = _get_bucket(row['account_type'])
            b['eligible_accounts'] += row['elig'] or 0
            b['visited_accounts'] += row['vis'] or 0

        def _finalize_bucket(b):
            b['planned_total'] = b['planned_completed'] + b['planned_incomplete']
            b['plan_completion_pct'] = safe_div(b['planned_completed'] * 100, b['planned_total'], 1)
            b['total_completed'] = b['planned_completed'] + b['unplanned_completed']
            b['unvisited_accounts'] = max(0, b['eligible_accounts'] - b['visited_accounts'])
            b['coverage_pct'] = min(100.0, safe_div(b['visited_accounts'] * 100, b['eligible_accounts'], 1))
            return b

        account_type_groups = [_finalize_bucket(group_buckets[k]) for k in ordered_group_keys]
        _finalize_bucket(unclassified_bucket)
        has_unclassified = bool(
            unclassified_bucket['eligible_accounts'] > 0
            or unclassified_bucket['total_completed'] > 0
            or unclassified_bucket['planned_total'] > 0
        )

        # 4. Continuous Daily Activity Series (every calendar day in [start_date, end_date])
        daily_series = []
        if include_daily_series:
            daily_map = defaultdict(lambda: {
                'planned_completed': 0,
                'unplanned_completed': 0,
                'planned_incomplete': 0,
            })
            for row in visits_clean_qs.values('date').annotate(
                p_comp=Count('id', filter=PLANNED_COMPLETED_Q),
                u_comp=Count('id', filter=UNPLANNED_COMPLETED_Q),
                p_inc=Count('id', filter=PLANNED_INCOMPLETE_Q),
            ):
                d = row['date']
                if d:
                    daily_map[d]['planned_completed'] += row['p_comp'] or 0
                    daily_map[d]['unplanned_completed'] += row['u_comp'] or 0
                    daily_map[d]['planned_incomplete'] += row['p_inc'] or 0

            if unlinked_incomplete:
                for row in unlinked_clean_qs.values('plan_day__date').annotate(cnt=Count('id')):
                    d = row['plan_day__date']
                    if d:
                        daily_map[d]['planned_incomplete'] += row['cnt'] or 0

            cur = start_date
            while cur <= end_date:
                dm = daily_map[cur]
                p_c = dm['planned_completed']
                u_c = dm['unplanned_completed']
                p_i = dm['planned_incomplete']
                tot_c = p_c + u_c
                daily_series.append({
                    'date': cur.isoformat(),
                    'label': cur.strftime('%m-%d'),
                    'weekday_ar': ARABIC_WEEKDAYS[cur.weekday()],
                    'planned_completed': p_c,
                    'unplanned_completed': u_c,
                    'planned_incomplete': p_i,
                    'total_completed': tot_c,
                    'total_planned': p_c + p_i,
                })
                cur += datetime.timedelta(days=1)

        return {
            'start_date': start_date,
            'end_date': end_date,
            'start_date_str': start_date.isoformat(),
            'end_date_str': end_date.isoformat(),
            'working_days': working_days,
            'calendar_days': calendar_days,
            'planned_completed': planned_completed,
            'planned_incomplete': planned_incomplete,
            'planned_total': planned_total,
            'plan_completion_pct': plan_completion_pct,
            'unplanned_completed': unplanned_completed,
            'unplanned_in_progress': unplanned_in_progress,
            'total_completed_visits': total_completed_visits,
            'planned_share_pct': safe_div(planned_completed * 100, total_completed_visits, 1),
            'unplanned_share_pct': safe_div(unplanned_completed * 100, total_completed_visits, 1),
            'avg_visits_per_working_day': avg_visits_per_working_day,
            'avg_visits_per_calendar_day': avg_visits_per_calendar_day,
            'total_duration_sec': total_duration_sec,
            'avg_visit_duration_mins': avg_visit_duration_mins,
            'avg_working_hours': avg_working_hours,
            'double_visits': v_agg['double_visits'] or 0,
            'double_visits_pct': safe_div((v_agg['double_visits'] or 0) * 100, total_completed_visits, 1),
            'in_range_visits': v_agg['in_range_visits'] or 0,
            'bypassed_visits': v_agg['bypassed_visits'] or 0,
            'accounts_summary': {
                'eligible_accounts': eligible_accounts,
                'visited_accounts': visited_accounts,
                'unvisited_accounts': unvisited_accounts,
                'coverage_pct': coverage_pct,
                'visit_frequency': visit_frequency,
            },
            'account_type_groups': account_type_groups,
            'unclassified_group': unclassified_bucket if has_unclassified else None,
            'all_group_rows': account_type_groups + ([unclassified_bucket] if has_unclassified else []),
            'daily_series': daily_series,
        }

    @classmethod
    def get_accounts_drilldown_queryset(cls, user, rf, tab='visited', search_q='', sort_by=''):
        """
        Return annotated Contact queryset for Visited / Unvisited / All Eligible accounts drill-down.
        Uses correlated Subqueries (zero Cartesian row multiplication) and exact scope parity.
        """
        eligible_qs, period_visits_qs, _, all_completed_visits_qs = cls.build_scoped_querysets(user, rf)

        visit_ids_subq = period_visits_qs.values('id')
        visits_clean_qs = Visit.objects.filter(id__in=visit_ids_subq)

        completed_subq = visits_clean_qs.filter(COMPLETED_VISIT_Q, contact_id=OuterRef('pk'))
        completed_count_sq = (
            visits_clean_qs.filter(COMPLETED_VISIT_Q, contact_id=OuterRef('pk'))
            .values('contact_id')
            .annotate(cnt=Count('id'))
            .values('cnt')[:1]
        )
        incomplete_count_sq = (
            visits_clean_qs.filter(PLANNED_INCOMPLETE_Q, contact_id=OuterRef('pk'))
            .values('contact_id')
            .annotate(cnt=Count('id'))
            .values('cnt')[:1]
        )
        last_visit_sq = (
            all_completed_visits_qs.filter(contact_id=OuterRef('pk'))
            .order_by('-date', '-id')
            .values('date')[:1]
        )

        qs = (
            Contact.objects.filter(id__in=eligible_qs.values('id'))
            .select_related('area', 'brick', 'created_by')
            .prefetch_related('assigned_team')
            .annotate(
                is_visited_in_period=Exists(completed_subq),
                period_completed_visits=Coalesce(
                    Subquery(completed_count_sq, output_field=IntegerField()), Value(0)
                ),
                period_incomplete_planned=Coalesce(
                    Subquery(incomplete_count_sq, output_field=IntegerField()), Value(0)
                ),
                last_qualifying_visit_date=Subquery(last_visit_sq),
            )
        )

        if tab == 'visited':
            qs = qs.filter(is_visited_in_period=True)
        elif tab == 'unvisited':
            qs = qs.filter(is_visited_in_period=False)

        if search_q:
            from master_data.search_utils import filter_by_arabic_search
            qs = filter_by_arabic_search(
                qs,
                ['name', 'code', 'mobile', 'account_type', 'specialty'],
                search_q,
                raw_fields=['code', 'mobile'],
                numeric_id_field='serial_num',
            )

        sort_map = {
            'name': 'name',
            '-name': '-name',
            'visits': 'period_completed_visits',
            '-visits': '-period_completed_visits',
            'last_visit': 'last_qualifying_visit_date',
            '-last_visit': '-last_qualifying_visit_date',
            'type': 'account_type',
            '-type': '-account_type',
        }
        order_field = sort_map.get(sort_by)
        if order_field:
            qs = qs.order_by(order_field, 'name')
        elif tab == 'visited':
            qs = qs.order_by('-period_completed_visits', '-last_qualifying_visit_date', 'name')
        else:
            qs = qs.order_by('-period_incomplete_planned', 'name')

        return qs

    @classmethod
    def get_account_visit_details_queryset(cls, user, rf):
        """Return scoped period visits (excluding cancelled/disapproved) for detailed export."""
        _, period_visits_qs, _, _ = cls.build_scoped_querysets(user, rf)
        return (
            Visit.objects.filter(id__in=period_visits_qs.values('id'))
            .exclude(status='cancelled')
            .exclude(approval_status='disapproved')
            .select_related('contact', 'contact__area', 'contact__brick', 'owner', 'template')
            .order_by('-date', '-id')
        )
