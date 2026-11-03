from decimal import Decimal
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from accounts.models import Role
from master_data.models import Area, CompanyProfile
from catalog.models import Product, ProductCategory
from inventory.models import Warehouse, InventoryStock, InventoryLot, InventoryMemo, ProductTransferRequest
from inventory.services import InventoryMemoService, ProductTransferService

User = get_user_model()


class WarehouseOperationsAndPermissionsTests(TestCase):
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
        # Previous: 200 units @ 60.00 = 12,000
        # Added: 100 units @ 90.00 = 9,000
        # New total qty = 300, new total cost = 21,000, new unit cost = 70.00
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

        # Lot lot created
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
        # Reserve 180 out of 200 -> available is 20
        self.stock_main.qty_reserved = Decimal('180.00')
        self.stock_main.save()

        items_data = [
            {'product': self.prod, 'quantity': Decimal('50.00')}  # Needs 50, but only 20 available
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

        # Rep role is NOT in roles_can_stock_in -> rejected
        self.profile.roles_can_stock_in.clear()
        with self.assertRaises(ValidationError):
            InventoryMemoService.create_memo(
                warehouse=self.wh_rep1,
                memo_type='inward',
                statement='محاولة إضافة غير مصرح بها',
                items_data=items_data,
                user=self.rep1
            )

        # Grant rep role permission in settings
        self.profile.roles_can_stock_in.add(self.rep_role)

        # Rep can now stock in to their own warehouse
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
        # rep1 requests 50 from main warehouse
        transfer_req = ProductTransferService.create_request(
            requesting_user=self.rep1,
            destination_warehouse=self.wh_rep1,
            source_warehouse=self.wh_main,
            items_data=[{'product': self.prod, 'quantity': Decimal('50.00')}]
        )
        ProductTransferService.approve_request(transfer_req, user=self.superadmin)

        # Now before execution, 180 units are reserved for a large sales order
        self.stock_main.qty_reserved = Decimal('180.00')
        self.stock_main.save()
        # On hand = 200, reserved = 180, available = 20 -> 50 cannot be moved!

        with self.assertRaises(ValidationError) as ctx:
            ProductTransferService.execute_transfer(transfer_req, user=self.superadmin)
        self.assertIn("غير كافٍ لإتمام التحويل", str(ctx.exception))
