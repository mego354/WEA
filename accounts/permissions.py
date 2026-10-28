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
    - CEO or Admin
    - Role marked is_manager_role, is_super, is_area_manager, or is_sub_area_manager
    - Role name or display name indicating managerial rank (manager, director, supervisor, etc.)
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser or getattr(user, 'is_super_admin', False):
        return True
    role = getattr(user, 'role', None)
    if not role or not role.is_active:
        return False
    if getattr(role, 'is_manager_role', False) or getattr(role, 'is_super', False) or getattr(role, 'is_area_manager', False) or getattr(role, 'is_sub_area_manager', False):
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
    Also honors settings-controlled universal access for visits, sales, purchases, and agreements.
    """
    if not user.is_authenticated or not user.is_active:
        return False
    if user.is_superuser or getattr(user, 'is_super_admin', False):
        return True
    if isinstance(perm_codename, (list, tuple, set)):
        return any(has_perm_or_admin(user, p) for p in perm_codename)

    # Check settings-controlled universal creation access
    try:
        from master_data.models import LocationSettings, SalesSettings, PurchaseSettings
        if perm_codename in ['activities:visits/create', 'activities:visits/view', 'activities:visits/list', 'activities:planned/list', 'activities:planned/manage']:
            if LocationSettings.get_settings().allow_all_users_to_create_visits:
                return True
        if perm_codename in ['activities:agreements/create', 'activities:agreements/view', 'activities:agreements/list']:
            if LocationSettings.get_settings().allow_all_users_to_create_agreements:
                return True
        if perm_codename in ['sales:orders/create', 'sales:orders/view', 'sales:orders/list']:
            if SalesSettings.get_settings().allow_all_users_to_create:
                return True
        if perm_codename in ['purchases:orders/create', 'purchases:orders/view', 'purchases:orders/list']:
            if PurchaseSettings.get_settings().allow_all_users_to_create:
                return True
    except Exception:
        pass

    if hasattr(user, 'has_permission'):
        return user.has_permission(perm_codename)
    if user.role and user.role.is_active:
        return user.role.permissions.filter(codename=perm_codename).exists()
    return False


def can_user_access_module(user, module_key: str) -> bool:
    """
    Checks if a user has access to a top-level module (e.g. 'purchases', 'sales').
    """
    if has_perm_or_admin(user, f"module:{module_key}"):
        return True
    try:
        from master_data.models import LocationSettings, SalesSettings, PurchaseSettings
        if module_key == 'activities' and (LocationSettings.get_settings().allow_all_users_to_create_visits or LocationSettings.get_settings().allow_all_users_to_create_agreements):
            return True
        if module_key == 'sales' and SalesSettings.get_settings().allow_all_users_to_create:
            return True
        if module_key == 'purchases' and PurchaseSettings.get_settings().allow_all_users_to_create:
            return True
    except Exception:
        pass
    return False


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
    Fails safely and returns None if area is None.
    """
    if not area:
        return None
    curr = area
    while getattr(curr, 'parent_id', None):
        curr = curr.parent
    return curr


def get_user_main_areas(user):
    """
    Returns a distinct QuerySet of canonical root Area objects (Main Areas / Governorates)
    assigned to this user.
    """
    from master_data.models import Area
    if not user or not user.is_authenticated or not user.is_active:
        return Area.objects.none()

    if getattr(user, 'is_super_admin', False) or user.is_superuser:
        return Area.objects.filter(parent__isnull=True)

    assigned_areas = user.assigned_areas.all()
    if not assigned_areas.exists():
        return Area.objects.none()

    main_area_ids = set()
    for a in assigned_areas:
        root = get_main_area(a)
        if root:
            main_area_ids.add(root.id)

    return Area.objects.filter(id__in=main_area_ids)


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
    return name_l == 'rep' or getattr(role, 'is_rep', False) and name_l != 'medical_rep'


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
    A representative's eligible manager is ANY authorized manager assigned to the SAME MAIN AREA.
    Secondary / sub-area equality is NOT required.

    Rules:
    - SuperAdmin / Executive CEO has system-wide eligibility.
    - Anti-self-approval: manager cannot manage or approve their own operations.
    - Must be a manager or higher: is_manager_or_higher(manager).
    - If either manager or target_user has no main areas assigned, fails securely (returns False).
    - Checks intersection of manager's root main areas and target_user's root main areas.
    """
    if not manager or not manager.is_authenticated or not manager.is_active:
        return False
    if not target_user or not target_user.is_authenticated:
        return False

    # Anti-self-approval
    if manager.id == target_user.id:
        return False

    # SuperAdmin / Executive override
    if getattr(manager, 'is_super_admin', False) or manager.is_superuser:
        return True

    role = getattr(manager, 'role', None)
    if role and role.is_active and (role.is_super or role.name in ['superadmin', 'SuperAdmin', 'CEO', 'Admin']):
        return True

    # Must be a manager
    if not is_manager_or_higher(manager):
        return False

    mgr_main_area_ids = set(get_user_main_areas(manager).values_list('id', flat=True))
    if not mgr_main_area_ids:
        return False

    target_main_area_ids = set(get_user_main_areas(target_user).values_list('id', flat=True))
    if not target_main_area_ids:
        return False

    return bool(mgr_main_area_ids & target_main_area_ids)


def is_manager_eligible_for_area(manager, area) -> bool:
    """
    Checks if a manager is eligible for a given Area (governorate or subarea).
    Matches based on canonical root main area.
    """
    if not manager or not manager.is_authenticated or not manager.is_active:
        return False
    if not area:
        return False

    if getattr(manager, 'is_super_admin', False) or manager.is_superuser:
        return True

    role = getattr(manager, 'role', None)
    if role and role.is_active and (role.is_super or role.name in ['superadmin', 'SuperAdmin', 'CEO', 'Admin']):
        return True

    if not is_manager_or_higher(manager):
        return False

    root = get_main_area(area)
    if not root:
        return False

    mgr_main_area_ids = set(get_user_main_areas(manager).values_list('id', flat=True))
    return root.id in mgr_main_area_ids


# ==============================================================================
# REGIONAL HIERARCHY & DATA ACCESS SCOPING (ABAC)
# ==============================================================================

def get_user_managed_areas(user):
    """
    Returns a QuerySet of all Area objects under the user's regional responsibility:
    - Superusers / SuperAdmins / Company Executives: all areas.
    - Managers: ALL areas (root main areas PLUS all their subareas) under the manager's assigned main areas.
    - Representatives & staff: assigned areas and sibling subareas under same governorate.
    """
    from master_data.models import Area
    if not user.is_authenticated or not user.is_active:
        return Area.objects.none()

    if getattr(user, 'is_super_admin', False) or user.is_superuser:
        return Area.objects.all()

    role = user.role
    if not role or not role.is_active:
        return Area.objects.none()

    if role.is_super or role.name in ['superadmin', 'SuperAdmin', 'CEO', 'Admin']:
        return Area.objects.all()

    assigned_area_ids = list(user.assigned_areas.values_list('id', flat=True))
    if not assigned_area_ids:
        return Area.objects.none()

    if is_manager_or_higher(user):
        # Resolve all root main areas for this manager
        main_area_ids = set(get_user_main_areas(user).values_list('id', flat=True))
        if not main_area_ids:
            return Area.objects.none()
        # Manager has oversight over the root area PLUS all subareas whose root is this main area
        return Area.objects.filter(
            Q(id__in=main_area_ids) |
            Q(parent_id__in=main_area_ids) |
            Q(parent__parent_id__in=main_area_ids)
        ).distinct()

    # Representatives & staff
    parent_ids = list(user.assigned_areas.filter(parent__isnull=False).values_list('parent_id', flat=True))
    return Area.objects.filter(
        Q(id__in=assigned_area_ids) |
        Q(parent_id__in=assigned_area_ids) |
        Q(parent_id__in=parent_ids)
    ).distinct()


def get_user_managed_representatives(user):
    """
    Returns a QuerySet of all active User (representatives) who fall under the user's
    regional management scope:
    - SuperAdmin / Executive: all active users.
    - Manager: all active representatives whose assigned areas share the SAME MAIN AREA
      (root governorate) as the manager.
    - Representative: only themselves.
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

    if role.is_super or role.name in ['superadmin', 'SuperAdmin', 'CEO', 'Admin']:
        return UserModel.objects.filter(is_active=True)

    if not is_manager_or_higher(user):
        return UserModel.objects.filter(pk=user.pk)

    managed_areas = get_user_managed_areas(user)
    if not managed_areas.exists():
        return UserModel.objects.none()

    # Representatives assigned to any of the manager's managed main regions or subregions
    return UserModel.objects.filter(
        Q(assigned_areas__in=managed_areas) | Q(id=user.id)
    ).filter(is_active=True).distinct()


def get_scoped_queryset(queryset, user, model_name: str = None):
    """
    Filters QuerySet based on user role, regional hierarchy, area assignment, and ownership rules:
    - SuperAdmin: global unrestricted visibility.
    - Accountant: broad visibility across financial, sales, purchases, treasury, and inventory records.
    - Manager: records of representatives within the manager's same main area (regardless of sub-area differences).
    - Rep: strictly own created / assigned records (no cross-rep access within the same area).
    - Medical rep: strictly own created / assigned records, plus legitimate shared contact/product access.
    """
    if not user.is_authenticated:
        return queryset.none()

    if getattr(user, 'is_super_admin', False) or user.is_superuser:
        return queryset

    role = user.role
    if not role or not role.is_active:
        return queryset.none()

    # Executive roles see company-wide records
    if role.is_super or role.name in ['superadmin', 'SuperAdmin', 'CEO', 'Admin']:
        return queryset

    model = queryset.model
    m_name = (model_name or model.__name__).lower()

    managed_areas = get_user_managed_areas(user)
    managed_reps = get_user_managed_representatives(user)

    # 1. Activities: Visit
    if m_name == 'visit':
        if not is_manager_or_higher(user):
            return queryset.filter(Q(owner=user) | Q(created_by=user))
        return queryset.filter(
            Q(owner__in=managed_reps) |
            Q(created_by__in=managed_reps)
        ).distinct()

    # 2. Activities: PlannedVisitDay
    elif m_name == 'plannedvisitday':
        if not is_manager_or_higher(user):
            return queryset.filter(assignee=user)
        return queryset.filter(assignee__in=managed_reps).distinct()

    # 3. Activities: Agreement
    elif m_name == 'agreement':
        if is_accountant(user):
            return queryset
        if not is_manager_or_higher(user):
            return queryset.filter(created_by=user)
        return queryset.filter(created_by__in=managed_reps).distinct()

    # 4. Contacts: Contact
    elif m_name == 'contact':
        if is_accountant(user):
            return queryset
        if not is_manager_or_higher(user):
            if is_medical_rep(user):
                return queryset.filter(
                    Q(created_by=user) | Q(assigned_team=user) | Q(activities__performed_by=user)
                ).distinct()
            return queryset.filter(
                Q(created_by=user) | Q(assigned_team=user)
            ).distinct()
        return queryset.filter(
            Q(area__in=managed_areas) |
            Q(created_by__in=managed_reps) |
            Q(assigned_team__in=managed_reps)
        ).distinct()

    # 5. Sales: SalesOrder & SalesReturnOrder
    elif m_name in ['salesorder', 'salesreturnorder']:
        if is_accountant(user):
            return queryset
        if not is_manager_or_higher(user):
            return queryset.filter(created_by=user)
        return queryset.filter(created_by__in=managed_reps).distinct()

    # 6. Sales: Collection
    elif m_name == 'collection':
        if is_accountant(user):
            return queryset
        if not is_manager_or_higher(user):
            return queryset.filter(created_by=user)
        return queryset.filter(created_by__in=managed_reps).distinct()

    # 7. Sales: CustomerAccount
    elif m_name == 'customeraccount':
        if is_accountant(user):
            return queryset
        if not is_manager_or_higher(user):
            scoped_contacts = get_scoped_queryset(Contact.objects.all(), user, 'contact')
            return queryset.filter(customer__in=scoped_contacts).distinct()
        return queryset.filter(
            Q(customer__area__in=managed_areas) |
            Q(customer__created_by__in=managed_reps) |
            Q(customer__assigned_team__in=managed_reps)
        ).distinct()

    # 8. Purchases: PurchaseOrder & PurchaseReturnOrder
    elif m_name in ['purchaseorder', 'purchasereturnorder']:
        if is_accountant(user):
            return queryset
        if not is_manager_or_higher(user):
            return queryset.filter(created_by=user)
        return queryset.filter(
            Q(created_by__in=managed_reps) |
            Q(target_warehouse__assigned_user__in=managed_reps) |
            Q(target_warehouse__area__in=managed_areas)
        ).distinct()

    # 9. Inventory: Warehouse
    elif m_name == 'warehouse':
        if is_accountant(user):
            return queryset
        if not is_manager_or_higher(user):
            return queryset.filter(Q(assigned_user=user) | Q(is_main=True))
        # Manager sees main warehouses, plus rep warehouses belonging to reps in their main area,
        # plus warehouses geographically located in their managed areas
        return queryset.filter(
            Q(is_main=True) |
            Q(assigned_user__in=managed_reps) |
            Q(area__in=managed_areas)
        ).distinct()

    # 10. Inventory: InventoryStock
    elif m_name == 'inventorystock':
        if is_accountant(user):
            return queryset
        from inventory.models import Warehouse
        scoped_warehouses = get_scoped_queryset(Warehouse.objects.all(), user, 'warehouse')
        return queryset.filter(warehouse__in=scoped_warehouses)

    # 11. Inventory: InventoryMemo
    elif m_name == 'inventorymemo':
        if is_accountant(user):
            return queryset
        from inventory.models import Warehouse
        scoped_warehouses = get_scoped_queryset(Warehouse.objects.all(), user, 'warehouse')
        return queryset.filter(warehouse__in=scoped_warehouses)

    # 12. Inventory: ProductTransferRequest
    elif m_name == 'producttransferrequest':
        if is_accountant(user):
            return queryset
        if not is_manager_or_higher(user):
            return queryset.filter(
                Q(requesting_user=user) |
                Q(source_warehouse__assigned_user=user) |
                Q(destination_warehouse__assigned_user=user)
            ).distinct()
        # Manager sees requests where requester or either warehouse belongs to managed reps
        return queryset.filter(
            Q(requesting_user__in=managed_reps) |
            Q(source_warehouse__assigned_user__in=managed_reps) |
            Q(destination_warehouse__assigned_user__in=managed_reps) |
            Q(source_warehouse__area__in=managed_areas) |
            Q(destination_warehouse__area__in=managed_areas)
        ).distinct()

    # 13. Treasury: Vault
    elif m_name == 'vault':
        if is_accountant(user):
            return queryset
        if not is_manager_or_higher(user):
            return queryset.filter(assigned_user=user)
        # Manager sees vaults of reps in their managed scope or assigned to themselves
        return queryset.filter(
            Q(assigned_user=user) |
            Q(assigned_user__in=managed_reps)
        ).distinct()

    # 14. Treasury: VaultTransaction
    elif m_name == 'vaulttransaction':
        if is_accountant(user):
            return queryset
        from treasury.models import Vault
        scoped_vaults = get_scoped_queryset(Vault.objects.all(), user, 'vault')
        return queryset.filter(vault__in=scoped_vaults)

    # 15. Treasury: VendorPayment
    elif m_name == 'vendorpayment':
        if is_accountant(user):
            return queryset
        if not is_manager_or_higher(user):
            return queryset.filter(created_by=user)
        return queryset.filter(created_by__in=managed_reps).distinct()

    # 16. Treasury: VendorTransaction
    elif m_name == 'vendortransaction':
        if is_accountant(user):
            return queryset
        if not is_manager_or_higher(user):
            return queryset.filter(created_by=user)
        return queryset.filter(created_by__in=managed_reps).distinct()

    # 17. Accounts: User
    elif m_name == 'user':
        if is_accountant(user) and not (getattr(user, 'is_super_admin', False) or user.is_superuser):
            return queryset.none()
        if not is_manager_or_higher(user):
            return queryset.filter(pk=user.pk)
        return queryset.filter(
            Q(pk=user.pk) | Q(assigned_areas__in=managed_areas)
        ).distinct()

    return queryset


def can_user_access_object(user, obj, action: str = 'view') -> bool:
    """
    Object-level security checker protecting against IDOR, BOLA, and privilege escalation.
    Enforces:
    1. SuperAdmin / Superuser company-wide access.
    2. Regional hierarchy: Area Manager has authority over Main Region + all Subregions + Reps.
    3. Self-approval restriction: Users cannot approve or reject their own submissions.
    4. Cross-region access rejection: Managers cannot view or alter records from other main areas.
    5. Treasury visibility without transaction authority: Viewing a rep's vault does NOT allow transacting or modifying.
    6. Product transfer requests: Superadmin or Accountant approval required before atomic execution.
    """
    if not user.is_authenticated:
        return False

    if getattr(user, 'is_super_admin', False) or user.is_superuser:
        return True

    role = user.role
    if not role or not role.is_active:
        return False

    if role.is_super or role.name in ['superadmin', 'SuperAdmin', 'CEO', 'Admin']:
        return True

    # Approval integrity rule: no user can approve or reject their own submission (anti-self-approval)
    if action in ['approve', 'reject', 'disapprove']:
        owner_id = (
            getattr(obj, 'owner_id', None) or
            getattr(obj, 'created_by_id', None) or
            getattr(obj, 'requesting_user_id', None)
        )
        if owner_id == user.id:
            return False

    managed_areas = set(get_user_managed_areas(user).values_list('id', flat=True))
    managed_rep_ids = set(get_user_managed_representatives(user).values_list('id', flat=True))

    model_name = obj.__class__.__name__.lower()

    if model_name == 'visit':
        if obj.owner_id == user.id or obj.created_by_id == user.id:
            return action not in ['approve', 'reject', 'disapprove']

        if not is_manager_or_higher(user):
            return False

        # Manager can only access visits of reps belonging to the same main area
        rep = obj.owner or obj.created_by
        rep_authorized = is_manager_eligible_for_user(user, rep) if rep else False
        if action in ['approve', 'reject', 'disapprove']:
            return rep_authorized
        return rep_authorized

    elif model_name == 'agreement':
        if is_accountant(user):
            return action == 'view'
        if not is_manager_or_higher(user):
            if action in ['edit', 'delete']:
                if obj.status in ['approved', 'done']:
                    return False
            return obj.created_by_id == user.id
        rep = obj.created_by
        return is_manager_eligible_for_user(user, rep) if rep else False

    elif model_name == 'contact':
        if is_accountant(user):
            return True
        if not is_manager_or_higher(user):
            if is_medical_rep(user):
                return (
                    obj.created_by_id == user.id or
                    obj.assigned_team.filter(id=user.id).exists() or
                    obj.activities.filter(performed_by=user).exists()
                )
            return obj.created_by_id == user.id or obj.assigned_team.filter(id=user.id).exists()
        return (
            obj.area_id in managed_areas or
            obj.created_by_id in managed_rep_ids or
            obj.assigned_team.filter(id__in=managed_rep_ids).exists() or
            is_manager_eligible_for_area(user, obj.area)
        )

    elif model_name in ['salesorder', 'salesreturnorder']:
        if is_accountant(user):
            return True
        if not is_manager_or_higher(user):
            return obj.created_by_id == user.id
        rep = obj.created_by
        return is_manager_eligible_for_user(user, rep) if rep else False

    elif model_name == 'collection':
        if is_accountant(user):
            return True
        if not is_manager_or_higher(user):
            return obj.created_by_id == user.id
        rep = obj.created_by
        return is_manager_eligible_for_user(user, rep) if rep else False

    elif model_name in ['purchaseorder', 'purchasereturnorder']:
        if is_accountant(user):
            return True
        if not is_manager_or_higher(user):
            return obj.created_by_id == user.id
        rep = obj.created_by
        rep_auth = is_manager_eligible_for_user(user, rep) if rep else False
        wh_rep = getattr(obj.target_warehouse, 'assigned_user', None)
        wh_auth = is_manager_eligible_for_user(user, wh_rep) if wh_rep else False
        area_auth = is_manager_eligible_for_area(user, getattr(obj.target_warehouse, 'area', None))
        return rep_auth or wh_auth or area_auth

    elif model_name == 'warehouse':
        if is_accountant(user):
            return True
        if obj.is_main:
            return action == 'view'
        if obj.assigned_user_id == user.id:
            return True
        if not is_manager_or_higher(user):
            return False
        # Manager can view warehouses of reps in their main area or warehouses in their managed areas
        wh_rep = obj.assigned_user
        rep_auth = is_manager_eligible_for_user(user, wh_rep) if wh_rep else False
        area_auth = is_manager_eligible_for_area(user, obj.area) if obj.area else False
        if action == 'view':
            return rep_auth or area_auth
        # Editing/deleting warehouses is reserved for SuperAdmin / Admin
        return False

    elif model_name == 'vault':
        if is_accountant(user):
            return True
        if obj.assigned_user_id == user.id:
            return True
        if not is_manager_or_higher(user):
            return False
        vault_rep = obj.assigned_user
        rep_auth = is_manager_eligible_for_user(user, vault_rep) if vault_rep else False
        if action == 'view':
            return rep_auth or (obj.assigned_user_id is None and has_perm_or_admin(user, 'treasury:vaults/view'))
        if action in ['transfer', 'withdraw', 'deposit']:
            return (rep_auth or obj.assigned_user_id == user.id) and has_perm_or_admin(user, 'treasury:vaults/transfer')
        if action in ['edit', 'manage', 'delete']:
            return has_perm_or_admin(user, 'treasury:vaults/manage')
        return False

    elif model_name == 'vaulttransaction':
        if is_accountant(user):
            return True
        return can_user_access_object(user, obj.vault, action)

    elif model_name == 'producttransferrequest':
        if is_accountant(user):
            return True
        is_rep_involved = (
            obj.requesting_user_id == user.id or
            getattr(obj.source_warehouse, 'assigned_user_id', None) == user.id or
            getattr(obj.destination_warehouse, 'assigned_user_id', None) == user.id
        )
        if is_rep_involved:
            if action in ['approve', 'reject', 'execute']:
                return False  # Rep cannot approve or execute transfer
            return True

        if not is_manager_or_higher(user):
            return False

        # Manager can only view requests involving reps in their main area
        req_rep = obj.requesting_user
        src_rep = getattr(obj.source_warehouse, 'assigned_user', None)
        dst_rep = getattr(obj.destination_warehouse, 'assigned_user', None)
        in_manager_scope = (
            (req_rep and is_manager_eligible_for_user(user, req_rep)) or
            (src_rep and is_manager_eligible_for_user(user, src_rep)) or
            (dst_rep and is_manager_eligible_for_user(user, dst_rep))
        )
        if action == 'view':
            return in_manager_scope
        # Approving and executing inter-warehouse transfers is strictly superadmin / accountant
        return False

    elif model_name in ['vendorpayment', 'vendortransaction']:
        if is_accountant(user):
            return True
        if not is_manager_or_higher(user):
            return obj.created_by_id == user.id
        rep = obj.created_by
        return is_manager_eligible_for_user(user, rep) if rep else False

    elif model_name == 'user':
        # Accountant must not receive user admin or security management access
        if is_accountant(user) and not (getattr(user, 'is_super_admin', False) or user.is_superuser):
            return False
        # Representative cannot manage users
        if not is_manager_or_higher(user):
            if action in ['edit', 'change_role', 'assign_area', 'deactivate', 'delete', 'reset_password']:
                return False
            return user.id == obj.id
        # Manager: can view/edit representatives in their managed areas
        if getattr(obj, 'is_super_admin', False) or obj.is_superuser or is_manager_or_higher(obj):
            if obj.id == user.id:
                return action == 'view'
            return False
        return is_manager_eligible_for_user(user, obj)

    return True


