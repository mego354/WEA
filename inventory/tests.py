from decimal import Decimal
import io
import openpyxl
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from catalog.models import Product, ProductCategory
from inventory.models import Warehouse, InventoryStock

User = get_user_model()


class InventoryExcelExportTestCase(TestCase):
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
