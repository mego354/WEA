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
from django.db.models import Q, Sum, Count
from django.utils import timezone
from django.http import HttpResponse, JsonResponse, FileResponse, Http404, HttpResponseForbidden
from django.contrib.auth import get_user_model
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

from django.urls import reverse

from .models import (
    Agreement, AgreementType, VisitTemplate, VisitTemplateQuestion,
    PlannedVisitDay, PlannedVisitItem, Visit,
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
    can_submit_answers, save_visit_answers, can_end_visit, end_visit,
    build_visit_timeline
)
from accounts.permissions import (
    require_permission, has_perm_or_admin, render_forbidden_response,
    get_scoped_queryset, can_user_access_object, get_user_managed_representatives,
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
    if module_type == 'agreements':
        return has_perm_or_admin(user, 'activities:agreements/approve')
    return has_perm_or_admin(user, 'activities:visits/approve')


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
    qs = Agreement.objects.select_related('customer', 'type', 'created_by').all().order_by('-serial_num')
    qs = get_scoped_queryset(qs, request.user, 'agreement')

    # Search
    q = request.GET.get('q', '').strip()
    active_filters = []

    if q:
        qs = qs.filter(
            Q(title__icontains=q) |
            Q(serial_num__icontains=q) |
            Q(customer__name__icontains=q) |
            Q(customer__code__icontains=q)
        )
        active_filters.append({'label': f'بحث: {q}', 'param': 'q'})

    # Type Filter
    type_id = request.GET.get('type')
    if type_id:
        qs = qs.filter(type_id=type_id)
        t_obj = AgreementType.objects.filter(id=type_id).first()
        active_filters.append({'label': f'النوع: {t_obj.name if t_obj else type_id}', 'param': 'type'})

    # Status Filter
    status = request.GET.get('status')
    if status:
        qs = qs.filter(status=status)
        status_labels = dict(Agreement.STATUS_CHOICES)
        active_filters.append({'label': f'الحالة: {status_labels.get(status, status)}', 'param': 'status'})

    # Assignee Filter (created_by)
    creator_id = request.GET.get('creator')
    if creator_id:
        qs = qs.filter(created_by_id=creator_id)
        u_obj = User.objects.filter(id=creator_id).first()
        active_filters.append({'label': f'المسؤول: {u_obj.get_full_name() or u_obj.username if u_obj else creator_id}', 'param': 'creator'})

    # Date Range Filters
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    if date_from:
        qs = qs.filter(date__gte=date_from)
        active_filters.append({'label': f'من تاريخ: {date_from}', 'param': 'date_from'})
    if date_to:
        qs = qs.filter(date__lte=date_to)
        active_filters.append({'label': f'إلى تاريخ: {date_to}', 'param': 'date_to'})

    # Summary Metrics (matches reference aggregate API)
    total_amount = qs.aggregate(s=Sum('amount'))['s'] or 0.00

    # Handle inline Create via POST
    if request.method == 'POST' and 'create_agreement' in request.POST:
        form = AgreementForm(request.POST, user=request.user)
        if form.is_valid():
            agreement = form.save(commit=False)
            agreement.created_by = request.user
            agreement.updated_by = request.user

            from master_data.models import LocationSettings
            loc_settings = LocationSettings.get_settings()
            if not loc_settings.require_manager_approval_for_agreements or has_perm_or_admin(request.user, 'activities:agreements/approve'):
                agreement.status = 'approved'
            else:
                agreement.status = 'new'

            agreement.save()
            messages.success(request, f"تم إنشاء الاتفاقية #{agreement.serial_num} بنجاح.")
            return redirect('agreements_list')
        else:
            messages.error(request, "يرجى تصحيح الأخطاء في نموذج إنشاء الاتفاقية.")
    else:
        form = AgreementForm(initial={'date': timezone.now().date()}, user=request.user)

    # Standardized bounded pagination
    paginator, page_obj = paginate_queryset(request, qs, default_per_page=25, max_per_page=100)

    # Filter dropdown options
    agreement_types = AgreementType.objects.filter(is_active=True)
    users = User.objects.filter(is_active=True).order_by('first_name', 'username')
    contacts = Contact.objects.all().order_by('name')[:50]

    base_scoped_agreements = get_scoped_queryset(Agreement.objects.all(), request.user, 'agreement')
    agreements_stats = {
        'total_count': base_scoped_agreements.count(),
        'total_amount': base_scoped_agreements.aggregate(s=Sum('amount'))['s'] or Decimal('0.00'),
        'approved_count': base_scoped_agreements.filter(status='approved').count(),
        'pending_count': base_scoped_agreements.filter(status='new').count(),
    }

    context = {
        'page_obj': page_obj,
        'paginator': paginator,
        'agreements': page_obj.object_list,
        'total_count': paginator.count,
        'total_amount': total_amount,
        'form': form,
        'agreement_types': agreement_types,
        'users': users,
        'contacts': contacts,
        'selected_q': q,
        'selected_type': type_id,
        'selected_status': status,
        'selected_creator': creator_id,
        'selected_date_from': date_from,
        'selected_date_to': date_to,
        'active_filters': active_filters,
        'can_manage_approvals': can_manage_approvals(request.user),
        'stats': agreements_stats,
    }
    return render(request, 'activities/agreements_list.html', context)


@require_permission('activities:agreements/approve')
def agreements_bulk_status(request):
    """
    Update status of multiple selected agreements in bulk.
    Matches reference action bar 'تغيير الحالة'.
    Requires manager/superuser authorization.
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

    updated_count = Agreement.objects.filter(pk__in=selected_ids).update(
        status=new_status,
        updated_by=request.user,
        updated_at=timezone.now()
    )

    status_names = {
        'new': 'جديد',
        'approved': 'معتمد',
        'disapproved': 'مرفوض',
        'done': 'تم الإنجاز',
    }
    messages.success(request, f"تم تغيير حالة {updated_count} اتفاقية إلى '{status_names.get(new_status, new_status)}' بنجاح.")
    return redirect('agreements_list')


@require_permission('activities:agreements/view')
def agreement_detail(request, pk):
    """View details of a specific agreement."""
    agreement = get_object_or_404(Agreement.objects.select_related('customer', 'type', 'created_by', 'updated_by'), pk=pk)
    if not can_user_access_object(request.user, agreement, 'view'):
        return render_forbidden_response(request, "لا يمكنك عرض هذه الاتفاقية خارج نطاق اختصاصك أو منطقتك الجغرافية.")

    return render(request, 'activities/agreement_detail.html', {
        'agreement': agreement,
        'can_manage_approvals': can_manage_approvals(request.user, 'agreements'),
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
                agreement.status = 'approved'
            else:
                agreement.status = 'new'

            agreement.save()
            messages.success(request, f"تم إنشاء الاتفاقية #{agreement.serial_num} بنجاح.")
            return redirect('agreement_detail', pk=agreement.pk)
    else:
        form = AgreementForm(initial={'date': timezone.now().date()}, user=request.user)
    return render(request, 'activities/agreement_form.html', {'form': form, 'title': 'إضافة اتفاقية جديدة'})


@require_permission('activities:agreements/edit')
def agreement_edit(request, pk):
    """Edit agreement (allowed if status is new)."""
    agreement = get_object_or_404(Agreement, pk=pk)
    if not can_user_access_object(request.user, agreement, 'edit'):
        return render_forbidden_response(request, "لا يمكنك تعديل هذه الاتفاقية خارج نطاق اختصاصك أو منطقتك الجغرافية.")

    if agreement.status not in ['new']:
        messages.warning(request, "لا يمكن تعديل الاتفاقية بعد اعتمادها أو إنجازها.")
        return redirect('agreement_detail', pk=agreement.pk)

    if request.method == 'POST':
        form = AgreementForm(request.POST, instance=agreement)
        if form.is_valid():
            agreement = form.save(commit=False)
            agreement.updated_by = request.user
            agreement.save()
            messages.success(request, f"تم تحديث الاتفاقية #{agreement.serial_num} بنجاح.")
            return redirect('agreement_detail', pk=agreement.pk)
    else:
        form = AgreementForm(instance=agreement)
    return render(request, 'activities/agreement_form.html', {'form': form, 'agreement': agreement, 'title': f'تعديل الاتفاقية #{agreement.serial_num}'})


@require_permission('activities:agreements/approve')
def agreement_action(request, pk, action):
    """Status transitions: approve, disapprove, done, reopen."""
    if not can_manage_approvals(request.user, 'agreements'):
        messages.error(request, "عذراً، لا تملك صلاحية تغيير حالة الاعتماد (خاص بالمدراء ومسؤولي النظام).")
        next_url = request.GET.get('next', 'agreement_detail')
        if next_url == 'list':
            return redirect('agreements_list')
        return redirect('agreement_detail', pk=pk)

    agreement = get_object_or_404(Agreement, pk=pk)
    if not can_user_access_object(request.user, agreement, action):
        return render_forbidden_response(request, "لا يمكنك تغيير حالة هذه الاتفاقية خارج نطاق اختصاصك أو اعتماد اتفاقيتك الخاصة.")

    status_before = agreement.status

    if action == 'approve':
        agreement.status = 'approved'
        agreement.updated_by = request.user
        agreement.save()
        messages.success(request, f"تم اعتماد الاتفاقية #{agreement.serial_num} بنجاح.")
    elif action == 'disapprove':
        agreement.status = 'disapproved'
        agreement.updated_by = request.user
        agreement.save()
        messages.error(request, f"تم رفض الاتفاقية #{agreement.serial_num}.")
    elif action == 'done':
        agreement.status = 'done'
        agreement.updated_by = request.user
        agreement.save()
        messages.success(request, f"تم إنجاز الاتفاقية #{agreement.serial_num} بنجاح.")
    elif action == 'reopen':
        agreement.status = 'new'
        agreement.updated_by = request.user
        agreement.save()
        messages.info(request, f"تم إعادة فتح الاتفاقية #{agreement.serial_num} لحالة جديد.")
    else:
        messages.error(request, "إجراء غير معروف.")
        return redirect('agreement_detail', pk=agreement.pk)

    AuditLogService.log(
        action_type='AGREEMENT_APPROVED' if action == 'approve' else ('AGREEMENT_REJECTED' if action == 'disapprove' else 'AGREEMENT_STATUS_CHANGED'),
        module='activities',
        actor=request.user,
        record_id=agreement.id,
        record_name=f"اتفاقية #{agreement.serial_num}",
        description=f"تغيير حالة الاتفاقية من '{status_before}' إلى '{agreement.status}'",
        previous_values={'status': status_before},
        new_values={'status': agreement.status},
        status='SUCCESS',
        request=request,
    )

    next_url = request.GET.get('next', 'agreement_detail')
    if next_url == 'list':
        return redirect('agreements_list')
    return redirect('agreement_detail', pk=agreement.pk)


@require_permission('activities:agreements/delete')
def agreement_delete(request, pk):
    """Delete an agreement if in new state."""
    agreement = get_object_or_404(Agreement, pk=pk)
    if not can_user_access_object(request.user, agreement, 'delete'):
        return render_forbidden_response(request, "لا يمكنك حذف هذه الاتفاقية.")

    if agreement.status != 'new' and not request.user.is_superuser:
        messages.error(request, "لا يمكن حذف اتفاقية معتمدة.")
        return redirect('agreement_detail', pk=agreement.pk)

    serial = agreement.serial_num
    agreement.delete()
    messages.success(request, f"تم حذف الاتفاقية #{serial} بنجاح.")
    return redirect('agreements_list')


@require_permission('activities:agreements/export')
def agreements_export(request):
    """Export filtered agreements to Excel (.xlsx) with styled formatting."""
    qs = Agreement.objects.select_related('customer', 'type', 'created_by').all()
    qs = get_scoped_queryset(qs, request.user, 'agreement')

    # Apply same filters
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(serial_num__icontains=q) | Q(customer__name__icontains=q))
    if request.GET.get('type'):
        qs = qs.filter(type_id=request.GET.get('type'))
    if request.GET.get('status'):
        qs = qs.filter(status=request.GET.get('status'))
    if request.GET.get('date_from'):
        qs = qs.filter(date__gte=request.GET.get('date_from'))
    if request.GET.get('date_to'):
        qs = qs.filter(date__lte=request.GET.get('date_to'))

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "الاتفاقيات"
    ws.views.sheetView[0].rightToLeft = True

    # Styling
    header_fill = PatternFill(start_color="27BEBE", end_color="27BEBE", fill_type="solid")
    header_font = Font(name="Cairo", size=11, bold=True, color="FFFFFF")
    data_font = Font(name="Cairo", size=10)
    thin_border = Border(
        left=Side(style='thin', color='E2E8F0'),
        right=Side(style='thin', color='E2E8F0'),
        top=Side(style='thin', color='E2E8F0'),
        bottom=Side(style='thin', color='E2E8F0')
    )

    headers = ["#", "العميل", "كود العميل", "العنوان", "النوع", "المبلغ (ج.م)", "التاريخ", "المنشئ", "الحالة"]
    ws.append(headers)

    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")

    for a in qs:
        row = [
            f"#{a.serial_num}",
            a.customer.name if a.customer else "",
            a.customer.code if a.customer else "",
            a.title,
            a.type.name if a.type else "",
            float(a.amount),
            a.date.strftime("%Y-%m-%d") if a.date else "",
            a.created_by.get_full_name() or a.created_by.username if a.created_by else "",
            a.status_display_ar
        ]
        ws.append(row)

    # Style rows & adjust widths
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.font = data_font
            cell.border = thin_border
            cell.alignment = Alignment(vertical="center")

    for col in ws.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        col_letter = openpyxl.utils.get_column_letter(col[0].column)
        ws.column_dimensions[col_letter].width = max(max_len + 4, 12)

    response = HttpResponse(content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response['Content-Disposition'] = f'attachment; filename="agreements_{timezone.now().strftime("%Y%m%d_%H%M")}.xlsx"'
    wb.save(response)
    return response


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
    can_view_others = (
        is_super or
        has_perm_or_admin(request.user, 'activities:planned/manage') or
        ScopeResolutionService.get_user_scope(request.user, 'activities', 'view') in ['area', 'all']
    )
    if is_super:
        all_reps = User.objects.filter(is_active=True).order_by('first_name', 'username')
    elif can_view_others:
        all_reps = get_user_managed_representatives(request.user).order_by('first_name', 'username')
    else:
        all_reps = User.objects.filter(id=request.user.id)

    rep_id = request.GET.get('assignee')
    if rep_id and can_view_others:
        selected_rep = get_object_or_404(User, pk=rep_id)
        if not is_super and not all_reps.filter(pk=selected_rep.pk).exists():
            return render_forbidden_response(request, "غير مصرح لك بعرض خطة زيارات مندوب خارج نطاق منطقتك الجغرافية.")
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

    # Fetch all days in range for selected rep
    plan_days = PlannedVisitDay.objects.filter(
        assignee=selected_rep,
        date__range=[start_date, end_date]
    ).prefetch_related('items__contact', 'items__template', 'items__visit')
    
    plan_days_map = {p.date: p for p in plan_days}

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

    while current_date <= end_date:
        plan_day = plan_days_map.get(current_date)
        items = list(plan_day.items.all()) if plan_day else []
        d_key = current_date.strftime('%Y-%m-%d')
        scheduled_contacts_by_date[d_key] = [it.contact_id for it in items]
        days_list.append({
            'date': current_date,
            'date_str': d_key,
            'weekday_ar': arabic_weekdays[current_date.weekday()],
            'formatted_date': current_date.strftime('%d/%m/%Y'),
            'plan_day': plan_day,
            'items': items,
            'items_count': len(items),
            'is_planned': len(items) > 0,
        })
        current_date += datetime.timedelta(days=1)

    # Contacts for drawer & bulk planner (scoped strictly to user's permitted geographical scope)
    base_contacts_qs = get_visit_eligible_contacts_queryset(
        Contact.objects.select_related('area', 'brick', 'area__parent', 'brick__parent').prefetch_related('addresses__area', 'addresses__brick').exclude(status='inactive'),
        request.user
    )
    contacts_qs = base_contacts_qs

    main_area_filter = (request.GET.get('main_area') or '').strip()
    area_filter = (request.GET.get('brick') or request.GET.get('area') or '').strip()
    account_type_filter = (request.GET.get('account_type') or '').strip()
    category_filter = (request.GET.get('customer_category') or '').strip()
    specialty_filter = (request.GET.get('specialty') or '').strip()
    search_contact = (request.GET.get('contact_search') or '').strip()

    if main_area_filter and main_area_filter.isdigit():
        ma_id = int(main_area_filter)
        contacts_qs = contacts_qs.filter(
            Q(area_id=ma_id) |
            Q(area__parent_id=ma_id) |
            Q(brick_id=ma_id) |
            Q(brick__parent_id=ma_id) |
            Q(addresses__area_id=ma_id) |
            Q(addresses__brick__parent_id=ma_id)
        ).distinct()

    if area_filter and area_filter.isdigit():
        b_id = int(area_filter)
        contacts_qs = contacts_qs.filter(
            Q(brick_id=b_id) |
            Q(area_id=b_id) |
            Q(addresses__brick_id=b_id) |
            Q(addresses__area_id=b_id)
        ).distinct()

    if account_type_filter:
        contacts_qs = contacts_qs.filter(account_type__iexact=account_type_filter)
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

    # AJAX Incremental Client Loader (Requirement 2: Performance & See More)
    if (request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.GET.get('format') == 'json') and request.GET.get('action') == 'load_contacts':
        try:
            offset = max(0, int(request.GET.get('offset', 0)))
        except (ValueError, TypeError):
            offset = 0
        try:
            limit = max(1, min(50, int(request.GET.get('limit', 10))))
        except (ValueError, TypeError):
            limit = 10

        total_count = contacts_qs.count()
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

    # Geographical areas scoped to user
    if is_super:
        areas = Area.objects.select_related('parent').all().order_by('name')
        main_areas = Area.objects.filter(parent__isnull=True).order_by('name')
        bricks = Area.objects.filter(parent__isnull=False).select_related('parent').order_by('name')
    else:
        managed_areas = get_user_managed_areas(request.user)
        root_areas = get_user_main_areas(request.user)
        areas = managed_areas.select_related('parent').order_by('name')
        main_areas = root_areas.order_by('name')
        bricks = managed_areas.filter(parent__isnull=False).select_related('parent').order_by('name')

    # Templates eligible for current user's role
    visit_templates = [t for t in VisitTemplate.objects.filter(active=True).prefetch_related('restricted_roles').order_by('name') if t.is_user_eligible(request.user)]

    context = {
        'selected_rep': selected_rep,
        'all_reps': all_reps,
        'start_date': start_date.strftime('%Y-%m-%d'),
        'end_date': end_date.strftime('%Y-%m-%d'),
        'today': today,
        'today_str': today.strftime('%Y-%m-%d'),
        'days_list': days_list,
        'drawer_contacts': initial_contacts,
        'total_clients_count': total_clients_count,
        'has_more_clients': has_more_clients,
        'areas': areas,
        'main_areas': main_areas,
        'bricks': bricks,
        'account_types': ACCOUNT_TYPES,
        'customer_categories': CUSTOMER_CATEGORIES,
        'specialties': SPECIALTIES,
        'visit_templates': visit_templates,
        'selected_main_area': main_area_filter,
        'selected_area': area_filter,
        'selected_account_type': account_type_filter,
        'selected_customer_category': category_filter,
        'selected_specialty': specialty_filter,
        'selected_contact_search': search_contact,
        'scheduled_contacts_json': json.dumps(scheduled_contacts_by_date),
    }
    return render(request, 'activities/planned_visits_list.html', context)


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

    qs = VisitTemplate.objects.filter(active=True).prefetch_related('questions', 'restricted_roles')

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
            results.append({
                'id': tmpl.id,
                'name': tmpl.name,
                'display_name_ar': tmpl.display_name_ar,
                'display_name_en': tmpl.display_name_en,
                'allow_unplanned': tmpl.allow_unplanned,
                'enable_product_detailing': tmpl.enable_product_detailing,
                'supports_product_detailing': tmpl.is_product_detailing_supported(),
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
            if not can_manage_others or (not is_super and not get_user_managed_representatives(request.user).filter(pk=assignee.pk).exists()):
                msg = "غير مصرح لك بإضافة زيارات لخطة مندوب آخر خارج نطاق مسؤوليتك الجغرافية."
                if is_ajax:
                    return JsonResponse({'success': False, 'message': msg}, status=403)
                messages.error(request, msg)
                return redirect(request.META.get('HTTP_REFERER', '/planned-visits/'))

        contact = get_object_or_404(Contact, pk=contact_id)
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
                notes=notes
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

    assignee = get_object_or_404(User, pk=assignee_id)
    is_super = request.user.is_superuser or getattr(request.user, 'is_super_admin', False)
    from accounts.scope_service import ScopeResolutionService
    can_manage_others = (
        is_super or
        has_perm_or_admin(request.user, 'activities:planned/manage') or
        ScopeResolutionService.get_user_scope(request.user, 'activities', 'manage') in ['area', 'all']
    )
    if assignee != request.user:
        if not can_manage_others or (not is_super and not get_user_managed_representatives(request.user).filter(pk=assignee.pk).exists()):
            msg = "غير مصرح لك بإضافة زيارات مجمعة لخطة مندوب آخر خارج نطاق مسؤوليتك الجغرافية."
            if is_ajax:
                return JsonResponse({'success': False, 'message': msg}, status=403)
            messages.error(request, msg)
            return redirect(request.META.get('HTTP_REFERER', '/planned-visits/'))

    contacts = list(Contact.objects.filter(id__in=contact_ids).select_related('area', 'brick', 'area__parent'))
    if len(contacts) != len(contact_ids):
        msg = "بعض العملاء المحددين غير موجودين."
        if is_ajax:
            return JsonResponse({'success': False, 'message': msg}, status=400)
        messages.error(request, msg)
        return redirect(request.META.get('HTTP_REFERER', '/planned-visits/'))

    # Enforce geographical scope for every selected client
    for c in contacts:
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

    with transaction.atomic():
        plan_day, _ = PlannedVisitDay.objects.get_or_create(
            assignee=assignee,
            date=target_date,
            defaults={'created_by': request.user}
        )
        existing_contact_ids = set(
            PlannedVisitItem.objects.filter(plan_day=plan_day).values_list('contact_id', flat=True)
        )
        current_order = plan_day.items.count()
        created_items = []
        skipped_duplicates = []
        skipped_ineligible = []

        # Preserve order of contact_ids
        contacts_by_id = {c.id: c for c in contacts}
        for cid in contact_ids:
            c = contacts_by_id.get(cid)
            if not c:
                continue
            if cid in existing_contact_ids:
                skipped_duplicates.append(c.name)
                continue
            item_template = templates_cache.get(client_template_map.get(cid))
            current_order += 1
            item = PlannedVisitItem.objects.create(
                plan_day=plan_day,
                order=current_order,
                contact=c,
                template=item_template,
                notes=notes
            )
            created_items.append(item)
            existing_contact_ids.add(cid)

        if created_items:
            AuditLogService.log(
                action='create',
                action_type='BULK_PLANNED_VISITS_CREATED',
                module='activities',
                user=request.user,
                request=request,
                record_id=plan_day.id,
                object_repr=f"Bulk Planned Visits ({len(created_items)} items on {date_str} for {assignee.username})",
                new_values={
                    'date': date_str,
                    'assignee_id': assignee.id,
                    'template_ids': list(needed_template_ids),
                    'created_count': len(created_items),
                    'skipped_duplicates_count': len(skipped_duplicates),
                    'contact_ids': [it.contact_id for it in created_items],
                }
            )

    if not created_items and skipped_duplicates:
        msg = f"جميع العملاء المحددين ({len(skipped_duplicates)}) مضافون بالفعل لخطة يوم {date_str}."
        if is_ajax:
            return JsonResponse({
                'success': False,
                'created_count': 0,
                'skipped_duplicates_count': len(skipped_duplicates),
                'message': msg
            }, status=400)
        messages.warning(request, msg)
    elif not created_items and skipped_ineligible:
        msg = f"تعذر إضافة العملاء المحددين لعدم توافق نوع حساباتهم مع القالب المختار."
        if is_ajax:
            return JsonResponse({'success': False, 'created_count': 0, 'message': msg}, status=400)
        messages.error(request, msg)
    else:
        msg = f"تم إنشاء خطة يوم {date_str} بنجاح لـ ({len(created_items)}) عميل."
        if skipped_duplicates:
            msg += f" (تم تخطي {len(skipped_duplicates)} عميل مكرر في نفس اليوم)."
        if skipped_ineligible:
            msg += f" (تم تخطي {len(skipped_ineligible)} عميل غير متوافق مع القالب)."
        if is_ajax:
            return JsonResponse({
                'success': True,
                'created_count': len(created_items),
                'skipped_duplicates_count': len(skipped_duplicates),
                'message': msg
            })
        messages.success(request, msg)

    return redirect(f"{request.META.get('HTTP_REFERER', '/planned-visits/')}#day-{date_str}")


@require_permission('activities:planned/manage')
def planned_visit_item_delete(request, pk):
    """Remove a planned visit item."""
    item = get_object_or_404(PlannedVisitItem, pk=pk)
    is_owner = (item.plan_day.assignee == request.user)
    from accounts.scope_service import ScopeResolutionService
    can_override = (
        request.user.is_superuser or
        getattr(request.user, 'is_super_admin', False) or
        has_perm_or_admin(request.user, 'activities:planned/manage') or
        ScopeResolutionService.get_user_scope(request.user, 'activities', 'manage') in ['area', 'all']
    )
    if not (is_owner or can_override):
        return render_forbidden_response(request, "غير مصرح لك بحذف زيارة مخططة لمندوب آخر.")

    contact_name = item.contact.name
    date_str = item.plan_day.date.strftime('%Y-%m-%d')
    item.delete()
    messages.success(request, f"تم حذف الزيارة المخططة للعميل {contact_name}.")
    return redirect(f"{request.META.get('HTTP_REFERER', '/planned-visits/')}#day-{date_str}")


@require_permission('activities:visits/create')
def planned_visit_item_execute(request, pk):
    """
    Route planned visit execution into the canonical visit registration workflow
    with prefilled customer, template, and plan day context.
    """
    item = get_object_or_404(PlannedVisitItem.objects.select_related('plan_day__assignee', 'contact', 'template'), pk=pk)
    
    # Permission check: only assigned rep or manager/superuser can execute
    is_owner = (item.plan_day.assignee == request.user)
    can_override = (
        request.user.is_superuser or
        getattr(request.user, 'is_super_admin', False) or
        has_perm_or_admin(request.user, 'activities:planned/manage')
    )
    if not (is_owner or can_override):
        return render_forbidden_response(request, "غير مصرح لك بتنفيذ خطة زيارة تابعة لمندوب آخر.")

    if item.is_executed and item.visit:
        messages.info(request, f"تم تنفيذ هذه الزيارة المخططة مسبقاً (زيارة #{item.visit.serial_num}).")
        return redirect('visit_detail', pk=item.visit.pk)

    template_param = f"&template_id={item.template.id}" if item.template else ""
    return redirect(f"/visits/create/?contact_id={item.contact.id}&planned_item_id={item.pk}{template_param}")



@require_permission('activities:planned/export')
def planned_visits_export(request):
    """Export planned visits list to Excel."""
    items = PlannedVisitItem.objects.select_related('plan_day__assignee', 'contact__area', 'template', 'visit').all().order_by('plan_day__date', 'order')

    from accounts.scope_service import ScopeResolutionService
    can_view_all = (
        request.user.is_superuser or
        getattr(request.user, 'is_super_admin', False) or
        has_perm_or_admin(request.user, 'activities:planned/manage') or
        ScopeResolutionService.get_user_scope(request.user, 'activities', 'view') in ['area', 'all']
    )
    if not can_view_all:
        items = items.filter(plan_day__assignee=request.user)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "خطة الزيارات"
    ws.views.sheetView[0].rightToLeft = True

    header_fill = PatternFill(start_color="27BEBE", end_color="27BEBE", fill_type="solid")
    header_font = Font(name="Cairo", size=11, bold=True, color="FFFFFF")

    headers = ["التاريخ", "المسؤول", "الترتيب", "العميل", "الكود", "المنطقة", "نوع الحساب", "القالب", "تم التنفيذ", "رقم الزيارة"]
    ws.append(headers)

    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")

    for it in items:
        ws.append([
            it.plan_day.date.strftime("%Y-%m-%d"),
            it.plan_day.assignee.get_full_name() or it.plan_day.assignee.username,
            it.order,
            it.contact.name,
            it.contact.code,
            it.contact.area.name if it.contact.area else "",
            it.contact.account_type or "",
            it.template.display_name_ar if it.template else "",
            "نعم" if it.is_executed else "لا",
            f"#{it.visit.serial_num}" if it.visit else ""
        ])

    response = HttpResponse(content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response['Content-Disposition'] = f'attachment; filename="planned_visits_{timezone.now().strftime("%Y%m%d")}.xlsx"'
    wb.save(response)
    return response


# -----------------------------------------------------------------------------
# VISITS MODULE (الزيارات)
# -----------------------------------------------------------------------------

@require_permission('activities:visits/list')
def visits_list(request):
    """
    Visits list with table & cards views, complete filters, status indicators, and export.
    Matches https://weapharma.bricks-rep.com/visits
    """
    qs = Visit.objects.select_related('contact', 'template', 'owner', 'created_by').prefetch_related('samples__product').all().order_by('-serial_num')
    qs = get_scoped_queryset(qs, request.user, 'visit')

    # Search
    q = request.GET.get('q', '').strip()
    active_filters = []

    if q:
        qs = qs.filter(
            Q(contact__name__icontains=q) |
            Q(contact__code__icontains=q) |
            Q(serial_num__icontains=q) |
            Q(owner__first_name__icontains=q) |
            Q(owner__username__icontains=q)
        )
        active_filters.append({'label': f'بحث: {q}', 'param': 'q'})

    # Status
    status = request.GET.get('status')
    if status:
        qs = qs.filter(status=status)
        status_labels = dict(Visit.STATUS_CHOICES)
        active_filters.append({'label': f'الحالة: {status_labels.get(status, status)}', 'param': 'status'})

    # Approval Status
    approval_status = request.GET.get('approval_status')
    if approval_status:
        qs = qs.filter(approval_status=approval_status)
        approval_labels = dict(Visit.APPROVAL_CHOICES)
        active_filters.append({'label': f'حالة الاعتماد: {approval_labels.get(approval_status, approval_status)}', 'param': 'approval_status'})

    # Planned vs Unplanned Classification Filter (Requirement 5)
    plan_type = request.GET.get('plan_type')
    if plan_type == 'planned':
        qs = qs.filter(is_planned=True)
        active_filters.append({'label': 'النوع: زيارة مخططة', 'param': 'plan_type'})
    elif plan_type == 'unplanned':
        qs = qs.filter(is_planned=False)
        active_filters.append({'label': 'النوع: زيارة خارج الخطة', 'param': 'plan_type'})

    # Representative (owner)
    rep_id = request.GET.get('owner')
    if rep_id:
        qs = qs.filter(owner_id=rep_id)
        u_obj = User.objects.filter(id=rep_id).first()
        active_filters.append({'label': f'المسؤول: {u_obj.get_full_name() or u_obj.username if u_obj else rep_id}', 'param': 'owner'})

    # Date Range
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    if date_from:
        qs = qs.filter(date__gte=date_from)
        active_filters.append({'label': f'من تاريخ: {date_from}', 'param': 'date_from'})
    if date_to:
        qs = qs.filter(date__lte=date_to)
        active_filters.append({'label': f'إلى تاريخ: {date_to}', 'param': 'date_to'})

    # View Mode: table or cards
    view_mode = request.GET.get('view', 'table')

    # Standardized bounded pagination
    paginator, page_obj = paginate_queryset(request, qs, default_per_page=25, max_per_page=100)

    user_can_manage = can_manage_approvals(request.user)
    for v in page_obj.object_list:
        v.user_can_approve = bool(
            user_can_manage and
            v.owner_id != request.user.id and
            can_user_access_object(request.user, v, 'approve')
        )

    # Filter dropdowns
    users = User.objects.filter(is_active=True).order_by('first_name', 'username')
    contacts = Contact.objects.all().order_by('name')[:50]
    templates = VisitTemplate.objects.filter(active=True)

    approved_count = qs.filter(approval_status='approved').count()
    pending_count = qs.filter(approval_status='pending').count()
    planned_count = Visit.objects.filter(is_planned=True).count()
    unplanned_count = Visit.objects.filter(is_planned=False).count()

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
        'contacts': contacts,
        'templates': templates,
        'selected_q': q,
        'selected_status': status,
        'selected_approval_status': approval_status,
        'selected_plan_type': plan_type,
        'selected_owner': rep_id,
        'selected_date_from': date_from,
        'selected_date_to': date_to,
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
        Visit.objects.select_related('contact', 'contact__area', 'template', 'owner', 'approved_by', 'created_by', 'bypassed_by')
        .prefetch_related('samples__product', 'expenses', 'detailed_products'),
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
        action = request.POST.get('action', 'complete').strip()

        if action == 'cancel':
            if not can_user_access_object(request.user, visit, 'edit') and visit.owner != request.user:
                return render_forbidden_response(request, "غير مصرح لك بإلغاء هذه الزيارة.")
            old_status = visit.status
            visit.status = 'cancelled'
            visit.save(update_fields=['status'])
            cancel_reason = (request.POST.get('cancel_reason') or 'إلغاء الزيارة').strip()
            ApprovalAuditLog.objects.create(
                record_type='visit',
                visit=visit,
                action='cancelled',
                actor=request.user,
                status_before=old_status,
                status_after='cancelled',
                reason=cancel_reason,
                ip_address=request.META.get('REMOTE_ADDR')
            )
            AuditLogService.log(
                action='update',
                action_type='VISIT_CANCELLED',
                module='visits',
                user=request.user,
                request=request,
                record_id=visit.pk,
                object_repr=f"Visit #{visit.serial_num}",
                previous_values={'status': old_status},
                new_values={'status': 'cancelled', 'reason': cancel_reason}
            )
            messages.warning(request, f"تم إلغاء الزيارة #{visit.serial_num}.")
            return redirect('visit_detail', pk=visit.pk)

        # Process Questionnaire Answers
        answers = dict(visit.questionnaire_answers or {})
        validation_errors = []

        if template:
            questions = template.get_active_questions()
            parent_answers = {}

            # First pass: collect parent answers
            for q in questions:
                field_name = f'question_{q.id}'
                val = request.POST.get(field_name) or request.POST.getlist(field_name)
                if isinstance(val, list) and len(val) == 1:
                    val = val[0]
                elif isinstance(val, list) and len(val) == 0:
                    val = ''
                if q.question_type == 'multiple_choice':
                    val = request.POST.getlist(field_name)
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
                val = request.POST.get(field_name) or request.POST.getlist(field_name)
                if isinstance(val, list) and len(val) == 1:
                    val = val[0]
                elif isinstance(val, list) and len(val) == 0:
                    val = ''
                if q.question_type == 'multiple_choice':
                    val = request.POST.getlist(field_name)

                # Validate required questions strictly when completing
                if action == 'complete' and q.is_required and (val is None or val == '' or val == []):
                    validation_errors.append(f"السؤال '{q.text_ar}' إلزامي لإتمام الزيارة.")

                if val is not None and val != '':
                    answers[str(q.id)] = val

        # Handle Location & Photo Evidence
        lat = request.POST.get('latitude') or visit.latitude
        lng = request.POST.get('longitude') or visit.longitude
        acc = request.POST.get('device_accuracy') or visit.device_accuracy
        photo_file = request.FILES.get('location_photo')
        force_bypass_raw = request.POST.get('force_bypass_location') in ('1', 'true', 'True', 'on')
        request_exception_raw = request.POST.get('request_distance_exception') in ('1', 'true', 'True', 'on')
        force_bypass = bool(force_bypass_raw and can_bypass_gps)
        request_distance_exception = bool((request_exception_raw or (force_bypass_raw and not can_bypass_gps)) and not can_bypass_gps)
        bypass_reason = (request.POST.get('bypass_reason') or '').strip()

        # Enforce GPS and Distance Validation when completing visit (Section 3.C & 3.D)
        if action == 'complete':
            if location_settings.verify_visits and not force_bypass and not can_bypass_gps and not request_distance_exception:
                if not lat or not lng:
                    validation_errors.append("تحديد الموقع الجغرافي (GPS) إلزامي للمندوب لإنهاء الزيارة.")

            if not validation_errors:
                try:
                    verify_visit_location(
                        visit, request.user, visit.contact,
                        visit_lat=lat, visit_lng=lng, device_accuracy=acc,
                        photo_file=photo_file, force_bypass=force_bypass,
                        bypass_reason=bypass_reason, stage='end',
                        request_distance_exception=request_distance_exception,
                        strict_distance=bool(location_settings.verify_visits and location_settings.verify_end_visit_distance)
                    )
                except ValidationError as ve:
                    err_text = ve.message if hasattr(ve, 'message') else (ve.messages[0] if hasattr(ve, 'messages') and ve.messages else str(ve))
                    validation_errors.append(err_text)
                except Exception as e:
                    validation_errors.append(f"خطأ في معالجة الموقع أو الصورة: {str(e)}")

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
                feedback = request.POST.get('feedback', '')
                if feedback:
                    visit.feedback = feedback

                # Outcome
                visit_outcome = request.POST.get('visit_outcome', '').strip()
                if visit_outcome:
                    visit.visit_outcome = visit_outcome
                    visit.is_successful = (visit_outcome == 'successful')

                if action != 'complete' and (lat or lng or photo_file or force_bypass):
                    try:
                        verify_visit_location(
                            visit, request.user, visit.contact,
                            visit_lat=lat, visit_lng=lng, device_accuracy=acc,
                            photo_file=photo_file, force_bypass=force_bypass,
                            bypass_reason=bypass_reason, stage='end',
                            request_distance_exception=request_distance_exception,
                            strict_distance=False
                        )
                    except Exception:
                        pass

                # Product Detailing (Requirement 8): Restricted to the three templates
                if template and template.is_product_detailing_supported():
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

                    if visit.requires_approval_due_to_distance:
                        ApprovalAuditLog.objects.create(
                            record_type='visit',
                            visit=visit,
                            action='distance_exception_requested',
                            actor=request.user,
                            status_before=old_status,
                            status_after='pending',
                            reason=f"طلب استثناء لتجاوز المسافة عند الإنهاء ({visit.distance}م مقابل المسموح {visit.allowed_distance}م): {bypass_reason}",
                            ip_address=request.META.get('REMOTE_ADDR')
                        )
                        AuditLogService.log(
                            action='update',
                            action_type='VISIT_DISTANCE_EXCEPTION_REQUESTED',
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
                                'bypass_reason': bypass_reason,
                                'approval_status': visit.approval_status,
                            }
                        )
                    elif visit.verification_status == 'force_bypassed':
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
                    # Save Draft (Status remains 'started', resumable)
                    visit.save()
                    AuditLogService.log(
                        action='update',
                        action_type='VISIT_DRAFT_SAVED',
                        module='visits',
                        user=request.user,
                        request=request,
                        record_id=visit.pk,
                        object_repr=f"Visit #{visit.serial_num}",
                        new_values={'questionnaire_answers': answers, 'feedback': visit.feedback}
                    )
                    messages.success(request, f"تم حفظ مسودة إجابات الزيارة #{visit.serial_num} بنجاح (الزيارة لا تزال جارية).")

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
    if visit.template:
        active_qs = list(visit.template.get_active_questions())
        if visit.status == 'started':
            all_questions = active_qs
        else:
            all_questions = list(visit.template.questions.all().order_by('order', 'id'))
        start_questions = [q for q in active_qs if q.stage == 'start_only']
        completion_questions = [q for q in active_qs if q.stage in ['all', 'end_only']]
        answers = visit.questionnaire_answers or {}
        for q in all_questions:
            ans = answers.get(str(q.id))
            if ans is not None and ans != '':
                if isinstance(ans, list):
                    display_ans = ", ".join(str(x) for x in ans)
                else:
                    display_ans = str(ans)
                questionnaire_responses.append({
                    'question': q,
                    'text_ar': q.text_ar,
                    'text_en': q.text_en,
                    'stage': q.get_stage_display(),
                    'answer': display_ans,
                    'raw_answer': ans,
                    'is_meeting_question': ('meet' in q.text_ar.lower() or 'قابلت' in q.text_ar)
                })

    # Configurable Product Suggestions: collect from template & global settings
    suggested_product_ids = set()
    if template:
        suggested_product_ids.update(template.get_eligible_suggested_products().values_list('id', flat=True))
    if location_settings.enable_product_suggestions:
        suggested_product_ids.update(location_settings.get_eligible_suggested_products().values_list('id', flat=True))

    # Eligible products (sellable & active) + any historically detailed products
    eligible_products = Product.get_eligible_for_visits()
    historical_ids = set(visit.detailed_products.values_list('id', flat=True))
    all_product_ids = set(eligible_products.values_list('id', flat=True)) | historical_ids
    products = Product.objects.filter(id__in=all_product_ids).order_by('name')

    can_approve = can_manage_approvals(request.user) and can_user_access_object(request.user, visit, 'approve')
    can_resubmit = (visit.approval_status in ('disapproved', 'rejected')) and (
        visit.owner == request.user or request.user.is_superuser or getattr(request.user, 'is_super_admin', False)
    )
    can_start_visit_val, _ = can_start_visit(visit, request.user)
    approval_history = visit.approval_history.select_related('actor').all()
    timeline_events = build_visit_timeline(visit)
    is_in_agenda = PlannedVisitItem.objects.filter(visit=visit).exists()
    effective_allowed_distance = visit.effective_allowed_distance

    return render(request, 'activities/visit_detail.html', {
        'visit': visit,
        'questionnaire_responses': questionnaire_responses,
        'all_questions': all_questions,
        'start_questions': start_questions,
        'completion_questions': completion_questions,
        'products': products,
        'suggested_product_ids': suggested_product_ids,
        'supports_detailing': supports_detailing,
        'can_bypass_gps': can_bypass_gps,
        'bypass_reason_mandatory': location_settings.bypass_reason_mandatory,
        'distance_bypass_requires_approval': location_settings.distance_bypass_requires_approval,
        'verify_visits_enabled': location_settings.verify_visits,
        'verify_end_visit_distance': location_settings.verify_end_visit_distance,
        'gps_tolerance': effective_allowed_distance,
        'allowed_distance': effective_allowed_distance,
        'default_tolerance': location_settings.tolerance,
        'can_manage_approvals': can_manage_approvals(request.user),
        'can_approve': can_approve,
        'can_resubmit': can_resubmit,
        'can_start_visit': can_start_visit_val,
        'approval_history': approval_history,
        'timeline_events': timeline_events,
        'is_in_agenda': is_in_agenda,
        'status_choices': Visit.STATUS_CHOICES,
        'approval_choices': Visit.APPROVAL_CHOICES,
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
                request.user.is_superuser or
                getattr(request.user, 'is_super_admin', False) or
                has_perm_or_admin(request.user, 'activities:planned/manage')
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
    can_bypass_gps = location_settings.can_user_bypass_without_approval(request.user, stage='create')

    # Planned visits must ONLY be created through the bulk planned-visits workflow
    # and executed via planned_item_id. Direct visits via /visits/create/ are strictly unplanned.
    is_planned_visit = bool(planned_item is not None)

    duplicate_warning = False
    existing_same_day_visits = Visit.objects.none()
    existing_same_day_plans = PlannedVisitItem.objects.none()

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
            elif (planned_item.plan_day.date if planned_item else (form.cleaned_data.get('date') or timezone.now().date())) < timezone.now().date():
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

                visit_date = planned_item.plan_day.date if planned_item else (form.cleaned_data.get('date') or timezone.now().date())

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
                else:
                    with transaction.atomic():
                        visit = form.save(commit=False)
                        visit.created_by = request.user
                        visit.owner = owner
                        visit.is_planned = is_planned_visit
                        visit.date = visit_date
                        visit.status = 'planned'
                        visit.started_at = None
                        visit.allowed_distance = location_settings.get_effective_tolerance(template)

                        if not location_settings.require_manager_approval_for_visits or has_perm_or_admin(request.user, 'activities:visits/approve'):
                            visit.approval_status = 'approved'
                            visit.approved_by = request.user
                            visit.approved_at = timezone.now()
                        else:
                            visit.approval_status = 'pending'

                        lat = request.POST.get('latitude') or request.POST.get('lat')
                        lng = request.POST.get('longitude') or request.POST.get('lng')
                        acc = request.POST.get('device_accuracy')
                        photo_file = request.FILES.get('location_photo')
                        force_bypass_raw = request.POST.get('force_bypass_location') in ('1', 'true', 'True', 'on')
                        request_exception_raw = request.POST.get('request_distance_exception') in ('1', 'true', 'True', 'on')
                        force_bypass = bool(force_bypass_raw and can_bypass_gps)
                        request_distance_exception = bool((request_exception_raw or (force_bypass_raw and not can_bypass_gps)) and not can_bypass_gps)
                        bypass_reason = (request.POST.get('bypass_reason') or '').strip()

                        try:
                            if not is_planned_visit:
                                if location_settings.verify_visits and location_settings.verify_unplanned_visit_distance:
                                    verify_visit_location(
                                        visit, request.user, contact,
                                        visit_lat=lat, visit_lng=lng, device_accuracy=acc,
                                        photo_file=photo_file, force_bypass=force_bypass,
                                        bypass_reason=bypass_reason, stage='create',
                                        request_distance_exception=request_distance_exception,
                                        strict_distance=True
                                    )
                                elif lat or lng or photo_file or force_bypass:
                                    verify_visit_location(
                                        visit, request.user, contact,
                                        visit_lat=lat, visit_lng=lng, device_accuracy=acc,
                                        photo_file=photo_file, force_bypass=force_bypass,
                                        bypass_reason=bypass_reason, stage='create',
                                        request_distance_exception=request_distance_exception,
                                        strict_distance=False
                                    )
                            else:
                                # Planned visits: distance validation is NOT required during creation (Section 3.B)
                                if (lat or lng) and location_settings.verify_visits:
                                    try:
                                        verify_visit_location(
                                            visit, request.user, contact,
                                            visit_lat=lat, visit_lng=lng, device_accuracy=acc,
                                            photo_file=photo_file, force_bypass=force_bypass,
                                            bypass_reason=bypass_reason, stage='create',
                                            request_distance_exception=request_distance_exception,
                                            strict_distance=False
                                        )
                                    except Exception:
                                        pass
                        except ValidationError as ve:
                            err_msg = ve.message if hasattr(ve, 'message') else (ve.messages[0] if hasattr(ve, 'messages') and ve.messages else str(ve))
                            form.add_error(None, err_msg)
                            return render(request, 'activities/visit_form.html', {
                                'form': form,
                                'contacts': contacts,
                                'templates': templates,
                                'location_settings': location_settings,
                                'planned_item': planned_item,
                                'planned_item_id': planned_item.id if planned_item else None,
                                'is_planned_workflow': is_planned_visit,
                                'verify_visits_enabled': location_settings.verify_visits,
                                'verify_unplanned_distance': location_settings.verify_unplanned_visit_distance,
                                'can_bypass_gps': can_bypass_gps,
                                'default_tolerance': location_settings.tolerance,
                            })

                        visit.save()

                        # Handle product detailing if submitted
                        if template and template.is_product_detailing_supported():
                            detailed_ids = request.POST.getlist('detailed_products')
                            if detailed_ids:
                                eligible_ids = set(Product.get_eligible_for_visits().values_list('id', flat=True))
                                valid_ids = [int(pid) for pid in detailed_ids if str(pid).isdigit() and int(pid) in eligible_ids]
                                visit.detailed_products.set(valid_ids)

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
                        if visit.requires_approval_due_to_distance:
                            ApprovalAuditLog.objects.create(
                                record_type='visit',
                                visit=visit,
                                action='distance_exception_requested',
                                actor=request.user,
                                status_before='planned',
                                status_after='pending',
                                reason=f"طلب استثناء لتجاوز المسافة عند الإنشاء ({visit.distance}م مقابل المسموح {visit.allowed_distance}م): {bypass_reason}",
                                ip_address=request.META.get('REMOTE_ADDR')
                            )
                        elif visit.verification_status == 'force_bypassed':
                            ApprovalAuditLog.objects.create(
                                record_type='visit',
                                visit=visit,
                                action='distance_bypass',
                                actor=request.user,
                                status_before='planned',
                                status_after=visit.approval_status,
                                reason=f"تجاوز المسافة عند الإنشاء ({visit.distance or 0}م مقابل المسموح {visit.allowed_distance}م): {bypass_reason or 'تجاوز مباشر بصلاحية المدير/المشرف'}",
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
        selected_contact = planned_item.contact
    else:
        contact_id = request.POST.get('contact') or request.GET.get('contact') or request.GET.get('contact_id')
        if contact_id and str(contact_id).isdigit():
            cand = Contact.objects.filter(pk=int(contact_id)).select_related('area', 'area__parent').first()
            if cand and can_user_access_contact_for_visit(request.user, cand):
                selected_contact = cand

    selected_template = None
    template_id_val = request.POST.get('template') or request.GET.get('template') or request.GET.get('template_id') or (planned_item.template_id if planned_item else None)
    if template_id_val and str(template_id_val).isdigit():
        selected_template = VisitTemplate.objects.filter(pk=int(template_id_val)).first()

    effective_tolerance = location_settings.get_effective_tolerance(selected_template)
    products = Product.get_eligible_for_visits()
    templates = [t for t in VisitTemplate.objects.filter(active=True).prefetch_related('restricted_roles').order_by('name') if t.is_user_eligible(request.user)]
    today_date = timezone.now().date()
    today_str = today_date.strftime('%Y-%m-%d')

    return render(request, 'activities/visit_form.html', {
        'form': form,
        'products': products,
        'templates': templates,
        'selected_contact': selected_contact,
        'selected_template': selected_template,
        'planned_item': planned_item,
        'planned_item_id': planned_item.pk if planned_item else None,
        'is_planned_visit': is_planned_visit,
        'today': today_date,
        'visit_type': 'planned' if is_planned_visit else 'unplanned',
        'can_bypass_gps': can_bypass_gps,
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
    Edit visit details while visit has not ended (status != 'finished').
    Ended visits remain strictly uneditable.
    Enforces Post-Approval Editing Reapproval Rules (Section 5.A).
    """
    visit = get_object_or_404(Visit, pk=pk)
    if not can_user_access_object(request.user, visit, 'edit'):
        return render_forbidden_response(request, "غير مصرح لك بتعديل بيانات هذه الزيارة.")

    # Strict restriction: Ended / Finished visits CANNOT be edited
    if visit.status == 'finished':
        messages.error(request, "لا يمكن تعديل بيانات الزيارة بعد اكتمالها وإنهائها نهائياً.")
        return redirect('visit_detail', pk=visit.pk)

    if request.method == 'POST':
        prev_approval_status = visit.approval_status
        prev_values = {
            'contact_id': visit.contact_id,
            'template_id': visit.template_id,
            'date': str(visit.date),
            'owner_id': visit.owner_id,
            'feedback': visit.feedback or '',
            'visit_outcome': visit.visit_outcome or '',
            'is_successful': visit.is_successful,
            'doubled': visit.doubled,
            'questionnaire_answers': dict(visit.questionnaire_answers or {}),
            'detailed_products': list(visit.detailed_products.values_list('id', flat=True)),
            'approval_status': visit.approval_status,
        }

        form = VisitForm(request.POST, request.FILES, instance=visit, user=request.user)
        if form.is_valid():
            with transaction.atomic():
                visit = form.save(commit=False)
                template = visit.template

                # Process Questionnaire Answers
                answers = dict(visit.questionnaire_answers or {})
                if template:
                    questions = template.get_active_questions()
                    parent_answers = {}
                    for q in questions:
                        is_visible = True
                        if q.is_conditional and q.conditional_parent_id:
                            parent_val = parent_answers.get(q.conditional_parent_id, '')
                            trigger_val = (q.conditional_trigger_value or '').strip().lower()
                            if str(parent_val).strip().lower() != trigger_val:
                                is_visible = False

                        if not is_visible:
                            answers.pop(str(q.id), None)
                            continue

                        field_name = f'question_{q.id}'
                        val = request.POST.get(field_name) or request.POST.getlist(field_name)
                        if isinstance(val, list) and len(val) == 1:
                            val = val[0]
                        elif isinstance(val, list) and len(val) == 0:
                            val = ''
                        if q.question_type == 'multiple_choice':
                            val = request.POST.getlist(field_name)

                        if val is not None and val != '':
                            answers[str(q.id)] = val
                            parent_answers[q.id] = val

                visit.questionnaire_answers = answers
                visit_outcome = request.POST.get('visit_outcome', '').strip()
                if visit_outcome:
                    visit.visit_outcome = visit_outcome
                    visit.is_successful = (visit_outcome == 'successful')

                # Post-Approval Editing Rule:
                # Identify if approval-relevant fields changed
                critical_fields_changed = False
                if str(visit.date) != prev_values['date']:
                    critical_fields_changed = True
                elif visit.contact_id != prev_values['contact_id']:
                    critical_fields_changed = True
                elif visit.template_id != prev_values['template_id']:
                    critical_fields_changed = True
                elif visit.owner_id != prev_values['owner_id']:
                    critical_fields_changed = True
                elif visit.doubled != prev_values['doubled']:
                    critical_fields_changed = True
                elif visit.questionnaire_answers != prev_values['questionnaire_answers']:
                    critical_fields_changed = True

                was_approved = (prev_approval_status == 'approved')
                user_has_approval_authority = can_manage_approvals(request.user) and can_user_access_object(request.user, visit, 'approve')
                reapproval_triggered = False

                # Handle product detailing only if supported
                detailed_product_ids = []
                if template and template.is_product_detailing_supported():
                    detailed_ids_raw = request.POST.getlist('detailed_products')
                    if detailed_ids_raw:
                        eligible_ids = set(Product.get_eligible_for_visits().values_list('id', flat=True))
                        historical_ids = set(visit.detailed_products.values_list('id', flat=True))
                        allowed_ids = eligible_ids | historical_ids
                        detailed_product_ids = [int(pid) for pid in detailed_ids_raw if str(pid).isdigit() and int(pid) in allowed_ids]
                        visit.detailed_products.set(detailed_product_ids)
                    elif 'detailed_products_submitted' in request.POST:
                        visit.detailed_products.clear()
                else:
                    visit.detailed_products.clear()

                if set(detailed_product_ids) != set(prev_values['detailed_products']):
                    critical_fields_changed = True

                if was_approved and not user_has_approval_authority and critical_fields_changed:
                    visit.approval_status = 'pending'
                    visit.waiting_for_reapproval = True
                    reapproval_triggered = True

                visit.save()

                new_values = {
                    'contact_id': visit.contact_id,
                    'template_id': visit.template_id,
                    'date': str(visit.date),
                    'owner_id': visit.owner_id,
                    'feedback': visit.feedback or '',
                    'visit_outcome': visit.visit_outcome or '',
                    'is_successful': visit.is_successful,
                    'doubled': visit.doubled,
                    'questionnaire_answers': dict(visit.questionnaire_answers or {}),
                    'detailed_products': list(visit.detailed_products.values_list('id', flat=True)),
                    'approval_status': visit.approval_status,
                    'waiting_for_reapproval': visit.waiting_for_reapproval,
                }

                if reapproval_triggered:
                    ApprovalAuditLog.objects.create(
                        record_type='visit',
                        visit=visit,
                        action='edited_reapproval_required',
                        actor=request.user,
                        status_before='approved',
                        status_after='pending',
                        reason='تم تعديل الزيارة بعد الاعتماد بواسطة المندوب — تتطلب إعادة اعتماد المدير',
                        ip_address=request.META.get('REMOTE_ADDR')
                    )
                    AuditLogService.log(
                        action='update',
                        action_type='VISIT_EDITED_REAPPROVAL_REQUIRED',
                        module='visits',
                        user=request.user,
                        request=request,
                        record_id=visit.pk,
                        object_repr=f"Visit #{visit.serial_num}",
                        previous_values=prev_values,
                        new_values=new_values
                    )
                    messages.warning(
                        request,
                        f"تم حفظ التعديلات على الزيارة #{visit.serial_num}. نظراً لتعديل بيانات جوهرية بعد اعتمادها، تم تحويل حالتها إلى (بانتظار إعادة الاعتماد) من المدير."
                    )
                else:
                    audit_action = 'edited_by_manager' if user_has_approval_authority else 'edited'
                    if user_has_approval_authority and was_approved:
                        ApprovalAuditLog.objects.create(
                            record_type='visit',
                            visit=visit,
                            action='edited_by_manager',
                            actor=request.user,
                            status_before=prev_approval_status,
                            status_after=visit.approval_status,
                            reason='تعديل بيانات الزيارة بواسطة مدير/مشرف معتمد',
                            ip_address=request.META.get('REMOTE_ADDR')
                        )
                    AuditLogService.log(
                        action='update',
                        action_type='VISIT_UPDATED',
                        module='visits',
                        user=request.user,
                        request=request,
                        record_id=visit.pk,
                        object_repr=f"Visit #{visit.serial_num}",
                        previous_values=prev_values,
                        new_values=new_values
                    )
                    messages.success(request, f"تم تحديث بيانات الزيارة #{visit.serial_num} بنجاح.")

            return redirect('visit_detail', pk=visit.pk)
    else:
        # GET request: Ended visits cannot be opened for editing
        if visit.status == 'finished':
            messages.error(request, "لا يمكن تعديل بيانات الزيارة بعد اكتمالها وإنهائها نهائياً.")
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
        'saved_detailed_products': saved_detailed_products,
        'can_bypass_gps': can_bypass_gps,
        'is_lower_user': not is_manager_or_higher(request.user),
        'verify_visits_enabled': location_settings.verify_visits,
        'gps_tolerance': visit.effective_allowed_distance,
        'title': f'تعديل الزيارة #{visit.serial_num}'
    })


@require_permission('activities:visits/edit')
def visit_set_time(request, pk):
    """
    Quick-action endpoint to set or update a visit's scheduled time
    without a full page reload (Requirement 7).
    Enforces authorization, regional/ABAC data scope, validates time format,
    updates Visit.time and Visit.visit_time, and records to SecurityAuditLog.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'MethodNotAllowed', 'detail': 'POST method required.'}, status=405)

    visit = get_object_or_404(Visit.objects.select_related('contact', 'owner'), pk=pk)

    # Scoping check: Representatives can only edit their own visits within their scope
    if not can_user_access_object(request.user, visit, 'edit'):
        return JsonResponse({
            'success': False,
            'error': 'PermissionDenied',
            'detail': 'غير مصرح لك بتعديل وقت هذه الزيارة خارج نطاقك الجغرافي أو صلاحياتك.'
        }, status=403)

    raw_time = (request.POST.get('time') or '').strip()
    if not raw_time:
        return JsonResponse({
            'success': False,
            'error': 'ValidationError',
            'detail': 'يرجى تحديد وقت الزيارة.'
        }, status=400)

    # Parse time (supports HH:MM or HH:MM:SS or 12h formats)
    parsed_time = None
    for fmt in ('%H:%M', '%H:%M:%S', '%I:%M %p', '%I:%M%p'):
        try:
            parsed_time = datetime.datetime.strptime(raw_time, fmt).time()
            break
        except ValueError:
            continue

    if not parsed_time:
        return JsonResponse({
            'success': False,
            'error': 'ValidationError',
            'detail': 'صيغة الوقت غير صالحة. يرجى إدخال الوقت بصيغة (HH:MM).'
        }, status=400)

    old_time_str = visit.time.strftime('%H:%M') if visit.time else None
    new_time_str = parsed_time.strftime('%H:%M')

    with transaction.atomic():
        visit.time = parsed_time
        if visit.date:
            combined_dt = datetime.datetime.combine(visit.date, parsed_time)
            visit.visit_time = timezone.make_aware(combined_dt) if timezone.is_naive(combined_dt) else combined_dt
        visit.save(update_fields=['time', 'visit_time'])

        AuditLogService.log(
            action='update',
            action_type='VISIT_TIME_UPDATED',
            module='visits',
            user=request.user,
            request=request,
            record_id=visit.pk,
            object_repr=f"Visit #{visit.serial_num} ({visit.contact.name})",
            previous_values={'time': old_time_str},
            new_values={'time': new_time_str},
        )

    formatted_12h = parsed_time.strftime('%I:%M %p')
    arabic_period = 'م' if parsed_time.hour >= 12 else 'ص'
    display_time_ar = f"{parsed_time.strftime('%I:%M')} {arabic_period}"

    return JsonResponse({
        'success': True,
        'message': f"تم تحديث وقت الزيارة بنجاح إلى {display_time_ar}.",
        'time_24': new_time_str,
        'time_12': formatted_12h,
        'display_time': display_time_ar,
    })


@require_permission('activities:visits/evidence')
def visit_evidence_photo(request, pk):
    """
    Secure Evidence Photo Access (Requirement 7).
    Prevents unauthorized access to another representative's private evidence photo.
    Authorized users:
    - Visit owner (conducted by)
    - Visit creator
    - Area managers / supervisors
    - Superusers and staff
    """
    visit = get_object_or_404(Visit, pk=pk)
    if not visit.location_photo:
        raise Http404("لا توجد صورة إثبات موقع مسجلة لهذه الزيارة.")

    user = request.user
    can_view = (
        user.is_superuser or
        getattr(user, 'is_super_admin', False) or
        visit.owner_id == user.pk or
        visit.created_by_id == user.pk or
        (user.role and user.role.is_area_manager) or
        can_manage_approvals(user)
    )

    if not can_view:
        return HttpResponseForbidden("عذراً، غير مصرح لك بالوصول إلى صورة الإثبات الخاصة بزيارة مستخدم آخر.")

    try:
        content_type, _ = mimetypes.guess_type(visit.location_photo.name)
        return FileResponse(visit.location_photo.open('rb'), content_type=content_type or 'image/jpeg')
    except Exception:
        raise Http404("تعذر فتح ملف صورة الإثبات.")



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
        if next_url and next_url.startswith('/'):
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

        can_bypass_gps = getattr(request.user, 'can_bypass_location', False) or request.user.is_superuser or getattr(request.user, 'is_super_admin', False)

        # Collect check-in questions (stage == 'start_only')
        checkin_answers = {}
        if visit.template:
            for q in visit.template.get_active_questions().filter(stage='start_only'):
                field_name = f'question_{q.id}'
                val = request.POST.get(field_name) or request.POST.getlist(field_name)
                if isinstance(val, list) and len(val) == 1:
                    val = val[0]
                elif isinstance(val, list) and len(val) == 0:
                    val = ''
                if q.question_type == 'multiple_choice':
                    val = request.POST.getlist(field_name)
                if val:
                    checkin_answers[str(q.id)] = val

        try:
            start_visit(
                visit, request.user, request=request,
                lat=request.POST.get('latitude') or request.GET.get('latitude'),
                lng=request.POST.get('longitude') or request.GET.get('longitude'),
                accuracy=request.POST.get('device_accuracy') or request.GET.get('device_accuracy'),
                photo_file=request.FILES.get('location_photo'),
                force_bypass=bool(request.POST.get('force_bypass_location') == '1' and can_bypass_gps),
                bypass_reason=request.POST.get('bypass_reason', ''),
                checkin_answers=checkin_answers
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
        request_exception_raw = request.POST.get('request_distance_exception') in ('1', 'true', 'True', 'on')
        force_bypass = bool(force_bypass_raw and can_bypass_gps)
        request_distance_exception = bool((request_exception_raw or (force_bypass_raw and not can_bypass_gps)) and not can_bypass_gps)
        try:
            end_visit(
                visit, request.user, request=request,
                lat=request.POST.get('latitude'),
                lng=request.POST.get('longitude'),
                accuracy=request.POST.get('device_accuracy'),
                photo_file=request.FILES.get('location_photo'),
                force_bypass=force_bypass,
                request_distance_exception=request_distance_exception,
                bypass_reason=request.POST.get('bypass_reason', ''),
                feedback=request.POST.get('feedback', ''),
                visit_outcome=request.POST.get('visit_outcome', '')
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
        if not can_manage_approvals(request.user):
            msg = "عذراً، لا تملك صلاحية اعتماد أو رفض الزيارات (خاص بالمدراء والمشرفين)."
            if is_ajax:
                return JsonResponse({'success': False, 'message': msg}, status=403)
            messages.error(request, msg)
            return get_redirect()

        if not can_user_access_object(request.user, visit, action):
            msg = "غير مصرح لك باتخاذ إجراء اعتماد على هذه الزيارة (خارج نطاق مسؤوليتك الإقليمية أو المندوب العادي لا يمكنه اعتماد زيارته الخاصة)."
            if is_ajax:
                return JsonResponse({'success': False, 'message': msg}, status=403)
            messages.error(request, msg)
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
        if not can_manage_approvals(request.user):
            msg = "عذراً، لا تملك صلاحية تغيير حالة أو اعتماد الزيارات (خاص بالمدراء والمشرفين)."
            return render_forbidden_response(request, msg)

        if not can_user_access_object(request.user, visit, 'approve'):
            msg = "غير مصرح لك بتغيير حالة هذه الزيارة (خارج نطاق مسؤوليتك الإقليمية أو لا يمكن للمندوب اعتماد زيارته الخاصة)."
            return render_forbidden_response(request, msg)

        new_approval_status = request.POST.get('approval_status', '').strip()
        new_visit_status = request.POST.get('visit_status', '').strip()
        reason = request.POST.get('reason', '').strip() or request.POST.get('approval_notes', '').strip() or 'تحديث الحالة من قبل مدير المنطقة'

        changes = []
        status_before = f"حالة: {visit.status} | اعتماد: {visit.approval_status}"

        if new_approval_status and new_approval_status in dict(Visit.APPROVAL_CHOICES):
            if new_approval_status != visit.approval_status:
                visit.approval_status = new_approval_status
                if new_approval_status == 'approved':
                    visit.approved_by = request.user
                    visit.approved_at = timezone.now()
                    visit.waiting_for_reapproval = False
                    visit.requires_approval_due_to_distance = False
                elif new_approval_status == 'disapproved':
                    visit.approved_by = request.user
                    visit.approved_at = timezone.now()
                    visit.waiting_for_reapproval = False
                elif new_approval_status == 'pending':
                    visit.approved_by = None
                    visit.approved_at = None
                changes.append(f"حالة الاعتماد: {visit.get_approval_status_display()}")

        if new_visit_status and new_visit_status in dict(Visit.STATUS_CHOICES):
            if new_visit_status != visit.status:
                visit.status = new_visit_status
                if new_visit_status == 'finished' and not visit.ended_at:
                    visit.ended_at = timezone.now()
                changes.append(f"حالة الزيارة: {visit.get_status_display()}")

        if reason:
            visit.approval_notes = reason

        visit.save()

        status_after = f"حالة: {visit.status} | اعتماد: {visit.approval_status}"
        ApprovalAuditLog.objects.create(
            record_type='visit',
            visit=visit,
            action='status_changed',
            actor=request.user,
            status_before=status_before,
            status_after=status_after,
            reason=reason,
            ip_address=request.META.get('REMOTE_ADDR')
        )
        msg = f"تم تحديث حالة الزيارة #{visit.serial_num} بنجاح ({' ، '.join(changes) if changes else 'بدون تغيير'})."
        if is_ajax:
            return JsonResponse({'success': True, 'message': msg, 'status': visit.status, 'approval_status': visit.approval_status})
        messages.success(request, msg)

    elif action == 'send_to_agenda':
        # Business rule: visit MUST be approved before sending it to the agenda
        if visit.approval_status != 'approved':
            msg = "عذراً، يجب اعتماد الزيارة أولاً من مدير المنطقة قبل إرسالها إلى جدول الأعمال."
            if is_ajax:
                return JsonResponse({'success': False, 'message': msg}, status=400)
            messages.error(request, msg)
            return get_redirect()

        can_access = (
            request.user.is_superuser or
            getattr(request.user, 'is_super_admin', False) or
            can_user_access_object(request.user, visit, 'view')
        )
        if not can_access:
            msg = "غير مصرح لك بإرسال هذه الزيارة إلى جدول الأعمال."
            if is_ajax:
                return JsonResponse({'success': False, 'message': msg}, status=403)
            messages.error(request, msg)
            return get_redirect()

        pday, _ = PlannedVisitDay.objects.get_or_create(
            assignee=visit.owner,
            date=visit.date,
            defaults={'created_by': request.user}
        )

        existing_item = PlannedVisitItem.objects.filter(visit=visit).first()
        if not existing_item:
            existing_contact_item = PlannedVisitItem.objects.filter(plan_day=pday, contact=visit.contact).first()
            if existing_contact_item and not existing_contact_item.visit:
                existing_item = existing_contact_item
                existing_item.visit = visit
                existing_item.is_executed = (visit.status == 'finished')
                existing_item.template = visit.template or existing_item.template
                existing_item.save()
            else:
                max_order = pday.items.count() + 1
                existing_item = PlannedVisitItem.objects.create(
                    plan_day=pday,
                    order=max_order,
                    contact=visit.contact,
                    template=visit.template,
                    visit=visit,
                    is_executed=(visit.status == 'finished'),
                    notes=visit.feedback or f"زيارة معتمدة #{visit.serial_num}"
                )

        visit.is_planned = True
        visit.save(update_fields=['is_planned'])

        ApprovalAuditLog.objects.create(
            record_type='visit',
            visit=visit,
            action='sent_to_agenda',
            actor=request.user,
            status_before=visit.approval_status,
            status_after='in_agenda',
            reason=f"إرسال الزيارة المعتمة #{visit.serial_num} إلى جدول الأعمال ليوم {visit.date}",
            ip_address=request.META.get('REMOTE_ADDR')
        )

        msg = f"تم إرسال الزيارة المعتمة #{visit.serial_num} بنجاح إلى جدول أعمال ({visit.owner.get_full_name() or visit.owner.username}) ليوم {visit.date.strftime('%d/%m/%Y')}."
        if is_ajax:
            return JsonResponse({
                'success': True,
                'message': msg,
                'agenda_url': f"{reverse('agenda')}?date={visit.date.strftime('%Y-%m-%d')}&assignee={visit.owner_id}"
            })
        messages.success(request, msg)
        return redirect(f"{reverse('agenda')}?date={visit.date.strftime('%Y-%m-%d')}&assignee={visit.owner_id}")

    else:
        msg = "إجراء غير معروف."
        if is_ajax:
            return JsonResponse({'success': False, 'message': msg}, status=400)
        messages.error(request, msg)

    return get_redirect()


@require_permission('activities:visits/export')
def visits_export(request):
    """Export visits to Excel (.xlsx)."""
    qs = Visit.objects.select_related('contact', 'template', 'owner').prefetch_related('samples__product').all()
    qs = get_scoped_queryset(qs, request.user, 'visit')

    # Same filters
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(Q(contact__name__icontains=q) | Q(serial_num__icontains=q))
    if request.GET.get('status'):
        qs = qs.filter(status=request.GET.get('status'))
    if request.GET.get('approval_status'):
        qs = qs.filter(approval_status=request.GET.get('approval_status'))
    if request.GET.get('owner'):
        qs = qs.filter(owner_id=request.GET.get('owner'))
    if request.GET.get('date_from'):
        qs = qs.filter(date__gte=request.GET.get('date_from'))
    if request.GET.get('date_to'):
        qs = qs.filter(date__lte=request.GET.get('date_to'))

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "الزيارات"
    ws.views.sheetView[0].rightToLeft = True

    header_fill = PatternFill(start_color="27BEBE", end_color="27BEBE", fill_type="solid")
    header_font = Font(name="Cairo", size=11, bold=True, color="FFFFFF")

    headers = [
        "رقم الزيارة", "العميل", "كود العميل", "التاريخ", "المسؤول",
        "القالب", "الحالة", "حالة الاعتماد", "زيارة ناجحة", "مزدوجة", "المدة (ثواني)", "العينات الموزعة"
    ]
    ws.append(headers)

    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")

    for v in qs:
        samples_str = ", ".join([f"{s.product.name} ({s.quantity})" for s in v.samples.all()])
        ws.append([
            f"#{v.serial_num}",
            v.contact.name if v.contact else "",
            v.contact.code if v.contact else "",
            v.date.strftime("%Y-%m-%d") if v.date else "",
            v.owner.get_full_name() or v.owner.username if v.owner else "",
            v.template.display_name_ar if v.template else "",
            v.status_display_ar,
            v.approval_display_ar,
            "نعم" if v.is_successful else "لا",
            "نعم" if v.doubled else "لا",
            v.duration,
            samples_str
        ])

    response = HttpResponse(content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response['Content-Disposition'] = f'attachment; filename="visits_{timezone.now().strftime("%Y%m%d_%H%M")}.xlsx"'
    wb.save(response)
    return response


# -----------------------------------------------------------------------------
# VISIT TEMPLATES MODULE (إدارة قوالب الزيارات)
# -----------------------------------------------------------------------------
# VISIT TEMPLATES & QUESTION BUILDER MODULE (قوالب الزيارات)
# -----------------------------------------------------------------------------

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
    template = get_object_or_404(VisitTemplate.objects.prefetch_related('questions'), pk=pk)
    questions = template.get_active_questions()
    products = Product.objects.filter(is_active=True)[:10]

    start_questions = [q for q in questions if q.stage == 'start_only']
    completion_questions = [q for q in questions if q.stage in ['all', 'end_only']]

    return render(request, 'activities/visit_template_preview.html', {
        'template': template,
        'questions': questions,
        'start_questions': start_questions,
        'completion_questions': completion_questions,
        'products': products,
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
        stage = request.POST.get('stage', 'all')
        is_required = request.POST.get('is_required') in ['true', '1', 'on']
        is_conditional = request.POST.get('is_conditional') in ['true', '1', 'on']
        conditional_parent_id = request.POST.get('conditional_parent') or None
        conditional_trigger_value = request.POST.get('conditional_trigger_value', '').strip()

        if not text_ar:
            messages.error(request, "يرجى كتابة نص السؤال بالعربية.")
            return redirect('visit_template_edit', pk=template_pk)

        # Build options list from POST
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
        stage = request.POST.get('stage', question.stage)
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
        if question_type in ['single_choice', 'multiple_choice']:
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
    is_mgr = ScopeResolutionService.get_user_scope(request.user, 'activities', 'view') in ['area', 'all']
    can_view_others = is_super or is_mgr

    if is_super:
        available_reps = User.objects.filter(is_active=True).order_by('first_name', 'username')
    elif is_mgr:
        managed_ids = list(get_user_managed_representatives(request.user).values_list('id', flat=True)) + [request.user.pk]
        available_reps = User.objects.filter(id__in=managed_ids, is_active=True).order_by('first_name', 'username')
    else:
        available_reps = User.objects.filter(pk=request.user.pk)

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

    # Query Planned visits for that day
    plan_day = PlannedVisitDay.objects.filter(assignee=selected_rep, date=selected_date).first()
    planned_items = []
    planned_visit_ids = set()
    if plan_day:
        planned_items = list(plan_day.items.select_related('contact', 'template', 'visit', 'visit__approved_by').order_by('order', 'id'))
        for itm in planned_items:
            if itm.visit_id:
                planned_visit_ids.add(itm.visit_id)

    # Query out-of-plan / ad-hoc visits executed for that day
    unplanned_visits = Visit.objects.filter(
        owner=selected_rep,
        date=selected_date
    ).exclude(
        id__in=planned_visit_ids
    ).select_related('contact', 'template', 'owner', 'approved_by').order_by('serial_num')

    user_can_manage = can_manage_approvals(request.user)
    agenda_visits = []
    for itm in planned_items:
        v = itm.visit
        if v:
            can_approve = bool(
                user_can_manage and
                v.owner_id != request.user.id and
                can_user_access_object(request.user, v, 'approve')
            )
            agenda_visits.append({
                'type': 'planned',
                'source_item': itm,
                'visit': v,
                'contact': itm.contact,
                'template': itm.template or v.template,
                'order': itm.order,
                'status': v.status,
                'status_display': v.status_display_ar,
                'status_badge_class': v.status_badge_class,
                'approval_status': v.approval_status,
                'approval_display': v.approval_display_ar,
                'approval_badge_class': v.approval_badge_class,
                'is_executed': (v.status == 'finished'),
                'can_approve': can_approve,
                'detail_url': reverse('visit_detail', args=[v.pk]),
                'action_url': reverse('visit_detail', args=[v.pk]),
                'action_label': 'متابعة الزيارة' if v.status == 'started' else ('بدء الزيارة' if v.status == 'planned' and v.approval_status == 'approved' else 'معاينة التفاصيل'),
                'notes': itm.notes,
            })
        else:
            agenda_visits.append({
                'type': 'planned',
                'source_item': itm,
                'visit': None,
                'contact': itm.contact,
                'template': itm.template,
                'order': itm.order,
                'status': 'planned',
                'status_display': 'مخططة',
                'status_badge_class': 'bg-sky-100 text-sky-800 border-sky-300',
                'approval_status': 'approved',
                'approval_display': 'مجدولة',
                'approval_badge_class': 'bg-teal-50 text-teal-700 border-teal-200',
                'is_executed': False,
                'can_approve': False,
                'detail_url': None,
                'action_url': f"{reverse('visit_create')}?contact_id={itm.contact_id}&template_id={itm.template_id or ''}&plan_item_id={itm.id}",
                'action_label': 'بدء الزيارة',
                'notes': itm.notes,
            })

    for v in unplanned_visits:
        can_approve = bool(
            user_can_manage and
            v.owner_id != request.user.id and
            can_user_access_object(request.user, v, 'approve')
        )
        agenda_visits.append({
            'type': 'unplanned',
            'source_item': None,
            'visit': v,
            'contact': v.contact,
            'template': v.template,
            'order': None,
            'status': v.status,
            'status_display': v.status_display_ar,
            'status_badge_class': v.status_badge_class,
            'approval_status': v.approval_status,
            'approval_display': v.approval_display_ar,
            'approval_badge_class': v.approval_badge_class,
            'is_executed': (v.status == 'finished'),
            'can_approve': can_approve,
            'detail_url': reverse('visit_detail', args=[v.pk]),
            'action_url': reverse('visit_detail', args=[v.pk]),
            'action_label': 'متابعة الزيارة' if v.status == 'started' else ('بدء الزيارة' if v.status == 'planned' and v.approval_status == 'approved' else 'معاينة التفاصيل'),
            'notes': v.feedback,
        })

    # Todos
    todos = AgendaTodo.objects.filter(user=selected_rep, date=selected_date).order_by('is_completed', '-created_at')

    # Available contacts for quick out-of-plan registration modal
    scoped_contacts = get_scoped_queryset(Contact.objects.all(), request.user, 'contact')
    quick_contacts = scoped_contacts.order_by('name')[:60]

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
        'agenda_visits': agenda_visits,
        'visits_count': len(agenda_visits),
        'todos': todos,
        'todos_count': todos.count(),
        'quick_contacts': quick_contacts,
        'current_tab': current_tab,
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
        is_mgr = ScopeResolutionService.get_user_scope(request.user, 'activities', 'view') in ['area', 'all']
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
    is_mgr = ScopeResolutionService.get_user_scope(request.user, 'activities', 'view') in ['area', 'all']
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
    is_mgr = ScopeResolutionService.get_user_scope(request.user, 'activities', 'view') in ['area', 'all']
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



