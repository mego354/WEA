from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission

from accounts.models import Role, RoleModuleScope, UserModuleScope
from accounts.scope_service import ScopeResolutionService
from accounts.permissions import can_user_access_object, get_scoped_queryset
from master_data.models import Area
from contacts.models import Contact
from activities.models import Visit, VisitTemplate
from sales.models import SalesOrder
from purchases.models import PurchaseOrder
from inventory.models import Warehouse, ProductTransferRequest
from treasury.models import Vault, VendorPayment
from catalog.models import Product, ProductCategory

User = get_user_model()


class ConfigurableAuthorizationScopeTests(TestCase):
    """
    Exhaustive test suite for the Configurable Authorization, Organizational Scope,
    and Module-Based Permission Refactoring.
    """

    def setUp(self):
        self.client = Client()

        # 1. Territorial Areas
        # Cairo Governorate (Main Area)
        self.cairo = Area.objects.create(name='القاهرة', code='CAI', area_type='governorate')
        self.nasr_city = Area.objects.create(name='مدينة نصر', code='NASR', area_type='sub_area', parent=self.cairo)
        self.maadi = Area.objects.create(name='المعادي', code='MAADI', area_type='sub_area', parent=self.cairo)

        # Giza Governorate (Different Main Area)
        self.giza = Area.objects.create(name='الجيزة', code='GIZ', area_type='governorate')
        self.dokki = Area.objects.create(name='الدقي', code='DOKKI', area_type='sub_area', parent=self.giza)

        # 2. Roles
        self.superadmin_role = Role.objects.get(name='superadmin')
        self.manager_role = Role.objects.get(name='manager')
        self.rep_role = Role.objects.get(name='rep')
        self.accountant_role = Role.objects.get(name='accountant')

        # 3. Users
        self.super_user = User.objects.create_superuser(
            username='boss', email='boss@wea.com', password='password123', name='المدير العام'
        )

        # Cairo Manager
        self.cairo_manager = User.objects.create_user(
            username='cairo_mgr', email='cmgr@wea.com', password='password123',
            name='مدير القاهرة', role=self.manager_role
        )
        self.cairo_manager.assigned_areas.add(self.cairo)

        # Giza Manager
        self.giza_manager = User.objects.create_user(
            username='giza_mgr', email='gmgr@wea.com', password='password123',
            name='مدير الجيزة', role=self.manager_role
        )
        self.giza_manager.assigned_areas.add(self.giza)

        # Cairo Rep 1 (Nasr City)
        self.rep_nasr = User.objects.create_user(
            username='rep_nasr', email='rnasr@wea.com', password='password123',
            name='مندوب مدينة نصر', role=self.rep_role
        )
        self.rep_nasr.assigned_areas.add(self.nasr_city)

        # Cairo Rep 2 (Maadi)
        self.rep_maadi = User.objects.create_user(
            username='rep_maadi', email='rmaadi@wea.com', password='password123',
            name='مندوب المعادي', role=self.rep_role
        )
        self.rep_maadi.assigned_areas.add(self.maadi)

        # Giza Rep (Dokki)
        self.rep_dokki = User.objects.create_user(
            username='rep_dokki', email='rdokki@wea.com', password='password123',
            name='مندوب الدقي', role=self.rep_role
        )
        self.rep_dokki.assigned_areas.add(self.dokki)

        # 4. Contacts (Territorial Customers & Suppliers)
        self.contact_nasr = Contact.objects.create(
            name='صيدلية الأمل - نصر', area=self.cairo, brick=self.nasr_city,
            is_customer=True, status='active', created_by=self.rep_nasr
        )
        self.contact_maadi = Contact.objects.create(
            name='صيدلية المعادي الكبرى', area=self.cairo, brick=self.maadi,
            is_customer=True, status='active', created_by=self.rep_maadi
        )
        self.contact_dokki = Contact.objects.create(
            name='صيدلية الدقي المركزية', area=self.giza, brick=self.dokki,
            is_customer=True, status='active', created_by=self.rep_dokki
        )

        # Territorial Supplier in Giza
        self.supplier_giza = Contact.objects.create(
            name='شركة الأهرام للتوريدات - الجيزة', area=self.giza, brick=self.dokki,
            is_supplier=True, status='active', created_by=self.giza_manager
        )

        # 5. Warehouses
        self.wh_main = Warehouse.objects.create(name='المخزن المركزي', code='WH-MAIN-TEST', is_main=True, area=self.cairo)
        self.wh_nasr = Warehouse.objects.create(name='مخزن عهدة نصر', code='WH-NASR-TEST', assigned_user=self.rep_nasr, area=self.nasr_city)
        self.wh_dokki = Warehouse.objects.create(name='مخزن عهدة دقي', code='WH-DOKKI-TEST', assigned_user=self.rep_dokki, area=self.dokki)

        # 6. Vaults
        self.vault_nasr = Vault.objects.create(name='خزنة عهدة نصر', assigned_user=self.rep_nasr, area=self.nasr_city)
        self.vault_dokki = Vault.objects.create(name='خزنة عهدة دقي', assigned_user=self.rep_dokki, area=self.dokki)

        # 7. Products
        self.cat = ProductCategory.objects.create(name='أدوية عامة')
        self.product = Product.objects.create(
            name='كونجستال أقراص', sku_code='CONG-01', category=self.cat,
            retail_price=Decimal('40.00'), default_purchase_cost=Decimal('28.00')
        )

    # =========================================================================
    # A. Dynamic Scope Resolution & Custom Overrides Tests
    # =========================================================================

    def test_role_module_scope_resolution(self):
        """Standard roles resolve their seeded scopes."""
        # Rep contacts scope is 'brick'
        self.assertEqual(ScopeResolutionService.get_user_scope(self.rep_nasr, 'contacts', 'view'), 'brick')
        self.assertEqual(ScopeResolutionService.get_user_scope(self.rep_nasr, 'sales', 'view'), 'own')

        # Manager contacts and sales scope is 'area'
        self.assertEqual(ScopeResolutionService.get_user_scope(self.cairo_manager, 'contacts', 'view'), 'area')
        self.assertEqual(ScopeResolutionService.get_user_scope(self.cairo_manager, 'sales', 'view'), 'area')
        self.assertEqual(ScopeResolutionService.get_user_scope(self.cairo_manager, 'sales', 'manage'), 'area')

    def test_user_custom_module_scope_override(self):
        """User with has_custom_permissions=True overrides role scopes 100%."""
        # Configure UserModuleScope for rep_nasr to have 'all' scope in contacts
        UserModuleScope.objects.create(
            user=self.rep_nasr,
            module='contacts',
            view_scope='all',
            manage_scope='area'
        )

        # Without custom flag, still returns role scope
        self.rep_nasr.has_custom_permissions = False
        self.rep_nasr.save()
        if hasattr(self.rep_nasr, '_module_scope_cache'):
            delattr(self.rep_nasr, '_module_scope_cache')
        self.assertEqual(ScopeResolutionService.get_user_scope(self.rep_nasr, 'contacts', 'view'), 'brick')

        # With custom flag, returns user custom scope
        self.rep_nasr.has_custom_permissions = True
        self.rep_nasr.save()
        if hasattr(self.rep_nasr, '_module_scope_cache'):
            delattr(self.rep_nasr, '_module_scope_cache')
        self.assertEqual(ScopeResolutionService.get_user_scope(self.rep_nasr, 'contacts', 'view'), 'all')
        self.assertEqual(ScopeResolutionService.get_user_scope(self.rep_nasr, 'contacts', 'manage'), 'area')

    # =========================================================================
    # B. Contacts Scoping Tests
    # =========================================================================

    def test_contacts_brick_scoping_for_representative(self):
        """Representative with 'brick' view scope only sees contacts in their assigned Brick."""
        qs = get_scoped_queryset(Contact.objects.all(), self.rep_nasr, 'contact', 'view')
        self.assertIn(self.contact_nasr, qs)
        self.assertNotIn(self.contact_maadi, qs)
        self.assertNotIn(self.contact_dokki, qs)

    def test_contacts_area_scoping_for_manager(self):
        """Manager with 'area' view scope sees all child bricks in their Governorate (Cairo) but not Giza."""
        qs = get_scoped_queryset(Contact.objects.all(), self.cairo_manager, 'contact', 'view')
        self.assertIn(self.contact_nasr, qs)
        self.assertIn(self.contact_maadi, qs)
        self.assertNotIn(self.contact_dokki, qs)

    def test_view_vs_manage_scope_separation_on_contacts(self):
        """
        Configure Rep with 'brick' view scope and 'own' manage scope:
        Rep can view peer's contact in same brick, but cannot edit it.
        """
        # Assign rep_maadi to Nasr City as well
        self.rep_maadi.assigned_areas.add(self.nasr_city)
        # Configure rep role with view='brick', manage='own'
        RoleModuleScope.objects.filter(role=self.rep_role, module='contacts').update(
            view_scope='brick', manage_scope='own'
        )

        # Can rep_maadi view contact_nasr (in Nasr City)? Yes
        self.assertTrue(can_user_access_object(self.rep_maadi, self.contact_nasr, 'view'))
        # Can rep_maadi edit contact_nasr (created by rep_nasr)? No, because manage_scope is 'own'
        self.assertFalse(can_user_access_object(self.rep_maadi, self.contact_nasr, 'edit'))
        # Can rep_nasr edit their own contact? Yes
        self.assertTrue(can_user_access_object(self.rep_nasr, self.contact_nasr, 'edit'))

    # =========================================================================
    # C. Sales Orders & Anti-Self-Approval Tests
    # =========================================================================

    def test_sales_orders_own_scoping_for_representative(self):
        """Representative with 'own' scope only sees their created sales orders."""
        so_nasr = SalesOrder.objects.create(
            order_number='SO-NASR-1', customer=self.contact_nasr,
            source_warehouse=self.wh_nasr, created_by=self.rep_nasr,
            subtotal=Decimal('100.00'), grand_total=Decimal('100.00'), status='pending'
        )
        so_maadi = SalesOrder.objects.create(
            order_number='SO-MAADI-1', customer=self.contact_maadi,
            source_warehouse=self.wh_main, created_by=self.rep_maadi,
            subtotal=Decimal('200.00'), grand_total=Decimal('200.00'), status='pending'
        )

        qs = get_scoped_queryset(SalesOrder.objects.all(), self.rep_nasr, 'salesorder', 'view')
        self.assertIn(so_nasr, qs)
        self.assertNotIn(so_maadi, qs)

    def test_manager_can_approve_subordinate_sales_order(self):
        """Cairo Manager can approve Cairo Rep's sales order."""
        so_nasr = SalesOrder.objects.create(
            order_number='SO-NASR-2', customer=self.contact_nasr,
            source_warehouse=self.wh_nasr, created_by=self.rep_nasr,
            subtotal=Decimal('100.00'), grand_total=Decimal('100.00'), status='pending'
        )
        # Cairo manager can access and approve
        self.assertTrue(can_user_access_object(self.cairo_manager, so_nasr, 'view'))
        self.assertTrue(can_user_access_object(self.cairo_manager, so_nasr, 'approve'))

        # Giza manager CANNOT access or approve Cairo order
        self.assertFalse(can_user_access_object(self.giza_manager, so_nasr, 'view'))
        self.assertFalse(can_user_access_object(self.giza_manager, so_nasr, 'approve'))

    def test_anti_self_approval_on_sales_order(self):
        """User cannot approve their own created order regardless of role."""
        so_mgr = SalesOrder.objects.create(
            order_number='SO-MGR-1', customer=self.contact_nasr,
            source_warehouse=self.wh_main, created_by=self.cairo_manager,
            subtotal=Decimal('150.00'), grand_total=Decimal('150.00'), status='pending'
        )
        # Cairo manager created this order -> ANTI-SELF-APPROVAL REJECTS
        self.assertFalse(can_user_access_object(self.cairo_manager, so_mgr, 'approve'))
        self.assertFalse(can_user_access_object(self.cairo_manager, so_mgr, 'reject'))

    # =========================================================================
    # D. Territorial Suppliers & Purchases Scoping
    # =========================================================================

    def test_territorial_suppliers_geographical_scoping(self):
        """Suppliers follow geographic scoping (A2): Giza supplier is visible in Giza, not Cairo."""
        cairo_contacts = get_scoped_queryset(Contact.objects.filter(is_supplier=True), self.cairo_manager, 'contact', 'view')
        self.assertNotIn(self.supplier_giza, cairo_contacts)

        giza_contacts = get_scoped_queryset(Contact.objects.filter(is_supplier=True), self.giza_manager, 'contact', 'view')
        self.assertIn(self.supplier_giza, giza_contacts)

    # =========================================================================
    # E. Inventory & Transfers Scoping
    # =========================================================================

    def test_warehouse_scoping(self):
        """Representative sees assigned warehouse + main; Manager sees warehouses in their territory."""
        rep_whs = get_scoped_queryset(Warehouse.objects.all(), self.rep_nasr, 'warehouse', 'view')
        self.assertIn(self.wh_main, rep_whs)
        self.assertIn(self.wh_nasr, rep_whs)
        self.assertNotIn(self.wh_dokki, rep_whs)

        cairo_whs = get_scoped_queryset(Warehouse.objects.all(), self.cairo_manager, 'warehouse', 'view')
        self.assertIn(self.wh_main, cairo_whs)
        self.assertIn(self.wh_nasr, cairo_whs)
        self.assertNotIn(self.wh_dokki, cairo_whs)

    def test_transfer_request_anti_self_approval(self):
        """Requester of warehouse transfer cannot approve their own transfer request."""
        transfer = ProductTransferRequest.objects.create(
            reference_number='TR-TEST-001',
            requesting_user=self.cairo_manager,
            source_warehouse=self.wh_main,
            destination_warehouse=self.wh_nasr,
            status='pending'
        )
        # Cairo Manager requested it -> Cannot self-approve
        self.assertFalse(can_user_access_object(self.cairo_manager, transfer, 'approve'))

    # =========================================================================
    # F. Treasury & Vault Scoping
    # =========================================================================

    def test_vault_territorial_scoping(self):
        """Vaults are scoped geographically using Vault.area and assigned user."""
        cairo_vaults = get_scoped_queryset(Vault.objects.all(), self.cairo_manager, 'vault', 'view')
        self.assertIn(self.vault_nasr, cairo_vaults)
        self.assertNotIn(self.vault_dokki, cairo_vaults)

        rep_vaults = get_scoped_queryset(Vault.objects.all(), self.rep_nasr, 'vault', 'view')
        self.assertIn(self.vault_nasr, rep_vaults)
        self.assertNotIn(self.vault_dokki, rep_vaults)

    # =========================================================================
    # G. Form Choices & Autocomplete (Zero Data Leakage)
    # =========================================================================

    def test_scoped_choices_no_data_leakage(self):
        """Dropdown selectors return only authorized geographic areas and entities."""
        # Governorates dropdown for Cairo Rep returns only Cairo
        rep_govs = ScopeResolutionService.get_scoped_choices(self.rep_nasr, 'governorates', 'contacts')
        self.assertIn(self.cairo, rep_govs)
        self.assertNotIn(self.giza, rep_govs)

        # Bricks dropdown for Cairo Rep returns only Nasr City
        rep_bricks = ScopeResolutionService.get_scoped_choices(self.rep_nasr, 'bricks', 'contacts')
        self.assertIn(self.nasr_city, rep_bricks)
        self.assertNotIn(self.dokki, rep_bricks)
        self.assertNotIn(self.maadi, rep_bricks)

        # Bricks dropdown for Cairo Manager returns Nasr City and Maadi, but NOT Dokki
        mgr_bricks = ScopeResolutionService.get_scoped_choices(self.cairo_manager, 'bricks', 'contacts')
        self.assertIn(self.nasr_city, mgr_bricks)
        self.assertIn(self.maadi, mgr_bricks)
        self.assertNotIn(self.dokki, mgr_bricks)

    # =========================================================================
    # H. IDOR Rejection on Direct URLs
    # =========================================================================

    def test_direct_url_idor_rejection(self):
        """Direct URL request to a contact outside user's scope returns 403 Forbidden."""
        self.client.force_login(self.rep_nasr)
        # Attempt to access Dokki contact (Giza) directly via URL
        res = self.client.get(reverse('contact_detail', kwargs={'pk': self.contact_dokki.pk}))
        self.assertEqual(res.status_code, 403)
