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
from sales.models import SalesOrder, SalesOrderItem, Collection, CustomerAccount, SalesReturnOrder, SalesReturnOrderItem
from sales.services import SalesOrderService, CollectionService, SalesReturnOrderService

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


class SalesReturnOrderWorkflowTests(TestCase):
    """
    Comprehensive verification for SalesReturnOrder lifecycle:
    - Original order linkage and returnable quantity bounds (Returnable = Original - Returned)
    - Anti-self-approval enforcement
    - Resalable vs damaged stock handling in delivery
    - Credit balance adjustments in settlement
    - POST-only action views
    """

    def setUp(self):
        self.client = Client()
        self.cairo = Area.objects.create(name='القاهرة الكبرى', code='CAI-RET')
        self.nasr = Area.objects.create(name='مدينة نصر', code='NASR-RET', parent=self.cairo)

        self.rep_role = Role.objects.get(name=Role.ROLE_REP)
        self.mgr_role = Role.objects.get(name=Role.ROLE_MANAGER)
        self.acc_role = Role.objects.get(name=Role.ROLE_ACCOUNTANT)

        self.rep = User.objects.create_user(
            username='rep_sales_ret', email='rep_ret@wea.com', password='Password123!', role=self.rep_role
        )
        self.rep.assigned_areas.add(self.nasr)

        self.manager = User.objects.create_user(
            username='mgr_sales_ret', email='mgr_ret@wea.com', password='Password123!', role=self.mgr_role
        )
        self.manager.assigned_areas.add(self.cairo)

        self.accountant = User.objects.create_user(
            username='acc_sales_ret', email='acc_ret@wea.com', password='Password123!', role=self.acc_role
        )

        self.customer = Contact.objects.create(
            name='صيدلية السلامة', code='CUST-RET-01', is_customer=True, area=self.nasr, status='active'
        )
        self.cust_acc, _ = CustomerAccount.objects.get_or_create(
            customer=self.customer,
            defaults={'credit_limit': Decimal('100000.00'), 'current_balance': Decimal('0.00')}
        )

        self.wh = Warehouse.objects.create(name='مخزن القاهرة التجاري', code='WH-CAI-RET', is_active=True)
        self.cat = ProductCategory.objects.create(name='أدوية عامة', code='CAT-RET-01')
        self.product = Product.objects.create(
            name='كونجستال أقراص', sku_code='PRD-CONG-RET', category=self.cat, retail_price=Decimal('40.00'), default_purchase_cost=Decimal('25.00'), is_active=True, sellable=True
        )
        self.stock = InventoryStock.objects.create(warehouse=self.wh, product=self.product, qty_on_hand=Decimal('100.00'), product_cost=Decimal('25.00'))

        # Create original delivered sales order with 10 units
        self.original_order = SalesOrder.objects.create(
            customer=self.customer,
            source_warehouse=self.wh,
            status='delivered',
            grand_total=Decimal('400.00'),
            created_by=self.rep
        )
        self.order_item = SalesOrderItem.objects.create(
            order=self.original_order,
            product=self.product,
            quantity=10,
            unit_price=Decimal('40.00')
        )
        self.cust_acc.current_balance = Decimal('400.00')
        self.cust_acc.save()

    def test_sales_return_creation_and_quantity_limit(self):
        """Cannot return more than original delivered quantity."""
        # 1. Valid return of 4 units
        ret_order = SalesReturnOrderService.create_return_order(
            sales_order=self.original_order,
            destination_warehouse=self.wh,
            items_data=[{
                'sales_order_item_id': self.order_item.id,
                'quantity': 4,
                'unit_price': Decimal('40.00'),
                'is_damaged': False
            }],
            user=self.rep,
            reason='فائض عن حاجة العميل'
        )
        self.assertEqual(ret_order.status, 'pending')
        self.assertEqual(ret_order.grand_total, Decimal('160.00'))

        # 2. Return of remaining 6 units is allowed
        ret_order2 = SalesReturnOrderService.create_return_order(
            sales_order=self.original_order,
            destination_warehouse=self.wh,
            items_data=[{
                'sales_order_item_id': self.order_item.id,
                'quantity': 6,
                'unit_price': Decimal('40.00'),
                'is_damaged': False
            }],
            user=self.rep
        )
        self.assertIsNotNone(ret_order2)

        # 3. Third return of even 1 unit fails (already returned 4 + 6 = 10)
        with self.assertRaises(ValidationError):
            SalesReturnOrderService.create_return_order(
                sales_order=self.original_order,
                destination_warehouse=self.wh,
                items_data=[{
                    'sales_order_item_id': self.order_item.id,
                    'quantity': 1,
                    'unit_price': Decimal('40.00'),
                    'is_damaged': False
                }],
                user=self.rep
            )

    def test_sales_return_anti_self_approval(self):
        """User who created the return order cannot approve it."""
        ret_order = SalesReturnOrderService.create_return_order(
            sales_order=self.original_order,
            destination_warehouse=self.wh,
            items_data=[{
                'sales_order_item_id': self.order_item.id,
                'quantity': 2,
                'unit_price': Decimal('40.00'),
                'is_damaged': False
            }],
            user=self.rep
        )

        # Rep attempts self-approval -> raises ValidationError
        with self.assertRaises(ValidationError):
            SalesReturnOrderService.approve_return_order(ret_order, user=self.rep)

        # Manager approves -> success
        approved_order = SalesReturnOrderService.approve_return_order(ret_order, user=self.manager)
        self.assertEqual(approved_order.status, 'approved')

    def test_sales_return_delivery_and_restocking(self):
        """Delivering resalable return restocks inventory, damaged does not."""
        initial_stock_qty = self.stock.qty_on_hand

        ret_order = SalesReturnOrderService.create_return_order(
            sales_order=self.original_order,
            destination_warehouse=self.wh,
            items_data=[
                {'sales_order_item_id': self.order_item.id, 'quantity': 3, 'unit_price': Decimal('40.00'), 'is_damaged': False},
                {'sales_order_item_id': self.order_item.id, 'quantity': 2, 'unit_price': Decimal('40.00'), 'is_damaged': True},
            ],
            user=self.rep
        )
        SalesReturnOrderService.approve_return_order(ret_order, user=self.manager)
        delivered_order = SalesReturnOrderService.deliver_return_order(ret_order, user=self.manager)
        self.assertEqual(delivered_order.status, 'delivered')

        self.stock.refresh_from_db()
        # Only 3 resalable items added to stock
        self.assertEqual(self.stock.qty_on_hand, initial_stock_qty + Decimal('3.00'))

    def test_sales_return_settlement_updates_customer_balance(self):
        """Settling delivered return order reduces customer outstanding balance."""
        ret_order = SalesReturnOrderService.create_return_order(
            sales_order=self.original_order,
            destination_warehouse=self.wh,
            items_data=[
                {'sales_order_item_id': self.order_item.id, 'quantity': 2, 'unit_price': Decimal('40.00'), 'is_damaged': False},
            ],
            user=self.rep
        )
        SalesReturnOrderService.approve_return_order(ret_order, user=self.manager)
        SalesReturnOrderService.deliver_return_order(ret_order, user=self.manager)

        initial_bal = self.cust_acc.current_balance  # 400.00
        settled_order = SalesReturnOrderService.settle_return_order(ret_order, user=self.accountant)
        self.assertEqual(settled_order.status, 'settled')

        self.cust_acc.refresh_from_db()
        # 400.00 - 80.00 (2 * 40.00) = 320.00
        self.assertEqual(self.cust_acc.current_balance, initial_bal - Decimal('80.00'))

    def test_sales_return_views_post_only_actions(self):
        """Action views (approve, reject, cancel, deliver, settle) reject GET and require POST."""
        ret_order = SalesReturnOrderService.create_return_order(
            sales_order=self.original_order,
            destination_warehouse=self.wh,
            items_data=[
                {'sales_order_item_id': self.order_item.id, 'quantity': 1, 'unit_price': Decimal('40.00'), 'is_damaged': False},
            ],
            user=self.rep
        )
        self.client.force_login(self.manager)

        # GET request on action endpoint should redirect (reject GET mutation)
        get_resp = self.client.get(reverse('sales_return_order_action', args=[ret_order.pk, 'approve']))
        self.assertEqual(get_resp.status_code, 302)
        ret_order.refresh_from_db()
        self.assertEqual(ret_order.status, 'pending')

        # POST request succeeds
        post_resp = self.client.post(reverse('sales_return_order_action', args=[ret_order.pk, 'approve']))
        self.assertEqual(post_resp.status_code, 302)
        ret_order.refresh_from_db()
        self.assertEqual(ret_order.status, 'approved')


class SalesCustomerScopingAndSmartSearchTests(TestCase):
    """Covers Task Two (Sales customer selection fix) and Task Three (Smart search & scoping)."""

    def setUp(self):
        from django.core.management import call_command
        from accounts.scope_service import ScopeResolutionService

        call_command('setup_permissions')
        self.ScopeResolutionService = ScopeResolutionService

        self.role_super = Role.objects.get(name='superadmin')
        self.role_manager = Role.objects.get(name='manager')
        self.role_accountant = Role.objects.get(name='accountant')
        self.role_rep = Role.objects.get(name='rep')

        self.cairo = Area.objects.create(code='SC-CAI', name='محافظة القاهرة', area_type='governorate')
        self.nasr = Area.objects.create(code='SC-NASR', name='مدينة نصر', area_type='subarea', parent=self.cairo)
        self.maadi = Area.objects.create(code='SC-MAADI', name='المعادي', area_type='subarea', parent=self.cairo)
        self.giza = Area.objects.create(code='SC-GIZ', name='محافظة الجيزة', area_type='governorate')
        self.dokki = Area.objects.create(code='SC-DOK', name='الدقي', area_type='subarea', parent=self.giza)

        self.superadmin = User.objects.create_superuser(
            username='sc_super@wea.com', email='sc_super@wea.com', password='Password123!', role=self.role_super
        )
        self.accountant = User.objects.create_user(
            username='sc_acc@wea.com', email='sc_acc@wea.com', password='Password123!', role=self.role_accountant
        )
        self.mgr_cairo = User.objects.create_user(
            username='sc_mgr_cai@wea.com', email='sc_mgr_cai@wea.com', password='Password123!', role=self.role_manager
        )
        self.mgr_cairo.assigned_areas.add(self.cairo)

        self.rep_nasr = User.objects.create_user(
            username='sc_rep_nasr@wea.com', email='sc_rep_nasr@wea.com', password='Password123!', role=self.role_rep
        )
        self.rep_nasr.assigned_areas.add(self.nasr)

        self.rep_gov_only = User.objects.create_user(
            username='sc_rep_gov@wea.com', email='sc_rep_gov@wea.com', password='Password123!', role=self.role_rep
        )
        self.rep_gov_only.assigned_areas.add(self.cairo)

        # Migrated status='customer' + status='active' + status='inactive' + supplier-only
        self.c_nasr = Contact.objects.create(
            serial_num=70001, name='أحمد فرع نصر', is_customer=True, status='customer',
            area=self.cairo, brick=self.nasr, code='CN1', created_by=self.superadmin
        )
        self.c_maadi = Contact.objects.create(
            serial_num=70002, name='صيدلية المعادي النشطة', is_customer=True, status='active',
            area=self.cairo, brick=self.maadi, code='CM1', created_by=self.superadmin
        )
        self.c_dokki = Contact.objects.create(
            serial_num=70003, name='عيادة الدقي بالجيزة', is_customer=True, status='customer',
            area=self.giza, brick=self.dokki, code='CD1', created_by=self.superadmin
        )
        self.c_inactive = Contact.objects.create(
            serial_num=70004, name='عميل موقوف نصر', is_customer=True, status='inactive',
            area=self.cairo, brick=self.nasr, created_by=self.superadmin
        )
        self.supplier_only = Contact.objects.create(
            serial_num=70005, name='مورد خامات فقط', is_customer=False, is_supplier=True, status='customer',
            area=self.cairo, brick=self.nasr, created_by=self.superadmin
        )

        self.wh_cairo = Warehouse.objects.create(name='مخزن القاهرة الرئيسي', code='WH-SC-CAI', area=self.cairo, is_main=True)
        self.wh_nasr = Warehouse.objects.create(name='مخزن عهدة نصر', code='WH-SC-NASR', area=self.nasr, assigned_user=self.rep_nasr, is_rep_warehouse=True)
        self.wh_giza = Warehouse.objects.create(name='مخزن الجيزة', code='WH-SC-GIZ', area=self.giza)

        self.vault_nasr = Vault.objects.create(serial_num=7101, name='خزنة نصر', assigned_user=self.rep_nasr, is_rep_vault=True, area=self.nasr)
        self.vault_other = Vault.objects.create(serial_num=7102, name='خزنة الجيزة', assigned_user=self.mgr_cairo, area=self.giza)

        self.cat = ProductCategory.objects.create(name='أدوية عامة')
        self.product = Product.objects.create(
            name='منتج اختبار مبيعات',
            sku_code='PRD-SC-1',
            category=self.cat,
            retail_price=Decimal('50.00'),
            default_purchase_cost=Decimal('30.00'),
        )
        InventoryStock.objects.create(warehouse=self.wh_nasr, product=self.product, qty_on_hand=Decimal('100.00'))
        InventoryStock.objects.create(warehouse=self.wh_cairo, product=self.product, qty_on_hand=Decimal('100.00'))

    def test_scoped_customer_choices_include_migrated_customer_status(self):
        # SuperAdmin & Accountant see active + customer across regions, never inactive or non-customer
        for u in (self.superadmin, self.accountant):
            ids = set(self.ScopeResolutionService.get_scoped_choices(u, 'customers', 'sales').values_list('id', flat=True))
            self.assertEqual(ids, {self.c_nasr.id, self.c_maadi.id, self.c_dokki.id})

        # Cairo Manager sees all bricks inside Cairo, never Giza
        mgr_ids = set(self.ScopeResolutionService.get_scoped_choices(self.mgr_cairo, 'customers', 'sales').values_list('id', flat=True))
        self.assertEqual(mgr_ids, {self.c_nasr.id, self.c_maadi.id})

        # Explicit brick rep sees ONLY Nasr City
        rep_ids = set(self.ScopeResolutionService.get_scoped_choices(self.rep_nasr, 'customers', 'sales').values_list('id', flat=True))
        self.assertEqual(rep_ids, {self.c_nasr.id})

        # Root-governorate rep (migrated pattern) resolves child bricks within Cairo, never Giza
        gov_rep_ids = set(self.ScopeResolutionService.get_scoped_choices(self.rep_gov_only, 'customers', 'sales').values_list('id', flat=True))
        self.assertEqual(gov_rep_ids, {self.c_nasr.id, self.c_maadi.id})

    def test_sales_order_create_and_search_apis_scoping_and_idor(self):
        # Rep sees Nasr customer on create form & search API with Arabic normalization
        self.client.force_login(self.rep_nasr)
        resp = self.client.get(reverse('sales_order_create'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'أحمد فرع نصر')
        self.assertNotContains(resp, 'عيادة الدقي بالجيزة')
        self.assertContains(resp, 'data-smart-select="true"')

        # Search 'احمد' (no hamza) finds 'أحمد فرع نصر' via normalized API
        search_resp = self.client.get(reverse('sales_customers_search_api') + '?q=احمد')
        self.assertEqual(search_resp.status_code, 200)
        ids = [r['id'] for r in search_resp.json()['results']]
        self.assertEqual(ids, [self.c_nasr.id])

        # Searching Giza customer returns empty for Nasr rep
        giza_search = self.client.get(reverse('sales_customers_search_api') + '?q=الدقي')
        self.assertEqual(giza_search.status_code, 200)
        self.assertEqual(giza_search.json()['results'], [])

        # POST IDOR: rep cannot create order for out-of-scope Giza customer -> 403
        forged_cust_resp = self.client.post(reverse('sales_order_create'), {
            'customer': self.c_dokki.id,
            'warehouse': self.wh_nasr.id,
            'order_date': '2026-11-16',
            'product_id[]': [self.product.id],
            'quantity[]': ['1'],
            'unit_price[]': ['50.00'],
        })
        self.assertEqual(forged_cust_resp.status_code, 403)

        # POST IDOR: rep cannot forge Giza warehouse even when rep_wh exists -> 403
        forged_wh_resp = self.client.post(reverse('sales_order_create'), {
            'customer': self.c_nasr.id,
            'warehouse': self.wh_giza.id,
            'order_date': '2026-11-16',
            'product_id[]': [self.product.id],
            'quantity[]': ['1'],
            'unit_price[]': ['50.00'],
        })
        self.assertEqual(forged_wh_resp.status_code, 403)

        # POST validation: rejects supplier-only or inactive contact
        before_count = SalesOrder.objects.count()
        bad_contact_resp = self.client.post(reverse('sales_order_create'), {
            'customer': self.supplier_only.id,
            'warehouse': self.wh_nasr.id,
            'order_date': '2026-11-16',
            'product_id[]': [self.product.id],
            'quantity[]': ['1'],
            'unit_price[]': ['50.00'],
        })
        self.assertEqual(bad_contact_resp.status_code, 302)
        self.assertEqual(SalesOrder.objects.count(), before_count)

        # Rep CAN collect into own assigned custody vault
        col_resp = self.client.post(reverse('collection_create'), {
            'customer': self.c_nasr.id,
            'vault': self.vault_nasr.id,
            'amount': '100.00',
            'payment_method': 'cash',
        })
        self.assertEqual(col_resp.status_code, 302)
        self.assertTrue(Collection.objects.filter(customer=self.c_nasr, vault=self.vault_nasr).exists())

        # Rep CANNOT collect into another vault -> 403
        bad_col_resp = self.client.post(reverse('collection_create'), {
            'customer': self.c_nasr.id,
            'vault': self.vault_other.id,
            'amount': '50.00',
            'payment_method': 'cash',
        })
        self.assertEqual(bad_col_resp.status_code, 403)

    def test_edit_preserves_selected_customer_beyond_alphabetical_cap(self):
        # Create order for 'ى...' style contact alphabetically late and ensure edit includes it
        late_cust = Contact.objects.create(
            serial_num=70099, name='ياسمين فارما الأخير', is_customer=True, status='customer',
            area=self.cairo, brick=self.nasr, created_by=self.superadmin
        )
        order = SalesOrderService.create_order(
            customer=late_cust,
            source_warehouse=self.wh_cairo,
            order_date=datetime.date(2026, 11, 16),
            items_data=[{'product': self.product, 'quantity': Decimal('2'), 'unit_price': Decimal('50.00')}],
            user=self.superadmin,
        )
        # Create 105 extra contacts alphabetically earlier than 'ياسمين'
        bulk = [
            Contact(serial_num=75000 + i, name=f'أأ عميل اختبار {i:03d}', is_customer=True, status='customer', area=self.cairo, brick=self.nasr)
            for i in range(105)
        ]
        Contact.objects.bulk_create(bulk)

        self.client.force_login(self.superadmin)
        edit_resp = self.client.get(reverse('sales_order_edit', args=[order.pk]))
        self.assertEqual(edit_resp.status_code, 200)
        self.assertContains(edit_resp, late_cust.name)

        # Smart search finds late customer remotely
        wh_api = self.client.get(reverse('sales_warehouses_search_api') + '?q=القاهره')
        self.assertEqual(wh_api.status_code, 200)
        self.assertTrue(any(w['id'] == self.wh_cairo.id for w in wh_api.json()['results']))



