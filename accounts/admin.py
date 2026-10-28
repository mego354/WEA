from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import UserChangeForm, UserCreationForm
from django.urls import reverse
from django.utils.html import format_html
from .models import User, Role, RoleTag, SecurityAuditLog


class CustomUserChangeForm(UserChangeForm):
    new_password = forms.CharField(
        label="تعيين كلمة مرور جديدة مباشرة",
        required=False,
        widget=forms.PasswordInput(
            attrs={
                'placeholder': 'أدخل كلمة المرور الجديدة أو اتركها فارغة للإبقاء على الحالية',
                'autocomplete': 'new-password',
                'style': 'width: 100%; max-width: 400px; padding: 6px 10px; border: 1px solid #cbd5e1; border-radius: 6px;'
            }
        ),
        help_text="يمكنك إدخال كلمة مرور جديدة وتأكيدها هنا وتحديث الحساب مباشرة عند الحفظ."
    )
    confirm_new_password = forms.CharField(
        label="تأكيد كلمة المرور الجديدة",
        required=False,
        widget=forms.PasswordInput(
            attrs={
                'placeholder': 'أعد إدخال كلمة المرور الجديدة للتأكيد',
                'autocomplete': 'new-password',
                'style': 'width: 100%; max-width: 400px; padding: 6px 10px; border: 1px solid #cbd5e1; border-radius: 6px;'
            }
        ),
    )

    class Meta(UserChangeForm.Meta):
        model = User
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if 'role' in self.fields:
            self.fields['role'].queryset = Role.get_supported_roles()

    def clean(self):
        cleaned_data = super().clean()
        new_pw = cleaned_data.get('new_password')
        confirm_pw = cleaned_data.get('confirm_new_password')

        if new_pw or confirm_pw:
            if new_pw != confirm_pw:
                raise forms.ValidationError({'confirm_new_password': "كلمتا المرور غير متطابقتين."})
            if len(new_pw) < 6:
                raise forms.ValidationError({'new_password': "يجب ألا تقل كلمة المرور عن 6 أحرف."})

        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        new_pw = self.cleaned_data.get('new_password')
        if new_pw:
            user.set_password(new_pw)
        if commit:
            user.save()
            self.save_m2m()
        return user


class CustomUserCreationForm(UserCreationForm):
    class Meta:
        model = User
        fields = ('username', 'name', 'email', 'mobile', 'role')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if 'name' in self.fields:
            self.fields['name'].required = True
        if 'role' in self.fields:
            self.fields['role'].queryset = Role.get_supported_roles()


@admin.register(RoleTag)
class RoleTagAdmin(admin.ModelAdmin):
    list_display = ('display_name', 'tag')
    search_fields = ('tag', 'display_name')
    ordering = ('tag',)


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = (
        'display_name', 'name', 'is_active_badge', 'is_system_badge',
        'is_manager_badge', 'is_rep', 'permissions_count', 'users_count', 'updated_at'
    )
    list_filter = ('is_active', 'is_system', 'is_super', 'is_area_manager', 'is_sub_area_manager', 'is_rep')
    search_fields = ('name', 'display_name', 'description')
    filter_horizontal = ('permissions', 'tags')
    actions = ['activate_roles', 'deactivate_roles']

    def is_active_badge(self, obj):
        if obj.is_active:
            return format_html('<span class="admin-pill admin-pill-success">مفعل</span>')
        return format_html('<span class="admin-pill admin-pill-danger">معطل</span>')
    is_active_badge.short_description = "الحالة"

    def is_system_badge(self, obj):
        if obj.is_system:
            return format_html('<span class="admin-pill admin-pill-purple">نظامي</span>')
        return format_html('<span class="admin-pill admin-pill-neutral">مخصص</span>')
    is_system_badge.short_description = "النوع"

    def is_manager_badge(self, obj):
        if obj.is_manager_role:
            return format_html('<span class="admin-pill admin-pill-info">مدير إدارة</span>')
        return format_html('<span class="admin-pill admin-pill-neutral">كادر تنفيذي</span>')
    is_manager_badge.short_description = "المستوى"

    def permissions_count(self, obj):
        return obj.permissions.count()
    permissions_count.short_description = "عدد الصلاحيات"

    def users_count(self, obj):
        return obj.users.count()
    users_count.short_description = "عدد المستخدمين"

    @admin.action(description="تفعيل الأدوار المحددة")
    def activate_roles(self, request, queryset):
        queryset.update(is_active=True)

    @admin.action(description="تعطيل الأدوار المحددة")
    def deactivate_roles(self, request, queryset):
        queryset.filter(is_system=False).update(is_active=False)


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    form = CustomUserChangeForm
    add_form = CustomUserCreationForm

    list_display = (
        'username', 'name', 'code', 'mobile', 'role_badge',
        'assigned_areas_display', 'is_active', 'is_staff', 'is_superuser',
        'bypass_location_verification', 'change_password_button'
    )
    list_filter = ('role', 'is_active', 'is_staff', 'is_superuser', 'bypass_location_verification', 'created_at')
    search_fields = ('username', 'name', 'code', 'mobile', 'email')
    filter_horizontal = ('assigned_areas', 'user_permissions', 'groups')
    ordering = ('-date_joined',)
    actions = [
        'reset_password_to_wea4444',
        'activate_users',
        'deactivate_users',
        'enable_location_bypass',
        'disable_location_bypass'
    ]

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "role":
            kwargs["queryset"] = Role.get_supported_roles()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    fieldsets = (
        ('معلومات الحساب الأساسية وتغيير كلمة المرور', {
            'fields': (
                'username', 'password',
                ('new_password', 'confirm_new_password'),
                'name', 'code', 'email', 'mobile', 'avatar', 'locale'
            )
        }),
        ('الدور والصلاحيات الجغرافية', {
            'fields': ('role', 'assigned_areas', 'bypass_location_verification')
        }),
        ('أذونات النظام وحالة الحساب', {
            'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')
        }),
        ('التواريخ والسجلات', {
            'fields': ('last_login', 'date_joined', 'created_at', 'updated_at')
        }),
    )
    readonly_fields = ('created_at', 'updated_at', 'last_login', 'date_joined')

    add_fieldsets = (
        (
            'إنشاء حساب جديد',
            {
                'classes': ('wide',),
                'fields': ('username', 'name', 'role', 'email', 'mobile', 'password1', 'password2'),
            },
        ),
    )

    def role_badge(self, obj):
        if obj.role:
            cls = "admin-pill-purple" if obj.role.is_manager_role else "admin-pill-info"
            return format_html('<span class="admin-pill {}">{}</span>', cls, obj.role.display_name)
        if obj.is_superuser:
            return format_html('<span class="admin-pill admin-pill-danger">مدير نظام (SuperAdmin)</span>')
        return format_html('<span class="admin-pill admin-pill-neutral">بدون دور</span>')
    role_badge.short_description = "الدور الوظيفي"

    def assigned_areas_display(self, obj):
        areas = list(obj.assigned_areas.values_list('name', flat=True)[:3])
        count = obj.assigned_areas.count()
        if not areas:
            return "-"
        text = ", ".join(areas)
        if count > 3:
            text += f" (+{count - 3})"
        return text
    assigned_areas_display.short_description = "المناطق المعينة"

    def change_password_button(self, obj):
        url = reverse('admin:auth_user_password_change', args=[obj.pk])
        return format_html(
            '<a href="{}" class="button" style="background:#4f46e5 !important; color:#ffffff !important; padding:4px 10px !important; border-radius:6px; font-size:11px; font-weight:700; text-decoration:none; display:inline-flex; align-items:center; gap:4px; box-shadow:0 1px 2px rgba(0,0,0,0.1);">'
            '🔑 تعديل كلمة المرور'
            '</a>',
            url
        )
    change_password_button.short_description = "كلمة المرور"

    def save_model(self, request, obj, form, change):
        new_pw = form.cleaned_data.get('new_password')
        if change and new_pw:
            SecurityAuditLog.objects.create(
                actor=request.user,
                action_type='USER_PASSWORD_RESET',
                target_user=obj,
                description=f"تم تحديث كلمة مرور المستخدم {obj.username} مباشرة من صفحة المستخدم بواسطة {request.user.username}.",
                ip_address=request.META.get('REMOTE_ADDR')
            )
        super().save_model(request, obj, form, change)

    def user_change_password(self, request, id, form_url=""):
        response = super().user_change_password(request, id, form_url)
        if response.status_code == 302:
            target_user = self.get_object(request, id)
            if target_user:
                SecurityAuditLog.objects.create(
                    actor=request.user,
                    action_type='USER_PASSWORD_RESET',
                    target_user=target_user,
                    description=f"تم تغيير كلمة مرور المستخدم {target_user.username} عبر نموذج تغيير كلمة المرور بواسطة {request.user.username}.",
                    ip_address=request.META.get('REMOTE_ADDR')
                )
        return response

    @admin.action(description="إعادة تعيين كلمة المرور إلى Wea@4444 للمستخدمين المحددين")
    def reset_password_to_wea4444(self, request, queryset):
        count = 0
        for user in queryset:
            user.set_password("Wea@4444")
            user.save()
            count += 1
            SecurityAuditLog.objects.create(
                actor=request.user,
                action_type='USER_PASSWORD_RESET',
                target_user=user,
                description=f"تمت إعادة تعيين كلمة مرور المستخدم {user.username} إلى 'Wea@4444' من لوحة التحكم بواسطة {request.user.username}.",
                ip_address=request.META.get('REMOTE_ADDR')
            )
        self.message_user(request, f"تمت إعادة تعيين كلمة المرور إلى 'Wea@4444' بنجاح لـ {count} مستخدم وتم تسجيل ذلك في سجل التدقيق الأمني.")

    @admin.action(description="تفعيل حسابات المستخدمين المحددة")
    def activate_users(self, request, queryset):
        queryset.update(is_active=True)

    @admin.action(description="تعطيل حسابات المستخدمين المحددة")
    def deactivate_users(self, request, queryset):
        queryset.exclude(is_superuser=True).update(is_active=False)

    @admin.action(description="منح صلاحية تجاوز التحقق الجغرافي للموقع")
    def enable_location_bypass(self, request, queryset):
        queryset.update(bypass_location_verification=True)

    @admin.action(description="إلغاء صلاحية تجاوز التحقق الجغرافي للموقع")
    def disable_location_bypass(self, request, queryset):
        queryset.update(bypass_location_verification=False)


@admin.register(SecurityAuditLog)
class SecurityAuditLogAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'action_type_badge', 'actor', 'target_user', 'target_role', 'ip_address', 'description_short')
    list_filter = ('action_type', 'created_at')
    search_fields = ('description', 'actor__username', 'actor__name', 'target_user__username', 'ip_address')
    date_hierarchy = 'created_at'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def action_type_badge(self, obj):
        return format_html('<span class="admin-pill admin-pill-neutral">{}</span>', obj.get_action_type_display())
    action_type_badge.short_description = "نوع العملية"

    def description_short(self, obj):
        if len(obj.description) > 60:
            return obj.description[:60] + "..."
        return obj.description
    description_short.short_description = "التفاصيل"
