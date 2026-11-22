"""
Centralized AuditLog -> Notification event dispatcher.
Maps SecurityAuditLog entries across all ERP modules to the canonical Notification Registry
without duplicating business logic or coupling core services to notifications.
"""

import logging
from typing import Optional

from django.urls import reverse

from .services import NotificationService

logger = logging.getLogger(__name__)


def _safe_reverse(name: str, pk=None) -> str:
    try:
        if pk is not None:
            return reverse(name, kwargs={'pk': pk})
        return reverse(name)
    except Exception:
        return ''


def _fetch_instance(model_path: str, record_id: str):
    if not record_id or not str(record_id).isdigit():
        return None
    try:
        app_label, model_name = model_path.split('.')
        from django.apps import apps
        model_cls = apps.get_model(app_label, model_name)
        return model_cls.objects.filter(pk=int(record_id)).first()
    except Exception:
        return None


# action_type -> (event_code, model_path, detail_url_name, list_url_name)
AUDIT_ACTION_MAP = {
    # Sales
    'SALES_ORDER_CREATED': ('sales.order_created', 'sales.SalesOrder', 'sales_order_detail', 'sales_orders_list'),
    'SALES_ORDER_APPROVED': ('sales.order_approved', 'sales.SalesOrder', 'sales_order_detail', 'sales_orders_list'),
    'SALES_ORDER_REJECTED': ('sales.order_rejected', 'sales.SalesOrder', 'sales_order_detail', 'sales_orders_list'),
    'SALES_ORDER_UPDATED': ('sales.order_updated', 'sales.SalesOrder', 'sales_order_detail', 'sales_orders_list'),
    'SALES_ORDER_CANCELLED': ('sales.order_cancelled', 'sales.SalesOrder', 'sales_order_detail', 'sales_orders_list'),
    'SALES_ORDER_DELETED': ('sales.order_deleted', 'sales.SalesOrder', None, 'sales_orders_list'),
    'SALES_RETURN_CREATED': ('sales.return_created', 'sales.SalesReturnOrder', 'sales_return_order_detail', 'sales_return_orders_list'),
    'SALES_RETURN_APPROVED': ('sales.return_approved', 'sales.SalesReturnOrder', 'sales_return_order_detail', 'sales_return_orders_list'),
    'SALES_RETURN_REJECTED': ('sales.return_rejected', 'sales.SalesReturnOrder', 'sales_return_order_detail', 'sales_return_orders_list'),
    'SALES_RETURN_DELETED': ('sales.return_deleted', 'sales.SalesReturnOrder', None, 'sales_return_orders_list'),
    'COLLECTION_CREATED': ('sales.collection_recorded', 'sales.Collection', None, 'collections_list'),
    # Purchases
    'PURCHASE_ORDER_CREATED': ('purchases.order_created', 'purchases.PurchaseOrder', 'purchase_order_detail', 'purchase_orders_list'),
    'PURCHASE_ORDER_APPROVED': ('purchases.order_approved', 'purchases.PurchaseOrder', 'purchase_order_detail', 'purchase_orders_list'),
    'PURCHASE_ORDER_REJECTED': ('purchases.order_rejected', 'purchases.PurchaseOrder', 'purchase_order_detail', 'purchase_orders_list'),
    'PURCHASE_ORDER_CANCELLED': ('purchases.order_cancelled', 'purchases.PurchaseOrder', 'purchase_order_detail', 'purchase_orders_list'),
    'PURCHASE_ORDER_DELETED': ('purchases.order_deleted', 'purchases.PurchaseOrder', None, 'purchase_orders_list'),
    'PURCHASE_RETURN_CREATED': ('purchases.return_created', 'purchases.PurchaseReturnOrder', 'purchase_return_order_detail', 'purchase_return_orders_list'),
    'PURCHASE_RETURN_APPROVED': ('purchases.return_approved', 'purchases.PurchaseReturnOrder', 'purchase_return_order_detail', 'purchase_return_orders_list'),
    'PURCHASE_RETURN_REJECTED': ('purchases.return_rejected', 'purchases.PurchaseReturnOrder', 'purchase_return_order_detail', 'purchase_return_orders_list'),
    # Treasury
    'VENDOR_PAYMENT_CREATED': ('treasury.vendor_payment_recorded', 'treasury.VendorPayment', None, 'vendor_payments_list'),
    'PAYMENT_REQUEST_CREATED': ('treasury.payment_request_created', 'treasury.VendorPaymentRequest', 'vendor_payment_request_detail', 'vendor_payment_requests_list'),
    'PAYMENT_REQUEST_APPROVED': ('treasury.payment_request_approved', 'treasury.VendorPaymentRequest', 'vendor_payment_request_detail', 'vendor_payment_requests_list'),
    'PAYMENT_REQUEST_REJECTED': ('treasury.payment_request_rejected', 'treasury.VendorPaymentRequest', 'vendor_payment_request_detail', 'vendor_payment_requests_list'),
    'PAYMENT_REQUEST_EXECUTED': ('treasury.payment_request_executed', 'treasury.VendorPaymentRequest', 'vendor_payment_request_detail', 'vendor_payment_requests_list'),
    'VAULT_TRANSFER': ('treasury.vault_transfer', 'treasury.Vault', 'vault_detail', 'vaults_list'),
    'VAULT_DEPOSIT': ('treasury.vault_deposit_withdraw', 'treasury.Vault', 'vault_detail', 'vaults_list'),
    'VAULT_WITHDRAWAL': ('treasury.vault_deposit_withdraw', 'treasury.Vault', 'vault_detail', 'vaults_list'),
    'VAULT_MANUAL_TRANSACTION': ('treasury.vault_deposit_withdraw', 'treasury.Vault', 'vault_detail', 'vaults_list'),
    'VAULT_TRANSACTION_REVERSED': ('treasury.transaction_reversed', 'treasury.VaultTransaction', None, 'vault_transactions_list'),
    # Inventory
    'TRANSFER_REQUEST_CREATED': ('inventory.transfer_requested', 'inventory.ProductTransferRequest', 'product_transfer_detail', 'product_transfers_list'),
    'TRANSFER_REQUEST_APPROVED': ('inventory.transfer_approved', 'inventory.ProductTransferRequest', 'product_transfer_detail', 'product_transfers_list'),
    'TRANSFER_REQUEST_REJECTED': ('inventory.transfer_rejected', 'inventory.ProductTransferRequest', 'product_transfer_detail', 'product_transfers_list'),
    'TRANSFER_REQUEST_EXECUTED': ('inventory.transfer_executed', 'inventory.ProductTransferRequest', 'product_transfer_detail', 'product_transfers_list'),
    'STOCK_IN': ('inventory.memo_created', 'inventory.InventoryMemo', 'inventory_memo_detail', 'inventory_memos_list'),
    'STOCK_OUT': ('inventory.memo_created', 'inventory.InventoryMemo', 'inventory_memo_detail', 'inventory_memos_list'),
    # Activities
    'VISIT_APPROVED': ('activities.visit_approved', 'activities.Visit', 'visit_detail', 'visits_list'),
    'VISIT_REJECTED': ('activities.visit_rejected', 'activities.Visit', 'visit_detail', 'visits_list'),
    'VISIT_DISTANCE_BYPASSED': ('activities.visit_gps_suspicious', 'activities.Visit', 'visit_detail', 'visits_list'),
    'VISIT_RESUBMITTED': ('activities.visit_reapproval_required', 'activities.Visit', 'visit_detail', 'visits_list'),
    'VISIT_PLAN_CREATED': ('activities.plan_submitted', 'activities.VisitPlan', None, 'planned_visits_list'),
    'VISIT_PLAN_APPROVED': ('activities.plan_approved', 'activities.VisitPlan', None, 'planned_visits_list'),
    'VISIT_PLAN_DISAPPROVED': ('activities.plan_rejected', 'activities.VisitPlan', None, 'planned_visits_list'),
    'AGREEMENT_CREATED': ('activities.agreement_created', 'activities.Agreement', 'agreement_detail', 'agreements_list'),
    'AGREEMENT_APPROVED': ('activities.agreement_approved', 'activities.Agreement', 'agreement_detail', 'agreements_list'),
    'AGREEMENT_REJECTED': ('activities.agreement_rejected', 'activities.Agreement', 'agreement_detail', 'agreements_list'),
    # Accounts
    'USER_CREATED': ('accounts.user_created', 'accounts.User', 'user_detail', 'users_list'),
    'USER_STATUS_TOGGLED': ('accounts.user_status_changed', 'accounts.User', 'user_detail', 'users_list'),
    'ROLE_UPDATED': ('accounts.role_updated', None, None, 'roles_list'),
    'ROLE_CREATED': ('accounts.role_updated', None, None, 'roles_list'),
    # Settings
    'LOCATION_SETTINGS_UPDATED': ('settings.critical_updated', None, None, 'location_settings'),
    'SALES_SETTINGS_UPDATED': ('settings.critical_updated', None, None, 'sales_settings'),
    'PURCHASE_SETTINGS_UPDATED': ('settings.critical_updated', None, None, 'purchase_settings'),
    'INVENTORY_SETTINGS_UPDATED': ('settings.critical_updated', None, None, 'inventory_settings'),
    'STORAGE_SETTINGS_UPDATED': ('settings.critical_updated', None, None, 'r2_storage_settings'),
    'SETTINGS_UPDATED': ('settings.critical_updated', None, None, 'branding_settings'),
}


def dispatch_from_audit_log(log_entry) -> None:
    """
    Translates a persisted SecurityAuditLog entry into centralized NotificationService.emit() calls.
    Never raises exceptions into callers.
    """
    try:
        action_type = (getattr(log_entry, 'action_type', '') or '').strip().upper()
        if not action_type or action_type not in AUDIT_ACTION_MAP:
            return
        if getattr(log_entry, 'status', 'success') == 'failed':
            return

        event_code, model_path, detail_url_name, list_url_name = AUDIT_ACTION_MAP[action_type]
        target_obj = None
        if model_path == 'accounts.User' and getattr(log_entry, 'target_user_id', None):
            target_obj = log_entry.target_user
        elif model_path:
            target_obj = _fetch_instance(model_path, getattr(log_entry, 'record_id', ''))

        action_url = ''
        if detail_url_name and target_obj is not None:
            action_url = _safe_reverse(detail_url_name, pk=target_obj.pk)
        if not action_url and list_url_name:
            action_url = _safe_reverse(list_url_name)

        rec_label = log_entry.record_name or log_entry.record_id or ''
        raw_desc = log_entry.description
        if isinstance(raw_desc, (dict, list)):
            import json
            body = json.dumps(raw_desc, ensure_ascii=False).strip()
        else:
            body = str(raw_desc or '').strip()
        if not body and rec_label:
            body = f"السجل: {rec_label}"

        dedupe_key = f"audit:{action_type}:{log_entry.record_id or log_entry.pk}"

        NotificationService.emit(
            event_code=event_code,
            target_obj=target_obj,
            actor=log_entry.actor,
            body=body,
            action_url=action_url,
            dedupe_key=dedupe_key,
            metadata={
                'audit_log_id': log_entry.pk,
                'action_type': action_type,
                'record_name': rec_label,
            },
        )

        # Secondary pending-approval event when a newly created order awaits manager approval
        if action_type == 'SALES_ORDER_CREATED' and target_obj is not None:
            if getattr(target_obj, 'status', '') in ('pending', 'manager_approval'):
                NotificationService.emit(
                    event_code='sales.order_pending_approval',
                    target_obj=target_obj,
                    actor=log_entry.actor,
                    title=f"أمر بيع بانتظار الاعتماد #{target_obj.order_number}",
                    body=body,
                    action_url=action_url,
                    dedupe_key=f"so_pending:{target_obj.pk}",
                )
        elif action_type == 'PURCHASE_ORDER_CREATED' and target_obj is not None:
            if getattr(target_obj, 'status', '') in ('pending', 'manager_approval'):
                NotificationService.emit(
                    event_code='purchases.order_pending_approval',
                    target_obj=target_obj,
                    actor=log_entry.actor,
                    title=f"أمر شراء بانتظار الاعتماد #{target_obj.order_number}",
                    body=body,
                    action_url=action_url,
                    dedupe_key=f"po_pending:{target_obj.pk}",
                )
    except Exception:
        logger.exception("dispatch_from_audit_log failed cleanly")
