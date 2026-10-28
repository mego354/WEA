import json
from decimal import Decimal
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.utils import timezone
from accounts.models import Role
from master_data.models import Area
from contacts.models import Contact
from sales.models import SalesOrder, SalesReturnOrder, Collection, CustomerAccount
from activities.models import Visit
from inventory.models import Warehouse, InventoryStock
from treasury.models import Vault, VendorAccount
from catalog.models import Product

UserModel = get_user_model()


class DashboardRolePermissionsAndMobileNavTests(TestCase):
    def setUp(self):
        self.client = Client()

        # Roles
        self.super_role, _ = Role.objects.get_or_create(
            name='SuperAdmin',
            defaults={'display_name': 'مدير النظام الأعلى', 'is_super': True, 'is_active': True}
        )
        self.mgr_role, _ = Role.objects.get_or_create(
            name='AreaManager',
            defaults={'display_name': 'مدير منطقة', 'is_area_manager': True, 'is_active': True}
        )
        self.rep_role, _ = Role.objects.get_or_create(
            name='SalesRep',
            defaults={'display_name': 'مندوب مبيعات', 'is_rep': True, 'is_active': True}
        )
        self.acct_role, _ = Role.objects.get_or_create(
            name='Accountant',
            defaults={'display_name': 'محاسب مالي', 'is_active': True}
        )

        # Areas: Cairo (Region A) and Alexandria (Region B)
        self.cairo_main = Area.objects.create(name='القاهرة (رئيسية)', code='CAI-MAIN')
        self.cairo_sub = Area.objects.create(name='المعادي', code='CAI-MAA', parent=self.cairo_main)
        self.alex_main = Area.objects.create(name='الإسكندرية (رئيسية)', code='ALX-MAIN')
        self.alex_sub = Area.objects.create(name='سموحة', code='ALX-SMH', parent=self.alex_main)

        # Users
        self.superadmin = UserModel.objects.create_user(
            username='super_boss',
            password='Password123!',
            name='Super Administrator Extremely Long Name Test For Ellipsis Handling',
            role=self.super_role,
            is_superuser=True
        )

        self.cairo_manager = UserModel.objects.create_user(
            username='cairo_mgr',
            password='Password123!',
            name='أحمد مدير منطقة القاهرة',
            role=self.mgr_role
        )
        self.cairo_manager.assigned_areas.add(self.cairo_main)

        self.cairo_rep = UserModel.objects.create_user(
            username='cairo_rep',
            password='Password123!',
            name='محمود مندوب القاهرة',
            role=self.rep_role
        )
        self.cairo_rep.assigned_areas.add(self.cairo_sub)

        self.alex_rep = UserModel.objects.create_user(
            username='alex_rep',
            password='Password123!',
            name='طارق مندوب الإسكندرية',
            role=self.rep_role
        )
        self.alex_rep.assigned_areas.add(self.alex_sub)

        self.accountant = UserModel.objects.create_user(
            username='acct_user',
            password='Password123!',
            name='محاسب الحسابات والمالية',
            role=self.acct_role
        )

        # Seed Product
        from catalog.models import ProductCategory
        self.cat = ProductCategory.objects.create(name='أدوية عامة', code='CAT-GEN')
        self.prod = Product.objects.create(
            category=self.cat,
            name='منتج تجريبي 1',
            sku_code='PRD-001',
            retail_price=Decimal('100.00'),
            default_purchase_cost=Decimal('70.00')
        )

        # Rep Warehouses & Vaults
        self.cairo_wh = Warehouse.objects.create(
            name='مخزن عهدة مندوب المعادي',
            code='WH-REP-CAI',
            assigned_user=self.cairo_rep,
            is_rep_warehouse=True,
            area=self.cairo_sub
        )
        self.alex_wh = Warehouse.objects.create(
            name='مخزن عهدة مندوب سموحة',
            code='WH-REP-ALX',
            assigned_user=self.alex_rep,
            is_rep_warehouse=True,
            area=self.alex_sub
        )
        InventoryStock.objects.create(
            warehouse=self.cairo_wh,
            product=self.prod,
            qty_on_hand=Decimal('45.00')
        )

        self.cairo_vault = Vault.objects.create(
            serial_num=5001,
            name='عهدة نقدية مندوب المعادي',
            assigned_user=self.cairo_rep,
            is_rep_vault=True,
            current_balance=Decimal('1500.00')
        )

        # Cairo Customer & Rep Operations
        self.cairo_cust = Contact.objects.create(
            name='عميل القاهرة للتجارة',
            is_customer=True,
            area=self.cairo_sub,
            created_by=self.cairo_rep
        )
        self.cairo_cust_account = CustomerAccount.objects.create(
            customer=self.cairo_cust,
            current_balance=Decimal('5000.00'),
            overdue_balance=Decimal('1200.00'),
            credit_period_days=30
        )

        # Cairo Sales Order & Collection
        self.cairo_so = SalesOrder.objects.create(
            order_number='SO-CAI-001',
            customer=self.cairo_cust,
            created_by=self.cairo_rep,
            source_warehouse=self.cairo_wh,
            status='delivered',
            grand_total=Decimal('3500.00'),
            order_date=timezone.now().date()
        )
        self.cairo_col = Collection.objects.create(
            customer=self.cairo_cust,
            vault=self.cairo_vault,
            created_by=self.cairo_rep,
            amount=Decimal('2000.00'),
            payment_method='cash',
            collection_date=timezone.now().date()
        )
        self.cairo_visit = Visit.objects.create(
            contact=self.cairo_cust,
            owner=self.cairo_rep,
            created_by=self.cairo_rep,
            status='finished',
            date=timezone.now().date()
        )

        # Alex Customer & Operations
        self.alex_cust = Contact.objects.create(
            name='عميل الإسكندرية الدولي',
            is_customer=True,
            area=self.alex_sub,
            created_by=self.alex_rep
        )
        self.alex_so = SalesOrder.objects.create(
            order_number='SO-ALX-001',
            customer=self.alex_cust,
            created_by=self.alex_rep,
            source_warehouse=self.alex_wh,
            status='delivered',
            grand_total=Decimal('9000.00'),
            order_date=timezone.now().date()
        )

    # =========================================================================
    # 1. MOBILE NAVIGATION & USERNAME OVERFLOW TESTS
    # =========================================================================
    def test_mobile_bottom_nav_has_no_redundant_menu_toggle(self):
        """Verifies mobile bottom nav has only 4 functional tabs and no redundant 5th menu toggle."""
        self.client.force_login(self.superadmin)
        response = self.client.get('/home/')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')

        # Top-right mobile drawer toggle must remain active
        self.assertIn('id="mobileMenuToggle"', content)

        # Redundant bottom drawer toggle button must NOT be present
        self.assertNotIn('id="mobileBottomMenuToggle"', content)
        self.assertNotIn('openMobileNavDrawer', content)

    def test_long_user_name_rendered_with_truncation_and_title(self):
        """Verifies long names do not break layout: use min-w-0, truncate, and title tooltip."""
        self.client.force_login(self.superadmin)
        response = self.client.get('/home/')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')

        # Check for truncate and title in user profile area
        self.assertIn('text-sm font-bold text-slate-900 truncate', content)
        self.assertIn('title="Super Administrator Extremely Long Name Test For Ellipsis Handling', content)

    # =========================================================================
    # 2. ROLE-BASED DASHBOARD: SUPERADMIN
    # =========================================================================
    def test_superadmin_dashboard_sees_system_wide_metrics_and_all_charts(self):
        """Superadmin can access all system-wide KPI metrics and all 6 sunburst charts."""
        self.client.force_login(self.superadmin)
        response = self.client.get('/home/?period=all')
        self.assertEqual(response.status_code, 200)

        context = response.context
        self.assertTrue(context['is_super'])
        self.assertEqual(len(context['kpi_cards']), 14)

        charts_data = json.loads(context['charts_json'])
        self.assertIn('collections_by_area', charts_data)
        self.assertIn('visits_by_area', charts_data)
        self.assertIn('orders_created_by_area', charts_data)
        self.assertIn('orders_delivered_by_area', charts_data)
        self.assertIn('reps_balance', charts_data)
        self.assertIn('reps_overdue', charts_data)

        # Eligible reps selector list is populated
        self.assertGreater(len(context['eligible_reps']), 0)

    # =========================================================================
    # 3. ROLE-BASED DASHBOARD: ACCOUNTANT
    # =========================================================================
    def test_accountant_dashboard_financial_only_and_no_visits(self):
        """Accountant sees financial stats and charts, but visits metrics and visit chart are excluded."""
        self.client.force_login(self.accountant)
        response = self.client.get('/home/?period=all')
        self.assertEqual(response.status_code, 200)

        context = response.context
        self.assertTrue(context['is_acct'])
        self.assertFalse(context['is_super'])

        card_ids = [c['id'] for c in context['kpi_cards']]
        # Must include financial cards
        self.assertIn('pos_created_stats', card_ids)
        self.assertIn('net_sales_stats', card_ids)
        self.assertIn('collections_collected_stats', card_ids)
        self.assertIn('vaults_total_stats', card_ids)
        self.assertIn('vendors_total_stats', card_ids)

        # Must NOT include visit cards
        self.assertNotIn('visits_created_lead_stats', card_ids)
        self.assertNotIn('visits_created_customer_stats', card_ids)

        # Charts: visits_by_area must NOT be in charts_json or available_charts
        charts_data = json.loads(context['charts_json'])
        self.assertNotIn('visits_by_area', charts_data)
        self.assertNotIn('visits_by_area', context['available_charts'])

        # Rep selector must be empty
        self.assertEqual(len(context['eligible_reps']), 0)

    # =========================================================================
    # 4. ROLE-BASED DASHBOARD: REPRESENTATIVE
    # =========================================================================
    def test_representative_sees_only_own_metrics_and_no_cross_rep_charts(self):
        """Representative sees their own operational metrics and peer privacy charts are omitted."""
        self.client.force_login(self.cairo_rep)
        response = self.client.get('/home/?period=all')
        self.assertEqual(response.status_code, 200)

        context = response.context
        self.assertTrue(context['is_rep'])
        self.assertFalse(context['is_mgr'])

        card_ids = [c['id'] for c in context['kpi_cards']]
        self.assertIn('rep_vault_stats', card_ids)
        self.assertIn('rep_stock_stats', card_ids)
        self.assertIn('visits_created_lead_stats', card_ids)

        # Cross-rep comparison charts MUST be omitted for reps
        charts_data = json.loads(context['charts_json'])
        self.assertNotIn('reps_balance', charts_data)
        self.assertNotIn('reps_overdue', charts_data)
        self.assertNotIn('reps_balance', context['available_charts'])
        self.assertNotIn('reps_overdue', context['available_charts'])

        # Rep selector is empty
        self.assertEqual(len(context['eligible_reps']), 0)

    # =========================================================================
    # 5. ROLE-BASED DASHBOARD: MANAGER & SCOPE ENFORCEMENT
    # =========================================================================
    def test_manager_sees_team_scope_in_their_main_area(self):
        """Cairo manager sees team-level data for Cairo, not Alexandria."""
        self.client.force_login(self.cairo_manager)
        response = self.client.get('/home/?period=all')
        self.assertEqual(response.status_code, 200)

        context = response.context
        self.assertTrue(context['is_mgr'])
        self.assertIsNone(context['selected_rep'])

        # Eligible reps only include Cairo rep, NOT Alexandria rep
        eligible_ids = [r.id for r in context['eligible_reps']]
        self.assertIn(self.cairo_rep.id, eligible_ids)
        self.assertNotIn(self.alex_rep.id, eligible_ids)

    def test_manager_can_select_eligible_representative(self):
        """Manager selects their authorized representative and views their individual metrics."""
        self.client.force_login(self.cairo_manager)
        response = self.client.get(f'/home/?period=all&rep_id={self.cairo_rep.id}')
        self.assertEqual(response.status_code, 200)

        context = response.context
        self.assertIsNotNone(context['selected_rep'])
        self.assertEqual(context['selected_rep'].id, self.cairo_rep.id)

        content = response.content.decode('utf-8')
        self.assertIn('يتم الآن استعراض إحصائيات المندوب', content)
        self.assertIn(self.cairo_rep.name, content)
        self.assertIn('العودة لإحصائيات الفريق كامل', content)

    def test_manager_cannot_select_unauthorized_cross_area_representative(self):
        """Manager attempting to pass an unauthorized rep_id (Alexandria) is safely denied."""
        self.client.force_login(self.cairo_manager)
        # Attempting to access Alex rep
        response = self.client.get(f'/home/?period=all&rep_id={self.alex_rep.id}')
        self.assertEqual(response.status_code, 200)

        context = response.context
        # Security enforcement: selected_rep must be None, falling back safely to team scope
        self.assertIsNone(context['selected_rep'])

        content = response.content.decode('utf-8')
        # Does NOT show Alex rep as selected
        self.assertNotIn(f'استعراض إحصائيات المندوب: {self.alex_rep.name}', content)

    # =========================================================================
    # 6. TABLE COLUMN PICKER STRUCTURE TEST
    # =========================================================================
    def test_tables_contain_data_col_and_column_picker_components(self):
        """Verify applicable list tables contain data-col-table and table_column_picker integration."""
        self.client.force_login(self.superadmin)

        urls_to_test = [
            '/contacts/',
            '/sales/',
            '/sales/collections/',
            '/inventory/',
            '/inventory/transfers/',
            '/purchases/',
            '/visits/',
            '/treasury/vaults/',
            '/users/',
            '/products/',
            '/agreements/',
        ]

        for url in urls_to_test:
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200, f"Failed on URL {url}")
            content = resp.content.decode('utf-8')
            self.assertIn('data-col-table=', content, f"Missing data-col-table in {url}")
            self.assertIn('data-col=', content, f"Missing data-col in {url}")
            self.assertIn('TableColumnManager', content, f"Missing TableColumnManager in {url}")
