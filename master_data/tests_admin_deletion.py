"""
Comprehensive tests for the 4-Category Django Admin Deletion Policy across all registered ERP models.
"""

from decimal import Decimal
from django.contrib import admin
from django.contrib.messages.storage.fallback import FallbackStorage
from django.core.exceptions import PermissionDenied
from django.core.management import call_command
from django.test import RequestFactory, TestCase

from accounts.models import Role, SecurityAuditLog, User
from activities.models import AgendaTodo
from catalog.models import Product, ProductCategory
from contacts.models import Contact
from inventory.models import InventoryStock, ProductTransferRequest, Warehouse
from master_data.models import Area, CompanyProfile, SalesSettings
from purchases.models import PurchaseOrder
from sales.models import CustomerAccount, CustomerTransaction, SalesOrder
from treasury.models import Vault, VaultTransaction, VendorPaymentRequest


def _make_admin_request(user):
    rf = RequestFactory()
    req = rf.post('/admin/')
    req.user = user
    req.session = {}
    req._messages = FallbackStorage(req)
    return req


class DjangoAdminDeletionPolicyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('setup_permissions')

    def setUp(self):
        self.super_role = Role.objects.get(name='superadmin')
        self.admin_user = User.objects.create_superuser(
            username='adm_del_pol@wea.com', email='adm_del_pol@wea.com', password='Password123!', role=self.super_role
        )
        self.req = _make_admin_request(self.admin_user)

    def test_every_registered_erp_model_has_deletion_category(self):
        missing = []
        for model, ma in admin.site._registry.items():
            if model._meta.app_label in ('auth', 'contenttypes', 'sessions', 'admin'):
                continue
            if not getattr(ma, 'admin_deletion_category', None):
                missing.append(f"{model._meta.app_label}.{model.__name__}")
        self.assertEqual(missing, [])

    def test_category_4_immutable_and_singletons_forbid_admin_deletion(self):
        immutable_models = [
            SecurityAuditLog, CustomerAccount, CustomerTransaction,
            VaultTransaction, InventoryStock, CompanyProfile, SalesSettings,
        ]
        for model in immutable_models:
            ma = admin.site._registry[model]
            self.assertFalse(ma.has_delete_permission(self.req), f"{model.__name__} must disable delete")
            self.assertNotIn('delete_selected', ma.get_actions(self.req))

        profile = CompanyProfile.get_settings()
        ma_profile = admin.site._registry[CompanyProfile]
        with self.assertRaises(PermissionDenied):
            ma_profile.delete_model(self.req, profile)

    def test_category_2_protected_master_blocks_cleanly_without_500(self):
        # System role cannot be deleted
        ma_role = admin.site._registry[Role]
        ma_role.delete_model(self.req, self.super_role)
        self.assertTrue(Role.objects.filter(pk=self.super_role.pk).exists())

        # Non-zero vault cannot be deleted
        vault = Vault.objects.create(name='خزنة محمية', serial_num=7701, current_balance=Decimal('500.00'))
        ma_vault = admin.site._registry[Vault]
        ma_vault.delete_model(self.req, vault)
        self.assertTrue(Vault.objects.filter(pk=vault.pk).exists())

    def test_category_3_controlled_service_blocks_bulk_delete_and_executed_transfers(self):
        for model in (User, SalesOrder, PurchaseOrder, ProductTransferRequest, VendorPaymentRequest):
            ma = admin.site._registry[model]
            self.assertNotIn('delete_selected', ma.get_actions(self.req))
            with self.assertRaises(PermissionDenied):
                ma.delete_queryset(self.req, model.objects.none())

        area = Area.objects.create(name='منطقة أدمين', code='ADM-A1', area_type='governorate')
        w1 = Warehouse.objects.create(name='مخزن أدمين 1', code='WH-ADM1', area=area)
        w2 = Warehouse.objects.create(name='مخزن أدمين 2', code='WH-ADM2', area=area)
        tr = ProductTransferRequest.objects.create(
            reference_number='TR-ADM-EXEC',
            requesting_user=self.admin_user,
            source_warehouse=w1,
            destination_warehouse=w2,
            status='executed',
        )
        ma_tr = admin.site._registry[ProductTransferRequest]
        ma_tr.delete_model(self.req, tr)
        # Executed transfer must remain protected!
        self.assertTrue(ProductTransferRequest.objects.filter(pk=tr.pk).exists())

    def test_category_1_safe_cascade_deletes_and_audits(self):
        from django.utils import timezone
        todo = AgendaTodo.objects.create(user=self.admin_user, title='مهمة تجريبية للحذف', date=timezone.localdate())
        todo_id = todo.pk
        ma_todo = admin.site._registry[AgendaTodo]
        ma_todo.delete_model(self.req, todo)
        self.assertFalse(AgendaTodo.objects.filter(pk=todo_id).exists())
        self.assertTrue(SecurityAuditLog.objects.filter(action_type='ADMIN_RECORD_DELETED', record_id=str(todo_id)).exists())
