import io
import openpyxl
from decimal import Decimal

from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from accounts.models import Role, Permission, SecurityAuditLog
from accounts.permission_registry import ERP_PERMISSIONS_CATALOG
from contacts.models import Contact
from master_data.models import Area
from treasury.models import Vault, VaultTransaction, VendorPayment, VendorAccount
from treasury.services import (
    transfer_funds, reverse_vault_transaction, record_vault_manual_transaction
)

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

