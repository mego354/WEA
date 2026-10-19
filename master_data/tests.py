from django.test import TestCase, Client
from django.urls import reverse
from accounts.models import User, Role
from master_data.models import (
    CompanyProfile, LocationSettings, Area, ExpenseType,
    TicketType, ApprovalRequestType, AgreementType,
    SalesSettings, PurchaseSettings, ContactFieldSetting,
    DataSyncConfig
)


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
            'contacts_udf',
            'sync_data',
        ]
        for ep in endpoints:
            response = self.client.get(reverse(ep))
            self.assertEqual(response.status_code, 302, f"Failed for endpoint {ep}")
            self.assertEqual(response.url, reverse('home'))

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
            ('contacts_udf', 'settings/contacts_udf.html'),
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

    def test_contacts_udf_update(self):
        self.client.login(username='admin@example.com', password='AdminPassword123!')
        field = ContactFieldSetting.objects.create(
            field_key='custom_tax',
            display_name='الرقم الضريبي للعميل',
            section='basic',
            is_locked=False,
            is_required=False,
            is_filterable=False
        )
        response = self.client.post(reverse('contacts_udf'), {
            'field_id': field.pk,
            'is_required': 'on',
            'is_filterable': 'on',
        })
        self.assertEqual(response.status_code, 302)
        field.refresh_from_db()
        self.assertTrue(field.is_required)
        self.assertTrue(field.is_filterable)

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
