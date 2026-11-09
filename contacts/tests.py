import io
import json
import openpyxl
from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile

from contacts.models import (
    Contact, ContactAddress, ContactComment, ContactTodo, ContactActivity
)
from master_data.models import Area, ContactFieldSetting
from accounts.models import Role

User = get_user_model()


class ContactModelAndLifecycleTests(TestCase):
    """Verifies Contact model properties, defaults, and coordinate persistence."""

    def setUp(self):
        self.user = User.objects.create_superuser(
            username='admin_contact_model',
            email='admin_contact_model@wea.com',
            password='TestPassword123!'
        )
        self.gov = Area.objects.create(code='GOV-CAI', name='القاهرة', area_type='governorate')
        self.brick = Area.objects.create(code='BRK-NASR', name='مدينة نصر', area_type='subarea', parent=self.gov)

    def test_contact_properties(self):
        contact = Contact.objects.create(
            name='صيدلية النجاح الجديدة',
            contact_type='organization',
            is_customer=True,
            customer_category='A',
            specialty='Pediatrics',
            account_type='Hospital',
            status='customer',
            phone='01012345678',
            mobile='01212345678',
            area=self.brick,
            created_by=self.user,
        )
        self.assertEqual(contact.initials, 'صا')
        self.assertIn(contact.name, contact.display_tag)
        self.assertEqual(contact.status_label, 'Customer')

    def test_default_contact_classification_is_lead(self):
        """Newly created contact via contact_create defaults to status='lead'."""
        client = Client()
        client.force_login(self.user)
        res = client.post(reverse('contact_create'), {
            'name': 'صيدلية المستقبل الجديدة',
            'contact_type': 'organization',
            'relations': ['عميل'],
            'area_id': self.gov.id,
            'mobile_number': '01012345678',
        })
        self.assertEqual(res.status_code, 302)
        new_contact = Contact.objects.filter(name='صيدلية المستقبل الجديدة').first()
        self.assertIsNotNone(new_contact)
        self.assertEqual(new_contact.status, 'lead')
        self.assertTrue(new_contact.is_customer)

    def test_contact_coordinates_saved_and_persisted_on_edit(self):
        """Coordinates entered on contact edit must be saved to ContactAddress and Contact."""
        contact = Contact.objects.create(
            name="صيدلية الأمل الكبرى",
            is_customer=True,
            mobile="01098765432",
            created_by=self.user,
            area=self.brick
        )
        client = Client()
        client.force_login(self.user)

        res = client.post(reverse('contact_edit', kwargs={'pk': contact.id}), {
            'name': "صيدلية الأمل الكبرى المحدثة",
            'contact_type': 'organization',
            'relations': ['عميل'],
            'mobile_number': '01098765432',
            'latitude': '30.044420',
            'longitude': '31.235712',
            'area_id': self.brick.id,
        })
        self.assertEqual(res.status_code, 302)
        contact.refresh_from_db()
        self.assertEqual(contact.name, "صيدلية الأمل الكبرى المحدثة")
        self.assertIsNotNone(contact.latitude)
        self.assertAlmostEqual(float(contact.latitude), 30.044420, places=4)
        self.assertAlmostEqual(float(contact.longitude), 31.235712, places=4)


class ContactViewAndCRUDTests(TestCase):
    """Verifies contacts list, search, filter, Kanban, detail, comments, address, and Excel workflows."""

    def setUp(self):
        self.user = User.objects.create_superuser(
            username='admin_contacts_crud',
            email='admin_contacts_crud@wea.com',
            password='TestPassword123!'
        )
        self.client = Client()
        self.client.force_login(self.user)

        self.gov = Area.objects.create(code='GOV01', name='القاهرة', area_type='governorate')
        self.area = Area.objects.create(code='SUB01', name='مدينة نصر', area_type='subarea', parent=self.gov)

        self.contact = Contact.objects.create(
            name='صيدلية النجاح الجديدة',
            contact_type='organization',
            is_customer=True,
            customer_category='A',
            specialty='Pediatrics',
            account_type='Hospital',
            status='customer',
            phone='01012345678',
            mobile='01212345678',
            area=self.area,
            created_by=self.user,
        )

        self.address = ContactAddress.objects.create(
            contact=self.contact,
            title='المقر الرئيسي',
            street_address='شارع عباس العقاد، عمارة 15',
            area=self.area,
            sub_area='المنطقة الأولى',
            is_main=True
        )

    def test_contacts_list_view(self):
        response = self.client.get(reverse('contacts_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'صيدلية النجاح الجديدة')
        self.assertContains(response, 'انشئ جهة اتصال')
        self.assertContains(response, 'تصدير إلى Excel')

    def test_contacts_list_filtering(self):
        response = self.client.get(reverse('contacts_list') + '?search=النجاح')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'صيدلية النجاح الجديدة')

        response_nomatch = self.client.get(reverse('contacts_list') + '?search=غير_موجود')
        self.assertEqual(response_nomatch.status_code, 200)
        self.assertNotContains(response_nomatch, 'صيدلية النجاح الجديدة')

        response_cust = self.client.get(reverse('contacts_list') + '?relation=customer')
        self.assertEqual(response_cust.status_code, 200)
        self.assertContains(response_cust, 'صيدلية النجاح الجديدة')

    def test_contacts_kanban_view_case_insensitive(self):
        res_capital = self.client.get(reverse('contacts_list') + '?view=Kanban')
        self.assertEqual(res_capital.status_code, 200)
        self.assertEqual(res_capital.context['view_mode'], 'kanban')
        self.assertContains(res_capital, 'id="kanban-container"')
        self.assertIn('kanban_columns', res_capital.context)
        self.assertIn('kanban_data', res_capital.context)

        res_lower = self.client.get(reverse('contacts_list') + '?view=kanban')
        self.assertEqual(res_lower.status_code, 200)
        self.assertEqual(res_lower.context['view_mode'], 'kanban')

        res_filter = self.client.get(reverse('contacts_list') + '?view=Kanban&relation=customer&search=النجاح')
        self.assertEqual(res_filter.status_code, 200)
        self.assertIn('relation=customer', res_filter.context['filter_querystring'])

    def test_contact_detail_view(self):
        response = self.client.get(reverse('contact_detail', args=[self.contact.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'صيدلية النجاح الجديدة')
        self.assertContains(response, 'نظرة عامة')
        self.assertContains(response, 'الأنشطة')
        self.assertContains(response, 'المبيعات')
        self.assertContains(response, 'المرفقات')

    def test_contact_edit_view(self):
        response = self.client.post(
            reverse('contact_edit', args=[self.contact.id]),
            {
                'name': 'صيدلية النجاح والشفاء',
                'contact_type': 'organization',
                'relations': ['عميل'],
                'mobile_number': '01099998888',
                'customer_status': 'customer',
            }
        )
        self.assertEqual(response.status_code, 302)
        self.contact.refresh_from_db()
        self.assertEqual(self.contact.name, 'صيدلية النجاح والشفاء')

    def test_contact_update_status_ajax(self):
        response = self.client.post(
            reverse('contact_update_status', args=[self.contact.id]),
            {'status': 'inactive'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data.get('status'), 'ok')
        self.assertEqual(data.get('new_status'), 'Inactive')
        self.contact.refresh_from_db()
        self.assertEqual(self.contact.status, 'inactive')

    def test_contact_add_comment(self):
        response = self.client.post(
            reverse('contact_add_comment', args=[self.contact.id]),
            {'comment': 'تم الاتصال بالعميل وتم الاتفاق على الزيارة.'}
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.contact.comments.count(), 1)
        self.assertEqual(self.contact.comments.first().text, 'تم الاتصال بالعميل وتم الاتفاق على الزيارة.')

    def test_contact_address_management(self):
        response = self.client.post(
            reverse('contact_add_address', args=[self.contact.id]),
            {
                'title': 'مخزن فرعي',
                'street_address': 'المنطقة الصناعية، بلوك 4',
                'area_id': self.area.id,
                'sub_area': 'المنطقة الصناعية',
            }
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.contact.addresses.count(), 2)

        new_address = self.contact.addresses.get(title='مخزن فرعي')
        response_del = self.client.post(reverse('contact_delete_address', args=[self.contact.id, new_address.id]))
        self.assertEqual(response_del.status_code, 302)
        self.assertEqual(self.contact.addresses.count(), 1)

    def test_contacts_export_excel(self):
        response = self.client.get(reverse('contacts_export'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        self.assertIn('.xlsx', response['Content-Disposition'])
        wb = openpyxl.load_workbook(io.BytesIO(response.content))
        ws = wb.active
        self.assertTrue(ws.sheet_view.rightToLeft)
        found = any(cell.value == 'صيدلية النجاح الجديدة' for row in ws.iter_rows() for cell in row)
        self.assertTrue(found)

    def test_contacts_import_template(self):
        response = self.client.get(reverse('contacts_import_template'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        wb = openpyxl.load_workbook(io.BytesIO(response.content))
        ws = wb.active
        self.assertEqual(ws.cell(row=1, column=1).value, 'المسلسل')

    def test_contacts_import_workflow(self):
        get_resp = self.client.get(reverse('contacts_import'))
        self.assertEqual(get_resp.status_code, 200)
        self.assertContains(get_resp, 'استيراد جهات الاتصال')

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(['المسلسل', 'الاسم', 'علاقة العمل (عميل / مورد / كلاهما)', 'الموبايل', 'الهاتف', 'المنطقة', 'العنوان التفصيلي', 'حد الائتمان'])
        ws.append([9999, 'صيدلية الأمل الكبرى', 'عميل', '01011122233', '0233445566', 'مدينة نصر', 'شارع الطيران', 50000.00])
        out = io.BytesIO()
        wb.save(out)
        out.seek(0)

        excel_file = SimpleUploadedFile('contacts_test.xlsx', out.getvalue(), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

        preview_resp = self.client.post(reverse('contacts_import'), {
            'action': 'preview',
            'excel_file': excel_file,
        })
        self.assertEqual(preview_resp.status_code, 200)
        self.assertContains(preview_resp, 'صيدلية الأمل الكبرى')

        import_resp = self.client.post(reverse('contacts_import'), {
            'action': 'execute',
            'import_mode': 'create_and_update',
        }, follow=True)
        self.assertEqual(import_resp.status_code, 200)
        self.assertTrue(Contact.objects.filter(name='صيدلية الأمل الكبرى').exists())
        c = Contact.objects.get(name='صيدلية الأمل الكبرى')
        self.assertEqual(c.mobile, '01011122233')
        self.assertTrue(c.is_customer)


class ContactUdfTodosTimelineTests(TestCase):
    """Verifies User-Defined Fields (UDF), TODOs management, and activity timeline."""

    def setUp(self):
        self.client = Client()
        self.superadmin_role, _ = Role.objects.get_or_create(
            name=Role.ROLE_SUPERADMIN,
            defaults={'display_name': 'مدير النظام الأعلى', 'is_super': True, 'is_system': True, 'is_active': True}
        )
        self.admin_user = User.objects.create_superuser(
            username='admin_contacts_udf@wea.com',
            email='admin_contacts_udf@wea.com',
            password='Password123!',
            name='Admin Contacts UDF',
            role=self.superadmin_role
        )
        self.client.login(username='admin_contacts_udf@wea.com', password='Password123!')

        self.cairo = Area.objects.create(name='القاهرة', area_type='governorate', is_company_area=False)

        self.udf_license = ContactFieldSetting.objects.create(
            field_key='license_number',
            display_name='رقم ترخيص الصيدلية',
            field_type='text',
            section='basic',
            order=1,
            is_active=True
        )
        self.udf_is_vip = ContactFieldSetting.objects.create(
            field_key='is_vip_customer',
            display_name='عميل مميز (VIP)',
            field_type='boolean',
            section='basic',
            order=2,
            is_active=True
        )
        self.udf_rating = ContactFieldSetting.objects.create(
            field_key='annual_capacity',
            display_name='السعة التخزينية',
            field_type='number',
            section='basic',
            order=3,
            is_active=True
        )
        self.udf_payment_terms = ContactFieldSetting.objects.create(
            field_key='payment_terms_choice',
            display_name='شروط الدفع المفضلة',
            field_type='single_choice',
            choices=['كاش', 'أجل 30 يوم', 'أجل 60 يوم'],
            section='basic',
            order=4,
            is_active=True
        )

        self.contact = Contact.objects.create(
            name='صيدلية الشفاء التجريبية',
            serial_num=8801,
            contact_type='organization',
            is_customer=True,
            area=self.cairo,
            custom_values={
                'license_number': 'LIC-998877',
                'is_vip_customer': True,
                'annual_capacity': 500,
                'payment_terms_choice': 'كاش'
            },
            created_by=self.admin_user
        )

    def test_contact_custom_fields_in_detail_view(self):
        res = self.client.get(reverse('contact_detail', kwargs={'pk': self.contact.id}))
        self.assertEqual(res.status_code, 200)
        self.assertIn('formatted_custom_fields', res.context)

        fields = res.context['formatted_custom_fields']
        lic_field = next(f for f in fields if f['setting'].field_key == 'license_number')
        self.assertEqual(lic_field['value'], 'LIC-998877')
        self.assertEqual(lic_field['display_value'], 'LIC-998877')

        vip_field = next(f for f in fields if f['setting'].field_key == 'is_vip_customer')
        self.assertEqual(vip_field['value'], True)
        self.assertEqual(vip_field['display_value'], 'نعم')

    def test_contact_create_with_custom_fields(self):
        post_data = {
            'name': 'مركز الأمل الطبي',
            'contact_type': 'organization',
            'relations': ['عميل'],
            'mobile_country_code': '+20',
            'mobile_number': '01011223344',
            'area_id': self.cairo.id,
            'custom_license_number': 'LIC-112233',
            'custom_is_vip_customer': 'on',
            'custom_annual_capacity': '1250',
            'custom_payment_terms_choice': 'أجل 30 يوم',
        }
        res = self.client.post(reverse('contact_create'), data=post_data)
        self.assertEqual(res.status_code, 302)

        new_contact = Contact.objects.filter(name='مركز الأمل الطبي').first()
        self.assertIsNotNone(new_contact)
        self.assertEqual(new_contact.custom_values.get('license_number'), 'LIC-112233')
        self.assertEqual(new_contact.custom_values.get('is_vip_customer'), True)
        self.assertEqual(new_contact.custom_values.get('annual_capacity'), 1250)
        self.assertEqual(new_contact.custom_values.get('payment_terms_choice'), 'أجل 30 يوم')

    def test_contact_edit_with_custom_fields(self):
        post_data = {
            'name': 'صيدلية الشفاء التجريبية المحدثة',
            'contact_type': 'organization',
            'relations': ['عميل'],
            'mobile_country_code': '+20',
            'mobile_number': '01099887766',
            'custom_license_number': 'LIC-UPDATED-001',
            'custom_is_vip_customer': 'on',
            'custom_annual_capacity': '800',
            'custom_payment_terms_choice': 'أجل 60 يوم',
        }
        res = self.client.post(reverse('contact_edit', kwargs={'pk': self.contact.id}), data=post_data)
        self.assertEqual(res.status_code, 302)

        self.contact.refresh_from_db()
        self.assertEqual(self.contact.name, 'صيدلية الشفاء التجريبية المحدثة')
        self.assertEqual(self.contact.custom_values.get('license_number'), 'LIC-UPDATED-001')
        self.assertEqual(self.contact.custom_values.get('annual_capacity'), 800)

    def test_contact_todos_no_blank_page_and_ajax_support(self):
        res = self.client.post(
            reverse('contact_create_todo', kwargs={'pk': self.contact.id}),
            data={'title': 'متابعة شحنة الأدوية مع المدير'}
        )
        self.assertEqual(res.status_code, 302)
        self.assertTrue(res.url.endswith('?tab=todos'))

        todo = ContactTodo.objects.filter(contact=self.contact, title='متابعة شحنة الأدوية مع المدير').first()
        self.assertIsNotNone(todo)
        self.assertFalse(todo.is_completed)

        res = self.client.post(
            reverse('contact_toggle_todo', kwargs={'pk': self.contact.id, 'todo_id': todo.id}),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data['status'], 'ok')
        self.assertTrue(data['is_completed'])

        res_detail = self.client.get(reverse('contact_detail', kwargs={'pk': self.contact.id}) + '?tab=todos')
        self.assertEqual(res_detail.status_code, 200)
        self.assertEqual(res_detail.context['active_tab'], 'todos')
        self.assertContains(res_detail, 'متابعة شحنة الأدوية مع المدير')

        res_del = self.client.post(
            reverse('contact_delete_todo', kwargs={'pk': self.contact.id, 'todo_id': todo.id}),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(res_del.status_code, 200)
        self.assertFalse(ContactTodo.objects.filter(id=todo.id).exists())

    def test_contact_timeline_top5_and_paginated_api(self):
        for i in range(8):
            ContactActivity.objects.create(
                contact=self.contact,
                activity_type='visit' if i % 2 == 0 else 'order',
                title=f'نشاط رقم {i + 1}',
                notes=f'تفاصيل النشاط رقم {i + 1}',
                performed_by=self.admin_user
            )

        res = self.client.get(reverse('contact_detail', kwargs={'pk': self.contact.id}))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.context['recent_timeline']), 5)
        self.assertGreaterEqual(res.context['total_timeline_count'], 8)

        api_url = reverse('contact_timeline_events', kwargs={'pk': self.contact.id})
        res = self.client.get(api_url + '?page=1&per_page=5')
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(len(data['events']), 5)
        self.assertEqual(data['page'], 1)
        self.assertTrue(data['has_next'])

    def test_contact_activities_tab_without_calls(self):
        res = self.client.get(reverse('contact_detail_overview', kwargs={'pk': self.contact.id}) + '?tab=activities')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.context['active_tab'], 'activities')
        content = res.content.decode('utf-8')
        self.assertIn('الزيارات', content)
        self.assertIn('الاتفاقيات', content)
        self.assertNotIn('المكالمات', content)


class ContactAPITests(TestCase):
    """Verifies Contacts REST / AJAX endpoints, security, and territorial scoping."""

    def setUp(self):
        self.client = Client()
        self.rep_role, _ = Role.objects.get_or_create(
            name=Role.ROLE_REP,
            defaults={'display_name': 'مندوب مبيعات', 'is_sales_team': True, 'is_rep': True}
        )
        self.manager_role, _ = Role.objects.get_or_create(
            name=Role.ROLE_MANAGER,
            defaults={'display_name': 'مدير فرع / منطقة', 'is_manager': True}
        )

        self.cairo_gov = Area.objects.create(code='CAI-GOV', name='القاهرة', area_type='governorate')
        self.dokki_subarea = Area.objects.create(code='DOK-BRK', name='حي الدقي', parent=self.cairo_gov, area_type='subarea')

        self.manager = User.objects.create_user(
            username='mgr_cairo',
            email='mgr_cairo@wea.com',
            password='Password123!',
            role=self.manager_role
        )
        self.manager.assigned_areas.add(self.cairo_gov)

        self.rep = User.objects.create_user(
            username='rep_cairo',
            email='rep_cairo@wea.com',
            password='Password123!',
            role=self.rep_role
        )
        self.rep.assigned_areas.add(self.cairo_gov)
        self.rep.assigned_areas.add(self.dokki_subarea)

    def test_get_subareas_api_auth_and_scoping(self):
        """Subareas API requires authentication and returns children scoped to user territory."""
        # 1. Anonymous user -> 401 Unauthorized
        anon_client = Client()
        anon_resp = anon_client.get(reverse('contact_subareas_api') + f'?area_id={self.cairo_gov.id}')
        self.assertEqual(anon_resp.status_code, 401)

        # 2. Manager with assigned Cairo area -> returns Cairo subareas
        self.client.force_login(self.manager)
        mgr_resp = self.client.get(reverse('contact_subareas_api') + f'?area_id={self.cairo_gov.id}')
        self.assertEqual(mgr_resp.status_code, 200)
        mgr_data = mgr_resp.json()
        self.assertIn('subareas', mgr_data)
        mgr_subarea_names = [s['name'] for s in mgr_data['subareas']]
        self.assertIn('حي الدقي', mgr_subarea_names)

        # 3. Representative assigned to Dokki brick -> returns assigned brick
        self.client.force_login(self.rep)
        rep_resp = self.client.get(reverse('contact_subareas_api') + f'?area_id={self.cairo_gov.id}')
        self.assertEqual(rep_resp.status_code, 200)
        rep_data = rep_resp.json()
        self.assertIn('subareas', rep_data)
        rep_subarea_names = [s['name'] for s in rep_data['subareas']]
        self.assertIn('حي الدقي', rep_subarea_names)
