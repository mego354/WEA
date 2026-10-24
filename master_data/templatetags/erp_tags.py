from django import template
from urllib.parse import urlencode

register = template.Library()


@register.simple_tag(takes_context=True)
def url_replace(context, **kwargs):
    """
    Safely replace or add GET parameters while preserving existing ones.
    Usage:
        <a href="{% url_replace page=page_obj.next_page_number %}">التالي</a>
        <a href="{% url_replace per_page=50 page=1 %}">50 سجل</a>
    """
    request = context.get('request')
    if not request:
        return '?' + urlencode({k: v for k, v in kwargs.items() if v is not None and v != ''})

    dict_ = request.GET.copy()
    for key, value in kwargs.items():
        if value is None or value == '':
            if key in dict_:
                del dict_[key]
        else:
            dict_[key] = str(value)
    
    encoded = dict_.urlencode()
    return f"?{encoded}" if encoded else "?"


@register.simple_tag(takes_context=True)
def url_remove_param(context, param_name, **kwargs):
    """
    Safely remove a dynamic parameter by name while preserving other parameters.
    Usage:
        <a href="{% url_remove_param filter.param page=1 %}">إزالة</a>
    """
    request = context.get('request')
    if not request:
        return "?"
    dict_ = request.GET.copy()
    if param_name and param_name in dict_:
        del dict_[param_name]
    for key, value in kwargs.items():
        if value is None or value == '':
            if key in dict_:
                del dict_[key]
        else:
            dict_[key] = str(value)
    encoded = dict_.urlencode()
    return f"?{encoded}" if encoded else "?"


@register.simple_tag
def smart_page_range(paginator, current_page, on_each_side=2, on_ends=1):
    """
    Returns a list of page numbers and ellipsis strings for smart pagination.
    Example output for page 6 of 20:
        [1, '...', 4, 5, 6, 7, 8, '...', 20]
    """
    if not paginator or paginator.num_pages <= 1:
        return []

    num_pages = paginator.num_pages
    current = int(current_page) if current_page else 1

    if num_pages <= (on_each_side * 2) + (on_ends * 2) + 2:
        return list(range(1, num_pages + 1))

    pages = []
    
    # Left ends
    for p in range(1, on_ends + 1):
        pages.append(p)

    left_start = max(on_ends + 1, current - on_each_side)
    left_end = min(num_pages - on_ends, current + on_each_side)

    if left_start > on_ends + 1:
        pages.append('...')

    for p in range(left_start, left_end + 1):
        if p not in pages:
            pages.append(p)

    if left_end < num_pages - on_ends:
        pages.append('...')

    # Right ends
    for p in range(num_pages - on_ends + 1, num_pages + 1):
        if p not in pages:
            pages.append(p)

    return pages


@register.filter
def get_item(dictionary, key):
    """Safely get dictionary item in templates."""
    if isinstance(dictionary, dict):
        return dictionary.get(key)
    return None


@register.filter(name='has_permission')
def has_permission_filter(user, perm_codename):
    """
    Template filter to check user permission:
    Usage: {% if request.user|has_permission:'purchases:orders/create' %}
    """
    if not user or not user.is_authenticated:
        return False
    if hasattr(user, 'has_permission'):
        return user.has_permission(perm_codename)
    return False


@register.filter(name='can_access_module')
def can_access_module_filter(user, module_key):
    """
    Template filter to check top-level module access:
    Usage: {% if request.user|can_access_module:'purchases' %}
    """
    if not user or not user.is_authenticated:
        return False
    if hasattr(user, 'has_permission'):
        return user.has_permission(f"module:{module_key}")
    return False


@register.filter(name='is_super_admin')
def is_super_admin_filter(user):
    """
    Template filter to check whether user is SuperAdmin:
    Usage: {% if request.user|is_super_admin %}
    """
    if not user or not user.is_authenticated:
        return False
    return getattr(user, 'is_super_admin', False) or user.is_superuser


@register.filter(name='is_manager')
def is_manager_filter(user):
    """
    Template filter to check if user has manager role or is super admin:
    Usage: {% if request.user|is_manager %}
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser or getattr(user, 'is_super_admin', False):
        return True
    if getattr(user, 'role', None):
        return getattr(user.role, 'is_manager_role', False)
    return False


