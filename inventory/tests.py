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

    def test_inventory_and_warehouses_list_stats_respect_filters(self):
        admin = User.objects.create_superuser(username='inv_stats_adm', email='inv_s@wea.com', password='TestPassword123!')
        self.client.force_login(admin)
        res_stock = self.client.get(reverse('inventory_stock_list') + '?search=NONEXISTENT_SKU')
        self.assertEqual(res_stock.status_code, 200)
        self.assertEqual(res_stock.context['stats']['total_items'], 0)

        res_wh = self.client.get(reverse('warehouses_list') + '?search=NONEXISTENT_WH')
        self.assertEqual(res_wh.status_code, 200)
        self.assertEqual(res_wh.context['stats']['total_warehouses'], 0)


class InventoryCostAveragingAndEnhancementTests(TestCase):
    """
    Verifies Phase 2 Inventory transfer enhancements:
    1. Recalculation of destination stock product_cost via weighted average
    2. Accurate InventoryLot batch deductions and additions
    3. Duplicate warehouse name/code prevention
    """

    def setUp(self):
        self.client = Client()
        self.superadmin = User.objects.create_superuser(
            username='admin_inv_enh', email='admin_inv_enh@wea.com', password='Password123!'
        )
        self.acc_role = Role.objects.get(name=Role.ROLE_ACCOUNTANT)
        self.accountant = User.objects.create_user(
            username='acc_inv_enh', email='acc_inv_enh@wea.com', password='Password123!', role=self.acc_role
        )

        self.cairo = Area.objects.create(name='القاهرة', code='CAI-INV-ENH')
        self.superadmin.assigned_areas.add(self.cairo)
        self.accountant.assigned_areas.add(self.cairo)

        self.wh_source = Warehouse.objects.create(name='مخزن المصنع القاهرة', code='WH-SRC-01', area=self.cairo, is_active=True)
        self.wh_dest = Warehouse.objects.create(name='مخزن التوزيع المعادي', code='WH-DST-01', area=self.cairo, is_active=True)

        self.cat = ProductCategory.objects.create(name='مضادات حيوية', code='CAT-INV-ENH')
        self.product = Product.objects.create(
            name='كلافيموكس 1 جم', sku_code='PRD-CLAV-01', category=self.cat,
            retail_price=Decimal('100.00'), default_purchase_cost=Decimal('60.00'),
            is_active=True, sellable=True
        )

        # Source warehouse: 50 units @ 20.00 LE
        self.source_stock = InventoryStock.objects.create(
            warehouse=self.wh_source, product=self.product,
            qty_on_hand=Decimal('50.00'), product_cost=Decimal('20.00')
        )
        # Destination warehouse: 50 units @ 10.00 LE
        self.dest_stock = InventoryStock.objects.create(
            warehouse=self.wh_dest, product=self.product,
            qty_on_hand=Decimal('50.00'), product_cost=Decimal('10.00')
        )

    def test_destination_warehouse_weighted_average_cost_recalculation(self):
        """Transferring items recalculates destination stock product_cost using weighted-average."""
        # Transfer 50 units from source to dest
        req = ProductTransferService.create_request(
            requesting_user=self.accountant,
            source_warehouse=self.wh_source,
            destination_warehouse=self.wh_dest,
            items_data=[{'product': self.product, 'quantity': Decimal('50.00')}],
            notes='تحويل تجريبي لاحتساب متوسط التكلفة'
        )
        ProductTransferService.approve_request(req, self.superadmin)
        ProductTransferService.execute_transfer(req, self.accountant)

        self.source_stock.refresh_from_db()
        self.dest_stock.refresh_from_db()

        self.assertEqual(self.source_stock.qty_on_hand, Decimal('0.00'))
        self.assertEqual(self.dest_stock.qty_on_hand, Decimal('100.00'))
        # Weighted average: (50 * 10 + 50 * 20) / 100 = 1500 / 100 = 15.00 LE
        self.assertEqual(self.dest_stock.product_cost, Decimal('15.00'))

    def test_inventory_lot_batch_transfer(self):
        """Batch lot quantity is decremented at source and incremented/created at destination."""
        import datetime
        source_lot = InventoryLot.objects.create(
            stock=self.source_stock,
            batch_number='LOT-CLAV-2026',
            expiry_date=datetime.date(2028, 6, 30),
            quantity=Decimal('50.00')
        )

        req = ProductTransferService.create_request(
            requesting_user=self.accountant,
            source_warehouse=self.wh_source,
            destination_warehouse=self.wh_dest,
            items_data=[{
                'product': self.product,
                'quantity': Decimal('20.00'),
                'batch_number': 'LOT-CLAV-2026',
                'expiry_date': datetime.date(2028, 6, 30)
            }]
        )
        ProductTransferService.approve_request(req, self.superadmin)
        ProductTransferService.execute_transfer(req, self.accountant)

        source_lot.refresh_from_db()
        self.assertEqual(source_lot.quantity, Decimal('30.00'))

        dest_lot = InventoryLot.objects.filter(stock=self.dest_stock, batch_number='LOT-CLAV-2026').first()
        self.assertIsNotNone(dest_lot)
        self.assertEqual(dest_lot.quantity, Decimal('20.00'))
        self.assertEqual(dest_lot.expiry_date, datetime.date(2028, 6, 30))

    def test_duplicate_warehouse_name_or_code_rejected(self):
        """Creating a warehouse with duplicate name or code is rejected."""
        self.client.force_login(self.superadmin)
        post_data = {
            'name': 'مخزن المصنع القاهرة', # Existing name
            'code': 'WH-NEW-UNIQUE',
            'address': 'العنوان'
        }
        res = self.client.post(reverse('warehouses_list'), post_data, follow=True)
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "يوجد مخزن مسجل مسبقاً بنفس الاسم أو الكود")


class InventoryPhase2ImprovementsTests(TestCase):
    """
    Verifies Phase 2 architectural improvements in Inventory:
    1. /inventory/api/warehouse-stock/ availability calculations and warehouse scoping (prevent IDOR)
    2. Outward memo stock validation preventing over-dispensing
    3. Form error recovery preserving user inputs and dynamic line items in inventory_memo_create and product_transfer_create
    """

    def setUp(self):
        from django.core.management import call_command
        call_command('setup_permissions')

        self.cairo = Area.objects.create(code='INV-P2-CAI', name='القاهرة', area_type='governorate')
        self.nasr = Area.objects.create(code='INV-P2-NC', name='مدينة نصر', area_type='subarea', parent=self.cairo)
        self.giza = Area.objects.create(code='INV-P2-GIZ', name='الجيزة', area_type='governorate')
        self.dokki = Area.objects.create(code='INV-P2-DOK', name='الدقي', area_type='subarea', parent=self.giza)

        self.role_super = Role.objects.get(name='superadmin')
        self.role_rep = Role.objects.get(name='rep')

        self.superadmin = User.objects.create_superuser(username='inv_p2_super', email='inv_p2_super@test.com', password='pass')
        self.rep_cairo = User.objects.create_user(username='inv_p2_rep_cai', role=self.role_rep)
        self.rep_cairo.assigned_areas.add(self.nasr)
        self.rep_giza = User.objects.create_user(username='inv_p2_rep_giz', role=self.role_rep)
        self.rep_giza.assigned_areas.add(self.dokki)

        from accounts.services import get_representative_warehouse
        self.wh_cairo = get_representative_warehouse(self.rep_cairo)
        self.wh_giza = get_representative_warehouse(self.rep_giza)

        self.cat = ProductCategory.objects.create(name='أدوية عامة', code='INV-GEN')
        self.prod = Product.objects.create(
            name='كونجستال أقراص',
            sku_code='CONG-TAB',
            retail_price=Decimal('35.00'),
            category=self.cat,
            sellable=True
        )

        self.stock_cairo = InventoryStock.objects.create(
            warehouse=self.wh_cairo,
            product=self.prod,
            qty_on_hand=Decimal('100.00'),
            qty_reserved=Decimal('15.00'),
            product_cost=Decimal('20.00')
        )

    def test_warehouse_stock_api_availability_and_scoping(self):
        """API returns available, on_hand, and reserved stock, respecting warehouse data scope."""
        self.client.force_login(self.superadmin)
        resp = self.client.get(reverse('inventory_warehouse_stock_api') + f'?warehouse_id={self.wh_cairo.id}')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['warehouse_id'], self.wh_cairo.id)
        prod_data = next((p for p in data['products'] if p['id'] == self.prod.id), None)
        self.assertIsNotNone(prod_data)
        self.assertEqual(prod_data['qty_on_hand'], 100.0)
        self.assertEqual(prod_data['qty_reserved'], 15.0)
        self.assertEqual(prod_data['qty_available'], 85.0)

        # Scoping: rep_giza cannot query rep_cairo custody warehouse -> 403
        self.client.force_login(self.rep_giza)
        bad_resp = self.client.get(reverse('inventory_warehouse_stock_api') + f'?warehouse_id={self.wh_cairo.id}')
        self.assertEqual(bad_resp.status_code, 403)

    def test_outward_memo_stock_validation(self):
        """Creating an outward memo fails if quantity exceeds available stock."""
        items_data = [{'product': self.prod, 'quantity': Decimal('90.00')}]  # Available is only 85
        with self.assertRaises(ValidationError) as ctx:
            InventoryMemoService.create_memo(
                warehouse=self.wh_cairo,
                memo_type='outward',
                statement='صرف بضاعة فائضة',
                items_data=items_data,
                user=self.superadmin
            )
        self.assertIn("غير كافٍ لصرف", str(ctx.exception))

    def test_memo_create_form_error_recovery(self):
        """Form validation errors in inventory_memo_create preserve entered dynamic rows without redirect."""
        self.client.force_login(self.superadmin)
        resp = self.client.post(reverse('inventory_memo_create'), {
            'warehouse': self.wh_cairo.id,
            'memo_type': 'outward',
            'statement': 'إذن صرف اختباري',
            'product_id[]': [self.prod.id],
            'quantity[]': ['120.00'],  # Exceeds available 85
            'notes': 'ملاحظات إذن صرف مهمة'
        })
        self.assertEqual(resp.status_code, 400)
        self.assertIn('form_data', resp.context)
        self.assertEqual(resp.context['form_data']['statement'], 'إذن صرف اختباري')
        self.assertIn('submitted_items', resp.context)
        self.assertEqual(len(resp.context['submitted_items']), 1)
        self.assertEqual(resp.context['submitted_items'][0]['quantity'], '120.00')

    def test_product_transfer_create_form_error_recovery(self):
        """Form validation errors in product_transfer_create preserve entered dynamic rows."""
        self.client.force_login(self.superadmin)
        resp = self.client.post(reverse('product_transfer_create'), {
            'source_warehouse': self.wh_cairo.id,
            'destination_warehouse': self.wh_cairo.id,  # Same warehouse -> invalid
            'products[]': [self.prod.id],
            'quantities[]': ['10.00'],
            'notes': 'تحويل خاطئ لنفس المخزن'
        })
        self.assertEqual(resp.status_code, 200)
        self.assertIn('form_data', resp.context)
        self.assertEqual(resp.context['form_data']['notes'], 'تحويل خاطئ لنفس المخزن')
        self.assertIn('submitted_items', resp.context)
        self.assertEqual(len(resp.context['submitted_items']), 1)


class WarehouseCrudAndScopingTests(TestCase):
    """
    Verifies Warehouse CRUD operations, data scoping (SuperAdmin / Manager / Rep),
    safe deletion integrity validations (blocking delete when stock on hand > 0 or memos exist),
    audit logging, and advanced filters in warehouses_list.
    """

    def setUp(self):
        from django.core.management import call_command
        call_command('setup_permissions')

        self.cairo = Area.objects.create(name='القاهرة', code='CAI-WH-CRUD', area_type='governorate')
        self.nasr_city = Area.objects.create(name='مدينة نصر', code='NC-WH-CRUD', area_type='subarea', parent=self.cairo)
        self.giza = Area.objects.create(name='الجيزة', code='GIZ-WH-CRUD', area_type='governorate')

        self.role_super = Role.objects.get(name=Role.ROLE_SUPERADMIN)
        self.role_manager = Role.objects.get(name=Role.ROLE_MANAGER)
        self.role_rep = Role.objects.get(name=Role.ROLE_REP)

        from django.contrib.auth.models import Permission
        p_manage = Permission.objects.get(codename='inventory:warehouses/manage')
        p_delete = Permission.objects.get(codename='inventory:warehouses/delete')
        self.role_manager.permissions.add(p_manage, p_delete)

        self.superadmin = User.objects.create_superuser(
            username='wh_crud_admin', email='wh_crud_admin@wea.com', password='Password123!', role=self.role_super
        )
        self.manager_cairo = User.objects.create_user(
            username='wh_crud_mgr_cai', email='wh_crud_mgr_cai@wea.com', password='Password123!', role=self.role_manager
        )
        self.manager_cairo.assigned_areas.add(self.cairo)

        self.manager_giza = User.objects.create_user(
            username='wh_crud_mgr_giz', email='wh_crud_mgr_giz@wea.com', password='Password123!', role=self.role_manager
        )
        self.manager_giza.assigned_areas.add(self.giza)

        self.rep_cairo = User.objects.create_user(
            username='wh_crud_rep_cai', email='wh_crud_rep_cai@wea.com', password='Password123!', role=self.role_rep
        )
        self.rep_cairo.assigned_areas.add(self.nasr_city)

        self.wh_main = Warehouse.objects.create(
            name='المخزن الرئيسي بالقاهرة',
            code='WH-MAIN-001',
            area=self.cairo,
            is_main=True,
            is_active=True
        )
        self.wh_nasr = Warehouse.objects.create(
            name='مخزن عهدة مدينة نصر',
            code='WH-REP-NC-01',
            area=self.nasr_city,
            is_rep_warehouse=True,
            assigned_user=self.rep_cairo,
            is_active=True
        )
        self.wh_giza = Warehouse.objects.create(
            name='مخزن فرعي الجيزة',
            code='WH-GIZ-001',
            area=self.giza,
            is_main=False,
            is_rep_warehouse=False,
            is_active=False
        )

    def test_warehouse_create_view_and_audit_log(self):
        """Superadmin creates a warehouse with GPS coordinates and audit logging."""
        from accounts.models import SecurityAuditLog
        self.client.force_login(self.superadmin)
        post_data = {
            'name': 'مخزن جديد اختباري',
            'code': 'WH-TEST-NEW',
            'area': self.cairo.id,
            'address': 'شارع الطيران',
            'latitude': '30.0444',
            'longitude': '31.2357',
            'is_active': 'on'
        }
        res = self.client.post(reverse('warehouse_create'), post_data)
        self.assertRedirects(res, reverse('warehouses_list'))

        wh = Warehouse.objects.filter(code='WH-TEST-NEW').first()
        self.assertIsNotNone(wh)
        self.assertEqual(wh.name, 'مخزن جديد اختباري')
        self.assertEqual(wh.area, self.cairo)
        self.assertAlmostEqual(float(wh.latitude), 30.0444, places=4)
        self.assertAlmostEqual(float(wh.longitude), 31.2357, places=4)

        audit = SecurityAuditLog.objects.filter(action_type='WAREHOUSE_CREATED', record_id=wh.id).first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.actor, self.superadmin)

    def test_warehouse_edit_scoping(self):
        """Managers can edit warehouses in their main area/subareas, but are blocked outside their region."""
        # Manager Cairo edits Nasr City warehouse (within Cairo region) -> Allowed
        self.client.force_login(self.manager_cairo)
        get_res = self.client.get(reverse('warehouse_edit', args=[self.wh_nasr.id]))
        self.assertEqual(get_res.status_code, 200)

        post_res = self.client.post(reverse('warehouse_edit', args=[self.wh_nasr.id]), {
            'name': 'مخزن عهدة مدينة نصر المعدل',
            'code': 'WH-REP-NC-01',
            'area': self.nasr_city.id,
            'assigned_user': self.rep_cairo.id,
            'is_active': 'on'
        })
        self.assertRedirects(post_res, reverse('warehouses_list'))
        self.wh_nasr.refresh_from_db()
        self.assertEqual(self.wh_nasr.name, 'مخزن عهدة مدينة نصر المعدل')

        # Manager Giza attempts to edit Nasr City warehouse -> Forbidden 403
        self.client.force_login(self.manager_giza)
        bad_get = self.client.get(reverse('warehouse_edit', args=[self.wh_nasr.id]))
        self.assertEqual(bad_get.status_code, 403)

        bad_post = self.client.post(reverse('warehouse_edit', args=[self.wh_nasr.id]), {
            'name': 'محاولة اختراق مخزن القاهرة',
            'code': 'WH-REP-NC-01',
        })
        self.assertEqual(bad_post.status_code, 403)

    def test_warehouse_delete_success(self):
        """Deleting an empty warehouse with no stock, memos, or transactions succeeds with audit log."""
        from accounts.models import SecurityAuditLog
        wh_to_del = Warehouse.objects.create(name='مخزن فارغ للحذف', code='WH-DEL-ME', area=self.cairo)
        wh_id = wh_to_del.id

        self.client.force_login(self.superadmin)
        res = self.client.post(reverse('warehouse_delete', args=[wh_id]))
        self.assertRedirects(res, reverse('warehouses_list'))
        self.assertFalse(Warehouse.objects.filter(id=wh_id).exists())

        audit = SecurityAuditLog.objects.filter(action_type='WAREHOUSE_DELETED', record_id=wh_id).first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.actor, self.superadmin)

    def test_warehouse_delete_blocked_when_stock_on_hand_exists(self):
        """Warehouse cannot be deleted if active stock on hand exists."""
        cat = ProductCategory.objects.create(name='تصنيف فحص الحذف', code='CAT-DEL-CHK')
        prod = Product.objects.create(name='منتج فحص الحذف', sku_code='PRD-DEL-CHK', category=cat, retail_price=Decimal('10.00'))
        InventoryStock.objects.create(warehouse=self.wh_main, product=prod, qty_on_hand=Decimal('25.00'))

        self.client.force_login(self.superadmin)
        res = self.client.post(reverse('warehouse_delete', args=[self.wh_main.id]), follow=True)
        self.assertEqual(res.status_code, 200)
        self.assertTrue(Warehouse.objects.filter(id=self.wh_main.id).exists())
        self.assertContains(res, "لا يمكن حذف المخزن لوجود أرصدة مخزنية حالية به")

    def test_warehouse_delete_blocked_when_memo_exists(self):
        """Warehouse cannot be deleted if inventory memos are linked to it."""
        wh_memo = Warehouse.objects.create(name='مخزن بأذونات مخزنية', code='WH-MEMO-CHK', area=self.cairo)
        InventoryMemo.objects.create(
            warehouse=wh_memo,
            memo_type='inward',
            statement='إذن إضافة رصيد تجريبي',
            created_by=self.superadmin
        )

        self.client.force_login(self.superadmin)
        res = self.client.post(reverse('warehouse_delete', args=[wh_memo.id]), follow=True)
        self.assertEqual(res.status_code, 200)
        self.assertTrue(Warehouse.objects.filter(id=wh_memo.id).exists())
        self.assertContains(res, "لا يمكن حذف المخزن لوجود أذونات مخزنية مسجلة عليه")

    def test_warehouse_delete_scoping(self):
        """Out-of-region managers cannot delete warehouses they do not manage."""
        self.client.force_login(self.manager_giza)
        res = self.client.post(reverse('warehouse_delete', args=[self.wh_nasr.id]))
        self.assertEqual(res.status_code, 403)
        self.assertTrue(Warehouse.objects.filter(id=self.wh_nasr.id).exists())

    def test_warehouses_list_advanced_filters(self):
        """Advanced filters drawer correctly isolates warehouse types, statuses, areas, and users."""
        self.client.force_login(self.superadmin)

        # Filter by type: main
        res_main = self.client.get(reverse('warehouses_list') + '?type=main')
        self.assertContains(res_main, self.wh_main.name)
        self.assertNotContains(res_main, self.wh_nasr.name)

        # Filter by type: rep
        res_rep = self.client.get(reverse('warehouses_list') + '?type=rep')
        self.assertContains(res_rep, self.wh_nasr.name)
        self.assertNotContains(res_rep, self.wh_main.name)

        # Filter by status: inactive
        res_inact = self.client.get(reverse('warehouses_list') + '?status=inactive')
        self.assertContains(res_inact, self.wh_giza.name)
        self.assertNotContains(res_inact, self.wh_main.name)

        # Filter by governorate/area (includes child subarea warehouses)
        res_area = self.client.get(reverse('warehouses_list') + f'?area={self.cairo.id}')
        self.assertContains(res_area, self.wh_main.name)
        self.assertContains(res_area, self.wh_nasr.name)
        self.assertNotContains(res_area, self.wh_giza.name)

        # Filter by assigned user
        res_user = self.client.get(reverse('warehouses_list') + f'?assigned_user={self.rep_cairo.id}')
        self.assertContains(res_user, self.wh_nasr.name)
        self.assertNotContains(res_user, self.wh_main.name)





class Phase2InventoryMemosAndExportsTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model
        from accounts.models import Role, Permission
        from catalog.models import Product, ProductCategory
        from inventory.models import Warehouse, InventoryStock
        from master_data.models import Area, CompanyProfile

        User = get_user_model()
        CompanyProfile.objects.get_or_create(pk=1, defaults={'company_name': 'WEA Test Pharma'})

        self.cairo = Area.objects.create(name='القاهرة اختبار', code='CAI-T1')
        self.giza = Area.objects.create(name='الجيزة اختبار', code='GIZ-T1')

        self.super_role, _ = Role.objects.get_or_create(name='superadmin', defaults={'display_name': 'Super Admin', 'is_super': True})
        self.rep_role, _ = Role.objects.get_or_create(name='rep', defaults={'display_name': 'Rep'})

        # Ensure required permissions are assigned
        perms = Permission.objects.filter(codename__in=[
            'module:inventory',
            'inventory:memos/manage', 'inventory:memos/export',
            'inventory:warehouses/export', 'inventory:transfers/export',
            'inventory:stocks/view', 'inventory:transfers/list',
        ])
        self.rep_role.permissions.add(*perms)

        self.superadmin = User.objects.create_superuser(username='inv_p2_super', email='inv_p2_super@wea.com', password='TestPassword123!', role=self.super_role)
        self.rep_cairo = User.objects.create_user(username='inv_p2_rep', email='inv_p2_rep@wea.com', password='TestPassword123!', role=self.rep_role)
        self.rep_cairo.assigned_areas.add(self.cairo)

        self.cat = ProductCategory.objects.create(name='أدوية اختبار', code='CAT-P2')
        self.prod = Product.objects.create(name='دواء اختبار', sku_code='SKU-P2-01', category=self.cat, retail_price=Decimal('50.00'), default_purchase_cost=Decimal('30.00'))

        self.wh_cairo = Warehouse.objects.create(name='مخزن القاهرة P2', code='WH-C-P2', area=self.cairo, assigned_user=self.rep_cairo, is_rep_warehouse=True)
        self.wh_giza = Warehouse.objects.create(name='مخزن الجيزة P2', code='WH-G-P2', area=self.giza)
        InventoryStock.objects.create(warehouse=self.wh_cairo, product=self.prod, qty_on_hand=Decimal('20.00'))

    def test_memo_create_inward_with_integer_qty_and_400_recovery(self):
        from django.urls import reverse
        from inventory.models import InventoryMemo

        self.client.force_login(self.superadmin)
        # Valid inward memo
        resp = self.client.post(reverse('inventory_memo_create'), {
            'memo_type': 'inward',
            'warehouse': self.wh_cairo.id,
            'statement': 'إضافة رصيد افتتاحي',
            'product_id[]': [self.prod.id],
            'quantity[]': ['5'],
            'unit_cost[]': ['30.00'],
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(InventoryMemo.objects.filter(warehouse=self.wh_cairo, statement='إضافة رصيد افتتاحي').exists())

        # Fractional quantity returns 400 and preserves form_data & submitted_items
        bad_resp = self.client.post(reverse('inventory_memo_create'), {
            'memo_type': 'outward',
            'warehouse': self.wh_cairo.id,
            'statement': 'صرف خاطئ عشري',
            'product_id[]': [self.prod.id],
            'quantity[]': ['2.5'],
            'unit_cost[]': ['30.00'],
        })
        self.assertEqual(bad_resp.status_code, 400)
        self.assertEqual(bad_resp.context['form_data']['statement'], 'صرف خاطئ عشري')
        self.assertEqual(len(bad_resp.context['submitted_items']), 1)
        self.assertEqual(bad_resp.context['submitted_items'][0]['quantity'], '2.5')

    def test_service_rejects_fractional_quantities(self):
        from django.core.exceptions import ValidationError
        from inventory.services import InventoryMemoService, ProductTransferService

        with self.assertRaises(ValidationError):
            InventoryMemoService.create_memo(
                warehouse=self.wh_cairo,
                memo_type='inward',
                items_data=[{'product': self.prod, 'quantity': Decimal('1.5'), 'unit_cost': Decimal('30.00')}],
                user=self.superadmin,
                statement='كسر',
            )

        with self.assertRaises(ValidationError):
            ProductTransferService.create_request(
                requesting_user=self.superadmin,
                destination_warehouse=self.wh_giza,
                source_warehouse=self.wh_cairo,
                items_data=[{'product': self.prod, 'quantity': Decimal('0.5')}],
            )

    def test_new_inventory_exports_and_smart_search_scoping(self):
        from django.urls import reverse
        self.client.force_login(self.rep_cairo)

        for url_name in ['warehouses_export', 'inventory_memos_export', 'product_transfers_export']:
            resp = self.client.get(reverse(url_name))
            self.assertEqual(resp.status_code, 200)
            self.assertIn('spreadsheetml.sheet', resp['Content-Type'])

        # Smart search must only return cairo warehouse, never giza
        sug_resp = self.client.get(reverse('list_suggestions_api'), {'module': 'warehouses', 'q': 'مخزن'})
        self.assertEqual(sug_resp.status_code, 200)
        labels = [r['label'] for r in sug_resp.json()['results']]
        self.assertTrue(any('القاهرة' in lbl for lbl in labels))
        self.assertFalse(any('الجيزة' in lbl for lbl in labels))
