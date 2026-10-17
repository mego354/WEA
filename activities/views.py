import datetime
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q, Sum, Count
from django.utils import timezone
from django.http import HttpResponse, JsonResponse
from django.contrib.auth import get_user_model
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

from .models import (
    Agreement, AgreementType, VisitTemplate,
    PlannedVisitDay, PlannedVisitItem, Visit,
    VisitSampleItem, VisitExpense
)
from .forms import AgreementForm, PlannedVisitItemForm, VisitForm
from contacts.models import Contact
from master_data.models import Area
from catalog.models import Product
from .services import verify_visit_location

User = get_user_model()



def can_manage_approvals(user):
    """
    Check if the user is authorized to approve/disapprove or change approval status
    of visits and agreements.
    Managers, superusers, and admins have access.
    Field Medical Reps (role.is_rep without manager status) do not.
    """
    if not user.is_authenticated:
        return False
    if user.is_superuser or user.is_staff:
        return True
    if hasattr(user, 'is_super_admin') and user.is_super_admin:
        return True
    if user.role:
        if user.role.is_area_manager:
            return True
        role_name = (user.role.name or '').lower()
        role_display = (user.role.display_name or '').lower()
        if any(term in role_name for term in ['manager', 'admin', 'supervisor', 'director']):
            return True
        if any(term in role_display for term in ['مدير', 'مشرف']):
            return True
        if user.role.is_rep:
            return False
    return False


# -----------------------------------------------------------------------------
# AGREEMENTS MODULE
# -----------------------------------------------------------------------------

@login_required
def agreements_list(request):
    """
    List agreements with search, filters, pagination, sum aggregation, and create modal.
    Matches https://weapharma.bricks-rep.com/agreements
    """
    qs = Agreement.objects.select_related('customer', 'type', 'created_by').all()

    # Search
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(
            Q(title__icontains=q) |
            Q(serial_num__icontains=q) |
            Q(customer__name__icontains=q) |
            Q(customer__code__icontains=q)
        )

    # Type Filter
    type_id = request.GET.get('type')
    if type_id:
        qs = qs.filter(type_id=type_id)

    # Status Filter
    status = request.GET.get('status')
    if status:
        qs = qs.filter(status=status)

    # Assignee Filter (created_by)
    creator_id = request.GET.get('creator')
    if creator_id:
        qs = qs.filter(created_by_id=creator_id)

    # Date Range Filters
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    if date_from:
        qs = qs.filter(date__gte=date_from)
    if date_to:
        qs = qs.filter(date__lte=date_to)

    # Summary Metrics (matches reference aggregate API)
    total_count = qs.count()
    total_amount = qs.aggregate(s=Sum('amount'))['s'] or 0.00

    # Handle inline Create via POST
    if request.method == 'POST' and 'create_agreement' in request.POST:
        form = AgreementForm(request.POST)
        if form.is_valid():
            agreement = form.save(commit=False)
            agreement.created_by = request.user
            agreement.updated_by = request.user
            agreement.status = 'new'
            agreement.save()
            messages.success(request, f"تم إنشاء الاتفاقية #{agreement.serial_num} بنجاح.")
            return redirect('agreements_list')
        else:
            messages.error(request, "يرجى تصحيح الأخطاء في نموذج إنشاء الاتفاقية.")
    else:
        form = AgreementForm(initial={'date': timezone.now().date()})

    # Pagination
    paginator = Paginator(qs, 15)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    # Filter dropdown options
    agreement_types = AgreementType.objects.filter(is_active=True)
    users = User.objects.filter(is_active=True).order_by('first_name', 'username')
    contacts = Contact.objects.all().order_by('name')[:50]

    context = {
        'page_obj': page_obj,
        'agreements': page_obj.object_list,
        'total_count': total_count,
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
        'can_manage_approvals': can_manage_approvals(request.user),
    }
    return render(request, 'activities/agreements_list.html', context)


@login_required
def agreements_bulk_status(request):
    """
    Update status of multiple selected agreements in bulk.
    Matches reference action bar 'تغيير الحالة'.
    Requires manager/superuser authorization.
    """
    if request.method != 'POST':
        return redirect('agreements_list')

    if not can_manage_approvals(request.user):
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


@login_required
def agreement_detail(request, pk):
    """View details of a specific agreement."""
    agreement = get_object_or_404(Agreement.objects.select_related('customer', 'type', 'created_by', 'updated_by'), pk=pk)
    return render(request, 'activities/agreement_detail.html', {
        'agreement': agreement,
        'can_manage_approvals': can_manage_approvals(request.user),
    })


@login_required
def agreement_create(request):
    """Full-page agreement creation."""
    if request.method == 'POST':
        form = AgreementForm(request.POST)
        if form.is_valid():
            agreement = form.save(commit=False)
            agreement.created_by = request.user
            agreement.updated_by = request.user
            agreement.status = 'new'
            agreement.save()
            messages.success(request, f"تم إنشاء الاتفاقية #{agreement.serial_num} بنجاح.")
            return redirect('agreement_detail', pk=agreement.pk)
    else:
        form = AgreementForm(initial={'date': timezone.now().date()})
    return render(request, 'activities/agreement_form.html', {'form': form, 'title': 'إضافة اتفاقية جديدة'})


@login_required
def agreement_edit(request, pk):
    """Edit agreement (allowed if status is new)."""
    agreement = get_object_or_404(Agreement, pk=pk)
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


@login_required
def agreement_action(request, pk, action):
    """Status transitions: approve, disapprove, done, reopen."""
    if not can_manage_approvals(request.user):
        messages.error(request, "عذراً، لا تملك صلاحية تغيير حالة الاعتماد (خاص بالمدراء ومسؤولي النظام).")
        next_url = request.GET.get('next', 'agreement_detail')
        if next_url == 'list':
            return redirect('agreements_list')
        return redirect('agreement_detail', pk=pk)

    agreement = get_object_or_404(Agreement, pk=pk)
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


@login_required
def agreement_delete(request, pk):
    """Delete an agreement if in new state."""
    agreement = get_object_or_404(Agreement, pk=pk)
    if agreement.status != 'new' and not request.user.is_superuser:
        messages.error(request, "لا يمكن حذف اتفاقية معتمدة.")
        return redirect('agreement_detail', pk=agreement.pk)

    serial = agreement.serial_num
    agreement.delete()
    messages.success(request, f"تم حذف الاتفاقية #{serial} بنجاح.")
    return redirect('agreements_list')


@login_required
def agreements_export(request):
    """Export filtered agreements to Excel (.xlsx) with styled formatting."""
    qs = Agreement.objects.select_related('customer', 'type', 'created_by').all()

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

@login_required
def planned_visits_list(request):
    """
    Day-by-day accordion planner view for selected representative and date range.
    Matches https://weapharma.bricks-rep.com/planned-visits
    """
    # Selected representative (defaults to current user)
    rep_id = request.GET.get('assignee')
    if rep_id:
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

    # Contacts for drawer filter
    contacts_qs = Contact.objects.all()
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
    all_reps = User.objects.filter(is_active=True).order_by('first_name', 'username')
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


@login_required
def visit_templates_api(request):
    """API endpoint returning active visit templates for modal dropdowns."""
    templates = VisitTemplate.objects.filter(active=True).values('id', 'name', 'display_name_ar')
    return JsonResponse({'results': list(templates)})


@login_required
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
        contact = get_object_or_404(Contact, pk=contact_id)
        template = VisitTemplate.objects.filter(pk=template_id).first() if template_id else None

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


@login_required
def planned_visit_item_delete(request, pk):
    """Remove a planned visit item."""
    item = get_object_or_404(PlannedVisitItem, pk=pk)
    contact_name = item.contact.name
    date_str = item.plan_day.date.strftime('%Y-%m-%d')
    item.delete()
    messages.success(request, f"تم حذف الزيارة المخططة للعميل {contact_name}.")
    return redirect(f"{request.META.get('HTTP_REFERER', '/planned-visits/')}#day-{date_str}")


@login_required
def planned_visit_item_execute(request, pk):
    """
    Route planned visit execution into the canonical visit registration workflow
    with prefilled customer, template, and plan day context.
    """
    item = get_object_or_404(PlannedVisitItem.objects.select_related('plan_day', 'contact', 'template'), pk=pk)
    
    if item.is_executed and item.visit:
        return redirect('visit_detail', pk=item.visit.pk)

    template_param = f"&template_id={item.template.id}" if item.template else ""
    return redirect(f"/visits/create/?contact_id={item.contact.id}&planned_item_id={item.pk}{template_param}")



@login_required
def planned_visits_export(request):
    """Export planned visits list to Excel."""
    items = PlannedVisitItem.objects.select_related('plan_day__assignee', 'contact__area', 'template', 'visit').all().order_by('plan_day__date', 'order')

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

@login_required
def visits_list(request):
    """
    Visits list with table & cards views, complete filters, status indicators, and export.
    Matches https://weapharma.bricks-rep.com/visits
    """
    qs = Visit.objects.select_related('contact', 'template', 'owner', 'created_by').prefetch_related('samples__product').all()

    # Search
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(
            Q(contact__name__icontains=q) |
            Q(contact__code__icontains=q) |
            Q(serial_num__icontains=q) |
            Q(owner__first_name__icontains=q) |
            Q(owner__username__icontains=q)
        )

    # Status
    status = request.GET.get('status')
    if status:
        qs = qs.filter(status=status)

    # Approval Status
    approval_status = request.GET.get('approval_status')
    if approval_status:
        qs = qs.filter(approval_status=approval_status)

    # Representative (owner)
    rep_id = request.GET.get('owner')
    if rep_id:
        qs = qs.filter(owner_id=rep_id)

    # Date Range
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    if date_from:
        qs = qs.filter(date__gte=date_from)
    if date_to:
        qs = qs.filter(date__lte=date_to)

    # Metrics
    total_count = qs.count()
    approved_count = qs.filter(approval_status='approved').count()
    pending_count = qs.filter(approval_status='pending').count()

    # View Mode: table or cards
    view_mode = request.GET.get('view', 'table')

    # Pagination
    paginator = Paginator(qs, 15)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    # Filter dropdowns
    users = User.objects.filter(is_active=True).order_by('first_name', 'username')
    contacts = Contact.objects.all().order_by('name')[:50]
    templates = VisitTemplate.objects.filter(active=True)

    context = {
        'page_obj': page_obj,
        'visits': page_obj.object_list,
        'total_count': total_count,
        'approved_count': approved_count,
        'pending_count': pending_count,
        'view_mode': view_mode,
        'users': users,
        'contacts': contacts,
        'templates': templates,
        'selected_q': q,
        'selected_status': status,
        'selected_approval_status': approval_status,
        'selected_owner': rep_id,
        'selected_date_from': date_from,
        'selected_date_to': date_to,
        'can_manage_approvals': can_manage_approvals(request.user),
    }
    return render(request, 'activities/visits_list.html', context)


@login_required
def visit_detail(request, pk):
    """View visit dossier, questionnaire answers, samples, and approval actions."""
    visit = get_object_or_404(
        Visit.objects.select_related('contact', 'template', 'owner', 'approved_by', 'created_by')
        .prefetch_related('samples__product', 'expenses'),
        pk=pk
    )
    return render(request, 'activities/visit_detail.html', {
        'visit': visit,
        'can_manage_approvals': can_manage_approvals(request.user),
    })


@login_required
def visit_create(request):
    """
    Canonical Visit Registration endpoint and workflow.
    Reused across ALL entry points:
    1. Visits list create button
    2. Planned visits item execution (بدء الزيارة)
    3. Contact dossier (تسجيل زيارة)
    4. FAB Action 1 (تسجيل زيارة خارج الخطة)
    5. Dashboard / shortcuts

    Enforces customer authorization scoping, location verification, and duplicate prevention.
    """
    planned_item_id = request.POST.get('planned_item_id') or request.GET.get('planned_item_id')

    if request.method == 'POST':
        form = VisitForm(request.POST, user=request.user)
        if form.is_valid():
            contact = form.cleaned_data['contact']
            owner = form.cleaned_data.get('owner') or request.user

            # Anti-duplicate check (within last 60 seconds)
            recent_duplicate = Visit.objects.filter(
                contact=contact,
                owner=owner,
                created_at__gte=timezone.now() - datetime.timedelta(seconds=60)
            ).first()
            if recent_duplicate:
                messages.warning(request, f"تم تسجيل هذه الزيارة بالفعل منذ لحظات (زيارة #{recent_duplicate.serial_num}).")
                return redirect('visit_detail', pk=recent_duplicate.pk)

            visit = form.save(commit=False)
            visit.created_by = request.user
            visit.owner = owner
            visit.is_planned = bool(planned_item_id)
            visit.status = 'finished'
            visit.approval_status = 'pending'
            visit.ended_at = timezone.now()
            visit.started_at = visit.ended_at - datetime.timedelta(minutes=15)
            visit.duration = 900

            # Location Verification with Haversine distance engine
            lat = request.POST.get('latitude') or form.cleaned_data.get('latitude')
            lng = request.POST.get('longitude') or form.cleaned_data.get('longitude')
            acc = request.POST.get('device_accuracy') or form.cleaned_data.get('device_accuracy')
            verify_visit_location(visit, request.user, contact, lat, lng, acc)

            visit.save()

            # Associate planned item if execution came from planned visits
            if planned_item_id:
                planned_item = PlannedVisitItem.objects.filter(pk=planned_item_id).first()
                if planned_item:
                    planned_item.is_executed = True
                    planned_item.visit = visit
                    planned_item.save()

            # Handle samples if provided
            product_id = request.POST.get('sample_product')
            quantity = request.POST.get('sample_quantity', 1)
            if product_id:
                product = Product.objects.filter(pk=product_id).first()
                if product:
                    try:
                        qty = max(1, int(quantity))
                        VisitSampleItem.objects.create(visit=visit, product=product, quantity=qty)
                    except (ValueError, TypeError):
                        pass

            messages.success(request, f"تم تسجيل الزيارة #{visit.serial_num} للعميل {contact.name} بنجاح.")
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
        if contact_id:
            initial['contact'] = contact_id
        if template_id:
            initial['template'] = template_id
        if planned_item_id:
            initial['planned_item_id'] = planned_item_id

        form = VisitForm(initial=initial, user=request.user)

    # Preselected customer details for rich card
    selected_contact = None
    contact_id = request.POST.get('contact') or request.GET.get('contact') or request.GET.get('contact_id')
    if contact_id:
        selected_contact = Contact.objects.filter(pk=contact_id).select_related('area').first()

    from master_data.models import LocationSettings
    location_settings = LocationSettings.get_settings()
    can_bypass_gps = getattr(request.user, 'can_bypass_location', False) or request.user.is_superuser or getattr(request.user, 'is_super_admin', False)

    products = Product.objects.filter(is_active=True).order_by('name')
    templates = VisitTemplate.objects.filter(active=True).order_by('name')
    return render(request, 'activities/visit_form.html', {
        'form': form,
        'products': products,
        'templates': templates,
        'selected_contact': selected_contact,
        'planned_item_id': planned_item_id,
        'can_bypass_gps': can_bypass_gps,
        'verify_visits_enabled': location_settings.verify_visits,
        'gps_tolerance': location_settings.tolerance,
        'title': 'تسجيل زيارة جديدة'
    })



@login_required
def visit_edit(request, pk):
    """Edit visit feedback or results."""
    visit = get_object_or_404(Visit, pk=pk)
    if request.method == 'POST':
        form = VisitForm(request.POST, instance=visit)
        if form.is_valid():
            visit = form.save()
            messages.success(request, f"تم تحديث بيانات الزيارة #{visit.serial_num}.")
            return redirect('visit_detail', pk=visit.pk)
    else:
        form = VisitForm(instance=visit)
    return render(request, 'activities/visit_form.html', {'form': form, 'visit': visit, 'title': f'تعديل الزيارة #{visit.serial_num}'})


@login_required
def visit_action(request, pk, action):
    """Approve or disapprove visit."""
    if not can_manage_approvals(request.user):
        messages.error(request, "عذراً، لا تملك صلاحية اعتماد أو رفض الزيارات (خاص بالمدراء).")
        return redirect('visit_detail', pk=pk)

    visit = get_object_or_404(Visit, pk=pk)
    notes = request.POST.get('approval_notes', '')

    if action == 'approve':
        visit.approval_status = 'approved'
        visit.approved_by = request.user
        if notes:
            visit.approval_notes = notes
        visit.save()
        messages.success(request, f"تم اعتماد الزيارة #{visit.serial_num} بنجاح.")
    elif action == 'disapprove':
        visit.approval_status = 'disapproved'
        visit.approved_by = request.user
        if notes:
            visit.approval_notes = notes
        visit.save()
        messages.error(request, f"تم رفض الزيارة #{visit.serial_num}.")
    else:
        messages.error(request, "إجراء غير معروف.")

    return redirect('visit_detail', pk=visit.pk)


@login_required
def visits_export(request):
    """Export visits to Excel (.xlsx)."""
    qs = Visit.objects.select_related('contact', 'template', 'owner').prefetch_related('samples__product').all()

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

