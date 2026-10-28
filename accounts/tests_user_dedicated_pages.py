import json
from decimal import Decimal
from io import BytesIO
from unittest.mock import patch
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import Permission
from accounts.models import User, Role, SecurityAuditLog
from master_data.models import Area
from inventory.models import Warehouse
from treasury.models import Vault


class UserDedicatedPagesAndLocationTests(TestCase):
    """
    Comprehensive tests for:
    1. Dedicated User Creation Page (/users/create/)
    2. Dedicated User Detail Page (/users/<pk>/)
    3. Dedicated User Edit Page (/users/<pk>/edit/)
    4. Isolated Password Reset (/users/<pk>/reset-password/)
    5. Server-side RBAC scoping (SuperAdmin, Manager, Accountant, Rep)
    6. Geocoding endpoints (/api/geocoding/search/ and /api/geocoding/reverse/)
    7. Warehouse location coordinates persistence
    """

    def setUp(self):
        # 1. Setup Roles
        self.super_role = Role.objects.get(name=Role.ROLE_SUPERADMIN)
        self.manager_role = Role.objects.get(name=Role.ROLE_MANAGER)
        self.manager_role.is_area_manager = True
        self.manager_role.is_active = True
        self.manager_role.save()

        self.accountant_role = Role.objects.get(name=Role.ROLE_ACCOUNTANT)
        self.rep_role = Role.objects.get(name=Role.ROLE_REP)

        # Assign user permissions with module root permission for module-level inheritance
        module_accounts_perm = Permission.objects.filter(codename='module:accounts').first()
        user_list_perm = Permission.objects.filter(codename='users:users/list').first()
        user_create_perm = Permission.objects.filter(codename='users:users/create').first()
        user_edit_perm = Permission.objects.filter(codename='users:users/edit').first()
        for p in [module_accounts_perm, user_list_perm, user_create_perm, user_edit_perm]:
            if p:
                self.manager_role.permissions.add(p)
                self.super_role.permissions.add(p)
                self.accountant_role.permissions.add(p)
                self.rep_role.permissions.add(p)

        # 2. Setup Areas
        self.cairo_gov = Area.objects.create(name='محافظة القاهرة', code='CAI-GOV', area_type='governorate')
        self.nasr_city = Area.objects.create(name='مدينة نصر', code='NASR', parent=self.cairo_gov, area_type='subarea')
        self.alex_gov = Area.objects.create(name='محافظة الإسكندرية', code='ALX-GOV', area_type='governorate')

        # 3. Setup Users
        self.superadmin = User.objects.create_user(
            username='super@wea.com',
            email='super@wea.com',
            password='AdminPass123!',
            name='Super Admin',
            role=self.super_role,
            is_staff=True,
            is_superuser=True
        )

        self.cairo_manager = User.objects.create_user(
            username='manager_cairo@wea.com',
            email='manager_cairo@wea.com',
            password='ManagerPass123!',
            name='Cairo Manager',
            role=self.manager_role,
            is_staff=False
        )
        self.cairo_manager.assigned_areas.set([self.cairo_gov, self.nasr_city])

        self.cairo_rep = User.objects.create_user(
            username='rep_cairo@wea.com',
            email='rep_cairo@wea.com',
            password='RepPass123!',
            name='Cairo Rep',
            role=self.rep_role,
            is_staff=False
        )
        self.cairo_rep.assigned_areas.set([self.nasr_city])

        self.alex_rep = User.objects.create_user(
            username='rep_alex@wea.com',
            email='rep_alex@wea.com',
            password='RepPass123!',
            name='Alex Rep',
            role=self.rep_role,
            is_staff=False
        )
        self.alex_rep.assigned_areas.set([self.alex_gov])

        self.accountant = User.objects.create_user(
            username='accountant@wea.com',
            email='accountant@wea.com',
            password='AccPass123!',
            name='System Accountant',
            role=self.accountant_role,
            is_staff=False
        )

        # Clear permission caches for fresh permission evaluation
        self.superadmin.clear_perm_cache()
        self.cairo_manager.clear_perm_cache()
        self.cairo_rep.clear_perm_cache()
        self.alex_rep.clear_perm_cache()
        self.accountant.clear_perm_cache()

        self.client = Client()

    # ==========================================
    # USER CREATION PAGE TESTS
    # ==========================================

    def test_user_create_page_get_superadmin(self):
        """Superadmin can load dedicated user creation page with all fields and roles."""
        self.client.login(username='super@wea.com', password='AdminPass123!')
        res = self.client.get('/users/create/')
        self.assertEqual(res.status_code, 200)
        self.assertTemplateUsed(res, 'accounts/user_create.html')
        self.assertContains(res, 'إضافة مستخدم جديد')
        self.assertContains(res, 'بيانات الحساب ومعلومات تسجيل الدخول')
        self.assertContains(res, 'تعيين المناطق الجغرافية')

    def test_user_create_post_success(self):
        """Superadmin successfully creates a user through the dedicated page."""
        self.client.login(username='super@wea.com', password='AdminPass123!')
        res = self.client.post('/users/create/', {
            'name': 'خالد محمد عبد الرحمن',
            'email': 'khaled.new@weapharma.com',
            'code': 'EMP-501',
            'mobile': '01099887766',
            'password': 'SecurePassword123!',
            'confirm_password': 'SecurePassword123!',
            'role': str(self.rep_role.id),
            'is_active': 'on',
            'assigned_areas': [str(self.nasr_city.id)]
        })
        new_user = User.objects.filter(email='khaled.new@weapharma.com').first()
        self.assertIsNotNone(new_user)
        self.assertEqual(res.status_code, 302)
        expected_url = reverse('user_detail', kwargs={'pk': new_user.pk})
        self.assertEqual(res.url, expected_url)
        self.assertEqual(new_user.name, 'خالد محمد عبد الرحمن')
        self.assertEqual(new_user.role, self.rep_role)
        self.assertTrue(new_user.check_password('SecurePassword123!'))
        self.assertTrue(new_user.assigned_areas.filter(id=self.nasr_city.id).exists())

        # Verify audit log
        log = SecurityAuditLog.objects.filter(target_user=new_user, action_type='USER_CREATED').first()
        self.assertIsNotNone(log)
        self.assertEqual(log.actor, self.superadmin)

    def test_user_create_validation_preserves_input(self):
        """Validation failures re-render user_create.html preserving entered values."""
        self.client.login(username='super@wea.com', password='AdminPass123!')
        res = self.client.post('/users/create/', {
            'name': 'محمد الخطأ',
            'email': 'not-matching@wea.com',
            'code': 'ERR-01',
            'mobile': '01122334455',
            'password': 'PasswordOne1!',
            'confirm_password': 'PasswordDifferent2!',
            'role': str(self.rep_role.id),
            'is_active': 'on',
        })
        self.assertEqual(res.status_code, 200)
        self.assertTemplateUsed(res, 'accounts/user_create.html')
        self.assertContains(res, 'محمد الخطأ')
        self.assertContains(res, 'not-matching@wea.com')
        self.assertFalse(User.objects.filter(email='not-matching@wea.com').exists())

    def test_user_create_accountant_forbidden(self):
        """Accountant is strictly forbidden from accessing user creation."""
        self.client.login(username='accountant@wea.com', password='AccPass123!')
        res = self.client.get('/users/create/')
        self.assertEqual(res.status_code, 403)

        res_post = self.client.post('/users/create/', {'name': 'Hack', 'email': 'hack@wea.com'})
        self.assertEqual(res_post.status_code, 403)

    def test_user_create_representative_forbidden(self):
        """Representative is strictly forbidden from creating users."""
        self.client.login(username='rep_cairo@wea.com', password='RepPass123!')
        res = self.client.get('/users/create/')
        self.assertEqual(res.status_code, 403)

    def test_user_create_manager_cannot_create_outside_region(self):
        """Manager cannot assign areas outside their regional jurisdiction."""
        self.client.login(username='manager_cairo@wea.com', password='ManagerPass123!')
        res = self.client.post('/users/create/', {
            'name': 'مندوب خارج النطاق',
            'email': 'alex_rep_by_cairo@wea.com',
            'password': 'SecurePassword123!',
            'confirm_password': 'SecurePassword123!',
            'role': str(self.rep_role.id),
            'assigned_areas': [str(self.alex_gov.id)]
        })
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'لا تمتلك الصلاحية لتعيين مناطق جغرافية خارج نطاق مسؤوليتك')
        self.assertFalse(User.objects.filter(email='alex_rep_by_cairo@wea.com').exists())

    # ==========================================
    # USER DETAIL PAGE TESTS
    # ==========================================

    def test_user_detail_page_get(self):
        """Dedicated user detail page shows profile, assigned areas, warehouses, vaults."""
        # Create warehouse and vault for rep
        wh = Warehouse.objects.create(name='مخزن عهدة مندوب القاهرة', code='WH-REP-CAI', assigned_user=self.cairo_rep)
        v = Vault.objects.create(name='خزنة عهدة مندوب القاهرة', serial_num=9901, assigned_user=self.cairo_rep)

        self.client.login(username='super@wea.com', password='AdminPass123!')
        res = self.client.get(f'/users/{self.cairo_rep.pk}/')
        self.assertEqual(res.status_code, 200)
        self.assertTemplateUsed(res, 'accounts/user_detail.html')
        self.assertContains(res, 'Cairo Rep')
        self.assertContains(res, 'مدينة نصر')
        self.assertContains(res, 'WH-REP-CAI')
        self.assertContains(res, 'خزنة عهدة مندوب القاهرة')

    def test_user_detail_manager_scoping(self):
        """Manager can view rep in their own area, but cannot view rep in another area."""
        self.client.login(username='manager_cairo@wea.com', password='ManagerPass123!')
        # In scope (Cairo Rep)
        res_cairo = self.client.get(f'/users/{self.cairo_rep.pk}/')
        self.assertEqual(res_cairo.status_code, 200)

        # Out of scope (Alex Rep)
        res_alex = self.client.get(f'/users/{self.alex_rep.pk}/')
        self.assertEqual(res_alex.status_code, 403)

    # ==========================================
    # USER EDIT PAGE TESTS
    # ==========================================

    def test_user_edit_preserves_password(self):
        """Editing user profile fields does not alter or erase the password."""
        self.client.login(username='super@wea.com', password='AdminPass123!')
        initial_hash = self.cairo_rep.password
        res = self.client.post(f'/users/{self.cairo_rep.pk}/edit/', {
            'name': 'Cairo Rep Updated',
            'email': 'rep_cairo@wea.com',
            'code': 'REP-NEW-99',
            'mobile': '01011122233',
            'role': str(self.rep_role.id),
            'is_active': 'on',
            'assigned_areas': [str(self.nasr_city.id)]
        })
        self.assertEqual(res.status_code, 302)
        self.cairo_rep.refresh_from_db()
        self.assertEqual(self.cairo_rep.name, 'Cairo Rep Updated')
        self.assertEqual(self.cairo_rep.code, 'REP-NEW-99')
        self.assertEqual(self.cairo_rep.password, initial_hash)
        self.assertTrue(self.cairo_rep.check_password('RepPass123!'))

    def test_user_password_reset_endpoint(self):
        """Isolated password reset changes password and logs audit without touching profile."""
        self.client.login(username='super@wea.com', password='AdminPass123!')
        res = self.client.post(f'/users/{self.cairo_rep.pk}/reset-password/', {
            'new_password': 'BrandNewPassword123!',
            'confirm_password': 'BrandNewPassword123!'
        })
        self.assertEqual(res.status_code, 302)
        self.cairo_rep.refresh_from_db()
        self.assertTrue(self.cairo_rep.check_password('BrandNewPassword123!'))

        log = SecurityAuditLog.objects.filter(target_user=self.cairo_rep, action_type='USER_PASSWORD_RESET').first()
        self.assertIsNotNone(log)

    def test_manager_cannot_edit_superadmin(self):
        """Area manager cannot edit superadmin account."""
        self.client.login(username='manager_cairo@wea.com', password='ManagerPass123!')
        res = self.client.get(f'/users/{self.superadmin.pk}/edit/')
        self.assertEqual(res.status_code, 403)

    # ==========================================
    # WAREHOUSE LOCATION TESTS
    # ==========================================

    def test_warehouse_location_persistence(self):
        """Warehouse coordinates (latitude, longitude) persist and update correctly."""
        wh = Warehouse.objects.create(
            name='مستودع رمسيس الرئيسي',
            code='WH-RAMSES-01',
            latitude=Decimal('30.0626000'),
            longitude=Decimal('31.2497000')
        )
        wh.refresh_from_db()
        self.assertTrue(wh.has_saved_location)
        self.assertEqual(float(wh.latitude), 30.0626)
        self.assertEqual(float(wh.longitude), 31.2497)

    # ==========================================
    # GEOCODING PROXY ENDPOINTS TESTS
    # ==========================================

    @patch('urllib.request.urlopen')
    def test_geocoding_search_api_proxy(self, mock_urlopen):
        """Backend geocoding search proxy forwards request with corporate User-Agent."""
        fake_response = BytesIO(json.dumps([
            {
                'display_name': 'Nasr City, Cairo, Egypt',
                'lat': '30.0561',
                'lon': '31.3301',
            }
        ]).encode('utf-8'))
        mock_urlopen.return_value.__enter__.return_value = fake_response

        self.client.login(username='super@wea.com', password='AdminPass123!')
        res = self.client.get('/api/geocoding/search/?q=Nasr City')
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn('results', data)
        self.assertEqual(len(data['results']), 1)
        self.assertEqual(data['results'][0]['display_name'], 'Nasr City, Cairo, Egypt')
        self.assertEqual(data['results'][0]['lat'], 30.0561)

    @patch('urllib.request.urlopen')
    def test_geocoding_reverse_api_proxy(self, mock_urlopen):
        """Backend reverse geocoding proxy resolves lat/lon to human readable address."""
        fake_response = BytesIO(json.dumps({
            'display_name': 'شارع مصطفى النحاس، مدينة نصر، القاهرة',
            'address': {'city': 'Cairo', 'road': 'Mostafa El-Nahas'}
        }).encode('utf-8'))
        mock_urlopen.return_value.__enter__.return_value = fake_response

        self.client.login(username='super@wea.com', password='AdminPass123!')
        res = self.client.get('/api/geocoding/reverse/?lat=30.0561&lon=31.3301')
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data['display_name'], 'شارع مصطفى النحاس، مدينة نصر، القاهرة')
