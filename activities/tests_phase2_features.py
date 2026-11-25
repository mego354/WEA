from decimal import Decimal
from django.core.exceptions import ValidationError
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission

from accounts.models import Role
from activities.models import Visit, VisitTemplate, VisitPlan, PlannedVisitDay, PlannedVisitItem
from activities.services import create_and_start_unplanned_visit, start_visit, end_visit
from contacts.models import Contact, ContactAddress
from master_data.models import Area, LocationSettings

User = get_user_model()


class VisitAddressSelectionAndAgendaTests(TestCase):
    """Comprehensive tests for Req A (Visit Address Selection & GPS) and Req B (Agenda Two Sections)."""

    def setUp(self):
        self.client = Client()

        self.cairo = Area.objects.create(name='القاهرة', code='CAI_P2')
        self.nasr = Area.objects.create(name='مدينة نصر', code='NSR_P2', parent=self.cairo)
        self.giza = Area.objects.create(name='الجيزة', code='GIZ_P2')
        self.dokki = Area.objects.create(name='الدقي', code='DOK_P2', parent=self.giza)

        rep_role = Role.objects.filter(name='rep').first()
        mgr_role = Role.objects.filter(name='manager').first()
        super_role = Role.objects.filter(name='superadmin').first()

        self.admin = User.objects.create_user(
            username='p2_admin', email='p2_admin@wea.com', password='Password123!',
            is_superuser=True, is_staff=True, role=super_role,
        )
        self.mgr_cairo = User.objects.create_user(
            username='p2_mgr_cai', email='p2_mgr_cai@wea.com', password='Password123!',
            role=mgr_role,
        )
        self.mgr_cairo.assigned_areas.add(self.cairo)

        self.mgr_giza = User.objects.create_user(
            username='p2_mgr_giz', email='p2_mgr_giz@wea.com', password='Password123!',
            role=mgr_role,
        )
        self.mgr_giza.assigned_areas.add(self.giza)

        self.rep = User.objects.create_user(
            username='p2_rep', email='p2_rep@wea.com', password='Password123!',
            role=rep_role,
        )
        self.rep.assigned_areas.add(self.nasr)

        self.rep_other = User.objects.create_user(
            username='p2_rep2', email='p2_rep2@wea.com', password='Password123!',
            role=rep_role,
        )
        self.rep_other.assigned_areas.add(self.nasr)

        self.loc_settings = LocationSettings.get_settings()
        self.loc_settings.tolerance = 300
        self.loc_settings.verify_visits = True
        self.loc_settings.verify_end_visit_distance = True
        self.loc_settings.auto_set_customer_location_in_visit = True  # Must still NEVER auto-save!
        self.loc_settings.save()

        self.template = VisitTemplate.objects.create(
            name='P2 Standard Visit',
            display_name_ar='زيارة قياسية',
            active=True,
        )

        # Contact with 2 addresses (Branch A & Branch B ~10km apart)
        self.multi_contact = Contact.objects.create(
            name='صيدلية الفروع المتعددة',
            code='MULTI01',
            account_type='Pharmacy',
            area=self.cairo,
            brick=self.nasr,
            is_customer=True,
            status='customer',
            created_by=self.rep,
        )
        self.addr_a = ContactAddress.objects.create(
            contact=self.multi_contact,
            title='الفرع الرئيسي - مدينة نصر',
            is_main=True,
            area=self.cairo,
            brick=self.nasr,
            street_address='شارع عباس العقاد',
            latitude=Decimal('30.0561000'),
            longitude=Decimal('31.3301000'),
        )
        self.addr_b = ContactAddress.objects.create(
            contact=self.multi_contact,
            title='فرع المعادي',
            is_main=False,
            area=self.cairo,
            brick=self.nasr,
            street_address='شارع 9 المعادي',
            latitude=Decimal('29.9602000'),
            longitude=Decimal('31.2569000'),
        )
        self.addr_no_gps = ContactAddress.objects.create(
            contact=self.multi_contact,
            title='فرع بدون إحداثيات',
            is_main=False,
            area=self.cairo,
            brick=self.nasr,
            street_address='شارع جديد',
            latitude=None,
            longitude=None,
        )

        # Another contact whose address must NOT be usable for multi_contact
        self.other_contact = Contact.objects.create(
            name='عيادة أخرى',
            code='OTHER01',
            account_type='Clinic',
            area=self.cairo,
            brick=self.nasr,
            is_customer=True,
            status='customer',
            created_by=self.rep,
        )
        self.other_addr = ContactAddress.objects.create(
            contact=self.other_contact,
            title='عنوان العيادة الأخرى',
            is_main=True,
            area=self.cairo,
            brick=self.nasr,
            latitude=Decimal('30.0561000'),
            longitude=Decimal('31.3301000'),
        )

    # ------------------------------------------------------------------
    # Requirement A: Visit Address Selection & GPS Verification
    # ------------------------------------------------------------------
    def test_unplanned_visit_uses_selected_address_for_start_and_end_gps(self):
        """Selecting Branch B verifies start AND end GPS against Branch B (not Branch A)."""
        self.client.force_login(self.rep)

        # 1. Near Branch A while selecting Branch B -> blocked & rolled back
        res_fail = self.client.post(reverse('visit_create'), {
            'contact': self.multi_contact.id,
            'contact_address_id': self.addr_b.id,
            'template': self.template.id,
            'latitude': '30.0561000',
            'longitude': '31.3301000',
        })
        self.assertEqual(res_fail.status_code, 200)
        self.assertFalse(Visit.objects.filter(contact=self.multi_contact, owner=self.rep).exists())

        # 2. Near Branch B while selecting Branch B -> succeeds and binds Branch B + snapshots
        res_ok = self.client.post(reverse('visit_create'), {
            'contact': self.multi_contact.id,
            'contact_address_id': self.addr_b.id,
            'template': self.template.id,
            'latitude': '29.9602500',
            'longitude': '31.2569500',
        })
        self.assertEqual(res_ok.status_code, 302)
        visit = Visit.objects.get(contact=self.multi_contact, owner=self.rep)
        self.assertEqual(visit.status, 'started')
        self.assertEqual(visit.contact_address_id, self.addr_b.id)
        self.assertEqual(visit.contact_address_title, 'فرع المعادي')
        self.assertIn('شارع 9 المعادي', visit.contact_address_text)
        self.assertAlmostEqual(float(visit.customer_latitude_snapshot), 29.9602, places=3)

        # 3. Attempting to END visit near Branch A fails (must match Branch B)
        res_end_fail = self.client.post(reverse('visit_action', args=[visit.pk, 'end']), {
            'latitude': '30.0561000',
            'longitude': '31.3301000',
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(res_end_fail.status_code, 400)
        visit.refresh_from_db()
        self.assertEqual(visit.status, 'started')

        # 4. Ending visit near Branch B succeeds
        res_end_ok = self.client.post(reverse('visit_action', args=[visit.pk, 'end']), {
            'latitude': '29.9602200',
            'longitude': '31.2569200',
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(res_end_ok.status_code, 200)
        visit.refresh_from_db()
        self.assertEqual(visit.status, 'finished')
        self.assertTrue(visit.location_verified)

    def test_cross_contact_address_id_is_rejected_server_side(self):
        """Passing another contact's ContactAddress ID is strictly rejected on create and start."""
        self.client.force_login(self.rep)

        # Unplanned create with other_contact's address
        res = self.client.post(reverse('visit_create'), {
            'contact': self.multi_contact.id,
            'contact_address_id': self.other_addr.id,
            'template': self.template.id,
            'latitude': '30.0561000',
            'longitude': '31.3301000',
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(res.status_code, 400)
        self.assertFalse(Visit.objects.filter(contact=self.multi_contact).exists())

        # Planned visit start with other_contact's address
        planned = Visit.objects.create(
            contact=self.multi_contact, template=self.template, owner=self.rep,
            created_by=self.rep, date=timezone.localdate(), status='planned',
            is_planned=True, approval_status='approved',
        )
        res_start = self.client.post(reverse('visit_action', args=[planned.pk, 'start']), {
            'contact_address_id': self.other_addr.id,
            'latitude': '30.0561000',
            'longitude': '31.3301000',
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(res_start.status_code, 400)
        planned.refresh_from_db()
        self.assertEqual(planned.status, 'planned')
        self.assertIsNone(planned.contact_address_id)

    def test_selected_address_without_gps_never_auto_saves_coordinates(self):
        """Selected address with NULL coords NEVER auto-saves device coords, even if auto_set setting is True."""
        self.client.force_login(self.rep)

        # Unauthorized rep blocked
        res_blocked = self.client.post(reverse('visit_create'), {
            'contact': self.multi_contact.id,
            'contact_address_id': self.addr_no_gps.id,
            'template': self.template.id,
            'latitude': '30.1111000',
            'longitude': '31.2222000',
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(res_blocked.status_code, 400)
        self.addr_no_gps.refresh_from_db()
        self.assertIsNone(self.addr_no_gps.latitude)
        self.assertIsNone(self.addr_no_gps.longitude)

        # Authorized bypass starts visit WITHOUT modifying addr_no_gps or addr_a
        bypass_perm = Permission.objects.get(codename='activities:visits/bypass_gps')
        self.rep.role.permissions.add(bypass_perm)
        self.rep.clear_perm_cache()

        res_ok = self.client.post(reverse('visit_create'), {
            'contact': self.multi_contact.id,
            'contact_address_id': self.addr_no_gps.id,
            'template': self.template.id,
            'latitude': '30.1111000',
            'longitude': '31.2222000',
            'force_bypass_location': '1',
            'bypass_reason': 'العنوان بدون إحداثيات',
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(res_ok.status_code, 200)
        self.addr_no_gps.refresh_from_db()
        self.addr_a.refresh_from_db()
        self.assertIsNone(self.addr_no_gps.latitude)
        self.assertIsNone(self.addr_no_gps.longitude)
        self.assertAlmostEqual(float(self.addr_a.latitude), 30.0561, places=4)

    def test_deleted_address_preserves_visit_snapshot_and_end_verification(self):
        """Deleting ContactAddress after start preserves visit title/text/coords snapshot for end verification."""
        visit = create_and_start_unplanned_visit(
            self.rep, self.multi_contact, self.template,
            contact_address_id=self.addr_b.id,
            lat='29.9602100', lng='31.2569100',
        )
        self.addr_b.delete()
        visit.refresh_from_db()
        self.assertIsNone(visit.contact_address)
        self.assertEqual(visit.contact_address_title, 'فرع المعادي')
        self.assertAlmostEqual(float(visit.customer_latitude_snapshot), 29.9602, places=3)

        # End visit near deleted Branch B snapshot succeeds; near Branch A fails
        with self.assertRaises(ValidationError):
            end_visit(visit, self.rep, lat='30.0561000', lng='31.3301000')
        end_visit(visit, self.rep, lat='29.9602200', lng='31.2569200')
        visit.refresh_from_db()
        self.assertEqual(visit.status, 'finished')

    def test_customers_search_api_includes_prefetched_addresses(self):
        """customers_search_api returns contact addresses ordered with main address first."""
        self.client.force_login(self.rep)
        res = self.client.get(reverse('customers_search_api') + '?q=MULTI01')
        self.assertEqual(res.status_code, 200)
        results = res.json()['results']
        self.assertEqual(len(results), 1)
        addrs = results[0]['addresses']
        self.assertEqual(len(addrs), 3)
        self.assertTrue(addrs[0]['is_main'])
        self.assertEqual(addrs[0]['id'], self.addr_a.id)
        self.assertTrue(addrs[0]['has_location'])

    # ------------------------------------------------------------------
    # Requirement B: Agenda Reorganization (Two Mutually Exclusive Sections)
    # ------------------------------------------------------------------
    def test_agenda_two_mutually_exclusive_sections_and_counts(self):
        """Agenda separates unfinished ('زيارات اليوم') from finished ('الزيارات الفعلية') with zero duplicates."""
        today = timezone.localdate()
        plan = VisitPlan.objects.create(
            assignee=self.rep, created_by=self.rep, date=today,
            approval_status='approved', comment='ملاحظة خطة اليوم',
        )
        pvd = PlannedVisitDay.objects.create(assignee=self.rep, date=today)

        v_planned_unstarted = Visit.objects.create(
            contact=self.multi_contact, template=self.template, owner=self.rep,
            created_by=self.rep, plan=plan, date=today, is_planned=True,
            status='planned', approval_status='approved',
        )
        v_planned_finished = Visit.objects.create(
            contact=self.other_contact, template=self.template, owner=self.rep,
            created_by=self.rep, plan=plan, date=today, is_planned=True,
            status='finished', started_at=timezone.now(), ended_at=timezone.now(),
            approval_status='approved',
        )
        PlannedVisitItem.objects.create(plan_day=pvd, plan=plan, contact=self.multi_contact, template=self.template, visit=v_planned_unstarted, order=1)
        PlannedVisitItem.objects.create(plan_day=pvd, plan=plan, contact=self.other_contact, template=self.template, visit=v_planned_finished, order=2, is_executed=True)

        v_unplanned_started = Visit.objects.create(
            contact=self.multi_contact, template=self.template, owner=self.rep,
            created_by=self.rep, date=today, is_planned=False,
            status='started', started_at=timezone.now(), ended_at=None,
            approval_status='approved',
        )
        v_unplanned_finished = Visit.objects.create(
            contact=self.other_contact, template=self.template, owner=self.rep,
            created_by=self.rep, date=today, is_planned=False,
            status='finished', started_at=timezone.now(), ended_at=timezone.now(),
            approval_status='approved',
        )
        v_cancelled = Visit.objects.create(
            contact=self.multi_contact, template=self.template, owner=self.rep,
            created_by=self.rep, date=today, is_planned=True,
            status='cancelled', approval_status='approved',
        )

        self.client.force_login(self.rep)
        resp = self.client.get(reverse('agenda') + f'?date={today.isoformat()}')
        self.assertEqual(resp.status_code, 200)

        today_ids = {c['visit'].id for c in resp.context['today_visit_cards'] if c['visit']}
        actual_ids = {c['visit'].id for c in resp.context['actual_visit_cards'] if c['visit']}

        self.assertEqual(today_ids, {v_planned_unstarted.id, v_unplanned_started.id})
        self.assertEqual(actual_ids, {v_planned_finished.id, v_unplanned_finished.id})
        self.assertEqual(today_ids & actual_ids, set())  # Strictly mutually exclusive!
        self.assertNotIn(v_cancelled.id, today_ids | actual_ids)

        self.assertEqual(resp.context['today_visits_count'], 2)
        self.assertEqual(resp.context['actual_visits_count'], 2)
        self.assertEqual(resp.context['total_visits_count'], 4)

        # HTML ordering: زيارات اليوم section appears before الزيارات الفعلية
        content = resp.content.decode('utf-8')
        idx_today = content.find('id="agenda-today-visits-section"')
        idx_actual = content.find('id="agenda-actual-visits-section"')
        self.assertGreater(idx_today, -1)
        self.assertGreater(idx_actual, idx_today)
        self.assertIn('زيارات اليوم', content)
        self.assertIn('الزيارات الفعلية', content)

        # Finish v_unplanned_started -> moves from زيارات اليوم to الزيارات الفعلية
        v_unplanned_started.status = 'finished'
        v_unplanned_started.ended_at = timezone.now()
        v_unplanned_started.save()

        resp2 = self.client.get(reverse('agenda') + f'?date={today.isoformat()}')
        today_ids2 = {c['visit'].id for c in resp2.context['today_visit_cards'] if c['visit']}
        actual_ids2 = {c['visit'].id for c in resp2.context['actual_visit_cards'] if c['visit']}
        self.assertEqual(today_ids2, {v_planned_unstarted.id})
        self.assertEqual(actual_ids2, {v_planned_finished.id, v_unplanned_finished.id, v_unplanned_started.id})
        self.assertEqual(today_ids2 & actual_ids2, set())

    def test_agenda_datascope_isolation(self):
        """Rep cannot view another rep's agenda; Giza manager cannot view Cairo rep's agenda; Cairo manager can."""
        today = timezone.localdate()
        self.client.force_login(self.rep)
        self.assertEqual(self.client.get(reverse('agenda') + f'?assignee={self.rep_other.id}&date={today.isoformat()}').status_code, 403)

        self.client.force_login(self.mgr_giza)
        self.assertEqual(self.client.get(reverse('agenda') + f'?assignee={self.rep.id}&date={today.isoformat()}').status_code, 403)

        self.client.force_login(self.mgr_cairo)
        self.assertEqual(self.client.get(reverse('agenda') + f'?assignee={self.rep.id}&date={today.isoformat()}').status_code, 200)

    def test_planned_item_visit_create_persists_selected_address_and_rejects_foreign_address(self):
        """Creating a planned visit from an uncreated PlannedVisitItem persists contact_address_id and rejects cross-contact IDs."""
        today = timezone.localdate()
        pvd = PlannedVisitDay.objects.create(assignee=self.rep, date=today)
        itm = PlannedVisitItem.objects.create(
            plan_day=pvd, contact=self.multi_contact, template=self.template, order=1,
        )
        self.client.force_login(self.rep)

        # Cross-contact address ID is rejected
        res_bad = self.client.post(reverse('visit_create') + f'?planned_item_id={itm.id}', {
            'planned_item_id': itm.id,
            'contact': self.multi_contact.id,
            'contact_address_id': self.other_addr.id,
            'template': self.template.id,
            'date': today.strftime('%Y-%m-%d'),
        })
        self.assertEqual(res_bad.status_code, 200)
        itm.refresh_from_db()
        self.assertIsNone(itm.visit)

        # Valid second address on the same contact is persisted on the created planned visit
        res_ok = self.client.post(reverse('visit_create') + f'?planned_item_id={itm.id}', {
            'planned_item_id': itm.id,
            'contact': self.multi_contact.id,
            'contact_address_id': self.addr_b.id,
            'template': self.template.id,
            'date': today.strftime('%Y-%m-%d'),
        })
        self.assertEqual(res_ok.status_code, 302)
        itm.refresh_from_db()
        self.assertIsNotNone(itm.visit)
        self.assertEqual(itm.visit.contact_address_id, self.addr_b.id)
        self.assertEqual(itm.visit.contact_address_title, self.addr_b.title)
        self.assertAlmostEqual(float(itm.visit.customer_latitude_snapshot), float(self.addr_b.latitude), places=3)

    def test_agenda_query_count_bounded_no_n_plus_1(self):
        """Agenda view keeps query growth sub-linear without N+1 per VisitPlan, PlannedVisitItem, or VisitTemplate."""
        from django.test.utils import CaptureQueriesContext
        from django.db import connection

        today = timezone.localdate()
        pvd, _ = PlannedVisitDay.objects.get_or_create(assignee=self.rep, date=today)

        def _add_plan_pair(idx):
            plan = VisitPlan.objects.create(
                assignee=self.rep, created_by=self.rep, date=today, approval_status='approved',
            )
            v_fin = Visit.objects.create(
                contact=self.multi_contact, template=self.template, owner=self.rep,
                created_by=self.rep, plan=plan, date=today, is_planned=True,
                status='finished', started_at=timezone.now(), ended_at=timezone.now(),
                approval_status='approved',
            )
            PlannedVisitItem.objects.create(
                plan=plan, plan_day=pvd, contact=self.multi_contact,
                template=self.template, visit=v_fin, order=idx * 2 + 1, is_executed=True,
            )
            v_plan = Visit.objects.create(
                contact=self.other_contact, template=self.template, owner=self.rep,
                created_by=self.rep, plan=plan, date=today, is_planned=True,
                status='planned', approval_status='approved',
            )
            PlannedVisitItem.objects.create(
                plan=plan, plan_day=pvd, contact=self.other_contact,
                template=self.template, visit=v_plan, order=idx * 2 + 2,
            )

        self.client.force_login(self.rep)
        _add_plan_pair(0)
        with CaptureQueriesContext(connection) as ctx_small:
            r1 = self.client.get(reverse('agenda') + f'?date={today.isoformat()}')
        self.assertEqual(r1.status_code, 200)

        # Add 3 more plans (6 more visits) -> query delta must stay small (no N+1 per plan/template/location)
        for i in range(1, 4):
            _add_plan_pair(i)
        with CaptureQueriesContext(connection) as ctx_large:
            r2 = self.client.get(reverse('agenda') + f'?date={today.isoformat()}')
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.context['today_visits_count'], 4)
        self.assertEqual(r2.context['actual_visits_count'], 4)
        delta = len(ctx_large) - len(ctx_small)
        self.assertLessEqual(delta, 10, f"Agenda query delta too high ({len(ctx_small)} -> {len(ctx_large)}, delta={delta})")

    def test_unplanned_visit_create_restricts_contacts_to_customers_only(self):
        """Unplanned visit creation (form, API customers_only=1, view, service) allows status='customer' only,
        while planned visits & default customers_search_api still allow status='lead'.
        """
        from activities.forms import VisitForm
        from activities.services import create_and_start_unplanned_visit
        from django.core.exceptions import ValidationError

        lead_contact = Contact.objects.create(
            name='عميل محتمل زيارة مباشرة', code='LEAD-UNPL', account_type='Pharmacy',
            area=self.cairo, brick=self.nasr, is_customer=True, status='lead',
            created_by=self.rep,
        )
        ContactAddress.objects.create(
            contact=lead_contact, title='العنوان الرئيسي', is_main=True,
            area=self.cairo, brick=self.nasr,
            latitude=Decimal('30.0561000'), longitude=Decimal('31.3301000'),
        )
        inactive_contact = Contact.objects.create(
            name='عميل غير نشط زيارة مباشرة', code='INACT-UNPL', account_type='Pharmacy',
            area=self.cairo, brick=self.nasr, is_customer=True, status='inactive',
            created_by=self.rep,
        )

        self.client.force_login(self.rep)

        # 1. customers_search_api?customers_only=1 excludes lead & inactive, returns customer
        res_cust_only_lead = self.client.get(reverse('customers_search_api') + '?customers_only=1&q=LEAD-UNPL')
        self.assertEqual(res_cust_only_lead.status_code, 200)
        self.assertEqual(res_cust_only_lead.json()['results'], [])

        res_cust_only_ok = self.client.get(reverse('customers_search_api') + '?customers_only=1&q=MULTI01')
        self.assertEqual(len(res_cust_only_ok.json()['results']), 1)

        # 2. Default customers_search_api (used by planned visits) still returns lead
        res_default_lead = self.client.get(reverse('customers_search_api') + '?q=LEAD-UNPL')
        self.assertEqual(len(res_default_lead.json()['results']), 1)

        # 3. Unplanned VisitForm queryset excludes lead & inactive and uses ?customers_only=1
        form_unplanned = VisitForm(user=self.rep)
        qs_ids = set(form_unplanned.fields['contact'].queryset.values_list('id', flat=True))
        self.assertIn(self.multi_contact.id, qs_ids)
        self.assertNotIn(lead_contact.id, qs_ids)
        self.assertNotIn(inactive_contact.id, qs_ids)
        self.assertEqual(
            form_unplanned.fields['contact'].widget.attrs.get('data-search-url'),
            '/contacts/api/search/?customers_only=1',
        )

        # 4. GET /visits/create/?contact_id=<lead> does not preselect lead
        res_get = self.client.get(reverse('visit_create') + f'?contact_id={lead_contact.id}')
        self.assertEqual(res_get.status_code, 200)
        self.assertIsNone(res_get.context['selected_contact'])

        # 5. Manipulated POST /visits/create/ and direct service call reject lead & inactive
        today_str = timezone.localdate().strftime('%Y-%m-%d')
        for bad_c in (lead_contact, inactive_contact):
            res_post = self.client.post(reverse('visit_create'), {
                'contact': bad_c.id,
                'template': self.template.id,
                'date': today_str,
                'latitude': '30.0561000',
                'longitude': '31.3301000',
            })
            self.assertEqual(res_post.status_code, 200)
            self.assertFalse(Visit.objects.filter(contact=bad_c).exists())
            with self.assertRaises(ValidationError):
                create_and_start_unplanned_visit(
                    self.rep, bad_c, self.template,
                    lat='30.0561000', lng='31.3301000',
                )
