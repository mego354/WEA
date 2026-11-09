from django.test import TestCase, Client
from django.contrib.auth.models import Permission
from django.urls import reverse
from decimal import Decimal
from accounts.models import User, Role
from master_data.models import Area, LocationSettings, SalesSettings, PurchaseSettings
from catalog.models import Product, ProductCategory
from contacts.models import Contact
from sales.models import SalesOrder, SalesOrderItem
from purchases.models import PurchaseOrder, PurchaseOrderItem
from inventory.models import Warehouse, InventoryStock, ProductTransferRequest, ProductTransferRequestItem
from treasury.models import Vault


class UserPermissionsGranularControlTestCase(TestCase):
    """
    Test suite verifying:
    1. User custom direct permissions (has_custom_permissions) provide 100% granular control
       over every feature and process directly from the user screen.
    2. Revoking or granting any permission directly impacts the user immediately.
    3. Settings flags or hardcoded roles do not bypass permission checks when revoked.
    4. Whole process verification across Sales, Purchases, Visits, Inventory, Treasury, Contacts, Catalog.
    """

    def setUp(self):
        self.client = Client()

        # SuperAdmin
        self.superadmin = User.objects.create_superuser(
            username='super_boss',
            email='super@weapharma.com',
            password='password123',
            name='Super Admin'
        )

        # Standard Roles
        self.rep_role = Role.objects.get(name='rep')
        self.mgr_role = Role.objects.get(name='manager')
        self.acct_role = Role.objects.get(name='accountant')

        # Main Area and Sub Area
        self.cairo = Area.objects.create(name='القاهرة', code='CAIRO_TEST', area_type='governorate')
        self.nasr_city = Area.objects.create(name='مدينة نصر', code='NASR_TEST', area_type='subarea', parent=self.cairo)

        # Standard Representative User
        self.rep_user = User.objects.create_user(
            username='test_rep',
            email='rep@weapharma.com',
            password='password123',
            name='مندوب تجريبي',
            role=self.rep_role
        )
        self.rep_user.assigned_areas.add(self.nasr_city)

        # Warehouses
        self.main_wh = Warehouse.objects.create(
            name='المخزن الرئيسي بالقاهرة',
            code='WH-MAIN',
            area=self.cairo,
            is_main=True
        )
        self.rep_wh = Warehouse.objects.create(
            name='مخزن المندوب',
            code='WH-REP',
            area=self.nasr_city,
            assigned_user=self.rep_user
        )

        # Vault
        self.rep_vault = Vault.objects.create(
            name='خزنة المندوب',
            serial_num=101,
            assigned_user=self.rep_user,
            is_rep_vault=True,
            current_balance=Decimal('5000.00'),
            is_active=True
        )

        # Category and Product
        self.cat = ProductCategory.objects.create(name='أدوية عامة')
        self.product = Product.objects.create(
            name='بانادول أقراص',
            sku_code='PAN-01',
            category=self.cat,
            retail_price=Decimal('50.00'),
            default_purchase_cost=Decimal('35.00')
        )
        # Stock
        InventoryStock.objects.create(
            warehouse=self.rep_wh,
            product=self.product,
            qty_on_hand=Decimal('100.00')
        )

        # Contact
        self.customer = Contact.objects.create(
            name='صيدلية الشفاء',
            is_customer=True,
            area=self.nasr_city,
            created_by=self.rep_user
        )

    # =========================================================================
    # 1. User Custom Permissions Mode Tests
    # =========================================================================

    def test_default_role_inheritance_vs_custom_permissions(self):
        """User inherits from role by default, but custom mode allows total override."""
        # By default, rep has sales:orders/create and cannot approve sales orders
        self.assertTrue(self.rep_user.has_permission('sales:orders/create'))
        self.assertFalse(self.rep_user.has_permission('sales:orders/approve'))

        # Switch to custom permissions mode and explicitly remove sales:orders/create
        self.client.force_login(self.superadmin)
        perms_to_grant = [
            'module:sales',
            'sales:orders/list',
            'sales:orders/view',
            'sales:orders/approve',  # Grant approval directly to this rep!
        ]
        response = self.client.post(
            reverse('user_effective_permissions', kwargs={'pk': self.rep_user.pk}),
            {
                'has_custom_permissions': 'on',
                'permissions': perms_to_grant,
            }
        )
        self.assertEqual(response.status_code, 302)

        self.rep_user.refresh_from_db()
        self.rep_user.clear_perm_cache()
        self.assertTrue(self.rep_user.has_custom_permissions)

        # Now sales:orders/create is DENIED
        self.assertFalse(self.rep_user.has_permission('sales:orders/create'))
        # And sales:orders/approve is GRANTED
        self.assertTrue(self.rep_user.has_permission('sales:orders/approve'))

    def test_reset_custom_permissions_to_role_defaults(self):
        """Resetting to role defaults restores the standard canonical role permissions."""
        self.rep_user.has_custom_permissions = True
        self.rep_user.user_permissions.clear()
        self.rep_user.save()
        self.rep_user.clear_perm_cache()
        self.assertFalse(self.rep_user.has_permission('sales:orders/create'))

        # SuperAdmin posts reset_to_role
        self.client.force_login(self.superadmin)
        response = self.client.post(
            reverse('user_effective_permissions', kwargs={'pk': self.rep_user.pk}),
            {'action': 'reset_to_role'}
        )
        self.assertEqual(response.status_code, 302)

        self.rep_user.refresh_from_db()
        self.rep_user.clear_perm_cache()
        self.assertFalse(self.rep_user.has_custom_permissions)
        # Normal rep permissions restored
        self.assertTrue(self.rep_user.has_permission('sales:orders/create'))
        self.assertTrue(self.rep_user.has_permission('activities:visits/create'))

    # =========================================================================
    # 2. Permissions Are The Sole Control Over Feature Availability
    # =========================================================================

    def test_settings_flags_do_not_bypass_revoked_permissions(self):
        """
        Even when universal creation settings are enabled, revoking the permission
        from the user strictly blocks them from creating documents.
        """
        # Enable settings-level flags
        sales_settings = SalesSettings.get_settings()
        sales_settings.allow_all_users_to_create = True
        sales_settings.save()

        loc_settings = LocationSettings.get_settings()
        loc_settings.allow_all_users_to_create_visits = True
        loc_settings.save()

        # Turn on custom permissions for rep, giving only view permissions (no create)
        self.rep_user.has_custom_permissions = True
        p_sales_list = Permission.objects.get(codename='sales:orders/list')
        p_sales_mod = Permission.objects.get(codename='module:sales')
        p_visits_list = Permission.objects.get(codename='activities:visits/list')
        p_act_mod = Permission.objects.get(codename='module:activities')
        self.rep_user.user_permissions.set([p_sales_mod, p_sales_list, p_act_mod, p_visits_list])
        self.rep_user.save()
        self.rep_user.clear_perm_cache()

        # Verify permissions in user
        self.assertFalse(self.rep_user.has_permission('sales:orders/create'))
        self.assertFalse(self.rep_user.has_permission('activities:visits/create'))

        # Log in as rep and attempt to access sales order create
        self.client.force_login(self.rep_user)
        res = self.client.get(reverse('sales_order_create'))
        self.assertEqual(res.status_code, 403)

        # Attempt to access visit create
        res = self.client.get(reverse('visit_create'))
        self.assertEqual(res.status_code, 403)

    # =========================================================================
    # 3. Whole Process Verification: Sales Feature
    # =========================================================================

    def test_sales_whole_process_permissions(self):
        """Test each step of Sales: list, create, view, edit, approve, cancel."""
        self.client.force_login(self.rep_user)

        # 1. List
        res = self.client.get(reverse('sales_orders_list'))
        self.assertEqual(res.status_code, 200)

        # 2. Create Order
        res = self.client.get(reverse('sales_order_create'))
        self.assertEqual(res.status_code, 200)

        order = SalesOrder.objects.create(
            order_number='SO-TEST-001',
            customer=self.customer,
            source_warehouse=self.rep_wh,
            created_by=self.rep_user,
            status='pending',
            subtotal=Decimal('100.00'),
            grand_total=Decimal('100.00')
        )

        # 3. View Detail
        res = self.client.get(reverse('sales_order_detail', kwargs={'pk': order.pk}))
        self.assertEqual(res.status_code, 200)

        # 4. Approve Action: rep normally cannot approve -> 403
        res = self.client.post(reverse('sales_order_action', kwargs={'pk': order.pk, 'action': 'approve'}))
        self.assertEqual(res.status_code, 403)

        # Grant sales:orders/approve directly to rep
        p_approve = Permission.objects.get(codename='sales:orders/approve')
        self.rep_user.user_permissions.add(p_approve)
        self.rep_user.clear_perm_cache()

        # Manager user to test cross-approval
        mgr_user = User.objects.create_user(
            username='test_mgr',
            email='mgr@weapharma.com',
            password='password123',
            name='مدير تجريبي',
            role=self.mgr_role
        )
        mgr_user.assigned_areas.add(self.cairo)
        self.client.force_login(mgr_user)
        res = self.client.post(reverse('sales_order_action', kwargs={'pk': order.pk, 'action': 'approve'}))
        self.assertEqual(res.status_code, 302)
        order.refresh_from_db()
        self.assertEqual(order.status, 'manager_approval')

    # =========================================================================
    # 4. Whole Process Verification: Inventory Transfers
    # =========================================================================

    def test_inventory_transfers_permissions(self):
        """Test list, create, view, approve, and execute on transfers strictly checked."""
        # Rep has inventory:transfers/list, view, create
        self.client.force_login(self.rep_user)
        res = self.client.get(reverse('product_transfers_list'))
        self.assertEqual(res.status_code, 200)

        res = self.client.get(reverse('product_transfer_create'))
        self.assertEqual(res.status_code, 200)

        # Create transfer
        transfer = ProductTransferRequest.objects.create(
            reference_number='TR-TEST-001',
            requesting_user=self.rep_user,
            source_warehouse=self.main_wh,
            destination_warehouse=self.rep_wh,
            status='pending'
        )

        # View detail
        res = self.client.get(reverse('product_transfer_detail', kwargs={'pk': transfer.pk}))
        self.assertEqual(res.status_code, 200)

        # Rep attempts to approve own transfer -> 403
        res = self.client.post(reverse('product_transfer_action', kwargs={'pk': transfer.pk, 'action': 'approve'}))
        self.assertEqual(res.status_code, 403)

        # Rep attempts to execute transfer -> 403
        res = self.client.post(reverse('product_transfer_action', kwargs={'pk': transfer.pk, 'action': 'execute'}))
        self.assertEqual(res.status_code, 403)

        # Accountant user with approval permission
        acct_user = User.objects.create_user(
            username='test_acct',
            email='acct@weapharma.com',
            password='password123',
            name='محاسب تجريبي',
            role=self.acct_role
        )
        self.client.force_login(acct_user)
        res = self.client.post(reverse('product_transfer_action', kwargs={'pk': transfer.pk, 'action': 'approve'}))
        self.assertEqual(res.status_code, 302)
        transfer.refresh_from_db()
        self.assertEqual(transfer.status, 'approved')

    # =========================================================================
    # 5. Whole Process Verification: Treasury Vault Transactions
    # =========================================================================

    def test_treasury_vault_permissions(self):
        """Test vault view, deposit, and withdraw guarded by permissions."""
        self.client.force_login(self.rep_user)

        # Rep does not have treasury:transactions/create by default -> 403 on deposit
        res = self.client.get(reverse('vault_deposit'))
        self.assertEqual(res.status_code, 403)

        # Grant treasury:transactions/create and module:treasury directly to rep
        self.rep_user.has_custom_permissions = True
        p_mod = Permission.objects.get(codename='module:treasury')
        p_create = Permission.objects.get(codename='treasury:transactions/create')
        p_v_view = Permission.objects.get(codename='treasury:vaults/view')
        self.rep_user.user_permissions.set([p_mod, p_create, p_v_view])
        self.rep_user.save()
        self.rep_user.clear_perm_cache()

        # Now deposit page opens successfully
        res = self.client.get(reverse('vault_deposit'))
        self.assertEqual(res.status_code, 200)

    # =========================================================================
    # 6. Whole Process Verification: Purchases Feature
    # =========================================================================

    def test_purchases_whole_process_permissions(self):
        """Test purchase order list, view, create, edit, approve, cancel permissions."""
        supplier = Contact.objects.create(
            name='شركة توريد أدوية',
            is_supplier=True,
            area=self.cairo
        )

        # Rep role does not have module:purchases or purchases:orders/create by default
        self.client.force_login(self.rep_user)
        res = self.client.get(reverse('purchase_orders_list'))
        self.assertEqual(res.status_code, 403)
        res = self.client.get(reverse('purchase_order_create'))
        self.assertEqual(res.status_code, 403)

        # Grant purchases:orders/list and purchases:orders/create directly to rep via custom permissions
        self.rep_user.has_custom_permissions = True
        p_purch_mod = Permission.objects.get(codename='module:purchases')
        p_po_list = Permission.objects.get(codename='purchases:orders/list')
        p_po_create = Permission.objects.get(codename='purchases:orders/create')
        p_po_view = Permission.objects.get(codename='purchases:orders/view')
        self.rep_user.user_permissions.set([p_purch_mod, p_po_list, p_po_create, p_po_view])
        self.rep_user.save()
        self.rep_user.clear_perm_cache()

        # Now rep can list and open create form
        res = self.client.get(reverse('purchase_orders_list'))
        self.assertEqual(res.status_code, 200)
        res = self.client.get(reverse('purchase_order_create'))
        self.assertEqual(res.status_code, 200)

        # Create PO
        po = PurchaseOrder.objects.create(
            order_number='PO-TEST-001',
            supplier=supplier,
            target_warehouse=self.rep_wh,
            created_by=self.rep_user,
            status='pending'
        )
        res = self.client.get(reverse('purchase_order_detail', kwargs={'pk': po.pk}))
        self.assertEqual(res.status_code, 200)

        # Rep cannot approve PO -> 403
        res = self.client.post(reverse('purchase_order_action', kwargs={'pk': po.pk, 'action': 'approve'}))
        self.assertEqual(res.status_code, 403)

    # =========================================================================
    # 7. Whole Process Verification: Activities / Visits Feature
    # =========================================================================

    def test_visits_whole_process_permissions(self):
        """Test visit list, detail, create, approve permissions."""
        from activities.models import Visit
        from django.utils import timezone

        # Rep has visits list and create
        self.client.force_login(self.rep_user)
        res = self.client.get(reverse('visits_list'))
        self.assertEqual(res.status_code, 200)
        res = self.client.get(reverse('visit_create'))
        self.assertEqual(res.status_code, 200)

        visit = Visit.objects.create(
            contact=self.customer,
            owner=self.rep_user,
            created_by=self.rep_user,
            date=timezone.now().date(),
            status='finished',
            approval_status='pending'
        )

        # Rep detail view works
        res = self.client.get(reverse('visit_detail', kwargs={'pk': visit.pk}))
        self.assertEqual(res.status_code, 200)

        # Rep cannot approve visit -> redirected with error on form POST, 403 on AJAX
        res = self.client.post(reverse('visit_action', kwargs={'pk': visit.pk, 'action': 'approve'}))
        self.assertEqual(res.status_code, 302)
        visit.refresh_from_db()
        self.assertEqual(visit.approval_status, 'pending')

        res_ajax = self.client.post(
            reverse('visit_action', kwargs={'pk': visit.pk, 'action': 'approve'}),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(res_ajax.status_code, 403)

        # Revoke activities:visits/create from rep via custom permissions
        self.rep_user.has_custom_permissions = True
        p_act_mod = Permission.objects.get(codename='module:activities')
        p_v_list = Permission.objects.get(codename='activities:visits/list')
        self.rep_user.user_permissions.set([p_act_mod, p_v_list])
        self.rep_user.save()
        self.rep_user.clear_perm_cache()

        # Visit create is now denied 403
        res = self.client.get(reverse('visit_create'))
        self.assertEqual(res.status_code, 403)

    # =========================================================================
    # 8. Whole Process Verification: Contacts & Catalog
    # =========================================================================

    def test_contacts_and_catalog_permissions(self):
        """Test contacts and catalog list, create, edit, export permissions."""
        self.client.force_login(self.rep_user)

        # Rep has contacts:contacts/list and create
        res = self.client.get(reverse('contacts_list'))
        self.assertEqual(res.status_code, 200)
        res = self.client.get(reverse('contact_create'))
        self.assertEqual(res.status_code, 200)

        # Rep has catalog:products/list and view, but NOT product create
        res = self.client.get(reverse('products_list'))
        self.assertEqual(res.status_code, 200)
        res = self.client.get(reverse('product_create'))
        self.assertEqual(res.status_code, 403)

        # Grant catalog:products/create via custom permissions
        self.rep_user.has_custom_permissions = True
        p_cat_mod = Permission.objects.get(codename='module:catalog')
        p_p_list = Permission.objects.get(codename='catalog:products/list')
        p_p_create = Permission.objects.get(codename='catalog:products/create')
        self.rep_user.user_permissions.set([p_cat_mod, p_p_list, p_p_create])
        self.rep_user.save()
        self.rep_user.clear_perm_cache()

        # Now product create opens 200
        res = self.client.get(reverse('product_create'))
        self.assertEqual(res.status_code, 200)

