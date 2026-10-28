from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from accounts.models import Role
from catalog.models import Product, ProductCategory
from activities.models import VisitTemplate
from activities.forms import VisitTemplateForm
from master_data.models import LocationSettings

User = get_user_model()


class VisitSuggestedProductsTests(TestCase):
    def setUp(self):
        self.client = Client()

        self.superadmin_role, _ = Role.objects.get_or_create(
            name=Role.ROLE_SUPERADMIN,
            defaults={'display_name': 'مدير النظام الأعلى', 'is_super': True, 'is_system': True, 'is_active': True}
        )
        self.admin_user = User.objects.create_superuser(
            username='admin_sugg@wea.com',
            email='admin_sugg@wea.com',
            password='Password123!',
            name='Admin Sugg',
            role=self.superadmin_role
        )

        self.category = ProductCategory.objects.create(name='Test Category', code='CAT-01')

        # Products: 1 active sellable, 1 non-sellable, 1 inactive
        self.p_active_sellable = Product.objects.create(
            category=self.category,
            name='Panadol Extra Active Sellable',
            sku_code='PAN-01',
            sellable=True,
            is_active=True
        )
        self.p_non_sellable = Product.objects.create(
            category=self.category,
            name='Display Stand Non Sellable',
            sku_code='DISP-01',
            sellable=False,
            is_active=True
        )
        self.p_inactive = Product.objects.create(
            category=self.category,
            name='Old Medicine Inactive',
            sku_code='OLD-01',
            sellable=True,
            is_active=False
        )

    def test_eligible_suggested_products_filtering(self):
        """VisitTemplate.get_eligible_suggested_products() must return only active, sellable products."""
        template = VisitTemplate.objects.create(
            name='doctor_routine_visit',
            display_name_ar='قالب زيارة الأطباء',
            active=True
        )
        template.suggested_products.add(self.p_active_sellable, self.p_non_sellable, self.p_inactive)

        eligible = list(template.get_eligible_suggested_products())
        self.assertEqual(len(eligible), 1)
        self.assertEqual(eligible[0].id, self.p_active_sellable.id)

    def test_visit_template_form_suggested_products(self):
        """VisitTemplateForm should only offer sellable, active products in suggested_products field."""
        form = VisitTemplateForm()
        queryset_product_ids = list(form.fields['suggested_products'].queryset.values_list('id', flat=True))
        self.assertIn(self.p_active_sellable.id, queryset_product_ids)
        self.assertNotIn(self.p_non_sellable.id, queryset_product_ids)
        self.assertNotIn(self.p_inactive.id, queryset_product_ids)

    def test_location_settings_does_not_contain_suggested_products(self):
        """Location settings view should no longer manage suggested products."""
        self.client.login(username='admin_sugg@wea.com', password='Password123!')
        res = self.client.get(reverse('location_settings'))
        self.assertEqual(res.status_code, 200)
        # Verify Card 4 text is removed
        self.assertNotContains(res, 'المنتجات المقترحة للزيارات الميدانية')
