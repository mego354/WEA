from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from django.core.exceptions import ValidationError

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
from sales.services import CustomerAccountService, CollectionService
from treasury.models import (
    Vault,
    VaultTransaction,
    VendorAccount,
    VendorTransaction,
    VendorPayment,
)
from treasury.services import TreasuryService


class FinancialRefactorTestSuite(TestCase):
    def setUp(self):
        self.super_role, _ = Role.objects.get_or_create(
            name='superadmin', defaults={'display_name': 'Super Admin', 'is_super': True}
        )
        self.rep_role, _ = Role.objects.get_or_create(
            name='medical_rep', defaults={'display_name': 'Medical Rep', 'is_super': False}
        )
        self.admin = User.objects.create_superuser(
            username='fin_admin', password='Password123!', email='fin_admin@test.local', role=self.super_role
        )
        self.rep = User.objects.create_user(
            username='fin_rep', password='Password123!', email='fin_rep@test.local', role=self.rep_role
        )
        self.area = Area.objects.create(name='القاهرة')
        self.customer = Contact.objects.create(
            name='صيدلية الاختبار المالي',
            is_customer=True,
            status='customer',
            area=self.area,
        )
        self.supplier = Contact.objects.create(
            name='مورد الاختبار المالي',
            is_supplier=True,
            is_customer=False,
            status='customer',
            area=self.area,
        )
        self.warehouse = Warehouse.objects.create(name='مخزن الاختبار', code='WH-FIN-01', is_active=True)
        self.cat = ProductCategory.objects.create(name='أدوية', code='CAT-FIN-01')
        self.product = Product.objects.create(
            name='صنف مالي',
            sku_code='FIN-001',
            category=self.cat,
            retail_price=Decimal('100.00'),
            default_purchase_cost=Decimal('60.00'),
        )
        InventoryStock.objects.create(
            warehouse=self.warehouse,
            product=self.product,
            qty_on_hand=Decimal('100.00'),
            qty_reserved=Decimal('0.00'),
            product_cost=Decimal('60.00'),
        )
        self.cash_vault = Vault.objects.create(
            name='خزنة الاختبار النقدية',
            vault_type='cash',
            is_active=True,
            current_balance=Decimal('0.00'),
        )
        self.client = Client()
        self.client.force_login(self.admin)

    def test_1000_opening_400_sale_300_collection_1100_settlement_scenario(self):
        """
        Verifies the exact Phase 1/2 business example:
        - Opening balance = 1,000 EGP
        - Sales Order = 400 EGP (account = 1,400 EGP, payment_status = 'credit')
        - Cash Collection = 300 EGP (account = 1,100 EGP, vault = 300 EGP)
        - Non-cash Settlement = 1,100 EGP credit
        Expected:
        - CustomerAccount.current_balance == 0.00
        - Contact.total_outstanding_balance == 0.00
        - Vault.current_balance == 300.00 (STRICTLY ZERO vault impact from settlement)
        - VaultTransaction count == 1 (only the 300 EGP collection)
        - Collection record == 300.00 untouched
        - SalesOrder.payment_status remains 'credit' (100% manual)
        """
        account = CustomerAccount.get_or_create_for_customer(self.customer)
        account.current_balance = Decimal('1000.00')
        account.overdue_balance = Decimal('1000.00')
        account.due_this_month_balance = Decimal('250.00')
        account.save()

        so = SalesOrder.objects.create(
            customer=self.customer,
            source_warehouse=self.warehouse,
            order_date=timezone.localdate(),
            status='invoiced',
            payment_status='credit',
            subtotal=Decimal('400.00'),
            grand_total=Decimal('400.00'),
            created_by=self.admin,
        )
        account.current_balance += Decimal('400.00')
        account.save()

        col = CollectionService.record_collection(
            customer=self.customer,
            vault=self.cash_vault,
            amount=Decimal('300.00'),
            user=self.admin,
            payment_method='cash',
            sales_order=so,
        )
        self.cash_vault.refresh_from_db()
        account.refresh_from_db()
        so.refresh_from_db()
        self.assertEqual(account.current_balance, Decimal('1100.00'))
        self.assertEqual(self.cash_vault.current_balance, Decimal('300.00'))
        self.assertEqual(so.payment_status, 'credit')

        # Non-cash settlement of remaining 1,100 EGP
        tx, prev_bal = CustomerAccountService.record_settlement(
            customer=self.customer,
            amount=Decimal('1100.00'),
            direction='credit',
            user=self.admin,
            reason_note='تسوية رصيد افتتاحي ومستحقات معتمدة',
            reference='SET-001',
        )
        self.cash_vault.refresh_from_db()
        account.refresh_from_db()
        so.refresh_from_db()
        col.refresh_from_db()

        self.assertEqual(prev_bal, Decimal('1100.00'))
        self.assertEqual(tx.reason, 'settlement')
        self.assertEqual(tx.credit, Decimal('1100.00'))
        self.assertEqual(account.current_balance, Decimal('0.00'))
        self.assertEqual(account.overdue_balance, Decimal('0.00'))
        self.assertEqual(account.due_this_month_balance, Decimal('0.00'))
        self.assertEqual(self.customer.total_outstanding_balance, Decimal('0.00'))
        self.assertEqual(self.cash_vault.current_balance, Decimal('300.00'))
        self.assertEqual(VaultTransaction.objects.filter(vault=self.cash_vault).count(), 1)
        self.assertEqual(col.amount, Decimal('300.00'))
        self.assertEqual(so.payment_status, 'credit')

    def test_customer_and_vendor_settlement_reversal_and_double_reversal_guard(self):
        c_acc = CustomerAccount.get_or_create_for_customer(self.customer)
        c_acc.current_balance = Decimal('500.00')
        c_acc.save()

        c_tx, _ = CustomerAccountService.record_settlement(
            customer=self.customer,
            amount=Decimal('200.00'),
            direction='credit',
            user=self.admin,
            reason_note='خصم تسوية جزئية',
        )
        c_acc.refresh_from_db()
        self.assertEqual(c_acc.current_balance, Decimal('300.00'))
        self.assertEqual(VaultTransaction.objects.count(), 0)

        rev = CustomerAccountService.reverse_settlement(c_tx.pk, self.admin, reason_note='خطأ إدخال')
        c_acc.refresh_from_db()
        c_tx.refresh_from_db()
        self.assertTrue(c_tx.is_reversed)
        self.assertEqual(c_tx.reversal_transaction_id, rev.id)
        self.assertEqual(c_acc.current_balance, Decimal('500.00'))
        self.assertEqual(VaultTransaction.objects.count(), 0)

        with self.assertRaises(ValidationError):
            CustomerAccountService.reverse_settlement(c_tx.pk, self.admin)

        # Vendor settlement + reversal
        v_acc = VendorAccount.get_or_create_for_supplier(self.supplier)
        v_acc.current_balance = Decimal('800.00')
        v_acc.save()

        v_tx, _ = TreasuryService.record_vendor_settlement(
            supplier=self.supplier,
            amount=Decimal('300.00'),
            direction='debit',
            user=self.admin,
            reason_note='تسوية مورد غير نقدية',
        )
        v_acc.refresh_from_db()
        self.assertEqual(v_acc.current_balance, Decimal('500.00'))
        self.assertEqual(VaultTransaction.objects.count(), 0)

        v_rev = TreasuryService.reverse_vendor_settlement(v_tx.pk, self.admin, reason_note='عكس تسوية')
        v_acc.refresh_from_db()
        v_tx.refresh_from_db()
        self.assertTrue(v_tx.is_reversed)
        self.assertEqual(v_tx.reversal_transaction_id, v_rev.id)
        self.assertEqual(v_acc.current_balance, Decimal('800.00'))
        self.assertEqual(VaultTransaction.objects.count(), 0)

        with self.assertRaises(ValidationError):
            TreasuryService.reverse_vendor_settlement(v_tx.pk, self.admin)

    def test_collection_any_vault_any_method_and_no_per_order_debt_cap(self):
        c_acc = CustomerAccount.get_or_create_for_customer(self.customer)
        c_acc.current_balance = Decimal('1500.00')
        c_acc.save()
        so = SalesOrder.objects.create(
            customer=self.customer,
            source_warehouse=self.warehouse,
            order_date=timezone.localdate(),
            status='invoiced',
            payment_status='credit',
            subtotal=Decimal('400.00'),
            grand_total=Decimal('400.00'),
            created_by=self.admin,
        )
        # Collect 700 EGP via bank_transfer into a regular cash vault even though linked SO is 400 EGP
        col = CollectionService.record_collection(
            customer=self.customer,
            vault=self.cash_vault,
            amount=Decimal('700.00'),
            user=self.admin,
            payment_method='bank_transfer',
            sales_order=so,
        )
        self.assertEqual(col.payment_method, 'bank_transfer')
        self.cash_vault.refresh_from_db()
        c_acc.refresh_from_db()
        so.refresh_from_db()
        self.assertEqual(self.cash_vault.current_balance, Decimal('700.00'))
        self.assertEqual(c_acc.current_balance, Decimal('800.00'))
        self.assertEqual(so.payment_status, 'credit')

    def test_purchase_orders_and_vendor_payments_templates_handle_null_created_by(self):
        """Regression test for VariableDoesNotExist when created_by is None."""
        PurchaseOrder.objects.create(
            supplier=self.supplier,
            target_warehouse=self.warehouse,
            order_date=timezone.localdate(),
            status='settled',
            grand_total=Decimal('500.00'),
            created_by=None,
        )
        VendorPayment.objects.create(
            supplier=self.supplier,
            vault=self.cash_vault,
            payment_date=timezone.localdate(),
            amount=Decimal('200.00'),
            created_by=None,
        )
        resp_po = self.client.get(reverse('purchase_orders_list'))
        self.assertEqual(resp_po.status_code, 200)
        resp_vp = self.client.get(reverse('vendor_payments_list'))
        self.assertEqual(resp_vp.status_code, 200)

    def test_dashboard_kpis_invoiced_delivered_returns_and_due_this_month(self):
        today = timezone.localdate()
        SalesOrder.objects.create(
            customer=self.customer,
            source_warehouse=self.warehouse,
            order_date=today,
            delivery_date=today,
            status='invoiced',
            grand_total=Decimal('1000.00'),
            created_by=self.admin,
        )
        SalesOrder.objects.create(
            customer=self.customer,
            source_warehouse=self.warehouse,
            order_date=today,
            status='preparing',
            grand_total=Decimal('300.00'),
            created_by=self.admin,
        )
        SalesReturnOrder.objects.create(
            customer=self.customer,
            order_date=today,
            status='settled',
            settled_at=timezone.now(),
            grand_total=Decimal('150.00'),
            created_by=self.admin,
        )
        c_acc = CustomerAccount.get_or_create_for_customer(self.customer)
        c_acc.current_balance = Decimal('850.00')
        c_acc.due_this_month_balance = Decimal('120.00')
        c_acc.save()

        resp = self.client.get(reverse('home'))
        self.assertEqual(resp.status_code, 200)
        cards_by_id = {c['id']: c for c in resp.context['kpi_cards']}

        self.assertIn('pos_delivered_stats', cards_by_id)
        self.assertIn('1 طلب', cards_by_id['pos_delivered_stats']['subtitle'])
        self.assertIn('1 طلب', cards_by_id['pos_pipeline_stats']['subtitle'])
        self.assertIn('ros_created_stats', cards_by_id)
        self.assertIn('ros_picked_stats', cards_by_id)
        self.assertIn('acc_stats_due_this_month', cards_by_id)
        self.assertNotIn('collections_waiting_collection_stats', cards_by_id)

    def test_settlement_http_endpoints_rbac(self):
        c_acc = CustomerAccount.get_or_create_for_customer(self.customer)
        c_acc.current_balance = Decimal('500.00')
        c_acc.save()

        resp = self.client.post(
            reverse('accounting_customer_settle', args=[c_acc.pk]),
            {'amount': '100.00', 'direction': 'credit', 'reason': 'تسوية HTTP'},
        )
        self.assertEqual(resp.status_code, 302)
        c_acc.refresh_from_db()
        self.assertEqual(c_acc.current_balance, Decimal('400.00'))

        # Rep without permission gets 403
        self.client.force_login(self.rep)
        resp_forb = self.client.post(
            reverse('accounting_customer_settle', args=[c_acc.pk]),
            {'amount': '50.00', 'direction': 'credit', 'reason': 'محاولة غير مصرح بها'},
        )
        self.assertEqual(resp_forb.status_code, 403)
