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
        from activities.models import AgreementType as ActivitiesAgreementType
        self.client.login(username='admin@example.com', password='AdminPassword123!')
        response = self.client.post(reverse('agreement_type_create'), {'name': 'اتفاقية بونص سنوي'})
        self.assertEqual(response.status_code, 302)
        agr = ActivitiesAgreementType.objects.get(name='اتفاقية بونص سنوي')

        self.client.post(reverse('agreement_type_edit', args=[agr.pk]), {'name': 'اتفاقية بونص نصف سنوي'})
        agr.refresh_from_db()
        self.assertEqual(agr.name, 'اتفاقية بونص نصف سنوي')

        self.client.post(reverse('agreement_type_delete', args=[agr.pk]))
        self.assertFalse(ActivitiesAgreementType.objects.filter(pk=agr.pk).exists())

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

    def test_sync_data_url_removed(self):
        """Verify that obsolete /settings/sync-data/ endpoints have been removed and return HTTP 404."""
        self.client.login(username='admin@example.com', password='AdminPassword123!')
        self.assertEqual(self.client.get('/settings/sync-data/').status_code, 404)
        self.assertEqual(self.client.get('/settings/sync-data/contacts/sync/').status_code, 404)


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

        self.super_role = Role.objects.get(name=Role.ROLE_SUPERADMIN)
        self.mgr_role = Role.objects.get(name=Role.ROLE_MANAGER)
        self.rep_role = Role.objects.get(name=Role.ROLE_REP)
        self.acct_role = Role.objects.get(name=Role.ROLE_ACCOUNTANT)

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
        self.assertEqual(len(context['kpi_cards']), 18)

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
        self.assertIn('net_sales_stats', card_ids)
        self.assertIn('collections_collected_stats', card_ids)
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


class EgyptGeocodingSearchTests(TestCase):
    """Verifies Egyptian geocoding scoped to Egypt and local Area fallback."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_superuser(
            username='admin_geocoding',
            email='admin_geo@wea.com',
            password='Password123!'
        )
        self.client.force_login(self.user)
        self.gov = Area.objects.create(name='محافظة الجيزة', code='GIZ-01', area_type='governorate')
        self.brick = Area.objects.create(name='الدقي', code='DOK-01', parent=self.gov, area_type='subarea')

    def test_geocoding_search_api_requires_auth(self):
        anon_client = Client()
        res = anon_client.get(reverse('geocoding_search_api') + '?q=الدقي')
        self.assertEqual(res.status_code, 302)

    def test_geocoding_search_api_local_fallback(self):
        from unittest.mock import patch
        with patch('urllib.request.urlopen', side_effect=Exception("Network down")):
            res = self.client.get(reverse('geocoding_search_api') + '?q=الدقي')
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertIn('results', data)
            self.assertTrue(len(data['results']) > 0)
            self.assertTrue(any('الدقي' in r['display_name'] for r in data['results']))
            first_result = data['results'][0]
            self.assertEqual(first_result['address']['suburb'], 'الدقي')
            self.assertEqual(first_result['address']['state'], 'محافظة الجيزة')


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


class DashboardVendorScopingTests(TestCase):
    """
    Verifies that the dashboard and VendorAccount scoping:
    1. Does not raise Cannot resolve keyword 'vendor' into field.
    2. Correctly scopes supplier balances across roles (superadmin, accountant, manager, rep).
    """

    def setUp(self):
        self.cairo = Area.objects.create(name='القاهرة', code='CAI-DSH', area_type='governorate')
        self.giza = Area.objects.create(name='الجيزة', code='GIZ-DSH', area_type='governorate')
        self.nasr = Area.objects.create(name='مدينة نصر', code='NASR-DSH', area_type='subarea', parent=self.cairo)

        self.superadmin = User.objects.create_superuser(
            username='sa_dsh', email='sa_dsh@wea.com', password='Password123!'
        )
        self.accountant_role = Role.objects.get(name=Role.ROLE_ACCOUNTANT)
        self.manager_role = Role.objects.get(name=Role.ROLE_MANAGER)
        self.rep_role = Role.objects.get(name=Role.ROLE_REP)

        self.accountant = User.objects.create_user(
            username='acc_dsh', email='acc_dsh@wea.com', password='Password123!', role=self.accountant_role
        )
        self.cairo_mgr = User.objects.create_user(
            username='mgr_cai_dsh', email='mgr_cai_dsh@wea.com', password='Password123!', role=self.manager_role
        )
        self.cairo_mgr.assigned_areas.add(self.cairo)

        self.giza_mgr = User.objects.create_user(
            username='mgr_giz_dsh', email='mgr_giz_dsh@wea.com', password='Password123!', role=self.manager_role
        )
        self.giza_mgr.assigned_areas.add(self.giza)

        self.rep = User.objects.create_user(
            username='rep_dsh', email='rep_dsh@wea.com', password='Password123!', role=self.rep_role
        )
        self.rep.assigned_areas.add(self.nasr)

        self.vendor_cairo = Contact.objects.create(
            name='شركة فارما القاهرة للتوريدات',
            code='SUP-CAI-01',
            is_supplier=True,
            area=self.nasr,
            status='customer'
        )
        self.vendor_acc, _ = VendorAccount.objects.get_or_create(
            supplier=self.vendor_cairo,
            defaults={'current_balance': Decimal('25000.00'), 'credit_limit': Decimal('50000.00')}
        )
        self.vendor_acc.current_balance = Decimal('25000.00')
        self.vendor_acc.credit_limit = Decimal('50000.00')
        self.vendor_acc.save()

    def test_vendor_account_scoping_no_keyword_error(self):
        """Scoping VendorAccount must use supplier__* relationship without 'vendor' keyword errors."""
        from accounts.permissions import get_scoped_queryset

        # Superadmin sees vendor account
        qs_sa = get_scoped_queryset(VendorAccount.objects.all(), self.superadmin, 'vendoraccount')
        self.assertIn(self.vendor_acc, qs_sa)

        # Accountant sees vendor account (financial view)
        qs_acc = get_scoped_queryset(VendorAccount.objects.all(), self.accountant, 'vendoraccount')
        self.assertIn(self.vendor_acc, qs_acc)

        # Cairo manager sees Cairo vendor
        qs_cai = get_scoped_queryset(VendorAccount.objects.all(), self.cairo_mgr, 'vendoraccount')
        self.assertIn(self.vendor_acc, qs_cai)

        # Giza manager does not see Cairo vendor
        qs_giz = get_scoped_queryset(VendorAccount.objects.all(), self.giza_mgr, 'vendoraccount')
        self.assertNotIn(self.vendor_acc, qs_giz)

        # Commercial Rep has no supplier scope -> empty
        qs_rep = get_scoped_queryset(VendorAccount.objects.all(), self.rep, 'vendoraccount')
        self.assertEqual(qs_rep.count(), 0)

    def test_dashboard_renders_without_vendor_error_for_all_roles(self):
        """Dashboard view must render with HTTP 200 without raising keyword errors across roles."""
        client = Client()

        for user in [self.superadmin, self.accountant, self.cairo_mgr, self.rep]:
            client.force_login(user)
            resp = client.get(reverse('home'))
            self.assertEqual(resp.status_code, 200, f"Dashboard failed for {user.username}")


class ArabicSearchNormalizationTests(TestCase):
    """
    Verifies Arabic search normalization across characters, diacritics, and query matching.
    """

    def test_normalize_arabic_text_variations(self):
        from master_data.search_utils import normalize_arabic_text

        # Alef variations
        self.assertEqual(normalize_arabic_text('أحمد'), 'احمد')
        self.assertEqual(normalize_arabic_text('إبراهيم'), 'ابراهيم')
        self.assertEqual(normalize_arabic_text('آدم'), 'ادم')
        self.assertEqual(normalize_arabic_text('ٱستخدام'), 'استخدام')

        # Taa Marbuta
        self.assertEqual(normalize_arabic_text('صيدلية'), 'صيدليه')
        self.assertEqual(normalize_arabic_text('مكة'), 'مكه')

        # Yaa / Alef Maqsura
        self.assertEqual(normalize_arabic_text('علي'), 'علي')
        self.assertEqual(normalize_arabic_text('منى'), 'مني')
        self.assertEqual(normalize_arabic_text('يحيى'), 'يحيي')

        # Tashkeel (diacritics) & Tatweel
        self.assertEqual(normalize_arabic_text('مُحَمَّدٌ'), 'محمد')
        self.assertEqual(normalize_arabic_text('شــــركة'), 'شركه')

    def test_matches_arabic_query(self):
        from master_data.search_utils import matches_arabic_query

        self.assertTrue(matches_arabic_query('صيدلية الأمل الحديثة', 'صيدليه الامل'))
        self.assertTrue(matches_arabic_query('شركة الإخوة المتحدون', 'اخوه'))
        self.assertTrue(matches_arabic_query('مستشفى الشفاء', 'مستشفي'))
        self.assertFalse(matches_arabic_query('صيدلية السلام', 'الامل'))

    def test_filter_by_arabic_search_orm(self):
        from master_data.search_utils import filter_by_arabic_search

        area = Area.objects.create(name='منطقة البحث', code='SRCH-01')
        c1 = Contact.objects.create(name='صيدلية الأهرام الكبرى', area=area, status='customer')
        c2 = Contact.objects.create(name='مستشفى الشروق التخصصي', area=area, status='customer')

        # Search with different letter forms
        res1 = filter_by_arabic_search(Contact.objects.all(), ['name'], 'صيدليه الاهرام')
        self.assertIn(c1, res1)
        self.assertNotIn(c2, res1)

        res2 = filter_by_arabic_search(Contact.objects.all(), ['name'], 'مستشفي')
        self.assertIn(c2, res2)
        self.assertNotIn(c1, res2)





class R2StorageAndAttachmentsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('setup_permissions')
        cls.superadmin_role = Role.objects.get(name=Role.ROLE_SUPERADMIN)
        cls.rep_role = Role.objects.get(name=Role.ROLE_REP)
        cls.cairo = Area.objects.create(name='القاهرة R2', code='R2-CAI')
        cls.giza = Area.objects.create(name='الجيزة R2', code='R2-GIZ')
        cls.admin = User.objects.create_superuser(username='r2_admin', password='Password123!', name='Admin R2')
        cls.rep_cai = User.objects.create_user(
            username='r2_rep_cai', password='Password123!', name='Rep Cairo', role=cls.rep_role
        )
        cls.rep_cai.assigned_areas.add(cls.cairo)
        cls.rep_giz = User.objects.create_user(
            username='r2_rep_giz', password='Password123!', name='Rep Giza', role=cls.rep_role
        )
        cls.rep_giz.assigned_areas.add(cls.giza)
        cls.customer_cai = Contact.objects.create(
            name='صيدلية R2 القاهرة', area=cls.cairo, is_customer=True, created_by=cls.rep_cai, status='customer'
        )
        cls.customer_cai2 = Contact.objects.create(
            name='صيدلية R2 القاهرة 2', area=cls.cairo, is_customer=True, created_by=cls.rep_cai, status='customer'
        )

    def test_r2_cost_calculator_and_settings_protection(self):
        from master_data.models import R2StorageConfig

        cfg = R2StorageConfig.get_settings()
        est_free = cfg.calculate_cost_estimate(
            storage_gb=Decimal('5'), class_a_ops=100000, class_b_ops=500000
        )
        self.assertEqual(est_free['total_usd'], 0.0)

        est_paid = cfg.calculate_cost_estimate(
            storage_gb=Decimal('110'), class_a_ops=2000000, class_b_ops=20000000
        )
        self.assertGreater(est_paid['total_usd'], 0.0)

        # Non-superadmin blocked from /settings/storage/
        self.client.force_login(self.rep_cai)
        res_rep = self.client.get(reverse('r2_storage_settings'))
        self.assertIn(res_rep.status_code, (302, 403))

        # Superadmin can view and update pricing
        self.client.force_login(self.admin)
        res_adm = self.client.get(reverse('r2_storage_settings'))
        self.assertEqual(res_adm.status_code, 200)
        res_post = self.client.post(reverse('r2_storage_settings'), {
            'action': 'update_pricing',
            'price_per_gb_month_usd': '0.0200',
            'free_storage_gb': '10.00',
            'price_per_million_class_a_usd': '4.5000',
            'free_class_a_ops': '1000000',
            'price_per_million_class_b_usd': '0.3600',
            'free_class_b_ops': '10000000',
            'egress_price_per_gb_usd': '0.0000',
            'usd_to_egp_rate': '50.00',
        })
        self.assertEqual(res_post.status_code, 302)
        cfg.refresh_from_db()
        self.assertEqual(cfg.price_per_gb_month_usd, Decimal('0.0200'))

    def test_attachment_validation_dedup_refcount_and_idor(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.core.exceptions import ValidationError
        from master_data.media_service import store_attachment, delete_attachment
        from master_data.models import ERPAttachment
        from django.core.files.storage import default_storage

        # Invalid extension rejected
        bad_file = SimpleUploadedFile('malware.exe', b'MZ\x90\x00', content_type='application/octet-stream')
        with self.assertRaises(ValidationError):
            store_attachment(self.customer_cai, bad_file, user=self.rep_cai)

        # Valid PDF uploaded twice on two records -> deduplicates same storage path
        pdf_bytes = b'%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n'
        f1 = SimpleUploadedFile('invoice1.pdf', pdf_bytes, content_type='application/pdf')
        f2 = SimpleUploadedFile('invoice2.pdf', pdf_bytes, content_type='application/pdf')
        att1, _ = store_attachment(self.customer_cai, f1, user=self.rep_cai)
        att2, dedup2 = store_attachment(self.customer_cai2, f2, user=self.rep_cai)
        self.assertTrue(dedup2)
        self.assertEqual(att1.file_hash, att2.file_hash)
        self.assertEqual(att1.file.name, att2.file.name)
        shared_name = att1.file.name

        # Giza rep cannot view/download/delete Cairo attachment (IDOR protection)
        self.client.force_login(self.rep_giz)
        self.assertIn(self.client.get(reverse('erp_attachment_view', args=[att1.pk])).status_code, (302, 403))
        self.assertIn(self.client.get(reverse('erp_attachment_download', args=[att1.pk])).status_code, (302, 403))

        # Deleting first ref preserves shared blob
        with self.captureOnCommitCallbacks(execute=True):
            delete_attachment(att1, user=self.rep_cai)
        self.assertTrue(ERPAttachment.objects.filter(pk=att2.pk).exists())
        self.assertTrue(default_storage.exists(shared_name))

        # Deleting last ref deletes blob
        with self.captureOnCommitCallbacks(execute=True):
            delete_attachment(att2, user=self.rep_cai)
        self.assertFalse(default_storage.exists(shared_name))


class PDFInvoicesAndStatementsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('setup_permissions')
        cls.rep_role = Role.objects.get(name=Role.ROLE_REP)
        cls.cairo = Area.objects.create(name='القاهرة PDF', code='PDF-CAI')
        cls.giza = Area.objects.create(name='الجيزة PDF', code='PDF-GIZ')
        cls.admin = User.objects.create_superuser(username='pdf_admin', password='Password123!', name='Admin PDF')
        cls.rep_giz = User.objects.create_user(
            username='pdf_rep_giz', password='Password123!', name='Rep Giza PDF', role=cls.rep_role
        )
        cls.rep_giz.assigned_areas.add(cls.giza)

        from catalog.models import Product, ProductCategory
        from inventory.models import Warehouse
        from sales.models import CustomerAccount, CustomerTransaction, SalesOrder, SalesOrderItem
        from purchases.models import PurchaseOrder, PurchaseOrderItem

        cls.cat = ProductCategory.objects.create(name='فئة PDF')
        cls.customer = Contact.objects.create(
            name='عميل PDF القاهرة', area=cls.cairo, is_customer=True, created_by=cls.admin, status='customer'
        )
        cls.supplier = Contact.objects.create(
            name='مورد PDF القاهرة', area=cls.cairo, is_supplier=True, created_by=cls.admin, status='customer'
        )
        cls.wh = Warehouse.objects.create(name='مخزن PDF', code='WH-PDF', area=cls.cairo, is_active=True)
        cls.prod = Product.objects.create(
            name='دواء PDF', sku_code='PDF-001', category=cls.cat, retail_price=Decimal('100.00'), default_purchase_cost=Decimal('60.00')
        )
        cls.so = SalesOrder.objects.create(
            serial_num=9501, order_number='SO-PDF-9501', customer=cls.customer, source_warehouse=cls.wh,
            order_date=datetime.date(2026, 5, 10), status='invoiced', created_by=cls.admin
        )
        SalesOrderItem.objects.create(
            order=cls.so, product=cls.prod, quantity=Decimal('2'), unit_price=Decimal('100.00')
        )
        cls.so.recalculate_totals()

        cls.po = PurchaseOrder.objects.create(
            serial_num=9502, order_number='PO-PDF-9502', supplier=cls.supplier, target_warehouse=cls.wh,
            order_date=datetime.date(2026, 5, 10), status='settled', created_by=cls.admin
        )
        PurchaseOrderItem.objects.create(
            order=cls.po, product=cls.prod, quantity=Decimal('5'), unit_price=Decimal('60.00')
        )
        cls.po.recalculate_totals()

        # Ledger transactions for customer statement
        acc, _ = CustomerAccount.objects.get_or_create(customer=cls.customer, defaults={'current_balance': Decimal('150.00')})
        CustomerTransaction.objects.create(
            serial=91001, account=acc, transaction_type='debit', reason='sales',
            transaction_date=datetime.date(2026, 4, 20), debit=Decimal('500.00'), credit=Decimal('0.00'),
            description='رصيد سابق'
        )
        CustomerTransaction.objects.create(
            serial=91002, account=acc, transaction_type='debit', reason='sales',
            transaction_date=datetime.date(2026, 5, 10), debit=Decimal('200.00'), credit=Decimal('0.00'),
            description='SO-PDF-9501'
        )
        CustomerTransaction.objects.create(
            serial=91003, account=acc, transaction_type='credit', reason='collection',
            transaction_date=datetime.date(2026, 5, 12), debit=Decimal('0.00'), credit=Decimal('550.00'),
            description='تحصيل نقدي'
        )

    def test_order_and_statement_pdfs_and_scope(self):
        from accounts.models import SecurityAuditLog

        self.client.force_login(self.admin)
        res_so = self.client.get(reverse('sales_order_pdf', args=[self.so.pk]))
        self.assertEqual(res_so.status_code, 200)
        self.assertEqual(res_so['Content-Type'], 'application/pdf')
        self.assertTrue(res_so.content.startswith(b'%PDF-'))

        res_po = self.client.get(reverse('purchase_order_pdf', args=[self.po.pk]), {'include_signatures': '1'})
        self.assertEqual(res_po.status_code, 200)
        self.assertTrue(res_po.content.startswith(b'%PDF-'))

        res_stmt = self.client.get(reverse('customer_statement_pdf', args=[self.customer.pk]), {
            'start_date': '2026-05-01',
            'end_date': '2026-05-31',
            'category': 'orders',
            'include_line_details': '1',
        })
        self.assertEqual(res_stmt.status_code, 200)
        self.assertTrue(res_stmt.content.startswith(b'%PDF-'))
        self.assertTrue(SecurityAuditLog.objects.filter(action_type='PDF_GENERATED').exists())

        # Giza rep blocked from Cairo order PDF & statement PDF
        self.client.force_login(self.rep_giz)
        self.assertIn(self.client.get(reverse('sales_order_pdf', args=[self.so.pk])).status_code, (302, 403))
        self.assertIn(self.client.get(reverse('customer_statement_pdf', args=[self.customer.pk])).status_code, (302, 403))

    def test_date_range_resolver_and_home_default_current_month(self):
        from master_data.date_filter_utils import resolve_date_range
        from django.test import RequestFactory

        rf = RequestFactory()
        s, e, preset, _, _ = resolve_date_range(rf.get('/home/'), default_preset='this_month')
        today = timezone.localdate()
        self.assertEqual(preset, 'this_month')
        self.assertEqual(s, today.replace(day=1))
        self.assertEqual(e, today)

        # Home view no longer defaults to hardcoded Oct 2026
        self.client.force_login(self.admin)
        res_home = self.client.get(reverse('home'))
        self.assertEqual(res_home.status_code, 200)
        self.assertEqual(res_home.context['start_date_str'], today.replace(day=1).strftime('%Y-%m-%d'))


class StandardizedFilteringUtilitiesTests(TestCase):
    """Verifies shared filter parsing, multi-value chip removal, and AR Aging export parity."""

    def test_parse_multi_int_and_str_and_malformed_tokens(self):
        from django.http import QueryDict
        from master_data.filter_utils import parse_multi_int, parse_multi_str, parse_single_int

        qd = QueryDict('status=pending&status=approved,finished&status=all&owner=12&owner=abc&owner=12&brick[]=5')
        self.assertEqual(parse_multi_str(qd, 'status'), ['pending', 'approved', 'finished'])
        self.assertEqual(parse_multi_int(qd, 'owner'), [12])
        self.assertEqual(parse_multi_int(qd, 'brick'), [5])
        self.assertIsNone(parse_single_int(QueryDict('owner=abc'), 'owner'))
        self.assertEqual(parse_single_int(QueryDict('owner=42'), 'owner'), 42)

    def test_url_remove_param_single_value_from_multi_select(self):
        from django.test import RequestFactory
        from master_data.templatetags.erp_tags import url_remove_param

        rf = RequestFactory()
        req = rf.get('/contacts/?area_id=1&area_id=2&status=active&page=3')
        ctx = {'request': req}
        out = url_remove_param(ctx, 'area_id', value='1', page=1)
        self.assertIn('area_id=2', out)
        self.assertNotIn('area_id=1', out)
        self.assertIn('status=active', out)
        self.assertIn('page=1', out)

    def test_ar_aging_export_respects_area_and_rep_filters(self):
        from sales.models import CustomerAccount
        cairo = Area.objects.create(name='القاهرة', code='AR-CAI', area_type='governorate')
        giza = Area.objects.create(name='الجيزة', code='AR-GIZ', area_type='governorate')
        c1 = Contact.objects.create(name='عميل القاهرة', code='C-AR-1', is_customer=True, area=cairo, status='customer')
        c2 = Contact.objects.create(name='عميل الجيزة', code='C-AR-2', is_customer=True, area=giza, status='customer')
        CustomerAccount.objects.update_or_create(customer=c1, defaults={'current_balance': Decimal('1000.00'), 'overdue_balance': Decimal('500.00')})
        CustomerAccount.objects.update_or_create(customer=c2, defaults={'current_balance': Decimal('2000.00'), 'overdue_balance': Decimal('0.00')})

        admin = User.objects.create_superuser(username='sa_ar_flt', email='sa_ar@wea.com', password='Password123!')
        self.client.force_login(admin)
        resp_html = self.client.get(reverse('report_ar_aging'), {'area': cairo.id})
        self.assertEqual(resp_html.status_code, 200)
        self.assertEqual(len(resp_html.context['rows']), 1)

        resp_exp = self.client.get(reverse('report_ar_aging_export'), {'area': cairo.id})
        self.assertEqual(resp_exp.status_code, 200)
        self.assertIn('spreadsheetml', resp_exp['Content-Type'])
        resp_prt = self.client.get(reverse('report_ar_aging_print'), {'area': cairo.id})
        self.assertEqual(resp_prt.status_code, 200)
        self.assertContains(resp_prt, 'عميل القاهرة')
        self.assertNotContains(resp_prt, 'عميل الجيزة')

    def test_dashboard_permission_gating_and_scoped_area_brick_apis(self):
        """Phase 2 (#7): Dashboard hides unauthorized module data from backend/charts_json and scopes geo APIs."""
        from accounts.models import Role, Permission
        from django.core.management import call_command
        import json as _json

        call_command('setup_permissions')
        cairo = Area.objects.create(name='القاهرة لوحة', code='DSH-CAI', area_type='governorate')
        giza = Area.objects.create(name='الجيزة لوحة', code='DSH-GIZ', area_type='governorate')
        brick_c = Area.objects.create(name='مدينة نصر لوحة', code='DSH-NSR', area_type='subarea', parent=cairo)
        brick_g = Area.objects.create(name='الدقي لوحة', code='DSH-DQ', area_type='subarea', parent=giza)

        # Custom role with visits permission ONLY (no sales, no purchases)
        vis_only_role = Role.objects.create(name='visits_only_dash', display_name='Visits Only', is_active=True)
        mod_act = Permission.objects.get(codename='module:activities')
        vis_perm = Permission.objects.filter(codename__in=['activities:visits/list', 'activities:visits/view']).first()
        self.assertIsNotNone(vis_perm)
        vis_only_role.permissions.add(mod_act, vis_perm)
        u = User.objects.create_user(
            username='vis_only@wea.com', email='vis_only@wea.com', password='Password123!',
            role=vis_only_role, is_active=True
        )
        u.assigned_areas.add(brick_c)

        self.client.force_login(u)
        res = self.client.get(reverse('home'))
        self.assertEqual(res.status_code, 200)
        charts = _json.loads(res.context['charts_json'])
        self.assertIn('visits_by_area', charts)
        self.assertNotIn('orders_created_by_area', charts)
        self.assertNotIn('collections_by_area', charts)
        self.assertFalse(res.context['can_view_sales'])
        self.assertFalse(res.context['can_view_purchases'])

        # Scoped geo search APIs must NOT expose Giza to Cairo-brick user
        area_res = self.client.get(reverse('dashboard_search_areas_api'))
        self.assertEqual(area_res.status_code, 200)
        area_ids = [r['id'] for r in area_res.json()['results']]
        self.assertIn(cairo.id, area_ids)
        self.assertNotIn(giza.id, area_ids)

        brick_res = self.client.get(reverse('dashboard_search_bricks_api'))
        self.assertEqual(brick_res.status_code, 200)
        brick_ids = [r['id'] for r in brick_res.json()['results']]
        self.assertIn(brick_c.id, brick_ids)
        self.assertNotIn(brick_g.id, brick_ids)


class SidebarActiveNavigationTests(TestCase):
    """Verify deterministic resolve_active_nav & single-active sidebar expansion across aliases and nested routes."""

    def setUp(self):
        from django.core.management import call_command
        call_command('setup_permissions')
        self.superadmin = User.objects.create_superuser(
            username='nav_sa@wea.com', email='nav_sa@wea.com', password='Password123!'
        )
        self.cairo = Area.objects.create(name='القاهرة nav', code='NAV-CAI', area_type='governorate')
        self.brick = Area.objects.create(name='نصر nav', code='NAV-NSR', area_type='subarea', parent=self.cairo)
        self.customer = Contact.objects.create(
            name='عميل nav', is_customer=True, account_type='Pharmacy',
            area=self.cairo, brick=self.brick, status='customer'
        )

    def test_resolve_active_nav_routes_and_rendered_sidebar_isolation(self):
        from django.urls import resolve
        from master_data.templatetags.erp_tags import resolve_active_nav

        visit = Visit.objects.create(
            contact=self.customer, owner=self.superadmin, created_by=self.superadmin,
            date=timezone.localdate()
        )
        rf = RequestFactory()

        cases = [
            ('/visits/', 'submenu-activities', 'visits'),
            (f'/visits/{visit.pk}/', 'submenu-activities', 'visits'),
            ('/planned-visits/', 'submenu-activities', 'planned_visits'),
            ('/agreements/', 'submenu-activities', 'agreements'),
            ('/settings/agreements/', 'submenu-settings', 'agreements_settings'),
            ('/settings/visits/templates/', 'submenu-settings', 'visit_templates'),
            ('/reports/agreements-roi/', 'submenu-reports', 'report_agreements_roi'),
            ('/accounting/customers/', 'submenu-sales', 'accounting_customers'),
            ('/accounting/vendors/', 'submenu-purchases', 'accounting_vendors'),
        ]

        for path, exp_section, exp_item in cases:
            req = rf.get(path)
            req.resolver_match = resolve(path)
            resolved = resolve_active_nav({'request': req})
            self.assertEqual(resolved['section'], exp_section, f"Wrong section for {path}")
            self.assertEqual(resolved['item'], exp_item, f"Wrong item for {path}")

        # Verify actual rendered HTML on colliding routes keeps ONLY the exact parent submenu open
        self.client.force_login(self.superadmin)
        for path, exp_section, exp_item in [
            ('/visits/', 'submenu-activities', 'visits'),
            ('/settings/visits/templates/', 'submenu-settings', 'visit_templates'),
            ('/agreements/', 'submenu-activities', 'agreements'),
            ('/settings/agreements/', 'submenu-settings', 'agreements_settings'),
            ('/reports/agreements-roi/', 'submenu-reports', 'report_agreements_roi'),
        ]:
            res = self.client.get(path)
            self.assertEqual(res.status_code, 200, f"GET {path} returned {res.status_code}")
            html = res.content.decode('utf-8')
            sidebar_html = html[html.index('<aside id="sidebar"'):html.index('</aside>')]
            self.assertIn(f'data-erp-nav-item="{exp_item}" data-erp-active-link="1"', sidebar_html, f"Active link missing on {path}")
            self.assertEqual(sidebar_html.count('data-erp-active-link="1"'), 1, f"Multiple active links on {path}")
            # Confirm other submenus have 'hidden' while exp_section does not
            for sub in ('submenu-catalog', 'submenu-activities', 'submenu-sales', 'submenu-purchases', 'submenu-inventory', 'submenu-treasury', 'submenu-performance', 'submenu-reports', 'submenu-settings'):
                marker = f'id="{sub}" class="'
                idx = sidebar_html.find(marker)
                self.assertNotEqual(idx, -1, f"Missing {sub} on {path}")
                cls_fragment = sidebar_html[idx:idx + 120]
                if sub == exp_section:
                    self.assertNotIn('hidden"', cls_fragment, f"Expected {sub} to be open on {path}")
                else:
                    self.assertIn('hidden"', cls_fragment, f"Expected {sub} to be collapsed on {path}")


class WeaDataIntegrationTests(TestCase):
    """Comprehensive tests for WeaDataIntegrationService: idempotency, dedup, cleanup safeguards, and reconciliation."""

    def setUp(self):
        import os
        import tempfile
        import openpyxl
        self.tmpdir = tempfile.TemporaryDirectory()
        self.wea_dir = os.path.join(self.tmpdir.name, 'wea data')
        self.data_dir = os.path.join(self.tmpdir.name, 'data_folder')
        os.makedirs(self.wea_dir, exist_ok=True)
        os.makedirs(self.data_dir, exist_ok=True)

        self.superadmin_role, _ = Role.objects.get_or_create(
            name=Role.ROLE_SUPERADMIN,
            defaults={'display_name': 'مدير النظام الأعلى', 'is_super': True, 'is_system': True, 'is_active': True},
        )
        self.admin = User.objects.create_superuser(
            username='wea.pharm2020@gmail.com',
            email='wea.pharm2020@gmail.com',
            password='Password123!',
            role=self.superadmin_role,
        )
        # Test records to verify safe cleanup
        self.test_user = User.objects.create_user(username='mgr2', password='Password123!')
        self.main_wh = Warehouse.objects.create(code='WH-MAIN-01', name='المخزن الرئيسي بضاعه', is_main=True)
        self.supplies_wh = Warehouse.objects.create(code='WH-SUPPLIES-01', name='مخزن المستلزمات')
        self.wh_feisal = Warehouse.objects.create(code='WH-REP-0095', name='عهدة مندوب فبصل', is_rep_warehouse=True)
        self.test_wh_empty = Warehouse.objects.create(code='WH-T1', name='wh_t_1')
        self.main_vault = Vault.objects.create(serial_num=1014, name='الخزينة الرئيسية - المقر الرئيسي')
        self.test_vault_empty = Vault.objects.create(serial_num=1018, name='v_del_test')

        # Existing supplier #16031 (to be renamed) + contact with code='nan'
        self.supp_16031 = Contact.objects.create(
            serial_num=16031, name='مصنع ليدر لمستحضرات التجميل', code='nan', is_supplier=True, is_customer=True
        )
        self.cust_w0047 = Contact.objects.create(
            serial_num=7001, name='مخزن ميجا فارم العياط', code='W0047', is_customer=True
        )
        self.cust_ct_only = Contact.objects.create(
            serial_num=7002, name='صيدلية مستردة من الحركات', code='W9999', is_customer=True
        )

        def write_xlsx(path, headers, rows):
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.append(headers)
            for r in rows:
                ws.append(r)
            wb.save(path)

        write_xlsx(os.path.join(self.data_dir, 'users.xlsx'),
                   ['id', 'email', 'name', 'active'],
                   [['u-admin', 'wea.pharm2020@gmail.com', 'Dr.wael Atta (CEO)', True]])

        write_xlsx(os.path.join(self.wea_dir, 'inventory stock.xlsx'),
                   ['المخزن', 'الكود', 'التصنيف', 'المنتج', 'تاريخ الصلاحية', 'التكلفة', 'رقم التشغيل', 'فى المخزن', 'محجوز', 'متاح', 'إجمالي التكلفة', 'سعر الوحدة', 'قيمة البيع'],
                   [
                       ['المخزن الرئيسي بضاعه', 'ST1', 'WEA', 'Steps', '2028-09-26', 10.0, 'B001', 100, 5, 95, 1000, 140, 14000],
                       ['عهدة د. أحمد عبد العظيم', 'ST1', 'WEA', 'Steps', None, 10.0, None, 20, None, 20, 200, 140, 2800],
                   ])

        write_xlsx(os.path.join(self.wea_dir, 'memos.xlsx'),
                   ['ID', 'Serial Number', 'Type', 'Note', 'Source ID', 'Source Type', 'Source Number', 'Source Contact ID', 'Source Contact Number', 'Source Contact Name', 'Cancelled At', 'Done At', 'Staged At', 'Warehouse Name', 'Warehouse IsActive', 'Creation Time', 'Creator Name', 'Status Name', 'Transfer Serial Number'],
                   [
                       ['m-1', 1, 'unstock', '', 'so-uuid-1', 'sales_order', '#9001', '', 'W0047', 'مخزن ميجا فارم العياط', None, '10/01/2026 10:00 AM', None, 'عهدة د. أحمد عبد العظيم', 'نعم', '10/01/2026 10:00 AM', 'Former Rep X', 'Done', None],
                       ['m-2', 2, 'stock', '', 'po-uuid-1', 'purchase_order', '#10', '', '#16031', 'مصنع بايوفيردا لمستحضرات التجميل', None, '11/01/2026 10:00 AM', None, 'المخزن الرئيسي بضاعه', 'نعم', '11/01/2026 10:00 AM', 'Dr.wael Atta (CEO)', 'Done', None],
                   ])

        write_xlsx(os.path.join(self.wea_dir, 'purchases orders.xlsx'),
                   ['المعرف', 'تاريخ الإنشاء', 'المنشء - المعرف', 'المنشء - الاسم', 'مسلسل', 'الرقم', 'العميل - مسلسل', 'العميل - الاسم', 'العميل - المنطقة - الكود', 'ملاحظة', 'الحالة - الاسم', 'الإجمالي', 'الإجمالي النهائي', 'تاريخ إصدار الفاتورة', 'تاريخ التخزين', 'تاريخ الاستحقاق', 'العناصر - المنتج - الكود', 'العناصر - المنتج - التصنيف', 'العناصر - المنتج - الاسم', 'العناصر - المنتج - سعر القطعة', 'العناصر - الكمية', 'العناصر - سعر القطعة', 'العناصر - الكلي', 'العناصر - رقم تشغيل المنتج', 'العناصر - تاريخ صلاحية المنتج', 'العناصر - خصم القطعة %', 'الخصم الإضافي - نسبة', 'الخصم الإضافي - قيمة', 'السعر قبل كل الخصومات', 'السعر بعد كل الخصومات'],
                   [['po-uuid-1', '11/01/2026 10:00 AM', 'u-admin', 'Dr.wael Atta (CEO)', 10, '#10', 16031, 'مصنع بايوفيردا لمستحضرات التجميل', '', 'نقل 200', 'Settled', '1000.00', '1200.00', '11/01/2026 10:00 AM', '11/01/2026 10:00 AM', '11/02/2026', 'ST1', 'WEA', 'Steps', '140.00', 100, '10.00', '1000.00', 'B001', '26/09/2028', '0.00', '0.00', '0.00', '1000.00', '1000.00']])

        write_xlsx(os.path.join(self.wea_dir, 'purchses return.xlsx'), ['المعرف'], [])

        write_xlsx(os.path.join(self.wea_dir, 'vendors accounts.xlsx'),
                   ['AccountID', 'Contact_SerialNum', 'Contact_Name', 'Contact_Mobile', 'Contact_Phone', 'Contact_Note', 'Contact_AreaID', 'Account_Name', 'Account_AccountStats_Balance', 'Account_AccountStats_OverdueAmount', 'Account_AccountStats_LastTransactionDate'],
                   [['va-1', 16031, 'مصنع بايوفيردا لمستحضرات التجميل', '+201000000000', '', '', '', '[#16031] مصنع ليدر لمستحضرات التجميل', '700.00', '700.00', '2026-01-12']])

        write_xlsx(os.path.join(self.wea_dir, 'vendor transactions.xlsx'),
                   ['المعرف', 'التاريخ', 'السبب', 'السبب - المعرف', 'السبب - الرقم', 'تاريخ الاستحقاق', 'نوع الحركة', 'دائن', 'مدين', 'الرصيد', 'ملاحظة', 'نفذ فى', 'نفذ بواسطة - المعرف', 'نفذ بواسطة - الاسم', 'المديونية', 'الحساب - الاسم'],
                   [
                       ['vt-1', '11/01/2026', 'purchase', 'po-uuid-1', '#10', '11/02/2026', 'credit', '1200.00', '0.00', '1200.00', '', '11/01/2026 10:00 AM', 'u-admin', 'Dr.wael Atta (CEO)', '700.00', '[#16031] مصنع ليدر لمستحضرات التجميل'],
                       ['vt-2', '12/01/2026', 'purchase_payments', 'vp-uuid-1', '#10001', '12/01/2026', 'debit', '0.00', '500.00', '700.00', '', '12/01/2026 10:00 AM', 'u-admin', 'Dr.wael Atta (CEO)', '0.00', '[#16031] مصنع ليدر لمستحضرات التجميل'],
                   ])

        write_xlsx(os.path.join(self.wea_dir, 'vendor-payments.xlsx'),
                   ['ID', 'رقم التسلسل', 'تاريخ الإنشاء', 'id المنشء', 'اسم المنشء', 'الكمية', 'طريقة الدفع', 'اسم حالة التحصيل', 'رقم تسلسل جهة الإتصال', 'ملاحظة جهة الإتصال'],
                   [['vp-uuid-1', 10001, '12/01/2026 10:00 AM', 'u-admin', 'Dr.wael Atta (CEO)', '500.00', 'cash', 'Pending', 16031, 'دفعة']])

        write_xlsx(os.path.join(self.wea_dir, 'sales orders.xlsx'),
                   ['المعرف', 'تاريخ الإنشاء', 'المنشء - المعرف', 'المنشء - الاسم', 'مسلسل', 'الرقم', 'العميل - مسلسل', 'العميل - الكود', 'العميل - الاسم', 'العميل - المنطقة - الكود', 'العميل - المنطقة - المنطقة الرئيسية - الكود', 'ملاحظة', 'الحالة - الاسم', 'الإجمالي', 'الإجمالي النهائي', 'تاريخ الخصم من المخزن', 'تاريخ الاستحقاق', 'الدفع كاش', 'الخصم الإضافي - نسبة', 'الخصم الإضافي - قيمة', 'السعر قبل كل الخصومات', 'السعر بعد كل الخصومات', 'مصاريف الشحن', 'العناصر - المنتج - الكود', 'العناصر - المنتج - التصنيف', 'العناصر - المنتج - الاسم', 'العناصر - المنتج - سعر القطعة', 'العناصر - الكمية', 'العناصر - سعر القطعة', 'العناصر - الكلي', 'العناصر - خصم القطعة %', 'العناصر - السعر بعد كل الخصومات'],
                   [['so-uuid-1', '10/01/2026 10:00 AM', 'u-former-1', 'Former Rep X', 9001, '#9001', 7001, 'W0047', 'مخزن ميجا فارم العياط', '', '', '', 'Invoiced', '1400.00', '1300.00', '10/01/2026 10:00 AM', '10/02/2026', 'لا', '0.00', '100.00', '1400.00', '1300.00', '0.00', 'ST1', 'WEA', 'Steps', '140.00', 10, '140.00', '1300.00', '0.00', '1300.00']])

        write_xlsx(os.path.join(self.wea_dir, 'sales return orders.xlsx'), ['المعرف'], [])

        write_xlsx(os.path.join(self.wea_dir, 'collections.xlsx'),
                   ['ID', 'رقم التسلسل', 'تاريخ الإنشاء', 'id المنشء', 'اسم المنشء', 'الكمية', 'طريقة الدفع', 'رقم الشيك', 'تاريخ استحقاق الشيك', 'اسم حالة التحصيل', 'رقم تسلسل العميل', 'كود العميل', 'اسم العميل', 'ملاحظة العميل', 'رقم محمول العميل', 'كود المنطقة', 'كود المنطقة الرئيسية'],
                   [['col-uuid-1', 15001, '10/01/2026 11:00 AM', 'u-former-1', 'Former Rep X', '800.00', 'cash', None, None, 'Settled', 7001, 'W0047', 'مخزن ميجا فارم العياط', None, None, '', '']])

        # Include exact duplicate row for W0047 to verify deduplication!
        write_xlsx(os.path.join(self.wea_dir, 'customers accounts.xlsx'),
                   ['AccountID', 'Contact_SerialNum', 'Contact_Code', 'Contact_Name', 'Contact_Mobile', 'Contact_Phone', 'Contact_Extra_account_type', 'Contact_Extra_class', 'Contact_Extra_specialty', 'Contact_AreaID', 'Account_Name', 'Account_AccountStats_Balance', 'Account_AccountStats_OverdueAmount', 'Account_AccountStats_LastTransactionDate', 'Account_AccountLimits_DefaultDuePeriodDays'],
                   [
                       ['ca-1', 7001, 'W0047', 'مخزن ميجا فارم العياط', '', '', '', '', '', '', '[W0047] مخزن ميجا فارم العياط', '1988.20', '0.00', '2026-01-10', 30],
                       ['ca-1', 7001, 'W0047', 'مخزن ميجا فارم العياط', '', '', '', '', '', '', '[W0047] مخزن ميجا فارم العياط', '1988.20', '0.00', '2026-01-10', 30],
                   ])

        write_xlsx(os.path.join(self.wea_dir, 'customer transactions 1.xlsx'),
                   ['المعرف', 'التاريخ', 'السبب', 'السبب - المعرف', 'السبب - الرقم', 'تاريخ الاستحقاق', 'نوع الحركة', 'دائن', 'مدين', 'الرصيد', 'ملاحظة', 'نفذ فى', 'نفذ بواسطة - المعرف', 'نفذ بواسطة - الاسم', 'الحساب - الاسم'],
                   [
                       ['ct-1', '10/01/2026', 'payments', 'col-uuid-1', '#15001', '10/01/2026', 'credit', '800.00', '0.00', '500.00', '', '10/01/2026 11:00 AM', 'u-former-1', 'Former Rep X', '[W0047] مخزن ميجا فارم العياط'],
                       ['ct-3', '10/01/2026', 'opening', None, None, '10/01/2026', 'credit', '0.00', '0.00', '0.00', '', '10/01/2026 09:00 AM', 'u-admin', 'Dr.wael Atta (CEO)', '[W9999] صيدلية مستردة من الحركات'],
                   ])

        write_xlsx(os.path.join(self.wea_dir, 'customer transactions 2.xlsx'),
                   ['المعرف', 'التاريخ', 'السبب', 'السبب - المعرف', 'السبب - الرقم', 'تاريخ الاستحقاق', 'نوع الحركة', 'دائن', 'مدين', 'الرصيد', 'ملاحظة', 'نفذ فى', 'نفذ بواسطة - المعرف', 'نفذ بواسطة - الاسم', 'الحساب - الاسم'],
                   [
                       ['ct-2', '10/01/2026', 'sales', 'so-uuid-1', '#9001', '10/02/2026', 'debit', '0.00', '1300.00', '1300.00', '', '10/01/2026 10:00 AM', 'u-admin', 'Dr.wael Atta (CEO)', '[W0047] مخزن ميجا فارم العياط'],
                       ['ct-4', '10/01/2026', 'sales', None, '#9002', '10/02/2026', 'debit', '0.00', '250.00', '250.00', '', '10/01/2026 10:00 AM', 'u-admin', 'Dr.wael Atta (CEO)', '[W9999] صيدلية مستردة من الحركات'],
                   ])

        write_xlsx(os.path.join(self.wea_dir, 'vaults transactions.xlsx'),
                   ['المعرف', 'التاريخ', 'السبب', 'السبب - المعرف', 'السبب - الرقم', 'نوع الحركة', 'دائن', 'مدين', 'الرصيد', 'ملاحظة', 'نفذ فى', 'نفذ بواسطة - المعرف', 'نفذ بواسطة - الاسم', 'الحساب - الاسم'],
                   [
                       ['vtx-1', '10/01/2026', 'payments', 'col-uuid-1', '#15001', 'debit', '0.00', '800.00', '800.00', '', '10/01/2026 11:00 AM', 'u-admin', 'Dr.wael Atta (CEO)', 'خزنة WEA'],
                       ['vtx-2', '12/01/2026', 'purchase_payments', 'vp-uuid-1', '#10001', 'credit', '500.00', '0.00', '300.00', '', '12/01/2026 10:00 AM', 'u-admin', 'Dr.wael Atta (CEO)', 'خزنة WEA'],
                   ])

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_full_integration_idempotency_cleanup_and_reconciliation(self):
        from master_data.wea_integration_service import WeaDataIntegrationService
        from purchases.models import PurchaseOrder
        from sales.models import SalesOrder, Collection, CustomerAccount, CustomerTransaction
        from treasury.models import VendorAccount, VendorPayment, VaultTransaction
        from inventory.models import InventoryStock, InventoryLot, InventoryMemo

        svc = WeaDataIntegrationService(wea_dir=self.wea_dir, data_dir=self.data_dir)
        res1 = svc.run(dry_run=False)

        # All 9 reconciliation checks must match 100%
        for k, v in res1['reconciliation'].items():
            self.assertTrue(v['match'], f"Reconciliation failed for {k}: {v}")

        # Verify cleanup decisions
        self.assertFalse(Warehouse.objects.filter(code='WH-T1').exists())
        self.assertFalse(Vault.objects.filter(serial_num=1018).exists())
        self.assertFalse(User.objects.filter(username='mgr2').exists())
        self.supp_16031.refresh_from_db()
        self.assertEqual(self.supp_16031.name, 'مصنع بايوفيردا لمستحضرات التجميل')
        self.assertEqual(self.supp_16031.code, '')
        self.assertFalse(self.supp_16031.is_customer)
        self.wh_feisal.refresh_from_db()
        self.assertEqual(self.wh_feisal.name, 'عهدة د. أحمد عبد العظيم')

        # Verify exact warehouse from memos.xlsx & inactive archive user
        so = SalesOrder.objects.get(serial_num=9001)
        self.assertEqual(so.source_warehouse, self.wh_feisal)
        self.assertEqual(so.grand_total, Decimal('1300.00'))
        self.assertFalse(so.created_by.is_active)
        self.assertIsNone(so.created_by.role)

        # Verify PO shipping fee derivation & cleared VendorPayment
        po = PurchaseOrder.objects.get(serial_num=10)
        self.assertEqual(po.shipping_fees, Decimal('200.00'))
        self.assertEqual(po.grand_total, Decimal('1200.00'))
        vp = VendorPayment.objects.get(serial_num=10001)
        self.assertEqual(vp.status, 'cleared')
        self.assertEqual(vp.vault, self.main_vault)

        # Verify W0047 approved balance override + CT-only customer recovery + dedup
        self.assertEqual(res1['stats']['ca_duplicates_skipped'], 1)
        self.assertEqual(CustomerAccount.objects.get(customer=self.cust_w0047).current_balance, Decimal('1988.20'))
        self.assertEqual(CustomerAccount.objects.get(customer=self.cust_ct_only).current_balance, Decimal('250.00'))
        self.assertEqual(Vault.objects.get(pk=self.main_vault.pk).current_balance, Decimal('300.00'))
        self.assertEqual(InventoryStock.objects.count(), 2)
        self.assertEqual(InventoryLot.objects.count(), 1)

        # Re-run second time -> verify 100% idempotency (zero duplicate records!)
        svc2 = WeaDataIntegrationService(wea_dir=self.wea_dir, data_dir=self.data_dir)
        res2 = svc2.run(dry_run=False)
        for k, v in res2['reconciliation'].items():
            self.assertTrue(v['match'], f"2nd run reconciliation failed for {k}: {v}")
        self.assertEqual(SalesOrder.objects.count(), 1)
        self.assertEqual(PurchaseOrder.objects.count(), 1)
        self.assertEqual(Collection.objects.count(), 1)
        self.assertEqual(VendorPayment.objects.count(), 1)
        self.assertEqual(CustomerTransaction.objects.count(), 4)
        self.assertEqual(VaultTransaction.objects.count(), 2)
        self.assertEqual(InventoryMemo.objects.count(), 2)
        self.assertEqual(Vault.objects.get(pk=self.main_vault.pk).current_balance, Decimal('300.00'))



