from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from accounts.models import Role, Permission, SecurityAuditLog
from accounts.permission_registry import ERP_PERMISSIONS_CATALOG
from treasury.models import Vault, VaultTransaction, VendorPayment, VendorAccount
from treasury.services import (
    transfer_funds, reverse_vault_transaction, record_vault_manual_transaction
)
from contacts.models import Contact
from master_data.models import Area

User = get_user_model()


class TreasuryRBACAndStatsTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        # 1. Setup Roles (retrieve canonical roles auto-synced by migrations / setup_permissions)
        cls.superadmin_role = Role.objects.get(name=Role.ROLE_SUPERADMIN)
        cls.accountant_role = Role.objects.get(name=Role.ROLE_ACCOUNTANT)
        cls.manager_role = Role.objects.get(name=Role.ROLE_MANAGER)
        cls.rep_role = Role.objects.get(name=Role.ROLE_REP)

        # 2. Setup Areas
        cls.cairo_area = Area.objects.create(name='منطقة القاهرة الكبرى', code='CAI-01')
        cls.alex_area = Area.objects.create(name='منطقة الإسكندرية', code='ALX-01')

        # 3. Setup Users
        cls.superadmin_user = User.objects.create_superuser(
            email='superadmin@wea.com',
            username='superadmin@wea.com',
            password='TestPassword123!',
            role=cls.superadmin_role
        )

        cls.accountant_user = User.objects.create_user(
            email='accountant@wea.com',
            username='accountant@wea.com',
            password='TestPassword123!',
            role=cls.accountant_role
        )

        cls.manager_cairo = User.objects.create_user(
            email='manager.cairo@wea.com',
            username='manager.cairo@wea.com',
            password='TestPassword123!',
            role=cls.manager_role
        )
        cls.manager_cairo.assigned_areas.add(cls.cairo_area)

        cls.rep_cairo = User.objects.create_user(
            email='rep.cairo@wea.com',
            username='rep.cairo@wea.com',
            password='TestPassword123!',
            role=cls.rep_role
        )
        cls.rep_cairo.assigned_areas.add(cls.cairo_area)

        cls.rep_alex = User.objects.create_user(
            email='rep.alex@wea.com',
            username='rep.alex@wea.com',
            password='TestPassword123!',
            role=cls.rep_role
        )
        cls.rep_alex.assigned_areas.add(cls.alex_area)

        # 4. Setup Vaults
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
        """Verify all 10 required granular permissions exist in catalog."""
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
        """Superadmin has unrestricted access to all treasury pages and management."""
        self.client.login(username='superadmin@wea.com', password='TestPassword123!')

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
        """Accountant can view treasury and perform financial transfers, but cannot access user management."""
        # Grant accountant treasury module and action permissions
        perm_mod = Permission.objects.get_or_create(codename='module:treasury', defaults={'name': 'قسم الخزينة'})[0]
        perm_view = Permission.objects.get_or_create(codename='treasury:vaults/view', defaults={'name': 'عرض الخزن'})[0]
        perm_transfer = Permission.objects.get_or_create(codename='treasury:vaults/transfer', defaults={'name': 'تحويل أموال'})[0]
        self.accountant_role.permissions.add(perm_mod, perm_view, perm_transfer)
        self.accountant_user.clear_perm_cache()

        self.client.login(username='accountant@wea.com', password='TestPassword123!')

        response = self.client.get(reverse('vaults_list'))
        self.assertEqual(response.status_code, 200)

        response = self.client.get(reverse('vault_transfer'))
        self.assertEqual(response.status_code, 200)

        # Accountant is forbidden from accessing administrative user pages
        user_create_resp = self.client.get(reverse('user_create'))
        self.assertEqual(user_create_resp.status_code, 403)

    def test_manager_without_permission_forbidden(self):
        """Manager without explicit treasury permission receives HTTP 403 Forbidden."""
        self.client.login(username='manager.cairo@wea.com', password='TestPassword123!')

        response = self.client.get(reverse('vaults_list'))
        self.assertEqual(response.status_code, 403)

        response = self.client.get(reverse('vault_transfer'))
        self.assertEqual(response.status_code, 403)

    def test_manager_with_permission_scoped_to_regional_area(self):
        """Manager with permission can view only vaults in their managed area (Cairo), not Alex or unscoped HQ."""
        perm_mod = Permission.objects.get_or_create(codename='module:treasury', defaults={'name': 'قسم الخزينة'})[0]
        perm_view = Permission.objects.get_or_create(codename='treasury:vaults/view', defaults={'name': 'عرض الخزن'})[0]
        self.manager_role.permissions.add(perm_mod, perm_view)
        self.manager_cairo.clear_perm_cache()

        self.client.login(username='manager.cairo@wea.com', password='TestPassword123!')

        response = self.client.get(reverse('vaults_list'))
        self.assertEqual(response.status_code, 200)

        # Scoped queryset must contain Cairo rep vault, but NOT Alex rep vault
        vault_ids = [v.id for v in response.context['vaults']]
        self.assertIn(self.cairo_rep_vault.id, vault_ids)
        self.assertNotIn(self.alex_rep_vault.id, vault_ids)

    def test_representative_default_no_treasury_access(self):
        """Representative has zero treasury access by default and receives 403 Forbidden."""
        self.client.login(username='rep.cairo@wea.com', password='TestPassword123!')

        response = self.client.get(reverse('vaults_list'))
        self.assertEqual(response.status_code, 403)

        response = self.client.get(reverse('vault_transfer'))
        self.assertEqual(response.status_code, 403)

    def test_representative_with_permission_scoped_strictly_to_own_vault(self):
        """Representative with explicit permission can see only their own vault."""
        perm_mod = Permission.objects.get_or_create(codename='module:treasury', defaults={'name': 'قسم الخزينة'})[0]
        perm_view = Permission.objects.get_or_create(codename='treasury:vaults/view', defaults={'name': 'عرض الخزن'})[0]
        self.rep_role.permissions.add(perm_mod, perm_view)
        self.rep_cairo.clear_perm_cache()

        self.client.login(username='rep.cairo@wea.com', password='TestPassword123!')

        response = self.client.get(reverse('vaults_list'))
        self.assertEqual(response.status_code, 200)

        vault_ids = [v.id for v in response.context['vaults']]
        self.assertIn(self.cairo_rep_vault.id, vault_ids)
        self.assertNotIn(self.central_vault.id, vault_ids)
        self.assertNotIn(self.alex_rep_vault.id, vault_ids)

    def test_transfer_funds_atomic_success(self):
        """Test atomic funds transfer between two vaults with double entry and audit logging."""
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

        # Audit log verified
        audit_entry = SecurityAuditLog.objects.filter(
            action_type='VAULT_TRANSFER',
            module='treasury'
        ).last()
        self.assertIsNotNone(audit_entry)

    def test_transfer_funds_validation_failures(self):
        """Test transfer validation: insufficient balance, non-positive amount, same vault, inactive vault."""
        # 1. Non-positive amount
        with self.assertRaises(ValidationError):
            transfer_funds(self.central_vault, self.cairo_rep_vault, Decimal('0.00'), self.superadmin_user)

        with self.assertRaises(ValidationError):
            transfer_funds(self.central_vault, self.cairo_rep_vault, Decimal('-500.00'), self.superadmin_user)

        # 2. Same vault
        with self.assertRaises(ValidationError):
            transfer_funds(self.central_vault, self.central_vault, Decimal('1000.00'), self.superadmin_user)

        # 3. Insufficient balance
        with self.assertRaises(ValidationError):
            transfer_funds(self.cairo_rep_vault, self.central_vault, Decimal('9999999.00'), self.superadmin_user)

        # 4. Inactive vault
        self.cairo_rep_vault.is_active = False
        self.cairo_rep_vault.save()

        with self.assertRaises(ValidationError):
            transfer_funds(self.central_vault, self.cairo_rep_vault, Decimal('1000.00'), self.superadmin_user)

        self.cairo_rep_vault.is_active = True
        self.cairo_rep_vault.save()

    def test_reverse_vault_transaction_success(self):
        """Test transaction reversal: updates balance, sets is_reversed, and links reversal transaction."""
        # Create a manual inflow
        tx = record_vault_manual_transaction(
            vault=self.cairo_rep_vault,
            tx_type='inflow',
            amount=Decimal('5000.00'),
            user=self.superadmin_user,
            description="إيداع نقدي إضافي"
        )
        self.cairo_rep_vault.refresh_from_db()
        balance_after_inflow = self.cairo_rep_vault.current_balance

        # Reverse the inflow
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
        """Attempting to reverse an already reversed transaction raises ValidationError."""
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
        """Verify that statistics in vaults_list match underlying database aggregations."""
        self.client.login(username='superadmin@wea.com', password='TestPassword123!')

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
