import csv
from io import StringIO
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from accounts.models import User, Role, RoleTag
from master_data.models import Area


class AccountsModelTests(TestCase):
    def setUp(self):
        self.super_role, _ = Role.objects.get_or_create(
            name='superadmin',
            defaults={
                'display_name': 'مدير نظام رئيسي',
                'is_super': True,
                'is_active': True
            }
        )
        self.rep_role, _ = Role.objects.get_or_create(
            name='medical_rep',
            defaults={
                'display_name': 'مندوب دعاية',
                'is_rep': True,
                'is_active': True
            }
        )
        self.area, _ = Area.objects.get_or_create(code='CAI', defaults={'name': 'القاهرة', 'area_type': 'governorate'})

    def test_user_creation_and_attributes(self):
        user = User.objects.create_user(
            username='rep@example.com',
            email='rep@example.com',
            password='Password123!',
            name='أحمد علي',
            code='REP-001',
            role=self.rep_role
        )
        user.assigned_areas.add(self.area)

        self.assertEqual(user.name, 'أحمد علي')
        self.assertEqual(user.code, 'REP-001')
        self.assertEqual(user.role.name, 'medical_rep')
        self.assertTrue(user.is_active)
        self.assertTrue(user.check_password('Password123!'))
        self.assertIn(self.area, user.assigned_areas.all())

    def test_role_attributes_and_tags(self):
        tag = RoleTag.objects.create(tag='sales', display_name='فريق المبيعات')
        self.rep_role.tags.add(tag)
        self.assertIn(tag, self.rep_role.tags.all())
        self.assertTrue(self.rep_role.is_rep)
        self.assertFalse(self.rep_role.is_super)

    def test_user_has_permission(self):
        ct = ContentType.objects.get_for_model(User)
        perm = Permission.objects.create(codename='view_custom_users', name='View Custom Users', content_type=ct)
        self.rep_role.permissions.add(perm)

        user = User.objects.create_user(
            username='rep2@example.com',
            email='rep2@example.com',
            password='Password123!',
            role=self.rep_role
        )
        self.assertTrue(user.has_permission('view_custom_users'))
        self.assertFalse(user.has_permission('non_existent_perm'))


class UserManagementViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin_role = Role.objects.create(
            name='admin',
            display_name='مدير النظام',
            is_super=True,
            is_active=True
        )
        self.restricted_role = Role.objects.create(
            name='restricted',
            display_name='مستخدم محدود',
            is_active=True
        )
        self.admin_user = User.objects.create_superuser(
            username='admin@example.com',
            email='admin@example.com',
            password='AdminPassword123!',
            name='مدير النظام',
            role=self.admin_role
        )
        self.restricted_user = User.objects.create_user(
            username='staff@example.com',
            email='staff@example.com',
            password='StaffPassword123!',
            name='موظف محدود',
            role=self.restricted_role
        )

    def test_anonymous_access_redirects_to_login(self):
        response = self.client.get(reverse('users_list'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response.url)

    def test_restricted_user_cannot_access_users_list(self):
        self.client.login(username='staff@example.com', password='StaffPassword123!')
        response = self.client.get(reverse('users_list'))
        self.assertEqual(response.status_code, 403)

    def test_admin_user_can_access_users_list(self):
        self.client.login(username='admin@example.com', password='AdminPassword123!')
        response = self.client.get(reverse('users_list'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'accounts/users_list.html')
        self.assertContains(response, 'مدير النظام')

    def test_user_create_post_success(self):
        self.client.login(username='admin@example.com', password='AdminPassword123!')
        data = {
            'name': 'محمود محمد',
            'email': 'mahmoud@example.com',
            'code': 'USR-99',
            'password': 'SecurePassword123!',
            'role': self.restricted_role.pk,
        }
        response = self.client.post(reverse('user_create'), data)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(User.objects.filter(email='mahmoud@example.com').exists())
        created_user = User.objects.get(email='mahmoud@example.com')
        self.assertEqual(created_user.name, 'محمود محمد')
        self.assertEqual(created_user.code, 'USR-99')
        self.assertTrue(created_user.check_password('SecurePassword123!'))

    def test_user_create_duplicate_email_fails(self):
        self.client.login(username='admin@example.com', password='AdminPassword123!')
        data = {
            'name': 'تكرار البريد',
            'email': 'admin@example.com', # Duplicate
            'code': 'DUP-01',
            'password': 'SecurePassword123!',
            'role': self.restricted_role.pk,
        }
        response = self.client.post(reverse('user_create'), data)
        self.assertEqual(response.status_code, 200)
        # Verify no duplicate user was created
        self.assertEqual(User.objects.filter(email='admin@example.com').count(), 1)

    def test_user_edit_post(self):
        self.client.login(username='admin@example.com', password='AdminPassword123!')
        data = {
            'name': 'موظف محدث',
            'email': 'staff_updated@example.com',
            'code': 'STAFF-02',
            'role': self.admin_role.pk,
            'is_active': 'on',
        }
        response = self.client.post(reverse('user_edit', args=[self.restricted_user.pk]), data)
        self.assertEqual(response.status_code, 302)
        self.restricted_user.refresh_from_db()
        self.assertEqual(self.restricted_user.name, 'موظف محدث')
        self.assertEqual(self.restricted_user.email, 'staff_updated@example.com')

    def test_cannot_deactivate_only_active_superuser(self):
        self.client.login(username='admin@example.com', password='AdminPassword123!')
        # Try to deactivate sole admin user via user_toggle_status
        response = self.client.get(reverse('user_toggle_status', args=[self.admin_user.pk]))
        self.assertEqual(response.status_code, 302)
        self.admin_user.refresh_from_db()
        self.assertTrue(self.admin_user.is_active) # Must remain active

    def test_reset_password(self):
        self.client.login(username='admin@example.com', password='AdminPassword123!')
        data = {
            'new_password': 'BrandNewPassword123!',
            'confirm_password': 'BrandNewPassword123!',
        }
        response = self.client.post(reverse('user_reset_password', args=[self.restricted_user.pk]), data)
        self.assertEqual(response.status_code, 302)
        self.restricted_user.refresh_from_db()
        self.assertTrue(self.restricted_user.check_password('BrandNewPassword123!'))

    def test_users_export_csv(self):
        self.client.login(username='admin@example.com', password='AdminPassword123!')
        response = self.client.get(reverse('users_export'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv; charset=utf-8')
        content = response.content.decode('utf-8')
        self.assertTrue(content.startswith('\ufeff')) # UTF-8 BOM
        self.assertIn('admin@example.com', content)


class RoleManagementViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin_role = Role.objects.create(
            name='admin',
            display_name='مدير النظام',
            is_super=True,
            is_active=True
        )
        self.admin_user = User.objects.create_superuser(
            username='admin@example.com',
            email='admin@example.com',
            password='AdminPassword123!',
            name='مدير النظام',
            role=self.admin_role
        )
        self.test_role, _ = Role.objects.get_or_create(
            name='accountant',
            defaults={
                'display_name': 'محاسب',
                'can_hold_vault': True,
                'is_active': True
            }
        )
        self.test_role.can_hold_vault = True
        self.test_role.is_active = True
        self.test_role.save()

    def test_roles_list_view(self):
        self.client.login(username='admin@example.com', password='AdminPassword123!')
        response = self.client.get(reverse('roles_list'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'accounts/roles_list.html')
        self.assertContains(response, 'محاسب')

    def test_role_create_view(self):
        self.client.login(username='admin@example.com', password='AdminPassword123!')
        data = {
            'name': 'warehouse_keeper',
            'display_name': 'أمين مخزن',
            'is_active': 'on',
        }
        response = self.client.post(reverse('role_create'), data)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Role.objects.filter(name='warehouse_keeper').exists())

    def test_role_duplicate_view(self):
        self.client.login(username='admin@example.com', password='AdminPassword123!')
        response = self.client.get(reverse('role_duplicate', args=[self.test_role.pk]))
        self.assertEqual(response.status_code, 302)
        clones = Role.objects.filter(name__startswith='accountant_copy')
        self.assertTrue(clones.exists())
        clone = clones.first()
        self.assertTrue(clone.can_hold_vault)
        self.assertIn('نسخة', clone.display_name)

    def test_delete_role_safeguard(self):
        self.client.login(username='admin@example.com', password='AdminPassword123!')
        # Cannot delete system role or role with assigned users
        User.objects.create_user(
            username='acc@example.com',
            email='acc@example.com',
            password='Pass!',
            role=self.test_role
        )
        response = self.client.get(reverse('role_delete', args=[self.test_role.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Role.objects.filter(pk=self.test_role.pk).exists())


class ERPAuthorizationSecurityTests(TestCase):
    """
    Comprehensive test suite validating:
    - 403 Forbidden enforcement on protected routes.
    - Module-level inheritance (disabling module blocks all child actions).
    - SuperAdmin restriction and privilege escalation prevention.
    - Last superadmin lockout safeguard.
    - ABAC territorial and IDOR object-level protection.
    - Security audit logging for permission changes.
    - Cache invalidation and immediate policy reflection.
    """
    def setUp(self):
        self.client = Client()

        # Create Roles
        self.super_role = Role.objects.create(
            name='superadmin_role',
            display_name='مدير نظام رئيسي',
            is_super=True,
            is_active=True
        )
        self.rep_role = Role.objects.create(
            name='sales_rep_role',
            display_name='مندوب مبيعات',
            is_rep=True,
            is_active=True
        )
        self.manager_role = Role.objects.create(
            name='sales_manager_role',
            display_name='مدير مبيعات',
            is_active=True
        )

        # Create Users
        self.super_user = User.objects.create_superuser(
            username='root@example.com',
            email='root@example.com',
            password='RootPassword123!',
            name='المدير العام',
            role=self.super_role
        )
        self.rep_user = User.objects.create_user(
            username='rep_a@example.com',
            email='rep_a@example.com',
            password='RepPassword123!',
            name='مندوب أ',
            role=self.rep_role
        )
        self.rep_user_b = User.objects.create_user(
            username='rep_b@example.com',
            email='rep_b@example.com',
            password='RepPassword123!',
            name='مندوب ب',
            role=self.rep_role
        )

    def test_anonymous_redirect_on_all_domains(self):
        """Anonymous access to protected routes redirects to login."""
        protected_urls = [
            reverse('purchase_orders_list'),
            reverse('purchase_order_create'),
            reverse('sales_orders_list'),
            reverse('products_list'),
            reverse('contacts_list'),
            reverse('visits_list'),
            reverse('vaults_list'),
            reverse('roles_list'),
            reverse('audit_logs_list'),
        ]
        for url in protected_urls:
            res = self.client.get(url)
            self.assertEqual(res.status_code, 302, f"URL {url} did not redirect anonymous user")
            self.assertIn('login', res.url)

    def test_unauthorized_user_gets_403_forbidden(self):
        """Authenticated user without specific permissions gets 403 Forbidden."""
        self.client.login(username='rep_a@example.com', password='RepPassword123!')
        
        # Rep has no purchases permissions
        res = self.client.get(reverse('purchase_orders_list'))
        self.assertEqual(res.status_code, 403)
        self.assertTemplateUsed(res, '403.html')

        res_post = self.client.post(reverse('purchase_order_create'), {})
        self.assertEqual(res_post.status_code, 403)

    def test_module_level_inheritance_enforcement(self):
        """
        Disabling root module permission blocks all child actions
        even if child permission is explicitly assigned to role.
        """
        p_child = Permission.objects.get(codename='purchases:orders/list')
        p_module = Permission.objects.get(codename='module:purchases')

        # Assign child only (WITHOUT module root)
        self.rep_role.permissions.add(p_child)
        self.rep_user.clear_perm_cache()

        self.assertFalse(self.rep_user.has_permission('purchases:orders/list'))

        self.client.login(username='rep_a@example.com', password='RepPassword123!')
        res = self.client.get(reverse('purchase_orders_list'))
        self.assertEqual(res.status_code, 403)

        # Now enable module root
        self.rep_role.permissions.add(p_module)
        self.rep_user.clear_perm_cache()

        self.assertTrue(self.rep_user.has_permission('purchases:orders/list'))
        res_ok = self.client.get(reverse('purchase_orders_list'))
        self.assertEqual(res_ok.status_code, 200)

    def test_superadmin_exclusive_settings_protection(self):
        """Only superadmins can access user/role/audit settings; other users receive 403."""
        # Non-superadmin
        self.client.login(username='rep_a@example.com', password='RepPassword123!')
        for url in [reverse('roles_list'), reverse('role_create'), reverse('audit_logs_list')]:
            res = self.client.get(url)
            self.assertEqual(res.status_code, 403)

        # SuperAdmin
        self.client.login(username='root@example.com', password='RootPassword123!')
        for url in [reverse('roles_list'), reverse('role_create'), reverse('audit_logs_list')]:
            res = self.client.get(url)
            self.assertEqual(res.status_code, 200)

    def test_privilege_escalation_prevention(self):
        """Non-superadmins cannot create or edit roles to grant is_super."""
        self.client.login(username='rep_a@example.com', password='RepPassword123!')
        data = {
            'name': 'hacked_role',
            'display_name': 'Hacked',
            'is_super': 'on',
        }
        res = self.client.post(reverse('role_create'), data)
        self.assertEqual(res.status_code, 403)
        self.assertFalse(Role.objects.filter(name='hacked_role').exists())

    def test_last_superadmin_lockout_protection(self):
        """System strictly prevents deactivating or deleting the last active superadmin."""
        self.client.login(username='root@example.com', password='RootPassword123!')
        
        # Attempt to toggle status of only active superadmin
        res = self.client.get(reverse('user_toggle_status', args=[self.super_user.pk]))
        self.assertEqual(res.status_code, 302)
        self.super_user.refresh_from_db()
        self.assertTrue(self.super_user.is_active)

    def test_security_audit_logging_on_role_changes(self):
        """SecurityAuditLog records actor, action, timestamp, and metadata on role updates."""
        from accounts.models import SecurityAuditLog
        initial_count = SecurityAuditLog.objects.count()

        self.client.login(username='root@example.com', password='RootPassword123!')
        p_module = Permission.objects.get(codename='module:catalog')
        p_view = Permission.objects.get(codename='catalog:products/list')

        data = {
            'name': 'audited_role',
            'display_name': 'دور مراجع',
            'is_active': 'on',
            'permissions': [p_module.pk, p_view.pk]
        }
        res = self.client.post(reverse('role_create'), data)
        self.assertEqual(res.status_code, 302)

        self.assertGreater(SecurityAuditLog.objects.count(), initial_count)
        log = SecurityAuditLog.objects.latest('id')
        self.assertEqual(log.actor, self.super_user)
        self.assertEqual(log.action_type, 'ROLE_CREATED')
        self.assertIn('إنشاء دور', log.description)

    def test_immediate_cache_invalidation(self):
        """Permission revocation reflects immediately in active session via clear_perm_cache."""
        p_mod = Permission.objects.get(codename='module:contacts')
        p_list = Permission.objects.get(codename='contacts:contacts/list')
        self.rep_role.permissions.add(p_mod, p_list)
        self.rep_user.clear_perm_cache()

        self.assertTrue(self.rep_user.has_permission('contacts:contacts/list'))

        # Revoke permission
        self.rep_role.permissions.remove(p_list)
        self.rep_user.clear_perm_cache()

        self.assertFalse(self.rep_user.has_permission('contacts:contacts/list'))

    def test_abac_object_access_and_idor_protection(self):
        """Field representative cannot access another representative's visit record."""
        from contacts.models import Contact
        from activities.models import Visit

        contact = Contact.objects.create(name='عميل تجريبي', code='C-TEST-01', is_customer=True)
        visit_b = Visit.objects.create(
            contact=contact,
            owner=self.rep_user_b,
            created_by=self.rep_user_b,
            date='2026-10-24',
            status='started'
        )

        # Grant rep_a visits viewing permission
        p_mod = Permission.objects.get(codename='module:activities')
        p_view = Permission.objects.get(codename='activities:visits/view')
        self.rep_role.permissions.add(p_mod, p_view)
        self.rep_user.clear_perm_cache()

        # Rep A attempts to access Visit B
        self.client.login(username='rep_a@example.com', password='RepPassword123!')
        res = self.client.get(reverse('visit_detail', args=[visit_b.pk]))
        self.assertEqual(res.status_code, 403)



import csv
import io
import json
import sys
from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO, StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.test import Client, RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import (
    Role,
    RoleModuleScope,
    RoleTag,
    SecurityAuditLog,
    User,
    UserModuleScope,
    UserSettings,
)
from accounts.permissions import (
    can_user_access_object,
    get_scoped_queryset,
    get_user_managed_areas,
    get_user_managed_representatives,
    has_perm_or_admin,
    is_accountant,
    is_manager_eligible_for_area,
    is_manager_eligible_for_user,
    is_manager_or_higher,
    is_representative,
)
from accounts.scope_service import ScopeResolutionService
from accounts.services import (
    AuditLogService,
    ensure_representative_resources,
    get_representative_treasury,
    get_representative_warehouse,
)
from accounts.views import get_hierarchical_areas, validate_assigned_areas_for_user
from activities.models import Visit, VisitTemplate
from catalog.models import Product, ProductCategory
from contacts.models import Contact
from inventory.models import (
    InventoryStock,
    ProductTransferRequest,
    ProductTransferRequestItem,
    Warehouse,
)
from master_data.models import (
    Area,
    CompanyProfile,
    LocationSettings,
    PurchaseSettings,
    SalesSettings,
)
from master_data.services import SettingsService
from purchases.models import PurchaseOrder, PurchaseOrderItem, PurchaseReturnOrder
from sales.models import Collection, CustomerAccount, SalesOrder, SalesOrderItem
from treasury.models import Vault, VendorPayment


class AreaBasedApprovalsAndVisibilityTests(TestCase):
    """
    Automated test suite verifying:
    1. Standardized Manager Eligibility based strictly on Main Area (Governorate root)
    2. Cross-subarea approval within same main area is permitted
    3. Cross-main-area approval is strictly rejected
    4. Anti-self-approval enforcement
    5. Manager operational visibility over warehouses, visits, and treasuries
    6. Read-only treasury visibility (no unauthorized transaction authority)
    """

    def setUp(self):
        # 1. Geographic Hierarchy:
        # Cairo Governorate (Root) -> Subareas: Nasr City, Maadi, Heliopolis
        self.cairo_main = Area.objects.create(code='CAI', name='القاهرة', area_type='governorate', parent=None)
        self.nasr_city = Area.objects.create(code='CAI-NC', name='مدينة نصر', area_type='subarea', parent=self.cairo_main)
        self.maadi = Area.objects.create(code='CAI-MD', name='المعادي', area_type='subarea', parent=self.cairo_main)
        self.heliopolis = Area.objects.create(code='CAI-HL', name='مصر الجديدة', area_type='subarea', parent=self.cairo_main)

        # Giza Governorate (Root) -> Subarea: Dokki
        self.giza_main = Area.objects.create(code='GIZ', name='الجيزة', area_type='governorate', parent=None)
        self.dokki = Area.objects.create(code='GIZ-DK', name='الدقي', area_type='subarea', parent=self.giza_main)

        # 2. Roles:
        self.rep_role, _ = Role.objects.get_or_create(name='MedicalRep', defaults={'display_name': 'مندوب دعاية', 'is_rep': True})
        self.rep_role.is_rep = True
        self.rep_role.save()

        self.mgr_role, _ = Role.objects.get_or_create(name='AreaManager', defaults={'display_name': 'مدير منطقة', 'is_area_manager': True, 'is_rep': False})
        self.mgr_role.is_area_manager = True
        self.mgr_role.is_rep = False
        self.mgr_role.save()

        # 3. Users:
        # Manager Cairo is assigned to Cairo Main (Governorate)
        self.mgr_cairo = User.objects.create_user(username='mgr_cairo', role=self.mgr_role)
        self.mgr_cairo.assigned_areas.add(self.cairo_main)

        # Manager Giza is assigned to Giza Main
        self.mgr_giza = User.objects.create_user(username='mgr_giza', role=self.mgr_role)
        self.mgr_giza.assigned_areas.add(self.giza_main)

        # Rep Cairo 1 is assigned to Nasr City (subarea in Cairo)
        self.rep_cairo1 = User.objects.create_user(username='rep_cairo1', role=self.rep_role)
        self.rep_cairo1.assigned_areas.add(self.nasr_city)

        # Rep Cairo 2 is assigned to Maadi (subarea in Cairo)
        self.rep_cairo2 = User.objects.create_user(username='rep_cairo2', role=self.rep_role)
        self.rep_cairo2.assigned_areas.add(self.maadi)

        # Rep Giza is assigned to Dokki (subarea in Giza)
        self.rep_giza = User.objects.create_user(username='rep_giza', role=self.rep_role)
        self.rep_giza.assigned_areas.add(self.dokki)

        # 4. Resources:
        self.wh_rep1 = Warehouse.objects.create(
            name='مخزن مندوب نصر سيتي', code='WH-REP-1', assigned_user=self.rep_cairo1,
            area=self.nasr_city, is_rep_warehouse=True
        )
        self.wh_rep_giza = Warehouse.objects.create(
            name='مخزن مندوب الدقي', code='WH-REP-G', assigned_user=self.rep_giza,
            area=self.dokki, is_rep_warehouse=True
        )

        self.vault_rep1 = Vault.objects.create(
            name='خزنة مندوب نصر سيتي', assigned_user=self.rep_cairo1,
            current_balance=Decimal('5000.00'), is_rep_vault=True
        )
        self.vault_rep_giza = Vault.objects.create(
            name='خزنة مندوب الدقي', assigned_user=self.rep_giza,
            current_balance=Decimal('3000.00'), is_rep_vault=True
        )

        # 5. Contacts & Visits:
        self.contact_cairo = Contact.objects.create(name='عيادة النور', area=self.nasr_city)
        self.visit_cairo = Visit.objects.create(
            serial_num=8801, owner=self.rep_cairo1, contact=self.contact_cairo,
            date=timezone.now().date(), status='finished', approval_status='pending'
        )

    def test_manager_eligibility_across_subareas_in_same_main_area(self):
        """Cairo Manager has eligibility over reps in Nasr City and Maadi because both belong to Cairo."""
        self.assertTrue(is_manager_eligible_for_user(self.mgr_cairo, self.rep_cairo1))
        self.assertTrue(is_manager_eligible_for_user(self.mgr_cairo, self.rep_cairo2))

    def test_manager_eligibility_fails_across_different_main_areas(self):
        """Cairo Manager has NO eligibility over Giza rep, and Giza Manager has NO eligibility over Cairo reps."""
        self.assertFalse(is_manager_eligible_for_user(self.mgr_cairo, self.rep_giza))
        self.assertFalse(is_manager_eligible_for_user(self.mgr_giza, self.rep_cairo1))

    def test_anti_self_approval(self):
        """Managers cannot approve their own operations."""
        self.assertFalse(is_manager_eligible_for_user(self.mgr_cairo, self.mgr_cairo))

    def test_manager_managed_representatives_scope(self):
        """get_user_managed_representatives returns all reps belonging to manager's main area."""
        cairo_reps = list(get_user_managed_representatives(self.mgr_cairo).values_list('id', flat=True))
        self.assertIn(self.rep_cairo1.id, cairo_reps)
        self.assertIn(self.rep_cairo2.id, cairo_reps)
        self.assertNotIn(self.rep_giza.id, cairo_reps)

    def test_manager_warehouse_visibility(self):
        """Cairo manager can view warehouses of Cairo reps, but cannot view Giza rep warehouse."""
        scoped_whs = list(get_scoped_queryset(Warehouse.objects.all(), self.mgr_cairo, 'warehouse').values_list('id', flat=True))
        self.assertIn(self.wh_rep1.id, scoped_whs)
        self.assertNotIn(self.wh_rep_giza.id, scoped_whs)

        # Object level access
        self.assertTrue(can_user_access_object(self.mgr_cairo, self.wh_rep1, 'view'))
        self.assertFalse(can_user_access_object(self.mgr_cairo, self.wh_rep_giza, 'view'))

    def test_manager_treasury_visibility_without_transaction_authority(self):
        """Cairo manager can view Cairo rep's vault balance, but CANNOT execute transactions or adjustments."""
        scoped_vaults = list(get_scoped_queryset(Vault.objects.all(), self.mgr_cairo, 'vault').values_list('id', flat=True))
        self.assertIn(self.vault_rep1.id, scoped_vaults)
        self.assertNotIn(self.vault_rep_giza.id, scoped_vaults)

        # Manager has read access
        self.assertTrue(can_user_access_object(self.mgr_cairo, self.vault_rep1, 'view'))

        # Manager has NO transaction authority over rep vault
        self.assertFalse(can_user_access_object(self.mgr_cairo, self.vault_rep1, 'deposit'))
        self.assertFalse(can_user_access_object(self.mgr_cairo, self.vault_rep1, 'withdraw'))
        self.assertFalse(can_user_access_object(self.mgr_cairo, self.vault_rep1, 'transfer'))
        self.assertFalse(can_user_access_object(self.mgr_cairo, self.vault_rep1, 'edit'))
        self.assertFalse(can_user_access_object(self.mgr_cairo, self.vault_rep1, 'delete'))

    def test_visit_approval_by_same_main_area_manager(self):
        """Cairo manager can approve Cairo visit; Giza manager cannot."""
        self.assertTrue(can_user_access_object(self.mgr_cairo, self.visit_cairo, 'approve'))
        self.assertFalse(can_user_access_object(self.mgr_giza, self.visit_cairo, 'approve'))

        # Rep cannot approve own visit
        self.assertFalse(can_user_access_object(self.rep_cairo1, self.visit_cairo, 'approve'))

class AuditLoggingTests(TestCase):
    def setUp(self):
        self.client = Client()

        self.superadmin_role, _ = Role.objects.get_or_create(
            name=Role.ROLE_SUPERADMIN,
            defaults={'display_name': 'مدير النظام الأعلى', 'is_super': True, 'is_system': True, 'is_active': True}
        )
        self.super_user = User.objects.create_superuser(
            username='admin_audit@wea.com',
            email='admin_audit@wea.com',
            password='Password123!',
            name='Admin Auditor',
            role=self.superadmin_role
        )

        self.rep_role, _ = Role.objects.get_or_create(
            name=Role.ROLE_REP,
            defaults={'display_name': 'مندوب', 'is_rep': True, 'is_system': True, 'is_active': True}
        )
        self.test_user = User.objects.create_user(
            username='rep_target@wea.com',
            email='rep_target@wea.com',
            password='Password123!',
            name='Target Rep',
            role=self.rep_role
        )

    def test_audit_log_service_creation_and_redaction(self):
        """Test that AuditLogService properly creates log records and recursively redacts sensitive fields."""
        log = AuditLogService.log(
            action='update',
            module='users',
            user=self.super_user,
            record_id=self.test_user.id,
            record_name=self.test_user.name,
            previous_values={
                'name': 'Old Name',
                'password': 'old_plain_password_123',
                'nested': {'api_token': 'secret_tok_123', 'status': 'active'}
            },
            new_values={
                'name': 'New Name',
                'password': 'new_plain_password_456',
                'nested': {'api_token': 'new_secret_tok_456', 'status': 'active'}
            },
            status='success',
            ip_address='192.168.1.100',
            user_agent='Mozilla/5.0 TestBrowser'
        )

        self.assertIsNotNone(log.id)
        self.assertEqual(log.module, 'users')
        self.assertEqual(log.action, 'update')
        self.assertEqual(log.user, self.super_user)
        self.assertEqual(log.ip_address, '192.168.1.100')

        # Verify sensitive redaction
        self.assertEqual(log.previous_values['password'], '[REDACTED]')
        self.assertEqual(log.new_values['password'], '[REDACTED]')
        self.assertEqual(log.previous_values['nested']['api_token'], '[REDACTED]')
        self.assertEqual(log.new_values['nested']['api_token'], '[REDACTED]')

        # Verify non-sensitive preserved
        self.assertEqual(log.previous_values['name'], 'Old Name')
        self.assertEqual(log.new_values['name'], 'New Name')
        self.assertEqual(log.new_values['nested']['status'], 'active')

    def test_audit_logs_view_filtering(self):
        """Test the audit logs list page filters by module, action, date range, and search query."""
        self.client.login(username='admin_audit@wea.com', password='Password123!')

        # Create distinct test logs
        AuditLogService.log(
            action='login',
            module='auth',
            user=self.super_user,
            record_name='تسجيل دخول ناجح',
            new_values={'username': 'admin_audit@wea.com'},
            ip_address='127.0.0.1'
        )
        AuditLogService.log(
            action='create',
            module='contacts',
            user=self.super_user,
            record_id=101,
            record_name='صيدلية الشفاء الممتازة',
            new_values={'name': 'صيدلية الشفاء الممتازة'},
            ip_address='127.0.0.1'
        )
        AuditLogService.log(
            action='delete',
            module='users',
            user=self.super_user,
            record_id=self.test_user.id,
            record_name='Target Rep',
            previous_values={'name': 'Target Rep'},
            ip_address='127.0.0.1'
        )

        # 1. Filter by module='contacts'
        res = self.client.get(reverse('audit_logs_list') + '?module=contacts')
        self.assertEqual(res.status_code, 200)
        logs = res.context['logs']
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0].record_name, 'صيدلية الشفاء الممتازة')

        # 2. Filter by action='login'
        res = self.client.get(reverse('audit_logs_list') + '?action=login')
        self.assertEqual(res.status_code, 200)
        logs = res.context['logs']
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0].module, 'auth')

        # 3. Search query q='الشفاء'
        res = self.client.get(reverse('audit_logs_list') + '?q=الشفاء')
        self.assertEqual(res.status_code, 200)
        logs = res.context['logs']
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0].record_name, 'صيدلية الشفاء الممتازة')

        # 4. Date range filtering
        today_str = date.today().strftime('%Y-%m-%d')
        res = self.client.get(reverse('audit_logs_list') + f'?date_from={today_str}&date_to={today_str}')
        self.assertEqual(res.status_code, 200)
        self.assertGreaterEqual(len(res.context['logs']), 3)

    def test_audit_log_detail_api(self):
        """Test fetching audit log details via AJAX JSON endpoint."""
        self.client.login(username='admin_audit@wea.com', password='Password123!')

        log = AuditLogService.log(
            action='update',
            module='contacts',
            user=self.super_user,
            record_id=50,
            record_name='مستشفى النيل',
            previous_values={'phone': '01011111111', 'notes': 'قديم'},
            new_values={'phone': '01022222222', 'notes': 'جديد'},
            ip_address='10.0.0.1'
        )

        url = reverse('audit_log_detail', kwargs={'pk': log.id})
        res = self.client.get(url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['log']['module'], 'contacts')
        self.assertEqual(data['log']['record_name'], 'مستشفى النيل')
        self.assertEqual(data['log']['previous_values']['phone'], '01011111111')
        self.assertEqual(data['log']['new_values']['phone'], '01022222222')

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

class AppWideDataScopingTests(TestCase):
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
        self.accountant_role, _ = Role.objects.get_or_create(
            name=Role.ROLE_ACCOUNTANT,
            defaults={'display_name': 'محاسب', 'is_system': True, 'is_active': True}
        )
        self.rep_role, _ = Role.objects.get_or_create(
            name=Role.ROLE_REP,
            defaults={'display_name': 'مندوب مبيعات', 'is_rep': True, 'is_system': True, 'is_active': True}
        )
        self.medical_rep_role, _ = Role.objects.get_or_create(
            name=Role.ROLE_MEDICAL_REP,
            defaults={'display_name': 'مندوب دعاية طبية', 'is_rep': True, 'is_system': True, 'is_active': True}
        )

        # Geographic Areas Hierarchy
        # Main Area 1: Cairo (القاهرة)
        self.cairo = Area.objects.create(code='CAI', name='القاهرة', area_type='governorate', is_company_area=False)
        self.nasr_city = Area.objects.create(code='NASR', name='مدينة نصر', area_type='subarea', parent=self.cairo, is_company_area=False)
        self.maadi = Area.objects.create(code='MAADI', name='المعادي', area_type='subarea', parent=self.cairo, is_company_area=False)

        # Main Area 2: Giza (الجيزة)
        self.giza = Area.objects.create(code='GIZ', name='الجيزة', area_type='governorate', is_company_area=False)
        self.dokki = Area.objects.create(code='DOK', name='الدقي', area_type='subarea', parent=self.giza, is_company_area=False)
        self.haram = Area.objects.create(code='HAR', name='الهرم', area_type='subarea', parent=self.giza, is_company_area=False)

        # Users
        # 1. Superadmin
        self.superadmin = User.objects.create_superuser(
            username='super@wea.com', email='super@wea.com', password='Password123!',
            name='Super Admin', role=self.superadmin_role
        )

        # 2. Accountant
        self.accountant = User.objects.create_user(
            username='acct@wea.com', email='acct@wea.com', password='Password123!',
            name='Chief Accountant', role=self.accountant_role
        )

        # 3. Manager Cairo (assigned to Cairo main area)
        self.mgr_cairo = User.objects.create_user(
            username='mgr_cairo@wea.com', email='mgr_cairo@wea.com', password='Password123!',
            name='Manager Cairo', role=self.manager_role
        )
        self.mgr_cairo.assigned_areas.add(self.cairo)

        # 4. Manager Giza (assigned to Giza main area)
        self.mgr_giza = User.objects.create_user(
            username='mgr_giza@wea.com', email='mgr_giza@wea.com', password='Password123!',
            name='Manager Giza', role=self.manager_role
        )
        self.mgr_giza.assigned_areas.add(self.giza)

        # 5. Manager Without Area (unassigned)
        self.mgr_no_area = User.objects.create_user(
            username='mgr_no_area@wea.com', email='mgr_no_area@wea.com', password='Password123!',
            name='Manager No Area', role=self.manager_role
        )

        # 6. Rep 1 Cairo (Nasr City subarea)
        self.rep_cairo_1 = User.objects.create_user(
            username='rep_cairo1@wea.com', email='rep_cairo1@wea.com', password='Password123!',
            name='Rep Cairo NasrCity', role=self.rep_role
        )
        self.rep_cairo_1.assigned_areas.add(self.nasr_city)

        # 7. Rep 2 Cairo (Maadi subarea - same main area, different secondary area)
        self.rep_cairo_2 = User.objects.create_user(
            username='rep_cairo2@wea.com', email='rep_cairo2@wea.com', password='Password123!',
            name='Rep Cairo Maadi', role=self.rep_role
        )
        self.rep_cairo_2.assigned_areas.add(self.maadi)

        # 8. Rep Giza (Dokki subarea)
        self.rep_giza = User.objects.create_user(
            username='rep_giza@wea.com', email='rep_giza@wea.com', password='Password123!',
            name='Rep Giza Dokki', role=self.rep_role
        )
        self.rep_giza.assigned_areas.add(self.dokki)

        # 9. Medical Rep Cairo
        self.med_rep_cairo = User.objects.create_user(
            username='med_rep@wea.com', email='med_rep@wea.com', password='Password123!',
            name='Medical Rep Cairo', role=self.medical_rep_role
        )
        self.med_rep_cairo.assigned_areas.add(self.nasr_city)

        # Contacts
        self.contact_cairo = Contact.objects.create(
            name='صيدلية مصر - مدينة نصر', area=self.nasr_city, is_customer=True,
            created_by=self.rep_cairo_1
        )
        self.contact_giza = Contact.objects.create(
            name='صيدلية النيل - الدقي', area=self.dokki, is_customer=True,
            created_by=self.rep_giza
        )

        # Warehouses
        self.wh_cairo = Warehouse.objects.create(code='WH-CAI', name='مخزن القاهرة الرئيسي', area=self.cairo, is_main=True, is_active=True)
        self.wh_giza = Warehouse.objects.create(code='WH-GIZ', name='مخزن الجيزة', area=self.giza, is_main=False, is_active=True)

        # Sales Orders
        self.order_cairo_1 = SalesOrder.objects.create(
            order_number='SO-C1', customer=self.contact_cairo, source_warehouse=self.wh_cairo,
            created_by=self.rep_cairo_1, grand_total=Decimal('1000.00'), status='pending'
        )
        self.order_cairo_2 = SalesOrder.objects.create(
            order_number='SO-C2', customer=self.contact_cairo, source_warehouse=self.wh_cairo,
            created_by=self.rep_cairo_2, grand_total=Decimal('2000.00'), status='pending'
        )
        self.order_giza = SalesOrder.objects.create(
            order_number='SO-G1', customer=self.contact_giza, source_warehouse=self.wh_giza,
            created_by=self.rep_giza, grand_total=Decimal('3000.00'), status='pending'
        )

        # Collections
        self.vault_cairo_1 = Vault.objects.create(
            name='خزنة مندوب نصر', assigned_user=self.rep_cairo_1, current_balance=Decimal('500.00'), is_active=True
        )
        self.vault_giza = Vault.objects.create(
            name='خزنة مندوب الدقي', assigned_user=self.rep_giza, current_balance=Decimal('700.00'), is_active=True
        )
        self.col_cairo_1 = Collection.objects.create(
            serial_num=101, customer=self.contact_cairo, vault=self.vault_cairo_1,
            amount=Decimal('500.00'), created_by=self.rep_cairo_1
        )
        self.col_giza = Collection.objects.create(
            serial_num=102, customer=self.contact_giza, vault=self.vault_giza,
            amount=Decimal('700.00'), created_by=self.rep_giza
        )

        # Visits
        self.visit_cairo_1 = Visit.objects.create(
            serial_num=501, contact=self.contact_cairo,
            owner=self.rep_cairo_1, created_by=self.rep_cairo_1, status='finished'
        )
        self.visit_cairo_2 = Visit.objects.create(
            serial_num=502, contact=self.contact_cairo,
            owner=self.rep_cairo_2, created_by=self.rep_cairo_2, status='finished'
        )
        self.visit_giza = Visit.objects.create(
            serial_num=503, contact=self.contact_giza,
            owner=self.rep_giza, created_by=self.rep_giza, status='finished'
        )

    def test_rep_data_scoping_strict_ownership(self):
        """A sales representative sees strictly their own records, not peers in the same or other areas."""
        # Sales Orders
        scoped_so = get_scoped_queryset(SalesOrder.objects.all(), self.rep_cairo_1, 'salesorder')
        self.assertIn(self.order_cairo_1, scoped_so)
        self.assertNotIn(self.order_cairo_2, scoped_so)  # Peer in same main area (different subarea) forbidden
        self.assertNotIn(self.order_giza, scoped_so)     # Rep in other main area forbidden

        # Collections
        scoped_col = get_scoped_queryset(Collection.objects.all(), self.rep_cairo_1, 'collection')
        self.assertIn(self.col_cairo_1, scoped_col)
        self.assertNotIn(self.col_giza, scoped_col)

        # Visits
        scoped_vis = get_scoped_queryset(Visit.objects.all(), self.rep_cairo_1, 'visit')
        self.assertIn(self.visit_cairo_1, scoped_vis)
        self.assertNotIn(self.visit_cairo_2, scoped_vis)
        self.assertNotIn(self.visit_giza, scoped_vis)

        # Object-level check
        self.assertTrue(can_user_access_object(self.rep_cairo_1, self.order_cairo_1, 'view'))
        self.assertFalse(can_user_access_object(self.rep_cairo_1, self.order_cairo_2, 'view'))
        self.assertFalse(can_user_access_object(self.rep_cairo_1, self.order_giza, 'view'))

    def test_manager_main_area_scoping(self):
        """A manager sees records of reps in their main area across sub-areas, but NOT other main areas."""
        # Manager Cairo sees reps in Nasr City and Maadi (both under Cairo)
        scoped_so = get_scoped_queryset(SalesOrder.objects.all(), self.mgr_cairo, 'salesorder')
        self.assertIn(self.order_cairo_1, scoped_so)
        self.assertIn(self.order_cairo_2, scoped_so)
        self.assertNotIn(self.order_giza, scoped_so)  # Giza is a different main area!

        # Visits
        scoped_vis = get_scoped_queryset(Visit.objects.all(), self.mgr_cairo, 'visit')
        self.assertIn(self.visit_cairo_1, scoped_vis)
        self.assertIn(self.visit_cairo_2, scoped_vis)
        self.assertNotIn(self.visit_giza, scoped_vis)

        # Manager Giza sees Giza rep, not Cairo reps
        scoped_so_giza = get_scoped_queryset(SalesOrder.objects.all(), self.mgr_giza, 'salesorder')
        self.assertIn(self.order_giza, scoped_so_giza)
        self.assertNotIn(self.order_cairo_1, scoped_so_giza)
        self.assertNotIn(self.order_cairo_2, scoped_so_giza)

        # Object level checks
        self.assertTrue(can_user_access_object(self.mgr_cairo, self.order_cairo_1, 'view'))
        self.assertTrue(can_user_access_object(self.mgr_cairo, self.order_cairo_2, 'view'))
        self.assertFalse(can_user_access_object(self.mgr_cairo, self.order_giza, 'view'))

    def test_manager_without_area_fails_securely(self):
        """A manager without a valid main-area assignment fails securely and sees no reps."""
        scoped_so = get_scoped_queryset(SalesOrder.objects.all(), self.mgr_no_area, 'salesorder')
        self.assertEqual(scoped_so.count(), 0)

        scoped_vis = get_scoped_queryset(Visit.objects.all(), self.mgr_no_area, 'visit')
        self.assertEqual(scoped_vis.count(), 0)

        self.assertFalse(can_user_access_object(self.mgr_no_area, self.order_cairo_1, 'view'))
        self.assertFalse(can_user_access_object(self.mgr_no_area, self.order_giza, 'view'))

    def test_accountant_broad_financial_visibility(self):
        """Accountant sees all sales orders and collections across all areas, but cannot approve/tamper."""
        scoped_so = get_scoped_queryset(SalesOrder.objects.all(), self.accountant, 'salesorder')
        self.assertEqual(scoped_so.count(), 3)
        self.assertIn(self.order_cairo_1, scoped_so)
        self.assertIn(self.order_cairo_2, scoped_so)
        self.assertIn(self.order_giza, scoped_so)

        scoped_col = get_scoped_queryset(Collection.objects.all(), self.accountant, 'collection')
        self.assertEqual(scoped_col.count(), 2)

        self.assertTrue(can_user_access_object(self.accountant, self.order_cairo_1, 'view'))
        self.assertTrue(can_user_access_object(self.accountant, self.order_giza, 'view'))

    def test_superadmin_unrestricted_access(self):
        """Superadmin has global unrestricted access to all records."""
        scoped_so = get_scoped_queryset(SalesOrder.objects.all(), self.superadmin, 'salesorder')
        self.assertEqual(scoped_so.count(), 3)

        scoped_vis = get_scoped_queryset(Visit.objects.all(), self.superadmin, 'visit')
        self.assertEqual(scoped_vis.count(), 3)

        self.assertTrue(can_user_access_object(self.superadmin, self.order_cairo_1, 'view'))
        self.assertTrue(can_user_access_object(self.superadmin, self.order_giza, 'view'))

    def test_anti_self_approval(self):
        """No user can approve or reject their own submitted visit or transaction."""
        # Manager Cairo visit created by themselves
        visit_mgr = Visit.objects.create(
            serial_num=504, contact=self.contact_cairo,
            owner=self.mgr_cairo, created_by=self.mgr_cairo, status='planned'
        )
        self.assertFalse(can_user_access_object(self.mgr_cairo, visit_mgr, 'approve'))
        self.assertFalse(can_user_access_object(self.mgr_cairo, visit_mgr, 'reject'))
        # But can view it
        self.assertTrue(can_user_access_object(self.mgr_cairo, visit_mgr, 'view'))

class GeographicAreaSelectorTests(TestCase):
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

        # Areas
        self.cairo = Area.objects.create(code='CAI', name='القاهرة', area_type='governorate', is_company_area=False)
        self.nasr_city = Area.objects.create(code='NASR', name='مدينة نصر', area_type='subarea', parent=self.cairo, is_company_area=False)
        self.maadi = Area.objects.create(code='MAADI', name='المعادي', area_type='subarea', parent=self.cairo, is_company_area=False)

        self.alex = Area.objects.create(code='ALX', name='الإسكندرية', area_type='governorate', is_company_area=False)
        self.smouha = Area.objects.create(code='SMH', name='سموحة', area_type='subarea', parent=self.alex, is_company_area=False)

        # Users
        self.superadmin = User.objects.create_superuser(
            username='admin@wea.com', email='admin@wea.com', password='Password123!',
            name='Super Admin User', role=self.superadmin_role
        )

        self.mgr_cairo = User.objects.create_user(
            username='mgr@wea.com', email='mgr@wea.com', password='Password123!',
            name='Manager Cairo', role=self.manager_role
        )
        self.mgr_cairo.assigned_areas.add(self.cairo)

        self.rep_user = User.objects.create_user(
            username='rep@wea.com', email='rep@wea.com', password='Password123!',
            name='Representative User', role=self.rep_role
        )
        self.rep_user.assigned_areas.add(self.nasr_city)

    def test_get_hierarchical_areas_for_superadmin_and_manager(self):
        """Superadmin gets all governorates with subareas, manager gets only their main areas."""
        super_areas = get_hierarchical_areas(self.superadmin)
        self.assertIn(self.cairo, super_areas)
        self.assertIn(self.alex, super_areas)

        mgr_areas = get_hierarchical_areas(self.mgr_cairo)
        self.assertIn(self.cairo, mgr_areas)
        self.assertNotIn(self.alex, mgr_areas)

    def test_validate_assigned_areas_server_side(self):
        """Validates valid, invalid, and unauthorized area assignment on the server."""
        # 1. Valid areas for superadmin
        valid, msg, ids = validate_assigned_areas_for_user(self.superadmin, [str(self.cairo.id), str(self.smouha.id)])
        self.assertTrue(valid)
        self.assertEqual(ids, [self.cairo.id, self.smouha.id])

        # 2. Invalid/bogus area ID
        valid, msg, ids = validate_assigned_areas_for_user(self.superadmin, ['999999'])
        self.assertFalse(valid)
        self.assertIn("غير صالحة", msg)

        # 3. Non-integer ID
        valid, msg, ids = validate_assigned_areas_for_user(self.superadmin, ['not_an_id'])
        self.assertFalse(valid)

        # 4. Manager trying to assign area outside their main area
        valid, msg, ids = validate_assigned_areas_for_user(self.mgr_cairo, [str(self.smouha.id)])
        self.assertFalse(valid)
        self.assertIn("خارج نطاق مسؤوليتك", msg)

        # 5. Manager assigning area inside their main area
        valid, msg, ids = validate_assigned_areas_for_user(self.mgr_cairo, [str(self.nasr_city.id)])
        self.assertTrue(valid)
        self.assertEqual(ids, [self.nasr_city.id])

    def test_user_edit_page_renders_hierarchical_selector(self):
        """Edit user page renders the hierarchical area selector component with existing areas selected."""
        self.client.login(username='admin@wea.com', password='Password123!')
        res = self.client.get(reverse('user_edit', kwargs={'pk': self.rep_user.pk}))
        self.assertEqual(res.status_code, 200)
        content = res.content.decode('utf-8')

        # Check for selector elements
        self.assertIn('المناطق الجغرافية المعينة للمستخدم', content)
        self.assertIn('ابحث باسم المنطقة أو المحافظة', content)
        self.assertIn('تحديد الكل', content)
        self.assertIn('مسح التحديد', content)
        self.assertIn(self.cairo.name, content)
        self.assertIn(self.nasr_city.name, content)

        # Nasr City is checked for rep_user
        self.assertIn(f'value="{self.nasr_city.id}"', content)
        self.assertIn(self.nasr_city.id, res.context['selected_area_ids'])

    def test_user_edit_post_updates_areas_safely(self):
        """POST to user_edit updates areas and logs security audit."""
        self.client.login(username='admin@wea.com', password='Password123!')
        data = {
            'name': 'Rep User Updated',
            'email': 'rep@wea.com',
            'code': 'REP-01',
            'mobile': '01012345678',
            'role': self.rep_role.id,
            'is_active': 'on',
            'assigned_areas': [str(self.nasr_city.id), str(self.maadi.id)],
        }
        res = self.client.post(reverse('user_edit', kwargs={'pk': self.rep_user.pk}), data)
        self.assertEqual(res.status_code, 302)

        self.rep_user.refresh_from_db()
        assigned_ids = set(self.rep_user.assigned_areas.values_list('id', flat=True))
        self.assertEqual(assigned_ids, {self.nasr_city.id, self.maadi.id})

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

class RepresentativeProvisioningTests(TestCase):
    """
    Automated test suite verifying:
    1. Automatic warehouse and treasury provisioning for representatives
    2. Settings toggle controls (auto_create_rep_warehouse / auto_create_rep_treasury)
    3. Idempotency upon repeated saves and profile edits
    4. Safe, non-destructive backfill command preserving existing balances
    """

    def setUp(self):
        # Create Main Area (Governorate) & Subarea
        self.cairo_main = Area.objects.create(code='CAI', name='القاهرة', area_type='governorate', parent=None)
        self.nasr_city = Area.objects.create(code='CAI-NC', name='مدينة نصر', area_type='subarea', parent=self.cairo_main)

        # Get or create Roles
        self.rep_role, _ = Role.objects.get_or_create(
            name='MedicalRep', defaults={'display_name': 'مندوب دعاية طبية', 'is_rep': True, 'is_sales_team': True}
        )
        self.rep_role.is_rep = True
        self.rep_role.is_sales_team = True
        self.rep_role.save()

        self.direct_sales_role, _ = Role.objects.get_or_create(
            name='DirectSalesRep', defaults={'display_name': 'مندوب مبيعات مباشر', 'is_rep': True, 'is_sales_team': True}
        )
        self.direct_sales_role.is_rep = True
        self.direct_sales_role.is_sales_team = True
        self.direct_sales_role.save()

        self.mgr_role, _ = Role.objects.get_or_create(
            name='AreaManager', defaults={'display_name': 'مدير منطقة', 'is_area_manager': True, 'is_sales_team': True, 'is_rep': False}
        )
        self.mgr_role.is_area_manager = True
        self.mgr_role.is_sales_team = True
        self.mgr_role.is_rep = False
        self.mgr_role.save()

        # Ensure settings are enabled by default
        self.settings = UserSettings.get_settings()
        self.settings.auto_create_rep_warehouse = True
        self.settings.auto_create_rep_treasury = True
        self.settings.save()

    def test_rep_role_identification(self):
        """Test is_representative accurately detects representatives and excludes managers."""
        rep = User.objects.create_user(username='test_rep1', role=self.rep_role)
        mgr = User.objects.create_user(username='test_mgr1', role=self.mgr_role)

        self.assertTrue(is_representative(rep))
        self.assertFalse(is_representative(mgr))

    def test_automatic_warehouse_and_treasury_creation(self):
        """Creating a representative automatically creates dedicated warehouse and treasury."""
        rep = User.objects.create_user(
            username='rep_auto1',
            first_name='أحمد',
            last_name='علي',
            role=self.rep_role
        )
        rep.assigned_areas.add(self.nasr_city)

        # Retrieve designated resources
        wh = get_representative_warehouse(rep)
        vault = get_representative_treasury(rep)

        self.assertIsNotNone(wh)
        self.assertIsNotNone(vault)
        self.assertTrue(wh.is_rep_warehouse)
        self.assertEqual(wh.assigned_user, rep)
        self.assertEqual(wh.area, self.nasr_city)
        self.assertEqual(wh.main_area, self.cairo_main)
        self.assertTrue(vault.is_rep_vault)
        self.assertEqual(vault.assigned_user, rep)

    def test_settings_toggle_disables_creation(self):
        """Disabling settings prevents automatic creation for new representatives."""
        self.settings.auto_create_rep_warehouse = False
        self.settings.auto_create_rep_treasury = False
        self.settings.save()

        rep = User.objects.create_user(
            username='rep_manual1',
            role=self.direct_sales_role
        )

        wh = get_representative_warehouse(rep)
        vault = get_representative_treasury(rep)

        self.assertIsNone(wh)
        self.assertIsNone(vault)

    def test_repeated_saves_do_not_create_duplicates(self):
        """Repeated saves and profile updates do NOT duplicate warehouse or treasury."""
        rep = User.objects.create_user(
            username='rep_idemp1',
            role=self.rep_role
        )

        wh1 = get_representative_warehouse(rep)
        v1 = get_representative_treasury(rep)

        # Profile edits
        rep.first_name = 'محمود'
        rep.email = 'm@example.com'
        rep.save()

        # Re-run explicit ensure_representative_resources
        wh2, v2, created_wh, created_v = ensure_representative_resources(rep)

        self.assertFalse(created_wh)
        self.assertFalse(created_v)
        self.assertEqual(wh1.pk, wh2.pk)
        self.assertEqual(v1.pk, v2.pk)
        self.assertEqual(Warehouse.objects.filter(assigned_user=rep).count(), 1)
        self.assertEqual(Vault.objects.filter(assigned_user=rep).count(), 1)

    def test_backfill_management_command_idempotence(self):
        """Backfill command safely provisions missing resources and preserves existing balances."""
        self.settings.auto_create_rep_warehouse = False
        self.settings.auto_create_rep_treasury = False
        self.settings.save()

        # Create rep without resources
        rep = User.objects.create_user(
            username='rep_backfill1',
            role=self.rep_role
        )
        rep.assigned_areas.add(self.nasr_city)

        # Pre-create a vault with a custom balance to test preservation
        existing_vault = Vault.objects.create(
            name="خزنة عهدة قديمة",
            assigned_user=rep,
            current_balance=Decimal('7500.00'),
            is_rep_vault=True
        )

        # Re-enable settings
        self.settings.auto_create_rep_warehouse = True
        self.settings.auto_create_rep_treasury = True
        self.settings.save()

        # Run backfill
        out = io.StringIO()
        call_command('backfill_representative_resources', stdout=out)

        # Refresh
        existing_vault.refresh_from_db()
        self.assertEqual(existing_vault.current_balance, Decimal('7500.00'))

        # Warehouse should have been created
        wh = get_representative_warehouse(rep)
        self.assertIsNotNone(wh)
        self.assertEqual(wh.assigned_user, rep)

        # Re-run backfill to verify 0 new created
        out2 = io.StringIO()
        call_command('backfill_representative_resources', stdout=out2)
        output_str = out2.getvalue()
        self.assertIn("Created 0 warehouses, 0 treasuries", output_str)

    def test_delayed_role_assignment_triggers_provisioning(self):
        """User created without a role, then updated to representative gets WH and Treasury."""
        user = User.objects.create_user(username='delayed_rep', first_name='سعيد', last_name='خالد')
        self.assertIsNone(get_representative_warehouse(user))
        self.assertIsNone(get_representative_treasury(user))

        user.role = self.rep_role
        user.save()

        wh = get_representative_warehouse(user)
        vault = get_representative_treasury(user)
        self.assertIsNotNone(wh)
        self.assertIsNotNone(vault)
        self.assertEqual(wh.assigned_user, user)
        self.assertEqual(vault.assigned_user, user)

class UserRoleConsolidationTests(TestCase):
    def setUp(self):
        self.client = Client()

        # Ensure canonical roles
        self.superadmin_role, _ = Role.objects.get_or_create(
            name=Role.ROLE_SUPERADMIN,
            defaults={'display_name': 'مدير النظام الأعلى', 'is_super': True, 'is_system': True, 'is_active': True}
        )
        self.manager_role, _ = Role.objects.get_or_create(
            name=Role.ROLE_MANAGER,
            defaults={'display_name': 'مدير', 'is_area_manager': True, 'is_sales_team': True, 'is_system': True, 'is_active': True}
        )
        self.accountant_role, _ = Role.objects.get_or_create(
            name=Role.ROLE_ACCOUNTANT,
            defaults={'display_name': 'محاسب', 'can_hold_vault': True, 'is_system': True, 'is_active': True}
        )
        self.rep_role, _ = Role.objects.get_or_create(
            name=Role.ROLE_REP,
            defaults={'display_name': 'مندوب مبيعات', 'is_rep': True, 'is_sales_team': True, 'is_system': True, 'is_active': True}
        )
        self.medical_rep_role, _ = Role.objects.get_or_create(
            name=Role.ROLE_MEDICAL_REP,
            defaults={'display_name': 'مندوب دعاية طبية', 'is_rep': True, 'is_sales_team': True, 'is_system': True, 'is_active': True}
        )

        # Inactive / obsolete role
        self.obsolete_role, _ = Role.objects.get_or_create(
            name='ObsoleteDriver',
            defaults={'display_name': 'سائق توزيع قديم', 'is_system': False, 'is_active': False}
        )
        self.obsolete_role.is_active = False
        self.obsolete_role.save()

        # Create test superuser
        self.superadmin_user = User.objects.create_superuser(
            username='super_test@wea.com',
            email='super_test@wea.com',
            password='Password123!',
            name='Super User',
            role=self.superadmin_role
        )

        # Create test users for each role
        self.mgr_user = User.objects.create_user(
            username='mgr_test@wea.com',
            email='mgr_test@wea.com',
            password='Password123!',
            name='Manager User',
            role=self.manager_role
        )
        self.acct_user = User.objects.create_user(
            username='acct_test@wea.com',
            email='acct_test@wea.com',
            password='Password123!',
            name='Accountant User',
            role=self.accountant_role
        )
        self.rep_user = User.objects.create_user(
            username='rep_test@wea.com',
            email='rep_test@wea.com',
            password='Password123!',
            name='Rep User',
            role=self.rep_role
        )
        self.med_rep_user = User.objects.create_user(
            username='med_rep_test@wea.com',
            email='med_rep_test@wea.com',
            password='Password123!',
            name='Med Rep User',
            role=self.medical_rep_role
        )

    def test_canonical_roles_queryset(self):
        """Only the 5 canonical roles must be returned by Role.get_supported_roles()."""
        supported = list(Role.get_supported_roles().values_list('name', flat=True))
        self.assertEqual(len(supported), 5)
        self.assertIn('superadmin', supported)
        self.assertIn('manager', supported)
        self.assertIn('accountant', supported)
        self.assertIn('rep', supported)
        self.assertIn('medical_rep', supported)
        self.assertNotIn('ObsoleteDriver', supported)

    def test_role_classification_helpers(self):
        """Verification of helper permissions and flags across all 5 roles."""
        self.assertTrue(self.superadmin_user.is_super_admin)
        self.assertTrue(is_manager_or_higher(self.superadmin_user))

        self.assertTrue(is_manager_or_higher(self.mgr_user))
        self.assertFalse(self.mgr_user.is_super_admin)
        self.assertFalse(is_representative(self.mgr_user))

        self.assertTrue(is_accountant(self.acct_user))
        self.assertFalse(is_representative(self.acct_user))

        self.assertTrue(is_representative(self.rep_user))
        self.assertEqual(self.rep_user.role.name, 'rep')
        self.assertEqual(self.rep_user.role.display_name, 'مندوب مبيعات')

        self.assertTrue(is_representative(self.med_rep_user))
        self.assertEqual(self.med_rep_user.role.name, 'medical_rep')
        self.assertEqual(self.med_rep_user.role.display_name, 'مندوب دعاية طبية')

    def test_user_creation_rejects_obsolete_role(self):
        """User creation must reject assigning any non-canonical role."""
        self.client.force_login(self.superadmin_user)
        response = self.client.post(reverse('user_create'), {
            'name': 'New User Test',
            'email': 'new_invalid@wea.com',
            'code': 'USR-099',
            'password': 'Password123!',
            'role': self.obsolete_role.id
        }, follow=True)
        self.assertContains(response, 'غير مدعوم')
        self.assertFalse(User.objects.filter(email='new_invalid@wea.com').exists())

    def test_user_creation_accepts_canonical_role(self):
        """User creation succeeds with canonical role and logs security audit."""
        self.client.force_login(self.superadmin_user)
        response = self.client.post(reverse('user_create'), {
            'name': 'New Rep Valid',
            'email': 'new_rep@wea.com',
            'code': 'USR-100',
            'password': 'Password123!',
            'role': self.medical_rep_role.id
        }, follow=True)
        self.assertTrue(User.objects.filter(email='new_rep@wea.com').exists())
        created_u = User.objects.get(email='new_rep@wea.com')
        self.assertEqual(created_u.role, self.medical_rep_role)
        self.assertTrue(SecurityAuditLog.objects.filter(target_user=created_u, action_type='USER_CREATED').exists())

    def test_user_edit_rejects_obsolete_role(self):
        """User edit rejects assigning any non-canonical role."""
        self.client.force_login(self.superadmin_user)
        response = self.client.post(reverse('user_edit', args=[self.rep_user.id]), {
            'name': 'Rep Updated',
            'email': self.rep_user.email,
            'code': 'R-01',
            'role': self.obsolete_role.id,
            'is_active': 'on'
        }, follow=True)
        self.assertContains(response, 'غير مدعوم')
        self.rep_user.refresh_from_db()
        self.assertEqual(self.rep_user.role, self.rep_role)

class UserDedicatedPagesAndLocationTests(TestCase):
    """
    Comprehensive tests for:
    1. Dedicated User Creation Page (/users/create/)
    2. Dedicated User Detail Page (/users/<pk>/)
    3. Dedicated User Edit Page (/users/<pk>/edit/)
    4. Isolated Password Reset (/users/<pk>/reset-password/)
    5. Server-side RBAC scoping (SuperAdmin, Manager, Accountant, Rep)
    6. Geocoding endpoints (/api/geocoding/search/ and /api/geocoding/reverse/)
    7. Warehouse location coordinates persistence
    """

    def setUp(self):
        # 1. Setup Roles
        self.super_role = Role.objects.get(name=Role.ROLE_SUPERADMIN)
        self.manager_role = Role.objects.get(name=Role.ROLE_MANAGER)
        self.manager_role.is_area_manager = True
        self.manager_role.is_active = True
        self.manager_role.save()

        self.accountant_role = Role.objects.get(name=Role.ROLE_ACCOUNTANT)
        self.rep_role = Role.objects.get(name=Role.ROLE_REP)

        # Assign user permissions with module root permission for module-level inheritance
        module_accounts_perm = Permission.objects.filter(codename='module:accounts').first()
        user_list_perm = Permission.objects.filter(codename='users:users/list').first()
        user_create_perm = Permission.objects.filter(codename='users:users/create').first()
        user_edit_perm = Permission.objects.filter(codename='users:users/edit').first()
        for p in [module_accounts_perm, user_list_perm, user_create_perm, user_edit_perm]:
            if p:
                self.manager_role.permissions.add(p)
                self.super_role.permissions.add(p)
                self.accountant_role.permissions.add(p)
                self.rep_role.permissions.add(p)

        # 2. Setup Areas
        self.cairo_gov = Area.objects.create(name='محافظة القاهرة', code='CAI-GOV', area_type='governorate')
        self.nasr_city = Area.objects.create(name='مدينة نصر', code='NASR', parent=self.cairo_gov, area_type='subarea')
        self.alex_gov = Area.objects.create(name='محافظة الإسكندرية', code='ALX-GOV', area_type='governorate')

        # 3. Setup Users
        self.superadmin = User.objects.create_user(
            username='super@wea.com',
            email='super@wea.com',
            password='AdminPass123!',
            name='Super Admin',
            role=self.super_role,
            is_staff=True,
            is_superuser=True
        )

        self.cairo_manager = User.objects.create_user(
            username='manager_cairo@wea.com',
            email='manager_cairo@wea.com',
            password='ManagerPass123!',
            name='Cairo Manager',
            role=self.manager_role,
            is_staff=False
        )
        self.cairo_manager.assigned_areas.set([self.cairo_gov, self.nasr_city])

        self.cairo_rep = User.objects.create_user(
            username='rep_cairo@wea.com',
            email='rep_cairo@wea.com',
            password='RepPass123!',
            name='Cairo Rep',
            role=self.rep_role,
            is_staff=False
        )
        self.cairo_rep.assigned_areas.set([self.nasr_city])

        self.alex_rep = User.objects.create_user(
            username='rep_alex@wea.com',
            email='rep_alex@wea.com',
            password='RepPass123!',
            name='Alex Rep',
            role=self.rep_role,
            is_staff=False
        )
        self.alex_rep.assigned_areas.set([self.alex_gov])

        self.accountant = User.objects.create_user(
            username='accountant@wea.com',
            email='accountant@wea.com',
            password='AccPass123!',
            name='System Accountant',
            role=self.accountant_role,
            is_staff=False
        )

        # Clear permission caches for fresh permission evaluation
        self.superadmin.clear_perm_cache()
        self.cairo_manager.clear_perm_cache()
        self.cairo_rep.clear_perm_cache()
        self.alex_rep.clear_perm_cache()
        self.accountant.clear_perm_cache()

        self.client = Client()

    # ==========================================
    # USER CREATION PAGE TESTS
    # ==========================================

    def test_user_create_page_get_superadmin(self):
        """Superadmin can load dedicated user creation page with all fields and roles."""
        self.client.login(username='super@wea.com', password='AdminPass123!')
        res = self.client.get('/users/create/')
        self.assertEqual(res.status_code, 200)
        self.assertTemplateUsed(res, 'accounts/user_create.html')
        self.assertContains(res, 'إضافة مستخدم جديد')
        self.assertContains(res, 'بيانات الحساب ومعلومات تسجيل الدخول')
        self.assertContains(res, 'تعيين المناطق الجغرافية')

    def test_user_create_post_success(self):
        """Superadmin successfully creates a user through the dedicated page."""
        self.client.login(username='super@wea.com', password='AdminPass123!')
        res = self.client.post('/users/create/', {
            'name': 'خالد محمد عبد الرحمن',
            'email': 'khaled.new@weapharma.com',
            'code': 'EMP-501',
            'mobile': '01099887766',
            'password': 'SecurePassword123!',
            'confirm_password': 'SecurePassword123!',
            'role': str(self.rep_role.id),
            'is_active': 'on',
            'assigned_areas': [str(self.nasr_city.id)]
        })
        new_user = User.objects.filter(email='khaled.new@weapharma.com').first()
        self.assertIsNotNone(new_user)
        self.assertEqual(res.status_code, 302)
        expected_url = reverse('user_detail', kwargs={'pk': new_user.pk})
        self.assertEqual(res.url, expected_url)
        self.assertEqual(new_user.name, 'خالد محمد عبد الرحمن')
        self.assertEqual(new_user.role, self.rep_role)
        self.assertTrue(new_user.check_password('SecurePassword123!'))
        self.assertTrue(new_user.assigned_areas.filter(id=self.nasr_city.id).exists())

        # Verify audit log
        log = SecurityAuditLog.objects.filter(target_user=new_user, action_type='USER_CREATED').first()
        self.assertIsNotNone(log)
        self.assertEqual(log.actor, self.superadmin)

    def test_user_create_validation_preserves_input(self):
        """Validation failures re-render user_create.html preserving entered values."""
        self.client.login(username='super@wea.com', password='AdminPass123!')
        res = self.client.post('/users/create/', {
            'name': 'محمد الخطأ',
            'email': 'not-matching@wea.com',
            'code': 'ERR-01',
            'mobile': '01122334455',
            'password': 'PasswordOne1!',
            'confirm_password': 'PasswordDifferent2!',
            'role': str(self.rep_role.id),
            'is_active': 'on',
        })
        self.assertEqual(res.status_code, 200)
        self.assertTemplateUsed(res, 'accounts/user_create.html')
        self.assertContains(res, 'محمد الخطأ')
        self.assertContains(res, 'not-matching@wea.com')
        self.assertFalse(User.objects.filter(email='not-matching@wea.com').exists())

    def test_user_create_accountant_forbidden(self):
        """Accountant is strictly forbidden from accessing user creation."""
        self.client.login(username='accountant@wea.com', password='AccPass123!')
        res = self.client.get('/users/create/')
        self.assertEqual(res.status_code, 403)

        res_post = self.client.post('/users/create/', {'name': 'Hack', 'email': 'hack@wea.com'})
        self.assertEqual(res_post.status_code, 403)

    def test_user_create_representative_forbidden(self):
        """Representative is strictly forbidden from creating users."""
        self.client.login(username='rep_cairo@wea.com', password='RepPass123!')
        res = self.client.get('/users/create/')
        self.assertEqual(res.status_code, 403)

    def test_user_create_manager_cannot_create_outside_region(self):
        """Manager cannot assign areas outside their regional jurisdiction."""
        self.client.login(username='manager_cairo@wea.com', password='ManagerPass123!')
        res = self.client.post('/users/create/', {
            'name': 'مندوب خارج النطاق',
            'email': 'alex_rep_by_cairo@wea.com',
            'password': 'SecurePassword123!',
            'confirm_password': 'SecurePassword123!',
            'role': str(self.rep_role.id),
            'assigned_areas': [str(self.alex_gov.id)]
        })
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'لا تمتلك الصلاحية لتعيين مناطق جغرافية خارج نطاق مسؤوليتك')
        self.assertFalse(User.objects.filter(email='alex_rep_by_cairo@wea.com').exists())

    # ==========================================
    # USER DETAIL PAGE TESTS
    # ==========================================

    def test_user_detail_page_get(self):
        """Dedicated user detail page shows profile, assigned areas, warehouses, vaults."""
        # Create warehouse and vault for rep
        wh = Warehouse.objects.create(name='مخزن عهدة مندوب القاهرة', code='WH-REP-CAI', assigned_user=self.cairo_rep)
        v = Vault.objects.create(name='خزنة عهدة مندوب القاهرة', serial_num=9901, assigned_user=self.cairo_rep)

        self.client.login(username='super@wea.com', password='AdminPass123!')
        res = self.client.get(f'/users/{self.cairo_rep.pk}/')
        self.assertEqual(res.status_code, 200)
        self.assertTemplateUsed(res, 'accounts/user_detail.html')
        self.assertContains(res, 'Cairo Rep')
        self.assertContains(res, 'مدينة نصر')
        self.assertContains(res, 'WH-REP-CAI')
        self.assertContains(res, 'خزنة عهدة مندوب القاهرة')

    def test_user_detail_manager_scoping(self):
        """Manager can view rep in their own area, but cannot view rep in another area."""
        self.client.login(username='manager_cairo@wea.com', password='ManagerPass123!')
        # In scope (Cairo Rep)
        res_cairo = self.client.get(f'/users/{self.cairo_rep.pk}/')
        self.assertEqual(res_cairo.status_code, 200)

        # Out of scope (Alex Rep)
        res_alex = self.client.get(f'/users/{self.alex_rep.pk}/')
        self.assertEqual(res_alex.status_code, 403)

    # ==========================================
    # USER EDIT PAGE TESTS
    # ==========================================

    def test_user_edit_preserves_password(self):
        """Editing user profile fields does not alter or erase the password."""
        self.client.login(username='super@wea.com', password='AdminPass123!')
        initial_hash = self.cairo_rep.password
        res = self.client.post(f'/users/{self.cairo_rep.pk}/edit/', {
            'name': 'Cairo Rep Updated',
            'email': 'rep_cairo@wea.com',
            'code': 'REP-NEW-99',
            'mobile': '01011122233',
            'role': str(self.rep_role.id),
            'is_active': 'on',
            'assigned_areas': [str(self.nasr_city.id)]
        })
        self.assertEqual(res.status_code, 302)
        self.cairo_rep.refresh_from_db()
        self.assertEqual(self.cairo_rep.name, 'Cairo Rep Updated')
        self.assertEqual(self.cairo_rep.code, 'REP-NEW-99')
        self.assertEqual(self.cairo_rep.password, initial_hash)
        self.assertTrue(self.cairo_rep.check_password('RepPass123!'))

    def test_user_password_reset_endpoint(self):
        """Isolated password reset changes password and logs audit without touching profile."""
        self.client.login(username='super@wea.com', password='AdminPass123!')
        res = self.client.post(f'/users/{self.cairo_rep.pk}/reset-password/', {
            'new_password': 'BrandNewPassword123!',
            'confirm_password': 'BrandNewPassword123!'
        })
        self.assertEqual(res.status_code, 302)
        self.cairo_rep.refresh_from_db()
        self.assertTrue(self.cairo_rep.check_password('BrandNewPassword123!'))

        log = SecurityAuditLog.objects.filter(target_user=self.cairo_rep, action_type='USER_PASSWORD_RESET').first()
        self.assertIsNotNone(log)

    def test_manager_cannot_edit_superadmin(self):
        """Area manager cannot edit superadmin account."""
        self.client.login(username='manager_cairo@wea.com', password='ManagerPass123!')
        res = self.client.get(f'/users/{self.superadmin.pk}/edit/')
        self.assertEqual(res.status_code, 403)

    # ==========================================
    # WAREHOUSE LOCATION TESTS
    # ==========================================

    def test_warehouse_location_persistence(self):
        """Warehouse coordinates (latitude, longitude) persist and update correctly."""
        wh = Warehouse.objects.create(
            name='مستودع رمسيس الرئيسي',
            code='WH-RAMSES-01',
            latitude=Decimal('30.0626000'),
            longitude=Decimal('31.2497000')
        )
        wh.refresh_from_db()
        self.assertTrue(wh.has_saved_location)
        self.assertEqual(float(wh.latitude), 30.0626)
        self.assertEqual(float(wh.longitude), 31.2497)

    # ==========================================
    # GEOCODING PROXY ENDPOINTS TESTS
    # ==========================================

    @patch('urllib.request.urlopen')
    def test_geocoding_search_api_proxy(self, mock_urlopen):
        """Backend geocoding search proxy forwards request with corporate User-Agent."""
        fake_response = BytesIO(json.dumps([
            {
                'display_name': 'Nasr City, Cairo, Egypt',
                'lat': '30.0561',
                'lon': '31.3301',
            }
        ]).encode('utf-8'))
        mock_urlopen.return_value.__enter__.return_value = fake_response

        self.client.login(username='super@wea.com', password='AdminPass123!')
        res = self.client.get('/api/geocoding/search/?q=Nasr City')
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn('results', data)
        self.assertEqual(len(data['results']), 1)
        self.assertEqual(data['results'][0]['display_name'], 'Nasr City, Cairo, Egypt')
        self.assertEqual(data['results'][0]['lat'], 30.0561)

    @patch('urllib.request.urlopen')
    def test_geocoding_reverse_api_proxy(self, mock_urlopen):
        """Backend reverse geocoding proxy resolves lat/lon to human readable address."""
        fake_response = BytesIO(json.dumps({
            'display_name': 'شارع مصطفى النحاس، مدينة نصر، القاهرة',
            'address': {'city': 'Cairo', 'road': 'Mostafa El-Nahas'}
        }).encode('utf-8'))
        mock_urlopen.return_value.__enter__.return_value = fake_response

        self.client.login(username='super@wea.com', password='AdminPass123!')
        res = self.client.get('/api/geocoding/reverse/?lat=30.0561&lon=31.3301')
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data['display_name'], 'شارع مصطفى النحاس، مدينة نصر، القاهرة')

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
