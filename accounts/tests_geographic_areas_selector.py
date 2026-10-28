from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from master_data.models import Area
from accounts.models import Role
from accounts.views import validate_assigned_areas_for_user, get_hierarchical_areas

User = get_user_model()


class GeographicAreaSelectorTests(TestCase):
    def setUp(self):
        self.client = Client()

        # Roles
        self.superadmin_role, _ = Role.objects.get_or_create(
            name=Role.ROLE_SUPERADMIN,
            defaults={'display_name': 'مدير النظام الأعلى', 'is_super': True, 'is_system': True, 'is_active': True}
        )
        self.manager_role, _ = Role.objects.get_or_create(
            name=Role.ROLE_MANAGER,
            defaults={'display_name': 'مدير', 'is_area_manager': True, 'is_system': True, 'is_active': True}
        )
        self.rep_role, _ = Role.objects.get_or_create(
            name=Role.ROLE_REP,
            defaults={'display_name': 'مندوب مبيعات', 'is_rep': True, 'is_system': True, 'is_active': True}
        )

        # Areas
        self.cairo = Area.objects.create(code='CAI', name='القاهرة', area_type='governorate', is_company_area=False)
        self.nasr_city = Area.objects.create(code='NASR', name='مدينة نصر', area_type='subarea', parent=self.cairo, is_company_area=False)
        self.maadi = Area.objects.create(code='MAADI', name='المعادي', area_type='subarea', parent=self.cairo, is_company_area=False)

        self.alex = Area.objects.create(code='ALX', name='الإسكندرية', area_type='governorate', is_company_area=False)
        self.smouha = Area.objects.create(code='SMH', name='سموحة', area_type='subarea', parent=self.alex, is_company_area=False)

        # Users
        self.superadmin = User.objects.create_superuser(
            username='admin@wea.com', email='admin@wea.com', password='Password123!',
            name='Super Admin User', role=self.superadmin_role
        )

        self.mgr_cairo = User.objects.create_user(
            username='mgr@wea.com', email='mgr@wea.com', password='Password123!',
            name='Manager Cairo', role=self.manager_role
        )
        self.mgr_cairo.assigned_areas.add(self.cairo)

        self.rep_user = User.objects.create_user(
            username='rep@wea.com', email='rep@wea.com', password='Password123!',
            name='Representative User', role=self.rep_role
        )
        self.rep_user.assigned_areas.add(self.nasr_city)

    def test_get_hierarchical_areas_for_superadmin_and_manager(self):
        """Superadmin gets all governorates with subareas, manager gets only their main areas."""
        super_areas = get_hierarchical_areas(self.superadmin)
        self.assertIn(self.cairo, super_areas)
        self.assertIn(self.alex, super_areas)

        mgr_areas = get_hierarchical_areas(self.mgr_cairo)
        self.assertIn(self.cairo, mgr_areas)
        self.assertNotIn(self.alex, mgr_areas)

    def test_validate_assigned_areas_server_side(self):
        """Validates valid, invalid, and unauthorized area assignment on the server."""
        # 1. Valid areas for superadmin
        valid, msg, ids = validate_assigned_areas_for_user(self.superadmin, [str(self.cairo.id), str(self.smouha.id)])
        self.assertTrue(valid)
        self.assertEqual(ids, [self.cairo.id, self.smouha.id])

        # 2. Invalid/bogus area ID
        valid, msg, ids = validate_assigned_areas_for_user(self.superadmin, ['999999'])
        self.assertFalse(valid)
        self.assertIn("غير صالحة", msg)

        # 3. Non-integer ID
        valid, msg, ids = validate_assigned_areas_for_user(self.superadmin, ['not_an_id'])
        self.assertFalse(valid)

        # 4. Manager trying to assign area outside their main area
        valid, msg, ids = validate_assigned_areas_for_user(self.mgr_cairo, [str(self.smouha.id)])
        self.assertFalse(valid)
        self.assertIn("خارج نطاق مسؤوليتك", msg)

        # 5. Manager assigning area inside their main area
        valid, msg, ids = validate_assigned_areas_for_user(self.mgr_cairo, [str(self.nasr_city.id)])
        self.assertTrue(valid)
        self.assertEqual(ids, [self.nasr_city.id])

    def test_user_edit_page_renders_hierarchical_selector(self):
        """Edit user page renders the hierarchical area selector component with existing areas selected."""
        self.client.login(username='admin@wea.com', password='Password123!')
        res = self.client.get(reverse('user_edit', kwargs={'pk': self.rep_user.pk}))
        self.assertEqual(res.status_code, 200)
        content = res.content.decode('utf-8')

        # Check for selector elements
        self.assertIn('المناطق الجغرافية المعينة للمستخدم', content)
        self.assertIn('ابحث باسم المنطقة أو المحافظة', content)
        self.assertIn('تحديد الكل', content)
        self.assertIn('مسح التحديد', content)
        self.assertIn(self.cairo.name, content)
        self.assertIn(self.nasr_city.name, content)

        # Nasr City is checked for rep_user
        self.assertIn(f'value="{self.nasr_city.id}"', content)
        self.assertIn(self.nasr_city.id, res.context['selected_area_ids'])

    def test_user_edit_post_updates_areas_safely(self):
        """POST to user_edit updates areas and logs security audit."""
        self.client.login(username='admin@wea.com', password='Password123!')
        data = {
            'name': 'Rep User Updated',
            'email': 'rep@wea.com',
            'code': 'REP-01',
            'mobile': '01012345678',
            'role': self.rep_role.id,
            'is_active': 'on',
            'assigned_areas': [str(self.nasr_city.id), str(self.maadi.id)],
        }
        res = self.client.post(reverse('user_edit', kwargs={'pk': self.rep_user.pk}), data)
        self.assertEqual(res.status_code, 302)

        self.rep_user.refresh_from_db()
        assigned_ids = set(self.rep_user.assigned_areas.values_list('id', flat=True))
        self.assertEqual(assigned_ids, {self.nasr_city.id, self.maadi.id})
