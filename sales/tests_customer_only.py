from decimal import Decimal
from django.core.exceptions import ValidationError
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from django.contrib.auth import get_user_model

from accounts.models import Role
from catalog.models import Product, ProductCategory
from contacts.models import Contact
from inventory.models import Warehouse, InventoryStock
from master_data.excel_importers import CollectionsExcelImporter
from master_data.models import Area, SalesSettings
from sales.models import SalesOrder, SalesOrderItem, CustomerAccount, Collection
from sales.services import SalesOrderService, SalesReturnOrderService, CollectionService
from treasury.models import Vault

User = get_user_model()


class SalesCustomerOnlySelectorsAndHistoricalLeadTests(TestCase):
    """Comprehensive tests for Req C: Customer-only selectors & preserved historical Lead workflows."""

    def setUp(self):
        self.client = Client()

        self.cairo = Area.objects.create(name='القاهرة', code='CAI_C')
        self.nasr = Area.objects.create(name='مدينة نصر', code='NSR_C', parent=self.cairo)

        super_role = Role.objects.filter(name='superadmin').first()
        rep_role = Role.objects.filter(name='rep').first()

        self.admin = User.objects.create_user(
            username='c_admin', email='c_admin@wea.com', password='Password123!',
            is_superuser=True, is_staff=True, role=super_role,
        )
        self.rep = User.objects.create_user(
            username='c_rep', email='c_rep@wea.com', password='Password123!',
            role=rep_role,
        )
        self.rep.assigned_areas.add(self.nasr)

        self.wh = Warehouse.objects.create(name='مخزن اختبار المبيعات', code='WH-C1', area=self.cairo, is_main=True)
        self.vault = Vault.objects.create(serial_num=8801, name='خزنة اختبار المبيعات', area=self.cairo)
        self.cat = ProductCategory.objects.create(name='أدوية عامة')
        self.product = Product.objects.create(
            name='دواء اختبار', sku_code='PRD-C1', category=self.cat,
            retail_price=Decimal('100.00'), default_purchase_cost=Decimal('50.00'),
            is_active=True, sellable=True,
        )
        InventoryStock.objects.create(
            warehouse=self.wh, product=self.product,
            qty_on_hand=Decimal('100.00'), qty_reserved=Decimal('0.00'),
            product_cost=Decimal('50.00'),
        )

        self.cust_active = Contact.objects.create(
            name='صيدلية العميل الفعلي', code='CUST01',
            is_customer=True, status='customer', area=self.cairo, brick=self.nasr, created_by=self.rep,
        )
        self.lead_fresh = Contact.objects.create(
            name='صيدلية عميل محتمل جديد', code='LEAD01',
            is_customer=True, status='lead', area=self.cairo, brick=self.nasr, created_by=self.rep,
        )
        self.lead_historical = Contact.objects.create(
            name='صيدلية عميل محتمل تاريخي', code='LEAD02',
            is_customer=True, status='lead', area=self.cairo, brick=self.nasr, created_by=self.rep,
        )
        self.cust_inactive = Contact.objects.create(
            name='صيدلية غير نشطة', code='INACT01',
            is_customer=True, status='inactive', area=self.cairo, brick=self.nasr, created_by=self.rep,
        )
        self.supplier_only = Contact.objects.create(
            name='مورد فقط', code='SUP01',
            is_customer=False, is_supplier=True, status='customer', area=self.cairo, brick=self.nasr, created_by=self.rep,
        )

        # Historical invoiced SalesOrder for lead_historical (simulating existing DB records)
        self.historical_lead_order = SalesOrder.objects.create(
            customer=self.lead_historical,
            source_warehouse=self.wh,
            order_date=timezone.localdate(),
            status='invoiced',
            subtotal=Decimal('500.00'),
            grand_total=Decimal('500.00'),
            created_by=self.admin,
        )
        SalesOrderItem.objects.create(
            order=self.historical_lead_order, product=self.product,
            quantity=Decimal('5.00'), unit_price=Decimal('100.00'),
        )
        acc = CustomerAccount.get_or_create_for_customer(self.lead_historical)
        acc.current_balance = Decimal('500.00')
        acc.save(update_fields=['current_balance'])

        # Editable pending historical SalesOrder for lead_historical
        self.historical_pending_lead_order = SalesOrder.objects.create(
            customer=self.lead_historical,
            source_warehouse=self.wh,
            order_date=timezone.localdate(),
            status='pending',
            subtotal=Decimal('200.00'),
            grand_total=Decimal('200.00'),
            created_by=self.admin,
        )
        SalesOrderItem.objects.create(
            order=self.historical_pending_lead_order, product=self.product,
            quantity=Decimal('2.00'), unit_price=Decimal('100.00'),
        )

    def test_sales_customer_search_api_excludes_leads_and_inactive_while_visits_keep_leads(self):
        """Sales customer search API returns ONLY status='customer'; Visits search API still includes leads."""
        self.client.force_login(self.admin)

        res_sales = self.client.get(reverse('sales_customers_search_api') + '?q=صيدلية')
        self.assertEqual(res_sales.status_code, 200)
        sales_ids = {r['id'] for r in res_sales.json()['results']}
        self.assertIn(self.cust_active.id, sales_ids)
        self.assertNotIn(self.lead_fresh.id, sales_ids)
        self.assertNotIn(self.lead_historical.id, sales_ids)
        self.assertNotIn(self.cust_inactive.id, sales_ids)
        self.assertNotIn(self.supplier_only.id, sales_ids)

        # Visits customer search API STILL returns leads (never broken!)
        res_visits = self.client.get(reverse('customers_search_api') + '?q=صيدلية')
        self.assertEqual(res_visits.status_code, 200)
        visit_ids = {r['id'] for r in res_visits.json()['results']}
        self.assertIn(self.cust_active.id, visit_ids)
        self.assertIn(self.lead_fresh.id, visit_ids)
        self.assertNotIn(self.cust_inactive.id, visit_ids)

    def test_new_sales_order_rejects_lead_and_inactive_and_accepts_customer(self):
        """New SalesOrder strictly rejects lead/inactive (service + HTTP POST) and accepts customer."""
        items = [{'product': self.product, 'quantity': 2, 'unit_price': Decimal('100.00'), 'discount_percentage': Decimal('0')}]

        with self.assertRaises(ValidationError):
            SalesOrderService.create_order(self.lead_fresh, self.wh, timezone.localdate(), items, self.admin)
        with self.assertRaises(ValidationError):
            SalesOrderService.create_order(self.cust_inactive, self.wh, timezone.localdate(), items, self.admin)

        self.client.force_login(self.admin)
        # Manipulated POST with lead ID
        res_lead = self.client.post(reverse('sales_order_create'), {
            'customer': self.lead_fresh.id,
            'warehouse': self.wh.id,
            'order_date': timezone.localdate().isoformat(),
            'product_id[]': [str(self.product.id)],
            'quantity[]': ['2'],
            'unit_price[]': ['100'],
            'discount_percentage[]': ['0'],
        })
        self.assertEqual(res_lead.status_code, 200)
        self.assertFalse(SalesOrder.objects.filter(customer=self.lead_fresh).exists())

        # Valid POST with active customer
        res_ok = self.client.post(reverse('sales_order_create'), {
            'customer': self.cust_active.id,
            'warehouse': self.wh.id,
            'order_date': timezone.localdate().isoformat(),
            'product_id[]': [str(self.product.id)],
            'quantity[]': ['2'],
            'unit_price[]': ['100'],
            'discount_percentage[]': ['0'],
        })
        self.assertEqual(res_ok.status_code, 302)
        self.assertTrue(SalesOrder.objects.filter(customer=self.cust_active).exists())

    def test_sales_order_edit_preserves_existing_lead_but_rejects_switching_to_other_lead(self):
        """Editing historical lead order allows keeping same lead, rejects switching to another lead/inactive."""
        self.client.force_login(self.admin)

        # GET edit form includes current historical lead customer
        res_get = self.client.get(reverse('sales_order_edit', args=[self.historical_pending_lead_order.pk]))
        self.assertEqual(res_get.status_code, 200)
        self.assertContains(res_get, self.lead_historical.name)

        # POST keeping same historical lead succeeds
        res_same = self.client.post(reverse('sales_order_edit', args=[self.historical_pending_lead_order.pk]), {
            'customer': self.lead_historical.id,
            'warehouse': self.wh.id,
            'order_date': timezone.localdate().isoformat(),
            'notes': 'تعديل ملاحظات الطلب التاريخي',
            'product_id[]': [str(self.product.id)],
            'quantity[]': ['3'],
            'unit_price[]': ['100'],
            'discount_percentage[]': ['0'],
        })
        self.assertEqual(res_same.status_code, 302)
        self.historical_pending_lead_order.refresh_from_db()
        self.assertEqual(self.historical_pending_lead_order.customer_id, self.lead_historical.id)

        # POST switching to a DIFFERENT lead fails
        res_other_lead = self.client.post(reverse('sales_order_edit', args=[self.historical_pending_lead_order.pk]), {
            'customer': self.lead_fresh.id,
            'warehouse': self.wh.id,
            'order_date': timezone.localdate().isoformat(),
            'product_id[]': [str(self.product.id)],
            'quantity[]': ['2'],
            'unit_price[]': ['100'],
            'discount_percentage[]': ['0'],
        })
        self.assertEqual(res_other_lead.status_code, 200)
        self.historical_pending_lead_order.refresh_from_db()
        self.assertEqual(self.historical_pending_lead_order.customer_id, self.lead_historical.id)

    def test_sales_return_allowed_for_historical_lead_order(self):
        """Creating a SalesReturnOrder against an existing historical Lead SalesOrder is preserved."""
        orig_item = self.historical_lead_order.items.first()
        ret = SalesReturnOrderService.create_return_order(
            sales_order=self.historical_lead_order,
            target_warehouse=self.wh,
            order_date=timezone.localdate(),
            items_data=[{
                'original_item': orig_item,
                'product': self.product,
                'quantity': Decimal('1.00'),
                'unit_price': Decimal('100.00'),
                'condition': 'resalable',
            }],
            user=self.admin,
            notes='مرتجع على طلب تاريخي لعميل محتمل',
        )
        self.assertEqual(ret.customer_id, self.lead_historical.id)
        self.assertEqual(ret.status, 'settled')

    def test_collections_allow_historical_lead_settlement_and_reject_fresh_lead_or_inactive(self):
        """Collections allow customer & historical lead settlement, reject fresh unrelated lead & inactive."""
        # Historical lead with existing order/balance succeeds
        col = CollectionService.record_collection(
            customer=self.lead_historical,
            vault=self.vault,
            amount=Decimal('100.00'),
            user=self.admin,
            sales_order=self.historical_lead_order,
        )
        self.assertEqual(col.customer_id, self.lead_historical.id)

        # Brand-new lead with no history is rejected
        with self.assertRaises(ValidationError):
            CollectionService.record_collection(
                customer=self.lead_fresh,
                vault=self.vault,
                amount=Decimal('50.00'),
                user=self.admin,
            )

        # Inactive contact is rejected
        with self.assertRaises(ValidationError):
            CollectionService.record_collection(
                customer=self.cust_inactive,
                vault=self.vault,
                amount=Decimal('50.00'),
                user=self.admin,
            )

        # GET /sales/collections/create/?order_id=<historical_lead_order> preloads historical lead cleanly
        self.client.force_login(self.admin)
        res_get = self.client.get(reverse('collection_create') + f'?order_id={self.historical_lead_order.id}')
        self.assertEqual(res_get.status_code, 200)
        self.assertEqual(res_get.context['selected_customer_id'], self.lead_historical.id)

        # Historical lead order remains visible in lists & detail
        self.assertContains(self.client.get(reverse('sales_orders_list')), self.lead_historical.name)
        self.assertEqual(self.client.get(reverse('sales_order_detail', args=[self.historical_lead_order.pk])).status_code, 200)

    def test_collections_excel_importer_customer_only_and_historical_lead(self):
        """CollectionsExcelImporter accepts customer & historical lead, rejects fresh lead & inactive."""
        importer = CollectionsExcelImporter(self.admin)
        importer.prepare_context()

        _, status_ok, errs_ok = importer.validate_row(2, {
            'customer': self.cust_active.code,
            'vault': self.vault.name,
            'amount': '100',
        }, set())
        self.assertEqual(status_ok, 'create', errs_ok)

        _, status_hist, errs_hist = importer.validate_row(3, {
            'customer': self.lead_historical.code,
            'vault': self.vault.name,
            'amount': '100',
            'sales_order': self.historical_lead_order.order_number,
        }, set())
        self.assertEqual(status_hist, 'create', errs_hist)

        _, status_fresh, errs_fresh = importer.validate_row(4, {
            'customer': self.lead_fresh.code,
            'vault': self.vault.name,
            'amount': '100',
        }, set())
        self.assertEqual(status_fresh, 'error')
        self.assertTrue(errs_fresh)

        _, status_inact, errs_inact = importer.validate_row(5, {
            'customer': self.cust_inactive.code,
            'vault': self.vault.name,
            'amount': '100',
        }, set())
        self.assertEqual(status_inact, 'error')
        self.assertTrue(errs_inact)
