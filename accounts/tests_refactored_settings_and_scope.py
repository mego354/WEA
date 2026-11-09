from decimal import Decimal
from django.test import TestCase, Client, RequestFactory
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission

from master_data.models import (
    Area, CompanyProfile, LocationSettings, SalesSettings, PurchaseSettings
)
from master_data.services import SettingsService
from accounts.models import Role, UserSettings, SecurityAuditLog
from accounts.permissions import (
    can_user_access_object, get_scoped_queryset, has_perm_or_admin
)
from contacts.models import Contact
from purchases.models import PurchaseOrder, PurchaseOrderItem, PurchaseReturnOrder
from inventory.models import Warehouse
from sales.models import SalesOrder

User = get_user_model()


class SettingsServiceArchitectureTests(TestCase):
    """
    Validates unified SettingsService behavior:
    - Thread-safe request caching
    - Atomic audited mutations
    - Safe default fallbacks
    - Clean cache invalidation
    """

    def setUp(self):
        self.factory = RequestFactory()
        self.superadmin = User.objects.create_superuser(
            username='super_settings@wea.com',
            email='super_settings@wea.com',
            password='Password123!'
        )

    def test_settings_service_cached_getters(self):
        """Settings getters should cache instances within request lifecycle."""
        req = self.factory.get('/')
        req.user = self.superadmin

        sales1 = SettingsService.get_sales_settings(request=req)
        sales2 = SettingsService.get_sales_settings(request=req)
        self.assertIs(sales1, sales2)

        pur1 = SettingsService.get_purchase_settings(request=req)
        pur2 = SettingsService.get_purchase_settings(request=req)
        self.assertIs(pur1, pur2)

        loc1 = SettingsService.get_location_settings(request=req)
        loc2 = SettingsService.get_location_settings(request=req)
        self.assertIs(loc1, loc2)

    def test_settings_service_atomic_update_and_audit(self):
        """Updating settings via SettingsService must save atomically and log audit event."""
        initial_log_count = SecurityAuditLog.objects.filter(module='settings').count()

        updated_sales = SettingsService.update_sales_settings(
            user=self.superadmin,
            data={
                'require_manager_approval': 'on',
                'tax_mode': 'mandatory',
                'default_packaging_unit': 'strip',
            }
        )
        self.assertTrue(updated_sales.require_manager_approval)
        self.assertEqual(updated_sales.tax_mode, 'mandatory')
        self.assertEqual(updated_sales.default_packaging_unit, 'strip')

        new_log_count = SecurityAuditLog.objects.filter(module='settings').count()
        self.assertEqual(new_log_count, initial_log_count + 1)
        audit_entry = SecurityAuditLog.objects.filter(module='settings').latest('id')
        self.assertEqual(audit_entry.action_type, 'SALES_SETTINGS_UPDATED')
        self.assertEqual(audit_entry.actor, self.superadmin)

    def test_settings_service_invalid_input_safe_fallback(self):
        """Invalid numeric/choice parameters in settings safely fallback to valid defaults."""
        loc = SettingsService.update_location_settings(
            user=self.superadmin,
            data={
                'tolerance': 'not-a-number',
                'max_verified_accuracy': '-50',
                'max_verified_warn_accuracy': 'abc',
            }
        )
        self.assertIsInstance(loc.tolerance, int)
        self.assertGreaterEqual(loc.tolerance, 1)
        self.assertGreaterEqual(loc.max_verified_accuracy, 1)


class PermissionSimplificationTests(TestCase):
    """
    Validates simplified permissions architecture:
    - Redundant alias normalization (treasury:vaults/transactions -> treasury:transactions/list)
    - Authoritative backend permission enforcement
    """

    def setUp(self):
        self.client = Client()
        self.role_acct, _ = Role.objects.get_or_create(
            name='test_accountant',
            defaults={'display_name': 'محاسب اختبار', 'is_active': True}
        )
        self.accountant = User.objects.create_user(
            username='acct_test@wea.com',
            email='acct_test@wea.com',
            password='Password123!',
            role=self.role_acct
        )
        perms = Permission.objects.filter(codename__in=['module:treasury', 'treasury:transactions/list'])
        self.role_acct.permissions.add(*perms)

    def test_treasury_alias_permission_normalization(self):
        """User possessing treasury:transactions/list automatically satisfies treasury:vaults/transactions."""
        self.assertTrue(self.accountant.has_permission('treasury:transactions/list'))
        # Alias check should normalize and return True
        self.assertTrue(self.accountant.has_permission('treasury:vaults/transactions'))
        self.assertTrue(has_perm_or_admin(self.accountant, 'treasury:vaults/transactions'))


class OrganizationalDataScopingAndSecurityTests(TestCase):
    """
    Validates Brick, Area, and Global organizational data isolation:
    - Rep vs Rep in same brick
    - Rep in Brick A vs Rep in Brick B (same Governorate)
    - Manager Cairo vs Giza records (direct URL & AJAX IDOR rejection)
    - Anti-self-approval enforcement
    - SuperAdmin global authority
    """

    def setUp(self):
        self.client = Client()

        # Roles
        self.superadmin_role, _ = Role.objects.get_or_create(
            name=Role.ROLE_SUPERADMIN,
            defaults={'display_name': 'مدير النظام الأعلى', 'is_super': True, 'is_system': True, 'is_active': True}
        )
        self.manager_role, _ = Role.objects.get_or_create(
            name=Role.ROLE_MANAGER,
            defaults={'display_name': 'مدير', 'is_area_manager': True, 'is_system': True, 'is_active': True}
        )
        self.rep_role, _ = Role.objects.get_or_create(
            name=Role.ROLE_REP,
            defaults={'display_name': 'مندوب مبيعات', 'is_rep': True, 'is_system': True, 'is_active': True}
        )

        # Assign basic permissions to manager role
        mgr_perms = Permission.objects.filter(codename__in=[
            'module:purchases', 'purchases:orders/list', 'purchases:orders/view',
            'purchases:orders/approve', 'purchases:returns/list', 'purchases:returns/view',
            'purchases:returns/manage', 'module:sales', 'sales:orders/list', 'sales:orders/view',
            'sales:orders/approve'
        ])
        self.manager_role.permissions.add(*mgr_perms)

        # Assign basic permissions to rep role
        rep_perms = Permission.objects.filter(codename__in=[
            'module:purchases', 'purchases:orders/list', 'purchases:orders/view',
            'purchases:orders/create', 'purchases:returns/list', 'purchases:returns/view',
            'purchases:returns/create', 'module:sales', 'sales:orders/list', 'sales:orders/view'
        ])
        self.rep_role.permissions.add(*rep_perms)

        # Geographic Areas Hierarchy
        # Main Area 1: Cairo (Governorate)
        self.cairo = Area.objects.create(code='CAI', name='القاهرة', area_type='governorate', is_company_area=False)
        self.nasr_city = Area.objects.create(code='NASR', name='مدينة نصر', area_type='subarea', parent=self.cairo, is_company_area=False)
        self.maadi = Area.objects.create(code='MAADI', name='المعادي', area_type='subarea', parent=self.cairo, is_company_area=False)

        # Main Area 2: Giza (Governorate)
        self.giza = Area.objects.create(code='GIZ', name='الجيزة', area_type='governorate', is_company_area=False)
        self.dokki = Area.objects.create(code='DOK', name='الدقي', area_type='subarea', parent=self.giza, is_company_area=False)

        # Users
        self.superadmin = User.objects.create_superuser(
            username='super_idor@wea.com', email='super_idor@wea.com', password='Password123!',
            name='Super Admin', role=self.superadmin_role
        )

        self.mgr_cairo = User.objects.create_user(
            username='mgr_cairo_sec@wea.com', email='mgr_cairo_sec@wea.com', password='Password123!',
            name='Manager Cairo', role=self.manager_role
        )
        self.mgr_cairo.assigned_areas.add(self.cairo)

        self.mgr_giza = User.objects.create_user(
            username='mgr_giza_sec@wea.com', email='mgr_giza_sec@wea.com', password='Password123!',
            name='Manager Giza', role=self.manager_role
        )
        self.mgr_giza.assigned_areas.add(self.giza)

        self.rep_cairo1 = User.objects.create_user(
            username='rep_cairo1_sec@wea.com', email='rep_cairo1_sec@wea.com', password='Password123!',
            name='Rep Cairo NasrCity 1', role=self.rep_role
        )
        self.rep_cairo1.assigned_areas.add(self.nasr_city)

        self.rep_cairo2 = User.objects.create_user(
            username='rep_cairo2_sec@wea.com', email='rep_cairo2_sec@wea.com', password='Password123!',
            name='Rep Cairo Maadi', role=self.rep_role
        )
        self.rep_cairo2.assigned_areas.add(self.maadi)

        self.rep_cairo3_same_brick = User.objects.create_user(
            username='rep_cairo3_sec@wea.com', email='rep_cairo3_sec@wea.com', password='Password123!',
            name='Rep Cairo NasrCity 2', role=self.rep_role
        )
        self.rep_cairo3_same_brick.assigned_areas.add(self.nasr_city)

        # Suppliers & Warehouses
        self.supplier_cairo = Contact.objects.create(
            name='مورد القاهرة الطبي',
            is_supplier=True,
            area=self.nasr_city,
            created_by=self.rep_cairo1
        )
        self.wh_cairo = Warehouse.objects.create(
            name='مخزن القاهرة',
            code='WH-CAI',
            area=self.nasr_city,
            assigned_user=self.rep_cairo1,
            is_active=True
        )

        # Purchase order created by rep_cairo1
        self.po_cairo = PurchaseOrder.objects.create(
            order_number='PO-CAI-001',
            supplier=self.supplier_cairo,
            target_warehouse=self.wh_cairo,
            status='pending',
            created_by=self.rep_cairo1,
            grand_total=Decimal('5000.00')
        )

        # Purchase return created by rep_cairo1
        self.return_cairo = PurchaseReturnOrder.objects.create(
            order_number='RET-CAI-001',
            supplier=self.supplier_cairo,
            warehouse=self.wh_cairo,
            status='draft',
            created_by=self.rep_cairo1,
            grand_total=Decimal('1000.00')
        )

    def test_rep_isolation_in_same_brick(self):
        """Representatives in the same brick cannot access each other's purchase orders (direct URL)."""
        self.client.login(username='rep_cairo3_sec@wea.com', password='Password123!')
        url = reverse('purchase_order_detail', kwargs={'pk': self.po_cairo.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)

    def test_rep_isolation_across_different_bricks(self):
        """Rep in Maadi cannot access purchase order created by Rep in Nasr City."""
        self.client.login(username='rep_cairo2_sec@wea.com', password='Password123!')
        url = reverse('purchase_order_detail', kwargs={'pk': self.po_cairo.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)

    def test_manager_cairo_can_view_cairo_orders(self):
        """Manager assigned to Cairo governorate can view orders from all its child bricks."""
        self.client.login(username='mgr_cairo_sec@wea.com', password='Password123!')
        url = reverse('purchase_order_detail', kwargs={'pk': self.po_cairo.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_manager_giza_cannot_access_or_approve_cairo_orders(self):
        """Manager Giza is strictly rejected from viewing or approving Cairo orders (IDOR prevention)."""
        self.client.login(username='mgr_giza_sec@wea.com', password='Password123!')

        # 1. Detail page IDOR
        url_detail = reverse('purchase_order_detail', kwargs={'pk': self.po_cairo.pk})
        res_detail = self.client.get(url_detail)
        self.assertEqual(res_detail.status_code, 403)

        # 2. Action approve IDOR
        url_action = reverse('purchase_order_action', kwargs={'pk': self.po_cairo.pk, 'action': 'approve'})
        res_action = self.client.post(url_action, {'approval_notes': 'محاولة غير مصرح بها'})
        self.assertEqual(res_action.status_code, 403)
        self.po_cairo.refresh_from_db()
        self.assertEqual(self.po_cairo.status, 'pending')

        # 3. AJAX approve IDOR
        url_ajax = reverse('purchase_order_update_status_ajax', kwargs={'pk': self.po_cairo.pk})
        res_ajax = self.client.post(url_ajax, {'status': 'approved'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(res_ajax.status_code, 403)
        self.po_cairo.refresh_from_db()
        self.assertEqual(self.po_cairo.status, 'pending')

    def test_manager_giza_cannot_access_purchase_return(self):
        """Manager Giza cannot view, print, or approve Cairo purchase return orders."""
        self.client.login(username='mgr_giza_sec@wea.com', password='Password123!')

        url_ret = reverse('purchase_return_order_detail', kwargs={'pk': self.return_cairo.pk})
        res_ret = self.client.get(url_ret)
        self.assertEqual(res_ret.status_code, 403)

        url_action = reverse('purchase_return_order_action', kwargs={'pk': self.return_cairo.pk, 'action': 'approve'})
        res_action = self.client.post(url_action)
        self.assertEqual(res_action.status_code, 403)

    def test_anti_self_approval_on_orders(self):
        """A user cannot approve their own purchase order even if they possess approval permissions."""
        # Grant approve permission to rep_cairo1
        perm = Permission.objects.filter(codename='purchases:orders/approve').first()
        self.rep_cairo1.user_permissions.add(perm)

        self.client.login(username='rep_cairo1_sec@wea.com', password='Password123!')
        url_action = reverse('purchase_order_action', kwargs={'pk': self.po_cairo.pk, 'action': 'approve'})
        response = self.client.post(url_action)
        self.po_cairo.refresh_from_db()
        # Must not be approved
        self.assertNotEqual(self.po_cairo.status, 'approved')

    def test_superadmin_global_access(self):
        """SuperAdmin has global access across all geographic areas and records."""
        self.client.login(username='super_idor@wea.com', password='Password123!')
        url_detail = reverse('purchase_order_detail', kwargs={'pk': self.po_cairo.pk})
        response = self.client.get(url_detail)
        self.assertEqual(response.status_code, 200)

        url_action = reverse('purchase_order_action', kwargs={'pk': self.po_cairo.pk, 'action': 'approve'})
        res_action = self.client.post(url_action, {'approval_notes': 'معتمد من السوبر أدمن'})
        self.po_cairo.refresh_from_db()
        self.assertEqual(self.po_cairo.status, 'approved')
