from decimal import Decimal
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from accounts.models import Role
from master_data.models import Area
from contacts.models import Contact
from catalog.models import Product, ProductCategory
from inventory.models import Warehouse, InventoryStock
from sales.models import SalesOrder, SalesOrderItem
from sales.services import SalesOrderService

User = get_user_model()


class SalesWorkflowAndValidationTests(TestCase):
    def setUp(self):
        # Create governorate and brick
        self.cairo = Area.objects.create(code='CAI', name='القاهرة', area_type='governorate', parent=None)
        self.nasr_city = Area.objects.create(code='NC', name='مدينة نصر', area_type='subarea', parent=self.cairo)

        # Create roles
        self.super_role, _ = Role.objects.get_or_create(name='superadmin', defaults={'is_super': True})
        self.rep_role, _ = Role.objects.get_or_create(name='MedicalRep', defaults={'is_rep': True, 'is_sales_team': True})

        # Users
        self.superadmin = User.objects.create_superuser(username='superadmin', email='super@test.com', password='pass')
        self.rep = User.objects.create_user(username='sales_rep', first_name='علي', last_name='حسن', role=self.rep_role)
        self.rep.assigned_areas.add(self.nasr_city)

        # Customer
        self.customer = Contact.objects.create(
            name='صيدلية الشفاء',
            is_customer=True,
            area=self.nasr_city,
            created_by=self.rep
        )

        # Warehouses
        self.warehouse = Warehouse.objects.create(name='المخزن الرئيسي', code='WH-MAIN', is_main=True, area=self.cairo)

        # Category and Products
        self.cat = ProductCategory.objects.create(name='أدوية')
        self.prod1 = Product.objects.create(name='بنادول إكسترا', sku_code='PAN-EX', retail_price=Decimal('50.00'), category=self.cat)
        self.prod2 = Product.objects.create(name='كونجستال', sku_code='CONG-1', retail_price=Decimal('30.00'), category=self.cat)

        # Initial Stock: prod1 = 100 units, prod2 = 50 units
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
        """Test calculation of line-item discounts, custom order discount, shipping, and grand total."""
        items_data = [
            {'product': self.prod1, 'quantity': Decimal('10.00'), 'unit_price': Decimal('50.00'), 'discount_percentage': Decimal('10.00')},
            # 10 * 50 = 500, discount 10% = 50, item subtotal = 450
            {'product': self.prod2, 'quantity': Decimal('5.00'), 'unit_price': Decimal('30.00'), 'discount_percentage': Decimal('0.00')},
            # 5 * 30 = 150, discount 0% = 0, item subtotal = 150
            # Net items = 450 + 150 = 600
        ]
        order = SalesOrderService.create_order(
            customer=self.customer,
            source_warehouse=self.warehouse,
            order_date='2026-11-01',
            items_data=items_data,
            user=self.superadmin,
            custom_discount_percentage=Decimal('5.00'),  # 5% of 600 = 30
            shipping_fees=Decimal('25.00'),               # + 25
            notes='Test order discounts'
        )

        self.assertEqual(order.subtotal, Decimal('650.00'))  # Gross: 500 + 150
        self.assertEqual(order.items_discount_total, Decimal('50.00'))  # Line discounts
        self.assertEqual(order.custom_discount_amount, Decimal('30.00'))  # 5% of 600
        self.assertEqual(order.shipping_fees, Decimal('25.00'))
        # Grand total = (650 - 50) - 30 + 25 = 595.00
        self.assertEqual(order.grand_total, Decimal('595.00'))

    def test_insufficient_stock_prevents_order_creation(self):
        """Creating an order for more than available stock is rejected when validate_stock=True."""
        items_data = [
            {'product': self.prod1, 'quantity': Decimal('150.00'), 'unit_price': Decimal('50.00')},  # Available is 100
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
        """Reserved stock must be deducted from available stock."""
        # Reserve 90 of prod1
        self.stock1.qty_reserved = Decimal('90.00')
        self.stock1.save()
        # Available is now 10 (100 on hand - 90 reserved)

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
        """Negative quantities, prices, invalid discounts, or negative shipping fees are rejected."""
        # Negative quantity
        with self.assertRaises(ValidationError):
            SalesOrderService.create_order(
                customer=self.customer,
                source_warehouse=self.warehouse,
                order_date='2026-11-01',
                items_data=[{'product': self.prod1, 'quantity': Decimal('-5.00'), 'unit_price': Decimal('50.00')}],
                user=self.superadmin
            )

        # Discount > 100%
        with self.assertRaises(ValidationError):
            SalesOrderService.create_order(
                customer=self.customer,
                source_warehouse=self.warehouse,
                order_date='2026-11-01',
                items_data=[{'product': self.prod1, 'quantity': Decimal('5.00'), 'unit_price': Decimal('50.00'), 'discount_percentage': Decimal('120.00')}],
                user=self.superadmin
            )

        # Custom discount > 100%
        with self.assertRaises(ValidationError):
            SalesOrderService.create_order(
                customer=self.customer,
                source_warehouse=self.warehouse,
                order_date='2026-11-01',
                items_data=[{'product': self.prod1, 'quantity': Decimal('5.00'), 'unit_price': Decimal('50.00')}],
                user=self.superadmin,
                custom_discount_percentage=Decimal('150.00')
            )

        # Negative shipping
        with self.assertRaises(ValidationError):
            SalesOrderService.create_order(
                customer=self.customer,
                source_warehouse=self.warehouse,
                order_date='2026-11-01',
                items_data=[{'product': self.prod1, 'quantity': Decimal('5.00'), 'unit_price': Decimal('50.00')}],
                user=self.superadmin,
                shipping_fees=Decimal('-20.00')
            )

