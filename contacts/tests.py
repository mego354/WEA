from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from contacts.models import Contact, ContactAddress, ContactComment, ContactTodo, ContactActivity
from master_data.models import Area

User = get_user_model()

class ContactsModuleTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(
            username='admin_test',
            email='admin_test@wea.com',
            password='TestPassword123!'
        )
        self.client = Client()
        self.client.force_login(self.user)

        # Create master data
        self.gov = Area.objects.create(code='GOV01', name='القاهرة', area_type='governorate')
        self.area = Area.objects.create(code='SUB01', name='مدينة نصر', area_type='subarea', parent=self.gov)

        # Create a contact
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

    def test_contact_properties(self):
        # Initials computation: 'صيدلية النجاح الجديدة' -> 'ص' + 'ا'
        self.assertEqual(self.contact.initials, 'صا')
        self.assertIn(self.contact.name, self.contact.display_tag)
        self.assertEqual(self.contact.status_label, 'Customer')

    def test_contacts_list_view(self):
        response = self.client.get(reverse('contacts_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'صيدلية النجاح الجديدة')
        self.assertContains(response, 'انشئ جهة اتصال')
        self.assertContains(response, 'تصدير البيانات')

    def test_contacts_list_filtering(self):
        # Search query
        response = self.client.get(reverse('contacts_list') + '?search=النجاح')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'صيدلية النجاح الجديدة')

        response_nomatch = self.client.get(reverse('contacts_list') + '?search=غير_موجود')
        self.assertEqual(response_nomatch.status_code, 200)
        self.assertNotContains(response_nomatch, 'صيدلية النجاح الجديدة')

        # Relation filter
        response_cust = self.client.get(reverse('contacts_list') + '?relation=customer')
        self.assertEqual(response_cust.status_code, 200)
        self.assertContains(response_cust, 'صيدلية النجاح الجديدة')

    def test_contacts_export_csv(self):
        response = self.client.get(reverse('contacts_export'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv; charset=utf-8-sig')
        content = response.content.decode('utf-8-sig')
        self.assertIn('صيدلية النجاح الجديدة', content)

    def test_contact_detail_view(self):
        response = self.client.get(reverse('contact_detail', args=[self.contact.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'صيدلية النجاح الجديدة')
        self.assertContains(response, 'نظرة عامة')
        self.assertContains(response, 'الأنشطة')
        self.assertContains(response, 'المبيعات')
        self.assertContains(response, 'المرفقات')
        self.assertContains(response, 'Todos')
        self.assertContains(response, 'المهام')

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

    def test_contact_todos(self):
        # Create Todo
        response = self.client.post(
            reverse('contact_create_todo', args=[self.contact.id]),
            {'title': 'متابعة سداد الشيك رقم 102'}
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.contact.todos.count(), 1)
        todo = self.contact.todos.first()
        self.assertFalse(todo.is_completed)

        # Toggle Todo
        response_toggle = self.client.post(
            reverse('contact_toggle_todo', args=[self.contact.id, todo.id]),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(response_toggle.status_code, 200)
        todo.refresh_from_db()
        self.assertTrue(todo.is_completed)

    def test_contact_address_management(self):
        # Add Address
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

        # Delete Address
        new_address = self.contact.addresses.get(title='مخزن فرعي')
        response_del = self.client.post(reverse('contact_delete_address', args=[self.contact.id, new_address.id]))
        self.assertEqual(response_del.status_code, 302)
        self.assertEqual(self.contact.addresses.count(), 1)

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
