from django.core.paginator import Paginator


def paginate_queryset(request, queryset, default_per_page=25, max_per_page=100):
    """
    Standardized, safe server-side pagination helper across all ERP modules.
    - Extracts `per_page` parameter from request, bounded by [1, max_per_page].
    - Safely returns (paginator, page_obj).
    - `get_page` automatically handles invalid and out-of-range pages gracefully.
    """
    try:
        raw_per_page = request.GET.get('per_page')
        if raw_per_page:
            per_page = int(raw_per_page)
            if per_page <= 0:
                per_page = default_per_page
            elif per_page > max_per_page:
                per_page = max_per_page
        else:
            per_page = default_per_page
    except (ValueError, TypeError):
        per_page = default_per_page

    paginator = Paginator(queryset, per_page)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    return paginator, page_obj
