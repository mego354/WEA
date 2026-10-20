# Pagination and Filtering Architecture & Standards

## 1. Overview and Architecture

The ERP application implements a unified, server-side pagination and active filtering architecture designed for high performance, maintainability, and consistent Arabic RTL user experience.

### Architecture Components:
1. **Utility Layer**: `master_data/pagination_utils.py`
   - `paginate_queryset(request, queryset, default_per_page=25, max_per_page=100)`:
     Safely parses `page` and `per_page` query parameters, enforces boundaries, and gracefully catches `PageNotAnInteger` (defaults to page 1) and `EmptyPage` (defaults to the last page).
2. **Template Tags**: `master_data/templatetags/erp_tags.py`
   - `{% url_replace key=val %}`: Preserves all existing GET query parameters while modifying or appending target keys.
   - `{% url_remove_param param_name %}`: Dynamically removes an active filter key while keeping pagination and other filter parameters intact.
   - `{% smart_page_range paginator current_page %}`: Produces an accessible sliding window of page numbers with ellipsis (e.g. `[1, '...', 4, 5, 6, 7, 8, '...', 20]`).
3. **UI Components**:
   - `templates/components/pagination.html`: Reusable Arabic RTL pagination toolbar with item range, `per_page` selector (15, 25, 50, 100), numbered buttons, and mobile indicator.
   - `templates/components/active_filters.html`: Reusable active filter badge chips with individual dismissal buttons and a "Clear All" reset link.

---

## 2. Standard Usage in Views

To add standardized pagination and active filters to any list view:

```python
from master_data.pagination_utils import paginate_queryset
from django.db.models import Q

@login_required
def example_list_view(request):
    search = request.GET.get('q', '').strip()
    status = request.GET.get('status', '').strip()

    qs = ExampleModel.objects.select_related('related_field').all().order_by('-created_at')

    active_filters = []
    if search:
        qs = qs.filter(Q(name__icontains=search) | Q(code__icontains=search))
        active_filters.append({'label': 'بحث', 'value': search, 'param': 'q'})

    if status:
        qs = qs.filter(status=status)
        active_filters.append({'label': 'الحالة', 'value': status, 'param': 'status'})

    paginator, page_obj = paginate_queryset(request, qs, default_per_page=25)

    context = {
        'items': page_obj.object_list,
        'page_obj': page_obj,
        'paginator': paginator,
        'total_count': paginator.count,  # Zero extra COUNT(*) queries!
        'active_filters': active_filters,
        'selected_q': search,
        'selected_status': status,
    }
    return render(request, 'app/example_list.html', context)
```

---

## 3. Standard Usage in Templates

In your list template:

```html
{% extends 'layouts/base.html' %}
{% load erp_tags %}

{% block content %}
<!-- Active Filter Chips -->
{% include 'components/active_filters.html' %}

<!-- Table or Cards Container -->
<div class="bg-white border border-slate-200 rounded-xl overflow-hidden shadow-xs">
    <div class="overflow-x-auto">
        <table class="w-full text-right text-xs">
            <!-- Table headers and body -->
        </table>
    </div>

    <!-- Reusable Pagination Toolbar -->
    {% include 'components/pagination.html' %}
</div>
{% endblock %}
```

---

## 4. Query Parameter Preservation Rules

1. Changing pages preserves all applied filters:
   `<a href="{% url_replace page=page_obj.next_page_number %}">`
2. Changing `per_page` resets to page 1 while keeping active filters:
   `<option value="{% url_replace per_page=50 page=1 %}">50</option>`
3. Dismissing a single filter chip removes that parameter and resets to page 1:
   `<a href="{% url_remove_param filter.param page=1 %}">`
4. Clicking "Clear All Filters" navigates to the clean URL (`request.path`).

---

## 5. Security & Data Integrity Safeguards

- **Queryset Authorization**: Pagination is applied strictly to the user's permission-filtered queryset. Users cannot manipulate `page` or `per_page` to access unauthorized records.
- **Allowed Sort Fields**: Sort parameters are validated against an explicit whitelist of field names.
- **No Raw SQL**: All filtering and pagination is executed via Django ORM `Paginator` and `slice` operations.
- **Graceful Error Handling**: Non-integer or negative page values safely fall back to page 1; values exceeding the last page safely fall back to the last page.
