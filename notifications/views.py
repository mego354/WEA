import json
import logging
from django.apps import apps
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST

from accounts.scope_service import ScopeResolutionService
from master_data.pagination_utils import paginate_queryset

from .fcm_provider import FCMProvider
from .models import Notification, NotificationDevice, PushDeliveryAttempt
from .registry import NOTIFICATION_MODULES_META
from .services import NotificationService

logger = logging.getLogger(__name__)

TARGET_MODEL_APP_MAP = {
    'salesorder': ('sales', 'SalesOrder'),
    'salesreturnorder': ('sales', 'SalesReturnOrder'),
    'collection': ('sales', 'Collection'),
    'customeraccount': ('sales', 'CustomerAccount'),
    'purchaseorder': ('purchases', 'PurchaseOrder'),
    'purchasereturnorder': ('purchases', 'PurchaseReturnOrder'),
    'vendorpayment': ('treasury', 'VendorPayment'),
    'vendorpaymentrequest': ('treasury', 'VendorPaymentRequest'),
    'vault': ('treasury', 'Vault'),
    'vaulttransaction': ('treasury', 'VaultTransaction'),
    'producttransferrequest': ('inventory', 'ProductTransferRequest'),
    'inventorymemo': ('inventory', 'InventoryMemo'),
    'inventorystock': ('inventory', 'InventoryStock'),
    'visit': ('activities', 'Visit'),
    'visitplan': ('activities', 'VisitPlan'),
    'agreement': ('activities', 'Agreement'),
    'contact': ('contacts', 'Contact'),
    'product': ('catalog', 'Product'),
    'user': ('accounts', 'User'),
}


def _parse_json_body(request):
    if request.content_type and 'application/json' in request.content_type:
        try:
            return json.loads(request.body.decode('utf-8') or '{}')
        except Exception:
            return {}
    return request.POST


def _is_safe_internal_target_url(request, target: str) -> bool:
    clean = (target or '').strip()
    if not clean or clean.startswith('//') or clean.lower().startswith(('javascript:', 'data:', 'file:', 'vbscript:')):
        return False
    return url_has_allowed_host_and_scheme(clean, allowed_hosts={request.get_host()}, require_https=False)


@login_required
def notifications_inbox(request):
    """Full-page responsive Notifications Inbox for Web & Mobile."""
    filter_read = request.GET.get('read', 'all').strip()
    filter_module = request.GET.get('module', '').strip()
    filter_severity = request.GET.get('severity', '').strip()

    qs = Notification.objects.filter(recipient=request.user).select_related('actor').order_by('-created_at', '-id')
    if filter_read == 'unread':
        qs = qs.filter(is_read=False)
    elif filter_read == 'read':
        qs = qs.filter(is_read=True)
    if filter_module:
        qs = qs.filter(module=filter_module)
    if filter_severity:
        qs = qs.filter(severity=filter_severity)

    paginator, page_obj = paginate_queryset(request, qs, default_per_page=25, max_per_page=100)
    unread_count = NotificationService.get_unread_count(request.user)
    user_devices = list(NotificationDevice.objects.filter(user=request.user).order_by('-last_seen_at')[:5])
    fcm_status = FCMProvider.get_config_status()

    return render(request, 'notifications/notifications_list.html', {
        'notifications': page_obj.object_list,
        'page_obj': page_obj,
        'paginator': paginator,
        'total_count': paginator.count,
        'unread_count': unread_count,
        'filter_read': filter_read,
        'filter_module': filter_module,
        'filter_severity': filter_severity,
        'modules_meta': NOTIFICATION_MODULES_META,
        'user_devices': user_devices,
        'fcm_status': fcm_status,
    })


@login_required
def notification_open(request, pk):
    """
    Marks notification read (recipient-owned only), verifies target record existence
    and current user permissions gracefully, and safely redirects to its action_url.
    """
    n = Notification.objects.filter(pk=pk, recipient=request.user).first()
    if not n:
        messages.warning(request, "عذراً، هذا الإشعار غير موجود أو لا ينتمي إلى حسابك.")
        return redirect('notifications_inbox')

    NotificationService.mark_as_read(request.user, n.id)

    # Check if the target record was deleted or user no longer has access
    t_model = (n.target_model or '').strip().lower()
    t_obj_id = n.target_object_id
    if t_model in TARGET_MODEL_APP_MAP and t_obj_id:
        app_label, model_name = TARGET_MODEL_APP_MAP[t_model]
        try:
            model_cls = apps.get_model(app_label, model_name)
            target_instance = model_cls.objects.filter(pk=t_obj_id).first()
            if target_instance is None:
                messages.warning(request, "عذراً، السجل المرتبط بهذا الإشعار تم حذفه أو لم يعد موجوداً.")
                return redirect('notifications_inbox')
            is_super = bool(request.user.is_superuser or getattr(request.user, 'is_super_admin', False))
            if not is_super and not ScopeResolutionService.can_user_access_object(request.user, target_instance, 'view'):
                messages.error(request, "عذراً، لم تعد تملك صلاحية عرض السجل المرتبط بهذا الإشعار.")
                return redirect('notifications_inbox')
        except Exception:
            logger.exception("Error validating target record for notification %s", n.id)

    target = (n.action_url or '').strip()
    if _is_safe_internal_target_url(request, target):
        return redirect(target)
    return redirect('notifications_inbox')


# ==========================================
# CAPACITOR-READY AUTHENTICATED JSON API (v1)
# ==========================================

@login_required
@require_GET
def api_notifications_list(request):
    """Paginated JSON notifications list for Web UI and Capacitor Android/iOS clients."""
    qs = Notification.objects.filter(recipient=request.user).select_related('actor').order_by('-created_at', '-id')

    is_read_param = request.GET.get('is_read', '').strip().lower()
    if is_read_param in ('true', '1', 'yes'):
        qs = qs.filter(is_read=True)
    elif is_read_param in ('false', '0', 'no'):
        qs = qs.filter(is_read=False)

    module = request.GET.get('module', '').strip()
    if module:
        qs = qs.filter(module=module)

    severity = request.GET.get('severity', '').strip()
    if severity:
        qs = qs.filter(severity=severity)

    try:
        page_size = min(100, max(1, int(request.GET.get('page_size') or request.GET.get('limit') or 20)))
    except ValueError:
        page_size = 20
    try:
        page_num = max(1, int(request.GET.get('page') or 1))
    except ValueError:
        page_num = 1

    total_count = qs.count()
    offset = (page_num - 1) * page_size
    items = list(qs[offset:offset + page_size])
    total_pages = max(1, (total_count + page_size - 1) // page_size)

    return JsonResponse({
        'status': 'ok',
        'unread_count': NotificationService.get_unread_count(request.user),
        'results': [NotificationService.serialize_notification(n) for n in items],
        'pagination': {
            'page': page_num,
            'page_size': page_size,
            'total_count': total_count,
            'total_pages': total_pages,
            'has_next': page_num < total_pages,
            'has_previous': page_num > 1,
        },
    })


@login_required
@require_GET
def api_notifications_unread_count(request):
    """Lightweight unread counter endpoint for visibility-aware polling & Capacitor badges."""
    return JsonResponse({
        'status': 'ok',
        'unread_count': NotificationService.get_unread_count(request.user),
    })


@login_required
@require_GET
def api_notifications_summary(request):
    """Combined unread count + latest items for header bell popover & mobile drawer."""
    try:
        limit = min(30, max(1, int(request.GET.get('limit') or 10)))
    except ValueError:
        limit = 10

    items = list(
        Notification.objects.filter(recipient=request.user)
        .select_related('actor')
        .order_by('-created_at', '-id')[:limit]
    )
    return JsonResponse({
        'status': 'ok',
        'unread_count': NotificationService.get_unread_count(request.user),
        'items': [NotificationService.serialize_notification(n) for n in items],
    })


@login_required
@require_GET
def api_notification_detail(request, pk):
    """Returns a single notification strictly owned by the authenticated user."""
    n = Notification.objects.filter(pk=pk, recipient=request.user).select_related('actor').first()
    if not n:
        return JsonResponse({'status': 'error', 'message': 'الإشعار غير موجود أو غير مصرح بالوصول إليه.'}, status=404)
    return JsonResponse({
        'status': 'ok',
        'notification': NotificationService.serialize_notification(n),
    })


@login_required
@require_POST
def api_notification_mark_read(request, pk):
    """Marks a single recipient-owned notification as read."""
    n = NotificationService.mark_as_read(request.user, pk)
    if not n:
        return JsonResponse({'status': 'error', 'message': 'الإشعار غير موجود أو غير مصرح بالوصول إليه.'}, status=404)
    return JsonResponse({
        'status': 'ok',
        'notification_id': n.id,
        'is_read': True,
        'unread_count': NotificationService.get_unread_count(request.user),
    })


@login_required
@require_POST
def api_notifications_mark_all_read(request):
    """Marks all (or filtered) unread notifications for the authenticated user as read."""
    payload = _parse_json_body(request)
    module = (payload.get('module') or '').strip() if hasattr(payload, 'get') else ''
    ids = payload.get('ids') if isinstance(payload, dict) else None
    if isinstance(ids, list):
        ids = [int(x) for x in ids if str(x).isdigit()]
    else:
        ids = None

    updated = NotificationService.mark_all_as_read(request.user, module=module, ids=ids)
    return JsonResponse({
        'status': 'ok',
        'updated_count': updated,
        'unread_count': NotificationService.get_unread_count(request.user),
    })


@login_required
@require_POST
def api_device_register(request):
    """
    Registers a Capacitor Android/iOS native FCM/APNs device token against the authenticated user.
    Accepts `device_token` (or `token` alias for compatibility) and rejects browser Web Push tokens
    when a native platform is specified.
    """
    payload = _parse_json_body(request)
    token = ''
    if hasattr(payload, 'get'):
        token = (payload.get('device_token') or payload.get('token') or '').strip()
    if not token:
        return JsonResponse({'status': 'error', 'message': 'device_token is required.'}, status=400)

    platform = (payload.get('platform') or 'android').strip().lower() if hasattr(payload, 'get') else 'android'
    default_provider = 'apns' if platform == 'ios' else 'fcm'
    provider = (payload.get('provider') or default_provider).strip().lower() if hasattr(payload, 'get') else default_provider
    device_name = (payload.get('device_name') or payload.get('deviceName') or '').strip() if hasattr(payload, 'get') else ''
    app_version = (payload.get('app_version') or payload.get('appVersion') or '').strip() if hasattr(payload, 'get') else ''
    app_id = (payload.get('app_id') or payload.get('appId') or payload.get('app') or '').strip() if hasattr(payload, 'get') else ''
    permission_status = (payload.get('permission_status') or payload.get('permissionStatus') or 'granted').strip() if hasattr(payload, 'get') else 'granted'

    try:
        device = NotificationService.register_device(
            user=request.user,
            device_token=token,
            platform=platform,
            provider=provider,
            device_name=device_name,
            app_version=app_version,
            app_id=app_id,
            permission_status=permission_status,
        )
    except ValueError as exc:
        logger.warning("[api_device_register] Rejected token for user=%s: %s", request.user.pk, str(exc))
        return JsonResponse({'status': 'error', 'message': str(exc)}, status=400)

    fcm_status = FCMProvider.get_config_status()
    return JsonResponse({
        'status': 'ok',
        'device_id': device.id,
        'masked_token': device.masked_token,
        'platform': device.platform,
        'provider': device.provider,
        'app_id': device.app_id,
        'is_active': device.is_active,
        'user_id': request.user.pk,
        'username': request.user.username,
        'push_delivery_enabled': fcm_status['fcm_configured'],
        'firebase_project_id': fcm_status['firebase_project_id'],
    })


@login_required
@require_POST
def api_device_unregister(request):
    """Deactivates a previously registered device token for the authenticated user."""
    payload = _parse_json_body(request)
    token = ''
    if hasattr(payload, 'get'):
        token = (payload.get('device_token') or payload.get('token') or '').strip()
    if not token:
        return JsonResponse({'status': 'error', 'message': 'device_token is required.'}, status=400)
    updated = NotificationService.unregister_device(request.user, token)
    return JsonResponse({'status': 'ok', 'deactivated_count': updated})


@login_required
@require_POST
def api_send_test_push(request):
    """
    Authenticated endpoint to trigger an end-to-end test push notification
    (Django -> FCM/APNs -> Physical Phone -> Deep Link Tap -> Target Page).
    """
    payload = _parse_json_body(request)
    title = (payload.get('title') or '').strip() if hasattr(payload, 'get') else ''
    body = (payload.get('body') or '').strip() if hasattr(payload, 'get') else ''
    target_url = (payload.get('target_url') or '/notifications/').strip() if hasattr(payload, 'get') else '/notifications/'
    raw_device_id = payload.get('device_id') if hasattr(payload, 'get') else None
    device_id = int(raw_device_id) if raw_device_id and str(raw_device_id).isdigit() else None

    if not _is_safe_internal_target_url(request, target_url):
        return JsonResponse({
            'status': 'error',
            'message': 'الرابط المستهدف غير صالح. يجب أن يكون مساراً داخلياً ينتمي لنفس النطاق (مثل /notifications/).',
        }, status=400)

    result = NotificationService.send_test_push_to_user(
        user=request.user,
        title=title,
        body=body,
        target_url=target_url,
        device_id=device_id,
    )
    http_status = 200 if result.get('success') or result.get('status') in ('ok', 'no_devices', 'provider_error') else 400
    return JsonResponse(result, status=http_status)


@login_required
@require_GET
def api_push_diagnostics(request):
    """
    Authorized diagnostic endpoint returning the authenticated user's registered devices
    (with masked tokens), FCM provider status, and recent push delivery attempts.
    Never exposes private keys or raw tokens.
    """
    fcm_config = FCMProvider.get_config_status()
    devices = list(NotificationDevice.objects.filter(user=request.user).order_by('-last_seen_at')[:10])
    attempts = list(
        PushDeliveryAttempt.objects.filter(recipient=request.user)
        .select_related('device')
        .order_by('-created_at', '-id')[:15]
    )

    return JsonResponse({
        'status': 'ok',
        'user': {
            'id': request.user.pk,
            'username': request.user.username,
            'name': getattr(request.user, 'name', '') or request.user.username,
        },
        'fcm_provider': fcm_config,
        'devices': [
            {
                'id': d.id,
                'platform': d.platform,
                'provider': d.provider,
                'masked_token': d.masked_token,
                'device_name': d.device_name,
                'app_version': d.app_version,
                'app_id': d.app_id,
                'permission_status': d.permission_status,
                'is_active': d.is_active,
                'last_seen_at': d.last_seen_at.isoformat() if d.last_seen_at else None,
                'last_push_attempt_at': d.last_push_attempt_at.isoformat() if d.last_push_attempt_at else None,
                'last_push_success_at': d.last_push_success_at.isoformat() if d.last_push_success_at else None,
                'last_push_error': d.last_push_error,
                'failure_count': d.failure_count,
                'deactivated_reason': d.deactivated_reason,
            }
            for d in devices
        ],
        'recent_attempts': [
            {
                'id': a.id,
                'notification_id': a.notification_id,
                'device_id': a.device_id,
                'masked_token': a.device.masked_token if a.device else '***',
                'provider': a.provider,
                'status': a.status,
                'target_url': a.target_url,
                'provider_message_id': a.provider_message_id,
                'error_code': a.error_code,
                'error_message': a.error_message,
                'created_at': a.created_at.isoformat() if a.created_at else None,
            }
            for a in attempts
        ],
    })
