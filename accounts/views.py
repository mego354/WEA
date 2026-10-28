import csv
from django.shortcuts import render, redirect, get_object_or_404
from django.db import models
from django.db.models import Q
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from .models import User, Role, RoleTag, SecurityAuditLog
from .services import AuditLogService
from master_data.models import Area
from .permissions import (
    require_permission, require_super_admin, has_perm_or_admin,
    can_user_access_object, get_scoped_queryset, is_accountant,
    is_representative, render_forbidden_response
)
from master_data.pagination_utils import paginate_queryset
from .permission_registry import ERP_PERMISSIONS_CATALOG


def _get_client_ip(request):
    """Utility to extract client IP address for security audit logs."""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0].strip()
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


def login_view(request):
    if request.user.is_authenticated:
        return redirect('home')

    if request.method == 'POST':
        login_input = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')
        
        # 1. Try direct authenticate by username or exact email
        user = authenticate(request, username=login_input, password=password)
        if not user:
            # 2. Comprehensive flexible resolution by email, username, or normalized variations
            variants = [
                login_input,
                login_input.replace('_', '.'),
                login_input.replace('.', '_'),
            ]
            if '@' in login_input:
                variants.append(login_input.split('@')[0])
            else:
                variants.append(f"{login_input}@wea.com")

            user_obj = User.objects.filter(
                Q(email__in=variants) | Q(username__in=variants)
            ).first()

            if user_obj:
                user = authenticate(request, username=user_obj.username, password=password)

        if user:
            if not user.is_active:
                AuditLogService.log(
                    action_type='AUTH_FAILED',
                    module='accounts',
                    description=f"محاولة تسجيل دخول لحساب معطل: {login_input}",
                    status='FAILURE',
                    request=request
                )
                messages.error(request, "هذا الحساب معطل حالياً. يرجى التواصل مع إدارة النظام.")
                return render(request, 'accounts/login.html')
            login(request, user)
            AuditLogService.log(
                action_type='AUTH_LOGIN',
                module='accounts',
                actor=user,
                target_user=user,
                description=f"تسجيل دخول ناجح للمستخدم: {user.name or user.username} ({user.email})",
                status='SUCCESS',
                request=request
            )
            messages.success(request, f"مرحباً بك مجدداً {user.name or user.username}")
            next_url = request.GET.get('next') or request.POST.get('next') or 'home'
            return redirect(next_url)
        else:
            AuditLogService.log(
                action_type='AUTH_FAILED',
                module='accounts',
                description=f"محاولة تسجيل دخول فاشلة بالبريد/المعرف: {login_input}",
                status='FAILURE',
                request=request
            )
            messages.error(request, "البريد الإلكتروني أو كلمة المرور غير صحيحة.")

    return render(request, 'accounts/login.html')


def logout_view(request):
    if request.user.is_authenticated:
        AuditLogService.log(
            action_type='AUTH_LOGOUT',
            module='accounts',
            actor=request.user,
            target_user=request.user,
            description=f"تسجيل خروج للمستخدم: {request.user.name or request.user.username} ({request.user.email})",
            status='SUCCESS',
            request=request
        )
    logout(request)
    messages.info(request, "تم تسجيل الخروج بنجاح.")
    return redirect('login')


# ==========================================
# USERS MANAGEMENT
# ==========================================

def get_hierarchical_areas(user=None):
    """
    Returns main root areas with their subareas prefetched,
    scoped if the requesting user is a manager.
    """
    from master_data.models import Area
    from accounts.permissions import is_manager_or_higher, get_user_main_areas

    if user and not user.is_superuser and not getattr(user, 'is_super_admin', False):
        if is_manager_or_higher(user):
            main_areas_qs = get_user_main_areas(user)
        else:
            main_areas_qs = Area.objects.none()
    else:
        main_areas_qs = Area.objects.filter(parent__isnull=True)

    return main_areas_qs.prefetch_related('subareas').order_by('name')


def validate_assigned_areas_for_user(request_user, area_ids):
    """
    Validates submitted area IDs:
    - Verifies all IDs exist in the database (rejects invalid/bogus IDs).
    - If request_user is a manager (not superadmin), ensures all submitted IDs belong to the manager's authorized main areas.
    """
    from master_data.models import Area
    from accounts.permissions import get_user_managed_areas

    if not area_ids:
        return True, "", []

    cleaned_ids = []
    for aid in area_ids:
        try:
            cleaned_ids.append(int(aid))
        except (ValueError, TypeError):
            return False, "توجد معرفات مناطق غير صالحة.", []

    valid_count = Area.objects.filter(id__in=cleaned_ids).count()
    if valid_count != len(set(cleaned_ids)):
        return False, "توجد مناطق جغرافية غير صالحة أو غير موجودة بالنظام.", []

    if not request_user.is_superuser and not getattr(request_user, 'is_super_admin', False):
        managed_area_ids = set(get_user_managed_areas(request_user).values_list('id', flat=True))
        if not set(cleaned_ids).issubset(managed_area_ids):
            return False, "لا تمتلك الصلاحية لتعيين مناطق جغرافية خارج نطاق مسؤوليتك الإدارية المعتمدة.", []

    return True, "", cleaned_ids


@login_required
@require_permission('users:users/list')
def users_list(request):
    """
    User accounts list matching reference ERP:
    Columns: الاسم, البريد الإلكتروني, مفعل, الدور, إجراءات
    Enforces strict RBAC: Accountant and Representative restricted; Manager scoped to region.
    """
    # 1. Accountant restriction
    if is_accountant(request.user) and not (getattr(request.user, 'is_super_admin', False) or request.user.is_superuser):
        return render_forbidden_response(request, 'users:users/list', 'عذراً، لا يمتلك المحاسب صلاحية إدارة المستخدمين.')

    # 2. Representative restriction
    if is_representative(request.user) and not (getattr(request.user, 'is_super_admin', False) or request.user.is_superuser):
        return render_forbidden_response(request, 'users:users/list', 'عذراً، لا تمتلك صلاحية استعراض قائمة المستخدمين.')

    query = request.GET.get('q', '').strip()
    role_filter = request.GET.get('role', '').strip()
    status_filter = request.GET.get('status', '').strip()

    users_qs = User.objects.select_related('role').prefetch_related('assigned_areas').order_by('-created_at')
    users_qs = get_scoped_queryset(users_qs, request.user, 'user')

    if query:
        users_qs = users_qs.filter(
            Q(name__icontains=query) |
            Q(email__icontains=query) |
            Q(username__icontains=query) |
            Q(code__icontains=query)
        )

    if role_filter:
        users_qs = users_qs.filter(role__id=role_filter)

    if status_filter == 'active':
        users_qs = users_qs.filter(is_active=True)
    elif status_filter == 'inactive':
        users_qs = users_qs.filter(is_active=False)

    active_filters = []
    if query:
        active_filters.append({'label': 'بحث', 'value': query, 'param': 'q'})
    if role_filter:
        selected_role = Role.objects.filter(pk=role_filter).first()
        if selected_role:
            active_filters.append({'label': 'الدور', 'value': selected_role.display_name, 'param': 'role'})
    if status_filter:
        active_filters.append({'label': 'الحالة', 'value': 'مفعل' if status_filter == 'active' else 'معطل', 'param': 'status'})

    paginator, page_obj = paginate_queryset(request, users_qs, default_per_page=25)

    roles = Role.get_supported_roles()
    if not (getattr(request.user, 'is_super_admin', False) or request.user.is_superuser):
        roles = roles.exclude(name__iexact='superadmin').exclude(is_super=True)

    hierarchical_areas = get_hierarchical_areas(request.user)
    areas = Area.objects.all().order_by('name')

    base_scoped_qs = get_scoped_queryset(User.objects.all(), request.user, 'user')
    stats = {
        'total_users': base_scoped_qs.count(),
        'active_users': base_scoped_qs.filter(is_active=True).count(),
        'inactive_users': base_scoped_qs.filter(is_active=False).count(),
        'roles_count': roles.count(),
    }

    context = {
        'users': page_obj.object_list,
        'page_obj': page_obj,
        'paginator': paginator,
        'roles': roles,
        'areas': areas,
        'hierarchical_areas': hierarchical_areas,
        'query': query,
        'role_filter': role_filter,
        'status_filter': status_filter,
        'active_filters': active_filters,
        'stats': stats,
    }
    return render(request, 'accounts/users_list.html', context)


@login_required
@require_permission('users:users/create')
def user_create(request):
    """
    Dedicated full HTML page for user creation.
    Enforces strict server-side validation, privilege escalation safeguards, and audit logging.
    """
    # 1. RBAC check: Accountant and Representative cannot create users
    if is_accountant(request.user) and not (getattr(request.user, 'is_super_admin', False) or request.user.is_superuser):
        return render_forbidden_response(request, 'users:users/create', 'عذراً، لا يمتلك المحاسب صلاحية إنشاء مستخدمين.')

    from accounts.permissions import is_manager_or_higher
    if not is_manager_or_higher(request.user) and not (getattr(request.user, 'is_super_admin', False) or request.user.is_superuser):
        return render_forbidden_response(request, 'users:users/create', 'عذراً، لا تمتلك الصلاحية لإنشاء مستخدمين.')

    roles = Role.get_supported_roles()
    if not (getattr(request.user, 'is_super_admin', False) or request.user.is_superuser):
        # Manager can only create Representatives in their area
        roles = roles.exclude(name__iexact='superadmin').exclude(is_super=True)

    hierarchical_areas = get_hierarchical_areas(request.user)

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        email = request.POST.get('email', '').strip().lower()
        code = request.POST.get('code', '').strip()
        mobile = request.POST.get('mobile', '').strip()
        password = request.POST.get('password', '')
        confirm_password = request.POST.get('confirm_password', '')
        role_id = request.POST.get('role', '')
        is_active = request.POST.get('is_active') == 'on' or 'is_active' in request.POST
        area_ids = request.POST.getlist('assigned_areas')

        form_data = {
            'name': name,
            'email': email,
            'code': code,
            'mobile': mobile,
            'role': role_id,
            'assigned_areas': [int(a) for a in area_ids if a.isdigit()],
        }

        # Server validations
        errors = []
        if not name or not email or not password or not role_id:
            errors.append("يرجى ملء جميع الحقول الإلزامية المطلوبة (الاسم، البريد الإلكتروني، كلمة المرور، الدور).")

        if password and len(password) < 6:
            errors.append("يجب أن تكون كلمة المرور مكونة من 6 أحرف أو أرقام على الأقل.")

        if confirm_password and password != confirm_password:
            errors.append("كلمة المرور وتأكيد كلمة المرور غير متطابقين.")

        if email and (User.objects.filter(email__iexact=email).exists() or User.objects.filter(username__iexact=email).exists()):
            errors.append(f"البريد الإلكتروني '{email}' مسجل بالفعل لمستخدم آخر.")

        role = Role.get_supported_roles().filter(pk=role_id).first() or Role.objects.filter(pk=role_id, is_active=True).first()
        if not role:
            errors.append("الدور الوظيفي المحدد غير مدعوم في النظام (يجب أن يكون أحد الأدوار الخمسة المعتمدة).")
        elif role.is_super and not getattr(request.user, 'is_super_admin', False):
            errors.append("عذراً، لا يمكنك تعيين دور مدير النظام الأعلى (SuperAdmin). هذا الإجراء مقصور على مدراء النظام الأعلى.")
        elif not (getattr(request.user, 'is_super_admin', False) or request.user.is_superuser):
            if role.name.lower() in ['superadmin', 'manager']:
                errors.append("مدير المنطقة يمكنه فقط إنشاء حسابات للمندوبين التابعين لمنطقته.")

        is_valid_areas, err_msg_areas, cleaned_area_ids = validate_assigned_areas_for_user(request.user, area_ids)
        if not is_valid_areas:
            errors.append(err_msg_areas)

        if errors:
            for err in errors:
                messages.error(request, err)
            return render(request, 'accounts/user_create.html', {
                'roles': roles,
                'hierarchical_areas': hierarchical_areas,
                'form_data': form_data,
            })

        # Create user
        user = User.objects.create_user(
            username=email,
            email=email,
            password=password,
            name=name,
            code=code,
            mobile=mobile,
            role=role,
            is_active=is_active,
            locale='ar'
        )

        if cleaned_area_ids:
            user.assigned_areas.set(cleaned_area_ids)

        # Record Security Audit Log
        AuditLogService.log(
            action_type='USER_CREATED',
            module='accounts',
            actor=request.user,
            target_user=user,
            target_role=role,
            record_id=user.id,
            record_name=user.name,
            new_values={'name': user.name, 'email': user.email, 'role': role.display_name, 'code': user.code, 'mobile': user.mobile},
            description=f"إنشاء حساب مستخدم جديد: {user.name} ({user.email}) وتعيين الدور: {role.display_name}",
            status='SUCCESS',
            request=request,
        )

        messages.success(request, f"تم إنشاء حساب المستخدم '{user.name}' بنجاح.")
        return redirect('user_detail', pk=user.pk)

    return render(request, 'accounts/user_create.html', {
        'roles': roles,
        'hierarchical_areas': hierarchical_areas,
        'form_data': {},
    })


@login_required
@require_permission('users:users/list')
def user_detail(request, pk):
    """
    Dedicated full HTML page for viewing a user profile, roles, assigned areas,
    warehouses, vaults, and recent audit logs.
    """
    target_user = get_object_or_404(User, pk=pk)

    if not can_user_access_object(request.user, target_user, 'view'):
        return render_forbidden_response(request, 'users:users/list', 'عذراً، لا تمتلك الصلاحية لعرض بيانات هذا المستخدم.')

    from inventory.models import Warehouse
    from treasury.models import Vault

    assigned_areas = target_user.assigned_areas.select_related('parent').all().order_by('name')
    assigned_warehouses = Warehouse.objects.filter(assigned_user=target_user)
    assigned_vaults = Vault.objects.filter(assigned_user=target_user)
    recent_audit_logs = SecurityAuditLog.objects.filter(
        Q(actor=target_user) | Q(target_user=target_user)
    ).order_by('-created_at')[:20]

    can_edit = can_user_access_object(request.user, target_user, 'edit')

    context = {
        'target_user': target_user,
        'assigned_areas': assigned_areas,
        'assigned_warehouses': assigned_warehouses,
        'warehouses': assigned_warehouses,
        'assigned_vaults': assigned_vaults,
        'vaults': assigned_vaults,
        'recent_audit_logs': recent_audit_logs,
        'can_edit': can_edit,
    }
    return render(request, 'accounts/user_detail.html', context)


@login_required
@require_permission('users:users/edit')
def user_edit(request, pk):
    """
    Dedicated full HTML page to edit user profile, role, status, code, and assigned areas with privilege escalation protection.
    """
    target_user = get_object_or_404(User, pk=pk)

    if not can_user_access_object(request.user, target_user, 'edit'):
        return render_forbidden_response(request, 'users:users/edit', 'عذراً، لا تمتلك الصلاحية لتعديل بيانات هذا المستخدم.')

    # Protect target superadmin: only superadmin can edit another superadmin
    if target_user.is_super_admin and not getattr(request.user, 'is_super_admin', False):
        messages.error(request, "عذراً، لا تمتلك الصلاحية الكافية لتعديل حساب مدير النظام الأعلى.")
        return redirect('users_list')

    roles = Role.get_supported_roles()
    if not (getattr(request.user, 'is_super_admin', False) or request.user.is_superuser):
        roles = roles.exclude(name__iexact='superadmin').exclude(is_super=True)

    hierarchical_areas = get_hierarchical_areas(request.user)

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        email = request.POST.get('email', '').strip().lower()
        code = request.POST.get('code', '').strip()
        role_id = request.POST.get('role', '')
        mobile = request.POST.get('mobile', '').strip()
        is_active = request.POST.get('is_active') == 'on'

        if not name or not email:
            messages.error(request, "الاسم والبريد الإلكتروني حقول إلزامية.")
            return render(request, 'accounts/user_edit.html', {
                'target_user': target_user,
                'roles': roles,
                'hierarchical_areas': hierarchical_areas,
                'selected_area_ids': list(target_user.assigned_areas.values_list('id', flat=True)),
            })

        # Check unique email against others
        if User.objects.filter(email__iexact=email).exclude(pk=target_user.pk).exists():
            messages.error(request, f"البريد الإلكتروني '{email}' مسجل لمستخدم آخر.")
            return render(request, 'accounts/user_edit.html', {
                'target_user': target_user,
                'roles': roles,
                'hierarchical_areas': hierarchical_areas,
                'selected_area_ids': list(target_user.assigned_areas.values_list('id', flat=True)),
            })

        # Safeguard: cannot deactivate last superadmin
        if target_user.is_superuser and not is_active:
            active_superusers = User.objects.filter(is_superuser=True, is_active=True).exclude(pk=target_user.pk).count()
            if active_superusers == 0:
                messages.error(request, "لا يمكن تعطيل مدير النظام الأعلى الأخير للنظام لمنع قفل النظام!")
                return render(request, 'accounts/user_edit.html', {
                    'target_user': target_user,
                    'roles': roles,
                    'hierarchical_areas': hierarchical_areas,
                    'selected_area_ids': list(target_user.assigned_areas.values_list('id', flat=True)),
                })

        old_values = {
            'name': target_user.name,
            'email': target_user.email,
            'role': target_user.role.display_name if target_user.role else 'بدون دور',
            'is_active': target_user.is_active,
            'code': target_user.code,
            'mobile': target_user.mobile,
        }

        old_role = target_user.role
        target_user.name = name
        target_user.email = email
        target_user.username = email
        target_user.code = code
        target_user.mobile = mobile
        target_user.is_active = is_active

        if role_id:
            new_role = Role.get_supported_roles().filter(pk=role_id).first() or Role.objects.filter(pk=role_id, is_active=True).first()
            if not new_role:
                messages.error(request, "الدور الوظيفي المحدد غير مدعوم في النظام (يجب أن يكون أحد الأدوار الخمسة المعتمدة).")
                return render(request, 'accounts/user_edit.html', {
                    'target_user': target_user,
                    'roles': roles,
                    'hierarchical_areas': hierarchical_areas,
                    'selected_area_ids': list(target_user.assigned_areas.values_list('id', flat=True)),
                })
            # Privilege escalation check: non-superadmin cannot assign SuperAdmin role
            if new_role.is_super and not getattr(request.user, 'is_super_admin', False):
                messages.error(request, "عذراً، لا يمكنك تعيين دور مدير النظام الأعلى (SuperAdmin).")
                return render(request, 'accounts/user_edit.html', {
                    'target_user': target_user,
                    'roles': roles,
                    'hierarchical_areas': hierarchical_areas,
                    'selected_area_ids': list(target_user.assigned_areas.values_list('id', flat=True)),
                })
            target_user.role = new_role
        else:
            if not target_user.is_superuser:
                target_user.role = None

        target_user.save()
        target_user.clear_perm_cache()

        # Update assigned areas with strict backend validation
        area_ids = request.POST.getlist('assigned_areas')
        is_valid, err_msg, cleaned_ids = validate_assigned_areas_for_user(request.user, area_ids)
        if not is_valid:
            messages.error(request, err_msg)
            return render(request, 'accounts/user_edit.html', {
                'target_user': target_user,
                'roles': roles,
                'hierarchical_areas': hierarchical_areas,
                'selected_area_ids': list(target_user.assigned_areas.values_list('id', flat=True)),
            })
        target_user.assigned_areas.set(cleaned_ids)

        new_values = {
            'name': target_user.name,
            'email': target_user.email,
            'role': target_user.role.display_name if target_user.role else 'بدون دور',
            'is_active': target_user.is_active,
            'code': target_user.code,
            'mobile': target_user.mobile,
        }

        # Record Security Audit Log with previous and new values
        AuditLogService.log(
            action_type='USER_UPDATED',
            module='accounts',
            actor=request.user,
            target_user=target_user,
            target_role=target_user.role,
            record_id=target_user.id,
            record_name=target_user.name,
            previous_values=old_values,
            new_values=new_values,
            description=f"تحديث بيانات المستخدم: {target_user.name} (الدور السابق: {old_role}, الدور الجديد: {target_user.role}, الحالة: {'مفعل' if is_active else 'معطل'})",
            status='SUCCESS',
            request=request,
        )

        messages.success(request, f"تم تحديث بيانات المستخدم '{target_user.name}' بنجاح.")
        return redirect('user_detail', pk=target_user.pk)

    selected_area_ids = list(target_user.assigned_areas.values_list('id', flat=True))
    areas = Area.objects.all().order_by('name')
    return render(request, 'accounts/user_edit.html', {
        'target_user': target_user,
        'roles': roles,
        'areas': areas,
        'hierarchical_areas': hierarchical_areas,
        'selected_area_ids': selected_area_ids,
    })


@login_required
@require_permission('users:users/edit')
def user_reset_password(request, pk):
    """
    Reset user password with server-side validation and audit logging.
    """
    target_user = get_object_or_404(User, pk=pk)

    if not can_user_access_object(request.user, target_user, 'reset_password'):
        return render_forbidden_response(request, 'users:users/edit', 'عذراً، لا تمتلك الصلاحية لتغيير كلمة مرور هذا المستخدم.')

    if target_user.is_super_admin and not getattr(request.user, 'is_super_admin', False):
        messages.error(request, "عذراً، لا تمتلك الصلاحية لتغيير كلمة مرور مدير النظام الأعلى.")
        return redirect('users_list')

    if request.method == 'POST':
        new_password = request.POST.get('new_password', '').strip()
        confirm_password = request.POST.get('confirm_password', '').strip()

        if len(new_password) < 6:
            messages.error(request, "يجب ألا تقل كلمة المرور عن 6 أحرف.")
            return redirect('user_edit', pk=pk)

        if new_password != confirm_password:
            messages.error(request, "كلمتا المرور غير متطابقتين.")
            return redirect('user_edit', pk=pk)

        target_user.set_password(new_password)
        target_user.save()

        # Record Security Audit Log
        AuditLogService.log(
            action_type='USER_PASSWORD_RESET',
            module='accounts',
            actor=request.user,
            target_user=target_user,
            record_id=target_user.id,
            record_name=target_user.name,
            description=f"إعادة تعيين كلمة المرور للمستخدم: {target_user.name} ({target_user.email})",
            status='SUCCESS',
            request=request,
        )

        messages.success(request, f"تم تغيير كلمة المرور للمستخدم '{target_user.name}' بنجاح.")
        return redirect('user_detail', pk=pk)

    return redirect('user_detail', pk=pk)


@login_required
@require_permission('users:users/edit')
def user_toggle_status(request, pk):
    """
    Toggles is_active on user with superuser lockout safeguard and audit logging.
    """
    target_user = get_object_or_404(User, pk=pk)

    if not can_user_access_object(request.user, target_user, 'deactivate'):
        return render_forbidden_response(request, 'users:users/edit', 'عذراً، لا تمتلك الصلاحية لتعديل حالة هذا المستخدم.')

    if target_user.is_active:
        if target_user.is_superuser:
            active_superusers = User.objects.filter(is_superuser=True, is_active=True).exclude(pk=target_user.pk).count()
            if active_superusers == 0:
                messages.error(request, "لا يمكن تعطيل حساب مدير النظام الأعلى الوحيد في النظام!")
                return redirect('users_list')

    prev_status = target_user.is_active
    target_user.is_active = not target_user.is_active
    target_user.save()
    target_user.clear_perm_cache()

    status_str = "تفعيل" if target_user.is_active else "تعطيل"

    # Record Security Audit Log
    AuditLogService.log(
        action_type='USER_STATUS_TOGGLED',
        module='accounts',
        actor=request.user,
        target_user=target_user,
        record_id=target_user.id,
        record_name=target_user.name,
        previous_values={'is_active': prev_status},
        new_values={'is_active': target_user.is_active},
        description=f"{status_str} حساب المستخدم: {target_user.name} ({target_user.email})",
        status='SUCCESS',
        request=request,
    )

    messages.success(request, f"تم {status_str} حساب المستخدم '{target_user.name}' بنجاح.")
    return redirect('users_list')


@login_required
@require_super_admin(redirect_url='users_list')
def user_toggle_bypass_location(request, pk):
    """
    SuperAdmin-only control to toggle bypass_location_verification for a user.
    """
    target_user = get_object_or_404(User, pk=pk)
    target_user.bypass_location_verification = not target_user.bypass_location_verification
    target_user.save()

    status_str = "تفعيل" if target_user.bypass_location_verification else "تعطيل"

    SecurityAuditLog.objects.create(
        actor=request.user,
        action_type='USER_BYPASS_LOCATION_TOGGLED',
        target_user=target_user,
        description=f"{status_str} تجاوز التحقق من الموقع الجغرافي للمستخدم: {target_user.name}",
        ip_address=_get_client_ip(request),
        user_agent=request.META.get('HTTP_USER_AGENT', ''),
    )

    messages.success(request, f"تم {status_str} تجاوز التحقق من الموقع للمستخدم {target_user.name or target_user.username} بنجاح.")
    return redirect('users_list')


@login_required
@require_permission('users:users/export')
def users_export(request):
    """
    Exports users list to CSV with UTF-8 BOM for Arabic Excel compatibility.
    """
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="users_list.csv"'
    response.write('\ufeff'.encode('utf8'))

    writer = csv.writer(response)
    writer.writerow(['المعرف', 'الاسم', 'البريد الإلكتروني', 'الكود', 'الدور الوظيفي', 'الحالة', 'الهاتف', 'تاريخ الإنشاء'])

    for u in User.objects.select_related('role').order_by('name'):
        status = 'مفعل' if u.is_active else 'معطل'
        role = u.role.display_name if u.role else ('مدير نظام' if u.is_superuser else '-')
        writer.writerow([u.id, u.name, u.email, u.code, role, status, u.mobile, u.created_at.strftime('%Y-%m-%d %H:%M')])

    return response


@login_required
@require_super_admin()
def user_effective_permissions(request, pk):
    """
    SuperAdmin inspector to view a user's effective permissions,
    including role attributes, assigned areas, tags, and active module/action trees.
    """
    target_user = get_object_or_404(User.objects.select_related('role').prefetch_related('assigned_areas', 'role__tags'), pk=pk)
    effective_codenames = target_user.get_effective_permission_codenames()

    modules_tree = get_grouped_permissions()

    return render(request, 'accounts/effective_permissions.html', {
        'target_user': target_user,
        'effective_codenames': effective_codenames,
        'modules_tree': modules_tree,
    })


# ==========================================
# ROLES & PERMISSIONS MANAGEMENT (SUPERADMIN ONLY)
# ==========================================

def get_grouped_permissions():
    """
    Helper returning the hierarchical permission matrix structured by Module -> Pages -> Actions,
    hydrated with database Permission objects.
    """
    db_perms = {p.codename: p for p in Permission.objects.all()}

    modules_tree = []
    for mod_key, mod_info in ERP_PERMISSIONS_CATALOG.items():
        root_perm = db_perms.get(mod_info['root_perm'])

        pages_list = []
        for page_key, page_info in mod_info['pages'].items():
            actions_list = []
            for codename, name_ar, action_type in page_info['actions']:
                p_obj = db_perms.get(codename)
                if p_obj:
                    actions_list.append({
                        'perm': p_obj,
                        'codename': codename,
                        'name': name_ar,
                        'action_type': action_type,
                    })
            if actions_list:
                pages_list.append({
                    'code': page_key,
                    'name_ar': page_info['name_ar'],
                    'actions': actions_list,
                })

        modules_tree.append({
            'code': mod_key,
            'name_ar': mod_info['name_ar'],
            'name_en': mod_info['name_en'],
            'icon': mod_info['icon'],
            'root_perm': root_perm,
            'pages': pages_list,
            'total_perms': sum(len(p['actions']) for p in pages_list) + (1 if root_perm else 0),
        })

    return modules_tree


@login_required
@require_super_admin()
def roles_list(request):
    """
    Roles list matching reference ERP (SuperAdmin only):
    Columns: المعرف, الاسم, مفعل, إجراءات (Edit pencil, Duplicate copy, Delete)
    """
    query = request.GET.get('q', '').strip()
    status_filter = request.GET.get('status', '').strip()

    roles = Role.objects.annotate(users_count=models.Count('users')).prefetch_related('tags').order_by('id')

    if query:
        roles = roles.filter(
            Q(name__icontains=query) |
            Q(display_name__icontains=query) |
            Q(description__icontains=query)
        )

    if status_filter == 'active':
        roles = roles.filter(is_active=True)
    elif status_filter == 'inactive':
        roles = roles.filter(is_active=False)

    active_filters = []
    if query:
        active_filters.append({'label': 'بحث', 'value': query, 'param': 'q'})
    if status_filter:
        active_filters.append({'label': 'الحالة', 'value': 'مفعل' if status_filter == 'active' else 'معطل', 'param': 'status'})

    paginator, page_obj = paginate_queryset(request, roles, default_per_page=25)

    return render(request, 'accounts/roles_list.html', {
        'roles': page_obj.object_list,
        'page_obj': page_obj,
        'paginator': paginator,
        'query': query,
        'status_filter': status_filter,
        'active_filters': active_filters,
    })


@login_required
@require_super_admin()
def role_create(request):
    """
    Create a new role with attributes, tags, and hierarchical permissions (SuperAdmin only).
    """
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        display_name = request.POST.get('display_name', '').strip() or name
        description = request.POST.get('description', '').strip()

        if not name:
            messages.error(request, "اسم الدور البرمجي حقل إلزامي.")
            return redirect('role_create')

        if Role.objects.filter(name__iexact=name).exists():
            messages.error(request, f"الدور '{name}' موجود بالفعل.")
            return redirect('role_create')

        is_super = request.POST.get('is_super') == 'on'
        if is_super and not getattr(request.user, 'is_super_admin', False):
            messages.error(request, "لا يمكن إنشاء دور سوبر إلا بواسطة مدير النظام الأعلى.")
            return redirect('roles_list')

        role = Role.objects.create(
            name=name,
            display_name=display_name,
            description=description,
            is_active=request.POST.get('is_active') == 'on',
            is_super=is_super,
            is_sales_team=request.POST.get('is_sales_team') == 'on',
            is_area_manager=request.POST.get('is_area_manager') == 'on',
            is_sub_area_manager=request.POST.get('is_sub_area_manager') == 'on',
            is_rep=request.POST.get('is_rep') == 'on',
            can_hold_vault=request.POST.get('can_hold_vault') == 'on',
            has_sales_targets=request.POST.get('has_sales_targets') == 'on',
            is_contact_manager=request.POST.get('is_contact_manager') == 'on',
            is_main_area_bound=request.POST.get('is_main_area_bound') == 'on',
            is_sub_area_bound=request.POST.get('is_sub_area_bound') == 'on',
        )

        # Tags
        tag_ids = request.POST.getlist('tags')
        if tag_ids:
            role.tags.set(tag_ids)

        # Permissions
        perm_ids = request.POST.getlist('permissions')
        if perm_ids:
            role.permissions.set(perm_ids)

        # Record Security Audit Log
        SecurityAuditLog.objects.create(
            actor=request.user,
            action_type='ROLE_CREATED',
            target_role=role,
            description=f"إنشاء دور صلاحيات جديد: {role.display_name} ({role.name}) وتعيين {role.permissions.count()} صلاحية.",
            ip_address=_get_client_ip(request),
            user_agent=request.META.get('HTTP_USER_AGENT', ''),
        )

        messages.success(request, f"تم إنشاء الدور '{role.display_name}' بنجاح.")
        return redirect('roles_list')

    all_tags = RoleTag.objects.all().order_by('tag')
    modules_tree = get_grouped_permissions()
    return render(request, 'accounts/role_form.html', {
        'role': None,
        'all_tags': all_tags,
        'modules_tree': modules_tree,
        'is_create': True,
    })


@login_required
@require_super_admin()
def role_edit(request, pk):
    """
    Role edit dossier matching reference ERP (/settings/roles/edit/<id>):
    Attributes switches, Tags dropdown, Granular Permissions Matrix.
    """
    role = get_object_or_404(Role, pk=pk)

    if request.method == 'POST':
        # Protect system SuperAdmin role
        if role.name == 'SuperAdmin':
            # Cannot rename or de-escalate SuperAdmin
            role.is_active = True
            role.is_super = True
        else:
            role.is_active = request.POST.get('is_active') == 'on'
            role.is_super = request.POST.get('is_super') == 'on'

        role.display_name = request.POST.get('display_name', role.display_name).strip()
        role.description = request.POST.get('description', '').strip()

        # Update attributes switches
        role.is_sales_team = request.POST.get('is_sales_team') == 'on'
        role.is_area_manager = request.POST.get('is_area_manager') == 'on'
        role.is_sub_area_manager = request.POST.get('is_sub_area_manager') == 'on'
        role.is_rep = request.POST.get('is_rep') == 'on'
        role.can_hold_vault = request.POST.get('can_hold_vault') == 'on'
        role.has_sales_targets = request.POST.get('has_sales_targets') == 'on'
        role.is_contact_manager = request.POST.get('is_contact_manager') == 'on'
        role.is_main_area_bound = request.POST.get('is_main_area_bound') == 'on'
        role.is_sub_area_bound = request.POST.get('is_sub_area_bound') == 'on'
        role.save()

        # Update Tags
        tag_ids = request.POST.getlist('tags')
        role.tags.set(tag_ids)

        # Update Permissions
        perm_ids = request.POST.getlist('permissions')
        role.permissions.set(perm_ids)

        # Invalidate cached permissions across existing sessions/users for this role
        for u in role.users.all():
            u.clear_perm_cache()

        # Record Security Audit Log
        SecurityAuditLog.objects.create(
            actor=request.user,
            action_type='ROLE_UPDATED',
            target_role=role,
            description=f"تعديل دور الصلاحيات: {role.display_name} ({role.name}) - تم حفظ {role.permissions.count()} صلاحية.",
            ip_address=_get_client_ip(request),
            user_agent=request.META.get('HTTP_USER_AGENT', ''),
        )

        messages.success(request, f"تم حفظ تعديلات الدور '{role.display_name}' بنجاح.")
        return redirect('roles_list')

    all_tags = RoleTag.objects.all().order_by('tag')
    role_tag_ids = set(role.tags.values_list('id', flat=True))
    role_perm_ids = set(role.permissions.values_list('id', flat=True))
    modules_tree = get_grouped_permissions()

    return render(request, 'accounts/role_form.html', {
        'role': role,
        'all_tags': all_tags,
        'role_tag_ids': role_tag_ids,
        'role_perm_ids': role_perm_ids,
        'modules_tree': modules_tree,
        'is_create': False,
    })


@login_required
@require_super_admin()
def role_duplicate(request, pk):
    """
    Duplicates an existing role deeply with all attributes, tags, and permissions.
    """
    original = get_object_or_404(Role, pk=pk)

    base_name = f"{original.name}_copy"
    counter = 1
    new_name = base_name
    while Role.objects.filter(name=new_name).exists():
        counter += 1
        new_name = f"{base_name}_{counter}"

    new_display = f"{original.display_name} (نسخة)"

    clone = Role.objects.create(
        name=new_name,
        display_name=new_display,
        description=original.description,
        is_system=False,
        is_active=original.is_active,
        is_super=False, # Clones are never super by default
        is_sales_team=original.is_sales_team,
        is_area_manager=original.is_area_manager,
        is_sub_area_manager=original.is_sub_area_manager,
        is_rep=original.is_rep,
        can_hold_vault=original.can_hold_vault,
        has_sales_targets=original.has_sales_targets,
        is_contact_manager=original.is_contact_manager,
        is_main_area_bound=original.is_main_area_bound,
        is_sub_area_bound=original.is_sub_area_bound,
    )

    clone.tags.set(original.tags.all())
    clone.permissions.set(original.permissions.all())

    SecurityAuditLog.objects.create(
        actor=request.user,
        action_type='ROLE_DUPLICATED',
        target_role=clone,
        description=f"استنساخ دور صلاحيات من '{original.display_name}' إلى '{clone.display_name}' ({clone.name})",
        ip_address=_get_client_ip(request),
        user_agent=request.META.get('HTTP_USER_AGENT', ''),
    )

    messages.success(request, f"تم استنساخ الدور بنجاح: '{clone.display_name}'.")
    return redirect('role_edit', pk=clone.pk)


@login_required
@require_super_admin()
def role_delete(request, pk):
    """
    Delete custom role (safeguarded against deleting system roles or roles with assigned users).
    """
    role = get_object_or_404(Role, pk=pk)
    if role.is_system or role.name == 'SuperAdmin':
        messages.error(request, "لا يمكن حذف الأدوار النظامية الأساسية.")
        return redirect('roles_list')

    if role.users.exists():
        messages.error(request, f"لا يمكن حذف الدور '{role.display_name}' لأنه مرتبط بـ {role.users.count()} مستخدم.")
        return redirect('roles_list')

    name = role.display_name
    role_id = role.id
    role.delete()

    SecurityAuditLog.objects.create(
        actor=request.user,
        action_type='ROLE_DELETED',
        description=f"حذف دور الصلاحيات: {name} (ID: {role_id})",
        ip_address=_get_client_ip(request),
        user_agent=request.META.get('HTTP_USER_AGENT', ''),
    )

    messages.success(request, f"تم حذف الدور '{name}' بنجاح.")
    return redirect('roles_list')


# ==========================================
# SECURITY AUDIT LOGS (SUPERADMIN ONLY)
# ==========================================
# AUDIT LOGS MANAGEMENT
# ==========================================

@login_required
@require_permission(['settings:auditLogs/view', 'settings:rbac/view'])
def audit_logs_list(request):
    """
    Comprehensive Audit history for all ERP operations:
    Filterable by module, action_type, actor/user, search query (records, IDs, names), and date range.
    Includes previous and new value tracking with server-side pagination.
    """
    from datetime import datetime, time
    from django.utils import timezone

    module_filter = request.GET.get('module', '').strip()
    action_filter = request.GET.get('action', '').strip()
    user_filter = request.GET.get('user', '').strip()
    date_from = request.GET.get('date_from', '').strip()
    date_to = request.GET.get('date_to', '').strip()
    query = request.GET.get('q', '').strip()

    logs_qs = SecurityAuditLog.objects.select_related('actor', 'target_user', 'target_role').order_by('-created_at')

    if module_filter:
        logs_qs = logs_qs.filter(module=module_filter)

    if action_filter:
        logs_qs = logs_qs.filter(action_type=action_filter)

    if user_filter and user_filter.isdigit():
        logs_qs = logs_qs.filter(actor_id=int(user_filter))

    if date_from:
        try:
            df = datetime.strptime(date_from, '%Y-%m-%d')
            df_aware = timezone.make_aware(datetime.combine(df.date(), time.min))
            logs_qs = logs_qs.filter(created_at__gte=df_aware)
        except (ValueError, TypeError):
            pass

    if date_to:
        try:
            dt = datetime.strptime(date_to, '%Y-%m-%d')
            dt_aware = timezone.make_aware(datetime.combine(dt.date(), time.max))
            logs_qs = logs_qs.filter(created_at__lte=dt_aware)
        except (ValueError, TypeError):
            pass

    if query:
        logs_qs = logs_qs.filter(
            Q(description__icontains=query) |
            Q(record_id__icontains=query) |
            Q(record_name__icontains=query) |
            Q(actor__name__icontains=query) |
            Q(actor__username__icontains=query) |
            Q(target_user__name__icontains=query) |
            Q(ip_address__icontains=query)
        )

    active_filters = []
    if module_filter:
        mod_dict = dict(SecurityAuditLog.MODULE_CHOICES)
        active_filters.append({'label': 'الموديول', 'value': mod_dict.get(module_filter, module_filter), 'param': 'module'})
    if action_filter:
        action_lbl = SecurityAuditLog.get_label_for_action(action_filter)
        active_filters.append({'label': 'نوع العملية', 'value': action_lbl, 'param': 'action'})
    if user_filter and user_filter.isdigit():
        u_obj = User.objects.filter(pk=int(user_filter)).first()
        if u_obj:
            active_filters.append({'label': 'المستخدم', 'value': u_obj.name or u_obj.username, 'param': 'user'})
    if date_from:
        active_filters.append({'label': 'من تاريخ', 'value': date_from, 'param': 'date_from'})
    if date_to:
        active_filters.append({'label': 'إلى تاريخ', 'value': date_to, 'param': 'date_to'})
    if query:
        active_filters.append({'label': 'بحث', 'value': query, 'param': 'q'})

    paginator, page_obj = paginate_queryset(request, logs_qs, default_per_page=25)

    all_users = User.objects.filter(is_active=True).order_by('name')

    return render(request, 'accounts/audit_logs.html', {
        'logs': page_obj.object_list,
        'page_obj': page_obj,
        'paginator': paginator,
        'module_choices': SecurityAuditLog.MODULE_CHOICES,
        'action_choices': SecurityAuditLog.ACTION_CHOICES,
        'module_filter': module_filter,
        'action_filter': action_filter,
        'user_filter': user_filter,
        'date_from': date_from,
        'date_to': date_to,
        'query': query,
        'active_filters': active_filters,
        'users': all_users,
    })


@login_required
@require_permission(['settings:auditLogs/view', 'settings:rbac/view'])
def audit_log_detail(request, pk):
    """JSON API endpoint returning comprehensive details and diffs for an audit entry."""
    log = get_object_or_404(SecurityAuditLog.objects.select_related('actor', 'target_user', 'target_role'), pk=pk)
    log_data = {
        'id': log.id,
        'created_at': log.created_at.strftime('%Y-%m-%d %H:%M:%S'),
        'module': log.module,
        'module_display': log.get_module_display(),
        'action_type': log.action_type,
        'action_type_display': log.get_action_type_display(),
        'action_type_display_en': log.get_action_type_display(lang='en'),
        'actor': log.actor.name or log.actor.username if log.actor else 'النظام تلقائياً',
        'record_id': log.record_id,
        'record_name': log.record_name,
        'description': log.description,
        'status': log.status,
        'reason': log.reason,
        'ip_address': log.ip_address or '–',
        'user_agent': log.user_agent or '–',
        'previous_values': log.previous_values,
        'new_values': log.new_values,
    }
    return JsonResponse({
        'success': True,
        'log': log_data,
        **log_data,
    })


# ==========================================
# USERS SETTINGS (SUPERADMIN ONLY)
# ==========================================

@login_required
@require_super_admin()
def users_settings_view(request):
    """
    Users Settings view:
    Controls automated provisioning of representative warehouses and treasuries.
    Includes toggle controls, explicit business rules documentation, and interactive backfill execution.
    Restricted strictly to authorized SuperAdmins.
    """
    from accounts.models import UserSettings
    from accounts.services import is_representative
    from django.core.management import call_command
    import io

    settings_obj = UserSettings.get_settings()

    if request.method == 'POST':
        action = request.POST.get('action', 'save_settings')

        if action == 'save_settings':
            settings_obj.auto_create_rep_warehouse = bool(request.POST.get('auto_create_rep_warehouse') == '1')
            settings_obj.auto_create_rep_treasury = bool(request.POST.get('auto_create_rep_treasury') == '1')
            settings_obj.save()
            messages.success(request, "تم حفظ إعدادات إنشاء المخازن والخزائن للمندوبين بنجاح.")
            return redirect('users_settings')

        elif action == 'run_backfill':
            out = io.StringIO()
            call_command('backfill_representative_resources', stdout=out)
            messages.success(request, "تم تشغيل المعالجة الاسترجاعية (Backfill) وتحديث موارد المندوبين بنجاح.")
            return redirect('users_settings')

    # Status summary
    active_users = User.objects.filter(is_active=True).select_related('role').prefetch_related('assigned_areas')
    reps = [u for u in active_users if is_representative(u)]
    reps_with_wh = [u for u in reps if u.get_default_warehouse() is not None]
    reps_with_vault = [u for u in reps if u.get_default_treasury() is not None]

    context = {
        'settings': settings_obj,
        'total_reps_count': len(reps),
        'reps_with_wh_count': len(reps_with_wh),
        'reps_missing_wh_count': len(reps) - len(reps_with_wh),
        'reps_with_vault_count': len(reps_with_vault),
        'reps_missing_vault_count': len(reps) - len(reps_with_vault),
        'reps': reps,
    }
    return render(request, 'accounts/users_settings.html', context)
