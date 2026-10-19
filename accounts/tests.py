import csv
from io import StringIO
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from accounts.models import User, Role, RoleTag
from master_data.models import Area


class AccountsModelTests(TestCase):
    def setUp(self):
        self.super_role = Role.objects.create(
            name='superadmin',
            display_name='مدير نظام رئيسي',
            is_super=True,
            is_active=True
        )
        self.rep_role = Role.objects.create(
            name='medical_rep',
            display_name='مندوب دعاية',
            is_rep=True,
            is_active=True
        )
        self.area = Area.objects.create(name='القاهرة', code='CAI', area_type='governorate')

    def test_user_creation_and_attributes(self):
        user = User.objects.create_user(
            username='rep@example.com',
            email='rep@example.com',
            password='Password123!',
            name='أحمد علي',
            code='REP-001',
            role=self.rep_role
        )
        user.assigned_areas.add(self.area)

        self.assertEqual(user.name, 'أحمد علي')
        self.assertEqual(user.code, 'REP-001')
        self.assertEqual(user.role.name, 'medical_rep')
        self.assertTrue(user.is_active)
        self.assertTrue(user.check_password('Password123!'))
        self.assertIn(self.area, user.assigned_areas.all())

    def test_role_attributes_and_tags(self):
        tag = RoleTag.objects.create(tag='sales', display_name='فريق المبيعات')
        self.rep_role.tags.add(tag)
        self.assertIn(tag, self.rep_role.tags.all())
        self.assertTrue(self.rep_role.is_rep)
        self.assertFalse(self.rep_role.is_super)

    def test_user_has_permission(self):
        ct = ContentType.objects.get_for_model(User)
        perm = Permission.objects.create(codename='view_custom_users', name='View Custom Users', content_type=ct)
        self.rep_role.permissions.add(perm)

        user = User.objects.create_user(
            username='rep2@example.com',
            email='rep2@example.com',
            password='Password123!',
            role=self.rep_role
        )
        self.assertTrue(user.has_permission('view_custom_users'))
        self.assertFalse(user.has_permission('non_existent_perm'))


class UserManagementViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin_role = Role.objects.create(
            name='admin',
            display_name='مدير النظام',
            is_super=True,
            is_active=True
        )
        self.restricted_role = Role.objects.create(
            name='restricted',
            display_name='مستخدم محدود',
            is_active=True
        )
        self.admin_user = User.objects.create_superuser(
            username='admin@example.com',
            email='admin@example.com',
            password='AdminPassword123!',
            name='مدير النظام',
            role=self.admin_role
        )
        self.restricted_user = User.objects.create_user(
            username='staff@example.com',
            email='staff@example.com',
            password='StaffPassword123!',
            name='موظف محدود',
            role=self.restricted_role
        )

    def test_anonymous_access_redirects_to_login(self):
        response = self.client.get(reverse('users_list'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response.url)

    def test_restricted_user_cannot_access_users_list(self):
        self.client.login(username='staff@example.com', password='StaffPassword123!')
        response = self.client.get(reverse('users_list'))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('home'))

    def test_admin_user_can_access_users_list(self):
        self.client.login(username='admin@example.com', password='AdminPassword123!')
        response = self.client.get(reverse('users_list'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'accounts/users_list.html')
        self.assertContains(response, 'مدير النظام')

    def test_user_create_post_success(self):
        self.client.login(username='admin@example.com', password='AdminPassword123!')
        data = {
            'name': 'محمود محمد',
            'email': 'mahmoud@example.com',
            'code': 'USR-99',
            'password': 'SecurePassword123!',
            'role': self.restricted_role.pk,
        }
        response = self.client.post(reverse('user_create'), data)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(User.objects.filter(email='mahmoud@example.com').exists())
        created_user = User.objects.get(email='mahmoud@example.com')
        self.assertEqual(created_user.name, 'محمود محمد')
        self.assertEqual(created_user.code, 'USR-99')
        self.assertTrue(created_user.check_password('SecurePassword123!'))

    def test_user_create_duplicate_email_fails(self):
        self.client.login(username='admin@example.com', password='AdminPassword123!')
        data = {
            'name': 'تكرار البريد',
            'email': 'admin@example.com', # Duplicate
            'code': 'DUP-01',
            'password': 'SecurePassword123!',
            'role': self.restricted_role.pk,
        }
        response = self.client.post(reverse('user_create'), data)
        self.assertEqual(response.status_code, 302)
        # Verify no duplicate user was created
        self.assertEqual(User.objects.filter(email='admin@example.com').count(), 1)

    def test_user_edit_post(self):
        self.client.login(username='admin@example.com', password='AdminPassword123!')
        data = {
            'name': 'موظف محدث',
            'email': 'staff_updated@example.com',
            'code': 'STAFF-02',
            'role': self.admin_role.pk,
            'is_active': 'on',
        }
        response = self.client.post(reverse('user_edit', args=[self.restricted_user.pk]), data)
        self.assertEqual(response.status_code, 302)
        self.restricted_user.refresh_from_db()
        self.assertEqual(self.restricted_user.name, 'موظف محدث')
        self.assertEqual(self.restricted_user.email, 'staff_updated@example.com')

    def test_cannot_deactivate_only_active_superuser(self):
        self.client.login(username='admin@example.com', password='AdminPassword123!')
        # Try to deactivate sole admin user via user_toggle_status
        response = self.client.get(reverse('user_toggle_status', args=[self.admin_user.pk]))
        self.assertEqual(response.status_code, 302)
        self.admin_user.refresh_from_db()
        self.assertTrue(self.admin_user.is_active) # Must remain active

    def test_reset_password(self):
        self.client.login(username='admin@example.com', password='AdminPassword123!')
        data = {
            'new_password': 'BrandNewPassword123!',
            'confirm_password': 'BrandNewPassword123!',
        }
        response = self.client.post(reverse('user_reset_password', args=[self.restricted_user.pk]), data)
        self.assertEqual(response.status_code, 302)
        self.restricted_user.refresh_from_db()
        self.assertTrue(self.restricted_user.check_password('BrandNewPassword123!'))

    def test_users_export_csv(self):
        self.client.login(username='admin@example.com', password='AdminPassword123!')
        response = self.client.get(reverse('users_export'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv; charset=utf-8')
        content = response.content.decode('utf-8')
        self.assertTrue(content.startswith('\ufeff')) # UTF-8 BOM
        self.assertIn('admin@example.com', content)


class RoleManagementViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin_role = Role.objects.create(
            name='admin',
            display_name='مدير النظام',
            is_super=True,
            is_active=True
        )
        self.admin_user = User.objects.create_superuser(
            username='admin@example.com',
            email='admin@example.com',
            password='AdminPassword123!',
            name='مدير النظام',
            role=self.admin_role
        )
        self.test_role = Role.objects.create(
            name='accountant',
            display_name='محاسب',
            can_hold_vault=True,
            is_active=True
        )

    def test_roles_list_view(self):
        self.client.login(username='admin@example.com', password='AdminPassword123!')
        response = self.client.get(reverse('roles_list'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'accounts/roles_list.html')
        self.assertContains(response, 'محاسب')

    def test_role_create_view(self):
        self.client.login(username='admin@example.com', password='AdminPassword123!')
        data = {
            'name': 'warehouse_keeper',
            'display_name': 'أمين مخزن',
            'is_active': 'on',
        }
        response = self.client.post(reverse('role_create'), data)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Role.objects.filter(name='warehouse_keeper').exists())

    def test_role_duplicate_view(self):
        self.client.login(username='admin@example.com', password='AdminPassword123!')
        response = self.client.get(reverse('role_duplicate', args=[self.test_role.pk]))
        self.assertEqual(response.status_code, 302)
        clones = Role.objects.filter(name__startswith='accountant_copy')
        self.assertTrue(clones.exists())
        clone = clones.first()
        self.assertTrue(clone.can_hold_vault)
        self.assertIn('نسخة', clone.display_name)

    def test_delete_role_safeguard(self):
        self.client.login(username='admin@example.com', password='AdminPassword123!')
        # Cannot delete system role or role with assigned users
        User.objects.create_user(
            username='acc@example.com',
            email='acc@example.com',
            password='Pass!',
            role=self.test_role
        )
        response = self.client.get(reverse('role_delete', args=[self.test_role.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Role.objects.filter(pk=self.test_role.pk).exists())
