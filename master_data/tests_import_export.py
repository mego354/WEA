import io
from decimal import Decimal
import openpyxl
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import User, Role
from catalog.models import Product, ProductCategory
from contacts.models import Contact
from inventory.models import Warehouse, InventoryStock
from master_data.models import Area
from purchases.models import PurchaseOrder
from sales.models import (
    CustomerAccount,
    CustomerTransaction,
    SalesOrder,
    SalesReturnOrder,
    Collection,
)
from treasury.models import Vault, VendorAccount, VendorPayment


class AllImportExportEndToEndTests(TestCase):
    def setUp(self):
        self.super_role, _ = Role.objects.get_or_create(
            name='superadmin', defaults={'display_name': 'Super Admin', 'is_super': True}
        )
        self.admin = User.objects.create_superuser(
            username='ie_admin', password='Password123!', email='ie_admin@test.local', role=self.super_role
        )
        self.area_cairo = Area.objects.create(name='القاهرة', code='IE-CAI')
        self.area_giza = Area.objects.create(name='الجيزة', code='IE-GIZ')
        self.c1 = Contact.objects.create(name='صيدلية النور', code='C001', is_customer=True, status='customer', area=self.area_cairo)
        self.c2 = Contact.objects.create(name='صيدلية الأمل', code='C002', is_customer=True, status='customer', area=self.area_giza)
        self.sup = Contact.objects.create(name='مورد الدواء', code='S001', is_supplier=True, is_customer=False, status='customer', area=self.area_cairo)

        self.acc1 = CustomerAccount.get_or_create_for_customer(self.c1)
        self.acc1.current_balance = Decimal('1000.00')
        self.acc1.due_this_month_balance = Decimal('200.00')
        self.acc1.save()
        self.acc2 = CustomerAccount.get_or_create_for_customer(self.c2)
        self.acc2.current_balance = Decimal('500.00')
        self.acc2.due_this_month_balance = Decimal('50.00')
        self.acc2.save()
        CustomerTransaction.objects.create(
            account=self.acc1, transaction_type='debit', reason='sales',
            transaction_date=timezone.localdate(), debit=Decimal('1000.00'), running_balance=Decimal('1000.00'),
            description='فاتورة مبيعات #1', created_by=self.admin,
        )
        CustomerTransaction.objects.create(
            account=self.acc2, transaction_type='credit', reason='collection',
            transaction_date=timezone.localdate(), credit=Decimal('200.00'), running_balance=Decimal('500.00'),
            description='تحصيل #1', created_by=self.admin,
        )

        self.wh = Warehouse.objects.create(name='المخزن الرئيسي', code='WH-IE-1', is_active=True)
        self.cat = ProductCategory.objects.create(name='أدوية عامة', code='CAT-IE-1')
        self.prod = Product.objects.create(name='بانادول', sku_code='PAN-1', category=self.cat, retail_price=Decimal('50.00'))
        InventoryStock.objects.create(warehouse=self.wh, product=self.prod, qty_on_hand=Decimal('10.00'))
        self.vault = Vault.objects.create(name='الخزينة الرئيسية', vault_type='cash', is_active=True, current_balance=Decimal('5000.00'))

        SalesOrder.objects.create(
            customer=self.c1, source_warehouse=self.wh, order_date=timezone.localdate(),
            status='invoiced', grand_total=Decimal('400.00'), created_by=self.admin,
        )
        SalesOrder.objects.create(
            customer=self.c2, source_warehouse=self.wh, order_date=timezone.localdate(),
            status='pending', grand_total=Decimal('250.00'), created_by=self.admin,
        )
        SalesReturnOrder.objects.create(
            customer=self.c1, order_date=timezone.localdate(), status='settled',
            grand_total=Decimal('100.00'), created_by=None,
        )
        Collection.objects.create(
            customer=self.c1, vault=self.vault, amount=Decimal('300.00'),
            collection_date=timezone.localdate(), created_by=self.admin,
        )
        PurchaseOrder.objects.create(
            supplier=self.sup, target_warehouse=self.wh, order_date=timezone.localdate(),
            status='settled', grand_total=Decimal('600.00'), created_by=None,
        )
        va = VendorAccount.get_or_create_for_supplier(self.sup)
        va.current_balance = Decimal('600.00')
        va.save()
        VendorPayment.objects.create(
            supplier=self.sup, vault=self.vault, payment_date=timezone.localdate(),
            amount=Decimal('200.00'), created_by=None,
        )

        self.client = Client()
        self.client.force_login(self.admin)

    def _parse_xlsx_rows(self, resp):
        self.assertEqual(resp.status_code, 200)
        self.assertIn('spreadsheetml', resp.get('Content-Type', ''))
        wb = openpyxl.load_workbook(io.BytesIO(resp.content), read_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        wb.close()
        return rows

    def test_all_44_export_endpoints_return_valid_xlsx(self):
        export_names = [
            'users_export', 'roles_export', 'audit_logs_export',
            'agreements_export', 'planned_visits_export', 'visits_export', 'visit_templates_export',
            'products_export', 'categories_export', 'contacts_export',
            'inventory_stock_export', 'warehouses_export', 'inventory_memos_export', 'product_transfers_export',
            'areas_export', 'expenses_export', 'tickets_export', 'requests_export', 'agreements_types_export',
            'purchase_orders_export', 'purchase_return_orders_export',
            'sales_orders_export', 'collections_export', 'accounting_customers_export',
            'customer_transactions_export', 'sales_return_orders_export',
            'vendor_payments_export', 'vendor_payment_requests_export', 'accounting_vendors_export',
            'vendor_transactions_export', 'vaults_export', 'vault_transactions_export',
            'performance_overview_export', 'performance_analysis_export',
            'performance_daily_export', 'performance_detailed_export',
            'report_ar_aging_export', 'report_trial_balance_export', 'report_agreements_roi_export',
            'report_customer_360_export', 'report_delivery_stock_export', 'report_net_sales_export',
            'report_item_purchases_export', 'report_item_sales_by_customer_export',
        ]
        for name in export_names:
            with self.subTest(export_endpoint=name):
                resp = self.client.get(reverse(name))
                rows = self._parse_xlsx_rows(resp)
                self.assertGreaterEqual(len(rows), 1, f"{name} returned empty workbook")

    def test_filtered_exports_match_filtered_data_only(self):
        # 1. Customer Accounts filtered by search & main_area
        rows_all = self._parse_xlsx_rows(self.client.get(reverse('accounting_customers_export')))
        rows_filtered = self._parse_xlsx_rows(self.client.get(reverse('accounting_customers_export') + '?search=النور'))
        rows_area = self._parse_xlsx_rows(self.client.get(reverse('accounting_customers_export') + f'?main_area={self.area_giza.id}'))
        self.assertEqual(len(rows_all) - 5, 2)
        self.assertEqual(len(rows_filtered) - 5, 1)
        self.assertEqual(len(rows_area) - 5, 1)
        # Verify due_this_month_balance header is included
        header_row = rows_all[4]
        self.assertIn('واجب السداد الشهر الحالي', header_row)

        # 2. Sales Orders filtered by status & preset=this_month; verify no 'المتبقي' column
        so_rows = self._parse_xlsx_rows(self.client.get(reverse('sales_orders_export') + '?status=invoiced&preset=this_month'))
        self.assertEqual(len(so_rows) - 5, 1)
        self.assertNotIn('المتبقي', so_rows[4])

        # 3. Customer Transactions filtered by type=debit & preset=this_month
        ct_rows = self._parse_xlsx_rows(self.client.get(reverse('customer_transactions_export') + '?type=debit&preset=this_month'))
        self.assertEqual(len(ct_rows) - 5, 1)

        # 4. Collections filtered by preset=this_month & main_area
        col_rows = self._parse_xlsx_rows(self.client.get(reverse('collections_export') + f'?preset=this_month&main_area={self.area_cairo.id}'))
        self.assertEqual(len(col_rows) - 5, 1)
        col_rows_empty = self._parse_xlsx_rows(self.client.get(reverse('collections_export') + f'?preset=this_month&main_area={self.area_giza.id}'))
        self.assertEqual(len(col_rows_empty) - 5, 0)

    def test_sales_returns_list_handles_null_created_by(self):
        resp = self.client.get(reverse('sales_return_orders_list'))
        self.assertEqual(resp.status_code, 200)

    def test_all_import_pages_and_templates_and_category_import_pipeline(self):
        entities = [
            'contacts', 'products', 'categories', 'areas', 'warehouses',
            'planned_visits', 'stock_adjustments', 'collections', 'vendor_payments', 'inventory_stock',
        ]
        for ent in entities:
            with self.subTest(import_entity=ent):
                r_page = self.client.get(reverse('excel_import', kwargs={'entity': ent}))
                self.assertEqual(r_page.status_code, 200)
                r_tpl = self.client.get(reverse('excel_import_template', kwargs={'entity': ent}))
                self.assertEqual(r_tpl.status_code, 200)
                wb = openpyxl.load_workbook(io.BytesIO(r_tpl.content), read_only=True)
                self.assertGreaterEqual(len(wb.sheetnames), 1)
                wb.close()

        # Legacy import endpoints
        for legacy in ('contacts_import', 'contacts_import_template', 'product_import', 'product_import_template'):
            resp = self.client.get(reverse(legacy))
            self.assertEqual(resp.status_code, 200)

        # End-to-end upload -> preview on categories
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = 'البيانات'
        ws.append(['الاسم', 'الكود', 'الوصف'])
        ws.append(['تصنيف مستورد اختباري', 'CAT-IMP-99', 'وصف اختباري'])
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        upload = SimpleUploadedFile('categories.xlsx', buf.read(), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        r_up = self.client.post(reverse('excel_import', kwargs={'entity': 'categories'}), {'file': upload, 'step': 'upload'})
        self.assertEqual(r_up.status_code, 200)
