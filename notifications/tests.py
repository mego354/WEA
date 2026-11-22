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

from django.core.management import call_command
from django.db import transaction
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role, User
from contacts.models import Contact
from inventory.models import InventoryStock, Warehouse
from master_data.models import Area, SalesSettings
from catalog.models import Product, ProductCategory
from notifications.models import Notification, NotificationDevice, RoleNotificationRule
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
