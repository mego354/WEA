import datetime
from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from django.core.management import call_command
from django.utils import timezone

from accounts.models import User, Role
from master_data.models import Area
from contacts.models import Contact
from catalog.models import Product, ProductCategory
from activities.models import Visit
from inventory.models import Warehouse
from treasury.models import Vault
from sales.models import SalesOrder, SalesOrderItem, Collection
from reports.models import SalesTarget, CustomerCall, CoachingEvaluation


class PerformanceViewsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('setup_permissions')

        cls.superadmin_role = Role.objects.get(name=Role.ROLE_SUPERADMIN)
        cls.manager_role = Role.objects.get(name=Role.ROLE_MANAGER)
        cls.rep_role = Role.objects.get(name=Role.ROLE_REP)

        # Areas
        cls.cairo = Area.objects.create(name='القاهرة', code='CAI-PERF', area_type='governorate')
        cls.nasr_city = Area.objects.create(name='مدينة نصر', code='NAS-PERF', parent=cls.cairo, area_type='subarea')

        # SuperAdmin
        cls.admin_user = User.objects.create_user(
            username='admin_perf@example.com',
            email='admin_perf@example.com',
            password='Password123!',
            role=cls.superadmin_role,
            is_superuser=True,
            is_staff=True
        )

        # Rep
        cls.rep_user = User.objects.create_user(
            username='rep_perf@example.com',
            email='rep_perf@example.com',
            password='Password123!',
            role=cls.rep_role,
            name='أحمد مندوب'
        )
        cls.rep_user.assigned_areas.add(cls.nasr_city)

        # Contact
        cls.customer = Contact.objects.create(
            name='صيدلية النجاح',
            contact_type='customer',
            account_type='pharmacy',
            area=cls.cairo,
            brick=cls.nasr_city,
            created_by=cls.admin_user
        )
        cls.customer.assigned_team.add(cls.rep_user)

        # Category and Product
        cls.cat = ProductCategory.objects.create(name='أدوية بشرية')
        cls.product = Product.objects.create(
            name='بانادول إكسترا',
            sku_code='PAN-EXT-PERF',
            category=cls.cat,
            retail_price=Decimal('45.00'),
            is_active=True
        )

        # Visit
        cls.today = timezone.now().date()
        cls.visit = Visit.objects.create(
            serial_num=99991,
            owner=cls.rep_user,
            contact=cls.customer,
            date=cls.today,
            status='ended',
            location_verified=True,
            created_by=cls.rep_user
        )

        # Warehouse & Sales Order
        cls.warehouse = Warehouse.objects.create(
            name='المخزن الرئيسي للأداء',
            code='WH-PERF-01',
            area=cls.cairo
        )
        cls.order = SalesOrder.objects.create(
            order_number='SO-PERF-001',
            customer=cls.customer,
            source_warehouse=cls.warehouse,
            order_date=cls.today,
            status='delivered',
            grand_total=Decimal('900.00'),
            created_by=cls.rep_user
        )
        SalesOrderItem.objects.create(
            order=cls.order,
            product=cls.product,
            quantity=20,
            unit_price=Decimal('45.00'),
            subtotal=Decimal('900.00')
        )

        # Vault & Collection
        cls.vault = Vault.objects.create(
            serial_num=8801,
            name='خزنة الأداء',
            area=cls.cairo,
            assigned_user=cls.admin_user
        )
        cls.col = Collection.objects.create(
            customer=cls.customer,
            vault=cls.vault,
            collection_date=cls.today,
            amount=Decimal('500.00'),
            payment_method='cash',
            created_by=cls.rep_user
        )

        # Sales Target
        cls.target = SalesTarget.objects.create(
            user=cls.rep_user,
            year=cls.today.year,
            month=cls.today.month,
            target_sales_amount=Decimal('10000.00'),
            target_collections_amount=Decimal('8000.00'),
            target_visits_count=50
        )

        # Coaching Evaluation
        cls.coach = CoachingEvaluation.objects.create(
            manager=cls.admin_user,
            rep=cls.rep_user,
            customer=cls.customer,
            visit=cls.visit,
            date=cls.today,
            product_knowledge_score=9,
            selling_skills_score=8,
            detailing_clarity_score=8,
            objection_handling_score=8,
            overall_score=Decimal('8.5'),
            action_items='حضور ورشة عمل إغلاق الصفقات',
            notes='معرفة دوائية ممتازة ومتابعة دقيقة'
        )

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.admin_user)

    def test_performance_overview_view(self):
        url = reverse('performance_overview')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'performance/overview.html')
        self.assertIn('kpis', response.context)
        self.assertIn('top_detailed_products', response.context)
        self.assertIn('period', response.context)
        # Check actual numbers
        kpis = response.context['kpis']
        self.assertGreaterEqual(kpis['sales_total']['value'], 900.0)
        self.assertGreaterEqual(kpis['collections_total']['value'], 500.0)
        self.assertGreaterEqual(kpis['total_visits']['value'], 1)

    def test_performance_overview_different_periods(self):
        for period in ['this_month', 'last_month', 'quarter', 'year']:
            response = self.client.get(reverse('performance_overview'), {'period': period})
            self.assertEqual(response.status_code, 200)

    def test_performance_analysis_view(self):
        url = reverse('performance_analysis')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'performance/analysis.html')
        self.assertIn('rep_rows', response.context)
        self.assertIn('chart_rep_sales', response.context)
        self.assertIn('chart_visits_mix', response.context)

    def test_performance_analysis_export(self):
        url = reverse('performance_analysis_export')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        self.assertIn('attachment; filename=', response['Content-Disposition'])

    def test_performance_daily_view(self):
        url = reverse('performance_daily')
        response = self.client.get(url, {'date': self.today.isoformat()})
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'performance/daily.html')
        self.assertIn('rep_rows', response.context)
        self.assertIn('kpis', response.context)
        self.assertIn('tab_visits', response.context)

    def test_performance_daily_export(self):
        url = reverse('performance_daily_export')
        response = self.client.get(url, {'date': self.today.isoformat()})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

    def test_performance_detailed_matrix_view(self):
        url = reverse('performance_detailed')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'performance/detailed.html')
        self.assertIn('matrix_rows', response.context)
        self.assertIn('coaching_rows', response.context)

    def test_performance_detailed_export(self):
        url = reverse('performance_detailed_export')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
