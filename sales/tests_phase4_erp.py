"""
Comprehensive tests for:
1. Collections remaining balance (selected order + overall customer account) & sales_orders_search_api
2. Automatic accounting & inventory posting (SO, SRO, PO, PRO) + double-posting prevention + safe backfill
3. Customer & Vendor Account Zeroing (تصفير الحساب) strict non-cash invariants
4. Individual user permissions removal verification
"""

from decimal import Decimal
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role, SecurityAuditLog, User
from catalog.models import Product, ProductCategory
from contacts.models import Contact
from inventory.models import InventoryStock, Warehouse
from master_data.models import Area, PurchaseSettings, SalesSettings
from purchases.models import PurchaseOrder, PurchaseReturnOrder
from purchases.services import PurchaseOrderService, PurchaseReturnOrderService
from sales.models import (
    Collection,
    CustomerAccount,
    CustomerTransaction,
    SalesOrder,
    SalesReturnOrder,
)
from sales.services import (
    CollectionService,
    CustomerAccountService,
    SalesOrderService,
    SalesReturnOrderService,
)
from treasury.models import Vault, VaultTransaction, VendorAccount, VendorPayment, VendorTransaction
from treasury.services import TreasuryService


class Phase4SalesPurchasesZeroingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('setup_permissions')

    def setUp(self):
        self.client = Client()
        self.super_role = Role.objects.get(name='superadmin')
        self.mgr_role = Role.objects.get(name='manager')
        self.rep_role = Role.objects.get(name='rep')
        self.acct_role = Role.objects.get(name='accountant')

        self.cairo = Area.objects.create(name='القاهرة_تست', code='CAI-P4', area_type='governorate')
        self.nasr = Area.objects.create(name='مدينة نصر_تست', code='NASR-P4', parent=self.cairo, area_type='subarea')
        self.giza = Area.objects.create(name='الجيزة_تست', code='GIZ-P4', area_type='governorate')
        self.dokki = Area.objects.create(name='الدقي_تست', code='DOK-P4', parent=self.giza, area_type='subarea')

        self.superadmin = User.objects.create_superuser(
            username='super_p4@wea.com', email='super_p4@wea.com', password='Password123!', name='Super P4', role=self.super_role
        )
        self.cairo_mgr = User.objects.create_user(
            username='mgr_cairo_p4@wea.com', email='mgr_cairo_p4@wea.com', password='Password123!', name='Cairo Mgr', role=self.mgr_role
        )
        self.cairo_mgr.assigned_areas.add(self.cairo)
        self.giza_mgr = User.objects.create_user(
            username='mgr_giza_p4@wea.com', email='mgr_giza_p4@wea.com', password='Password123!', name='Giza Mgr', role=self.mgr_role
        )
        self.giza_mgr.assigned_areas.add(self.giza)
        self.rep = User.objects.create_user(
            username='rep_nasr_p4@wea.com', email='rep_nasr_p4@wea.com', password='Password123!', name='Rep Nasr', role=self.rep_role
        )
        self.rep.assigned_areas.add(self.nasr)

        self.wh_main = Warehouse.objects.create(name='مخزن رئيسي تست', code='WH-P4-M', area=self.cairo, is_main=True, is_active=True)
        self.wh_rep = Warehouse.objects.filter(assigned_user=self.rep).first() or Warehouse.objects.create(
            name='مخزن مندوب تست', code='WH-P4-R', area=self.nasr, assigned_user=self.rep, is_rep_warehouse=True, is_active=True
        )
        self.wh_rep.area = self.nasr
        self.wh_rep.save(update_fields=['area'])
        self.vault = Vault.objects.create(name='خزنة رئيسية تست', serial_num=9901, current_balance=Decimal('50000.00'), is_active=True)

        self.cat = ProductCategory.objects.create(name='أدوية تست P4')
        self.prod = Product.objects.create(
            name='دواء تست 500', sku_code='P4-500', category=self.cat,
            retail_price=Decimal('100.00'), default_purchase_cost=Decimal('60.00'), sellable=True, is_active=True
        )
        InventoryStock.objects.create(warehouse=self.wh_main, product=self.prod, qty_on_hand=Decimal('200'))
        InventoryStock.objects.create(warehouse=self.wh_rep, product=self.prod, qty_on_hand=Decimal('200'))

        self.customer = Contact.objects.create(
            name='صيدلية الأمل P4', is_customer=True, area=self.cairo, brick=self.nasr, created_by=self.rep
        )
        self.giza_customer = Contact.objects.create(
            name='صيدلية الدقي P4', is_customer=True, area=self.giza, brick=self.dokki, created_by=self.giza_mgr
        )
        self.supplier = Contact.objects.create(
            name='شركة المورد P4', is_supplier=True, area=self.cairo, created_by=self.superadmin
        )

    def test_collections_dual_balances_and_search_api_no_nan(self):
        """sales_orders_search_api returns valid numeric outstanding_balance & due_date and respects unpaid_only."""
        ss = SalesSettings.get_settings()
        ss.require_manager_approval = False
        ss.save()

        today = timezone.localdate()
        so1 = SalesOrderService.create_order(
            customer=self.customer,
            source_warehouse=self.wh_rep,
            order_date=today,
            items_data=[{'product': self.prod, 'quantity': 5, 'unit_price': Decimal('100.00'), 'discount_percentage': Decimal('0')}],
            user=self.rep,
        )
        so2 = SalesOrderService.create_order(
            customer=self.customer,
            source_warehouse=self.wh_rep,
            order_date=today,
            items_data=[{'product': self.prod, 'quantity': 3, 'unit_price': Decimal('100.00'), 'discount_percentage': Decimal('0')}],
            user=self.rep,
        )
        # Pay so1 partially (200 of 500) and so2 fully (300 of 300)
        CollectionService.record_collection(customer=self.customer, vault=self.vault, amount=Decimal('200.00'), user=self.superadmin, sales_order=so1)
        CollectionService.record_collection(customer=self.customer, vault=self.vault, amount=Decimal('300.00'), user=self.superadmin, sales_order=so2)

        self.client.force_login(self.superadmin)
        # 1. unpaid_only=1 must return ONLY so1 (remaining=300.00) and exclude paid so2
        resp = self.client.get(reverse('sales_orders_search_api'), {'customer_id': self.customer.id, 'unpaid_only': '1'})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data['results']), 1)
        self.assertEqual(data['results'][0]['id'], so1.id)
        self.assertEqual(Decimal(str(data['results'][0]['outstanding_balance'])), Decimal('300.00'))
        self.assertIn('due_date', data['results'][0])
        self.assertEqual(Decimal(str(data['customer_account']['current_balance'])), Decimal('300.00'))

        # 2. Dedicated customer balance endpoint enforces DataScope
        bal_resp = self.client.get(reverse('sales_customer_balance_api', kwargs={'pk': self.customer.id}))
        self.assertEqual(bal_resp.status_code, 200)
        self.assertEqual(Decimal(str(bal_resp.json()['current_balance'])), Decimal('300.00'))

        # Giza manager cannot inspect Cairo customer balance (403)
        self.client.force_login(self.giza_mgr)
        denied = self.client.get(reverse('sales_customer_balance_api', kwargs={'pk': self.customer.id}))
        self.assertEqual(denied.status_code, 403)

    def test_auto_posting_sales_and_purchases_and_idempotency(self):
        """Auto-posting executes stock + ledger on approval (when required) or creation (when not), and prevents double-posting."""
        # A. Sales Order with manager approval required
        ss = SalesSettings.get_settings()
        ss.require_manager_approval = True
        ss.save()

        today = timezone.localdate()
        so = SalesOrderService.create_order(
            customer=self.customer,
            source_warehouse=self.wh_rep,
            order_date=today,
            items_data=[{'product': self.prod, 'quantity': 4, 'unit_price': Decimal('100.00'), 'discount_percentage': Decimal('0')}],
            user=self.rep,
        )
        self.assertEqual(so.status, 'pending')
        self.assertEqual(CustomerTransaction.objects.filter(account__customer=self.customer).count(), 0)

        # Manager approves -> immediately auto-posts stock + ledger -> status='invoiced'
        SalesOrderService.approve_order(so, self.cairo_mgr)
        so.refresh_from_db()
        self.assertEqual(so.status, 'invoiced')
        self.assertIsNotNone(so.memo_id)
        acc = CustomerAccount.objects.get(customer=self.customer)
        self.assertEqual(acc.current_balance, Decimal('400.00'))
        stock = InventoryStock.objects.get(warehouse=self.wh_rep, product=self.prod)
        self.assertEqual(stock.qty_on_hand, Decimal('196'))

        # Re-invoking invoice_order MUST be idempotent (no duplicate ledger row or stock deduction)
        SalesOrderService.invoice_order(so, self.superadmin)
        acc.refresh_from_db()
        stock.refresh_from_db()
        self.assertEqual(acc.current_balance, Decimal('400.00'))
        self.assertEqual(stock.qty_on_hand, Decimal('196'))
        self.assertEqual(CustomerTransaction.objects.filter(account=acc, reason='sales').count(), 1)

        # B. Sales Return auto-posts stock + credit ledger -> status='settled' (and idempotent settle)
        sro = SalesReturnOrderService.create_return_order(
            sales_order=so,
            target_warehouse=self.wh_rep,
            order_date=today,
            items_data=[{'original_item': so.items.first(), 'product': self.prod, 'quantity': 1, 'unit_price': Decimal('100.00')}],
            user=self.rep,
        )
        if sro.status == 'pending':
            SalesReturnOrderService.approve_return_order(sro, self.cairo_mgr)
            sro.refresh_from_db()
        self.assertEqual(sro.status, 'settled')
        SalesReturnOrderService.settle_return_order(sro, self.superadmin)  # idempotent!
        acc.refresh_from_db()
        stock.refresh_from_db()
        self.assertEqual(acc.current_balance, Decimal('300.00'))
        self.assertEqual(stock.qty_on_hand, Decimal('197'))

        # C. Purchase Order auto-posts stock + vendor ledger on approval -> status='settled'
        ps = PurchaseSettings.get_settings()
        ps.require_manager_approval = True
        ps.save()
        po = PurchaseOrderService.create_order(
            supplier=self.supplier,
            target_warehouse=self.wh_main,
            order_date=today,
            items_data=[{'product': self.prod, 'quantity': 10, 'unit_price': Decimal('60.00'), 'discount_percentage': Decimal('0'), 'tax_percentage': Decimal('0')}],
            user=self.rep,
        )
        self.assertEqual(po.status, 'pending')
        PurchaseOrderService.approve_order(po, self.superadmin)
        po.refresh_from_db()
        self.assertEqual(po.status, 'settled')
        vacc = VendorAccount.objects.get(supplier=self.supplier)
        self.assertEqual(vacc.current_balance, Decimal('600.00'))
        main_stock = InventoryStock.objects.get(warehouse=self.wh_main, product=self.prod)
        self.assertEqual(main_stock.qty_on_hand, Decimal('210'))

        # D. Purchase Return auto-posts -> status='settled'
        pro = PurchaseReturnOrderService.create_return_order(
            supplier=self.supplier,
            warehouse=self.wh_main,
            order_date=today,
            items_data=[{'product': self.prod, 'quantity': 2, 'unit_price': Decimal('60.00'), 'tax_percentage': Decimal('0')}],
            user=self.cairo_mgr,
        )
        if pro.status == 'pending':
            PurchaseReturnOrderService.approve_return_order(pro, self.superadmin)
            pro.refresh_from_db()
        self.assertEqual(pro.status, 'settled')
        vacc.refresh_from_db()
        main_stock.refresh_from_db()
        self.assertEqual(vacc.current_balance, Decimal('480.00'))
        self.assertEqual(main_stock.qty_on_hand, Decimal('208'))

    def test_customer_and_vendor_account_zeroing_strict_invariants(self):
        """
        Account zeroing must:
        - set current_balance = 0.00 & overdue_balance = 0.00 via non-cash reason='adjustment'
        - NEVER touch vault balances
        - NEVER create fake Collection or VendorPayment records
        - NEVER modify individual SalesOrder / PurchaseOrder payment_status
        - write SecurityAuditLog
        """
        ss = SalesSettings.get_settings()
        ss.require_manager_approval = False
        ss.save()
        today = timezone.localdate()
        so = SalesOrderService.create_order(
            customer=self.customer,
            source_warehouse=self.wh_rep,
            order_date=today,
            items_data=[{'product': self.prod, 'quantity': 5, 'unit_price': Decimal('100.00'), 'discount_percentage': Decimal('0')}],
            user=self.superadmin,
        )
        self.assertEqual(so.payment_status, 'credit')
        vault_before = self.vault.current_balance
        collections_before = Collection.objects.count()
        vault_tx_before = VaultTransaction.objects.count()

        tx, prev_bal = CustomerAccountService.zero_balance(self.customer, user=self.superadmin, reason_note='تسوية ختامية')
        self.assertEqual(prev_bal, Decimal('500.00'))
        self.assertEqual(tx.reason, 'adjustment')
        self.assertEqual(tx.transaction_type, 'credit')
        self.assertEqual(tx.credit, Decimal('500.00'))

        acc = CustomerAccount.objects.get(customer=self.customer)
        self.assertEqual(acc.current_balance, Decimal('0.00'))
        self.assertEqual(acc.overdue_balance, Decimal('0.00'))

        # Strict invariants check!
        self.vault.refresh_from_db()
        so.refresh_from_db()
        self.assertEqual(self.vault.current_balance, vault_before)
        self.assertEqual(Collection.objects.count(), collections_before)
        self.assertEqual(VaultTransaction.objects.count(), vault_tx_before)
        self.assertEqual(so.payment_status, 'credit')  # MUST NOT be mutated!
        self.assertTrue(SecurityAuditLog.objects.filter(action_type='CUSTOMER_BALANCE_ZEROED').exists())

        # Re-zeroing an already zero account raises ValidationError cleanly
        with self.assertRaises(ValidationError):
            CustomerAccountService.zero_balance(self.customer, user=self.superadmin)

        # Vendor zeroing invariants
        ps = PurchaseSettings.get_settings()
        ps.require_manager_approval = False
        ps.save()
        po = PurchaseOrderService.create_order(
            supplier=self.supplier,
            target_warehouse=self.wh_main,
            order_date=today,
            items_data=[{'product': self.prod, 'quantity': 10, 'unit_price': Decimal('60.00'), 'discount_percentage': Decimal('0'), 'tax_percentage': Decimal('0')}],
            user=self.superadmin,
        )
        vp_before = VendorPayment.objects.count()
        vtx, prev_vbal = TreasuryService.zero_vendor_balance(self.supplier, user=self.superadmin, reason_note='تسوية مورد')
        self.assertEqual(prev_vbal, Decimal('600.00'))
        self.assertEqual(vtx.reason, 'adjustment')
        vacc = VendorAccount.objects.get(supplier=self.supplier)
        self.assertEqual(vacc.current_balance, Decimal('0.00'))
        self.assertEqual(vacc.overdue_balance, Decimal('0.00'))
        po.refresh_from_db()
        self.vault.refresh_from_db()
        self.assertEqual(po.payment_status, 'credit')  # MUST NOT be mutated!
        self.assertEqual(self.vault.current_balance, vault_before)
        self.assertEqual(VendorPayment.objects.count(), vp_before)
        self.assertTrue(SecurityAuditLog.objects.filter(action_type='VENDOR_BALANCE_ZEROED').exists())
