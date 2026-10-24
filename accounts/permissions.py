from functools import wraps
from django.shortcuts import render, redirect
from django.contrib import messages
from django.http import JsonResponse, HttpResponseForbidden
from django.contrib.auth.mixins import AccessMixin
from django.db.models import Q


def has_perm_or_admin(user, perm_codename: str) -> bool:
    """
    Checks if a user has a specific permission codename,
    with SuperAdmin automatic override and module inheritance.
    """
    if not user.is_authenticated or not user.is_active:
        return False
    if user.is_superuser or getattr(user, 'is_super_admin', False):
        return True
    if isinstance(perm_codename, (list, tuple, set)):
        return any(has_perm_or_admin(user, p) for p in perm_codename)
    if hasattr(user, 'has_permission'):
        return user.has_permission(perm_codename)
    if user.role and user.role.is_active:
        return user.role.permissions.filter(codename=perm_codename).exists()
    return False


def can_user_access_module(user, module_key: str) -> bool:
    """
    Checks if a user has access to a top-level module (e.g. 'purchases', 'sales').
    """
    return has_perm_or_admin(user, f"module:{module_key}")


def is_ajax_or_api(request) -> bool:
    """Detects whether a request expects a JSON API response."""
    return (
        request.headers.get('x-requested-with') == 'XMLHttpRequest' or
        request.path.startswith('/api/') or
        'application/json' in request.headers.get('accept', '').lower()
    )


def render_forbidden_response(request, message: str = None, perm_codename: str = None):
    """Returns 403 response appropriate for AJAX/API or HTML browser requests."""
    if is_ajax_or_api(request):
        return JsonResponse({
            'error': 'PermissionDenied',
            'detail': message or f'عذراً، لا تمتلك الصلاحية الكافية ({perm_codename or "Denied"}) لتنفيذ هذا الإجراء.',
            'perm_codename': perm_codename or '',
        }, status=403)
    return render(request, '403.html', {'perm_codename': perm_codename, 'detail': message}, status=403)


def require_permission(perm_codename: str, redirect_url: str = None):
    """
    View decorator to enforce backend authorization.
    Rejects unauthorized access with:
    - HTTP 403 JSON response for API/AJAX requests.
    - HTTP 403 Forbidden rendered page (or redirect if redirect_url specified) for normal browser requests.
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if not request.user.is_authenticated:
                if is_ajax_or_api(request):
                    return JsonResponse({
                        'error': 'Unauthenticated',
                        'detail': 'يجب تسجيل الدخول أولاً للوصول إلى هذا المورد.'
                    }, status=401)
                return redirect(f"/login/?next={request.path}")

            if not request.user.is_active:
                if is_ajax_or_api(request):
                    return JsonResponse({
                        'error': 'InactiveAccount',
                        'detail': 'هذا الحساب معطل حالياً.'
                    }, status=403)
                messages.error(request, "هذا الحساب معطل حالياً. يرجى مراجعة إدارة النظام.")
                return redirect('login')

            if has_perm_or_admin(request.user, perm_codename):
                return view_func(request, *args, **kwargs)

            # Access Denied
            if redirect_url:
                messages.error(request, f"عذراً، لا تمتلك الصلاحية الكافية ({perm_codename}) للوصول إلى هذه الصفحة.")
                return redirect(redirect_url)

            return render_forbidden_response(request, perm_codename=perm_codename)

        return _wrapped_view
    return decorator


def require_super_admin(redirect_url: str = None):
    """
    Strict decorator reserving endpoints exclusively for SuperAdmin.
    Verifies actual superuser/superadmin status, preventing privilege escalation.
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if not request.user.is_authenticated:
                if is_ajax_or_api(request):
                    return JsonResponse({'error': 'Unauthenticated', 'detail': 'يرجى تسجيل الدخول أولاً.'}, status=401)
                return redirect(f"/login/?next={request.path}")

            if not getattr(request.user, 'is_super_admin', False):
                if is_ajax_or_api(request):
                    return JsonResponse({
                        'error': 'Forbidden',
                        'detail': 'هذا الإجراء مقصور حصرياً على مدراء النظام الأعلى (SuperAdmin).'
                    }, status=403)

                if redirect_url:
                    messages.error(request, "عذراً، هذه الصفحة مقصورة حصرياً على مدراء النظام الأعلى (SuperAdmin).")
                    return redirect(redirect_url)

                return render(request, '403.html', {
                    'perm_codename': 'SuperAdmin Privilege Required'
                }, status=403)

            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator


class RequirePermissionMixin(AccessMixin):
    """CBV mixin enforcing backend permissions."""
    required_permission = None

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()

        if self.required_permission and not has_perm_or_admin(request.user, self.required_permission):
            if is_ajax_or_api(request):
                return JsonResponse({
                    'error': 'PermissionDenied',
                    'detail': f'عذراً، لا تمتلك الصلاحية الكافية ({self.required_permission}).'
                }, status=403)
            return render(request, '403.html', {'perm_codename': self.required_permission}, status=403)

        return super().dispatch(request, *args, **kwargs)


class RequireSuperAdminMixin(AccessMixin):
    """CBV mixin strictly for SuperAdmin."""
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()

        if not getattr(request.user, 'is_super_admin', False):
            if is_ajax_or_api(request):
                return JsonResponse({'error': 'Forbidden', 'detail': 'مقصور على SuperAdmin.'}, status=403)
            return render(request, '403.html', {'perm_codename': 'SuperAdmin Privilege'}, status=403)

        return super().dispatch(request, *args, **kwargs)


# ==============================================================================
# ==============================================================================
# REGIONAL HIERARCHY & DATA ACCESS SCOPING (ABAC)
# ==============================================================================

def get_user_managed_areas(user):
    """
    Returns a QuerySet of all Area objects under the user's regional responsibility:
    - Superusers / SuperAdmins / Company Executives: all areas.
    - Area Managers (مدير منطقة رئيسية): The assigned parent region(s) PLUS all subareas
      (المنطقة الفرعية) that belong to those regions.
    - Sub-Area Managers: Their assigned subareas.
    - Representatives: Their assigned areas.
    """
    from master_data.models import Area
    if not user.is_authenticated or not user.is_active:
        return Area.objects.none()

    if getattr(user, 'is_super_admin', False) or user.is_superuser:
        return Area.objects.all()

    role = user.role
    if not role or not role.is_active:
        return Area.objects.none()

    if role.name in ['CEO', 'Admin']:
        return Area.objects.all()

    assigned_area_ids = list(user.assigned_areas.values_list('id', flat=True))
    if not assigned_area_ids:
        return Area.objects.none()

    # If user is an Area Manager or holds a managerial/supervisory role, expand to all subareas
    is_manager = (
        role.is_area_manager or
        role.is_sub_area_manager or
        any(kw in (role.name or '').lower() or kw in (role.display_name or '').lower()
            for kw in ['manager', 'director', 'supervisor', 'مدير', 'مشرف'])
    )

    if is_manager:
        # Include assigned areas, plus any subarea whose parent (or ancestor) is in assigned areas
        return Area.objects.filter(
            Q(id__in=assigned_area_ids) |
            Q(parent_id__in=assigned_area_ids) |
            Q(parent__parent_id__in=assigned_area_ids)
        ).distinct()

    return user.assigned_areas.all()


def get_user_managed_representatives(user):
    """
    Returns a QuerySet of all active User (representatives) who fall under the user's
    regional management scope:
    - A manager responsible for Region A is responsible for representatives assigned to
      Region A, plus representatives working in any subregion belonging to Region A.
    - SuperAdmin / Executive: all active users.
    - Representatives: only themselves.
    """
    from django.contrib.auth import get_user_model
    UserModel = get_user_model()

    if not user.is_authenticated or not user.is_active:
        return UserModel.objects.none()

    if getattr(user, 'is_super_admin', False) or user.is_superuser:
        return UserModel.objects.filter(is_active=True)

    role = user.role
    if not role or not role.is_active:
        return UserModel.objects.none()

    if role.name in ['CEO', 'Admin']:
        return UserModel.objects.filter(is_active=True)

    # Standard representative only manages themselves
    if role.is_rep and not role.is_area_manager:
        return UserModel.objects.filter(pk=user.pk)

    managed_areas = get_user_managed_areas(user)
    if not managed_areas.exists():
        return UserModel.objects.filter(pk=user.pk)

    # Representatives assigned to any of the manager's managed regions/subregions
    return UserModel.objects.filter(
        Q(assigned_areas__in=managed_areas) | Q(id=user.id)
    ).filter(is_active=True).distinct()


def get_scoped_queryset(queryset, user, model_name: str = None):
    """
    Filters QuerySet based on user role, regional hierarchy, area assignment, and ownership rules:
    - SuperAdmin / Executive CEO: sees company-wide dataset.
    - Area Manager: sees records belonging to their region, all its subregions, and assigned reps.
    - Sub-Area Manager: sees records in assigned subareas and assigned reps.
    - Representative (Rep): sees records they created/own, or contacts in assigned areas.
    """
    if not user.is_authenticated:
        return queryset.none()

    if getattr(user, 'is_super_admin', False) or user.is_superuser:
        return queryset

    role = user.role
    if not role or not role.is_active:
        return queryset.none()

    # Executive roles see company-wide records
    if role.name in ['CEO', 'Admin']:
        return queryset

    model = queryset.model
    m_name = (model_name or model.__name__).lower()

    managed_areas = get_user_managed_areas(user)
    managed_reps = get_user_managed_representatives(user)

    # 1. Activities: Visit
    if m_name == 'visit':
        if role.is_rep and not role.is_area_manager:
            return queryset.filter(Q(owner=user) | Q(created_by=user))
        return queryset.filter(
            Q(owner__in=managed_reps) |
            Q(created_by__in=managed_reps) |
            Q(contact__area__in=managed_areas)
        ).distinct()

    # 2. Activities: PlannedVisitDay
    elif m_name == 'plannedvisitday':
        if role.is_rep and not role.is_area_manager:
            return queryset.filter(assignee=user)
        return queryset.filter(
            Q(assignee__in=managed_reps) |
            Q(assignee__assigned_areas__in=managed_areas)
        ).distinct()

    # 3. Activities: Agreement
    elif m_name == 'agreement':
        if role.is_rep and not role.is_area_manager:
            return queryset.filter(Q(created_by=user) | Q(customer__area__in=managed_areas))
        return queryset.filter(
            Q(created_by__in=managed_reps) |
            Q(customer__area__in=managed_areas)
        ).distinct()

    # 4. Contacts: Contact
    elif m_name == 'contact':
        if role.is_rep and not role.is_area_manager:
            return queryset.filter(Q(created_by=user) | Q(assigned_team=user) | Q(area__in=managed_areas)).distinct()
        return queryset.filter(
            Q(created_by__in=managed_reps) |
            Q(assigned_team__in=managed_reps) |
            Q(area__in=managed_areas)
        ).distinct()

    # 5. Sales: SalesOrder
    elif m_name == 'salesorder':
        if role.is_rep and not role.is_area_manager:
            return queryset.filter(Q(created_by=user) | Q(customer__area__in=managed_areas))
        return queryset.filter(
            Q(created_by__in=managed_reps) |
            Q(customer__area__in=managed_areas)
        ).distinct()

    # 6. Sales: Collection
    elif m_name == 'collection':
        if role.is_rep and not role.is_area_manager:
            return queryset.filter(Q(created_by=user) | Q(customer__area__in=managed_areas))
        return queryset.filter(
            Q(created_by__in=managed_reps) |
            Q(customer__area__in=managed_areas)
        ).distinct()

    # 7. Sales: CustomerAccount
    elif m_name == 'customeraccount':
        return queryset.filter(customer__area__in=managed_areas).distinct()

    # 8. Treasury: Vault
    elif m_name == 'vault':
        if role.is_rep or not role.can_hold_vault:
            return queryset.filter(assigned_user=user)

    return queryset


def can_user_access_object(user, obj, action: str = 'view') -> bool:
    """
    Object-level security checker protecting against IDOR, BOLA, and privilege escalation.
    Enforces:
    1. SuperAdmin / Superuser company-wide access.
    2. Regional hierarchy: Area Manager has authority over Region + all Subregions + Reps.
    3. Self-approval restriction: Reps cannot approve or reject their own submissions.
    4. Cross-region access rejection: Managers cannot view or alter records from other regions.
    """
    if not user.is_authenticated:
        return False

    if getattr(user, 'is_super_admin', False) or user.is_superuser:
        return True

    role = user.role
    if not role or not role.is_active:
        return False

    if role.name in ['CEO', 'Admin']:
        return True

    # Approval integrity rule: representative cannot approve/reject their own submission
    if action in ['approve', 'reject', 'disapprove']:
        owner_id = getattr(obj, 'owner_id', None) or getattr(obj, 'created_by_id', None)
        if owner_id == user.id:
            return False

    managed_areas = set(get_user_managed_areas(user).values_list('id', flat=True))
    managed_rep_ids = set(get_user_managed_representatives(user).values_list('id', flat=True))

    model_name = obj.__class__.__name__.lower()

    if model_name == 'visit':
        if role.is_rep and not role.is_area_manager:
            return obj.owner_id == user.id or obj.created_by_id == user.id

        # Manager authority over visit: either rep belongs to managed reps, or contact is in managed areas
        rep_authorized = (obj.owner_id in managed_rep_ids or obj.created_by_id in managed_rep_ids)
        area_authorized = getattr(obj.contact, 'area_id', None) in managed_areas
        return rep_authorized or area_authorized

    elif model_name == 'agreement':
        if role.is_rep and not role.is_area_manager:
            if action in ['edit', 'delete']:
                if obj.status in ['approved', 'done']:
                    return False
            return obj.created_by_id == user.id or getattr(obj.customer, 'area_id', None) in managed_areas
        return (obj.created_by_id in managed_rep_ids) or (getattr(obj.customer, 'area_id', None) in managed_areas)

    elif model_name == 'contact':
        if role.is_rep and not role.is_area_manager:
            return obj.created_by_id == user.id or obj.area_id in managed_areas or obj.assigned_team.filter(id=user.id).exists()
        return (obj.area_id in managed_areas) or (obj.created_by_id in managed_rep_ids) or (obj.assigned_team.filter(id__in=managed_rep_ids).exists())

    elif model_name == 'salesorder':
        if role.is_rep and not role.is_area_manager:
            return obj.created_by_id == user.id or getattr(obj.customer, 'area_id', None) in managed_areas
        return (obj.created_by_id in managed_rep_ids) or (getattr(obj.customer, 'area_id', None) in managed_areas)

    elif model_name == 'collection':
        if role.is_rep and not role.is_area_manager:
            return obj.created_by_id == user.id or getattr(obj.customer, 'area_id', None) in managed_areas
        return (obj.created_by_id in managed_rep_ids) or (getattr(obj.customer, 'area_id', None) in managed_areas)

    elif model_name == 'vault':
        if role.is_rep:
            return obj.assigned_user_id == user.id

    return True

