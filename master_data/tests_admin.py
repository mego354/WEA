from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse
from accounts.models import Role, SecurityAuditLog
from activities.models import ApprovalAuditLog

User = get_user_model()


class AdminDashboardAndModulesTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin_user = User.objects.create_superuser(
            username='admin_test',
            email='admin@test.com',
            password='Password123!',
            first_name='Admin',
            last_name='User'
        )
        self.client.force_login(self.admin_user)

    def test_admin_index_dashboard_renders(self):
        """Test that the custom executive admin dashboard renders successfully with metrics and quick links."""
        url = reverse('admin:index')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "لوحة التحكم والإدارة المركزية")
        self.assertContains(response, "الزيارات الميدانية")
        self.assertContains(response, "أوامر المبيعات")
        self.assertContains(response, "أوامر المشتريات والتوريد")
        self.assertContains(response, "العمليات والاختصارات السريعة")

    def test_admin_changelists_render(self):
        """Test that key changelist views load with 200 OK across apps."""
        changelist_urls = [
            'admin:accounts_user_changelist',
            'admin:accounts_role_changelist',
            'admin:accounts_securityauditlog_changelist',
            'admin:activities_visit_changelist',
            'admin:activities_visittemplate_changelist',
            'admin:activities_plannedvisitday_changelist',
            'admin:activities_approvalauditlog_changelist',
            'admin:contacts_contact_changelist',
            'admin:catalog_product_changelist',
            'admin:inventory_warehouse_changelist',
            'admin:purchases_purchaseorder_changelist',
            'admin:sales_salesorder_changelist',
            'admin:treasury_vault_changelist',
            'admin:master_data_locationsettings_changelist',
        ]
        for url_name in changelist_urls:
            with self.subTest(url=url_name):
                url = reverse(url_name)
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)

    def test_audit_logs_immutability(self):
        """Test that audit log admins disallow adding new records directly via admin."""
        security_add_url = reverse('admin:accounts_securityauditlog_add')
        res_sec = self.client.get(security_add_url)
        self.assertEqual(res_sec.status_code, 403)

        approval_add_url = reverse('admin:activities_approvalauditlog_add')
        res_app = self.client.get(approval_add_url)
        self.assertEqual(res_app.status_code, 403)

    def test_user_password_update_in_change_form(self):
        """Test that an administrator can update any user's password directly from the user changeform."""
        target_user = User.objects.create_user(
            username='rep_user',
            name='Rep User',
            email='rep@test.com',
            password='OldPassword123!'
        )
        url = reverse('admin:accounts_user_change', args=[target_user.id])
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "new_password")
        self.assertContains(res, "confirm_new_password")

        # Post new password directly via change form
        post_data = {
            'username': target_user.username,
            'name': target_user.name,
            'email': target_user.email,
            'locale': 'ar',
            'new_password': 'BrandNewPassword999!',
            'confirm_new_password': 'BrandNewPassword999!',
        }
        post_res = self.client.post(url, post_data)
        self.assertEqual(post_res.status_code, 302)

        target_user.refresh_from_db()
        self.assertTrue(target_user.check_password('BrandNewPassword999!'))
        self.assertFalse(target_user.check_password('OldPassword123!'))

    def test_admin_bulk_reset_password_to_wea4444(self):
        """Test that the bulk admin action resets selected users' password to Wea@4444 and logs audit."""
        user1 = User.objects.create_user(username='u1', name='User 1', email='u1@test.com', password='InitialPassword1!')
        user2 = User.objects.create_user(username='u2', name='User 2', email='u2@test.com', password='InitialPassword2!')

        changelist_url = reverse('admin:accounts_user_changelist')
        post_data = {
            'action': 'reset_password_to_wea4444',
            '_selected_action': [str(user1.id), str(user2.id)],
        }
        response = self.client.post(changelist_url, post_data, follow=True)
        self.assertEqual(response.status_code, 200)

        user1.refresh_from_db()
        user2.refresh_from_db()
        self.assertTrue(user1.check_password('Wea@4444'))
        self.assertTrue(user2.check_password('Wea@4444'))

        # Verify SecurityAuditLog
        audit_logs = SecurityAuditLog.objects.filter(action_type='USER_PASSWORD_RESET', target_user__in=[user1, user2])
        self.assertEqual(audit_logs.count(), 2)

    def test_user_password_change_view(self):
        """Test that the dedicated user password change subpage (/admin/accounts/user/<id>/password/) works."""
        target_user = User.objects.create_user(
            username='target_subpage',
            name='Target Subpage',
            email='subpage@test.com',
            password='InitialPassword1!'
        )
        url = reverse('admin:auth_user_password_change', args=[target_user.id])
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)

        post_data = {
            'password1': 'DedicatedNewPass123!',
            'password2': 'DedicatedNewPass123!',
        }
        post_res = self.client.post(url, post_data)
        self.assertEqual(post_res.status_code, 302)

        target_user.refresh_from_db()
        self.assertTrue(target_user.check_password('DedicatedNewPass123!'))
