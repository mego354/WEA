import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from decimal import Decimal
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.urls import reverse

from master_data.models import Area, SalesSettings
from accounts.models import Role
from contacts.models import Contact
from catalog.models import Product, ProductCategory
from inventory.models import Warehouse, InventoryStock
from sales.models import SalesOrder
from sales.services import SalesOrderService

User = get_user_model()


class RepresentativeSalesWarehouseTests(TestCase):
    """
    Automated test suite verifying:
    1. Every representative sale uses their designated default warehouse
    2. Client-submitted / forged warehouse IDs are rejected/overridden on server
    3. Required manager approval follows main area eligibility
    4. Anti-self-approval prevents reps from approving their own orders
    """

    def setUp(self):
        self.client = Client()

        # Areas
        self.cairo_main = Area.objects.create(code='CAI', name='القاهرة', area_type='governorate', parent=None)
        self.nasr_city = Area.objects.create(code='CAI-NC', name='مدينة نصر', area_type='subarea', parent=self.cairo_main)

        self.alex_main = Area.objects.create(code='ALX', name='الإسكندرية', area_type='governorate', parent=None)
        self.smouha = Area.objects.create(code='ALX-SM', name='سموحة', area_type='subarea', parent=self.alex_main)

        # Roles
        self.rep_role, _ = Role.objects.get_or_create(name='MedicalRep', defaults={'display_name': 'مندوب دعاية', 'is_rep': True})
        self.rep_role.is_rep = True
        self.rep_role.save()

        self.mgr_role, _ = Role.objects.get_or_create(name='AreaManager', defaults={'display_name': 'مدير منطقة', 'is_area_manager': True, 'is_rep': False})
        self.mgr_role.is_area_manager = True
        self.mgr_role.is_rep = False
        self.mgr_role.save()

        # Rep Cairo
        self.rep_cairo = User.objects.create_user(username='rep_cairo_sale', role=self.rep_role)
        self.rep_cairo.assigned_areas.add(self.nasr_city)

        # Managers
        self.mgr_cairo = User.objects.create_user(username='mgr_cairo_sale', role=self.mgr_role)
        self.mgr_cairo.assigned_areas.add(self.cairo_main)

        self.mgr_alex = User.objects.create_user(username='mgr_alex_sale', role=self.mgr_role)
        self.mgr_alex.assigned_areas.add(self.alex_main)

        # Customer & Product
        self.customer = Contact.objects.create(name='صيدلية الشفاء', is_customer=True, area=self.nasr_city)
        self.category = ProductCategory.objects.create(name='أدوية')
        self.product = Product.objects.create(
            name='كونجستال أقراص', sku_code='CONG-TAB',
            retail_price=Decimal('25.00'), default_purchase_cost=Decimal('15.00'), category=self.category
        )

        # Rep Warehouse & Another Warehouse
        self.rep_wh = self.rep_cairo.get_default_warehouse()
        if not self.rep_wh:
            self.rep_wh = Warehouse.objects.create(
                name='مخزن عهدة المندوب', code='WH-REP-C', assigned_user=self.rep_cairo,
                area=self.nasr_city, is_rep_warehouse=True
            )
        self.other_wh = Warehouse.objects.create(
            name='مخزن فرع آخر', code='WH-OTHER', area=self.smouha, is_rep_warehouse=False
        )

        # Populate stock in rep warehouse
        InventoryStock.objects.create(
            warehouse=self.rep_wh,
            product=self.product,
            qty_on_hand=Decimal('50.00'),
            qty_reserved=Decimal('0.00'),
            product_cost=Decimal('15.00')
        )

        # Require manager approval
        settings = SalesSettings.get_settings()
        settings.require_manager_approval = True
        settings.save()

    def test_sales_enforces_representative_warehouse(self):
        """A representative's sale automatically resolves and enforces their designated warehouse."""
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
        """Attempting to create a sale under another warehouse raises ValidationError for rep."""
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
        """A manager in the same main area (Cairo) can approve the sale; Alex manager cannot."""
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
