from functools import wraps
from django.shortcuts import render, redirect
from django.contrib import messages
from django.http import JsonResponse, HttpResponseForbidden
from django.contrib.auth.mixins import AccessMixin
from django.db.models import Q


def is_manager_or_higher(user) -> bool:
    """
    Returns True if user is a manager or higher:
    - Superuser or SuperAdmin
    - Role marked is_manager_role, is_super, is_area_manager, or is_sub_area_manager
    - Configured with 'area' or 'all' management scope in activities or contacts
    """
    if not user or not user.is_authenticated or not user.is_active:
        return False
    if user.is_superuser or getattr(user, 'is_super_admin', False):
        return True
    role = getattr(user, 'role', None)
    if not role or not role.is_active:
        return False
    if getattr(role, 'is_manager_role', False) or getattr(role, 'is_super', False) or getattr(role, 'is_area_manager', False) or getattr(role, 'is_sub_area_manager', False):
        return True
    from accounts.scope_service import ScopeResolutionService
    if ScopeResolutionService.get_user_scope(user, 'activities', 'manage') in ['area', 'all']:
        return True
    name_l = (role.name or '').lower()
    disp_l = (role.display_name or '').lower()
    if name_l in ['ceo', 'admin', 'superadmin', 'manager', 'area_manager', 'sub_area_manager', 'purchasingmanager']:
        return True
    return any(k in name_l or k in disp_l for k in ['manager', 'director', 'supervisor', 'مدير', 'مشرف', 'رئيس'])


def has_perm_or_admin(user, perm_codename: str) -> bool:
    """
    Checks if a user has a specific permission codename,
    with SuperAdmin automatic override and module inheritance.
    When a user has custom permissions (has_custom_permissions=True),
    their user-level permissions strictly and exclusively govern access
    without settings-level bypasses (100% user-level authority).
    """
    if not user or not user.is_authenticated or not user.is_active:
        return False
    if user.is_superuser or getattr(user, 'is_super_admin', False):
        return True
    if isinstance(perm_codename, (list, tuple, set)):
        return any(has_perm_or_admin(user, p) for p in perm_codename)

    # Normalize redundant alias codenames for single source of truth
    if perm_codename == 'treasury:vaults/transactions':
        perm_codename = 'treasury:transactions/list'

    # 1. If user has custom permissions configured directly,
    # those direct user permissions are 100% authoritative (no settings bypass).
    if getattr(user, 'has_custom_permissions', False):
        if hasattr(user, 'has_permission'):
            return user.has_permission(perm_codename)
        return False

    # 2. Check user's effective permissions (enforces module-level inheritance)
    if hasattr(user, 'has_permission') and user.has_permission(perm_codename):
        return True

    # 3. Dynamic settings flags apply only to non-custom role users when enabled
    if perm_codename in ('activities:visits/create', 'activities:visits/view'):
        from master_data.models import LocationSettings
        loc_settings = LocationSettings.get_settings()
        if getattr(loc_settings, 'allow_all_users_to_create_visits', False):
            return True

    if perm_codename in ('activities:agreements/create', 'activities:agreements/view'):
        from master_data.models import LocationSettings
        loc_settings = LocationSettings.get_settings()
        if getattr(loc_settings, 'allow_all_users_to_create_agreements', False):
            return True

    if perm_codename in ('sales:orders/create', 'sales:orders/view'):
        from master_data.models import SalesSettings
        sales_settings = SalesSettings.get_settings()
        if getattr(sales_settings, 'allow_all_users_to_create', False):
            return True

    if perm_codename in ('purchases:orders/create', 'purchases:orders/view'):
        from master_data.models import PurchaseSettings
        pur_settings = PurchaseSettings.get_settings()
        if getattr(pur_settings, 'allow_all_users_to_create', False):
            return True

    return False


def can_user_access_module(user, module_key: str) -> bool:
    """
    Checks if a user has access to a top-level module (e.g. 'purchases', 'sales').
    Strictly enforced via module root permission (e.g. 'module:sales').
    Settings-level shortcuts only apply to default role-based users when enabled.
    """
    if has_perm_or_admin(user, f"module:{module_key}"):
        return True

    if not getattr(user, 'has_custom_permissions', False):
        if module_key == 'activities':
            from master_data.models import LocationSettings
            loc_settings = LocationSettings.get_settings()
            if getattr(loc_settings, 'allow_all_users_to_create_visits', False) or getattr(loc_settings, 'allow_all_users_to_create_agreements', False):
                return True

        if module_key == 'sales':
            from master_data.models import SalesSettings
            sales_settings = SalesSettings.get_settings()
            if getattr(sales_settings, 'allow_all_users_to_create', False):
                return True

        if module_key == 'purchases':
            from master_data.models import PurchaseSettings
            pur_settings = PurchaseSettings.get_settings()
            if getattr(pur_settings, 'allow_all_users_to_create', False):
                return True

    return False


def is_ajax_or_api(request) -> bool:
    """Detects whether a request expects a JSON API response."""
    return (
        request.headers.get('x-requested-with') == 'XMLHttpRequest' or
        request.path.startswith('/api/') or
        '/api/' in request.path or
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


def require_permission(perm_codename, redirect_url: str = None):
    """
    View decorator to enforce backend authorization.
    Accepts either a single codename string or an iterable of acceptable codenames (OR logic).
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

            codenames = [perm_codename] if isinstance(perm_codename, str) else list(perm_codename)
            if any(has_perm_or_admin(request.user, c) for c in codenames):
                return view_func(request, *args, **kwargs)

            # Access Denied
            perm_str = " أو ".join(codenames)
            if redirect_url:
                messages.error(request, f"عذراً، لا تمتلك الصلاحية الكافية ({perm_str}) للوصول إلى هذه الصفحة.")
                return redirect(redirect_url)

            return render_forbidden_response(request, perm_codename=perm_str)

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
# CANONICAL AREA TRAVERSAL & MAIN AREA RESOLUTION
# ==============================================================================

def get_main_area(area):
    """
    Returns the canonical root main area (e.g. Governorate) for an Area.
    Traverses parent relationships up to the top-level parent (parent is None).
    """
    from accounts.scope_service import ScopeResolutionService
    return ScopeResolutionService.get_main_area(area)


def get_user_main_areas(user):
    """
    Returns a distinct QuerySet of canonical root Area objects (Main Areas / Governorates)
    assigned to this user.
    """
    from accounts.scope_service import ScopeResolutionService
    return ScopeResolutionService.get_user_main_areas(user)


def is_accountant(user) -> bool:
    """
    Returns True if user is an accountant, bookkeeper, or financial administrator.
    """
    if not user or not user.is_authenticated or not user.is_active:
        return False
    if user.is_superuser or getattr(user, 'is_super_admin', False):
        return True
    role = getattr(user, 'role', None)
    if not role or not role.is_active:
        return False
    if has_perm_or_admin(user, 'module:treasury') and has_perm_or_admin(user, 'treasury:transactions/list'):
        return True
    name_l = (role.name or '').lower()
    disp_l = (role.display_name or '').lower()
    return 'accountant' in name_l or 'bookkeeper' in name_l or 'محاسب' in disp_l or 'حسابات' in disp_l


def is_representative(user) -> bool:
    """
    Returns True if user is a sales representative or medical representative.
    """
    if not user or not user.is_authenticated or not user.is_active:
        return False
    if user.is_superuser or getattr(user, 'is_super_admin', False):
        return False
    role = getattr(user, 'role', None)
    if not role or not role.is_active:
        return False
    if getattr(role, 'is_rep', False):
        return True
    name_l = (role.name or '').lower()
    disp_l = (role.display_name or '').lower()
    return name_l in ['rep', 'medical_rep'] or 'rep' in name_l or 'مندوب' in disp_l


def is_rep(user) -> bool:
    """Returns True specifically if user is a standard sales representative ('rep')."""
    if not user or not user.is_authenticated or not user.is_active:
        return False
    if user.is_superuser or getattr(user, 'is_super_admin', False):
        return False
    role = getattr(user, 'role', None)
    if not role or not role.is_active:
        return False
    name_l = (role.name or '').lower()
    return name_l == 'rep' or (getattr(role, 'is_rep', False) and name_l != 'medical_rep')


def is_medical_rep(user) -> bool:
    """Returns True specifically if user is a medical representative ('medical_rep')."""
    if not user or not user.is_authenticated or not user.is_active:
        return False
    if user.is_superuser or getattr(user, 'is_super_admin', False):
        return False
    role = getattr(user, 'role', None)
    if not role or not role.is_active:
        return False
    name_l = (role.name or '').lower()
    return name_l == 'medical_rep'


def is_manager_eligible_for_user(manager, target_user) -> bool:
    """
    Standardized eligibility check:
    Delegates to ScopeResolutionService.is_manager_eligible_for_user.
    """
    from accounts.scope_service import ScopeResolutionService
    return ScopeResolutionService.is_manager_eligible_for_user(manager, target_user)


def is_manager_eligible_for_area(manager, area) -> bool:
    """
    Checks if a manager is eligible for a given Area (governorate or subarea).
    Delegates to ScopeResolutionService.is_manager_eligible_for_area.
    """
    from accounts.scope_service import ScopeResolutionService
    return ScopeResolutionService.is_manager_eligible_for_area(manager, area)


def get_user_managed_areas(user, scope: str = 'area'):
    """
    Returns a QuerySet of all Area objects under the user's regional responsibility.
    Delegates to ScopeResolutionService.get_user_managed_areas.
    """
    from accounts.scope_service import ScopeResolutionService
    return ScopeResolutionService.get_user_managed_areas(user, scope=scope)


def get_visit_eligible_contacts_queryset(queryset, user):
    """
    Filters Contact queryset for Visit creation, Planned Visit scheduling, and Visit client pickers
    strictly according to configurable scoping.
    Delegates to ScopeResolutionService.get_scoped_queryset.
    """
    from accounts.scope_service import ScopeResolutionService
    return ScopeResolutionService.get_scoped_queryset(queryset, user, 'contact', 'view')


def can_user_access_contact_for_visit(user, contact) -> bool:
    """
    Checks whether `user` is geographically authorized to create or access a visit for `contact`.
    """
    if not user or not user.is_authenticated or not user.is_active or not contact:
        return False
    if getattr(user, 'is_super_admin', False) or user.is_superuser:
        return True
    from contacts.models import Contact
    return get_visit_eligible_contacts_queryset(
        Contact.objects.filter(pk=contact.pk),
        user
    ).exists()


def get_user_managed_representatives(user, module: str = 'accounts'):
    """
    Returns a QuerySet of all active User (representatives/subordinates) under user's scope.
    Delegates to ScopeResolutionService.get_user_managed_subordinates.
    """
    from accounts.scope_service import ScopeResolutionService
    return ScopeResolutionService.get_user_managed_subordinates(user, module=module)


def get_scoped_queryset(queryset, user, model_name: str = None, scope_type: str = 'view'):
    """
    Filters QuerySet based on configurable module data scopes (OWN, BRICK, AREA, ALL).
    Delegates to ScopeResolutionService.get_scoped_queryset.
    """
    from accounts.scope_service import ScopeResolutionService
    return ScopeResolutionService.get_scoped_queryset(queryset, user, model_name=model_name, scope_type=scope_type)


def can_user_access_object(user, obj, action: str = 'view') -> bool:
    """
    Object-level security checker protecting against IDOR, BOLA, and privilege escalation.
    Delegates to ScopeResolutionService.can_user_access_object.
    """
    from accounts.scope_service import ScopeResolutionService
    return ScopeResolutionService.can_user_access_object(user, obj, action=action)


def can_user_perform_stock_in(user, warehouse=None) -> bool:
    """Checks if user has permission to create a Stock In memo for the given warehouse."""
    if not user or not user.is_authenticated:
        return False
    if getattr(user, 'is_super_admin', False) or user.is_superuser:
        return True
    role = getattr(user, 'role', None)
    if role and (role.is_super or role.name in ['superadmin', 'SuperAdmin', 'CEO', 'Admin']):
        return True
    if is_accountant(user):
        if warehouse:
            return can_user_access_object(user, warehouse, 'operate')
        return True

    from master_data.models import CompanyProfile
    profile = CompanyProfile.get_settings()
    configured_roles = profile.roles_can_stock_in.all()

    if configured_roles.exists():
        if not (role and role.is_active and configured_roles.filter(id=role.id).exists()):
            return False
    else:
        if not has_perm_or_admin(user, 'inventory:memos/manage') and not is_manager_or_higher(user):
            return False

    if warehouse:
        return can_user_access_object(user, warehouse, 'operate')
    return True


def can_user_perform_stock_out(user, warehouse=None) -> bool:
    """Checks if user has permission to create a Stock Out memo from the given warehouse."""
    if not user or not user.is_authenticated:
        return False
    if getattr(user, 'is_super_admin', False) or user.is_superuser:
        return True
    role = getattr(user, 'role', None)
    if role and (role.is_super or role.name in ['superadmin', 'SuperAdmin', 'CEO', 'Admin']):
        return True
    if is_accountant(user):
        if warehouse:
            return can_user_access_object(user, warehouse, 'operate')
        return True

    from master_data.models import CompanyProfile
    profile = CompanyProfile.get_settings()
    configured_roles = profile.roles_can_stock_out.all()

    if configured_roles.exists():
        if not (role and role.is_active and configured_roles.filter(id=role.id).exists()):
            return False
    else:
        if not has_perm_or_admin(user, 'inventory:memos/manage') and not is_manager_or_higher(user):
            return False

    if warehouse:
        return can_user_access_object(user, warehouse, 'operate')
    return True


def can_user_perform_transfer(user, source_warehouse=None, dest_warehouse=None) -> bool:
    """Checks if user has permission to request/execute warehouse transfers."""
    if not user or not user.is_authenticated:
        return False
    if getattr(user, 'is_super_admin', False) or user.is_superuser:
        return True
    role = getattr(user, 'role', None)
    if role and (role.is_super or role.name in ['superadmin', 'SuperAdmin', 'CEO', 'Admin']):
        return True
    if is_accountant(user):
        return True

    from master_data.models import CompanyProfile
    profile = CompanyProfile.get_settings()
    configured_roles = profile.roles_can_transfer.all()

    if configured_roles.exists():
        if not (role and role.is_active and configured_roles.filter(id=role.id).exists()):
            return False

    if dest_warehouse:
        if dest_warehouse.assigned_user_id == user.id:
            pass  # Rep requesting into own warehouse
        elif is_manager_or_higher(user):
            rep = dest_warehouse.assigned_user
            if rep and not is_manager_eligible_for_user(user, rep):
                return False
        elif not has_perm_or_admin(user, ['inventory:transfers/approve', 'inventory:transfers/manage']):
            return False

    return True

