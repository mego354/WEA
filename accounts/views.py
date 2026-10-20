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
from .models import User, Role, RoleTag
from master_data.models import Area
from .permissions import require_permission, has_perm_or_admin


def login_view(request):
    if request.user.is_authenticated:
        return redirect('home')

    if request.method == 'POST':
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')
        
        user = authenticate(request, username=email, password=password)
        if not user:
            user_obj = User.objects.filter(email__iexact=email).first()
            if user_obj:
                user = authenticate(request, username=user_obj.username, password=password)

        if user:
            if not user.is_active:
                messages.error(request, "هذا الحساب معطل حالياً. يرجى التواصل مع إدارة النظام.")
                return render(request, 'accounts/login.html')
            login(request, user)
            messages.success(request, f"مرحباً بك مجدداً {user.name or user.username}")
            next_url = request.GET.get('next') or request.POST.get('next') or 'home'
            return redirect(next_url)
        else:
            messages.error(request, "البريد الإلكتروني أو كلمة المرور غير صحيحة.")

    return render(request, 'accounts/login.html')


def logout_view(request):
    logout(request)
    messages.info(request, "تم تسجيل الخروج بنجاح.")
    return redirect('login')


# ==========================================
# USERS MANAGEMENT
# ==========================================

from master_data.pagination_utils import paginate_queryset


@login_required
@require_permission('users:users/list')
def users_list(request):
    """
    User accounts list matching reference ERP:
    Columns: الاسم, البريد الإلكتروني, مفعل, الدور
    """
    query = request.GET.get('q', '').strip()
    role_filter = request.GET.get('role', '').strip()
    status_filter = request.GET.get('status', '').strip()

    users_qs = User.objects.select_related('role').prefetch_related('assigned_areas').order_by('-created_at')

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

    roles = Role.objects.filter(is_active=True).order_by('display_name')
    areas = Area.objects.all().order_by('name')

    context = {
        'users': page_obj.object_list,
        'page_obj': page_obj,
        'paginator': paginator,
        'roles': roles,
        'areas': areas,
        'query': query,
        'role_filter': role_filter,
        'status_filter': status_filter,
        'active_filters': active_filters,
    }
    return render(request, 'accounts/users_list.html', context)


@login_required
@require_permission('users:users/create')
def user_create(request):
    """
    Handles user creation from modal or dedicated form:
    Fields: الاسم*, البريد الإلكتروني*, الكود, كلمة المرور*, الدور*
    """
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        email = request.POST.get('email', '').strip().lower()
        code = request.POST.get('code', '').strip()
        password = request.POST.get('password', '')
        role_id = request.POST.get('role', '')

        # Server validation
        if not name or not email or not password or not role_id:
            messages.error(request, "يرجى ملء جميع الحقول الإلزامية المطلوبة (الاسم، البريد الإلكتروني، كلمة المرور، الدور).")
            return redirect('users_list')

        # Check unique email
        if User.objects.filter(email__iexact=email).exists() or User.objects.filter(username__iexact=email).exists():
            messages.error(request, f"البريد الإلكتروني '{email}' مسجل بالفعل لمستخدم آخر.")
            return redirect('users_list')

        try:
            role = Role.objects.get(pk=role_id)
        except Role.DoesNotExist:
            messages.error(request, "الدور الوظيفي المحدد غير موجود.")
            return redirect('users_list')

        # Create user
        user = User.objects.create_user(
            username=email,
            email=email,
            password=password,
            name=name,
            code=code,
            role=role,
            is_active=True,
            locale='ar'
        )

        # Handle areas if provided
        area_ids = request.POST.getlist('assigned_areas')
        if area_ids:
            user.assigned_areas.set(area_ids)

        messages.success(request, f"تم إنشاء حساب المستخدم '{user.name}' بنجاح.")
        return redirect('users_list')

    return redirect('users_list')


@login_required
@require_permission('users:users/edit')
def user_edit(request, pk):
    """
    Edit user profile, role, status, code, and assigned areas.
    """
    target_user = get_object_or_404(User, pk=pk)

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        email = request.POST.get('email', '').strip().lower()
        code = request.POST.get('code', '').strip()
        role_id = request.POST.get('role', '')
        mobile = request.POST.get('mobile', '').strip()
        is_active = request.POST.get('is_active') == 'on'

        if not name or not email:
            messages.error(request, "الاسم والبريد الإلكتروني حقول إلزامية.")
            return redirect('user_edit', pk=pk)

        # Check unique email against others
        if User.objects.filter(email__iexact=email).exclude(pk=target_user.pk).exists():
            messages.error(request, f"البريد الإلكتروني '{email}' مسجل لمستخدم آخر.")
            return redirect('user_edit', pk=pk)

        # Safeguard: cannot deactivate last superadmin
        if target_user.is_superuser and not is_active:
            active_superusers = User.objects.filter(is_superuser=True, is_active=True).exclude(pk=target_user.pk).count()
            if active_superusers == 0:
                messages.error(request, "لا يمكن تعطيل مدير النظام الأعلى الأخير للنظام!")
                return redirect('user_edit', pk=pk)

        target_user.name = name
        target_user.email = email
        target_user.username = email
        target_user.code = code
        target_user.mobile = mobile
        target_user.is_active = is_active

        if role_id:
            try:
                target_user.role = Role.objects.get(pk=role_id)
            except Role.DoesNotExist:
                pass
        else:
            target_user.role = None

        target_user.save()

        # Update assigned areas
        area_ids = request.POST.getlist('assigned_areas')
        target_user.assigned_areas.set(area_ids)

        messages.success(request, f"تم تحديث بيانات المستخدم '{target_user.name}' بنجاح.")
        return redirect('users_list')

    roles = Role.objects.filter(is_active=True).order_by('display_name')
    areas = Area.objects.all().order_by('name')
    return render(request, 'accounts/user_edit.html', {
        'target_user': target_user,
        'roles': roles,
        'areas': areas,
    })


@login_required
@require_permission('users:users/edit')
def user_reset_password(request, pk):
    """
    Reset user password with server-side validation.
    """
    target_user = get_object_or_404(User, pk=pk)
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
        messages.success(request, f"تم تغيير كلمة المرور للمستخدم '{target_user.name}' بنجاح.")
        return redirect('user_edit', pk=pk)

    return redirect('user_edit', pk=pk)


@login_required
@require_permission('users:users/edit')
def user_toggle_status(request, pk):
    """
    Toggles is_active on user with superuser lockout safeguard.
    """
    target_user = get_object_or_404(User, pk=pk)

    if target_user.is_active:
        if target_user.is_superuser:
            active_superusers = User.objects.filter(is_superuser=True, is_active=True).exclude(pk=target_user.pk).count()
            if active_superusers == 0:
                messages.error(request, "لا يمكن تعطيل حساب مدير النظام الأعلى الوحيد في النظام!")
                return redirect('users_list')

    target_user.is_active = not target_user.is_active
    target_user.save()
    status_str = "تفعيل" if target_user.is_active else "تعطيل"
    messages.success(request, f"تم {status_str} حساب المستخدم '{target_user.name}' بنجاح.")
    return redirect('users_list')


@login_required
@require_permission('users:users/list')
def users_export(request):
    """
    Exports users list to CSV with UTF-8 BOM for Arabic Excel compatibility.
    """
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="users_list.csv"'
    response.write('\ufeff'.encode('utf8')) # UTF-8 BOM for Excel

    writer = csv.writer(response)
    writer.writerow(['المعرف', 'الاسم', 'البريد الإلكتروني', 'الكود', 'الدور الوظيفي', 'الحالة', 'الهاتف', 'تاريخ الإنشاء'])

    for u in User.objects.select_related('role').order_by('name'):
        status = 'مفعل' if u.is_active else 'معطل'
        role = u.role.display_name if u.role else ('مدير نظام' if u.is_superuser else '-')
        writer.writerow([u.id, u.name, u.email, u.code, role, status, u.mobile, u.created_at.strftime('%Y-%m-%d %H:%M')])

    return response


@login_required
def user_toggle_bypass_location(request, pk):
    """
    Superuser-only control to toggle bypass_location_verification for a user.
    """
    if not (request.user.is_superuser or getattr(request.user, 'is_super_admin', False)):
        messages.error(request, "عذراً، هذه الصلاحية مقصورة حصرياً على مدراء النظام (SuperAdmin).")
        return redirect('users_list')

    target_user = get_object_or_404(User, pk=pk)
    target_user.bypass_location_verification = not target_user.bypass_location_verification
    target_user.save()

    status_str = "تفعيل" if target_user.bypass_location_verification else "تعطيل"
    messages.success(request, f"تم {status_str} تجاوز التحقق من الموقع للمستخدم {target_user.name or target_user.username} بنجاح.")
    return redirect('users_list')


# ==========================================
# ROLES & PERMISSIONS MANAGEMENT
# ==========================================

def get_grouped_permissions():
    """
    Helper to group permissions into domains/modules matching reference ERP.
    """
    MODULE_MAPPING = {
        'accounting': 'الحسابات والخزن (Accounting & Vaults)',
        'purchases': 'المشتريات والموردين (Purchases & Vendors)',
        'sales': 'المبيعات والعملاء (Sales & Customers)',
        'inventory': 'المخازن والأصناف (Inventory & Stocks)',
        'contacts': 'جهات الاتصال (Contacts)',
        'catalog': 'دليل المنتجات (Product Catalog)',
        'treasury': 'الخزينة والمدفوعات (Treasury & Cash)',
        'activities': 'الأنشطة والزيارات (Activities & Visits)',
        'master_data': 'الإعدادات والبيانات الأساسية (Settings & Master Data)',
        'accounts': 'المستخدمون والصلاحيات (Users & RBAC)',
    }

    perms = Permission.objects.select_related('content_type').order_by('content_type__app_label', 'codename')
    grouped = {}

    for p in perms:
        app_label = p.content_type.app_label
        if app_label in ['admin', 'sessions', 'contenttypes']:
            continue
        group_name = MODULE_MAPPING.get(app_label, app_label)
        if group_name not in grouped:
            grouped[group_name] = []
        grouped[group_name].append(p)

    return grouped


@login_required
@require_permission('system:rbac/manage')
def roles_list(request):
    """
    Roles list matching reference ERP:
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
@require_permission('system:rbac/manage')
def role_create(request):
    """
    Create a new role with attributes, tags, and permissions.
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

        role = Role.objects.create(
            name=name,
            display_name=display_name,
            description=description,
            is_active=request.POST.get('is_active') == 'on',
            is_super=request.POST.get('is_super') == 'on',
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

        messages.success(request, f"تم إنشاء الدور '{role.display_name}' بنجاح.")
        return redirect('roles_list')

    all_tags = RoleTag.objects.all().order_by('tag')
    grouped_perms = get_grouped_permissions()
    return render(request, 'accounts/role_form.html', {
        'role': None,
        'all_tags': all_tags,
        'grouped_perms': grouped_perms,
        'is_create': True,
    })


@login_required
@require_permission('system:rbac/manage')
def role_edit(request, pk):
    """
    Role edit dossier matching reference ERP (/settings/roles/edit/<id>):
    Attributes switches, Tags dropdown, Granular Permissions Matrix.
    """
    role = get_object_or_404(Role, pk=pk)

    if request.method == 'POST':
        role.display_name = request.POST.get('display_name', role.display_name).strip()
        role.description = request.POST.get('description', '').strip()

        # Update attributes switches
        role.is_active = request.POST.get('is_active') == 'on'
        role.is_super = request.POST.get('is_super') == 'on'
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

        messages.success(request, f"تم حفظ تعديلات الدور '{role.display_name}' بنجاح.")
        return redirect('roles_list')

    all_tags = RoleTag.objects.all().order_by('tag')
    role_tag_ids = set(role.tags.values_list('id', flat=True))
    role_perm_ids = set(role.permissions.values_list('id', flat=True))
    grouped_perms = get_grouped_permissions()

    return render(request, 'accounts/role_form.html', {
        'role': role,
        'all_tags': all_tags,
        'role_tag_ids': role_tag_ids,
        'role_perm_ids': role_perm_ids,
        'grouped_perms': grouped_perms,
        'is_create': False,
    })


@login_required
@require_permission('system:rbac/manage')
def role_duplicate(request, pk):
    """
    Duplicates an existing role deeply with all attributes, tags, and permissions.
    """
    original = get_object_or_404(Role, pk=pk)
    
    # Generate unique name
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
        is_super=original.is_super,
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

    # Copy tags
    clone.tags.set(original.tags.all())
    # Copy permissions
    clone.permissions.set(original.permissions.all())

    messages.success(request, f"تم استنساخ الدور بنجاح: '{clone.display_name}'.")
    return redirect('role_edit', pk=clone.pk)


@login_required
@require_permission('system:rbac/manage')
def role_delete(request, pk):
    """
    Delete custom role (safeguarded against deleting system roles or roles with assigned users).
    """
    role = get_object_or_404(Role, pk=pk)
    if role.is_system:
        messages.error(request, "لا يمكن حذف الأدوار النظامية الأساسية.")
        return redirect('roles_list')

    if role.users.exists():
        messages.error(request, f"لا يمكن حذف الدور '{role.display_name}' لأنه مرتبط بـ {role.users.count()} مستخدم.")
        return redirect('roles_list')

    name = role.display_name
    role.delete()
    messages.success(request, f"تم حذف الدور '{name}' بنجاح.")
    return redirect('roles_list')
