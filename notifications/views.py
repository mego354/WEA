import json
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST

from master_data.pagination_utils import paginate_queryset

from .models import Notification
from .registry import NOTIFICATION_MODULES_META
from .services import NotificationService


def _parse_json_body(request):
    if request.content_type and 'application/json' in request.content_type:
        try:
            return json.loads(request.body.decode('utf-8') or '{}')
        except Exception:
            return {}
    return request.POST


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
    })


@login_required
def notification_open(request, pk):
    """Marks notification read (recipient-owned only) and safely redirects to its action_url."""
    n = get_object_or_404(Notification, pk=pk, recipient=request.user)
    NotificationService.mark_as_read(request.user, n.id)
    target = (n.action_url or '').strip()
    if target and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=False):
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
    """Registers a Capacitor Android/iOS or Web Push device token for future push channels."""
    payload = _parse_json_body(request)
    token = (payload.get('device_token') or '').strip() if hasattr(payload, 'get') else ''
    if not token:
        return JsonResponse({'status': 'error', 'message': 'device_token is required.'}, status=400)
    device = NotificationService.register_device(
        user=request.user,
        device_token=token,
        platform=(payload.get('platform') or 'android').strip(),
        provider=(payload.get('provider') or 'fcm').strip(),
        device_name=(payload.get('device_name') or '').strip(),
        app_version=(payload.get('app_version') or '').strip(),
    )
    return JsonResponse({
        'status': 'ok',
        'device_id': device.id,
        'platform': device.platform,
        'provider': device.provider,
        'is_active': device.is_active,
        'push_delivery_enabled': False,
    })


@login_required
@require_POST
def api_device_unregister(request):
    """Deactivates a previously registered device token for the authenticated user."""
    payload = _parse_json_body(request)
    token = (payload.get('device_token') or '').strip() if hasattr(payload, 'get') else ''
    if not token:
        return JsonResponse({'status': 'error', 'message': 'device_token is required.'}, status=400)
    updated = NotificationService.unregister_device(request.user, token)
    return JsonResponse({'status': 'ok', 'deactivated_count': updated})
