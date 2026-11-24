"""
Centralized Arabic-First Notification Formatter & Canonical Destination Router.

Responsibilities:
1. Map every notification event_code to a stable internal `route_key` (not hardcoded URLs).
2. Resolve `(route_key, target_obj, target_object_id)` safely into internal Django URLs via `reverse()`.
3. Format clear, natural, professional Arabic titles and bodies answering:
   - What happened?
   - Which record is involved?
   - Who performed the action (when relevant)?
   - What should the recipient do next (when action is required)?
4. Never expose raw English DB enum values, raw JSON dumps, internal model names, or sensitive tokens.
"""

from decimal import Decimal
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlencode

from django.urls import reverse

from .registry import NOTIFICATION_MODULES_META, get_event_definition

# =====================================================================
# 1. ARABIC DISPLAY LABELS (Status, Severity, Module, Contact Relations)
# =====================================================================

SEVERITY_LABELS_AR: Dict[str, str] = {
    'info': 'معلومات',
    'success': 'نجاح',
    'warning': 'تنبيه',
    'danger': 'عاجل',
}

CONTACT_STATUS_LABELS_AR: Dict[str, str] = {
    'lead': 'Lead',
    'customer': 'Customer',
    'inactive': 'Inactive',
}

SETTINGS_ACTION_LABELS_AR: Dict[str, Tuple[str, str]] = {
    'LOCATION_SETTINGS_UPDATED': ('إعدادات الموقع الجغرافي', 'settings.location'),
    'SALES_SETTINGS_UPDATED': ('إعدادات المبيعات', 'settings.sales'),
    'PURCHASE_SETTINGS_UPDATED': ('إعدادات المشتريات', 'settings.purchase'),
    'INVENTORY_SETTINGS_UPDATED': ('إعدادات المخازن', 'settings.inventory'),
    'STORAGE_SETTINGS_UPDATED': ('إعدادات التخزين السحابي R2', 'settings.storage'),
    'SETTINGS_UPDATED': ('بيانات الشركة والنظام', 'settings.branding'),
}


def get_module_label_ar(module: str) -> str:
    meta = NOTIFICATION_MODULES_META.get((module or '').strip())
    return meta['name_ar'] if meta else 'عام'


def get_severity_label_ar(severity: str) -> str:
    return SEVERITY_LABELS_AR.get((severity or '').strip().lower(), 'معلومات')


def localize_contact_status(status: Optional[str]) -> str:
    key = (status or '').strip().lower()
    return CONTACT_STATUS_LABELS_AR.get(key, 'Customer')


def format_egp(amount: Any) -> str:
    try:
        return f"{Decimal(str(amount or 0)):,.2f} ج.م"
    except Exception:
        return "0.00 ج.م"


def actor_label(actor) -> str:
    if not actor:
        return 'النظام'
    return (getattr(actor, 'name', '') or getattr(actor, 'username', '') or 'مستخدم').strip()


def contact_relation_label(contact) -> str:
    if contact is None:
        return 'جهة اتصال'
    is_cust = bool(getattr(contact, 'is_customer', False))
    is_sup = bool(getattr(contact, 'is_supplier', False))
    status = (getattr(contact, 'status', '') or '').strip().lower()
    if status == 'lead':
        return 'Lead'
    if is_cust and is_sup:
        return 'عميل ومورد'
    if is_sup:
        return 'مورد'
    if is_cust:
        return 'عميل'
    return 'جهة اتصال'


# =====================================================================
# 2. CANONICAL DESTINATION ROUTING (route_key -> Django Named URL)
# =====================================================================

# route_key -> (url_name, needs_pk, query_param_for_pk_or_none, extra_query_dict)
DESTINATION_ROUTES: Dict[str, Tuple[str, bool, Optional[str], Optional[Dict[str, str]]]] = {
    'sales.order_detail': ('sales_order_detail', True, None, None),
    'sales.orders_list': ('sales_orders_list', False, None, None),
    'sales.return_detail': ('sales_return_order_detail', True, None, None),
    'sales.returns_list': ('sales_return_orders_list', False, None, None),
    'sales.collections_list': ('collections_list', False, None, None),
    'sales.customer_transactions': ('customer_transactions_list', False, 'customer_id', None),
    'purchases.order_detail': ('purchase_order_detail', True, None, None),
    'purchases.orders_list': ('purchase_orders_list', False, None, None),
    'purchases.return_detail': ('purchase_return_order_detail', True, None, None),
    'purchases.returns_list': ('purchase_return_orders_list', False, None, None),
    'treasury.vendor_payments': ('vendor_payments_list', False, None, None),
    'treasury.payment_request_detail': ('vendor_payment_request_detail', True, None, None),
    'treasury.payment_requests_list': ('vendor_payment_requests_list', False, None, None),
    'treasury.vault_detail': ('vault_detail', True, None, None),
    'treasury.vaults_list': ('vaults_list', False, None, None),
    'treasury.vault_transactions': ('vault_transactions_list', False, None, None),
    'treasury.vendor_transactions': ('vendor_transactions_list', False, 'vendor_id', None),
    'inventory.transfer_detail': ('product_transfer_detail', True, None, None),
    'inventory.transfers_list': ('product_transfers_list', False, None, None),
    'inventory.memo_detail': ('inventory_memo_detail', True, None, None),
    'inventory.memos_list': ('inventory_memos_list', False, None, None),
    'inventory.stock_list': ('inventory_stock_list', False, None, None),
    'activities.visit_detail': ('visit_detail', True, None, None),
    'activities.visits_list': ('visits_list', False, None, None),
    'activities.planned_visits': ('planned_visits_list', False, None, None),
    'activities.agreement_detail': ('agreement_detail', True, None, None),
    'activities.agreements_list': ('agreements_list', False, None, None),
    'contacts.detail': ('contact_detail', True, None, None),
    'contacts.detail_todos': ('contact_detail', True, None, {'tab': 'todos'}),
    'contacts.list': ('contacts_list', False, None, None),
    'catalog.product_detail': ('product_detail', True, None, None),
    'catalog.products_list': ('products_list', False, None, None),
    'accounts.user_detail': ('user_detail', True, None, None),
    'accounts.users_list': ('users_list', False, None, None),
    'accounts.roles_list': ('roles_list', False, None, None),
    'settings.location': ('location_settings', False, None, None),
    'settings.sales': ('sales_settings', False, None, None),
    'settings.purchase': ('purchase_settings', False, None, None),
    'settings.inventory': ('inventory_settings', False, None, None),
    'settings.storage': ('r2_storage_settings', False, None, None),
    'settings.branding': ('branding_settings', False, None, None),
    'performance.overview': ('performance_overview', False, None, None),
    'performance.detailed': ('performance_detailed', False, None, None),
    'notifications.inbox': ('notifications_inbox', False, None, None),
}

# Default route_key for each of the 60 canonical events + system.test_push
EVENT_DEFAULT_ROUTE_KEY: Dict[str, str] = {
    # Sales (13)
    'sales.order_created': 'sales.order_detail',
    'sales.order_pending_approval': 'sales.order_detail',
    'sales.order_approved': 'sales.order_detail',
    'sales.order_rejected': 'sales.order_detail',
    'sales.order_updated': 'sales.order_detail',
    'sales.order_cancelled': 'sales.order_detail',
    'sales.order_deleted': 'sales.orders_list',
    'sales.return_created': 'sales.return_detail',
    'sales.return_approved': 'sales.return_detail',
    'sales.return_rejected': 'sales.return_detail',
    'sales.return_deleted': 'sales.returns_list',
    'sales.collection_recorded': 'sales.collections_list',
    'sales.customer_balance_zeroed': 'sales.customer_transactions',
    # Purchases (9)
    'purchases.order_created': 'purchases.order_detail',
    'purchases.order_pending_approval': 'purchases.order_detail',
    'purchases.order_approved': 'purchases.order_detail',
    'purchases.order_rejected': 'purchases.order_detail',
    'purchases.order_cancelled': 'purchases.order_detail',
    'purchases.order_deleted': 'purchases.orders_list',
    'purchases.return_created': 'purchases.return_detail',
    'purchases.return_approved': 'purchases.return_detail',
    'purchases.return_rejected': 'purchases.return_detail',
    # Treasury (9)
    'treasury.vendor_payment_recorded': 'treasury.vendor_payments',
    'treasury.payment_request_created': 'treasury.payment_request_detail',
    'treasury.payment_request_approved': 'treasury.payment_request_detail',
    'treasury.payment_request_rejected': 'treasury.payment_request_detail',
    'treasury.payment_request_executed': 'treasury.payment_request_detail',
    'treasury.vault_transfer': 'treasury.vault_detail',
    'treasury.vault_deposit_withdraw': 'treasury.vault_detail',
    'treasury.transaction_reversed': 'treasury.vault_transactions',
    'treasury.vendor_balance_zeroed': 'treasury.vendor_transactions',
    # Inventory (6)
    'inventory.transfer_requested': 'inventory.transfer_detail',
    'inventory.transfer_approved': 'inventory.transfer_detail',
    'inventory.transfer_rejected': 'inventory.transfer_detail',
    'inventory.transfer_executed': 'inventory.transfer_detail',
    'inventory.memo_created': 'inventory.memo_detail',
    'inventory.low_stock_alert': 'inventory.stock_list',
    # Activities (11)
    'activities.visit_created': 'activities.visit_detail',
    'activities.visit_pending_approval': 'activities.visit_detail',
    'activities.visit_approved': 'activities.visit_detail',
    'activities.visit_rejected': 'activities.visit_detail',
    'activities.visit_gps_suspicious': 'activities.visit_detail',
    'activities.visit_reapproval_required': 'activities.visit_detail',
    'activities.plan_submitted': 'activities.planned_visits',
    'activities.plan_approved': 'activities.planned_visits',
    'activities.plan_rejected': 'activities.planned_visits',
    'activities.agreement_created': 'activities.agreement_detail',
    'activities.agreement_approved': 'activities.agreement_detail',
    'activities.agreement_rejected': 'activities.agreement_detail',
    # Contacts (4)
    'contacts.contact_created': 'contacts.detail',
    'contacts.contact_status_changed': 'contacts.detail',
    'contacts.contact_credit_changed': 'contacts.detail',
    'contacts.todo_assigned': 'contacts.detail_todos',
    # Catalog (2)
    'catalog.product_price_changed': 'catalog.product_detail',
    'catalog.excel_import_completed': 'catalog.products_list',
    # Accounts (3)
    'accounts.user_created': 'accounts.user_detail',
    'accounts.user_status_changed': 'accounts.user_detail',
    'accounts.role_updated': 'accounts.roles_list',
    # Settings (1)
    'settings.critical_updated': 'settings.branding',
    # Reports (2)
    'reports.target_assigned': 'performance.overview',
    'reports.coaching_evaluated': 'performance.detailed',
    # System
    'system.test_push': 'notifications.inbox',
}


def get_default_route_key(event_code: str) -> str:
    return EVENT_DEFAULT_ROUTE_KEY.get((event_code or '').strip(), 'notifications.inbox')


def resolve_destination_url(
    route_key: str,
    record_id: Optional[int] = None,
    target_obj=None,
    fallback_url: str = '',
) -> str:
    """
    Safely resolves a canonical `route_key` + `record_id` into an internal Django URL
    strictly through Django's `reverse()` registry (never interpolating untrusted URLs).
    """
    rk = (route_key or '').strip()
    spec = DESTINATION_ROUTES.get(rk)
    if not spec:
        return fallback_url or '/notifications/'

    url_name, needs_pk, query_param, extra_qs = spec
    try:
        if needs_pk:
            pk_val = record_id or getattr(target_obj, 'pk', None)
            if not pk_val:
                return fallback_url or '/notifications/'
            base_url = reverse(url_name, kwargs={'pk': int(pk_val)})
        else:
            base_url = reverse(url_name)

        params: Dict[str, str] = {}
        if extra_qs:
            params.update(extra_qs)
        if query_param:
            # For customer_transactions / vendor_transactions, extract customer_id / supplier_id from account if present
            q_val = None
            if target_obj is not None:
                if query_param == 'customer_id':
                    q_val = getattr(target_obj, 'customer_id', None) or getattr(target_obj, 'pk', None)
                elif query_param == 'vendor_id':
                    q_val = getattr(target_obj, 'supplier_id', None) or getattr(target_obj, 'pk', None)
            if q_val is None and record_id:
                q_val = record_id
            if q_val:
                params[query_param] = str(q_val)

        if params:
            return f"{base_url}?{urlencode(params)}"
        return base_url
    except Exception:
        return fallback_url or '/notifications/'


# =====================================================================
# 3. ARABIC-FIRST EVENT MESSAGE BUILDER (ALL 60 EVENTS)
# =====================================================================

def _clean_reason(raw: Optional[str]) -> str:
    text = str(raw or '').strip()
    return text[:200] if text else ''


def build_arabic_notification(
    event_code: str,
    target_obj=None,
    actor=None,
    action_type: str = '',
    fallback_title: str = '',
    fallback_body: str = '',
    record_name: str = '',
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Generates natural, concise, consistent Arabic `title`, `body`, `route_key`, `action_url`,
    and non-sensitive `metadata` for any ERP notification event.
    """
    extra = dict(extra or {})
    ev_def = get_event_definition(event_code) or {}
    actor_name = actor_label(actor)
    route_key = get_default_route_key(event_code)
    meta: Dict[str, Any] = {}

    title = ''
    body = ''

    # --- 1. SALES ---
    if event_code.startswith('sales.order_'):
        order_num = getattr(target_obj, 'order_number', None) or record_name or ''
        cust_name = getattr(getattr(target_obj, 'customer', None), 'name', '') or ''
        total_str = format_egp(getattr(target_obj, 'grand_total', None)) if target_obj is not None else ''
        if order_num:
            meta['document_number'] = str(order_num)

        if event_code == 'sales.order_created':
            title = f"أمر بيع جديد #{order_num}" if order_num else "تم إنشاء أمر بيع جديد"
            body = f"أنشأ {actor_name} أمر بيع"
            if cust_name:
                body += f" للعميل {cust_name}"
            if total_str:
                body += f" بقيمة {total_str}"
            body += "."
        elif event_code == 'sales.order_pending_approval':
            meta['requires_action'] = True
            title = f"أمر بيع #{order_num} بانتظار اعتمادك" if order_num else "أمر بيع بانتظار اعتمادك"
            body = f"قدّم {actor_name} أمر بيع"
            if cust_name:
                body += f" للعميل {cust_name}"
            if total_str:
                body += f" بقيمة {total_str}"
            body += "، ويتطلب مراجعتك واعتمادك."
        elif event_code == 'sales.order_approved':
            title = f"تم اعتماد أمر البيع #{order_num}" if order_num else "تم اعتماد أمر البيع"
            body = f"اعتمد {actor_name} أمر البيع"
            if cust_name:
                body += f" الخاص بالعميل {cust_name}"
            if total_str:
                body += f" بقيمة {total_str}"
            body += "."
        elif event_code == 'sales.order_rejected':
            title = f"تم رفض أمر البيع #{order_num}" if order_num else "تم رفض أمر البيع"
            reason = _clean_reason(extra.get('reason') or getattr(target_obj, 'rejection_reason', ''))
            body = f"رفض {actor_name} أمر البيع" + (f" للعميل {cust_name}" if cust_name else "") + "."
            if reason:
                body += f" السبب: {reason}."
        elif event_code == 'sales.order_updated':
            title = f"تعديل أمر البيع #{order_num}" if order_num else "تم تعديل أمر بيع"
            body = f"حدّث {actor_name} بيانات أمر البيع"
            if cust_name:
                body += f" للعميل {cust_name}"
            if total_str:
                body += f" ليصبح الإجمالي {total_str}"
            body += "."
        elif event_code == 'sales.order_cancelled':
            title = f"تم إلغاء أمر البيع #{order_num}" if order_num else "تم إلغاء أمر بيع"
            body = f"ألغى {actor_name} أمر البيع" + (f" الخاص بالعميل {cust_name}" if cust_name else "") + "."
        elif event_code == 'sales.order_deleted':
            title = f"تم حذف أمر البيع #{order_num}" if order_num else "تم حذف أمر بيع"
            body = f"حذف {actor_name} أمر البيع" + (f" للعميل {cust_name}" if cust_name else "") + " وعكس قيوده المخزنية والمالية."

    elif event_code.startswith('sales.return_'):
        ret_num = getattr(target_obj, 'order_number', None) or record_name or ''
        cust_name = getattr(getattr(target_obj, 'customer', None), 'name', '') or ''
        total_str = format_egp(getattr(target_obj, 'grand_total', None)) if target_obj is not None else ''
        if ret_num:
            meta['document_number'] = str(ret_num)

        if event_code == 'sales.return_created':
            meta['requires_action'] = True
            title = f"مرتجع مبيعات جديد #{ret_num}" if ret_num else "مرتجع مبيعات جديد"
            body = f"سجّل {actor_name} مرتجع مبيعات" + (f" للعميل {cust_name}" if cust_name else "") + (f" بقيمة {total_str}" if total_str else "") + "، يرجى المراجعة."
        elif event_code == 'sales.return_approved':
            title = f"تم اعتماد مرتجع المبيعات #{ret_num}" if ret_num else "تم اعتماد مرتجع مبيعات"
            body = f"اعتمد {actor_name} مرتجع المبيعات" + (f" للعميل {cust_name}" if cust_name else "") + (f" بقيمة {total_str}" if total_str else "") + "."
        elif event_code == 'sales.return_rejected':
            title = f"تم رفض مرتجع المبيعات #{ret_num}" if ret_num else "تم رفض مرتجع مبيعات"
            reason = _clean_reason(extra.get('reason') or getattr(target_obj, 'rejection_reason', ''))
            body = f"رفض {actor_name} مرتجع المبيعات" + (f" للعميل {cust_name}" if cust_name else "") + "."
            if reason:
                body += f" السبب: {reason}."
        elif event_code == 'sales.return_deleted':
            title = f"تم حذف مرتجع المبيعات #{ret_num}" if ret_num else "تم حذف مرتجع مبيعات"
            body = f"حذف {actor_name} مرتجع المبيعات" + (f" للعميل {cust_name}" if cust_name else "") + " وعكس قيوده."

    elif event_code == 'sales.collection_recorded':
        serial = getattr(target_obj, 'serial_num', None) or record_name or ''
        cust_name = getattr(getattr(target_obj, 'customer', None), 'name', '') or ''
        amt_str = format_egp(getattr(target_obj, 'amount', None)) if target_obj is not None else ''
        title = f"تحصيل جديد بقيمة {amt_str}" if amt_str else "تسجيل تحصيل جديد"
        body = f"سجّل {actor_name} سند تحصيل" + (f" #{serial}" if serial else "") + (f" من العميل {cust_name}" if cust_name else "") + (f" بمبلغ {amt_str}" if amt_str else "") + "."

    elif event_code == 'sales.customer_balance_zeroed':
        cust_name = getattr(getattr(target_obj, 'customer', None), 'name', '') or record_name or ''
        title = f"تصفير رصيد العميل {cust_name}".strip()
        body = fallback_body or f"صفّر {actor_name} رصيد حساب العميل {cust_name} (تسوية غير نقدية)."

    # --- 2. PURCHASES ---
    elif event_code.startswith('purchases.order_'):
        order_num = getattr(target_obj, 'order_number', None) or record_name or ''
        sup_name = getattr(getattr(target_obj, 'supplier', None), 'name', '') or ''
        total_str = format_egp(getattr(target_obj, 'grand_total', None)) if target_obj is not None else ''
        if order_num:
            meta['document_number'] = str(order_num)

        if event_code == 'purchases.order_created':
            title = f"أمر شراء جديد #{order_num}" if order_num else "تم إنشاء أمر شراء جديد"
            body = f"أنشأ {actor_name} أمر شراء" + (f" للمورد {sup_name}" if sup_name else "") + (f" بقيمة {total_str}" if total_str else "") + "."
        elif event_code == 'purchases.order_pending_approval':
            meta['requires_action'] = True
            title = f"أمر شراء #{order_num} بانتظار اعتمادك" if order_num else "أمر شراء بانتظار اعتمادك"
            body = f"قدّم {actor_name} أمر شراء" + (f" للمورد {sup_name}" if sup_name else "") + (f" بقيمة {total_str}" if total_str else "") + "، ويتطلب مراجعتك واعتمادك."
        elif event_code == 'purchases.order_approved':
            title = f"تم اعتماد أمر الشراء #{order_num}" if order_num else "تم اعتماد أمر الشراء"
            body = f"اعتمد {actor_name} أمر الشراء" + (f" للمورد {sup_name}" if sup_name else "") + (f" بقيمة {total_str}" if total_str else "") + "."
        elif event_code == 'purchases.order_rejected':
            title = f"تم رفض أمر الشراء #{order_num}" if order_num else "تم رفض أمر الشراء"
            reason = _clean_reason(extra.get('reason') or getattr(target_obj, 'rejection_reason', ''))
            body = f"رفض {actor_name} أمر الشراء" + (f" للمورد {sup_name}" if sup_name else "") + "."
            if reason:
                body += f" السبب: {reason}."
        elif event_code == 'purchases.order_cancelled':
            title = f"تم إلغاء أمر الشراء #{order_num}" if order_num else "تم إلغاء أمر شراء"
            body = f"ألغى {actor_name} أمر الشراء" + (f" للمورد {sup_name}" if sup_name else "") + "."
        elif event_code == 'purchases.order_deleted':
            title = f"تم حذف أمر الشراء #{order_num}" if order_num else "تم حذف أمر شراء"
            body = f"حذف {actor_name} أمر الشراء" + (f" للمورد {sup_name}" if sup_name else "") + " وعكس قيوده المخزنية والمالية."

    elif event_code.startswith('purchases.return_'):
        ret_num = getattr(target_obj, 'order_number', None) or record_name or ''
        sup_name = getattr(getattr(target_obj, 'supplier', None), 'name', '') or ''
        total_str = format_egp(getattr(target_obj, 'grand_total', None)) if target_obj is not None else ''
        if ret_num:
            meta['document_number'] = str(ret_num)

        if event_code == 'purchases.return_created':
            meta['requires_action'] = True
            title = f"مرتجع مشتريات جديد #{ret_num}" if ret_num else "مرتجع مشتريات جديد"
            body = f"سجّل {actor_name} مرتجع مشتريات" + (f" للمورد {sup_name}" if sup_name else "") + (f" بقيمة {total_str}" if total_str else "") + "، يرجى المراجعة."
        elif event_code == 'purchases.return_approved':
            title = f"تم اعتماد مرتجع المشتريات #{ret_num}" if ret_num else "تم اعتماد مرتجع مشتريات"
            body = f"اعتمد {actor_name} مرتجع المشتريات" + (f" للمورد {sup_name}" if sup_name else "") + (f" بقيمة {total_str}" if total_str else "") + "."
        elif event_code == 'purchases.return_rejected':
            title = f"تم رفض مرتجع المشتريات #{ret_num}" if ret_num else "تم رفض مرتجع مشتريات"
            reason = _clean_reason(extra.get('reason') or getattr(target_obj, 'rejection_reason', ''))
            body = f"رفض {actor_name} مرتجع المشتريات" + (f" للمورد {sup_name}" if sup_name else "") + "."
            if reason:
                body += f" السبب: {reason}."

    # --- 3. TREASURY ---
    elif event_code == 'treasury.vendor_payment_recorded':
        sup_name = getattr(getattr(target_obj, 'supplier', None), 'name', '') or ''
        vault_name = getattr(getattr(target_obj, 'vault', None), 'name', '') or ''
        amt_str = format_egp(getattr(target_obj, 'amount', None)) if target_obj is not None else ''
        title = f"سداد مورد بقيمة {amt_str}" if amt_str else "تسجيل سداد لمورد"
        body = f"سجّل {actor_name} سداداً" + (f" للمورد {sup_name}" if sup_name else "") + (f" بمبلغ {amt_str}" if amt_str else "") + (f" من خزنة {vault_name}" if vault_name else "") + "."

    elif event_code.startswith('treasury.payment_request_'):
        req_num = getattr(target_obj, 'request_number', None) or getattr(target_obj, 'serial_num', None) or record_name or ''
        sup_name = getattr(getattr(target_obj, 'supplier', None), 'name', '') or ''
        amt_str = format_egp(getattr(target_obj, 'amount', None)) if target_obj is not None else ''
        if req_num:
            meta['document_number'] = str(req_num)
        if event_code == 'treasury.payment_request_created':
            meta['requires_action'] = True
            title = f"طلب سداد مورد #{req_num} بانتظار اعتمادك" if req_num else "طلب سداد مورد بانتظار اعتمادك"
            body = f"قدّم {actor_name} طلب سداد" + (f" للمورد {sup_name}" if sup_name else "") + (f" بقيمة {amt_str}" if amt_str else "") + "، ويتطلب مراجعتك واعتمادك."
        elif event_code == 'treasury.payment_request_approved':
            title = f"تم اعتماد طلب السداد #{req_num}" if req_num else "تم اعتماد طلب سداد مورد"
            body = f"اعتمد {actor_name} طلب سداد المورد {sup_name}" + (f" بقيمة {amt_str}" if amt_str else "") + "."
        elif event_code == 'treasury.payment_request_rejected':
            title = f"تم رفض طلب السداد #{req_num}" if req_num else "تم رفض طلب سداد مورد"
            reason = _clean_reason(extra.get('reason') or getattr(target_obj, 'rejection_reason', ''))
            body = f"رفض {actor_name} طلب سداد المورد {sup_name}." + (f" السبب: {reason}." if reason else "")
        elif event_code == 'treasury.payment_request_executed':
            title = f"تم تنفيذ صرف طلب السداد #{req_num}" if req_num else "تم تنفيذ صرف طلب سداد مورد"
            body = f"نفّذ {actor_name} صرف طلب سداد المورد {sup_name}" + (f" بمبلغ {amt_str}" if amt_str else "") + "."

    elif event_code == 'treasury.vault_transfer':
        vault_name = getattr(target_obj, 'name', '') or record_name or ''
        title = f"تحويل نقدي — {vault_name}" if vault_name else "تحويل نقدي بين الخزن"
        body = fallback_body or f"نفّذ {actor_name} تحويلاً نقدياً يشمل خزنة {vault_name}."

    elif event_code == 'treasury.vault_deposit_withdraw':
        vault_name = getattr(target_obj, 'name', '') or record_name or ''
        op = 'إيداع' if action_type == 'VAULT_DEPOSIT' else ('سحب' if action_type == 'VAULT_WITHDRAWAL' else 'حركة')
        title = f"{op} نقدي في خزنة {vault_name}" if vault_name else f"تسجيل {op} نقدي بالخزنة"
        body = fallback_body or f"سجّل {actor_name} عملية {op} نقدي في خزنة {vault_name}."

    elif event_code == 'treasury.transaction_reversed':
        tx_id = getattr(target_obj, 'pk', None) or record_name or ''
        vault_name = getattr(getattr(target_obj, 'vault', None), 'name', '') or ''
        amt_str = format_egp(getattr(target_obj, 'amount', None)) if target_obj is not None else ''
        title = f"عكس حركة خزينة #{tx_id}" if tx_id else "عكس حركة خزينة"
        body = f"عكس {actor_name} حركة خزينة" + (f" بقيمة {amt_str}" if amt_str else "") + (f" في خزنة {vault_name}" if vault_name else "") + "."

    elif event_code == 'treasury.vendor_balance_zeroed':
        sup_name = getattr(getattr(target_obj, 'supplier', None), 'name', '') or record_name or ''
        title = f"تصفير رصيد المورد {sup_name}".strip()
        body = fallback_body or f"صفّر {actor_name} رصيد حساب المورد {sup_name} (تسوية غير نقدية)."

    # --- 4. INVENTORY ---
    elif event_code.startswith('inventory.transfer_'):
        ref = getattr(target_obj, 'reference_number', None) or record_name or ''
        src = getattr(getattr(target_obj, 'source_warehouse', None), 'name', '') or ''
        dst = getattr(getattr(target_obj, 'destination_warehouse', None), 'name', '') or ''
        if ref:
            meta['document_number'] = str(ref)
        route_phrase = f" من {src} إلى {dst}" if (src and dst) else ""
        if event_code == 'inventory.transfer_requested':
            meta['requires_action'] = True
            title = f"طلب تحويل مخزني #{ref} بانتظار اعتمادك" if ref else "طلب تحويل مخزني بانتظار اعتمادك"
            body = f"طلب {actor_name} تحويل أصناف{route_phrase}، ويتطلب مراجعتك واعتمادك."
        elif event_code == 'inventory.transfer_approved':
            title = f"تم اعتماد التحويل المخزني #{ref}" if ref else "تم اعتماد طلب تحويل مخزني"
            body = f"اعتمد {actor_name} طلب التحويل المخزني{route_phrase}."
        elif event_code == 'inventory.transfer_rejected':
            title = f"تم رفض التحويل المخزني #{ref}" if ref else "تم رفض طلب تحويل مخزني"
            body = f"رفض {actor_name} طلب التحويل المخزني{route_phrase}."
        elif event_code == 'inventory.transfer_executed':
            title = f"تم تنفيذ التحويل المخزني #{ref}" if ref else "تم تنفيذ التحويل المخزني"
            body = f"نفّذ {actor_name} التحويل المخزني ونقل البضاعة{route_phrase}."

    elif event_code == 'inventory.memo_created':
        memo_num = getattr(target_obj, 'memo_number', None) or record_name or ''
        wh_name = getattr(getattr(target_obj, 'warehouse', None), 'name', '') or ''
        m_type = getattr(target_obj, 'memo_type', '') or ('inward' if action_type == 'STOCK_IN' else 'outward')
        m_ar = 'إضافة' if m_type == 'inward' else 'صرف'
        title = f"إذن {m_ar} مخزني #{memo_num}" if memo_num else f"تسجيل إذن {m_ar} مخزني"
        body = f"سجّل {actor_name} إذن {m_ar} مخزني" + (f" في مخزن {wh_name}" if wh_name else "") + "."

    elif event_code == 'inventory.low_stock_alert':
        prod_name = getattr(getattr(target_obj, 'product', None), 'name', '') or ''
        wh_name = getattr(getattr(target_obj, 'warehouse', None), 'name', '') or ''
        qty = getattr(target_obj, 'qty_on_hand', 0)
        title = f"تنبيه انخفاض رصيد: {prod_name}" if prod_name else "تنبيه انخفاض رصيد بالمخزن"
        body = f"وصل الرصيد المتاح للصنف \"{prod_name}\" في مخزن \"{wh_name}\" إلى {Decimal(str(qty or 0)):,.0f} وحدة فقط. يرجى مراجعة إعادة التوريد."

    # --- 5. ACTIVITIES ---
    elif event_code.startswith('activities.visit_'):
        cust_name = getattr(getattr(target_obj, 'contact', None), 'name', '') or ''
        visit_serial = getattr(target_obj, 'serial_num', None) or getattr(target_obj, 'pk', None) or ''
        visit_date = getattr(target_obj, 'date', None)
        date_str = visit_date.strftime('%Y-%m-%d') if hasattr(visit_date, 'strftime') else (str(visit_date) if visit_date else '')
        if event_code == 'activities.visit_created':
            title = f"تسجيل زيارة للعميل {cust_name}" if cust_name else "تسجيل زيارة ميدانية جديدة"
            body = f"أنشأ {actor_name} زيارة (#{visit_serial}) للعميل {cust_name}" + (f" بتاريخ {date_str}" if date_str else "") + "."
        elif event_code == 'activities.visit_pending_approval':
            meta['requires_action'] = True
            title = f"زيارة للعميل {cust_name} بانتظار اعتمادك" if cust_name else "زيارة ميدانية بانتظار اعتمادك"
            body = f"سجّل {actor_name} زيارة للعميل {cust_name}" + (f" بتاريخ {date_str}" if date_str else "") + "، وتتطلب مراجعتك واعتمادك."
        elif event_code == 'activities.visit_approved':
            title = f"تم اعتماد زيارة {cust_name}" if cust_name else "تم اعتماد زيارة ميدانية"
            body = f"اعتمد {actor_name} زيارتك للعميل {cust_name}" + (f" بتاريخ {date_str}" if date_str else "") + "."
        elif event_code == 'activities.visit_rejected':
            title = f"تم رفض زيارة {cust_name}" if cust_name else "تم رفض زيارة ميدانية"
            body = f"رفض {actor_name} الزيارة الخاصة بالعميل {cust_name}" + (f" بتاريخ {date_str}" if date_str else "") + ". يرجى مراجعة التفاصيل."
        elif event_code == 'activities.visit_gps_suspicious':
            meta['requires_action'] = True
            title = f"تنبيه موقع GPS لزيارة {cust_name}" if cust_name else "تنبيه موقع GPS مشبوه"
            reason = _clean_reason(getattr(target_obj, 'gps_suspicion_reason', ''))
            body = reason or f"تم رصد تجاوز مسافة أو مؤشر GPS غير معتاد في زيارة {actor_name} للعميل {cust_name} (#{visit_serial}). يرجى المراجعة."
        elif event_code == 'activities.visit_reapproval_required':
            meta['requires_action'] = True
            title = f"تعديل زيارة معتمدة — {cust_name}" if cust_name else "زيارة معتمدة تتطلب إعادة اعتماد"
            body = f"عدّل {actor_name} الزيارة #{visit_serial} للعميل {cust_name} بعد اعتمادها، وتتطلب إعادة مراجعتك واعتمادك."

    elif event_code.startswith('activities.plan_'):
        plan_id = getattr(target_obj, 'plan_id', None) or record_name or ''
        plan_approval = getattr(target_obj, 'approval_status', '')
        if event_code == 'activities.plan_submitted':
            if plan_approval == 'approved':
                meta['requires_action'] = False
                title = f"تم إنشاء خطة زيارات #{plan_id}" if plan_id else "تم إنشاء خطة زيارات جديدة"
                body = f"أنشأ {actor_name} خطة زيارات" + (f" #{plan_id}" if plan_id else "") + "."
            else:
                meta['requires_action'] = True
                title = f"خطة زيارات #{plan_id} بانتظار الاعتماد" if plan_id else "تقديم خطة زيارات للاعتماد"
                body = f"قدّم {actor_name} خطة زيارات" + (f" #{plan_id}" if plan_id else "") + "، وتتطلب مراجعتك واعتمادك."
        elif event_code == 'activities.plan_approved':
            title = f"تم اعتماد خطة الزيارات #{plan_id}" if plan_id else "تم اعتماد خطة الزيارات"
            body = f"اعتمد {actor_name} خطة الزيارات" + (f" #{plan_id}" if plan_id else "") + "."
        elif event_code == 'activities.plan_rejected':
            title = f"تم رفض خطة الزيارات #{plan_id}" if plan_id else "تم رفض خطة الزيارات"
            body = f"رفض {actor_name} خطة الزيارات" + (f" #{plan_id}" if plan_id else "") + ". يرجى مراجعة الخطة وتعديلها."

    elif event_code.startswith('activities.agreement_'):
        agr_serial = getattr(target_obj, 'serial_num', None) or getattr(target_obj, 'pk', None) or ''
        cust_name = getattr(getattr(target_obj, 'customer', None), 'name', '') or ''
        amt_str = format_egp(getattr(target_obj, 'amount', None)) if target_obj is not None and getattr(target_obj, 'amount', None) else ''
        if event_code == 'activities.agreement_created':
            meta['requires_action'] = True
            title = f"اتفاقية جديدة بانتظار اعتمادك — {cust_name}" if cust_name else "اتفاقية تجارية جديدة بانتظار اعتمادك"
            body = f"أنشأ {actor_name} اتفاقية #{agr_serial}" + (f" للعميل {cust_name}" if cust_name else "") + (f" بقيمة {amt_str}" if amt_str else "") + "، وتتطلب مراجعتك واعتمادك."
        elif event_code == 'activities.agreement_approved':
            title = f"تم اعتماد الاتفاقية #{agr_serial}" if agr_serial else "تم اعتماد اتفاقية تجارية"
            body = f"اعتمد {actor_name} الاتفاقية" + (f" الخاصة بالعميل {cust_name}" if cust_name else "") + "."
        elif event_code == 'activities.agreement_rejected':
            title = f"تم رفض الاتفاقية #{agr_serial}" if agr_serial else "تم رفض اتفاقية تجارية"
            reason = _clean_reason(getattr(target_obj, 'approval_notes', ''))
            body = f"رفض {actor_name} الاتفاقية" + (f" الخاصة بالعميل {cust_name}" if cust_name else "") + "." + (f" السبب: {reason}." if reason else "")

    # --- 6. CONTACTS ---
    elif event_code == 'contacts.contact_created':
        c_name = getattr(target_obj, 'name', '') or record_name or ''
        rel_ar = contact_relation_label(target_obj)
        area_name = getattr(getattr(target_obj, 'area', None), 'name', '') or ''
        brick_name = getattr(getattr(target_obj, 'brick', None), 'name', '') or ''
        loc = ' - '.join(x for x in (area_name, brick_name) if x)
        title = f"إضافة {rel_ar} جديد: {c_name}" if c_name else "إضافة جهة اتصال جديدة"
        body = f"أضاف {actor_name} {rel_ar} جديداً باسم \"{c_name}\"" + (f" في نطاق {loc}" if loc else "") + "."

    elif event_code == 'contacts.contact_status_changed':
        c_name = getattr(target_obj, 'name', '') or record_name or ''
        old_ar = localize_contact_status(extra.get('old_status'))
        new_ar = localize_contact_status(extra.get('new_status') or getattr(target_obj, 'status', ''))
        title = f"تحديث حالة {c_name}" if c_name else "تحديث حالة جهة اتصال"
        body = f"تغيّرت حالة \"{c_name}\" من \"{old_ar}\" إلى \"{new_ar}\"" + (f" بواسطة {actor_name}" if actor else "") + "."

    elif event_code == 'contacts.contact_credit_changed':
        c_name = getattr(target_obj, 'name', '') or record_name or ''
        old_lim = format_egp(extra.get('old_limit'))
        new_lim = format_egp(extra.get('new_limit'))
        title = f"تعديل الحد الائتماني لـ {c_name}" if c_name else "تعديل الحد الائتماني لعميل"
        body = f"تم تعديل الحد الائتماني للعميل \"{c_name}\" من {old_lim} إلى {new_lim}."

    elif event_code == 'contacts.todo_assigned':
        c_name = getattr(target_obj, 'name', '') or ''
        todo_title = extra.get('todo_title') or ''
        due = extra.get('due_date')
        title = f"مهمة متابعة جديدة — {c_name}" if c_name else "مهمة متابعة عميل جديدة"
        body = f"عيّن {actor_name} مهمة \"{todo_title}\" للعميل {c_name}" + (f" بتاريخ استحقاق {due}" if due else "") + "."

    # --- 7. CATALOG ---
    elif event_code == 'catalog.product_price_changed':
        p_name = getattr(target_obj, 'name', '') or record_name or ''
        old_p = format_egp(extra.get('old_price'))
        new_p = format_egp(extra.get('new_price'))
        title = f"تعديل سعر المنتج: {p_name}" if p_name else "تعديل سعر بيع منتج"
        body = f"تغيّر سعر بيع المنتج \"{p_name}\" من {old_p} إلى {new_p}."

    elif event_code == 'catalog.excel_import_completed':
        title = fallback_title or "اكتمال استيراد ملف Excel"
        body = fallback_body or f"أنهى {actor_name} استيراد البيانات من ملف Excel بنجاح."

    # --- 8. ACCOUNTS ---
    elif event_code == 'accounts.user_created':
        u_name = (getattr(target_obj, 'name', '') or getattr(target_obj, 'username', '') or record_name or '')
        role_ar = getattr(getattr(target_obj, 'role', None), 'display_name', '') or ''
        title = f"إنشاء حساب مستخدم جديد: {u_name}" if u_name else "إنشاء حساب مستخدم جديد"
        body = f"أنشأ {actor_name} حساباً جديداً للموظف \"{u_name}\"" + (f" بدور {role_ar}" if role_ar else "") + "."

    elif event_code == 'accounts.user_status_changed':
        u_name = (getattr(target_obj, 'name', '') or getattr(target_obj, 'username', '') or record_name or '')
        is_act = getattr(target_obj, 'is_active', None)
        state_ar = 'تفعيل' if is_act is True else ('تعطيل' if is_act is False else 'تحديث حالة')
        title = f"{state_ar} حساب المستخدم: {u_name}" if u_name else "تغيير حالة حساب مستخدم"
        body = f"قام {actor_name} بـ{state_ar} حساب المستخدم \"{u_name}\"."

    elif event_code == 'accounts.role_updated':
        title = f"تحديث صلاحيات الدور: {record_name}" if record_name else "تحديث صلاحيات الأدوار"
        body = f"حدّث {actor_name} صلاحيات أو نطاقات الوصول للدور" + (f" \"{record_name}\"" if record_name else "") + "."

    # --- 9. SETTINGS ---
    elif event_code == 'settings.critical_updated':
        section_ar, mapped_rk = SETTINGS_ACTION_LABELS_AR.get(
            (action_type or '').upper(),
            ('إعدادات النظام', 'settings.branding'),
        )
        route_key = mapped_rk
        title = f"تحديث {section_ar}"
        body = f"حدّث {actor_name} {section_ar} في النظام. يرجى مراجعة التعديلات عند الحاجة."

    # --- 10. REPORTS / PERFORMANCE ---
    elif event_code == 'reports.target_assigned':
        month = getattr(target_obj, 'month', '')
        year = getattr(target_obj, 'year', '')
        sales_t = format_egp(getattr(target_obj, 'target_sales_amount', 0))
        coll_t = format_egp(getattr(target_obj, 'target_collections_amount', 0))
        visits_t = getattr(target_obj, 'target_visits_count', 0)
        title = f"تحديث هدف الأداء ({month}/{year})" if month and year else "تحديث هدف الأداء الشهري"
        body = f"حدّد {actor_name} هدفك الشهري: مبيعات {sales_t}، تحصيلات {coll_t}، وعدد {visits_t} زيارة."

    elif event_code == 'reports.coaching_evaluated':
        score = getattr(target_obj, 'overall_score', '')
        eval_date = getattr(target_obj, 'date', '')
        title = "تسجيل تقييم توجيه ميداني جديد"
        body = f"سجّل {actor_name} تقييم زيارة مشتركة بدرجة إجمالية {score}/10 بتاريخ {eval_date}. يرجى مراجعة التوصيات."

    # Safe fallbacks (never raw JSON, never empty title)
    if not title:
        title = (fallback_title or ev_def.get('name_ar') or 'إشعار من النظام').strip()
    if not body:
        body = (fallback_body or '').strip()

    action_url = resolve_destination_url(
        route_key=route_key,
        record_id=getattr(target_obj, 'pk', None),
        target_obj=target_obj,
    )

    return {
        'title': title[:200],
        'body': body[:2000],
        'route_key': route_key,
        'action_url': action_url,
        'metadata': meta,
    }
