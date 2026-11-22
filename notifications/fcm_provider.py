"""
Firebase Cloud Messaging (FCM HTTP v1) Native Push Delivery Provider for WEA Pharma ERP.
- Uses server-side Service Account credentials (from FIREBASE_SERVICE_ACCOUNT_JSON or FIREBASE_SERVICE_ACCOUNT_PATH).
- Never embeds or logs private keys, access tokens, or full device tokens.
- Supports structured notification + deep-link data payloads for Android and iOS (APNs via FCM).
- Automatically deactivates invalid/expired tokens (UNREGISTERED, INVALID_ARGUMENT, SENDER_ID_MISMATCH)
  and records PushDeliveryAttempt audit rows.
"""

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

import requests
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

FCM_SCOPE = 'https://www.googleapis.com/auth/firebase.messaging'
OAUTH_TOKEN_URI = 'https://oauth2.googleapis.com/token'

# Permanent token error codes returned by FCM HTTP v1 that require deactivating the device token
PERMANENT_TOKEN_ERROR_CODES = {
    'UNREGISTERED',
    'INVALID_ARGUMENT',
    'SENDER_ID_MISMATCH',
    'NOT_FOUND',
}


def mask_token(token: str) -> str:
    tok = (token or '').strip()
    if len(tok) <= 14:
        return f"{tok[:4]}...{tok[-2:]}" if len(tok) > 6 else "***"
    return f"{tok[:8]}...{tok[-6:]}"


def is_Likely_webpush_or_invalid_native_token(token: str, platform: str = 'android') -> Tuple[bool, str]:
    """
    Detects if a browser Web Push subscription or malformed token was accidentally sent
    when a native FCM/APNs token is expected.
    """
    tok = (token or '').strip()
    if not tok:
        return True, 'رمز الجهاز (device_token) فارغ.'
    if len(tok) < 12:
        return True, 'رمز الجهاز قصير جداً ولا يطابق تنسيق FCM/APNs الصالح.'
    if platform in ('android', 'ios'):
        if tok.startswith('http://') or tok.startswith('https://'):
            return True, 'تم استلام رابط Web Push بدلاً من رمز تسجيل FCM الأصلي للتطبيق.'
        if tok.startswith('{') and ('endpoint' in tok or 'keys' in tok):
            return True, 'تم استلام كائن Web Push Subscription بدلاً من رمز تسجيل FCM الأصلي للتطبيق.'
    return False, ''


class FCMProvider:
    _cached_access_token: Optional[str] = None
    _cached_token_expiry: float = 0.0
    _cached_project_id: Optional[str] = None

    @classmethod
    def _load_service_account_info(cls) -> Tuple[Optional[Dict[str, Any]], str]:
        """
        Loads Firebase Service Account JSON dictionary from settings or environment.
        Returns (service_account_dict, source_label).
        """
        raw_json = getattr(settings, 'FIREBASE_SERVICE_ACCOUNT_JSON', '') or os.getenv('FIREBASE_SERVICE_ACCOUNT_JSON', '')
        if raw_json and raw_json.strip():
            try:
                info = json.loads(raw_json.strip())
                if isinstance(info, dict) and info.get('private_key') and info.get('client_email'):
                    return info, 'env:FIREBASE_SERVICE_ACCOUNT_JSON'
            except Exception as exc:
                logger.error("[FCMProvider] Failed to parse FIREBASE_SERVICE_ACCOUNT_JSON: %s", type(exc).__name__)

        sa_path = (
            getattr(settings, 'FIREBASE_SERVICE_ACCOUNT_PATH', '')
            or os.getenv('FIREBASE_SERVICE_ACCOUNT_PATH', '')
            or os.getenv('GOOGLE_APPLICATION_CREDENTIALS', '')
        ).strip()
        if sa_path and os.path.isfile(sa_path):
            try:
                with open(sa_path, 'r', encoding='utf-8') as f:
                    info = json.load(f)
                if isinstance(info, dict) and info.get('private_key') and info.get('client_email'):
                    return info, f"file:{os.path.basename(sa_path)}"
            except Exception as exc:
                logger.error("[FCMProvider] Failed to load service account file: %s", type(exc).__name__)

        return None, 'unconfigured'

    @classmethod
    def get_config_status(cls) -> Dict[str, Any]:
        info, source = cls._load_service_account_info()
        project_id = (
            (info.get('project_id') if info else '')
            or getattr(settings, 'FIREBASE_PROJECT_ID', '')
            or os.getenv('FIREBASE_PROJECT_ID', '')
        ).strip()
        configured = bool(info and project_id and info.get('private_key') and info.get('client_email'))
        return {
            'fcm_configured': configured,
            'firebase_project_id': project_id or None,
            'credentials_source': source,
            'channel_id': getattr(settings, 'FCM_DEFAULT_CHANNEL_ID', 'app_push_notifications_channel'),
        }

    @classmethod
    def is_configured(cls) -> bool:
        return bool(cls.get_config_status()['fcm_configured'])

    @classmethod
    def get_project_id(cls) -> str:
        return cls.get_config_status()['firebase_project_id'] or ''

    @classmethod
    def _get_access_token(cls, service_account_info: Dict[str, Any]) -> str:
        """
        Generates an OAuth2 Bearer access token for FCM HTTP v1 using the service account.
        Caches the token in memory until 5 minutes before expiration.
        """
        now = time.time()
        project_id = service_account_info.get('project_id', '')
        if (
            cls._cached_access_token
            and cls._cached_project_id == project_id
            and now < (cls._cached_token_expiry - 300)
        ):
            return cls._cached_access_token

        # Use google.oauth2.service_account or PyJWT RS256 assertion
        try:
            from google.auth.transport.requests import Request as GoogleAuthRequest
            from google.oauth2 import service_account

            creds = service_account.Credentials.from_service_account_info(
                service_account_info,
                scopes=[FCM_SCOPE],
            )
            creds.refresh(GoogleAuthRequest())
            cls._cached_access_token = creds.token
            cls._cached_project_id = project_id
            cls._cached_token_expiry = creds.expiry.timestamp() if creds.expiry else (now + 3300)
            return creds.token
        except Exception:
            # Fallback to direct RS256 JWT assertion exchange
            import jwt

            iat = int(now)
            exp = iat + 3600
            token_uri = service_account_info.get('token_uri') or OAUTH_TOKEN_URI
            payload = {
                'iss': service_account_info['client_email'],
                'sub': service_account_info['client_email'],
                'aud': token_uri,
                'iat': iat,
                'exp': exp,
                'scope': FCM_SCOPE,
            }
            signed_jwt = jwt.encode(payload, service_account_info['private_key'], algorithm='RS256')
            resp = requests.post(
                token_uri,
                data={
                    'grant_type': 'urn:ietf:params:oauth:grant-type:jwt-bearer',
                    'assertion': signed_jwt,
                },
                timeout=15,
            )
            resp.raise_for_status()
            token_data = resp.json()
            access_token = token_data['access_token']
            cls._cached_access_token = access_token
            cls._cached_project_id = project_id
            cls._cached_token_expiry = now + int(token_data.get('expires_in', 3600))
            return access_token

    @classmethod
    def build_fcm_v1_payload(
        cls,
        device_token: str,
        title: str,
        body: str,
        notification_id: str = '',
        event_type: str = 'system',
        route_key: str = '',
        object_type: str = '',
        object_id: str = '',
        target_url: str = '/notifications/',
        module: str = 'general',
        severity: str = 'info',
        extra_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Builds a canonical FCM HTTP v1 message payload with structured deep-link data.
        All values in `message.data` are strictly strings as required by FCM HTTP v1.
        """
        from .formatters import get_default_route_key

        clean_target = (target_url or '').strip() or '/notifications/'
        open_url = f"/notifications/{notification_id}/open/" if notification_id and str(notification_id).isdigit() else clean_target
        resolved_route_key = (route_key or '').strip() or get_default_route_key(event_type)
        channel_id = getattr(settings, 'FCM_DEFAULT_CHANNEL_ID', 'app_push_notifications_channel')

        data_dict: Dict[str, str] = {
            'notification_id': str(notification_id or ''),
            'title': str(title or ''),
            'body': str(body or ''),
            'type': str(event_type or 'system'),
            'event_code': str(event_type or 'system'),
            'module': str(module or 'general'),
            'severity': str(severity or 'info'),
            'route_key': str(resolved_route_key),
            'record_type': str(object_type or ''),
            'record_id': str(object_id or ''),
            'object_type': str(object_type or ''),
            'object_id': str(object_id or ''),
            'open_url': str(open_url),
            'target_url': str(clean_target),
            'action_url': str(clean_target),
        }
        if extra_data:
            for k, v in extra_data.items():
                if v is not None and k not in data_dict:
                    data_dict[str(k)] = str(v)

        return {
            'message': {
                'token': device_token,
                'notification': {
                    'title': str(title or ''),
                    'body': str(body or ''),
                },
                'data': data_dict,
                'android': {
                    'priority': 'high',
                    'notification': {
                        'channel_id': channel_id,
                        'sound': 'default',
                        'default_vibrate_timings': True,
                    },
                },
                'apns': {
                    'headers': {
                        'apns-priority': '10',
                    },
                    'payload': {
                        'aps': {
                            'alert': {
                                'title': str(title or ''),
                                'body': str(body or ''),
                            },
                            'sound': 'default',
                        },
                    },
                },
            },
        }

    @classmethod
    def _extract_fcm_error(cls, response: requests.Response) -> Tuple[str, str]:
        """Extracts canonical FCM v1 error code (e.g. UNREGISTERED) and message from HTTP error response."""
        try:
            body = response.json()
            err = body.get('error', {}) if isinstance(body, dict) else {}
            status_code_str = str(err.get('status') or f"HTTP_{response.status_code}")
            msg = str(err.get('message') or response.text[:300])
            for detail in err.get('details', []) or []:
                if isinstance(detail, dict) and detail.get('errorCode'):
                    status_code_str = str(detail['errorCode'])
                    break
            return status_code_str, msg
        except Exception:
            return f"HTTP_{response.status_code}", (response.text or '')[:300]

    @classmethod
    def send_to_device(
        cls,
        device,
        title: str,
        body: str,
        notification_obj=None,
        notification_id: str = '',
        event_type: str = 'system',
        route_key: str = '',
        object_type: str = '',
        object_id: str = '',
        target_url: str = '/notifications/',
        module: str = 'general',
        severity: str = 'info',
        extra_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Dispatches a single notification to a registered NotificationDevice via FCM HTTP v1,
        updates device diagnostic timestamps, deactivates dead tokens, and logs a PushDeliveryAttempt.
        """
        from .models import PushDeliveryAttempt

        now = timezone.now()
        notif_id_str = str(notification_id or (notification_obj.pk if notification_obj else '') or '')
        final_target = (target_url or (notification_obj.action_url if notification_obj else '') or '').strip()
        if not final_target:
            final_target = f"/notifications/{notif_id_str}/open/" if notif_id_str.isdigit() else '/notifications/'

        # 1. Validate token format before calling provider
        is_bad, bad_reason = is_Likely_webpush_or_invalid_native_token(device.device_token, device.platform)
        if is_bad:
            device.is_active = False
            device.last_push_attempt_at = now
            device.last_push_error = f"INVALID_TOKEN_FORMAT: {bad_reason}"
            device.deactivated_reason = 'INVALID_TOKEN_FORMAT'
            device.failure_count = (device.failure_count or 0) + 1
            device.save(update_fields=[
                'is_active', 'last_push_attempt_at', 'last_push_error', 'deactivated_reason', 'failure_count'
            ])
            attempt = PushDeliveryAttempt.objects.create(
                notification=notification_obj,
                device=device,
                recipient=device.user,
                provider=device.provider,
                status='invalid_token',
                target_url=final_target,
                error_code='INVALID_TOKEN_FORMAT',
                error_message=bad_reason,
            )
            logger.warning(
                "[FCMProvider] Deactivated malformed token for user=%s device=%s token=%s reason=%s",
                device.user_id, device.id, device.masked_token, bad_reason,
            )
            return {
                'success': False,
                'status': 'invalid_token',
                'attempt_id': attempt.id,
                'device_id': device.id,
                'masked_token': device.masked_token,
                'error_code': 'INVALID_TOKEN_FORMAT',
                'error_message': bad_reason,
            }

        # 2. Check if server-side Firebase credentials exist
        sa_info, source = cls._load_service_account_info()
        project_id = (
            (sa_info.get('project_id') if sa_info else '')
            or getattr(settings, 'FIREBASE_PROJECT_ID', '')
            or os.getenv('FIREBASE_PROJECT_ID', '')
        ).strip()

        if not sa_info or not project_id:
            err_msg = (
                "FCM HTTP v1 credentials are not configured on the Django server. "
                "Set FIREBASE_SERVICE_ACCOUNT_PATH or FIREBASE_SERVICE_ACCOUNT_JSON in environment variables."
            )
            device.last_push_attempt_at = now
            device.last_push_error = f"MISSING_FCM_CREDENTIALS: {err_msg}"
            device.save(update_fields=['last_push_attempt_at', 'last_push_error'])
            attempt = PushDeliveryAttempt.objects.create(
                notification=notification_obj,
                device=device,
                recipient=device.user,
                provider=device.provider,
                status='skipped',
                target_url=final_target,
                error_code='MISSING_FCM_CREDENTIALS',
                error_message=err_msg,
            )
            logger.warning(
                "[FCMProvider] Push skipped (credentials missing) for user=%s device=%s token=%s",
                device.user_id, device.id, device.masked_token,
            )
            return {
                'success': False,
                'status': 'skipped',
                'attempt_id': attempt.id,
                'device_id': device.id,
                'masked_token': device.masked_token,
                'error_code': 'MISSING_FCM_CREDENTIALS',
                'error_message': err_msg,
            }

        # 3. Build payload & authenticate with Google OAuth2
        payload = cls.build_fcm_v1_payload(
            device_token=device.device_token,
            title=title,
            body=body,
            notification_id=notif_id_str,
            event_type=event_type,
            route_key=route_key or (getattr(notification_obj, 'route_key', '') if notification_obj else ''),
            object_type=object_type,
            object_id=object_id,
            target_url=final_target,
            module=module,
            severity=severity,
            extra_data=extra_data,
        )

        try:
            access_token = cls._get_access_token(sa_info)
            endpoint = f"https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"
            logger.info(
                "[FCMProvider] Sending FCM v1 push: project=%s user=%s device=%s token=%s type=%s target_url=%s",
                project_id, device.user_id, device.id, device.masked_token, event_type, final_target,
            )
            resp = requests.post(
                endpoint,
                headers={
                    'Authorization': f"Bearer {access_token}",
                    'Content-Type': 'application/json; charset=UTF-8',
                },
                json=payload,
                timeout=15,
            )

            if 200 <= resp.status_code < 300:
                resp_data = resp.json() if resp.content else {}
                msg_id = str(resp_data.get('name') or '')
                device.last_push_attempt_at = now
                device.last_push_success_at = now
                device.last_push_error = ''
                device.failure_count = 0
                device.save(update_fields=[
                    'last_push_attempt_at', 'last_push_success_at', 'last_push_error', 'failure_count'
                ])
                attempt = PushDeliveryAttempt.objects.create(
                    notification=notification_obj,
                    device=device,
                    recipient=device.user,
                    provider=device.provider,
                    status='sent',
                    target_url=final_target,
                    provider_message_id=msg_id,
                )
                logger.info(
                    "[FCMProvider] Push delivered: user=%s device=%s token=%s message_id=%s",
                    device.user_id, device.id, device.masked_token, msg_id,
                )
                return {
                    'success': True,
                    'status': 'sent',
                    'attempt_id': attempt.id,
                    'device_id': device.id,
                    'masked_token': device.masked_token,
                    'provider_message_id': msg_id,
                    'target_url': final_target,
                }

            # Handle FCM rejection / error
            err_code, err_msg = cls._extract_fcm_error(resp)
            is_permanent = (
                err_code in PERMANENT_TOKEN_ERROR_CODES
                or resp.status_code == 404
                or 'not a valid fcm registration token' in err_msg.lower()
                or 'requested entity was not found' in err_msg.lower()
            )
            attempt_status = 'invalid_token' if is_permanent else 'failed'
            device.last_push_attempt_at = now
            device.last_push_error = f"{err_code}: {err_msg}"
            device.failure_count = (device.failure_count or 0) + 1
            update_fields = ['last_push_attempt_at', 'last_push_error', 'failure_count']
            if is_permanent:
                device.is_active = False
                device.deactivated_reason = err_code
                update_fields.extend(['is_active', 'deactivated_reason'])
            device.save(update_fields=update_fields)

            attempt = PushDeliveryAttempt.objects.create(
                notification=notification_obj,
                device=device,
                recipient=device.user,
                provider=device.provider,
                status=attempt_status,
                target_url=final_target,
                error_code=err_code,
                error_message=err_msg,
            )
            logger.warning(
                "[FCMProvider] Push rejected by FCM: user=%s device=%s token=%s code=%s deactivated=%s msg=%s",
                device.user_id, device.id, device.masked_token, err_code, is_permanent, err_msg,
            )
            return {
                'success': False,
                'status': attempt_status,
                'attempt_id': attempt.id,
                'device_id': device.id,
                'masked_token': device.masked_token,
                'error_code': err_code,
                'error_message': err_msg,
                'deactivated': is_permanent,
            }

        except Exception as exc:
            err_msg = f"{type(exc).__name__}: {str(exc)[:300]}"
            device.last_push_attempt_at = now
            device.last_push_error = err_msg
            device.failure_count = (device.failure_count or 0) + 1
            device.save(update_fields=['last_push_attempt_at', 'last_push_error', 'failure_count'])
            attempt = PushDeliveryAttempt.objects.create(
                notification=notification_obj,
                device=device,
                recipient=device.user,
                provider=device.provider,
                status='failed',
                target_url=final_target,
                error_code='TRANSPORT_ERROR',
                error_message=err_msg,
            )
            logger.error(
                "[FCMProvider] Transport exception for user=%s device=%s token=%s: %s",
                device.user_id, device.id, device.masked_token, err_msg,
            )
            return {
                'success': False,
                'status': 'failed',
                'attempt_id': attempt.id,
                'device_id': device.id,
                'masked_token': device.masked_token,
                'error_code': 'TRANSPORT_ERROR',
                'error_message': err_msg,
            }
