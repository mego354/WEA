from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from accounts.models import Role, SecurityAuditLog
from accounts.services import AuditLogService
from datetime import date, timedelta

User = get_user_model()


class AuditLoggingTests(TestCase):
    def setUp(self):
        self.client = Client()

        self.superadmin_role, _ = Role.objects.get_or_create(
            name=Role.ROLE_SUPERADMIN,
            defaults={'display_name': 'مدير النظام الأعلى', 'is_super': True, 'is_system': True, 'is_active': True}
        )
        self.super_user = User.objects.create_superuser(
            username='admin_audit@wea.com',
            email='admin_audit@wea.com',
            password='Password123!',
            name='Admin Auditor',
            role=self.superadmin_role
        )

        self.rep_role, _ = Role.objects.get_or_create(
            name=Role.ROLE_REP,
            defaults={'display_name': 'مندوب', 'is_rep': True, 'is_system': True, 'is_active': True}
        )
        self.test_user = User.objects.create_user(
            username='rep_target@wea.com',
            email='rep_target@wea.com',
            password='Password123!',
            name='Target Rep',
            role=self.rep_role
        )

    def test_audit_log_service_creation_and_redaction(self):
        """Test that AuditLogService properly creates log records and recursively redacts sensitive fields."""
        log = AuditLogService.log(
            action='update',
            module='users',
            user=self.super_user,
            record_id=self.test_user.id,
            record_name=self.test_user.name,
            previous_values={
                'name': 'Old Name',
                'password': 'old_plain_password_123',
                'nested': {'api_token': 'secret_tok_123', 'status': 'active'}
            },
            new_values={
                'name': 'New Name',
                'password': 'new_plain_password_456',
                'nested': {'api_token': 'new_secret_tok_456', 'status': 'active'}
            },
            status='success',
            ip_address='192.168.1.100',
            user_agent='Mozilla/5.0 TestBrowser'
        )

        self.assertIsNotNone(log.id)
        self.assertEqual(log.module, 'users')
        self.assertEqual(log.action, 'update')
        self.assertEqual(log.user, self.super_user)
        self.assertEqual(log.ip_address, '192.168.1.100')

        # Verify sensitive redaction
        self.assertEqual(log.previous_values['password'], '[REDACTED]')
        self.assertEqual(log.new_values['password'], '[REDACTED]')
        self.assertEqual(log.previous_values['nested']['api_token'], '[REDACTED]')
        self.assertEqual(log.new_values['nested']['api_token'], '[REDACTED]')

        # Verify non-sensitive preserved
        self.assertEqual(log.previous_values['name'], 'Old Name')
        self.assertEqual(log.new_values['name'], 'New Name')
        self.assertEqual(log.new_values['nested']['status'], 'active')

    def test_audit_logs_view_filtering(self):
        """Test the audit logs list page filters by module, action, date range, and search query."""
        self.client.login(username='admin_audit@wea.com', password='Password123!')

        # Create distinct test logs
        AuditLogService.log(
            action='login',
            module='auth',
            user=self.super_user,
            record_name='تسجيل دخول ناجح',
            new_values={'username': 'admin_audit@wea.com'},
            ip_address='127.0.0.1'
        )
        AuditLogService.log(
            action='create',
            module='contacts',
            user=self.super_user,
            record_id=101,
            record_name='صيدلية الشفاء الممتازة',
            new_values={'name': 'صيدلية الشفاء الممتازة'},
            ip_address='127.0.0.1'
        )
        AuditLogService.log(
            action='delete',
            module='users',
            user=self.super_user,
            record_id=self.test_user.id,
            record_name='Target Rep',
            previous_values={'name': 'Target Rep'},
            ip_address='127.0.0.1'
        )

        # 1. Filter by module='contacts'
        res = self.client.get(reverse('audit_logs_list') + '?module=contacts')
        self.assertEqual(res.status_code, 200)
        logs = res.context['logs']
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0].record_name, 'صيدلية الشفاء الممتازة')

        # 2. Filter by action='login'
        res = self.client.get(reverse('audit_logs_list') + '?action=login')
        self.assertEqual(res.status_code, 200)
        logs = res.context['logs']
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0].module, 'auth')

        # 3. Search query q='الشفاء'
        res = self.client.get(reverse('audit_logs_list') + '?q=الشفاء')
        self.assertEqual(res.status_code, 200)
        logs = res.context['logs']
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0].record_name, 'صيدلية الشفاء الممتازة')

        # 4. Date range filtering
        today_str = date.today().strftime('%Y-%m-%d')
        res = self.client.get(reverse('audit_logs_list') + f'?date_from={today_str}&date_to={today_str}')
        self.assertEqual(res.status_code, 200)
        self.assertGreaterEqual(len(res.context['logs']), 3)

    def test_audit_log_detail_api(self):
        """Test fetching audit log details via AJAX JSON endpoint."""
        self.client.login(username='admin_audit@wea.com', password='Password123!')

        log = AuditLogService.log(
            action='update',
            module='contacts',
            user=self.super_user,
            record_id=50,
            record_name='مستشفى النيل',
            previous_values={'phone': '01011111111', 'notes': 'قديم'},
            new_values={'phone': '01022222222', 'notes': 'جديد'},
            ip_address='10.0.0.1'
        )

        url = reverse('audit_log_detail', kwargs={'pk': log.id})
        res = self.client.get(url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['log']['module'], 'contacts')
        self.assertEqual(data['log']['record_name'], 'مستشفى النيل')
        self.assertEqual(data['log']['previous_values']['phone'], '01011111111')
        self.assertEqual(data['log']['new_values']['phone'], '01022222222')
