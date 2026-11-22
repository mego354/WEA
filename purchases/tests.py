import datetime
import json
from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone

from accounts.models import Role, SecurityAuditLog
from master_data.models import Area
from contacts.models import Contact
from catalog.models import Product, ProductCategory
from inventory.models import Warehouse, InventoryStock, InventoryLot, InventoryMemo
from purchases.models import PurchaseOrder, PurchaseOrderItem, PurchaseOrderComment, PurchaseReturnOrder, PurchaseReturnOrderItem
from purchases.services import PurchaseOrderService, PurchaseReturnOrderService
from treasury.models import Vault, VendorAccount, VendorTransaction, VendorPayment
from treasury.services import TreasuryService

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
        self.assertEqual(data.get('new_status'), 'settled')
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'settled')

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
        self.assertEqual(ret_order.status, 'settled')
        self.assertEqual(ret_order.grand_total, Decimal('376.00'))
        self.assertIsNotNone(ret_order.memo)
        self.assertEqual(ret_order.memo.memo_type, 'outward')

        stock.refresh_from_db()
        lot.refresh_from_db()
        self.assertEqual(stock.qty_on_hand, Decimal('80.00'))
        self.assertEqual(lot.quantity, Decimal('80.00'))

        vendor_acc.refresh_from_db()
        self.assertEqual(vendor_acc.current_balance, Decimal('9624.00'))
        tx = VendorTransaction.objects.filter(reason='purchase_returns').first()
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
        with self.assertRaises(ValidationError):
            PurchaseReturnOrderService.create_return_order(
                supplier=self.supplier,
                warehouse=self.warehouse,
                order_date='2026-10-10',
                items_data=items_data,
                user=self.user
            )

    def test_purchase_return_order_cancel(self):
        InventoryStock.objects.create(
            warehouse=self.warehouse,
            product=self.product,
            qty_on_hand=Decimal('10.00')
        )
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
        ret_order.status = 'pending'
        ret_order.save()
        PurchaseReturnOrderService.cancel_return_order(ret_order, self.user)
        ret_order.refresh_from_db()
        self.assertEqual(ret_order.status, 'cancelled')

    def test_purchase_return_order_views_crud_and_export(self):
        InventoryStock.objects.create(
            warehouse=self.warehouse,
            product=self.product,
            qty_on_hand=Decimal('50.00')
        )
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
        ret.status = 'pending'
        ret.save()
        act_resp = self.client.post(reverse('purchase_return_order_action', args=[ret.id, 'approve']), follow=True)
        self.assertEqual(act_resp.status_code, 200)
        ret.refresh_from_db()
        self.assertEqual(ret.status, 'settled')

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


class PurchaseOrderLifecycleAndSettlementTests(TestCase):
    """Verifies purchase order lifecycle, state transitions, security audit logging, and order-linked payments."""

    def setUp(self):
        self.superadmin_role, _ = Role.objects.get_or_create(
            name=Role.ROLE_SUPERADMIN,
            defaults={'display_name': 'مدير النظام الأعلى', 'is_super': True, 'is_system': True, 'is_active': True}
        )
        self.accountant_role, _ = Role.objects.get_or_create(
            name=Role.ROLE_ACCOUNTANT,
            defaults={'display_name': 'محاسب', 'is_accountant': True}
        )

        self.superadmin = User.objects.create_superuser(
            username='po_superadmin',
            email='po_super@wea.com',
            password='Password123!',
            role=self.superadmin_role
        )
        self.accountant = User.objects.create_user(
            username='po_accountant',
            email='po_acct@wea.com',
            password='Password123!',
            role=self.accountant_role
        )

        self.warehouse = Warehouse.objects.create(name='مخزن التوريدات المركزي', code='WH-PO-MAIN', is_main=True)
        self.vault = Vault.objects.create(name='خزينة التوريدات', serial_num=8801, current_balance=Decimal('100000.00'))

        self.supplier = Contact.objects.create(name='شركة فارما للتوريدات الطبية', is_supplier=True, mobile='01055566677')
        VendorAccount.get_or_create_for_supplier(self.supplier)

        self.category = ProductCategory.objects.create(name='أدوية عامة', code='PO-GEN')
        self.product = Product.objects.create(
            name='أموكسيسيلين 500',
            sku_code='AMX-500',
            retail_price=Decimal('50.00'),
            default_purchase_cost=Decimal('40.00'),
            category=self.category
        )

    def test_purchase_order_lifecycle_and_audit_logging(self):
        """Purchase order lifecycle generates audit log events with correct actor and status."""
        due_date = datetime.date(2026, 11, 15)
        order = PurchaseOrderService.create_order(
            supplier=self.supplier,
            target_warehouse=self.warehouse,
            order_date=timezone.now().date(),
            items_data=[{
                'product': self.product,
                'quantity': 100,
                'unit_price': Decimal('40.00'),
                'discount_percentage': Decimal('0.00'),
                'tax_percentage': Decimal('0.00'),
            }],
            user=self.accountant,
            due_date=due_date,
            notes='شحنة أدوية طارئة'
        )
        self.assertEqual(order.grand_total, Decimal('4000.00'))
        self.assertEqual(order.due_date, due_date)
        self.assertEqual(order.outstanding_balance, Decimal('4000.00'))
        self.assertFalse(order.is_paid)

        create_audit = SecurityAuditLog.objects.filter(
            module='purchases', action_type='PURCHASE_ORDER_CREATED', record_id=order.id
        ).first()
        self.assertIsNotNone(create_audit)
        self.assertEqual(create_audit.actor, self.accountant)

        # Test approval and subsequent workflow on pending order
        if order.memo:
            order.memo.items.all().delete()
            order.memo.delete()
            order.memo = None
            order.save()
        order.status = 'pending'
        order.save()
        PurchaseOrderService.approve_order(order, self.superadmin)
        order.refresh_from_db()
        self.assertEqual(order.status, 'settled')

        approve_audit = SecurityAuditLog.objects.filter(
            module='purchases', action_type='PURCHASE_ORDER_APPROVED', record_id=order.id
        ).first()
        self.assertIsNotNone(approve_audit)
        self.assertEqual(approve_audit.actor, self.superadmin)

        # Idempotent downstream calls keep order safely settled without double-posting
        PurchaseOrderService.invoice_order(order, self.accountant)
        order.refresh_from_db()
        self.assertEqual(order.status, 'settled')

    def test_vendor_payment_linked_to_purchase_order(self):
        """Vendor payment linked to a specific purchase order reduces its outstanding balance."""
        po = PurchaseOrderService.create_order(
            supplier=self.supplier,
            target_warehouse=self.warehouse,
            order_date=timezone.now().date(),
            items_data=[{'product': self.product, 'quantity': 50, 'unit_price': Decimal('40.00')}],
            user=self.accountant,
            due_date=datetime.date(2026, 11, 20)
        )
        po.refresh_from_db()
        self.assertEqual(po.outstanding_balance, Decimal('2000.00'))

        # Partial payment: 800 LE
        payment1 = TreasuryService.record_vendor_payment(
            supplier=self.supplier,
            vault=self.vault,
            amount=Decimal('800.00'),
            payment_method='cash',
            user=self.accountant,
            purchase_order=po,
            notes='دفعة أولى'
        )
        po.refresh_from_db()
        self.assertEqual(po.total_paid, Decimal('800.00'))
        self.assertEqual(po.outstanding_balance, Decimal('1200.00'))
        self.assertFalse(po.is_paid)

        # Full settlement remaining: 1200 LE
        payment2 = TreasuryService.record_vendor_payment(
            supplier=self.supplier,
            vault=self.vault,
            amount=Decimal('1200.00'),
            payment_method='cash',
            user=self.accountant,
            purchase_order=po,
            notes='تسوية كاملة'
        )
        po.refresh_from_db()
        self.assertEqual(po.total_paid, Decimal('2000.00'))
        self.assertEqual(po.outstanding_balance, Decimal('0.00'))
        self.assertTrue(po.is_paid)

    def test_vendor_payment_overpayment_rejected(self):
        """Attempting to pay more than the purchase order's outstanding balance must raise ValidationError."""
        po = PurchaseOrderService.create_order(
            supplier=self.supplier,
            target_warehouse=self.warehouse,
            order_date=timezone.now().date(),
            items_data=[{'product': self.product, 'quantity': 10, 'unit_price': Decimal('40.00')}],
            user=self.accountant
        )
        self.assertEqual(po.outstanding_balance, Decimal('400.00'))

        with self.assertRaises(ValidationError) as ctx:
            TreasuryService.record_vendor_payment(
                supplier=self.supplier,
                vault=self.vault,
                amount=Decimal('500.00'),
                payment_method='cash',
                user=self.accountant,
                purchase_order=po
            )
        self.assertIn('يتجاوز الرصيد المستحق', str(ctx.exception))

    def test_purchase_list_stats_respect_active_filters(self):
        PurchaseOrderService.create_order(
            supplier=self.supplier,
            target_warehouse=self.warehouse,
            order_date=timezone.now().date(),
            items_data=[{'product': self.product, 'quantity': 5, 'unit_price': Decimal('40.00')}],
            user=self.accountant
        )
        self.client.force_login(self.superadmin)
        res = self.client.get(reverse('purchase_orders_list') + '?search=NO_SUCH_PO_999')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.context['stats']['total_orders'], 0)
        self.assertEqual(res.context['stats']['total_value'], Decimal('0.00'))


class PurchaseReturnOrderWorkflowTests(TestCase):
    """
    Verifies Phase 2 Purchase Return Order workflows:
    1. Quantity bounds (Returnable = Original Delivered - Previously Returned)
    2. Anti-self-approval enforcement
    3. Rejection workflow with required reason
    4. Outward memo warehouse dispatch and stock reduction
    5. Financial debit note settlement and VendorAccount balance reduction
    6. Timeline events and POST-only action views
    """

    def setUp(self):
        self.client = Client()
        self.superadmin = User.objects.create_superuser(
            username='admin_pret', email='admin_pret@wea.com', password='Password123!'
        )
        self.mgr_role = Role.objects.get(name=Role.ROLE_MANAGER)
        self.acc_role = Role.objects.get(name=Role.ROLE_ACCOUNTANT)

        self.alex = Area.objects.create(name='الإسكندرية', code='ALX-PRET')
        self.manager = User.objects.create_user(
            username='mgr_pret', email='mgr_pret@wea.com', password='Password123!', role=self.mgr_role
        )
        self.manager.assigned_areas.add(self.alex)

        self.accountant = User.objects.create_user(
            username='acc_pret', email='acc_pret@wea.com', password='Password123!', role=self.acc_role
        )

        self.wh = Warehouse.objects.create(name='مخزن الإسكندرية المركزي', code='WH-ALX-PRET', area=self.alex, is_active=True)
        self.supplier = Contact.objects.create(
            name='شركة الدلتا للأدوية', code='SUP-DELTA-01', is_supplier=True, area=self.alex, status='active'
        )
        self.vendor_acc = VendorAccount.get_or_create_for_supplier(self.supplier)

        self.cat = ProductCategory.objects.create(name='أدوية عامة', code='CAT-PRET-01')
        self.product = Product.objects.create(
            name='بانادول أقراص', sku_code='PRD-PAN-01', category=self.cat,
            retail_price=Decimal('50.00'), default_purchase_cost=Decimal('30.00'),
            is_active=True, sellable=True
        )
        self.stock = InventoryStock.objects.create(
            warehouse=self.wh, product=self.product, qty_on_hand=Decimal('100.00'), product_cost=Decimal('30.00')
        )

        from master_data.models import PurchaseSettings
        ps = PurchaseSettings.get_settings()
        ps.require_manager_approval = False
        ps.save()

        # Create original purchase order (immediately settled, stocked, and invoiced)
        self.orig_po = PurchaseOrderService.create_order(
            supplier=self.supplier,
            target_warehouse=self.wh,
            order_date=timezone.now().date(),
            items_data=[{'product': self.product, 'quantity': 20, 'unit_price': Decimal('30.00')}],
            user=self.accountant
        )
        self.orig_po.refresh_from_db()
        self.orig_po_item = self.orig_po.items.first()
        self.vendor_acc.refresh_from_db()
        self.assertEqual(self.vendor_acc.current_balance, Decimal('600.00'))

    def test_purchase_return_quantity_bounds_and_over_return_prevention(self):
        """Return quantity cannot exceed original delivered quantity minus previous returns."""
        # 1. Return 8 units
        ret1 = PurchaseReturnOrderService.create_return_order(
            supplier=self.supplier,
            warehouse=self.wh,
            purchase_order=self.orig_po,
            items_data=[{
                'product': self.product,
                'quantity': Decimal('8.00'),
                'unit_price': Decimal('30.00'),
                'original_item': self.orig_po_item
            }],
            user=self.accountant,
            notes='مرتجع عيوب صناعة'
        )
        self.assertEqual(ret1.status, 'settled')
        self.assertEqual(ret1.grand_total, Decimal('240.00'))

        # 2. Return remaining 12 units
        ret2 = PurchaseReturnOrderService.create_return_order(
            supplier=self.supplier,
            warehouse=self.wh,
            purchase_order=self.orig_po,
            items_data=[{
                'product': self.product,
                'quantity': Decimal('12.00'),
                'unit_price': Decimal('30.00'),
                'original_item': self.orig_po_item
            }],
            user=self.accountant
        )
        self.assertIsNotNone(ret2)

        # 3. Third return of even 1 unit fails (8 + 12 = 20 max reached)
        with self.assertRaises(ValidationError) as ctx:
            PurchaseReturnOrderService.create_return_order(
                supplier=self.supplier,
                warehouse=self.wh,
                purchase_order=self.orig_po,
                items_data=[{
                    'product': self.product,
                    'quantity': Decimal('1.00'),
                    'unit_price': Decimal('30.00'),
                    'original_item': self.orig_po_item
                }],
                user=self.accountant
            )
        self.assertIn('تتجاوز الكمية المتاحة للإرجاع', str(ctx.exception))

    def test_purchase_return_anti_self_approval(self):
        """User who created purchase return cannot approve it."""
        ret = PurchaseReturnOrderService.create_return_order(
            supplier=self.supplier,
            warehouse=self.wh,
            purchase_order=self.orig_po,
            items_data=[{
                'product': self.product,
                'quantity': Decimal('5.00'),
                'unit_price': Decimal('30.00'),
                'original_item': self.orig_po_item
            }],
            user=self.accountant
        )
        ret.status = 'pending'
        ret.save()

        # Self-approval by accountant fails
        with self.assertRaises(ValidationError) as ctx:
            PurchaseReturnOrderService.approve_return_order(ret, self.accountant)
        self.assertIn('منع الاعتماد الذاتي', str(ctx.exception))

        # Approval by manager succeeds and auto-settles return
        approved = PurchaseReturnOrderService.approve_return_order(ret, self.manager)
        self.assertEqual(approved.status, 'settled')

    def test_purchase_return_rejection_workflow(self):
        """Rejecting purchase return requires manager approval and saves rejection reason."""
        ret = PurchaseReturnOrderService.create_return_order(
            supplier=self.supplier,
            warehouse=self.wh,
            purchase_order=self.orig_po,
            items_data=[{
                'product': self.product,
                'quantity': Decimal('3.00'),
                'unit_price': Decimal('30.00'),
                'original_item': self.orig_po_item
            }],
            user=self.accountant
        )
        ret.status = 'pending'
        ret.save()
        rejected = PurchaseReturnOrderService.reject_return_order(ret, self.manager, rejection_reason='تجاوز فترة الضمان المسموح بها')
        self.assertEqual(rejected.status, 'rejected')
        self.assertEqual(rejected.rejection_reason, 'تجاوز فترة الضمان المسموح بها')

    def test_purchase_return_delivery_and_settlement_workflow(self):
        """Dispatching return un-stocks warehouse; settling decrements vendor payable balance."""
        self.stock.refresh_from_db()
        initial_stock = self.stock.qty_on_hand
        initial_bal = self.vendor_acc.current_balance

        ret = PurchaseReturnOrderService.create_return_order(
            supplier=self.supplier,
            warehouse=self.wh,
            purchase_order=self.orig_po,
            items_data=[{
                'product': self.product,
                'quantity': Decimal('4.00'),
                'unit_price': Decimal('30.00'),
                'original_item': self.orig_po_item
            }],
            user=self.accountant
        )
        self.assertEqual(ret.status, 'settled')

        self.stock.refresh_from_db()
        self.assertEqual(self.stock.qty_on_hand, initial_stock - Decimal('4.00'))

        self.vendor_acc.refresh_from_db()
        self.assertEqual(self.vendor_acc.current_balance, initial_bal - Decimal('120.00'))

    def test_purchase_return_views_post_only_actions(self):
        """Purchase return action endpoints reject GET and require POST."""
        ret = PurchaseReturnOrderService.create_return_order(
            supplier=self.supplier,
            warehouse=self.wh,
            purchase_order=self.orig_po,
            items_data=[{
                'product': self.product,
                'quantity': Decimal('2.00'),
                'unit_price': Decimal('30.00'),
                'original_item': self.orig_po_item
            }],
            user=self.accountant
        )
        ret.status = 'pending'
        ret.save()
        self.client.force_login(self.manager)

        # GET request on approve endpoint redirects to detail view without action
        get_resp = self.client.get(reverse('purchase_return_order_action', args=[ret.pk, 'approve']))
        self.assertEqual(get_resp.status_code, 302)
        ret.refresh_from_db()
        self.assertEqual(ret.status, 'pending')
        self.assertEqual(ret.status, 'pending')

        # POST request on approve endpoint executes action and auto-settles return
        post_resp = self.client.post(reverse('purchase_return_order_action', args=[ret.pk, 'approve']))
        self.assertEqual(post_resp.status_code, 302)
        ret.refresh_from_db()
        self.assertEqual(ret.status, 'settled')


class PurchasesSupplierScopingAndSmartSearchTests(TestCase):
    """Verifies corporate company-area supplier scoping, territorial isolation, and smart search APIs."""

    def setUp(self):
        from django.core.management import call_command

        call_command('setup_permissions')
        self.role_super = Role.objects.get(name='superadmin')
        self.role_manager = Role.objects.get(name='manager')

        self.superadmin = User.objects.create_superuser(
            username='pur_super@wea.com', email='pur_super@wea.com', password='Password123!', role=self.role_super
        )
        self.cairo = Area.objects.create(code='P-CAI', name='القاهرة', area_type='governorate', is_company_area=False)
        self.alex = Area.objects.create(code='P-ALX', name='الإسكندرية', area_type='governorate', is_company_area=False)
        self.corp_sup_area = Area.objects.create(code='P-CORP', name='موردين', area_type='governorate', is_company_area=True)

        self.mgr_cairo = User.objects.create_user(
            username='pur_mgr_cai@wea.com', email='pur_mgr_cai@wea.com', password='Password123!', role=self.role_manager
        )
        self.mgr_cairo.assigned_areas.add(self.cairo)

        self.corp_supplier = Contact.objects.create(
            serial_num=16115, name='مصنع اورجانيك للمكملات الغذائية بنها',
            is_supplier=True, is_customer=True, status='customer', area=self.corp_sup_area
        )
        self.alex_supplier = Contact.objects.create(
            serial_num=88101, name='مورد إقليمي الإسكندرية',
            is_supplier=True, is_customer=False, status='customer', area=self.alex
        )
        self.cust_only = Contact.objects.create(
            serial_num=88102, name='عميل القاهرة فقط',
            is_supplier=False, is_customer=True, status='customer', area=self.cairo
        )

        self.wh_cairo = Warehouse.objects.create(name='مخزن مشتريات القاهرة', code='WH-P-CAI', area=self.cairo)
        self.wh_alex = Warehouse.objects.create(name='مخزن مشتريات الإسكندرية', code='WH-P-ALX', area=self.alex)
        self.vault_cairo = Vault.objects.create(serial_num=8801, name='خزنة القاهرة', area=self.cairo)

    def test_supplier_search_and_return_list_scoping(self):
        self.client.force_login(self.mgr_cairo)

        # Corporate company-area supplier is visible with Arabic normalization ('أورجانيك' -> 'اورجانيك')
        sup_api = self.client.get(reverse('purchases_suppliers_search_api') + '?q=أورجانيك')
        self.assertEqual(sup_api.status_code, 200)
        ids = [r['id'] for r in sup_api.json()['results']]
        self.assertIn(self.corp_supplier.id, ids)
        self.assertNotIn(self.alex_supplier.id, ids)
        self.assertNotIn(self.cust_only.id, ids)

        # Purchase returns list page also scopes suppliers cleanly (previously leaked unscoped suppliers)
        ret_list = self.client.get(reverse('purchase_return_orders_list'))
        self.assertEqual(ret_list.status_code, 200)
        ctx_supplier_ids = {s.id for s in ret_list.context['suppliers']}
        self.assertIn(self.corp_supplier.id, ctx_supplier_ids)
        self.assertNotIn(self.alex_supplier.id, ctx_supplier_ids)

        # Warehouses smart search is scoped to Cairo
        wh_api = self.client.get(reverse('purchases_warehouses_search_api') + '?q=القاهره')
        self.assertEqual(wh_api.status_code, 200)
        wh_ids = [r['id'] for r in wh_api.json()['results']]
        self.assertIn(self.wh_cairo.id, wh_ids)
        self.assertNotIn(self.wh_alex.id, wh_ids)

        # POST rejects non-supplier contact (checked under superadmin with create permission)
        self.client.force_login(self.superadmin)
        before = PurchaseOrder.objects.count()
        bad_po = self.client.post(reverse('purchase_order_create'), {
            'supplier': self.cust_only.id,
            'warehouse': self.wh_cairo.id,
            'order_date': '2026-11-16',
        })
        self.assertEqual(bad_po.status_code, 302)
        self.assertEqual(PurchaseOrder.objects.count(), before)

    def test_purchases_orders_search_api_and_total_count(self):
        """Verifies purchases_orders_search_api scoping, for_return, unsettled, and total_count."""
        po_cairo_1 = PurchaseOrder.objects.create(
            order_number='PO-CAI-001',
            supplier=self.corp_supplier,
            target_warehouse=self.wh_cairo,
            status='received',
            order_date='2026-11-16',
            created_by=self.mgr_cairo,
            grand_total=Decimal('5000.00'),
        )
        po_cairo_2 = PurchaseOrder.objects.create(
            order_number='PO-CAI-002',
            supplier=self.corp_supplier,
            target_warehouse=self.wh_cairo,
            status='settled',
            order_date='2026-11-16',
            created_by=self.mgr_cairo,
            grand_total=Decimal('3000.00'),
        )
        po_alex = PurchaseOrder.objects.create(
            order_number='PO-ALX-001',
            supplier=self.alex_supplier,
            target_warehouse=self.wh_alex,
            status='settled',
            order_date='2026-11-16',
            created_by=self.superadmin,
            grand_total=Decimal('7000.00'),
        )

        self.client.force_login(self.mgr_cairo)
        res = self.client.get(reverse('purchases_orders_search_api'))
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn('total_count', data)
        self.assertEqual(data['total_count'], 2)
        ids = [item['id'] for item in data['results']]
        self.assertIn(po_cairo_1.id, ids)
        self.assertIn(po_cairo_2.id, ids)
        self.assertNotIn(po_alex.id, ids)

        # Filter unsettled=1
        res_unsettled = self.client.get(reverse('purchases_orders_search_api') + '?unsettled=1')
        self.assertEqual(res_unsettled.status_code, 200)
        unsettled_ids = [item['id'] for item in res_unsettled.json()['results']]
        self.assertIn(po_cairo_1.id, unsettled_ids)
        self.assertNotIn(po_cairo_2.id, unsettled_ids)


class PurchasesPhase2ImprovementsTests(TestCase):
    """
    Verifies Phase 2 architectural improvements in Purchases:
    1. /purchases/api/orders/<id>/return-details/ API returning returnable quantities and scoping
    2. Form error recovery preserving user inputs and dynamic line items in purchase_return_order_create
    """

    def setUp(self):
        from django.core.management import call_command
        call_command('setup_permissions')

        self.cairo = Area.objects.create(code='PUR-P2-CAI', name='القاهرة', area_type='governorate')
        self.giza = Area.objects.create(code='PUR-P2-GIZ', name='الجيزة', area_type='governorate')

        self.role_super = Role.objects.get(name='superadmin')
        self.role_manager = Role.objects.get(name='manager')

        self.superadmin = User.objects.create_superuser(username='pur_p2_super', email='pur_p2_super@test.com', password='pass')
        self.mgr_cairo = User.objects.create_user(username='pur_p2_mgr_cai', role=self.role_manager, is_staff=True)
        self.mgr_cairo.assigned_areas.add(self.cairo)
        self.mgr_giza = User.objects.create_user(username='pur_p2_mgr_giz', role=self.role_manager, is_staff=True)
        self.mgr_giza.assigned_areas.add(self.giza)

        self.wh_cairo = Warehouse.objects.create(name='مخزن مشتريات القاهرة', code='PUR-WH-CAI', area=self.cairo, is_main=True)
        self.wh_giza = Warehouse.objects.create(name='مخزن مشتريات الجيزة', code='PUR-WH-GIZ', area=self.giza, is_main=True)

        self.supplier = Contact.objects.create(
            serial_num=88001,
            name='شركة فارما للتوزيع',
            is_supplier=True,
            status='supplier',
            area=self.cairo,
            created_by=self.superadmin
        )

        self.cat = ProductCategory.objects.create(name='أدوية مشتريات', code='PUR-GEN')
        self.prod = Product.objects.create(
            name='سيتال 500 ملجم',
            sku_code='CETAL-500',
            retail_price=Decimal('20.00'),
            default_purchase_cost=Decimal('14.00'),
            category=self.cat,
            sellable=True
        )

        self.po = PurchaseOrder.objects.create(
            order_number='PO-P2-TEST-001',
            supplier=self.supplier,
            target_warehouse=self.wh_cairo,
            status='settled',
            order_date='2026-11-17',
            created_by=self.mgr_cairo,
            grand_total=Decimal('1400.00')
        )
        self.po_item = PurchaseOrderItem.objects.create(
            order=self.po,
            product=self.prod,
            quantity=Decimal('100.00'),
            unit_price=Decimal('14.00')
        )

    def test_purchases_order_return_details_api(self):
        """API returns PO returnable items and limits, respecting data scope."""
        self.client.force_login(self.mgr_cairo)
        resp = self.client.get(reverse('purchases_order_return_details_api', args=[self.po.id]))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['order_number'], self.po.order_number)
        self.assertEqual(data['supplier_id'], self.supplier.id)
        self.assertEqual(data['warehouse_id'], self.wh_cairo.id)
        self.assertEqual(len(data['items']), 1)
        item = data['items'][0]
        self.assertEqual(item['product_name'], self.prod.name)
        self.assertEqual(item['product_code'], self.prod.sku_code)
        self.assertEqual(item['original_quantity'], '100.00')
        self.assertEqual(item['remaining_returnable'], '100.00')

        # Giza manager cannot access Cairo PO -> 403
        self.client.force_login(self.mgr_giza)
        bad_resp = self.client.get(reverse('purchases_order_return_details_api', args=[self.po.id]))
        self.assertEqual(bad_resp.status_code, 403)

    def test_purchase_return_order_form_error_recovery(self):
        """Validation errors in purchase_return_order_create preserve entered dynamic items and form data."""
        self.client.force_login(self.superadmin)
        resp = self.client.post(reverse('purchase_return_order_create'), {
            'purchase_order': self.po.id,
            'supplier': self.supplier.id,
            'warehouse': self.wh_cairo.id,
            'return_date': '2026-11-17',
            'product_id[]': [self.prod.id],
            'quantity[]': ['250.00'],  # Exceeds remaining returnable quantity (100)
            'unit_price[]': ['14.00'],
            'notes': 'ملاحظات مرتجع مشتريات هامة'
        })
        self.assertEqual(resp.status_code, 200)
        self.assertIn('form_data', resp.context)
        self.assertEqual(resp.context['form_data']['notes'], 'ملاحظات مرتجع مشتريات هامة')
        self.assertIn('submitted_items', resp.context)
        self.assertEqual(len(resp.context['submitted_items']), 1)
        self.assertEqual(resp.context['submitted_items'][0]['quantity'], '250.00')







class Phase2PurchasesIntegerAndStatsTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model
        from accounts.models import Role
        from catalog.models import Product, ProductCategory
        from contacts.models import Contact
        from inventory.models import Warehouse
        from master_data.models import Area, CompanyProfile

        User = get_user_model()
        CompanyProfile.objects.get_or_create(pk=1, defaults={'company_name': 'WEA Test Pharma'})
        self.cairo = Area.objects.create(name='القاهرة مشتريات P2', code='CAI-P2')
        self.super_role, _ = Role.objects.get_or_create(name='superadmin', defaults={'display_name': 'Super Admin', 'is_super': True})
        self.superadmin = User.objects.create_superuser(username='pur_p2_super', email='pur_p2_super@wea.com', password='TestPassword123!', role=self.super_role)
        self.supplier = Contact.objects.create(name='مورد مشتريات P2', is_supplier=True, area=self.cairo)
        self.wh = Warehouse.objects.create(name='مخزن مشتريات P2', code='WH-P-P2', area=self.cairo)
        self.cat = ProductCategory.objects.create(name='تصنيف مشتريات P2', code='CAT-PP2')
        self.prod = Product.objects.create(name='صنف مشتريات P2', sku_code='SKU-PP2', category=self.cat, default_purchase_cost=Decimal('40.00'))

    def test_purchase_service_rejects_fractional_quantity(self):
        from django.core.exceptions import ValidationError
        from purchases.services import PurchaseOrderService

        with self.assertRaises(ValidationError):
            PurchaseOrderService.create_order(
                supplier=self.supplier,
                target_warehouse=self.wh,
                order_date='2026-11-17',
                items_data=[{'product': self.prod, 'quantity': Decimal('1.25'), 'unit_cost': Decimal('40.00')}],
                user=self.superadmin,
            )

    def test_purchase_return_orders_list_stats_and_exports(self):
        from django.urls import reverse
        self.client.force_login(self.superadmin)

        resp = self.client.get(reverse('purchase_return_orders_list'))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('draft_count', resp.context['stats'])
        self.assertIn('settled_count', resp.context['stats'])

        for url_name in ['purchase_orders_export', 'purchase_return_orders_export']:
            exp = self.client.get(reverse(url_name), {'date_from': '2026-01-01', 'total_min': '10'})
            self.assertEqual(exp.status_code, 200)
            self.assertIn('spreadsheetml.sheet', exp['Content-Type'])

    def test_purchase_order_edit_renders_batch_number_and_expiry_date(self):
        """Regression test: purchase_order_edit template binds item.product_batch_number and item.product_expiry_date."""
        from django.urls import reverse
        from purchases.models import PurchaseOrder, PurchaseOrderItem

        po = PurchaseOrder.objects.create(
            order_number='PO-BATCH-REG-01',
            supplier=self.supplier,
            target_warehouse=self.wh,
            status='pending',
            order_date='2026-11-18',
            created_by=self.superadmin,
            grand_total=Decimal('400.00'),
        )
        PurchaseOrderItem.objects.create(
            order=po,
            product=self.prod,
            quantity=Decimal('10.00'),
            unit_price=Decimal('40.00'),
            product_batch_number='LOT-2026-XYZ',
            product_expiry_date=datetime.date(2028, 6, 30),
        )
        self.client.force_login(self.superadmin)
        resp = self.client.get(reverse('purchase_order_edit', args=[po.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'LOT-2026-XYZ')
        self.assertContains(resp, '2028-06-30')

    def test_purchase_return_order_create_uses_order_details_api_and_approver_perm(self):
        """Regression test: purchase_return_order_create uses /purchases/api/order-details/ and approve action checks purchases:returns/approve."""
        from django.urls import reverse
        from accounts.models import Permission, Role, User
        from purchases.models import PurchaseOrder, PurchaseOrderItem, PurchaseReturnOrder, PurchaseReturnOrderItem

        self.client.force_login(self.superadmin)
        create_resp = self.client.get(reverse('purchase_return_order_create'))
        self.assertEqual(create_resp.status_code, 200)
        self.assertContains(create_resp, '/purchases/api/order-details/')
        self.assertNotContains(create_resp, '/return-details/')

        # Approver with purchases:returns/approve (without purchases:returns/manage) can reject/approve
        custom_role = Role.objects.create(name='po_return_approver_only', display_name='معتمد مرتجعات فقط', is_active=True)
        p_mod = Permission.objects.get(codename='module:purchases')
        p_approve = Permission.objects.get(codename='purchases:returns/approve')
        p_view = Permission.objects.get(codename='purchases:returns/view')
        custom_role.permissions.add(p_mod, p_approve, p_view)
        from accounts.models import RoleModuleScope
        RoleModuleScope.objects.update_or_create(
            role=custom_role, module='purchases', defaults={'view_scope': 'all', 'manage_scope': 'all'}
        )
        approver = User.objects.create_user(username='pret_approver_only', password='TestPassword123!', role=custom_role)

        po = PurchaseOrder.objects.create(
            order_number='PO-RET-PERM-01',
            supplier=self.supplier,
            target_warehouse=self.wh,
            status='settled',
            order_date='2026-11-18',
            created_by=self.superadmin,
            grand_total=Decimal('400.00'),
        )
        po_item = PurchaseOrderItem.objects.create(
            order=po, product=self.prod, quantity=Decimal('10.00'), unit_price=Decimal('40.00')
        )
        ret = PurchaseReturnOrder.objects.create(
            order_number='PRET-PERM-01',
            purchase_order=po,
            supplier=self.supplier,
            warehouse=self.wh,
            status='pending',
            order_date='2026-11-18',
            created_by=self.superadmin,
            grand_total=Decimal('80.00'),
        )
        PurchaseReturnOrderItem.objects.create(
            return_order=ret, original_item=po_item, product=self.prod, quantity=Decimal('2.00'), unit_price=Decimal('40.00')
        )

        self.client.force_login(approver)
        reject_resp = self.client.post(reverse('purchase_return_order_action', args=[ret.pk, 'reject']), {
            'rejection_reason': 'سبب رفض اختباري'
        })
        self.assertEqual(reject_resp.status_code, 302)
        ret.refresh_from_db()
        self.assertEqual(ret.status, 'rejected')

