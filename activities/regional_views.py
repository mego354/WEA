import datetime
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q, Sum, Count, Max
from django.utils import timezone
from django.contrib.auth import get_user_model

from master_data.pagination_utils import paginate_queryset
from master_data.models import Area
from contacts.models import Contact
from sales.models import SalesOrder, Collection, CustomerAccount
from activities.models import Visit
from accounts.permissions import (
    require_permission, has_perm_or_admin,
    get_scoped_queryset, get_user_managed_areas,
    get_user_managed_representatives
)

User = get_user_model()


@login_required
def regional_dashboard(request):
    """
    Regional Management Dashboard.
    Provides regional managers (and super admins) with a comprehensive command center:
    - Territories & Subregions hierarchy overview
    - Managed Representatives breakdown (visits, sales, collections, activity status)
    - Regional Financial & Billing summaries (order volume, collected funds, receivables)
    - Quick access to pending approvals and performance indicators.
    """
    is_manager = bool(
        request.user.is_superuser or
        getattr(request.user, 'is_super_admin', False) or
        (request.user.role and request.user.role.is_manager_role)
    )

    if not is_manager:
        messages.error(request, "عذراً، هذه الصفحة مخصصة لمدراء المناطق والإدارة العليا فقط.")
        return redirect('home')

    # Regional territories
    managed_areas = get_user_managed_areas(request.user)
    governorates = managed_areas.filter(area_type='governorate').prefetch_related('children').order_by('name')
    subareas = managed_areas.filter(area_type='subarea').select_related('parent').order_by('name')

    # Selected subregion filter
    selected_subregion_id = request.GET.get('subregion')
    selected_subregion = None
    if selected_subregion_id:
        selected_subregion = managed_areas.filter(pk=selected_subregion_id).first()

    # Managed Representatives
    managed_reps_qs = get_user_managed_representatives(request.user).filter(is_active=True).select_related('role').prefetch_related('assigned_areas')
    if selected_subregion:
        if selected_subregion.area_type == 'governorate':
            sub_ids = list(selected_subregion.children.values_list('id', flat=True)) + [selected_subregion.id]
            managed_reps_qs = managed_reps_qs.filter(assigned_areas__id__in=sub_ids).distinct()
        else:
            managed_reps_qs = managed_reps_qs.filter(assigned_areas__id=selected_subregion.id).distinct()

    rep_ids = list(managed_reps_qs.values_list('id', flat=True))

    # Regional KPIs: Contacts, Visits, Sales, Collections
    contacts_qs = get_scoped_queryset(Contact.objects.all(), request.user, 'contact')
    visits_qs = get_scoped_queryset(Visit.objects.all(), request.user, 'visit')
    orders_qs = get_scoped_queryset(SalesOrder.objects.all(), request.user, 'salesorder')
    collections_qs = get_scoped_queryset(Collection.objects.all(), request.user, 'collection')

    if selected_subregion:
        if selected_subregion.area_type == 'governorate':
            sub_ids = list(selected_subregion.children.values_list('id', flat=True)) + [selected_subregion.id]
            contacts_qs = contacts_qs.filter(area_id__in=sub_ids)
            visits_qs = visits_qs.filter(contact__area_id__in=sub_ids)
            orders_qs = orders_qs.filter(customer__area_id__in=sub_ids)
            collections_qs = collections_qs.filter(customer__area_id__in=sub_ids)
        else:
            contacts_qs = contacts_qs.filter(area_id=selected_subregion.id)
            visits_qs = visits_qs.filter(contact__area_id=selected_subregion.id)
            orders_qs = orders_qs.filter(customer__area_id=selected_subregion.id)
            collections_qs = collections_qs.filter(customer__area_id=selected_subregion.id)

    total_contacts = contacts_qs.count()
    total_reps = len(rep_ids)

    # Visits statistics
    total_visits = visits_qs.count()
    pending_visits = visits_qs.filter(approval_status='pending').count()
    approved_visits = visits_qs.filter(approval_status='approved').count()

    # Sales & Billing statistics
    total_orders_count = orders_qs.count()
    pending_orders = orders_qs.filter(status='pending').count()
    approved_orders = orders_qs.filter(status__in=['manager_approval', 'in_preparation', 'delivered', 'invoiced']).count()

    total_sales_value = orders_qs.filter(status__in=['manager_approval', 'in_preparation', 'delivered', 'invoiced']).aggregate(
        total=Sum('grand_total')
    )['total'] or 0

    total_collections_value = collections_qs.aggregate(
        total=Sum('amount')
    )['total'] or 0

    # Managed Representatives Detailed Table
    reps_data = []
    for rep in managed_reps_qs.order_by('first_name', 'username'):
        rep_visits = visits_qs.filter(owner=rep)
        rep_orders = orders_qs.filter(created_by=rep)
        rep_colls = collections_qs.filter(created_by=rep)

        reps_data.append({
            'user': rep,
            'name': rep.get_full_name() or rep.username,
            'assigned_area': rep.assigned_areas.first(),
            'visits_total': rep_visits.count(),
            'visits_pending': rep_visits.filter(approval_status='pending').count(),
            'orders_total': rep_orders.count(),
            'orders_pending': rep_orders.filter(status='pending').count(),
            'sales_amount': rep_orders.filter(status__in=['manager_approval', 'in_preparation', 'delivered', 'invoiced']).aggregate(t=Sum('grand_total'))['t'] or 0,
            'collections_amount': rep_colls.aggregate(t=Sum('amount'))['t'] or 0,
            'last_active': rep_visits.aggregate(m=Max('date'))['m'],
        })

    # Recent pending items for fast review
    recent_pending_visits = visits_qs.filter(approval_status='pending').select_related('contact', 'owner', 'template').order_by('-date')[:6]
    recent_pending_orders = orders_qs.filter(status='pending').select_related('customer', 'created_by').order_by('-created_at')[:6]

    context = {
        'managed_areas': managed_areas,
        'governorates': governorates,
        'subareas': subareas,
        'selected_subregion': selected_subregion,
        'total_contacts': total_contacts,
        'total_reps': total_reps,
        'total_visits': total_visits,
        'pending_visits': pending_visits,
        'approved_visits': approved_visits,
        'total_orders_count': total_orders_count,
        'pending_orders': pending_orders,
        'approved_orders': approved_orders,
        'total_sales_value': total_sales_value,
        'total_collections_value': total_collections_value,
        'reps_data': reps_data,
        'recent_pending_visits': recent_pending_visits,
        'recent_pending_orders': recent_pending_orders,
    }
    return render(request, 'regional/regional_dashboard.html', context)
