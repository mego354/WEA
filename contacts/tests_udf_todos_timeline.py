from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from contacts.models import Contact, ContactTodo, ContactActivity
from master_data.models import ContactFieldSetting, Area
from accounts.models import Role
import json

User = get_user_model()


class ContactUdfTodosTimelineTests(TestCase):
    def setUp(self):
        self.client = Client()

        self.superadmin_role, _ = Role.objects.get_or_create(
            name=Role.ROLE_SUPERADMIN,
            defaults={'display_name': 'مدير النظام الأعلى', 'is_super': True, 'is_system': True, 'is_active': True}
        )
        self.admin_user = User.objects.create_superuser(
            username='admin_contacts@wea.com',
            email='admin_contacts@wea.com',
            password='Password123!',
            name='Admin Contacts',
            role=self.superadmin_role
        )
        self.client.login(username='admin_contacts@wea.com', password='Password123!')

        self.cairo = Area.objects.create(name='القاهرة', area_type='governorate', is_company_area=False)

        # Create custom fields of various types
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

        # Create a contact
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
        """Contact detail overview must pass formatted_custom_fields to context."""
        res = self.client.get(reverse('contact_detail', kwargs={'pk': self.contact.id}))
        self.assertEqual(res.status_code, 200)
        self.assertIn('formatted_custom_fields', res.context)

        fields = res.context['formatted_custom_fields']
        field_keys = [f['setting'].field_key for f in fields]
        self.assertIn('license_number', field_keys)
        self.assertIn('is_vip_customer', field_keys)

        lic_field = next(f for f in fields if f['setting'].field_key == 'license_number')
        self.assertEqual(lic_field['value'], 'LIC-998877')
        self.assertEqual(lic_field['display_value'], 'LIC-998877')

        vip_field = next(f for f in fields if f['setting'].field_key == 'is_vip_customer')
        self.assertEqual(vip_field['value'], True)
        self.assertEqual(vip_field['display_value'], 'نعم')

    def test_contact_create_with_custom_fields(self):
        """Creating a contact must parse and store custom_values JSONField properly."""
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
        """Editing a contact must update custom_values and create an audit log."""
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
        self.assertEqual(self.contact.custom_values.get('payment_terms_choice'), 'أجل 60 يوم')

    def test_contact_todos_no_blank_page_and_ajax_support(self):
        """Creating, toggling, and deleting TODOs must not blank the page and support JSON."""
        # 1. Standard POST create todo redirects to lowercase ?tab=todos
        res = self.client.post(
            reverse('contact_create_todo', kwargs={'pk': self.contact.id}),
            data={'title': 'متابعة شحنة الأدوية مع المدير'}
        )
        self.assertEqual(res.status_code, 302)
        self.assertTrue(res.url.endswith('?tab=todos'))

        todo = ContactTodo.objects.filter(contact=self.contact, title='متابعة شحنة الأدوية مع المدير').first()
        self.assertIsNotNone(todo)
        self.assertFalse(todo.is_completed)

        # 2. AJAX toggle todo returns JSON and flips is_completed
        res = self.client.post(
            reverse('contact_toggle_todo', kwargs={'pk': self.contact.id, 'todo_id': todo.id}),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data['status'], 'ok')
        self.assertTrue(data['is_completed'])

        todo.refresh_from_db()
        self.assertTrue(todo.is_completed)

        # 3. Standard POST toggle todo redirects to lowercase ?tab=todos
        res = self.client.post(
            reverse('contact_toggle_todo', kwargs={'pk': self.contact.id, 'todo_id': todo.id})
        )
        self.assertEqual(res.status_code, 302)
        self.assertTrue(res.url.endswith('?tab=todos'))
        todo.refresh_from_db()
        self.assertFalse(todo.is_completed)

        # 4. Detail view with ?tab=todos renders cleanly without blanking
        res = self.client.get(reverse('contact_detail', kwargs={'pk': self.contact.id}) + '?tab=todos')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.context['active_tab'], 'todos')
        self.assertContains(res, 'متابعة شحنة الأدوية مع المدير')

        # 5. Detail view with uppercase ?tab=Todos normalizes to 'todos'
        res = self.client.get(reverse('contact_detail', kwargs={'pk': self.contact.id}) + '?tab=Todos')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.context['active_tab'], 'todos')

        # 6. AJAX delete todo
        res = self.client.post(
            reverse('contact_delete_todo', kwargs={'pk': self.contact.id, 'todo_id': todo.id}),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(res.status_code, 200)
        self.assertFalse(ContactTodo.objects.filter(id=todo.id).exists())

    def test_contact_timeline_top5_and_paginated_api(self):
        """Timeline shows top 5 on overview and provides paginated JSON API."""
        # Create 8 activity events
        for i in range(8):
            ContactActivity.objects.create(
                contact=self.contact,
                activity_type='visit' if i % 2 == 0 else 'order',
                title=f'نشاط رقم {i + 1}',
                notes=f'تفاصيل النشاط رقم {i + 1}',
                performed_by=self.admin_user
            )

        # 1. Detail view overview shows exactly top 5 recent activities
        res = self.client.get(reverse('contact_detail', kwargs={'pk': self.contact.id}))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.context['recent_timeline']), 5)
        self.assertGreaterEqual(res.context['total_timeline_count'], 8)

        # 2. Timeline events JSON API with pagination
        api_url = reverse('contact_timeline_events', kwargs={'pk': self.contact.id})
        res = self.client.get(api_url + '?page=1&per_page=5')
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(len(data['events']), 5)
        self.assertEqual(data['page'], 1)
        self.assertTrue(data['has_next'])

        # 3. Timeline events JSON API filter by activity_type='visit'
        res = self.client.get(api_url + '?activity_type=visit')
        self.assertEqual(res.status_code, 200)
        data = res.json()
        for evt in data['events']:
            self.assertEqual(evt['activity_type'], 'visit')

    def test_contact_activities_tab_without_calls(self):
        """Activities tab displays visits and agreements sections, and excludes calls."""
        res = self.client.get(reverse('contact_detail_overview', kwargs={'pk': self.contact.id}) + '?tab=activities')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.context['active_tab'], 'activities')
        content = res.content.decode('utf-8')
        self.assertIn('الزيارات', content)
        self.assertIn('الاتفاقيات', content)
        self.assertNotIn('المكالمات', content)
