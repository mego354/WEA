from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages
from django.http import JsonResponse, HttpResponseForbidden
from django.contrib.auth.mixins import AccessMixin


def has_perm_or_admin(user, perm_codename):
    """
    Checks if a user has a specific permission codename,
    with SuperAdmin / superuser automatic override.
    """
    if not user.is_authenticated:
        return False
    if user.is_superuser or getattr(user, 'is_super_admin', False):
        return True
    if not user.is_active:
        return False
    if hasattr(user, 'has_permission'):
        return user.has_permission(perm_codename)
    if user.role and user.role.is_active:
        return user.role.permissions.filter(codename=perm_codename).exists()
    return False


def require_permission(perm_codename, redirect_url='home'):
    """
    View decorator to enforce backend authorization.
    Rejects unauthorized access with a 403 response for JSON/AJAX or redirect with error message.
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect('login')

            if has_perm_or_admin(request.user, perm_codename):
                return view_func(request, *args, **kwargs)

            # Handle unauthorized access
            if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.path.startswith('/api/'):
                return JsonResponse({
                    'error': 'PermissionDenied',
                    'detail': f'عذراً، ليس لديك صلاحية ({perm_codename}) للقيام بهذا الإجراء.'
                }, status=403)

            messages.error(request, "عذراً، لا تمتلك الصلاحية الكافية للوصول إلى هذه الصفحة أو تنفيذ هذا الإجراء.")
            return redirect(redirect_url)
        return _wrapped_view
    return decorator


class RequirePermissionMixin(AccessMixin):
    """
    CBV mixin enforcing backend permissions.
    """
    required_permission = None

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()

        if self.required_permission and not has_perm_or_admin(request.user, self.required_permission):
            messages.error(request, "عذراً، لا تمتلك الصلاحية الكافية للوصول إلى هذه الصفحة.")
            return redirect('home')

        return super().dispatch(request, *args, **kwargs)
