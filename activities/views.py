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
from master_data.models import Area
from catalog.models import Product
from .services import (
    verify_visit_location, can_start_visit, start_visit,
    can_submit_answers, save_visit_answers, can_end_visit, end_visit
)
from accounts.permissions import (
    require_permission, has_perm_or_admin, render_forbidden_response,
    get_scoped_queryset, can_user_access_object, get_user_managed_representatives
)

User = get_user_model()


def can_manage_approvals(user, module_type='visits'):
    """
    Check if the user is authorized to approve/disapprove or change approval status
    of visits and agreements using centralized permission architecture.
    """
    if not user.is_authenticated:
        return False
    from accounts.permissions import is_manager_or_higher
    if is_manager_or_higher(user):
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
    if user.role and (user.role.is_area_manager or user.role.is_sub_area_manager):
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
            from accounts.permissions import is_manager_or_higher
            loc_settings = LocationSettings.get_settings()
            if not loc_settings.require_manager_approval_for_agreements or is_manager_or_higher(request.user):
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
            from accounts.permissions import is_manager_or_higher
            loc_settings = LocationSettings.get_settings()
            if not loc_settings.require_manager_approval_for_agreements or is_manager_or_higher(request.user):
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
    if not can_user_access_object(request.user, agreement, 'edit'):
        return render_forbidden_response(request, "لا يمكنك تغيير حالة هذه الاتفاقية.")

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
    Day-by-day accordion planner view for selected representative and date range.
    Matches https://weapharma.bricks-rep.com/planned-visits
    """
    # Selected representative (rep scoping: non-managers can only view their own plan)
    can_view_others = (
        request.user.is_superuser or
        getattr(request.user, 'is_super_admin', False) or
        (request.user.role and request.user.role.is_manager_role) or
        has_perm_or_admin(request.user, 'activities:planned/manage')
    )
    rep_id = request.GET.get('assignee')
    if rep_id and can_view_others:
        selected_rep = get_object_or_404(User, pk=rep_id)
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

    # Build calendar day cards
    current_date = start_date
    days_list = []
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
        days_list.append({
            'date': current_date,
            'weekday_ar': arabic_weekdays[current_date.weekday()],
            'formatted_date': current_date.strftime('%d/%m/%Y'),
            'plan_day': plan_day,
            'items': items,
            'items_count': len(items),
            'is_planned': len(items) > 0,
        })
        current_date += datetime.timedelta(days=1)

    # Contacts for drawer filter (scoped to representative's assigned area/hierarchy)
    contacts_qs = get_scoped_queryset(Contact.objects.all(), request.user, 'contact')
    area_filter = request.GET.get('area')
    specialty_filter = request.GET.get('specialty')
    search_contact = request.GET.get('contact_search')

    if area_filter:
        contacts_qs = contacts_qs.filter(area_id=area_filter)
    if specialty_filter:
        contacts_qs = contacts_qs.filter(specialty__icontains=specialty_filter)
    if search_contact:
        contacts_qs = contacts_qs.filter(Q(name__icontains=search_contact) | Q(code__icontains=search_contact))

    drawer_contacts = contacts_qs.order_by('name')[:40]

    # Dropdowns for UI
    if can_view_others:
        all_reps = User.objects.filter(is_active=True).order_by('first_name', 'username')
    else:
        all_reps = User.objects.filter(id=request.user.id)
    areas = Area.objects.all().order_by('name')
    visit_templates = VisitTemplate.objects.filter(active=True)

    context = {
        'selected_rep': selected_rep,
        'all_reps': all_reps,
        'start_date': start_date.strftime('%Y-%m-%d'),
        'end_date': end_date.strftime('%Y-%m-%d'),
        'days_list': days_list,
        'drawer_contacts': drawer_contacts,
        'areas': areas,
        'visit_templates': visit_templates,
        'selected_area': area_filter,
        'selected_specialty': specialty_filter,
        'selected_contact_search': search_contact,
    }
    return render(request, 'activities/planned_visits_list.html', context)


@require_permission(['activities:visits/create', 'activities:visits/list', 'activities:planned/list', 'settings:visitsTemplates/manage'])
def visit_templates_api(request):
    """
    API endpoint returning active visit templates.
    Supports filtering by contact_id or account_type.
    Returns template metadata, questions schema, and product detailing capabilities.
    """
    contact_id = request.GET.get('contact_id') or request.GET.get('contact')
    account_type = request.GET.get('account_type', '').strip().lower()

    contact = None
    if contact_id:
        contact = Contact.objects.filter(pk=contact_id).first()
        if contact and contact.account_type:
            account_type = contact.account_type.strip().lower()

    qs = VisitTemplate.objects.filter(active=True).prefetch_related('questions')

    results = []
    for tmpl in qs:
        # Centralized check via model method
        if not tmpl.is_user_eligible(request.user):
            continue
        if contact:
            is_eligible = tmpl.is_contact_eligible(contact, user=request.user)
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
            results.append({
                'id': tmpl.id,
                'name': tmpl.name,
                'display_name_ar': tmpl.display_name_ar,
                'display_name_en': tmpl.display_name_en,
                'allow_unplanned': tmpl.allow_unplanned,
                'enable_product_detailing': tmpl.enable_product_detailing,
                'supports_product_detailing': tmpl.is_product_detailing_supported(),
                'restrict_account_types': tmpl.restrict_account_types or [],
                'questions': questions_data
            })

    return JsonResponse({'results': results})



@require_permission('activities:planned/manage')
def planned_visit_add_item(request):
    """Add a contact to a specific day's plan with strict parity and duplicate checks."""
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

        assignee = get_object_or_404(User, pk=assignee_id)
        # Rep permission check: non-managers cannot add items to another representative's plan
        can_manage_others = (
            request.user.is_superuser or
            getattr(request.user, 'is_super_admin', False) or
            (request.user.role and request.user.role.is_manager_role)
        )
        if assignee != request.user and not can_manage_others:
            msg = "غير مصرح لك بإضافة زيارات لخطة مندوب آخر."
            if is_ajax:
                return JsonResponse({'success': False, 'message': msg}, status=403)
            messages.error(request, msg)
            return redirect(request.META.get('HTTP_REFERER', '/planned-visits/'))

        contact = get_object_or_404(Contact, pk=contact_id)
        template = VisitTemplate.objects.filter(pk=template_id).first() if template_id else None

        if template and not template.is_contact_eligible(contact, user=request.user):
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
            msg = f"تمت إضافة {contact.name} إلى خطة يوم {date_str} بنجاح."
            if is_ajax:
                return JsonResponse({'success': True, 'message': msg, 'item_id': item.id, 'contact_name': contact.name})
            messages.success(request, msg)

    return redirect(f"{request.META.get('HTTP_REFERER', '/planned-visits/')}#day-{date_str}")


@require_permission('activities:planned/manage')
def planned_visit_item_delete(request, pk):
    """Remove a planned visit item."""
    item = get_object_or_404(PlannedVisitItem, pk=pk)
    is_owner = (item.plan_day.assignee == request.user)
    can_override = (
        request.user.is_superuser or
        getattr(request.user, 'is_super_admin', False) or
        (request.user.role and request.user.role.is_manager_role)
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
        (request.user.role and request.user.role.name in ['manager', 'admin'])
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

    can_view_all = (
        request.user.is_superuser or
        getattr(request.user, 'is_super_admin', False) or
        (request.user.role and request.user.role.is_manager_role)
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
        Visit.objects.select_related('contact', 'template', 'owner', 'approved_by', 'created_by')
        .prefetch_related('samples__product', 'expenses', 'detailed_products'),
        pk=pk
    )

    if not can_user_access_object(request.user, visit, 'view'):
        return render_forbidden_response(request, "غير مصرح لك بالوصول إلى تفاصيل هذه الزيارة.")

    can_bypass_gps = getattr(request.user, 'can_bypass_location', False) or request.user.is_superuser or getattr(request.user, 'is_super_admin', False)
    template = visit.template
    supports_detailing = template.is_product_detailing_supported() if template else False

    if request.method == 'POST':
        action = request.POST.get('action', 'complete').strip()

        if action == 'cancel':
            visit.status = 'cancelled'
            visit.save()
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
        force_bypass = bool(request.POST.get('force_bypass_location') == '1' and can_bypass_gps)
        bypass_reason = request.POST.get('bypass_reason', '')

        from master_data.models import LocationSettings
        location_settings = LocationSettings.get_settings()

        # Enforce GPS and Photo requirement when completing visit (Requirement 7)
        if action == 'complete' and location_settings.verify_visits and not force_bypass and not can_bypass_gps:
            if not lat or not lng:
                validation_errors.append("تحديد الموقع الجغرافي (GPS) إلزامي للمندوب لإنهاء الزيارة.")
            if not photo_file and not visit.location_photo:
                validation_errors.append("التقاط صورة إثبات الموقع الحالية إلزامي لإنهاء الزيارة.")

        if validation_errors:
            # Preserve answers when a validation error occurs! (Requirement 4)
            visit.questionnaire_answers = answers
            visit.save()
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

                # Location & Photo Evidence Verification
                try:
                    verify_visit_location(
                        visit, request.user, visit.contact,
                        visit_lat=lat, visit_lng=lng, device_accuracy=acc,
                        photo_file=photo_file, force_bypass=force_bypass, bypass_reason=bypass_reason
                    )
                except Exception as e:
                    messages.error(request, f"خطأ في معالجة الموقع أو الصورة: {str(e)}")

                # Product Detailing (Requirement 8): Restricted to the three templates
                if template and template.is_product_detailing_supported():
                    detailed_product_ids = request.POST.getlist('detailed_products')
                    if detailed_product_ids:
                        # Products not intended for sale must not be selectable for new visit-related operations.
                        # Preserve historical detailed products already linked to this visit.
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

                    ApprovalAuditLog.objects.create(
                        record_type='visit',
                        visit=visit,
                        action='status_changed',
                        actor=request.user,
                        status_before='started',
                        status_after='finished',
                        reason='إنهاء الزيارة وتوثيق الإجراءات رسمياً (Check-out)',
                        ip_address=request.META.get('REMOTE_ADDR')
                    )
                    messages.success(request, f"تم إنهاء وتوثيق الزيارة #{visit.serial_num} بنجاح. استغرقت الزيارة {visit.duration_formatted}.")
                else:
                    # Save Draft (Status remains 'started', resumable)
                    visit.save()
                    messages.success(request, f"تم حفظ مسودة إجابات الزيارة #{visit.serial_num} بنجاح (الزيارة لا تزال جارية).")

            is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'application/json' in request.headers.get('accept', '')
            if is_ajax:
                return JsonResponse({
                    'success': True,
                    'status': visit.status,
                    'serial_num': visit.serial_num,
                    'duration': visit.duration,
                    'duration_formatted': visit.duration_formatted,
                    'message': f"تم إنهاء وتوثيق الزيارة #{visit.serial_num} بنجاح (استغرقت {visit.duration_formatted})." if action == 'complete' else "تم حفظ البيانات بنجاح."
                })
            return redirect('visit_detail', pk=visit.pk)

    # GET Request: prepare structured questionnaire answers and questions
    questionnaire_responses = []
    all_questions = []
    if visit.template:
        if visit.status == 'started':
            all_questions = list(visit.template.get_active_questions())
        else:
            all_questions = list(visit.template.questions.all().order_by('order', 'id'))
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

    from master_data.models import LocationSettings
    location_settings = LocationSettings.get_settings()

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
    # can_start_visit: centralized service check
    can_start_visit_val, _ = can_start_visit(visit, request.user)
    approval_history = visit.approval_history.select_related('actor').all()
    is_in_agenda = PlannedVisitItem.objects.filter(visit=visit).exists()

    return render(request, 'activities/visit_detail.html', {
        'visit': visit,
        'questionnaire_responses': questionnaire_responses,
        'all_questions': all_questions,
        'products': products,
        'suggested_product_ids': suggested_product_ids,
        'supports_detailing': supports_detailing,
        'can_bypass_gps': can_bypass_gps,
        'verify_visits_enabled': location_settings.verify_visits,
        'gps_tolerance': location_settings.tolerance,
        'can_manage_approvals': can_manage_approvals(request.user),
        'can_approve': can_approve,
        'can_resubmit': can_resubmit,
        'can_start_visit': can_start_visit_val,
        'approval_history': approval_history,
        'is_in_agenda': is_in_agenda,
        'status_choices': Visit.STATUS_CHOICES,
        'approval_choices': Visit.APPROVAL_CHOICES,
    })


@require_permission('activities:visits/create')
def visit_create(request):
    """
    Standardized Unified Visit Registration endpoint: /visits/create/
    Used by both planned visits (via planned-visits/ with planned_item_id)
    and unplanned visits (via floating '+' or quick add without planned_item_id).
    Validates permissions, template restrictions, representative locking, and persists
    the visit record first with status='started' before directing to questionnaire.
    """
    planned_item_id = request.POST.get('planned_item_id') or request.GET.get('planned_item_id')
    planned_item = None
    if planned_item_id:
        try:
            planned_item = PlannedVisitItem.objects.select_related('plan_day__assignee', 'contact', 'template').get(pk=planned_item_id)
            is_owner = (planned_item.plan_day.assignee == request.user)
            can_override = (
                request.user.is_superuser or
                getattr(request.user, 'is_super_admin', False) or
                (request.user.role and request.user.role.name in ['manager', 'admin'])
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

    can_bypass_gps = getattr(request.user, 'can_bypass_location', False) or request.user.is_superuser or getattr(request.user, 'is_super_admin', False)

    if request.method == 'POST':
        form = VisitForm(request.POST, request.FILES, user=request.user)
        if form.is_valid():
            contact = form.cleaned_data['contact']
            template = form.cleaned_data.get('template')

            # Backend Eligibility Validation
            if template and not template.is_contact_eligible(contact):
                allowed_str = ", ".join(template.restrict_account_types) if template.restrict_account_types else "الكل"
                form.add_error('template', f"قالب الزيارة '{template.display_name_ar}' غير مصرح به لنوع حساب العميل ({contact.account_type or 'غير محدد'}). الأنواع المصرح بها: {allowed_str}.")
                messages.error(request, form.errors.as_text())
            else:
                # Representative Assignment Locking
                if can_assign_other_representative(request.user):
                    owner = form.cleaned_data.get('owner') or request.user
                else:
                    owner = request.user

                # Anti-duplicate check (within last 60 seconds)
                recent_duplicate = Visit.objects.filter(
                    contact=contact,
                    owner=owner,
                    status__in=['planned', 'started'],
                    created_at__gte=timezone.now() - datetime.timedelta(seconds=60)
                ).first()
                if recent_duplicate:
                    messages.warning(request, f"يوجد زيارة تم إنشاؤها منذ لحظات لهذا العميل (زيارة #{recent_duplicate.serial_num}).")
                    return redirect('visit_detail', pk=recent_duplicate.pk)

                with transaction.atomic():
                    visit = form.save(commit=False)
                    visit.created_by = request.user
                    visit.owner = owner
                    visit.is_planned = bool(planned_item)
                    if planned_item:
                        visit.date = planned_item.plan_day.date
                    # Visit is created as 'planned'; the rep must explicitly start it after approval
                    visit.status = 'planned'
                    visit.started_at = None

                    from master_data.models import LocationSettings
                    from accounts.permissions import is_manager_or_higher
                    loc_settings = LocationSettings.get_settings()
                    if not loc_settings.require_manager_approval_for_visits or is_manager_or_higher(request.user):
                        visit.approval_status = 'approved'
                        visit.approved_by = request.user
                        visit.approved_at = timezone.now()
                    else:
                        visit.approval_status = 'pending'

                    # Initial location verification if coordinates provided
                    lat = request.POST.get('latitude') or request.POST.get('lat')
                    lng = request.POST.get('longitude') or request.POST.get('lng')
                    acc = request.POST.get('device_accuracy')
                    photo_file = request.FILES.get('location_photo')
                    force_bypass = bool(request.POST.get('force_bypass_location') == '1' and can_bypass_gps)
                    bypass_reason = request.POST.get('bypass_reason', '')
                    if loc_settings.verify_visits or lat or lng or photo_file or force_bypass:
                        try:
                            verify_visit_location(
                                visit, request.user, contact,
                                visit_lat=lat, visit_lng=lng, device_accuracy=acc,
                                photo_file=photo_file, force_bypass=force_bypass, bypass_reason=bypass_reason
                            )
                        except Exception:
                            pass

                    visit.save()

                    # Handle product detailing if template supports it
                    if template and template.is_product_detailing_supported():
                        detailed_ids = request.POST.getlist('detailed_products')
                        if detailed_ids:
                            eligible_ids = set(Product.get_eligible_for_visits().values_list('id', flat=True))
                            valid_ids = [int(pid) for pid in detailed_ids if str(pid).isdigit() and int(pid) in eligible_ids]
                            visit.detailed_products.set(valid_ids)

                    # Associate planned item if execution came from planned visits
                    if planned_item:
                        planned_item.is_executed = False  # Not executed until visit is started & finished
                        planned_item.visit = visit
                        planned_item.save()

                messages.success(request, f"تم إنشاء الزيارة #{visit.serial_num} للعميل {contact.name} بنجاح. {'يمكنك بدء الزيارة الآن.' if visit.approval_status == 'approved' else 'الزيارة في انتظار الاعتماد.'}")
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
        initial = {'date': timezone.now().date(), 'owner': request.user}
        if planned_item:
            initial['contact'] = planned_item.contact.id
            if planned_item.template:
                initial['template'] = planned_item.template.id
            initial['date'] = planned_item.plan_day.date
            initial['planned_item_id'] = planned_item.pk
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
        if contact_id:
            selected_contact = Contact.objects.filter(pk=contact_id).select_related('area').first()

    from master_data.models import LocationSettings
    location_settings = LocationSettings.get_settings()
    can_bypass_gps = getattr(request.user, 'can_bypass_location', False) or request.user.is_superuser or getattr(request.user, 'is_super_admin', False)

    products = Product.get_eligible_for_visits()
    templates = VisitTemplate.objects.filter(active=True).order_by('name')
    return render(request, 'activities/visit_form.html', {
        'form': form,
        'products': products,
        'templates': templates,
        'selected_contact': selected_contact,
        'planned_item': planned_item,
        'planned_item_id': planned_item.pk if planned_item else None,
        'is_planned_visit': bool(planned_item),
        'can_bypass_gps': can_bypass_gps,
        'verify_visits_enabled': location_settings.verify_visits,
        'gps_tolerance': location_settings.tolerance,
        'title': 'تسجيل زيارة مخططة' if planned_item else 'تسجيل زيارة خارج الخطة'
    })



@require_permission('activities:visits/edit')
def visit_edit(request, pk):
    """Edit visit feedback, template answers, and detailed products."""
    visit = get_object_or_404(Visit, pk=pk)
    if not can_user_access_object(request.user, visit, 'edit'):
        return render_forbidden_response(request, "غير مصرح لك بتعديل بيانات هذه الزيارة.")

    if request.method == 'POST':
        form = VisitForm(request.POST, request.FILES, instance=visit, user=request.user)
        if form.is_valid():
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
            visit.save()

            # Handle product detailing only if supported (Requirement 8)
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

            messages.success(request, f"تم تحديث بيانات الزيارة #{visit.serial_num}.")
            return redirect('visit_detail', pk=visit.pk)
    else:
        form = VisitForm(instance=visit, user=request.user)

    eligible_products = Product.get_eligible_for_visits()
    historical_ids = set(visit.detailed_products.values_list('id', flat=True))
    all_product_ids = set(eligible_products.values_list('id', flat=True)) | historical_ids
    products = Product.objects.filter(id__in=all_product_ids).order_by('name')
    templates = VisitTemplate.objects.filter(active=True).order_by('name')
    selected_contact = visit.contact
    from master_data.models import LocationSettings
    location_settings = LocationSettings.get_settings()
    can_bypass_gps = getattr(request.user, 'can_bypass_location', False) or request.user.is_superuser or getattr(request.user, 'is_super_admin', False)

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
        'verify_visits_enabled': location_settings.verify_visits,
        'gps_tolerance': location_settings.tolerance,
        'title': f'تعديل الزيارة #{visit.serial_num}'
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
        can_bypass_gps = getattr(request.user, 'can_bypass_location', False) or request.user.is_superuser or getattr(request.user, 'is_super_admin', False)
        try:
            start_visit(
                visit, request.user, request=request,
                lat=request.POST.get('latitude') or request.GET.get('latitude'),
                lng=request.POST.get('longitude') or request.GET.get('longitude'),
                accuracy=request.POST.get('device_accuracy') or request.GET.get('device_accuracy'),
                photo_file=request.FILES.get('location_photo'),
                force_bypass=bool(request.POST.get('force_bypass_location') == '1' and can_bypass_gps),
                bypass_reason=request.POST.get('bypass_reason', '')
            )
            msg = f"تم بدء الزيارة #{visit.serial_num} بنجاح. يمكنك الآن الإجابة على الاستبيان وإنهاء الزيارة."
            if is_ajax:
                return JsonResponse({'success': True, 'message': msg, 'status': 'started'})
            messages.success(request, msg)
        except ValidationError as e:
            msg = e.message if hasattr(e, 'message') else str(e)
            if is_ajax:
                return JsonResponse({'success': False, 'message': msg}, status=400)
            messages.error(request, msg)
        return get_redirect()

    elif action == 'end':
        can_bypass_gps = getattr(request.user, 'can_bypass_location', False) or request.user.is_superuser or getattr(request.user, 'is_super_admin', False)
        try:
            end_visit(
                visit, request.user, request=request,
                lat=request.POST.get('latitude'),
                lng=request.POST.get('longitude'),
                accuracy=request.POST.get('device_accuracy'),
                photo_file=request.FILES.get('location_photo'),
                force_bypass=bool(request.POST.get('force_bypass_location') == '1' and can_bypass_gps),
                bypass_reason=request.POST.get('bypass_reason', ''),
                feedback=request.POST.get('feedback', ''),
                visit_outcome=request.POST.get('visit_outcome', '')
            )
            msg = f"تم إنهاء وتوثيق الزيارة #{visit.serial_num} بنجاح. استغرقت الزيارة {visit.duration_formatted}."
            if is_ajax:
                return JsonResponse({'success': True, 'message': msg, 'status': 'finished', 'duration': visit.duration, 'duration_formatted': visit.duration_formatted})
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
            visit.approval_status = 'approved'
            visit.approved_by = request.user
            visit.approved_at = timezone.now()
            if notes:
                visit.approval_notes = notes
            visit.save()

            ApprovalAuditLog.objects.create(
                record_type='visit',
                visit=visit,
                action='approved',
                actor=request.user,
                status_before=status_before,
                status_after='approved',
                reason=notes or 'تم اعتماد الزيارة من قبل المدير الإقليمي',
                ip_address=request.META.get('REMOTE_ADDR')
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
                elif new_approval_status == 'disapproved':
                    visit.approved_by = request.user
                    visit.approved_at = timezone.now()
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
    is_super = bool(request.user.is_superuser or getattr(request.user, 'is_super_admin', False))
    is_mgr = bool(request.user.role and request.user.role.is_manager_role)
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
        is_super = bool(request.user.is_superuser or getattr(request.user, 'is_super_admin', False))
        is_mgr = bool(request.user.role and request.user.role.is_manager_role)
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
    is_super = bool(request.user.is_superuser or getattr(request.user, 'is_super_admin', False))
    is_mgr = bool(request.user.role and request.user.role.is_manager_role)
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
    is_super = bool(request.user.is_superuser or getattr(request.user, 'is_super_admin', False))
    is_mgr = bool(request.user.role and request.user.role.is_manager_role)
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



