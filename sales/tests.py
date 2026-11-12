import io
import datetime
import openpyxl
from decimal import Decimal

from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone

from accounts.models import Role
from master_data.models import Area, SalesSettings
from contacts.models import Contact
from catalog.models import Product, ProductCategory
from inventory.models import Warehouse, InventoryStock
from treasury.models import Vault
from sales.models import SalesOrder, SalesOrderItem, Collection, CustomerAccount
from sales.services import SalesOrderService, CollectionService

User = get_user_model()


class SalesExcelExportTestCase(TestCase):
    """Verifies sales orders and collections Excel export workflows."""

    def setUp(self):
        self.user = User.objects.create_superuser(
            email='salesadmin@weapharma.com',
            username='salesadmin@weapharma.com',
            password='Password123!',
            first_name='Sales',
            last_name='Admin'
        )
        self.client = Client()
        self.client.login(username='salesadmin@weapharma.com', password='Password123!')

        self.contact = Contact.objects.create(
            serial_num=8801,
            name='صيدلية الشفاء التخصصية',
            is_customer=True,
            phone='01234567890'
        )
        self.customer_account, _ = CustomerAccount.objects.get_or_create(customer=self.contact)
        self.customer_account.credit_limit = Decimal('100000.00')
        self.customer_account.current_balance = Decimal('25000.00')
        self.customer_account.save()

        self.warehouse = Warehouse.objects.create(name='مخزن مبيعات رئيسي', code='WH-SALES')
        self.vault = Vault.objects.create(name='خزينة مبيعات', vault_type='cash')

        self.order = SalesOrder.objects.create(
            customer=self.contact,
            source_warehouse=self.warehouse,
            status='pending',
            grand_total=Decimal('4800.00'),
            created_by=self.user
        )
        self.collection = Collection.objects.create(
            customer=self.contact,
            vault=self.vault,
            amount=Decimal('4800.00'),
            payment_method='cash',
            created_by=self.user
        )

    def test_sales_orders_export_excel(self):
        response = self.client.get(reverse('sales_orders_export'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        self.assertIn('.xlsx', response['Content-Disposition'])

        wb = openpyxl.load_workbook(io.BytesIO(response.content))
        ws = wb.active
        self.assertTrue(ws.sheet_view.rightToLeft)
        found = any(cell.value == self.order.order_number for row in ws.iter_rows() for cell in row)
        self.assertTrue(found)

    def test_collections_export_excel(self):
        response = self.client.get(reverse('collections_export'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        self.assertIn('.xlsx', response['Content-Disposition'])

        wb = openpyxl.load_workbook(io.BytesIO(response.content))
        ws = wb.active
        self.assertTrue(ws.sheet_view.rightToLeft)
        found = any('صيدلية الشفاء' in str(cell.value) for row in ws.iter_rows() for cell in row)
        self.assertTrue(found)


class RepresentativeSalesWarehouseTests(TestCase):
    """
    Verifies representative sale warehouse rules:
    1. Every representative sale uses their designated default warehouse
    2. Client-submitted / forged warehouse IDs are rejected on server
    3. Required manager approval follows main area eligibility
    4. Anti-self-approval prevents reps from approving their own orders
    """

    def setUp(self):
        self.client = Client()

        self.cairo_main = Area.objects.create(code='CAI-SALES', name='القاهرة', area_type='governorate', parent=None)
        self.nasr_city = Area.objects.create(code='CAI-NC-SALES', name='مدينة نصر', area_type='subarea', parent=self.cairo_main)

        self.alex_main = Area.objects.create(code='ALX-SALES', name='الإسكندرية', area_type='governorate', parent=None)
        self.smouha = Area.objects.create(code='ALX-SM-SALES', name='سموحة', area_type='subarea', parent=self.alex_main)

        self.rep_role, _ = Role.objects.get_or_create(name='MedicalRep_Sales', defaults={'display_name': 'مندوب دعاية', 'is_rep': True})
        self.rep_role.is_rep = True
        self.rep_role.save()

        self.mgr_role, _ = Role.objects.get_or_create(name='AreaManager_Sales', defaults={'display_name': 'مدير منطقة', 'is_area_manager': True, 'is_rep': False})
        self.mgr_role.is_area_manager = True
        self.mgr_role.is_rep = False
        self.mgr_role.save()

        self.rep_cairo = User.objects.create_user(username='rep_cairo_sale', role=self.rep_role)
        self.rep_cairo.assigned_areas.add(self.nasr_city)

        self.mgr_cairo = User.objects.create_user(username='mgr_cairo_sale', role=self.mgr_role)
        self.mgr_cairo.assigned_areas.add(self.cairo_main)

        self.mgr_alex = User.objects.create_user(username='mgr_alex_sale', role=self.mgr_role)
        self.mgr_alex.assigned_areas.add(self.alex_main)

        self.customer = Contact.objects.create(name='صيدلية الشفاء بالحي السابع', is_customer=True, area=self.nasr_city)
        self.category = ProductCategory.objects.create(name='أدوية للأطفال')
        self.product = Product.objects.create(
            name='كونجستال أقراص', sku_code='CONG-TAB-REP',
            retail_price=Decimal('25.00'), default_purchase_cost=Decimal('15.00'), category=self.category
        )

        from accounts.services import ensure_representative_resources
        ensure_representative_resources(self.rep_cairo, create_warehouse=True)
        self.rep_wh = self.rep_cairo.get_default_warehouse()

        self.other_wh = Warehouse.objects.create(
            name='مخزن فرع آخر إسكندرية', code='WH-OTHER-SALES', area=self.smouha, is_rep_warehouse=False
        )

        InventoryStock.objects.create(
            warehouse=self.rep_wh,
            product=self.product,
            qty_on_hand=Decimal('50.00'),
            qty_reserved=Decimal('0.00'),
            product_cost=Decimal('15.00')
        )

        settings = SalesSettings.get_settings()
        settings.require_manager_approval = True
        settings.save()

    def test_sales_enforces_representative_warehouse(self):
        items_data = [{'product': self.product, 'quantity': Decimal('5.00'), 'unit_price': Decimal('25.00')}]
        order = SalesOrderService.create_order(
            customer=self.customer,
            source_warehouse=self.rep_wh,
            order_date=None,
            items_data=items_data,
            user=self.rep_cairo
        )
        self.assertEqual(order.source_warehouse, self.rep_wh)
        self.assertEqual(order.status, 'pending')

    def test_forged_warehouse_id_is_rejected(self):
        items_data = [{'product': self.product, 'quantity': Decimal('5.00'), 'unit_price': Decimal('25.00')}]
        with self.assertRaises(ValidationError) as ctx:
            SalesOrderService.create_order(
                customer=self.customer,
                source_warehouse=self.other_wh,
                order_date=None,
                items_data=items_data,
                user=self.rep_cairo
            )
        self.assertIn("غير مصرح للمندوب بإجراء مبيعات من مخزن آخر", str(ctx.exception))

    def test_sales_approval_by_same_main_area_manager(self):
        items_data = [{'product': self.product, 'quantity': Decimal('5.00'), 'unit_price': Decimal('25.00')}]
        order = SalesOrderService.create_order(
            customer=self.customer,
            source_warehouse=self.rep_wh,
            order_date=None,
            items_data=items_data,
            user=self.rep_cairo
        )

        # Rep cannot approve own sale (anti-self-approval)
        with self.assertRaises(ValidationError):
            SalesOrderService.approve_order(order, self.rep_cairo)

        # Alex manager cannot approve Cairo sale
        with self.assertRaises(ValidationError) as ctx:
            SalesOrderService.approve_order(order, self.mgr_alex)
        self.assertIn("خارج نطاق منطقتك الرئيسية", str(ctx.exception))

        # Cairo manager CAN approve
        approved_order = SalesOrderService.approve_order(order, self.mgr_cairo, notes='معتمد من مدير القاهرة')
        self.assertEqual(approved_order.status, 'manager_approval')
        self.assertEqual(approved_order.approved_by, self.mgr_cairo)


class SalesWorkflowAndValidationTests(TestCase):
    """Verifies sales calculations, discount formulas, stock validation, and boundary conditions."""

    def setUp(self):
        self.cairo = Area.objects.create(code='CAI-WF', name='القاهرة', area_type='governorate', parent=None)
        self.nasr_city = Area.objects.create(code='NC-WF', name='مدينة نصر', area_type='subarea', parent=self.cairo)

        self.super_role, _ = Role.objects.get_or_create(name='superadmin', defaults={'is_super': True})
        self.rep_role, _ = Role.objects.get_or_create(name='Rep_WF', defaults={'is_rep': True, 'is_sales_team': True})

        self.superadmin = User.objects.create_superuser(username='superadmin_wf', email='super_wf@test.com', password='pass')
        self.rep = User.objects.create_user(username='sales_rep_wf', first_name='علي', last_name='حسن', role=self.rep_role)
        self.rep.assigned_areas.add(self.nasr_city)

        self.customer = Contact.objects.create(
            name='صيدلية الحياة الكبرى',
            is_customer=True,
            area=self.nasr_city,
            created_by=self.rep
        )

        self.warehouse = Warehouse.objects.create(name='مخزن الدعم اللوجستي', code='WH-WF-MAIN', is_main=True, area=self.cairo)

        self.cat = ProductCategory.objects.create(name='أدوية ومستحضرات')
        self.prod1 = Product.objects.create(name='بنادول إكسترا', sku_code='PAN-EX-WF', retail_price=Decimal('50.00'), category=self.cat)
        self.prod2 = Product.objects.create(name='كونجستال شراب', sku_code='CONG-SYR-WF', retail_price=Decimal('30.00'), category=self.cat)

        self.stock1 = InventoryStock.objects.create(
            warehouse=self.warehouse,
            product=self.prod1,
            qty_on_hand=Decimal('100.00'),
            qty_reserved=Decimal('0.00'),
            product_cost=Decimal('35.00')
        )
        self.stock2 = InventoryStock.objects.create(
            warehouse=self.warehouse,
            product=self.prod2,
            qty_on_hand=Decimal('50.00'),
            qty_reserved=Decimal('0.00'),
            product_cost=Decimal('20.00')
        )

    def test_sales_order_discounts_and_shipping_calculation(self):
        items_data = [
            {'product': self.prod1, 'quantity': Decimal('10.00'), 'unit_price': Decimal('50.00'), 'discount_percentage': Decimal('10.00')},
            {'product': self.prod2, 'quantity': Decimal('5.00'), 'unit_price': Decimal('30.00'), 'discount_percentage': Decimal('0.00')},
        ]
        order = SalesOrderService.create_order(
            customer=self.customer,
            source_warehouse=self.warehouse,
            order_date='2026-11-01',
            items_data=items_data,
            user=self.superadmin,
            custom_discount_percentage=Decimal('5.00'),
            shipping_fees=Decimal('25.00'),
            notes='Test order discounts'
        )

        self.assertEqual(order.subtotal, Decimal('650.00'))
        self.assertEqual(order.items_discount_total, Decimal('50.00'))
        self.assertEqual(order.custom_discount_amount, Decimal('30.00'))
        self.assertEqual(order.shipping_fees, Decimal('25.00'))
        self.assertEqual(order.grand_total, Decimal('595.00'))

    def test_insufficient_stock_prevents_order_creation(self):
        items_data = [
            {'product': self.prod1, 'quantity': Decimal('150.00'), 'unit_price': Decimal('50.00')},
        ]
        with self.assertRaises(ValidationError) as ctx:
            SalesOrderService.create_order(
                customer=self.customer,
                source_warehouse=self.warehouse,
                order_date='2026-11-01',
                items_data=items_data,
                user=self.superadmin,
                validate_stock=True
            )
        self.assertIn("الرصيد المتاح", str(ctx.exception))

    def test_reserved_stock_prevents_overselling(self):
        self.stock1.qty_reserved = Decimal('90.00')
        self.stock1.save()

        items_data = [
            {'product': self.prod1, 'quantity': Decimal('20.00'), 'unit_price': Decimal('50.00')},
        ]
        with self.assertRaises(ValidationError) as ctx:
            SalesOrderService.create_order(
                customer=self.customer,
                source_warehouse=self.warehouse,
                order_date='2026-11-01',
                items_data=items_data,
                user=self.superadmin,
                validate_stock=True
            )
        self.assertIn("الرصيد المتاح", str(ctx.exception))

    def test_validation_rejects_negative_or_invalid_values(self):
        with self.assertRaises(ValidationError):
            SalesOrderService.create_order(
                customer=self.customer,
                source_warehouse=self.warehouse,
                order_date='2026-11-01',
                items_data=[{'product': self.prod1, 'quantity': Decimal('-5.00'), 'unit_price': Decimal('50.00')}],
                user=self.superadmin
            )

        with self.assertRaises(ValidationError):
            SalesOrderService.create_order(
                customer=self.customer,
                source_warehouse=self.warehouse,
                order_date='2026-11-01',
                items_data=[{'product': self.prod1, 'quantity': Decimal('5.00'), 'unit_price': Decimal('50.00'), 'discount_percentage': Decimal('120.00')}],
                user=self.superadmin
            )

        with self.assertRaises(ValidationError):
            SalesOrderService.create_order(
                customer=self.customer,
                source_warehouse=self.warehouse,
                order_date='2026-11-01',
                items_data=[{'product': self.prod1, 'quantity': Decimal('5.00'), 'unit_price': Decimal('50.00')}],
                user=self.superadmin,
                shipping_fees=Decimal('-20.00')
            )


class SalesCollectionAndTerritoryScopingTests(TestCase):
    """Verifies collections linked to sales orders, overpayment guards, representative IDOR prevention, and manager scope."""

    def setUp(self):
        self.client = Client()

        self.rep_role, _ = Role.objects.get_or_create(
            name=Role.ROLE_REP,
            defaults={'display_name': 'مندوب مبيعات', 'is_sales_team': True, 'is_rep': True}
        )
        self.manager_role, _ = Role.objects.get_or_create(
            name=Role.ROLE_MANAGER,
            defaults={'display_name': 'مدير فرع', 'is_manager': True}
        )

        self.cairo_gov = Area.objects.create(code='CAI-SCOPE', name='القاهرة', area_type='governorate')
        self.alex_gov = Area.objects.create(code='ALX-SCOPE', name='الإسكندرية', area_type='governorate')

        self.manager_cairo = User.objects.create_user(
            username='mgr_cairo_scope',
            email='mgr_cairo_scope@wea.com',
            password='Password123!',
            role=self.manager_role
        )
        self.manager_cairo.assigned_areas.add(self.cairo_gov)

        self.rep_cairo = User.objects.create_user(
            username='rep_cairo_scope',
            email='rep_cairo_scope@wea.com',
            password='Password123!',
            role=self.rep_role
        )
        self.rep_cairo.assigned_areas.add(self.cairo_gov)

        self.rep_alex = User.objects.create_user(
            username='rep_alex_scope',
            email='rep_alex_scope@wea.com',
            password='Password123!',
            role=self.rep_role
        )
        self.rep_alex.assigned_areas.add(self.alex_gov)

        from accounts.services import ensure_representative_resources
        ensure_representative_resources(self.rep_cairo, create_warehouse=True)
        self.rep_cairo_warehouse = self.rep_cairo.get_default_warehouse()

        self.main_vault = Vault.objects.create(
            name='خزينة تحصيلات القاهرة',
            serial_num=9102,
            current_balance=Decimal('50000.00')
        )

        self.customer = Contact.objects.create(
            name='صيدلية مصر الجديدة الحديثة',
            is_customer=True,
            area=self.cairo_gov,
            created_by=self.rep_cairo
        )

        self.category = ProductCategory.objects.create(name='أدوية عامة', code='CAT-SC')
        self.product = Product.objects.create(
            name='باراسيتامول 500',
            sku_code='PARA-500-SC',
            retail_price=Decimal('50.00'),
            default_purchase_cost=Decimal('35.00'),
            category=self.category
        )

        InventoryStock.objects.create(
            warehouse=self.rep_cairo_warehouse,
            product=self.product,
            qty_on_hand=Decimal('100.00'),
            qty_reserved=Decimal('0.00'),
            product_cost=Decimal('35.00')
        )

    def test_sales_collection_linked_to_sales_order(self):
        due_date = datetime.date(2026, 11, 10)
        so = SalesOrderService.create_order(
            customer=self.customer,
            source_warehouse=self.rep_cairo_warehouse,
            order_date=timezone.now().date(),
            items_data=[{'product': self.product, 'quantity': 20, 'unit_price': Decimal('50.00')}],
            user=self.rep_cairo,
            due_date=due_date
        )
        self.assertEqual(so.grand_total, Decimal('1000.00'))
        self.assertEqual(so.outstanding_balance, Decimal('1000.00'))
        self.assertEqual(so.due_date, due_date)

        # Partial collection: 400 LE
        col = CollectionService.record_collection(
            customer=self.customer,
            vault=self.main_vault,
            amount=Decimal('400.00'),
            user=self.rep_cairo,
            sales_order=so,
            due_date=due_date,
            notes='دفعة نقدية'
        )
        so.refresh_from_db()
        self.assertEqual(so.total_paid, Decimal('400.00'))
        self.assertEqual(so.outstanding_balance, Decimal('600.00'))
        self.assertFalse(so.is_paid)

        # Overpayment rejected
        with self.assertRaises(ValidationError):
            CollectionService.record_collection(
                customer=self.customer,
                vault=self.main_vault,
                amount=Decimal('700.00'),
                user=self.rep_cairo,
                sales_order=so
            )

    def test_representative_cannot_access_other_representative_order(self):
        cairo_order = SalesOrderService.create_order(
            customer=self.customer,
            source_warehouse=self.rep_cairo_warehouse,
            order_date=timezone.now().date(),
            items_data=[{'product': self.product, 'quantity': 5, 'unit_price': Decimal('50.00')}],
            user=self.rep_cairo
        )

        self.client.force_login(self.rep_alex)
        detail_url = reverse('sales_order_detail', args=[cairo_order.pk])
        resp = self.client.get(detail_url)
        self.assertEqual(resp.status_code, 403)

    def test_manager_scoped_to_own_area_and_representatives(self):
        cairo_order = SalesOrderService.create_order(
            customer=self.customer,
            source_warehouse=self.rep_cairo_warehouse,
            order_date=timezone.now().date(),
            items_data=[{'product': self.product, 'quantity': 5, 'unit_price': Decimal('50.00')}],
            user=self.rep_cairo
        )

        self.client.force_login(self.manager_cairo)
        resp = self.client.get(reverse('sales_order_detail', args=[cairo_order.pk]))
        self.assertEqual(resp.status_code, 200)

    def test_sales_list_stats_respect_active_filters(self):
        SalesOrderService.create_order(
            customer=self.customer,
            source_warehouse=self.rep_cairo_warehouse,
            order_date=timezone.now().date(),
            items_data=[{'product': self.product, 'quantity': 2, 'unit_price': Decimal('50.00')}],
            user=self.rep_cairo
        )
        SalesOrderService.create_order(
            customer=self.customer,
            source_warehouse=self.rep_cairo_warehouse,
            order_date=timezone.now().date(),
            items_data=[{'product': self.product, 'quantity': 4, 'unit_price': Decimal('50.00')}],
            user=self.rep_cairo
        )
        CollectionService.record_collection(
            customer=self.customer,
            vault=self.main_vault,
            amount=Decimal('120.00'),
            user=self.rep_cairo
        )
        self.client.force_login(self.manager_cairo)
        res_filtered = self.client.get(reverse('sales_orders_list') + '?search=NOT_FOUND_XYZ')
        self.assertEqual(res_filtered.status_code, 200)
        self.assertEqual(res_filtered.context['stats']['total_orders'], 0)
        self.assertEqual(res_filtered.context['stats']['total_value'], Decimal('0.00'))

        res_col_filt = self.client.get(reverse('collections_list') + '?search=NOT_FOUND_XYZ')
        self.assertEqual(res_col_filt.status_code, 200)
        self.assertEqual(res_col_filt.context['stats']['total_count'], 0)
        self.assertEqual(res_col_filt.context['stats']['total_amount'], Decimal('0.00'))

        res_cust_filt = self.client.get(reverse('sales_customers_list') + '?search=NOT_FOUND_XYZ')
        self.assertEqual(res_cust_filt.status_code, 200)
        self.assertEqual(res_cust_filt.context['stats']['total_customers'], 0)

