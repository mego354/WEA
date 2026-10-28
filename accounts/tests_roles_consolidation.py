from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from accounts.models import Role, SecurityAuditLog
from accounts.permissions import is_manager_or_higher, is_accountant, is_representative

User = get_user_model()


class UserRoleConsolidationTests(TestCase):
    def setUp(self):
        self.client = Client()

        # Ensure canonical roles
        self.superadmin_role, _ = Role.objects.get_or_create(
            name=Role.ROLE_SUPERADMIN,
            defaults={'display_name': 'مدير النظام الأعلى', 'is_super': True, 'is_system': True, 'is_active': True}
        )
        self.manager_role, _ = Role.objects.get_or_create(
            name=Role.ROLE_MANAGER,
            defaults={'display_name': 'مدير', 'is_area_manager': True, 'is_sales_team': True, 'is_system': True, 'is_active': True}
        )
        self.accountant_role, _ = Role.objects.get_or_create(
            name=Role.ROLE_ACCOUNTANT,
            defaults={'display_name': 'محاسب', 'can_hold_vault': True, 'is_system': True, 'is_active': True}
        )
        self.rep_role, _ = Role.objects.get_or_create(
            name=Role.ROLE_REP,
            defaults={'display_name': 'مندوب مبيعات', 'is_rep': True, 'is_sales_team': True, 'is_system': True, 'is_active': True}
        )
        self.medical_rep_role, _ = Role.objects.get_or_create(
            name=Role.ROLE_MEDICAL_REP,
            defaults={'display_name': 'مندوب دعاية طبية', 'is_rep': True, 'is_sales_team': True, 'is_system': True, 'is_active': True}
        )

        # Inactive / obsolete role
        self.obsolete_role, _ = Role.objects.get_or_create(
            name='ObsoleteDriver',
            defaults={'display_name': 'سائق توزيع قديم', 'is_system': False, 'is_active': False}
        )
        self.obsolete_role.is_active = False
        self.obsolete_role.save()

        # Create test superuser
        self.superadmin_user = User.objects.create_superuser(
            username='super_test@wea.com',
            email='super_test@wea.com',
            password='Password123!',
            name='Super User',
            role=self.superadmin_role
        )

        # Create test users for each role
        self.mgr_user = User.objects.create_user(
            username='mgr_test@wea.com',
            email='mgr_test@wea.com',
            password='Password123!',
            name='Manager User',
            role=self.manager_role
        )
        self.acct_user = User.objects.create_user(
            username='acct_test@wea.com',
            email='acct_test@wea.com',
            password='Password123!',
            name='Accountant User',
            role=self.accountant_role
        )
        self.rep_user = User.objects.create_user(
            username='rep_test@wea.com',
            email='rep_test@wea.com',
            password='Password123!',
            name='Rep User',
            role=self.rep_role
        )
        self.med_rep_user = User.objects.create_user(
            username='med_rep_test@wea.com',
            email='med_rep_test@wea.com',
            password='Password123!',
            name='Med Rep User',
            role=self.medical_rep_role
        )

    def test_canonical_roles_queryset(self):
        """Only the 5 canonical roles must be returned by Role.get_supported_roles()."""
        supported = list(Role.get_supported_roles().values_list('name', flat=True))
        self.assertEqual(len(supported), 5)
        self.assertIn('superadmin', supported)
        self.assertIn('manager', supported)
        self.assertIn('accountant', supported)
        self.assertIn('rep', supported)
        self.assertIn('medical_rep', supported)
        self.assertNotIn('ObsoleteDriver', supported)

    def test_role_classification_helpers(self):
        """Verification of helper permissions and flags across all 5 roles."""
        self.assertTrue(self.superadmin_user.is_super_admin)
        self.assertTrue(is_manager_or_higher(self.superadmin_user))

        self.assertTrue(is_manager_or_higher(self.mgr_user))
        self.assertFalse(self.mgr_user.is_super_admin)
        self.assertFalse(is_representative(self.mgr_user))

        self.assertTrue(is_accountant(self.acct_user))
        self.assertFalse(is_representative(self.acct_user))

        self.assertTrue(is_representative(self.rep_user))
        self.assertEqual(self.rep_user.role.name, 'rep')
        self.assertEqual(self.rep_user.role.display_name, 'مندوب مبيعات')

        self.assertTrue(is_representative(self.med_rep_user))
        self.assertEqual(self.med_rep_user.role.name, 'medical_rep')
        self.assertEqual(self.med_rep_user.role.display_name, 'مندوب دعاية طبية')

    def test_user_creation_rejects_obsolete_role(self):
        """User creation must reject assigning any non-canonical role."""
        self.client.force_login(self.superadmin_user)
        response = self.client.post(reverse('user_create'), {
            'name': 'New User Test',
            'email': 'new_invalid@wea.com',
            'code': 'USR-099',
            'password': 'Password123!',
            'role': self.obsolete_role.id
        }, follow=True)
        self.assertContains(response, 'غير مدعوم')
        self.assertFalse(User.objects.filter(email='new_invalid@wea.com').exists())

    def test_user_creation_accepts_canonical_role(self):
        """User creation succeeds with canonical role and logs security audit."""
        self.client.force_login(self.superadmin_user)
        response = self.client.post(reverse('user_create'), {
            'name': 'New Rep Valid',
            'email': 'new_rep@wea.com',
            'code': 'USR-100',
            'password': 'Password123!',
            'role': self.medical_rep_role.id
        }, follow=True)
        self.assertTrue(User.objects.filter(email='new_rep@wea.com').exists())
        created_u = User.objects.get(email='new_rep@wea.com')
        self.assertEqual(created_u.role, self.medical_rep_role)
        self.assertTrue(SecurityAuditLog.objects.filter(target_user=created_u, action_type='USER_CREATED').exists())

    def test_user_edit_rejects_obsolete_role(self):
        """User edit rejects assigning any non-canonical role."""
        self.client.force_login(self.superadmin_user)
        response = self.client.post(reverse('user_edit', args=[self.rep_user.id]), {
            'name': 'Rep Updated',
            'email': self.rep_user.email,
            'code': 'R-01',
            'role': self.obsolete_role.id,
            'is_active': 'on'
        }, follow=True)
        self.assertContains(response, 'غير مدعوم')
        self.rep_user.refresh_from_db()
        self.assertEqual(self.rep_user.role, self.rep_role)
