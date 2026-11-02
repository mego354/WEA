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
from .services import can_end_visit, end_visit, can_start_visit, start_visit
from .forms import VisitTemplateForm

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
        from django.contrib.auth.models import Permission
        from accounts.models import Role
        self.rep_role = Role.objects.create(
            name='medical_rep_test_activities',
            display_name='مندوب دعاية تجريبي',
            is_rep=True,
            is_area_manager=False
        )
        rep_perms = Permission.objects.filter(
            codename__in=[
                'activities:visits/list', 'activities:visits/view', 'activities:visits/create', 'activities:visits/edit', 'activities:visits/export',
                'activities:planned/list', 'activities:planned/manage', 'activities:planned/export',
                'activities:agreements/list', 'activities:agreements/view', 'activities:agreements/create', 'activities:agreements/export',
                'module:activities', 'module:contacts'
            ]
        )
        self.rep_role.permissions.set(rep_perms)
        self.rep = User.objects.create_user(
            username='testrep',
            email='rep@example.com',
            password='Password123!',
            first_name='Ali',
            last_name='Rep',
            role=self.rep_role,
            bypass_location_verification=True
        )
        self.user = self.rep
        self.client.login(username='testrep', password='Password123!')

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
        self.ag_type, _ = AgreementType.objects.get_or_create(name='Cash money', defaults={'display_name_ar': 'نقدي'})

        # Create visit template
        self.template, _ = VisitTemplate.objects.get_or_create(
            name='Single visit (DR)',
            defaults={'display_name_ar': 'زيارة فردية لطبيب', 'active': True}
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
        self.client.login(username='testmanager', password='Password123!')
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
        self.assertFalse(item.is_executed)
        self.assertIsNotNone(item.visit)
        self.assertTrue(item.visit.is_planned)

        # Approve, start and finish the visit to complete execution
        item.visit.approval_status = 'approved'
        item.visit.save(update_fields=['approval_status'])
        self.client.post(reverse('visit_action', args=[item.visit.pk, 'start']))
        self.client.post(reverse('visit_action', args=[item.visit.pk, 'end']))
        item.refresh_from_db()
        self.assertTrue(item.is_executed)

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
        self.client.login(username='testmanager', password='Password123!')
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

        self.client.login(username='testmanager', password='Password123!')
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
        rep_role = Role.objects.filter(is_rep=True).first()
        self.rep = User.objects.create_user(
            username='rep_user',
            email='rep@wea.com',
            password='RepPassword123!',
            is_staff=False,
            is_superuser=False,
            bypass_location_verification=False,
            role=rep_role
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
            'template': self.template.id,
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
        """Visit outside 300m for non-bypassed rep requires exception request + reason and receives unverified status pending manager approval."""
        self.client.login(username='rep_user', password='RepPassword123!')
        today = timezone.now().date()
        # 1. Without exception request -> blocked with validation error (status 200)
        res_blocked = self.client.post(reverse('visit_create'), {
            'contact': self.customer.id,
            'template': self.template.id,
            'owner': self.rep.id,
            'date': today.strftime('%Y-%m-%d'),
            'latitude': '30.0444000',
            'longitude': '31.2357000',
            'device_accuracy': '20.0',
            'is_successful': 'on',
            'feedback': 'زيارة بعيدة عن الموقع'
        })
        self.assertEqual(res_blocked.status_code, 200)
        self.assertEqual(Visit.objects.filter(contact=self.customer, owner=self.rep).count(), 0)

        # 2. With exception request and mandatory reason -> created as pending manager approval
        res = self.client.post(reverse('visit_create'), {
            'contact': self.customer.id,
            'template': self.template.id,
            'owner': self.rep.id,
            'date': today.strftime('%Y-%m-%d'),
            'latitude': '30.0444000',
            'longitude': '31.2357000',
            'device_accuracy': '20.0',
            'request_distance_exception': '1',
            'bypass_reason': 'العميل انتقل إلى فرع مؤقت بالقاهرة',
            'is_successful': 'on',
            'feedback': 'زيارة بعيدة عن الموقع'
        })
        self.assertEqual(res.status_code, 302)
        visit = Visit.objects.filter(contact=self.customer, owner=self.rep).first()
        self.assertIsNotNone(visit)
        self.assertFalse(visit.location_verified)
        self.assertEqual(visit.verification_status, 'unverified')
        self.assertTrue(visit.requires_approval_due_to_distance)
        self.assertEqual(visit.approval_status, 'pending')
        self.assertGreater(float(visit.distance), 300.0)
        self.assertIn('خارج النطاق', visit.location_status)

    def test_location_verification_outside_geofence_with_superuser_bypass(self):
        """Superuser visit outside 300m receives force_bypassed status."""
        today = timezone.now().date()
        res = self.client.post(reverse('visit_create'), {
            'contact': self.customer.id,
            'template': self.template.id,
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
            'template': self.template.id,
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
        self.assertEqual(res_rep.status_code, 403)

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
        """Duplicate visit on the same date displays confirmation warning and does not silently create duplicates."""
        today = timezone.now().date()
        payload = {
            'contact': self.customer.id,
            'template': self.template.id,
            'owner': self.superuser.id,
            'date': today.strftime('%Y-%m-%d'),
            'is_successful': 'on',
            'feedback': 'الزيارة الأولى'
        }
        res1 = self.client.post(reverse('visit_create'), payload)
        self.assertEqual(res1.status_code, 302)
        first_visit = Visit.objects.filter(contact=self.customer).first()
        self.assertIsNotNone(first_visit)

        # Immediate duplicate attempt without confirmation -> displays warning (status 200) and does not create duplicate
        res2 = self.client.post(reverse('visit_create'), payload)
        self.assertEqual(res2.status_code, 200)
        self.assertTrue(res2.context.get('duplicate_warning'))

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
            'template': self.template.id,
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
            'template': self.template.id,
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
            'template': self.template.id,
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
            'template': self.template.id,
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
                'template': self.template.id,
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
            'template': self.template.id,
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
            'template': self.template.id,
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
            'template': self.template.id,
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
            'template': self.template.id,
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
                'template_id': self.template.id,
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
                'template_id': self.template.id,
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
                        allow_unplanned=True,
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
            'active': 'on',
            'allow_unplanned': 'on',
            'enable_product_detailing': 'on',
            'special_tolerance': 300,
            'restrict_account_types': ['pharmacy'],
            'restricted_roles': [str(self.rep_role.id)]
        })
        self.assertEqual(create_res.status_code, 302)
        new_tmpl = VisitTemplate.objects.filter(name='pharmacy_new_test').first()
        self.assertIsNotNone(new_tmpl)
        self.assertEqual(new_tmpl.display_name_ar, 'قالب صيدلية جديد')
        self.assertEqual(new_tmpl.restrict_account_types, ['pharmacy'])
        self.assertIn(self.rep_role, new_tmpl.restricted_roles.all())

        # Edit
        edit_res = self.client.post(reverse('visit_template_edit', args=[new_tmpl.pk]), {
            'display_name_ar': 'قالب صيدلية محدث',
            'display_name_en': 'Updated Pharmacy Template',
            'name': 'pharmacy_new_test',
            'active': 'on',
            'special_tolerance': 400,
            'restrict_account_types': ['pharmacy', 'store']
        })
        self.assertEqual(edit_res.status_code, 302)
        new_tmpl.refresh_from_db()
        self.assertEqual(new_tmpl.display_name_ar, 'قالب صيدلية محدث')
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
        self.assertEqual(res.status_code, 403)


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
                        allow_unplanned=True,
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
                        allow_unplanned=True,
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
        # Superuser creator is auto-approved; status is planned until explicitly started
        self.assertEqual(visit.approval_status, 'approved')
        self.assertEqual(visit.status, 'planned')

        # Start visit explicitly
        self.client.post(reverse('visit_action', args=[visit.pk, 'start']))
        visit.refresh_from_db()
        self.assertEqual(visit.status, 'started')

        # Submit answers and complete visit
        self.client.post(reverse('visit_detail', args=[visit.pk]), {
            'action': 'complete',
            'visit_outcome': 'successful',
            'feedback': 'زيارة ممتازة ومثمرة',
            f'question_{self.q_meet.id}': 'Yes',
            f'question_{self.q_details.id}': 'تمت مناقشة فاعلية الصنف وتأكيد كتابة 5 علب أسبوعياً',
            'detailed_products': [self.product1.id, self.product2.id],
        })
        visit.refresh_from_db()
        self.assertEqual(visit.status, 'finished')
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

        # Step 1: Create visit first with minimal information (Create First, Answer Later)
        create_res = self.client.post(reverse('visit_create'), {
            'contact': self.clinic_customer.id,
            'template': self.tmpl_dr.id,
            'owner': self.user.id,
            'date': today.strftime('%Y-%m-%d'),
        })
        self.assertEqual(create_res.status_code, 302)
        visit = Visit.objects.filter(contact=self.clinic_customer, template=self.tmpl_dr).first()
        self.assertIsNotNone(visit)
        self.assertEqual(visit.status, 'planned')

        # Approve and start visit
        visit.approval_status = 'approved'
        visit.save(update_fields=['approval_status'])
        self.client.post(reverse('visit_action', args=[visit.pk, 'start']))
        visit.refresh_from_db()
        self.assertEqual(visit.status, 'started')

        # Step 2: Attempt to complete visit without answering required question q_meet
        post_data = {
            'action': 'complete',
            'latitude': '31.2001',
            'longitude': '29.9187',
        }
        res = self.client.post(reverse('visit_detail', args=[visit.pk]), post_data, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
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

        # Verify plan item is executed only after visit ends
        plan_item.refresh_from_db()
        self.assertFalse(plan_item.is_executed)
        self.assertIsNotNone(plan_item.visit)
        self.assertEqual(plan_item.visit.is_planned, True)

        # Approve, start, and end visit
        plan_item.visit.approval_status = 'approved'
        plan_item.visit.save(update_fields=['approval_status'])
        self.client.post(reverse('visit_action', args=[plan_item.visit.pk, 'start']))
        self.client.post(reverse('visit_detail', args=[plan_item.visit.pk]), {
            'action': 'complete',
            f'question_{self.q_meet.id}': 'No',
            f'question_{self.q_reason_not.id}': 'الطبيب في مؤتمر علمي بالخارج',
        })
        plan_item.refresh_from_db()
        self.assertTrue(plan_item.is_executed)
        self.assertEqual(plan_item.visit.questionnaire_answers.get(str(self.q_reason_not.id)), 'الطبيب في مؤتمر علمي بالخارج')


from io import BytesIO
from PIL import Image
from django.core.files.uploadedfile import SimpleUploadedFile


def generate_test_image_file(name="evidence.jpg"):
    """Generate a valid test JPEG image file in memory."""
    buf = BytesIO()
    img = Image.new('RGB', (100, 100), color=(39, 190, 190))
    img.save(buf, format='JPEG')
    return SimpleUploadedFile(name, buf.getvalue(), content_type="image/jpeg")


class VisitWorkflowsAndPermissionsComprehensiveTestCase(TestCase):
    """
    Comprehensive acceptance test suite verifying all 12 Codex Requirements:
    1. Visit Template Account-Type Restrictions
    2. Audit & Enforce Visit Settings and Permissions
    3. Standardize Visit Lifecycle (Create First, Answer Later)
    4. Distinguish Planned and Unplanned Visits
    5. Lock Representative Assignment to Authenticated User
    6. Photo Evidence of Location & Superuser Audited Bypass
    7. Restrict المنتجات المشروحة to exactly 3 template types
    """

    def setUp(self):
        self.client = Client()

        # Roles
        self.admin_role = Role.objects.create(name='admin_test_role', display_name='مدير عام', is_rep=False, is_area_manager=True)
        self.rep_role = Role.objects.create(name='rep_test_role', display_name='مندوب دعاية', is_rep=True, is_area_manager=False)
        med_rep = Role.objects.filter(is_rep=True).exclude(pk=self.rep_role.pk).first()
        if med_rep:
            self.rep_role.permissions.set(med_rep.permissions.all())

        # Users
        self.superuser = User.objects.create_superuser(
            username='admin_boss', email='boss@example.com', password='Password123!',
            first_name='Boss', last_name='Admin'
        )
        self.rep_user = User.objects.create_user(
            username='field_rep_ahmed', email='ahmed@example.com', password='Password123!',
            first_name='Ahmed', last_name='Rep', role=self.rep_role
        )
        self.other_rep = User.objects.create_user(
            username='field_rep_sara', email='sara@example.com', password='Password123!',
            first_name='Sara', last_name='Rep', role=self.rep_role
        )

        # Contacts / Accounts
        self.pharmacy_contact = Contact.objects.create(
            name='صيدلية الشفاء الكبرى', code='PHARM01', account_type='Pharmacy',
            latitude=Decimal('31.2001'), longitude=Decimal('29.9187'), is_customer=True
        )
        self.clinic_contact = Contact.objects.create(
            name='عيادة الأمل التخصصية', code='CLINIC01', account_type='Clinic',
            latitude=Decimal('31.2005'), longitude=Decimal('29.9190'), is_customer=True
        )
        self.hospital_contact = Contact.objects.create(
            name='مستشفى السلام الدولي', code='HOSP01', account_type='Hospital',
            latitude=Decimal('31.2010'), longitude=Decimal('29.9200'), is_customer=True
        )

        # Products
        self.cat = ProductCategory.objects.create(name='أدوية عامة')
        self.product_a = Product.objects.create(category=self.cat, name='Medicine Alpha', sku_code='MED-A', is_active=True)
        self.product_b = Product.objects.create(category=self.cat, name='Medicine Beta', sku_code='MED-B', is_active=True)

        # Template 1: Pharmacy Only
        self.tmpl_pharmacy_only = VisitTemplate.objects.create(
            name='single_visit_pharmacy',
            display_name_ar='زيارة صيدلية فردية',
                        restrict_account_types=['Pharmacy'],
            active=True
        )
        self.q_stock = VisitTemplateQuestion.objects.create(
            template=self.tmpl_pharmacy_only,
            text_ar='هل الصنف متوفر في المخزون؟',
            question_type='boolean',
            is_required=True,
            order=1
        )

        # Template 2: Clinics & Hospitals
        self.tmpl_clinics_hospitals = VisitTemplate.objects.create(
            name='single_visit_dr',
            display_name_ar='زيارة فردية لطبيب',
                        restrict_account_types=['Clinic', 'Hospital'],
            active=True
        )
        self.q_prescribe = VisitTemplateQuestion.objects.create(
            template=self.tmpl_clinics_hospitals,
            text_ar='هل الطبيب يكتب الصنف؟',
            question_type='boolean',
            is_required=True,
            order=1
        )

        # Template 3: Healthy Day
        self.tmpl_healthy_day = VisitTemplate.objects.create(
            name='healthy_day',
            display_name_ar='اليوم الصحي',
                        restrict_account_types=['Pharmacy', 'Clinic', 'Hospital'],
            active=True
        )

        # Template 4: Coaching / General (does NOT support product detailing)
        self.tmpl_coaching = VisitTemplate.objects.create(
            name='coaching_visit',
            display_name_ar='زيارة مرافقة وتدريب',
                        active=True
        )

    # -------------------------------------------------------------------------
    # 1. TEMPLATE ACCOUNT-TYPE RESTRICTIONS
    # -------------------------------------------------------------------------
    def test_account_type_restrictions_persistence_and_enforcement(self):
        """A pharmacy-only template accepts pharmacies and rejects clinics/hospitals."""
        # Check model methods
        self.assertTrue(self.tmpl_pharmacy_only.is_contact_eligible(self.pharmacy_contact))
        self.assertFalse(self.tmpl_pharmacy_only.is_contact_eligible(self.clinic_contact))
        self.assertFalse(self.tmpl_pharmacy_only.is_contact_eligible(self.hospital_contact))

        self.assertTrue(self.tmpl_clinics_hospitals.is_contact_eligible(self.clinic_contact))
        self.assertTrue(self.tmpl_clinics_hospitals.is_contact_eligible(self.hospital_contact))
        self.assertFalse(self.tmpl_clinics_hospitals.is_contact_eligible(self.pharmacy_contact))

        # Test VisitForm clean() backend rejection
        self.client.login(username='admin_boss', password='Password123!')
        today = timezone.now().date()

        # Ineligible submission: Pharmacy template with Clinic contact -> rejected with error
        bad_res = self.client.post(reverse('visit_create'), {
            'contact': self.clinic_contact.id,
            'template': self.tmpl_pharmacy_only.id,
            'date': today.strftime('%Y-%m-%d'),
            'latitude': '31.2005',
            'longitude': '29.9190',
        })
        self.assertEqual(bad_res.status_code, 200)
        self.assertContains(bad_res, 'غير مخصص لنوع حساب العميل')

        # Eligible submission: Pharmacy template with Pharmacy contact -> accepted
        good_res = self.client.post(reverse('visit_create'), {
            'contact': self.pharmacy_contact.id,
            'template': self.tmpl_pharmacy_only.id,
            'date': today.strftime('%Y-%m-%d'),
            'latitude': '31.2001',
            'longitude': '29.9187',
        })
        self.assertEqual(good_res.status_code, 302)

    def test_unauthorized_user_cannot_modify_template_settings(self):
        """Field representatives are forbidden from creating or modifying templates."""
        self.client.login(username='field_rep_ahmed', password='Password123!')

        create_res = self.client.post(reverse('visit_template_create'), {
            'name': 'hacked_tmpl', 'display_name_ar': 'قالب غير مصرح'
        })
        self.assertIn(create_res.status_code, [302, 403])
        self.assertFalse(VisitTemplate.objects.filter(name='hacked_tmpl').exists())

        edit_res = self.client.post(reverse('visit_template_edit', args=[self.tmpl_pharmacy_only.pk]), {
            'display_name_ar': 'قالب ملعوب به'
        })
        self.assertIn(edit_res.status_code, [302, 403])
        self.tmpl_pharmacy_only.refresh_from_db()
        self.assertEqual(self.tmpl_pharmacy_only.display_name_ar, 'زيارة صيدلية فردية')

    # -------------------------------------------------------------------------
    # 2. CREATE FIRST, ANSWER LATER LIFECYCLE
    # -------------------------------------------------------------------------
    def test_create_first_answer_later_lifecycle(self):
        """
        Visits are created first with status='started' with minimal fields,
        then answered and completed on the detail screen.
        """
        self.client.login(username='field_rep_ahmed', password='Password123!')
        today = timezone.now().date()

        # Step 1: Create minimal visit record
        create_res = self.client.post(reverse('visit_create'), {
            'contact': self.pharmacy_contact.id,
            'template': self.tmpl_pharmacy_only.id,
            'date': today.strftime('%Y-%m-%d'),
            'latitude': '31.2001',
            'longitude': '29.9187',
        })
        self.assertEqual(create_res.status_code, 302)
        visit = Visit.objects.filter(contact=self.pharmacy_contact, owner=self.rep_user).first()
        self.assertIsNotNone(visit)
        self.assertEqual(visit.status, 'planned')
        self.assertEqual(visit.approval_status, 'pending')
        self.assertRedirects(create_res, reverse('visit_detail', args=[visit.pk]))

        # Manager approves visit, representative starts visit
        visit.approval_status = 'approved'
        visit.save(update_fields=['approval_status'])
        self.client.post(reverse('visit_action', args=[visit.pk, 'start']))
        visit.refresh_from_db()
        self.assertEqual(visit.status, 'started')

        # Step 2: Open visit detail screen (answering screen)
        detail_res = self.client.get(reverse('visit_detail', args=[visit.pk]))
        self.assertEqual(detail_res.status_code, 200)
        self.assertContains(detail_res, 'الزيارة جارية وقيد التوثيق')
        self.assertContains(detail_res, self.q_stock.text_ar)

        # Step 3: Save partial answers as draft (status remains 'started')
        draft_res = self.client.post(reverse('visit_detail', args=[visit.pk]), {
            'action': 'save_draft',
            f'question_{self.q_stock.id}': 'Yes',
            'feedback': 'مسودة مبدئية أثناء التواجد بالصيدلية'
        })
        self.assertEqual(draft_res.status_code, 302)
        visit.refresh_from_db()
        self.assertEqual(visit.status, 'started')
        self.assertEqual(visit.questionnaire_answers.get(str(self.q_stock.id)), 'Yes')
        self.assertEqual(visit.feedback, 'مسودة مبدئية أثناء التواجد بالصيدلية')

        # Step 4: Complete visit with photo evidence
        photo = generate_test_image_file("pharmacy_checkin.jpg")
        complete_res = self.client.post(reverse('visit_detail', args=[visit.pk]), {
            'action': 'complete',
            f'question_{self.q_stock.id}': 'Yes',
            'latitude': '31.2001',
            'longitude': '29.9187',
            'location_photo': photo,
            'visit_outcome': 'successful',
            'feedback': 'تم الانتهاء بنجاح ومراجعة طلبيات الصيدلية'
        })
        self.assertEqual(complete_res.status_code, 302)
        visit.refresh_from_db()
        self.assertEqual(visit.status, 'finished')
        self.assertTrue(visit.has_photo_evidence)
        self.assertEqual(visit.verification_status, 'verified')
        self.assertIsNotNone(visit.ended_at)

    def test_duplicate_submission_protection(self):
        """Repeated submission on the same date prompts for duplicate confirmation and does not silently create duplicates."""
        self.client.login(username='field_rep_ahmed', password='Password123!')
        today = timezone.now().date()

        post_data = {
            'contact': self.pharmacy_contact.id,
            'template': self.tmpl_pharmacy_only.id,
            'date': today.strftime('%Y-%m-%d'),
            'latitude': '31.2001',
            'longitude': '29.9187',
        }
        res1 = self.client.post(reverse('visit_create'), post_data)
        self.assertEqual(res1.status_code, 302)
        count_after_1 = Visit.objects.filter(contact=self.pharmacy_contact, owner=self.rep_user).count()

        # Immediate repeat click without confirm_duplicate -> displays warning (status 200) and does not create duplicate
        res2 = self.client.post(reverse('visit_create'), post_data)
        self.assertEqual(res2.status_code, 200)
        self.assertTrue(res2.context.get('duplicate_warning'))
        count_after_2 = Visit.objects.filter(contact=self.pharmacy_contact, owner=self.rep_user).count()
        self.assertEqual(count_after_1, count_after_2)

    # -------------------------------------------------------------------------
    # 3. PLANNED VS UNPLANNED CLASSIFICATION
    # -------------------------------------------------------------------------
    def test_planned_and_unplanned_classification_and_filters(self):
        """Visits are persistently classified as planned or unplanned and filtered cleanly."""
        today = timezone.now().date()

        # Unplanned visit
        v_unplanned = Visit.objects.create(
            contact=self.pharmacy_contact,
            owner=self.rep_user,
            date=today,
            is_planned=False,
            status='finished',
            created_by=self.rep_user
        )

        # Planned visit linked to planned item
        plan_day = PlannedVisitDay.objects.create(assignee=self.rep_user, date=today, created_by=self.rep_user)
        plan_item = PlannedVisitItem.objects.create(
            plan_day=plan_day, contact=self.clinic_contact, template=self.tmpl_clinics_hospitals, order=1
        )
        v_planned = Visit.objects.create(
            contact=self.clinic_contact,
            owner=self.rep_user,
            date=today,
            is_planned=True,
            status='finished',
            created_by=self.rep_user
        )
        plan_item.is_executed = True
        plan_item.visit = v_planned
        plan_item.save()

        # Verify model badges
        self.assertEqual(v_planned.plan_type_display_ar, 'زيارة مخططة')
        self.assertEqual(v_unplanned.plan_type_display_ar, 'زيارة خارج الخطة')

        # Test Filter: plan_type=planned
        self.client.login(username='admin_boss', password='Password123!')
        res_planned = self.client.get(reverse('visits_list') + '?plan_type=planned')
        self.assertEqual(res_planned.status_code, 200)
        self.assertContains(res_planned, f'#{v_planned.serial_num}')
        self.assertNotContains(res_planned, f'#{v_unplanned.serial_num}')

        # Test Filter: plan_type=unplanned
        res_unplanned = self.client.get(reverse('visits_list') + '?plan_type=unplanned')
        self.assertEqual(res_unplanned.status_code, 200)
        self.assertContains(res_unplanned, f'#{v_unplanned.serial_num}')
        self.assertNotContains(res_unplanned, f'#{v_planned.serial_num}')

    # -------------------------------------------------------------------------
    # 4. LOCKED REPRESENTATIVE ASSIGNMENT
    # -------------------------------------------------------------------------
    def test_representative_assignment_locked_for_field_reps(self):
        """Field representatives are locked to themselves and cannot spoof other reps."""
        self.client.login(username='field_rep_ahmed', password='Password123!')
        today = timezone.now().date()

        # Ahmed attempts to assign the visit to Sara
        res = self.client.post(reverse('visit_create'), {
            'contact': self.pharmacy_contact.id,
            'template': self.tmpl_pharmacy_only.id,
            'owner': self.other_rep.id,  # Tampered assignment attempt
            'date': today.strftime('%Y-%m-%d'),
            'latitude': '31.2001',
            'longitude': '29.9187',
        })
        self.assertEqual(res.status_code, 302)
        visit = Visit.objects.filter(contact=self.pharmacy_contact).latest('id')
        # Backend overrides/ignores spoofed owner -> assigns authenticated user Ahmed
        self.assertEqual(visit.owner, self.rep_user)
        self.assertNotEqual(visit.owner, self.other_rep)

    def test_superuser_can_assign_other_representative(self):
        """Superuser/Manager can assign visits to other representatives."""
        self.client.login(username='admin_boss', password='Password123!')
        today = timezone.now().date()

        res = self.client.post(reverse('visit_create'), {
            'contact': self.pharmacy_contact.id,
            'template': self.tmpl_pharmacy_only.id,
            'owner': self.other_rep.id,
            'date': today.strftime('%Y-%m-%d'),
            'latitude': '31.2001',
            'longitude': '29.9187',
        })
        self.assertEqual(res.status_code, 302)
        visit = Visit.objects.filter(contact=self.pharmacy_contact).latest('id')
        self.assertEqual(visit.owner, self.other_rep)

    # -------------------------------------------------------------------------
    # 5. PHOTO EVIDENCE & AUDITED SUPERUSER BYPASS
    # -------------------------------------------------------------------------
    def test_evidence_photo_protected_endpoint(self):
        """Evidence photo endpoint serves file to owner/manager and rejects unauthorized users with 403."""
        today = timezone.now().date()
        photo = generate_test_image_file("private_evidence.jpg")

        visit = Visit.objects.create(
            contact=self.pharmacy_contact,
            owner=self.rep_user,
            created_by=self.rep_user,
            date=today,
            status='finished',
            location_photo=photo
        )

        # Owner Ahmed can view photo
        self.client.login(username='field_rep_ahmed', password='Password123!')
        owner_res = self.client.get(reverse('visit_evidence_photo', args=[visit.pk]))
        self.assertEqual(owner_res.status_code, 200)

        # Other rep Sara is forbidden (403)
        self.client.login(username='field_rep_sara', password='Password123!')
        unauth_res = self.client.get(reverse('visit_evidence_photo', args=[visit.pk]))
        self.assertEqual(unauth_res.status_code, 403)

        # Superuser boss can view photo
        self.client.login(username='admin_boss', password='Password123!')
        admin_res = self.client.get(reverse('visit_evidence_photo', args=[visit.pk]))
        self.assertEqual(admin_res.status_code, 200)

    def test_superuser_bypass_audit_trail(self):
        """Authorized superuser bypass records bypassed_by, bypassed_at, and bypass_reason."""
        self.client.login(username='admin_boss', password='Password123!')
        today = timezone.now().date()

        visit = Visit.objects.create(
            contact=self.clinic_contact,
            owner=self.superuser,
            created_by=self.superuser,
            date=today,
            status='started'
        )

        bypass_res = self.client.post(reverse('visit_detail', args=[visit.pk]), {
            'action': 'complete',
            'force_bypass_location': '1',
            'bypass_reason': 'ضعف إشارة GPS داخل العيادة وتم التحقق هاتفياً'
        })
        self.assertEqual(bypass_res.status_code, 302)
        visit.refresh_from_db()
        self.assertEqual(visit.status, 'finished')
        self.assertEqual(visit.verification_status, 'force_bypassed')
        self.assertEqual(visit.bypassed_by, self.superuser)
        self.assertIsNotNone(visit.bypassed_at)
        self.assertEqual(visit.bypass_reason, 'ضعف إشارة GPS داخل العيادة وتم التحقق هاتفياً')

    # -------------------------------------------------------------------------
    # 6. PRODUCT DETAILING (المنتجات المشروحة) STRICT RESTRICTION
    # -------------------------------------------------------------------------
    def test_product_detailing_strictly_restricted_to_three_templates(self):
        """
        المنتجات المشروحة is supported only for:
        1. Single visit (DR)
        2. Single visit (Pharmacy)
        3. Healthy day
        Unsupported templates automatically clear and reject detailing.
        """
        # 1. DR visit supports detailing
        self.assertTrue(self.tmpl_clinics_hospitals.is_product_detailing_supported())
        self.assertTrue(self.tmpl_pharmacy_only.is_product_detailing_supported())
        self.assertTrue(self.tmpl_healthy_day.is_product_detailing_supported())
        self.assertFalse(self.tmpl_coaching.is_product_detailing_supported())

        today = timezone.now().date()

        # Detailing saved for DR visit
        v_dr = Visit.objects.create(
            contact=self.clinic_contact, template=self.tmpl_clinics_hospitals,
            owner=self.superuser, date=today, status='started'
        )
        self.client.login(username='admin_boss', password='Password123!')
        self.client.post(reverse('visit_detail', args=[v_dr.pk]), {
            'action': 'save_draft',
            'detailed_products': [self.product_a.id, self.product_b.id]
        })
        v_dr.refresh_from_db()
        self.assertEqual(v_dr.detailed_products.count(), 2)

        # Detailing cleared/hidden for coaching visit
        v_coaching = Visit.objects.create(
            contact=self.clinic_contact, template=self.tmpl_coaching,
            owner=self.superuser, date=today, status='started'
        )
        self.client.post(reverse('visit_detail', args=[v_coaching.pk]), {
            'action': 'save_draft',
            'detailed_products': [self.product_a.id]
        })
        v_coaching.refresh_from_db()
        self.assertEqual(v_coaching.detailed_products.count(), 0)

    # -------------------------------------------------------------------------
    # 8. QUESTION REMOVAL & DUPLICATE OUTCOME QUESTION SAFEGUARD
    # -------------------------------------------------------------------------
    def test_duplicate_outcome_question_completely_removed_from_active_workflow(self):
        """
        'هل كان يوم ناجح ؟ *' must never appear in active visit creation, answering,
        or preview screens, and must not block completion, while preserving historical answers.
        """
        # Deactivate / exclude duplicate question
        q_dup, _ = VisitTemplateQuestion.objects.get_or_create(
            template=self.tmpl_healthy_day,
            text_ar='هل كان يوم ناجح ؟',
            defaults={'question_type': 'single_choice', 'is_active': False, 'is_required': True, 'order': 1}
        )
        q_dup.is_active = False
        q_dup.save()

        q_valid = VisitTemplateQuestion.objects.create(
            template=self.tmpl_healthy_day,
            text_ar='ما هي نتائج اليوم الطبية والبيعية؟',
            question_type='text',
            is_active=True,
            is_required=True,
            order=2
        )

        # 1. Model get_active_questions excludes duplicate question
        active_qs = list(self.tmpl_healthy_day.get_active_questions())
        self.assertNotIn(q_dup, active_qs)
        self.assertIn(q_valid, active_qs)

        # 2. Template preview does not render the duplicate question
        self.client.login(username='admin_boss', password='Password123!')
        prev_res = self.client.get(reverse('visit_template_preview', args=[self.tmpl_healthy_day.pk]))
        self.assertEqual(prev_res.status_code, 200)
        self.assertNotContains(prev_res, 'هل كان يوم ناجح')

        # 3. Active visit detail answering screen does not render the duplicate question
        today = timezone.now().date()
        v_active = Visit.objects.create(
            contact=self.clinic_contact,
            template=self.tmpl_healthy_day,
            owner=self.superuser,
            date=today,
            status='started'
        )
        detail_res = self.client.get(reverse('visit_detail', args=[v_active.pk]))
        self.assertEqual(detail_res.status_code, 200)
        self.assertNotContains(detail_res, 'هل كان يوم ناجح')

        # 4. Finishing visit without answering duplicate question succeeds
        test_img = generate_test_image_file("healthy.jpg")
        complete_res = self.client.post(reverse('visit_detail', args=[v_active.pk]), {
            'action': 'complete',
            f'question_{q_valid.id}': 'تم تحقيق المستهدف بالكامل',
            'visit_outcome': 'successful',
            'latitude': '31.2005',
            'longitude': '29.9190',
            'device_accuracy': '15.0',
            'location_photo': test_img
        })
        self.assertEqual(complete_res.status_code, 302)
        v_active.refresh_from_db()
        self.assertEqual(v_active.status, 'finished')
        self.assertEqual(v_active.questionnaire_answers.get(str(q_valid.id)), 'تم تحقيق المستهدف بالكامل')
        self.assertNotIn(str(q_dup.id), v_active.questionnaire_answers)

        # 5. Historical records with past answers remain viewable for auditability
        v_hist = Visit.objects.create(
            contact=self.clinic_contact,
            template=self.tmpl_healthy_day,
            owner=self.superuser,
            date=today,
            status='finished',
            questionnaire_answers={str(q_dup.id): 'Yes', str(q_valid.id): 'سجل تاريخي ممتاز'}
        )
        hist_res = self.client.get(reverse('visit_detail', args=[v_hist.pk]))
        self.assertEqual(hist_res.status_code, 200)
        self.assertContains(hist_res, 'سجل تاريخي ممتاز')

    # -------------------------------------------------------------------------
    # 9. SAMPLE DISTRIBUTION FEATURE REMOVAL
    # -------------------------------------------------------------------------
    def test_sample_distribution_completely_removed_from_active_workflow(self):
        """
        'توزيع عينة طبية (اختياري)' must be stripped from active visit forms and APIs.
        Submitting samples in active requests is ignored and creates no VisitSampleItem.
        Existing historical samples remain intact for auditability.
        """
        self.client.login(username='admin_boss', password='Password123!')

        # 1. Active form does not contain sample distribution section or input
        create_page = self.client.get(reverse('visit_create'))
        self.assertEqual(create_page.status_code, 200)
        self.assertNotContains(create_page, 'توزيع عينة طبية')
        self.assertNotContains(create_page, 'name="sample_product"')
        self.assertNotContains(create_page, 'name="sample_quantity"')

        # 2. Submitting sample fields does not create VisitSampleItem
        today = timezone.now().date()
        post_data = {
            'contact': self.pharmacy_contact.id,
            'template': self.tmpl_pharmacy_only.id,
            'owner': self.superuser.id,
            'date': today.strftime('%Y-%m-%d'),
            'latitude': '31.2001',
            'longitude': '29.9187',
            'device_accuracy': '10.0',
            'sample_product': self.product_a.id,
            'sample_quantity': '10'
        }
        res = self.client.post(reverse('visit_create'), post_data)
        self.assertEqual(res.status_code, 302)
        created_visit = Visit.objects.filter(contact=self.pharmacy_contact).order_by('-id').first()
        self.assertIsNotNone(created_visit)
        self.assertEqual(created_visit.samples.count(), 0)

        # 3. Historical visit with samples preserves them and renders read-only dossier
        v_hist = Visit.objects.create(
            contact=self.pharmacy_contact,
            template=self.tmpl_pharmacy_only,
            owner=self.superuser,
            date=today,
            status='finished'
        )
        VisitSampleItem.objects.create(visit=v_hist, product=self.product_b, quantity=5, notes='عينة سابقة')
        hist_res = self.client.get(reverse('visit_detail', args=[v_hist.pk]))
        self.assertEqual(hist_res.status_code, 200)
        self.assertContains(hist_res, 'Medicine Beta')
        self.assertContains(hist_res, 'عينة سابقة')

    # -------------------------------------------------------------------------
    # 10. UNIFIED VISIT CREATION ROUTE & CLASSIFICATION
    # -------------------------------------------------------------------------
    def test_unified_visit_creation_route_and_classification_enforcement(self):
        """
        Both planned and unplanned visits use canonical /visits/create/.
        Planned visits associate the plan item and show 'زيارة مخططة'.
        Unplanned visits set is_planned=False and show 'زيارة خارج الخطة'.
        Tampered plan items or other rep's plans are securely rejected.
        """
        today = timezone.now().date()

        # 1. Planned visit from planned-visits/
        plan_day = PlannedVisitDay.objects.create(assignee=self.rep_user, date=today, created_by=self.superuser)
        plan_item = PlannedVisitItem.objects.create(
            plan_day=plan_day,
            contact=self.pharmacy_contact,
            template=self.tmpl_pharmacy_only,
            order=1
        )

        # Rep executes planned item -> redirects to /visits/create/
        self.client.login(username='field_rep_ahmed', password='Password123!')
        exec_res = self.client.get(reverse('planned_visit_item_execute', args=[plan_item.pk]))
        self.assertEqual(exec_res.status_code, 302)
        self.assertIn('/visits/create/', exec_res.url)
        self.assertIn(f'planned_item_id={plan_item.pk}', exec_res.url)

        # Canonical creation page displays 'زيارة مخططة'
        create_planned_page = self.client.get(exec_res.url)
        self.assertEqual(create_planned_page.status_code, 200)
        self.assertContains(create_planned_page, 'زيارة مخططة')

        # Submit planned visit
        post_planned = {
            'contact': self.pharmacy_contact.id,
            'template': self.tmpl_pharmacy_only.id,
            'planned_item_id': plan_item.pk,
            'date': today.strftime('%Y-%m-%d'),
            'latitude': '31.2001',
            'longitude': '29.9187',
            'device_accuracy': '10.0'
        }
        res_planned = self.client.post(reverse('visit_create'), post_planned)
        self.assertEqual(res_planned.status_code, 302)
        v_planned = Visit.objects.filter(contact=self.pharmacy_contact, is_planned=True).first()
        self.assertIsNotNone(v_planned)
        self.assertTrue(v_planned.is_planned)
        self.assertEqual(v_planned.plan_type_display_ar, 'زيارة مخططة')
        plan_item.refresh_from_db()
        self.assertFalse(plan_item.is_executed, "Planned item is not executed until visit is completed")
        self.assertEqual(plan_item.visit, v_planned)

        # Complete visit -> plan item becomes executed
        v_planned.approval_status = 'approved'
        v_planned.questionnaire_answers = {str(self.q_stock.id): 'Yes'}
        v_planned.save(update_fields=['approval_status', 'questionnaire_answers'])
        self.client.post(reverse('visit_action', args=[v_planned.pk, 'start']), {
            'latitude': '31.2001',
            'longitude': '29.9187',
            'device_accuracy': '10.0'
        })
        self.client.post(reverse('visit_action', args=[v_planned.pk, 'end']), {
            'latitude': '31.2001',
            'longitude': '29.9187',
            'device_accuracy': '10.0'
        })
        plan_item.refresh_from_db()
        self.assertTrue(plan_item.is_executed)

        # 2. Unplanned visit creation directly at /visits/create/
        create_unplanned_page = self.client.get(reverse('visit_create'))
        self.assertEqual(create_unplanned_page.status_code, 200)
        self.assertContains(create_unplanned_page, 'زيارة خارج الخطة')

        post_unplanned = {
            'contact': self.clinic_contact.id,
            'template': self.tmpl_clinics_hospitals.id,
            'date': today.strftime('%Y-%m-%d'),
            'latitude': '31.2005',
            'longitude': '29.9190',
            'device_accuracy': '12.0'
        }
        res_unplanned = self.client.post(reverse('visit_create'), post_unplanned)
        self.assertEqual(res_unplanned.status_code, 302)
        v_unplanned = Visit.objects.filter(contact=self.clinic_contact, is_planned=False).first()
        self.assertIsNotNone(v_unplanned)
        self.assertFalse(v_unplanned.is_planned)
        self.assertEqual(v_unplanned.plan_type_display_ar, 'زيارة خارج الخطة')

        # 3. Security: non-manager cannot execute another rep's plan item
        other_plan_day = PlannedVisitDay.objects.create(assignee=self.other_rep, date=today, created_by=self.superuser)
        other_item = PlannedVisitItem.objects.create(
            plan_day=other_plan_day,
            contact=self.hospital_contact,
            template=self.tmpl_clinics_hospitals,
            order=1
        )
        unauth_exec = self.client.get(reverse('planned_visit_item_execute', args=[other_item.pk]))
        self.assertEqual(unauth_exec.status_code, 403)

        # Security: non-manager tampering by submitting another rep's plan_item_id is rejected
        tampered_post = {
            'contact': self.hospital_contact.id,
            'template': self.tmpl_clinics_hospitals.id,
            'planned_item_id': other_item.pk,
            'date': today.strftime('%Y-%m-%d'),
            'latitude': '31.2010',
            'longitude': '29.9200',
            'device_accuracy': '10.0'
        }
        tampered_res = self.client.post(reverse('visit_create'), tampered_post)
        self.assertRedirects(tampered_res, reverse('visits_list'))
        self.assertFalse(Visit.objects.filter(contact=self.hospital_contact).exists())

    # -------------------------------------------------------------------------
    # 11. STANDARDIZE CLIENT DISPLAY (NAMES WITHOUT CODES)
    # -------------------------------------------------------------------------
    def test_client_display_names_without_codes(self):
        """
        Contact names must be displayed cleanly without appended/prepended codes
        in selectors, list views, cards, and detail pages, while preserving codes in DB
        and enabling internal searching by code.
        """
        # 1. Model __str__ and display_tag return clean name
        self.assertEqual(str(self.pharmacy_contact), self.pharmacy_contact.name)
        self.assertEqual(self.pharmacy_contact.display_tag, self.pharmacy_contact.name)
        self.assertNotIn(self.pharmacy_contact.code, str(self.pharmacy_contact))

        # 2. CustomerModelChoiceField returns clean name
        from activities.forms import CustomerModelChoiceField
        field = CustomerModelChoiceField(queryset=Contact.objects.all())
        self.assertEqual(field.label_from_instance(self.pharmacy_contact), self.pharmacy_contact.name)
        self.assertNotIn(self.pharmacy_contact.code, field.label_from_instance(self.pharmacy_contact))

        # 3. Visit detail renders client name cleanly
        today = timezone.now().date()
        v = Visit.objects.create(
            contact=self.pharmacy_contact,
            template=self.tmpl_pharmacy_only,
            owner=self.superuser,
            date=today,
            status='started'
        )
        self.client.login(username='admin_boss', password='Password123!')
        detail_res = self.client.get(reverse('visit_detail', args=[v.pk]))
        self.assertEqual(detail_res.status_code, 200)
        self.assertContains(detail_res, self.pharmacy_contact.name)
        # Verify no 'كود: PHARM01' block rendered in client dossier
        self.assertNotContains(detail_res, f'كود: {self.pharmacy_contact.code}')

        # 4. Search API supports search by code, but displays name without code tags
        search_res = self.client.get('/contacts/api/search/', {'q': self.pharmacy_contact.code})
        self.assertEqual(search_res.status_code, 200)
        data = search_res.json()
        self.assertGreater(data.get('count', 0), 0)
        found_item = data['results'][0]
        self.assertEqual(found_item['display_tag'], self.pharmacy_contact.name)
        self.assertEqual(found_item['name'], self.pharmacy_contact.name)
        # Database code preserved internally
        self.assertEqual(found_item['code'], self.pharmacy_contact.code)


import datetime
from master_data.models import Area
from accounts.models import SecurityAuditLog
from .models import ApprovalAuditLog
from .services import calculate_haversine_distance, build_visit_timeline


class VisitManagementImprovementsTestCase(TestCase):
    """
    Comprehensive test suite for Visit Planning, Distance Validation,
    Approval Workflow, Geographical Hierarchy, Timeline, and Bulk Planning (Sections 3–13).
    """

    def setUp(self):
        self.client = Client()

        # Geographical Hierarchy:
        # Cairo Main Area -> Nasr City Brick (B1), Maadi Brick (B2)
        # Alex Main Area -> Smouha Brick (B3)
        self.cairo_area = Area.objects.create(code='CAI', name='القاهرة', area_type='governorate')
        self.nasr_brick = Area.objects.create(code='CAI-NC', name='مدينة نصر', area_type='subarea', parent=self.cairo_area)
        self.maadi_brick = Area.objects.create(code='CAI-MD', name='المعادي', area_type='subarea', parent=self.cairo_area)

        self.alex_area = Area.objects.create(code='ALX', name='الإسكندرية', area_type='governorate')
        self.smouha_brick = Area.objects.create(code='ALX-SM', name='سموحة', area_type='subarea', parent=self.alex_area)

        # Roles & Permissions
        from django.contrib.auth.models import Permission
        perms = Permission.objects.filter(
            codename__in=[
                'activities:visits/list', 'activities:visits/view', 'activities:visits/create',
                'activities:visits/edit', 'activities:visits/approve', 'activities:visits/export',
                'activities:planned/list', 'activities:planned/manage', 'activities:planned/export',
                'module:activities', 'module:contacts', 'settings:location/manage', 'module:settings'
            ]
        )
        self.manager_role = Role.objects.create(
            name='area_mgr_imp', display_name='مدير منطقة', is_area_manager=True, is_rep=False
        )
        self.manager_role.permissions.set(perms)

        self.rep_role = Role.objects.create(
            name='med_rep_imp', display_name='مندوب دعاية', is_rep=True, is_area_manager=False
        )
        self.rep_role.permissions.set(perms.exclude(codename__in=['activities:visits/approve', 'settings:location/manage']))

        # Users
        self.superadmin = User.objects.create_superuser(
            username='sa_imp', email='sa_imp@wea.com', password='Password123!',
            first_name='Super', last_name='Admin'
        )
        self.cairo_manager = User.objects.create_user(
            username='mgr_cairo', email='mgr_cairo@wea.com', password='Password123!',
            first_name='Mahmoud', last_name='CairoMgr', role=self.manager_role
        )
        self.cairo_manager.assigned_areas.add(self.cairo_area)

        self.alex_manager = User.objects.create_user(
            username='mgr_alex', email='mgr_alex@wea.com', password='Password123!',
            first_name='Tarek', last_name='AlexMgr', role=self.manager_role
        )
        self.alex_manager.assigned_areas.add(self.alex_area)

        self.nasr_rep = User.objects.create_user(
            username='rep_nasr', email='rep_nasr@wea.com', password='Password123!',
            first_name='Karim', last_name='NasrRep', role=self.rep_role
        )
        self.nasr_rep.assigned_areas.add(self.nasr_brick)

        self.maadi_rep = User.objects.create_user(
            username='rep_maadi', email='rep_maadi@wea.com', password='Password123!',
            first_name='Youssef', last_name='MaadiRep', role=self.rep_role
        )
        self.maadi_rep.assigned_areas.add(self.maadi_brick)

        self.smouha_rep = User.objects.create_user(
            username='rep_smouha', email='rep_smouha@wea.com', password='Password123!',
            first_name='Hossam', last_name='SmouhaRep', role=self.rep_role
        )
        self.smouha_rep.assigned_areas.add(self.smouha_brick)

        # Contacts with known GPS coordinates
        # Nasr City Clinic: 30.0561, 31.3301
        self.contact_nasr_1 = Contact.objects.create(
            name='عيادة النصر التخصصية', code='NC001', account_type='Clinic',
            customer_category='A+', specialty='Cardiology',
            area=self.nasr_brick, latitude=Decimal('30.0561000'), longitude=Decimal('31.3301000'),
            is_customer=True, status='customer'
        )
        self.contact_nasr_2 = Contact.objects.create(
            name='صيدلية الشروق مدينة نصر', code='NC002', account_type='Pharmacy',
            customer_category='A', specialty='General',
            area=self.nasr_brick, latitude=Decimal('30.0565000'), longitude=Decimal('31.3305000'),
            is_customer=True, status='customer'
        )
        # Maadi Clinic: 29.9602, 31.2569
        self.contact_maadi = Contact.objects.create(
            name='عيادة المعادي الحديثة', code='MD001', account_type='Clinic',
            customer_category='B', specialty='Pediatrics',
            area=self.maadi_brick, latitude=Decimal('29.9602000'), longitude=Decimal('31.2569000'),
            is_customer=True, status='customer'
        )
        # Alex Smouha Pharmacy: 31.2156, 29.9553
        self.contact_smouha = Contact.objects.create(
            name='صيدلية سموحة المركزية', code='SM001', account_type='Pharmacy',
            customer_category='A+', specialty='General',
            area=self.smouha_brick, latitude=Decimal('31.2156000'), longitude=Decimal('29.9553000'),
            is_customer=True, status='customer'
        )

        # Templates:
        # 1. Default distance template
        self.default_template = VisitTemplate.objects.create(
            name='Default Dist Template', display_name_ar='قالب مسافة افتراضية',
            allow_unplanned=True, has_special_location_settings=False, special_tolerance=300, active=True
        )
        self.q_note = VisitTemplateQuestion.objects.create(
            template=self.default_template, text_ar='ما نتيجة المقابلة؟',
            question_type='text', is_required=True, is_active=True, order=1
        )
        # 2. Custom distance template (800m)
        self.custom_template = VisitTemplate.objects.create(
            name='Custom 800m Template', display_name_ar='قالب مسافة مخصصة 800 متر',
            allow_unplanned=True, has_special_location_settings=True, special_tolerance=800, active=True
        )

        # Configure LocationSettings
        self.loc_settings = LocationSettings.get_settings()
        self.loc_settings.tolerance = 300
        self.loc_settings.verify_visits = True
        self.loc_settings.allow_template_distance_override = True
        self.loc_settings.verify_unplanned_visit_distance = True
        self.loc_settings.verify_end_visit_distance = True
        self.loc_settings.bypass_reason_mandatory = True
        self.loc_settings.distance_bypass_requires_approval = True
        self.loc_settings.require_manager_approval_for_visits = True
        self.loc_settings.save()

    def test_01_dynamic_allowed_distance_default_vs_custom_template(self):
        """Section 3.A & 3.E: Allowed distance uses default tolerance or template custom distance when enabled."""
        # Default template -> 300m
        self.assertEqual(self.loc_settings.get_effective_tolerance(self.default_template), 300)
        # Custom template with override enabled -> 800m
        self.assertEqual(self.loc_settings.get_effective_tolerance(self.custom_template), 800)

        # When allow_template_distance_override is disabled in settings -> falls back to 300m
        self.loc_settings.allow_template_distance_override = False
        self.loc_settings.save()
        self.assertEqual(self.loc_settings.get_effective_tolerance(self.custom_template), 300)

        # Verify templates API exposes effective_tolerance
        self.loc_settings.allow_template_distance_override = True
        self.loc_settings.save()
        self.client.force_login(self.nasr_rep)
        res = self.client.get(reverse('visit_templates_api'), {'contact_id': self.contact_nasr_1.id})
        self.assertEqual(res.status_code, 200)
        results = {r['id']: r for r in res.json()['results']}
        self.assertEqual(results[self.default_template.id]['effective_tolerance'], 300)
        self.assertEqual(results[self.custom_template.id]['effective_tolerance'], 800)

    def test_02_unplanned_vs_planned_distance_validation_on_creation(self):
        """
        Section 3.B & 4:
        - Planned visits do NOT require distance validation during creation.
        - Unplanned visits DO require distance validation during creation.
        - Custom template threshold (800m) allows creation at ~550m where default (300m) blocks it.
        """
        self.client.force_login(self.nasr_rep)
        today = timezone.now().date().strftime('%Y-%m-%d')

        # 1. Planned visit created without GPS coordinates -> succeeds!
        res_planned = self.client.post(reverse('visit_create'), {
            'visit_type': 'planned',
            'is_planned': '1',
            'contact': self.contact_nasr_1.id,
            'template': self.default_template.id,
            'date': today,
        })
        self.assertEqual(res_planned.status_code, 302)
        v_planned = Visit.objects.filter(contact=self.contact_nasr_1, is_planned=True).first()
        self.assertIsNotNone(v_planned)
        self.assertTrue(v_planned.is_planned)
        self.assertEqual(v_planned.owner, self.nasr_rep)

        # 2. Unplanned visit at ~550m (~0.005 deg lat away: 30.0611, 31.3301) with default 300m template -> blocked!
        res_unplanned_blocked = self.client.post(reverse('visit_create'), {
            'visit_type': 'unplanned',
            'is_planned': '0',
            'contact': self.contact_nasr_2.id,
            'template': self.default_template.id,
            'date': today,
            'latitude': '30.0615000',
            'longitude': '31.3305000',
        })
        self.assertEqual(res_unplanned_blocked.status_code, 200)
        self.assertFalse(Visit.objects.filter(contact=self.contact_nasr_2).exists())

        # 3. Same ~550m distance with Custom 800m template -> succeeds within threshold!
        res_unplanned_custom = self.client.post(reverse('visit_create'), {
            'visit_type': 'unplanned',
            'is_planned': '0',
            'contact': self.contact_nasr_2.id,
            'template': self.custom_template.id,
            'date': today,
            'latitude': '30.0615000',
            'longitude': '31.3305000',
        })
        self.assertEqual(res_unplanned_custom.status_code, 302)
        v_custom = Visit.objects.filter(contact=self.contact_nasr_2).first()
        self.assertIsNotNone(v_custom)
        self.assertTrue(v_custom.location_verified)
        self.assertEqual(float(v_custom.allowed_distance), 800.0)

    def test_03_end_visit_distance_validation_rep_exception_vs_manager_bypass(self):
        """
        Section 3.C & 3.D:
        - Ending a visit validates distance for both planned and unplanned visits.
        - Representative outside threshold must request exception + provide mandatory reason -> marks visit pending approval & requires_approval_due_to_distance=True.
        - Manager/Superadmin can bypass directly without extra approval -> records bypassed_by, actual distance, allowed threshold, and reason.
        """
        today = timezone.now().date()

        # Create approved & started visit for nasr_rep
        v_rep = Visit.objects.create(
            contact=self.contact_nasr_1,
            template=self.default_template,
            owner=self.nasr_rep,
            created_by=self.nasr_rep,
            date=today,
            is_planned=True,
            status='started',
            approval_status='approved',
            approved_by=self.cairo_manager,
            approved_at=timezone.now(),
            started_at=timezone.now() - datetime.timedelta(minutes=20)
        )

        self.client.force_login(self.nasr_rep)
        # 1. Rep tries to end visit from 2km away without requesting exception -> blocked (400 on AJAX)
        res_block = self.client.post(
            reverse('visit_detail', args=[v_rep.pk]),
            {
                'action': 'complete',
                f'question_{self.q_note.id}': 'تمت الزيارة',
                'visit_outcome': 'successful',
                'latitude': '30.0750000',
                'longitude': '31.3500000',
            },
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(res_block.status_code, 400)
        v_rep.refresh_from_db()
        self.assertEqual(v_rep.status, 'started')

        # 2. Rep requests exception WITHOUT reason -> blocked
        res_no_reason = self.client.post(
            reverse('visit_detail', args=[v_rep.pk]),
            {
                'action': 'complete',
                f'question_{self.q_note.id}': 'تمت الزيارة',
                'visit_outcome': 'successful',
                'latitude': '30.0750000',
                'longitude': '31.3500000',
                'request_distance_exception': '1',
                'bypass_reason': '',
            },
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(res_no_reason.status_code, 400)

        # 3. Rep requests exception WITH reason -> visit ends, preserves answers, marks requires_approval_due_to_distance=True & approval_status='pending'
        res_exc = self.client.post(
            reverse('visit_detail', args=[v_rep.pk]),
            {
                'action': 'complete',
                f'question_{self.q_note.id}': 'تمت مقابلة الطبيب في العيادة البديلة',
                'visit_outcome': 'successful',
                'latitude': '30.0750000',
                'longitude': '31.3500000',
                'request_distance_exception': '1',
                'bypass_reason': 'الطبيب تواجد في المستشفى المجاور',
            }
        )
        self.assertEqual(res_exc.status_code, 302)
        v_rep.refresh_from_db()
        self.assertEqual(v_rep.status, 'finished')
        self.assertEqual(v_rep.approval_status, 'pending')
        self.assertTrue(v_rep.requires_approval_due_to_distance)
        self.assertEqual(v_rep.bypass_reason, 'الطبيب تواجد في المستشفى المجاور')
        self.assertEqual(v_rep.questionnaire_answers.get(str(self.q_note.id)), 'تمت مقابلة الطبيب في العيادة البديلة')
        self.assertTrue(ApprovalAuditLog.objects.filter(visit=v_rep, action='distance_exception_requested').exists())

        # 4. Manager bypasses distance directly on their own visit -> remains approved and records force_bypassed
        v_mgr = Visit.objects.create(
            contact=self.contact_nasr_1,
            template=self.default_template,
            owner=self.cairo_manager,
            created_by=self.cairo_manager,
            date=today,
            is_planned=False,
            status='started',
            approval_status='approved',
            started_at=timezone.now() - datetime.timedelta(minutes=15)
        )
        self.client.force_login(self.cairo_manager)
        res_mgr_bypass = self.client.post(
            reverse('visit_detail', args=[v_mgr.pk]),
            {
                'action': 'complete',
                f'question_{self.q_note.id}': 'متابعة إشرافية',
                'visit_outcome': 'successful',
                'latitude': '30.0800000',
                'longitude': '31.3600000',
                'force_bypass_location': '1',
                'bypass_reason': 'اجتماع مع الطبيب في مؤتمر طبي',
            }
        )
        self.assertEqual(res_mgr_bypass.status_code, 302)
        v_mgr.refresh_from_db()
        self.assertEqual(v_mgr.status, 'finished')
        self.assertEqual(v_mgr.approval_status, 'approved')
        self.assertFalse(v_mgr.requires_approval_due_to_distance)
        self.assertEqual(v_mgr.verification_status, 'force_bypassed')
        self.assertEqual(v_mgr.bypassed_by, self.cairo_manager)
        self.assertGreater(float(v_mgr.distance), 300.0)
        self.assertEqual(float(v_mgr.allowed_distance), 300.0)
        self.assertTrue(ApprovalAuditLog.objects.filter(visit=v_mgr, action='distance_bypass').exists())

    def test_04_simplified_creation_past_date_prevention_and_duplicate_confirmation(self):
        """
        Section 4.A, 4.B, 4.C, 4.D:
        - Creation form hides owner and defaults to logged-in user.
        - Does not require questions or creation comment during creation.
        - Unplanned visit prevents selecting past dates.
        - Duplicate visit on same date warns first and requires confirm_duplicate=1 to proceed.
        """
        self.client.force_login(self.nasr_rep)
        today = timezone.now().date()
        yesterday = today - datetime.timedelta(days=1)

        # 1. Unplanned visit with past date -> rejected!
        res_past = self.client.post(reverse('visit_create'), {
            'visit_type': 'unplanned',
            'contact': self.contact_nasr_1.id,
            'template': self.default_template.id,
            'date': yesterday.strftime('%Y-%m-%d'),
            'latitude': '30.0561000',
            'longitude': '31.3301000',
        })
        self.assertEqual(res_past.status_code, 200)
        self.assertContains(res_past, 'لا يمكن اختيار تاريخ في الماضي')
        self.assertEqual(Visit.objects.count(), 0)

        # 2. Create first visit on today -> succeeds without questions or feedback
        res_first = self.client.post(reverse('visit_create'), {
            'visit_type': 'unplanned',
            'contact': self.contact_nasr_1.id,
            'template': self.default_template.id,
            'date': today.strftime('%Y-%m-%d'),
            'latitude': '30.0561000',
            'longitude': '31.3301000',
        })
        self.assertEqual(res_first.status_code, 302)
        self.assertEqual(Visit.objects.filter(contact=self.contact_nasr_1, date=today).count(), 1)

        # 3. Check duplicate API returns has_duplicate=True
        dup_api_res = self.client.get(reverse('visit_check_duplicate_api'), {
            'contact_id': self.contact_nasr_1.id,
            'date': today.strftime('%Y-%m-%d'),
        })
        self.assertEqual(dup_api_res.status_code, 200)
        self.assertTrue(dup_api_res.json()['has_duplicate'])

        # 4. Second visit on same date WITHOUT confirm_duplicate -> warns and does NOT create
        res_dup_warn = self.client.post(reverse('visit_create'), {
            'visit_type': 'unplanned',
            'contact': self.contact_nasr_1.id,
            'template': self.default_template.id,
            'date': today.strftime('%Y-%m-%d'),
            'latitude': '30.0561000',
            'longitude': '31.3301000',
        })
        self.assertEqual(res_dup_warn.status_code, 200)
        self.assertTrue(res_dup_warn.context['duplicate_warning'])
        self.assertEqual(Visit.objects.filter(contact=self.contact_nasr_1, date=today).count(), 1)

        # 5. Second visit on same date WITH confirm_duplicate='1' -> creates second visit!
        res_dup_confirmed = self.client.post(reverse('visit_create'), {
            'visit_type': 'unplanned',
            'contact': self.contact_nasr_1.id,
            'template': self.default_template.id,
            'date': today.strftime('%Y-%m-%d'),
            'latitude': '30.0561000',
            'longitude': '31.3301000',
            'confirm_duplicate': '1',
        })
        self.assertEqual(res_dup_confirmed.status_code, 302)
        self.assertEqual(Visit.objects.filter(contact=self.contact_nasr_1, date=today).count(), 2)

    def test_05_post_approval_editing_invalidates_approval_and_preserves_history_and_timeline(self):
        """
        Section 5 & Section 6:
        - When a Representative edits an already-approved visit, approval_status resets to 'pending'
          and waiting_for_reapproval becomes True.
        - Previous approval records are preserved in ApprovalAuditLog.
        - Complete visit timeline shows creation, approval, edit with previous/new values, and reapproval.
        """
        today = timezone.now().date()
        visit = Visit.objects.create(
            contact=self.contact_nasr_1,
            template=self.default_template,
            owner=self.nasr_rep,
            created_by=self.nasr_rep,
            date=today,
            status='finished',
            approval_status='pending',
            feedback='الملاحظة الأصلية قبل التعديل',
            questionnaire_answers={str(self.q_note.id): 'إجابة أولية'},
            distance=Decimal('45.00'),
            allowed_distance=Decimal('300.00'),
            location_verified=True,
            verification_status='verified'
        )
        # Manager approves first
        self.client.force_login(self.cairo_manager)
        self.client.post(reverse('visit_action', args=[visit.pk, 'approve']), {
            'approval_notes': 'اعتماد أولي من مدير القاهرة'
        })
        visit.refresh_from_db()
        self.assertEqual(visit.approval_status, 'approved')
        self.assertFalse(visit.waiting_for_reapproval)

        # Representative edits the approved visit
        self.client.force_login(self.nasr_rep)
        edit_res = self.client.post(reverse('visit_edit', args=[visit.pk]), {
            'contact': self.contact_nasr_1.id,
            'template': self.default_template.id,
            'date': today.strftime('%Y-%m-%d'),
            'is_successful': 'on',
            'feedback': 'الملاحظة المعدلة بعد الاعتماد',
            f'question_{self.q_note.id}': 'إجابة محدثة بعد التعديل',
        })
        self.assertEqual(edit_res.status_code, 302)
        visit.refresh_from_db()

        # Approval is invalidated and waiting_for_reapproval is True
        self.assertEqual(visit.approval_status, 'pending')
        self.assertTrue(visit.waiting_for_reapproval)
        self.assertEqual(visit.feedback, 'الملاحظة المعدلة بعد الاعتماد')

        # Previous approval record is preserved AND edited_reapproval_required is logged
        self.assertTrue(ApprovalAuditLog.objects.filter(visit=visit, action='approved').exists())
        self.assertTrue(ApprovalAuditLog.objects.filter(visit=visit, action='edited_reapproval_required').exists())
        self.assertTrue(SecurityAuditLog.objects.filter(
            module='visits', record_id=str(visit.pk), action_type='VISIT_EDITED_REAPPROVAL_REQUIRED'
        ).exists())

        # Manager reapproves -> clears waiting_for_reapproval
        self.client.force_login(self.cairo_manager)
        self.client.post(reverse('visit_action', args=[visit.pk, 'approve']), {
            'approval_notes': 'إعادة اعتماد بعد مراجعة التعديلات'
        })
        visit.refresh_from_db()
        self.assertEqual(visit.approval_status, 'approved')
        self.assertFalse(visit.waiting_for_reapproval)

        # Timeline contains full lifecycle events and renders on visit_detail
        timeline = build_visit_timeline(visit)
        self.assertGreaterEqual(len(timeline), 4)
        detail_res = self.client.get(reverse('visit_detail', args=[visit.pk]))
        self.assertEqual(detail_res.status_code, 200)
        self.assertContains(detail_res, 'الخط الزمني الكامل للزيارة')
        self.assertContains(detail_res, 'تعديل بعد الاعتماد')
        self.assertContains(detail_res, 'اعتماد أولي من مدير القاهرة')
        self.assertContains(detail_res, 'إعادة اعتماد بعد مراجعة التعديلات')

    def test_06_geographical_hierarchy_enforcement_superadmin_manager_representative(self):
        """
        Section 7:
        - Representative (Nasr Brick): can only access/create visits in Nasr Brick; blocked from Maadi Brick (same governorate) and Smouha Brick (Alex).
        - Manager (Cairo Main Area): can access/create visits in both Nasr Brick and Maadi Brick; blocked from Smouha Brick (Alex).
        - Superadmin: full access across all areas and bricks.
        """
        today_str = timezone.now().date().strftime('%Y-%m-%d')

        # 1. Nasr Rep attempts to create visit for Maadi contact (sibling brick) -> blocked!
        self.client.force_login(self.nasr_rep)
        res_sibling = self.client.post(reverse('visit_create'), {
            'visit_type': 'planned',
            'is_planned': '1',
            'contact': self.contact_maadi.id,
            'template': self.default_template.id,
            'date': today_str,
        })
        self.assertEqual(res_sibling.status_code, 200)
        self.assertFalse(Visit.objects.filter(contact=self.contact_maadi).exists())

        # Customer search API for Nasr Rep returns only Nasr Brick contacts
        search_rep = self.client.get('/contacts/api/search/')
        rep_contact_ids = [c['id'] for c in search_rep.json()['results']]
        self.assertIn(self.contact_nasr_1.id, rep_contact_ids)
        self.assertNotIn(self.contact_maadi.id, rep_contact_ids)
        self.assertNotIn(self.contact_smouha.id, rep_contact_ids)

        # 2. Cairo Manager can create planned visits in both Nasr Brick and Maadi Brick, but NOT Alex Smouha Brick
        self.client.force_login(self.cairo_manager)
        res_mgr_maadi = self.client.post(reverse('visit_create'), {
            'visit_type': 'planned',
            'is_planned': '1',
            'contact': self.contact_maadi.id,
            'template': self.default_template.id,
            'date': today_str,
        })
        self.assertEqual(res_mgr_maadi.status_code, 302)
        self.assertTrue(Visit.objects.filter(contact=self.contact_maadi).exists())

        res_mgr_alex = self.client.post(reverse('visit_create'), {
            'visit_type': 'planned',
            'is_planned': '1',
            'contact': self.contact_smouha.id,
            'template': self.default_template.id,
            'date': today_str,
        })
        self.assertEqual(res_mgr_alex.status_code, 200)
        self.assertFalse(Visit.objects.filter(contact=self.contact_smouha).exists())

        # 3. Superadmin can create in Alex Smouha Brick
        self.client.force_login(self.superadmin)
        res_sa_alex = self.client.post(reverse('visit_create'), {
            'visit_type': 'planned',
            'is_planned': '1',
            'contact': self.contact_smouha.id,
            'template': self.default_template.id,
            'date': today_str,
        })
        self.assertEqual(res_sa_alex.status_code, 302)
        self.assertTrue(Visit.objects.filter(contact=self.contact_smouha).exists())

    def test_07_bulk_daily_planned_visit_scheduling_and_duplicate_prevention(self):
        """
        Section 8:
        - Bulk planned visit creation creates multiple PlannedVisitItem records for a selected date.
        - Prevents duplicate planned visits on the same date.
        - Enforces geographical restrictions (rejects out-of-brick contacts for representatives with 403).
        - Logs BULK_PLANNED_VISITS_CREATED in SecurityAuditLog.
        """
        self.client.force_login(self.nasr_rep)
        target_date = (timezone.now().date() + datetime.timedelta(days=2)).strftime('%Y-%m-%d')

        # 1. Attempting to include an unauthorized Maadi contact in bulk request -> rejected with 403!
        res_unauth = self.client.post(
            reverse('planned_visits_bulk_add'),
            {
                'date': target_date,
                'template_id': self.default_template.id,
                'contact_ids': [self.contact_nasr_1.id, self.contact_maadi.id],
            },
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(res_unauth.status_code, 403)
        self.assertEqual(PlannedVisitItem.objects.filter(plan_day__assignee=self.nasr_rep, plan_day__date=target_date).count(), 0)

        # 2. Bulk add 2 authorized Nasr City contacts -> succeeds!
        res_bulk = self.client.post(
            reverse('planned_visits_bulk_add'),
            {
                'date': target_date,
                'template_id': self.default_template.id,
                'contact_ids': [self.contact_nasr_1.id, self.contact_nasr_2.id],
                'notes': 'خطة عمل مجمعة لمدينة نصر',
            },
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(res_bulk.status_code, 200)
        data = res_bulk.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['created_count'], 2)

        # Verify DB records
        items = PlannedVisitItem.objects.filter(plan_day__assignee=self.nasr_rep, plan_day__date=target_date)
        self.assertEqual(items.count(), 2)

        # Verify AuditLogService recorded BULK_PLANNED_VISITS_CREATED
        self.assertTrue(SecurityAuditLog.objects.filter(
            module='activities', action_type='BULK_PLANNED_VISITS_CREATED'
        ).exists())

        # 3. Repeat same bulk request -> prevents duplicates (0 created, 2 skipped_duplicates)
        res_dup = self.client.post(
            reverse('planned_visits_bulk_add'),
            {
                'date': target_date,
                'template_id': self.default_template.id,
                'contact_ids': [self.contact_nasr_1.id, self.contact_nasr_2.id],
            },
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(res_dup.status_code, 400)
        dup_data = res_dup.json()
        self.assertEqual(dup_data['created_count'], 0)
        self.assertEqual(dup_data['skipped_duplicates_count'], 2)
        self.assertEqual(items.count(), 2)


class RefinedVisitRequirementsTestCase(TestCase):
    """
    Comprehensive tests for the 5 refined visit requirements:
    1. Visit Templates: Role Restrictions and Client-Based Filtering
    2. Bulk Daily Planning: Reuse the Existing Client Filters & Incremental 10-batch loading
    3. Individual Planned Visit: Connect Planning to Visit Creation
    4. Visit Date Validation: No Past Dates (all visit types)
    5. Visit Completion: Enforce Required Questions
    """
    def setUp(self):
        self.client = Client()
        today = timezone.now().date()
        self.today = today
        self.today_str = today.strftime('%Y-%m-%d')
        self.yesterday_str = (today - datetime.timedelta(days=1)).strftime('%Y-%m-%d')
        self.tomorrow_str = (today + datetime.timedelta(days=1)).strftime('%Y-%m-%d')

        # Roles
        self.role_rep = Role.objects.create(
            name='medical_rep_refined',
            display_name='مندوب دعاية متخصص',
            is_rep=True,
            is_area_manager=False
        )
        self.role_mgr = Role.objects.create(
            name='area_manager_refined',
            display_name='مدير منطقة متخصص',
            is_rep=False,
            is_area_manager=True
        )

        from django.contrib.auth.models import Permission
        all_perms = Permission.objects.filter(
            codename__in=[
                'activities:visits/list', 'activities:visits/view', 'activities:visits/create', 'activities:visits/edit',
                'activities:planned/list', 'activities:planned/manage',
                'settings:visitsTemplates/manage',
                'module:activities', 'module:contacts'
            ]
        )
        self.role_rep.permissions.set(all_perms)
        self.role_mgr.permissions.set(all_perms)

        # Users
        self.rep_user = User.objects.create_user(
            username='rep_refined',
            email='rep_refined@wea.com',
            password='Password123!',
            role=self.role_rep,
            bypass_location_verification=True
        )
        self.mgr_user = User.objects.create_user(
            username='mgr_refined',
            email='mgr_refined@wea.com',
            password='Password123!',
            role=self.role_mgr,
            bypass_location_verification=True
        )
        self.super_user = User.objects.create_user(
            username='super_refined',
            email='super_refined@wea.com',
            password='Password123!',
            is_superuser=True,
            is_staff=True,
            bypass_location_verification=True
        )

        # Clients with different account types
        self.pharmacy_contact = Contact.objects.create(
            name='صيدلية الشفاء الكبرى',
            code='PHARM_01',
            account_type='Pharmacy',
            customer_category='A',
            is_customer=True,
            status='customer'
        )
        self.clinic_contact = Contact.objects.create(
            name='عيادة النور التخصصية',
            code='CLINIC_01',
            account_type='Clinic',
            customer_category='B',
            is_customer=True,
            status='customer'
        )

        # Visit Templates
        # Template 1: General (no restrictions)
        self.tmpl_general = VisitTemplate.objects.create(
            name='General Template',
            display_name_ar='قالب زيارة عام',
            active=True
        )

        # Template 2: Role-restricted to manager only
        self.tmpl_manager_only = VisitTemplate.objects.create(
            name='Manager Audit Template',
            display_name_ar='قالب زيارة إشرافية للمدير فقط',
            active=True
        )
        self.tmpl_manager_only.restricted_roles.add(self.role_mgr)

        # Template 3: Account-type restricted to Pharmacy only
        self.tmpl_pharmacy_only = VisitTemplate.objects.create(
            name='Pharmacy Sales Template',
            display_name_ar='قالب زيارة صيدليات فقط',
            restrict_account_types=['Pharmacy'],
            active=True
        )

    def test_01_visit_template_role_restrictions(self):
        """Requirement 1: Templates restricted to specific roles appear only to authorized roles."""
        # 1. Check is_user_eligible logic
        self.assertTrue(self.tmpl_manager_only.is_user_eligible(self.mgr_user))
        self.assertTrue(self.tmpl_manager_only.is_user_eligible(self.super_user))
        self.assertFalse(self.tmpl_manager_only.is_user_eligible(self.rep_user))

        # 2. General template is eligible for rep, manager, and superuser
        self.assertTrue(self.tmpl_general.is_user_eligible(self.rep_user))
        self.assertTrue(self.tmpl_general.is_user_eligible(self.mgr_user))

        # 3. Test API endpoint filters out role-restricted templates
        self.client.force_login(self.rep_user)
        res_rep = self.client.get(reverse('visit_templates_api'))
        self.assertEqual(res_rep.status_code, 200)
        data_rep = res_rep.json()
        rep_tmpl_ids = [t['id'] for t in data_rep['templates']]
        self.assertIn(self.tmpl_general.id, rep_tmpl_ids)
        self.assertNotIn(self.tmpl_manager_only.id, rep_tmpl_ids)

        # Manager sees the restricted template
        self.client.force_login(self.mgr_user)
        res_mgr = self.client.get(reverse('visit_templates_api'))
        self.assertEqual(res_mgr.status_code, 200)
        data_mgr = res_mgr.json()
        mgr_tmpl_ids = [t['id'] for t in data_mgr['templates']]
        self.assertIn(self.tmpl_manager_only.id, mgr_tmpl_ids)

        # 4. VisitTemplateForm renders restricted_roles checkboxes and saves them properly
        self.client.force_login(self.super_user)
        form_data = {
            'name': 'New Restricted Form Template',
            'display_name_ar': 'قالب تجريبي للتحقق من النموذج',
            'active': 'on',
            'special_tolerance': '300',
            'restricted_roles': [self.role_rep.id],
            'restrict_account_types': ['Clinic'],
        }
        form = VisitTemplateForm(data=form_data)
        self.assertTrue(form.is_valid(), form.errors.as_text())
        saved_tmpl = form.save()
        self.assertIn(self.role_rep, saved_tmpl.restricted_roles.all())
        self.assertTrue(saved_tmpl.is_user_eligible(self.rep_user))
        self.assertFalse(saved_tmpl.is_user_eligible(self.mgr_user))

    def test_02_visit_template_client_filtering_and_common_intersection(self):
        """Requirement 1: Available templates depend on selected clients and calculate common eligible templates."""
        self.client.force_login(self.rep_user)

        # Single contact: pharmacy -> gets general AND pharmacy template
        res_pharm = self.client.get(f"{reverse('visit_templates_api')}?contact_id={self.pharmacy_contact.id}")
        self.assertEqual(res_pharm.status_code, 200)
        pharm_ids = [t['id'] for t in res_pharm.json()['templates']]
        self.assertIn(self.tmpl_general.id, pharm_ids)
        self.assertIn(self.tmpl_pharmacy_only.id, pharm_ids)

        # Single contact: clinic -> gets general, but NOT pharmacy template
        res_clinic = self.client.get(f"{reverse('visit_templates_api')}?contact_id={self.clinic_contact.id}")
        self.assertEqual(res_clinic.status_code, 200)
        clinic_ids = [t['id'] for t in res_clinic.json()['templates']]
        self.assertIn(self.tmpl_general.id, clinic_ids)
        self.assertNotIn(self.tmpl_pharmacy_only.id, clinic_ids)

        # Bulk group: both pharmacy AND clinic -> common templates is only general!
        res_both = self.client.get(f"{reverse('visit_templates_api')}?contact_ids={self.pharmacy_contact.id},{self.clinic_contact.id}")
        self.assertEqual(res_both.status_code, 200)
        both_ids = [t['id'] for t in res_both.json()['templates']]
        self.assertIn(self.tmpl_general.id, both_ids)
        self.assertNotIn(self.tmpl_pharmacy_only.id, both_ids)

    def test_03_mandatory_template_selection_enforcement(self):
        """Requirement 1: Selecting a visit template is REQUIRED for all creation methods."""
        self.client.force_login(self.rep_user)

        # 1. Planned visit add item without template -> rejected (400)
        res_plan = self.client.post(
            reverse('planned_visit_add_item'),
            {
                'assignee_id': self.rep_user.id,
                'date': self.tomorrow_str,
                'contact_id': self.pharmacy_contact.id,
                # No template_id!
            },
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(res_plan.status_code, 400)
        self.assertIn('قالب الزيارة إلزامي', res_plan.json().get('message', ''))

        # 2. Bulk planned visits without template -> rejected (400)
        res_bulk = self.client.post(
            reverse('planned_visits_bulk_add'),
            {
                'assignee_id': self.rep_user.id,
                'date': self.tomorrow_str,
                'contact_ids': [self.pharmacy_contact.id],
                # No template_id!
            },
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(res_bulk.status_code, 400)
        self.assertIn('قالب الزيارة إلزامي', res_bulk.json().get('message', ''))

        # 3. Unplanned visit creation without template -> form validation error (status 200)
        res_unplanned = self.client.post(reverse('visit_create'), {
            'visit_type': 'unplanned',
            'contact': self.pharmacy_contact.id,
            'date': self.today_str,
            # No template!
        })
        self.assertEqual(res_unplanned.status_code, 200)
        self.assertContains(res_unplanned, 'اختيار قالب الزيارة إلزامي')
        self.assertEqual(Visit.objects.count(), 0)

    def test_04_visit_date_validation_no_past_dates(self):
        """Requirement 4: Under no circumstances should any visit be created with a past date."""
        self.client.force_login(self.rep_user)

        # 1. Planned visit add item with yesterday date -> rejected
        res_plan_past = self.client.post(
            reverse('planned_visit_add_item'),
            {
                'assignee_id': self.rep_user.id,
                'date': self.yesterday_str,
                'contact_id': self.pharmacy_contact.id,
                'template_id': self.tmpl_general.id,
            },
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(res_plan_past.status_code, 400)
        self.assertIn('تاريخ سابق', res_plan_past.json().get('message', ''))

        # 2. Bulk planning with past date -> rejected
        res_bulk_past = self.client.post(
            reverse('planned_visits_bulk_add'),
            {
                'assignee_id': self.rep_user.id,
                'date': self.yesterday_str,
                'contact_ids': [self.pharmacy_contact.id],
                'template_id': self.tmpl_general.id,
            },
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(res_bulk_past.status_code, 400)
        self.assertIn('تاريخ سابق', res_bulk_past.json().get('message', ''))

        # 3. Unplanned visit with past date -> rejected
        res_visit_past = self.client.post(reverse('visit_create'), {
            'visit_type': 'unplanned',
            'contact': self.pharmacy_contact.id,
            'template': self.tmpl_general.id,
            'date': self.yesterday_str,
        })
        self.assertEqual(res_visit_past.status_code, 200)
        self.assertContains(res_visit_past, 'لا يمكن اختيار تاريخ في الماضي')
        self.assertEqual(Visit.objects.count(), 0)

        # 4. Valid future date succeeds for bulk planning
        res_bulk_ok = self.client.post(
            reverse('planned_visits_bulk_add'),
            {
                'assignee_id': self.rep_user.id,
                'date': self.tomorrow_str,
                'contact_ids': [self.pharmacy_contact.id],
                'template_id': self.tmpl_general.id,
            },
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(res_bulk_ok.status_code, 200)
        self.assertTrue(res_bulk_ok.json().get('success'))
        self.assertEqual(PlannedVisitItem.objects.filter(contact=self.pharmacy_contact, plan_day__date=self.tomorrow_str).count(), 1)

    def test_05_visit_completion_enforces_required_questions(self):
        """Requirement 5: Ending a visit requires all active required questions to be answered."""
        # Setup questions on general template
        q_req = VisitTemplateQuestion.objects.create(
            template=self.tmpl_general,
            text_ar='سؤال إلزامي: هل تم الترويج للمنتج بنجاح؟',
            question_type='single_select',
            options=['نعم', 'لا'],
            is_required=True,
            order=1
        )
        q_opt = VisitTemplateQuestion.objects.create(
            template=self.tmpl_general,
            text_ar='سؤال اختياري: أي ملاحظات إضافية؟',
            question_type='text',
            is_required=False,
            order=2
        )

        # Create active visit
        self.client.force_login(self.rep_user)
        visit = Visit.objects.create(
            contact=self.pharmacy_contact,
            template=self.tmpl_general,
            owner=self.rep_user,
            created_by=self.rep_user,
            date=self.today,
            status='started',
            approval_status='approved',
            location_verified=True,
            verification_status='verified'
        )

        # 1. can_end_visit check with no answers -> False
        can_end, reason = can_end_visit(visit, self.rep_user)
        self.assertFalse(can_end)
        self.assertIn('إلزامي', reason)

        # 2. Attempt to end visit via HTTP POST -> blocked
        res_end_blocked = self.client.post(reverse('visit_action', args=[visit.pk, 'end']))
        self.assertEqual(res_end_blocked.status_code, 302)
        visit.refresh_from_db()
        self.assertEqual(visit.status, 'started')  # Still started!

        # 3. Save whitespace-only answer -> still invalid
        visit.questionnaire_answers = {str(q_req.id): '   '}
        visit.save(update_fields=['questionnaire_answers'])
        can_end, _ = can_end_visit(visit, self.rep_user)
        self.assertFalse(can_end)

        # 4. Save valid answer for required question (optional question left empty) -> allowed!
        visit.questionnaire_answers = {str(q_req.id): 'نعم'}
        visit.save(update_fields=['questionnaire_answers'])
        can_end, reason = can_end_visit(visit, self.rep_user)
        self.assertTrue(can_end)
        self.assertEqual(reason, "")

        # 5. Successfully end visit via HTTP POST
        res_end_ok = self.client.post(reverse('visit_action', args=[visit.pk, 'end']))
        self.assertEqual(res_end_ok.status_code, 302)
        visit.refresh_from_db()
        self.assertEqual(visit.status, 'finished')

    def test_06_incremental_client_loading_and_filtering(self):
        """Requirement 2: Incremental client loader returns 10-batch results with total count and has_more."""
        # Create 15 dummy contacts to test pagination
        for i in range(15):
            Contact.objects.create(
                name=f'عميل تجريبي {i+1:02d}',
                code=f'BATCH_{i+1:02d}',
                account_type='Clinic',
                is_customer=True,
                status='customer'
            )

        self.client.force_login(self.super_user)

        # Batch 1: offset=0, limit=10
        res1 = self.client.get(
            f"{reverse('planned_visits_list')}?action=load_contacts&offset=0&limit=10",
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(res1.status_code, 200)
        data1 = res1.json()
        self.assertTrue(data1['success'])
        self.assertEqual(len(data1['contacts']), 10)
        self.assertTrue(data1['has_more'])
        self.assertGreaterEqual(data1['total_count'], 17)  # 15 dummy + 2 setup contacts

        # Batch 2: offset=10, limit=10
        res2 = self.client.get(
            f"{reverse('planned_visits_list')}?action=load_contacts&offset=10&limit=10",
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(res2.status_code, 200)
        data2 = res2.json()
        self.assertTrue(data2['success'])
        self.assertGreaterEqual(len(data2['contacts']), 7)

        # Verify no overlap between batch 1 and batch 2
        batch1_ids = {c['id'] for c in data1['contacts']}
        batch2_ids = {c['id'] for c in data2['contacts']}
        self.assertEqual(len(batch1_ids.intersection(batch2_ids)), 0)






