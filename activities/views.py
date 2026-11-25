import datetime
import json
import mimetypes
from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from master_data.pagination_utils import paginate_queryset
from django.db import transaction
from django.db.models import Q, Sum, Count, Max
from django.utils import timezone
from django.http import HttpResponse, JsonResponse, FileResponse, Http404, HttpResponseForbidden
from django.contrib.auth import get_user_model
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

from django.urls import reverse

from .models import (
    Agreement, AgreementType, VisitTemplate, VisitTemplateQuestion,
    PlannedVisitDay, PlannedVisitItem, Visit, VisitPlan,
    VisitSampleItem, VisitExpense, ApprovalAuditLog, AgendaTodo
)
from .forms import (
    AgreementForm, PlannedVisitItemForm, VisitForm,
    VisitTemplateForm, VisitTemplateQuestionForm
)
from django.core.exceptions import ValidationError
from contacts.models import Contact
from contacts.constants import ACCOUNT_TYPES, CUSTOMER_CATEGORIES, SPECIALTIES
from master_data.models import Area
from catalog.models import Product
from .services import (
    verify_visit_location, can_start_visit, start_visit,
    create_and_start_unplanned_visit, extract_checkin_answers_from_post, get_open_visit_for_owner,
    can_submit_answers, can_end_visit, end_visit,
    build_visit_timeline, can_delete_unended_visit, delete_unended_visit,
    _delete_visit_and_related_records,
    can_edit_visit_answers, update_visit_questionnaire_answers,
    build_agreement_timeline, _agreement_snapshot, _diff_agreement_fields,
    get_question_product_choices, parse_suggested_products_submission,
    preload_visit_qa_product_map, format_answer_for_display,
    can_edit_agreement, can_delete_agreement,
)
from master_data.date_filter_utils import resolve_date_range
from master_data.search_utils import filter_by_arabic_search
from accounts.scope_service import ScopeResolutionService
from accounts.permissions import (
    require_permission, has_perm_or_admin, render_forbidden_response,
    get_scoped_queryset, can_user_access_object, get_user_managed_representatives,
    get_visible_assignees_queryset,
    get_visit_eligible_contacts_queryset, can_user_access_contact_for_visit,
    get_user_managed_areas, get_user_main_areas, is_manager_or_higher
)
from accounts.services import AuditLogService

User = get_user_model()


def can_manage_approvals(user, module_type='visits'):
    """
    Check if the user is authorized to approve/disapprove or change approval status
    of visits and agreements using centralized permission architecture.
    """
    if not user.is_authenticated:
        return False
    if getattr(user, 'is_super_admin', False) or user.is_superuser:
        return True
    role = getattr(user, 'role', None)
    if role and getattr(role, 'is_super', False):
        return True
    if module_type == 'agreements':
        return has_perm_or_admin(user, 'activities:agreements/approve')
    return has_perm_or_admin(user, 'activities:visits/approve')


def can_user_approve_contact_visit(user, contact=None, module_type='visits', visit_owner=None):
    """
    Verify supervisory approval authority combining permission, regional manage scope
    ('area' or 'all'), and target contact/area isolation. Users with 'own' or 'brick'
    manage scope (representatives) can never self-approve or bypass visit approval.
    """
    if not user or not getattr(user, 'is_authenticated', False):
        return False
    if getattr(user, 'is_superuser', False) or getattr(user, 'is_super_admin', False):
        return True
    role = getattr(user, 'role', None)
    if role and getattr(role, 'is_super', False):
        return True
    if not can_manage_approvals(user, module_type):
        return False

    from accounts.scope_service import ScopeResolutionService
    manage_scope = ScopeResolutionService.get_user_scope(user, 'activities', 'manage')
    if manage_scope == 'all':
        return True
    if manage_scope != 'area':
        return False

    if visit_owner is not None and visit_owner != user:
        if not get_user_managed_representatives(user, module='activities').filter(pk=visit_owner.pk).exists():
            return False
    if contact is not None:
        return can_user_access_contact_for_visit(user, contact)
    return True


def resolve_visit_creation_approval(user, contact, is_planned, location_settings, visit_owner=None):
    """
    Approval resolution for newly created visits:
    - Unplanned visits (is_planned=False): Auto-approved upon creation.
    - Planned visits (is_planned=True): Require approval if creator lacks supervisory approval
      authority (activities:visits/approve) or if anti-self-approval applies.
    Returns (approval_status, approved_by, approved_at).
    """
    if not is_planned:
        # Unplanned visits are auto-approved
        return 'approved', user, timezone.now()

    # Planned visits:
    target_owner = visit_owner or user
    is_super = getattr(user, 'is_super_admin', False) or user.is_superuser

    # Anti-self-approval: a user cannot approve their own planned visit
    if target_owner.id == user.id and not is_super:
        return 'pending', None, None

    if can_user_approve_contact_visit(user, contact=contact, module_type='visits', visit_owner=target_owner):
        return 'approved', user, timezone.now()

    return 'pending', None, None


def can_manage_templates(user):
    """Check if user has permission to manage visit templates."""
    return has_perm_or_admin(user, 'settings:visitsTemplates/manage')


def can_assign_other_representative(user):
    """
    Standard representatives cannot change the assigned representative.
    Superusers and authorized managers/admins can select another representative.
    """
    if not user.is_authenticated:
        return False
    if user.is_superuser or getattr(user, 'is_super_admin', False):
        return True
    from accounts.scope_service import ScopeResolutionService
    if ScopeResolutionService.get_user_scope(user, 'activities', 'manage') in ['area', 'all']:
        return True
    if has_perm_or_admin(user, 'activities:planned/manage'):
        return True
    role = getattr(user, 'role', None)
    if role and (role.is_manager_role or role.is_area_manager):
        return True
    return False


# -----------------------------------------------------------------------------
# AGREEMENTS MODULE
# -----------------------------------------------------------------------------

@require_permission('activities:agreements/list')
def agreements_list(request):
    """
    List agreements with search, filters, pagination, sum aggregation, and create modal.
    Matches https://weapharma.bricks-rep.com/agreements
    """
    from master_data.filter_utils import (
        parse_multi_int,
        parse_multi_str,
        parse_single_int,
        resolve_scoped_area_brick_filters,
        build_contact_area_q,
        build_contact_brick_q,
    )

    qs = Agreement.objects.select_related('customer', 'customer__area', 'customer__brick', 'type', 'created_by').all().order_by('-serial_num')
    qs = get_scoped_queryset(qs, request.user, 'agreement')

    # Search with Arabic normalization
    q = (request.GET.get('search') or request.GET.get('q') or '').strip()
    active_filters = []

    if q:
        qs = filter_by_arabic_search(
            qs,
            ['title', 'description', 'customer__name', 'customer__code'],
            q,
            raw_fields=['customer__code'],
            numeric_id_field='serial_num'
        )
        active_filters.append({'label': 'بحث', 'value': q, 'param': 'search'})

    # Type Filter (multi-select)
    selected_types = parse_multi_int(request.GET, 'type')
    type_id = str(selected_types[0]) if len(selected_types) == 1 else ''
    if selected_types:
        qs = qs.filter(type_id__in=selected_types)
        for t_obj in AgreementType.objects.filter(id__in=selected_types):
            active_filters.append({'label': 'النوع', 'value': t_obj.name, 'param': 'type', 'remove_value': str(t_obj.id)})

    # Status Filter (Exact 2-status lifecycle: new and done)
    status = request.GET.get('status')
    if status:
        if status == 'done':
            qs = qs.filter(status__in=['done', 'approved'])
            active_filters.append({'label': 'الحالة', 'value': 'منجزة', 'param': 'status'})
        elif status == 'new':
            qs = qs.filter(status__in=['new', 'disapproved'])
            active_filters.append({'label': 'الحالة', 'value': 'جديدة', 'param': 'status'})
        else:
            qs = qs.filter(status=status)
            status_labels = dict(Agreement.STATUS_CHOICES)
            active_filters.append({'label': 'الحالة', 'value': status_labels.get(status, status), 'param': 'status'})

    # Customer Filter (safe int parsing)
    customer_id_int = parse_single_int(request.GET, 'customer')
    customer_id = str(customer_id_int) if customer_id_int else ''
    if customer_id_int:
        qs = qs.filter(customer_id=customer_id_int)
        c_obj = get_scoped_queryset(Contact.objects.all(), request.user, 'contact').filter(id=customer_id_int).first()
        active_filters.append({'label': 'العميل', 'value': c_obj.name if c_obj else customer_id, 'param': 'customer'})

    # Assignee Filter (created_by, multi-select, strictly scoped)
    visible_users_qs = get_visible_assignees_queryset(request.user, 'activities')
    raw_creator_ids = parse_multi_int(request.GET, 'creator')
    selected_creators = []
    if raw_creator_ids:
        auth_creators = list(visible_users_qs.filter(id__in=raw_creator_ids))
        selected_creators = [u.id for u in auth_creators]
        if selected_creators:
            qs = qs.filter(created_by_id__in=selected_creators)
            for u_obj in auth_creators:
                active_filters.append({
                    'label': 'المسؤول',
                    'value': u_obj.get_full_name() or u_obj.username,
                    'param': 'creator',
                    'remove_value': str(u_obj.id),
                })
        else:
            qs = qs.none()
    creator_id = str(selected_creators[0]) if len(selected_creators) == 1 else ''

    # Amount Range Filters (Min & Max with partial boundaries support)
    amount_min = request.GET.get('amount_min', '').strip()
    amount_max = request.GET.get('amount_max', '').strip()
    if amount_min:
        try:
            amt_min_val = Decimal(amount_min)
            qs = qs.filter(amount__gte=amt_min_val)
            active_filters.append({'label': 'الحد الأدنى للمبلغ', 'value': f'{amt_min_val:,.2f} ج.م', 'param': 'amount_min'})
        except Exception:
            amount_min = ''
    if amount_max:
        try:
            amt_max_val = Decimal(amount_max)
            qs = qs.filter(amount__lte=amt_max_val)
            active_filters.append({'label': 'الحد الأقصى للمبلغ', 'value': f'{amt_max_val:,.2f} ج.م', 'param': 'amount_max'})
        except Exception:
            amount_max = ''

    # Scoped Main Area & Brick multi-select filters (supports main_area/governorate & brick)
    main_area_ids, brick_ids, selected_main_areas_chips, selected_bricks_chips = resolve_scoped_area_brick_filters(
        request, 'activities',
        area_params=('main_area', 'governorate', 'area_id'),
        brick_params=('brick', 'brick_id', 'area'),
    )
    gov_id = str(main_area_ids[0]) if len(main_area_ids) == 1 else ''
    brick_id = str(brick_ids[0]) if len(brick_ids) == 1 else ''

    if main_area_ids:
        qs = qs.filter(build_contact_area_q(main_area_ids, prefix='customer', include_addresses=False))
        for a_chip in selected_main_areas_chips:
            active_filters.append({'label': 'المحافظة', 'value': a_chip['name'], 'param': 'main_area', 'remove_value': str(a_chip['id'])})
    if brick_ids:
        qs = qs.filter(build_contact_brick_q(brick_ids, prefix='customer', include_addresses=False))
        for b_chip in selected_bricks_chips:
            active_filters.append({'label': 'المنطقة (Brick)', 'value': b_chip['name'], 'param': 'brick', 'remove_value': str(b_chip['id'])})

    # Account Type multi-select filter
    selected_account_types = parse_multi_str(request.GET, 'account_type')
    if selected_account_types:
        qs = qs.filter(customer__account_type__in=selected_account_types)
        for at in selected_account_types:
            active_filters.append({'label': 'نوع العميل', 'value': at, 'param': 'account_type', 'remove_value': at})

    # Date Range Filters (Unified resolve_date_range)
    parsed_from, parsed_to, active_preset, date_from, date_to = resolve_date_range(request, default_preset='all_time')
    if parsed_from:
        qs = qs.filter(date__gte=parsed_from)
        active_filters.append({'label': 'من تاريخ', 'value': date_from, 'param': 'date_from'})
    if parsed_to:
        qs = qs.filter(date__lte=parsed_to)
        active_filters.append({'label': 'إلى تاريخ', 'value': date_to, 'param': 'date_to'})

    # Summary Metrics (matches reference aggregate API - committed amount is done/approved)
    agreements_agg = qs.aggregate(
        total_count=Count('id'),
        all_amount=Sum('amount'),
        done_amount=Sum('amount', filter=Q(status__in=['done', 'approved'])),
        new_amount=Sum('amount', filter=Q(status='new')),
        done_count=Count('id', filter=Q(status__in=['done', 'approved'])),
        new_count=Count('id', filter=Q(status='new')),
    )
    total_amount = agreements_agg['done_amount'] or Decimal('0.00')
    done_amount = agreements_agg['done_amount'] or Decimal('0.00')
    new_amount = agreements_agg['new_amount'] or Decimal('0.00')
    done_count = agreements_agg['done_count'] or 0
    new_count = agreements_agg['new_count'] or 0

    # Handle inline Create via POST
    if request.method == 'POST' and 'create_agreement' in request.POST:
        if not has_perm_or_admin(request.user, 'activities:agreements/create'):
            return render_forbidden_response(request, "عذراً، لا تملك صلاحية إضافة اتفاقية.")
        form = AgreementForm(request.POST, user=request.user)
        if form.is_valid():
            agreement = form.save(commit=False)
            agreement.created_by = request.user
            agreement.updated_by = request.user
            agreement.status = 'new'
            agreement.save()

            ApprovalAuditLog.objects.create(
                record_type='agreement',
                agreement=agreement,
                action='created',
                actor=request.user,
                status_before='',
                status_after=agreement.status,
                reason='إنشاء اتفاقية جديدة عبر النافذة السريعة',
                changes=[
                    {'field': 'العنوان', 'old': '-', 'new': agreement.title},
                    {'field': 'العميل', 'old': '-', 'new': agreement.customer.name},
                    {'field': 'المبلغ', 'old': '-', 'new': f"{agreement.amount} ج.م"},
                    {'field': 'الحالة', 'old': '-', 'new': agreement.status_display_ar},
                ],
                ip_address=request.META.get('REMOTE_ADDR'),
            )
            AuditLogService.log(
                action='create',
                action_type='AGREEMENT_CREATED',
                module='activities',
                actor=request.user,
                record_id=agreement.pk,
                record_name=f"اتفاقية #{agreement.serial_num}",
                description=f"إنشاء الاتفاقية #{agreement.serial_num} للعميل {agreement.customer.name}",
                new_values={'title': agreement.title, 'amount': str(agreement.amount), 'status': agreement.status, 'customer': agreement.customer.name},
                status='SUCCESS',
                request=request,
            )
            messages.success(request, f"تم إنشاء الاتفاقية #{agreement.serial_num} بنجاح.")
            return redirect('agreements_list')
        else:
            messages.error(request, "يرجى تصحيح الأخطاء في نموذج إنشاء الاتفاقية.")
    else:
        form = AgreementForm(initial={'date': timezone.now().date()}, user=request.user)

    # Standardized bounded pagination
    paginator, page_obj = paginate_queryset(request, qs, default_per_page=25, max_per_page=100)

    # Filter dropdown options (strictly scoped)
    agreement_types = AgreementType.objects.filter(is_active=True)
    users = get_visible_assignees_queryset(request.user, 'activities').order_by('first_name', 'username')
    governorates = ScopeResolutionService.get_scoped_choices(request.user, 'governorates', 'activities')
    bricks = ScopeResolutionService.get_scoped_choices(request.user, 'bricks', 'activities')
    customers = get_scoped_queryset(Contact.objects.filter(is_customer=True).exclude(status='inactive'), request.user, 'contact').order_by('name')[:150]

    user_scope = ScopeResolutionService.get_user_scope(request.user, 'activities')
    can_filter_creator = (
        request.user.is_superuser
        or bool(request.user.role and request.user.role.is_super)
        or user_scope in ['area', 'all']
    )

    agreements_stats = {
        'total_count': agreements_agg['total_count'] or 0,
        'total_amount': total_amount,
        'pending_amount': new_amount,
        'done_amount': done_amount,
        'approved_amount': done_amount,
        'approved_count': done_count,
        'done_count': done_count,
        'pending_count': new_count,
        'new_count': new_count,
    }

    for a in page_obj.object_list:
        a.user_can_edit = can_edit_agreement(request.user, a)[0]
        a.user_can_delete = can_delete_agreement(request.user, a)[0]

    type_options = [{'value': str(t.id), 'label': t.name} for t in agreement_types]
    selected_type_str = [str(x) for x in selected_types]
    selected_type_items = [o for o in type_options if o['value'] in selected_type_str]
    creator_options = [{'value': str(u.id), 'label': u.get_full_name() or u.username} for u in users]
    selected_creator_str = [str(x) for x in selected_creators]
    selected_creator_items = [o for o in creator_options if o['value'] in selected_creator_str]

    context = {
        'page_obj': page_obj,
        'paginator': paginator,
        'agreements': page_obj.object_list,
        'total_count': paginator.count,
        'total_amount': total_amount,
        'form': form,
        'agreement_types': agreement_types,
        'type_options': type_options,
        'selected_type_items': selected_type_items,
        'selected_types': selected_type_str,
        'users': users,
        'creator_options': creator_options,
        'selected_creator_items': selected_creator_items,
        'selected_creators': selected_creator_str,
        'governorates': governorates,
        'bricks': bricks,
        'selected_main_areas_chips': selected_main_areas_chips,
        'selected_bricks_chips': selected_bricks_chips,
        'account_types': ACCOUNT_TYPES,
        'selected_account_types': selected_account_types,
        'customers': customers,
        'can_filter_creator': can_filter_creator,
        'selected_q': q,
        'selected_type': type_id,
        'selected_status': status,
        'selected_customer': customer_id,
        'selected_creator': creator_id,
        'selected_amount_min': amount_min,
        'selected_amount_max': amount_max,
        'selected_governorate': gov_id,
        'selected_brick': brick_id,
        'selected_date_from': date_from,
        'selected_date_to': date_to,
        'date_from': date_from,
        'date_to': date_to,
        'active_preset': active_preset,
        'active_filters': active_filters,
        'can_manage_approvals': can_manage_approvals(request.user, 'agreements'),
        'can_view_agreement': has_perm_or_admin(request.user, 'activities:agreements/view'),
        'can_create_agreement': has_perm_or_admin(request.user, 'activities:agreements/create'),
        'can_export_agreements': has_perm_or_admin(request.user, 'activities:agreements/export'),
        'stats': agreements_stats,
    }
    return render(request, 'activities/agreements_list.html', context)


@require_permission('activities:agreements/approve')
def agreements_bulk_status(request):
    """
    Update status of multiple selected agreements in bulk.
    Matches reference action bar 'تغيير الحالة'.
    Requires manager/superuser authorization.
    Enforces server-side data scoping and anti-self-approval.
    """
    if request.method != 'POST':
        return redirect('agreements_list')

    if not can_manage_approvals(request.user, 'agreements'):
        messages.error(request, "عذراً، لا تملك صلاحية تغيير حالة الاتفاقيات (خاص بالمدراء).")
        return redirect('agreements_list')

    new_status = request.POST.get('status')
    if new_status not in ['new', 'approved', 'disapproved', 'done']:
        messages.error(request, "حالة غير صالحة.")
        return redirect('agreements_list')

    selected_ids = request.POST.getlist('selected_ids')
    if not selected_ids:
        raw_ids = request.POST.get('selected_ids_str', '')
        if raw_ids:
            selected_ids = [x.strip() for x in raw_ids.split(',') if x.strip()]

    if not selected_ids:
        messages.warning(request, "لم يتم تحديد أي اتفاقيات لتحديث حالتها.")
        return redirect('agreements_list')

    # Strictly scope target agreements (manage scope for bulk mutation)
    scoped_agreements = get_scoped_queryset(Agreement.objects.filter(pk__in=selected_ids), request.user, 'agreement', scope_type='manage')

    status_names = {
        'new': 'جديدة',
        'done': 'منجزة',
        'approved': 'منجزة',
        'disapproved': 'جديدة',
    }

    target_status = 'done' if new_status in ['done', 'approved'] else 'new'
    action_act = 'done' if target_status == 'done' else 'reopen'

    updated_count = 0
    skipped_self = 0
    now = timezone.now()

    for ag in scoped_agreements:
        # Check action permission & anti-self-approval
        if not can_user_access_object(request.user, ag, action_act):
            skipped_self += 1
            continue

        status_before = ag.status
        if status_before == target_status:
            continue

        ag.status = target_status
        ag.updated_by = request.user
        ag.updated_at = now
        if target_status == 'done':
            ag.approved_by = request.user
            ag.approved_at = now
            ag.waiting_for_reapproval = False
        else:
            ag.approved_by = None
            ag.approved_at = None
            ag.waiting_for_reapproval = False

        ag.save()
        updated_count += 1

        ApprovalAuditLog.objects.create(
            record_type='agreement',
            agreement=ag,
            action='approved' if target_status == 'done' else 'status_changed',
            actor=request.user,
            status_before=status_before,
            status_after=target_status,
            reason=f"تحديث جماعي للحالة إلى '{status_names.get(target_status, target_status)}'",
            changes=[{'field': 'الحالة', 'old': status_names.get(status_before, status_before), 'new': status_names.get(target_status, target_status)}],
            ip_address=request.META.get('REMOTE_ADDR'),
        )
        AuditLogService.log(
            action_type='AGREEMENT_APPROVED' if target_status == 'done' else 'AGREEMENT_STATUS_CHANGED',
            module='activities',
            actor=request.user,
            record_id=ag.id,
            record_name=f"اتفاقية #{ag.serial_num}",
            description=f"تحديث حالة الاتفاقية من '{status_before}' إلى '{target_status}' (تحديث جماعي)",
            previous_values={'status': status_before},
            new_values={'status': target_status},
            status='SUCCESS',
            request=request,
        )

    if skipped_self > 0:
        messages.warning(request, f"تم تخطي {skipped_self} اتفاقية لا تملك صلاحية اعتمادها أو أنك منشئها (منع الاعتماد الذاتي).")

    if updated_count > 0:
        messages.success(request, f"تم تغيير حالة {updated_count} اتفاقية إلى '{status_names.get(target_status, target_status)}' بنجاح.")
    elif skipped_self == 0:
        messages.info(request, "لم يتم تعديل أي اتفاقية (قد تكون بالحالة المطلوبة بالفعل).")

    return redirect('agreements_list')


@require_permission('activities:agreements/view')
def agreement_detail(request, pk):
    """View details of a specific agreement with timeline and permission gating."""
    agreement = get_object_or_404(Agreement.objects.select_related('customer', 'type', 'created_by', 'updated_by', 'approved_by'), pk=pk)
    if not can_user_access_object(request.user, agreement, 'view'):
        return render_forbidden_response(request, "لا يمكنك عرض هذه الاتفاقية خارج نطاق اختصاصك أو منطقتك الجغرافية.")

    can_approve_this = can_manage_approvals(request.user, 'agreements') and can_user_access_object(request.user, agreement, 'approve')
    can_edit = can_edit_agreement(request.user, agreement)[0]
    can_delete = can_delete_agreement(request.user, agreement)[0]
    timeline_events = build_agreement_timeline(agreement)

    return render(request, 'activities/agreement_detail.html', {
        'agreement': agreement,
        'can_manage_approvals': can_manage_approvals(request.user, 'agreements'),
        'can_approve_this': can_approve_this,
        'can_edit': can_edit,
        'can_delete': can_delete,
        'timeline_events': timeline_events,
    })


@require_permission('activities:agreements/create')
def agreement_create(request):
    """Full-page agreement creation."""
    if request.method == 'POST':
        form = AgreementForm(request.POST, user=request.user)
        if form.is_valid():
            agreement = form.save(commit=False)
            agreement.created_by = request.user
            agreement.updated_by = request.user

            from master_data.models import LocationSettings
            loc_settings = LocationSettings.get_settings()
            if not loc_settings.require_manager_approval_for_agreements or has_perm_or_admin(request.user, 'activities:agreements/approve'):
                agreement.status = 'done'
                agreement.approved_by = request.user
                agreement.approved_at = timezone.now()
            else:
                agreement.status = 'new'

            agreement.save()

            ApprovalAuditLog.objects.create(
                record_type='agreement',
                agreement=agreement,
                action='created',
                actor=request.user,
                status_before='',
                status_after=agreement.status,
                reason='إنشاء اتفاقية جديدة',
                changes=[
                    {'field': 'العنوان', 'old': '-', 'new': agreement.title},
                    {'field': 'العميل', 'old': '-', 'new': agreement.customer.name},
                    {'field': 'المبلغ', 'old': '-', 'new': f"{agreement.amount} ج.م"},
                    {'field': 'الحالة', 'old': '-', 'new': agreement.status_display_ar},
                ],
                ip_address=request.META.get('REMOTE_ADDR'),
            )
            AuditLogService.log(
                action='create',
                action_type='AGREEMENT_CREATED',
                module='activities',
                actor=request.user,
                record_id=agreement.pk,
                record_name=f"اتفاقية #{agreement.serial_num}",
                description=f"إنشاء الاتفاقية #{agreement.serial_num} للعميل {agreement.customer.name}",
                new_values={'title': agreement.title, 'amount': str(agreement.amount), 'status': agreement.status, 'customer': agreement.customer.name},
                status='SUCCESS',
                request=request,
            )
            messages.success(request, f"تم إنشاء الاتفاقية #{agreement.serial_num} بنجاح.")
            return redirect('agreement_detail', pk=agreement.pk)
    else:
        form = AgreementForm(initial={'date': timezone.now().date()}, user=request.user)
    return render(request, 'activities/agreement_form.html', {
        'form': form,
        'title': 'إضافة اتفاقية جديدة',
        'selected_contact': None,
    })


@require_permission('activities:agreements/edit')
def agreement_edit(request, pk):
    """Edit agreement (allowed strictly if status is unapproved: new or disapproved)."""
    agreement = get_object_or_404(Agreement, pk=pk)
    if not can_user_access_object(request.user, agreement, 'view'):
        return render_forbidden_response(request, "لا يمكنك تعديل هذه الاتفاقية خارج نطاق اختصاصك أو منطقتك الجغرافية.")

    if agreement.status not in ('new', 'disapproved'):
        messages.warning(request, "لا يمكن تعديل الاتفاقية بعد إنجازها. يرجى إعادة فتحها أولاً.")
        return redirect('agreement_detail', pk=agreement.pk)

    allowed, reason = can_edit_agreement(request.user, agreement)
    if not allowed:
        return render_forbidden_response(request, reason)

    before_snap = _agreement_snapshot(agreement)

    if request.method == 'POST':
        form = AgreementForm(request.POST, instance=agreement, user=request.user)
        if form.is_valid():
            agreement = form.save(commit=False)
            agreement.updated_by = request.user

            # If editing a disapproved agreement, transition back to pending approval
            if before_snap['status'] == 'disapproved':
                agreement.status = 'new'
                agreement.waiting_for_reapproval = True
                agreement.approved_by = None
                agreement.approved_at = None

            agreement.save()
            after_snap = _agreement_snapshot(agreement)
            diffs = _diff_agreement_fields(before_snap, after_snap)

            if diffs:
                action_choice = 'resubmitted' if before_snap['status'] == 'disapproved' else (
                    'edited_by_manager' if is_manager_or_higher(request.user) else 'submitted'
                )
                ApprovalAuditLog.objects.create(
                    record_type='agreement',
                    agreement=agreement,
                    action=action_choice,
                    actor=request.user,
                    status_before=before_snap['status'],
                    status_after=agreement.status,
                    reason=f"تعديل بيانات الاتفاقية ({len(diffs)} حقول معدلة)",
                    changes=diffs,
                    approval_required=(agreement.status == 'new'),
                    ip_address=request.META.get('REMOTE_ADDR'),
                )
                AuditLogService.log(
                    action='update',
                    action_type='AGREEMENT_UPDATED',
                    module='activities',
                    actor=request.user,
                    record_id=agreement.pk,
                    record_name=f"اتفاقية #{agreement.serial_num}",
                    description=f"تحديث بيانات الاتفاقية #{agreement.serial_num} ({len(diffs)} حقول)",
                    previous_values=before_snap,
                    new_values=after_snap,
                    status='SUCCESS',
                    request=request,
                )

            messages.success(request, f"تم تحديث الاتفاقية #{agreement.serial_num} بنجاح.")
            return redirect('agreement_detail', pk=agreement.pk)
    else:
        form = AgreementForm(instance=agreement, user=request.user)
    return render(request, 'activities/agreement_form.html', {
        'form': form,
        'agreement': agreement,
        'title': f'تعديل الاتفاقية #{agreement.serial_num}',
        'selected_contact': agreement.customer,
    })


@require_permission('activities:agreements/approve')
def agreement_action(request, pk, action):
    """
    Status transitions: approve, disapprove, done, reopen.
    POST method required.
    Anti-self-approval enforced via can_user_access_object.
    """
    if request.method != 'POST':
        messages.error(request, "طريقة طلب غير صالحة. يلزم استخدام POST لتغيير الحالة.")
        return redirect('agreement_detail', pk=pk)

    if not can_manage_approvals(request.user, 'agreements'):
        messages.error(request, "عذراً، لا تملك صلاحية تغيير حالة الاعتماد (خاص بالمدراء ومسؤولي النظام).")
        next_url = request.POST.get('next') or request.GET.get('next', 'agreement_detail')
        if next_url == 'list':
            return redirect('agreements_list')
        return redirect('agreement_detail', pk=pk)

    agreement = get_object_or_404(Agreement, pk=pk)
    if not can_user_access_object(request.user, agreement, action):
        return render_forbidden_response(request, "لا يمكنك تغيير حالة هذه الاتفاقية خارج نطاق اختصاصك أو اعتماد اتفاقيتك الخاصة.")

    status_before = agreement.status
    now = timezone.now()
    reason = request.POST.get('reason', '').strip()

    status_map = {
        'new': 'جديدة',
        'done': 'منجزة',
        'approved': 'منجزة',
        'disapproved': 'جديدة',
    }

    if action in ('done', 'approve'):
        agreement.status = 'done'
        agreement.approved_by = request.user
        agreement.approved_at = now
        agreement.waiting_for_reapproval = False
        agreement.updated_by = request.user
        agreement.save()
        messages.success(request, f"تم إنجاز الاتفاقية #{agreement.serial_num} بنجاح.")
        log_action = 'status_changed'
        log_reason = reason or "إنجاز الاتفاقية بنجاح"
    elif action in ('reopen', 'new', 'disapprove'):
        agreement.status = 'new'
        agreement.waiting_for_reapproval = False
        agreement.approved_by = None
        agreement.approved_at = None
        agreement.approval_notes = reason
        agreement.updated_by = request.user
        agreement.save()
        messages.info(request, f"تم إعادة فتح الاتفاقية #{agreement.serial_num} وباتت جديدة.")
        log_action = 'status_changed'
        log_reason = reason or "إعادة فتح الاتفاقية"
    else:
        messages.error(request, "إجراء غير معروف.")
        return redirect('agreement_detail', pk=agreement.pk)

    ApprovalAuditLog.objects.create(
        record_type='agreement',
        agreement=agreement,
        action=log_action,
        actor=request.user,
        status_before=status_before,
        status_after=agreement.status,
        reason=log_reason,
        changes=[{'field': 'الحالة', 'old': status_map.get(status_before, status_before), 'new': status_map.get(agreement.status, agreement.status)}],
        ip_address=request.META.get('REMOTE_ADDR'),
    )

    AuditLogService.log(
        action_type='AGREEMENT_APPROVED' if action == 'approve' else ('AGREEMENT_REJECTED' if action == 'disapprove' else 'AGREEMENT_STATUS_CHANGED'),
        module='activities',
        actor=request.user,
        record_id=agreement.id,
        record_name=f"اتفاقية #{agreement.serial_num}",
        description=f"تغيير حالة الاتفاقية من '{status_before}' إلى '{agreement.status}': {log_reason}",
        previous_values={'status': status_before},
        new_values={'status': agreement.status},
        status='SUCCESS',
        request=request,
    )

    next_url = request.POST.get('next') or request.GET.get('next', 'agreement_detail')
    if next_url == 'list':
        return redirect('agreements_list')
    return redirect('agreement_detail', pk=agreement.pk)


@require_permission('activities:agreements/delete')
def agreement_delete(request, pk):
    """
    Delete an agreement strictly if in unapproved state (new or disapproved).
    POST method required. Enforces scope & status rules, cleans up ERPAttachments,
    and writes permanent SecurityAuditLog trail.
    """
    is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'application/json' in request.headers.get('accept', '')
    if request.method != 'POST':
        if is_ajax:
            return JsonResponse({'success': False, 'message': 'طريقة طلب غير صالحة للحذف. يلزم استخدام POST.'}, status=405)
        messages.error(request, "طريقة طلب غير صالحة للحذف. يلزم استخدام POST.")
        return redirect('agreement_detail', pk=pk)

    agreement = get_object_or_404(Agreement, pk=pk)
    if not can_user_access_object(request.user, agreement, 'view'):
        return render_forbidden_response(request, "لا يمكنك حذف هذه الاتفاقية خارج نطاق اختصاصك.")

    if agreement.status not in ('new', 'disapproved'):
        msg = "لا يمكن حذف اتفاقية بعد إنجازها أو اعتمادها."
        if is_ajax:
            return JsonResponse({'success': False, 'message': msg}, status=400)
        messages.error(request, msg)
        return redirect('agreement_detail', pk=agreement.pk)

    allowed, reason = can_delete_agreement(request.user, agreement)
    if not allowed:
        return render_forbidden_response(request, reason)

    from django.contrib.contenttypes.models import ContentType
    from master_data.models import ERPAttachment
    from master_data.media_service import delete_attachment

    with transaction.atomic():
        agreement = Agreement.objects.select_for_update().select_related('customer', 'type').get(pk=agreement.pk)
        serial = agreement.serial_num
        before_snap = _agreement_snapshot(agreement)

        ct_agr = ContentType.objects.get_for_model(Agreement)
        for att in ERPAttachment.objects.filter(content_type=ct_agr, object_id=agreement.pk):
            delete_attachment(att, request.user, request=request)

        AuditLogService.log(
            action='delete',
            action_type='AGREEMENT_DELETED',
            module='activities',
            actor=request.user,
            record_id=agreement.id,
            record_name=f"اتفاقية #{serial}",
            description=f"حذف الاتفاقية #{serial} (الحالة: {agreement.status})",
            previous_values=before_snap,
            status='SUCCESS',
            request=request,
        )

        agreement.delete()

    msg = f"تم حذف الاتفاقية #{serial} بنجاح."
    if is_ajax:
        return JsonResponse({'success': True, 'message': msg, 'redirect_url': reverse('agreements_list')})
    messages.success(request, msg)
    return redirect('agreements_list')


@require_permission('activities:agreements/export')
def agreements_export(request):
    """Export filtered agreements to Excel (.xlsx) with styled formatting."""
    qs = Agreement.objects.select_related('customer', 'type', 'created_by').all().order_by('-serial_num')
    qs = get_scoped_queryset(qs, request.user, 'agreement')

    # Apply same filters with Arabic normalization
    q = (request.GET.get('search') or request.GET.get('q') or '').strip()
    if q:
        qs = filter_by_arabic_search(
            qs,
            ['title', 'description', 'customer__name', 'customer__code'],
            q,
            raw_fields=['customer__code'],
            numeric_id_field='serial_num'
        )
    if request.GET.get('type'):
        qs = qs.filter(type_id=request.GET.get('type'))
    if request.GET.get('status'):
        qs = qs.filter(status=request.GET.get('status'))
    if request.GET.get('creator'):
        qs = qs.filter(created_by_id=request.GET.get('creator'))
    parsed_from, parsed_to, _, _, _ = resolve_date_range(request, default_preset='all_time')
    if parsed_from:
        qs = qs.filter(date__gte=parsed_from)
    if parsed_to:
        qs = qs.filter(date__lte=parsed_to)

    from master_data.excel_utils import export_to_excel_response
    columns = [
        {'header': '#', 'key': lambda a: f"#{a.serial_num}", 'width': 12, 'align': 'center'},
        {'header': 'العميل', 'key': lambda a: a.customer.name if a.customer else '', 'width': 28, 'align': 'right'},
        {'header': 'كود العميل', 'key': lambda a: a.customer.code if a.customer else '', 'width': 16, 'align': 'center'},
        {'header': 'العنوان', 'key': 'title', 'width': 28, 'align': 'right'},
        {'header': 'النوع', 'key': lambda a: a.type.name if a.type else '', 'width': 18, 'align': 'center'},
        {'header': 'المبلغ (ج.م)', 'key': lambda a: float(a.amount or 0), 'format': '#,##0.00', 'width': 18, 'align': 'right'},
        {'header': 'التاريخ', 'key': lambda a: a.date.strftime('%Y-%m-%d') if a.date else '', 'width': 16, 'align': 'center'},
        {'header': 'المنشئ', 'key': lambda a: a.created_by.get_full_name() or a.created_by.username if a.created_by else '', 'width': 22, 'align': 'right'},
        {'header': 'الحالة', 'key': lambda a: a.status_display_ar, 'width': 16, 'align': 'center'},
    ]
    return export_to_excel_response(
        qs,
        columns,
        filename="agreements_export",
        sheet_title="الاتفاقيات",
        report_title="سجل الاتفاقيات التجارية",
        user=request.user,
    )


# -----------------------------------------------------------------------------
# PLANNED VISITS MODULE (خطة الزيارات)
# -----------------------------------------------------------------------------

@require_permission('activities:planned/list')
def planned_visits_list(request):
    """
    Day-by-day accordion planner view for selected representative and date range,
    with Bulk Daily Planning (Section 8) and strict geographical scoping (Section 7).
    Matches https://weapharma.bricks-rep.com/planned-visits
    """
    is_super = request.user.is_superuser or getattr(request.user, 'is_super_admin', False)
    from accounts.scope_service import ScopeResolutionService
    view_scope = ScopeResolutionService.get_user_scope(request.user, 'activities', 'view')
    can_view_others = (is_super or view_scope in ['area', 'all'])

    all_reps = get_visible_assignees_queryset(request.user, module='activities')

    rep_id = (request.GET.get('assignee') or '').strip()
    is_all_reps_view = False
    if rep_id:
        if rep_id == 'all':
            if not can_view_others:
                selected_rep = request.user
            else:
                selected_rep = None
                is_all_reps_view = True
        else:
            if not can_view_others and str(rep_id) != str(request.user.id):
                return render_forbidden_response(request, "غير مصرح لك بعرض خطة زيارات مندوب آخر.")
            selected_rep = get_object_or_404(User, pk=rep_id)
            if not is_super and view_scope != 'all' and not all_reps.filter(pk=selected_rep.pk).exists():
                return render_forbidden_response(request, "غير مصرح لك بعرض خطة زيارات مندوب خارج نطاق منطقتك الجغرافية.")
    else:
        if can_view_others:
            selected_rep = None
            is_all_reps_view = True
        else:
            selected_rep = request.user

    # Date range (defaults to current month)
    today = timezone.now().date()
    start_date_str = request.GET.get('date_from')
    end_date_str = request.GET.get('date_to')

    if start_date_str:
        try:
            start_date = datetime.datetime.strptime(start_date_str, '%Y-%m-%d').date()
        except ValueError:
            start_date = today
    else:
        start_date = today

    if end_date_str:
        try:
            end_date = datetime.datetime.strptime(end_date_str, '%Y-%m-%d').date()
        except ValueError:
            end_date = start_date + datetime.timedelta(days=15)
    else:
        end_date = start_date + datetime.timedelta(days=15)

    # Fetch all days in range for selected rep (or all reps in authorized scope when viewing all)
    if is_all_reps_view:
        plan_days = PlannedVisitDay.objects.filter(
            assignee__in=all_reps,
            date__range=[start_date, end_date]
        ).select_related('assignee').prefetch_related(
            'items__contact', 'items__template', 'items__visit', 'items__plan_day__assignee', 'items__plan'
        )
    else:
        plan_days = PlannedVisitDay.objects.filter(
            assignee=selected_rep,
            date__range=[start_date, end_date]
        ).select_related('assignee').prefetch_related(
            'items__contact', 'items__template', 'items__visit', 'items__plan_day__assignee', 'items__plan'
        )

    plan_days_by_date = {}
    for p in plan_days:
        plan_days_by_date.setdefault(p.date, []).append(p)

    # Scoped VisitPlan query for grouping visits by plan under each day (Requirement 4)
    scoped_plans_qs = get_scoped_queryset(VisitPlan.objects.all(), request.user, 'visitplan', 'view').filter(
        date__range=[start_date, end_date]
    ).select_related('assignee', 'created_by', 'approved_by').prefetch_related(
        'planned_items__contact', 'planned_items__template', 'planned_items__visit',
        'planned_items__contact__area', 'planned_items__contact__brick', 'visits'
    )
    if not is_all_reps_view:
        scoped_plans_qs = scoped_plans_qs.filter(assignee=selected_rep)
    elif not is_super and view_scope != 'all':
        scoped_plans_qs = scoped_plans_qs.filter(assignee__in=all_reps)

    plans_by_date = {}
    for pl in scoped_plans_qs:
        plans_by_date.setdefault(pl.date, []).append(pl)

    # Build calendar day cards and scheduled map for duplicate prevention
    current_date = start_date
    days_list = []
    scheduled_contacts_by_date = {}
    arabic_weekdays = {
        0: 'الاثنين',
        1: 'الثلاثاء',
        2: 'الأربعاء',
        3: 'الخميس',
        4: 'الجمعة',
        5: 'السبت',
        6: 'الأحد'
    }

    can_manage_planned = has_perm_or_admin(request.user, 'activities:planned/manage')
    user_can_delete_visits = has_perm_or_admin(request.user, 'activities:visits/delete')

    while current_date <= end_date:
        day_plans = plans_by_date.get(current_date, [])
        plan_groups = []
        all_day_items = []
        covered_item_ids = set()

        for pl in day_plans:
            pl_items = list(pl.planned_items.all().order_by('order', 'id'))
            if not pl_items:
                continue
            all_day_items.extend(pl_items)
            for it in pl_items:
                covered_item_ids.add(it.id)
                requires_visit_del = bool(
                    it.visit and (it.visit.status != 'planned' or it.visit.ended_at is not None)
                )
                it.can_delete_item = (
                    can_manage_planned
                    and can_user_access_object(request.user, it, 'manage')
                    and (
                        not requires_visit_del
                        or (user_can_delete_visits and can_user_access_object(request.user, it.visit, 'delete'))
                    )
                )
            can_approve_pl = can_manage_approvals(request.user) and can_user_access_object(request.user, pl, 'approve')
            plan_groups.append({
                'plan': pl,
                'plan_id': pl.plan_id,
                'comment': pl.comment,
                'approval_status': pl.approval_status,
                'assignee': pl.assignee,
                'can_approve': can_approve_pl,
                'items': pl_items,
                'items_count': len(pl_items),
            })

        # Check for any legacy unlinked items in PlannedVisitDay
        legacy_days = plan_days_by_date.get(current_date, [])
        unlinked_items = []
        for pvd in legacy_days:
            for it in pvd.items.all():
                if it.id not in covered_item_ids:
                    requires_visit_del = bool(
                        it.visit and (it.visit.status != 'planned' or it.visit.ended_at is not None)
                    )
                    it.can_delete_item = (
                        can_manage_planned
                        and can_user_access_object(request.user, it, 'manage')
                        and (
                            not requires_visit_del
                            or (user_can_delete_visits and can_user_access_object(request.user, it.visit, 'delete'))
                        )
                    )
                    unlinked_items.append(it)
                    all_day_items.append(it)

        if unlinked_items:
            plan_groups.append({
                'plan': None,
                'plan_id': 'خطة عامة',
                'comment': '',
                'approval_status': 'approved',
                'assignee': selected_rep or (unlinked_items[0].plan_day.assignee if unlinked_items else request.user),
                'can_approve': False,
                'items': unlinked_items,
                'items_count': len(unlinked_items),
            })

        d_key = current_date.strftime('%Y-%m-%d')
        scheduled_contacts_by_date[d_key] = [it.contact_id for it in all_day_items]
        days_list.append({
            'date': current_date,
            'date_str': d_key,
            'weekday_ar': arabic_weekdays[current_date.weekday()],
            'formatted_date': current_date.strftime('%d/%m/%Y'),
            'plans': plan_groups,
            'plan_day': legacy_days[0] if legacy_days else None,
            'items': all_day_items,
            'items_count': len(all_day_items),
            'is_planned': len(all_day_items) > 0,
        })
        current_date += datetime.timedelta(days=1)

    # Contacts for drawer & bulk planner (scoped strictly to user's permitted geographical scope)
    base_contacts_qs = get_visit_eligible_contacts_queryset(
        Contact.objects.select_related('area', 'brick', 'area__parent', 'brick__parent').prefetch_related('addresses__area', 'addresses__brick').exclude(status='inactive'),
        request.user
    )
    contacts_qs = base_contacts_qs

    # Parse multi-select areas and bricks (Requirement I & Additional Requirement A)
    raw_main_areas = request.GET.getlist('main_area') or request.GET.getlist('main_area[]')
    submitted_main_area_ids = []
    for ma in raw_main_areas:
        for p in str(ma).split(','):
            if p.strip().isdigit():
                submitted_main_area_ids.append(int(p.strip()))

    raw_bricks = request.GET.getlist('brick') or request.GET.getlist('brick[]') or request.GET.getlist('area') or request.GET.getlist('area[]')
    submitted_brick_ids = []
    for br in raw_bricks:
        for p in str(br).split(','):
            if p.strip().isdigit():
                submitted_brick_ids.append(int(p.strip()))

    # Security & Scope Validation: Reject forged, unrelated, or unauthorized IDs
    if is_super:
        auth_main_areas_qs = Area.objects.filter(parent__isnull=True)
        auth_bricks_qs = Area.objects.filter(parent__isnull=False).select_related('parent')
    else:
        auth_main_areas_qs = ScopeResolutionService.get_scoped_choices(request.user, 'governorates', 'activities')
        auth_bricks_qs = ScopeResolutionService.get_scoped_choices(request.user, 'bricks', 'activities')

    auth_main_area_ids = set(auth_main_areas_qs.values_list('id', flat=True))
    auth_brick_map = dict(auth_bricks_qs.values_list('id', 'parent_id'))

    # Reject unauthorized main area IDs
    main_area_ids = [aid for aid in submitted_main_area_ids if aid in auth_main_area_ids]

    # Reject unauthorized brick IDs, and verify every selected brick belongs to one of the selected areas
    brick_ids = []
    for bid in submitted_brick_ids:
        if bid in auth_brick_map:
            p_id = auth_brick_map[bid]
            if not main_area_ids or p_id in main_area_ids:
                brick_ids.append(bid)

    main_area_filter = str(main_area_ids[0]) if len(main_area_ids) == 1 else ''
    area_filter = str(brick_ids[0]) if len(brick_ids) == 1 else ''

    # Parse multi-select Account Type (Requirement 5)
    raw_account_types = request.GET.getlist('account_type') or request.GET.getlist('account_type[]')
    selected_account_types = []
    for at in raw_account_types:
        for p in str(at).split(','):
            p = p.strip()
            if p and p != 'all' and p not in selected_account_types:
                selected_account_types.append(p)

    account_type_filter = selected_account_types[0] if selected_account_types else ''
    category_filter = (request.GET.get('customer_category') or '').strip()
    specialty_filter = (request.GET.get('specialty') or '').strip()
    contact_status_filter = (request.GET.get('contact_status') or '').strip().lower()
    if contact_status_filter not in ('customer', 'lead'):
        contact_status_filter = ''
    search_contact = (request.GET.get('contact_search') or '').strip()

    if main_area_ids:
        contacts_qs = contacts_qs.filter(
            Q(area_id__in=main_area_ids) |
            Q(area__parent_id__in=main_area_ids) |
            Q(brick_id__in=main_area_ids) |
            Q(brick__parent_id__in=main_area_ids) |
            Q(addresses__area_id__in=main_area_ids) |
            Q(addresses__brick__parent_id__in=main_area_ids)
        ).distinct()

    if brick_ids:
        contacts_qs = contacts_qs.filter(
            Q(brick_id__in=brick_ids) |
            Q(addresses__brick_id__in=brick_ids)
        ).distinct()

    if selected_account_types:
        contacts_qs = contacts_qs.filter(account_type__in=selected_account_types)
    if contact_status_filter:
        contacts_qs = contacts_qs.filter(status=contact_status_filter)
    if category_filter:
        contacts_qs = contacts_qs.filter(customer_category__iexact=category_filter)
    if specialty_filter:
        contacts_qs = contacts_qs.filter(specialty__icontains=specialty_filter)
    if search_contact:
        contacts_qs = contacts_qs.filter(
            Q(name__icontains=search_contact) |
            Q(code__icontains=search_contact) |
            Q(phone__icontains=search_contact) |
            Q(mobile__icontains=search_contact)
        ).distinct()

    # AJAX "Select All Results" IDs endpoint (Requirement E)
    if (request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.GET.get('format') == 'json') and request.GET.get('action') == 'select_all_ids':
        all_rows = list(contacts_qs.order_by('name').values('id', 'account_type'))
        return JsonResponse({
            'success': True,
            'total_count': len(all_rows),
            'contacts': [
                {'id': r['id'], 'account_type': (r['account_type'] or 'عميل')}
                for r in all_rows
            ],
        })

    # AJAX Incremental / Display-All Client Loader (Requirements 2 & E)
    if (request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.GET.get('format') == 'json') and request.GET.get('action') == 'load_contacts':
        show_all = request.GET.get('show_all') in ('1', 'true', 'True') or request.GET.get('limit') == 'all'
        try:
            offset = max(0, int(request.GET.get('offset', 0)))
        except (ValueError, TypeError):
            offset = 0
        total_count = contacts_qs.count()
        if show_all:
            batch = list(contacts_qs.order_by('name')[offset:])
            limit = len(batch)
        else:
            try:
                limit = max(1, min(100, int(request.GET.get('limit', 10))))
            except (ValueError, TypeError):
                limit = 10
            batch = list(contacts_qs.order_by('name')[offset:offset+limit])
        items_data = []
        for c in batch:
            brick_name = c.brick.name if c.brick else ''
            area_name = c.area.name if c.area else ''
            if brick_name and area_name:
                location_label = f"{brick_name} ({area_name})"
            elif brick_name:
                location_label = brick_name
            elif area_name:
                location_label = area_name
            else:
                location_label = ''

            items_data.append({
                'id': c.id,
                'name': c.name,
                'code': c.code or c.formatted_number or '',
                'account_type': c.account_type or 'عميل',
                'customer_category': c.customer_category or '',
                'specialty': c.specialty or 'عام',
                'brick_name': brick_name,
                'area_name': area_name,
                'location_label': location_label,
                'parent_area_name': c.area.parent.name if c.area and c.area.parent else (c.brick.parent.name if c.brick and c.brick.parent else ''),
            })
        return JsonResponse({
            'success': True,
            'total_count': total_count,
            'offset': offset,
            'limit': limit,
            'has_more': (offset + len(batch)) < total_count,
            'contacts': items_data
        })

    # Requirement 2: Initially display only first 10 clients
    total_clients_count = contacts_qs.count()
    initial_contacts = list(contacts_qs.order_by('name')[:10])
    has_more_clients = total_clients_count > 10

    # Initial chips for already selected items
    selected_main_areas_chips = []
    if main_area_ids:
        selected_main_areas_chips = list(Area.objects.filter(id__in=main_area_ids).values('id', 'name', 'code'))

    selected_bricks_chips = []
    if brick_ids:
        selected_bricks_chips = [
            {
                'id': b.id,
                'name': b.name,
                'code': b.code or '',
                'parent_id': b.parent_id,
                'parent_name': b.parent.name if b.parent else ''
            }
            for b in Area.objects.filter(id__in=brick_ids).select_related('parent')
        ]

    # Templates eligible for current user's role
    visit_templates = [t for t in VisitTemplate.objects.filter(active=True).prefetch_related('restricted_roles').order_by('name') if t.is_user_eligible(request.user)]

    context = {
        'selected_rep': selected_rep,
        'is_all_reps_view': is_all_reps_view,
        'can_view_others': can_view_others,
        'all_reps': all_reps,
        'start_date': start_date.strftime('%Y-%m-%d'),
        'end_date': end_date.strftime('%Y-%m-%d'),
        'today': today,
        'today_str': today.strftime('%Y-%m-%d'),
        'days_list': days_list,
        'drawer_contacts': initial_contacts,
        'total_clients_count': total_clients_count,
        'has_more_clients': has_more_clients,
        'account_types': ACCOUNT_TYPES,
        'customer_categories': CUSTOMER_CATEGORIES,
        'specialties': SPECIALTIES,
        'visit_templates': visit_templates,
        'selected_main_area': main_area_filter,
        'selected_area': area_filter,
        'selected_main_areas': [str(x) for x in main_area_ids],
        'selected_bricks': [str(x) for x in brick_ids],
        'selected_main_areas_chips': selected_main_areas_chips,
        'selected_bricks_chips': selected_bricks_chips,
        'selected_account_type': account_type_filter,
        'selected_account_types': selected_account_types,
        'selected_contact_status': contact_status_filter,
        'selected_customer_category': category_filter,
        'selected_specialty': specialty_filter,
        'selected_contact_search': search_contact,
        'scheduled_contacts_json': json.dumps(scheduled_contacts_by_date),
    }
    return render(request, 'activities/planned_visits_list.html', context)


@require_permission(['activities:planned/list', 'activities:planned/manage', 'activities:visits/create', 'activities:visits/list'])
def planned_visits_search_areas_api(request):
    """
    Multiselect autocomplete endpoint for Main Areas (Governorates) (Requirements C & D).
    Immediately returns available authorized options on open (even when q is empty),
    and filters suggestions when search query q is entered.
    """
    q = (request.GET.get('q') or '').strip()

    from accounts.scope_service import ScopeResolutionService
    is_super = request.user.is_superuser or getattr(request.user, 'is_super_admin', False)
    if is_super:
        qs = Area.objects.filter(parent__isnull=True).order_by('name')
    else:
        qs = ScopeResolutionService.get_scoped_choices(request.user, 'governorates', 'activities')

    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(code__icontains=q))

    matches = qs.order_by('name')[:100]
    results = [{'id': a.id, 'name': a.name, 'code': a.code or ''} for a in matches]
    return JsonResponse({'results': results})


@require_permission(['activities:planned/list', 'activities:planned/manage', 'activities:visits/create', 'activities:visits/list'])
def planned_visits_search_bricks_api(request):
    """
    Multiselect autocomplete endpoint for Bricks (Requirements C & D).
    Enforces strict authorized scope via ScopeResolutionService:
    - Immediately displays available authorized options even when search query q is empty.
    - If Main Areas are selected, restricts bricks strictly to children of those areas (within user's authorized scope).
    - If no Main Area is selected, returns all bricks available within user's authorized scope
      (never expanding a representative's brick scope to sibling bricks in the same governorate).
    """
    q = (request.GET.get('q') or '').strip()

    raw_main_areas = request.GET.getlist('main_area') or request.GET.getlist('main_area[]')
    main_area_ids = []
    for ma in raw_main_areas:
        for p in str(ma).split(','):
            if p.strip().isdigit():
                main_area_ids.append(int(p.strip()))

    from accounts.scope_service import ScopeResolutionService
    is_super = request.user.is_superuser or getattr(request.user, 'is_super_admin', False)
    if is_super:
        qs = Area.objects.filter(parent__isnull=False).select_related('parent')
        auth_main_areas = set(Area.objects.filter(parent__isnull=True).values_list('id', flat=True))
    else:
        qs = ScopeResolutionService.get_scoped_choices(request.user, 'bricks', 'activities')
        auth_main_areas = set(ScopeResolutionService.get_scoped_choices(request.user, 'governorates', 'activities').values_list('id', flat=True))

    if main_area_ids:
        valid_main_ids = [aid for aid in main_area_ids if aid in auth_main_areas]
        if valid_main_ids:
            qs = qs.filter(parent_id__in=valid_main_ids)
        else:
            return JsonResponse({'results': []})

    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(code__icontains=q))

    matches = qs.order_by('name')[:150]
    results = [{
        'id': b.id,
        'name': b.name,
        'code': b.code or '',
        'parent_id': b.parent_id,
        'parent_name': b.parent.name if b.parent else ''
    } for b in matches]
    return JsonResponse({'results': results})


@require_permission(['activities:visits/create', 'activities:visits/list', 'activities:planned/list', 'settings:visitsTemplates/manage'])
def visit_templates_api(request):
    """
    API endpoint returning active visit templates.
    Supports filtering by:
    - contact_id / contact (single client)
    - contact_ids / contact_ids[] (multiple clients for bulk planning -> common eligible templates)
    - account_type
    Returns template metadata, questions schema, product detailing capabilities,
    and dynamic allowed distance threshold (Section 3.A & Requirement 1).
    """
    from master_data.models import LocationSettings
    from accounts.permissions import get_visit_eligible_contacts_queryset
    loc_settings = LocationSettings.get_settings()

    # Parse contact_ids (multiple or single)
    raw_cids = request.GET.getlist('contact_ids') or request.GET.getlist('contact_ids[]') or request.GET.get('contact_ids')
    cids_list = []
    if isinstance(raw_cids, str):
        cids_list = [c.strip() for c in raw_cids.split(',') if c.strip()]
    elif isinstance(raw_cids, (list, tuple)):
        for item in raw_cids:
            if isinstance(item, str) and ',' in item:
                cids_list.extend([x.strip() for x in item.split(',') if x.strip()])
            elif item:
                cids_list.append(str(item).strip())

    contact_id = request.GET.get('contact_id') or request.GET.get('contact')
    if contact_id and str(contact_id).strip() not in cids_list:
        cids_list.append(str(contact_id).strip())

    valid_cids = [int(x) for x in cids_list if x.isdigit()]
    contacts = []
    if valid_cids:
        contacts = list(get_visit_eligible_contacts_queryset(
            Contact.objects.filter(pk__in=valid_cids).select_related('area', 'area__parent'),
            request.user
        ))

    account_type = request.GET.get('account_type', '').strip().lower()

    qs = VisitTemplate.objects.filter(active=True).prefetch_related('questions', 'restricted_roles', 'suggested_products')

    results = []
    for tmpl in qs:
        # 1. Role restriction check (centralized model method)
        if not tmpl.is_user_eligible(request.user):
            continue

        # 2. Client / Group eligibility check
        if contacts:
            # Common eligible template: must be eligible for ALL selected clients (Requirement 1)
            is_eligible = all(tmpl.is_contact_eligible(c, user=request.user) for c in contacts)
        elif account_type:
            is_eligible = tmpl.is_account_type_eligible(account_type)
        else:
            is_eligible = True

        if is_eligible:
            questions_data = []
            for q in tmpl.get_active_questions():
                questions_data.append({
                    'id': q.id,
                    'text_ar': q.text_ar,
                    'text_en': q.text_en,
                    'question_type': q.question_type,
                    'options': q.options or [],
                    'is_required': q.is_required,
                    'is_conditional': q.is_conditional,
                    'conditional_parent_id': q.conditional_parent_id,
                    'conditional_trigger_value': q.conditional_trigger_value,
                    'stage': q.stage,
                    'order': q.order
                })
            effective_tol = loc_settings.get_effective_tolerance(tmpl)
            pool_qs = tmpl.get_suggested_products_pool()
            results.append({
                'id': tmpl.id,
                'name': tmpl.name,
                'display_name_ar': tmpl.display_name_ar,
                'display_name_en': tmpl.display_name_en,
                'allow_unplanned': tmpl.allow_unplanned,
                'enable_product_detailing': tmpl.enable_product_detailing,
                'supports_product_detailing': tmpl.is_product_detailing_supported(),
                'suggested_products': [
                    {'id': p.id, 'name': p.name, 'sku_code': p.sku_code}
                    for p in pool_qs
                ],
                'restrict_account_types': tmpl.restrict_account_types or [],
                'restricted_roles': [r.name for r in tmpl.restricted_roles.all()],
                'has_special_location_settings': tmpl.has_special_location_settings,
                'special_tolerance': tmpl.special_tolerance,
                'effective_tolerance': effective_tol,
                'default_tolerance': loc_settings.tolerance,
                'allow_template_distance_override': loc_settings.allow_template_distance_override,
                'questions': questions_data
            })

    return JsonResponse({
        'results': results,
        'templates': results,
        'count': len(results),
        'default_tolerance': loc_settings.tolerance,
        'allow_template_distance_override': loc_settings.allow_template_distance_override,
    })


@require_permission('activities:planned/manage')
def planned_visit_add_item(request):
    """Add a contact to a specific day's plan with strict parity, geographical scope, and duplicate checks."""
    if request.method == 'POST':
        assignee_id = request.POST.get('assignee_id') or request.user.id
        date_str = request.POST.get('date')
        contact_id = request.POST.get('contact_id')
        template_id = request.POST.get('template_id')
        notes = request.POST.get('notes', '').strip()

        is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'application/json' in request.headers.get('accept', '')

        if not contact_id:
            msg = "يرجى اختيار العميل المطلوب إضافته إلى الخطة."
            if is_ajax:
                return JsonResponse({'success': False, 'message': msg}, status=400)
            messages.error(request, msg)
            return redirect(request.META.get('HTTP_REFERER', '/planned-visits/'))

        if not date_str:
            msg = "يرجى تحديد تاريخ اليوم في الخطة."
            if is_ajax:
                return JsonResponse({'success': False, 'message': msg}, status=400)
            messages.error(request, msg)
            return redirect(request.META.get('HTTP_REFERER', '/planned-visits/'))

        try:
            target_date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            msg = "صيغة التاريخ غير صالحة."
            if is_ajax:
                return JsonResponse({'success': False, 'message': msg}, status=400)
            messages.error(request, msg)
            return redirect(request.META.get('HTTP_REFERER', '/planned-visits/'))

        # Date Validation (Requirement 4): No past dates
        today = timezone.now().date()
        if target_date < today:
            msg = "لا يمكن إضافة خطة زيارة في تاريخ سابق. يرجى اختيار تاريخ اليوم أو تاريخ مستقبلي."
            if is_ajax:
                return JsonResponse({'success': False, 'message': msg}, status=400)
            messages.error(request, msg)
            return redirect(f"{request.META.get('HTTP_REFERER', '/planned-visits/')}#day-{date_str}")

        assignee = get_object_or_404(User, pk=assignee_id)
        is_super = request.user.is_superuser or getattr(request.user, 'is_super_admin', False)
        from accounts.scope_service import ScopeResolutionService
        can_manage_others = (
            is_super or
            has_perm_or_admin(request.user, 'activities:planned/manage') or
            ScopeResolutionService.get_user_scope(request.user, 'activities', 'manage') in ['area', 'all']
        )
        if assignee != request.user:
            if not can_manage_others or (not is_super and not get_user_managed_representatives(request.user, module='activities').filter(pk=assignee.pk).exists()):
                msg = "غير مصرح لك بإضافة زيارات لخطة مندوب آخر خارج نطاق مسؤوليتك الجغرافية."
                if is_ajax:
                    return JsonResponse({'success': False, 'message': msg}, status=403)
                messages.error(request, msg)
                return redirect(request.META.get('HTTP_REFERER', '/planned-visits/'))

        contact = get_object_or_404(Contact, pk=contact_id)
        if contact.status == 'inactive':
            msg = f"لا يمكن جدولة زيارة للعميل '{contact.name}' لأن حالته غير نشط (Inactive)."
            if is_ajax:
                return JsonResponse({'success': False, 'message': msg}, status=400)
            messages.error(request, msg)
            return redirect(request.META.get('HTTP_REFERER', '/planned-visits/'))
        if not can_user_access_contact_for_visit(request.user, contact):
            msg = f"غير مصرح لك بجدولة زيارة للعميل '{contact.name}' لأنه يقع خارج نطاق منطقتك أو خطك الجغرافي."
            if is_ajax:
                return JsonResponse({'success': False, 'message': msg}, status=403)
            messages.error(request, msg)
            return redirect(request.META.get('HTTP_REFERER', '/planned-visits/'))

        # Mandatory template validation & eligibility (Requirement 1)
        if not template_id or not str(template_id).isdigit():
            msg = "اختيار قالب الزيارة إلزامي لإتمام التخطيط."
            if is_ajax:
                return JsonResponse({'success': False, 'message': msg}, status=400)
            messages.error(request, msg)
            return redirect(f"{request.META.get('HTTP_REFERER', '/planned-visits/')}#day-{date_str}")

        template = VisitTemplate.objects.filter(pk=int(template_id), active=True).first()
        if not template or not template.is_user_eligible(request.user):
            msg = "قالب الزيارة المحدد غير موجود أو غير مصرح لدورك الوظيفي باستخدامه."
            if is_ajax:
                return JsonResponse({'success': False, 'message': msg}, status=403)
            messages.error(request, msg)
            return redirect(f"{request.META.get('HTTP_REFERER', '/planned-visits/')}#day-{date_str}")

        if not template.is_contact_eligible(contact, user=request.user):
            allowed_str = ", ".join(template.restrict_account_types) if template.restrict_account_types else "الكل"
            msg = f"قالب الزيارة '{template.display_name_ar}' غير مصرح به لنوع حساب العميل ({contact.account_type or 'غير محدد'}). الأنواع المصرح بها: {allowed_str}."
            if is_ajax:
                return JsonResponse({'success': False, 'message': msg}, status=400)
            messages.error(request, msg)
            return redirect(f"{request.META.get('HTTP_REFERER', '/planned-visits/')}#day-{date_str}")

        # Get or create PlannedVisitDay
        plan_day, _ = PlannedVisitDay.objects.get_or_create(
            assignee=assignee,
            date=target_date,
            defaults={'created_by': request.user}
        )

        # Check existing item (anti-duplicate)
        if PlannedVisitItem.objects.filter(plan_day=plan_day, contact=contact).exists():
            msg = f"العميل {contact.name} مضاف بالفعل لخطة يوم {date_str}."
            if is_ajax:
                return JsonResponse({'success': False, 'message': msg}, status=400)
            messages.warning(request, msg)
        else:
            max_order = plan_day.items.count() + 1
            item = PlannedVisitItem.objects.create(
                plan_day=plan_day,
                order=max_order,
                contact=contact,
                template=template,
                notes=notes,
                is_executed=False,
            )
            AuditLogService.log(
                action='create',
                action_type='PLANNED_VISIT_CREATED',
                module='activities',
                user=request.user,
                request=request,
                record_id=item.id,
                object_repr=f"PlannedVisitItem #{item.id} ({contact.name} on {date_str})",
                new_values={'date': date_str, 'contact_id': contact.id, 'assignee_id': assignee.id}
            )
            msg = f"تمت إضافة {contact.name} إلى خطة يوم {date_str} بنجاح."
            if is_ajax:
                return JsonResponse({'success': True, 'message': msg, 'item_id': item.id, 'contact_name': contact.name})
            messages.success(request, msg)

    return redirect(f"{request.META.get('HTTP_REFERER', '/planned-visits/')}#day-{date_str}")


@require_permission(['activities:planned/manage', 'activities:planned/list', 'activities:visits/create'])
def planned_visits_bulk_add(request):
    """
    Bulk Daily Planning (Section 8):
    Create planned visits for multiple selected clients on a single planning date
    in one atomic operation, enforcing geographical scope and duplicate prevention.
    """
    if request.method != 'POST':
        return redirect('planned_visits_list')

    is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'application/json' in request.headers.get('accept', '')
    assignee_id = request.POST.get('assignee_id') or request.user.id
    date_str = (request.POST.get('date') or '').strip()
    template_id = (request.POST.get('template_id') or '').strip()
    notes = (request.POST.get('notes') or '').strip()

    raw_contact_ids = request.POST.getlist('contact_ids') or request.POST.getlist('contact_ids[]')
    if len(raw_contact_ids) == 1 and ',' in raw_contact_ids[0]:
        raw_contact_ids = [x.strip() for x in raw_contact_ids[0].split(',') if x.strip()]
    contact_ids = []
    for cid in raw_contact_ids:
        if str(cid).isdigit() and int(cid) not in contact_ids:
            contact_ids.append(int(cid))

    if not date_str:
        msg = "يرجى تحديد تاريخ اليوم المطلوب تخطيط الزيارات فيه."
        if is_ajax:
            return JsonResponse({'success': False, 'message': msg}, status=400)
        messages.error(request, msg)
        return redirect(request.META.get('HTTP_REFERER', '/planned-visits/'))

    try:
        target_date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        msg = "صيغة التاريخ غير صالحة."
        if is_ajax:
            return JsonResponse({'success': False, 'message': msg}, status=400)
        messages.error(request, msg)
        return redirect(request.META.get('HTTP_REFERER', '/planned-visits/'))

    # Date Validation (Requirement 4): No past dates
    today = timezone.now().date()
    if target_date < today:
        msg = "لا يمكن جدولة خطة زيارات في تاريخ سابق. يرجى اختيار تاريخ اليوم أو تاريخ مستقبلي."
        if is_ajax:
            return JsonResponse({'success': False, 'message': msg}, status=400)
        messages.error(request, msg)
        return redirect(request.META.get('HTTP_REFERER', '/planned-visits/'))

    if not contact_ids:
        msg = "يرجى اختيار عميل واحد على الأقل لإضافته إلى خطة اليوم."
        if is_ajax:
            return JsonResponse({'success': False, 'message': msg}, status=400)
        messages.error(request, msg)
        return redirect(request.META.get('HTTP_REFERER', '/planned-visits/'))

    # Parse templates_by_type (Group by Client Type - Requirement 5)
    templates_by_type = {}
    raw_templates_by_type = request.POST.get('templates_by_type')
    if raw_templates_by_type:
        try:
            parsed = json.loads(raw_templates_by_type)
            if isinstance(parsed, dict):
                templates_by_type.update({str(k).strip(): str(v).strip() for k, v in parsed.items() if v})
        except Exception:
            pass

    for k, v in request.POST.items():
        if k.startswith('template_for_type_') and v:
            type_name = k[len('template_for_type_'):].strip()
            templates_by_type[type_name] = str(v).strip()
            templates_by_type[type_name.lower()] = str(v).strip()

    fallback_template_id = (request.POST.get('template_id') or '').strip()

    # Bulk Planned Visit Creation: Always assign the currently authenticated user
    assignee = request.user

    contacts = list(Contact.objects.filter(id__in=contact_ids).select_related('area', 'brick', 'area__parent'))
    if len(contacts) != len(contact_ids):
        msg = "بعض العملاء المحددين غير موجودين."
        if is_ajax:
            return JsonResponse({'success': False, 'message': msg}, status=400)
        messages.error(request, msg)
        return redirect(request.META.get('HTTP_REFERER', '/planned-visits/'))

    # Enforce geographical scope and active contact status for every selected client
    for c in contacts:
        if c.status == 'inactive':
            msg = f"لا يمكن جدولة زيارة للعميل '{c.name}' لأن حالته Inactive."
            if is_ajax:
                return JsonResponse({'success': False, 'message': msg}, status=400)
            messages.error(request, msg)
            return redirect(request.META.get('HTTP_REFERER', '/planned-visits/'))
        if not can_user_access_contact_for_visit(request.user, c):
            msg = f"غير مصرح لك بجدولة زيارة للعميل '{c.name}' لأنه يقع خارج نطاق منطقتك أو خطك الجغرافي."
            if is_ajax:
                return JsonResponse({'success': False, 'message': msg}, status=403)
            messages.error(request, msg)
            return redirect(request.META.get('HTTP_REFERER', '/planned-visits/'))

    # Collect and validate templates for each client type (Requirement 5.1)
    needed_template_ids = set()
    client_template_map = {}
    for c in contacts:
        c_type = (c.account_type or '').strip()
        t_id = (
            templates_by_type.get(c_type) or
            templates_by_type.get(c_type.lower()) or
            templates_by_type.get('__default__') or
            fallback_template_id
        )
        if not t_id or not str(t_id).isdigit():
            type_label = c_type or 'عام'
            msg = f"اختيار قالب الزيارة إلزامي لمجموعة العملاء من نوع '{type_label}' ({c.name})."
            if is_ajax:
                return JsonResponse({'success': False, 'message': msg}, status=400)
            messages.error(request, msg)
            return redirect(request.META.get('HTTP_REFERER', '/planned-visits/'))
        t_id_int = int(t_id)
        needed_template_ids.add(t_id_int)
        client_template_map[c.id] = t_id_int

    templates_cache = {
        t.id: t for t in VisitTemplate.objects.filter(id__in=needed_template_ids, active=True).prefetch_related('restricted_roles')
    }

    # Validate each client against its assigned template atomically
    for c in contacts:
        t_id = client_template_map.get(c.id)
        tmpl = templates_cache.get(t_id)
        if not tmpl:
            msg = f"قالب الزيارة المحدد للعميل '{c.name}' غير موجود أو غير نشط."
            if is_ajax:
                return JsonResponse({'success': False, 'message': msg}, status=400)
            messages.error(request, msg)
            return redirect(request.META.get('HTTP_REFERER', '/planned-visits/'))
        if not tmpl.is_user_eligible(request.user):
            msg = f"قالب الزيارة '{tmpl.display_name_ar}' غير مصرح لدورك الوظيفي باستخدامه."
            if is_ajax:
                return JsonResponse({'success': False, 'message': msg}, status=403)
            messages.error(request, msg)
            return redirect(request.META.get('HTTP_REFERER', '/planned-visits/'))
        if not tmpl.is_contact_eligible(c, user=request.user):
            allowed_str = ", ".join(tmpl.restrict_account_types) if tmpl.restrict_account_types else "الكل"
            msg = f"العميل '{c.name}' (نوع الحساب: {c.account_type or 'غير محدد'}) غير متوافق مع قالب الزيارة '{tmpl.display_name_ar}'. الأنواع المصرح بها: {allowed_str}."
            if is_ajax:
                return JsonResponse({'success': False, 'message': msg}, status=400)
            messages.error(request, msg)
            return redirect(request.META.get('HTTP_REFERER', '/planned-visits/'))

    from master_data.models import LocationSettings
    location_settings = LocationSettings.get_settings()

    with transaction.atomic():
        plan_day, _ = PlannedVisitDay.objects.get_or_create(
            assignee=assignee,
            date=target_date,
            defaults={'created_by': request.user}
        )

        # Plan-Based Architecture (Requirement 4): Distinct VisitPlan with unique plan_id
        has_approval_perm = has_perm_or_admin(request.user, 'activities:visits/approve')
        is_self = (assignee.id == request.user.id)
        is_super = (request.user.is_superuser or getattr(request.user, 'is_super_admin', False))

        if not has_approval_perm or (is_self and not is_super):
            plan_approval_status = 'pending'
            plan_approved_by = None
            plan_approved_at = None
        else:
            plan_approval_status = 'approved'
            plan_approved_by = request.user
            plan_approved_at = timezone.now()

        plan_instance = VisitPlan.objects.create(
            assignee=assignee,
            date=target_date,
            comment=notes,
            approval_status=plan_approval_status,
            approved_by=plan_approved_by,
            approved_at=plan_approved_at,
            created_by=request.user
        )

        existing_contact_ids = set(
            PlannedVisitItem.objects.filter(plan_day=plan_day).values_list('contact_id', flat=True)
        )
        existing_visit_contact_ids = set(
            Visit.objects.filter(
                owner=assignee,
                date=target_date,
                contact_id__in=contact_ids
            ).exclude(status='cancelled').values_list('contact_id', flat=True)
        )
        blocked_duplicate_ids = existing_contact_ids | existing_visit_contact_ids

        current_order = plan_day.items.count()
        next_serial = (Visit.objects.aggregate(m=Max('serial_num'))['m'] or 1000)
        created_items = []
        created_visit_ids = []
        skipped_duplicates = []
        skipped_ineligible = []

        # Preserve order of contact_ids
        contacts_by_id = {c.id: c for c in contacts}
        for cid in contact_ids:
            c = contacts_by_id.get(cid)
            if not c:
                continue
            if cid in blocked_duplicate_ids:
                skipped_duplicates.append(c.name)
                continue
            item_template = templates_cache.get(client_template_map.get(cid))
            current_order += 1
            next_serial += 1

            visit = Visit(
                serial_num=next_serial,
                contact=c,
                template=item_template,
                date=target_date,
                status='planned',
                is_planned=True,
                approval_status=plan_approval_status,
                approved_by=plan_approved_by,
                approved_at=plan_approved_at,
                allowed_distance=location_settings.get_effective_tolerance(item_template),
                owner=assignee,
                created_by=request.user,
                plan=plan_instance,
                location_verified=False,
                verification_status='unverified',
                location_status='زيارة مخططة (بانتظار بدء التنفيذ والتحقق من الموقع)',
            )
            visit._suppress_creation_notification = True
            visit.save()
            item = PlannedVisitItem.objects.create(
                plan_day=plan_day,
                order=current_order,
                contact=c,
                template=item_template,
                plan=plan_instance,
                notes='',
                visit=visit,
                is_executed=False,
            )
            ApprovalAuditLog.objects.create(
                record_type='visit',
                visit=visit,
                action='created',
                actor=request.user,
                status_before='',
                status_after=visit.approval_status,
                reason=f"إنشاء زيارة مخططة جماعية ضمن الخطة {plan_instance.plan_id} للعميل {c.name}",
                ip_address=request.META.get('REMOTE_ADDR')
            )
            created_items.append(item)
            created_visit_ids.append(visit.id)
            blocked_duplicate_ids.add(cid)

        if not created_items:
            plan_instance.delete()
        else:
            AuditLogService.log(
                action='create',
                action_type='VISIT_PLAN_CREATED',
                module='activities',
                user=request.user,
                request=request,
                record_id=plan_instance.pk,
                object_repr=f"VisitPlan #{plan_instance.plan_id}",
                new_values={
                    'plan_id': plan_instance.plan_id,
                    'date': date_str,
                    'assignee_id': assignee.id,
                    'visits_count': len(created_items),
                    'approval_status': plan_approval_status,
                    'comment': notes
                }
            )

        if created_items:
            AuditLogService.log(
                action='create',
                action_type='BULK_PLANNED_VISITS_CREATED',
                module='activities',
                user=request.user,
                request=request,
                record_id=plan_day.id,
                object_repr=f"Bulk Planned Visits ({len(created_items)} visits on {date_str} for {assignee.username})",
                new_values={
                    'date': date_str,
                    'assignee_id': assignee.id,
                    'template_ids': list(needed_template_ids),
                    'created_count': len(created_items),
                    'created_visit_ids': created_visit_ids,
                    'skipped_duplicates_count': len(skipped_duplicates),
                    'contact_ids': [it.contact_id for it in created_items],
                }
            )

    if not created_items and skipped_duplicates:
        msg = f"جميع العملاء المحددين ({len(skipped_duplicates)}) لديهم زيارات مضافة بالفعل في يوم {date_str}."
        if is_ajax:
            return JsonResponse({
                'success': False,
                'created_count': 0,
                'created_visit_ids': [],
                'skipped_duplicates_count': len(skipped_duplicates),
                'message': msg
            }, status=400)
        messages.warning(request, msg)
    elif not created_items and skipped_ineligible:
        msg = f"تعذر إضافة العملاء المحددين لعدم توافق نوع حساباتهم مع القالب المختار."
        if is_ajax:
            return JsonResponse({'success': False, 'created_count': 0, 'created_visit_ids': [], 'message': msg}, status=400)
        messages.error(request, msg)
    else:
        msg = f"تم إنشاء ({len(created_items)}) زيارة مخططة ليوم {date_str} بنجاح."
        if skipped_duplicates:
            msg += f" (تم تخطي {len(skipped_duplicates)} عميل مكرر في نفس اليوم)."
        if skipped_ineligible:
            msg += f" (تم تخطي {len(skipped_ineligible)} عميل غير متوافق مع القالب)."
        if is_ajax:
            return JsonResponse({
                'success': True,
                'created_count': len(created_items),
                'created_visit_ids': created_visit_ids,
                'skipped_duplicates_count': len(skipped_duplicates),
                'message': msg
            })
        messages.success(request, msg)

    return redirect(f"{request.META.get('HTTP_REFERER', '/planned-visits/')}#day-{date_str}")


@require_permission('activities:planned/manage')
def planned_visit_item_delete(request, pk):
    """
    Remove a planned visit item (and its linked Visit, if any, plus empty parent VisitPlan)
    regardless of pending-approval or visit lifecycle status.
    If the linked visit has already started or ended, also requires `activities:visits/delete`
    and visit-level delete DataScope.
    """
    is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'application/json' in request.headers.get('accept', '')
    if request.method != 'POST':
        if is_ajax:
            return JsonResponse({'success': False, 'error': 'MethodNotAllowed', 'message': 'POST method required.'}, status=405)
        messages.error(request, "لا يمكن تنفيذ عملية الحذف إلا عبر طلب POST آمن.")
        return redirect('planned_visits_list')

    item = get_object_or_404(
        PlannedVisitItem.objects.select_related('plan', 'plan_day__assignee', 'contact', 'visit', 'visit__owner', 'visit__template'),
        pk=pk
    )
    if not can_user_access_object(request.user, item, 'manage'):
        if is_ajax:
            return JsonResponse({'success': False, 'message': "غير مصرح لك بحذف زيارة مخططة لمندوب أو منطقة خارج نطاقك."}, status=403)
        return render_forbidden_response(request, "غير مصرح لك بحذف زيارة مخططة لمندوب أو منطقة خارج نطاقك.")

    if item.visit and (item.visit.status != 'planned' or item.visit.ended_at is not None):
        if not (has_perm_or_admin(request.user, 'activities:visits/delete') and can_user_access_object(request.user, item.visit, 'delete')):
            msg = "عذراً، حذف زيارة مخططة بدأ تنفيذها أو اكتملت يتطلب صلاحية حذف الزيارات ضمن نطاقك."
            if is_ajax:
                return JsonResponse({'success': False, 'message': msg}, status=403)
            return render_forbidden_response(request, msg)

    contact_name = item.contact.name
    date_str = item.plan_day.date.strftime('%Y-%m-%d')
    with transaction.atomic():
        linked_visit = item.visit
        parent_plan = item.plan
        if linked_visit is not None:
            _delete_visit_and_related_records(linked_visit, request.user, request=request)
        else:
            item.delete()
            if parent_plan and not parent_plan.planned_items.exists() and not parent_plan.visits.exists():
                parent_plan.delete()
        AuditLogService.log(
            action='delete',
            action_type='PLANNED_VISIT_ITEM_DELETED',
            module='activities',
            user=request.user,
            request=request,
            record_id=pk,
            object_repr=f"PlannedVisitItem #{pk} ({contact_name} - {date_str})",
        )
    msg = f"تم حذف الزيارة المخططة للعميل {contact_name} من الخطة."
    if is_ajax:
        return JsonResponse({'success': True, 'message': msg})
    messages.success(request, msg)
    return redirect(f"{request.META.get('HTTP_REFERER', '/planned-visits/')}#day-{date_str}")


@require_permission('activities:visits/create')
def planned_visit_item_execute(request, pk):
    """
    Route planned visit item into its linked Visit detail (when directly created)
    or into visit creation fallback for legacy unlinked items.
    """
    item = get_object_or_404(PlannedVisitItem.objects.select_related('plan_day__assignee', 'contact', 'template', 'visit'), pk=pk)

    if not can_user_access_object(request.user, item, 'manage'):
        return render_forbidden_response(request, "غير مصرح لك بتنفيذ خطة زيارة تابعة لمندوب أو منطقة خارج نطاقك.")

    if item.visit:
        return redirect('visit_detail', pk=item.visit.pk)

    template_param = f"&template_id={item.template.id}" if item.template else ""
    return redirect(f"/visits/create/?contact_id={item.contact.id}&planned_item_id={item.pk}{template_param}")


@require_permission('activities:planned/export')
def planned_visits_export(request):
    """Export planned visits list to Excel strictly within user's authorized scope and active filters."""
    items = PlannedVisitItem.objects.select_related(
        'plan_day__assignee', 'contact__area', 'contact__brick', 'template', 'visit'
    ).all().order_by('plan_day__date', 'order')
    items = get_scoped_queryset(items, request.user, 'plannedvisititem')

    assignee_id = request.GET.get('assignee', '').strip()
    if assignee_id and assignee_id != 'all' and assignee_id.isdigit():
        target_id = int(assignee_id)
        from accounts.scope_service import ScopeResolutionService
        is_super = request.user.is_superuser or getattr(request.user, 'is_super_admin', False)
        view_scope = ScopeResolutionService.get_user_scope(request.user, 'activities', 'view')
        can_view_others = (is_super or view_scope in ['area', 'all'])
        if not can_view_others and target_id != request.user.id:
            return render_forbidden_response(request, "غير مصرح لك بتصدير خطة زيارات مندوب آخر.")
        if not is_super and view_scope != 'all' and target_id != request.user.id:
            all_reps = get_visible_assignees_queryset(request.user, module='activities')
            if not all_reps.filter(pk=target_id).exists():
                return render_forbidden_response(request, "غير مصرح لك بتصدير خطة زيارات مندوب خارج نطاق منطقتك الجغرافية.")
        items = items.filter(plan_day__assignee_id=target_id)
    date_from = request.GET.get('date_from', '').strip()
    date_to = request.GET.get('date_to', '').strip()
    if date_from:
        items = items.filter(plan_day__date__gte=date_from)
    if date_to:
        items = items.filter(plan_day__date__lte=date_to)

    from master_data.excel_utils import export_to_excel_response
    columns = [
        {'header': 'التاريخ', 'key': lambda it: it.plan_day.date.strftime('%Y-%m-%d') if it.plan_day and it.plan_day.date else '', 'width': 16, 'align': 'center'},
        {'header': 'المسؤول', 'key': lambda it: (it.plan_day.assignee.get_full_name() or it.plan_day.assignee.username) if it.plan_day and it.plan_day.assignee else '', 'width': 22, 'align': 'right'},
        {'header': 'الترتيب', 'key': lambda it: int(it.order or 0), 'format': '#,##0', 'width': 10, 'align': 'center'},
        {'header': 'العميل', 'key': lambda it: it.contact.name if it.contact else '', 'width': 28, 'align': 'right'},
        {'header': 'الكود', 'key': lambda it: it.contact.code if it.contact else '', 'width': 14, 'align': 'center'},
        {'header': 'المنطقة', 'key': lambda it: it.contact.area.name if it.contact and it.contact.area else '', 'width': 20, 'align': 'right'},
        {'header': 'نوع الحساب', 'key': lambda it: it.contact.account_type if it.contact else '', 'width': 18, 'align': 'center'},
        {'header': 'القالب', 'key': lambda it: it.template.display_name_ar if it.template else '', 'width': 20, 'align': 'right'},
        {'header': 'تم التنفيذ', 'key': lambda it: 'نعم' if it.is_executed else 'لا', 'width': 12, 'align': 'center'},
        {'header': 'رقم الزيارة', 'key': lambda it: f"#{it.visit.serial_num}" if it.visit else '', 'width': 14, 'align': 'center'},
    ]
    return export_to_excel_response(
        items,
        columns,
        filename="planned_visits_export",
        sheet_title="خطة الزيارات",
        report_title="جدول خطة الزيارات",
        user=request.user,
    )


# -----------------------------------------------------------------------------
# VISITS MODULE (الزيارات)
# -----------------------------------------------------------------------------

def _apply_visits_list_filters(request, qs, can_view_gps_suspicion=False):
    """Shared filter pipeline for visits_list and visits_export (respecting DataScope and permissions)."""
    from master_data.filter_utils import (
        parse_multi_str,
        parse_multi_int,
        resolve_scoped_area_brick_filters,
        build_contact_area_q,
        build_contact_brick_q,
    )
    from master_data.models import Area

    q = (request.GET.get('search') or request.GET.get('q') or '').strip()
    active_filters = []

    if q:
        qs = filter_by_arabic_search(
            qs,
            ['contact__name', 'contact__code', 'owner__name', 'owner__username'],
            q,
            raw_fields=['contact__code'],
            numeric_id_field='serial_num',
        )
        active_filters.append({'label': 'بحث', 'value': q, 'param': 'search'})

    status_labels = dict(Visit.STATUS_CHOICES)
    selected_statuses = [s for s in parse_multi_str(request.GET, 'status') if s in status_labels]
    if selected_statuses:
        qs = qs.filter(status__in=selected_statuses)
        for s in selected_statuses:
            active_filters.append({'label': 'الحالة', 'value': status_labels.get(s, s), 'param': 'status', 'remove_value': s})
    status = selected_statuses[0] if len(selected_statuses) == 1 else ''

    approval_labels = dict(Visit.APPROVAL_CHOICES)
    selected_approval_statuses = [a for a in parse_multi_str(request.GET, 'approval_status') if a in approval_labels]
    if selected_approval_statuses:
        qs = qs.filter(approval_status__in=selected_approval_statuses)
        for a in selected_approval_statuses:
            active_filters.append({'label': 'حالة الاعتماد', 'value': approval_labels.get(a, a), 'param': 'approval_status', 'remove_value': a})
    approval_status = selected_approval_statuses[0] if len(selected_approval_statuses) == 1 else ''

    plan_type = request.GET.get('plan_type')
    if plan_type == 'planned':
        qs = qs.filter(is_planned=True)
        active_filters.append({'label': 'النوع', 'value': 'زيارة مخططة', 'param': 'plan_type'})
    elif plan_type == 'unplanned':
        qs = qs.filter(is_planned=False)
        active_filters.append({'label': 'النوع', 'value': 'زيارة خارج الخطة', 'param': 'plan_type'})

    visible_users_qs = get_visible_assignees_queryset(request.user, 'activities')
    raw_owner_ids = parse_multi_int(request.GET, 'owner')
    selected_owners = []
    if raw_owner_ids:
        auth_owners = list(visible_users_qs.filter(id__in=raw_owner_ids))
        selected_owners = [u.id for u in auth_owners]
        if selected_owners:
            qs = qs.filter(owner_id__in=selected_owners)
            for u_obj in auth_owners:
                active_filters.append({
                    'label': 'المسؤول',
                    'value': u_obj.name or u_obj.username,
                    'param': 'owner',
                    'remove_value': str(u_obj.id),
                })
        else:
            qs = qs.none()
    rep_id = str(selected_owners[0]) if len(selected_owners) == 1 else ''

    # Scoped Area & Brick multi-select filters
    main_area_ids, brick_ids, selected_main_areas_chips, selected_bricks_chips = resolve_scoped_area_brick_filters(
        request, 'activities',
        area_params=('main_area', 'area_id', 'governorate'),
        brick_params=('brick', 'brick_id', 'area'),
    )
    if main_area_ids:
        qs = qs.filter(build_contact_area_q(main_area_ids, prefix='contact', include_addresses=False))
        for a_chip in selected_main_areas_chips:
            active_filters.append({
                'label': 'المنطقة الرئيسية',
                'value': a_chip['name'],
                'param': 'main_area',
                'remove_value': str(a_chip['id']),
            })
    if brick_ids:
        qs = qs.filter(build_contact_brick_q(brick_ids, prefix='contact', include_addresses=False))
        for b_chip in selected_bricks_chips:
            active_filters.append({
                'label': 'الخط الجغرافي / Brick',
                'value': b_chip['name'],
                'param': 'brick',
                'remove_value': str(b_chip['id']),
            })

    # Account Type multi-select filter
    selected_account_types = parse_multi_str(request.GET, 'account_type')
    if selected_account_types:
        qs = qs.filter(contact__account_type__in=selected_account_types)
        for at in selected_account_types:
            active_filters.append({'label': 'نوع العميل', 'value': at, 'param': 'account_type', 'remove_value': at})

    # Visit Template multi-select filter
    selected_templates = parse_multi_int(request.GET, 'template')
    if selected_templates:
        qs = qs.filter(template_id__in=selected_templates)
        for tpl in VisitTemplate.objects.filter(id__in=selected_templates):
            active_filters.append({'label': 'نموذج الزيارة', 'value': tpl.name, 'param': 'template', 'remove_value': str(tpl.id)})

    parsed_from, parsed_to, active_preset, date_from, date_to = resolve_date_range(request, default_preset='all_time')
    if parsed_from:
        qs = qs.filter(date__gte=parsed_from)
        active_filters.append({'label': 'من تاريخ', 'value': date_from, 'param': 'date_from'})
    if parsed_to:
        qs = qs.filter(date__lte=parsed_to)
        active_filters.append({'label': 'إلى تاريخ', 'value': date_to, 'param': 'date_to'})

    distance_ignored = request.GET.get('distance_ignored')
    if distance_ignored:
        if distance_ignored == 'any':
            qs = qs.filter(Q(gps_forced_start=True) | Q(gps_forced_end=True))
            active_filters.append({'label': 'تجاوز المسافة', 'value': 'بدء أو إنهاء', 'param': 'distance_ignored'})
        elif distance_ignored == 'start':
            qs = qs.filter(gps_forced_start=True)
            active_filters.append({'label': 'تجاوز المسافة', 'value': 'عند البدء', 'param': 'distance_ignored'})
        elif distance_ignored == 'end':
            qs = qs.filter(gps_forced_end=True)
            active_filters.append({'label': 'تجاوز المسافة', 'value': 'عند الإنهاء', 'param': 'distance_ignored'})
        elif distance_ignored == 'none':
            qs = qs.filter(gps_forced_start=False, gps_forced_end=False)
            active_filters.append({'label': 'تجاوز المسافة', 'value': 'ضمن النطاق (لم يتم التجاوز)', 'param': 'distance_ignored'})

    # Creator Edit Status filter
    edited_by_creator = (request.GET.get('edited_by_creator') or '').strip().lower()
    if edited_by_creator == 'yes':
        qs = qs.filter(edited_by_creator=True)
        active_filters.append({'label': 'تعديل المنشئ', 'value': 'تم تعديلها بواسطة المنشئ', 'param': 'edited_by_creator'})
    elif edited_by_creator == 'no':
        qs = qs.filter(edited_by_creator=False)
        active_filters.append({'label': 'تعديل المنشئ', 'value': 'لم تُعدّل بواسطة المنشئ', 'param': 'edited_by_creator'})
    else:
        edited_by_creator = ''

    # Permission-gated GPS Integrity filter (ignored if user lacks permission)
    gps_integrity = ''
    if can_view_gps_suspicion:
        gps_integrity = (request.GET.get('gps_integrity') or '').strip()
        valid_integrity = dict(Visit.GPS_INTEGRITY_STATUS_CHOICES)
        if gps_integrity and gps_integrity in valid_integrity:
            qs = qs.filter(gps_integrity_status=gps_integrity)
            active_filters.append({'label': 'نزاهة الموقع (GBS)', 'value': valid_integrity[gps_integrity], 'param': 'gps_integrity'})
        else:
            gps_integrity = ''

    return qs, {
        'q': q,
        'status': status,
        'selected_statuses': selected_statuses,
        'approval_status': approval_status,
        'selected_approval_statuses': selected_approval_statuses,
        'plan_type': plan_type,
        'owner': rep_id,
        'selected_owners': [str(x) for x in selected_owners],
        'selected_main_areas_chips': selected_main_areas_chips,
        'selected_bricks_chips': selected_bricks_chips,
        'selected_account_types': selected_account_types,
        'selected_templates': [str(x) for x in selected_templates],
        'date_from': date_from,
        'date_to': date_to,
        'active_preset': active_preset,
        'distance_ignored': distance_ignored,
        'edited_by_creator': edited_by_creator,
        'gps_integrity': gps_integrity,
        'active_filters': active_filters,
    }


@require_permission('activities:visits/list')
def visits_list(request):
    """
    Visits list with table & cards views, complete filters, status indicators, and export.
    """
    qs = (
        Visit.objects.select_related('contact', 'contact__area', 'contact__brick', 'template', 'owner', 'created_by', 'last_edited_by')
        .prefetch_related('samples__product', 'template__questions', 'detailed_products')
        .all()
        .order_by('-serial_num')
    )
    qs = get_scoped_queryset(qs, request.user, 'visit')

    can_view_gps_suspicion = has_perm_or_admin(request.user, 'activities:visits/view_gps_suspicion')
    qs, f_state = _apply_visits_list_filters(request, qs, can_view_gps_suspicion=can_view_gps_suspicion)
    q = f_state['q']
    status = f_state['status']
    approval_status = f_state['approval_status']
    plan_type = f_state['plan_type']
    rep_id = f_state['owner']
    date_from = f_state['date_from']
    date_to = f_state['date_to']
    active_preset = f_state['active_preset']
    distance_ignored = f_state['distance_ignored']
    edited_by_creator = f_state['edited_by_creator']
    gps_integrity = f_state['gps_integrity']
    active_filters = f_state['active_filters']

    # View Mode: unified table across desktop and mobile
    view_mode = 'table'

    # Standardized bounded pagination
    paginator, page_obj = paginate_queryset(request, qs, default_per_page=25, max_per_page=100)
    preload_visit_qa_product_map(page_obj.object_list)

    user_can_manage = can_manage_approvals(request.user)
    user_can_delete_perm = has_perm_or_admin(request.user, 'activities:visits/delete')
    for v in page_obj.object_list:
        v.user_can_approve = bool(
            user_can_manage and
            v.owner_id != request.user.id and
            can_user_access_object(request.user, v, 'approve')
        )
        v.user_can_delete = bool(
            user_can_delete_perm and
            can_user_access_object(request.user, v, 'delete')
        )

    # Scoped filter dropdowns
    users = get_visible_assignees_queryset(request.user, 'activities')
    templates = VisitTemplate.objects.filter(active=True)

    visits_agg = qs.aggregate(
        approved_count=Count('id', filter=Q(approval_status='approved')),
        pending_count=Count('id', filter=Q(approval_status='pending')),
        planned_count=Count('id', filter=Q(is_planned=True)),
        unplanned_count=Count('id', filter=Q(is_planned=False)),
    )
    approved_count = visits_agg['approved_count'] or 0
    pending_count = visits_agg['pending_count'] or 0
    planned_count = visits_agg['planned_count'] or 0
    unplanned_count = visits_agg['unplanned_count'] or 0

    owner_options = [{'value': str(u.id), 'label': u.name or u.username} for u in users]
    selected_owner_items = [o for o in owner_options if o['value'] in f_state['selected_owners']]
    status_options = [{'value': k, 'label': v} for k, v in Visit.STATUS_CHOICES]
    selected_status_items = [o for o in status_options if o['value'] in f_state['selected_statuses']]
    approval_options = [{'value': k, 'label': v} for k, v in Visit.APPROVAL_CHOICES]
    selected_approval_items = [o for o in approval_options if o['value'] in f_state['selected_approval_statuses']]
    template_options = [{'value': str(t.id), 'label': t.name} for t in templates]
    selected_template_items = [o for o in template_options if o['value'] in f_state['selected_templates']]

    context = {
        'page_obj': page_obj,
        'paginator': paginator,
        'visits': page_obj.object_list,
        'total_count': paginator.count,
        'approved_count': approved_count,
        'pending_count': pending_count,
        'planned_count': planned_count,
        'unplanned_count': unplanned_count,
        'view_mode': view_mode,
        'users': users,
        'can_filter_owner': users.count() > 1 or getattr(request.user, 'is_super_admin', False) or request.user.is_superuser,
        'templates': templates,
        'account_types': ACCOUNT_TYPES,
        'selected_account_types': f_state['selected_account_types'],
        'selected_main_areas_chips': f_state['selected_main_areas_chips'],
        'selected_bricks_chips': f_state['selected_bricks_chips'],
        'owner_options': owner_options,
        'selected_owner_items': selected_owner_items,
        'selected_owners': f_state['selected_owners'],
        'status_options': status_options,
        'selected_status_items': selected_status_items,
        'selected_statuses': f_state['selected_statuses'],
        'approval_options': approval_options,
        'selected_approval_items': selected_approval_items,
        'selected_approval_statuses': f_state['selected_approval_statuses'],
        'template_options': template_options,
        'selected_template_items': selected_template_items,
        'selected_templates': f_state['selected_templates'],
        'selected_q': q,
        'selected_status': status,
        'selected_approval_status': approval_status,
        'selected_plan_type': plan_type,
        'selected_owner': rep_id,
        'selected_date_from': date_from,
        'selected_date_to': date_to,
        'date_from': date_from,
        'date_to': date_to,
        'active_preset': active_preset,
        'selected_distance_ignored': distance_ignored,
        'selected_edited_by_creator': edited_by_creator,
        'can_view_gps_suspicion': can_view_gps_suspicion,
        'selected_gps_integrity': gps_integrity if can_view_gps_suspicion else '',
        'gps_integrity_choices': Visit.GPS_INTEGRITY_STATUS_CHOICES if can_view_gps_suspicion else [],
        'active_filters': active_filters,
        'can_manage_approvals': can_manage_approvals(request.user),
    }
    return render(request, 'activities/visits_list.html', context)


@require_permission('activities:visits/view')
def visit_detail(request, pk):
    """
    Standardized Visit Lifecycle Screen (Create First, Answer Later).
    Allows viewing dossier, answering template questions, uploading location photo,
    verifying GPS, saving draft progress, completing, cancelling, and manager approvals.
    """
    visit = get_object_or_404(
        Visit.objects.select_related(
            'contact', 'contact__area', 'contact_address', 'contact_address__area', 'contact_address__brick',
            'template', 'owner', 'approved_by', 'created_by', 'bypassed_by', 'last_edited_by',
        ).prefetch_related(
            'samples__product', 'expenses', 'detailed_products', 'template__questions',
            'contact__addresses__area', 'contact__addresses__brick',
        ),
        pk=pk
    )

    if not can_user_access_object(request.user, visit, 'view'):
        return render_forbidden_response(request, "غير مصرح لك بالوصول إلى تفاصيل هذه الزيارة.")

    from master_data.models import LocationSettings
    location_settings = LocationSettings.get_settings()
    can_bypass_gps = location_settings.can_user_bypass_without_approval(request.user, stage='end')
    template = visit.template
    supports_detailing = template.is_product_detailing_supported() if template else False

    if request.method == 'POST':
        if visit.status in ('finished', 'cancelled'):
            return render_forbidden_response(request, "لا يمكن تقديم الإجابات أو إنهاء الزيارة لأنها مكتملة أو ملغاة بالفعل.")

        if visit.is_planned and visit.approval_status != 'approved':
            return render_forbidden_response(request, "لا يمكن إنهاء زيارة مخططة غير معتمدة. يجب اعتماد الزيارة أولاً.")

        # Visit execution ownership check
        if visit.owner_id != request.user.id and not (request.user.is_superuser or getattr(request.user, 'is_super_admin', False)):
            return render_forbidden_response(request, "فقط المندوب المسؤول عن الزيارة هو المصرح له بتقديم إجاباتها وإنهائها.")

        action = request.POST.get('action', 'complete').strip()
        if action != 'complete':
            return redirect('visit_detail', pk=visit.pk)

        # Process Questionnaire Answers
        answers = dict(visit.questionnaire_answers or {})
        validation_errors = []

        if template:
            questions = template.get_active_questions()
            parent_answers = {}

            # First pass: collect parent answers (preserving any already-saved answers such as check-in)
            for q in questions:
                field_name = f'question_{q.id}'
                val = request.POST.get(field_name) or request.POST.getlist(field_name)
                if isinstance(val, list) and len(val) == 1:
                    val = val[0]
                elif isinstance(val, list) and len(val) == 0:
                    val = ''
                if q.question_type in ('multiple_choice', 'suggested_products'):
                    val = request.POST.getlist(field_name)
                if not val and str(q.id) in answers:
                    val = answers[str(q.id)]
                if val:
                    parent_answers[q.id] = val

            for q in questions:
                # Conditional visibility check
                is_visible = True
                if q.is_conditional and q.conditional_parent_id:
                    parent_val = parent_answers.get(q.conditional_parent_id, '')
                    trigger_val = (q.conditional_trigger_value or '').strip().lower()
                    if str(parent_val).strip().lower() != trigger_val:
                        is_visible = False

                if not is_visible:
                    # Remove hidden conditional answers to prevent submitting incompatible answers
                    answers.pop(str(q.id), None)
                    continue

                field_name = f'question_{q.id}'
                if q.question_type == 'suggested_products':
                    eligible_qs, historical_ids, _ = get_question_product_choices(template, visit=visit, question=q)
                    allowed_ids = set(eligible_qs.values_list('id', flat=True)) | historical_ids
                    try:
                        val = parse_suggested_products_submission(request.POST, field_name, allowed_ids, strict=True)
                    except ValidationError as ve:
                        err_msg = ve.message if hasattr(ve, 'message') else (ve.messages[0] if getattr(ve, 'messages', None) else str(ve))
                        validation_errors.append(err_msg)
                        val = []
                    if not val and q.stage == 'start_only' and str(q.id) in answers:
                        val = answers[str(q.id)]
                else:
                    val = request.POST.get(field_name) or request.POST.getlist(field_name)
                    if isinstance(val, list) and len(val) == 1:
                        val = val[0]
                    elif isinstance(val, list) and len(val) == 0:
                        val = ''
                    if q.question_type == 'multiple_choice':
                        val = request.POST.getlist(field_name)
                    if (val is None or val == '' or val == []) and q.stage == 'start_only' and str(q.id) in answers:
                        val = answers[str(q.id)]

                # Validate required questions strictly when completing
                if action == 'complete' and q.is_required and (val is None or val == '' or val == []):
                    validation_errors.append(f"السؤال '{q.text_ar}' إلزامي لإتمام الزيارة.")

                if val is not None and val != '' and val != []:
                    answers[str(q.id)] = val
                else:
                    answers.pop(str(q.id), None)

        # Handle Location Verification
        lat = request.POST.get('latitude') or visit.latitude
        lng = request.POST.get('longitude') or visit.longitude
        acc = request.POST.get('device_accuracy') or visit.device_accuracy
        force_bypass_raw = request.POST.get('force_bypass_location') in ('1', 'true', 'True', 'on')
        if force_bypass_raw and not can_bypass_gps:
            validation_errors.append("عذراً، لا تملك صلاحية تجاوز التحقق الجغرافي (GPS).")
        force_bypass = bool(force_bypass_raw)
        bypass_reason = (request.POST.get('bypass_reason') or '').strip()

        # Enforce GPS and Distance Validation when completing visit (Section 3.C & 3.D)
        if action == 'complete':
            if location_settings.verify_visits and not force_bypass and not can_bypass_gps:
                if not lat or not lng:
                    validation_errors.append("تحديد الموقع الجغرافي (GPS) إلزامي للمندوب لإنهاء الزيارة.")

            if not validation_errors:
                try:
                    verify_visit_location(
                        visit, request.user, visit.contact,
                        visit_lat=lat, visit_lng=lng, device_accuracy=acc,
                        force_bypass=force_bypass,
                        bypass_reason=bypass_reason, stage='end',
                        strict_distance=bool(location_settings.verify_visits and location_settings.verify_end_visit_distance),
                        contact_address=visit.contact_address,
                    )
                except ValidationError as ve:
                    err_text = ve.message if hasattr(ve, 'message') else (ve.messages[0] if hasattr(ve, 'messages') and ve.messages else str(ve))
                    validation_errors.append(err_text)
                except Exception as e:
                    validation_errors.append(f"خطأ في معالجة الموقع: {str(e)}")

        if validation_errors:
            # Preserve answers when a validation error occurs!
            visit.questionnaire_answers = answers
            visit.save(update_fields=['questionnaire_answers'])
            is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'application/json' in request.headers.get('accept', '')
            if is_ajax:
                return JsonResponse({
                    'success': False,
                    'message': validation_errors[0],
                    'errors': validation_errors
                }, status=400)
            for err in validation_errors:
                messages.error(request, err)
        else:
            with transaction.atomic():
                visit.questionnaire_answers = answers

                # Outcome is determined by Question 1 of the template
                if template:
                    first_q = template.get_active_questions().order_by('order', 'id').first()
                    if first_q:
                        ans_q1 = answers.get(str(first_q.id))
                        if ans_q1:
                            ans_str = str(ans_q1).strip().lower()
                            visit.is_successful = (('ناجح' in ans_str and 'غير' not in ans_str) or ('successful' in ans_str and 'unsuccessful' not in ans_str))

                # Product Detailing (Requirement 8): Restricted to the three templates
                if template and template.is_product_detailing_supported():
                    if template.has_suggested_products_question():
                        sp_union_ids = []
                        for q in template.get_active_questions():
                            if q.question_type == 'suggested_products':
                                for pid in (answers.get(str(q.id)) or []):
                                    if str(pid).isdigit() and int(pid) not in sp_union_ids:
                                        sp_union_ids.append(int(pid))
                        visit.detailed_products.set(sp_union_ids)
                    else:
                        detailed_product_ids = request.POST.getlist('detailed_products')
                        if detailed_product_ids:
                            eligible_ids = set(Product.get_eligible_for_visits().values_list('id', flat=True))
                            historical_ids = set(visit.detailed_products.values_list('id', flat=True))
                            allowed_ids = eligible_ids | historical_ids
                            valid_ids = [int(pid) for pid in detailed_product_ids if str(pid).isdigit() and int(pid) in allowed_ids]
                            visit.detailed_products.set(valid_ids)
                        elif 'detailed_products_submitted' in request.POST:
                            visit.detailed_products.clear()
                else:
                    visit.detailed_products.clear()

                if action == 'complete':
                    old_status = visit.status
                    visit.status = 'finished'
                    visit.ended_at = timezone.now()
                    if visit.started_at:
                        visit.duration = max(1, int((visit.ended_at - visit.started_at).total_seconds()))
                    else:
                        visit.started_at = visit.ended_at - datetime.timedelta(minutes=15)
                        visit.duration = 900

                    visit.save()

                    # Mark planned item as executed upon visit completion
                    planned_item = PlannedVisitItem.objects.filter(visit=visit).first()
                    if planned_item:
                        planned_item.is_executed = True
                        planned_item.save(update_fields=['is_executed'])

                    if visit.verification_status == 'force_bypassed' or visit.gps_forced_end:
                        ApprovalAuditLog.objects.create(
                            record_type='visit',
                            visit=visit,
                            action='distance_bypass',
                            actor=request.user,
                            status_before=old_status,
                            status_after=visit.approval_status,
                            reason=f"تجاوز المسافة عند الإنهاء ({visit.distance or 0}م مقابل المسموح {visit.allowed_distance}م): {bypass_reason or 'تجاوز مباشر بصلاحية المدير/المشرف'}",
                            ip_address=request.META.get('REMOTE_ADDR')
                        )
                        AuditLogService.log(
                            action='update',
                            action_type='VISIT_DISTANCE_BYPASSED',
                            module='visits',
                            user=request.user,
                            request=request,
                            record_id=visit.pk,
                            object_repr=f"Visit #{visit.serial_num}",
                            new_values={
                                'stage': 'end',
                                'distance': float(visit.distance) if visit.distance is not None else None,
                                'allowed_distance': visit.allowed_distance,
                                'distance_discrepancy': visit.distance_discrepancy,
                                'bypassed_by': request.user.username,
                                'bypass_reason': bypass_reason,
                            }
                        )

                    ApprovalAuditLog.objects.create(
                        record_type='visit',
                        visit=visit,
                        action='status_changed',
                        actor=request.user,
                        status_before=old_status,
                        status_after='finished',
                        reason='إنهاء الزيارة وتوثيق الإجراءات رسمياً (Check-out)',
                        ip_address=request.META.get('REMOTE_ADDR')
                    )
                    AuditLogService.log(
                        action='update',
                        action_type='VISIT_COMPLETED',
                        module='visits',
                        user=request.user,
                        request=request,
                        record_id=visit.pk,
                        object_repr=f"Visit #{visit.serial_num}",
                        previous_values={'status': old_status},
                        new_values={
                            'status': 'finished',
                            'duration': visit.duration,
                            'verification_status': visit.verification_status,
                            'approval_status': visit.approval_status,
                        }
                    )
                    if visit.requires_approval_due_to_distance:
                        messages.warning(
                            request,
                            f"تم إنهاء الزيارة #{visit.serial_num} وإرسالها لاعتماد المدير بسبب تجاوز المسافة المسموح بها ({visit.distance}م مقابل {visit.allowed_distance}م)."
                        )
                    else:
                        messages.success(request, f"تم إنهاء وتوثيق الزيارة #{visit.serial_num} بنجاح. استغرقت الزيارة {visit.duration_formatted}.")
                else:
                    msg = "تم إيقاف حفظ المسودات للزيارات؛ يرجى إنهاء وتوثيق الزيارة مباشرة."
                    is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'application/json' in request.headers.get('accept', '')
                    if is_ajax:
                        return JsonResponse({'success': False, 'message': msg}, status=400)
                    messages.warning(request, msg)
                    return redirect('visit_detail', pk=visit.pk)

            is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'application/json' in request.headers.get('accept', '')
            if is_ajax:
                return JsonResponse({
                    'success': True,
                    'status': visit.status,
                    'approval_status': visit.approval_status,
                    'requires_approval_due_to_distance': visit.requires_approval_due_to_distance,
                    'serial_num': visit.serial_num,
                    'duration': visit.duration,
                    'duration_formatted': visit.duration_formatted,
                    'message': f"تم إنهاء وتوثيق الزيارة #{visit.serial_num} بنجاح (استغرقت {visit.duration_formatted})." if action == 'complete' else "تم حفظ البيانات بنجاح."
                })
            return redirect('visit_detail', pk=visit.pk)

    # GET Request: prepare structured questionnaire answers and questions
    questionnaire_responses = []
    all_questions = []
    start_questions = []
    completion_questions = []
    question_product_choices = {}
    question_selected_product_ids = {}
    matched_qids = set()
    answers = visit.questionnaire_answers or {}

    if visit.template:
        active_qs = list(visit.template.get_active_questions())
        if visit.status == 'started':
            all_questions = active_qs
        else:
            all_questions = list(visit.template.questions.all().order_by('order', 'id'))
        start_questions = [q for q in active_qs if q.stage == 'start_only']
        completion_questions = [q for q in active_qs if q.stage in ['all', 'end_only']]

        # Build product choices & batch-fetch product names for all suggested_products questions
        sp_answer_pids = set()
        for q in all_questions:
            if q.question_type == 'suggested_products':
                eligible_qs, _, _ = get_question_product_choices(visit.template, visit=visit, question=q)
                question_product_choices[q.id] = list(eligible_qs)
                raw_ans = answers.get(str(q.id), [])
                items = raw_ans if isinstance(raw_ans, (list, tuple)) else ([raw_ans] if raw_ans not in (None, '') else [])
                sel_ids = [int(str(x).strip()) for x in items if str(x).strip().isdigit()]
                question_selected_product_ids[q.id] = set(sel_ids)
                sp_answer_pids.update(sel_ids)

        qa_product_map = dict(Product.objects.filter(id__in=sp_answer_pids).values_list('id', 'name')) if sp_answer_pids else {}

        for q in all_questions:
            qid_str = str(q.id)
            ans = answers.get(qid_str)
            if q.question_type == 'suggested_products':
                sel_set = []
                items = ans if isinstance(ans, (list, tuple)) else ([ans] if ans not in (None, '') else [])
                for item in items:
                    if str(item).strip().isdigit():
                        pid = int(str(item).strip())
                        sel_set.append({'id': pid, 'name': qa_product_map.get(pid, f"منتج #{pid}")})
                if sel_set or (visit.status == 'finished' and q.is_active):
                    matched_qids.add(qid_str)
                    display_ans = '، '.join(p['name'] for p in sel_set) if sel_set else 'لم يتم اختيار منتجات'
                    questionnaire_responses.append({
                        'question': q,
                        'text_ar': q.text_ar,
                        'text_en': q.text_en,
                        'stage': q.get_stage_display(),
                        'answer': display_ans,
                        'raw_answer': ans or [],
                        'question_type': q.question_type,
                        'selected_products': sel_set,
                        'is_product_list': True,
                        'is_empty': not bool(sel_set),
                        'is_meeting_question': False,
                    })
            elif ans is not None and ans != '' and ans != []:
                matched_qids.add(qid_str)
                display_ans = format_answer_for_display(q, ans, product_map=qa_product_map)
                questionnaire_responses.append({
                    'question': q,
                    'text_ar': q.text_ar,
                    'text_en': q.text_en,
                    'stage': q.get_stage_display(),
                    'answer': display_ans,
                    'raw_answer': ans,
                    'question_type': q.question_type,
                    'is_product_list': False,
                    'is_empty': False,
                    'is_meeting_question': ('meet' in q.text_ar.lower() or 'قابلت' in q.text_ar),
                })

    # Preserve any deleted/legacy question answers so they are never silently dropped
    for k, ans in answers.items():
        if str(k) not in matched_qids and ans not in (None, '', []):
            if isinstance(ans, list):
                display_ans = "، ".join(Visit.translate_answer_value(x) for x in ans if x not in (None, ''))
            else:
                display_ans = Visit.translate_answer_value(ans)
            questionnaire_responses.append({
                'question': None,
                'text_ar': f"سؤال #{k}",
                'text_en': f"Question #{k}",
                'stage': 'أرشيف',
                'answer': display_ans,
                'raw_answer': ans,
                'question_type': '',
                'is_product_list': False,
                'is_empty': False,
                'is_meeting_question': False,
            })

    has_suggested_products_question = template.has_suggested_products_question() if template else False
    det_prods_list = list(visit.detailed_products.all())
    if visit.status == 'finished' and supports_detailing and not has_suggested_products_question:
        questionnaire_responses.append({
            'question': None,
            'text_ar': 'المنتجات المشروحة (Product Detailing)',
            'text_en': 'Detailed Products',
            'stage': 'نهاية الزيارة',
            'answer': '، '.join(p.name for p in det_prods_list) if det_prods_list else 'لم يتم اختيار منتجات',
            'selected_products': [{'id': p.id, 'name': p.name} for p in det_prods_list],
            'raw_answer': [p.id for p in det_prods_list],
            'question_type': 'detailed_products',
            'is_product_list': True,
            'is_empty': not bool(det_prods_list),
            'is_meeting_question': False,
        })

    # Configurable Product Suggestions: collect from template & global settings
    suggested_product_ids = set()
    if template:
        suggested_product_ids.update(template.get_eligible_suggested_products().values_list('id', flat=True))
    if location_settings.enable_product_suggestions:
        suggested_product_ids.update(location_settings.get_eligible_suggested_products().values_list('id', flat=True))

    # Eligible products (sellable & active) + any historically detailed products (suggested first)
    eligible_products = Product.get_eligible_for_visits()
    historical_ids = {p.id for p in det_prods_list}
    all_product_ids = set(eligible_products.values_list('id', flat=True)) | historical_ids
    products = sorted(
        Product.objects.filter(id__in=all_product_ids).order_by('name'),
        key=lambda p: (0 if p.id in suggested_product_ids else 1, p.name),
    )

    can_approve = can_manage_approvals(request.user) and can_user_access_object(request.user, visit, 'approve')
    can_resubmit = (visit.approval_status in ('disapproved', 'rejected')) and (
        visit.owner == request.user or request.user.is_superuser or getattr(request.user, 'is_super_admin', False)
    )
    can_start_visit_val, _ = can_start_visit(visit, request.user)
    owner_open_visit = get_open_visit_for_owner(visit.owner_id, exclude_visit_id=visit.pk) if visit.status == 'planned' else None
    can_delete_visit_val, _ = can_delete_unended_visit(visit, request.user)
    can_edit_answers_val, _ = can_edit_visit_answers(visit, request.user)
    can_bypass_start_gps = location_settings.can_user_bypass_without_approval(request.user, stage='start')
    approval_history = visit.approval_history.select_related('actor').all()
    timeline_events = build_visit_timeline(visit)
    is_in_agenda = PlannedVisitItem.objects.filter(visit=visit).exists()
    effective_allowed_distance = visit.effective_allowed_distance
    from activities.services import serialize_contact_addresses
    contact_addresses = serialize_contact_addresses(visit.contact)
    # Effective target coordinates for End Visit verification: selected address > immutable snapshot > legacy main address
    if visit.contact_address_id and visit.contact_address:
        visit_target_lat = visit.contact_address.latitude
        visit_target_lng = visit.contact_address.longitude
    elif visit.customer_latitude_snapshot is not None and visit.customer_longitude_snapshot is not None:
        visit_target_lat = visit.customer_latitude_snapshot
        visit_target_lng = visit.customer_longitude_snapshot
    else:
        visit_target_lat = visit.contact.latitude
        visit_target_lng = visit.contact.longitude

    return render(request, 'activities/visit_detail.html', {
        'visit': visit,
        'contact_addresses': contact_addresses,
        'contact_addresses_json': json.dumps(contact_addresses),
        'visit_target_lat': visit_target_lat,
        'visit_target_lng': visit_target_lng,
        'questionnaire_responses': questionnaire_responses,
        'all_questions': all_questions,
        'start_questions': start_questions,
        'completion_questions': completion_questions,
        'question_product_choices': question_product_choices,
        'question_selected_product_ids': question_selected_product_ids,
        'selected_detailed_product_ids': historical_ids,
        'has_suggested_products_question': has_suggested_products_question,
        'products': products,
        'suggested_product_ids': suggested_product_ids,
        'supports_detailing': supports_detailing,
        'can_bypass_gps': can_bypass_gps,
        'can_bypass_start_gps': can_bypass_start_gps,
        'owner_open_visit': owner_open_visit,
        'bypass_reason_mandatory': location_settings.bypass_reason_mandatory,
        'distance_bypass_requires_approval': location_settings.distance_bypass_requires_approval,
        'verify_visits_enabled': location_settings.verify_visits,
        'verify_unplanned_visit_distance': location_settings.verify_unplanned_visit_distance,
        'verify_end_visit_distance': location_settings.verify_end_visit_distance,
        'gps_tolerance': effective_allowed_distance,
        'allowed_distance': effective_allowed_distance,
        'default_tolerance': location_settings.tolerance,
        'can_manage_approvals': can_manage_approvals(request.user),
        'can_approve': can_approve,
        'can_resubmit': can_resubmit,
        'can_start_visit': can_start_visit_val,
        'can_delete_visit': can_delete_visit_val,
        'can_edit_answers': can_edit_answers_val,
        'approval_history': approval_history,
        'timeline_events': timeline_events,
        'is_in_agenda': is_in_agenda,
        'status_choices': Visit.STATUS_CHOICES,
        'approval_choices': Visit.APPROVAL_CHOICES,
        'can_view_gps_suspicion': has_perm_or_admin(request.user, 'activities:visits/view_gps_suspicion'),
    })


@require_permission(['activities:visits/create', 'activities:visits/list', 'activities:planned/list'])
def visit_check_duplicate_api(request):
    """
    AJAX endpoint checking whether the selected client already has a scheduled
    or recorded visit on the selected date (Section 4.D).
    """
    contact_id = (request.GET.get('contact_id') or request.GET.get('contact') or '').strip()
    date_str = (request.GET.get('date') or '').strip()
    planned_item_id = (request.GET.get('planned_item_id') or '').strip()

    if not contact_id or not contact_id.isdigit() or not date_str:
        return JsonResponse({'has_duplicate': False, 'visits_count': 0, 'planned_count': 0})

    try:
        target_date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return JsonResponse({'has_duplicate': False, 'visits_count': 0, 'planned_count': 0})

    contact = Contact.objects.filter(pk=int(contact_id)).select_related('area', 'area__parent').first()
    if not contact or not can_user_access_contact_for_visit(request.user, contact):
        return JsonResponse({'has_duplicate': False, 'visits_count': 0, 'planned_count': 0})

    existing_visits = Visit.objects.filter(contact=contact, date=target_date).exclude(status='cancelled')
    existing_plans = PlannedVisitItem.objects.filter(contact=contact, plan_day__date=target_date, visit__isnull=True)
    if planned_item_id and planned_item_id.isdigit():
        existing_plans = existing_plans.exclude(pk=int(planned_item_id))

    v_count = existing_visits.count()
    p_count = existing_plans.count()
    has_dup = (v_count + p_count) > 0
    msg = ""
    if has_dup:
        msg = (
            f"تنبيه: يوجد بالفعل ({v_count} زيارة مسجلة و {p_count} زيارة مجدولة) "
            f"للعميل '{contact.name}' في تاريخ {date_str}. يرجى تأكيد الرغبة في المتابعة لإنشاء زيارة إضافية في نفس اليوم."
        )
    return JsonResponse({
        'has_duplicate': has_dup,
        'visits_count': v_count,
        'planned_count': p_count,
        'message': msg,
    })


@require_permission('activities:visits/create')
def visit_create(request):
    """
    Standardized Unified Visit Registration endpoint: /visits/create/ (Section 4)
    Used by both planned visits and unplanned visits with a single common form.
    Enforces geographical scope (Section 7), dynamic distance validation (Section 3),
    date rules, and duplicate visit confirmation (Section 4.D).
    """
    planned_item_id = request.POST.get('planned_item_id') or request.GET.get('planned_item_id')
    planned_item = None
    if planned_item_id:
        try:
            planned_item = PlannedVisitItem.objects.select_related('plan_day__assignee', 'contact', 'contact__area', 'template').get(pk=planned_item_id)
            is_owner = (planned_item.plan_day.assignee == request.user)
            can_override = (
                (
                    request.user.is_superuser
                    or getattr(request.user, 'is_super_admin', False)
                    or has_perm_or_admin(request.user, 'activities:planned/manage')
                )
                and can_user_access_object(request.user, planned_item, 'manage')
            )
            if not (is_owner or can_override):
                messages.error(request, "غير مصرح لك بتسجيل أو تنفيذ خطة زيارة تابعة لمندوب آخر.")
                return redirect('visits_list')
            if planned_item.is_executed and planned_item.visit:
                messages.info(request, f"تم تنفيذ هذه الزيارة المخططة مسبقاً (زيارة #{planned_item.visit.serial_num}).")
                return redirect('visit_detail', pk=planned_item.visit.pk)
        except PlannedVisitItem.DoesNotExist:
            messages.error(request, "عنصر الخطة المطلوب غير موجود أو غير صالح.")
            return redirect('visits_list')

    from master_data.models import LocationSettings
    location_settings = LocationSettings.get_settings()
    can_bypass_gps = location_settings.can_user_bypass_without_approval(request.user, stage='start')

    # Planned visits must ONLY be created through the bulk planned-visits workflow
    # and executed via planned_item_id. Direct visits via /visits/create/ are strictly unplanned.
    is_planned_visit = bool(planned_item is not None)

    duplicate_warning = False
    existing_same_day_visits = Visit.objects.none()
    existing_same_day_plans = PlannedVisitItem.objects.none()
    today_date = timezone.localdate()
    today_str = today_date.strftime('%Y-%m-%d')

    if request.method == 'POST':
        form = VisitForm(request.POST, request.FILES, user=request.user)
        if form.is_valid():
            contact = form.cleaned_data['contact']
            template = form.cleaned_data.get('template')
            is_planned_visit = bool(planned_item is not None)

            # Backend Eligibility Validation (Requirement 1 & Requirement 4)
            if not template:
                form.add_error('template', "اختيار قالب الزيارة إلزامي لإتمام العملية.")
                messages.error(request, form.errors.as_text())
            elif not template.is_user_eligible(request.user):
                form.add_error('template', f"دورك الوظيفي غير مصرح له باستخدام قالب الزيارة '{template.display_name_ar}'.")
                messages.error(request, form.errors.as_text())
            elif not template.is_contact_eligible(contact, user=request.user):
                allowed_str = ", ".join(template.restrict_account_types) if template.restrict_account_types else "الكل"
                form.add_error('template', f"قالب الزيارة '{template.display_name_ar}' غير مصرح به لنوع حساب العميل ({contact.account_type or 'غير محدد'}). الأنواع المصرح بها: {allowed_str}.")
                messages.error(request, form.errors.as_text())
            elif is_planned_visit and planned_item.plan_day.date < today_date:
                form.add_error('date', "لا يمكن اختيار تاريخ في الماضي. يرجى اختيار تاريخ اليوم أو تاريخ مستقبلي.")
                messages.error(request, form.errors.as_text())
            else:
                # Representative Assignment Locking (defaults to logged-in user)
                if can_assign_other_representative(request.user) and form.cleaned_data.get('owner'):
                    owner = form.cleaned_data.get('owner')
                elif planned_item and can_assign_other_representative(request.user):
                    owner = planned_item.plan_day.assignee
                else:
                    owner = request.user

                visit_date = planned_item.plan_day.date if planned_item else today_date

                # Duplicate Visit Confirmation (Section 4.D):
                # If a client already has a visit scheduled or recorded for the same date,
                # display a clear warning and ask the user to confirm before creating.
                existing_same_day_visits = Visit.objects.filter(
                    contact=contact,
                    date=visit_date
                ).exclude(status='cancelled')
                existing_same_day_plans = PlannedVisitItem.objects.filter(
                    contact=contact,
                    plan_day__date=visit_date,
                    visit__isnull=True
                )
                if planned_item:
                    existing_same_day_plans = existing_same_day_plans.exclude(pk=planned_item.pk)

                has_same_day_duplicate = existing_same_day_visits.exists() or existing_same_day_plans.exists()
                confirm_duplicate = request.POST.get('confirm_duplicate') in ('1', 'true', 'True', 'on', 'yes')

                if has_same_day_duplicate and not confirm_duplicate:
                    duplicate_warning = True
                    dup_msg = (
                        f"تنبيه تكرار الزيارة: يوجد بالفعل زيارة مسجلة أو مجدولة للعميل ({contact.name}) "
                        f"في تاريخ {visit_date.strftime('%Y-%m-%d')}. يرجى تأكيد الرغبة في المتابعة لإنشاء زيارة إضافية في نفس اليوم."
                    )
                    is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'application/json' in request.headers.get('accept', '')
                    if is_ajax:
                        return JsonResponse({
                            'success': False,
                            'duplicate_warning': True,
                            'message': dup_msg,
                            'visits_count': existing_same_day_visits.count(),
                            'planned_count': existing_same_day_plans.count(),
                        }, status=409)
                    messages.warning(request, dup_msg)
                elif not is_planned_visit:
                    # Atomic Unplanned Visit Create + Immediate Start (Requirement F)
                    is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'application/json' in request.headers.get('accept', '')
                    force_bypass = request.POST.get('force_bypass_location') in ('1', 'true', 'True', 'on')
                    bypass_reason = request.POST.get('bypass_reason', '')
                    lat = request.POST.get('latitude')
                    lng = request.POST.get('longitude')
                    accuracy = request.POST.get('device_accuracy')
                    checkin_answers = extract_checkin_answers_from_post(request.POST, template)

                    try:
                        visit = create_and_start_unplanned_visit(
                            request.user,
                            contact,
                            template,
                            owner=owner,
                            doubled=bool(form.cleaned_data.get('doubled')),
                            is_successful=bool(form.cleaned_data.get('is_successful', True)),
                            post_data=request.POST,
                            lat=lat,
                            lng=lng,
                            accuracy=accuracy,
                            force_bypass=force_bypass,
                            bypass_reason=bypass_reason,
                            checkin_answers=checkin_answers,
                            contact_address_id=request.POST.get('contact_address_id') or None,
                            request=request,
                        )
                        msg = f"تم إنشاء وبدء الزيارة #{visit.serial_num} للعميل {contact.name} بنجاح."
                        if is_ajax:
                            return JsonResponse({
                                'success': True,
                                'message': msg,
                                'visit_id': visit.pk,
                                'status': visit.status,
                                'redirect_url': reverse('visit_detail', kwargs={'pk': visit.pk}),
                            })
                        messages.success(request, msg)
                        return redirect('visit_detail', pk=visit.pk)
                    except ValidationError as ve:
                        err_msg = ve.message if hasattr(ve, 'message') else (ve.messages[0] if hasattr(ve, 'messages') and ve.messages else str(ve))
                        if is_ajax:
                            return JsonResponse({'success': False, 'message': err_msg}, status=400)
                        form.add_error(None, err_msg)
                        messages.error(request, err_msg)
                else:
                    # Planned-Visit Creation Path (from uncreated PlannedVisitItem)
                    from activities.services import resolve_visit_contact_address, snapshot_visit_contact_address
                    addr_error = None
                    selected_addr = None
                    try:
                        selected_addr = resolve_visit_contact_address(
                            contact,
                            contact_address_id=request.POST.get('contact_address_id') or None,
                        )
                    except ValidationError as ve:
                        addr_error = ve.message if hasattr(ve, 'message') else (ve.messages[0] if hasattr(ve, 'messages') and ve.messages else str(ve))
                        form.add_error(None, addr_error)
                        messages.error(request, addr_error)

                if not duplicate_warning and is_planned_visit and not addr_error:
                    with transaction.atomic():
                        visit = form.save(commit=False)
                        visit.created_by = request.user
                        visit.owner = owner
                        visit.is_planned = is_planned_visit
                        visit.date = visit_date
                        visit.status = 'planned'
                        visit.started_at = None
                        visit.allowed_distance = location_settings.get_effective_tolerance(template)
                        snapshot_visit_contact_address(visit, selected_addr)
                        if selected_addr is not None:
                            visit.customer_latitude_snapshot = selected_addr.latitude
                            visit.customer_longitude_snapshot = selected_addr.longitude

                        # Visits submitted through visit_create: resolve approval based on is_planned_visit
                        visit.approval_status, visit.approved_by, visit.approved_at = resolve_visit_creation_approval(
                            request.user, contact, is_planned_visit, location_settings, visit_owner=owner
                        )

                        # Distance verification is not needed to create a visit at all (planned and unplanned are identical)
                        visit.location_verified = False
                        visit.verification_status = 'unverified'
                        visit.location_status = 'بانتظار بدء الزيارة والتحقق من الموقع الجغرافي'
                        visit.requires_approval_due_to_distance = False

                        visit.save()

                        # Persist optional suggested_products answers if submitted at creation
                        if template:
                            sp_answers = dict(visit.questionnaire_answers or {})
                            sp_changed = False
                            for q in template.get_active_questions().filter(question_type='suggested_products'):
                                fname = f'question_{q.id}'
                                if fname in request.POST:
                                    eligible_qs, _, _ = get_question_product_choices(template, question=q)
                                    allowed_ids = set(eligible_qs.values_list('id', flat=True))
                                    parsed_sp = parse_suggested_products_submission(request.POST, fname, allowed_ids, strict=False)
                                    if parsed_sp:
                                        sp_answers[str(q.id)] = parsed_sp
                                        sp_changed = True
                            if sp_changed:
                                visit.questionnaire_answers = sp_answers
                                visit.save(update_fields=['questionnaire_answers'])

                        # Handle product detailing if submitted
                        if template and template.is_product_detailing_supported():
                            detailed_ids = request.POST.getlist('detailed_products')
                            if detailed_ids:
                                eligible_ids = set(Product.get_eligible_for_visits().values_list('id', flat=True))
                                valid_ids = [int(pid) for pid in detailed_ids if str(pid).isdigit() and int(pid) in eligible_ids]
                                visit.detailed_products.set(valid_ids)
                            elif template.has_suggested_products_question() and visit.questionnaire_answers:
                                sp_union = []
                                for q in template.get_active_questions().filter(question_type='suggested_products'):
                                    for pid in (visit.questionnaire_answers.get(str(q.id)) or []):
                                        if str(pid).isdigit() and int(pid) not in sp_union:
                                            sp_union.append(int(pid))
                                if sp_union:
                                    visit.detailed_products.set(sp_union)

                        # Associate or create planned item if visit is planned
                        if planned_item:
                            planned_item.is_executed = False
                            planned_item.visit = visit
                            planned_item.save()
                        elif is_planned_visit:
                            pday, _ = PlannedVisitDay.objects.get_or_create(
                                assignee=owner,
                                date=visit_date,
                                defaults={'created_by': request.user}
                            )
                            existing_pitem = PlannedVisitItem.objects.filter(plan_day=pday, contact=contact, visit__isnull=True).first()
                            if existing_pitem:
                                existing_pitem.visit = visit
                                if template and not existing_pitem.template:
                                    existing_pitem.template = template
                                existing_pitem.save()
                            else:
                                max_ord = pday.items.count() + 1
                                PlannedVisitItem.objects.create(
                                    plan_day=pday,
                                    order=max_ord,
                                    contact=contact,
                                    template=template,
                                    visit=visit,
                                    is_executed=False
                                )

                        # Audit logs
                        ApprovalAuditLog.objects.create(
                            record_type='visit',
                            visit=visit,
                            action='created',
                            actor=request.user,
                            status_before='',
                            status_after=visit.approval_status,
                            reason=f"إنشاء {'زيارة مخططة' if visit.is_planned else 'زيارة خارج الخطة'} للعميل {contact.name}",
                            ip_address=request.META.get('REMOTE_ADDR')
                        )

                        AuditLogService.log(
                            action='create',
                            action_type='VISIT_CREATED',
                            module='visits',
                            user=request.user,
                            request=request,
                            record_id=visit.pk,
                            object_repr=f"Visit #{visit.serial_num}",
                            new_values={
                                'serial_num': visit.serial_num,
                                'contact_id': contact.id,
                                'contact_name': contact.name,
                                'is_planned': visit.is_planned,
                                'date': str(visit.date),
                                'owner_id': owner.id,
                                'template_id': template.id if template else None,
                                'doubled': visit.doubled,
                                'distance': float(visit.distance) if visit.distance is not None else None,
                                'allowed_distance': visit.allowed_distance,
                                'verification_status': visit.verification_status,
                                'approval_status': visit.approval_status,
                                'requires_approval_due_to_distance': visit.requires_approval_due_to_distance,
                            }
                        )

                    messages.success(
                        request,
                        f"تم إنشاء الزيارة #{visit.serial_num} للعميل {contact.name} بنجاح. "
                        f"{'يمكنك بدء الزيارة الآن.' if visit.approval_status == 'approved' else 'الزيارة في انتظار اعتماد المدير.'}"
                    )
                    return redirect('visit_detail', pk=visit.pk)
        else:
            is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'application/json' in request.headers.get('accept', '')
            if is_ajax:
                return JsonResponse({
                    'success': False,
                    'message': form.non_field_errors()[0] if form.non_field_errors() else "فشل التحقق من بيانات الزيارة.",
                    'errors': form.errors.get_json_data()
                }, status=400)
            error_msg = form.non_field_errors()[0] if form.non_field_errors() else "يرجى تصحيح الأخطاء في نموذج تسجيل الزيارة."
            messages.error(request, error_msg)
    else:
        contact_id = request.GET.get('contact') or request.GET.get('contact_id')
        template_id = request.GET.get('template') or request.GET.get('template_id')
        date_param = request.GET.get('date')
        initial_date = timezone.now().date()
        if date_param:
            try:
                parsed_d = datetime.datetime.strptime(date_param, '%Y-%m-%d').date()
                initial_date = parsed_d
            except ValueError:
                pass

        initial = {
            'date': initial_date,
            'owner': request.user,
            'visit_type': 'planned' if is_planned_visit else 'unplanned',
        }
        if planned_item:
            initial['contact'] = planned_item.contact.id
            if planned_item.template:
                initial['template'] = planned_item.template.id
            initial['date'] = planned_item.plan_day.date
            initial['planned_item_id'] = planned_item.pk
            initial['visit_type'] = 'planned'
        else:
            if contact_id:
                initial['contact'] = contact_id
            if template_id:
                initial['template'] = template_id

        form = VisitForm(initial=initial, user=request.user)

    # Preselected customer details for rich card
    selected_contact = None
    if planned_item:
        selected_contact = Contact.objects.filter(pk=planned_item.contact_id).select_related(
            'area', 'area__parent', 'brick'
        ).prefetch_related('addresses__area', 'addresses__brick').first() or planned_item.contact
    else:
        contact_id = request.POST.get('contact') or request.GET.get('contact') or request.GET.get('contact_id')
        if contact_id and str(contact_id).isdigit():
            cand = Contact.objects.filter(pk=int(contact_id)).select_related(
                'area', 'area__parent', 'brick'
            ).prefetch_related('addresses__area', 'addresses__brick').first()
            if cand and can_user_access_contact_for_visit(request.user, cand):
                selected_contact = cand

    from activities.services import serialize_contact_addresses
    selected_contact_addresses = serialize_contact_addresses(selected_contact) if selected_contact else []
    selected_contact_address_id = (request.POST.get('contact_address_id') or '').strip()
    if not selected_contact_address_id and selected_contact_addresses:
        selected_contact_address_id = str(selected_contact_addresses[0]['id'])

    selected_template = None
    template_id_val = request.POST.get('template') or request.GET.get('template') or request.GET.get('template_id') or (planned_item.template_id if planned_item else None)
    if template_id_val and str(template_id_val).isdigit():
        selected_template = VisitTemplate.objects.filter(pk=int(template_id_val)).first()

    effective_tolerance = location_settings.get_effective_tolerance(selected_template)
    products = Product.get_eligible_for_visits()
    templates = [t for t in VisitTemplate.objects.filter(active=True).prefetch_related('restricted_roles').order_by('name') if t.is_user_eligible(request.user)]
    active_open_visit = get_open_visit_for_owner(request.user.pk) if not is_planned_visit else None

    saved_answers_dict = {}
    if request.method == 'POST' and not is_planned_visit:
        for k, vals in request.POST.lists():
            if k.startswith('question_'):
                qid_str = k[len('question_'):]
                saved_answers_dict[qid_str] = vals if len(vals) > 1 else (vals[0] if vals else '')

    return render(request, 'activities/visit_form.html', {
        'form': form,
        'products': products,
        'templates': templates,
        'selected_contact': selected_contact,
        'selected_contact_addresses': selected_contact_addresses,
        'selected_contact_addresses_json': json.dumps(selected_contact_addresses),
        'selected_contact_address_id': selected_contact_address_id,
        'selected_template': selected_template,
        'planned_item': planned_item,
        'planned_item_id': planned_item.pk if planned_item else None,
        'is_planned_visit': is_planned_visit,
        'today': today_date,
        'visit_type': 'planned' if is_planned_visit else 'unplanned',
        'can_bypass_gps': can_bypass_gps,
        'active_open_visit': active_open_visit,
        'saved_answers_json': json.dumps(saved_answers_dict),
        'bypass_reason_mandatory': location_settings.bypass_reason_mandatory,
        'distance_bypass_requires_approval': location_settings.distance_bypass_requires_approval,
        'verify_visits_enabled': location_settings.verify_visits,
        'verify_unplanned_visit_distance': location_settings.verify_unplanned_visit_distance,
        'allow_template_distance_override': location_settings.allow_template_distance_override,
        'gps_tolerance': effective_tolerance,
        'default_tolerance': location_settings.tolerance,
        'today_str': today_str,
        'duplicate_warning': duplicate_warning,
        'existing_same_day_visits': existing_same_day_visits,
        'existing_same_day_plans': existing_same_day_plans,
        'title': 'تسجيل زيارة مخططة' if is_planned_visit else 'تسجيل زيارة خارج الخطة'
    })


@require_permission('activities:visits/edit')
def visit_edit(request, pk):
    """
    Edit visit metadata while visit has not ended (status != 'finished').
    Ended visits remain strictly uneditable.
    Strictly separated from questionnaire answers: editing visit metadata NEVER modifies
    VisitTemplate, its questions, other visits, or `visit.questionnaire_answers`.
    Enforces Post-Approval Editing Reapproval Rules (Section 5.A).
    """
    visit = get_object_or_404(Visit, pk=pk)
    if not can_user_access_object(request.user, visit, 'edit'):
        return render_forbidden_response(request, "غير مصرح لك بتعديل بيانات هذه الزيارة.")

    # Strict restriction: Ended or Cancelled visits CANNOT have their metadata edited
    if visit.status in ('finished', 'cancelled') or visit.ended_at is not None:
        messages.error(request, "لا يمكن تعديل موعد أو قالب الزيارة بعد اكتمالها أو إلغائها.")
        return redirect('visit_detail', pk=visit.pk)

    if request.method == 'POST':
        prev_approval_status = visit.approval_status
        prev_date = visit.date
        prev_template = visit.template
        prev_doubled = visit.doubled
        prev_time = visit.time
        prev_values = {
            'template_id': visit.template_id,
            'template_name': visit.template.display_name_ar if visit.template else '',
            'date': str(visit.date),
            'doubled': visit.doubled,
            'time': str(visit.time) if visit.time else '',
            'approval_status': visit.approval_status,
        }

        form = VisitForm(request.POST, request.FILES, instance=visit, user=request.user)
        if form.is_valid():
            with transaction.atomic():
                cleaned_date = form.cleaned_data.get('date')
                cleaned_template = form.cleaned_data.get('template')
                cleaned_doubled = bool(form.cleaned_data.get('doubled', False))

                visit.date = cleaned_date
                visit.template = cleaned_template
                visit.doubled = cleaned_doubled

                # Track changes
                field_changes = []
                if str(cleaned_date) != str(prev_date):
                    field_changes.append({
                        'field': 'تاريخ الزيارة',
                        'old': str(prev_date),
                        'new': str(cleaned_date),
                    })
                if cleaned_template != prev_template:
                    field_changes.append({
                        'field': 'قالب الزيارة',
                        'old': prev_template.display_name_ar if prev_template else 'بدون قالب',
                        'new': cleaned_template.display_name_ar if cleaned_template else 'بدون قالب',
                    })
                if cleaned_doubled != prev_doubled:
                    field_changes.append({
                        'field': 'زيارة مزدوجة',
                        'old': 'نعم' if prev_doubled else 'لا',
                        'new': 'نعم' if cleaned_doubled else 'لا',
                    })

                changes_summary = " | ".join(
                    f"{c['field']}: ({c['old']}) ➔ ({c['new']})" for c in field_changes
                ) if field_changes else "تعديل موعد وقالب الزيارة"

                user_has_approval_authority = (
                    can_user_approve_contact_visit(request.user, visit.contact) and
                    can_user_access_object(request.user, visit, 'approve')
                )
                was_approved = (prev_approval_status == 'approved')

                if user_has_approval_authority and was_approved:
                    visit.approval_status = 'approved'
                    visit.waiting_for_reapproval = False
                    audit_action = 'edited_by_manager'
                    audit_reason = 'تعديل بيانات الزيارة بواسطة مدير/مشرف معتمد'
                    approval_required = False
                    status_after = 'approved'
                else:
                    visit.approval_status = 'pending'
                    visit.waiting_for_reapproval = True
                    visit.approved_by = None
                    visit.approved_at = None
                    audit_action = 'resubmitted' if prev_approval_status in ('disapproved', 'rejected') else 'edited_reapproval_required'
                    audit_reason = (
                        f"إعادة تقديم الزيارة بعد التعديل: {changes_summary}"
                        if audit_action == 'resubmitted' else
                        f"تعديل بيانات الزيارة قبل البدء (يتطلب إعادة اعتماد المدير): {changes_summary}"
                    )
                    approval_required = True
                    status_after = 'pending'

                fields_to_save = ['date', 'template', 'doubled', 'approval_status', 'waiting_for_reapproval', 'approved_by', 'approved_at', 'updated_at']
                if field_changes:
                    visit.last_edited_by = request.user
                    visit.last_edited_at = timezone.now()
                    if visit.created_by_id and request.user.id == visit.created_by_id:
                        visit.edited_by_creator = True
                    fields_to_save.extend(['edited_by_creator', 'last_edited_by', 'last_edited_at'])
                visit.save(update_fields=fields_to_save)

                new_values = {
                    'template_id': visit.template_id,
                    'template_name': visit.template.display_name_ar if visit.template else '',
                    'date': str(visit.date),
                    'doubled': visit.doubled,
                    'time': str(visit.time) if visit.time else '',
                    'approval_status': visit.approval_status,
                    'waiting_for_reapproval': visit.waiting_for_reapproval,
                }

                ApprovalAuditLog.objects.create(
                    record_type='visit',
                    visit=visit,
                    action=audit_action,
                    actor=request.user,
                    status_before=prev_approval_status,
                    status_after=status_after,
                    reason=audit_reason,
                    changes=field_changes,
                    approval_required=approval_required,
                    context_data={'previous_approval_status': prev_approval_status},
                    ip_address=request.META.get('REMOTE_ADDR')
                )
                AuditLogService.log(
                    action='update',
                    action_type='VISIT_EDITED_BY_MANAGER' if audit_action == 'edited_by_manager' else 'VISIT_EDITED_REAPPROVAL_REQUIRED',
                    module='visits',
                    user=request.user,
                    request=request,
                    record_id=visit.pk,
                    record_name=f"Visit #{visit.serial_num}",
                    description=audit_reason,
                    previous_values=prev_values,
                    new_values=new_values
                )
                if audit_action == 'edited_by_manager':
                    messages.success(request, f"تم حفظ تعديلات المدير على الزيارة #{visit.serial_num} بنجاح مع الاحتفاظ بحالة الاعتماد.")
                else:
                    messages.warning(
                        request,
                        f"تم حفظ التعديلات على الزيارة #{visit.serial_num}. تم تحويل حالتها تلقائياً إلى (قيد الاعتماد) من المدير."
                    )

            return redirect('visit_detail', pk=visit.pk)
        else:
            messages.error(request, "تعذر حفظ التعديلات. يرجى مراجعة الحقول المطلوبة والتأكد من صحتها.")
    else:
        # GET request: Started or Ended visits cannot be opened for editing
        if visit.status in ('started', 'finished') or visit.ended_at is not None:
            messages.error(request, "لا يمكن تعديل موعد أو قالب الزيارة بعد بدئها أو اكتمالها.")
            return redirect('visit_detail', pk=visit.pk)
        form = VisitForm(instance=visit, user=request.user)

    eligible_products = Product.get_eligible_for_visits()
    historical_ids = set(visit.detailed_products.values_list('id', flat=True))
    all_product_ids = set(eligible_products.values_list('id', flat=True)) | historical_ids
    products = Product.objects.filter(id__in=all_product_ids).order_by('name')
    templates = VisitTemplate.objects.filter(active=True).order_by('name')
    selected_contact = visit.contact
    from master_data.models import LocationSettings
    location_settings = LocationSettings.get_settings()
    can_bypass_gps = location_settings.can_user_bypass_without_approval(request.user, stage='end')

    saved_detailed_products = list(visit.detailed_products.values_list('id', flat=True))
    saved_answers = visit.questionnaire_answers or {}

    return render(request, 'activities/visit_form.html', {
        'form': form,
        'visit': visit,
        'products': products,
        'templates': templates,
        'selected_contact': selected_contact,
        'saved_answers': saved_answers,
        'saved_answers_json': json.dumps(saved_answers),
        'saved_detailed_products': saved_detailed_products,
        'can_bypass_gps': can_bypass_gps,
        'is_lower_user': not is_manager_or_higher(request.user),
        'verify_visits_enabled': location_settings.verify_visits,
        'bypass_reason_mandatory': location_settings.bypass_reason_mandatory,
        'default_tolerance': location_settings.tolerance,
        'allow_template_distance_override': location_settings.allow_template_distance_override,
        'gps_tolerance': visit.effective_allowed_distance,
        'today_str': timezone.now().date().strftime('%Y-%m-%d'),
        'title': f'تعديل الزيارة #{visit.serial_num}'
    })


@login_required
def visit_delete(request, pk):
    """
    Permission- and DataScope-controlled deletion of visits at any lifecycle stage.
    Rules:
    - POST only.
    - RBAC (`activities:visits/delete`) and object-level DataScope checked BEFORE
      inspecting or exposing visit existence/status.
    - Allowed across all lifecycle stages (planned, started, finished, cancelled),
      decoupled from LocationSettings.
    - Deletes associated PlannedVisitItem records, cleans up attachments/photo, and logs
      comprehensive snapshot + ApprovalAuditLog history in `SecurityAuditLog` (`VISIT_DELETED`).
    """
    is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'application/json' in request.headers.get('accept', '')
    if request.method != 'POST':
        if is_ajax:
            return JsonResponse({'success': False, 'error': 'MethodNotAllowed', 'message': 'POST method required.'}, status=405)
        messages.error(request, "لا يمكن تنفيذ عملية الحذف إلا عبر طلب POST آمن.")
        return redirect('visit_detail', pk=pk)

    if not has_perm_or_admin(request.user, 'activities:visits/delete'):
        reason = "عذراً، لا تملك صلاحية حذف الزيارات."
        if is_ajax:
            return JsonResponse({'success': False, 'message': reason}, status=403)
        return render_forbidden_response(request, reason)

    visit = Visit.objects.select_related('contact', 'owner', 'template').filter(pk=pk).first()
    if visit is None:
        from accounts.scope_service import ScopeResolutionService
        is_super = request.user.is_superuser or getattr(request.user, 'is_super_admin', False)
        if is_super or ScopeResolutionService.get_user_scope(request.user, 'activities', 'delete') == 'all':
            if is_ajax:
                return JsonResponse({'success': False, 'message': 'الزيارة غير موجودة.'}, status=404)
            raise Http404("Visit not found")
        reason = "غير مصرح لك بحذف هذه الزيارة خارج نطاق صلاحياتك أو منطقتك الجغرافية."
        if is_ajax:
            return JsonResponse({'success': False, 'message': reason}, status=403)
        return render_forbidden_response(request, reason)

    if not can_user_access_object(request.user, visit, 'delete'):
        reason = "غير مصرح لك بحذف هذه الزيارة خارج نطاق صلاحياتك أو منطقتك الجغرافية."
        if is_ajax:
            return JsonResponse({'success': False, 'message': reason}, status=403)
        return render_forbidden_response(request, reason)

    allowed, reason = can_delete_unended_visit(visit, request.user)
    if not allowed:
        if is_ajax:
            return JsonResponse({'success': False, 'message': reason}, status=403)
        return render_forbidden_response(request, reason)

    try:
        snapshot = delete_unended_visit(visit, request.user, request=request)
        msg = f"تم حذف الزيارة #{snapshot['serial_num']} بنجاح."
        if is_ajax:
            return JsonResponse({'success': True, 'message': msg, 'redirect_url': reverse('visits_list')})
        messages.success(request, msg)
        return redirect('visits_list')
    except ValidationError as ve:
        err_msg = ve.message if hasattr(ve, 'message') else (ve.messages[0] if hasattr(ve, 'messages') and ve.messages else str(ve))
        if is_ajax:
            return JsonResponse({'success': False, 'message': err_msg}, status=400)
        messages.error(request, err_msg)
        return redirect('visit_detail', pk=pk)


@require_permission(['activities:visits/edit_answers', 'activities:visits/edit'])
def visit_update_answers(request, pk):
    """
    Separate operation to update a visit's questionnaire answers (Requirement D):
    - Allowed ONLY for the visit creator/owner (or SuperAdmin).
    - Never modifies VisitTemplate, its questions, or other visits.
    - Preserves `visit.approval_status` and `visit.waiting_for_reapproval` unchanged.
    - Records before/after answer diffs in the visit timeline and audit trail.
    """
    is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'application/json' in request.headers.get('accept', '')
    if request.method != 'POST':
        if is_ajax:
            return JsonResponse({'success': False, 'message': 'POST method required.'}, status=405)
        return redirect('visit_detail', pk=pk)

    visit = get_object_or_404(Visit.objects.select_related('template', 'contact', 'owner'), pk=pk)

    allowed, reason = can_edit_visit_answers(visit, request.user)
    if not allowed:
        if is_ajax:
            return JsonResponse({'success': False, 'message': reason}, status=403)
        return render_forbidden_response(request, reason)

    try:
        updated_visit, answer_changes = update_visit_questionnaire_answers(
            visit, request.user, request.POST, request=request
        )
        if answer_changes:
            msg = f"تم تحديث إجابات استبيان الزيارة #{updated_visit.serial_num} بنجاح وتوثيق التغييرات في السجل الزمني."
        else:
            msg = "لم يتم إجراء أي تغييرات على إجابات الاستبيان."
        if is_ajax:
            return JsonResponse({
                'success': True,
                'message': msg,
                'changes_count': len(answer_changes),
                'changes': answer_changes,
            })
        messages.success(request, msg)
    except ValidationError as ve:
        err_msg = ve.message if hasattr(ve, 'message') else (ve.messages[0] if hasattr(ve, 'messages') and ve.messages else str(ve))
        if is_ajax:
            return JsonResponse({'success': False, 'message': err_msg}, status=400)
        messages.error(request, err_msg)

    return redirect('visit_detail', pk=pk)


@login_required
def plan_action(request, pk, action):
    """
    Plan-Level Approval Workflow (Requirement 4.B):
    Approve or reject an entire visit plan and all its associated visits.
    Enforces activities:visits/approve permission, organizational data scope,
    and anti-self-approval rule.
    """
    plan = get_object_or_404(VisitPlan, pk=pk)
    is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'application/json' in request.headers.get('accept', '')
    next_url = request.POST.get('next') or request.GET.get('next')

    def get_redirect():
        from django.utils.http import url_has_allowed_host_and_scheme
        if next_url and url_has_allowed_host_and_scheme(
            next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
        ):
            return redirect(next_url)
        return redirect('planned_visits_list')

    if action in ('approve', 'disapprove', 'reject'):
        if not can_manage_approvals(request.user) or not can_user_access_object(request.user, plan, action):
            msg = "غير مصرح لك باتخاذ إجراء اعتماد على هذه الخطة (خارج نطاق صلاحياتك أو لا يمكن للمستخدم اعتماد خطته بنفسه)."
            if is_ajax:
                return JsonResponse({'success': False, 'message': msg}, status=403)
            messages.error(request, msg)
            return get_redirect()

        if plan.approval_status != 'pending':
            msg = "تم اتخاذ قرار الاعتماد لهذه الخطة مسبقاً ولا يمكن تغييره."
            if is_ajax:
                return JsonResponse({'success': False, 'message': msg}, status=400)
            messages.warning(request, msg)
            return get_redirect()

        notes = request.POST.get('approval_notes', '').strip() or request.POST.get('reason', '').strip()

        with transaction.atomic():
            if action == 'approve':
                plan.approval_status = 'approved'
                plan.approved_by = request.user
                plan.approved_at = timezone.now()
                plan.approval_notes = notes
                plan.save(update_fields=['approval_status', 'approved_by', 'approved_at', 'approval_notes', 'updated_at'])

                # Update all visits in this plan
                plan.visits.update(
                    approval_status='approved',
                    approved_by=request.user,
                    approved_at=timezone.now()
                )

                for v in plan.visits.all():
                    ApprovalAuditLog.objects.create(
                        record_type='visit',
                        visit=v,
                        action='approved',
                        actor=request.user,
                        status_before='pending',
                        status_after='approved',
                        reason=f"اعتماد خطة الزيارات رقم {plan.plan_id}: {notes or 'تم الاعتماد'}",
                        ip_address=request.META.get('REMOTE_ADDR')
                    )

                AuditLogService.log(
                    action='update',
                    action_type='VISIT_PLAN_APPROVED',
                    module='activities',
                    user=request.user,
                    request=request,
                    record_id=plan.pk,
                    object_repr=f"VisitPlan #{plan.plan_id}",
                    new_values={'approval_status': 'approved', 'reason': notes}
                )
                msg = f"تم اعتماد خطة الزيارات رقم {plan.plan_id} وجميع زياراتها بنجاح."

            else:
                plan.approval_status = 'disapproved'
                plan.approved_by = request.user
                plan.approved_at = timezone.now()
                plan.approval_notes = notes
                plan.save(update_fields=['approval_status', 'approved_by', 'approved_at', 'approval_notes', 'updated_at'])

                plan.visits.update(
                    approval_status='disapproved',
                    approved_by=request.user,
                    approved_at=timezone.now(),
                    approval_notes=notes
                )

                for v in plan.visits.all():
                    ApprovalAuditLog.objects.create(
                        record_type='visit',
                        visit=v,
                        action='rejected',
                        actor=request.user,
                        status_before='pending',
                        status_after='disapproved',
                        reason=f"رفض خطة الزيارات رقم {plan.plan_id}: {notes or 'تم الرفض'}",
                        ip_address=request.META.get('REMOTE_ADDR')
                    )

                AuditLogService.log(
                    action='update',
                    action_type='VISIT_PLAN_DISAPPROVED',
                    module='activities',
                    user=request.user,
                    request=request,
                    record_id=plan.pk,
                    object_repr=f"VisitPlan #{plan.plan_id}",
                    new_values={'approval_status': 'disapproved', 'reason': notes}
                )
                msg = f"تم رفض خطة الزيارات رقم {plan.plan_id}."

        if is_ajax:
            return JsonResponse({'success': True, 'message': msg, 'approval_status': plan.approval_status})
        messages.success(request, msg)
        return get_redirect()

    return JsonResponse({'success': False, 'message': 'إجراء غير صالح'}, status=400)



@login_required
def visit_action(request, pk, action):
    """
    Approve, disapprove/reject, or resubmit visit.
    Enforces regional authority, prevents representative self-approval,
    records audit trail, and handles resubmission workflow.
    """
    visit = get_object_or_404(Visit, pk=pk)
    is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'application/json' in request.headers.get('accept', '')
    next_url = request.POST.get('next') or request.GET.get('next')

    def get_redirect():
        from django.utils.http import url_has_allowed_host_and_scheme
        if next_url and url_has_allowed_host_and_scheme(
            next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
        ):
            return redirect(next_url)
        return redirect('visit_detail', pk=visit.pk)

    if action == 'start':
        if visit.status == 'started':
            msg = f"الزيارة #{visit.serial_num} جارية بالفعل وقيد التوثيق."
            if is_ajax:
                return JsonResponse({'success': True, 'message': msg, 'status': 'started'})
            messages.info(request, msg)
            return get_redirect()

        if visit.status == 'finished':
            msg = "لا يمكن بدء زيارة منتهية بالفعل."
            if is_ajax:
                return JsonResponse({'success': False, 'message': msg}, status=400)
            messages.error(request, msg)
            return get_redirect()

        from master_data.models import LocationSettings
        loc_settings = LocationSettings.get_settings()
        can_bypass_gps = loc_settings.can_user_bypass_without_approval(request.user, stage='start')
        force_bypass_raw = request.POST.get('force_bypass_location') in ('1', 'true', 'True', 'on')
        if force_bypass_raw and not can_bypass_gps:
            msg = "عذراً، لا تملك صلاحية تجاوز التحقق الجغرافي (GPS)."
            if is_ajax:
                return JsonResponse({'success': False, 'message': msg}, status=400)
            messages.error(request, msg)
            return get_redirect()
        force_bypass = bool(force_bypass_raw)

        # Collect check-in questions (stage == 'start_only')
        checkin_answers = extract_checkin_answers_from_post(request.POST, visit.template)

        try:
            start_visit(
                visit, request.user, request=request,
                lat=request.POST.get('latitude') or request.GET.get('latitude'),
                lng=request.POST.get('longitude') or request.GET.get('longitude'),
                accuracy=request.POST.get('device_accuracy') or request.GET.get('device_accuracy'),
                force_bypass=force_bypass,
                bypass_reason=request.POST.get('bypass_reason', ''),
                checkin_answers=checkin_answers,
                contact_address_id=request.POST.get('contact_address_id') or None,
            )
            msg = f"تم بدء الزيارة #{visit.serial_num} بنجاح. يمكنك الآن استكمال الاستبيان والإنهاء."
            if is_ajax:
                return JsonResponse({'success': True, 'message': msg, 'status': 'started'})
            messages.success(request, msg)
        except ValidationError as e:
            msg = e.message if hasattr(e, 'message') else (e.messages[0] if hasattr(e, 'messages') and e.messages else str(e))
            if is_ajax:
                return JsonResponse({'success': False, 'message': msg}, status=400)
            messages.error(request, msg)
        return get_redirect()

    elif action == 'end':
        from master_data.models import LocationSettings
        loc_settings = LocationSettings.get_settings()
        can_bypass_gps = loc_settings.can_user_bypass_without_approval(request.user, stage='end')
        force_bypass_raw = request.POST.get('force_bypass_location') in ('1', 'true', 'True', 'on')
        if force_bypass_raw and not can_bypass_gps:
            msg = "عذراً، لا تملك صلاحية تجاوز التحقق الجغرافي (GPS)."
            if is_ajax:
                return JsonResponse({'success': False, 'message': msg}, status=400)
            messages.error(request, msg)
            return get_redirect()
        force_bypass = bool(force_bypass_raw)
        try:
            end_visit(
                visit, request.user, request=request,
                lat=request.POST.get('latitude'),
                lng=request.POST.get('longitude'),
                accuracy=request.POST.get('device_accuracy'),
                force_bypass=force_bypass,
                bypass_reason=request.POST.get('bypass_reason', '')
            )
            msg = f"تم إنهاء وتوثيق الزيارة #{visit.serial_num} بنجاح. استغرقت الزيارة {visit.duration_formatted}."
            if is_ajax:
                return JsonResponse({
                    'success': True,
                    'message': msg,
                    'status': 'finished',
                    'approval_status': visit.approval_status,
                    'requires_approval_due_to_distance': visit.requires_approval_due_to_distance,
                    'duration': visit.duration,
                    'duration_formatted': visit.duration_formatted
                })
            messages.success(request, msg)
        except ValidationError as e:
            msg = e.message if hasattr(e, 'message') else str(e)
            if is_ajax:
                return JsonResponse({'success': False, 'message': msg}, status=400)
            messages.error(request, msg)
        return get_redirect()

    elif action in ('approve', 'disapprove', 'reject'):
        if not can_user_approve_contact_visit(request.user, visit.contact) or not can_user_access_object(request.user, visit, action):
            msg = "غير مصرح لك باتخاذ إجراء اعتماد على هذه الزيارة (خارج نطاق مسؤوليتك الإقليمية أو المندوب العادي لا يمكنه اعتماد زيارته الخاصة)."
            if is_ajax:
                return JsonResponse({'success': False, 'message': msg}, status=403)
            messages.error(request, msg)
            return get_redirect()

        if visit.approval_status != 'pending':
            if visit.approval_status == 'approved':
                msg = "لا يمكن تعديل قرار الاعتماد لأن الزيارة معتمدة بالفعل."
            else:
                msg = "تم رفض هذه الزيارة مسبقاً. يجب إعادة تقديمها من المندوب قبل اتخاذ قرار اعتماد جديد."
            if is_ajax:
                return JsonResponse({'success': False, 'message': msg}, status=400)
            messages.warning(request, msg)
            return get_redirect()

        notes = request.POST.get('approval_notes', '').strip() or request.POST.get('reason', '').strip()

        if action == 'approve':
            status_before = visit.approval_status
            was_reapproval = visit.waiting_for_reapproval
            was_distance_exception = visit.requires_approval_due_to_distance
            visit.approval_status = 'approved'
            visit.waiting_for_reapproval = False
            visit.requires_approval_due_to_distance = False
            visit.approved_by = request.user
            visit.approved_at = timezone.now()
            if notes:
                visit.approval_notes = notes
            visit.save()

            default_reason = 'تم إعادة اعتماد الزيارة بعد التعديل من قبل المدير' if was_reapproval else (
                'تم اعتماد استثناء المسافة والزيارة من قبل المدير' if was_distance_exception else 'تم اعتماد الزيارة من قبل المدير الإقليمي'
            )
            ApprovalAuditLog.objects.create(
                record_type='visit',
                visit=visit,
                action='approved',
                actor=request.user,
                status_before=status_before,
                status_after='approved',
                reason=notes or default_reason,
                ip_address=request.META.get('REMOTE_ADDR')
            )
            AuditLogService.log(
                action='approve',
                action_type='VISIT_APPROVED',
                module='visits',
                user=request.user,
                request=request,
                record_id=visit.pk,
                object_repr=f"Visit #{visit.serial_num}",
                previous_values={'approval_status': status_before, 'waiting_for_reapproval': was_reapproval, 'requires_approval_due_to_distance': was_distance_exception},
                new_values={'approval_status': 'approved', 'waiting_for_reapproval': False, 'requires_approval_due_to_distance': False, 'reason': notes or default_reason}
            )
            msg = f"تم اعتماد الزيارة #{visit.serial_num} بنجاح."
            if is_ajax:
                return JsonResponse({'success': True, 'message': msg, 'status': 'approved'})
            messages.success(request, msg)

        elif action in ('disapprove', 'reject'):
            if visit.approval_status == 'approved':
                msg = "لا يمكن رفض زيارة معتمدة بالفعل."
                if is_ajax:
                    return JsonResponse({'success': False, 'message': msg}, status=400)
                messages.error(request, msg)
                return get_redirect()

            if not notes:
                msg = "يرجى توضيح سبب الرفض لتحديد التعديلات المطلوبة من قبل المندوب."
                if is_ajax:
                    return JsonResponse({'success': False, 'message': msg}, status=400)
                messages.error(request, msg)
                return get_redirect()

            status_before = visit.approval_status
            visit.approval_status = 'disapproved'
            visit.waiting_for_reapproval = False
            visit.approved_by = request.user
            visit.approved_at = timezone.now()
            visit.approval_notes = notes
            visit.save()

            ApprovalAuditLog.objects.create(
                record_type='visit',
                visit=visit,
                action='rejected',
                actor=request.user,
                status_before=status_before,
                status_after='disapproved',
                reason=notes,
                ip_address=request.META.get('REMOTE_ADDR')
            )
            AuditLogService.log(
                action='reject',
                action_type='VISIT_REJECTED',
                module='visits',
                user=request.user,
                request=request,
                record_id=visit.pk,
                object_repr=f"Visit #{visit.serial_num}",
                previous_values={'approval_status': status_before},
                new_values={'approval_status': 'disapproved', 'reason': notes}
            )
            msg = f"تم رفض الزيارة #{visit.serial_num} وإعادتها للمندوب للمراجعة والتصحيح."
            if is_ajax:
                return JsonResponse({'success': True, 'message': msg, 'status': 'disapproved'})
            messages.error(request, msg)

    elif action == 'resubmit':
        is_owner = (visit.owner == request.user)
        can_resubmit_override = request.user.is_superuser or getattr(request.user, 'is_super_admin', False)
        if not (is_owner or can_resubmit_override):
            msg = "غير مصرح لك بإعادة تقديم هذه الزيارة (فقط المندوب المسؤول عن الزيارة يمكنه إعادة تقديمها)."
            return render_forbidden_response(request, msg)

        if visit.approval_status not in ('disapproved', 'rejected'):
            msg = "لا يمكن إعادة تقديم زيارة إلا إذا كانت مرفوضة بحاجة لتصحيح."
            if is_ajax:
                return JsonResponse({'success': False, 'message': msg}, status=400)
            messages.warning(request, msg)
            return get_redirect()

        status_before = visit.approval_status
        visit.approval_status = 'pending'
        visit.approved_by = None
        visit.approved_at = None
        resubmit_notes = request.POST.get('notes', '').strip() or request.POST.get('approval_notes', '').strip() or "إعادة تقديم بعد مراجعة الملاحظات وتصحيحها"
        visit.save()

        ApprovalAuditLog.objects.create(
            record_type='visit',
            visit=visit,
            action='resubmitted',
            actor=request.user,
            status_before=status_before,
            status_after='pending',
            reason=resubmit_notes,
            ip_address=request.META.get('REMOTE_ADDR')
        )
        AuditLogService.log(
            action='update',
            action_type='VISIT_RESUBMITTED',
            module='visits',
            user=request.user,
            request=request,
            record_id=visit.pk,
            object_repr=f"Visit #{visit.serial_num}",
            previous_values={'approval_status': status_before},
            new_values={'approval_status': 'pending', 'reason': resubmit_notes}
        )
        msg = f"تمت إعادة تقديم الزيارة #{visit.serial_num} للمدير للاعتماد."
        if is_ajax:
            return JsonResponse({'success': True, 'message': msg, 'status': 'pending'})
        messages.success(request, msg)

    elif action in ('change_status', 'manage_status'):
        msg = "إجراء تغيير الحالة اليدوي لم يعد مدعوماً. يرجى استخدام إجراءات سير العمل المعتمدة (اعتماد / بدء / إنهاء)."
        if is_ajax:
            return JsonResponse({'success': False, 'message': msg}, status=400)
        messages.error(request, msg)
        return get_redirect()

    elif action == 'send_to_agenda':
        msg = "تظهر جميع الزيارات المعتمدة غير الملغاة تلقائياً في جدول الأعمال دون الحاجة لإرسال يدوي."
        if is_ajax:
            return JsonResponse({'success': False, 'message': msg}, status=410)
        messages.info(request, msg)
        return get_redirect()

    else:
        msg = "إجراء غير معروف."
        if is_ajax:
            return JsonResponse({'success': False, 'message': msg}, status=400)
        messages.error(request, msg)

    return get_redirect()


@require_permission('activities:visits/export')
def visits_export(request):
    """Export visits to Excel (.xlsx) with CompanyProfile branding and full filter parity."""
    from master_data.excel_utils import export_to_excel_response

    qs = (
        Visit.objects.select_related('contact', 'template', 'owner', 'last_edited_by')
        .prefetch_related('samples__product', 'template__questions', 'detailed_products')
        .all()
        .order_by('-serial_num')
    )
    qs = get_scoped_queryset(qs, request.user, 'visit')

    can_view_gps_suspicion = has_perm_or_admin(request.user, 'activities:visits/view_gps_suspicion')
    qs, _ = _apply_visits_list_filters(request, qs, can_view_gps_suspicion=can_view_gps_suspicion)
    export_visits = list(qs)
    preload_visit_qa_product_map(export_visits)

    columns = [
        {'header': 'رقم الزيارة', 'key': lambda v: f"#{v.serial_num}", 'width': 14, 'align': 'center'},
        {'header': 'العميل', 'key': lambda v: v.contact.name if v.contact else '', 'width': 30, 'align': 'right'},
        {'header': 'كود العميل', 'key': lambda v: v.contact.code if v.contact else '', 'width': 14, 'align': 'center'},
        {'header': 'التاريخ', 'key': lambda v: v.date.strftime('%Y-%m-%d') if v.date else '', 'width': 14, 'align': 'center'},
        {'header': 'المسؤول', 'key': lambda v: (v.owner.name or v.owner.username) if v.owner else '', 'width': 22, 'align': 'right'},
        {'header': 'القالب', 'key': lambda v: v.template.display_name_ar if v.template else '', 'width': 22, 'align': 'right'},
        {'header': 'الحالة', 'key': lambda v: v.status_display_ar, 'width': 14, 'align': 'center'},
        {'header': 'حالة الاعتماد', 'key': lambda v: v.approval_display_ar, 'width': 14, 'align': 'center'},
        {'header': 'تم التعديل بواسطة المنشئ', 'key': lambda v: 'نعم' if v.edited_by_creator else 'لا', 'width': 18, 'align': 'center'},
        {'header': 'إجابات الاستبيان', 'key': lambda v: ' | '.join(f"{qa['question_text']}: {qa['answer']}" for qa in v.qa_display_list) or 'لم يتم تسجيل إجابات بعد', 'width': 45, 'align': 'right'},
        {'header': 'مزدوجة', 'key': lambda v: 'نعم' if v.doubled else 'لا', 'width': 10, 'align': 'center'},
        {'header': 'المدة (ثواني)', 'key': 'duration', 'width': 14, 'align': 'center'},
        {'header': 'العينات الموزعة', 'key': lambda v: ', '.join(f"{s.product.name} ({s.quantity})" for s in v.samples.all()), 'width': 30, 'align': 'right'},
    ]
    if can_view_gps_suspicion:
        columns.append({'header': 'نزاهة الموقع (GBS)', 'key': lambda v: v.gps_integrity_status_display_ar, 'width': 18, 'align': 'center'})
        columns.append({'header': 'إشارات الاشتباه', 'key': lambda v: v.gps_suspicion_reason or '—', 'width': 35, 'align': 'right'})
    return export_to_excel_response(
        export_visits,
        columns,
        filename=f"visits_{timezone.now().strftime('%Y%m%d_%H%M')}",
        sheet_title="سجل الزيارات",
        report_title="تقرير سجل الزيارات الميدانية",
        user=request.user,
    )


# -----------------------------------------------------------------------------
# VISIT TEMPLATES MODULE (إدارة قوالب الزيارات)
# -----------------------------------------------------------------------------
# VISIT TEMPLATES & QUESTION BUILDER MODULE (قوالب الزيارات)
# -----------------------------------------------------------------------------

@require_permission('settings:visitsTemplates/manage')
def visit_templates_export(request):
    """Export visit templates to Excel honoring active filters."""
    from master_data.excel_utils import export_to_excel_response

    qs = VisitTemplate.objects.prefetch_related('questions').annotate(
        usage_count=Count('visits'),
        q_count=Count('questions', distinct=True),
    ).order_by('id')

    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(
            Q(name__icontains=q) |
            Q(display_name_ar__icontains=q) |
            Q(display_name_en__icontains=q)
        )
    status = request.GET.get('status')
    if status == 'active':
        qs = qs.filter(active=True)
    elif status == 'inactive':
        qs = qs.filter(active=False)

    columns = [
        {'header': 'المعرف', 'key': 'id', 'width': 10, 'align': 'center'},
        {'header': 'اسم القالب', 'key': lambda t: t.display_name_ar or t.name, 'width': 32, 'align': 'right'},
        {'header': 'الاسم بالإنجليزية', 'key': lambda t: t.display_name_en or '', 'width': 25, 'align': 'left'},
        {'header': 'النمط', 'key': lambda t: t.mode or '', 'width': 16, 'align': 'center'},
        {'header': 'عدد الأسئلة', 'key': 'q_count', 'width': 14, 'align': 'center'},
        {'header': 'مرات الاستخدام', 'key': 'usage_count', 'width': 16, 'align': 'center'},
        {'header': 'الحالة', 'key': lambda t: 'مفعل' if t.active else 'معطل', 'width': 14, 'align': 'center'},
    ]
    return export_to_excel_response(
        qs,
        columns,
        filename='visit_templates_export',
        sheet_title='قوالب الزيارات',
        report_title='تقرير قوالب الزيارات الميدانية',
        user=request.user,
    )


@require_permission('settings:visitsTemplates/manage')
def visit_templates_list(request):
    """
    List visit templates with status badges, questions count, mode, and target accounts.
    Matches https://weapharma.bricks-rep.com/settings/visits/templates
    """
    qs = VisitTemplate.objects.prefetch_related('questions', 'restricted_roles').annotate(
        usage_count=Count('visits')
    ).order_by('id')

    q = request.GET.get('q', '').strip()
    active_filters = []

    if q:
        qs = qs.filter(
            Q(name__icontains=q) |
            Q(display_name_ar__icontains=q) |
            Q(display_name_en__icontains=q)
        )
        active_filters.append({'label': f'بحث: {q}', 'param': 'q'})

    status = request.GET.get('status')
    if status == 'active':
        qs = qs.filter(active=True)
        active_filters.append({'label': 'الحالة: مفعل', 'param': 'status'})
    elif status == 'inactive':
        qs = qs.filter(active=False)
        active_filters.append({'label': 'الحالة: معطل', 'param': 'status'})

    paginator, page_obj = paginate_queryset(request, qs, default_per_page=25, max_per_page=100)

    active_count = qs.filter(active=True).count()

    return render(request, 'activities/visit_templates_list.html', {
        'templates': page_obj.object_list,
        'page_obj': page_obj,
        'paginator': paginator,
        'total_count': paginator.count,
        'active_count': active_count,
        'selected_q': q,
        'selected_status': status,
        'active_filters': active_filters,
        'can_manage': can_manage_templates(request.user),
    })


@require_permission('settings:visitsTemplates/manage')
def visit_template_create(request):
    """Create a new visit template with accordions for settings, location, and constraints."""
    if not can_manage_templates(request.user):
        messages.error(request, "عذراً، لا تمتلك الصلاحية الكافية لإنشاء قوالب الزيارات.")
        return redirect('visit_templates_list')

    if request.method == 'POST':
        form = VisitTemplateForm(request.POST)
        if form.is_valid():
            template = form.save()
            messages.success(request, f"تم إنشاء القالب '{template.display_name_ar}' بنجاح. يمكنك الآن إضافة الأسئلة والاستبيان.")
            return redirect('visit_template_edit', pk=template.pk)
        else:
            messages.error(request, "يرجى تصحيح الأخطاء في نموذج إنشاء القالب.")
    else:
        form = VisitTemplateForm()

    return render(request, 'activities/visit_template_form.html', {
        'form': form,
        'is_create': True,
        'title': 'إنشاء قالب زيارة جديد'
    })


@require_permission('settings:visitsTemplates/manage')
def visit_template_edit(request, pk):
    """
    Edit an existing visit template and manage its questions, choices, conditionals, and stages.
    """
    if not can_manage_templates(request.user):
        messages.error(request, "عذراً، لا تمتلك الصلاحية الكافية لتعديل قوالب الزيارات.")
        return redirect('visit_templates_list')

    template = get_object_or_404(VisitTemplate.objects.prefetch_related('questions'), pk=pk)

    if request.method == 'POST':
        form = VisitTemplateForm(request.POST, instance=template)
        if form.is_valid():
            form.save()
            messages.success(request, f"تم تحديث إعدادات القالب '{template.display_name_ar}' بنجاح.")
            return redirect('visit_template_edit', pk=template.pk)
        else:
            messages.error(request, "يرجى تصحيح الأخطاء في نموذج القالب.")
    else:
        form = VisitTemplateForm(instance=template)

    questions = template.questions.all().order_by('order', 'id')
    question_form = VisitTemplateQuestionForm(template=template)

    return render(request, 'activities/visit_template_form.html', {
        'form': form,
        'template': template,
        'questions': questions,
        'question_form': question_form,
        'is_create': False,
        'title': f'تعديل قالب: {template.display_name_ar}'
    })


@require_permission('settings:visitsTemplates/manage')
def visit_template_preview(request, pk):
    """Interactive questionnaire preview simulating representative mobile/tablet device screen."""
    template = get_object_or_404(VisitTemplate.objects.prefetch_related('questions', 'suggested_products'), pk=pk)
    questions = template.get_active_questions()
    suggested_products_pool = list(template.get_suggested_products_pool())
    products = suggested_products_pool[:10] if suggested_products_pool else list(Product.get_eligible_for_visits()[:10])

    start_questions = [q for q in questions if q.stage == 'start_only']
    completion_questions = [q for q in questions if q.stage in ['all', 'end_only']]

    return render(request, 'activities/visit_template_preview.html', {
        'template': template,
        'questions': questions,
        'start_questions': start_questions,
        'completion_questions': completion_questions,
        'products': products,
        'suggested_products_pool': suggested_products_pool,
        'has_suggested_products_question': any(q.question_type == 'suggested_products' for q in questions),
        'title': f'معاينة استبيان: {template.display_name_ar}'
    })


@require_permission('settings:visitsTemplates/manage')
def visit_template_delete(request, pk):
    """
    Delete or deactivate template.
    If template has associated visits, prevents hard delete to preserve historical data integrity.
    """
    if not can_manage_templates(request.user):
        messages.error(request, "عذراً، لا تمتلك الصلاحية الكافية لحذف قوالب الزيارات.")
        return redirect('visit_templates_list')

    template = get_object_or_404(VisitTemplate, pk=pk)
    visits_count = template.visits.count()

    if visits_count > 0:
        template.active = False
        template.save()
        messages.warning(
            request,
            f"لا يمكن حذف القالب '{template.display_name_ar}' نهائياً لوجود {visits_count} زيارة مرتبطة به. "
            "تم إلغاء تفعيل القالب تلقائياً لحماية سلامة السجلات التاريخية."
        )
    else:
        name = template.display_name_ar
        template.delete()
        messages.success(request, f"تم حذف القالب '{name}' بنجاح.")

    return redirect('visit_templates_list')


@require_permission('settings:visitsTemplates/manage')
def visit_template_toggle_status(request, pk):
    """Fast toggle active status of visit template."""
    if not can_manage_templates(request.user):
        return JsonResponse({'success': False, 'message': 'غير مصرح.'}, status=403)

    template = get_object_or_404(VisitTemplate, pk=pk)
    template.active = not template.active
    template.save()

    is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'application/json' in request.headers.get('accept', '')
    if is_ajax:
        return JsonResponse({'success': True, 'active': template.active})

    status_str = "تفعيل" if template.active else "تعطيل"
    messages.success(request, f"تم {status_str} القالب '{template.display_name_ar}' بنجاح.")
    return redirect('visit_templates_list')


# -----------------------------------------------------------------------------
# QUESTION BUILDER AJAX & FORM ENDPOINTS
# -----------------------------------------------------------------------------

@require_permission('settings:visitsTemplates/manage')
def template_question_add(request, template_pk):
    """Add a question to a template with options and conditional logic."""
    if not can_manage_templates(request.user):
        return JsonResponse({'success': False, 'message': 'غير مصرح.'}, status=403)

    template = get_object_or_404(VisitTemplate, pk=template_pk)

    if request.method == 'POST':
        text_ar = request.POST.get('text_ar', '').strip()
        text_en = request.POST.get('text_en', '').strip()
        question_type = request.POST.get('question_type', 'single_choice')
        valid_q_types = dict(VisitTemplateQuestion.QUESTION_TYPES)
        if question_type not in valid_q_types:
            messages.error(request, "نوع السؤال المحدد غير صالح.")
            return redirect('visit_template_edit', pk=template_pk)
        stage = 'end_only'
        is_required = request.POST.get('is_required') in ['true', '1', 'on']
        is_conditional = request.POST.get('is_conditional') in ['true', '1', 'on']
        conditional_parent_id = request.POST.get('conditional_parent') or None
        conditional_trigger_value = request.POST.get('conditional_trigger_value', '').strip()

        if not text_ar:
            messages.error(request, "يرجى كتابة نص السؤال بالعربية.")
            return redirect('visit_template_edit', pk=template_pk)

        # Build options list from POST (not used for suggested_products)
        options = []
        if question_type in ['single_choice', 'multiple_choice']:
            raw_options = request.POST.get('options_json')
            if raw_options:
                try:
                    options = json.loads(raw_options)
                except Exception:
                    options = []
            if not options:
                opt_texts_ar = request.POST.getlist('option_text_ar[]')
                opt_texts_en = request.POST.getlist('option_text_en[]')
                opt_values = request.POST.getlist('option_value[]')
                for i in range(len(opt_texts_ar)):
                    val = opt_values[i] if i < len(opt_values) and opt_values[i] else opt_texts_ar[i]
                    en = opt_texts_en[i] if i < len(opt_texts_en) else ''
                    if opt_texts_ar[i].strip():
                        options.append({
                            'text_ar': opt_texts_ar[i].strip(),
                            'text_en': en.strip(),
                            'value': val.strip()
                        })

        max_order = template.questions.count() + 1
        question = VisitTemplateQuestion.objects.create(
            template=template,
            text_ar=text_ar,
            text_en=text_en,
            question_type=question_type,
            options=options,
            stage=stage,
            is_required=is_required,
            is_conditional=is_conditional,
            conditional_parent_id=conditional_parent_id,
            conditional_trigger_value=conditional_trigger_value,
            order=max_order
        )

        is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'application/json' in request.headers.get('accept', '')
        if is_ajax:
            return JsonResponse({'success': True, 'question_id': question.id})

        messages.success(request, f"تمت إضافة السؤال '{question.text_ar}' بنجاح.")
        return redirect('visit_template_edit', pk=template_pk)


@require_permission('settings:visitsTemplates/manage')
def template_question_edit(request, question_pk):
    """Edit an existing template question."""
    if not can_manage_templates(request.user):
        return JsonResponse({'success': False, 'message': 'غير مصرح.'}, status=403)

    question = get_object_or_404(VisitTemplateQuestion, pk=question_pk)
    template_pk = question.template_id

    if request.method == 'POST':
        text_ar = request.POST.get('text_ar', '').strip()
        text_en = request.POST.get('text_en', '').strip()
        question_type = request.POST.get('question_type', question.question_type)
        valid_q_types = dict(VisitTemplateQuestion.QUESTION_TYPES)
        if question_type not in valid_q_types:
            messages.error(request, "نوع السؤال المحدد غير صالح.")
            return redirect('visit_template_edit', pk=template_pk)
        stage = 'end_only'
        is_required = request.POST.get('is_required') in ['true', '1', 'on']
        is_conditional = request.POST.get('is_conditional') in ['true', '1', 'on']
        conditional_parent_id = request.POST.get('conditional_parent') or None
        conditional_trigger_value = request.POST.get('conditional_trigger_value', '').strip()

        if text_ar:
            question.text_ar = text_ar
        question.text_en = text_en
        question.question_type = question_type
        question.stage = stage
        question.is_required = is_required
        question.is_conditional = is_conditional
        question.conditional_parent_id = conditional_parent_id
        question.conditional_trigger_value = conditional_trigger_value

        # Build options list from POST
        if question_type == 'suggested_products':
            question.options = []
        elif question_type in ['single_choice', 'multiple_choice']:
            raw_options = request.POST.get('options_json')
            if raw_options:
                try:
                    question.options = json.loads(raw_options)
                except Exception:
                    pass
            else:
                opt_texts_ar = request.POST.getlist('option_text_ar[]')
                opt_texts_en = request.POST.getlist('option_text_en[]')
                opt_values = request.POST.getlist('option_value[]')
                if opt_texts_ar:
                    opts = []
                    for i in range(len(opt_texts_ar)):
                        val = opt_values[i] if i < len(opt_values) and opt_values[i] else opt_texts_ar[i]
                        en = opt_texts_en[i] if i < len(opt_texts_en) else ''
                        if opt_texts_ar[i].strip():
                            opts.append({
                                'text_ar': opt_texts_ar[i].strip(),
                                'text_en': en.strip(),
                                'value': val.strip()
                            })
                    question.options = opts

        question.save()

        is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'application/json' in request.headers.get('accept', '')
        if is_ajax:
            return JsonResponse({'success': True})

        messages.success(request, f"تم تحديث السؤال '{question.text_ar}' بنجاح.")
        return redirect('visit_template_edit', pk=template_pk)


@require_permission('settings:visitsTemplates/manage')
def template_question_delete(request, question_pk):
    """Delete a template question."""
    if not can_manage_templates(request.user):
        return JsonResponse({'success': False, 'message': 'غير مصرح.'}, status=403)

    question = get_object_or_404(VisitTemplateQuestion, pk=question_pk)
    template_pk = question.template_id
    question.delete()

    is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'application/json' in request.headers.get('accept', '')
    if is_ajax:
        return JsonResponse({'success': True})

    messages.success(request, "تم حذف السؤال بنجاح.")
    return redirect('visit_template_edit', pk=template_pk)


@require_permission('settings:visitsTemplates/manage')
def template_questions_reorder(request, template_pk):
    """AJAX endpoint for drag-and-drop or order updates of questions."""
    if not can_manage_templates(request.user):
        return JsonResponse({'success': False, 'message': 'غير مصرح.'}, status=403)

    template = get_object_or_404(VisitTemplate, pk=template_pk)
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            order_list = data.get('order', [])
            for idx, q_id in enumerate(order_list):
                VisitTemplateQuestion.objects.filter(id=q_id, template=template).update(order=idx + 1)
            return JsonResponse({'success': True})
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)}, status=400)
    return JsonResponse({'success': False, 'message': 'Invalid request method'}, status=405)


@login_required
@require_permission('activities:visits/list')
def agenda_view(request):
    """
    Agenda Tab (جدول الاعمال)
    Replicates https://weapharma.bricks-rep.com/agenda:
    - Displays planned and executed visits for the selected date and representative.
    - Scoped by role:
        * Reps: view their own agenda only. Cross-rep access returns 403.
        * Regional Managers: view their own agenda or filter by reps in their managed region/subregions.
          Cross-region access returns 403.
        * SuperAdministrators: global oversight across all representatives and regions.
    - Provides Date navigation (Previous, Next, Today, and specific date picker).
    - Features tab switcher between 'الزيارات' (Visits) and 'Todos' (Tasks).
    - Preserves approval status badges (معتمد, قيد الاعتماد, مرفوض) and execution links.
    - Includes '+ تسجيل زيارة خارج الخطة' action modal.
    - Displays empty state 'لا خطط أخرى لهذا اليوم' when no visits are scheduled.
    """
    from accounts.scope_service import ScopeResolutionService
    is_super = bool(request.user.is_superuser or getattr(request.user, 'is_super_admin', False))
    is_mgr = ScopeResolutionService.get_user_scope(request.user, 'activities', 'manage') in ['area', 'all']
    can_view_others = is_super or is_mgr

    available_reps = get_visible_assignees_queryset(request.user, module='activities')

    target_rep_id = request.GET.get('assignee')
    if target_rep_id:
        try:
            target_rep_id = int(target_rep_id)
        except (ValueError, TypeError):
            return render_forbidden_response(request, "معرّف المندوب غير صالح.")

        if not can_view_others and target_rep_id != request.user.id:
            return render_forbidden_response(request, "غير مصرح لك باستعراض جدول أعمال مستخدم آخر.")

        if can_view_others:
            if not available_reps.filter(pk=target_rep_id).exists():
                return render_forbidden_response(request, "لا يمكنك استعراض جدول أعمال مندوب خارج نطاق اختصاصك أو منطقتك الجغرافية.")
            selected_rep = get_object_or_404(User, pk=target_rep_id)
        else:
            selected_rep = request.user
    else:
        selected_rep = request.user

    # Date handling
    date_str = request.GET.get('date', '').strip()
    today = timezone.now().date()
    selected_date = today
    if date_str:
        for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%Y/%m/%d'):
            try:
                selected_date = datetime.datetime.strptime(date_str, fmt).date()
                break
            except ValueError:
                continue

    prev_date = selected_date - datetime.timedelta(days=1)
    next_date = selected_date + datetime.timedelta(days=1)

    arabic_days = ['الاثنين', 'الثلاثاء', 'الأربعاء', 'الخميس', 'الجمعة', 'السبت', 'الأحد']
    weekday_ar = arabic_days[selected_date.weekday()]

    from master_data.models import LocationSettings
    from activities.services import serialize_contact_addresses
    loc_settings = LocationSettings.get_settings()
    user_can_manage = can_manage_approvals(request.user)
    can_bypass_start_gps = loc_settings.can_user_bypass_without_approval(request.user, stage='start')

    def _is_agenda_entry_finished(visit_obj=None, source_item=None):
        if visit_obj is not None:
            return bool(visit_obj.status == 'finished' or visit_obj.ended_at is not None)
        return bool(source_item is not None and source_item.is_executed)

    agenda_visit_addresses = {}
    start_questions_cache = {}
    rep_open_visit = get_open_visit_for_owner(selected_rep.pk)

    def _get_start_questions_for_template(tpl):
        if not tpl:
            return []
        if tpl.pk not in start_questions_cache:
            start_questions_cache[tpl.pk] = list(tpl.get_active_questions().filter(stage='start_only'))
        return start_questions_cache[tpl.pk]

    def _build_visit_card(v, entry_type, source_item=None, order_num=None, plan_label=''):
        contact_obj = source_item.contact if source_item else v.contact
        can_approve = bool(
            user_can_manage and
            v.owner_id != request.user.id and
            can_user_access_object(request.user, v, 'approve')
        )
        if v.status == 'planned':
            if rep_open_visit is not None and rep_open_visit.pk != v.pk and v.owner_id == selected_rep.pk:
                can_start = False
            else:
                can_start, _ = can_start_visit(v, request.user)
        else:
            can_start = False
        start_questions = _get_start_questions_for_template(v.template) if (v.status == 'planned' and can_start) else []
        if v.status == 'planned' and can_start:
            agenda_visit_addresses[str(v.pk)] = serialize_contact_addresses(contact_obj)
        is_finished = _is_agenda_entry_finished(visit_obj=v, source_item=source_item)
        effective_dist = (
            float(v.allowed_distance)
            if v.allowed_distance is not None
            else loc_settings.get_effective_tolerance(v.template)
        )
        return {
            'type': entry_type,
            'source_item': source_item,
            'visit': v,
            'contact': contact_obj,
            'template': (source_item.template if source_item else None) or v.template,
            'order': order_num,
            'plan_label': plan_label,
            'status': v.status,
            'status_display': v.status_display_ar,
            'status_badge_class': v.status_badge_class,
            'approval_status': v.approval_status,
            'approval_display': v.approval_display_ar,
            'approval_badge_class': v.approval_badge_class,
            'is_executed': is_finished,
            'is_finished': is_finished,
            'can_approve': can_approve,
            'can_start': can_start,
            'start_questions': start_questions,
            'effective_allowed_distance': effective_dist,
            'detail_url': reverse('visit_detail', args=[v.pk]),
            'action_url': reverse('visit_detail', args=[v.pk]),
            'action_label': 'متابعة الزيارة' if v.status == 'started' else ('بدء الزيارة' if v.status == 'planned' and v.approval_status == 'approved' else 'معاينة التفاصيل'),
        }

    # Scoped VisitPlan query for grouping visits by plan under agenda
    scoped_plans_qs = get_scoped_queryset(VisitPlan.objects.all(), request.user, 'visitplan', 'view').filter(
        date=selected_date
    ).select_related('assignee', 'created_by', 'approved_by').prefetch_related(
        'planned_items__contact', 'planned_items__template', 'planned_items__visit',
        'planned_items__visit__approved_by', 'planned_items__visit__template',
        'planned_items__visit__contact_address', 'planned_items__visit__contact_address__area',
        'planned_items__visit__contact_address__brick',
        'planned_items__contact__area', 'planned_items__contact__brick',
        'planned_items__contact__addresses__area', 'planned_items__contact__addresses__brick',
    )
    if selected_rep:
        scoped_plans_qs = scoped_plans_qs.filter(assignee=selected_rep)

    today_plan_groups = []
    today_unplanned_cards = []
    actual_visit_cards = []
    seen_visit_ids = set()
    covered_item_ids = set()
    planned_count = 0
    unplanned_count = 0

    for pl in scoped_plans_qs:
        pl_items = sorted(pl.planned_items.all(), key=lambda x: (x.order, x.id))
        can_approve_pl = bool(
            user_can_manage and
            pl.assignee_id != request.user.id and
            can_user_access_object(request.user, pl, 'approve')
        )
        unfinished_group_visits = []
        for itm in pl_items:
            covered_item_ids.add(itm.id)
            v = itm.visit
            if v and v.status != 'cancelled' and (v.approval_status == 'approved' or v.is_planned or (user_can_manage and v.approval_status == 'pending')):
                if v.id in seen_visit_ids:
                    continue
                seen_visit_ids.add(v.id)
                v_data = _build_visit_card(v, 'planned', source_item=itm, order_num=itm.order, plan_label=pl.plan_id)
                planned_count += 1
                if v_data['is_finished']:
                    actual_visit_cards.append(v_data)
                else:
                    unfinished_group_visits.append(v_data)
            elif not v:
                is_finished = _is_agenda_entry_finished(visit_obj=None, source_item=itm)
                v_data = {
                    'type': 'planned',
                    'source_item': itm,
                    'visit': None,
                    'contact': itm.contact,
                    'template': itm.template,
                    'order': itm.order,
                    'plan_label': pl.plan_id,
                    'status': 'finished' if is_finished else 'planned',
                    'status_display': 'منتهية' if is_finished else 'مخططة (بانتظار التنفيذ)',
                    'status_badge_class': 'bg-emerald-50 text-emerald-700 border-emerald-200' if is_finished else 'bg-slate-100 text-slate-700 border-slate-200',
                    'approval_status': pl.approval_status,
                    'approval_display': pl.get_approval_status_display() if hasattr(pl, 'get_approval_status_display') else pl.approval_status,
                    'approval_badge_class': 'bg-emerald-50 text-emerald-700 border-emerald-200' if pl.approval_status == 'approved' else 'bg-amber-50 text-amber-700 border-amber-200',
                    'is_executed': is_finished,
                    'is_finished': is_finished,
                    'can_approve': False,
                    'can_start': False,
                    'start_questions': [],
                    'effective_allowed_distance': loc_settings.get_effective_tolerance(itm.template),
                    'detail_url': reverse('visit_create') + f'?contact_id={itm.contact_id}&planned_item_id={itm.id}',
                    'action_url': reverse('visit_create') + f'?contact_id={itm.contact_id}&planned_item_id={itm.id}',
                    'action_label': 'بدء الزيارة',
                }
                planned_count += 1
                if is_finished:
                    actual_visit_cards.append(v_data)
                else:
                    unfinished_group_visits.append(v_data)

        if unfinished_group_visits:
            today_plan_groups.append({
                'plan': pl,
                'plan_id': pl.plan_id,
                'comment': pl.comment,
                'approval_status': pl.approval_status,
                'assignee': pl.assignee,
                'can_approve': can_approve_pl,
                'visits': unfinished_group_visits,
                'items_count': len(unfinished_group_visits),
            })

    # Legacy unlinked PlannedVisitDay items (selected_rep is already scope-authorized; per-visit scope enforced)
    legacy_plan_days = PlannedVisitDay.objects.filter(
        assignee=selected_rep, date=selected_date
    ).prefetch_related(
        'items__contact', 'items__contact__area', 'items__contact__brick',
        'items__contact__addresses__area', 'items__contact__addresses__brick',
        'items__template', 'items__visit', 'items__visit__approved_by', 'items__visit__template',
        'items__visit__contact_address', 'items__visit__contact_address__area', 'items__visit__contact_address__brick',
    )
    unfinished_unlinked_visits = []
    for pvd in legacy_plan_days:
        raw_items = sorted(pvd.items.all(), key=lambda x: (x.order, x.id))
        for itm in raw_items:
            if itm.id in covered_item_ids:
                continue
            covered_item_ids.add(itm.id)
            v = itm.visit
            if v and v.status != 'cancelled' and (v.approval_status == 'approved' or v.is_planned):
                if v.id in seen_visit_ids:
                    continue
                if not can_user_access_object(request.user, v, 'view'):
                    continue
                seen_visit_ids.add(v.id)
                v_data = _build_visit_card(v, 'planned', source_item=itm, order_num=itm.order, plan_label='خطة عامة')
                planned_count += 1
                if v_data['is_finished']:
                    actual_visit_cards.append(v_data)
                else:
                    unfinished_unlinked_visits.append(v_data)
            elif not v:
                is_finished = _is_agenda_entry_finished(visit_obj=None, source_item=itm)
                v_data = {
                    'type': 'planned',
                    'source_item': itm,
                    'visit': None,
                    'contact': itm.contact,
                    'template': itm.template,
                    'order': itm.order,
                    'plan_label': 'خطة عامة',
                    'status': 'finished' if is_finished else 'planned',
                    'status_display': 'منتهية' if is_finished else 'مخططة (بانتظار التنفيذ)',
                    'status_badge_class': 'bg-emerald-50 text-emerald-700 border-emerald-200' if is_finished else 'bg-slate-100 text-slate-700 border-slate-200',
                    'approval_status': 'approved',
                    'approval_display': 'معتمدة',
                    'approval_badge_class': 'bg-emerald-50 text-emerald-700 border-emerald-200',
                    'is_executed': is_finished,
                    'is_finished': is_finished,
                    'can_approve': False,
                    'can_start': False,
                    'start_questions': [],
                    'effective_allowed_distance': loc_settings.get_effective_tolerance(itm.template),
                    'detail_url': reverse('visit_create') + f'?contact_id={itm.contact_id}&planned_item_id={itm.id}',
                    'action_url': reverse('visit_create') + f'?contact_id={itm.contact_id}&planned_item_id={itm.id}',
                    'action_label': 'بدء الزيارة',
                }
                planned_count += 1
                if is_finished:
                    actual_visit_cards.append(v_data)
                else:
                    unfinished_unlinked_visits.append(v_data)

    if unfinished_unlinked_visits:
        today_plan_groups.append({
            'plan': None,
            'plan_id': 'خطة عامة',
            'comment': '',
            'approval_status': 'approved',
            'assignee': selected_rep,
            'can_approve': False,
            'visits': unfinished_unlinked_visits,
            'items_count': len(unfinished_unlinked_visits),
        })

    # Standalone planned visits (is_planned=True) not already linked to a plan item
    allowed_approvals = ['approved', 'pending'] if user_can_manage else ['approved']
    standalone_planned_qs = get_scoped_queryset(
        Visit.objects.filter(
            owner=selected_rep,
            date=selected_date,
            is_planned=True,
            approval_status__in=allowed_approvals,
        ).exclude(
            status='cancelled'
        ).exclude(
            id__in=seen_visit_ids
        ).select_related(
            'contact', 'contact__area', 'contact__brick',
            'contact_address', 'contact_address__area', 'contact_address__brick',
            'template', 'owner', 'approved_by',
        ).prefetch_related(
            'contact__addresses__area', 'contact__addresses__brick',
        ).order_by('serial_num'),
        request.user,
        'visit',
    )
    unfinished_standalone_planned = []
    for v in standalone_planned_qs:
        if v.id in seen_visit_ids:
            continue
        seen_visit_ids.add(v.id)
        sp_data = _build_visit_card(v, 'planned', source_item=None, order_num=None, plan_label='زيارات مخططة')
        planned_count += 1
        if sp_data['is_finished']:
            actual_visit_cards.append(sp_data)
        else:
            unfinished_standalone_planned.append(sp_data)

    if unfinished_standalone_planned:
        today_plan_groups.append({
            'plan': None,
            'plan_id': 'زيارات مخططة',
            'comment': '',
            'approval_status': 'approved',
            'assignee': selected_rep,
            'can_approve': False,
            'visits': unfinished_standalone_planned,
            'items_count': len(unfinished_standalone_planned),
        })

    # Query explicitly unplanned visits (is_planned=False) not already shown
    unplanned_visits_qs = get_scoped_queryset(
        Visit.objects.filter(
            owner=selected_rep,
            date=selected_date,
            is_planned=False,
            approval_status__in=allowed_approvals,
        ).exclude(
            status='cancelled'
        ).exclude(
            id__in=seen_visit_ids
        ).select_related(
            'contact', 'contact__area', 'contact__brick',
            'contact_address', 'contact_address__area', 'contact_address__brick',
            'template', 'owner', 'approved_by',
        ).prefetch_related(
            'contact__addresses__area', 'contact__addresses__brick',
        ).order_by('serial_num'),
        request.user,
        'visit',
    )

    for v in unplanned_visits_qs:
        if v.id in seen_visit_ids:
            continue
        seen_visit_ids.add(v.id)
        u_data = _build_visit_card(v, 'unplanned', source_item=None, order_num=None, plan_label='')
        unplanned_count += 1
        if u_data['is_finished']:
            actual_visit_cards.append(u_data)
        else:
            today_unplanned_cards.append(u_data)

    today_visit_cards = [
        card
        for grp in today_plan_groups
        for card in grp['visits']
    ] + list(today_unplanned_cards)

    today_visits_count = len(today_visit_cards)
    actual_visits_count = len(actual_visit_cards)
    total_visits_count = today_visits_count + actual_visits_count
    planned_visit_cards = [c for c in (today_visit_cards + actual_visit_cards) if c['type'] == 'planned']
    unplanned_visit_cards = [c for c in (today_visit_cards + actual_visit_cards) if c['type'] == 'unplanned']
    agenda_visits = today_visit_cards + actual_visit_cards

    # Todos
    todos = AgendaTodo.objects.filter(user=selected_rep, date=selected_date).order_by('is_completed', '-created_at')

    current_tab = request.GET.get('tab', 'visits')

    context = {
        'selected_rep': selected_rep,
        'available_reps': available_reps,
        'can_view_others': can_view_others,
        'selected_date': selected_date,
        'formatted_date': selected_date.strftime('%Y-%m-%d'),
        'display_date': selected_date.strftime('%d/%m/%Y'),
        'prev_date': prev_date.strftime('%Y-%m-%d'),
        'next_date': next_date.strftime('%Y-%m-%d'),
        'today_date': today.strftime('%Y-%m-%d'),
        'is_today': selected_date == today,
        'weekday_ar': weekday_ar,
        # Two mutually exclusive Agenda sections (Req B)
        'today_plan_groups': today_plan_groups,
        'today_unplanned_cards': today_unplanned_cards,
        'today_visit_cards': today_visit_cards,
        'today_visits_count': today_visits_count,
        'actual_visit_cards': actual_visit_cards,
        'actual_visits_count': actual_visits_count,
        # Preserved compatibility keys
        'plan_groups': today_plan_groups,
        'planned_visit_cards': planned_visit_cards,
        'unplanned_visit_cards': unplanned_visit_cards,
        'agenda_visits': agenda_visits,
        'planned_visits_count': planned_count,
        'unplanned_visits_count': unplanned_count,
        'total_visits_count': total_visits_count,
        'visits_count': total_visits_count,
        'todos': todos,
        'todos_count': todos.count(),
        'current_tab': current_tab,
        'can_bypass_start_gps': can_bypass_start_gps,
        'verify_visits_enabled': loc_settings.verify_visits,
        'agenda_visit_addresses_json': json.dumps(agenda_visit_addresses),
    }
    return render(request, 'activities/agenda.html', context)


@login_required
def agenda_todo_add(request):
    """Add a new task/todo for the current user or managed representative."""
    if request.method != 'POST':
        return redirect('agenda')

    title = request.POST.get('title', '').strip()
    date_str = request.POST.get('date', '').strip()
    target_user_id = request.POST.get('assignee')

    if not title:
        messages.error(request, "يرجى إدخال عنوان المهمة.")
        return redirect(f"{reverse('agenda')}?tab=todos")

    today = timezone.now().date()
    target_date = today
    if date_str:
        try:
            target_date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            pass

    target_user = request.user
    if target_user_id:
        from accounts.scope_service import ScopeResolutionService
        is_super = bool(request.user.is_superuser or getattr(request.user, 'is_super_admin', False))
        is_mgr = ScopeResolutionService.get_user_scope(request.user, 'activities', 'manage') in ['area', 'all']
        if is_super or is_mgr:
            managed_reps = get_user_managed_representatives(request.user)
            rep = managed_reps.filter(pk=target_user_id).first()
            if rep:
                target_user = rep

    AgendaTodo.objects.create(
        user=target_user,
        date=target_date,
        title=title,
        is_completed=False
    )
    messages.success(request, f"تمت إضافة المهمة '{title}' بنجاح.")
    return redirect(f"{reverse('agenda')}?date={target_date.strftime('%Y-%m-%d')}&assignee={target_user.id}&tab=todos")


@login_required
def agenda_todo_toggle(request, pk):
    """Toggle completion status of a todo."""
    todo = get_object_or_404(AgendaTodo, pk=pk)
    from accounts.scope_service import ScopeResolutionService
    is_super = bool(request.user.is_superuser or getattr(request.user, 'is_super_admin', False))
    is_mgr = ScopeResolutionService.get_user_scope(request.user, 'activities', 'manage') in ['area', 'all']
    if todo.user != request.user and not is_super:
        if is_mgr:
            managed_reps = get_user_managed_representatives(request.user)
            if not managed_reps.filter(pk=todo.user_id).exists():
                return render_forbidden_response(request, "غير مصرح بتعديل هذه المهمة.")
        else:
            return render_forbidden_response(request, "غير مصرح بتعديل هذه المهمة.")

    todo.is_completed = not todo.is_completed
    todo.save(update_fields=['is_completed', 'updated_at'])

    is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'application/json' in request.headers.get('accept', '')
    if is_ajax:
        return JsonResponse({'success': True, 'is_completed': todo.is_completed})

    return redirect(f"{reverse('agenda')}?date={todo.date.strftime('%Y-%m-%d')}&assignee={todo.user_id}&tab=todos")


@login_required
def agenda_todo_delete(request, pk):
    """Delete a todo."""
    todo = get_object_or_404(AgendaTodo, pk=pk)
    from accounts.scope_service import ScopeResolutionService
    is_super = bool(request.user.is_superuser or getattr(request.user, 'is_super_admin', False))
    is_mgr = ScopeResolutionService.get_user_scope(request.user, 'activities', 'manage') in ['area', 'all']
    if todo.user != request.user and not is_super:
        if is_mgr:
            managed_reps = get_user_managed_representatives(request.user)
            if not managed_reps.filter(pk=todo.user_id).exists():
                return render_forbidden_response(request, "غير مصرح بحذف هذه المهمة.")
        else:
            return render_forbidden_response(request, "غير مصرح بحذف هذه المهمة.")

    date_str = todo.date.strftime('%Y-%m-%d')
    user_id = todo.user_id
    todo.delete()
    messages.success(request, "تم حذف المهمة بنجاح.")
    return redirect(f"{reverse('agenda')}?date={date_str}&assignee={user_id}&tab=todos")



