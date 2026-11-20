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
def url_remove_param(context, param_name, value=None, **kwargs):
    """
    Safely remove a dynamic parameter (or a single value from a multi-value parameter)
    by name while preserving other parameters.
    Usage:
        <a href="{% url_remove_param filter.param value=filter.remove_value page=1 %}">إزالة</a>
    """
    request = context.get('request')
    if not request:
        return "?"
    dict_ = request.GET.copy()
    if param_name and param_name in dict_:
        if value is not None and value != '':
            target = str(value)
            remaining = [v for v in dict_.getlist(param_name) if v != target]
            if remaining:
                dict_.setlist(param_name, remaining)
            else:
                del dict_[param_name]
        else:
            del dict_[param_name]
    for key, val in kwargs.items():
        if val is None or val == '':
            if key in dict_:
                del dict_[key]
        else:
            dict_[key] = str(val)
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


@register.filter(name='stat_number')
def stat_number_filter(value):
    """
    Format numeric statistics cleanly for KPI/stat boxes:
    rounds decimals to nearest integer for large amounts (>= 100) or up to 1 decimal place
    for small amounts so the entire number fits comfortably on mobile screens without truncation.
    """
    if value is None or value == '':
        return '0'
    try:
        num = float(value)
    except (ValueError, TypeError):
        return str(value)
    if abs(num) >= 100 or num == int(num):
        return f"{int(round(num)):,}"
    return f"{round(num, 1):,}".rstrip('0').rstrip('.')


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


@register.simple_tag
def get_erp_attachments(obj):
    """Returns ERPAttachment queryset for any model instance."""
    if not obj or not getattr(obj, 'pk', None):
        return []
    from django.contrib.contenttypes.models import ContentType
    from master_data.models import ERPAttachment
    ct = ContentType.objects.get_for_model(obj.__class__)
    return ERPAttachment.objects.filter(content_type=ct, object_id=obj.pk).select_related('uploaded_by')


_NAV_URL_MAP = {
    # Top-level items
    'home': ('', 'home'),
    'agenda': ('', 'agenda'),
    'agenda_root': ('', 'agenda'),
    'agenda_todo_add': ('', 'agenda'),
    'agenda_todo_toggle': ('', 'agenda'),
    'agenda_todo_delete': ('', 'agenda'),
    'contacts_list': ('', 'contacts'),
    'contact_create': ('', 'contacts'),
    'contacts_export': ('', 'contacts'),
    'contacts_import': ('', 'contacts'),
    'contacts_import_template': ('', 'contacts'),
    'contact_detail': ('', 'contacts'),
    'contact_detail_overview': ('', 'contacts'),
    'contact_edit': ('', 'contacts'),
    'contact_delete': ('', 'contacts'),
    'contact_update_status': ('', 'contacts'),
    'approvals_hub': ('', 'approvals'),
    'approvals_hub_root': ('', 'approvals'),

    # Catalog
    'products_list': ('submenu-catalog', 'products'),
    'product_create': ('submenu-catalog', 'products'),
    'products_export': ('submenu-catalog', 'products'),
    'product_import': ('submenu-catalog', 'products'),
    'product_import_template': ('submenu-catalog', 'products'),
    'product_detail': ('submenu-catalog', 'products'),
    'product_edit': ('submenu-catalog', 'products'),
    'product_delete': ('submenu-catalog', 'products'),
    'categories_list': ('submenu-catalog', 'categories'),
    'categories_export': ('submenu-catalog', 'categories'),
    'category_edit': ('submenu-catalog', 'categories'),
    'category_delete': ('submenu-catalog', 'categories'),
    'product_categories_alias': ('submenu-catalog', 'categories'),

    # Activities
    'planned_visits_list': ('submenu-activities', 'planned_visits'),
    'planned_visit_add_item': ('submenu-activities', 'planned_visits'),
    'planned_visits_bulk_add': ('submenu-activities', 'planned_visits'),
    'planned_visits_export': ('submenu-activities', 'planned_visits'),
    'planned_visit_item_delete': ('submenu-activities', 'planned_visits'),
    'planned_visit_item_execute': ('submenu-activities', 'planned_visits'),
    'plan_action': ('submenu-activities', 'planned_visits'),
    'plan_action_alias': ('submenu-activities', 'planned_visits'),
    'visits_list': ('submenu-activities', 'visits'),
    'visit_create': ('submenu-activities', 'visits'),
    'visits_export': ('submenu-activities', 'visits'),
    'visit_detail': ('submenu-activities', 'visits'),
    'visit_edit': ('submenu-activities', 'visits'),
    'visit_delete': ('submenu-activities', 'visits'),
    'visit_update_answers': ('submenu-activities', 'visits'),
    'visit_action': ('submenu-activities', 'visits'),
    'agreements_list': ('submenu-activities', 'agreements'),
    'agreements_bulk_status': ('submenu-activities', 'agreements'),
    'agreement_create': ('submenu-activities', 'agreements'),
    'agreements_export': ('submenu-activities', 'agreements'),
    'agreement_detail': ('submenu-activities', 'agreements'),
    'agreement_edit': ('submenu-activities', 'agreements'),
    'agreement_delete': ('submenu-activities', 'agreements'),
    'agreement_action': ('submenu-activities', 'agreements'),

    # Sales
    'sales_orders_list': ('submenu-sales', 'sales_orders'),
    'sales_orders_export': ('submenu-sales', 'sales_orders'),
    'sales_order_create': ('submenu-sales', 'sales_orders'),
    'sales_order_detail': ('submenu-sales', 'sales_orders'),
    'sales_order_pdf': ('submenu-sales', 'sales_orders'),
    'sales_order_edit': ('submenu-sales', 'sales_orders'),
    'sales_order_delete': ('submenu-sales', 'sales_orders'),
    'sales_order_action': ('submenu-sales', 'sales_orders'),
    'sales_order_update_payment_status': ('submenu-sales', 'sales_orders'),
    'sales_return_orders_list': ('submenu-sales', 'sales_returns'),
    'sales_return_orders_export': ('submenu-sales', 'sales_returns'),
    'sales_return_order_create': ('submenu-sales', 'sales_returns'),
    'sales_return_order_detail': ('submenu-sales', 'sales_returns'),
    'sales_return_order_delete': ('submenu-sales', 'sales_returns'),
    'sales_return_order_action': ('submenu-sales', 'sales_returns'),
    'sales_return_order_print': ('submenu-sales', 'sales_returns'),
    'sales_return_order_pdf': ('submenu-sales', 'sales_returns'),
    'sales_return_orders_alias': ('submenu-sales', 'sales_returns'),
    'sales_return_order_create_alias': ('submenu-sales', 'sales_returns'),
    'sales_return_orders_export_alias': ('submenu-sales', 'sales_returns'),
    'sales_return_order_detail_alias': ('submenu-sales', 'sales_returns'),
    'sales_return_order_action_alias': ('submenu-sales', 'sales_returns'),
    'sales_return_order_print_alias': ('submenu-sales', 'sales_returns'),
    'collections_list': ('submenu-sales', 'collections'),
    'collections_export': ('submenu-sales', 'collections'),
    'collection_create': ('submenu-sales', 'collections'),
    'accounting_customers_list': ('submenu-sales', 'accounting_customers'),
    'accounting_customers_export': ('submenu-sales', 'accounting_customers'),
    'accounting_customers_root_alias': ('submenu-sales', 'accounting_customers'),
    'sales_customers_list': ('submenu-sales', 'accounting_customers'),
    'sales_customer_create': ('submenu-sales', 'accounting_customers'),
    'sales_customer_detail': ('submenu-sales', 'accounting_customers'),
    'customer_statement_pdf': ('submenu-sales', 'accounting_customers'),
    'sales_customer_edit': ('submenu-sales', 'accounting_customers'),
    'customer_transactions_list': ('submenu-sales', 'customer_transactions'),
    'customer_transactions_export': ('submenu-sales', 'customer_transactions'),
    'customer_transactions_root_alias': ('submenu-sales', 'customer_transactions'),

    # Purchases & Vendor Ledger
    'purchase_orders_list': ('submenu-purchases', 'purchase_orders'),
    'purchase_order_create': ('submenu-purchases', 'purchase_orders'),
    'purchase_orders_export': ('submenu-purchases', 'purchase_orders'),
    'purchase_order_detail': ('submenu-purchases', 'purchase_orders'),
    'purchase_order_edit': ('submenu-purchases', 'purchase_orders'),
    'purchase_order_delete': ('submenu-purchases', 'purchase_orders'),
    'purchase_order_update_payment_status': ('submenu-purchases', 'purchase_orders'),
    'purchase_order_split': ('submenu-purchases', 'purchase_orders'),
    'purchase_order_action': ('submenu-purchases', 'purchase_orders'),
    'purchase_order_print': ('submenu-purchases', 'purchase_orders'),
    'purchase_order_pdf': ('submenu-purchases', 'purchase_orders'),
    'purchase_return_orders_list': ('submenu-purchases', 'purchase_returns'),
    'purchase_return_order_create': ('submenu-purchases', 'purchase_returns'),
    'purchase_return_orders_export': ('submenu-purchases', 'purchase_returns'),
    'purchase_return_order_detail': ('submenu-purchases', 'purchase_returns'),
    'purchase_return_order_delete': ('submenu-purchases', 'purchase_returns'),
    'purchase_return_order_action': ('submenu-purchases', 'purchase_returns'),
    'purchase_return_order_print': ('submenu-purchases', 'purchase_returns'),
    'purchase_return_order_pdf': ('submenu-purchases', 'purchase_returns'),
    'purchase_return_orders_alias': ('submenu-purchases', 'purchase_returns'),
    'purchase_return_order_create_alias': ('submenu-purchases', 'purchase_returns'),
    'purchase_return_orders_export_alias': ('submenu-purchases', 'purchase_returns'),
    'purchase_return_order_detail_alias': ('submenu-purchases', 'purchase_returns'),
    'purchase_return_order_action_alias': ('submenu-purchases', 'purchase_returns'),
    'purchase_return_order_print_alias': ('submenu-purchases', 'purchase_returns'),
    'vendor_payments_list': ('submenu-purchases', 'vendor_payments'),
    'vendor_payments_export': ('submenu-purchases', 'vendor_payments'),
    'vendor_payment_create': ('submenu-purchases', 'vendor_payments'),
    'vendor_payments_alias': ('submenu-purchases', 'vendor_payments'),
    'vendor_payment_create_alias': ('submenu-purchases', 'vendor_payments'),
    'vendor_payment_requests_list': ('submenu-purchases', 'vendor_payment_requests'),
    'vendor_payment_request_create': ('submenu-purchases', 'vendor_payment_requests'),
    'vendor_payment_requests_export': ('submenu-purchases', 'vendor_payment_requests'),
    'vendor_payment_request_detail': ('submenu-purchases', 'vendor_payment_requests'),
    'vendor_payment_request_action': ('submenu-purchases', 'vendor_payment_requests'),
    'vendor_payment_requests_alias': ('submenu-purchases', 'vendor_payment_requests'),
    'vendor_payment_request_create_alias': ('submenu-purchases', 'vendor_payment_requests'),
    'vendor_payment_request_export_alias': ('submenu-purchases', 'vendor_payment_requests'),
    'vendor_payment_request_detail_alias': ('submenu-purchases', 'vendor_payment_requests'),
    'vendor_payment_request_action_alias': ('submenu-purchases', 'vendor_payment_requests'),
    'accounting_vendors_list': ('submenu-purchases', 'accounting_vendors'),
    'accounting_vendors_export': ('submenu-purchases', 'accounting_vendors'),
    'accounting_vendors_alias': ('submenu-purchases', 'accounting_vendors'),
    'vendor_statement_pdf': ('submenu-purchases', 'accounting_vendors'),
    'vendor_transactions_list': ('submenu-purchases', 'vendor_transactions'),
    'vendor_transactions_export': ('submenu-purchases', 'vendor_transactions'),
    'vendor_transactions_alias': ('submenu-purchases', 'vendor_transactions'),

    # Inventory
    'inventory_stock_list': ('submenu-inventory', 'inventory_stock'),
    'inventory_stock_export': ('submenu-inventory', 'inventory_stock'),
    'warehouses_list': ('submenu-inventory', 'warehouses'),
    'warehouses_export': ('submenu-inventory', 'warehouses'),
    'warehouse_create': ('submenu-inventory', 'warehouses'),
    'warehouse_edit': ('submenu-inventory', 'warehouses'),
    'warehouse_delete': ('submenu-inventory', 'warehouses'),
    'inventory_memos_list': ('submenu-inventory', 'inventory_memos'),
    'inventory_memos_export': ('submenu-inventory', 'inventory_memos'),
    'inventory_memo_create': ('submenu-inventory', 'inventory_memos'),
    'inventory_memo_detail': ('submenu-inventory', 'inventory_memos'),
    'product_transfers_list': ('submenu-inventory', 'inventory_memos'),
    'product_transfers_export': ('submenu-inventory', 'inventory_memos'),
    'product_transfer_create': ('submenu-inventory', 'inventory_memos'),
    'product_transfer_detail': ('submenu-inventory', 'inventory_memos'),
    'product_transfer_action': ('submenu-inventory', 'inventory_memos'),

    # Treasury
    'vaults_list': ('submenu-treasury', 'vaults'),
    'vaults_export': ('submenu-treasury', 'vaults'),
    'vault_detail': ('submenu-treasury', 'vaults'),
    'vault_create': ('submenu-treasury', 'vaults'),
    'vault_edit': ('submenu-treasury', 'vaults'),
    'vault_delete': ('submenu-treasury', 'vaults'),
    'vault_transactions_list': ('submenu-treasury', 'vault_transactions'),
    'vault_transactions_export': ('submenu-treasury', 'vault_transactions'),
    'vault_transaction_reverse': ('submenu-treasury', 'vault_transactions'),
    'vault_transfer': ('submenu-treasury', 'vault_transactions'),
    'vault_deposit': ('submenu-treasury', 'vault_transactions'),
    'vault_withdraw': ('submenu-treasury', 'vault_transactions'),

    # Performance
    'performance_root': ('submenu-performance', 'performance_overview'),
    'performance_overview': ('submenu-performance', 'performance_overview'),
    'performance_analysis': ('submenu-performance', 'performance_analysis'),
    'performance_analysis_export': ('submenu-performance', 'performance_analysis'),
    'performance_daily': ('submenu-performance', 'performance_daily'),
    'performance_daily_export': ('submenu-performance', 'performance_daily'),
    'performance_detailed': ('submenu-performance', 'performance_detailed'),
    'performance_detailed_export': ('submenu-performance', 'performance_detailed'),

    # Reports
    'reports_hub': ('submenu-reports', 'reports_hub'),
    'report_ar_aging': ('submenu-reports', 'report_ar_aging'),
    'report_ar_aging_export': ('submenu-reports', 'report_ar_aging'),
    'report_ar_aging_print': ('submenu-reports', 'report_ar_aging'),
    'report_trial_balance': ('submenu-reports', 'report_trial_balance'),
    'report_trial_balance_export': ('submenu-reports', 'report_trial_balance'),
    'report_trial_balance_print': ('submenu-reports', 'report_trial_balance'),
    'report_net_sales': ('submenu-reports', 'report_net_sales'),
    'report_net_sales_export': ('submenu-reports', 'report_net_sales'),
    'report_customer_360': ('submenu-reports', 'report_customer_360'),
    'report_customer_360_export': ('submenu-reports', 'report_customer_360'),
    'report_item_sales_by_customer': ('submenu-reports', 'report_item_sales_by_customer'),
    'report_item_sales_by_customer_export': ('submenu-reports', 'report_item_sales_by_customer'),
    'report_delivery_stock': ('submenu-reports', 'report_delivery_stock'),
    'report_delivery_stock_export': ('submenu-reports', 'report_delivery_stock'),
    'report_item_purchases': ('submenu-reports', 'report_item_purchases'),
    'report_item_purchases_export': ('submenu-reports', 'report_item_purchases'),
    'report_agreements_roi': ('submenu-reports', 'report_agreements_roi'),
    'report_agreements_roi_export': ('submenu-reports', 'report_agreements_roi'),

    # Settings
    'users_list': ('submenu-settings', 'users'),
    'users_list_root_alias': ('submenu-settings', 'users'),
    'users_settings': ('submenu-settings', 'users'),
    'user_create': ('submenu-settings', 'users'),
    'user_create_root_alias': ('submenu-settings', 'users'),
    'user_create_page': ('submenu-settings', 'users'),
    'user_create_page_root_alias': ('submenu-settings', 'users'),
    'user_detail': ('submenu-settings', 'users'),
    'user_detail_root_alias': ('submenu-settings', 'users'),
    'user_edit': ('submenu-settings', 'users'),
    'user_edit_root_alias': ('submenu-settings', 'users'),
    'user_effective_permissions': ('submenu-settings', 'users'),
    'user_reset_password': ('submenu-settings', 'users'),
    'user_reset_password_root_alias': ('submenu-settings', 'users'),
    'user_toggle_status': ('submenu-settings', 'users'),
    'user_toggle_status_root_alias': ('submenu-settings', 'users'),
    'user_delete': ('submenu-settings', 'users'),
    'user_delete_root_alias': ('submenu-settings', 'users'),
    'user_toggle_bypass_location': ('submenu-settings', 'users'),
    'user_toggle_bypass_location_root_alias': ('submenu-settings', 'users'),
    'users_export': ('submenu-settings', 'users'),
    'roles_list': ('submenu-settings', 'roles'),
    'roles_list_root_alias': ('submenu-settings', 'roles'),
    'role_create': ('submenu-settings', 'roles'),
    'role_edit': ('submenu-settings', 'roles'),
    'role_duplicate': ('submenu-settings', 'roles'),
    'role_delete': ('submenu-settings', 'roles'),
    'audit_logs_list': ('submenu-settings', 'audit_logs'),
    'audit_logs_export': ('submenu-settings', 'audit_logs'),
    'audit_log_detail': ('submenu-settings', 'audit_logs'),
    'visit_templates_list': ('submenu-settings', 'visit_templates'),
    'visit_template_create': ('submenu-settings', 'visit_templates'),
    'visit_template_edit': ('submenu-settings', 'visit_templates'),
    'visit_template_preview': ('submenu-settings', 'visit_templates'),
    'visit_template_delete': ('submenu-settings', 'visit_templates'),
    'visit_template_toggle_status': ('submenu-settings', 'visit_templates'),
    'template_question_add': ('submenu-settings', 'visit_templates'),
    'template_question_edit': ('submenu-settings', 'visit_templates'),
    'template_question_delete': ('submenu-settings', 'visit_templates'),
    'template_questions_reorder': ('submenu-settings', 'visit_templates'),
    'branding_settings': ('submenu-settings', 'branding_settings'),
    'r2_storage_settings': ('submenu-settings', 'r2_storage_settings'),
    'location_settings': ('submenu-settings', 'location_settings'),
    'areas_settings': ('submenu-settings', 'areas_settings'),
    'area_create': ('submenu-settings', 'areas_settings'),
    'area_edit': ('submenu-settings', 'areas_settings'),
    'area_delete': ('submenu-settings', 'areas_settings'),
    'agreements_settings': ('submenu-settings', 'agreements_settings'),
    'agreement_type_create': ('submenu-settings', 'agreements_settings'),
    'agreement_type_edit': ('submenu-settings', 'agreements_settings'),
    'agreement_type_delete': ('submenu-settings', 'agreements_settings'),
    'sales_settings': ('submenu-settings', 'sales_settings'),
    'purchase_settings': ('submenu-settings', 'purchase_settings'),
    'inventory_settings': ('submenu-settings', 'inventory_settings'),
}

# Ordered longest-prefix-first fallback when resolver_match is absent (e.g. unit tests)
_NAV_PATH_PREFIXES = [
    ('/settings/visits/templates', ('submenu-settings', 'visit_templates')),
    ('/activities/settings/visits/templates', ('submenu-settings', 'visit_templates')),
    ('/settings/branding', ('submenu-settings', 'branding_settings')),
    ('/settings/storage', ('submenu-settings', 'r2_storage_settings')),
    ('/settings/location', ('submenu-settings', 'location_settings')),
    ('/settings/areas', ('submenu-settings', 'areas_settings')),
    ('/settings/agreements', ('submenu-settings', 'agreements_settings')),
    ('/settings/sales', ('submenu-settings', 'sales_settings')),
    ('/settings/purchase', ('submenu-settings', 'purchase_settings')),
    ('/settings/inventory', ('submenu-settings', 'inventory_settings')),
    ('/settings/audit-logs', ('submenu-settings', 'audit_logs')),
    ('/settings/roles', ('submenu-settings', 'roles')),
    ('/settings/users', ('submenu-settings', 'users')),
    ('/auth/audit-logs', ('submenu-settings', 'audit_logs')),
    ('/auth/roles', ('submenu-settings', 'roles')),
    ('/auth/users', ('submenu-settings', 'users')),
    ('/audit-logs', ('submenu-settings', 'audit_logs')),
    ('/roles', ('submenu-settings', 'roles')),
    ('/users', ('submenu-settings', 'users')),
    ('/reports/item-sales-by-customer', ('submenu-reports', 'report_item_sales_by_customer')),
    ('/reports/agreements-roi', ('submenu-reports', 'report_agreements_roi')),
    ('/reports/delivery-stock', ('submenu-reports', 'report_delivery_stock')),
    ('/reports/item-purchases', ('submenu-reports', 'report_item_purchases')),
    ('/reports/trial-balance', ('submenu-reports', 'report_trial_balance')),
    ('/reports/customer-360', ('submenu-reports', 'report_customer_360')),
    ('/reports/net-sales', ('submenu-reports', 'report_net_sales')),
    ('/reports/ar-aging', ('submenu-reports', 'report_ar_aging')),
    ('/reports', ('submenu-reports', 'reports_hub')),
    ('/performance/analysis', ('submenu-performance', 'performance_analysis')),
    ('/performance/detailed', ('submenu-performance', 'performance_detailed')),
    ('/performance/overview', ('submenu-performance', 'performance_overview')),
    ('/performance/daily', ('submenu-performance', 'performance_daily')),
    ('/performance', ('submenu-performance', 'performance_overview')),
    ('/activities/planned-visits', ('submenu-activities', 'planned_visits')),
    ('/planned-visits', ('submenu-activities', 'planned_visits')),
    ('/activities/agreements', ('submenu-activities', 'agreements')),
    ('/agreements', ('submenu-activities', 'agreements')),
    ('/activities/visits', ('submenu-activities', 'visits')),
    ('/visits', ('submenu-activities', 'visits')),
    ('/sales/customer-transactions', ('submenu-sales', 'customer_transactions')),
    ('/accounting/customer-transactions', ('submenu-sales', 'customer_transactions')),
    ('/sales/customers/accounts', ('submenu-sales', 'accounting_customers')),
    ('/sales/accounting/customers', ('submenu-sales', 'accounting_customers')),
    ('/accounting/customers', ('submenu-sales', 'accounting_customers')),
    ('/sales/customers', ('submenu-sales', 'accounting_customers')),
    ('/sales/collections', ('submenu-sales', 'collections')),
    ('/sales-return-orders', ('submenu-sales', 'sales_returns')),
    ('/sales/returns', ('submenu-sales', 'sales_returns')),
    ('/sales', ('submenu-sales', 'sales_orders')),
    ('/treasury/vendor-transactions', ('submenu-purchases', 'vendor_transactions')),
    ('/accounting/vendor-transactions', ('submenu-purchases', 'vendor_transactions')),
    ('/treasury/vendors', ('submenu-purchases', 'accounting_vendors')),
    ('/accounting/vendors', ('submenu-purchases', 'accounting_vendors')),
    ('/treasury/payment-requests', ('submenu-purchases', 'vendor_payment_requests')),
    ('/vendor-payment-requests', ('submenu-purchases', 'vendor_payment_requests')),
    ('/treasury/payments', ('submenu-purchases', 'vendor_payments')),
    ('/vendor-payments', ('submenu-purchases', 'vendor_payments')),
    ('/purchase-return-orders', ('submenu-purchases', 'purchase_returns')),
    ('/purchases/returns', ('submenu-purchases', 'purchase_returns')),
    ('/purchase-orders', ('submenu-purchases', 'purchase_orders')),
    ('/purchases', ('submenu-purchases', 'purchase_orders')),
    ('/inventory/warehouses', ('submenu-inventory', 'warehouses')),
    ('/inventory/transfers', ('submenu-inventory', 'inventory_memos')),
    ('/inventory/memos', ('submenu-inventory', 'inventory_memos')),
    ('/inventory', ('submenu-inventory', 'inventory_stock')),
    ('/treasury/vault-transactions', ('submenu-treasury', 'vault_transactions')),
    ('/treasury/transfer', ('submenu-treasury', 'vault_transactions')),
    ('/treasury/deposit', ('submenu-treasury', 'vault_transactions')),
    ('/treasury/withdraw', ('submenu-treasury', 'vault_transactions')),
    ('/treasury/vaults', ('submenu-treasury', 'vaults')),
    ('/product-categories', ('submenu-catalog', 'categories')),
    ('/products/categories', ('submenu-catalog', 'categories')),
    ('/catalog/categories', ('submenu-catalog', 'categories')),
    ('/products', ('submenu-catalog', 'products')),
    ('/catalog', ('submenu-catalog', 'products')),
    ('/contacts', ('', 'contacts')),
    ('/agenda', ('', 'agenda')),
    ('/home', ('', 'home')),
]


@register.simple_tag(takes_context=True)
def resolve_active_nav(context):
    """
    Deterministically resolve active sidebar section and link item from Django's
    URL resolver_match (or ordered longest-prefix path fallback). Eliminates all
    ambiguous substring collisions (e.g. 'visits', 'agreements', 'sales').
    """
    request = context.get('request')
    if not request:
        return {'section': '', 'item': ''}

    resolver_match = getattr(request, 'resolver_match', None)
    url_name = getattr(resolver_match, 'url_name', '') or ''
    if url_name in _NAV_URL_MAP:
        section, item = _NAV_URL_MAP[url_name]
        return {'section': section, 'item': item}

    path = getattr(request, 'path', '') or '/'
    normalized = '/' + path.strip('/') if path.strip('/') else '/'
    if normalized == '/':
        return {'section': '', 'item': 'home'}

    for prefix, (section, item) in _NAV_PATH_PREFIXES:
        if normalized == prefix or normalized.startswith(prefix + '/'):
            return {'section': section, 'item': item}

    return {'section': '', 'item': ''}




