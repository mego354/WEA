import datetime
import json
from decimal import Decimal
from io import StringIO

from django.test import TestCase, Client, RequestFactory
from django.urls import reverse
from django.core.management import call_command
from django.core.paginator import Paginator
from django.core.signals import request_started, request_finished
from django.utils import timezone

from accounts.models import User, Role, SecurityAuditLog
from activities.models import ApprovalAuditLog, Visit
from catalog.models import Product, ProductCategory
from contacts.models import Contact
from inventory.models import Warehouse, InventoryStock
from purchases.models import PurchaseOrder
from purchases.services import PurchaseOrderService
from sales.models import SalesOrder, SalesReturnOrder, Collection, CustomerAccount
from treasury.models import Vault, VendorAccount
from master_data.models import (
    CompanyProfile, LocationSettings, Area, ExpenseType,
    TicketType, ApprovalRequestType, AgreementType,
    SalesSettings, PurchaseSettings, ContactFieldSetting,
    DataSyncConfig
)
from master_data.services import SettingsService, _thread_locals
from master_data.pagination_utils import paginate_queryset
from master_data.templatetags.erp_tags import url_replace, url_remove_param, smart_page_range


class SettingsModelsTests(TestCase):
    def test_company_profile_singleton(self):
        p1 = CompanyProfile.get_settings()
        p2 = CompanyProfile.get_settings()
        self.assertEqual(p1.pk, p2.pk)

    def test_location_settings_singleton(self):
        s1 = LocationSettings.get_settings()
        s2 = LocationSettings.get_settings()
        self.assertEqual(s1.pk, s2.pk)
        self.assertEqual(s1.tolerance, 300)

    def test_area_hierarchy(self):
        gov = Area.objects.create(name='الجيزة', code='GIZ', area_type='governorate')
        sub = Area.objects.create(name='الدقي', code='DOK', area_type='subarea', parent=gov)
        self.assertEqual(sub.parent, gov)
        self.assertIn(sub, gov.subareas.all())

    def test_sales_and_purchase_settings_singletons(self):
        sales = SalesSettings.get_settings()
        purchase = PurchaseSettings.get_settings()
        self.assertIsNotNone(sales.pk)
        self.assertIsNotNone(purchase.pk)
        self.assertTrue(sales.auto_invoice_on_dispatch)
        self.assertTrue(purchase.auto_invoice_on_dispatch)


class SettingsViewsTests(TestCase):
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
            role=self.admin_role
        )
        self.restricted_user = User.objects.create_user(
            username='staff@example.com',
            email='staff@example.com',
            password='StaffPassword123!',
            role=self.restricted_role
        )

    def test_unauthorized_user_blocked_from_settings(self):
        self.client.login(username='staff@example.com', password='StaffPassword123!')
        endpoints = [
            'branding_settings',
            'location_settings',
            'areas_settings',
            'expenses_settings',
            'tickets_settings',
            'requests_settings',
            'agreements_settings',
            'sales_settings',
            'purchase_settings',
            'inventory_settings',
            'sync_data',
        ]
        for ep in endpoints:
            response = self.client.get(reverse(ep))
            self.assertEqual(response.status_code, 403, f"Failed for endpoint {ep}")

    def test_admin_can_access_all_settings(self):
        self.client.login(username='admin@example.com', password='AdminPassword123!')
        endpoints = [
            ('branding_settings', 'settings/branding_settings.html'),
            ('location_settings', 'settings/location_settings.html'),
            ('areas_settings', 'settings/areas_settings.html'),
            ('expenses_settings', 'settings/expenses_settings.html'),
            ('tickets_settings', 'settings/tickets_settings.html'),
            ('requests_settings', 'settings/requests_settings.html'),
            ('agreements_settings', 'settings/agreements_settings.html'),
            ('sales_settings', 'settings/sales_settings.html'),
            ('purchase_settings', 'settings/purchase_settings.html'),
            ('inventory_settings', 'settings/inventory_settings.html'),
            ('sync_data', 'settings/sync_data.html'),
        ]
        for ep, tpl in endpoints:
            response = self.client.get(reverse(ep))
            self.assertEqual(response.status_code, 200, f"Failed status for {ep}")
            self.assertTemplateUsed(response, tpl, f"Failed template for {ep}")

    def test_branding_settings_update(self):
        self.client.login(username='admin@example.com', password='AdminPassword123!')
        data = {
            'company_name': 'شركة وي فارما المحدثة',
            'commercial_registry': '123456789',
            'tax_id': '987-654-321',
            'phone': '01012345678',
            'address': 'القاهرة، مصر',
            'email': 'info@weapharma.com',
        }
        response = self.client.post(reverse('branding_settings'), data)
        self.assertEqual(response.status_code, 302)
        profile = CompanyProfile.get_settings()
        self.assertEqual(profile.company_name, 'شركة وي فارما المحدثة')
        self.assertEqual(profile.commercial_registry, '123456789')

    def test_location_settings_update(self):
        self.client.login(username='admin@example.com', password='AdminPassword123!')
        data = {
            'tolerance': '500',
            'max_verified_accuracy': '80',
            'max_verified_warn_accuracy': '150',
            'auto_start_location_tracking_service': 'on',
            'auto_set_customer_location_in_visit': 'on',
            'verify_visits': '1',
            'verify_sales_orders': '0',
            'verify_sales_returns': '1',
        }
        response = self.client.post(reverse('location_settings'), data)
        self.assertEqual(response.status_code, 302)
        loc = LocationSettings.get_settings()
        self.assertEqual(loc.tolerance, 500)
        self.assertEqual(loc.max_verified_accuracy, 80)
        self.assertTrue(loc.auto_start_location_tracking_service)
        self.assertTrue(loc.verify_visits)
        self.assertFalse(loc.verify_sales_orders)

    def test_geofence_api(self):
        self.client.login(username='admin@example.com', password='AdminPassword123!')
        response = self.client.get(reverse('geofence_settings_api'))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('settings', data)
        self.assertIn('tolerance', data['settings'])

    def test_area_crud_and_deletion_safeguard(self):
        self.client.login(username='admin@example.com', password='AdminPassword123!')
        # 1. Create Governorate
        response = self.client.post(reverse('area_create'), {'name': 'الإسكندرية', 'code': 'ALX'})
        self.assertEqual(response.status_code, 302)
        gov = Area.objects.get(code='ALX')

        # 2. Create Subarea
        response = self.client.post(reverse('area_create'), {'name': 'سموحة', 'code': 'SMH', 'parent': gov.pk})
        self.assertEqual(response.status_code, 302)
        sub = Area.objects.get(code='SMH')
        self.assertEqual(sub.parent, gov)

        # 3. Cannot delete governorate with subareas
        response = self.client.post(reverse('area_delete', args=[gov.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Area.objects.filter(pk=gov.pk).exists())

        # 4. Delete subarea then governorate
        self.client.post(reverse('area_delete', args=[sub.pk]))
        self.assertFalse(Area.objects.filter(pk=sub.pk).exists())
        self.client.post(reverse('area_delete', args=[gov.pk]))
        self.assertFalse(Area.objects.filter(pk=gov.pk).exists())

    def test_expenses_crud(self):
        self.client.login(username='admin@example.com', password='AdminPassword123!')
        # Create
        data = {'name': 'فواتير هاتف', 'name_en': 'Phone bills', 'category': 'general', 'unit': 'فاتورة'}
        response = self.client.post(reverse('expense_create'), data)
        self.assertEqual(response.status_code, 302)
        exp = ExpenseType.objects.get(name='فواتير هاتف')
        self.assertEqual(exp.category, 'general')

        # Edit
        response = self.client.post(reverse('expense_edit', args=[exp.pk]), {
            'name': 'فواتير هاتف ومحمول',
            'name_en': 'Phone and mobile bills',
            'unit': 'فاتورة'
        })
        self.assertEqual(response.status_code, 302)
        exp.refresh_from_db()
        self.assertEqual(exp.name, 'فواتير هاتف ومحمول')

        # Delete
        response = self.client.post(reverse('expense_delete', args=[exp.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(ExpenseType.objects.filter(pk=exp.pk).exists())

    def test_ticket_types_and_default_safeguard(self):
        self.client.login(username='admin@example.com', password='AdminPassword123!')
        default_ticket = TicketType.objects.create(name='مهمة عامة', is_default=True)
        custom_ticket = TicketType.objects.create(name='صيانة أجهزة', is_default=False)

        # Cannot delete default
        self.client.post(reverse('ticket_delete', args=[default_ticket.pk]))
        self.assertTrue(TicketType.objects.filter(pk=default_ticket.pk).exists())

        # Can delete custom
        self.client.post(reverse('ticket_delete', args=[custom_ticket.pk]))
        self.assertFalse(TicketType.objects.filter(pk=custom_ticket.pk).exists())

    def test_requests_types_and_default_safeguard(self):
        self.client.login(username='admin@example.com', password='AdminPassword123!')
        default_req = ApprovalRequestType.objects.create(name='طلب إجازة', is_default=True)
        custom_req = ApprovalRequestType.objects.create(name='طلب سلفة مؤقتة', is_default=False)

        # Cannot delete default
        self.client.post(reverse('request_type_delete', args=[default_req.pk]))
        self.assertTrue(ApprovalRequestType.objects.filter(pk=default_req.pk).exists())

        # Can delete custom
        self.client.post(reverse('request_type_delete', args=[custom_req.pk]))
        self.assertFalse(ApprovalRequestType.objects.filter(pk=custom_req.pk).exists())

    def test_agreements_crud(self):
        self.client.login(username='admin@example.com', password='AdminPassword123!')
        response = self.client.post(reverse('agreement_type_create'), {'name': 'اتفاقية بونص سنوي'})
        self.assertEqual(response.status_code, 302)
        agr = AgreementType.objects.get(name='اتفاقية بونص سنوي')

        self.client.post(reverse('agreement_type_edit', args=[agr.pk]), {'name': 'اتفاقية بونص نصف سنوي'})
        agr.refresh_from_db()
        self.assertEqual(agr.name, 'اتفاقية بونص نصف سنوي')

        self.client.post(reverse('agreement_type_delete', args=[agr.pk]))
        self.assertFalse(AgreementType.objects.filter(pk=agr.pk).exists())

    def test_sales_and_purchase_settings_update(self):
        self.client.login(username='admin@example.com', password='AdminPassword123!')
        # Sales
        response = self.client.post(reverse('sales_settings'), {
            'require_verification_manager': 'on',
            'auto_invoice_on_dispatch': 'on',
            'tax_mode': 'mandatory',
            'default_packaging_unit': 'strip',
        })
        self.assertEqual(response.status_code, 302)
        sales = SalesSettings.get_settings()
        self.assertTrue(sales.require_verification_manager)
        self.assertEqual(sales.tax_mode, 'mandatory')
        self.assertEqual(sales.default_packaging_unit, 'strip')

        # Purchase
        response = self.client.post(reverse('purchase_settings'), {
            'auto_invoice_on_dispatch': 'on',
            'auto_close_cash_payment': 'on',
            'tax_mode': 'exempt',
            'default_packaging_unit': 'carton',
        })
        self.assertEqual(response.status_code, 302)
        purch = PurchaseSettings.get_settings()
        self.assertEqual(purch.tax_mode, 'exempt')
        self.assertEqual(purch.default_packaging_unit, 'carton')

    def test_inventory_settings_update(self):
        self.client.login(username='admin@example.com', password='AdminPassword123!')
        response = self.client.post(reverse('inventory_settings'), {
            'use_expiry_date': 'on',
            'is_expiry_mandatory': 'on',
            'use_batch_number': 'on',
            'is_batch_mandatory': 'on',
        })
        self.assertEqual(response.status_code, 302)
        prof = CompanyProfile.get_settings()
        self.assertTrue(prof.use_expiry_date)
        self.assertTrue(prof.is_expiry_mandatory)
        self.assertTrue(prof.use_batch_number)
        self.assertTrue(prof.is_batch_mandatory)

    def test_contacts_udf_url_not_found(self):
        """Verify that /settings/contacts-udf/ has been removed and returns HTTP 404."""
        self.client.login(username='admin@example.com', password='AdminPassword123!')
        response = self.client.get('/settings/contacts-udf/')
        self.assertEqual(response.status_code, 404)

    def test_sync_data_views(self):
        self.client.login(username='admin@example.com', password='AdminPassword123!')
        cfg = DataSyncConfig.objects.create(
            sync_type='contacts',
            title='إستيراد جهات الاتصال',
            google_sheet_url='https://docs.google.com/spreadsheets/d/test1'
        )
        # Update URL
        response = self.client.post(reverse('sync_data'), {
            'sync_type': 'contacts',
            'google_sheet_url': 'https://docs.google.com/spreadsheets/d/test2'
        })
        self.assertEqual(response.status_code, 302)
        cfg.refresh_from_db()
        self.assertEqual(cfg.google_sheet_url, 'https://docs.google.com/spreadsheets/d/test2')

        # Trigger sync
        response = self.client.get(reverse('sync_data_trigger', args=['contacts']))
        self.assertEqual(response.status_code, 302)
        cfg.refresh_from_db()
        self.assertEqual(cfg.status, 'success')
        self.assertIsNotNone(cfg.last_synced_at)


class SettingsServiceAndCacheTests(TestCase):
    """Verifies SettingsService request-bound caching, cache invalidation on save, and dashboard purchase calculations."""

    def setUp(self):
        self.client = Client()
        self.superadmin_role, _ = Role.objects.get_or_create(
            name=Role.ROLE_SUPERADMIN,
            defaults={'display_name': 'مدير النظام الأعلى', 'is_super': True, 'is_system': True, 'is_active': True}
        )
        self.accountant_role, _ = Role.objects.get_or_create(
            name=Role.ROLE_ACCOUNTANT,
            defaults={'display_name': 'محاسب', 'is_accountant': True}
        )
        self.superadmin_user = User.objects.create_superuser(
            username='super_settings_svc',
            email='super_settings@wea.com',
            password='Password123!',
            role=self.superadmin_role
        )
        self.accountant_user = User.objects.create_user(
            username='acct_settings_svc',
            email='acct_settings@wea.com',
            password='Password123!',
            role=self.accountant_role
        )

        self.main_warehouse = Warehouse.objects.create(name='مخزن القاهرة المركزي', code='WH-SETT-MAIN', is_main=True)
        self.supplier = Contact.objects.create(name='المورد الرئيسي للتجارب', is_supplier=True, mobile='01022334455')
        VendorAccount.get_or_create_for_supplier(self.supplier)

        self.category = ProductCategory.objects.create(name='أدوية عامة', code='CAT-SETT')
        self.product = Product.objects.create(
            name='فيتامين سي 1000',
            sku_code='VIT-C-1000',
            retail_price=Decimal('50.00'),
            default_purchase_cost=Decimal('40.00'),
            category=self.category
        )

    def test_settings_service_request_lifecycle_and_invalidation(self):
        """SettingsService must not retain stale cache across test transactions or outside requests."""
        p1 = SettingsService.get_company_profile()
        self.assertFalse(getattr(_thread_locals, 'in_request', False))

        request_started.send(sender=self.__class__)
        self.assertTrue(getattr(_thread_locals, 'in_request', False))

        p2 = SettingsService.get_company_profile()
        self.assertIn('company_profile', SettingsService._get_cache())

        p2.company_name = "New Company Name Test"
        p2.save()
        self.assertNotIn('company_profile', getattr(_thread_locals, 'settings_cache', {}))

        request_finished.send(sender=self.__class__)
        self.assertFalse(getattr(_thread_locals, 'in_request', False))

    def test_dashboard_purchase_statistics_calculation(self):
        """Dashboard home_view computes accurate purchase and financial metrics matching DB state."""
        po = PurchaseOrderService.create_order(
            supplier=self.supplier,
            target_warehouse=self.main_warehouse,
            order_date=timezone.now().date(),
            items_data=[{'product': self.product, 'quantity': 25, 'unit_price': Decimal("40.00")}],
            user=self.accountant_user,
            due_date=datetime.date(2026, 10, 25)
        )
        PurchaseOrderService.approve_order(po, self.superadmin_user)

        self.client.force_login(self.superadmin_user)
        resp = self.client.get(reverse('home'), {'period': 'all'})
        self.assertEqual(resp.status_code, 200)

        content = resp.content.decode('utf-8')
        self.assertIn("أوامر الشراء", content)
        self.assertIn("المدفوع للموردين", content)
        self.assertIn("أحدث أوامر الشراء", content)
        self.assertIn(f"{po.order_number}", content)


class AdminDashboardAndModulesTestCase(TestCase):
    """Verifies executive admin dashboard rendering, changelists, audit immutability, and password management."""

    def setUp(self):
        self.client = Client()
        self.admin_user = User.objects.create_superuser(
            username='admin_test',
            email='admin@test.com',
            password='Password123!',
            first_name='Admin',
            last_name='User'
        )
        self.client.force_login(self.admin_user)

    def test_admin_index_dashboard_renders(self):
        url = reverse('admin:index')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "لوحة التحكم والإدارة المركزية")
        self.assertContains(response, "الزيارات الميدانية")
        self.assertContains(response, "أوامر المبيعات")
        self.assertContains(response, "أوامر المشتريات والتوريد")
        self.assertContains(response, "العمليات والاختصارات السريعة")

    def test_admin_changelists_render(self):
        changelist_urls = [
            'admin:accounts_user_changelist',
            'admin:accounts_role_changelist',
            'admin:accounts_securityauditlog_changelist',
            'admin:activities_visit_changelist',
            'admin:activities_visittemplate_changelist',
            'admin:activities_plannedvisitday_changelist',
            'admin:activities_approvalauditlog_changelist',
            'admin:contacts_contact_changelist',
            'admin:catalog_product_changelist',
            'admin:inventory_warehouse_changelist',
            'admin:purchases_purchaseorder_changelist',
            'admin:sales_salesorder_changelist',
            'admin:treasury_vault_changelist',
            'admin:master_data_locationsettings_changelist',
        ]
        for url_name in changelist_urls:
            with self.subTest(url=url_name):
                url = reverse(url_name)
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)

    def test_audit_logs_immutability(self):
        security_add_url = reverse('admin:accounts_securityauditlog_add')
        res_sec = self.client.get(security_add_url)
        self.assertEqual(res_sec.status_code, 403)

        approval_add_url = reverse('admin:activities_approvalauditlog_add')
        res_app = self.client.get(approval_add_url)
        self.assertEqual(res_app.status_code, 403)

    def test_user_password_update_in_change_form(self):
        target_user = User.objects.create_user(
            username='rep_user',
            name='Rep User',
            email='rep@test.com',
            password='OldPassword123!'
        )
        url = reverse('admin:accounts_user_change', args=[target_user.id])
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "new_password")
        self.assertContains(res, "confirm_new_password")

        post_data = {
            'username': target_user.username,
            'name': target_user.name,
            'email': target_user.email,
            'locale': 'ar',
            'new_password': 'BrandNewPassword999!',
            'confirm_new_password': 'BrandNewPassword999!',
        }
        post_res = self.client.post(url, post_data)
        self.assertEqual(post_res.status_code, 302)

        target_user.refresh_from_db()
        self.assertTrue(target_user.check_password('BrandNewPassword999!'))
        self.assertFalse(target_user.check_password('OldPassword123!'))

    def test_admin_bulk_reset_password_to_wea4444(self):
        user1 = User.objects.create_user(username='u1', name='User 1', email='u1@test.com', password='InitialPassword1!')
        user2 = User.objects.create_user(username='u2', name='User 2', email='u2@test.com', password='InitialPassword2!')

        changelist_url = reverse('admin:accounts_user_changelist')
        post_data = {
            'action': 'reset_password_to_wea4444',
            '_selected_action': [str(user1.id), str(user2.id)],
        }
        response = self.client.post(changelist_url, post_data, follow=True)
        self.assertEqual(response.status_code, 200)

        user1.refresh_from_db()
        user2.refresh_from_db()
        self.assertTrue(user1.check_password('Wea@4444'))
        self.assertTrue(user2.check_password('Wea@4444'))

        audit_logs = SecurityAuditLog.objects.filter(action_type='USER_PASSWORD_RESET', target_user__in=[user1, user2])
        self.assertEqual(audit_logs.count(), 2)

    def test_user_password_change_view(self):
        target_user = User.objects.create_user(
            username='target_subpage',
            name='Target Subpage',
            email='subpage@test.com',
            password='InitialPassword1!'
        )
        url = reverse('admin:auth_user_password_change', args=[target_user.id])
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)

        post_data = {
            'password1': 'DedicatedNewPass123!',
            'password2': 'DedicatedNewPass123!',
        }
        post_res = self.client.post(url, post_data)
        self.assertEqual(post_res.status_code, 302)

        target_user.refresh_from_db()
        self.assertTrue(target_user.check_password('DedicatedNewPass123!'))


class DashboardRolePermissionsAndMobileNavTests(TestCase):
    """Verifies mobile responsiveness, role-based metrics visibility, chart privacy, and manager rep selection."""

    def setUp(self):
        self.client = Client()

        self.super_role, _ = Role.objects.get_or_create(
            name='SuperAdmin',
            defaults={'display_name': 'مدير النظام الأعلى', 'is_super': True, 'is_active': True}
        )
        self.mgr_role, _ = Role.objects.get_or_create(
            name='AreaManager',
            defaults={'display_name': 'مدير منطقة', 'is_area_manager': True, 'is_active': True}
        )
        self.rep_role, _ = Role.objects.get_or_create(
            name='SalesRep',
            defaults={'display_name': 'مندوب مبيعات', 'is_rep': True, 'is_active': True}
        )
        self.acct_role, _ = Role.objects.get_or_create(
            name='Accountant',
            defaults={'display_name': 'محاسب مالي', 'is_active': True}
        )

        self.cairo_main = Area.objects.create(name='القاهرة (رئيسية)', code='CAI-MAIN')
        self.cairo_sub = Area.objects.create(name='المعادي', code='CAI-MAA', parent=self.cairo_main)
        self.alex_main = Area.objects.create(name='الإسكندرية (رئيسية)', code='ALX-MAIN')
        self.alex_sub = Area.objects.create(name='سموحة', code='ALX-SMH', parent=self.alex_main)

        self.superadmin = User.objects.create_user(
            username='super_boss',
            password='Password123!',
            name='Super Administrator Extremely Long Name Test For Ellipsis Handling',
            role=self.super_role,
            is_superuser=True
        )

        self.cairo_manager = User.objects.create_user(
            username='cairo_mgr',
            password='Password123!',
            name='أحمد مدير منطقة القاهرة',
            role=self.mgr_role
        )
        self.cairo_manager.assigned_areas.add(self.cairo_main)

        self.cairo_rep = User.objects.create_user(
            username='cairo_rep',
            password='Password123!',
            name='محمود مندوب القاهرة',
            role=self.rep_role
        )
        self.cairo_rep.assigned_areas.add(self.cairo_sub)

        self.alex_rep = User.objects.create_user(
            username='alex_rep',
            password='Password123!',
            name='طارق مندوب الإسكندرية',
            role=self.rep_role
        )
        self.alex_rep.assigned_areas.add(self.alex_sub)

        self.accountant = User.objects.create_user(
            username='acct_user',
            password='Password123!',
            name='محاسب الحسابات والمالية',
            role=self.acct_role
        )

        self.cat = ProductCategory.objects.create(name='أدوية عامة', code='CAT-GEN')
        self.prod = Product.objects.create(
            category=self.cat,
            name='منتج تجريبي 1',
            sku_code='PRD-001',
            retail_price=Decimal('100.00'),
            default_purchase_cost=Decimal('70.00')
        )

        self.cairo_wh = Warehouse.objects.create(
            name='مخزن عهدة مندوب المعادي',
            code='WH-REP-CAI',
            assigned_user=self.cairo_rep,
            is_rep_warehouse=True,
            area=self.cairo_sub
        )
        self.alex_wh = Warehouse.objects.create(
            name='مخزن عهدة مندوب سموحة',
            code='WH-REP-ALX',
            assigned_user=self.alex_rep,
            is_rep_warehouse=True,
            area=self.alex_sub
        )
        InventoryStock.objects.create(
            warehouse=self.cairo_wh,
            product=self.prod,
            qty_on_hand=Decimal('45.00')
        )

        self.cairo_vault = Vault.objects.create(
            serial_num=5001,
            name='عهدة نقدية مندوب المعادي',
            assigned_user=self.cairo_rep,
            is_rep_vault=True,
            current_balance=Decimal('1500.00')
        )

        self.cairo_cust = Contact.objects.create(
            name='عميل القاهرة للتجارة',
            is_customer=True,
            area=self.cairo_sub,
            created_by=self.cairo_rep
        )
        self.cairo_cust_account, _ = CustomerAccount.objects.get_or_create(customer=self.cairo_cust)
        self.cairo_cust_account.current_balance = Decimal('5000.00')
        self.cairo_cust_account.overdue_balance = Decimal('1200.00')
        self.cairo_cust_account.credit_period_days = 30
        self.cairo_cust_account.save()

        self.cairo_so = SalesOrder.objects.create(
            order_number='SO-CAI-001',
            customer=self.cairo_cust,
            created_by=self.cairo_rep,
            source_warehouse=self.cairo_wh,
            status='delivered',
            grand_total=Decimal('3500.00'),
            order_date=timezone.now().date()
        )
        self.cairo_col = Collection.objects.create(
            customer=self.cairo_cust,
            vault=self.cairo_vault,
            created_by=self.cairo_rep,
            amount=Decimal('2000.00'),
            payment_method='cash',
            collection_date=timezone.now().date()
        )
        self.cairo_visit = Visit.objects.create(
            contact=self.cairo_cust,
            owner=self.cairo_rep,
            created_by=self.cairo_rep,
            status='finished',
            date=timezone.now().date()
        )

        self.alex_cust = Contact.objects.create(
            name='عميل الإسكندرية الدولي',
            is_customer=True,
            area=self.alex_sub,
            created_by=self.alex_rep
        )
        self.alex_so = SalesOrder.objects.create(
            order_number='SO-ALX-001',
            customer=self.alex_cust,
            created_by=self.alex_rep,
            source_warehouse=self.alex_wh,
            status='delivered',
            grand_total=Decimal('9000.00'),
            order_date=timezone.now().date()
        )

    def test_mobile_bottom_nav_has_no_redundant_menu_toggle(self):
        self.client.force_login(self.superadmin)
        response = self.client.get('/home/')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        self.assertIn('id="mobileMenuToggle"', content)
        self.assertNotIn('id="mobileBottomMenuToggle"', content)
        self.assertNotIn('openMobileNavDrawer', content)

    def test_long_user_name_rendered_with_truncation_and_title(self):
        self.client.force_login(self.superadmin)
        response = self.client.get('/home/')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        self.assertIn('text-sm font-bold text-slate-900 truncate', content)
        self.assertIn('title="Super Administrator Extremely Long Name Test For Ellipsis Handling', content)

    def test_superadmin_dashboard_sees_system_wide_metrics_and_all_charts(self):
        self.client.force_login(self.superadmin)
        response = self.client.get('/home/?period=all')
        self.assertEqual(response.status_code, 200)

        context = response.context
        self.assertTrue(context['is_super'])
        self.assertEqual(len(context['kpi_cards']), 14)

        charts_data = json.loads(context['charts_json'])
        self.assertIn('collections_by_area', charts_data)
        self.assertIn('visits_by_area', charts_data)
        self.assertIn('orders_created_by_area', charts_data)
        self.assertIn('orders_delivered_by_area', charts_data)
        self.assertIn('reps_balance', charts_data)
        self.assertIn('reps_overdue', charts_data)
        self.assertGreater(len(context['eligible_reps']), 0)

    def test_accountant_dashboard_financial_only_and_no_visits(self):
        self.client.force_login(self.accountant)
        response = self.client.get('/home/?period=all')
        self.assertEqual(response.status_code, 200)

        context = response.context
        self.assertTrue(context['is_acct'])
        self.assertFalse(context['is_super'])

        card_ids = [c['id'] for c in context['kpi_cards']]
        self.assertIn('pos_created_stats', card_ids)
        self.assertIn('net_sales_stats', card_ids)
        self.assertIn('collections_collected_stats', card_ids)
        self.assertIn('vaults_total_stats', card_ids)
        self.assertIn('vendors_total_stats', card_ids)

        self.assertNotIn('visits_created_lead_stats', card_ids)
        self.assertNotIn('visits_created_customer_stats', card_ids)

        charts_data = json.loads(context['charts_json'])
        self.assertNotIn('visits_by_area', charts_data)
        self.assertNotIn('visits_by_area', context['available_charts'])
        self.assertEqual(len(context['eligible_reps']), 0)

    def test_representative_sees_only_own_metrics_and_no_cross_rep_charts(self):
        self.client.force_login(self.cairo_rep)
        response = self.client.get('/home/?period=all')
        self.assertEqual(response.status_code, 200)

        context = response.context
        self.assertTrue(context['is_rep'])
        self.assertFalse(context['is_mgr'])

        card_ids = [c['id'] for c in context['kpi_cards']]
        self.assertIn('rep_vault_stats', card_ids)
        self.assertIn('rep_stock_stats', card_ids)
        self.assertIn('visits_created_lead_stats', card_ids)

        charts_data = json.loads(context['charts_json'])
        self.assertNotIn('reps_balance', charts_data)
        self.assertNotIn('reps_overdue', charts_data)
        self.assertNotIn('reps_balance', context['available_charts'])
        self.assertNotIn('reps_overdue', context['available_charts'])
        self.assertEqual(len(context['eligible_reps']), 0)

    def test_manager_sees_team_scope_in_their_main_area(self):
        self.client.force_login(self.cairo_manager)
        response = self.client.get('/home/?period=all')
        self.assertEqual(response.status_code, 200)

        context = response.context
        self.assertTrue(context['is_mgr'])
        self.assertIsNone(context['selected_rep'])

        eligible_ids = [r.id for r in context['eligible_reps']]
        self.assertIn(self.cairo_rep.id, eligible_ids)
        self.assertNotIn(self.alex_rep.id, eligible_ids)

    def test_manager_can_select_eligible_representative(self):
        self.client.force_login(self.cairo_manager)
        response = self.client.get(f'/home/?period=all&rep_id={self.cairo_rep.id}')
        self.assertEqual(response.status_code, 200)

        context = response.context
        self.assertIsNotNone(context['selected_rep'])
        self.assertEqual(context['selected_rep'].id, self.cairo_rep.id)

        content = response.content.decode('utf-8')
        self.assertIn('يتم الآن استعراض إحصائيات المندوب', content)
        self.assertIn(self.cairo_rep.name, content)
        self.assertIn('العودة لإحصائيات الفريق كامل', content)

    def test_manager_cannot_select_unauthorized_cross_area_representative(self):
        self.client.force_login(self.cairo_manager)
        response = self.client.get(f'/home/?period=all&rep_id={self.alex_rep.id}')
        self.assertEqual(response.status_code, 200)

        context = response.context
        self.assertIsNone(context['selected_rep'])

        content = response.content.decode('utf-8')
        self.assertNotIn(f'استعراض إحصائيات المندوب: {self.alex_rep.name}', content)

    def test_tables_contain_data_col_and_column_picker_components(self):
        self.client.force_login(self.superadmin)
        urls_to_test = [
            '/contacts/',
            '/sales/',
            '/sales/collections/',
            '/inventory/',
            '/inventory/transfers/',
            '/purchases/',
            '/visits/',
            '/treasury/vaults/',
            '/users/',
            '/products/',
            '/agreements/',
        ]
        for url in urls_to_test:
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200, f"Failed on URL {url}")
            content = resp.content.decode('utf-8')
            self.assertIn('data-col-table=', content, f"Missing data-col-table in {url}")
            self.assertIn('data-col=', content, f"Missing data-col in {url}")
            self.assertIn('TableColumnManager', content, f"Missing TableColumnManager in {url}")


class EgyptAreasTests(TestCase):
    """Verifies geographic setup command, 27 governorates count, company area exclusion, and subarea count annotations."""

    def setUp(self):
        self.client = Client()
        self.superadmin_role, _ = Role.objects.get_or_create(
            name=Role.ROLE_SUPERADMIN,
            defaults={'display_name': 'مدير النظام الأعلى', 'is_super': True, 'is_system': True, 'is_active': True}
        )
        self.admin_user = User.objects.create_superuser(
            username='admin_areas@wea.com',
            email='admin_areas@wea.com',
            password='Password123!',
            name='Admin Areas',
            role=self.superadmin_role
        )

        out = StringIO()
        call_command('setup_egypt_areas', stdout=out)

    def test_27_egyptian_governorates_exist(self):
        govs = Area.objects.filter(parent__isnull=True, is_company_area=False)
        self.assertEqual(govs.count(), 27)

        gov_names = set(govs.values_list('name', flat=True))
        expected_sample = {'محافظة القاهرة', 'محافظة الجيزة', 'محافظة الإسكندرية', 'محافظة اسوان', 'محافظة الأقصر', 'محافظة بورسعيد', 'محافظة مطروح', 'محافظة شمال سيناء'}
        for expected in expected_sample:
            self.assertIn(expected, gov_names)

    def test_company_areas_excluded_from_settings(self):
        company_branch = Area.objects.create(
            name='WEA Main Warehouse HQ',
            code='WEA-HQ',
            is_company_area=True
        )

        self.client.login(username='admin_areas@wea.com', password='Password123!')
        res = self.client.get(reverse('areas_settings'))
        self.assertEqual(res.status_code, 200)

        govs_in_context = res.context['governorates']
        gov_ids_in_context = [a.id for a in govs_in_context]
        self.assertNotIn(company_branch.id, gov_ids_in_context)
        self.assertEqual(len(govs_in_context), 27)

    def test_subarea_count_aggregation(self):
        cairo = Area.objects.filter(name='محافظة القاهرة', parent__isnull=True).first()
        self.assertIsNotNone(cairo)

        Area.objects.create(name='مدينة نصر', code='CAI-01-NASR', parent=cairo, area_type='subarea')
        Area.objects.create(name='المعادي', code='CAI-01-MAADI', parent=cairo, area_type='subarea')

        self.client.login(username='admin_areas@wea.com', password='Password123!')
        res = self.client.get(reverse('areas_settings'))
        self.assertEqual(res.status_code, 200)

        cairo_in_ctx = next(a for a in res.context['governorates'] if a.id == cairo.id)
        self.assertEqual(cairo_in_ctx.subareas_count, 2)


class PaginationUtilsTests(TestCase):
    """Verifies queryset pagination, page sizes, bounds checking, and fallbacks."""

    def setUp(self):
        self.factory = RequestFactory()
        self.sample_list = list(range(1, 151))

    def test_default_pagination(self):
        request = self.factory.get('/some-list/')
        paginator, page_obj = paginate_queryset(request, self.sample_list, default_per_page=25)
        self.assertEqual(paginator.per_page, 25)
        self.assertEqual(paginator.count, 150)
        self.assertEqual(paginator.num_pages, 6)
        self.assertEqual(page_obj.number, 1)
        self.assertEqual(len(page_obj.object_list), 25)

    def test_custom_per_page_selection(self):
        request = self.factory.get('/some-list/?per_page=50')
        paginator, page_obj = paginate_queryset(request, self.sample_list, default_per_page=25)
        self.assertEqual(paginator.per_page, 50)
        self.assertEqual(paginator.num_pages, 3)

    def test_per_page_safety_cap(self):
        request = self.factory.get('/some-list/?per_page=5000')
        paginator, page_obj = paginate_queryset(request, self.sample_list, default_per_page=25, max_per_page=100)
        self.assertEqual(paginator.per_page, 100)

    def test_invalid_per_page_fallback(self):
        request = self.factory.get('/some-list/?per_page=invalid_string')
        paginator, page_obj = paginate_queryset(request, self.sample_list, default_per_page=25)
        self.assertEqual(paginator.per_page, 25)

    def test_negative_per_page_fallback(self):
        request = self.factory.get('/some-list/?per_page=-10')
        paginator, page_obj = paginate_queryset(request, self.sample_list, default_per_page=25)
        self.assertEqual(paginator.per_page, 25)

    def test_out_of_range_page_fallback_to_last(self):
        request = self.factory.get('/some-list/?page=999')
        paginator, page_obj = paginate_queryset(request, self.sample_list, default_per_page=25)
        self.assertEqual(page_obj.number, 6)

    def test_invalid_page_fallback_to_first(self):
        request = self.factory.get('/some-list/?page=abc')
        paginator, page_obj = paginate_queryset(request, self.sample_list, default_per_page=25)
        self.assertEqual(page_obj.number, 1)

    def test_empty_dataset_pagination(self):
        request = self.factory.get('/some-list/')
        paginator, page_obj = paginate_queryset(request, [], default_per_page=25)
        self.assertEqual(paginator.count, 0)
        self.assertEqual(paginator.num_pages, 1)
        self.assertEqual(page_obj.number, 1)


class UrlReplaceAndFilterTagsTests(TestCase):
    """Verifies ERP template tags for URL manipulation, query preservation, and pagination range."""

    def setUp(self):
        self.factory = RequestFactory()

    def test_url_replace_preserves_existing_params(self):
        request = self.factory.get('/products/?search=panadol&category=2&page=1')
        context = {'request': request}
        result = url_replace(context, page=2)
        self.assertIn('page=2', result)
        self.assertIn('search=panadol', result)
        self.assertIn('category=2', result)

    def test_url_replace_removes_none_and_empty(self):
        request = self.factory.get('/products/?search=panadol&status=active&page=2')
        context = {'request': request}
        result = url_replace(context, status=None, page=1)
        self.assertNotIn('status=', result)
        self.assertIn('page=1', result)
        self.assertIn('search=panadol', result)

    def test_url_remove_param_dynamic(self):
        request = self.factory.get('/sales/orders/?status=pending&date_from=2026-01-01&page=3')
        context = {'request': request}
        result = url_remove_param(context, 'status', page=1)
        self.assertNotIn('status=', result)
        self.assertIn('page=1', result)
        self.assertIn('date_from=2026-01-01', result)

    def test_smart_page_range_few_pages(self):
        paginator = Paginator(list(range(50)), 10)
        pages = smart_page_range(paginator, current_page=2)
        self.assertEqual(pages, [1, 2, 3, 4, 5])

    def test_smart_page_range_with_ellipsis(self):
        paginator = Paginator(list(range(300)), 15)
        pages = smart_page_range(paginator, current_page=10, on_each_side=2, on_ends=1)
        self.assertEqual(pages[0], 1)
        self.assertEqual(pages[-1], 20)
        self.assertIn('...', pages)


class WeaMigrationCommandTests(TestCase):
    """
    Automated regression and validation tests for the WEA enterprise migration command.
    """

    def test_migration_dry_run_execution(self):
        """Verifies that execute_wea_migration runs in dry-run mode without modifying the database."""
        out = StringIO()
        call_command('execute_wea_migration', '--phase=all', '--dry-run', stdout=out)
        output = out.getvalue()
        self.assertIn('WEA PHARMA ERP — ENTERPRISE DATA MIGRATION ENGINE', output)
        self.assertIn('[DRY-RUN]', output)
        self.assertIn('MIGRATION COMMAND COMPLETED SUCCESSFULLY!', output)

    def test_migration_command_phase_filtering(self):
        """Verifies that phase ranges like 1-3 can be scheduled."""
        from master_data.management.commands.execute_wea_migration import Command
        cmd = Command()
        self.assertEqual(cmd.get_phases('all'), [0, 1, 2, 3, 4, 6, 7, 8, 10, 12, 13, 14, 15])
        self.assertEqual(cmd.get_phases('1-3'), [1, 2, 3])
        self.assertEqual(cmd.get_phases('4,6,7'), [4, 6, 7])
        self.assertEqual(cmd.get_phases('15'), [15])

    def test_parse_dec_helper(self):
        """Verifies safe decimal parsing handles NaN, commas, None, and strings gracefully."""
        import numpy as np
        from master_data.management.commands.execute_wea_migration import parse_dec
        self.assertEqual(parse_dec(None), Decimal('0.00'))
        self.assertEqual(parse_dec(np.nan), Decimal('0.00'))
        self.assertEqual(parse_dec('nan'), Decimal('0.00'))
        self.assertEqual(parse_dec(''), Decimal('0.00'))
        self.assertEqual(parse_dec('1,234.50'), Decimal('1234.50'))
        self.assertEqual(parse_dec(100.25), Decimal('100.25'))


