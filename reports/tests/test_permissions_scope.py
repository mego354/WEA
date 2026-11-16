import datetime
from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from django.core.management import call_command
from django.utils import timezone

from accounts.models import User, Role, RoleModuleScope
from master_data.models import Area
from contacts.models import Contact
from catalog.models import Product, ProductCategory
from inventory.models import Warehouse, InventoryStock
from treasury.models import Vault
from activities.models import Visit
from sales.models import SalesOrder, SalesOrderItem, Collection, CustomerAccount, CustomerTransaction
from reports.models import SalesTarget
from reports.services import (
    get_performance_overview_data,
    get_ar_aging_report_data,
    get_customer_360_report_data,
    get_target_achievement_report_data,
)


class ReportsPermissionsAndDataScopeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('setup_permissions')

        cls.superadmin_role = Role.objects.get(name=Role.ROLE_SUPERADMIN)
        cls.manager_role = Role.objects.get(name=Role.ROLE_MANAGER)
        cls.rep_role = Role.objects.get(name=Role.ROLE_REP)
        cls.accountant_role = Role.objects.get(name=Role.ROLE_ACCOUNTANT)

        # 1. Geographic Hierarchy: Cairo (Nasr City, Maadi) vs Giza (Dokki)
        cls.cairo = Area.objects.create(name='القاهرة', code='CAI-SCOPE', area_type='governorate')
        cls.nasr_city = Area.objects.create(name='مدينة نصر', code='NAS-SCOPE', parent=cls.cairo, area_type='subarea')
        cls.maadi = Area.objects.create(name='المعادي', code='MAA-SCOPE', parent=cls.cairo, area_type='subarea')

        cls.giza = Area.objects.create(name='الجيزة', code='GIZ-SCOPE', area_type='governorate')
        cls.dokki = Area.objects.create(name='الدقي', code='DOK-SCOPE', parent=cls.giza, area_type='subarea')

        # 2. Users
        cls.superadmin = User.objects.create_user(
            username='admin_sc@example.com',
            email='admin_sc@example.com',
            password='Password123!',
            role=cls.superadmin_role,
            is_superuser=True,
            is_staff=True
        )

        cls.cairo_manager = User.objects.create_user(
            username='mgr_cairo_sc@example.com',
            email='mgr_cairo_sc@example.com',
            password='Password123!',
            role=cls.manager_role,
            name='مدير منطقة القاهرة'
        )
        cls.cairo_manager.assigned_areas.add(cls.cairo)

        cls.giza_manager = User.objects.create_user(
            username='mgr_giza_sc@example.com',
            email='mgr_giza_sc@example.com',
            password='Password123!',
            role=cls.manager_role,
            name='مدير منطقة الجيزة'
        )
        cls.giza_manager.assigned_areas.add(cls.giza)

        cls.rep_cairo = User.objects.create_user(
            username='rep_cairo_sc@example.com',
            email='rep_cairo_sc@example.com',
            password='Password123!',
            role=cls.rep_role,
            name='مندوب القاهرة'
        )
        cls.rep_cairo.assigned_areas.add(cls.nasr_city)

        cls.rep_giza = User.objects.create_user(
            username='rep_giza_sc@example.com',
            email='rep_giza_sc@example.com',
            password='Password123!',
            role=cls.rep_role,
            name='مندوب الجيزة'
        )
        cls.rep_giza.assigned_areas.add(cls.dokki)

        cls.accountant = User.objects.create_user(
            username='acc_sc@example.com',
            email='acc_sc@example.com',
            password='Password123!',
            role=cls.accountant_role,
            name='محاسب الشركة'
        )

        # 3. Warehouses & Vaults
        cls.wh_cairo = Warehouse.objects.create(name='مخزن القاهرة', code='WH-CAI-SC')
        cls.wh_giza = Warehouse.objects.create(name='مخزن الجيزة', code='WH-GIZ-SC')
        cls.vault = Vault.objects.create(name='خزينة رئيسية', vault_type='cash')

        # 4. Catalog
        cls.cat = ProductCategory.objects.create(name='عام')
        cls.product = Product.objects.create(
            name='كونجستال', sku_code='CONG-SC', category=cls.cat, retail_price=Decimal('30.00'), is_active=True
        )

        cls.today = timezone.now().date()

        # 5. Cairo Records
        cls.cust_cairo = Contact.objects.create(
            name='صيدلية القاهرة الكبرى', status='customer', area=cls.cairo, brick=cls.nasr_city, created_by=cls.superadmin
        )
        cls.cust_cairo.assigned_team.add(cls.rep_cairo)

        cls.acc_cairo, _ = CustomerAccount.objects.get_or_create(
            customer=cls.cust_cairo, defaults={'credit_limit': Decimal('20000.00')}
        )
        CustomerTransaction.objects.create(
            serial=8801, account=cls.acc_cairo, transaction_type='debit', reason='sales',
            transaction_date=cls.today, due_date=cls.today - datetime.timedelta(days=10),
            debit=Decimal('3000.00'), credit=Decimal('0.00'), running_balance=Decimal('3000.00'),
            description='فاتورة القاهرة', created_by=cls.rep_cairo
        )
        cls.acc_cairo.current_balance = Decimal('3000.00')
        cls.acc_cairo.overdue_balance = Decimal('3000.00')
        cls.acc_cairo.save()

        cls.visit_cairo = Visit.objects.create(
            owner=cls.rep_cairo, contact=cls.cust_cairo, date=cls.today, status='ended',
            location_verified=True, created_by=cls.rep_cairo
        )
        cls.order_cairo = SalesOrder.objects.create(
            customer=cls.cust_cairo, source_warehouse=cls.wh_cairo, order_date=cls.today,
            status='delivered', subtotal=Decimal('3000.00'), grand_total=Decimal('3000.00'), created_by=cls.rep_cairo
        )

        # 6. Giza Records
        cls.cust_giza = Contact.objects.create(
            name='صيدلية الدقي التخصصية', status='customer', area=cls.giza, brick=cls.dokki, created_by=cls.superadmin
        )
        cls.cust_giza.assigned_team.add(cls.rep_giza)

        cls.acc_giza, _ = CustomerAccount.objects.get_or_create(
            customer=cls.cust_giza, defaults={'credit_limit': Decimal('15000.00')}
        )
        CustomerTransaction.objects.create(
            serial=8802, account=cls.acc_giza, transaction_type='debit', reason='sales',
            transaction_date=cls.today, due_date=cls.today - datetime.timedelta(days=20),
            debit=Decimal('7000.00'), credit=Decimal('0.00'), running_balance=Decimal('7000.00'),
            description='فاتورة الجيزة', created_by=cls.rep_giza
        )
        cls.acc_giza.current_balance = Decimal('7000.00')
        cls.acc_giza.overdue_balance = Decimal('7000.00')
        cls.acc_giza.save()

        cls.visit_giza = Visit.objects.create(
            owner=cls.rep_giza, contact=cls.cust_giza, date=cls.today, status='ended',
            location_verified=True, created_by=cls.rep_giza
        )
        cls.order_giza = SalesOrder.objects.create(
            customer=cls.cust_giza, source_warehouse=cls.wh_giza, order_date=cls.today,
            status='delivered', subtotal=Decimal('7000.00'), grand_total=Decimal('7000.00'), created_by=cls.rep_giza
        )

    def setUp(self):
        self.client = Client()

    def test_anonymous_user_redirected_to_login(self):
        endpoints = [
            reverse('performance_overview'),
            reverse('performance_analysis'),
            reverse('performance_daily'),
            reverse('performance_detailed'),
            reverse('reports_hub'),
            reverse('report_ar_aging'),
            reverse('report_trial_balance'),
            reverse('report_net_sales'),
        ]
        for url in endpoints:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302)
            self.assertIn('login', response.url)

    def test_user_without_permission_receives_403(self):
        # Create a user with a role that has 0 permissions
        empty_role = Role.objects.create(name='guest_test', display_name='زائر بدون صلاحيات')
        guest_user = User.objects.create_user(
            username='guest@example.com', email='guest@example.com', password='Password123!', role=empty_role
        )
        self.client.force_login(guest_user)

        response = self.client.get(reverse('performance_overview'))
        self.assertEqual(response.status_code, 403)

        response = self.client.get(reverse('report_ar_aging'))
        self.assertEqual(response.status_code, 403)

    def test_superadmin_data_scoping_sees_all(self):
        # Superadmin sees both Cairo (3,000) and Giza (7,000) -> Total 10,000
        start_d = self.today - datetime.timedelta(days=1)
        end_d = self.today
        data = get_performance_overview_data(self.superadmin, start_d, end_d, start_d, end_d)
        self.assertEqual(data['current']['sales_total'], Decimal('10000.00'))
        self.assertEqual(data['current']['total_visits'], 2)

        ar_data = get_ar_aging_report_data(self.superadmin)
        self.assertEqual(len(ar_data['rows']), 2)
        self.assertEqual(ar_data['summary']['total_receivables'], 10000.0)

    def test_cairo_manager_data_scoping_strictly_isolated_from_giza(self):
        # Cairo Manager sees only Cairo (3,000), 0 from Giza
        start_d = self.today - datetime.timedelta(days=1)
        end_d = self.today
        data = get_performance_overview_data(self.cairo_manager, start_d, end_d, start_d, end_d)
        self.assertEqual(data['current']['sales_total'], Decimal('3000.00'))
        self.assertEqual(data['current']['total_visits'], 1)

        ar_data = get_ar_aging_report_data(self.cairo_manager)
        self.assertEqual(len(ar_data['rows']), 1)
        self.assertEqual(ar_data['rows'][0]['customer_name'], 'صيدلية القاهرة الكبرى')
        self.assertEqual(ar_data['summary']['total_receivables'], 3000.0)

    def test_giza_manager_data_scoping_strictly_isolated_from_cairo(self):
        # Giza Manager sees only Giza (7,000), 0 from Cairo
        start_d = self.today - datetime.timedelta(days=1)
        end_d = self.today
        data = get_performance_overview_data(self.giza_manager, start_d, end_d, start_d, end_d)
        self.assertEqual(data['current']['sales_total'], Decimal('7000.00'))
        self.assertEqual(data['current']['total_visits'], 1)

        ar_data = get_ar_aging_report_data(self.giza_manager)
        self.assertEqual(len(ar_data['rows']), 1)
        self.assertEqual(ar_data['rows'][0]['customer_name'], 'صيدلية الدقي التخصصية')
        self.assertEqual(ar_data['summary']['total_receivables'], 7000.0)

    def test_cairo_rep_own_scoping(self):
        # Cairo Rep sees only their own visits and assigned customers
        c360 = get_customer_360_report_data(self.rep_cairo, self.today, self.today)
        self.assertEqual(len(c360['rows']), 1)
        self.assertEqual(c360['rows'][0]['name'], 'صيدلية القاهرة الكبرى')

    def test_accountant_can_view_financial_and_sales_reports_across_company(self):
        # Accountant role has view_scope='all' for financial, sales, inventory, purchases
        self.client.force_login(self.accountant)

        # AR Aging (Financial)
        res_ar = self.client.get(reverse('report_ar_aging'))
        self.assertEqual(res_ar.status_code, 200)

        # Trial Balance (Financial)
        res_tb = self.client.get(reverse('report_trial_balance'))
        self.assertEqual(res_tb.status_code, 200)

        # Net Sales (Sales)
        res_sales = self.client.get(reverse('report_net_sales'))
        self.assertEqual(res_sales.status_code, 200)

        # Delivery Stock (Inventory)
        res_stock = self.client.get(reverse('report_delivery_stock'))
        self.assertEqual(res_stock.status_code, 200)
