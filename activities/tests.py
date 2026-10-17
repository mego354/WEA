from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from django.contrib.auth import get_user_model
from contacts.models import Contact
from catalog.models import Product
from .models import (
    AgreementType, Agreement, VisitTemplate,
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


