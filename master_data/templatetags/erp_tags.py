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


@register.simple_tag
def get_admin_dashboard_metrics():
    """
    Computes comprehensive real-time KPIs and recent activity
    for the professional Django Admin Dashboard.
    """
    from accounts.models import User, Role, SecurityAuditLog
    from contacts.models import Contact
    from catalog.models import Product
    from inventory.models import Warehouse, InventoryStock
    from sales.models import SalesOrder, Collection
    from purchases.models import PurchaseOrder
    from treasury.models import Vault
    from activities.models import Visit, Agreement, ApprovalAuditLog
    from django.db.models import Sum, Count, Q
    from django.utils import timezone
    from decimal import Decimal

    today = timezone.now().date()

    # 1. Users & Team
    total_users = User.objects.count()
    active_users = User.objects.filter(is_active=True).count()
    reps_count = User.objects.filter(role__is_rep=True).count()
    managers_count = User.objects.filter(
        Q(role__is_area_manager=True) | Q(role__is_sub_area_manager=True) | Q(role__is_super=True)
    ).count()

    # 2. Contacts
    total_contacts = Contact.objects.count()
    customers_count = Contact.objects.filter(is_customer=True).count()
    suppliers_count = Contact.objects.filter(is_supplier=True).count()

    # 3. Products & Stock
    total_products = Product.objects.count()
    sellable_products = Product.objects.filter(sellable=True, is_active=True).count()
    total_warehouses = Warehouse.objects.filter(is_active=True).count()

    # 4. Visits
    total_visits = Visit.objects.count()
    today_visits = Visit.objects.filter(date=today).count()
    pending_visits = Visit.objects.filter(approval_status='pending').count()
    approved_visits = Visit.objects.filter(approval_status='approved').count()

    # 5. Sales
    sales_qs = SalesOrder.objects.all()
    total_sales_orders = sales_qs.count()
    pending_sales = sales_qs.filter(status__in=['pending', 'manager_approval']).count()
    total_sales_volume = sales_qs.exclude(status='cancelled').aggregate(s=Sum('grand_total'))['s'] or Decimal('0.00')

    # 6. Purchases
    po_qs = PurchaseOrder.objects.all()
    total_po_orders = po_qs.count()
    pending_po = po_qs.filter(status='pending').count()
    total_po_volume = po_qs.exclude(status='cancelled').aggregate(s=Sum('grand_total'))['s'] or Decimal('0.00')

    # 7. Treasury
    total_vaults = Vault.objects.filter(is_active=True).count()
    total_liquidity = Vault.objects.filter(is_active=True).aggregate(s=Sum('current_balance'))['s'] or Decimal('0.00')

    # 8. Approvals & Pending Total
    total_pending_approvals = pending_visits + pending_sales + pending_po

    # 9. Recent Activity
    recent_visits = list(Visit.objects.select_related('contact', 'owner', 'template').order_by('-id')[:6])
    recent_sales = list(SalesOrder.objects.select_related('customer', 'created_by').order_by('-id')[:6])
    recent_purchases = list(PurchaseOrder.objects.select_related('supplier', 'created_by').order_by('-id')[:6])
    recent_security_logs = list(SecurityAuditLog.objects.select_related('actor', 'target_user').order_by('-id')[:6])
    recent_approval_logs = list(ApprovalAuditLog.objects.select_related('actor', 'visit').order_by('-id')[:6])

    return {
        'users': {
            'total': total_users,
            'active': active_users,
            'reps': reps_count,
            'managers': managers_count,
        },
        'contacts': {
            'total': total_contacts,
            'customers': customers_count,
            'suppliers': suppliers_count,
        },
        'catalog': {
            'total': total_products,
            'sellable': sellable_products,
            'warehouses': total_warehouses,
        },
        'visits': {
            'total': total_visits,
            'today': today_visits,
            'pending': pending_visits,
            'approved': approved_visits,
        },
        'sales': {
            'total_orders': total_sales_orders,
            'pending': pending_sales,
            'volume': total_sales_volume,
        },
        'purchases': {
            'total_orders': total_po_orders,
            'pending': pending_po,
            'volume': total_po_volume,
        },
        'treasury': {
            'vaults': total_vaults,
            'liquidity': total_liquidity,
        },
        'approvals': {
            'total_pending': total_pending_approvals,
            'visits': pending_visits,
            'sales': pending_sales,
            'purchases': pending_po,
        },
        'recent_visits': recent_visits,
        'recent_sales': recent_sales,
        'recent_purchases': recent_purchases,
        'recent_security_logs': recent_security_logs,
        'recent_approval_logs': recent_approval_logs,
    }



