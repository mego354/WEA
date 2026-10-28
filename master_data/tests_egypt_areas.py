from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.core.management import call_command
from master_data.models import Area
from accounts.models import Role

User = get_user_model()


class EgyptAreasTests(TestCase):
    def setUp(self):
        self.client = Client()

        self.superadmin_role, _ = Role.objects.get_or_create(
            name=Role.ROLE_SUPERADMIN,
            defaults={'display_name': 'مدير النظام الأعلى', 'is_super': True, 'is_system': True, 'is_active': True}
        )
        self.admin_user = User.objects.create_superuser(
            username='admin_areas@wea.com',
            email='admin_areas@wea.com',
            password='Password123!',
            name='Admin Areas',
            role=self.superadmin_role
        )

        # Run command to ensure 27 governorates exist
        call_command('setup_egypt_areas')

    def test_27_egyptian_governorates_exist(self):
        """Verify exactly 27 geographic Egyptian governorates exist with is_company_area=False."""
        govs = Area.objects.filter(parent__isnull=True, is_company_area=False)
        self.assertEqual(govs.count(), 27)

        gov_names = set(govs.values_list('name', flat=True))
        expected_sample = {'محافظة القاهرة', 'محافظة الجيزة', 'محافظة الإسكندرية', 'محافظة اسوان', 'محافظة الأقصر', 'محافظة بورسعيد', 'محافظة مطروح', 'محافظة شمال سيناء'}
        for expected in expected_sample:
            self.assertIn(expected, gov_names)

    def test_company_areas_excluded_from_settings(self):
        """Areas marked as is_company_area=True must not appear in areas_settings_view."""
        # Create a company internal area
        company_branch = Area.objects.create(
            name='WEA Main Warehouse HQ',
            code='WEA-HQ',
            is_company_area=True
        )

        self.client.login(username='admin_areas@wea.com', password='Password123!')
        res = self.client.get(reverse('areas_settings'))
        self.assertEqual(res.status_code, 200)

        govs_in_context = res.context['governorates']
        gov_ids_in_context = [a.id for a in govs_in_context]

        self.assertNotIn(company_branch.id, gov_ids_in_context)
        self.assertEqual(len(govs_in_context), 27)

    def test_subarea_count_aggregation(self):
        """Governorates in areas_settings must have subareas_count annotated."""
        cairo = Area.objects.filter(name='محافظة القاهرة', parent__isnull=True).first()
        self.assertIsNotNone(cairo)

        # Add subareas
        Area.objects.create(name='مدينة نصر', code='CAI-01-NASR', parent=cairo, area_type='subarea')
        Area.objects.create(name='المعادي', code='CAI-01-MAADI', parent=cairo, area_type='subarea')

        self.client.login(username='admin_areas@wea.com', password='Password123!')
        res = self.client.get(reverse('areas_settings'))
        self.assertEqual(res.status_code, 200)

        cairo_in_ctx = next(a for a in res.context['governorates'] if a.id == cairo.id)
        self.assertEqual(cairo_in_ctx.subareas_count, 2)
