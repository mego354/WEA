import json
import datetime
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.utils import timezone

from accounts.models import Role, Permission
from accounts.models import SecurityAuditLog
from master_data.models import Area, LocationSettings
from contacts.models import Contact, ContactAddress
from activities.models import (
    Visit, VisitTemplate, PlannedVisitDay, PlannedVisitItem
)

User = get_user_model()


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

