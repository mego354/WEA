import io
import openpyxl
from decimal import Decimal

from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone

from accounts.models import Role, Permission, SecurityAuditLog
from accounts.permission_registry import ERP_PERMISSIONS_CATALOG
from contacts.models import Contact
from master_data.models import Area
from treasury.models import Vault, VaultTransaction, VendorPayment, VendorAccount, VendorPaymentRequest
from treasury.services import (
    transfer_funds, reverse_vault_transaction, record_vault_manual_transaction,
    VendorPaymentRequestService, build_payment_request_timeline
)
from purchases.models import PurchaseOrder, PurchaseOrderItem
from purchases.services import PurchaseOrderService
from catalog.models import Product, ProductCategory
from inventory.models import Warehouse, InventoryStock

User = get_user_model()


class TreasuryExcelExportTestCase(TestCase):
    """Verifies treasury Excel exports."""

    def setUp(self):
        self.user = User.objects.create_superuser(
            email='treasuryadmin@weapharma.com',
            username='treasuryadmin@weapharma.com',
            password='Password123!',
            first_name='Treasury',
            last_name='Admin'
        )
        self.client = Client()
        self.client.login(username='treasuryadmin@weapharma.com', password='Password123!')

        self.vault = Vault.objects.create(
            name='الخزينة الرئيسية - المقر',
            vault_type='cash',
            current_balance=Decimal('500000.00'),
            is_active=True
        )
        self.supplier = Contact.objects.create(
            serial_num=7701,
            name='شركة فارما للتوزيع الدوائي',
            is_supplier=True,
            phone='01122334455'
        )
        self.payment = VendorPayment.objects.create(
            supplier=self.supplier,
            vault=self.vault,
            amount=Decimal('15000.00'),
            payment_method='cash',
            status='cleared',
            reference_number='REF-PAY-2026',
            created_by=self.user
        )

    def test_vendor_payments_export_excel(self):
        response = self.client.get(reverse('vendor_payments_export'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        self.assertIn('.xlsx', response['Content-Disposition'])

        wb = openpyxl.load_workbook(io.BytesIO(response.content))
        ws = wb.active
        self.assertTrue(ws.sheet_view.rightToLeft)
        found = any('شركة فارما للتوزيع' in str(cell.value) for row in ws.iter_rows() for cell in row)
        self.assertTrue(found)


class VaultDetailViewTestCase(TestCase):
    """Verifies vault detail view, permissions, and links."""

    def setUp(self):
        self.super_user = User.objects.create_superuser(
            email='vaultsuper@weapharma.com',
            username='vaultsuper@weapharma.com',
            password='Password123!',
            first_name='Super',
            last_name='User'
        )
        self.regular_user = User.objects.create_user(
            email='regular@weapharma.com',
            username='regular@weapharma.com',
            password='Password123!',
            first_name='Regular',
            last_name='User'
        )
        self.client = Client()
        self.vault = Vault.objects.create(
            name='خزينة فرع القاهرة الرئيسية',
            vault_type='cash',
            current_balance=Decimal('1250000.00'),
            is_active=True
        )

    def test_vault_detail_view_success(self):
        self.client.login(username='vaultsuper@weapharma.com', password='Password123!')
        url = reverse('vault_detail', kwargs={'pk': self.vault.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'خزينة فرع القاهرة الرئيسية')
        self.assertContains(response, str(self.vault.serial_num))
        self.assertContains(response, '1,250,000')

    def test_vault_detail_permission_denied_for_unauthorized_user(self):
        self.client.login(username='regular@weapharma.com', password='Password123!')
        url = reverse('vault_detail', kwargs={'pk': self.vault.pk})
        response = self.client.get(url)
        self.assertIn(response.status_code, [302, 403])

    def test_vaults_list_has_clickable_links_and_detail_button(self):
        self.client.login(username='vaultsuper@weapharma.com', password='Password123!')
        url = reverse('vaults_list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        detail_url = reverse('vault_detail', kwargs={'pk': self.vault.pk})
        self.assertContains(response, f'href="{detail_url}"')


class TreasuryRBACAndStatsTestCase(TestCase):
    """Verifies Treasury RBAC scoping, atomic fund transfers, reversals, deposits, withdrawals, and KPIs."""

    @classmethod
    def setUpTestData(cls):
        cls.superadmin_role = Role.objects.get(name=Role.ROLE_SUPERADMIN)
        cls.accountant_role = Role.objects.get(name=Role.ROLE_ACCOUNTANT)
        cls.manager_role = Role.objects.get(name=Role.ROLE_MANAGER)
        cls.rep_role = Role.objects.get(name=Role.ROLE_REP)

        cls.cairo_area = Area.objects.create(name='منطقة القاهرة الكبرى', code='CAI-01')
        cls.alex_area = Area.objects.create(name='منطقة الإسكندرية', code='ALX-01')

        cls.superadmin_user = User.objects.create_superuser(
            email='superadmin_tr@wea.com',
            username='superadmin_tr@wea.com',
            password='TestPassword123!',
            role=cls.superadmin_role
        )

        cls.accountant_user = User.objects.create_user(
            email='accountant_tr@wea.com',
            username='accountant_tr@wea.com',
            password='TestPassword123!',
            role=cls.accountant_role
        )

        cls.manager_cairo = User.objects.create_user(
            email='manager.cairo_tr@wea.com',
            username='manager.cairo_tr@wea.com',
            password='TestPassword123!',
            role=cls.manager_role
        )
        cls.manager_cairo.assigned_areas.add(cls.cairo_area)

        cls.rep_cairo = User.objects.create_user(
            email='rep.cairo_tr@wea.com',
            username='rep.cairo_tr@wea.com',
            password='TestPassword123!',
            role=cls.rep_role
        )
        cls.rep_cairo.assigned_areas.add(cls.cairo_area)

        cls.rep_alex = User.objects.create_user(
            email='rep.alex_tr@wea.com',
            username='rep.alex_tr@wea.com',
            password='TestPassword123!',
            role=cls.rep_role
        )
        cls.rep_alex.assigned_areas.add(cls.alex_area)

        cls.central_vault = Vault.objects.create(
            name='خزينة الإدارة العامة الرئيسية',
            vault_type='bank',
            current_balance=Decimal('1000000.00'),
            is_active=True
        )

        cls.cairo_rep_vault = Vault.objects.create(
            name='عهدة مندوب القاهرة',
            vault_type='cash',
            current_balance=Decimal('50000.00'),
            assigned_user=cls.rep_cairo,
            is_active=True
        )

        cls.alex_rep_vault = Vault.objects.create(
            name='عهدة مندوب الإسكندرية',
            vault_type='cash',
            current_balance=Decimal('25000.00'),
            assigned_user=cls.rep_alex,
            is_active=True
        )

    def setUp(self):
        self.client = Client()

    def test_treasury_permissions_in_catalog(self):
        treasury_cat = ERP_PERMISSIONS_CATALOG.get('treasury', {})
        self.assertTrue(treasury_cat, "Treasury module must exist in ERP_PERMISSIONS_CATALOG")

        pages = treasury_cat.get('pages', {})
        vault_actions = [a[0] for a in pages.get('vaults', {}).get('actions', [])]
        tx_actions = [a[0] for a in pages.get('transactions', {}).get('actions', [])]

        self.assertIn('treasury:vaults/view', vault_actions)
        self.assertIn('treasury:vaults/transfer', vault_actions)
        self.assertIn('treasury:vaults/manage', vault_actions)
        self.assertIn('treasury:transactions/list', tx_actions)
        self.assertIn('treasury:transactions/create', tx_actions)
        self.assertIn('treasury:transactions/reverse', tx_actions)

    def test_superadmin_full_treasury_access(self):
        self.client.login(username='superadmin_tr@wea.com', password='TestPassword123!')

        response = self.client.get(reverse('vaults_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'خزينة الإدارة العامة الرئيسية')
        self.assertContains(response, 'عهدة مندوب القاهرة')
        self.assertContains(response, 'عهدة مندوب الإسكندرية')

        response = self.client.get(reverse('vault_transactions_list'))
        self.assertEqual(response.status_code, 200)

        response = self.client.get(reverse('vendor_payments_list'))
        self.assertEqual(response.status_code, 200)

        response = self.client.get(reverse('accounting_vendors_list'))
        self.assertEqual(response.status_code, 200)

        response = self.client.get(reverse('vault_transfer'))
        self.assertEqual(response.status_code, 200)

    def test_accountant_treasury_access_and_admin_restriction(self):
        perm_mod = Permission.objects.get_or_create(codename='module:treasury', defaults={'name': 'قسم الخزينة'})[0]
        perm_view = Permission.objects.get_or_create(codename='treasury:vaults/view', defaults={'name': 'عرض الخزن'})[0]
        perm_transfer = Permission.objects.get_or_create(codename='treasury:vaults/transfer', defaults={'name': 'تحويل أموال'})[0]
        self.accountant_role.permissions.add(perm_mod, perm_view, perm_transfer)
        self.accountant_user.clear_perm_cache()

        self.client.login(username='accountant_tr@wea.com', password='TestPassword123!')

        response = self.client.get(reverse('vaults_list'))
        self.assertEqual(response.status_code, 200)

        response = self.client.get(reverse('vault_transfer'))
        self.assertEqual(response.status_code, 200)

        user_create_resp = self.client.get(reverse('user_create'))
        self.assertEqual(user_create_resp.status_code, 403)

    def test_manager_without_permission_forbidden(self):
        self.client.login(username='manager.cairo_tr@wea.com', password='TestPassword123!')

        response = self.client.get(reverse('vaults_list'))
        self.assertEqual(response.status_code, 403)

        response = self.client.get(reverse('vault_transfer'))
        self.assertEqual(response.status_code, 403)

    def test_manager_with_permission_scoped_to_regional_area(self):
        perm_mod = Permission.objects.get_or_create(codename='module:treasury', defaults={'name': 'قسم الخزينة'})[0]
        perm_view = Permission.objects.get_or_create(codename='treasury:vaults/view', defaults={'name': 'عرض الخزن'})[0]
        self.manager_role.permissions.add(perm_mod, perm_view)
        self.manager_cairo.clear_perm_cache()

        self.client.login(username='manager.cairo_tr@wea.com', password='TestPassword123!')

        response = self.client.get(reverse('vaults_list'))
        self.assertEqual(response.status_code, 200)

        vault_ids = [v.id for v in response.context['vaults']]
        self.assertIn(self.cairo_rep_vault.id, vault_ids)
        self.assertNotIn(self.alex_rep_vault.id, vault_ids)

    def test_representative_default_no_treasury_access(self):
        self.client.login(username='rep.cairo_tr@wea.com', password='TestPassword123!')

        response = self.client.get(reverse('vaults_list'))
        self.assertEqual(response.status_code, 403)

        response = self.client.get(reverse('vault_transfer'))
        self.assertEqual(response.status_code, 403)

    def test_representative_with_permission_scoped_strictly_to_own_vault(self):
        perm_mod = Permission.objects.get_or_create(codename='module:treasury', defaults={'name': 'قسم الخزينة'})[0]
        perm_view = Permission.objects.get_or_create(codename='treasury:vaults/view', defaults={'name': 'عرض الخزن'})[0]
        self.rep_role.permissions.add(perm_mod, perm_view)
        self.rep_cairo.clear_perm_cache()

        self.client.login(username='rep.cairo_tr@wea.com', password='TestPassword123!')

        response = self.client.get(reverse('vaults_list'))
        self.assertEqual(response.status_code, 200)

        vault_ids = [v.id for v in response.context['vaults']]
        self.assertIn(self.cairo_rep_vault.id, vault_ids)
        self.assertNotIn(self.central_vault.id, vault_ids)
        self.assertNotIn(self.alex_rep_vault.id, vault_ids)

    def test_transfer_funds_atomic_success(self):
        initial_source = self.central_vault.current_balance
        initial_dest = self.cairo_rep_vault.current_balance
        transfer_amt = Decimal('10000.00')

        tx_out, tx_in = transfer_funds(
            source_vault=self.central_vault,
            destination_vault=self.cairo_rep_vault,
            amount=transfer_amt,
            user=self.superadmin_user,
            description="تحويل عهدة تشغيلية للمندوب"
        )

        self.central_vault.refresh_from_db()
        self.cairo_rep_vault.refresh_from_db()

        self.assertEqual(self.central_vault.current_balance, initial_source - transfer_amt)
        self.assertEqual(self.cairo_rep_vault.current_balance, initial_dest + transfer_amt)

        self.assertEqual(tx_out.transaction_type, 'outflow')
        self.assertEqual(tx_out.reference_type, 'vault_transfer_out')
        self.assertEqual(tx_out.amount, transfer_amt)
        self.assertEqual(tx_in.transaction_type, 'inflow')
        self.assertEqual(tx_in.reference_type, 'vault_transfer_in')
        self.assertEqual(tx_in.amount, transfer_amt)

        audit_entry = SecurityAuditLog.objects.filter(
            action_type='VAULT_TRANSFER',
            module='treasury'
        ).last()
        self.assertIsNotNone(audit_entry)

    def test_transfer_funds_validation_failures(self):
        with self.assertRaises(ValidationError):
            transfer_funds(self.central_vault, self.cairo_rep_vault, Decimal('0.00'), self.superadmin_user)

        with self.assertRaises(ValidationError):
            transfer_funds(self.central_vault, self.cairo_rep_vault, Decimal('-500.00'), self.superadmin_user)

        with self.assertRaises(ValidationError):
            transfer_funds(self.central_vault, self.central_vault, Decimal('1000.00'), self.superadmin_user)

        with self.assertRaises(ValidationError):
            transfer_funds(self.cairo_rep_vault, self.central_vault, Decimal('9999999.00'), self.superadmin_user)

        self.cairo_rep_vault.is_active = False
        self.cairo_rep_vault.save()

        with self.assertRaises(ValidationError):
            transfer_funds(self.central_vault, self.cairo_rep_vault, Decimal('1000.00'), self.superadmin_user)

        self.cairo_rep_vault.is_active = True
        self.cairo_rep_vault.save()

    def test_reverse_vault_transaction_success(self):
        tx = record_vault_manual_transaction(
            vault=self.cairo_rep_vault,
            tx_type='inflow',
            amount=Decimal('5000.00'),
            user=self.superadmin_user,
            description="إيداع نقدي إضافي"
        )
        self.cairo_rep_vault.refresh_from_db()
        balance_after_inflow = self.cairo_rep_vault.current_balance

        reversal_tx = reverse_vault_transaction(
            transaction=tx,
            user=self.superadmin_user,
            reason="إلغاء الإيداع بسبب خطأ محاسبي"
        )

        self.cairo_rep_vault.refresh_from_db()
        tx.refresh_from_db()

        self.assertEqual(self.cairo_rep_vault.current_balance, balance_after_inflow - Decimal('5000.00'))
        self.assertTrue(tx.is_reversed)
        self.assertEqual(tx.reversed_by, self.superadmin_user)
        self.assertEqual(tx.reversal_transaction, reversal_tx)
        self.assertEqual(reversal_tx.transaction_type, 'outflow')

    def test_reverse_vault_transaction_double_reversal_prevented(self):
        tx = record_vault_manual_transaction(
            vault=self.cairo_rep_vault,
            tx_type='inflow',
            amount=Decimal('2000.00'),
            user=self.superadmin_user,
            description="إيداع للاختبار"
        )

        reverse_vault_transaction(tx, self.superadmin_user, reason="عكس أولي")

        with self.assertRaises(ValidationError):
            reverse_vault_transaction(tx, self.superadmin_user, reason="عكس ثانوي مكرر")

    def test_treasury_statistics_calculations(self):
        self.client.login(username='superadmin_tr@wea.com', password='TestPassword123!')

        response = self.client.get(reverse('vaults_list'))
        self.assertEqual(response.status_code, 200)

        stats = response.context['stats']
        total_balance_db = sum(v.current_balance for v in Vault.objects.all())
        cash_balance_db = sum(v.current_balance for v in Vault.objects.filter(vault_type='cash'))
        bank_balance_db = sum(v.current_balance for v in Vault.objects.filter(vault_type='bank'))

        self.assertEqual(stats['total_vaults'], Vault.objects.count())
        self.assertEqual(stats['total_balance'], total_balance_db)
        self.assertEqual(stats['cash_balance'], cash_balance_db)
        self.assertEqual(stats['bank_balance'], bank_balance_db)

    def test_vault_deposit_service_and_view(self):
        self.client.login(username='accountant_tr@wea.com', password='TestPassword123!')
        init_balance = self.cairo_rep_vault.current_balance
        dep_amount = Decimal('1500.00')

        res = self.client.get(reverse('vault_deposit') + f'?vault={self.cairo_rep_vault.id}')
        self.assertEqual(res.status_code, 200)

        post_data = {
            'vault_id': self.cairo_rep_vault.id,
            'amount': str(dep_amount),
            'description': 'إيداع نقدي تجريبي',
            'reference_number': 'DEP-999',
            'notes': 'ملاحظات إيداع'
        }
        post_res = self.client.post(reverse('vault_deposit'), post_data)
        self.assertEqual(post_res.status_code, 302)

        self.cairo_rep_vault.refresh_from_db()
        self.assertEqual(self.cairo_rep_vault.current_balance, init_balance + dep_amount)

        tx = VaultTransaction.objects.filter(vault=self.cairo_rep_vault, reference_type='deposit').first()
        self.assertIsNotNone(tx)
        self.assertEqual(tx.amount, dep_amount)
        self.assertEqual(tx.transaction_type, 'inflow')

        audit = SecurityAuditLog.objects.filter(action_type='VAULT_DEPOSIT', record_id=str(tx.id)).first()
        self.assertIsNotNone(audit)

    def test_vault_withdrawal_service_and_view(self):
        self.client.login(username='accountant_tr@wea.com', password='TestPassword123!')
        init_balance = self.cairo_rep_vault.current_balance
        wth_amount = Decimal('1000.00')

        res = self.client.get(reverse('vault_withdraw') + f'?vault={self.cairo_rep_vault.id}')
        self.assertEqual(res.status_code, 200)

        post_data = {
            'vault_id': self.cairo_rep_vault.id,
            'amount': str(wth_amount),
            'description': 'صرف نثريات تجريبية',
            'reference_number': 'WTH-888',
        }
        post_res = self.client.post(reverse('vault_withdraw'), post_data)
        self.assertEqual(post_res.status_code, 302)

        self.cairo_rep_vault.refresh_from_db()
        self.assertEqual(self.cairo_rep_vault.current_balance, init_balance - wth_amount)

        tx = VaultTransaction.objects.filter(vault=self.cairo_rep_vault, reference_type='withdrawal').first()
        self.assertIsNotNone(tx)
        self.assertEqual(tx.amount, wth_amount)
        self.assertEqual(tx.transaction_type, 'outflow')

        audit = SecurityAuditLog.objects.filter(action_type='VAULT_WITHDRAWAL', record_id=str(tx.id)).first()
        self.assertIsNotNone(audit)

    def test_vault_withdrawal_insufficient_funds_rejected(self):
        self.client.login(username='accountant_tr@wea.com', password='TestPassword123!')
        huge_amount = self.cairo_rep_vault.current_balance + Decimal('999999.00')

        post_data = {
            'vault_id': self.cairo_rep_vault.id,
            'amount': str(huge_amount),
            'description': 'محاولة سحب أكبر من الرصيد',
        }
        post_res = self.client.post(reverse('vault_withdraw'), post_data)
        self.assertEqual(post_res.status_code, 200)
        self.assertContains(post_res, "غير كافٍ")

    def test_vault_deposit_and_withdrawal_unauthorized_user_forbidden(self):
        self.client.login(username='rep.cairo_tr@wea.com', password='TestPassword123!')
        res_dep = self.client.get(reverse('vault_deposit'))
        self.assertEqual(res_dep.status_code, 403)
        res_wth = self.client.get(reverse('vault_withdraw'))
        self.assertEqual(res_wth.status_code, 403)

    def test_treasury_list_stats_respect_filters(self):
        self.client.login(username='accountant_tr@wea.com', password='TestPassword123!')
        res_v = self.client.get(reverse('vaults_list') + '?search=NONEXISTENT_VAULT')
        self.assertEqual(res_v.status_code, 200)
        self.assertEqual(res_v.context['stats']['total_vaults'], 0)

        res_tx = self.client.get(reverse('vault_transactions_list') + '?search=NONEXISTENT_TX')
        self.assertEqual(res_tx.status_code, 200)
        self.assertEqual(res_tx.context['stats']['total_count'], 0)

        res_vp = self.client.get(reverse('vendor_payments_list') + '?search=NONEXISTENT_VP')
        self.assertEqual(res_vp.status_code, 200)
        self.assertEqual(res_vp.context['stats']['total_count'], 0)


class VendorPaymentRequestWorkflowTests(TestCase):
    """
    Verifies Phase 2 Vendor Payment Request workflows:
    1. Creation and overpayment validation against PO balance
    2. Anti-self-approval enforcement
    3. Concurrency-safe execution with OneToOneField(VendorPayment) preventing double payments
    4. Rejection and Cancellation flows
    5. Timeline events
    """

    def setUp(self):
        self.client = Client()
        self.cairo = Area.objects.create(name='القاهرة الكبرى', code='CAI-TREAS')
        self.superadmin = User.objects.create_superuser(
            username='admin_vpr', email='admin_vpr@wea.com', password='Password123!'
        )
        self.mgr_role = Role.objects.get(name=Role.ROLE_MANAGER)
        self.acc_role = Role.objects.get(name=Role.ROLE_ACCOUNTANT)

        self.manager = User.objects.create_user(
            username='mgr_vpr', email='mgr_vpr@wea.com', password='Password123!', role=self.mgr_role
        )
        self.manager.assigned_areas.add(self.cairo)

        self.accountant = User.objects.create_user(
            username='acc_vpr', email='acc_vpr@wea.com', password='Password123!', role=self.acc_role
        )
        self.accountant.assigned_areas.add(self.cairo)

        self.wh = Warehouse.objects.create(name='مخزن القاهرة الرئيسي', code='WH-CAI-VPR', area=self.cairo, is_active=True)
        self.vault = Vault.objects.create(
            name='خزينة القاهرة المركزية', vault_type='cash', current_balance=Decimal('100000.00'), is_active=True
        )
        self.supplier = Contact.objects.create(
            name='شركة الدواء الحديث للتوريدات', code='SUP-MOD-01', is_supplier=True, area=self.cairo, status='customer'
        )
        self.vendor_acc = VendorAccount.get_or_create_for_supplier(self.supplier)

        self.cat = ProductCategory.objects.create(name='أدوية عامة', code='CAT-VPR-01')
        self.product = Product.objects.create(
            name='أوجمنتين 1 جم', sku_code='PRD-AUG-01', category=self.cat,
            retail_price=Decimal('90.00'), default_purchase_cost=Decimal('60.00'),
            is_active=True, sellable=True
        )
        self.stock = InventoryStock.objects.create(
            warehouse=self.wh, product=self.product, qty_on_hand=Decimal('100.00'), product_cost=Decimal('60.00')
        )

        from master_data.models import PurchaseSettings
        ps = PurchaseSettings.get_settings()
        ps.require_manager_approval = False
        ps.save()

        # Invoiced purchase order with outstanding balance: 10 * 60 = 600.00 LE
        self.po = PurchaseOrderService.create_order(
            supplier=self.supplier,
            target_warehouse=self.wh,
            order_date=timezone.now().date(),
            items_data=[{'product': self.product, 'quantity': 10, 'unit_price': Decimal('60.00')}],
            user=self.accountant
        )
        self.po.refresh_from_db()
        self.assertEqual(self.po.outstanding_balance, Decimal('600.00'))
        self.vendor_acc.refresh_from_db()
        self.assertEqual(self.vendor_acc.current_balance, Decimal('600.00'))

    def test_vendor_payment_request_creation_and_bounds(self):
        """Cannot create payment request exceeding PO outstanding balance."""
        # 1. Valid request of 400 LE
        req = VendorPaymentRequestService.create_request(
            supplier=self.supplier,
            amount=Decimal('400.00'),
            preferred_vault=self.vault,
            purchase_order=self.po,
            notes='دفعة تحت الحساب',
            user=self.accountant
        )
        self.assertEqual(req.status, 'pending')
        self.assertEqual(req.amount, Decimal('400.00'))

        # 2. Request for 700 LE exceeds 600 LE outstanding balance
        with self.assertRaises(ValidationError) as ctx:
            VendorPaymentRequestService.create_request(
                supplier=self.supplier,
                amount=Decimal('700.00'),
                preferred_vault=self.vault,
                purchase_order=self.po,
                user=self.accountant
            )
        self.assertIn('يتجاوز الرصيد المستحق', str(ctx.exception))

    def test_vendor_payment_request_anti_self_approval(self):
        """User who created payment request cannot approve or reject it."""
        req = VendorPaymentRequestService.create_request(
            supplier=self.supplier,
            amount=Decimal('300.00'),
            preferred_vault=self.vault,
            purchase_order=self.po,
            user=self.accountant
        )

        # Accountant attempts self-approval -> raises ValidationError
        with self.assertRaises(ValidationError) as ctx:
            VendorPaymentRequestService.approve_request(req, self.accountant)
        self.assertIn('لا يمكنك اعتماد طلب سداد قمت بإنشائه بنفسك', str(ctx.exception))

        # Manager approves -> success
        approved = VendorPaymentRequestService.approve_request(req, self.manager)
        self.assertEqual(approved.status, 'approved')

    def test_vendor_payment_request_execution_and_duplicate_prevention(self):
        """Executing payment request creates VendorPayment and prevents duplicate execution."""
        req = VendorPaymentRequestService.create_request(
            supplier=self.supplier,
            amount=Decimal('500.00'),
            preferred_vault=self.vault,
            purchase_order=self.po,
            user=self.accountant
        )
        VendorPaymentRequestService.approve_request(req, self.manager)

        init_vault_bal = self.vault.current_balance
        init_vendor_bal = self.vendor_acc.current_balance

        # Execute payment
        executed, payment = VendorPaymentRequestService.execute_request(
            req, self.accountant, vault=self.vault, payment_method='cash'
        )
        self.assertEqual(executed.status, 'executed')
        self.assertEqual(executed.vendor_payment, payment)

        self.vault.refresh_from_db()
        self.assertEqual(self.vault.current_balance, init_vault_bal - Decimal('500.00'))

        self.vendor_acc.refresh_from_db()
        self.assertEqual(self.vendor_acc.current_balance, init_vendor_bal - Decimal('500.00'))

        # Second execution attempt is rejected (double-payment prevention)
        with self.assertRaises(ValidationError) as ctx:
            VendorPaymentRequestService.execute_request(req, self.accountant, vault=self.vault)
        self.assertIn('تم صرف هذا الطلب مسبقاً', str(ctx.exception))

    def test_vendor_payment_request_rejection_and_cancellation(self):
        """Rejected or cancelled request cannot be executed."""
        req = VendorPaymentRequestService.create_request(
            supplier=self.supplier,
            amount=Decimal('200.00'),
            preferred_vault=self.vault,
            purchase_order=self.po,
            user=self.accountant
        )
        rejected = VendorPaymentRequestService.reject_request(req, self.manager, reason='عدم توفر سيولة حالياً')
        self.assertEqual(rejected.status, 'rejected')
        self.assertEqual(rejected.rejection_reason, 'عدم توفر سيولة حالياً')

        # Execution of rejected request fails
        with self.assertRaises(ValidationError):
            VendorPaymentRequestService.execute_request(req, self.accountant, vault=self.vault)

    def test_vendor_payment_request_timeline(self):
        """Timeline events accurately record submission, approval, and execution."""
        req = VendorPaymentRequestService.create_request(
            supplier=self.supplier,
            amount=Decimal('150.00'),
            preferred_vault=self.vault,
            purchase_order=self.po,
            user=self.accountant
        )
        VendorPaymentRequestService.approve_request(req, self.manager)
        VendorPaymentRequestService.execute_request(req, self.accountant, vault=self.vault)

        events = build_payment_request_timeline(req)
        self.assertTrue(len(events) >= 3)
        titles = [e['title'] for e in events]
        self.assertTrue(any('إنشاء' in t or 'تقديم' in t for t in titles))
        self.assertTrue(any('اعتماد' in t for t in titles))
        self.assertTrue(any('صرف' in t or 'تنفيذ' in t for t in titles))


class VaultEnhancementTests(TestCase):
    """
    Verifies Vault creation and transaction enhancements:
    1. Opening balance transaction with audit log on vault create
    2. Duplicate vault name validation
    3. Scoped destination vault in transfer
    4. Non-destructive transaction reversal
    """

    def setUp(self):
        self.client = Client()
        self.cairo = Area.objects.create(name='القاهرة', code='CAI-VH')
        self.superadmin = User.objects.create_superuser(
            username='admin_vh', email='admin_vh@wea.com', password='Password123!'
        )
        self.acc_role = Role.objects.get(name=Role.ROLE_ACCOUNTANT)
        self.accountant = User.objects.create_user(
            username='acc_vh', email='acc_vh@wea.com', password='Password123!', role=self.acc_role
        )
        self.accountant.assigned_areas.add(self.cairo)

        self.vault1 = Vault.objects.create(
            name='خزنة الفرع 1', vault_type='cash', current_balance=Decimal('20000.00'), is_active=True
        )
        self.vault2 = Vault.objects.create(
            name='خزنة الفرع 2', vault_type='cash', current_balance=Decimal('5000.00'), is_active=True
        )

    def test_vault_create_opening_balance_transaction_and_audit(self):
        """Creating a vault with initial balance generates opening transaction and audit log."""
        self.client.force_login(self.superadmin)
        post_data = {
            'name': 'خزنة المعادي الجديدة',
            'vault_type': 'cash',
            'current_balance': '15000.00',
            'description': 'خزنة فرع المعادي'
        }
        res = self.client.post(reverse('vault_create'), post_data)
        self.assertEqual(res.status_code, 302)

        new_vault = Vault.objects.filter(name='خزنة المعادي الجديدة').first()
        self.assertIsNotNone(new_vault)
        self.assertEqual(new_vault.current_balance, Decimal('15000.00'))

        opening_tx = VaultTransaction.objects.filter(vault=new_vault, reference_type='opening_balance').first()
        self.assertIsNotNone(opening_tx)
        self.assertEqual(opening_tx.amount, Decimal('15000.00'))
        self.assertEqual(opening_tx.transaction_type, 'inflow')

        audit = SecurityAuditLog.objects.filter(action_type='VAULT_OPENING_BALANCE', record_id=str(opening_tx.id)).first()
        self.assertIsNotNone(audit)

    def test_vault_create_duplicate_name_rejected(self):
        """Vault with duplicate name is rejected with error message."""
        self.client.force_login(self.superadmin)
        post_data = {
            'name': 'خزنة الفرع 1',  # Already exists
            'vault_type': 'cash',
            'current_balance': '1000.00'
        }
        res = self.client.post(reverse('vault_create'), post_data, follow=True)
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "توجد خزنة مسجلة مسبقاً بنفس الاسم")

    def test_vault_transfer_scoped_and_balance_updated(self):
        """Funds transferred between vaults update balances and create audit log."""
        outflow, inflow = transfer_funds(
            source_vault=self.vault1,
            destination_vault=self.vault2,
            amount=Decimal('4000.00'),
            user=self.accountant
        )
        self.vault1.refresh_from_db()
        self.vault2.refresh_from_db()

        self.assertEqual(self.vault1.current_balance, Decimal('16000.00'))
        self.assertEqual(self.vault2.current_balance, Decimal('9000.00'))

        self.assertEqual(outflow.transaction_type, 'outflow')
        self.assertEqual(inflow.transaction_type, 'inflow')

    def test_reverse_vault_transaction_non_destructive(self):
        """Reversing a vault transaction posts an exact balancing entry without deleting original."""
        from treasury.services import deposit_funds
        tx = deposit_funds(
            vault=self.vault1,
            amount=Decimal('3000.00'),
            user=self.accountant,
            description='إيداع مؤقت'
        )
        self.vault1.refresh_from_db()
        self.assertEqual(self.vault1.current_balance, Decimal('23000.00'))

        # Reverse the deposit
        reversal_tx = reverse_vault_transaction(tx=tx, user=self.accountant, reason='خطأ في رقم الحساب')
        tx.refresh_from_db()
        self.vault1.refresh_from_db()

        self.assertTrue(tx.is_reversed)
        self.assertEqual(tx.reversal_transaction, reversal_tx)
        self.assertEqual(self.vault1.current_balance, Decimal('20000.00'))
        self.assertEqual(reversal_tx.reference_type, 'reversal')
        self.assertEqual(reversal_tx.amount, Decimal('3000.00'))
        # Original transaction record is preserved in database
        self.assertTrue(VaultTransaction.objects.filter(id=tx.id).exists())


class TreasurySmartSearchValidationTests(TestCase):
    """Verifies Treasury smart-search vault API scoping, template rendering, and IDOR checks."""

    def setUp(self):
        from django.core.management import call_command

        call_command('setup_permissions')
        self.role_manager = Role.objects.get(name='manager')
        perm_req_create = Permission.objects.get(codename='treasury:payment_requests/create')
        self.role_manager.permissions.add(perm_req_create)
        self.role_accountant = Role.objects.get(name='accountant')

        self.cairo = Area.objects.create(code='TR-CAI', name='القاهرة', area_type='governorate', is_company_area=False)
        self.giza = Area.objects.create(code='TR-GIZ', name='الجيزة', area_type='governorate', is_company_area=False)
        self.corp = Area.objects.create(code='TR-CORP', name='موردين', area_type='governorate', is_company_area=True)

        self.mgr_cairo = User.objects.create_user(
            username='tr_mgr_cai@wea.com', email='tr_mgr_cai@wea.com', password='Password123!', role=self.role_manager
        )
        self.mgr_cairo.assigned_areas.add(self.cairo)
        self.accountant = User.objects.create_user(
            username='tr_acc@wea.com', email='tr_acc@wea.com', password='Password123!', role=self.role_accountant
        )

        self.corp_sup = Contact.objects.create(
            serial_num=16032, name='مصنع العز تيوب', is_supplier=True, status='customer', area=self.corp
        )
        self.non_sup = Contact.objects.create(
            serial_num=91001, name='عميل عادي', is_supplier=False, is_customer=True, status='customer', area=self.cairo
        )
        self.vault_cairo = Vault.objects.create(serial_num=9201, name='خزنة القاهرة النقدية', area=self.cairo, current_balance=Decimal('5000.00'))
        self.vault_giza = Vault.objects.create(serial_num=9202, name='خزنة الجيزة النقدية', area=self.giza, current_balance=Decimal('5000.00'))

    def test_payment_request_create_validates_preferred_vault_and_supplier(self):
        self.client.force_login(self.mgr_cairo)

        # Out-of-scope vault returns 403 Forbidden
        bad_vault = self.client.post(reverse('vendor_payment_create'), {
            'supplier': self.corp_sup.id,
            'vault': self.vault_giza.id,
            'amount': '250.00',
        })
        self.assertEqual(bad_vault.status_code, 403)

        # Non-supplier contact is rejected (returns 403 or redirects)
        bad_sup = self.client.post(reverse('vendor_payment_create'), {
            'supplier': self.non_sup.id,
            'vault': self.vault_cairo.id,
            'amount': '250.00',
        })
        self.assertIn(bad_sup.status_code, [302, 403])

        # Requirement B6: Payment request creation redirects to vendor_payment_create
        redir = self.client.get(reverse('vendor_payment_request_create') + f'?supplier={self.corp_sup.id}')
        self.assertEqual(redir.status_code, 302)
        self.assertIn(reverse('vendor_payment_create'), redir.url)

        # Vault search API returns Cairo vault for Cairo manager, never Giza vault
        v_api = self.client.get(reverse('purchases_vaults_search_api') + '?q=النقديه')
        self.assertEqual(v_api.status_code, 200)
        ids = [r['id'] for r in v_api.json()['results']]
        self.assertIn(self.vault_cairo.id, ids)
        self.assertNotIn(self.vault_giza.id, ids)

    def test_treasury_views_render_smart_select_attributes(self):
        self.client.force_login(self.accountant)
        for url_name in ('vendor_payment_create', 'vendor_payments_list', 'vendor_transactions_list', 'vault_transactions_list', 'vault_transfer'):
            resp = self.client.get(reverse(url_name))
            self.assertEqual(resp.status_code, 200, f"Failed GET {url_name}")
            self.assertContains(resp, 'data-smart-select="true"')


class VaultCrudAndScopingTests(TestCase):
    """
    Verifies Vault CRUD operations, data scoping (SuperAdmin / Manager / Rep),
    safe deletion integrity validations (blocking delete when balance != 0 or transactions exist),
    opening balance recording, audit logging, and advanced filters in vaults_list.
    """

    def setUp(self):
        from django.core.management import call_command
        call_command('setup_permissions')

        self.cairo = Area.objects.create(name='القاهرة', code='CAI-VLT-CRUD', area_type='governorate')
        self.nasr_city = Area.objects.create(name='مدينة نصر', code='NC-VLT-CRUD', area_type='subarea', parent=self.cairo)
        self.giza = Area.objects.create(name='الجيزة', code='GIZ-VLT-CRUD', area_type='governorate')

        self.role_super = Role.objects.get(name=Role.ROLE_SUPERADMIN)
        self.role_manager = Role.objects.get(name=Role.ROLE_MANAGER)
        self.role_rep = Role.objects.get(name=Role.ROLE_REP)

        from django.contrib.auth.models import Permission
        p_manage = Permission.objects.get(codename='treasury:vaults/manage')
        p_delete = Permission.objects.get(codename='treasury:vaults/delete')
        self.role_manager.permissions.add(p_manage, p_delete)

        self.superadmin = User.objects.create_superuser(
            username='vlt_crud_admin', email='vlt_crud_admin@wea.com', password='Password123!', role=self.role_super
        )
        self.manager_cairo = User.objects.create_user(
            username='vlt_crud_mgr_cai', email='vlt_crud_mgr_cai@wea.com', password='Password123!', role=self.role_manager
        )
        self.manager_cairo.assigned_areas.add(self.cairo)

        self.manager_giza = User.objects.create_user(
            username='vlt_crud_mgr_giz', email='vlt_crud_mgr_giz@wea.com', password='Password123!', role=self.role_manager
        )
        self.manager_giza.assigned_areas.add(self.giza)

        self.rep_cairo = User.objects.create_user(
            username='vlt_crud_rep_cai', email='vlt_crud_rep_cai@wea.com', password='Password123!', role=self.role_rep
        )
        self.rep_cairo.assigned_areas.add(self.nasr_city)

        self.vault_cairo = Vault.objects.create(
            name='الخزينة المركزية القاهرة',
            vault_type='cash',
            area=self.cairo,
            current_balance=Decimal('50000.00'),
            is_active=True
        )
        self.vault_rep_nasr = Vault.objects.create(
            name='عهدة مندوب مدينة نصر المالية',
            vault_type='cash',
            is_rep_vault=True,
            area=self.nasr_city,
            assigned_user=self.rep_cairo,
            current_balance=Decimal('0.00'),
            is_active=True
        )
        self.vault_bank_giza = Vault.objects.create(
            name='حساب البنك الأهلي الجيزة',
            vault_type='bank',
            area=self.giza,
            current_balance=Decimal('120000.00'),
            is_active=False
        )

    def test_vault_create_with_opening_balance_and_audit_log(self):
        """Creating a vault with opening balance records VaultTransaction and SecurityAuditLog."""
        self.client.force_login(self.superadmin)
        post_data = {
            'name': 'خزينة فرعية جديدة للاختبار',
            'vault_type': 'cash',
            'area': self.cairo.id,
            'initial_balance': '15000.00',
            'is_active': 'on'
        }
        res = self.client.post(reverse('vault_create'), post_data)
        v = Vault.objects.filter(name='خزينة فرعية جديدة للاختبار').first()
        self.assertIsNotNone(v)
        self.assertRedirects(res, reverse('vaults_list'))
        self.assertEqual(v.current_balance, Decimal('15000.00'))
        self.assertEqual(v.area, self.cairo)

        # Opening balance transaction created
        tx = VaultTransaction.objects.filter(vault=v, reference_type='opening_balance').first()
        self.assertIsNotNone(tx)
        self.assertEqual(tx.amount, Decimal('15000.00'))

        # SecurityAuditLog recorded
        self.assertTrue(SecurityAuditLog.objects.filter(action_type='VAULT_CREATED', record_id=v.id).exists())
        self.assertTrue(SecurityAuditLog.objects.filter(action_type='VAULT_OPENING_BALANCE', record_id=tx.id).exists())

    def test_vault_edit_scoping(self):
        """Managers can edit vaults within their assigned governorate/subareas, but are blocked outside it."""
        # Manager Cairo edits Nasr City vault -> Allowed
        self.client.force_login(self.manager_cairo)
        get_res = self.client.get(reverse('vault_edit', args=[self.vault_rep_nasr.id]))
        self.assertEqual(get_res.status_code, 200)

        post_res = self.client.post(reverse('vault_edit', args=[self.vault_rep_nasr.id]), {
            'name': 'عهدة مندوب مدينة نصر المعدلة',
            'vault_type': 'cash',
            'area': self.nasr_city.id,
            'assigned_user': self.rep_cairo.id,
            'is_rep_vault': 'on',
            'is_active': 'on'
        })
        self.assertRedirects(post_res, reverse('vault_detail', args=[self.vault_rep_nasr.id]))
        self.vault_rep_nasr.refresh_from_db()
        self.assertEqual(self.vault_rep_nasr.name, 'عهدة مندوب مدينة نصر المعدلة')

        # Manager Giza attempts to edit Nasr City vault -> Forbidden 403
        self.client.force_login(self.manager_giza)
        bad_get = self.client.get(reverse('vault_edit', args=[self.vault_rep_nasr.id]))
        self.assertEqual(bad_get.status_code, 403)

        bad_post = self.client.post(reverse('vault_edit', args=[self.vault_rep_nasr.id]), {
            'name': 'محاولة اختراق خزينة القاهرة',
        })
        self.assertEqual(bad_post.status_code, 403)

    def test_vault_delete_success(self):
        """Deleting an empty vault with zero balance and no transactions succeeds with audit log."""
        v_empty = Vault.objects.create(name='خزينة فارغة للحذف', vault_type='cash', area=self.cairo, current_balance=Decimal('0.00'))
        v_id = v_empty.id

        self.client.force_login(self.superadmin)
        res = self.client.post(reverse('vault_delete', args=[v_id]))
        self.assertRedirects(res, reverse('vaults_list'))
        self.assertFalse(Vault.objects.filter(id=v_id).exists())

        audit = SecurityAuditLog.objects.filter(action_type='VAULT_DELETED', record_id=v_id).first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.actor, self.superadmin)

    def test_vault_delete_blocked_when_balance_nonzero(self):
        """Vault with non-zero balance cannot be deleted."""
        self.client.force_login(self.superadmin)
        res = self.client.post(reverse('vault_delete', args=[self.vault_cairo.id]), follow=True)
        self.assertEqual(res.status_code, 200)
        self.assertTrue(Vault.objects.filter(id=self.vault_cairo.id).exists())
        self.assertContains(res, "لا يمكن حذف الخزنة لوجود رصيد حالي بها")

    def test_vault_delete_blocked_when_transactions_exist(self):
        """Vault with zero balance cannot be deleted if transactions are linked to it."""
        v_tx = Vault.objects.create(name='خزينة بحركات سابقة', vault_type='cash', area=self.cairo, current_balance=Decimal('0.00'))
        VaultTransaction.objects.create(
            vault=v_tx,
            transaction_type='inflow',
            amount=Decimal('100.00'),
            running_balance=Decimal('100.00'),
            description='حركة اختبارية',
            created_by=self.superadmin
        )

        self.client.force_login(self.superadmin)
        res = self.client.post(reverse('vault_delete', args=[v_tx.id]), follow=True)
        self.assertEqual(res.status_code, 200)
        self.assertTrue(Vault.objects.filter(id=v_tx.id).exists())
        self.assertContains(res, "لا يمكن حذف الخزنة لوجود حركات مالية مسجلة عليها")

    def test_vault_delete_scoping(self):
        """Out-of-region managers cannot delete vaults in other regions."""
        self.client.force_login(self.manager_giza)
        res = self.client.post(reverse('vault_delete', args=[self.vault_rep_nasr.id]))
        self.assertEqual(res.status_code, 403)
        self.assertTrue(Vault.objects.filter(id=self.vault_rep_nasr.id).exists())

    def test_vaults_list_advanced_filters(self):
        """Advanced filters drawer correctly filters by vault_type, custody_type, status, area, and balance ranges."""
        self.client.force_login(self.superadmin)

        # Filter by vault_type: bank
        res_bank = self.client.get(reverse('vaults_list') + '?vault_type=bank')
        self.assertContains(res_bank, self.vault_bank_giza.name)
        self.assertNotContains(res_bank, self.vault_cairo.name)

        # Filter by custody_type: rep
        res_rep = self.client.get(reverse('vaults_list') + '?custody_type=rep')
        self.assertContains(res_rep, self.vault_rep_nasr.name)
        self.assertNotContains(res_rep, self.vault_cairo.name)

        # Filter by status: inactive
        res_inact = self.client.get(reverse('vaults_list') + '?status=inactive')
        self.assertContains(res_inact, self.vault_bank_giza.name)
        self.assertNotContains(res_inact, self.vault_cairo.name)

        # Filter by area: Cairo (includes child subarea Nasr City)
        res_area = self.client.get(reverse('vaults_list') + f'?area={self.cairo.id}')
        self.assertContains(res_area, self.vault_cairo.name)
        self.assertContains(res_area, self.vault_rep_nasr.name)
        self.assertNotContains(res_area, self.vault_bank_giza.name)

        # Filter by balance range: balance_min >= 100000
        res_bal = self.client.get(reverse('vaults_list') + '?balance_min=100000.00')
        self.assertContains(res_bal, self.vault_bank_giza.name)
        self.assertNotContains(res_bal, self.vault_cairo.name)
        self.assertNotContains(res_bal, self.vault_rep_nasr.name)

    def test_reverse_linked_transfer_blocked_for_double_entry_integrity(self):
        """AUD-010: Linked vault transfer transactions cannot be half-reversed independently."""
        from treasury.services import transfer_funds, reverse_vault_transaction
        from django.core.exceptions import ValidationError
        out_tx, in_tx = transfer_funds(
            source_vault=self.vault_cairo,
            destination_vault=self.vault_rep_nasr,
            amount=Decimal('100.00'),
            user=self.superadmin,
            description='تحويل اختبار'
        )
        with self.assertRaises(ValidationError):
            reverse_vault_transaction(tx=out_tx, user=self.superadmin, reason='اختبار')

    def test_payment_request_cancel_does_not_crash_audit_log(self):
        """AUD-018: VendorPaymentRequestService.cancel_request creates valid ApprovalAuditLog without TypeError."""
        from contacts.models import Contact
        from treasury.models import VendorPaymentRequest
        from treasury.services import VendorPaymentRequestService
        supplier = Contact.objects.create(name='مورد إلغاء', is_supplier=True, area=self.cairo)
        req = VendorPaymentRequest.objects.create(
            supplier=supplier, amount=Decimal('500.00'), status='pending', created_by=self.superadmin
        )
        cancelled = VendorPaymentRequestService.cancel_request(req, self.superadmin, reason='إلغاء اختباري')
        self.assertEqual(cancelled.status, 'cancelled')



