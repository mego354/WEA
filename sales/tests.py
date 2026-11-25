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
        from master_data.models import SalesSettings
        ss = SalesSettings.get_settings()
        ss.require_manager_approval = False
        ss.save()
        items_data = [{'product': self.product, 'quantity': Decimal('5.00'), 'unit_price': Decimal('25.00')}]
        order = SalesOrderService.create_order(
            customer=self.customer,
            source_warehouse=self.rep_wh,
            order_date=None,
            items_data=items_data,
            user=self.rep_cairo
        )
        self.assertEqual(order.source_warehouse, self.rep_wh)
        self.assertEqual(order.status, 'invoiced')

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
        order.status = 'pending'
        order.save()

        # Rep cannot approve own sale (anti-self-approval)
        with self.assertRaises(ValidationError):
            SalesOrderService.approve_order(order, self.rep_cairo)

        # Alex manager cannot approve Cairo sale
        with self.assertRaises(ValidationError) as ctx:
            SalesOrderService.approve_order(order, self.mgr_alex)
        self.assertIn("خارج نطاق منطقتك الرئيسية", str(ctx.exception))

        # Cairo manager CAN approve (streamlined workflow dispatches stock, debits customer ledger, and transitions to invoiced)
        approved_order = SalesOrderService.approve_order(order, self.mgr_cairo, notes='معتمد من مدير القاهرة')
        self.assertEqual(approved_order.status, 'invoiced')
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

        # Account-level Single Source of Truth: collections are NOT capped by independent per-order debt
        # and never auto-modify manual SalesOrder.payment_status.
        col2 = CollectionService.record_collection(
            customer=self.customer,
            vault=self.main_vault,
            amount=Decimal('700.00'),
            user=self.rep_cairo,
            sales_order=so
        )
        self.assertEqual(col2.amount, Decimal('700.00'))
        so.refresh_from_db()
        self.assertEqual(so.payment_status, 'credit')

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
        self.assertEqual(res_cust_filt.status_code, 302)
        self.assertIn('relation=customer', res_cust_filt['Location'])
        self.assertIn('search=NOT_FOUND_XYZ', res_cust_filt['Location'])
        res_cust_followed = self.client.get(res_cust_filt['Location'])
        self.assertEqual(res_cust_followed.status_code, 200)
        self.assertEqual(res_cust_followed.context['stats']['total_customers'], 0)


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
            name='صيدلية السلامة', code='CUST-RET-01', is_customer=True, area=self.nasr, status='customer'
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
        self.assertEqual(ret_order.status, 'settled')
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
        ret_order.status = 'pending'
        ret_order.save()

        # Rep attempts self-approval -> raises ValidationError
        with self.assertRaises(ValidationError):
            SalesReturnOrderService.approve_return_order(ret_order, user=self.rep)

        # Manager approves -> automatically settles stock & ledger
        approved_order = SalesReturnOrderService.approve_return_order(ret_order, user=self.manager)
        self.assertEqual(approved_order.status, 'settled')

    def test_sales_return_delivery_and_restocking(self):
        """Creating sales return immediately restocks resalable items, damaged does not."""
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
        self.assertEqual(ret_order.status, 'settled')

        self.stock.refresh_from_db()
        # Only 3 resalable items added to stock
        self.assertEqual(self.stock.qty_on_hand, initial_stock_qty + Decimal('3.00'))

    def test_sales_return_settlement_updates_customer_balance(self):
        """Settling delivered return order reduces customer outstanding balance."""
        initial_bal = self.cust_acc.current_balance  # 400.00
        ret_order = SalesReturnOrderService.create_return_order(
            sales_order=self.original_order,
            destination_warehouse=self.wh,
            items_data=[
                {'sales_order_item_id': self.order_item.id, 'quantity': 2, 'unit_price': Decimal('40.00'), 'is_damaged': False},
            ],
            user=self.rep
        )
        self.assertEqual(ret_order.status, 'settled')

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
        ret_order.status = 'pending'
        ret_order.save()
        self.client.force_login(self.manager)

        # GET request on action endpoint should redirect (reject GET mutation)
        get_resp = self.client.get(reverse('sales_return_order_action', args=[ret_order.pk, 'approve']))
        self.assertEqual(get_resp.status_code, 302)
        ret_order.refresh_from_db()
        self.assertEqual(ret_order.status, 'pending')

        # POST request succeeds -> automatically settles return
        post_resp = self.client.post(reverse('sales_return_order_action', args=[ret_order.pk, 'approve']))
        self.assertEqual(post_resp.status_code, 302)
        ret_order.refresh_from_db()
        self.assertEqual(ret_order.status, 'settled')


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
            serial_num=70002, name='صيدلية المعادي النشطة', is_customer=True, status='customer',
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

        # POST validation: rejects supplier-only or inactive contact (form error recovery preserves data with 200)
        before_count = SalesOrder.objects.count()
        bad_contact_resp = self.client.post(reverse('sales_order_create'), {
            'customer': self.supplier_only.id,
            'warehouse': self.wh_nasr.id,
            'order_date': '2026-11-16',
            'product_id[]': [self.product.id],
            'quantity[]': ['1'],
            'unit_price[]': ['50.00'],
        })
        self.assertEqual(bad_contact_resp.status_code, 200)
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


class CustomerAccountsTransactionsScopeAndCollectionsPerfTests(TestCase):
    """Verifies RBAC, data scope, IDOR, exports for customer accounts/transactions, and collections/create performance."""

    def setUp(self):
        from django.core.management import call_command
        from accounts.models import RoleModuleScope
        from django.contrib.auth.models import Permission

        call_command('setup_permissions')
        self.Permission = Permission

        self.role_super = Role.objects.get(name='superadmin')
        self.role_manager = Role.objects.get(name='manager')
        self.role_accountant = Role.objects.get(name='accountant')
        self.role_rep = Role.objects.get(name='rep')
        self.role_med_rep = Role.objects.get(name='medical_rep')

        self.cairo = Area.objects.create(code='CAT-CAI', name='القاهرة الكبرى', area_type='governorate')
        self.nasr = Area.objects.create(code='CAT-NASR', name='مدينة نصر', area_type='subarea', parent=self.cairo)
        self.maadi = Area.objects.create(code='CAT-MAADI', name='المعادي', area_type='subarea', parent=self.cairo)
        self.giza = Area.objects.create(code='CAT-GIZ', name='الجيزة', area_type='governorate')
        self.dokki = Area.objects.create(code='CAT-DOK', name='الدقي', area_type='subarea', parent=self.giza)

        self.superadmin = User.objects.create_superuser(
            username='cat_super@wea.com', email='cat_super@wea.com', password='Password123!', role=self.role_super
        )
        self.accountant = User.objects.create_user(
            username='cat_acc@wea.com', email='cat_acc@wea.com', password='Password123!', role=self.role_accountant
        )
        self.mgr_cairo = User.objects.create_user(
            username='cat_mgr_cai@wea.com', email='cat_mgr_cai@wea.com', password='Password123!', role=self.role_manager
        )
        self.mgr_cairo.assigned_areas.add(self.cairo)

        self.mgr_giza = User.objects.create_user(
            username='cat_mgr_giz@wea.com', email='cat_mgr_giz@wea.com', password='Password123!', role=self.role_manager
        )
        self.mgr_giza.assigned_areas.add(self.giza)

        self.mgr_unassigned = User.objects.create_user(
            username='cat_mgr_none@wea.com', email='cat_mgr_none@wea.com', password='Password123!', role=self.role_manager
        )

        self.rep_nasr = User.objects.create_user(
            username='cat_rep_nasr@wea.com', email='cat_rep_nasr@wea.com', password='Password123!', role=self.role_rep
        )
        self.rep_nasr.assigned_areas.add(self.nasr)

        self.rep_maadi = User.objects.create_user(
            username='cat_rep_maadi@wea.com', email='cat_rep_maadi@wea.com', password='Password123!', role=self.role_rep
        )
        self.rep_maadi.assigned_areas.add(self.maadi)

        self.med_rep = User.objects.create_user(
            username='cat_med_rep@wea.com', email='cat_med_rep@wea.com', password='Password123!', role=self.role_med_rep
        )
        self.med_rep.assigned_areas.add(self.nasr)

        # Brick-scoped sales reviewer role to verify BRICK scope explicitly
        self.brick_viewer_role = Role.objects.create(name='BrickSalesViewer', display_name='مراجع خط', is_active=True)
        self.brick_viewer_role.permissions.set(Permission.objects.filter(codename__in=[
            'module:sales', 'sales:customers/accounting', 'sales:customers/transactions',
        ]))
        RoleModuleScope.objects.update_or_create(
            role=self.brick_viewer_role, module='sales', defaults={'view_scope': 'brick', 'manage_scope': 'own'}
        )
        self.brick_viewer = User.objects.create_user(
            username='cat_brick_v@wea.com', email='cat_brick_v@wea.com', password='Password123!', role=self.brick_viewer_role
        )
        self.brick_viewer.assigned_areas.add(self.nasr)

        # Customers & Accounts across Nasr (rep_nasr), Maadi (rep_maadi), Dokki (Giza)
        self.c_nasr = Contact.objects.create(
            serial_num=95001, name='صيدلية النصر المميزة', is_customer=True, status='customer',
            area=self.cairo, brick=self.nasr, created_by=self.rep_nasr
        )
        self.c_maadi = Contact.objects.create(
            serial_num=95002, name='صيدلية المعادي المتحدة', is_customer=True, status='customer',
            area=self.cairo, brick=self.maadi, created_by=self.rep_maadi
        )
        self.c_dokki = Contact.objects.create(
            serial_num=95003, name='صيدلية الدقي الكبرى', is_customer=True, status='customer',
            area=self.giza, brick=self.dokki, created_by=self.superadmin
        )

        self.acc_nasr, _ = CustomerAccount.objects.get_or_create(customer=self.c_nasr)
        self.acc_nasr.current_balance = Decimal('1000.00')
        self.acc_nasr.save()

        self.acc_maadi, _ = CustomerAccount.objects.get_or_create(customer=self.c_maadi)
        self.acc_maadi.current_balance = Decimal('2500.00')
        self.acc_maadi.save()

        self.acc_dokki, _ = CustomerAccount.objects.get_or_create(customer=self.c_dokki)
        self.acc_dokki.current_balance = Decimal('9000.00')
        self.acc_dokki.save()

        from sales.models import CustomerTransaction
        self.tx_nasr = CustomerTransaction.objects.create(
            serial=96001, account=self.acc_nasr, transaction_type='debit', reason='sales',
            debit=Decimal('1000.00'), running_balance=Decimal('1000.00'),
            description='فاتورة مبيعات النصر', created_by=self.rep_nasr
        )
        self.tx_maadi = CustomerTransaction.objects.create(
            serial=96002, account=self.acc_maadi, transaction_type='debit', reason='sales',
            debit=Decimal('2500.00'), running_balance=Decimal('2500.00'),
            description='فاتورة مبيعات المعادي', created_by=self.rep_maadi
        )
        self.tx_dokki = CustomerTransaction.objects.create(
            serial=96003, account=self.acc_dokki, transaction_type='debit', reason='sales',
            debit=Decimal('9000.00'), running_balance=Decimal('9000.00'),
            description='فاتورة مبيعات الدقي', created_by=self.superadmin
        )

        self.wh_cairo = Warehouse.objects.create(name='مخزن تحصيل القاهرة', code='WH-PERF-CAI', area=self.cairo, is_main=True)
        self.vault_nasr = Vault.objects.create(serial_num=9701, name='عهدة مندوب نصر', assigned_user=self.rep_nasr, is_rep_vault=True, area=self.nasr)
        self.cat = ProductCategory.objects.create(name='فئة تحصيل')
        self.product = Product.objects.create(
            name='صنف تحصيل سريع', sku_code='PRD-COL-PERF', category=self.cat,
            retail_price=Decimal('100.00'), default_purchase_cost=Decimal('60.00')
        )

    def test_customer_accounts_and_transactions_rbac_and_all_scopes(self):
        # 1. Unprivileged user without sales accounting permissions is denied 403 on accounts, transactions, exports, and root aliases
        unprivileged = User.objects.create_user(username='sales_unprivileged@wea.com', password='Password123!', role=None)
        self.client.force_login(unprivileged)
        for route in (
            reverse('accounting_customers_list'),
            reverse('accounting_customers_export'),
            reverse('customer_transactions_list'),
            reverse('customer_transactions_export'),
            '/sales/accounting/customers/',
            '/accounting/customers/',
            '/accounting/customer-transactions/',
        ):
            resp = self.client.get(route)
            self.assertEqual(resp.status_code, 403, f"Expected 403 for {unprivileged.username} on {route}")

        # 2. Role permissions separate page view from Excel export, and enforce OWN sales scope
        self.rep_nasr.role.permissions.set(self.Permission.objects.filter(codename__in=[
            'module:sales', 'sales:customers/accounting', 'sales:customers/transactions'
        ]))
        self.rep_nasr.clear_perm_cache()

        self.client.force_login(self.rep_nasr)
        acc_resp = self.client.get(reverse('accounting_customers_list'))
        self.assertEqual(acc_resp.status_code, 200)
        self.assertContains(acc_resp, self.c_nasr.name)
        self.assertNotContains(acc_resp, self.c_maadi.name)
        self.assertNotContains(acc_resp, self.c_dokki.name)
        self.assertEqual(acc_resp.context['stats']['total_receivable'], Decimal('1000.00'))

        # Direct URL query param tampering (?customer_id=<dokki>) does NOT reveal Giza customer name or balance
        idor_acc = self.client.get(reverse('accounting_customers_list') + f'?customer_id={self.c_dokki.id}')
        self.assertEqual(idor_acc.status_code, 200)
        self.assertNotContains(idor_acc, self.c_dokki.name)
        self.assertEqual(idor_acc.context['stats']['total_receivable'], Decimal('0.00'))

        tx_resp = self.client.get(reverse('customer_transactions_list'))
        self.assertEqual(tx_resp.status_code, 200)
        self.assertContains(tx_resp, 'فاتورة مبيعات النصر')
        self.assertNotContains(tx_resp, 'فاتورة مبيعات المعادي')
        self.assertNotContains(tx_resp, 'فاتورة مبيعات الدقي')

        # Still denied exports without export permissions
        self.assertEqual(self.client.get(reverse('accounting_customers_export')).status_code, 403)
        self.assertEqual(self.client.get(reverse('customer_transactions_export')).status_code, 403)

        # Search API with scope_model=customeraccount obeys OWN scope (not broader contacts brick scope)
        api_maadi = self.client.get(reverse('sales_customers_search_api') + '?scope_model=customeraccount&q=المعادي')
        self.assertEqual(api_maadi.status_code, 200)
        self.assertEqual(api_maadi.json()['results'], [])

        # 3. BRICK scope sees Nasr City brick customer, never Maadi or Giza
        self.client.force_login(self.brick_viewer)
        brick_resp = self.client.get(reverse('accounting_customers_list'))
        self.assertEqual(brick_resp.status_code, 200)
        self.assertContains(brick_resp, self.c_nasr.name)
        self.assertNotContains(brick_resp, self.c_maadi.name)
        self.assertNotContains(brick_resp, self.c_dokki.name)

        # 4. AREA scope (Cairo Manager sees Nasr + Maadi = 3500, never Dokki = 9000; unassigned Manager fails closed)
        self.client.force_login(self.mgr_cairo)
        mgr_acc = self.client.get(reverse('accounting_customers_list'))
        self.assertEqual(mgr_acc.status_code, 200)
        self.assertContains(mgr_acc, self.c_nasr.name)
        self.assertContains(mgr_acc, self.c_maadi.name)
        self.assertNotContains(mgr_acc, self.c_dokki.name)
        self.assertEqual(mgr_acc.context['stats']['total_receivable'], Decimal('3500.00'))

        # Scoped Excel export succeeds and contains only Cairo rows
        exp_acc = self.client.get(reverse('accounting_customers_export'))
        self.assertEqual(exp_acc.status_code, 200)
        wb = openpyxl.load_workbook(io.BytesIO(exp_acc.content))
        sheet_text = ' '.join(str(cell.value or '') for row in wb.active.iter_rows() for cell in row)
        self.assertIn(self.c_nasr.name, sheet_text)
        self.assertIn(self.c_maadi.name, sheet_text)
        self.assertNotIn(self.c_dokki.name, sheet_text)

        exp_tx = self.client.get(reverse('customer_transactions_export'))
        self.assertEqual(exp_tx.status_code, 200)

        self.client.force_login(self.mgr_unassigned)
        unassigned_resp = self.client.get(reverse('accounting_customers_list'))
        self.assertEqual(unassigned_resp.status_code, 200)
        self.assertEqual(unassigned_resp.context['stats']['total_customers'], 0)

        # 5. ALL scope (Accountant & SuperAdmin see all regions: 12,500)
        for u in (self.accountant, self.superadmin):
            self.client.force_login(u)
            all_acc = self.client.get(reverse('accounting_customers_list'))
            self.assertEqual(all_acc.status_code, 200)
            self.assertEqual(all_acc.context['stats']['total_receivable'], Decimal('12500.00'))

    def test_collections_create_constant_query_performance_and_order_search_api(self):
        from django.test.utils import CaptureQueriesContext
        from django.db import connection
        from accounts.models import SecurityAuditLog
        from sales.models import CustomerTransaction

        # Create 30 open SalesOrders across Cairo and Giza to verify O(1) query count on collections/create/
        created_orders = []
        for i in range(30):
            cust = self.c_nasr if i % 2 == 0 else self.c_dokki
            owner = self.rep_nasr if i % 2 == 0 else self.superadmin
            so = SalesOrder.objects.create(
                customer=cust,
                source_warehouse=self.wh_cairo,
                status='invoiced',
                order_date=datetime.date(2026, 11, 15),
                grand_total=Decimal('400.00'),
                created_by=owner,
            )
            created_orders.append(so)

        self.client.force_login(self.superadmin)
        with CaptureQueriesContext(connection) as ctx:
            resp = self.client.get(reverse('collection_create'))
        self.assertEqual(resp.status_code, 200)
        self.assertLessEqual(len(ctx.captured_queries), 15, f"Expected <=15 queries, got {len(ctx.captured_queries)}")

        # Customer-filtered async order API returns only unpaid orders for c_nasr, in <= 10 queries
        with CaptureQueriesContext(connection) as api_ctx:
            api_resp = self.client.get(reverse('sales_orders_search_api') + f'?customer={self.c_nasr.id}')
        self.assertEqual(api_resp.status_code, 200)
        self.assertLessEqual(len(api_ctx.captured_queries), 10)
        payload = api_resp.json()
        self.assertEqual(payload['count'], 15)
        self.assertTrue(all(item['customer_id'] == self.c_nasr.id for item in payload['results']))

        # Scoping: rep_nasr cannot query c_dokki orders via sales_orders_search_api
        self.client.force_login(self.rep_nasr)
        rep_dokki_api = self.client.get(reverse('sales_orders_search_api') + f'?customer={self.c_dokki.id}')
        self.assertEqual(rep_dokki_api.status_code, 200)
        self.assertEqual(rep_dokki_api.json()['results'], [])

        # End-to-end collection creation linked to a SalesOrder updates balances, ledger, vault & audit log
        target_order = created_orders[0]  # c_nasr, created by rep_nasr, grand_total=400.00
        self.vault_nasr.refresh_from_db()
        before_vault = Decimal(str(self.vault_nasr.current_balance))
        before_acc = Decimal(str(CustomerAccount.objects.get(customer=self.c_nasr).current_balance))
        post_resp = self.client.post(reverse('collection_create'), {
            'customer': self.c_nasr.id,
            'sales_order': target_order.id,
            'vault': self.vault_nasr.id,
            'amount': '150.00',
            'payment_method': 'cash',
            'collection_date': '2026-11-16',
        })
        self.assertEqual(post_resp.status_code, 302)

        self.vault_nasr.refresh_from_db()
        self.acc_nasr.refresh_from_db()
        target_order.refresh_from_db()
        self.assertEqual(self.vault_nasr.current_balance, before_vault + Decimal('150.00'))
        self.assertEqual(self.acc_nasr.current_balance, before_acc - Decimal('150.00'))
        self.assertEqual(target_order.outstanding_balance, Decimal('250.00'))
        self.assertTrue(CustomerTransaction.objects.filter(account=self.acc_nasr, credit=Decimal('150.00')).exists())
        self.assertTrue(SecurityAuditLog.objects.filter(action_type='COLLECTION_CREATED', actor=self.rep_nasr).exists())


class SalesPhase2ImprovementsTests(TestCase):
    """
    Verifies Phase 2 architectural improvements in Sales:
    1. Automated order fulfillment upon approval (atomic stock deduction, outward memo, ledger debit, invoiced status)
    2. Over-selling prevention & stock validation
    3. Payment status management (credit/partial/paid/returned) and permission gating
    4. Form error recovery preserving user input and dynamic items
    5. Sales order return details API robustness
    """

    def setUp(self):
        from django.core.management import call_command
        call_command('setup_permissions')

        self.cairo = Area.objects.create(code='P2-CAI', name='محافظة القاهرة', area_type='governorate')
        self.nasr = Area.objects.create(code='P2-NC', name='مدينة نصر', area_type='subarea', parent=self.cairo)

        self.role_super = Role.objects.get(name='superadmin')
        self.role_manager = Role.objects.get(name='manager')
        self.role_accountant = Role.objects.get(name='accountant')
        self.role_rep = Role.objects.get(name='rep')

        self.superadmin = User.objects.create_superuser(username='p2_super', email='p2_super@test.com', password='pass')
        self.manager = User.objects.create_user(username='p2_mgr', role=self.role_manager, is_staff=True)
        self.manager.assigned_areas.add(self.cairo)
        self.accountant = User.objects.create_user(username='p2_acc', role=self.role_accountant, is_staff=True)
        self.rep = User.objects.create_user(username='p2_rep', role=self.role_rep, is_staff=True)
        self.rep.assigned_areas.add(self.nasr)

        self.cat = ProductCategory.objects.create(name='أدوية عامة', code='P2-GEN')
        self.prod = Product.objects.create(
            name='أوجمنتين 1 جم',
            sku_code='AUG-1G',
            retail_price=Decimal('120.00'),
            default_purchase_cost=Decimal('80.00'),
            category=self.cat,
            sellable=True
        )

        self.wh = Warehouse.objects.create(
            name='مخزن القاهرة الرئيسي',
            code='P2-WH-CAI',
            area=self.cairo,
            is_main=True
        )

        from accounts.services import get_representative_warehouse
        self.wh_rep = get_representative_warehouse(self.rep)
        if not self.wh_rep:
            self.wh_rep = Warehouse.objects.create(
                name='مخزن عهدة مندوب نصر',
                code='P2-WH-REP',
                area=self.nasr,
                is_rep_warehouse=True,
                assigned_user=self.rep
            )

        self.stock = InventoryStock.objects.create(
            warehouse=self.wh,
            product=self.prod,
            qty_on_hand=Decimal('100.00'),
            qty_reserved=Decimal('0.00'),
            product_cost=Decimal('80.00')
        )

        self.stock_rep = InventoryStock.objects.create(
            warehouse=self.wh_rep,
            product=self.prod,
            qty_on_hand=Decimal('100.00'),
            qty_reserved=Decimal('0.00'),
            product_cost=Decimal('80.00')
        )

        self.customer = Contact.objects.create(
            serial_num=99001,
            name='صيدلية النجاح',
            is_customer=True,
            status='customer',
            area=self.cairo,
            brick=self.nasr,
            created_by=self.superadmin
        )

    def test_automated_order_fulfillment_upon_creation(self):
        """Creating a sales order with manager approval disabled atomically dispatches stock, debits customer ledger, and marks it invoiced."""
        from inventory.models import InventoryMemo
        from master_data.models import SalesSettings
        from sales.models import CustomerTransaction
        ss = SalesSettings.get_settings()
        ss.require_manager_approval = False
        ss.save()
        order = SalesOrderService.create_order(
            customer=self.customer,
            source_warehouse=self.wh_rep,
            order_date='2026-11-17',
            items_data=[{'product': self.prod, 'quantity': Decimal('10.00'), 'unit_price': Decimal('120.00')}],
            user=self.rep,
            validate_stock=True
        )
        self.assertEqual(order.status, 'invoiced')
        self.assertEqual(order.payment_status, 'credit')

        # Stock deducted
        self.stock_rep.refresh_from_db()
        self.assertEqual(self.stock_rep.qty_on_hand, Decimal('90.00'))

        # Outward InventoryMemo generated
        memo = InventoryMemo.objects.filter(sales_order=order, memo_type='outward').first()
        self.assertIsNotNone(memo)
        self.assertEqual(memo.status, 'applied')
        self.assertEqual(memo.items.first().quantity, Decimal('10.00'))

        # Customer ledger debited
        acc = CustomerAccount.objects.get(customer=self.customer)
        self.assertEqual(acc.current_balance, Decimal('1200.00'))
        self.assertTrue(CustomerTransaction.objects.filter(account=acc, debit=Decimal('1200.00')).exists())

    def test_stock_validation_prevents_overselling(self):
        """Creating an order fails cleanly if available stock is insufficient."""
        with self.assertRaises(ValidationError) as ctx:
            SalesOrderService.create_order(
                customer=self.customer,
                source_warehouse=self.wh_rep,
                order_date='2026-11-17',
                items_data=[{'product': self.prod, 'quantity': Decimal('150.00'), 'unit_price': Decimal('120.00')}],
                user=self.rep,
                validate_stock=True
            )
        self.assertIn("غير كافٍ للكمية المطلوبة", str(ctx.exception))

        # Stock untouched
        self.stock_rep.refresh_from_db()
        self.assertEqual(self.stock_rep.qty_on_hand, Decimal('100.00'))

    def test_sales_order_payment_status_workflow(self):
        """Verifies payment status transitions, permission checks, and list filtering."""
        order = SalesOrderService.create_order(
            customer=self.customer,
            source_warehouse=self.wh,
            order_date='2026-11-17',
            items_data=[{'product': self.prod, 'quantity': Decimal('5.00'), 'unit_price': Decimal('120.00')}],
            user=self.superadmin,
            validate_stock=False
        )
        self.assertEqual(order.payment_status, 'credit')
        self.assertEqual(order.payment_status_display_ar, 'آجل')

        # Rep without sales:orders/manage_payment_status cannot update
        self.client.force_login(self.rep)
        resp = self.client.post(reverse('sales_order_update_payment_status', args=[order.pk]), {
            'payment_status': 'partial',
            'notes': 'دفع جزء'
        })
        self.assertEqual(resp.status_code, 403)

        # Accountant or superadmin with permission CAN update
        self.client.force_login(self.superadmin)
        resp2 = self.client.post(reverse('sales_order_update_payment_status', args=[order.pk]), {
            'payment_status': 'partial',
            'notes': 'تم استلام دفعة مقدمة'
        })
        self.assertEqual(resp2.status_code, 302)
        order.refresh_from_db()
        self.assertEqual(order.payment_status, 'partial')
        self.assertEqual(order.payment_status_display_ar, 'جزئي')

        # Filter in list view
        list_resp = self.client.get(reverse('sales_orders_list') + '?payment_status=partial')
        self.assertEqual(list_resp.status_code, 200)
        self.assertContains(list_resp, order.order_number)

        empty_resp = self.client.get(reverse('sales_orders_list') + '?payment_status=paid')
        self.assertEqual(empty_resp.status_code, 200)
        self.assertNotContains(empty_resp, order.order_number)

    def test_form_error_recovery_preserves_dynamic_items(self):
        """Validation errors preserve entered values and dynamic rows without redirect."""
        self.client.force_login(self.superadmin)
        resp = self.client.post(reverse('sales_order_create'), {
            'customer': self.customer.id,
            'warehouse': self.wh.id,
            'order_date': '2026-11-17',
            'custom_discount_percentage': '150.00',  # Invalid discount percentage > 100
            'product_id[]': [self.prod.id],
            'quantity[]': ['12'],
            'unit_price[]': ['120.00'],
            'discount_percentage[]': ['5.00'],
            'notes': 'ملاحظات هامة جداً'
        })
        self.assertEqual(resp.status_code, 200)
        self.assertIn('form_data', resp.context)
        self.assertEqual(resp.context['form_data']['notes'], 'ملاحظات هامة جداً')
        self.assertIn('submitted_items', resp.context)
        self.assertEqual(len(resp.context['submitted_items']), 1)
        self.assertEqual(resp.context['submitted_items'][0]['quantity'], '12')

    def test_sales_order_return_details_api(self):
        """API returns returnable items and limits with sku_code safely."""
        order = SalesOrderService.create_order(
            customer=self.customer,
            source_warehouse=self.wh,
            order_date='2026-11-17',
            items_data=[{'product': self.prod, 'quantity': Decimal('10.00'), 'unit_price': Decimal('120.00')}],
            user=self.superadmin,
            validate_stock=False
        )

        self.client.force_login(self.superadmin)
        resp = self.client.get(reverse('sales_order_return_details_api', args=[order.pk]))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['order_number'], order.order_number)
        self.assertEqual(len(data['items']), 1)
        item = data['items'][0]
        self.assertEqual(item['product_name'], self.prod.name)
        self.assertEqual(item['product_code'], self.prod.sku_code)
        self.assertEqual(item['original_quantity'], '10.00')
        self.assertEqual(item['remaining_returnable'], '10.00')







class Phase2SalesListAndIntegerQtyTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model
        from accounts.models import Role
        from catalog.models import Product, ProductCategory
        from contacts.models import Contact
        from inventory.models import Warehouse, InventoryStock
        from master_data.models import Area, CompanyProfile

        User = get_user_model()
        CompanyProfile.objects.get_or_create(pk=1, defaults={'company_name': 'WEA Test Pharma'})
        self.cairo = Area.objects.create(name='القاهرة مبيعات P2', code='CAI-S2')
        self.super_role, _ = Role.objects.get_or_create(name='superadmin', defaults={'display_name': 'Super Admin', 'is_super': True})
        self.superadmin = User.objects.create_superuser(username='sales_p2_super', email='sales_p2_super@wea.com', password='TestPassword123!', role=self.super_role)
        self.customer = Contact.objects.create(name='عميل مبيعات P2', is_customer=True, area=self.cairo)
        self.wh = Warehouse.objects.create(name='مخزن مبيعات P2', code='WH-S-P2', area=self.cairo)
        self.cat = ProductCategory.objects.create(name='تصنيف مبيعات P2', code='CAT-SP2')
        self.prod = Product.objects.create(name='صنف مبيعات P2', sku_code='SKU-SP2', category=self.cat, retail_price=Decimal('100.00'))
        InventoryStock.objects.create(warehouse=self.wh, product=self.prod, qty_on_hand=Decimal('50.00'))

    def test_sales_service_rejects_fractional_quantity(self):
        from django.core.exceptions import ValidationError
        from sales.services import SalesOrderService

        with self.assertRaises(ValidationError):
            SalesOrderService.create_order(
                customer=self.customer,
                source_warehouse=self.wh,
                order_date='2026-11-17',
                items_data=[{'product': self.prod, 'quantity': Decimal('2.5'), 'unit_price': Decimal('100.00')}],
                user=self.superadmin,
            )

    def test_sales_orders_list_remaining_filter_and_customers_context(self):
        from django.urls import reverse
        self.client.force_login(self.superadmin)

        resp = self.client.get(reverse('sales_orders_list'), {'remaining_min': '10', 'remaining_max': '500'})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'col-picker-dropdown')

        cust_resp = self.client.get(reverse('sales_customers_list'), {'area_id': self.cairo.id, 'status': 'active'})
        self.assertEqual(cust_resp.status_code, 302)
        self.assertIn('relation=customer', cust_resp['Location'])
        self.assertIn(f'area_id={self.cairo.id}', cust_resp['Location'])
        followed = self.client.get(cust_resp['Location'])
        self.assertEqual(followed.status_code, 200)
        self.assertEqual(followed.context['current_relation'], 'customer')
        self.assertEqual(followed.context['current_status'], 'active')

        exp_resp = self.client.get(reverse('customer_transactions_export'))
        self.assertEqual(exp_resp.status_code, 200)
        self.assertIn('spreadsheetml.sheet', exp_resp['Content-Type'])

    def test_sales_return_order_detail_and_print_show_sku_code_and_reject_modal(self):
        """Regression test: sales_return_order_detail and print render product.sku_code and rejection modal posts rejection_reason."""
        from django.urls import reverse
        from sales.models import SalesOrder, SalesOrderItem, SalesReturnOrder, SalesReturnOrderItem

        so = SalesOrder.objects.create(
            order_number='SO-RET-REG-01',
            customer=self.customer,
            source_warehouse=self.wh,
            status='invoiced',
            order_date='2026-11-18',
            grand_total=Decimal('200.00'),
            created_by=self.superadmin,
        )
        so_item = SalesOrderItem.objects.create(
            order=so, product=self.prod, quantity=Decimal('2.00'), unit_price=Decimal('100.00')
        )
        sret = SalesReturnOrder.objects.create(
            order_number='SRET-REG-01',
            sales_order=so,
            customer=self.customer,
            target_warehouse=self.wh,
            status='pending',
            order_date='2026-11-18',
            grand_total=Decimal('100.00'),
            created_by=self.superadmin,
        )
        SalesReturnOrderItem.objects.create(
            order=sret, original_item=so_item, product=self.prod, quantity=Decimal('1.00'), unit_price=Decimal('100.00')
        )

        self.client.force_login(self.superadmin)
        detail_resp = self.client.get(reverse('sales_return_order_detail', args=[sret.pk]))
        self.assertEqual(detail_resp.status_code, 200)
        self.assertContains(detail_resp, self.prod.sku_code)
        self.assertContains(detail_resp, 'id="reject-modal"')

        print_resp = self.client.get(reverse('sales_return_order_print', args=[sret.pk]))
        self.assertEqual(print_resp.status_code, 200)
        self.assertContains(print_resp, self.prod.sku_code)


class CustomerOnlySelectorsAndHistoricalLeadTests(TestCase):
    """Comprehensive tests for Requirement C:
    - Customer-only selectors & APIs across Sales / Returns / Collections / Accounting
    - Visits picker still allows Lead contacts
    - Strict rejection of Lead/Inactive on new Sales Orders
    - Preserved historical Lead workflows (order edit without changing customer, returns, collections, lists, Excel import)
    """

    def setUp(self):
        self.superadmin_role = Role.objects.get(name='superadmin')
        self.superadmin = User.objects.create_user(
            username='cust_only_sa@wea.com', email='cust_only_sa@wea.com',
            password='Password123!', is_superuser=True, is_staff=True, role=self.superadmin_role,
        )
        self.cairo = Area.objects.create(name='القاهرة_C', code='CAI_C')
        self.nasr = Area.objects.create(name='نصر_C', code='NSR_C', parent=self.cairo)
        self.wh = Warehouse.objects.create(name='مخزن C', code='WH-C', area=self.cairo, is_main=True)
        self.vault = Vault.objects.create(serial_num=9901, name='خزنة C', area=self.cairo)
        self.cat = ProductCategory.objects.create(name='فئة C')
        self.prod = Product.objects.create(
            name='دواء اختبار C', sku_code='PRD-C-01', category=self.cat,
            retail_price=Decimal('100.00'), default_purchase_cost=Decimal('50.00'),
            is_active=True, sellable=True,
        )
        InventoryStock.objects.create(
            warehouse=self.wh, product=self.prod,
            qty_on_hand=Decimal('100.00'), qty_reserved=Decimal('0.00'),
            product_cost=Decimal('50.00'),
        )

        self.active_customer = Contact.objects.create(
            name='صيدلية عميل فعلي', code='CUST-ACTIVE', is_customer=True, status='customer',
            area=self.cairo, brick=self.nasr, created_by=self.superadmin,
        )
        self.lead_with_history = Contact.objects.create(
            name='صيدلية محتمل تاريخي', code='LEAD-HIST', is_customer=True, status='lead',
            area=self.cairo, brick=self.nasr, created_by=self.superadmin,
        )
        self.lead_fresh = Contact.objects.create(
            name='صيدلية محتمل جديد', code='LEAD-NEW', is_customer=True, status='lead',
            area=self.cairo, brick=self.nasr, created_by=self.superadmin,
        )
        self.inactive_contact = Contact.objects.create(
            name='صيدلية غير نشطة', code='CUST-INACT', is_customer=True, status='inactive',
            area=self.cairo, brick=self.nasr, created_by=self.superadmin,
        )

        # Historical invoiced SalesOrder belonging to `lead_with_history`
        self.hist_invoiced_order = SalesOrder.objects.create(
            order_number='SO-HIST-LEAD-01',
            customer=self.lead_with_history,
            source_warehouse=self.wh,
            status='invoiced',
            order_date='2026-11-01',
            grand_total=Decimal('500.00'),
            created_by=self.superadmin,
        )
        self.hist_invoiced_item = SalesOrderItem.objects.create(
            order=self.hist_invoiced_order, product=self.prod,
            quantity=Decimal('5.00'), unit_price=Decimal('100.00'),
        )
        acc = CustomerAccount.get_or_create_for_customer(self.lead_with_history)
        acc.current_balance = Decimal('500.00')
        acc.save(update_fields=['current_balance'])

        # Historical editable pending SalesOrder belonging to `lead_with_history`
        self.hist_pending_order = SalesOrder.objects.create(
            order_number='SO-HIST-LEAD-PEND',
            customer=self.lead_with_history,
            source_warehouse=self.wh,
            status='pending',
            order_date='2026-11-10',
            grand_total=Decimal('200.00'),
            created_by=self.superadmin,
        )
        SalesOrderItem.objects.create(
            order=self.hist_pending_order, product=self.prod,
            quantity=Decimal('2.00'), unit_price=Decimal('100.00'),
        )

        self.client.force_login(self.superadmin)

    def test_sales_selectors_return_only_customers_while_visits_allows_leads(self):
        from accounts.scope_service import ScopeResolutionService

        choices = list(ScopeResolutionService.get_scoped_choices(self.superadmin, 'customers', 'sales'))
        choice_ids = [c.id for c in choices]
        self.assertIn(self.active_customer.id, choice_ids)
        self.assertNotIn(self.lead_with_history.id, choice_ids)
        self.assertNotIn(self.lead_fresh.id, choice_ids)
        self.assertNotIn(self.inactive_contact.id, choice_ids)

        # sales_customers_search_api excludes lead & inactive
        for code in ('LEAD-HIST', 'LEAD-NEW', 'CUST-INACT'):
            resp = self.client.get(reverse('sales_customers_search_api') + f'?q={code}')
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.json()['results'], [])

        resp_cust = self.client.get(reverse('sales_customers_search_api') + '?q=CUST-ACTIVE')
        self.assertEqual(len(resp_cust.json()['results']), 1)

        # scope_model=customeraccount also enforces status='customer' (excludes lead & inactive)
        CustomerAccount.get_or_create_for_customer(self.active_customer)
        resp_acc_cust = self.client.get(reverse('sales_customers_search_api') + '?scope_model=customeraccount&q=CUST-ACTIVE')
        self.assertEqual(len(resp_acc_cust.json()['results']), 1)
        resp_acc_lead = self.client.get(reverse('sales_customers_search_api') + '?scope_model=customeraccount&q=LEAD-HIST')
        self.assertEqual(resp_acc_lead.json()['results'], [])

        # Visits search API (`customers_search_api`) MUST still return lead contacts
        resp_visit_lead = self.client.get(reverse('customers_search_api') + '?q=LEAD-NEW')
        self.assertEqual(resp_visit_lead.status_code, 200)
        self.assertEqual(len(resp_visit_lead.json()['results']), 1)

    def test_new_sales_order_rejects_lead_and_inactive_and_accepts_customer(self):
        # Service layer rejects lead & inactive
        for bad_contact in (self.lead_fresh, self.lead_with_history, self.inactive_contact):
            with self.assertRaises(ValidationError):
                SalesOrderService.create_order(
                    customer=bad_contact, source_warehouse=self.wh,
                    order_date='2026-11-20',
                    items_data=[{'product': self.prod, 'quantity': Decimal('1'), 'unit_price': Decimal('100')}],
                    user=self.superadmin,
                )

        # View POST rejects lead even via manipulated POST
        before_cnt = SalesOrder.objects.count()
        res_bad = self.client.post(reverse('sales_order_create'), {
            'customer': self.lead_fresh.id,
            'warehouse': self.wh.id,
            'order_date': '2026-11-20',
            'product_id[]': [str(self.prod.id)],
            'quantity[]': ['1'],
            'unit_price[]': ['100'],
            'discount_percentage[]': ['0'],
        })
        self.assertEqual(res_bad.status_code, 200)
        self.assertEqual(SalesOrder.objects.count(), before_cnt)

        # View POST accepts active customer
        res_ok = self.client.post(reverse('sales_order_create'), {
            'customer': self.active_customer.id,
            'warehouse': self.wh.id,
            'order_date': '2026-11-20',
            'product_id[]': [str(self.prod.id)],
            'quantity[]': ['1'],
            'unit_price[]': ['100'],
            'discount_percentage[]': ['0'],
        })
        self.assertEqual(res_ok.status_code, 302)
        self.assertEqual(SalesOrder.objects.count(), before_cnt + 1)

    def test_edit_historical_lead_sales_order_rules(self):
        # 1. GET edit page includes existing historical lead as selectable option
        res_get = self.client.get(reverse('sales_order_edit', args=[self.hist_pending_order.pk]))
        self.assertEqual(res_get.status_code, 200)
        self.assertContains(res_get, self.lead_with_history.name)

        # 2. POST keeping the same historical lead succeeds
        res_same = self.client.post(reverse('sales_order_edit', args=[self.hist_pending_order.pk]), {
            'customer': self.lead_with_history.id,
            'warehouse': self.wh.id,
            'order_date': '2026-11-10',
            'notes': 'تعديل ملاحظة فقط',
            'product_id[]': [str(self.prod.id)],
            'quantity[]': ['3'],
            'unit_price[]': ['100'],
            'discount_percentage[]': ['0'],
        })
        self.assertEqual(res_same.status_code, 302)
        self.hist_pending_order.refresh_from_db()
        self.assertEqual(self.hist_pending_order.customer_id, self.lead_with_history.id)
        self.assertEqual(self.hist_pending_order.grand_total, Decimal('300.00'))

        # 3. POST changing to a DIFFERENT lead or inactive is strictly rejected
        for other_bad in (self.lead_fresh, self.inactive_contact):
            res_reject = self.client.post(reverse('sales_order_edit', args=[self.hist_pending_order.pk]), {
                'customer': other_bad.id,
                'warehouse': self.wh.id,
                'order_date': '2026-11-10',
                'product_id[]': [str(self.prod.id)],
                'quantity[]': ['2'],
                'unit_price[]': ['100'],
                'discount_percentage[]': ['0'],
            })
            self.assertEqual(res_reject.status_code, 200)
            self.hist_pending_order.refresh_from_db()
            self.assertEqual(self.hist_pending_order.customer_id, self.lead_with_history.id)

        # 4. POST changing to a valid status='customer' succeeds
        res_upgrade = self.client.post(reverse('sales_order_edit', args=[self.hist_pending_order.pk]), {
            'customer': self.active_customer.id,
            'warehouse': self.wh.id,
            'order_date': '2026-11-10',
            'product_id[]': [str(self.prod.id)],
            'quantity[]': ['2'],
            'unit_price[]': ['100'],
            'discount_percentage[]': ['0'],
        })
        self.assertEqual(res_upgrade.status_code, 302)
        self.hist_pending_order.refresh_from_db()
        self.assertEqual(self.hist_pending_order.customer_id, self.active_customer.id)

    def test_historical_lead_sales_return_and_collection_preserved(self):
        # 1. Sales return against historical lead order succeeds
        ret = SalesReturnOrderService.create_return_order(
            sales_order=self.hist_invoiced_order,
            target_warehouse=self.wh,
            order_date='2026-11-20',
            items_data=[{
                'original_item': self.hist_invoiced_item,
                'product': self.prod,
                'quantity': Decimal('1'),
                'unit_price': Decimal('100.00'),
                'condition': 'resalable',
            }],
            user=self.superadmin,
            notes='مرتجع على فاتورة تاريخية',
        )
        self.assertEqual(ret.customer_id, self.lead_with_history.id)

        # 2. Collection against historical lead order succeeds (view GET + POST)
        res_get = self.client.get(reverse('collection_create') + f'?order_id={self.hist_invoiced_order.id}')
        self.assertEqual(res_get.status_code, 200)
        self.assertContains(res_get, self.lead_with_history.name)

        col = CollectionService.record_collection(
            customer=self.lead_with_history,
            vault=self.vault,
            amount=Decimal('150.00'),
            user=self.superadmin,
            sales_order=self.hist_invoiced_order,
        )
        self.assertEqual(col.customer_id, self.lead_with_history.id)

        # 3. Collection for fresh lead with NO history or inactive contact is rejected
        for bad_c in (self.lead_fresh, self.inactive_contact):
            with self.assertRaises(ValidationError):
                CollectionService.record_collection(
                    customer=bad_c,
                    vault=self.vault,
                    amount=Decimal('50.00'),
                    user=self.superadmin,
                )

        # 4. Historical lead records remain visible in list views
        self.assertContains(self.client.get(reverse('sales_orders_list')), self.lead_with_history.name)
        self.assertContains(self.client.get(reverse('collections_list')), self.lead_with_history.name)
        self.assertContains(self.client.get(reverse('accounting_customers_list')), self.lead_with_history.name)

    def test_collections_excel_importer_customer_and_historical_lead_rules(self):
        from master_data.excel_importers import CollectionsExcelImporter

        imp = CollectionsExcelImporter(self.superadmin)
        imp.prepare_context()

        # Active customer -> valid
        _, status_ok, errs_ok = imp.validate_row(2, {
            'customer': 'CUST-ACTIVE', 'vault': self.vault.name, 'amount': '100',
        }, {})
        self.assertEqual(status_ok, 'create', errs_ok)

        # Historical lead with existing order -> valid
        _, status_lead_ok, errs_lead_ok = imp.validate_row(3, {
            'customer': 'LEAD-HIST', 'vault': self.vault.name, 'amount': '50',
            'sales_order': self.hist_invoiced_order.order_number,
        }, {})
        self.assertEqual(status_lead_ok, 'create', errs_lead_ok)

        # Fresh lead without history -> error
        _, status_lead_bad, _ = imp.validate_row(4, {
            'customer': 'LEAD-NEW', 'vault': self.vault.name, 'amount': '50',
        }, {})
        self.assertEqual(status_lead_bad, 'error')

        # Inactive contact -> error
        _, status_inact, _ = imp.validate_row(5, {
            'customer': 'CUST-INACT', 'vault': self.vault.name, 'amount': '50',
        }, {})
        self.assertEqual(status_inact, 'error')


