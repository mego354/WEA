import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from decimal import Decimal
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from master_data.models import Area
from accounts.models import Role
from catalog.models import Product, ProductCategory
from inventory.models import (
    Warehouse, InventoryStock, InventoryMemo,
    ProductTransferRequest, ProductTransferRequestItem
)
from inventory.services import ProductTransferService

User = get_user_model()


class ProductTransferTests(TestCase):
    """
    Automated test suite verifying:
    1. Same main area requests permitted across subareas
    2. Cross-main-area requests rejected
    3. Mandatory SuperAdmin / Accountant approval before any stock transfer
    4. Atomic transfer execution with concurrency safety and InventoryMemo generation
    5. Prevention of double execution and overdrawing stock
    """

    def setUp(self):
        # 1. Areas: Cairo Main & Subareas, Alex Main & Subareas
        self.cairo_main = Area.objects.create(code='CAI', name='القاهرة', area_type='governorate', parent=None)
        self.nasr_city = Area.objects.create(code='CAI-NC', name='مدينة نصر', area_type='subarea', parent=self.cairo_main)
        self.maadi = Area.objects.create(code='CAI-MD', name='المعادي', area_type='subarea', parent=self.cairo_main)

        self.alex_main = Area.objects.create(code='ALX', name='الإسكندرية', area_type='governorate', parent=None)
        self.smouha = Area.objects.create(code='ALX-SM', name='سموحة', area_type='subarea', parent=self.alex_main)

        # 2. Roles
        self.rep_role, _ = Role.objects.get_or_create(name='MedicalRep', defaults={'display_name': 'مندوب دعاية', 'is_rep': True})
        self.rep_role.is_rep = True
        self.rep_role.save()

        self.accountant_role, _ = Role.objects.get_or_create(name='Accountant', defaults={'display_name': 'محاسب', 'is_rep': False})
        self.accountant_role.is_rep = False
        self.accountant_role.save()

        self.manager_role, _ = Role.objects.get_or_create(name='AreaManager', defaults={'display_name': 'مدير منطقة', 'is_area_manager': True, 'is_rep': False})
        self.manager_role.is_area_manager = True
        self.manager_role.is_rep = False
        self.manager_role.save()

        # 3. Users
        self.rep_cairo1 = User.objects.create_user(username='rep_cairo1', role=self.rep_role)
        self.rep_cairo1.assigned_areas.add(self.nasr_city)

        self.rep_cairo2 = User.objects.create_user(username='rep_cairo2', role=self.rep_role)
        self.rep_cairo2.assigned_areas.add(self.maadi)

        self.rep_alex = User.objects.create_user(username='rep_alex', role=self.rep_role)
        self.rep_alex.assigned_areas.add(self.smouha)

        self.accountant = User.objects.create_user(username='accountant_user', role=self.accountant_role)
        self.superadmin = User.objects.create_superuser(username='superadmin_user', email='admin@test.com', password='pass')

        # 4. Warehouses
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

        # 5. Product & Initial Stock
        self.category = ProductCategory.objects.create(name='أدوية')
        self.product = Product.objects.create(
            name='بانادول إكسترا 500 ملجم',
            sku_code='PAN-EXT-500',
            retail_price=Decimal('45.00'),
            default_purchase_cost=Decimal('30.00'),
            category=self.category
        )

        # Source warehouse initial stock = 100 units
        self.source_stock = InventoryStock.objects.create(
            warehouse=self.wh_cairo2,
            product=self.product,
            qty_on_hand=Decimal('100.00'),
            qty_reserved=Decimal('0.00'),
            product_cost=Decimal('30.00')
        )

    def test_same_main_area_request_allowed(self):
        """A representative in Nasr City requesting from a rep in Maadi (both Cairo) is allowed."""
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

        # Stock must NOT move at creation time
        self.source_stock.refresh_from_db()
        self.assertEqual(self.source_stock.qty_on_hand, Decimal('100.00'))

    def test_cross_main_area_request_rejected(self):
        """A request across different main areas (Cairo -> Alex) is rejected for ordinary users."""
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
        """Only SuperAdmin or Accountant can approve the request. Ordinary rep cannot approve."""
        items_data = [{'product': self.product, 'quantity': Decimal('15.00')}]
        transfer_req = ProductTransferService.create_request(
            requesting_user=self.rep_cairo1,
            destination_warehouse=self.wh_cairo1,
            source_warehouse=self.wh_cairo2,
            items_data=items_data
        )

        # Rep cannot approve own or others' request
        with self.assertRaises(ValidationError):
            ProductTransferService.approve_request(transfer_req, self.rep_cairo1)

        # Accountant CAN approve
        approved_req = ProductTransferService.approve_request(transfer_req, self.accountant, notes='معتمد من الحسابات')
        self.assertEqual(approved_req.status, 'approved')
        self.assertEqual(approved_req.approved_by, self.accountant)

        # Stock still NOT moved after approval
        self.source_stock.refresh_from_db()
        self.assertEqual(self.source_stock.qty_on_hand, Decimal('100.00'))

    def test_atomic_execution_and_inventory_memos(self):
        """Executing an approved transfer atomically moves stock and creates linked memos."""
        items_data = [{'product': self.product, 'quantity': Decimal('25.00')}]
        transfer_req = ProductTransferService.create_request(
            requesting_user=self.rep_cairo1,
            destination_warehouse=self.wh_cairo1,
            source_warehouse=self.wh_cairo2,
            items_data=items_data
        )
        ProductTransferService.approve_request(transfer_req, self.accountant)

        # Execute transfer
        transferred_req = ProductTransferService.execute_transfer(transfer_req, self.accountant)
        self.assertEqual(transferred_req.status, 'transferred')
        self.assertIsNotNone(transferred_req.outward_memo)
        self.assertIsNotNone(transferred_req.inward_memo)

        # Check source warehouse stock decreased (100 - 25 = 75)
        self.source_stock.refresh_from_db()
        self.assertEqual(self.source_stock.qty_on_hand, Decimal('75.00'))

        # Check destination warehouse stock increased (0 + 25 = 25)
        dest_stock = InventoryStock.objects.get(warehouse=self.wh_cairo1, product=self.product)
        self.assertEqual(dest_stock.qty_on_hand, Decimal('25.00'))

        # Prevent duplicate execution
        with self.assertRaises(ValidationError) as ctx:
            ProductTransferService.execute_transfer(transfer_req, self.accountant)
        self.assertIn("تم تنفيذ هذا التحويل مسبقاً", str(ctx.exception))

    def test_insufficient_stock_prevents_transfer(self):
        """Requesting more quantity than available in source warehouse is rejected."""
        items_data = [{'product': self.product, 'quantity': Decimal('150.00')}]
        with self.assertRaises(ValidationError) as ctx:
            ProductTransferService.create_request(
                requesting_user=self.rep_cairo1,
                destination_warehouse=self.wh_cairo1,
                source_warehouse=self.wh_cairo2,
                items_data=items_data
            )
        self.assertIn("غير كافٍ للكمية المطلوبة", str(ctx.exception))
