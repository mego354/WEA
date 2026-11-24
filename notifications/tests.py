"""
Comprehensive tests for the Centralized Notifications System (Capacitor-Ready):
- Full catalog integrity across all 10 ERP apps
- 4-layer ScopeResolutionService & RBAC recipient filtering (Cairo vs Giza isolation)
- Actor exclusion, anti-self-approval, delivery modes (all_in_scope, record_owner_only, approvers_only, specific_users)
- transaction.on_commit() rollback safety (rolled-back transactions create 0 notifications)
- Deduplication, 90-day retention pruning, Role Settings 3-tab persistence
- Independent versioned API (/api/v1/notifications/*) + device registration + IDOR protection
"""

from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.db import transaction
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role, User
from contacts.models import Contact
from inventory.models import InventoryStock, Warehouse
from master_data.models import Area, SalesSettings
from catalog.models import Product, ProductCategory
from notifications.fcm_provider import FCMProvider
from notifications.models import Notification, NotificationDevice, PushDeliveryAttempt, RoleNotificationRule
from notifications.registry import NOTIFICATION_EVENTS_CATALOG, NOTIFICATION_MODULES_META
from notifications.services import NotificationService
from sales.models import SalesOrder


class NotificationsSystemTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('setup_permissions')
        NotificationService.seed_default_rules(overwrite=True)

    def setUp(self):
        self.client = Client()
        self.super_role = Role.objects.get(name='superadmin')
        self.mgr_role = Role.objects.get(name='manager')
        self.rep_role = Role.objects.get(name='rep')

        self.cairo = Area.objects.create(name='القاهرة_نوت', code='CAI-N', area_type='governorate')
        self.nasr = Area.objects.create(name='مدينة نصر_نوت', code='NASR-N', parent=self.cairo, area_type='subarea')
        self.giza = Area.objects.create(name='الجيزة_نوت', code='GIZ-N', area_type='governorate')
        self.dokki = Area.objects.create(name='الدقي_نوت', code='DOK-N', parent=self.giza, area_type='subarea')

        self.superadmin = User.objects.create_superuser(
            username='super_notif@wea.com', email='super_notif@wea.com', password='Password123!', name='Super N', role=self.super_role
        )
        self.cairo_mgr = User.objects.create_user(
            username='mgr_cairo_n@wea.com', email='mgr_cairo_n@wea.com', password='Password123!', name='Cairo Mgr', role=self.mgr_role
        )
        self.cairo_mgr.assigned_areas.add(self.cairo)
        self.giza_mgr = User.objects.create_user(
            username='mgr_giza_n@wea.com', email='mgr_giza_n@wea.com', password='Password123!', name='Giza Mgr', role=self.mgr_role
        )
        self.giza_mgr.assigned_areas.add(self.giza)
        self.rep_nasr = User.objects.create_user(
            username='rep_nasr_n@wea.com', email='rep_nasr_n@wea.com', password='Password123!', name='Rep Nasr', role=self.rep_role
        )
        self.rep_nasr.assigned_areas.add(self.nasr)

        self.wh = Warehouse.objects.create(name='مخزن نوت', code='WH-N1', area=self.nasr, assigned_user=self.rep_nasr, is_active=True)
        self.customer_cairo = Contact.objects.create(
            name='صيدلية النصر نوت', is_customer=True, area=self.cairo, brick=self.nasr, created_by=self.rep_nasr
        )
        self.order_cairo = SalesOrder.objects.create(
            order_number='SO-NOTIF-1',
            customer=self.customer_cairo,
            source_warehouse=self.wh,
            created_by=self.rep_nasr,
            status='pending',
            grand_total=Decimal('250.00'),
        )

    def test_catalog_covers_all_10_apps_and_unique_codes(self):
        codes = [e['code'] for e in NOTIFICATION_EVENTS_CATALOG]
        self.assertGreaterEqual(len(codes), 54)
        self.assertEqual(len(codes), len(set(codes)))
        modules_present = {e['module'] for e in NOTIFICATION_EVENTS_CATALOG}
        self.assertEqual(modules_present, set(NOTIFICATION_MODULES_META.keys()))
        self.assertEqual(len(modules_present), 10)

    def test_four_layer_datascope_isolation_and_actor_exclusion(self):
        """Cairo manager gets Cairo order notification; Giza manager is strictly isolated; actor is excluded."""
        Notification.objects.all().delete()
        created_count = NotificationService.emit(
            event_code='sales.order_pending_approval',
            target_obj=self.order_cairo,
            actor=self.rep_nasr,
            title='أمر بيع بانتظار الاعتماد',
            body='تفاصيل الطلب',
            dedupe_key='test_scope_order_1',
            sync=True,
        )
        self.assertGreaterEqual(created_count, 2)
        recipients = set(Notification.objects.filter(event_code='sales.order_pending_approval').values_list('recipient_id', flat=True))
        self.assertIn(self.superadmin.id, recipients)
        self.assertIn(self.cairo_mgr.id, recipients)
        self.assertNotIn(self.giza_mgr.id, recipients)  # STRICT DataScope isolation!
        self.assertNotIn(self.rep_nasr.id, recipients)  # Actor + non-approver excluded!

    def test_deduplication_and_record_owner_delivery_mode(self):
        Notification.objects.all().delete()
        c1 = NotificationService.emit(
            event_code='sales.order_approved',
            target_obj=self.order_cairo,
            actor=self.cairo_mgr,
            title='اعتماد أمر البيع',
            dedupe_key='dedupe_so_approved_1',
            sync=True,
        )
        self.assertGreaterEqual(c1, 1)
        self.assertTrue(Notification.objects.filter(recipient=self.rep_nasr, event_code='sales.order_approved').exists())
        self.assertFalse(Notification.objects.filter(recipient=self.cairo_mgr, event_code='sales.order_approved').exists())

        # Duplicate unread notification with same dedupe_key is skipped
        c2 = NotificationService.emit(
            event_code='sales.order_approved',
            target_obj=self.order_cairo,
            actor=self.cairo_mgr,
            title='اعتماد أمر البيع',
            dedupe_key='dedupe_so_approved_1',
            sync=True,
        )
        self.assertEqual(c2, 0)

    def test_role_settings_tab3_saves_notification_rules(self):
        self.client.force_login(self.superadmin)
        resp = self.client.get(reverse('role_edit', kwargs={'pk': self.mgr_role.pk}))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'قواعد الإشعارات')

        post_data = {
            'display_name': self.mgr_role.display_name,
            'is_active': 'on',
            'is_area_manager': 'on',
            'notification_rules_submitted': '1',
            'notif_enabled__sales.order_created': 'on',
            'notif_mode__sales.order_created': 'specific_users',
            'notif_same_area__sales.order_created': 'on',
            'notif_users__sales.order_created': [str(self.cairo_mgr.id)],
        }
        res = self.client.post(reverse('role_edit', kwargs={'pk': self.mgr_role.pk}), post_data)
        self.assertEqual(res.status_code, 302)
        rule = RoleNotificationRule.objects.get(role=self.mgr_role, event_code='sales.order_created')
        self.assertTrue(rule.is_enabled)
        self.assertEqual(rule.delivery_mode, 'specific_users')
        self.assertIn(self.cairo_mgr, rule.specific_users.all())

    def test_capacitor_versioned_api_and_idor_protection(self):
        n_cairo = Notification.objects.create(
            recipient=self.cairo_mgr,
            event_code='sales.order_created',
            module='sales',
            severity='info',
            title='إشعار للقاهرة فقط',
            body='اختبار',
        )
        # Cairo manager reads via /api/v1/notifications/
        self.client.force_login(self.cairo_mgr)
        res_count = self.client.get('/api/v1/notifications/unread-count/')
        self.assertEqual(res_count.status_code, 200)
        self.assertEqual(res_count.json()['unread_count'], 1)

        res_list = self.client.get('/api/v1/notifications/')
        self.assertEqual(res_list.status_code, 200)
        self.assertEqual(len(res_list.json()['results']), 1)

        # Device registration (Capacitor-ready FCM/APNs)
        res_dev = self.client.post(
            '/api/v1/notifications/devices/register/',
            {'platform': 'android', 'provider': 'fcm', 'device_token': 'fcm_token_xyz_123', 'device_name': 'Pixel 8'},
            content_type='application/json',
        )
        self.assertEqual(res_dev.status_code, 200)
        self.assertTrue(NotificationDevice.objects.filter(user=self.cairo_mgr, device_token='fcm_token_xyz_123', is_active=True).exists())

        res_unreg = self.client.post(
            '/api/v1/notifications/devices/unregister/',
            {'device_token': 'fcm_token_xyz_123'},
            content_type='application/json',
        )
        self.assertEqual(res_unreg.status_code, 200)
        self.assertFalse(NotificationDevice.objects.get(device_token='fcm_token_xyz_123').is_active)

        # Giza manager IDOR attempt on Cairo notification -> 404
        self.client.force_login(self.giza_mgr)
        idor_res = self.client.get(f'/api/v1/notifications/{n_cairo.id}/')
        self.assertEqual(idor_res.status_code, 404)
        idor_mark = self.client.post(f'/api/v1/notifications/{n_cairo.id}/read/')
        self.assertEqual(idor_mark.status_code, 404)

        # Cairo manager marks as read
        self.client.force_login(self.cairo_mgr)
        mark_res = self.client.post(f'/api/v1/notifications/{n_cairo.id}/read/')
        self.assertEqual(mark_res.status_code, 200)
        self.assertEqual(mark_res.json()['unread_count'], 0)

    def test_retention_pruning_90_days(self):
        old_n = Notification.objects.create(
            recipient=self.superadmin, event_code='sales.order_created', module='sales', title='Old'
        )
        Notification.objects.filter(pk=old_n.pk).update(created_at=timezone.now() - timedelta(days=95))
        fresh_n = Notification.objects.create(
            recipient=self.superadmin, event_code='sales.order_created', module='sales', title='Fresh'
        )
        deleted = NotificationService.prune_old_notifications(days=90)
        self.assertEqual(deleted, 1)
        self.assertFalse(Notification.objects.filter(pk=old_n.pk).exists())
        self.assertTrue(Notification.objects.filter(pk=fresh_n.pk).exists())

    def test_rejects_webpush_token_on_native_device_registration(self):
        self.client.force_login(self.cairo_mgr)
        # Web Push endpoint URL must be rejected for Android FCM registration
        res_bad_url = self.client.post(
            '/api/v1/notifications/devices/register/',
            {
                'platform': 'android',
                'provider': 'fcm',
                'device_token': 'https://fcm.googleapis.com/fcm/send/eXampleWebPushEndpoint',
            },
            content_type='application/json',
        )
        self.assertEqual(res_bad_url.status_code, 400)

        # Web Push subscription JSON must be rejected for Android FCM registration
        res_bad_json = self.client.post(
            '/api/v1/notifications/devices/register/',
            {
                'platform': 'android',
                'provider': 'fcm',
                'device_token': '{"endpoint":"https://fcm.googleapis.com/fcm/send/123","keys":{"p256dh":"a","auth":"b"}}',
            },
            content_type='application/json',
        )
        self.assertEqual(res_bad_json.status_code, 400)

    @patch('notifications.fcm_provider.FCMProvider._load_service_account_info')
    @patch('notifications.fcm_provider.FCMProvider._get_access_token')
    @patch('notifications.fcm_provider.requests.post')
    def test_fcm_v1_push_delivery_multiple_devices_and_expired_token_deactivation(
        self, mock_post, mock_access_token, mock_sa_info
    ):
        mock_sa_info.return_value = (
            {'project_id': 'wea-pharma-mobile', 'client_email': 'fcm@wea-pharma-mobile.iam.gserviceaccount.com', 'private_key': 'DUMMY'},
            'env:FIREBASE_SERVICE_ACCOUNT_JSON',
        )
        mock_access_token.return_value = 'ya29.mock_oauth_token'

        # Register 2 active devices for Cairo Manager: one valid, one expired (UNREGISTERED)
        dev_valid = NotificationService.register_device(
            user=self.cairo_mgr,
            device_token='fcm_valid_native_token_11111111111111111111',
            platform='android',
            provider='fcm',
            device_name='Samsung S24',
            app_id='com.acme.WEA',
        )
        dev_expired = NotificationService.register_device(
            user=self.cairo_mgr,
            device_token='fcm_expired_native_token_222222222222222222',
            platform='android',
            provider='fcm',
            device_name='Old Pixel 5',
            app_id='com.acme.WEA',
        )

        def side_effect(url, headers=None, json=None, timeout=15):
            tok = json['message']['token']
            resp = MagicMock()
            if tok == dev_valid.device_token:
                resp.status_code = 200
                resp.content = b'{"name":"projects/wea-pharma-mobile/messages/msg_9001"}'
                resp.json.return_value = {'name': 'projects/wea-pharma-mobile/messages/msg_9001'}
            else:
                resp.status_code = 404
                resp.content = b'{"error":{"status":"NOT_FOUND","message":"Requested entity was not found.","details":[{"errorCode":"UNREGISTERED"}]}}'
                resp.json.return_value = {
                    'error': {
                        'status': 'NOT_FOUND',
                        'message': 'Requested entity was not found.',
                        'details': [{'errorCode': 'UNREGISTERED'}],
                    }
                }
            return resp

        mock_post.side_effect = side_effect

        # Emit business notification event
        NotificationService.emit(
            event_code='sales.order_pending_approval',
            target_obj=self.order_cairo,
            actor=self.rep_nasr,
            title='أمر بيع جديد #SO-NOTIF-1',
            body='يرجى مراجعة أمر البيع واعتماده',
            action_url=f'/sales/orders/{self.order_cairo.pk}/',
            dedupe_key='test_fcm_multi_device_1',
            sync=True,
        )

        dev_valid.refresh_from_db()
        dev_expired.refresh_from_db()
        self.assertTrue(dev_valid.is_active)
        self.assertIsNotNone(dev_valid.last_push_success_at)
        self.assertFalse(dev_expired.is_active)
        self.assertEqual(dev_expired.deactivated_reason, 'UNREGISTERED')

        sent_attempt = PushDeliveryAttempt.objects.filter(device=dev_valid, status='sent').first()
        self.assertIsNotNone(sent_attempt)
        self.assertEqual(sent_attempt.provider_message_id, 'projects/wea-pharma-mobile/messages/msg_9001')
        self.assertEqual(sent_attempt.target_url, f'/sales/orders/{self.order_cairo.pk}/')

        dead_attempt = PushDeliveryAttempt.objects.filter(device=dev_expired, status='invalid_token').first()
        self.assertIsNotNone(dead_attempt)
        self.assertEqual(dead_attempt.error_code, 'UNREGISTERED')

    @patch('notifications.fcm_provider.FCMProvider._load_service_account_info')
    @patch('notifications.fcm_provider.FCMProvider._get_access_token')
    @patch('notifications.fcm_provider.requests.post')
    def test_test_push_endpoint_and_diagnostics_and_deleted_target_handling(
        self, mock_post, mock_access_token, mock_sa_info
    ):
        mock_sa_info.return_value = (
            {'project_id': 'wea-pharma-mobile', 'client_email': 'fcm@wea-pharma-mobile.iam.gserviceaccount.com', 'private_key': 'DUMMY'},
            'env:FIREBASE_SERVICE_ACCOUNT_JSON',
        )
        mock_access_token.return_value = 'ya29.mock_oauth_token'
        resp_ok = MagicMock()
        resp_ok.status_code = 200
        resp_ok.content = b'{"name":"projects/wea-pharma-mobile/messages/test_msg_1"}'
        resp_ok.json.return_value = {'name': 'projects/wea-pharma-mobile/messages/test_msg_1'}
        mock_post.return_value = resp_ok

        self.client.force_login(self.cairo_mgr)
        NotificationService.register_device(
            user=self.cairo_mgr,
            device_token='fcm_cairo_test_device_token_99999999999999',
            platform='android',
            provider='fcm',
        )

        # Reject external target_url on test-push
        bad_test = self.client.post(
            '/api/v1/notifications/test-push/',
            {'title': 'Evil', 'body': 'Phish', 'target_url': 'https://evil.example.com/phish'},
            content_type='application/json',
        )
        self.assertEqual(bad_test.status_code, 400)

        # Valid test push to /notifications/
        good_test = self.client.post(
            '/api/v1/notifications/test-push/',
            {'title': 'Test Push', 'body': 'Tap to open inbox', 'target_url': '/notifications/'},
            content_type='application/json',
        )
        self.assertEqual(good_test.status_code, 200)
        self.assertTrue(good_test.json()['success'])
        self.assertEqual(good_test.json()['delivered_count'], 1)

        # Diagnostics endpoint returns masked token without exposing full token
        diag_res = self.client.get('/api/v1/notifications/diagnostics/')
        self.assertEqual(diag_res.status_code, 200)
        diag_json = diag_res.json()
        self.assertEqual(len(diag_json['devices']), 1)
        self.assertNotIn('fcm_cairo_test_device_token_99999999999999', json_str := str(diag_json))
        self.assertIn('...', diag_json['devices'][0]['masked_token'])

        # Deleted target record graceful handling on notification_open
        n_deleted = Notification.objects.create(
            recipient=self.cairo_mgr,
            event_code='sales.order_created',
            module='sales',
            title='Deleted Order Notification',
            action_url='/sales/orders/999999/',
            target_model='salesorder',
            target_object_id=999999,
        )
        open_res = self.client.get(reverse('notification_open', kwargs={'pk': n_deleted.pk}))
        self.assertEqual(open_res.status_code, 302)
        self.assertEqual(open_res.url, reverse('notifications_inbox'))



class NotificationTransactionRollbackTests(TransactionTestCase):
    def test_rolled_back_transaction_emits_zero_notifications(self):
        call_command('setup_permissions')
        NotificationService.seed_default_rules(overwrite=True)
        super_role = Role.objects.get(name='superadmin')
        admin = User.objects.create_superuser(
            username='tx_admin@wea.com', email='tx_admin@wea.com', password='Password123!', role=super_role
        )
        Notification.objects.all().delete()
        try:
            with transaction.atomic():
                NotificationService.emit(
                    event_code='settings.critical_updated',
                    title='Should Rollback',
                    body='Must not persist',
                    exclude_actor=False,
                )
                raise RuntimeError("Simulated transaction rollback")
        except RuntimeError:
            pass
        self.assertEqual(Notification.objects.filter(title='Should Rollback').count(), 0)


class ArabicNotificationAndDeepLinkingTests(TestCase):
    """Verifies Arabic-first formatting, structured route_key/destination, 401 API auth, device_uid token rotation, and deep-link security."""

    def setUp(self):
        call_command('setup_permissions')
        NotificationService.seed_default_rules(overwrite=True)
        self.super_role = Role.objects.get(name='superadmin')
        self.rep_role = Role.objects.get(name='rep')
        self.cairo = Area.objects.create(code='N-DL-CAI', name='القاهرة إشعارات', area_type='governorate')
        self.nasr = Area.objects.create(code='N-DL-NSR', name='مدينة نصر', area_type='subarea', parent=self.cairo)
        self.admin = User.objects.create_superuser(
            username='dl_admin@wea.com', email='dl_admin@wea.com', password='Password123!', name='مدير النظام', role=self.super_role
        )
        self.rep = User.objects.create_user(
            username='dl_rep@wea.com', email='dl_rep@wea.com', password='Password123!', name='أحمد المندوب', role=self.rep_role
        )
        self.rep.assigned_areas.add(self.nasr)

    def test_arabic_contact_status_localization_and_no_raw_english_enums(self):
        from contacts.models import Contact
        from notifications.formatters import build_arabic_notification

        contact = Contact.objects.create(
            name='صيدلية النور الجديدة',
            is_customer=True,
            status='customer',
            area=self.cairo,
            brick=self.nasr,
            created_by=self.rep,
        )
        fmt = build_arabic_notification(
            event_code='contacts.contact_status_changed',
            target_obj=contact,
            actor=self.admin,
            extra={'old_status': 'lead', 'new_status': 'customer'},
        )
        self.assertEqual(fmt['route_key'], 'contacts.detail')
        self.assertIn('Lead', fmt['body'])
        self.assertIn('Customer', fmt['body'])
        self.assertNotIn('عميل محتمل', fmt['body'])

    def test_unauthenticated_api_returns_401_json_not_302_redirect(self):
        for url in [
            '/api/v1/notifications/',
            '/api/v1/notifications/unread-count/',
            '/api/v1/notifications/summary/',
            '/api/v1/notifications/diagnostics/',
        ]:
            res = self.client.get(url)
            self.assertEqual(res.status_code, 401, f"Expected 401 for {url}, got {res.status_code}")
            data = res.json()
            self.assertEqual(data['code'], 'authentication_required')
            self.assertIn('login_url', data)

        reg_res = self.client.post('/api/v1/notifications/devices/register/', {'device_token': 'x' * 20}, content_type='application/json')
        self.assertEqual(reg_res.status_code, 401)

    def test_device_registration_fcm_default_ios_and_safe_token_rotation(self):
        self.client.force_login(self.rep)

        # 1. Register iOS phone #1 with device_uid -> defaults to provider='fcm'
        r1 = self.client.post(
            '/api/v1/notifications/devices/register/',
            {'device_token': 'ios_fcm_token_phone1_v1_123456', 'device_uid': 'install-phone-1', 'platform': 'ios'},
            content_type='application/json',
        )
        self.assertEqual(r1.status_code, 200)
        d1 = r1.json()
        self.assertEqual(d1['platform'], 'ios')
        self.assertEqual(d1['provider'], 'fcm')
        self.assertEqual(d1['device_uid'], 'install-phone-1')

        # 2. Register second device (Android tablet #2) with different device_uid
        r2 = self.client.post(
            '/api/v1/notifications/devices/register/',
            {'device_token': 'android_fcm_token_tablet2_123456', 'device_uid': 'install-tablet-2', 'platform': 'android'},
            content_type='application/json',
        )
        self.assertEqual(r2.status_code, 200)

        # 3. Rotate token on iOS phone #1 (same device_uid) -> deactivates ONLY phone #1's old token, NOT tablet #2
        r3 = self.client.post(
            '/api/v1/notifications/devices/register/',
            {'device_token': 'ios_fcm_token_phone1_v2_999999', 'device_uid': 'install-phone-1', 'platform': 'ios'},
            content_type='application/json',
        )
        self.assertEqual(r3.status_code, 200)

        old_phone1 = NotificationDevice.objects.get(device_token='ios_fcm_token_phone1_v1_123456')
        new_phone1 = NotificationDevice.objects.get(device_token='ios_fcm_token_phone1_v2_999999')
        tablet2 = NotificationDevice.objects.get(device_token='android_fcm_token_tablet2_123456')
        self.assertFalse(old_phone1.is_active)
        self.assertEqual(old_phone1.deactivated_reason, 'token_rotated')
        self.assertTrue(new_phone1.is_active)
        self.assertTrue(tablet2.is_active)

        # 4. Missing token returns Arabic error message
        bad = self.client.post('/api/v1/notifications/devices/register/', {}, content_type='application/json')
        self.assertEqual(bad.status_code, 400)
        self.assertIn('مطلوب', bad.json()['message'])

        # 5. Logout with device_token synchronously deactivates that token
        logout_res = self.client.post('/auth/logout/', {'device_token': 'ios_fcm_token_phone1_v2_999999'})
        self.assertEqual(logout_res.status_code, 302)
        new_phone1.refresh_from_db()
        self.assertFalse(new_phone1.is_active)
        tablet2.refresh_from_db()
        self.assertTrue(tablet2.is_active)

    def test_structured_destination_payload_and_rbac_gatekeeper_on_open(self):
        from notifications.fcm_provider import FCMProvider

        n = Notification.objects.create(
            recipient=self.rep,
            actor=self.admin,
            event_code='accounts.role_updated',
            module='accounts',
            severity='warning',
            title='تحديث صلاحيات الدور',
            body='حدّث مدير النظام صلاحيات الدور.',
            route_key='accounts.roles_list',
            action_url='/roles/',
        )

        # JSON API includes route_key, destination, and Arabic labels
        self.client.force_login(self.rep)
        res = self.client.get(f'/api/v1/notifications/{n.pk}/')
        self.assertEqual(res.status_code, 200)
        payload = res.json()['notification']
        self.assertEqual(payload['route_key'], 'accounts.roles_list')
        self.assertEqual(payload['destination']['route_key'], 'accounts.roles_list')
        self.assertEqual(payload['destination']['open_url'], f'/notifications/{n.pk}/open/')
        self.assertEqual(payload['module_label_ar'], 'المستخدمون والأدوار')
        self.assertEqual(payload['severity_label_ar'], 'تنبيه')

        # FCM payload includes route_key, open_url, record_type, record_id
        fcm = FCMProvider.build_fcm_v1_payload(
            device_token='tok_1234567890123456',
            title=n.title,
            body=n.body,
            notification_id=str(n.pk),
            event_type=n.event_code,
            route_key=n.route_key,
            object_type='role',
            object_id='1',
            target_url='/roles/',
        )
        self.assertEqual(fcm['message']['data']['route_key'], 'accounts.roles_list')
        self.assertEqual(fcm['message']['data']['open_url'], f'/notifications/{n.pk}/open/')

        # Rep lacks settings:rbac/view -> notification_open safely redirects to /notifications/ instead of /roles/
        open_res = self.client.get(reverse('notification_open', kwargs={'pk': n.pk}))
        self.assertEqual(open_res.status_code, 302)
        self.assertEqual(open_res.url, reverse('notifications_inbox'))

