import json
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from django.contrib.auth import get_user_model
from accounts.models import Role
from contacts.models import Contact
from catalog.models import Product, ProductCategory
from .models import (
    AgreementType, Agreement, VisitTemplate, VisitTemplateQuestion,
    PlannedVisitDay, PlannedVisitItem, Visit,
    VisitSampleItem
)

User = get_user_model()


class ActivitiesModuleTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.manager = User.objects.create_user(
            username='testmanager',
            email='manager@example.com',
            password='Password123!',
            first_name='Khaled',
            last_name='Manager',
            is_staff=True,
            is_superuser=True
        )
        self.user = self.manager
        self.client.login(username='testmanager', password='Password123!')

        # Create contact
        self.contact = Contact.objects.create(
            name='د. أحمد علي',
            code='DOC001',
            account_type='Clinic',
            specialty='Pediatrics',
            is_customer=True,
            status='customer'
        )

        # Create agreement type
        self.ag_type = AgreementType.objects.create(name='Cash money', display_name_ar='نقدي')

        # Create visit template
        self.template = VisitTemplate.objects.create(
            name='Single visit (DR)',
            display_name_ar='زيارة فردية لطبيب',
            active=True
        )

    def test_agreement_crud_and_status_transitions(self):
        # 1. Create Agreement
        response = self.client.post(reverse('agreements_list'), {
            'create_agreement': '1',
            'customer': self.contact.id,
            'title': 'اتفاقية رعاية عيادة',
            'type': self.ag_type.id,
            'amount': '3500.00',
            'date': timezone.now().date().strftime('%Y-%m-%d'),
            'description': 'دعم وتوفير مستلزمات'
        })
        self.assertEqual(response.status_code, 302)
        agreement = Agreement.objects.first()
        self.assertIsNotNone(agreement)
        self.assertEqual(agreement.title, 'اتفاقية رعاية عيادة')
        self.assertEqual(agreement.status, 'new')
        self.assertTrue(agreement.serial_num > 0)

        # 2. Detail View
        detail_res = self.client.get(reverse('agreement_detail', args=[agreement.pk]))
        self.assertEqual(detail_res.status_code, 200)
        self.assertContains(detail_res, 'اتفاقية رعاية عيادة')

        # 3. Approve Action
        approve_res = self.client.get(reverse('agreement_action', args=[agreement.pk, 'approve']))
        self.assertEqual(approve_res.status_code, 302)
        agreement.refresh_from_db()
        self.assertEqual(agreement.status, 'approved')

        # 4. Done Action
        done_res = self.client.get(reverse('agreement_action', args=[agreement.pk, 'done']))
        self.assertEqual(done_res.status_code, 302)
        agreement.refresh_from_db()
        self.assertEqual(agreement.status, 'done')

        # 5. Export Excel
        export_res = self.client.get(reverse('agreements_export'))
        self.assertEqual(export_res.status_code, 200)
        self.assertIn('application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', export_res['Content-Type'])

    def test_planned_visits_workflow_and_conversion(self):
        today = timezone.now().date()
        
        # 1. Add Planned Visit Item
        add_res = self.client.post(reverse('planned_visit_add_item'), {
            'assignee_id': self.user.id,
            'date': today.strftime('%Y-%m-%d'),
            'contact_id': self.contact.id,
            'template_id': self.template.id,
            'notes': 'خطة زيارة صباحية'
        })
        self.assertEqual(add_res.status_code, 302)

        plan_day = PlannedVisitDay.objects.get(assignee=self.user, date=today)
        self.assertIsNotNone(plan_day)
        item = plan_day.items.first()
        self.assertIsNotNone(item)
        self.assertEqual(item.contact, self.contact)
        self.assertFalse(item.is_executed)

        # 2. View Planned Visits List
        list_res = self.client.get(reverse('planned_visits_list'))
        self.assertEqual(list_res.status_code, 200)
        self.assertContains(list_res, self.contact.name)

        # 3. Execute / Start Visit from plan (routes to canonical registration)
        exec_res = self.client.get(reverse('planned_visit_item_execute', args=[item.pk]))
        self.assertEqual(exec_res.status_code, 302)
        self.assertIn('/visits/create/', exec_res.url)
        self.assertIn(f'planned_item_id={item.pk}', exec_res.url)

        # Submit canonical visit registration with planned_item_id context
        visit_res = self.client.post(reverse('visit_create'), {
            'contact': self.contact.id,
            'template': self.template.id,
            'owner': self.user.id,
            'date': today.strftime('%Y-%m-%d'),
            'planned_item_id': item.pk,
            'is_successful': 'on',
            'feedback': 'تم تنفيذ الزيارة بنجاح من الخطة'
        })
        self.assertEqual(visit_res.status_code, 302)

        item.refresh_from_db()
        self.assertTrue(item.is_executed)
        self.assertIsNotNone(item.visit)
        self.assertTrue(item.visit.is_planned)

        # 4. Export Planned Visits
        export_res = self.client.get(reverse('planned_visits_export'))
        self.assertEqual(export_res.status_code, 200)

    def test_visits_crud_and_approval(self):
        today = timezone.now().date()

        # 1. Create Unplanned Visit
        create_res = self.client.post(reverse('visit_create'), {
            'contact': self.contact.id,
            'template': self.template.id,
            'owner': self.user.id,
            'date': today.strftime('%Y-%m-%d'),
            'is_successful': 'on',
            'doubled': 'on',
            'feedback': 'تم التحدث مع الطبيب وشرح المستحضر الجديد'
        })
        self.assertEqual(create_res.status_code, 302)
        visit = Visit.objects.filter(contact=self.contact).first()
        self.assertIsNotNone(visit)
        self.assertEqual(visit.approval_status, 'pending')
        self.assertTrue(visit.doubled)

        # 2. Detail View
        detail_res = self.client.get(reverse('visit_detail', args=[visit.pk]))
        self.assertEqual(detail_res.status_code, 200)
        self.assertContains(detail_res, 'تم التحدث مع الطبيب')

        # 3. Manager Approval
        approve_res = self.client.post(reverse('visit_action', args=[visit.pk, 'approve']), {
            'approval_notes': 'معتمدة - عمل ممتاز'
        })
        self.assertEqual(approve_res.status_code, 302)
        visit.refresh_from_db()
        self.assertEqual(visit.approval_status, 'approved')

        # 4. Visits List & Filter
        list_res = self.client.get(reverse('visits_list') + '?approval_status=approved')
        self.assertEqual(list_res.status_code, 200)
        self.assertContains(list_res, str(visit.serial_num))

        # 5. Export Visits
        export_res = self.client.get(reverse('visits_export'))
        self.assertEqual(export_res.status_code, 200)

    def test_agreements_bulk_status(self):
        ag1 = Agreement.objects.create(
            customer=self.contact,
            title='اتفاقية 1',
            type=self.ag_type,
            amount=1000,
            status='new',
            created_by=self.manager
        )
        ag2 = Agreement.objects.create(
            customer=self.contact,
            title='اتفاقية 2',
            type=self.ag_type,
            amount=2000,
            status='new',
            created_by=self.manager
        )

        res = self.client.post(reverse('agreements_bulk_status'), {
            'status': 'approved',
            'selected_ids': [ag1.pk, ag2.pk]
        })
        self.assertEqual(res.status_code, 302)
        ag1.refresh_from_db()
        ag2.refresh_from_db()
        self.assertEqual(ag1.status, 'approved')
        self.assertEqual(ag2.status, 'approved')

    def test_rep_permissions_restriction(self):
        from accounts.models import Role
        rep_role = Role.objects.create(name='rep_role', display_name='مندوب دعاية', is_rep=True, is_area_manager=False)
        rep = User.objects.create_user(
            username='field_rep',
            email='field_rep@example.com',
            password='Password123!',
            role=rep_role,
            is_staff=False,
            is_superuser=False
        )

        rep_client = Client()
        rep_client.login(username='field_rep', password='Password123!')

        ag = Agreement.objects.create(
            customer=self.contact,
            title='اتفاقية ميدانية',
            type=self.ag_type,
            amount=1500,
            status='new',
            created_by=rep
        )

        # Rep attempts to approve agreement -> should not change status
        rep_client.get(reverse('agreement_action', args=[ag.pk, 'approve']))
        ag.refresh_from_db()
        self.assertEqual(ag.status, 'new')

        # Rep attempts bulk status -> should be blocked
        rep_client.post(reverse('agreements_bulk_status'), {
            'status': 'approved',
            'selected_ids': [ag.pk]
        })
        ag.refresh_from_db()
        self.assertEqual(ag.status, 'new')


from master_data.models import LocationSettings
from decimal import Decimal


class VisitAndLocationParityTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.superuser = User.objects.create_user(
            username='admin_user',
            email='admin@wea.com',
            password='AdminPassword123!',
            is_staff=True,
            is_superuser=True
        )
        self.rep = User.objects.create_user(
            username='rep_user',
            email='rep@wea.com',
            password='RepPassword123!',
            is_staff=False,
            is_superuser=False,
            bypass_location_verification=False
        )
        self.client.login(username='admin_user', password='AdminPassword123!')

        # Set default location settings
        self.loc_settings = LocationSettings.get_settings()
        self.loc_settings.tolerance = 300
        self.loc_settings.verify_visits = True
        self.loc_settings.auto_set_customer_location_in_visit = True
        self.loc_settings.save()

        # Create customer with known coordinates (Alexandria: 31.2000000, 29.9100000)
        self.customer = Contact.objects.create(
            name='صيدلية الإسكندرية الكبرى',
            code='ALX001',
            account_type='Pharmacy',
            customer_category='A',
            specialty='Community Pharmacy',
            latitude=Decimal('31.2000000'),
            longitude=Decimal('29.9100000'),
            is_customer=True,
            status='customer'
        )

        # Create customer WITHOUT coordinates
        self.new_customer = Contact.objects.create(
            name='عيادة الشروق التخصصية',
            code='CLIN999',
            account_type='Clinic',
            is_customer=True,
            status='customer'
        )

        # Create active visit template
        self.template = VisitTemplate.objects.create(
            name='Single visit (DR)',
            display_name_ar='زيارة فردية لطبيب',
            active=True
        )

    def test_customer_search_api_results_and_code(self):
        """API returns role-scoped customer list with [Code] Name and coordinates."""
        res = self.client.get('/contacts/api/search/?q=ALX001')
        self.assertEqual(res.status_code, 200)
        data = res.json()
        results = data.get('results', [])
        self.assertTrue(len(results) >= 1)
        item = results[0]
        self.assertEqual(item['id'], self.customer.id)
        self.assertEqual(item['code'], 'ALX001')
        self.assertTrue(item['has_saved_location'])
        self.assertAlmostEqual(float(item['latitude']), 31.2000, places=3)

    def test_location_verification_within_geofence(self):
        """Visit within 300m tolerance receives verified status."""
        today = timezone.now().date()
        # ~15 meters away from customer
        res = self.client.post(reverse('visit_create'), {
            'contact': self.customer.id,
            'owner': self.superuser.id,
            'date': today.strftime('%Y-%m-%d'),
            'latitude': '31.2001000',
            'longitude': '29.9101000',
            'device_accuracy': '15.0',
            'is_successful': 'on',
            'feedback': 'زيارة ممتازة ومطابقة للموقع الجغرافي'
        })
        self.assertEqual(res.status_code, 302)
        visit = Visit.objects.filter(contact=self.customer).first()
        self.assertIsNotNone(visit)
        self.assertTrue(visit.location_verified)
        self.assertEqual(visit.verification_status, 'verified')
        self.assertLess(float(visit.distance), 300.0)
        self.assertIn('ضمن النطاق', visit.location_status)

    def test_location_verification_outside_geofence_without_bypass(self):
        """Visit outside 300m for non-bypassed rep receives unverified status."""
        self.client.login(username='rep_user', password='RepPassword123!')
        today = timezone.now().date()
        # Location in Cairo (approx 180 km away from Alexandria)
        res = self.client.post(reverse('visit_create'), {
            'contact': self.customer.id,
            'owner': self.rep.id,
            'date': today.strftime('%Y-%m-%d'),
            'latitude': '30.0444000',
            'longitude': '31.2357000',
            'device_accuracy': '20.0',
            'is_successful': 'on',
            'feedback': 'زيارة بعيدة عن الموقع'
        })
        self.assertEqual(res.status_code, 302)
        visit = Visit.objects.filter(contact=self.customer, owner=self.rep).first()
        self.assertIsNotNone(visit)
        self.assertFalse(visit.location_verified)
        self.assertEqual(visit.verification_status, 'unverified')
        self.assertGreater(float(visit.distance), 300.0)
        self.assertIn('بعيد جدا', visit.location_status)

    def test_location_verification_outside_geofence_with_superuser_bypass(self):
        """Superuser visit outside 300m receives force_bypassed status."""
        today = timezone.now().date()
        res = self.client.post(reverse('visit_create'), {
            'contact': self.customer.id,
            'owner': self.superuser.id,
            'date': today.strftime('%Y-%m-%d'),
            'latitude': '30.0444000',
            'longitude': '31.2357000',
            'device_accuracy': '20.0',
            'is_successful': 'on',
            'feedback': 'زيارة مستثناة بواسطة مدير النظام'
        })
        self.assertEqual(res.status_code, 302)
        visit = Visit.objects.filter(contact=self.customer, owner=self.superuser).first()
        self.assertIsNotNone(visit)
        self.assertTrue(visit.location_verified)
        self.assertEqual(visit.verification_status, 'force_bypassed')
        self.assertEqual(visit.verification_status_display_ar, 'تم تجاهل التحقق بالقوة')
        self.assertIn('بعيد جدا', visit.location_status)

    def test_auto_set_customer_location_on_first_visit(self):
        """First visit check-in automatically saves GPS to customer dossier."""
        today = timezone.now().date()
        self.assertFalse(self.new_customer.has_saved_location)

        res = self.client.post(reverse('visit_create'), {
            'contact': self.new_customer.id,
            'owner': self.superuser.id,
            'date': today.strftime('%Y-%m-%d'),
            'latitude': '31.2200000',
            'longitude': '29.9300000',
            'device_accuracy': '10.0',
            'is_successful': 'on',
            'feedback': 'أول زيارة للعميل وحفظ الموقع تلقائياً'
        })
        self.assertEqual(res.status_code, 302)

        self.new_customer.refresh_from_db()
        self.assertTrue(self.new_customer.has_saved_location)
        self.assertAlmostEqual(float(self.new_customer.latitude), 31.2200, places=3)
        self.assertAlmostEqual(float(self.new_customer.longitude), 29.9300, places=3)

    def test_location_settings_superuser_only_enforcement(self):
        """Settings page /settings/location/ is strictly restricted to superusers."""
        # 1. Superuser has access
        res = self.client.get('/settings/location/')
        self.assertEqual(res.status_code, 200)

        # 2. Regular rep is denied access
        self.client.login(username='rep_user', password='RepPassword123!')
        res_rep = self.client.get('/settings/location/')
        self.assertEqual(res_rep.status_code, 302)
        self.assertIn('/', res_rep.url)

    def test_superuser_only_user_bypass_toggle(self):
        """Only superusers can toggle bypass_location_verification on users."""
        # Rep tries to toggle bypass on self -> denied
        self.client.login(username='rep_user', password='RepPassword123!')
        res = self.client.get(f'/auth/users/{self.rep.id}/toggle-bypass-location/')
        self.assertEqual(res.status_code, 302)
        self.rep.refresh_from_db()
        self.assertFalse(self.rep.bypass_location_verification)

        # Superuser toggles bypass on rep -> allowed
        self.client.login(username='admin_user', password='AdminPassword123!')
        res_admin = self.client.get(f'/auth/users/{self.rep.id}/toggle-bypass-location/')
        self.assertEqual(res_admin.status_code, 302)
        self.rep.refresh_from_db()
        self.assertTrue(self.rep.bypass_location_verification)

    def test_anti_duplicate_visit_prevention(self):
        """Duplicate submission within 60s is caught and redirected."""
        today = timezone.now().date()
        payload = {
            'contact': self.customer.id,
            'owner': self.superuser.id,
            'date': today.strftime('%Y-%m-%d'),
            'is_successful': 'on',
            'feedback': 'الزيارة الأولى'
        }
        res1 = self.client.post(reverse('visit_create'), payload)
        self.assertEqual(res1.status_code, 302)
        first_visit = Visit.objects.filter(contact=self.customer).first()

        # Immediate duplicate attempt
        res2 = self.client.post(reverse('visit_create'), payload)
        self.assertEqual(res2.status_code, 302)
        self.assertEqual(res2.url, reverse('visit_detail', args=[first_visit.pk]))

        # Count should remain 1
        self.assertEqual(Visit.objects.filter(contact=self.customer).count(), 1)

    # -------------------------------------------------------------------------
    # MANDATORY GPS MATRIX SCENARIOS (1 to 9)
    # -------------------------------------------------------------------------

    def test_gps_matrix_1_rep_valid_location(self):
        """Matrix Scenario 1: Representative with valid location within 300m -> verified."""
        self.client.login(username='rep_user', password='RepPassword123!')
        today = timezone.now().date()
        res = self.client.post(reverse('visit_create'), {
            'contact': self.customer.id,
            'owner': self.rep.id,
            'date': today.strftime('%Y-%m-%d'),
            'latitude': '31.2001000',
            'longitude': '29.9101000',
            'device_accuracy': '12.0',
            'feedback': 'Scen 1: Representative valid coords within tolerance'
        })
        self.assertEqual(res.status_code, 302)
        visit = Visit.objects.filter(owner=self.rep, feedback__contains='Scen 1').first()
        self.assertIsNotNone(visit)
        self.assertTrue(visit.location_verified)
        self.assertEqual(visit.verification_status, 'verified')
        self.assertIn('ضمن النطاق', visit.location_status)

    def test_gps_matrix_2_rep_permission_denied(self):
        """Matrix Scenario 2: Representative permission denied (no coordinates) -> rejected by server validation."""
        self.client.login(username='rep_user', password='RepPassword123!')
        today = timezone.now().date()
        initial_count = Visit.objects.count()

        res = self.client.post(reverse('visit_create'), {
            'contact': self.customer.id,
            'owner': self.rep.id,
            'date': today.strftime('%Y-%m-%d'),
            # No latitude or longitude provided (permission denied in browser)
            'feedback': 'Scen 2: Permission denied attempt'
        })
        # Rejects with re-rendered form (status 200) containing error message
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'تحديد الموقع الجغرافي (GPS) إلزامي للمندوب')
        self.assertEqual(Visit.objects.count(), initial_count)

    def test_gps_matrix_3_rep_location_unavailable_or_timeout(self):
        """Matrix Scenario 3: Representative location unavailable or timeout -> rejected."""
        self.client.login(username='rep_user', password='RepPassword123!')
        today = timezone.now().date()
        initial_count = Visit.objects.count()

        res = self.client.post(reverse('visit_create'), {
            'contact': self.customer.id,
            'owner': self.rep.id,
            'date': today.strftime('%Y-%m-%d'),
            'latitude': '',
            'longitude': '',
            'feedback': 'Scen 3: Timeout attempt'
        })
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'تحديد الموقع الجغرافي (GPS) إلزامي للمندوب')
        self.assertEqual(Visit.objects.count(), initial_count)

    def test_gps_matrix_4_rep_missing_or_invalid_coordinates(self):
        """Matrix Scenario 4: Representative invalid coordinates -> rejected."""
        self.client.login(username='rep_user', password='RepPassword123!')
        today = timezone.now().date()
        initial_count = Visit.objects.count()

        # Out-of-bounds latitude (999.0)
        res = self.client.post(reverse('visit_create'), {
            'contact': self.customer.id,
            'owner': self.rep.id,
            'date': today.strftime('%Y-%m-%d'),
            'latitude': '999.0000000',
            'longitude': '29.9100000',
            'feedback': 'Scen 4: Invalid lat'
        })
        self.assertEqual(res.status_code, 200)
        self.assertEqual(Visit.objects.count(), initial_count)

    def test_gps_matrix_5_rep_direct_api_request_without_valid_verification(self):
        """Matrix Scenario 5: Representative direct API/AJAX POST without GPS -> rejected with HTTP 400."""
        self.client.login(username='rep_user', password='RepPassword123!')
        today = timezone.now().date()
        initial_count = Visit.objects.count()

        res = self.client.post(
            reverse('visit_create'),
            {
                'contact': self.customer.id,
                'owner': self.rep.id,
                'date': today.strftime('%Y-%m-%d'),
                'feedback': 'Scen 5: Direct API bypass attempt'
            },
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(res.status_code, 400)
        data = res.json()
        self.assertFalse(data.get('success', True))
        self.assertIn('تحديد الموقع الجغرافي (GPS) إلزامي', str(data))
        self.assertEqual(Visit.objects.count(), initial_count)

    def test_gps_matrix_6_superuser_gps_unavailable(self):
        """Matrix Scenario 6: Superuser, GPS unavailable -> allowed past GPS check (force_bypassed)."""
        self.client.login(username='admin_user', password='AdminPassword123!')
        today = timezone.now().date()

        res = self.client.post(reverse('visit_create'), {
            'contact': self.customer.id,
            'owner': self.superuser.id,
            'date': today.strftime('%Y-%m-%d'),
            # No coordinates
            'feedback': 'Scen 6: Superuser GPS unavailable'
        })
        self.assertEqual(res.status_code, 302)
        visit = Visit.objects.filter(owner=self.superuser, feedback__contains='Scen 6').first()
        self.assertIsNotNone(visit)
        self.assertTrue(visit.location_verified)
        self.assertEqual(visit.verification_status, 'force_bypassed')
        self.assertIn('تم تجاهل التحقق بالقوة', visit.location_status)

    def test_gps_matrix_7_superuser_gps_permission_denied(self):
        """Matrix Scenario 7: Superuser, GPS permission denied -> allowed past GPS check."""
        self.client.login(username='admin_user', password='AdminPassword123!')
        today = timezone.now().date()

        res = self.client.post(reverse('visit_create'), {
            'contact': self.customer.id,
            'owner': self.superuser.id,
            'date': today.strftime('%Y-%m-%d'),
            'latitude': '',
            'longitude': '',
            'feedback': 'Scen 7: Superuser GPS permission denied'
        })
        self.assertEqual(res.status_code, 302)
        visit = Visit.objects.filter(owner=self.superuser, feedback__contains='Scen 7').first()
        self.assertIsNotNone(visit)
        self.assertTrue(visit.location_verified)
        self.assertEqual(visit.verification_status, 'force_bypassed')

    def test_gps_matrix_8_superuser_other_required_fields_invalid(self):
        """Matrix Scenario 8: Superuser submits but contact field is missing -> rejected normally."""
        self.client.login(username='admin_user', password='AdminPassword123!')
        today = timezone.now().date()
        initial_count = Visit.objects.count()

        res = self.client.post(reverse('visit_create'), {
            # Missing contact!
            'owner': self.superuser.id,
            'date': today.strftime('%Y-%m-%d'),
            'feedback': 'Scen 8: Missing contact'
        })
        # Must fail regular form validation
        self.assertEqual(res.status_code, 200)
        self.assertEqual(Visit.objects.count(), initial_count)

    def test_gps_matrix_9_non_superuser_impersonates_superuser(self):
        """Matrix Scenario 9: Non-superuser passes is_superuser / bypass params -> privilege bypass is rejected."""
        self.client.login(username='rep_user', password='RepPassword123!')
        today = timezone.now().date()
        initial_count = Visit.objects.count()

        # Attacker tries to pass spoofed superuser params in POST body
        res = self.client.post(reverse('visit_create'), {
            'contact': self.customer.id,
            'owner': self.rep.id,
            'date': today.strftime('%Y-%m-%d'),
            'is_superuser': 'True',
            'is_super_admin': '1',
            'bypass_location_verification': 'true',
            'can_bypass_location': 'true',
            'feedback': 'Scen 9: Spoofed superuser params'
        })
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'تحديد الموقع الجغرافي (GPS) إلزامي للمندوب')
        self.assertEqual(Visit.objects.count(), initial_count)

    # -------------------------------------------------------------------------
    # UNIFIED CUSTOMER SELECTION & PLANNED VISITS WORKFLOW TESTS
    # -------------------------------------------------------------------------

    def test_visit_templates_api(self):
        """API /activities/api/templates/ returns active visit templates."""
        res = self.client.get(reverse('visit_templates_api'))
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn('results', data)
        self.assertTrue(len(data['results']) >= 1)
        self.assertIn('display_name_ar', data['results'][0])

    def test_planned_visit_add_item_ajax_and_anti_duplicate(self):
        """Unified customer addition to plan via AJAX handles add and anti-duplicate."""
        today = timezone.now().date()
        date_str = today.strftime('%Y-%m-%d')

        # 1. Successful AJAX addition
        res1 = self.client.post(
            reverse('planned_visit_add_item'),
            {
                'assignee_id': self.rep.id,
                'date': date_str,
                'contact_id': self.customer.id,
                'notes': 'خطة من النموذج الموحد'
            },
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(res1.status_code, 200)
        data1 = res1.json()
        self.assertTrue(data1.get('success'))

        # Check record in DB
        item = PlannedVisitItem.objects.filter(contact=self.customer, plan_day__date=today).first()
        self.assertIsNotNone(item)
        self.assertEqual(item.notes, 'خطة من النموذج الموحد')

        # 2. Duplicate attempt
        res2 = self.client.post(
            reverse('planned_visit_add_item'),
            {
                'assignee_id': self.rep.id,
                'date': date_str,
                'contact_id': self.customer.id,
            },
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(res2.status_code, 400)
        data2 = res2.json()
        self.assertFalse(data2.get('success'))
        self.assertIn('مضاف بالفعل', data2.get('message', ''))


class VisitTemplatesManagementTestCase(TestCase):
    """Tests for Visit Templates CRUD, Question Builder, and Deletion Protection."""

    def setUp(self):
        self.admin = User.objects.create_superuser(
            username='admin_template_tester',
            email='admin_tmpl@test.com',
            password='Password123!'
        )
        self.rep_role = Role.objects.create(name='rep_tester', display_name='مندوب دعاية', is_rep=True)
        self.rep = User.objects.create_user(
            username='rep_template_tester',
            email='rep_tmpl@test.com',
            password='Password123!',
            role=self.rep_role
        )
        self.client.force_login(self.admin)

        self.template = VisitTemplate.objects.create(
            name='single_visit_dr_test',
            display_name_ar='زيارة فردية لطبيب (اختبار)',
            display_name_en='Single visit (DR) Test',
            mode='checkin_checkout',
            allow_unplanned=True,
            auto_approve_unplanned=False,
            enable_product_detailing=True,
            restrict_account_types=['clinic', 'hospital'],
            active=True
        )

        self.q1 = VisitTemplateQuestion.objects.create(
            template=self.template,
            text_ar='هل قابلت الطبيب؟',
            text_en='Did you meet the Dr?',
            question_type='single_choice',
            options=[{'text_ar': 'نعم', 'value': 'Yes'}, {'text_ar': 'لا', 'value': 'No'}],
            stage='all',
            is_required=True,
            order=1
        )

        self.q2 = VisitTemplateQuestion.objects.create(
            template=self.template,
            text_ar='ماذا حدث في الزيارة؟',
            question_type='textarea',
            stage='all',
            is_required=True,
            is_conditional=True,
            conditional_parent=self.q1,
            conditional_trigger_value='Yes',
            order=2
        )

    def test_templates_list_view(self):
        res = self.client.get(reverse('visit_templates_list'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'قوالب الزيارات')
        self.assertContains(res, 'زيارة فردية لطبيب (اختبار)')
        self.assertContains(res, 'Clinic')

    def test_template_create_and_edit(self):
        # Create
        create_res = self.client.post(reverse('visit_template_create'), {
            'display_name_ar': 'قالب صيدلية جديد',
            'display_name_en': 'New Pharmacy Template',
            'name': 'pharmacy_new_test',
            'mode': 'checkin_checkout',
            'active': 'on',
            'allow_unplanned': 'on',
            'enable_product_detailing': 'on',
            'visit_outcome_mode': 'enabled',
            'special_tolerance': 300,
            'restrict_account_types': ['pharmacy']
        })
        self.assertEqual(create_res.status_code, 302)
        new_tmpl = VisitTemplate.objects.filter(name='pharmacy_new_test').first()
        self.assertIsNotNone(new_tmpl)
        self.assertEqual(new_tmpl.display_name_ar, 'قالب صيدلية جديد')
        self.assertEqual(new_tmpl.restrict_account_types, ['pharmacy'])

        # Edit
        edit_res = self.client.post(reverse('visit_template_edit', args=[new_tmpl.pk]), {
            'display_name_ar': 'قالب صيدلية محدث',
            'display_name_en': 'Updated Pharmacy Template',
            'name': 'pharmacy_new_test',
            'mode': 'normal',
            'active': 'on',
            'visit_outcome_mode': 'enabled',
            'special_tolerance': 400,
            'restrict_account_types': ['pharmacy', 'store']
        })
        self.assertEqual(edit_res.status_code, 302)
        new_tmpl.refresh_from_db()
        self.assertEqual(new_tmpl.display_name_ar, 'قالب صيدلية محدث')
        self.assertEqual(new_tmpl.mode, 'normal')
        self.assertIn('store', new_tmpl.restrict_account_types)

    def test_template_preview_view(self):
        res = self.client.get(reverse('visit_template_preview', args=[self.template.pk]))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'هل قابلت الطبيب؟')
        self.assertContains(res, 'ماذا حدث في الزيارة؟')
        self.assertContains(res, 'معاينة')

    def test_template_toggle_status(self):
        self.assertTrue(self.template.active)
        res = self.client.post(reverse('visit_template_toggle_status', args=[self.template.pk]))
        self.assertEqual(res.status_code, 302)
        self.template.refresh_from_db()
        self.assertFalse(self.template.active)

    def test_template_delete_safety_with_and_without_visits(self):
        # 1. Template without visits -> hard deleted
        fresh_tmpl = VisitTemplate.objects.create(name='deletable_tmpl', display_name_ar='قالب قابل للحذف')
        res1 = self.client.post(reverse('visit_template_delete', args=[fresh_tmpl.pk]))
        self.assertEqual(res1.status_code, 302)
        self.assertFalse(VisitTemplate.objects.filter(pk=fresh_tmpl.pk).exists())

        # 2. Template with visits -> protected, auto-deactivated
        contact = Contact.objects.create(name='مستشفى النور', account_type='hospital')
        visit = Visit.objects.create(
            serial_num=9991,
            contact=contact,
            template=self.template,
            owner=self.admin
        )
        res2 = self.client.post(reverse('visit_template_delete', args=[self.template.pk]))
        self.assertEqual(res2.status_code, 302)
        self.template.refresh_from_db()
        # Verify not hard deleted, but deactivated to protect history
        self.assertTrue(VisitTemplate.objects.filter(pk=self.template.pk).exists())
        self.assertFalse(self.template.active)

    def test_question_builder_endpoints(self):
        # Add question
        add_res = self.client.post(reverse('template_question_add', args=[self.template.pk]), {
            'text_ar': 'احتياجات الطبيب',
            'text_en': 'Dr needs',
            'question_type': 'text',
            'stage': 'end_only',
            'is_required': 'on',
            'is_conditional': 'on',
            'conditional_parent': self.q1.id,
            'conditional_trigger_value': 'Yes'
        })
        self.assertEqual(add_res.status_code, 302)
        q3 = VisitTemplateQuestion.objects.filter(template=self.template, text_ar='احتياجات الطبيب').first()
        self.assertIsNotNone(q3)
        self.assertEqual(q3.stage, 'end_only')
        self.assertEqual(q3.conditional_parent_id, self.q1.id)

        # Edit question
        edit_res = self.client.post(reverse('template_question_edit', args=[q3.pk]), {
            'text_ar': 'احتياجات وملاحظات الطبيب',
            'question_type': 'textarea',
            'stage': 'all'
        })
        self.assertEqual(edit_res.status_code, 302)
        q3.refresh_from_db()
        self.assertEqual(q3.text_ar, 'احتياجات وملاحظات الطبيب')
        self.assertEqual(q3.question_type, 'textarea')

        # Reorder questions via AJAX
        reorder_res = self.client.post(
            reverse('template_questions_reorder', args=[self.template.pk]),
            json.dumps({'order': [q3.id, self.q1.id, self.q2.id]}),
            content_type='application/json'
        )
        self.assertEqual(reorder_res.status_code, 200)
        q3.refresh_from_db()
        self.assertEqual(q3.order, 1)

        # Delete question
        del_res = self.client.post(reverse('template_question_delete', args=[q3.pk]))
        self.assertEqual(del_res.status_code, 302)
        self.assertFalse(VisitTemplateQuestion.objects.filter(pk=q3.pk).exists())

    def test_rep_cannot_manage_templates(self):
        self.client.force_login(self.rep)
        res = self.client.get(reverse('visit_template_create'))
        self.assertEqual(res.status_code, 302)
        self.assertRedirects(res, reverse('visit_templates_list'))


class VisitTemplatesWorkflowIntegrationTestCase(TestCase):
    """Tests integrating templates throughout visit lifecycle (planned, unplanned, answers, detailing)."""

    def setUp(self):
        self.user = User.objects.create_superuser(
            username='workflow_user_tester',
            email='wf_user@test.com',
            password='Password123!'
        )
        self.client.force_login(self.user)

        self.clinic_customer = Contact.objects.create(
            name='عيادة الشفاء',
            code='CLI01',
            account_type='clinic',
            is_customer=True,
            status='customer'
        )
        self.pharmacy_customer = Contact.objects.create(
            name='صيدلية الأمل',
            code='PH01',
            account_type='pharmacy',
            is_customer=True,
            status='customer'
        )

        self.test_category = ProductCategory.objects.create(name='الأدوية التجريبية', code='EXP_CAT')
        self.product1 = Product.objects.create(category=self.test_category, name='Cipram 20mg', sku_code='CIP20', is_active=True)
        self.product2 = Product.objects.create(category=self.test_category, name='Amoxil 500mg', sku_code='AMX500', is_active=True)

        # Template 1: Clinic Doctor (auto_approve_unplanned=True)
        self.tmpl_dr = VisitTemplate.objects.create(
            name='single_visit_dr_wf',
            display_name_ar='زيارة فردية لطبيب',
            mode='checkin_checkout',
            allow_unplanned=True,
            auto_approve_unplanned=True,
            enable_product_detailing=True,
            restrict_account_types=['clinic', 'hospital'],
            active=True
        )
        self.q_meet = VisitTemplateQuestion.objects.create(
            template=self.tmpl_dr,
            text_ar='هل قابلت الطبيب؟',
            question_type='single_choice',
            options=[{'text_ar': 'نعم', 'value': 'Yes'}, {'text_ar': 'لا', 'value': 'No'}],
            stage='all',
            is_required=True,
            order=1
        )
        self.q_details = VisitTemplateQuestion.objects.create(
            template=self.tmpl_dr,
            text_ar='ماذا حدث في الزيارة؟',
            question_type='textarea',
            stage='all',
            is_required=True,
            is_conditional=True,
            conditional_parent=self.q_meet,
            conditional_trigger_value='Yes',
            order=2
        )
        self.q_reason_not = VisitTemplateQuestion.objects.create(
            template=self.tmpl_dr,
            text_ar='سبب عدم مقابلة الطبيب؟',
            question_type='textarea',
            stage='all',
            is_required=True,
            is_conditional=True,
            conditional_parent=self.q_meet,
            conditional_trigger_value='No',
            order=3
        )

        # Template 2: Pharmacy
        self.tmpl_pharmacy = VisitTemplate.objects.create(
            name='single_visit_pharmacy_wf',
            display_name_ar='زيارة صيدلية',
            mode='checkin_checkout',
            allow_unplanned=True,
            auto_approve_unplanned=False,
            enable_product_detailing=True,
            restrict_account_types=['pharmacy'],
            active=True
        )

    def test_visit_templates_api_filters_by_account_type(self):
        # 1. Query for clinic customer
        res_clinic = self.client.get(reverse('visit_templates_api'), {'contact_id': self.clinic_customer.id})
        self.assertEqual(res_clinic.status_code, 200)
        data_clinic = res_clinic.json().get('results', [])
        clinic_names = [t['name'] for t in data_clinic]
        self.assertIn('single_visit_dr_wf', clinic_names)
        self.assertNotIn('single_visit_pharmacy_wf', clinic_names)

        # 2. Query for pharmacy customer
        res_pharm = self.client.get(reverse('visit_templates_api'), {'contact_id': self.pharmacy_customer.id})
        self.assertEqual(res_pharm.status_code, 200)
        data_pharm = res_pharm.json().get('results', [])
        pharm_names = [t['name'] for t in data_pharm]
        self.assertIn('single_visit_pharmacy_wf', pharm_names)
        self.assertNotIn('single_visit_dr_wf', pharm_names)

    def test_unplanned_visit_creation_answers_and_product_detailing(self):
        today = timezone.now().date()

        # Submit with meeting = Yes: requires q_details, but q_reason_not is skipped
        post_data = {
            'contact': self.clinic_customer.id,
            'template': self.tmpl_dr.id,
            'owner': self.user.id,
            'date': today.strftime('%Y-%m-%d'),
            f'question_{self.q_meet.id}': 'Yes',
            f'question_{self.q_details.id}': 'تمت مناقشة فاعلية الصنف وتأكيد كتابة 5 علب أسبوعياً',
            'detailed_products': [self.product1.id, self.product2.id],
            'visit_outcome': 'successful',
            'feedback': 'زيارة ممتازة ومثمرة'
        }

        res = self.client.post(reverse('visit_create'), post_data)
        self.assertEqual(res.status_code, 302)

        visit = Visit.objects.filter(contact=self.clinic_customer).first()
        self.assertIsNotNone(visit)
        # Template has auto_approve_unplanned=True -> should be automatically approved
        self.assertEqual(visit.approval_status, 'approved')
        self.assertEqual(visit.visit_outcome, 'successful')

        # Check answers persisted properly in JSON
        answers = visit.questionnaire_answers
        self.assertEqual(answers.get(str(self.q_meet.id)), 'Yes')
        self.assertEqual(answers.get(str(self.q_details.id)), 'تمت مناقشة فاعلية الصنف وتأكيد كتابة 5 علب أسبوعياً')
        self.assertNotIn(str(self.q_reason_not.id), answers)

        # Check product detailing persisted
        detailed_ids = list(visit.detailed_products.values_list('id', flat=True))
        self.assertIn(self.product1.id, detailed_ids)
        self.assertIn(self.product2.id, detailed_ids)

        # Check visit detail view
        detail_res = self.client.get(reverse('visit_detail', args=[visit.pk]))
        self.assertEqual(detail_res.status_code, 200)
        self.assertContains(detail_res, 'زيارة فردية لطبيب')
        self.assertContains(detail_res, 'Cipram 20mg')
        self.assertContains(detail_res, 'تمت مناقشة فاعلية الصنف')

    def test_unplanned_visit_validation_enforces_required_fields(self):
        today = timezone.now().date()

        # Missing required answer to q_meet
        post_data = {
            'contact': self.clinic_customer.id,
            'template': self.tmpl_dr.id,
            'owner': self.user.id,
            'date': today.strftime('%Y-%m-%d'),
        }
        res = self.client.post(reverse('visit_create'), post_data, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(res.status_code, 400)
        data = res.json()
        self.assertFalse(data.get('success'))
        self.assertIn('إلزامي', data.get('message', ''))

    def test_planned_visit_execution_with_template(self):
        today = timezone.now().date()

        # 1. Create a planned day & item
        plan_day = PlannedVisitDay.objects.create(assignee=self.user, date=today, created_by=self.user)
        plan_item = PlannedVisitItem.objects.create(
            plan_day=plan_day,
            contact=self.clinic_customer,
            template=self.tmpl_dr,
            order=1,
            notes='زيارة مخططة للأسبوع الثالث'
        )

        # 2. Rep clicks Execute
        exec_res = self.client.get(reverse('planned_visit_item_execute', args=[plan_item.pk]))
        self.assertEqual(exec_res.status_code, 302)
        self.assertIn(f'planned_item_id={plan_item.pk}', exec_res.url)
        self.assertIn(f'contact_id={self.clinic_customer.id}', exec_res.url)

        # 3. Rep submits visit through form
        post_data = {
            'contact': self.clinic_customer.id,
            'template': self.tmpl_dr.id,
            'owner': self.user.id,
            'date': today.strftime('%Y-%m-%d'),
            'planned_item_id': plan_item.id,
            f'question_{self.q_meet.id}': 'No',
            f'question_{self.q_reason_not.id}': 'الطبيب في مؤتمر علمي بالخارج',
            'feedback': 'تأجيل المتابعة للأسبوع القادم'
        }
        submit_res = self.client.post(reverse('visit_create'), post_data)
        self.assertEqual(submit_res.status_code, 302)

        # Verify plan item executed
        plan_item.refresh_from_db()
        self.assertTrue(plan_item.is_executed)
        self.assertIsNotNone(plan_item.visit)
        self.assertEqual(plan_item.visit.is_planned, True)
        self.assertEqual(plan_item.visit.questionnaire_answers.get(str(self.q_reason_not.id)), 'الطبيب في مؤتمر علمي بالخارج')



