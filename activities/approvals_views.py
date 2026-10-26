import datetime
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q, Sum, Count
from django.utils import timezone
from django.http import HttpResponse, JsonResponse, HttpResponseForbidden
from django.contrib.auth import get_user_model

from master_data.pagination_utils import paginate_queryset
from master_data.models import Area
from contacts.models import Contact
from sales.models import SalesOrder
from activities.models import Visit, ApprovalAuditLog
from accounts.permissions import (
    require_permission, has_perm_or_admin,
    get_scoped_queryset, can_user_access_object,
    get_user_managed_areas, get_user_managed_representatives
)

User = get_user_model()


from django.urls import reverse

@login_required
def approvals_hub(request):
    """
    Canonical redirect: The separate approval tab has been removed in favor of
    integrating approvals directly into item detail pages and existing list views.
    Redirects legacy bookmarks and navigation links:
    - tab=orders -> sales_orders_list?status=pending
    - others -> visits_list?approval_status=pending
    """
    tab = request.GET.get('tab', 'visits')
    if tab == 'orders':
        url = reverse('sales_orders_list') + '?status=pending'
    else:
        url = reverse('visits_list') + '?approval_status=pending'
    return redirect(url)
    status_filter = request.GET.get('status', 'pending')  # 'pending', 'approved', 'rejected', 'all'
    rep_filter = request.GET.get('representative', '')
    area_filter = request.GET.get('area', '')
    q = request.GET.get('q', '').strip()
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')

    # Filter dropdown datasets scoped to user's regional authority
    managed_reps = get_user_managed_representatives(request.user).filter(is_active=True).order_by('first_name', 'username')
    managed_areas = get_user_managed_areas(request.user).order_by('name')

    # Base QuerySets scoped to regional permissions
    visits_base_qs = Visit.objects.select_related('contact', 'contact__area', 'template', 'owner', 'approved_by').all()
    visits_base_qs = get_scoped_queryset(visits_base_qs, request.user, 'visit')

    orders_base_qs = SalesOrder.objects.select_related('customer', 'customer__area', 'created_by', 'approved_by', 'warehouse').all()
    orders_base_qs = get_scoped_queryset(orders_base_qs, request.user, 'salesorder')

    # Counters for header KPI badges
    pending_visits_count = visits_base_qs.filter(approval_status='pending').count()
    approved_visits_count = visits_base_qs.filter(approval_status='approved').count()
    rejected_visits_count = visits_base_qs.filter(approval_status__in=['disapproved', 'rejected']).count()

    pending_orders_count = orders_base_qs.filter(status='pending').count()
    approved_orders_count = orders_base_qs.filter(status='manager_approval').count()
    rejected_orders_count = orders_base_qs.filter(status='rejected').count()

    total_pending = pending_visits_count + pending_orders_count

    # Filter by Representative
    if rep_filter:
        visits_base_qs = visits_base_qs.filter(owner_id=rep_filter)
        orders_base_qs = orders_base_qs.filter(created_by_id=rep_filter)

    # Filter by Area / Subregion
    if area_filter:
        try:
            target_area = Area.objects.get(pk=area_filter)
            if target_area.area_type == 'governorate':
                sub_ids = list(target_area.children.values_list('id', flat=True)) + [target_area.id]
                visits_base_qs = visits_base_qs.filter(contact__area_id__in=sub_ids)
                orders_base_qs = orders_base_qs.filter(customer__area_id__in=sub_ids)
            else:
                visits_base_qs = visits_base_qs.filter(contact__area_id=target_area.id)
                orders_base_qs = orders_base_qs.filter(customer__area_id=target_area.id)
        except Area.DoesNotExist:
            pass

    # Filter by Date
    if date_from:
        visits_base_qs = visits_base_qs.filter(date__gte=date_from)
        orders_base_qs = orders_base_qs.filter(created_at__date__gte=date_from)
    if date_to:
        visits_base_qs = visits_base_qs.filter(date__lte=date_to)
        orders_base_qs = orders_base_qs.filter(created_at__date__lte=date_to)

    # Filter by Search Query
    if q:
        visits_base_qs = visits_base_qs.filter(
            Q(serial_num__icontains=q) |
            Q(contact__name__icontains=q) |
            Q(contact__code__icontains=q) |
            Q(owner__first_name__icontains=q) |
            Q(owner__username__icontains=q)
        )
        orders_base_qs = orders_base_qs.filter(
            Q(order_number__icontains=q) |
            Q(customer__name__icontains=q) |
            Q(customer__code__icontains=q) |
            Q(created_by__first_name__icontains=q) |
            Q(created_by__username__icontains=q)
        )

    # Page Data depending on active tab
    page_obj = None
    paginator = None

    if active_tab == 'orders':
        qs = orders_base_qs
        if status_filter == 'pending':
            qs = qs.filter(status='pending')
        elif status_filter == 'approved':
            qs = qs.filter(status__in=['manager_approval', 'in_preparation', 'delivered', 'invoiced'])
        elif status_filter == 'rejected':
            qs = qs.filter(status='rejected')
        qs = qs.order_by('-created_at')
        paginator, page_obj = paginate_queryset(request, qs, default_per_page=20, max_per_page=100)

    elif active_tab == 'audit':
        audit_qs = ApprovalAuditLog.objects.select_related('actor', 'visit', 'sales_order').all()
        # Regional filtering for audit log
        managed_user_ids = list(managed_reps.values_list('id', flat=True))
        if not (request.user.is_superuser or getattr(request.user, 'is_super_admin', False)):
            audit_qs = audit_qs.filter(
                Q(visit__owner_id__in=managed_user_ids) |
                Q(sales_order__created_by_id__in=managed_user_ids) |
                Q(actor=request.user)
            )
        if q:
            audit_qs = audit_qs.filter(
                Q(reason__icontains=q) |
                Q(actor__first_name__icontains=q) |
                Q(visit__serial_num__icontains=q) |
                Q(sales_order__order_number__icontains=q)
            )
        audit_qs = audit_qs.order_by('-created_at')
        paginator, page_obj = paginate_queryset(request, audit_qs, default_per_page=25, max_per_page=100)

    else:
        # Default 'visits' tab
        qs = visits_base_qs
        if status_filter == 'pending':
            qs = qs.filter(approval_status='pending')
        elif status_filter == 'approved':
            qs = qs.filter(approval_status='approved')
        elif status_filter == 'rejected':
            qs = qs.filter(approval_status__in=['disapproved', 'rejected'])
        qs = qs.order_by('-date', '-serial_num')
        paginator, page_obj = paginate_queryset(request, qs, default_per_page=20, max_per_page=100)

    context = {
        'active_tab': active_tab,
        'status_filter': status_filter,
        'rep_filter': rep_filter,
        'area_filter': area_filter,
        'q': q,
        'date_from': date_from,
        'date_to': date_to,
        'managed_reps': managed_reps,
        'managed_areas': managed_areas,
        'page_obj': page_obj,
        'paginator': paginator,
        'pending_visits_count': pending_visits_count,
        'approved_visits_count': approved_visits_count,
        'rejected_visits_count': rejected_visits_count,
        'pending_orders_count': pending_orders_count,
        'approved_orders_count': approved_orders_count,
        'rejected_orders_count': rejected_orders_count,
        'total_pending': total_pending,
        'can_approve_visits': can_approve_visits,
        'can_approve_orders': can_approve_orders,
    }
    return render(request, 'approvals/approvals_hub.html', context)
