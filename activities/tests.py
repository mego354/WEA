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
        pday, _ = PlannedVisitDay.objects.get_or_create(assignee=self.nasr_rep, date=timezone.now().date())
        pitem = PlannedVisitItem.objects.create(plan_day=pday, order=1, contact=self.contact_nasr_1, template=self.default_template)
        res_planned = self.client.post(reverse('visit_create'), {
            'planned_item_id': pitem.id,
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
            status='started',
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
        pday_rep, _ = PlannedVisitDay.objects.get_or_create(assignee=self.nasr_rep, date=timezone.now().date())
        pitem_rep = PlannedVisitItem.objects.create(plan_day=pday_rep, order=1, contact=self.contact_maadi, template=self.default_template)
        res_sibling = self.client.post(reverse('visit_create'), {
            'planned_item_id': pitem_rep.id,
            'contact': self.contact_maadi.id,
            'template': self.default_template.id,
            'date': today_str,
        })
        self.assertEqual(res_sibling.status_code, 200)
        self.assertFalse(Visit.objects.filter(contact=self.contact_maadi).exists())
        pitem_rep.delete()

        # Customer search API for Nasr Rep returns only Nasr Brick contacts
        search_rep = self.client.get('/contacts/api/search/')
        rep_contact_ids = [c['id'] for c in search_rep.json()['results']]
        self.assertIn(self.contact_nasr_1.id, rep_contact_ids)
        self.assertNotIn(self.contact_maadi.id, rep_contact_ids)
        self.assertNotIn(self.contact_smouha.id, rep_contact_ids)

        # 2. Cairo Manager can create planned visits in both Nasr Brick and Maadi Brick, but NOT Alex Smouha Brick
        self.client.force_login(self.cairo_manager)
        pday_mgr, _ = PlannedVisitDay.objects.get_or_create(assignee=self.cairo_manager, date=timezone.now().date())
        pitem_mgr_maadi = PlannedVisitItem.objects.create(plan_day=pday_mgr, order=1, contact=self.contact_maadi, template=self.default_template)
        res_mgr_maadi = self.client.post(reverse('visit_create'), {
            'planned_item_id': pitem_mgr_maadi.id,
            'contact': self.contact_maadi.id,
            'template': self.default_template.id,
            'date': today_str,
        })
        self.assertEqual(res_mgr_maadi.status_code, 302)
        self.assertTrue(Visit.objects.filter(contact=self.contact_maadi).exists())

        pitem_mgr_alex = PlannedVisitItem.objects.create(plan_day=pday_mgr, order=2, contact=self.contact_smouha, template=self.default_template)
        res_mgr_alex = self.client.post(reverse('visit_create'), {
            'planned_item_id': pitem_mgr_alex.id,
            'contact': self.contact_smouha.id,
            'template': self.default_template.id,
            'date': today_str,
        })
        self.assertEqual(res_mgr_alex.status_code, 200)
        self.assertFalse(Visit.objects.filter(contact=self.contact_smouha).exists())
        pitem_mgr_alex.delete()

        # 3. Superadmin can create in Alex Smouha Brick
        self.client.force_login(self.superadmin)
        pday_sa, _ = PlannedVisitDay.objects.get_or_create(assignee=self.superadmin, date=timezone.now().date())
        pitem_sa = PlannedVisitItem.objects.create(plan_day=pday_sa, order=1, contact=self.contact_smouha, template=self.default_template)
        res_sa_alex = self.client.post(reverse('visit_create'), {
            'planned_item_id': pitem_sa.id,
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


class GPSValidationAndToleranceTestCase(TestCase):
    def setUp(self):
        from master_data.models import LocationSettings
        self.loc_settings = LocationSettings.get_settings()
        self.loc_settings.tolerance = 250
        self.loc_settings.allow_template_distance_override = True
        self.loc_settings.save()

    def test_calculate_haversine_distance_accuracy(self):
        from activities.services import calculate_haversine_distance
        # Identical points -> 0
        dist_same = calculate_haversine_distance(30.0444, 31.2357, 30.0444, 31.2357)
        self.assertEqual(dist_same, 0.0)

        # Cairo Tahrir (30.0444, 31.2357) to Cairo Tower (30.0459, 31.2243) is ~1.1km (1000m - 1250m)
        dist_tower = calculate_haversine_distance(30.0444, 31.2357, 30.0459, 31.2243)
        self.assertGreater(dist_tower, 1000)
        self.assertLess(dist_tower, 1250)

    def test_tolerance_hierarchy(self):
        from master_data.models import LocationSettings
        from activities.models import VisitTemplate

        loc = LocationSettings.get_settings()
        loc.tolerance = 200
        loc.allow_template_distance_override = True
        loc.save()

        # No template -> default tolerance
        self.assertEqual(loc.get_effective_tolerance(None), 200)

        # Template without special settings -> default tolerance
        template = VisitTemplate.objects.create(
            name='Regular Visit Template',
            display_name_ar='قالب زيارة عادي',
            has_special_location_settings=False
        )
        self.assertEqual(loc.get_effective_tolerance(template), 200)

        # Template with special tolerance of 500m
        template.has_special_location_settings = True
        template.special_tolerance = 500
        template.save()
        self.assertEqual(loc.get_effective_tolerance(template), 500)

        # If admin disables template override globally -> fallback to default tolerance
        loc.allow_template_distance_override = False
        loc.save()
        self.assertEqual(loc.get_effective_tolerance(template), 200)










import datetime
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.contrib.auth.models import Permission
from accounts.models import SecurityAuditLog
from accounts.permissions import get_scoped_queryset, can_user_access_object, get_user_managed_areas, get_user_managed_representatives
from master_data.models import Area, LocationSettings, SalesSettings, PurchaseSettings
from contacts.models import ContactAddress
from inventory.models import Warehouse
from sales.models import SalesOrder, SalesOrderItem
from sales.services import SalesOrderService
from purchases.models import PurchaseOrder, PurchaseOrderItem
from purchases.services import PurchaseOrderService
from activities.models import AgendaTodo, ApprovalAuditLog


class AgendaWorkflowTests(TestCase):
    def setUp(self):
        self.client = Client()

        # Roles
        self.manager_role = Role.objects.create(
            name='area_manager',
            display_name='مدير منطقة',
            is_area_manager=True
        )
        self.rep_role = Role.objects.create(
            name='sales_rep',
            display_name='مندوب مبيعات',
            is_rep=True
        )

        # Assign standard permissions
        perms = Permission.objects.filter(
            codename__in=[
                'activities:visits/list', 'activities:visits/view', 'activities:visits/create',
                'activities:visits/approve', 'activities:planned/list', 'activities:planned/manage',
                'module:activities', 'module:contacts'
            ]
        )
        for perm in perms:
            self.manager_role.permissions.add(perm)
            if perm.codename in ['activities:visits/list', 'activities:visits/view', 'activities:visits/create', 'activities:planned/list', 'module:activities', 'module:contacts']:
                self.rep_role.permissions.add(perm)

        # Regional hierarchy
        self.region_cairo = Area.objects.create(name='القاهرة الكبرى', code='AGN-CAI', area_type='governorate')
        self.subregion_nasr_city = Area.objects.create(name='مدينة نصر', code='AGN-NASR', parent=self.region_cairo, area_type='subarea')

        self.region_alex = Area.objects.create(name='الإسكندرية', code='AGN-ALX', area_type='governorate')
        self.subregion_smouha = Area.objects.create(name='سموحة', code='AGN-SMH', parent=self.region_alex, area_type='subarea')

        # Users
        self.rep_cairo = User.objects.create_user(
            username='rep_cairo', password='Password123!', role=self.rep_role
        )
        self.rep_cairo.assigned_areas.add(self.subregion_nasr_city)

        self.rep_alex = User.objects.create_user(
            username='rep_alex', password='Password123!', role=self.rep_role
        )
        self.rep_alex.assigned_areas.add(self.subregion_smouha)

        self.manager_cairo = User.objects.create_user(
            username='manager_cairo', password='Password123!', role=self.manager_role
        )
        self.manager_cairo.assigned_areas.add(self.region_cairo)

        self.superadmin = User.objects.create_superuser(
            username='superadmin', password='Password123!', email='admin@wea.com'
        )

        # Contacts
        self.contact_cairo = Contact.objects.create(
            name='د. أحمد القاهرة', area=self.subregion_nasr_city, status='lead'
        )
        self.contact_alex = Contact.objects.create(
            name='د. محمود الإسكندرية', area=self.subregion_smouha, status='lead'
        )

        self.template = VisitTemplate.objects.create(
            name='single_visit_dr', display_name_ar='زيارة فردية - أطباء', active=True
        )

        self.today = timezone.now().date()
        self.tomorrow = self.today + datetime.timedelta(days=1)

    def test_representative_can_view_own_agenda(self):
        """Rep can view their own agenda and sees empty state when no visits are planned."""
        self.client.login(username='rep_cairo', password='Password123!')
        res = self.client.get(reverse('agenda'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'جدول الاعمال')
        self.assertContains(res, 'لا خطط أخرى لهذا اليوم')

    def test_representative_cannot_access_other_representative_agenda(self):
        """Rep cannot pass ?assignee=<other_user_id> to view another rep's agenda."""
        self.client.login(username='rep_cairo', password='Password123!')
        res = self.client.get(reverse('agenda'), {'assignee': self.rep_alex.id})
        self.assertEqual(res.status_code, 403)

    def test_manager_can_access_subordinate_agenda(self):
        """Manager of Cairo can view the agenda of a representative in their subregion."""
        self.client.login(username='manager_cairo', password='Password123!')
        res = self.client.get(reverse('agenda'), {'assignee': self.rep_cairo.id})
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'rep_cairo')

    def test_manager_cannot_access_unrelated_regional_representative_agenda(self):
        """Manager of Cairo cannot view the agenda of an Alexandria representative."""
        self.client.login(username='manager_cairo', password='Password123!')
        res = self.client.get(reverse('agenda'), {'assignee': self.rep_alex.id})
        self.assertEqual(res.status_code, 403)

    def test_superadmin_has_global_agenda_access(self):
        """Superadmin can view any representative's agenda across all regions."""
        self.client.login(username='superadmin', password='Password123!')
        res_cairo = self.client.get(reverse('agenda'), {'assignee': self.rep_cairo.id})
        self.assertEqual(res_cairo.status_code, 200)

        res_alex = self.client.get(reverse('agenda'), {'assignee': self.rep_alex.id})
        self.assertEqual(res_alex.status_code, 200)

    def test_agenda_displays_planned_and_executed_visits(self):
        """Agenda correctly combines planned visit items and executed visits with badges."""
        # 1. Create a planned day with 1 item
        plan_day = PlannedVisitDay.objects.create(assignee=self.rep_cairo, date=self.today)
        plan_item = PlannedVisitItem.objects.create(
            plan_day=plan_day,
            contact=self.contact_cairo,
            template=self.template,
            order=1,
            notes='مناقشة عينات جديدة'
        )

        # 2. Create an executed out-of-plan visit for the same day
        unplanned_visit = Visit.objects.create(
            serial_num=8801,
            owner=self.rep_cairo,
            contact=self.contact_cairo,
            template=self.template,
            is_planned=False,
            date=self.today,
            status='finished',
            approval_status='approved'
        )

        self.client.login(username='rep_cairo', password='Password123!')
        res = self.client.get(reverse('agenda'), {'date': self.today.strftime('%Y-%m-%d')})
        self.assertEqual(res.status_code, 200)

        # Both items should be present
        self.assertContains(res, 'د. أحمد القاهرة')
        self.assertContains(res, 'من الخطة')
        self.assertContains(res, 'خارج الخطة')
        self.assertContains(res, 'بدء الزيارة')
        self.assertContains(res, 'معاينة التفاصيل')
        self.assertContains(res, reverse('visit_detail', args=[unplanned_visit.pk]))

    def test_agenda_date_navigation(self):
        """Changing date correctly displays only records belonging to the selected date."""
        # Visit today
        v_today = Visit.objects.create(
            serial_num=8802,
            owner=self.rep_cairo,
            contact=self.contact_cairo,
            date=self.today,
            status='finished',
            approval_status='approved'
        )
        # Visit tomorrow
        v_tomorrow = Visit.objects.create(
            serial_num=8803,
            owner=self.rep_cairo,
            contact=self.contact_cairo,
            date=self.tomorrow,
            status='finished',
            approval_status='approved'
        )

        self.client.login(username='rep_cairo', password='Password123!')
        res_today = self.client.get(reverse('agenda'), {'date': self.today.strftime('%Y-%m-%d')})
        self.assertContains(res_today, reverse('visit_detail', args=[v_today.pk]))
        self.assertNotContains(res_today, reverse('visit_detail', args=[v_tomorrow.pk]))

        res_tomorrow = self.client.get(reverse('agenda'), {'date': self.tomorrow.strftime('%Y-%m-%d')})
        self.assertContains(res_tomorrow, reverse('visit_detail', args=[v_tomorrow.pk]))
        self.assertNotContains(res_tomorrow, reverse('visit_detail', args=[v_today.pk]))

    def test_agenda_todos_lifecycle(self):
        """Adding, toggling, and deleting daily todos in Agenda."""
        self.client.login(username='rep_cairo', password='Password123!')

        # Add Todo
        add_res = self.client.post(reverse('agenda_todo_add'), {
            'title': 'متابعة شيك الصيدلية',
            'date': self.today.strftime('%Y-%m-%d')
        }, follow=True)
        self.assertEqual(add_res.status_code, 200)
        self.assertTrue(AgendaTodo.objects.filter(user=self.rep_cairo, title='متابعة شيك الصيدلية').exists())

        todo = AgendaTodo.objects.get(user=self.rep_cairo, title='متابعة شيك الصيدلية')
        self.assertFalse(todo.is_completed)

        # Toggle Todo
        toggle_res = self.client.post(reverse('agenda_todo_toggle', args=[todo.id]), follow=True)
        self.assertEqual(toggle_res.status_code, 200)
        todo.refresh_from_db()
        self.assertTrue(todo.is_completed)

        # Rep alex cannot toggle Rep cairo's todo
        self.client.login(username='rep_alex', password='Password123!')
        unauth_res = self.client.post(reverse('agenda_todo_toggle', args=[todo.id]))
        self.assertEqual(unauth_res.status_code, 403)

        # Cairo rep can delete their todo
        self.client.login(username='rep_cairo', password='Password123!')
        del_res = self.client.post(reverse('agenda_todo_delete', args=[todo.id]), follow=True)
        self.assertEqual(del_res.status_code, 200)
        self.assertFalse(AgendaTodo.objects.filter(pk=todo.id).exists())

    def test_manager_can_approve_subordinate_visit_from_agenda(self):
        """Manager can approve subordinate representative visit from agenda with return redirect."""
        visit = Visit.objects.create(
            serial_num=801,
            owner=self.rep_cairo,
            contact=self.contact_cairo,
            template=self.template,
            date=self.today,
            status='finished',
            approval_status='pending',
            created_by=self.rep_cairo
        )

        self.client.login(username='manager_cairo', password='Password123!')
        agenda_url = f"{reverse('agenda')}?assignee={self.rep_cairo.id}&date={self.today.strftime('%Y-%m-%d')}"
        res_view = self.client.get(agenda_url)
        self.assertEqual(res_view.status_code, 200)
        self.assertContains(res_view, 'اعتماد')
        self.assertContains(res_view, 'رفض')

        approve_res = self.client.post(
            reverse('visit_action', args=[visit.pk, 'approve']),
            {'next': agenda_url}
        )
        self.assertEqual(approve_res.status_code, 302)
        self.assertEqual(approve_res.url, agenda_url)

        visit.refresh_from_db()
        self.assertEqual(visit.approval_status, 'approved')
        self.assertEqual(visit.approved_by, self.manager_cairo)

    def test_manager_can_decline_subordinate_visit_from_agenda(self):
        """Manager can decline subordinate visit from agenda with required reason and next redirect."""
        visit = Visit.objects.create(
            serial_num=802,
            owner=self.rep_cairo,
            contact=self.contact_cairo,
            template=self.template,
            date=self.today,
            status='finished',
            approval_status='pending',
            created_by=self.rep_cairo
        )

        self.client.login(username='manager_cairo', password='Password123!')
        agenda_url = f"{reverse('agenda')}?assignee={self.rep_cairo.id}&date={self.today.strftime('%Y-%m-%d')}"

        # Rejection without reason fails
        fail_res = self.client.post(
            reverse('visit_action', args=[visit.pk, 'disapprove']),
            {'next': agenda_url, 'approval_notes': ''}
        )
        self.assertEqual(fail_res.status_code, 302)
        visit.refresh_from_db()
        self.assertEqual(visit.approval_status, 'pending')

        # Rejection with reason succeeds and preserves next redirect
        ok_res = self.client.post(
            reverse('visit_action', args=[visit.pk, 'disapprove']),
            {'next': agenda_url, 'approval_notes': 'يرجى مراجعة إجابات استبيان الزيارة بدقة'}
        )
        self.assertEqual(ok_res.status_code, 302)
        self.assertEqual(ok_res.url, agenda_url)

        visit.refresh_from_db()
        self.assertEqual(visit.approval_status, 'disapproved')
        self.assertEqual(visit.approval_notes, 'يرجى مراجعة إجابات استبيان الزيارة بدقة')

    def test_manager_can_approve_and_decline_from_visits_list(self):
        """Manager can approve and decline visits directly from visits list view."""
        v1 = Visit.objects.create(
            serial_num=803,
            owner=self.rep_cairo,
            contact=self.contact_cairo,
            template=self.template,
            date=self.today,
            status='finished',
            approval_status='pending',
            created_by=self.rep_cairo
        )
        v2 = Visit.objects.create(
            serial_num=804,
            owner=self.rep_cairo,
            contact=self.contact_cairo,
            template=self.template,
            date=self.today,
            status='finished',
            approval_status='pending',
            created_by=self.rep_cairo
        )

        self.client.login(username='manager_cairo', password='Password123!')
        res_list = self.client.get(reverse('visits_list'))
        self.assertEqual(res_list.status_code, 200)
        self.assertContains(res_list, 'اعتماد')

        # Approve v1 with next=/activities/visits/
        list_url = reverse('visits_list')
        appr_res = self.client.post(
            reverse('visit_action', args=[v1.pk, 'approve']),
            {'next': list_url}
        )
        self.assertEqual(appr_res.status_code, 302)
        self.assertEqual(appr_res.url, list_url)
        v1.refresh_from_db()
        self.assertEqual(v1.approval_status, 'approved')

        # Decline v2 with next=/activities/visits/
        decl_res = self.client.post(
            reverse('visit_action', args=[v2.pk, 'disapprove']),
            {'next': list_url, 'approval_notes': 'تم الرفض من جدول الزيارات'}
        )
        self.assertEqual(decl_res.status_code, 302)
        self.assertEqual(decl_res.url, list_url)
        v2.refresh_from_db()
        self.assertEqual(v2.approval_status, 'disapproved')

    def test_anti_self_approval_and_cross_region_security(self):
        """Dual-control anti-self-approval rule and cross-region isolation remain strictly enforced."""
        # 1. Manager own visit cannot be approved by self
        mgr_visit = Visit.objects.create(
            serial_num=805,
            owner=self.manager_cairo,
            contact=self.contact_cairo,
            template=self.template,
            date=self.today,
            status='finished',
            approval_status='pending',
            created_by=self.manager_cairo
        )
        self.client.login(username='manager_cairo', password='Password123!')
        res_self = self.client.post(reverse('visit_action', args=[mgr_visit.pk, 'approve']))
        self.assertEqual(res_self.status_code, 302)
        mgr_visit.refresh_from_db()
        self.assertEqual(mgr_visit.approval_status, 'pending')

        # 2. Cairo manager cannot approve Alexandria rep visit
        alex_visit = Visit.objects.create(
            serial_num=806,
            owner=self.rep_alex,
            contact=self.contact_alex,
            template=self.template,
            date=self.today,
            status='finished',
            approval_status='pending',
            created_by=self.rep_alex
        )
        res_cross = self.client.post(reverse('visit_action', args=[alex_visit.pk, 'approve']))
        self.assertEqual(res_cross.status_code, 302)
        alex_visit.refresh_from_db()
        self.assertEqual(alex_visit.approval_status, 'pending')

class RoleBasedTemplatesAndRegionalApprovalsTestCase(TestCase):
    def setUp(self):
        self.client = Client()

        # 1. Create Roles
        self.manager_role = Role.objects.create(
            name='area_manager',
            display_name='مدير منطقة',
            is_area_manager=True
        )
        self.rep_role = Role.objects.create(
            name='sales_rep',
            display_name='مندوب مبيعات',
            is_rep=True
        )

        # 2. Assign standard permissions to manager and rep roles
        perms = Permission.objects.filter(
            codename__in=[
                'activities:visits/list', 'activities:visits/view', 'activities:visits/create', 'activities:visits/edit',
                'activities:visits/approve', 'activities:planned/list', 'activities:planned/manage',
                'sales:orders/list', 'sales:orders/view', 'sales:orders/create', 'sales:orders/approve',
                'purchases:orders/list', 'purchases:orders/view', 'purchases:orders/create', 'purchases:orders/approve',
                'module:activities', 'module:sales', 'module:contacts', 'module:purchases'
            ]
        )
        self.manager_role.permissions.set(perms)
        self.rep_role.permissions.set(
            perms.exclude(codename__in=['activities:visits/approve', 'sales:orders/approve', 'purchases:orders/approve'])
        )

        # 3. Create Regional Hierarchy
        # Region A: Riyadh (Governorate) with Subregions Olaya and Malaz
        self.region_a = Area.objects.create(code='REG-A', name='الرياض', area_type='governorate')
        self.subregion_a1 = Area.objects.create(code='SUB-A1', name='العليا', area_type='subarea', parent=self.region_a)
        self.subregion_a2 = Area.objects.create(code='SUB-A2', name='الملز', area_type='subarea', parent=self.region_a)

        # Region B: Jeddah (Governorate) with Subregion Rawdah
        self.region_b = Area.objects.create(code='REG-B', name='جدة', area_type='governorate')
        self.subregion_b1 = Area.objects.create(code='SUB-B1', name='الروضة', area_type='subarea', parent=self.region_b)

        # 4. Create Users
        # SuperAdmin
        self.superadmin = User.objects.create_superuser(
            username='superadmin', email='super@example.com', password='Password123!',
            first_name='Super', last_name='Admin'
        )

        # Manager A (Assigned to Region A)
        self.manager_a = User.objects.create_user(
            username='manager_a', email='manager_a@example.com', password='Password123!',
            first_name='أحمد', last_name='مدير الرياض', role=self.manager_role
        )
        self.manager_a.assigned_areas.add(self.region_a)

        # Manager B (Assigned to Region B)
        self.manager_b = User.objects.create_user(
            username='manager_b', email='manager_b@example.com', password='Password123!',
            first_name='سعيد', last_name='مدير جدة', role=self.manager_role
        )
        self.manager_b.assigned_areas.add(self.region_b)

        # Rep A1 (Assigned to Subregion A1 under Region A)
        self.rep_a1 = User.objects.create_user(
            username='rep_a1', email='rep_a1@example.com', password='Password123!',
            first_name='خالد', last_name='مندوب العليا', role=self.rep_role
        )
        self.rep_a1.assigned_areas.add(self.subregion_a1)

        # Rep B1 (Assigned to Subregion B1 under Region B)
        self.rep_b1 = User.objects.create_user(
            username='rep_b1', email='rep_b1@example.com', password='Password123!',
            first_name='طارق', last_name='مندوب الروضة', role=self.rep_role
        )
        self.rep_b1.assigned_areas.add(self.subregion_b1)

        # 5. Create Contacts
        self.contact_pharmacy_a = Contact.objects.create(
            name='صيدلية الأمل', code='PH001', account_type='Pharmacy',
            area=self.subregion_a1, is_customer=True, status='customer'
        )
        self.contact_clinic_a = Contact.objects.create(
            name='عيادة النور', code='CL001', account_type='Clinic',
            area=self.subregion_a1, is_customer=True, status='customer'
        )
        self.contact_clinic_a2 = Contact.objects.create(
            name='عيادة الملز', code='CL002', account_type='Clinic',
            area=self.subregion_a2, is_customer=True, status='customer'
        )
        self.contact_pharmacy_b = Contact.objects.create(
            name='صيدلية الشفاء بجدة', code='PH002', account_type='Pharmacy',
            area=self.subregion_b1, is_customer=True, status='customer'
        )
        self.supplier = Contact.objects.create(
            name='شركة توريد الأدوية العالمية', code='SUP001', account_type='Store',
            area=self.subregion_a1, is_supplier=True, status='supplier'
        )

        # 6. Create Templates
        self.pharmacy_template = VisitTemplate.objects.create(
            name='Pharmacy Routine Visit',
            display_name_ar='زيارة دورية لصيدلية',
            restrict_account_types=['Pharmacy', 'Store'],
            active=True
        )
        self.clinic_template = VisitTemplate.objects.create(
            name='Physician Detailing',
            display_name_ar='زيارة شرح لطبيب بعيادة',
            restrict_account_types=['Clinic', 'Center'],
            active=True
        )
        self.general_template = VisitTemplate.objects.create(
            name='General Contact Visit',
            display_name_ar='زيارة عامة لأي عميل',
            restrict_account_types=[],
            active=True
        )

        # 7. Create Warehouse and Product for Sales Orders
        self.category = ProductCategory.objects.create(name='الأدوية', code='CAT-MED')
        self.product = Product.objects.create(
            name='بانادول 500 ملجم', sku_code='PAN500', category=self.category,
            retail_price=Decimal('15.00'), default_purchase_cost=Decimal('10.00'), is_active=True
        )
        self.warehouse = Warehouse.objects.create(name='مستودع الرياض المركزي', code='WH-RYD', is_active=True)

    # =========================================================================
    # REQUIREMENT 1 & 2: Role-Based Visit Templates & Contact Compatibility
    # =========================================================================
    def test_visit_template_contact_eligibility_model_level(self):
        """Model level tests for template/contact eligibility with aliases."""
        # Pharmacy template vs Pharmacy contact -> True
        self.assertTrue(self.pharmacy_template.is_contact_eligible(self.contact_pharmacy_a))
        # Pharmacy template vs Clinic contact -> False
        self.assertFalse(self.pharmacy_template.is_contact_eligible(self.contact_clinic_a))
        # Clinic template vs Clinic contact -> True
        self.assertTrue(self.clinic_template.is_contact_eligible(self.contact_clinic_a))
        # Clinic template vs Pharmacy contact -> False
        self.assertFalse(self.clinic_template.is_contact_eligible(self.contact_pharmacy_a))
        # General template (empty restrictions) -> True for all
        self.assertTrue(self.general_template.is_contact_eligible(self.contact_pharmacy_a))
        self.assertTrue(self.general_template.is_contact_eligible(self.contact_clinic_a))

    def test_planned_visit_add_item_enforces_template_compatibility(self):
        """Planned visit item creation must reject incompatible templates."""
        self.client.login(username='rep_a1', password='Password123!')
        
        # Incompatible: Assigning Pharmacy template to Clinic contact
        res_incompatible = self.client.post(reverse('planned_visit_add_item'), {
            'date': timezone.now().strftime('%Y-%m-%d'),
            'contact_id': self.contact_clinic_a.id,
            'template_id': self.pharmacy_template.id,
            'assignee_id': self.rep_a1.id,
        })
        self.assertFalse(PlannedVisitItem.objects.filter(contact=self.contact_clinic_a, template=self.pharmacy_template).exists())

        # Compatible: Assigning Clinic template to Clinic contact
        res_compatible = self.client.post(reverse('planned_visit_add_item'), {
            'date': timezone.now().strftime('%Y-%m-%d'),
            'contact_id': self.contact_clinic_a.id,
            'template_id': self.clinic_template.id,
            'assignee_id': self.rep_a1.id,
        })
        self.assertTrue(PlannedVisitItem.objects.filter(contact=self.contact_clinic_a, template=self.clinic_template).exists())

    def test_unplanned_visit_backend_rejects_incompatible_template(self):
        """Unplanned visit form submission must reject incompatible template independently on backend."""
        self.client.login(username='rep_a1', password='Password123!')
        
        # Try submitting visit for Clinic contact with Pharmacy template
        post_data = {
            'contact': self.contact_clinic_a.id,
            'template': self.pharmacy_template.id,
            'date': timezone.now().strftime('%Y-%m-%d'),
            'is_successful': 'on',
            'latitude': '24.7136',
            'longitude': '46.6753',
            'device_accuracy': '15.0',
        }
        res = self.client.post(reverse('visit_create'), post_data)
        # Form error should prevent creation
        self.assertFalse(Visit.objects.filter(contact=self.contact_clinic_a, template=self.pharmacy_template).exists())

        # Now submit compatible template
        post_data['template'] = self.clinic_template.id
        res_valid = self.client.post(reverse('visit_create'), post_data)
        self.assertTrue(Visit.objects.filter(contact=self.contact_clinic_a, template=self.clinic_template).exists())

    def test_visit_templates_api_filters_by_contact_and_user_role(self):
        """API /api/templates/ must return only templates eligible for the requested contact."""
        self.client.login(username='rep_a1', password='Password123!')
        
        # Query for Pharmacy contact
        res_ph = self.client.get(f"{reverse('visit_templates_api')}?contact_id={self.contact_pharmacy_a.id}")
        self.assertEqual(res_ph.status_code, 200)
        data_ph = res_ph.json()
        ids_ph = [t['id'] for t in data_ph['results']]
        self.assertIn(self.pharmacy_template.id, ids_ph)
        self.assertIn(self.general_template.id, ids_ph)
        self.assertNotIn(self.clinic_template.id, ids_ph)

        # Query for Clinic contact
        res_cl = self.client.get(f"{reverse('visit_templates_api')}?contact_id={self.contact_clinic_a.id}")
        self.assertEqual(res_cl.status_code, 200)
        data_cl = res_cl.json()
        ids_cl = [t['id'] for t in data_cl['results']]
        self.assertIn(self.clinic_template.id, ids_cl)
        self.assertIn(self.general_template.id, ids_cl)
        self.assertNotIn(self.pharmacy_template.id, ids_cl)

    # =========================================================================
    # REQUIREMENT 4: Regional Hierarchy & Horizontal/Vertical Data Isolation
    # =========================================================================
    def test_regional_hierarchy_scope_calculation(self):
        """Manager assigned to governorate automatically manages all child subareas and their reps."""
        managed_areas_a = get_user_managed_areas(self.manager_a)
        self.assertIn(self.region_a, managed_areas_a)
        self.assertIn(self.subregion_a1, managed_areas_a)
        self.assertIn(self.subregion_a2, managed_areas_a)
        self.assertNotIn(self.region_b, managed_areas_a)
        self.assertNotIn(self.subregion_b1, managed_areas_a)

        managed_reps_a = get_user_managed_representatives(self.manager_a)
        self.assertIn(self.rep_a1, managed_reps_a)
        self.assertNotIn(self.rep_b1, managed_reps_a)

        # SuperAdmin manages all
        all_reps = get_user_managed_representatives(self.superadmin)
        self.assertIn(self.rep_a1, all_reps)
        self.assertIn(self.rep_b1, all_reps)

    def test_horizontal_data_isolation_between_regions(self):
        """Manager A cannot access or view records of Region B."""
        # Create Visit and Order in Region A
        visit_a = Visit.objects.create(
            serial_num=8001, contact=self.contact_pharmacy_a,
            template=self.pharmacy_template, owner=self.rep_a1,
            approval_status='pending', status='finished'
        )
        order_a = SalesOrder.objects.create(
            serial_num=9001,
            order_number='SO-REG-A01', customer=self.contact_pharmacy_a,
            source_warehouse=self.warehouse, created_by=self.rep_a1,
            grand_total=Decimal('150.00'), status='pending'
        )

        # Create Visit and Order in Region B
        visit_b = Visit.objects.create(
            serial_num=8002, contact=self.contact_pharmacy_b,
            template=self.pharmacy_template, owner=self.rep_b1,
            approval_status='pending', status='finished'
        )
        order_b = SalesOrder.objects.create(
            serial_num=9002,
            order_number='SO-REG-B01', customer=self.contact_pharmacy_b,
            source_warehouse=self.warehouse, created_by=self.rep_b1,
            grand_total=Decimal('200.00'), status='pending'
        )

        # Manager A access checks:
        self.assertTrue(can_user_access_object(self.manager_a, visit_a, 'view'))
        self.assertTrue(can_user_access_object(self.manager_a, visit_a, 'approve'))
        self.assertTrue(can_user_access_object(self.manager_a, order_a, 'view'))
        self.assertTrue(can_user_access_object(self.manager_a, order_a, 'approve'))

        # Manager A cross-region access to Region B must be FALSE:
        self.assertFalse(can_user_access_object(self.manager_a, visit_b, 'view'))
        self.assertFalse(can_user_access_object(self.manager_a, visit_b, 'approve'))
        self.assertFalse(can_user_access_object(self.manager_a, order_b, 'view'))
        self.assertFalse(can_user_access_object(self.manager_a, order_b, 'approve'))

        # Direct HTTP attempt by Manager A on Region B records must be blocked:
        self.client.login(username='manager_a', password='Password123!')
        res_visit_b = self.client.get(reverse('visit_detail', args=[visit_b.pk]))
        self.assertEqual(res_visit_b.status_code, 403)

        res_order_b = self.client.get(reverse('sales_order_detail', args=[order_b.pk]))
        self.assertEqual(res_order_b.status_code, 403)

    # =========================================================================
    # REQUIREMENT 3 & 5: Approval Workflows, Self-Approval Block & Resubmission
    # =========================================================================
    def test_representative_cannot_self_approve_visit_or_order(self):
        """A representative must never be able to approve their own visit or sales order."""
        visit_a = Visit.objects.create(
            serial_num=8003, contact=self.contact_pharmacy_a,
            template=self.pharmacy_template, owner=self.rep_a1,
            approval_status='pending', status='finished'
        )
        order_a = SalesOrder.objects.create(
            serial_num=9003,
            order_number='SO-REG-A02', customer=self.contact_pharmacy_a,
            source_warehouse=self.warehouse, created_by=self.rep_a1,
            grand_total=Decimal('300.00'), status='pending'
        )

        self.assertFalse(can_user_access_object(self.rep_a1, visit_a, 'approve'))
        self.assertFalse(can_user_access_object(self.rep_a1, order_a, 'approve'))

        # Rep direct HTTP approval attempt must fail
        self.client.login(username='rep_a1', password='Password123!')
        res_approve_visit = self.client.post(reverse('visit_action', args=[visit_a.pk, 'approve']))
        visit_a.refresh_from_db()
        self.assertEqual(visit_a.approval_status, 'pending')

        res_approve_order = self.client.post(reverse('sales_order_action', args=[order_a.pk, 'approve']))
        order_a.refresh_from_db()
        self.assertEqual(order_a.status, 'pending')

    def test_visit_approval_rejection_and_resubmission_lifecycle(self):
        """Full lifecycle of visit approval, rejection with mandatory reason, and resubmission."""
        visit = Visit.objects.create(
            serial_num=8004, contact=self.contact_pharmacy_a,
            template=self.pharmacy_template, owner=self.rep_a1,
            approval_status='pending', status='finished'
        )

        # 1. Manager rejects without reason -> must be blocked
        self.client.login(username='manager_a', password='Password123!')
        res_reject_no_reason = self.client.post(reverse('visit_action', args=[visit.pk, 'disapprove']), {
            'approval_notes': ''
        })
        visit.refresh_from_db()
        self.assertEqual(visit.approval_status, 'pending')

        # 2. Manager rejects with reason -> succeeds and logs audit
        res_reject = self.client.post(reverse('visit_action', args=[visit.pk, 'disapprove']), {
            'approval_notes': 'يرجى مراجعة إجابات أسئلة المخزون وإعادة الإرسال.'
        })
        visit.refresh_from_db()
        self.assertEqual(visit.approval_status, 'disapproved')
        self.assertEqual(visit.approved_by, self.manager_a)
        self.assertIn('يرجى مراجعة', visit.approval_notes)
        self.assertTrue(ApprovalAuditLog.objects.filter(visit=visit, action='rejected').exists())

        # 3. Representative resubmits after correction
        self.client.login(username='rep_a1', password='Password123!')
        res_resubmit = self.client.post(reverse('visit_action', args=[visit.pk, 'resubmit']), {
            'notes': 'تم تعديل البيانات وفق الملاحظات.'
        })
        visit.refresh_from_db()
        self.assertEqual(visit.approval_status, 'pending')
        self.assertIsNone(visit.approved_by)
        self.assertTrue(ApprovalAuditLog.objects.filter(visit=visit, action='resubmitted').exists())

        # 4. Manager approves -> succeeds
        self.client.login(username='manager_a', password='Password123!')
        res_approve = self.client.post(reverse('visit_action', args=[visit.pk, 'approve']), {
            'approval_notes': 'معتمد ومقبول.'
        })
        visit.refresh_from_db()
        self.assertEqual(visit.approval_status, 'approved')
        self.assertEqual(visit.approved_by, self.manager_a)
        self.assertIsNotNone(visit.approved_at)
        self.assertTrue(ApprovalAuditLog.objects.filter(visit=visit, action='approved').exists())

    def test_sales_order_approval_rejection_resubmission_and_downstream_enforcement(self):
        """Full sales order approval lifecycle and strict prevention of downstream bypass."""
        from inventory.models import InventoryStock
        InventoryStock.objects.create(
            warehouse=self.warehouse, product=self.product,
            qty_on_hand=Decimal('100.00'), qty_reserved=Decimal('0.00'),
            product_cost=Decimal('10.00')
        )

        order = SalesOrder.objects.create(
            serial_num=9004,
            order_number='SO-REG-A03', customer=self.contact_pharmacy_a,
            source_warehouse=self.warehouse, created_by=self.rep_a1,
            grand_total=Decimal('450.00'), status='pending'
        )
        SalesOrderItem.objects.create(
            order=order, product=self.product, quantity=30,
            unit_price=Decimal('15.00'), subtotal=Decimal('450.00')
        )

        # 1. Downstream preparation while status is 'pending' MUST fail
        with self.assertRaises(ValidationError):
            SalesOrderService.prepare_order(order, self.manager_a)
        with self.assertRaises(ValidationError):
            SalesOrderService.deliver_order(order, self.manager_a)
        with self.assertRaises(ValidationError):
            SalesOrderService.invoice_order(order, self.manager_a)

        # 2. Manager rejects order with reason
        SalesOrderService.reject_order(order, self.manager_a, reason='تجاوز الحد الائتماني المسموح به')
        order.refresh_from_db()
        self.assertEqual(order.status, 'rejected')
        self.assertEqual(order.rejection_reason, 'تجاوز الحد الائتماني المسموح به')
        self.assertTrue(ApprovalAuditLog.objects.filter(sales_order=order, action='rejected').exists())

        # 3. Downstream operations while rejected MUST fail
        with self.assertRaises(ValidationError):
            SalesOrderService.prepare_order(order, self.manager_a)

        # 4. Rep resubmits order
        SalesOrderService.resubmit_order(order, self.rep_a1)
        order.refresh_from_db()
        self.assertEqual(order.status, 'pending')
        self.assertTrue(ApprovalAuditLog.objects.filter(sales_order=order, action='resubmitted').exists())

        # 5. Manager approves order
        SalesOrderService.approve_order(order, self.manager_a)
        order.refresh_from_db()
        self.assertEqual(order.status, 'manager_approval')
        self.assertEqual(order.approved_by, self.manager_a)
        self.assertIsNotNone(order.approved_at)
        self.assertTrue(ApprovalAuditLog.objects.filter(sales_order=order, action='approved').exists())

        # 6. Now downstream prepare_order is allowed!
        SalesOrderService.prepare_order(order, self.manager_a)
        order.refresh_from_db()
        self.assertEqual(order.status, 'preparing')

    # =========================================================================
    # REQUIREMENT 5 & 8: Approvals Removal & Canonical List/Detail Integration
    # =========================================================================
    def test_approvals_hub_and_regional_dashboard_endpoints(self):
        """Verify approvals hub redirects to canonical item list views and regional dashboard loads."""
        # Unauthenticated or rep login
        self.client.login(username='rep_a1', password='Password123!')
        res_rep_appr = self.client.get(reverse('approvals_hub'))
        # Canonical redirect to visits list pending
        self.assertEqual(res_rep_appr.status_code, 302)
        self.assertIn('/visits/', res_rep_appr.url)

        # Manager A accessing approvals_hub also cleanly redirects to canonical list
        self.client.login(username='manager_a', password='Password123!')
        res_mgr_appr = self.client.get(reverse('approvals_hub'))
        self.assertEqual(res_mgr_appr.status_code, 302)
        self.assertIn('/visits/', res_mgr_appr.url)

        # Orders tab redirects to sales list
        res_orders_tab = self.client.get(f"{reverse('approvals_hub')}?tab=orders")
        self.assertEqual(res_orders_tab.status_code, 302)
        self.assertIn('/sales/', res_orders_tab.url)

        # Manager A can view Agenda for subordinate reps
        res_mgr_agenda = self.client.get(reverse('agenda'), {'assignee': self.rep_a1.id})
        self.assertEqual(res_mgr_agenda.status_code, 200)
        self.assertContains(res_mgr_agenda, 'جدول الاعمال')

    def test_purchase_order_approval_lifecycle_and_downstream_enforcement(self):
        """Verify purchase order approval, rejection with reason, resubmit, self-approval prevention, and downstream blocks."""
        po = PurchaseOrder.objects.create(
            serial_num=999,
            order_number="#999",
            supplier=self.supplier,
            target_warehouse=self.warehouse,
            created_by=self.rep_a1,
            status='pending'
        )
        PurchaseOrderItem.objects.create(
            order=po,
            product=self.product,
            quantity=10,
            unit_price=100
        )
        po.recalculate_totals()

        # 1. Downstream block: Cannot stock unapproved purchase order
        with self.assertRaises(ValidationError):
            PurchaseOrderService.stock_order(po, self.manager_a)

        # 2. Self-approval prevention: Purchaser/creator cannot approve own order
        with self.assertRaises(ValidationError):
            PurchaseOrderService.approve_order(po, self.rep_a1)

        # 3. Rejection requires non-empty reason
        with self.assertRaises(ValidationError):
            PurchaseOrderService.reject_order(po, self.manager_a, reason="")

        # 4. Authorized rejection
        PurchaseOrderService.reject_order(po, self.manager_a, reason="سعر التكلفة غير مطابق للاتفاقية")
        po.refresh_from_db()
        self.assertEqual(po.status, 'rejected')
        self.assertEqual(po.rejection_reason, "سعر التكلفة غير مطابق للاتفاقية")
        self.assertTrue(ApprovalAuditLog.objects.filter(purchase_order=po, action='rejected').exists())

        # 5. Resubmission by creator resets status to pending
        PurchaseOrderService.resubmit_order(po, self.rep_a1)
        po.refresh_from_db()
        self.assertEqual(po.status, 'pending')
        self.assertEqual(po.rejection_reason, "")
        self.assertTrue(ApprovalAuditLog.objects.filter(purchase_order=po, action='resubmitted').exists())

        # 6. Authorized approval by manager
        PurchaseOrderService.approve_order(po, self.manager_a, notes="معتمد للشراء")
        po.refresh_from_db()
        self.assertEqual(po.status, 'approved')
        self.assertEqual(po.approved_by, self.manager_a)
        self.assertTrue(ApprovalAuditLog.objects.filter(purchase_order=po, action='approved').exists())

        # 7. Downstream stocking unlocked after approval
        PurchaseOrderService.stock_order(po, self.manager_a)
        po.refresh_from_db()
        self.assertEqual(po.status, 'picked')

    def test_item_detail_pages_approval_actions_and_list_filters(self):
        """Verify approval actions directly on Visit, SalesOrder, and PurchaseOrder detail pages, and list filters."""
        # --- Visit Detail & Approval ---
        visit = Visit.objects.create(
            serial_num=888,
            owner=self.rep_a1,
            contact=self.contact_pharmacy_a,
            template=self.pharmacy_template,
            status='finished',
            approval_status='pending',
            date=timezone.now().date(),
            created_by=self.rep_a1
        )
        self.client.login(username='manager_a', password='Password123!')
        res_v_detail = self.client.get(reverse('visit_detail', args=[visit.pk]))
        self.assertEqual(res_v_detail.status_code, 200)
        self.assertTrue(res_v_detail.context['can_approve'])

        # Approve visit via detail page action
        res_v_act = self.client.post(reverse('visit_action', args=[visit.pk, 'approve']))
        self.assertEqual(res_v_act.status_code, 302)
        visit.refresh_from_db()
        self.assertEqual(visit.approval_status, 'approved')

        # Visits list filter by approval_status
        res_v_list = self.client.get(reverse('visits_list') + '?approval_status=approved')
        self.assertEqual(res_v_list.status_code, 200)
        self.assertContains(res_v_list, str(visit.serial_num))

        # --- Sales Order Detail & Approval ---
        order = SalesOrder.objects.create(
            serial_num=888,
            order_number="#SO-888",
            customer=self.contact_pharmacy_a,
            source_warehouse=self.warehouse,
            created_by=self.rep_a1,
            status='pending',
            order_date=timezone.now().date()
        )
        res_so_detail = self.client.get(reverse('sales_order_detail', args=[order.pk]))
        self.assertEqual(res_so_detail.status_code, 200)
        self.assertTrue(res_so_detail.context['can_approve'])

        # Reject sales order with reason
        res_so_reject = self.client.post(reverse('sales_order_action', args=[order.pk, 'reject']), {
            'rejection_reason': 'الحد الائتماني غير كافي'
        })
        self.assertEqual(res_so_reject.status_code, 302)
        order.refresh_from_db()
        self.assertEqual(order.status, 'rejected')

        # Sales list filter by status=rejected
        res_so_list = self.client.get(reverse('sales_orders_list') + '?status=rejected')
        self.assertEqual(res_so_list.status_code, 200)
        self.assertContains(res_so_list, order.order_number)

        # --- Purchase Order Detail & Approval ---
        po = PurchaseOrder.objects.create(
            serial_num=888,
            order_number="#PO-888",
            supplier=self.supplier,
            target_warehouse=self.warehouse,
            created_by=self.rep_a1,
            status='pending',
            order_date=timezone.now().date()
        )
        res_po_detail = self.client.get(reverse('purchase_order_detail', args=[po.pk]))
        self.assertEqual(res_po_detail.status_code, 200)
        self.assertTrue(res_po_detail.context['can_approve'])

        # Approve purchase order via detail action
        res_po_act = self.client.post(reverse('purchase_order_action', args=[po.pk, 'approve']), {
            'approval_notes': 'معتمد من مدير المشتريات'
        })
        self.assertEqual(res_po_act.status_code, 302)
        po.refresh_from_db()
        self.assertEqual(po.status, 'approved')

        # Purchase orders list filter by status=approved
        res_po_list = self.client.get(reverse('purchase_orders_list') + '?status=approved')
        self.assertEqual(res_po_list.status_code, 200)
        self.assertContains(res_po_list, po.order_number)

    def test_manager_of_same_area_can_change_visit_status_and_approve(self):
        """Manager of the same regional area can approve and change visit status from detail page."""
        visit = Visit.objects.create(
            serial_num=9901,
            contact=self.contact_pharmacy_a,
            template=self.pharmacy_template,
            owner=self.rep_a1,
            created_by=self.rep_a1,
            date=timezone.now().date(),
            status='started',
            approval_status='pending'
        )

        # Manager A (same area) views detail page
        self.client.force_login(self.manager_a)
        res_detail = self.client.get(reverse('visit_detail', args=[visit.pk]))
        self.assertEqual(res_detail.status_code, 200)
        self.assertTrue(res_detail.context['can_approve'])
        self.assertFalse(res_detail.context['is_in_agenda'])

        # Manager A changes status to approved and finished
        res_change = self.client.post(
            reverse('visit_action', args=[visit.pk, 'change_status']),
            {
                'approval_status': 'approved',
                'visit_status': 'finished',
                'reason': 'اعتماد وتغيير الحالة من مدير المنطقة'
            }
        )
        self.assertEqual(res_change.status_code, 302)
        visit.refresh_from_db()
        self.assertEqual(visit.approval_status, 'approved')
        self.assertEqual(visit.status, 'finished')
        self.assertEqual(visit.approved_by, self.manager_a)
        self.assertIsNotNone(visit.approved_at)

        # Audit log verification
        audit = ApprovalAuditLog.objects.filter(visit=visit, action='status_changed').first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.actor, self.manager_a)

    def test_manager_of_different_area_cannot_change_visit_status(self):
        """Manager of a different region cannot approve or change visit status."""
        visit = Visit.objects.create(
            serial_num=9902,
            contact=self.contact_pharmacy_a,
            template=self.pharmacy_template,
            owner=self.rep_a1,
            created_by=self.rep_a1,
            date=timezone.now().date(),
            status='started',
            approval_status='pending'
        )

        # Manager B (Alexandria/Jeddah) attempts to change status of Region A visit
        self.client.force_login(self.manager_b)
        res = self.client.post(
            reverse('visit_action', args=[visit.pk, 'change_status']),
            {
                'approval_status': 'approved',
                'visit_status': 'finished',
            }
        )
        visit.refresh_from_db()
        self.assertEqual(visit.approval_status, 'pending')
        self.assertEqual(visit.status, 'started')

    def test_representative_cannot_self_approve_visit(self):
        """Representative cannot approve or change approval status on their own visit."""
        visit = Visit.objects.create(
            serial_num=9903,
            contact=self.contact_pharmacy_a,
            template=self.pharmacy_template,
            owner=self.rep_a1,
            created_by=self.rep_a1,
            date=timezone.now().date(),
            status='finished',
            approval_status='pending'
        )

        self.client.force_login(self.rep_a1)
        res = self.client.post(reverse('visit_action', args=[visit.pk, 'approve']))
        visit.refresh_from_db()
        self.assertEqual(visit.approval_status, 'pending')

    def test_unapproved_visit_cannot_be_sent_to_agenda(self):
        """A visit must be approved before sending it to the agenda."""
        visit = Visit.objects.create(
            serial_num=9904,
            contact=self.contact_pharmacy_a,
            template=self.pharmacy_template,
            owner=self.rep_a1,
            created_by=self.rep_a1,
            date=timezone.now().date(),
            status='started',
            approval_status='pending'
        )

        self.client.force_login(self.manager_a)
        res = self.client.post(reverse('visit_action', args=[visit.pk, 'send_to_agenda']))
        # Should redirect back to detail with an error message
        self.assertEqual(res.status_code, 302)
        self.assertFalse(PlannedVisitItem.objects.filter(visit=visit).exists())

    def test_approved_visit_can_be_sent_to_agenda(self):
        """Once approved by area manager, the visit is successfully sent to the agenda."""
        visit = Visit.objects.create(
            serial_num=9905,
            contact=self.contact_pharmacy_a,
            template=self.pharmacy_template,
            owner=self.rep_a1,
            created_by=self.rep_a1,
            date=timezone.now().date(),
            status='started',
            approval_status='approved',
            approved_by=self.manager_a,
            approved_at=timezone.now()
        )

        self.client.force_login(self.manager_a)
        res = self.client.post(reverse('visit_action', args=[visit.pk, 'send_to_agenda']))
        self.assertEqual(res.status_code, 302)
        self.assertIn('/agenda/', res.url)

        # Verify item added to PlannedVisitDay
        item = PlannedVisitItem.objects.filter(visit=visit).first()
        self.assertIsNotNone(item)
        self.assertEqual(item.plan_day.assignee, self.rep_a1)
        self.assertEqual(item.plan_day.date, visit.date)
        self.assertEqual(item.contact, self.contact_pharmacy_a)

        # Detail page now reflects is_in_agenda=True
        res_detail = self.client.get(reverse('visit_detail', args=[visit.pk]))
        self.assertTrue(res_detail.context['is_in_agenda'])

class VisitSuggestedProductsTests(TestCase):
    def setUp(self):
        self.client = Client()

        self.superadmin_role, _ = Role.objects.get_or_create(
            name=Role.ROLE_SUPERADMIN,
            defaults={'display_name': 'مدير النظام الأعلى', 'is_super': True, 'is_system': True, 'is_active': True}
        )
        self.admin_user = User.objects.create_superuser(
            username='admin_sugg@wea.com',
            email='admin_sugg@wea.com',
            password='Password123!',
            name='Admin Sugg',
            role=self.superadmin_role
        )

        self.category = ProductCategory.objects.create(name='Test Category', code='CAT-01')

        # Products: 1 active sellable, 1 non-sellable, 1 inactive
        self.p_active_sellable = Product.objects.create(
            category=self.category,
            name='Panadol Extra Active Sellable',
            sku_code='PAN-01',
            sellable=True,
            is_active=True
        )
        self.p_non_sellable = Product.objects.create(
            category=self.category,
            name='Display Stand Non Sellable',
            sku_code='DISP-01',
            sellable=False,
            is_active=True
        )
        self.p_inactive = Product.objects.create(
            category=self.category,
            name='Old Medicine Inactive',
            sku_code='OLD-01',
            sellable=True,
            is_active=False
        )

    def test_eligible_suggested_products_filtering(self):
        """VisitTemplate.get_eligible_suggested_products() must return only active, sellable products."""
        template = VisitTemplate.objects.create(
            name='doctor_routine_visit',
            display_name_ar='قالب زيارة الأطباء',
            active=True
        )
        template.suggested_products.add(self.p_active_sellable, self.p_non_sellable, self.p_inactive)

        eligible = list(template.get_eligible_suggested_products())
        self.assertEqual(len(eligible), 1)
        self.assertEqual(eligible[0].id, self.p_active_sellable.id)

    def test_visit_template_form_suggested_products(self):
        """VisitTemplateForm should only offer sellable, active products in suggested_products field."""
        form = VisitTemplateForm()
        queryset_product_ids = list(form.fields['suggested_products'].queryset.values_list('id', flat=True))
        self.assertIn(self.p_active_sellable.id, queryset_product_ids)
        self.assertNotIn(self.p_non_sellable.id, queryset_product_ids)
        self.assertNotIn(self.p_inactive.id, queryset_product_ids)

    def test_location_settings_does_not_contain_suggested_products(self):
        """Location settings view should no longer manage suggested products."""
        self.client.login(username='admin_sugg@wea.com', password='Password123!')
        res = self.client.get(reverse('location_settings'))
        self.assertEqual(res.status_code, 200)
        # Verify Card 4 text is removed
        self.assertNotContains(res, 'المنتجات المقترحة للزيارات الميدانية')

class ComprehensiveUserWorkflowsTestCase(TestCase):
    """
    Full end-to-end test suite for user workflows:
    - Different kinds of users: Medical Rep, Area Manager, Accountant.
    - Planned and unplanned visits.
    - Single and double visits (doubled=True/False).
    - Creation, Manager Approval, Rep Completion flow.
    - Settings-controlled permissions and require_manager_approval for visits, sales, purchases, and agreements.
    """

    def setUp(self):
        self.client = Client()

        # 1. Settings Setup
        self.loc_settings = LocationSettings.get_settings()
        self.loc_settings.allow_all_users_to_create_visits = True
        self.loc_settings.require_manager_approval_for_visits = True
        self.loc_settings.allow_all_users_to_create_agreements = True
        self.loc_settings.require_manager_approval_for_agreements = True
        self.loc_settings.verify_visits = False
        self.loc_settings.save()

        self.sales_settings = SalesSettings.get_settings()
        self.sales_settings.allow_all_users_to_create = True
        self.sales_settings.require_manager_approval = True
        self.sales_settings.save()

        self.purchase_settings = PurchaseSettings.get_settings()
        self.purchase_settings.allow_all_users_to_create = True
        self.purchase_settings.require_manager_approval = True
        self.purchase_settings.save()

        # 2. Roles Setup
        self.manager_role = Role.objects.create(
            name='area_manager',
            display_name='مدير منطقة',
            is_area_manager=True
        )
        self.rep_role = Role.objects.create(
            name='sales_rep',
            display_name='مندوب مبيعات',
            is_rep=True
        )
        self.accountant_role, _ = Role.objects.get_or_create(
            name='accountant',
            defaults={
                'display_name': 'محاسب',
                'is_rep': False,
                'is_area_manager': False
            }
        )

        all_perms = Permission.objects.filter(
            codename__in=[
                'activities:visits/list', 'activities:visits/view', 'activities:visits/create', 'activities:visits/edit',
                'activities:visits/approve', 'activities:planned/list', 'activities:planned/manage',
                'activities:agreements/list', 'activities:agreements/view', 'activities:agreements/create', 'activities:agreements/approve',
                'sales:orders/list', 'sales:orders/view', 'sales:orders/create', 'sales:orders/approve',
                'purchases:orders/list', 'purchases:orders/view', 'purchases:orders/create', 'purchases:orders/approve',
                'module:activities', 'module:sales', 'module:contacts', 'module:purchases', 'module:treasury'
            ]
        )
        self.manager_role.permissions.set(all_perms)
        self.rep_role.permissions.set(
            all_perms.exclude(codename__in=['activities:visits/approve', 'sales:orders/approve', 'purchases:orders/approve', 'activities:agreements/approve'])
        )
        # Accountant role has accounting/treasury perms only, no visit/sales creation perms
        self.accountant_role.permissions.set(
            Permission.objects.filter(codename__in=['module:treasury', 'module:contacts'])
        )

        # 3. Areas Hierarchy
        self.region_cairo = Area.objects.create(code='CAI', name='القاهرة', area_type='governorate')
        self.sub_nasr_city = Area.objects.create(code='CAI-NASR', name='مدينة نصر', area_type='subarea', parent=self.region_cairo)
        self.sub_maadi = Area.objects.create(code='CAI-MAADI', name='المعادي', area_type='subarea', parent=self.region_cairo)

        self.region_alex = Area.objects.create(code='ALX', name='الإسكندرية', area_type='governorate')
        self.sub_smouha = Area.objects.create(code='ALX-SMO', name='سموحة', area_type='subarea', parent=self.region_alex)

        # 4. Users
        self.manager_cairo = User.objects.create_user(
            username='mgr_cairo', email='mgr_cairo@example.com', password='Password123!',
            first_name='مدير', last_name='القاهرة', role=self.manager_role
        )
        self.manager_cairo.assigned_areas.add(self.region_cairo)

        self.manager_alex = User.objects.create_user(
            username='mgr_alex', email='mgr_alex@example.com', password='Password123!',
            first_name='مدير', last_name='الإسكندرية', role=self.manager_role
        )
        self.manager_alex.assigned_areas.add(self.region_alex)

        self.rep_cairo = User.objects.create_user(
            username='rep_cairo', email='rep_cairo@example.com', password='Password123!',
            first_name='مندوب', last_name='القاهرة', role=self.rep_role
        )
        self.rep_cairo.assigned_areas.add(self.sub_nasr_city)

        self.accountant_user = User.objects.create_user(
            username='acc_user', email='acc@example.com', password='Password123!',
            first_name='محمود', last_name='محاسب', role=self.accountant_role
        )
        self.accountant_user.assigned_areas.add(self.sub_nasr_city)

        # 5. Contacts (Customers & Suppliers)
        self.customer_cairo = Contact.objects.create(
            name='صيدلية الشفاء مدينة نصر', code='CUST-001', account_type='Pharmacy',
            area=self.sub_nasr_city, is_customer=True, status='customer'
        )
        self.customer_maadi = Contact.objects.create(
            name='مستشفى المعادي الدولي', code='CUST-002', account_type='Hospital',
            area=self.sub_maadi, is_customer=True, status='customer'
        )
        self.customer_alex = Contact.objects.create(
            name='صيدلية سموحة الإسكندرية', code='CUST-003', account_type='Pharmacy',
            area=self.sub_smouha, is_customer=True, status='customer'
        )
        self.supplier_cairo = Contact.objects.create(
            name='شركة الأدوية المتحدة', code='SUPP-001', is_supplier=True, status='supplier',
            area=self.sub_nasr_city
        )

        # 6. Inventory & Catalog
        self.cat = ProductCategory.objects.create(name='أدوية عامة', code='GEN-CAT')
        self.product = Product.objects.create(
            name='بانادول إكسترا 500 ملجم', sku_code='PAN-01', retail_price=50.00, default_purchase_cost=35.00, category=self.cat
        )
        self.warehouse = Warehouse.objects.create(name='المخزن الرئيسي بالقاهرة', code='WH-CAI')

        # 7. Visit Templates & Agreement Type
        self.general_template = VisitTemplate.objects.create(
            name='general_field_visit',
            display_name_ar='زيارة ميدانية عامة',
            active=True
        )
        self.agreement_type = AgreementType.objects.create(
            name='اتفاقية توريد سنوية'
        )

    # =========================================================================
    # Test 1: Rep creates Unplanned Single Visit -> Manager Approves -> Rep Completes
    # =========================================================================
    def test_rep_unplanned_single_visit_full_flow(self):
        """
        Flow:
        1. Rep creates unplanned single visit (doubled=False) in their area.
        2. Visit starts in approval_status='pending' because rep is not a manager.
        3. Area manager reviews and approves visit in visit detail page.
        4. Rep completes visit (status='finished').
        5. Prior manager approval is preserved (approval_status remains 'approved').
        6. Visit can now be sent to agenda.
        """
        # Step 1: Rep logs in and creates unplanned single visit
        self.client.login(username='rep_cairo', password='Password123!')
        res_create = self.client.post(reverse('visit_create'), {
            'contact': self.customer_cairo.id,
            'template': self.general_template.id,
            'date': timezone.now().strftime('%Y-%m-%d'),
            'doubled': '',  # Single visit (unchecked)
            'is_successful': 'on',
            'feedback': 'مناقشة طلبيات الشهر الجديد مع صيدلية الشفاء',
        })
        self.assertEqual(res_create.status_code, 302)
        visit = Visit.objects.filter(contact=self.customer_cairo, owner=self.rep_cairo).first()
        self.assertIsNotNone(visit)
        self.assertFalse(visit.is_planned)
        self.assertFalse(visit.doubled, "Must be recorded as a single visit")
        self.assertEqual(visit.status, 'planned')
        self.assertEqual(visit.approval_status, 'pending', "Must require manager approval for non-manager rep")

        # Rep attempts to start visit before manager approval -> MUST FAIL
        res_start_unapproved = self.client.post(reverse('visit_action', args=[visit.pk, 'start']))
        visit.refresh_from_db()
        self.assertEqual(visit.status, 'planned', "Visit cannot be started before manager approval")

        # Step 2: Rep tries to send unapproved visit to agenda -> MUST FAIL
        res_agenda_unapproved = self.client.post(reverse('visit_action', args=[visit.pk, 'send_to_agenda']))
        self.assertEqual(visit.approval_status, 'pending')
        # Agenda should not have this item
        self.assertFalse(PlannedVisitItem.objects.filter(visit=visit).exists())

        # Step 3: Area Manager logs in and approves the visit
        self.client.logout()
        self.client.login(username='mgr_cairo', password='Password123!')
        res_approve = self.client.post(reverse('visit_action', args=[visit.pk, 'manage_status']), {
            'approval_status': 'approved',
            'approval_notes': 'معتمد من مدير منطقة القاهرة'
        })
        self.assertEqual(res_approve.status_code, 302)
        visit.refresh_from_db()
        self.assertEqual(visit.approval_status, 'approved', "Manager of the area successfully approved the visit")
        self.assertEqual(visit.approved_by, self.manager_cairo)
        self.assertIsNotNone(visit.approved_at)

        # Step 4: Rep logs in, starts the visit, submits answers, and completes the visit
        self.client.logout()
        self.client.login(username='rep_cairo', password='Password123!')
        res_start = self.client.post(reverse('visit_action', args=[visit.pk, 'start']))
        self.assertEqual(res_start.status_code, 302)
        visit.refresh_from_db()
        self.assertEqual(visit.status, 'started', "Visit successfully transitioned to started upon explicit start action")
        self.assertIsNotNone(visit.started_at)

        # Rep saves draft answers -> status remains 'started'
        res_draft = self.client.post(reverse('visit_detail', args=[visit.pk]), {
            'action': 'save_draft',
            'feedback': 'حفظ مسودة مؤقتة',
        })
        self.assertEqual(res_draft.status_code, 302)
        visit.refresh_from_db()
        self.assertEqual(visit.status, 'started', "Submitting answers does not end visit; status remains started")

        # Rep explicitly completes the visit
        res_complete = self.client.post(reverse('visit_detail', args=[visit.pk]), {
            'action': 'complete',
            'visit_outcome': 'successful',
            'feedback': 'تم إنهاء الزيارة بنجاح والاتفاق على التوريد',
        })
        self.assertEqual(res_complete.status_code, 302)
        visit.refresh_from_db()
        self.assertEqual(visit.status, 'finished', "Visit status transitioned to finished")
        self.assertEqual(visit.approval_status, 'approved', "Approval status must remain approved after completion")
        self.assertFalse(visit.doubled)

        # Step 5: Send approved visit to agenda -> MUST SUCCEED
        res_agenda = self.client.post(reverse('visit_action', args=[visit.pk, 'send_to_agenda']))
        self.assertEqual(res_agenda.status_code, 302)
        item = PlannedVisitItem.objects.filter(visit=visit).first()
        self.assertIsNotNone(item, "Visit was successfully dispatched to agenda after approval")
        self.assertTrue(item.is_executed)

    # =========================================================================
    # Test 2: Rep creates Unplanned Double Visit -> Manager Approves -> Rep Completes
    # =========================================================================
    def test_rep_unplanned_double_visit_full_flow(self):
        """
        Flow:
        1. Rep creates double visit (doubled=True) for coaching/joint visit.
        2. Visit starts in approval_status='pending', doubled=True.
        3. Manager approves the double visit.
        4. Rep completes the double visit.
        5. Double flag and approved status are preserved.
        """
        self.client.login(username='rep_cairo', password='Password123!')
        res = self.client.post(reverse('visit_create'), {
            'contact': self.customer_cairo.id,
            'template': self.general_template.id,
            'date': timezone.now().strftime('%Y-%m-%d'),
            'doubled': 'on',  # Double visit checked
            'is_successful': 'on',
            'feedback': 'زيارة مشتركة ومرافقة ميدانية مع الإدارة',
        })
        self.assertEqual(res.status_code, 302)
        visit = Visit.objects.filter(contact=self.customer_cairo, owner=self.rep_cairo, doubled=True).first()
        self.assertIsNotNone(visit)
        self.assertTrue(visit.doubled, "Must be recorded as a double visit")
        self.assertEqual(visit.status, 'planned')
        self.assertEqual(visit.approval_status, 'pending')

        # Manager approves
        self.client.logout()
        self.client.login(username='mgr_cairo', password='Password123!')
        self.client.post(reverse('visit_action', args=[visit.pk, 'manage_status']), {
            'approval_status': 'approved',
            'approval_notes': 'اعتماد الزيارة المزدوجة'
        })
        visit.refresh_from_db()
        self.assertEqual(visit.approval_status, 'approved')

        # Rep starts and completes
        self.client.logout()
        self.client.login(username='rep_cairo', password='Password123!')
        self.client.post(reverse('visit_action', args=[visit.pk, 'start']))
        visit.refresh_from_db()
        self.assertEqual(visit.status, 'started')

        self.client.post(reverse('visit_detail', args=[visit.pk]), {
            'action': 'complete',
            'visit_outcome': 'successful',
        })
        visit.refresh_from_db()
        self.assertEqual(visit.status, 'finished')
        self.assertEqual(visit.approval_status, 'approved')
        self.assertTrue(visit.doubled, "Double visit flag must remain True upon completion")

    # =========================================================================
    # Test 3: Rep Planned Visit Flow (Plan Item -> Execute -> Manager Approves -> Complete)
    # =========================================================================
    def test_rep_planned_visit_flow(self):
        """
        Flow:
        1. Rep plans a visit via planned_visit_add_item for their area.
        2. Rep executes the planned visit via planned_visit_item_execute.
        3. Visit is created with is_planned=True and approval_status='pending'.
        4. Manager of the same area approves the visit.
        5. Rep completes the planned visit -> finished and approved.
        """
        self.client.login(username='rep_cairo', password='Password123!')
        today_str = timezone.now().strftime('%Y-%m-%d')

        # 1. Add item to plan
        res_plan = self.client.post(reverse('planned_visit_add_item'), {
            'assignee_id': self.rep_cairo.id,
            'date': today_str,
            'contact_id': self.customer_cairo.id,
            'template_id': self.general_template.id,
            'notes': 'زيارة مجدولة ضمن الخطة الأسبوعية'
        })
        self.assertEqual(res_plan.status_code, 302)
        plan_item = PlannedVisitItem.objects.filter(contact=self.customer_cairo, plan_day__assignee=self.rep_cairo).first()
        self.assertIsNotNone(plan_item)

        # 2. Execute planned item
        res_exec = self.client.post(reverse('visit_create'), {
            'planned_item_id': plan_item.pk,
            'contact': self.customer_cairo.id,
            'template': self.general_template.id,
            'date': today_str,
            'is_successful': 'on',
        })
        self.assertEqual(res_exec.status_code, 302)
        plan_item.refresh_from_db()
        self.assertFalse(plan_item.is_executed, "Planned item is NOT executed until visit finishes")
        visit = plan_item.visit
        self.assertIsNotNone(visit)
        self.assertTrue(visit.is_planned)
        self.assertEqual(visit.status, 'planned')
        self.assertEqual(visit.approval_status, 'pending')

        # 3. Manager approves
        self.client.logout()
        self.client.login(username='mgr_cairo', password='Password123!')
        self.client.post(reverse('visit_action', args=[visit.pk, 'manage_status']), {
            'approval_status': 'approved',
            'approval_notes': 'معتمد'
        })
        visit.refresh_from_db()
        self.assertEqual(visit.approval_status, 'approved')

        # 4. Rep starts and completes
        self.client.logout()
        self.client.login(username='rep_cairo', password='Password123!')
        self.client.post(reverse('visit_action', args=[visit.pk, 'start']))
        visit.refresh_from_db()
        self.assertEqual(visit.status, 'started')

        self.client.post(reverse('visit_detail', args=[visit.pk]), {
            'action': 'complete',
            'visit_outcome': 'successful',
        })
        visit.refresh_from_db()
        self.assertEqual(visit.status, 'finished')
        plan_item.refresh_from_db()
        self.assertTrue(plan_item.is_executed, "Planned item is executed after visit finishes")
        self.assertEqual(visit.approval_status, 'approved')
        self.assertTrue(visit.is_planned)

    # =========================================================================
    # Test 4: Manager Created Visit Auto-Approved (No Manager Approval Required)
    # =========================================================================
    def test_manager_created_visit_auto_approved(self):
        """When an Area Manager or executive creates a visit, approval is auto-granted."""
        self.client.login(username='mgr_cairo', password='Password123!')
        res = self.client.post(reverse('visit_create'), {
            'contact': self.customer_cairo.id,
            'template': self.general_template.id,
            'date': timezone.now().strftime('%Y-%m-%d'),
            'is_successful': 'on',
            'feedback': 'زيارة تفقدية من مدير المنطقة',
        })
        self.assertEqual(res.status_code, 302)
        visit = Visit.objects.filter(contact=self.customer_cairo, owner=self.manager_cairo).first()
        self.assertIsNotNone(visit)
        self.assertEqual(visit.approval_status, 'approved', "Manager creation must auto-approve")
        self.assertEqual(visit.approved_by, self.manager_cairo)

    # =========================================================================
    # Test 5: Accountant Can Create Visits When Setting Enabled
    # =========================================================================
    def test_accountant_user_can_create_and_complete_visit(self):
        """
        'all kind of users can make a visit either planned or not'
        Accountant user (without rep permissions) can create visit because
        allow_all_users_to_create_visits is True in settings.
        """
        self.client.login(username='acc_user', password='Password123!')
        res = self.client.post(reverse('visit_create'), {
            'contact': self.customer_cairo.id,
            'template': self.general_template.id,
            'date': timezone.now().strftime('%Y-%m-%d'),
            'is_successful': 'on',
            'feedback': 'زيارة ميدانية لمطابقة أرصدة العميل',
        })
        self.assertEqual(res.status_code, 302)
        visit = Visit.objects.filter(contact=self.customer_cairo, owner=self.accountant_user).first()
        self.assertIsNotNone(visit)
        self.assertEqual(visit.approval_status, 'pending', "Accountant is non-manager so approval is required")

        # Manager approves
        self.client.logout()
        self.client.login(username='mgr_cairo', password='Password123!')
        self.client.post(reverse('visit_action', args=[visit.pk, 'manage_status']), {
            'approval_status': 'approved',
            'approval_notes': 'موافق على زيارة المحاسب'
        })
        visit.refresh_from_db()
        self.assertEqual(visit.approval_status, 'approved')

        # Accountant starts and completes
        self.client.logout()
        self.client.login(username='acc_user', password='Password123!')
        self.client.post(reverse('visit_action', args=[visit.pk, 'start']))
        visit.refresh_from_db()
        self.assertEqual(visit.status, 'started')

        self.client.post(reverse('visit_detail', args=[visit.pk]), {
            'action': 'complete',
            'visit_outcome': 'successful',
        })
        visit.refresh_from_db()
        self.assertEqual(visit.status, 'finished')
        self.assertEqual(visit.approval_status, 'approved')

    # =========================================================================
    # Test 6: Settings Toggle - require_manager_approval_for_visits=False Auto-Approves
    # =========================================================================
    def test_require_manager_approval_disabled_auto_approves_for_all(self):
        """When require_manager_approval_for_visits is turned OFF in settings, all users auto-approve."""
        self.loc_settings.require_manager_approval_for_visits = False
        self.loc_settings.save()

        self.client.login(username='rep_cairo', password='Password123!')
        res = self.client.post(reverse('visit_create'), {
            'contact': self.customer_cairo.id,
            'template': self.general_template.id,
            'date': timezone.now().strftime('%Y-%m-%d'),
            'is_successful': 'on',
        })
        self.assertEqual(res.status_code, 302)
        visit = Visit.objects.filter(contact=self.customer_cairo, owner=self.rep_cairo).order_by('-id').first()
        self.assertEqual(visit.approval_status, 'approved', "Must auto-approve when require_manager_approval is False")

    # =========================================================================
    # Test 7: Universal Purchases, Sales, and Agreements Approval Workflows
    # =========================================================================
    def test_sales_purchases_agreements_approval_by_role(self):
        """
        Verify settings-controlled creation and require_manager_approval for:
        - Sales Orders
        - Purchase Orders
        - Agreements
        """
        # A. Sales Orders
        # 1. Rep creates Sales Order -> Pending
        self.client.login(username='rep_cairo', password='Password123!')
        res_so_rep = self.client.post(reverse('sales_order_create'), {
            'customer': self.customer_cairo.id,
            'warehouse': self.warehouse.id,
            'order_date': timezone.now().strftime('%Y-%m-%d'),
            'product_id[]': [self.product.id],
            'quantity[]': ['10'],
            'unit_price[]': ['50.00'],
        })
        self.assertEqual(res_so_rep.status_code, 302)
        so_rep = SalesOrder.objects.filter(customer=self.customer_cairo, created_by=self.rep_cairo).first()
        self.assertIsNotNone(so_rep)
        self.assertEqual(so_rep.status, 'pending', "Rep sales order must be pending manager approval")

        # 2. Manager creates Sales Order -> Auto-approved to manager_approval
        self.client.logout()
        self.client.login(username='mgr_cairo', password='Password123!')
        res_so_mgr = self.client.post(reverse('sales_order_create'), {
            'customer': self.customer_cairo.id,
            'warehouse': self.warehouse.id,
            'order_date': timezone.now().strftime('%Y-%m-%d'),
            'product_id[]': [self.product.id],
            'quantity[]': ['5'],
            'unit_price[]': ['50.00'],
        })
        self.assertEqual(res_so_mgr.status_code, 302)
        so_mgr = SalesOrder.objects.filter(customer=self.customer_cairo, created_by=self.manager_cairo).first()
        self.assertIsNotNone(so_mgr)
        self.assertEqual(so_mgr.status, 'manager_approval', "Manager sales order must be auto-approved")
        self.assertEqual(so_mgr.approved_by, self.manager_cairo)

        # B. Purchase Orders
        # 1. Accountant creates Purchase Order -> Pending
        self.client.logout()
        self.client.login(username='acc_user', password='Password123!')
        res_po_acc = self.client.post(reverse('purchase_order_create'), {
            'supplier': self.supplier_cairo.id,
            'warehouse': self.warehouse.id,
            'order_date': timezone.now().strftime('%Y-%m-%d'),
            'product_id[]': [self.product.id],
            'quantity[]': ['20'],
            'unit_price[]': ['35.00'],
        })
        self.assertEqual(res_po_acc.status_code, 302)
        po_acc = PurchaseOrder.objects.filter(supplier=self.supplier_cairo, created_by=self.accountant_user).first()
        self.assertIsNotNone(po_acc)
        self.assertEqual(po_acc.status, 'pending', "Accountant purchase order must require manager approval")

        # 2. Manager creates Purchase Order -> Auto-approved
        self.client.logout()
        self.client.login(username='mgr_cairo', password='Password123!')
        res_po_mgr = self.client.post(reverse('purchase_order_create'), {
            'supplier': self.supplier_cairo.id,
            'warehouse': self.warehouse.id,
            'order_date': timezone.now().strftime('%Y-%m-%d'),
            'product_id[]': [self.product.id],
            'quantity[]': ['10'],
            'unit_price[]': ['35.00'],
        })
        self.assertEqual(res_po_mgr.status_code, 302)
        po_mgr = PurchaseOrder.objects.filter(supplier=self.supplier_cairo, created_by=self.manager_cairo).first()
        self.assertIsNotNone(po_mgr)
        self.assertEqual(po_mgr.status, 'approved', "Manager purchase order must auto-approve")
        self.assertEqual(po_mgr.approved_by, self.manager_cairo)

        # C. Agreements
        # 1. Rep creates agreement -> status='new' (awaiting approval)
        self.client.logout()
        self.client.login(username='rep_cairo', password='Password123!')
        res_ag_rep = self.client.post(reverse('agreement_create'), {
            'customer': self.customer_cairo.id,
            'title': 'اتفاقية توريد صيدلية الشفاء',
            'type': self.agreement_type.id,
            'amount': '15000.00',
            'date': timezone.now().strftime('%Y-%m-%d'),
            'description': 'شروط التوريد'
        })
        self.assertEqual(res_ag_rep.status_code, 302)
        ag_rep = Agreement.objects.filter(customer=self.customer_cairo, created_by=self.rep_cairo).first()
        self.assertIsNotNone(ag_rep)
        self.assertEqual(ag_rep.status, 'new', "Rep agreement must be in new/pending status")

        # 2. Manager creates agreement -> status='approved'
        self.client.logout()
        self.client.login(username='mgr_cairo', password='Password123!')
        res_ag_mgr = self.client.post(reverse('agreement_create'), {
            'customer': self.customer_cairo.id,
            'title': 'اتفاقية توريد معتمدة من الإدارة',
            'type': self.agreement_type.id,
            'amount': '50000.00',
            'date': timezone.now().strftime('%Y-%m-%d'),
            'description': 'معتمدة مباشرة'
        })
        self.assertEqual(res_ag_mgr.status_code, 302)
        ag_mgr = Agreement.objects.filter(customer=self.customer_cairo, created_by=self.manager_cairo).first()
        self.assertIsNotNone(ag_mgr)
        self.assertEqual(ag_mgr.status, 'approved', "Manager agreement must be auto-approved")

    # =========================================================================
    # Test 8: Cross-Regional Security & Isolation
    # =========================================================================
    def test_cross_region_isolation(self):
        """Manager B (Alex) cannot approve visits created in Region A (Cairo)."""
        # Rep Cairo creates visit
        self.client.login(username='rep_cairo', password='Password123!')
        self.client.post(reverse('visit_create'), {
            'contact': self.customer_cairo.id,
            'template': self.general_template.id,
            'date': timezone.now().strftime('%Y-%m-%d'),
            'is_successful': 'on',
        })
        visit = Visit.objects.filter(contact=self.customer_cairo, owner=self.rep_cairo).first()

        # Manager Alex tries to approve Cairo visit -> MUST BE 403 FORBIDDEN
        self.client.logout()
        self.client.login(username='mgr_alex', password='Password123!')
        res_cross = self.client.post(reverse('visit_action', args=[visit.pk, 'manage_status']), {
            'approval_status': 'approved',
        })
        self.assertEqual(res_cross.status_code, 403, "Cross-region manager status change must be rejected with 403")
        visit.refresh_from_db()
        self.assertEqual(visit.approval_status, 'pending', "Approval status must remain unchanged")

    # =========================================================================
    # Test 9: Product Eligibility in Visits (Sellable Only)
    # =========================================================================
    def test_product_eligibility_in_visits(self):
        """
        Products not intended for sale (sellable=False or is_active=False)
        must not be selectable for new visit-related operations.
        """
        pharmacy_tmpl = VisitTemplate.objects.create(
            name='single_visit_pharmacy',
            display_name_ar='زيارة فردية صيدلية',
            active=True,
            enable_product_detailing=True
        )

        p_sellable = Product.objects.create(
            name='دواء معتمد للبيع', sku_code='SELL-01', retail_price=100.00,
            category=self.cat, sellable=True, is_active=True
        )
        p_nonsellable = Product.objects.create(
            name='عينات مجانية غير معروضة للبيع', sku_code='FREE-01', retail_price=0.00,
            category=self.cat, sellable=False, is_active=True
        )
        p_inactive = Product.objects.create(
            name='دواء مسحوب من السوق', sku_code='INACT-01', retail_price=50.00,
            category=self.cat, sellable=True, is_active=False
        )

        eligible_qs = Product.get_eligible_for_visits()
        self.assertIn(p_sellable, eligible_qs)
        self.assertNotIn(p_nonsellable, eligible_qs)
        self.assertNotIn(p_inactive, eligible_qs)

        self.client.login(username='rep_cairo', password='Password123!')
        res = self.client.post(reverse('visit_create'), {
            'contact': self.customer_cairo.id,
            'template': pharmacy_tmpl.id,
            'date': timezone.now().strftime('%Y-%m-%d'),
            'detailed_products': [str(p_sellable.id), str(p_nonsellable.id), str(p_inactive.id)],
            'is_successful': 'on',
        })
        self.assertEqual(res.status_code, 302)
        visit = Visit.objects.filter(contact=self.customer_cairo, owner=self.rep_cairo).order_by('-id').first()
        detailed_ids = set(visit.detailed_products.values_list('id', flat=True))
        self.assertIn(p_sellable.id, detailed_ids, "Sellable product must be linked")
        self.assertNotIn(p_nonsellable.id, detailed_ids, "Non-sellable product must be filtered out")
        self.assertNotIn(p_inactive.id, detailed_ids, "Inactive product must be filtered out")

        # Rep attempts to add non-sellable product during visit completion
        res_complete = self.client.post(reverse('visit_detail', args=[visit.pk]), {
            'action': 'save_details',
            'detailed_products': [str(p_nonsellable.id)],
            'detailed_products_submitted': '1',
        })
        self.assertEqual(res_complete.status_code, 302)
        visit.refresh_from_db()
        self.assertNotIn(p_nonsellable.id, visit.detailed_products.values_list('id', flat=True))

    # =========================================================================
    # Test 10: Configurable Product Suggestions in Settings and Visit Detail
    # =========================================================================
    def test_configurable_product_suggestions(self):
        """
        Product suggestions must be configurable through the existing settings UI
        and restricted to eligible products.
        """
        pharmacy_tmpl = VisitTemplate.objects.create(
            name='single_visit_pharmacy',
            display_name_ar='زيارة فردية صيدلية',
            active=True,
            enable_product_detailing=True
        )

        p_sugg1 = Product.objects.create(
            name='بانادول مقترح 1', sku_code='PAN-SUGG1', retail_price=60.00,
            category=self.cat, sellable=True, is_active=True
        )
        p_sugg2 = Product.objects.create(
            name='بانادول مقترح 2', sku_code='PAN-SUGG2', retail_price=70.00,
            category=self.cat, sellable=True, is_active=True
        )
        p_nonsellable = Product.objects.create(
            name='عينات غير معروضة للبيع', sku_code='SAMPLE-X', retail_price=0.00,
            category=self.cat, sellable=False, is_active=True
        )

        # 1. Global Location Settings configure suggestions
        self.loc_settings.enable_product_suggestions = True
        self.loc_settings.suggested_products.set([p_sugg1, p_nonsellable])
        self.loc_settings.save()

        eligible_global_sugg = list(self.loc_settings.get_eligible_suggested_products())
        self.assertIn(p_sugg1, eligible_global_sugg)
        self.assertNotIn(p_nonsellable, eligible_global_sugg)

        # 2. Template-level configurable suggestions
        pharmacy_tmpl.suggested_products.set([p_sugg2, p_nonsellable])
        eligible_tmpl_sugg = list(pharmacy_tmpl.get_eligible_suggested_products())
        self.assertIn(p_sugg2, eligible_tmpl_sugg)
        self.assertNotIn(p_nonsellable, eligible_tmpl_sugg)

        # 3. Create visit and view visit detail
        visit = Visit.objects.create(
            contact=self.customer_cairo,
            template=pharmacy_tmpl,
            owner=self.rep_cairo,
            created_by=self.rep_cairo,
            date=timezone.now().date(),
            status='started',
            approval_status='approved'
        )

        self.client.login(username='rep_cairo', password='Password123!')
        res_view = self.client.get(reverse('visit_detail', args=[visit.pk]))
        self.assertEqual(res_view.status_code, 200)

        suggested_ids = res_view.context['suggested_product_ids']
        self.assertIn(p_sugg1.id, suggested_ids)
        self.assertIn(p_sugg2.id, suggested_ids)
        self.assertNotIn(p_nonsellable.id, suggested_ids)

    # =========================================================================
    # Test 11: Historical Non-Sellable Products Preserved
    # =========================================================================
    def test_historical_non_sellable_products_preserved(self):
        """
        Historical data preservation: if a product was previously detailed and is
        later marked non-sellable (sellable=False), it must remain linked to the visit.
        """
        pharmacy_tmpl = VisitTemplate.objects.create(
            name='single_visit_pharmacy',
            display_name_ar='زيارة فردية صيدلية',
            active=True,
            enable_product_detailing=True
        )

        p_historical = Product.objects.create(
            name='دواء تم إيقاف بيعه لاحقاً', sku_code='HIST-01', retail_price=80.00,
            category=self.cat, sellable=True, is_active=True
        )

        visit = Visit.objects.create(
            contact=self.customer_cairo,
            template=pharmacy_tmpl,
            owner=self.rep_cairo,
            created_by=self.rep_cairo,
            date=timezone.now().date(),
            status='started',
            approval_status='approved'
        )
        visit.detailed_products.set([p_historical])

        # Product is now retired/marked non-sellable
        p_historical.sellable = False
        p_historical.save()

        # Rep opens visit_detail: historical product should still be included in context products
        self.client.login(username='rep_cairo', password='Password123!')
        res_view = self.client.get(reverse('visit_detail', args=[visit.pk]))
        self.assertEqual(res_view.status_code, 200)
        context_product_ids = set(p.id for p in res_view.context['products'])
        self.assertIn(p_historical.id, context_product_ids, "Historical product must be preserved in context")

        # Rep completes visit without removing detailed products
        res_complete = self.client.post(reverse('visit_detail', args=[visit.pk]), {
            'action': 'complete',
            'detailed_products': [str(p_historical.id)],
            'visit_outcome': 'successful',
        })
        self.assertEqual(res_complete.status_code, 302)
        visit.refresh_from_db()
        self.assertIn(p_historical.id, visit.detailed_products.values_list('id', flat=True),
                      "Historical product must remain attached to the completed visit")

class VisitsScopeGbsTests(TestCase):
    def setUp(self):
        self.client = Client()

        # Location Settings: Disable GPS validation initially for easy setup
        self.loc_settings = LocationSettings.get_settings()
        self.loc_settings.verify_visits = False
        self.loc_settings.verify_unplanned_visit_distance = False
        self.loc_settings.verify_end_visit_distance = False
        self.loc_settings.save()

        # Roles
        self.manager_role = Role.objects.create(
            name='area_manager',
            display_name='مدير منطقة',
            is_area_manager=True
        )
        self.rep_role = Role.objects.create(
            name='sales_rep',
            display_name='مندوب مبيعات',
            is_rep=True
        )

        all_perms = Permission.objects.filter(
            codename__in=[
                'activities:visits/list', 'activities:visits/view', 'activities:visits/create',
                'activities:visits/edit', 'activities:visits/approve', 'activities:planned/list',
                'activities:planned/manage', 'module:activities', 'module:contacts',
                'contacts:contacts/list', 'contacts:contacts/view', 'contacts:contacts/create',
                'contacts:contacts/edit'
            ]
        )
        for p in all_perms:
            self.manager_role.permissions.add(p)
            if p.codename not in ['activities:visits/approve']:
                self.rep_role.permissions.add(p)

        # Geographic Areas
        self.cairo = Area.objects.create(name='القاهرة', code='CAI-01', area_type='governorate')
        self.nasr_city = Area.objects.create(name='مدينة نصر', code='NASR-01', parent=self.cairo, area_type='subarea')
        self.maadi = Area.objects.create(name='المعادي', code='MAADI-01', parent=self.cairo, area_type='subarea')

        self.alex = Area.objects.create(name='الإسكندرية', code='ALX-01', area_type='governorate')
        self.smouha = Area.objects.create(name='سموحة', code='SMOU-01', parent=self.alex, area_type='subarea')

        # Users
        self.superadmin = User.objects.create_superuser('sa_user', 'sa@test.com', 'pass123')

        self.cairo_manager = User.objects.create_user('cairo_mgr', 'cmgr@test.com', 'pass123', role=self.manager_role)
        self.cairo_manager.main_area = self.cairo
        self.cairo_manager.assigned_areas.set([self.cairo, self.nasr_city, self.maadi])
        self.cairo_manager.save()

        self.nasr_rep = User.objects.create_user('nasr_rep', 'nrep@test.com', 'pass123', role=self.rep_role)
        self.nasr_rep.assigned_areas.set([self.nasr_city])
        self.nasr_rep.save()

        self.maadi_rep = User.objects.create_user('maadi_rep', 'mrep@test.com', 'pass123', role=self.rep_role)
        self.maadi_rep.assigned_areas.set([self.maadi])
        self.maadi_rep.save()

        # Contacts with Area and Brick
        self.contact_nasr = Contact.objects.create(
            name='صيدلية الأمل',
            contact_type='organization',
            is_customer=True,
            account_type='صيدلية',
            area=self.cairo,
            brick=self.nasr_city,
            created_by=self.nasr_rep
        )
        self.contact_maadi = Contact.objects.create(
            name='عيادة النور د. أحمد',
            contact_type='person',
            is_customer=True,
            account_type='عيادة',
            area=self.cairo,
            brick=self.maadi,
            created_by=self.maadi_rep
        )
        self.contact_alex = Contact.objects.create(
            name='مستشفى الإسكندرية',
            contact_type='organization',
            is_customer=True,
            account_type='مستشفى',
            area=self.alex,
            brick=self.smouha,
            created_by=self.superadmin
        )

        # Visit Templates
        self.template_general = VisitTemplate.objects.create(
            name='general_template',
            display_name_ar='قالب عام لجميع العملاء',
            active=True
        )
        self.template_pharmacy = VisitTemplate.objects.create(
            name='pharmacy_template',
            display_name_ar='قالب الصيدليات',
            restrict_account_types=['صيدلية'],
            active=True
        )
        self.template_clinic = VisitTemplate.objects.create(
            name='clinic_template',
            display_name_ar='قالب العيادات والأطباء',
            restrict_account_types=['عيادة'],
            active=True
        )

    def test_01_automatic_planned_vs_unplanned_determination(self):
        """
        Requirement 2:
        - Manual POST with visit_type='planned' or is_planned='1' WITHOUT planned_item_id
          must be automatically coerced to an unplanned visit (is_planned=False).
        - Execution with valid planned_item_id automatically identifies as planned (is_planned=True).
        """
        self.client.force_login(self.nasr_rep)
        today = timezone.now().date().strftime('%Y-%m-%d')

        # 1. Tampered request trying to create a planned visit directly
        res_tampered = self.client.post(reverse('visit_create'), {
            'visit_type': 'planned',
            'is_planned': '1',
            'contact': self.contact_nasr.id,
            'template': self.template_general.id,
            'date': today,
        })
        self.assertEqual(res_tampered.status_code, 302)
        visit_unplanned = Visit.objects.filter(contact=self.contact_nasr).order_by('-id').first()
        self.assertIsNotNone(visit_unplanned)
        self.assertFalse(visit_unplanned.is_planned, "Direct visit_create must enforce is_planned=False without planned_item_id")

        visit_unplanned.delete()

        # 2. Execution with valid planned_item_id -> automatically sets is_planned=True
        plan_day, _ = PlannedVisitDay.objects.get_or_create(assignee=self.nasr_rep, date=timezone.now().date())
        plan_item = PlannedVisitItem.objects.create(
            plan_day=plan_day,
            order=1,
            contact=self.contact_nasr,
            template=self.template_pharmacy
        )

        res_planned = self.client.post(reverse('visit_create'), {
            'planned_item_id': plan_item.id,
            'contact': self.contact_nasr.id,
            'template': self.template_pharmacy.id,
            'date': today,
        })
        self.assertEqual(res_planned.status_code, 302)
        visit_planned = Visit.objects.filter(contact=self.contact_nasr, is_planned=True).order_by('-id').first()
        self.assertIsNotNone(visit_planned)
        self.assertTrue(visit_planned.is_planned)
        plan_item.refresh_from_db()
        self.assertEqual(plan_item.visit, visit_planned)

    def test_02_contact_and_address_brick_relationships(self):
        """
        Requirement 7:
        - Contact and ContactAddress must properly store both area (Governorate) and brick (Subarea).
        """
        self.client.force_login(self.nasr_rep)
        res_create = self.client.post(reverse('contact_create'), {
            'name': 'مركز مصر الطبي',
            'contact_type': 'organization',
            'relations': ['عميل'],
            'customer_category': 'A',
            'account_type': 'مستشفى',
            'address_title[]': ['الفرع الرئيسي'],
            'address_area[]': [str(self.cairo.id)],
            'address_sub_area[]': [str(self.nasr_city.id)],
            'address_street[]': ['شارع عباس العقاد'],
            'address_is_main[]': ['1'],
        })
        self.assertEqual(res_create.status_code, 302)

        c = Contact.objects.filter(name='مركز مصر الطبي').first()
        self.assertIsNotNone(c)
        self.assertEqual(c.area, self.cairo)
        self.assertEqual(c.brick, self.nasr_city)

        addr = c.addresses.first()
        self.assertIsNotNone(addr)
        self.assertEqual(addr.area, self.cairo)
        self.assertEqual(addr.brick, self.nasr_city)
        self.assertEqual(addr.sub_area, self.nasr_city.name)

    def test_03_organizational_data_scoping_rep_vs_manager(self):
        """
        Requirement 3:
        - Reps are restricted to their authorized brick(s).
        - Managers can access all bricks within their assigned root governorate.
        - Superadmins access all areas.
        """
        # Rep view: Nasr Rep searching contacts
        self.client.force_login(self.nasr_rep)
        search_res = self.client.get('/contacts/api/search/')
        ids = [c['id'] for c in search_res.json()['results']]
        self.assertIn(self.contact_nasr.id, ids)
        self.assertNotIn(self.contact_maadi.id, ids)
        self.assertNotIn(self.contact_alex.id, ids)

        # Manager view: Cairo Manager sees both Nasr City and Maadi, but not Alex
        self.client.force_login(self.cairo_manager)
        search_mgr = self.client.get('/contacts/api/search/')
        mgr_ids = [c['id'] for c in search_mgr.json()['results']]
        self.assertIn(self.contact_nasr.id, mgr_ids)
        self.assertIn(self.contact_maadi.id, mgr_ids)
        self.assertNotIn(self.contact_alex.id, mgr_ids)

        # Superadmin sees all
        self.client.force_login(self.superadmin)
        search_sa = self.client.get('/contacts/api/search/')
        sa_ids = [c['id'] for c in search_sa.json()['results']]
        self.assertIn(self.contact_nasr.id, sa_ids)
        self.assertIn(self.contact_maadi.id, sa_ids)
        self.assertIn(self.contact_alex.id, sa_ids)

    def test_04_bulk_planning_with_per_client_type_templates(self):
        """
        Requirement 5:
        - Multi-client selection with different client types groups by type and assigns eligible templates.
        - Atomic validation creates all items or aborts if any client is incompatible.
        """
        self.client.force_login(self.cairo_manager)
        today_str = timezone.now().date().strftime('%Y-%m-%d')

        # 1. Successful bulk add with heterogeneous client types
        templates_by_type = {
            'صيدلية': str(self.template_pharmacy.id),
            'عيادة': str(self.template_clinic.id),
        }
        res_bulk = self.client.post(
            reverse('planned_visits_bulk_add'),
            {
                'date': today_str,
                'assignee_id': self.cairo_manager.id,
                'contact_ids[]': [self.contact_nasr.id, self.contact_maadi.id],
                'templates_by_type': json.dumps(templates_by_type),
            },
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(res_bulk.status_code, 200)
        data = res_bulk.json()
        self.assertTrue(data.get('success'))
        self.assertEqual(data.get('created_count'), 2)

        item_pharm = PlannedVisitItem.objects.filter(contact=self.contact_nasr, plan_day__date=today_str).first()
        self.assertEqual(item_pharm.template, self.template_pharmacy)

        item_clinic = PlannedVisitItem.objects.filter(contact=self.contact_maadi, plan_day__date=today_str).first()
        self.assertEqual(item_clinic.template, self.template_clinic)

        # 2. Reject incompatible template atomically
        tomorrow_str = (timezone.now().date() + datetime.timedelta(days=1)).strftime('%Y-%m-%d')
        bad_templates = {
            'صيدلية': str(self.template_clinic.id),  # Incompatible: Pharmacy using Clinic template!
        }
        res_bad = self.client.post(
            reverse('planned_visits_bulk_add'),
            {
                'date': tomorrow_str,
                'assignee_id': self.cairo_manager.id,
                'contact_ids[]': [self.contact_nasr.id],
                'templates_by_type': json.dumps(bad_templates),
            },
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(res_bad.status_code, 400)
        self.assertFalse(PlannedVisitItem.objects.filter(contact=self.contact_nasr, plan_day__date=tomorrow_str).exists())

    def test_05_gbs_disabled_workflow(self):
        """
        Requirement 3:
        - When LocationSettings.verify_visits is False, visits can be created and completed without GPS coordinates.
        """
        self.loc_settings.verify_visits = False
        self.loc_settings.verify_unplanned_visit_distance = False
        self.loc_settings.verify_end_visit_distance = False
        self.loc_settings.save()

        self.client.force_login(self.nasr_rep)
        today = timezone.now().date().strftime('%Y-%m-%d')

        # Create unplanned visit without GPS coordinates
        res_create = self.client.post(reverse('visit_create'), {
            'contact': self.contact_nasr.id,
            'template': self.template_general.id,
            'date': today,
        })
        self.assertEqual(res_create.status_code, 302)
        v = Visit.objects.filter(contact=self.contact_nasr).order_by('-id').first()
        self.assertIsNotNone(v)

        # Complete visit without GPS coordinates
        res_complete = self.client.post(reverse('visit_detail', args=[v.pk]), {
            'action': 'complete',
            'feedback': 'تمت الزيارة بنجاح دون الحاجة لـ GPS',
            'visit_outcome': 'successful'
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(res_complete.status_code, 200)
        data = res_complete.json()
        self.assertTrue(data.get('success'))
        v.refresh_from_db()
        self.assertEqual(v.status, 'finished')

    def test_06_visit_set_time_quick_action(self):
        """
        Requirement 6:
        - Every visit supports a scheduled time field.
        - POST /activities/visits/<pk>/set-time/ updates time, logs audit, and returns JSON.
        - Representatives cannot edit visits of other representatives.
        """
        today = timezone.now().date()
        v = Visit.objects.create(
            serial_num=1001,
            contact=self.contact_nasr,
            template=self.template_general,
            owner=self.nasr_rep,
            created_by=self.nasr_rep,
            date=today,
            status='planned'
        )

        # 1. Nasr rep sets time
        self.client.force_login(self.nasr_rep)
        res_time = self.client.post(
            reverse('visit_set_time', args=[v.pk]),
            {'time': '15:45'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(res_time.status_code, 200)
        data = res_time.json()
        self.assertTrue(data.get('success'))
        self.assertEqual(data.get('time_24'), '15:45')
        self.assertEqual(data.get('display_time'), '03:45 م')

        v.refresh_from_db()
        self.assertEqual(v.time, datetime.time(15, 45))
        self.assertIsNotNone(v.visit_time)
        self.assertEqual(v.formatted_time, '03:45 م')

        # Check SecurityAuditLog
        audit_entry = SecurityAuditLog.objects.filter(
            record_id=str(v.pk),
            action_type='VISIT_TIME_UPDATED'
        ).first()
        self.assertIsNotNone(audit_entry)

        # 2. Maadi rep (unauthorized for Nasr visit) tries to set time -> blocked (403 or 404)
        self.client.force_login(self.maadi_rep)
        res_blocked = self.client.post(
            reverse('visit_set_time', args=[v.pk]),
            {'time': '16:00'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertIn(res_blocked.status_code, [403, 404])

class AgreementWorkflowTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.cairo_gov = Area.objects.create(name='محافظة القاهرة - اتفاقيات', code='CAI-AGR', area_type='governorate')
        self.nasr_city = Area.objects.create(name='حي مدينة نصر - اتفاقيات', code='NASR-AGR', area_type='subarea', parent=self.cairo_gov)

        self.rep_role = Role.objects.get(name=Role.ROLE_REP)
        self.manager_role = Role.objects.get(name=Role.ROLE_MANAGER)

        self.rep_cairo = User.objects.create_user(
            username='rep_cairo_ag@example.com', email='rep_cairo_ag@example.com', password='Password123!',
            role=self.rep_role
        )
        self.rep_cairo.assigned_areas.add(self.nasr_city)

        self.manager_cairo = User.objects.create_user(
            username='manager_cairo_ag@example.com', email='manager_cairo_ag@example.com', password='Password123!',
            role=self.manager_role
        )
        self.manager_cairo.assigned_areas.add(self.cairo_gov)

        self.customer = Contact.objects.create(
            name='صيدلية الاتفاقيات التجريبية', area=self.nasr_city, status='customer'
        )

    def test_agreement_anti_self_approval_and_audit(self):
        """Users cannot approve their own agreements, managers can approve subordinate agreements with audit logging."""
        ag_type, _ = AgreementType.objects.get_or_create(name="عقد توريد تجريبي")

        # 1. Cairo rep creates an agreement
        agreement = Agreement.objects.create(
            title="اتفاقية توريد أدوية مندوب",
            customer=self.customer,
            type=ag_type,
            status='new',
            created_by=self.rep_cairo
        )

        # 2. Cairo rep attempts to approve own agreement -> Blocked
        self.client.force_login(self.rep_cairo)
        resp_rep = self.client.get(reverse('agreement_action', args=[agreement.pk, 'approve']))
        agreement.refresh_from_db()
        self.assertEqual(agreement.status, 'new')

        # 3. Cairo manager approves Cairo rep's agreement -> Allowed
        self.client.force_login(self.manager_cairo)
        resp_mgr = self.client.get(reverse('agreement_action', args=[agreement.pk, 'approve']))
        self.assertEqual(resp_mgr.status_code, 302)
        agreement.refresh_from_db()
        self.assertEqual(agreement.status, 'approved')

        # Verify audit log was created
        audit_exists = SecurityAuditLog.objects.filter(
            action_type='AGREEMENT_APPROVED',
            record_id=agreement.id,
            actor=self.manager_cairo
        ).exists()
        self.assertTrue(audit_exists)

        # 4. Cairo manager creates own agreement and attempts to self-approve -> Blocked
        mgr_agreement = Agreement.objects.create(
            title="اتفاقية توريد أدوية مدير",
            customer=self.customer,
            type=ag_type,
            status='new',
            created_by=self.manager_cairo
        )
        resp_self_mgr = self.client.get(reverse('agreement_action', args=[mgr_agreement.pk, 'approve']))
        self.assertEqual(resp_self_mgr.status_code, 403)
        mgr_agreement.refresh_from_db()
        self.assertEqual(mgr_agreement.status, 'new')


class VisitWorkflowAndEditingImprovementsTestCase(TestCase):
    """
    Tests for the 6 target areas:
    - Eliminating duplicate Start Visit step & check-in questions separation (stage='start_only')
    - Active visit transitions directly to End Visit action
    - Strict locking of ended visits (status == 'finished')
    - Smart reapproval rules (rep edits revoke approval, manager edits retain approval)
    """

    def setUp(self):
        from master_data.models import Area
        from accounts.models import Role
        from django.contrib.auth.models import Permission

        self.cairo_gov = Area.objects.create(name='محافظة القاهرة', code='CAI_IMPR')
        self.nasr_city = Area.objects.create(name='مدينة نصر', code='NASR_IMPR', parent=self.cairo_gov)

        self.rep_role = Role.objects.create(name='rep_impr', display_name='مندوب دعاية تجريبي', is_rep=True)
        self.mgr_role = Role.objects.create(name='mgr_impr', display_name='مدير منطقة تجريبي', is_area_manager=True)

        rep_perms = Permission.objects.filter(
            codename__in=[
                'activities:visits/list', 'activities:visits/view', 'activities:visits/create',
                'activities:visits/edit', 'module:activities', 'module:contacts'
            ]
        )
        mgr_perms = Permission.objects.filter(
            codename__in=[
                'activities:visits/list', 'activities:visits/view', 'activities:visits/create',
                'activities:visits/edit', 'activities:visits/approve', 'module:activities', 'module:contacts'
            ]
        )
        self.rep_role.permissions.set(rep_perms)
        self.mgr_role.permissions.set(mgr_perms)

        self.rep = User.objects.create_user(
            username='rep_impr_user', password='Password123!', role=self.rep_role, bypass_location_verification=True
        )
        self.manager = User.objects.create_user(
            username='mgr_impr_user', password='Password123!', role=self.mgr_role, bypass_location_verification=True
        )
        self.rep.assigned_areas.add(self.nasr_city)
        self.manager.assigned_areas.add(self.cairo_gov)

        self.customer = Contact.objects.create(
            name='صيدلية الاختبارات المتقدمة', area=self.nasr_city, status='customer'
        )

        self.template = VisitTemplate.objects.create(
            name='قالب التحسينات الشامل'
        )
        self.q_start_req = VisitTemplateQuestion.objects.create(
            template=self.template,
            text_ar='سؤال بداية الزيارة الإلزامي: هل الموقع مفتوح؟',
            question_type='single_select',
            stage='start_only',
            options=['نعم', 'لا'],
            is_required=True,
            order=1
        )
        self.q_start_opt = VisitTemplateQuestion.objects.create(
            template=self.template,
            text_ar='ملاحظة عند الوصول',
            question_type='text',
            stage='start_only',
            is_required=False,
            order=2
        )
        self.q_end_req = VisitTemplateQuestion.objects.create(
            template=self.template,
            text_ar='سؤال إنهاء الزيارة: نتيجة المقابلة',
            question_type='text',
            stage='end_only',
            is_required=True,
            order=3
        )

    def test_start_visit_with_checkin_questions_and_duplicate_prevention(self):
        """
        Verify:
        1. Starting visit validates required check-in questions (stage='start_only').
        2. Starting visit saves answers in visit.questionnaire_answers.
        3. Starting visit changes status to 'started'.
        4. Attempting to start an already started visit does not repeat start or error out.
        5. Active visit dossier shows completion questions directly and does NOT render start button.
        """
        today = timezone.now().date()
        visit = Visit.objects.create(
            contact=self.customer,
            template=self.template,
            owner=self.rep,
            created_by=self.rep,
            date=today,
            status='planned',
            approval_status='approved',
            location_verified=True,
            verification_status='verified'
        )

        self.client.force_login(self.rep)

        # 1. Start without answering required start_only question -> rejected
        res_fail = self.client.post(reverse('visit_action', args=[visit.pk, 'start']), {})
        self.assertEqual(res_fail.status_code, 302)
        visit.refresh_from_db()
        self.assertEqual(visit.status, 'planned')

        # 2. Start with required answer -> succeeds
        res_ok = self.client.post(reverse('visit_action', args=[visit.pk, 'start']), {
            f'question_{self.q_start_req.id}': 'نعم',
            f'question_{self.q_start_opt.id}': 'وصلت في الموعد'
        })
        self.assertEqual(res_ok.status_code, 302)
        visit.refresh_from_db()
        self.assertEqual(visit.status, 'started')
        self.assertIsNotNone(visit.started_at)
        self.assertEqual(visit.questionnaire_answers.get(str(self.q_start_req.id)), 'نعم')
        self.assertEqual(visit.questionnaire_answers.get(str(self.q_start_opt.id)), 'وصلت في الموعد')

        # 3. Repeat start attempt on active visit -> safely redirects with info, does NOT crash or duplicate
        res_repeat = self.client.post(reverse('visit_action', args=[visit.pk, 'start']), {})
        self.assertEqual(res_repeat.status_code, 302)
        visit.refresh_from_db()
        self.assertEqual(visit.status, 'started')

        # 4. GET visit_detail for active visit
        res_detail = self.client.get(reverse('visit_detail', args=[visit.pk]))
        self.assertEqual(res_detail.status_code, 200)
        content = res_detail.content.decode('utf-8')
        # Shows completion questions and End Visit action
        self.assertIn('إنهاء وتوثيق الزيارة', content)
        self.assertIn(self.q_end_req.text_ar, content)
        # Does NOT have open start visit button
        self.assertNotIn('onclick="openStartVisitModal()"', content)

    def test_ended_visit_cannot_be_edited(self):
        """Ended / Finished visits are strictly locked from editing."""
        today = timezone.now().date()
        visit = Visit.objects.create(
            contact=self.customer,
            template=self.template,
            owner=self.rep,
            created_by=self.rep,
            date=today,
            status='finished',
            approval_status='approved',
            feedback='التقرير النهائي قبل الإغلاق'
        )

        self.client.force_login(self.rep)
        # Attempt to GET edit view
        res_get = self.client.get(reverse('visit_edit', args=[visit.pk]))
        self.assertEqual(res_get.status_code, 302)

        # Attempt to POST edit view
        res_post = self.client.post(reverse('visit_edit', args=[visit.pk]), {
            'contact': self.customer.id,
            'template': self.template.id,
            'date': today.strftime('%Y-%m-%d'),
            'feedback': 'محاولة تعديل مرفوضة'
        })
        self.assertEqual(res_post.status_code, 302)
        visit.refresh_from_db()
        self.assertEqual(visit.feedback, 'التقرير النهائي قبل الإغلاق')

    def test_in_progress_visit_smart_reapproval_rules(self):
        """
        When active visit is approved:
        - Rep editing critical fields revokes approval (waiting_for_reapproval=True).
        - Manager editing preserves approval (edited_by_manager logged).
        """
        from activities.models import ApprovalAuditLog

        today = timezone.now().date()
        visit = Visit.objects.create(
            contact=self.customer,
            template=self.template,
            owner=self.rep,
            created_by=self.rep,
            date=today,
            status='started',
            approval_status='approved',
            waiting_for_reapproval=False,
            feedback='ملاحظة مبدئية',
            questionnaire_answers={str(self.q_start_req.id): 'نعم'}
        )

        # 1. Rep edits critical fields -> approval revoked
        self.client.force_login(self.rep)
        res_rep_edit = self.client.post(reverse('visit_edit', args=[visit.pk]), {
            'contact': self.customer.id,
            'template': self.template.id,
            'date': today.strftime('%Y-%m-%d'),
            'feedback': 'تعديل المندوب للملاحظات',
            f'question_{self.q_start_req.id}': 'لا'
        })
        self.assertEqual(res_rep_edit.status_code, 302)
        visit.refresh_from_db()
        self.assertEqual(visit.approval_status, 'pending')
        self.assertTrue(visit.waiting_for_reapproval)
        self.assertEqual(visit.questionnaire_answers.get(str(self.q_start_req.id)), 'لا')

        # 2. Manager reapproves
        self.client.force_login(self.manager)
        self.client.post(reverse('visit_action', args=[visit.pk, 'approve']), {
            'approval_notes': 'تمت الموافقة على تعديل المندوب'
        })
        visit.refresh_from_db()
        self.assertEqual(visit.approval_status, 'approved')
        self.assertFalse(visit.waiting_for_reapproval)

        # 3. Manager edits critical fields -> approval retained, logged as edited_by_manager
        res_mgr_edit = self.client.post(reverse('visit_edit', args=[visit.pk]), {
            'contact': self.customer.id,
            'template': self.template.id,
            'owner': self.rep.id,
            'date': today.strftime('%Y-%m-%d'),
            'feedback': 'تعديل المدير الإداري',
            f'question_{self.q_start_req.id}': 'نعم'
        })
        self.assertEqual(res_mgr_edit.status_code, 302)
        visit.refresh_from_db()
        self.assertEqual(visit.approval_status, 'approved')
        self.assertFalse(visit.waiting_for_reapproval)
        self.assertEqual(visit.feedback, 'تعديل المدير الإداري')
        self.assertTrue(
            ApprovalAuditLog.objects.filter(visit=visit, action='edited_by_manager', actor=self.manager).exists()
        )


class PlannedVisitsMultiAreaFilteringTests(TestCase):
    """Verifies planned visits bulk planning drawer multi-area and multi-brick filtering."""

    def setUp(self):
        self.client = Client()
        self.superadmin_role, _ = Role.objects.get_or_create(
            name=Role.ROLE_SUPERADMIN,
            defaults={'display_name': 'مدير النظام الأعلى', 'is_super': True, 'is_system': True, 'is_active': True}
        )
        self.admin = User.objects.create_superuser(
            username='admin_multi_area',
            email='admin_multi@wea.com',
            password='TestPassword123!',
            role=self.superadmin_role
        )
        self.client.force_login(self.admin)

        self.cairo = Area.objects.create(name='محافظة القاهرة', code='GOV-CAI-M', area_type='governorate')
        self.giza = Area.objects.create(name='محافظة الجيزة', code='GOV-GIZ-M', area_type='governorate')
        self.alex = Area.objects.create(name='محافظة الإسكندرية', code='GOV-ALX-M', area_type='governorate')

        self.nasr_city = Area.objects.create(name='مدينة نصر', code='BRK-NASR-M', parent=self.cairo, area_type='subarea')
        self.dokki = Area.objects.create(name='الدقي', code='BRK-DOK-M', parent=self.giza, area_type='subarea')
        self.smouha = Area.objects.create(name='سموحة', code='BRK-SMO-M', parent=self.alex, area_type='subarea')

        self.c1 = Contact.objects.create(
            name='صيدلية مدينة نصر الحديثة',
            is_customer=True,
            status='customer',
            area=self.cairo,
            brick=self.nasr_city,
            created_by=self.admin
        )
        self.c2 = Contact.objects.create(
            name='صيدلية الدقي المركزية',
            is_customer=True,
            status='customer',
            area=self.giza,
            brick=self.dokki,
            created_by=self.admin
        )
        self.c3 = Contact.objects.create(
            name='صيدلية سموحة الإسكندرية',
            is_customer=True,
            status='customer',
            area=self.alex,
            brick=self.smouha,
            created_by=self.admin
        )

    def test_multi_main_area_drawer_filter(self):
        # Query with both Cairo and Giza (excluding Alex)
        url = reverse('planned_visits_list') + f'?action=load_contacts&main_area={self.cairo.id}&main_area={self.giza.id}'
        res = self.client.get(url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data.get('success'))
        returned_names = [c['name'] for c in data['contacts']]
        self.assertIn('صيدلية مدينة نصر الحديثة', returned_names)
        self.assertIn('صيدلية الدقي المركزية', returned_names)
        self.assertNotIn('صيدلية سموحة الإسكندرية', returned_names)

    def test_multi_brick_drawer_filter(self):
        # Query with Dokki and Smouha bricks
        url = reverse('planned_visits_list') + f'?action=load_contacts&area={self.dokki.id}&area={self.smouha.id}'
        res = self.client.get(url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data.get('success'))
        returned_names = [c['name'] for c in data['contacts']]
        self.assertIn('صيدلية الدقي المركزية', returned_names)
        self.assertIn('صيدلية سموحة الإسكندرية', returned_names)
        self.assertNotIn('صيدلية مدينة نصر الحديثة', returned_names)

