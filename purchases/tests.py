import json
from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from contacts.models import Contact
from catalog.models import Product, ProductCategory
from inventory.models import Warehouse, InventoryStock, InventoryLot, InventoryMemo
from purchases.models import PurchaseOrder, PurchaseOrderItem, PurchaseOrderComment, PurchaseReturnOrder, PurchaseReturnOrderItem
from purchases.services import PurchaseOrderService, PurchaseReturnOrderService
from treasury.models import VendorAccount, VendorTransaction

User = get_user_model()


class PurchasesModelsAndViewsTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(
            email='testpurchases@weapharma.com',
            username='testpurchases@weapharma.com',
            password='Password123!',
            first_name='Purchasing',
            last_name='Manager'
        )
        self.client = Client()
        self.client.login(username='testpurchases@weapharma.com', password='Password123!')

        self.warehouse = Warehouse.objects.create(
            name='المخزن الرئيسي - الإسكندرية',
            code='WH-MAIN',
            is_active=True
        )

        self.supplier = Contact.objects.create(
            name='مصنع اورجانيك للمكملات الغذائية بنها',
            is_supplier=True,
            mobile='01099887766',
            created_by=self.user
        )
        VendorAccount.get_or_create_for_supplier(self.supplier)

        self.category = ProductCategory.objects.create(
            name='مكملات غذائية',
            code='SUPP'
        )

        self.product = Product.objects.create(
            name='Geron',
            sku_code='GER-001',
            category=self.category,
            retail_price=Decimal('18.80'),
            default_purchase_cost=Decimal('18.80'),
            unit='علبة'
        )

        self.order = PurchaseOrder.objects.create(
            serial_num=16,
            order_number='#16',
            supplier=self.supplier,
            target_warehouse=self.warehouse,
            order_date='2026-09-26',
            delivery_time='2026-09-28',
            delivery_agent='مندوب الشحن السريع',
            status='pending',
            notes='طلب توريد تجريبي مطابق للريفرنس',
            shipping_fees=Decimal('400.00'),
            custom_discount_amount=Decimal('0.00'),
            created_by=self.user
        )

        self.order_item = PurchaseOrderItem.objects.create(
            order=self.order,
            product=self.product,
            quantity=Decimal('3109'),
            unit_price=Decimal('18.80'),
            product_batch_number='269222',
            product_expiry_date='2028-09-26',
            discount_percentage=Decimal('0.00')
        )
        self.order.recalculate_totals()

    def test_purchase_order_calculations_and_properties(self):
        # 3109 * 18.80 = 58449.20; + 400 shipping = 58849.20
        self.assertEqual(self.order.subtotal, Decimal('58449.20'))
        self.assertEqual(self.order.grand_total, Decimal('58849.20'))
        self.assertEqual(self.order.status_label_en, 'Pending')
        self.assertEqual(self.order.status_label_ar, 'قيد الانتظار')
        self.assertEqual(self.order.supplier.initials, 'ما')
        self.assertEqual(self.order.order_number, '#16')

    def test_purchase_orders_list_view(self):
        response = self.client.get(reverse('purchase_orders_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'مصنع اورجانيك للمكملات الغذائية بنها')
        self.assertContains(response, '58849')

    def test_purchase_orders_list_filtering(self):
        # Filter by supplier
        resp_sup = self.client.get(reverse('purchase_orders_list'), {'supplier': self.supplier.id})
        self.assertEqual(resp_sup.status_code, 200)
        self.assertContains(resp_sup, 'مصنع اورجانيك')

        # Filter by status
        resp_status = self.client.get(reverse('purchase_orders_list'), {'status': 'pending'})
        self.assertEqual(resp_status.status_code, 200)
        self.assertContains(resp_status, 'قيد الانتظار')

        # Filter by search
        resp_search = self.client.get(reverse('purchase_orders_list'), {'search': '16'})
        self.assertEqual(resp_search.status_code, 200)
        self.assertContains(resp_search, 'مصنع اورجانيك')

    def test_purchase_order_detail_view(self):
        detail_url = reverse('purchase_order_detail', args=[self.order.id])
        response = self.client.get(detail_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'مصنع اورجانيك للمكملات الغذائية بنها')
        self.assertContains(response, 'Geron')
        self.assertContains(response, '3109')
        self.assertContains(response, '58849')

    def test_purchase_order_create_view_get(self):
        create_url = reverse('purchase_order_create')
        response = self.client.get(create_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'أمر مشتريات جديد')

    def test_purchase_order_create_view_post(self):
        create_url = reverse('purchase_order_create')
        data = {
            'supplier': self.supplier.id,
            'warehouse': self.warehouse.id,
            'order_date': '2026-10-10',
            'expected_delivery_date': '2026-10-12',
            'delivery_agent': 'مندوب الشركة',
            'delivery_time': 'صباحاً',
            'shipping_fees': '250.00',
            'custom_discount_percentage': '0.00',
            'notes': 'طلب جديد للاختبار',
            'product_id[]': [self.product.id],
            'quantity[]': ['100'],
            'unit_price[]': ['18.80'],
            'batch_number[]': ['B-9988'],
            'expiry_date[]': ['2028-10-10'],
            'discount_percentage[]': ['0'],
        }
        response = self.client.post(create_url, data, follow=True)
        self.assertEqual(response.status_code, 200)
        new_po = PurchaseOrder.objects.filter(notes='طلب جديد للاختبار').first()
        self.assertIsNotNone(new_po)
        self.assertEqual(new_po.items.count(), 1)
        # 100 * 18.80 = 1880; + 250 ship = 2130.00
        self.assertEqual(new_po.grand_total, Decimal('2130.00'))

    def test_purchase_order_ajax_status_update(self):
        status_url = reverse('purchase_order_update_status_ajax', args=[self.order.id])
        resp = self.client.post(
            status_url,
            {'status': 'approved'},
            headers={'x-requested-with': 'XMLHttpRequest'}
        )
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.content)
        self.assertEqual(data.get('status'), 'ok')
        self.assertEqual(data.get('new_status'), 'approved')
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'approved')

    def test_purchase_order_add_comment(self):
        comment_url = reverse('purchase_order_add_comment', args=[self.order.id])
        resp = self.client.post(comment_url, {'comment': 'تم التواصل مع المورد لتأكيد تاريخ الشحن'}, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(PurchaseOrderComment.objects.filter(order=self.order).count(), 1)
        self.assertIn('تم التواصل مع المورد', self.order.comments.first().text)

    def test_purchase_orders_export_excel(self):
        import io
        import openpyxl
        export_url = reverse('purchase_orders_export')
        response = self.client.get(export_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        self.assertIn('.xlsx', response['Content-Disposition'])
        wb = openpyxl.load_workbook(io.BytesIO(response.content))
        ws = wb.active
        self.assertTrue(ws.sheet_view.rightToLeft)
        found = any('مصنع اورجانيك' in str(cell.value) for row in ws.iter_rows() for cell in row)
        self.assertTrue(found)

    def test_purchase_return_orders_list(self):
        returns_url = reverse('purchase_return_orders_list')
        response = self.client.get(returns_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'المرتجعات')

    def test_purchase_order_split(self):
        # Split 1000 units from the 3109 into a child order
        child = PurchaseOrderService.split_order(
            self.order,
            {self.order_item.id: Decimal('1000')},
            self.user
        )
        self.assertIsNotNone(child)
        self.assertTrue(child.is_split)
        self.assertEqual(child.parent_order, self.order)
        self.assertEqual(child.items.count(), 1)
        self.assertEqual(child.items.first().quantity, Decimal('1000'))
        self.assertEqual(child.grand_total, Decimal('18800.00'))

        self.order.refresh_from_db()
        self.assertTrue(self.order.is_split)
        remaining_item = self.order.items.first()
        self.assertEqual(remaining_item.quantity, Decimal('2109'))
        # 2109 * 18.80 = 39649.20 + 400 shipping = 40049.20
        self.assertEqual(self.order.grand_total, Decimal('40049.20'))

    def test_purchase_return_order_lifecycle(self):
        # 1. Setup warehouse stock and lot
        stock = InventoryStock.objects.create(
            warehouse=self.warehouse,
            product=self.product,
            qty_on_hand=Decimal('100.00'),
            product_cost=Decimal('18.80')
        )
        lot = InventoryLot.objects.create(
            stock=stock,
            batch_number='269222',
            quantity=Decimal('100.00'),
            expiry_date='2028-09-26'
        )

        vendor_acc = VendorAccount.get_or_create_for_supplier(self.supplier)
        vendor_acc.current_balance = Decimal('10000.00')
        vendor_acc.save()

        # 2. Create return order
        items_data = [{
            'product': self.product,
            'quantity': Decimal('20.00'),
            'unit_price': Decimal('18.80'),
            'batch_number': '269222',
            'expiry_date': '2028-09-26'
        }]
        ret_order = PurchaseReturnOrderService.create_return_order(
            supplier=self.supplier,
            warehouse=self.warehouse,
            order_date='2026-10-10',
            items_data=items_data,
            user=self.user,
            notes='مرتجع تجريبي'
        )
        self.assertEqual(ret_order.status, 'pending')
        self.assertEqual(ret_order.grand_total, Decimal('376.00'))

        # 3. Approve return order
        PurchaseReturnOrderService.approve_return_order(ret_order, self.user)
        ret_order.refresh_from_db()
        self.assertEqual(ret_order.status, 'approved')

        # 4. Deliver / Dispatch unstocking
        PurchaseReturnOrderService.deliver_return_order(ret_order, self.user)
        ret_order.refresh_from_db()
        self.assertEqual(ret_order.status, 'delivered')
        self.assertIsNotNone(ret_order.memo)
        self.assertEqual(ret_order.memo.memo_type, 'outward')

        stock.refresh_from_db()
        lot.refresh_from_db()
        self.assertEqual(stock.qty_on_hand, Decimal('80.00'))
        self.assertEqual(lot.quantity, Decimal('80.00'))

        # 5. Financial Settlement (Debit Note)
        PurchaseReturnOrderService.settle_return_order(ret_order, self.user)
        ret_order.refresh_from_db()
        self.assertEqual(ret_order.status, 'settled')

        vendor_acc.refresh_from_db()
        self.assertEqual(vendor_acc.current_balance, Decimal('9624.00'))
        tx = VendorTransaction.objects.filter(reason='purchase_return').first()
        self.assertIsNotNone(tx)
        self.assertEqual(tx.debit, Decimal('376.00'))

    def test_purchase_return_order_insufficient_stock(self):
        InventoryStock.objects.create(
            warehouse=self.warehouse,
            product=self.product,
            qty_on_hand=Decimal('10.00')
        )
        items_data = [{
            'product': self.product,
            'quantity': Decimal('50.00'),
            'unit_price': Decimal('18.80')
        }]
        ret_order = PurchaseReturnOrderService.create_return_order(
            supplier=self.supplier,
            warehouse=self.warehouse,
            order_date='2026-10-10',
            items_data=items_data,
            user=self.user
        )
        with self.assertRaises(ValidationError):
            PurchaseReturnOrderService.deliver_return_order(ret_order, self.user)

    def test_purchase_return_order_cancel(self):
        items_data = [{
            'product': self.product,
            'quantity': Decimal('5.00'),
            'unit_price': Decimal('18.80')
        }]
        ret_order = PurchaseReturnOrderService.create_return_order(
            supplier=self.supplier,
            warehouse=self.warehouse,
            order_date='2026-10-10',
            items_data=items_data,
            user=self.user
        )
        PurchaseReturnOrderService.cancel_return_order(ret_order, self.user)
        ret_order.refresh_from_db()
        self.assertEqual(ret_order.status, 'cancelled')

    def test_purchase_return_order_views_crud_and_export(self):
        # 1. GET create
        create_resp = self.client.get(reverse('purchase_return_order_create'))
        self.assertEqual(create_resp.status_code, 200)

        # 2. POST create
        post_data = {
            'supplier': self.supplier.id,
            'warehouse': self.warehouse.id,
            'order_date': '2026-10-11',
            'delivery_agent': 'مندوب الاسترجاع',
            'notes': 'إنشاء مرتجع عبر الواجهة',
            'product_id[]': [self.product.id],
            'quantity[]': ['15'],
            'unit_price[]': ['18.80'],
            'batch_number[]': ['269222'],
            'expiry_date[]': ['2028-09-26'],
        }
        post_resp = self.client.post(reverse('purchase_return_order_create'), post_data, follow=True)
        self.assertEqual(post_resp.status_code, 200)
        ret = PurchaseReturnOrder.objects.filter(notes='إنشاء مرتجع عبر الواجهة').first()
        self.assertIsNotNone(ret)
        self.assertEqual(ret.items.count(), 1)
        self.assertEqual(ret.grand_total, Decimal('282.00'))

        # 3. GET detail
        detail_resp = self.client.get(reverse('purchase_return_order_detail', args=[ret.id]))
        self.assertEqual(detail_resp.status_code, 200)
        self.assertContains(detail_resp, ret.order_number)

        # 4. Action transition POST (approve)
        act_resp = self.client.post(reverse('purchase_return_order_action', args=[ret.id, 'approve']), follow=True)
        self.assertEqual(act_resp.status_code, 200)
        ret.refresh_from_db()
        self.assertEqual(ret.status, 'approved')

        # 5. GET print
        print_resp = self.client.get(reverse('purchase_return_order_print', args=[ret.id]))
        self.assertEqual(print_resp.status_code, 200)
        self.assertContains(print_resp, ret.order_number)

        # 6. GET export
        export_resp = self.client.get(reverse('purchase_return_orders_export'))
        self.assertEqual(export_resp.status_code, 200)
        self.assertEqual(export_resp['Content-Type'], 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

    def test_reference_url_aliases(self):
        # /purchase-orders/
        resp_po = self.client.get('/purchase-orders/')
        self.assertEqual(resp_po.status_code, 200)
        self.assertContains(resp_po, 'مصنع اورجانيك')

        # /purchase-return-orders/
        resp_returns = self.client.get('/purchase-return-orders/')
        self.assertEqual(resp_returns.status_code, 200)
        self.assertContains(resp_returns, 'المرتجعات')

        # /vendor-payments/
        resp_pay = self.client.get('/vendor-payments/')
        self.assertEqual(resp_pay.status_code, 200)

        # /vendor-payment-requests/
        resp_req = self.client.get('/vendor-payment-requests/')
        self.assertEqual(resp_req.status_code, 200)

        # /accounting/vendors/
        resp_vnd = self.client.get('/accounting/vendors/')
        self.assertEqual(resp_vnd.status_code, 200)

        # /accounting/vendor-transactions/
        resp_tx = self.client.get('/accounting/vendor-transactions/')
        self.assertEqual(resp_tx.status_code, 200)

