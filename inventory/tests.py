import io
import openpyxl
from decimal import Decimal

from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from master_data.models import Area, CompanyProfile
from accounts.models import Role
from catalog.models import Product, ProductCategory
from inventory.models import (
    Warehouse, InventoryStock, InventoryLot, InventoryMemo,
    ProductTransferRequest, ProductTransferRequestItem
)
from inventory.services import InventoryMemoService, ProductTransferService

User = get_user_model()


class InventoryExcelExportAndListViewTests(TestCase):
    """Verifies inventory stock listing, filtering, aggregates, and Excel exports."""

    def setUp(self):
        self.user = User.objects.create_superuser(
            email='invadmin@weapharma.com',
            username='invadmin@weapharma.com',
            password='Password123!',
            first_name='Inv',
            last_name='Admin'
        )
        self.client = Client()
        self.client.login(username='invadmin@weapharma.com', password='Password123!')

        self.category = ProductCategory.objects.create(name='أدوية عامة', code='GEN')
        self.product = Product.objects.create(
            name='أمبيسيلين 500',
            sku_code='AMP-500',
            category=self.category,
            retail_price=Decimal('25.00'),
            default_purchase_cost=Decimal('18.00'),
            sellable=True
        )
        self.warehouse = Warehouse.objects.create(
            name='مخزن الأدوية الرئيسي',
            code='WH-MAIN',
            is_main=True
        )
        self.stock = InventoryStock.objects.create(
            warehouse=self.warehouse,
            product=self.product,
            qty_on_hand=Decimal('150.00'),
            qty_reserved=Decimal('10.00'),
            product_cost=Decimal('18.00')
        )

    def test_inventory_export_excel(self):
        response = self.client.get(reverse('inventory_stock_export'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        self.assertIn('.xlsx', response['Content-Disposition'])

        wb = openpyxl.load_workbook(io.BytesIO(response.content))
        ws = wb.active
        self.assertTrue(ws.sheet_view.rightToLeft)
        found = any(cell.value == 'AMP-500' for row in ws.iter_rows() for cell in row)
        self.assertTrue(found)

    def test_inventory_stock_list_view_and_aggregations(self):
        """Test that inventory_stock_list loads with 200 and calculates aggregates without FieldError."""
        response = self.client.get(reverse('inventory_stock_list'))
        self.assertEqual(response.status_code, 200)
        stats = response.context['stats']
        self.assertEqual(stats['total_items'], 1)
        self.assertEqual(stats['total_qty_on_hand'], Decimal('150.00'))
        self.assertEqual(stats['total_qty_available'], Decimal('140.00'))
        self.assertEqual(stats['total_cost_value'], Decimal('2700.00'))

    def test_inventory_stock_list_warehouse_filter(self):
        """Test warehouse filtering on inventory_stock_list."""
        response = self.client.get(reverse('inventory_stock_list') + f'?warehouse={self.warehouse.id}')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['stocks']), 1)


class WarehouseOperationsAndPermissionsTests(TestCase):
    """Verifies stock in/out, lot management, weighted average costs, and settings-based permissions."""

    def setUp(self):
        # Areas
        self.cairo = Area.objects.create(code='CAI', name='القاهرة', area_type='governorate', parent=None)
        self.nasr_city = Area.objects.create(code='NC', name='مدينة نصر', area_type='subarea', parent=self.cairo)
        self.maadi = Area.objects.create(code='MAA', name='المعادي', area_type='subarea', parent=self.cairo)

        # Roles
        self.super_role, _ = Role.objects.get_or_create(name='superadmin', defaults={'is_super': True, 'display_name': 'مدير النظام الأعلى'})
        self.accountant_role, _ = Role.objects.get_or_create(name='accountant', defaults={'display_name': 'محاسب'})
        self.rep_role, _ = Role.objects.get_or_create(name='rep', defaults={'is_rep': True, 'is_sales_team': True, 'display_name': 'مندوب مبيعات'})

        # Users
        self.superadmin = User.objects.create_superuser(username='superadmin_wh', email='super@wh.com', password='pass')
        self.accountant = User.objects.create_user(username='accountant_wh', role=self.accountant_role)
        self.rep1 = User.objects.create_user(username='rep_nc', first_name='أحمد', role=self.rep_role)
        self.rep1.assigned_areas.add(self.nasr_city)
        self.rep2 = User.objects.create_user(username='rep_maadi', first_name='خالد', role=self.rep_role)
        self.rep2.assigned_areas.add(self.maadi)

        # Warehouses
        self.wh_main = Warehouse.objects.create(name='المخزن الرئيسي', code='WH-MAIN', is_main=True, area=self.cairo)
        self.wh_rep1 = Warehouse.objects.create(name='مخزن عهدة أحمد', code='WH-REP-1', is_rep_warehouse=True, assigned_user=self.rep1, area=self.nasr_city)
        self.wh_rep2 = Warehouse.objects.create(name='مخزن عهدة خالد', code='WH-REP-2', is_rep_warehouse=True, assigned_user=self.rep2, area=self.maadi)

        # Products
        self.cat = ProductCategory.objects.create(name='أدوية')
        self.prod = Product.objects.create(name='أمبولات فيتامين', sku_code='VIT-AMP', retail_price=Decimal('100.00'), category=self.cat)

        # Initial Stock on Main Warehouse
        self.stock_main = InventoryStock.objects.create(
            warehouse=self.wh_main,
            product=self.prod,
            qty_on_hand=Decimal('200.00'),
            qty_reserved=Decimal('0.00'),
            product_cost=Decimal('60.00')
        )

        # Profile
        self.profile = CompanyProfile.get_settings()

    def test_stock_in_operation_updates_balance_and_cost(self):
        """Stock In increments inventory and calculates weighted average cost."""
        items_data = [
            {
                'product': self.prod,
                'quantity': Decimal('100.00'),
                'unit_cost': Decimal('90.00'),
                'batch_number': 'BCH-001',
                'expiry_date': '2028-12-31'
            }
        ]
        memo = InventoryMemoService.create_memo(
            warehouse=self.wh_main,
            memo_type='inward',
            statement='استلام شحنة إضافية',
            items_data=items_data,
            user=self.superadmin
        )

        self.assertEqual(memo.status, 'applied')
        self.stock_main.refresh_from_db()
        self.assertEqual(self.stock_main.qty_on_hand, Decimal('300.00'))
        self.assertEqual(self.stock_main.product_cost, Decimal('70.00'))

        lot = InventoryLot.objects.filter(stock=self.stock_main, batch_number='BCH-001').first()
        self.assertIsNotNone(lot)
        self.assertEqual(lot.quantity, Decimal('100.00'))

    def test_stock_out_operation_deducts_balance(self):
        """Stock Out deducts available quantity from the warehouse."""
        items_data = [
            {'product': self.prod, 'quantity': Decimal('50.00')}
        ]
        memo = InventoryMemoService.create_memo(
            warehouse=self.wh_main,
            memo_type='outward',
            statement='صرف عينات ترويجية',
            items_data=items_data,
            user=self.superadmin
        )
        self.assertEqual(memo.status, 'applied')
        self.stock_main.refresh_from_db()
        self.assertEqual(self.stock_main.qty_on_hand, Decimal('150.00'))

    def test_stock_out_rejects_insufficient_or_reserved_stock(self):
        """Stock Out rejects dispensing more than available stock, accounting for reservations."""
        self.stock_main.qty_reserved = Decimal('180.00')
        self.stock_main.save()

        items_data = [
            {'product': self.prod, 'quantity': Decimal('50.00')}
        ]
        with self.assertRaises(ValidationError) as ctx:
            InventoryMemoService.create_memo(
                warehouse=self.wh_main,
                memo_type='outward',
                statement='صرف غير متاح',
                items_data=items_data,
                user=self.superadmin
            )
        self.assertIn("غير كافٍ لصرف الكمية", str(ctx.exception))

    def test_role_permissions_via_settings(self):
        """Settings configure which roles can perform Stock In / Out."""
        items_data = [{'product': self.prod, 'quantity': Decimal('10.00'), 'unit_cost': Decimal('60.00')}]

        self.profile.roles_can_stock_in.clear()
        with self.assertRaises(ValidationError):
            InventoryMemoService.create_memo(
                warehouse=self.wh_rep1,
                memo_type='inward',
                statement='محاولة إضافة غير مصرح بها',
                items_data=items_data,
                user=self.rep1
            )

        self.profile.roles_can_stock_in.add(self.rep_role)
        memo = InventoryMemoService.create_memo(
            warehouse=self.wh_rep1,
            memo_type='inward',
            statement='إضافة مصرح بها في مخزن العهدة',
            items_data=items_data,
            user=self.rep1
        )
        self.assertEqual(memo.status, 'applied')

    def test_accountant_operational_access(self):
        """Accountant has full operational access to warehouses."""
        items_data = [{'product': self.prod, 'quantity': Decimal('15.00')}]
        memo = InventoryMemoService.create_memo(
            warehouse=self.wh_main,
            memo_type='outward',
            statement='صرف محاسبي معتمد',
            items_data=items_data,
            user=self.accountant
        )
        self.assertEqual(memo.status, 'applied')

    def test_transfers_protect_reserved_stock(self):
        """Warehouse transfer execution strictly checks qty_available, not just qty_on_hand."""
        transfer_req = ProductTransferService.create_request(
            requesting_user=self.rep1,
            destination_warehouse=self.wh_rep1,
            source_warehouse=self.wh_main,
            items_data=[{'product': self.prod, 'quantity': Decimal('50.00')}]
        )
        ProductTransferService.approve_request(transfer_req, user=self.superadmin)

        self.stock_main.qty_reserved = Decimal('180.00')
        self.stock_main.save()

        with self.assertRaises(ValidationError) as ctx:
            ProductTransferService.execute_transfer(transfer_req, user=self.superadmin)
        self.assertIn("غير كافٍ لإتمام التحويل", str(ctx.exception))


class ProductTransferWorkflowTests(TestCase):
    """
    Verifies inter-warehouse product transfer workflows:
    1. Same main area requests permitted across subareas
    2. Cross-main-area requests rejected
    3. Mandatory SuperAdmin / Accountant approval before any stock transfer
    4. Atomic transfer execution with concurrency safety and InventoryMemo generation
    5. Prevention of double execution and overdrawing stock
    """

    def setUp(self):
        self.cairo_main = Area.objects.create(code='CAI', name='القاهرة', area_type='governorate', parent=None)
        self.nasr_city = Area.objects.create(code='CAI-NC', name='مدينة نصر', area_type='subarea', parent=self.cairo_main)
        self.maadi = Area.objects.create(code='CAI-MD', name='المعادي', area_type='subarea', parent=self.cairo_main)

        self.alex_main = Area.objects.create(code='ALX', name='الإسكندرية', area_type='governorate', parent=None)
        self.smouha = Area.objects.create(code='ALX-SM', name='سموحة', area_type='subarea', parent=self.alex_main)

        self.rep_role, _ = Role.objects.get_or_create(name='MedicalRep', defaults={'display_name': 'مندوب دعاية', 'is_rep': True})
        self.rep_role.is_rep = True
        self.rep_role.save()

        self.accountant_role, _ = Role.objects.get_or_create(name='Accountant', defaults={'display_name': 'محاسب', 'is_rep': False})
        self.accountant_role.is_rep = False
        self.accountant_role.save()

        self.rep_cairo1 = User.objects.create_user(username='rep_cairo1', role=self.rep_role)
        self.rep_cairo1.assigned_areas.add(self.nasr_city)

        self.rep_cairo2 = User.objects.create_user(username='rep_cairo2', role=self.rep_role)
        self.rep_cairo2.assigned_areas.add(self.maadi)

        self.rep_alex = User.objects.create_user(username='rep_alex', role=self.rep_role)
        self.rep_alex.assigned_areas.add(self.smouha)

        self.accountant = User.objects.create_user(username='accountant_user', role=self.accountant_role)
        self.superadmin = User.objects.create_superuser(username='superadmin_user', email='admin@test.com', password='pass')

        self.wh_cairo1 = Warehouse.objects.create(
            name='مخزن مندوب نصر سيتي', code='WH-NC', assigned_user=self.rep_cairo1,
            area=self.nasr_city, is_rep_warehouse=True
        )
        self.wh_cairo2 = Warehouse.objects.create(
            name='مخزن مندوب المعادي', code='WH-MD', assigned_user=self.rep_cairo2,
            area=self.maadi, is_rep_warehouse=True
        )
        self.wh_alex = Warehouse.objects.create(
            name='مخزن مندوب سموحة', code='WH-SM', assigned_user=self.rep_alex,
            area=self.smouha, is_rep_warehouse=True
        )

        self.category = ProductCategory.objects.create(name='أدوية')
        self.product = Product.objects.create(
            name='بانادول إكسترا 500 ملجم',
            sku_code='PAN-EXT-500',
            retail_price=Decimal('45.00'),
            default_purchase_cost=Decimal('30.00'),
            category=self.category
        )

        self.source_stock = InventoryStock.objects.create(
            warehouse=self.wh_cairo2,
            product=self.product,
            qty_on_hand=Decimal('100.00'),
            qty_reserved=Decimal('0.00'),
            product_cost=Decimal('30.00')
        )

    def test_same_main_area_request_allowed(self):
        items_data = [{'product': self.product, 'quantity': Decimal('20.00')}]
        transfer_req = ProductTransferService.create_request(
            requesting_user=self.rep_cairo1,
            destination_warehouse=self.wh_cairo1,
            source_warehouse=self.wh_cairo2,
            items_data=items_data,
            notes='طلب بضاعة لنفس المحافظة'
        )
        self.assertEqual(transfer_req.status, 'pending')
        self.assertEqual(transfer_req.items.count(), 1)
        self.assertEqual(transfer_req.items.first().requested_quantity, Decimal('20.00'))

        self.source_stock.refresh_from_db()
        self.assertEqual(self.source_stock.qty_on_hand, Decimal('100.00'))

    def test_cross_main_area_request_rejected(self):
        items_data = [{'product': self.product, 'quantity': Decimal('10.00')}]
        with self.assertRaises(ValidationError) as ctx:
            ProductTransferService.create_request(
                requesting_user=self.rep_cairo1,
                destination_warehouse=self.wh_cairo1,
                source_warehouse=self.wh_alex,
                items_data=items_data
            )
        self.assertIn("غير مصرح بالتحويل المخزني عبر مناطق رئيسية مختلفة", str(ctx.exception))

    def test_superadmin_or_accountant_approval_required(self):
        items_data = [{'product': self.product, 'quantity': Decimal('15.00')}]
        transfer_req = ProductTransferService.create_request(
            requesting_user=self.rep_cairo1,
            destination_warehouse=self.wh_cairo1,
            source_warehouse=self.wh_cairo2,
            items_data=items_data
        )

        with self.assertRaises(ValidationError):
            ProductTransferService.approve_request(transfer_req, self.rep_cairo1)

        approved_req = ProductTransferService.approve_request(transfer_req, self.accountant, notes='معتمد من الحسابات')
        self.assertEqual(approved_req.status, 'approved')
        self.assertEqual(approved_req.approved_by, self.accountant)

        self.source_stock.refresh_from_db()
        self.assertEqual(self.source_stock.qty_on_hand, Decimal('100.00'))

    def test_atomic_execution_and_inventory_memos(self):
        items_data = [{'product': self.product, 'quantity': Decimal('25.00')}]
        transfer_req = ProductTransferService.create_request(
            requesting_user=self.rep_cairo1,
            destination_warehouse=self.wh_cairo1,
            source_warehouse=self.wh_cairo2,
            items_data=items_data
        )
        ProductTransferService.approve_request(transfer_req, self.accountant)

        transferred_req = ProductTransferService.execute_transfer(transfer_req, self.accountant)
        self.assertEqual(transferred_req.status, 'transferred')
        self.assertIsNotNone(transferred_req.outward_memo)
        self.assertIsNotNone(transferred_req.inward_memo)

        self.source_stock.refresh_from_db()
        self.assertEqual(self.source_stock.qty_on_hand, Decimal('75.00'))

        dest_stock = InventoryStock.objects.get(warehouse=self.wh_cairo1, product=self.product)
        self.assertEqual(dest_stock.qty_on_hand, Decimal('25.00'))

        with self.assertRaises(ValidationError) as ctx:
            ProductTransferService.execute_transfer(transfer_req, self.accountant)
        self.assertIn("تم تنفيذ هذا التحويل مسبقاً", str(ctx.exception))

    def test_insufficient_stock_prevents_transfer(self):
        items_data = [{'product': self.product, 'quantity': Decimal('150.00')}]
        with self.assertRaises(ValidationError) as ctx:
            ProductTransferService.create_request(
                requesting_user=self.rep_cairo1,
                destination_warehouse=self.wh_cairo1,
                source_warehouse=self.wh_cairo2,
                items_data=items_data
            )
        self.assertIn("غير كافٍ للكمية المطلوبة", str(ctx.exception))
