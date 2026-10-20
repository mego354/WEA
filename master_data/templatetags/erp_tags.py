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
