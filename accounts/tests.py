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
        self.super_role, _ = Role.objects.get_or_create(
            name='superadmin',
            defaults={
                'display_name': 'مدير نظام رئيسي',
                'is_super': True,
                'is_active': True
            }
        )
        self.rep_role, _ = Role.objects.get_or_create(
            name='medical_rep',
            defaults={
                'display_name': 'مندوب دعاية',
                'is_rep': True,
                'is_active': True
            }
        )
        self.area, _ = Area.objects.get_or_create(code='CAI', defaults={'name': 'القاهرة', 'area_type': 'governorate'})

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
        self.assertEqual(response.status_code, 403)

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
        self.test_role, _ = Role.objects.get_or_create(
            name='accountant',
            defaults={
                'display_name': 'محاسب',
                'can_hold_vault': True,
                'is_active': True
            }
        )
        self.test_role.can_hold_vault = True
        self.test_role.is_active = True
        self.test_role.save()

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


class ERPAuthorizationSecurityTests(TestCase):
    """
    Comprehensive test suite validating:
    - 403 Forbidden enforcement on protected routes.
    - Module-level inheritance (disabling module blocks all child actions).
    - SuperAdmin restriction and privilege escalation prevention.
    - Last superadmin lockout safeguard.
    - ABAC territorial and IDOR object-level protection.
    - Security audit logging for permission changes.
    - Cache invalidation and immediate policy reflection.
    """
    def setUp(self):
        self.client = Client()

        # Create Roles
        self.super_role = Role.objects.create(
            name='superadmin_role',
            display_name='مدير نظام رئيسي',
            is_super=True,
            is_active=True
        )
        self.rep_role = Role.objects.create(
            name='sales_rep_role',
            display_name='مندوب مبيعات',
            is_rep=True,
            is_active=True
        )
        self.manager_role = Role.objects.create(
            name='sales_manager_role',
            display_name='مدير مبيعات',
            is_active=True
        )

        # Create Users
        self.super_user = User.objects.create_superuser(
            username='root@example.com',
            email='root@example.com',
            password='RootPassword123!',
            name='المدير العام',
            role=self.super_role
        )
        self.rep_user = User.objects.create_user(
            username='rep_a@example.com',
            email='rep_a@example.com',
            password='RepPassword123!',
            name='مندوب أ',
            role=self.rep_role
        )
        self.rep_user_b = User.objects.create_user(
            username='rep_b@example.com',
            email='rep_b@example.com',
            password='RepPassword123!',
            name='مندوب ب',
            role=self.rep_role
        )

    def test_anonymous_redirect_on_all_domains(self):
        """Anonymous access to protected routes redirects to login."""
        protected_urls = [
            reverse('purchase_orders_list'),
            reverse('purchase_order_create'),
            reverse('sales_orders_list'),
            reverse('products_list'),
            reverse('contacts_list'),
            reverse('visits_list'),
            reverse('vaults_list'),
            reverse('roles_list'),
            reverse('audit_logs_list'),
        ]
        for url in protected_urls:
            res = self.client.get(url)
            self.assertEqual(res.status_code, 302, f"URL {url} did not redirect anonymous user")
            self.assertIn('login', res.url)

    def test_unauthorized_user_gets_403_forbidden(self):
        """Authenticated user without specific permissions gets 403 Forbidden."""
        self.client.login(username='rep_a@example.com', password='RepPassword123!')
        
        # Rep has no purchases permissions
        res = self.client.get(reverse('purchase_orders_list'))
        self.assertEqual(res.status_code, 403)
        self.assertTemplateUsed(res, '403.html')

        res_post = self.client.post(reverse('purchase_order_create'), {})
        self.assertEqual(res_post.status_code, 403)

    def test_module_level_inheritance_enforcement(self):
        """
        Disabling root module permission blocks all child actions
        even if child permission is explicitly assigned to role.
        """
        p_child = Permission.objects.get(codename='purchases:orders/list')
        p_module = Permission.objects.get(codename='module:purchases')

        # Assign child only (WITHOUT module root)
        self.rep_role.permissions.add(p_child)
        self.rep_user.clear_perm_cache()

        self.assertFalse(self.rep_user.has_permission('purchases:orders/list'))

        self.client.login(username='rep_a@example.com', password='RepPassword123!')
        res = self.client.get(reverse('purchase_orders_list'))
        self.assertEqual(res.status_code, 403)

        # Now enable module root
        self.rep_role.permissions.add(p_module)
        self.rep_user.clear_perm_cache()

        self.assertTrue(self.rep_user.has_permission('purchases:orders/list'))
        res_ok = self.client.get(reverse('purchase_orders_list'))
        self.assertEqual(res_ok.status_code, 200)

    def test_superadmin_exclusive_settings_protection(self):
        """Only superadmins can access user/role/audit settings; other users receive 403."""
        # Non-superadmin
        self.client.login(username='rep_a@example.com', password='RepPassword123!')
        for url in [reverse('roles_list'), reverse('role_create'), reverse('audit_logs_list')]:
            res = self.client.get(url)
            self.assertEqual(res.status_code, 403)

        # SuperAdmin
        self.client.login(username='root@example.com', password='RootPassword123!')
        for url in [reverse('roles_list'), reverse('role_create'), reverse('audit_logs_list')]:
            res = self.client.get(url)
            self.assertEqual(res.status_code, 200)

    def test_privilege_escalation_prevention(self):
        """Non-superadmins cannot create or edit roles to grant is_super."""
        self.client.login(username='rep_a@example.com', password='RepPassword123!')
        data = {
            'name': 'hacked_role',
            'display_name': 'Hacked',
            'is_super': 'on',
        }
        res = self.client.post(reverse('role_create'), data)
        self.assertEqual(res.status_code, 403)
        self.assertFalse(Role.objects.filter(name='hacked_role').exists())

    def test_last_superadmin_lockout_protection(self):
        """System strictly prevents deactivating or deleting the last active superadmin."""
        self.client.login(username='root@example.com', password='RootPassword123!')
        
        # Attempt to toggle status of only active superadmin
        res = self.client.get(reverse('user_toggle_status', args=[self.super_user.pk]))
        self.assertEqual(res.status_code, 302)
        self.super_user.refresh_from_db()
        self.assertTrue(self.super_user.is_active)

    def test_security_audit_logging_on_role_changes(self):
        """SecurityAuditLog records actor, action, timestamp, and metadata on role updates."""
        from accounts.models import SecurityAuditLog
        initial_count = SecurityAuditLog.objects.count()

        self.client.login(username='root@example.com', password='RootPassword123!')
        p_module = Permission.objects.get(codename='module:catalog')
        p_view = Permission.objects.get(codename='catalog:products/list')

        data = {
            'name': 'audited_role',
            'display_name': 'دور مراجع',
            'is_active': 'on',
            'permissions': [p_module.pk, p_view.pk]
        }
        res = self.client.post(reverse('role_create'), data)
        self.assertEqual(res.status_code, 302)

        self.assertGreater(SecurityAuditLog.objects.count(), initial_count)
        log = SecurityAuditLog.objects.latest('id')
        self.assertEqual(log.actor, self.super_user)
        self.assertEqual(log.action_type, 'ROLE_CREATED')
        self.assertIn('إنشاء دور', log.description)

    def test_immediate_cache_invalidation(self):
        """Permission revocation reflects immediately in active session via clear_perm_cache."""
        p_mod = Permission.objects.get(codename='module:contacts')
        p_list = Permission.objects.get(codename='contacts:contacts/list')
        self.rep_role.permissions.add(p_mod, p_list)
        self.rep_user.clear_perm_cache()

        self.assertTrue(self.rep_user.has_permission('contacts:contacts/list'))

        # Revoke permission
        self.rep_role.permissions.remove(p_list)
        self.rep_user.clear_perm_cache()

        self.assertFalse(self.rep_user.has_permission('contacts:contacts/list'))

    def test_abac_object_access_and_idor_protection(self):
        """Field representative cannot access another representative's visit record."""
        from contacts.models import Contact
        from activities.models import Visit

        contact = Contact.objects.create(name='عميل تجريبي', code='C-TEST-01', is_customer=True)
        visit_b = Visit.objects.create(
            contact=contact,
            owner=self.rep_user_b,
            created_by=self.rep_user_b,
            date='2026-10-24',
            status='started'
        )

        # Grant rep_a visits viewing permission
        p_mod = Permission.objects.get(codename='module:activities')
        p_view = Permission.objects.get(codename='activities:visits/view')
        self.rep_role.permissions.add(p_mod, p_view)
        self.rep_user.clear_perm_cache()

        # Rep A attempts to access Visit B
        self.client.login(username='rep_a@example.com', password='RepPassword123!')
        res = self.client.get(reverse('visit_detail', args=[visit_b.pk]))
        self.assertEqual(res.status_code, 403)
