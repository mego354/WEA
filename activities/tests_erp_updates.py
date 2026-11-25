import datetime
import importlib
import shutil
import tempfile
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Permission as ErpPermission
from accounts.models import Role, RoleModuleScope, SecurityAuditLog
from activities.models import (
    ApprovalAuditLog,
    PlannedVisitDay,
    PlannedVisitItem,
    Visit,
    VisitPlan,
    VisitTemplate,
    VisitTemplateQuestion,
)
from activities.services import (
    create_and_start_unplanned_visit,
    start_visit,
)
from contacts.models import Contact
from master_data.media_service import store_attachment
from master_data.models import Area, ERPAttachment, LocationSettings
from notifications.formatters import build_arabic_notification, localize_contact_status
from notifications.models import Notification, RoleNotificationRule

User = get_user_model()


class ApprovedErpUpdatesTests(TestCase):
    """Comprehensive verification for approved ERP requirements A through I."""

    @classmethod
    def setUpTestData(cls):
        call_command('setup_permissions')
        cls.rep_role = Role.objects.get(name=Role.ROLE_REP)
        cls.manager_role = Role.objects.get(name=Role.ROLE_MANAGER)
        cls.super_role = Role.objects.get(name=Role.ROLE_SUPERADMIN)

        RoleModuleScope.objects.update_or_create(
            role=cls.rep_role,
            module='activities',
            defaults={'view_scope': 'own', 'manage_scope': 'own'},
        )
        RoleModuleScope.objects.update_or_create(
            role=cls.manager_role,
            module='activities',
            defaults={'view_scope': 'area', 'manage_scope': 'area'},
        )

        # Ensure notification rules for visit_created, visit_pending_approval, plan_submitted
        for role in (cls.super_role, cls.manager_role):
            for evt, mode in (
                ('activities.visit_created', 'all_in_scope'),
                ('activities.visit_pending_approval', 'approvers_only'),
                ('activities.plan_submitted', 'all_in_scope'),
            ):
                RoleNotificationRule.objects.update_or_create(
                    role=role,
                    event_code=evt,
                    defaults={
                        'is_enabled': True,
                        'delivery_mode': mode,
                        'same_area_only': True,
                        'include_record_owner': False,
                        'include_actor': False,
                    },
                )

    def setUp(self):
        self.loc = LocationSettings.get_settings()
        self.loc.tolerance = 300
        self.loc.verify_visits = True
        self.loc.verify_unplanned_visit_distance = True
        self.loc.verify_end_visit_distance = False
        self.loc.allow_visit_deletion_before_end = False
        self.loc.save()

        self.cairo = Area.objects.create(name='القاهرة تحديثات', code='UPD-CAI', area_type='governorate')
        self.giza = Area.objects.create(name='الجيزة تحديثات', code='UPD-GIZ', area_type='governorate')
        self.nasr = Area.objects.create(name='مدينة نصر تحديثات', code='UPD-NSR', area_type='subarea', parent=self.cairo)
        self.maadi = Area.objects.create(name='المعادي تحديثات', code='UPD-MAD', area_type='subarea', parent=self.cairo)
        self.dokki = Area.objects.create(name='الدقي تحديثات', code='UPD-DOK', area_type='subarea', parent=self.giza)

        self.superadmin = User.objects.create_superuser(
            username='sa_upd@wea.com', email='sa_upd@wea.com', password='Password123!'
        )
        self.mgr_cairo = User.objects.create_user(
            username='mgr_cai_upd@wea.com', email='mgr_cai_upd@wea.com', password='Password123!',
            role=self.manager_role, is_active=True
        )
        self.mgr_cairo.assigned_areas.add(self.cairo)

        self.mgr_giza = User.objects.create_user(
            username='mgr_giz_upd@wea.com', email='mgr_giz_upd@wea.com', password='Password123!',
            role=self.manager_role, is_active=True
        )
        self.mgr_giza.assigned_areas.add(self.giza)

        self.rep_nasr = User.objects.create_user(
            username='rep_nasr_upd@wea.com', email='rep_nasr_upd@wea.com', password='Password123!',
            role=self.rep_role, is_active=True
        )
        self.rep_nasr.assigned_areas.add(self.nasr)

        self.c_nasr = Contact.objects.create(
            name='صيدلية نصر الرئيسية',
            code='PH-UPD-1',
            mobile='01012345678',
            specialty='صيدلية مجتمعية',
            account_type='Pharmacy',
            is_customer=True,
            status='customer',
            area=self.cairo,
            brick=self.nasr,
            latitude=Decimal('30.056100'),
            longitude=Decimal('31.330100'),
            created_by=self.rep_nasr,
        )
        self.c_nasr_lead = Contact.objects.create(
            name='عيادة الأمل المحتملة',
            code='CL-UPD-2',
            mobile='01098765432',
            specialty='باطنة',
            account_type='Clinic',
            is_customer=True,
            status='lead',
            area=self.cairo,
            brick=self.nasr,
            latitude=Decimal('30.056200'),
            longitude=Decimal('31.330200'),
            created_by=self.rep_nasr,
        )
        self.c_maadi = Contact.objects.create(
            name='صيدلية المعادي الأخوة',
            code='PH-MAD-3',
            account_type='Pharmacy',
            is_customer=True,
            status='customer',
            area=self.cairo,
            brick=self.maadi,
            created_by=self.mgr_cairo,
        )
        self.c_dokki = Contact.objects.create(
            name='صيدلية الدقي الجيزة',
            code='PH-DOK-4',
            account_type='Pharmacy',
            is_customer=True,
            status='customer',
            area=self.giza,
            brick=self.dokki,
            created_by=self.mgr_giza,
        )
        self.c_inactive = Contact.objects.create(
            name='صيدلية موقوفة',
            code='PH-INA-5',
            account_type='Pharmacy',
            is_customer=True,
            status='inactive',
            area=self.cairo,
            brick=self.nasr,
            created_by=self.rep_nasr,
        )

        self.template = VisitTemplate.objects.create(
            name='UPD Standard Template',
            display_name_ar='قالب التحديثات القياسي',
            active=True,
        )

    # ------------------------------------------------------------------
    # Req A: Visit deletion decoupled from LocationSettings + Unified List
    # ------------------------------------------------------------------
    def test_req_a_visit_deletion_rules_cleanup_audit_and_unified_list(self):
        # Permission label check
        del_perm = ErpPermission.objects.get(codename='activities:visits/delete')
        self.assertEqual(del_perm.name, 'حذف الزيارات')

        today = timezone.localdate()
        plan = VisitPlan.objects.create(date=today, assignee=self.rep_nasr, created_by=self.rep_nasr, approval_status='approved')
        pday = PlannedVisitDay.objects.create(assignee=self.rep_nasr, date=today, created_by=self.rep_nasr)

        # Unended visit with PlannedVisitItem, ApprovalAuditLog, ERPAttachment
        temp_media = tempfile.mkdtemp()
        try:
            with override_settings(MEDIA_ROOT=temp_media):
                v_started = Visit.objects.create(
                    contact=self.c_nasr, template=self.template, owner=self.rep_nasr, created_by=self.rep_nasr,
                    date=today, status='started', is_planned=True, plan=plan, approval_status='approved',
                )
                pitem = PlannedVisitItem.objects.create(
                    plan=plan, plan_day=pday, order=1, contact=self.c_nasr, template=self.template, visit=v_started
                )
                ApprovalAuditLog.objects.create(
                    record_type='visit', visit=v_started, action='approved', actor=self.mgr_cairo,
                    status_before='pending', status_after='approved', reason='اعتماد قبل الحذف'
                )
                att, _ = store_attachment(
                    v_started,
                    SimpleUploadedFile('doc.pdf', b'%PDF-1.4\n%UNIQUE_ATT_CONTENT\n%%EOF', content_type='application/pdf'),
                    self.rep_nasr,
                )
                att_key = att.storage_key

                # 1. Cross-area finished visit: Giza manager is denied 403/404 BEFORE seeing finished 400
                v_finished = Visit.objects.create(
                    contact=self.c_nasr, template=self.template, owner=self.rep_nasr, created_by=self.rep_nasr,
                    date=today, status='finished', ended_at=timezone.now(), approval_status='approved'
                )
                self.manager_role.permissions.add(del_perm)
                self.mgr_giza.clear_perm_cache()
                self.client.force_login(self.mgr_giza)
                res_idor_fin = self.client.post(
                    reverse('visit_delete', args=[v_finished.pk]),
                    HTTP_X_REQUESTED_WITH='XMLHttpRequest',
                )
                self.assertIn(res_idor_fin.status_code, (403, 404))

                # 2. Unauthorized user without activities:visits/delete -> 403
                self.rep_role.permissions.remove(del_perm)
                self.rep_nasr.clear_perm_cache()
                self.client.force_login(self.rep_nasr)
                res_unauth = self.client.post(
                    reverse('visit_delete', args=[v_started.pk]),
                    HTTP_X_REQUESTED_WITH='XMLHttpRequest',
                )
                self.assertEqual(res_unauth.status_code, 403)
                self.assertTrue(Visit.objects.filter(pk=v_started.pk).exists())

                # 3. Grant delete permission with allow_visit_deletion_before_end=False -> STILL SUCCEEDS
                self.loc.allow_visit_deletion_before_end = False
                self.loc.save()
                self.rep_role.permissions.add(del_perm)
                self.rep_nasr.clear_perm_cache()

                with self.captureOnCommitCallbacks(execute=True):
                    res_del = self.client.post(
                        reverse('visit_delete', args=[v_started.pk]),
                        {'reason': 'اختبار حذف زيارة بدأ تنفيذها'},
                        HTTP_X_REQUESTED_WITH='XMLHttpRequest',
                    )
                self.assertEqual(res_del.status_code, 200)
                self.assertTrue(res_del.json()['success'])
                self.assertFalse(Visit.objects.filter(pk=v_started.pk).exists())
                # Associated PlannedVisitItem & empty VisitPlan deleted cleanly
                self.assertFalse(PlannedVisitItem.objects.filter(pk=pitem.pk).exists())
                self.assertFalse(VisitPlan.objects.filter(pk=plan.pk).exists())
                # Attachment cleaned up from DB and storage
                self.assertFalse(ERPAttachment.objects.filter(pk=att.pk).exists())
                from django.core.files.storage import default_storage
                self.assertFalse(default_storage.exists(att_key))

                # SecurityAuditLog snapshot + approval history preserved
                audit = SecurityAuditLog.objects.filter(action_type='VISIT_DELETED', record_id=str(v_started.pk)).first()
                self.assertIsNotNone(audit)
                self.assertIn('approval_history', audit.previous_values)
                self.assertEqual(len(audit.previous_values['approval_history']), 1)

                # 4. Authorized deletion on finished visit ALSO succeeds (any lifecycle stage) and logs snapshot
                v_fin_pk = v_finished.pk
                res_fin = self.client.post(
                    reverse('visit_delete', args=[v_fin_pk]),
                    HTTP_X_REQUESTED_WITH='XMLHttpRequest',
                )
                self.assertEqual(res_fin.status_code, 200)
                self.assertTrue(res_fin.json()['success'])
                self.assertFalse(Visit.objects.filter(pk=v_fin_pk).exists())
                fin_audit = SecurityAuditLog.objects.filter(action_type='VISIT_DELETED', record_id=str(v_fin_pk)).first()
                self.assertIsNotNone(fin_audit)
                self.assertEqual(fin_audit.previous_values.get('status'), 'finished')
                self.assertIsNotNone(fin_audit.previous_values.get('ended_at'))

                # 4b. PlannedVisitItem deletion allowed while pending approval, and finished item requires visits/delete
                plan_p = VisitPlan.objects.create(date=today, assignee=self.rep_nasr, created_by=self.rep_nasr, approval_status='pending')
                v_pending = Visit.objects.create(
                    contact=self.c_nasr, template=self.template, owner=self.rep_nasr, created_by=self.rep_nasr,
                    date=today, status='planned', is_planned=True, plan=plan_p, approval_status='pending',
                )
                item_pending = PlannedVisitItem.objects.create(
                    plan=plan_p, plan_day=pday, order=2, contact=self.c_nasr, template=self.template, visit=v_pending
                )
                self.client.force_login(self.mgr_cairo)
                res_item_pend = self.client.post(
                    reverse('planned_visit_item_delete', args=[item_pending.pk]),
                    HTTP_X_REQUESTED_WITH='XMLHttpRequest',
                )
                self.assertEqual(res_item_pend.status_code, 200)
                self.assertFalse(PlannedVisitItem.objects.filter(pk=item_pending.pk).exists())
                self.assertFalse(Visit.objects.filter(pk=v_pending.pk).exists())
                self.assertFalse(VisitPlan.objects.filter(pk=plan_p.pk).exists())

                # Finished planned item deletion requires activities:visits/delete
                plan_f = VisitPlan.objects.create(date=today, assignee=self.rep_nasr, created_by=self.rep_nasr, approval_status='approved')
                v_pfin = Visit.objects.create(
                    contact=self.c_nasr_lead, template=self.template, owner=self.rep_nasr, created_by=self.rep_nasr,
                    date=today, status='finished', ended_at=timezone.now(), is_planned=True, plan=plan_f, approval_status='approved',
                )
                item_pfin = PlannedVisitItem.objects.create(
                    plan=plan_f, plan_day=pday, order=3, contact=self.c_nasr_lead, template=self.template, visit=v_pfin
                )
                self.manager_role.permissions.remove(del_perm)
                self.mgr_cairo.clear_perm_cache()
                res_item_fin_denied = self.client.post(
                    reverse('planned_visit_item_delete', args=[item_pfin.pk]),
                    HTTP_X_REQUESTED_WITH='XMLHttpRequest',
                )
                self.assertEqual(res_item_fin_denied.status_code, 403)
                self.assertTrue(PlannedVisitItem.objects.filter(pk=item_pfin.pk).exists())

                self.manager_role.permissions.add(del_perm)
                self.mgr_cairo.clear_perm_cache()
                res_item_fin_ok = self.client.post(
                    reverse('planned_visit_item_delete', args=[item_pfin.pk]),
                    HTTP_X_REQUESTED_WITH='XMLHttpRequest',
                )
                self.assertEqual(res_item_fin_ok.status_code, 200)
                self.assertFalse(PlannedVisitItem.objects.filter(pk=item_pfin.pk).exists())
                self.assertFalse(Visit.objects.filter(pk=v_pfin.pk).exists())
                self.assertFalse(VisitPlan.objects.filter(pk=plan_f.pk).exists())

                self.client.force_login(self.rep_nasr)

                # 5. Unified visits_list UI ignores view=cards and keeps Delete inside more_vert
                Visit.objects.create(
                    contact=self.c_nasr, template=self.template, owner=self.rep_nasr, created_by=self.rep_nasr,
                    date=today, status='finished', ended_at=timezone.now(), approval_status='approved',
                )
                self.client.force_login(self.rep_nasr)
                res_plain = self.client.get(reverse('visits_list'))
                self.assertEqual(res_plain.status_code, 200)
                self.assertNotIn('view=cards', res_plain.content.decode('utf-8'))

                res_list = self.client.get(reverse('visits_list'), {'view': 'cards'})
                self.assertEqual(res_list.status_code, 200)
                self.assertEqual(res_list.context['view_mode'], 'table')
                html = res_list.content.decode('utf-8')
                self.assertIn('<table', html)
                self.assertIn('more_vert', html)
                self.assertIn('visit_delete', html) if False else self.assertIn('حذف الزيارة', html)
        finally:
            shutil.rmtree(temp_media, ignore_errors=True)

        # Shared storage key must NOT be deleted when still referenced by another attachment
        temp_media2 = tempfile.mkdtemp()
        try:
            with override_settings(MEDIA_ROOT=temp_media2):
                v1 = Visit.objects.create(contact=self.c_nasr, template=self.template, owner=self.rep_nasr, date=today, status='planned')
                v2 = Visit.objects.create(contact=self.c_nasr_lead, template=self.template, owner=self.rep_nasr, date=today, status='planned')
                shared_bytes = b'%PDF-1.4\n%SHARED_FILE_BYTES_ABC\n%%EOF'
                a1, _ = store_attachment(v1, SimpleUploadedFile('shared.pdf', shared_bytes, content_type='application/pdf'), self.rep_nasr)
                a2, _ = store_attachment(v2, SimpleUploadedFile('shared.pdf', shared_bytes, content_type='application/pdf'), self.rep_nasr)
                self.assertEqual(a1.storage_key, a2.storage_key)

                self.client.force_login(self.superadmin)
                with self.captureOnCommitCallbacks(execute=True):
                    self.client.post(reverse('visit_delete', args=[v1.pk]), HTTP_X_REQUESTED_WITH='XMLHttpRequest')
                from django.core.files.storage import default_storage
                self.assertTrue(ERPAttachment.objects.filter(pk=a2.pk).exists())
                self.assertTrue(default_storage.exists(a2.storage_key))
        finally:
            shutil.rmtree(temp_media2, ignore_errors=True)

    # ------------------------------------------------------------------
    # Req B: customers_search_api excludes area__name & brick__name
    # ------------------------------------------------------------------
    def test_req_b_customers_search_api_excludes_area_and_brick_and_preserves_scope(self):
        self.client.force_login(self.rep_nasr)

        # Matches name, code, mobile, specialty
        for query in ('صيدلية نصر', 'PH-UPD-1', '01012345678', 'مجتمعية', str(self.c_nasr.serial_num)):
            res = self.client.get(reverse('customers_search_api'), {'q': query})
            self.assertEqual(res.status_code, 200)
            ids = [r['id'] for r in res.json()['results']]
            self.assertIn(self.c_nasr.id, ids, f"Expected match for {query}")

        # Area/brick names must NOT match when contact text fields do not contain them
        res_area = self.client.get(reverse('customers_search_api'), {'q': 'القاهرة تحديثات'})
        self.assertEqual([r['id'] for r in res_area.json()['results']], [])

        res_brick = self.client.get(reverse('customers_search_api'), {'q': 'مدينة نصر تحديثات'})
        self.assertEqual([r['id'] for r in res_brick.json()['results']], [])

        # DataScope preserved: rep sees Nasr City only, never Maadi / Dokki / inactive
        res_all = self.client.get(reverse('customers_search_api'))
        ids_all = {r['id'] for r in res_all.json()['results']}
        self.assertEqual(ids_all, {self.c_nasr.id, self.c_nasr_lead.id})

        # Unrelated sales_customers_search_api still returns customer normally
        res_sales = self.client.get(reverse('sales_customers_search_api'), {'q': 'نصر'})
        self.assertEqual(res_sales.status_code, 200)
        self.assertTrue(any(r['id'] == self.c_nasr.id for r in res_sales.json()['results']))

    # ------------------------------------------------------------------
    # Req C: Strict English Contact Statuses + Migration Logic
    # ------------------------------------------------------------------
    def test_req_c_contact_status_standardization(self):
        self.assertEqual(
            Contact.STATUS_CHOICES,
            [('customer', 'Customer'), ('lead', 'Lead'), ('inactive', 'Inactive')],
        )

        # Model clean rejects legacy/Arabic status
        bad_contact = Contact(name='اختبار', status='active', is_customer=True)
        with self.assertRaises(ValidationError):
            bad_contact.full_clean()

        # Notifications formatter & localization strictly English
        self.assertEqual(localize_contact_status('customer'), 'Customer')
        self.assertEqual(localize_contact_status('lead'), 'Lead')
        self.assertEqual(localize_contact_status('inactive'), 'Inactive')
        fmt = build_arabic_notification(
            'contacts.contact_status_changed', target_obj=self.c_nasr, actor=self.superadmin,
            extra={'old_status': 'lead', 'new_status': 'customer'}
        )
        self.assertIn('Lead', fmt['body'])
        self.assertIn('Customer', fmt['body'])
        self.assertNotIn('عميل محتمل', fmt['body'])

        # Views accept only customer / lead / inactive
        self.client.force_login(self.superadmin)
        res_bad_post = self.client.post(
            reverse('contact_update_status', args=[self.c_nasr.pk]),
            {'status': 'active'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(res_bad_post.status_code, 400)

        res_ok_post = self.client.post(
            reverse('contact_update_status', args=[self.c_nasr.pk]),
            {'status': 'lead'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(res_ok_post.status_code, 200)
        self.assertEqual(res_ok_post.json()['status_label'], 'Lead')

        # 3-column Kanban & table render English labels cleanly
        res_kanban = self.client.get(reverse('contacts_list'), {'view': 'kanban'})
        self.assertEqual(res_kanban.status_code, 200)
        html = res_kanban.content.decode('utf-8')
        self.assertIn('lg:grid-cols-3', html)
        self.assertNotIn('نشط', html.split('<table')[0]) if '<table' in html else None

        # Migration helper normalization test (raw DB values -> canonical)
        mig_mod = importlib.import_module('contacts.migrations.0011_standardize_contact_statuses')
        Contact.objects.filter(pk=self.c_maadi.pk).update(status='active')
        Contact.objects.filter(pk=self.c_dokki.pk).update(status='supplier')
        from django.apps import apps
        mig_mod.normalize_contact_statuses_forward(apps, None)
        self.c_maadi.refresh_from_db()
        self.c_dokki.refresh_from_db()
        self.assertEqual(self.c_maadi.status, 'customer')
        self.assertEqual(self.c_dokki.status, 'customer')

    # ------------------------------------------------------------------
    # Req D: Separate Planned / Unplanned / Total Counts in Agenda
    # ------------------------------------------------------------------
    def test_req_d_agenda_separate_visit_counts(self):
        today = timezone.localdate()
        pday = PlannedVisitDay.objects.create(assignee=self.rep_nasr, date=today, created_by=self.rep_nasr)
        # 1 uncreated PlannedVisitItem + 1 standalone is_planned=True Visit + 1 unplanned Visit
        PlannedVisitItem.objects.create(plan_day=pday, order=1, contact=self.c_nasr, template=self.template)
        Visit.objects.create(
            contact=self.c_nasr_lead, template=self.template, owner=self.rep_nasr, created_by=self.rep_nasr,
            date=today, status='planned', is_planned=True, approval_status='approved'
        )
        Visit.objects.create(
            contact=self.c_nasr, template=self.template, owner=self.rep_nasr, created_by=self.rep_nasr,
            date=today, status='started', is_planned=False, approval_status='approved'
        )

        self.client.force_login(self.rep_nasr)
        res = self.client.get(reverse('agenda'), {'date': today.strftime('%Y-%m-%d')})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.context['planned_visits_count'], 2)
        self.assertEqual(res.context['unplanned_visits_count'], 1)
        self.assertEqual(res.context['total_visits_count'], 3)
        self.assertEqual(res.context['visits_count'], 3)
        self.assertContains(res, 'خارج الخطة')

    # ------------------------------------------------------------------
    # Req E: GPS Bypass Behavior (Strict bypass_gps only + UI reset/hidden)
    # ------------------------------------------------------------------
    def test_req_e_gps_bypass_permission_tolerance_and_ui(self):
        today = timezone.localdate()
        exc_perm = ErpPermission.objects.filter(codename='activities:visits/gps_request_exception').first()
        bypass_perm = ErpPermission.objects.get(codename='activities:visits/bypass_gps')
        if exc_perm:
            self.rep_role.permissions.add(exc_perm)
        self.rep_role.permissions.remove(bypass_perm)
        self.rep_nasr.clear_perm_cache()

        # Non-bypass user gets NO bypass container on create/detail/agenda even with gps_request_exception
        self.client.force_login(self.rep_nasr)
        res_form = self.client.get(reverse('visit_create'))
        self.assertEqual(res_form.status_code, 200)
        self.assertNotIn('id="distance-bypass-container"', res_form.content.decode('utf-8'))
        self.assertIn('id="distance-error-banner"', res_form.content.decode('utf-8'))

        # Grant bypass permission -> container exists and starts hidden
        self.rep_role.permissions.add(bypass_perm)
        self.rep_nasr.clear_perm_cache()
        res_form_bp = self.client.get(reverse('visit_create'))
        form_bp_html = res_form_bp.content.decode('utf-8')
        self.assertIn('id="distance-bypass-container" class="hidden', form_bp_html)
        self.assertNotIn('10 أحرف', form_bp_html)

        # When bypass_reason_mandatory=False, authorized user can start unplanned visit out-of-range with empty reason
        self.loc.bypass_reason_mandatory = False
        self.loc.save()
        res_bypass_no_reason = self.client.post(reverse('visit_create'), {
            'contact': self.c_nasr.id,
            'template': self.template.id,
            'date': today.strftime('%Y-%m-%d'),
            'latitude': '30.200000',
            'longitude': '31.500000',
            'force_bypass_location': '1',
            'bypass_reason': '',
            'confirm_duplicate': '1',
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(res_bypass_no_reason.status_code, 200)
        created_bp = Visit.objects.get(pk=res_bypass_no_reason.json()['visit_id'])
        self.assertTrue(created_bp.gps_forced_start)
        created_bp.status = 'finished'
        created_bp.ended_at = timezone.now()
        created_bp.save(update_fields=['status', 'ended_at'])

        # Missing mandatory bypass reason rejected when out of range
        self.loc.bypass_reason_mandatory = True
        self.loc.save()
        v_planned = Visit.objects.create(
            contact=self.c_nasr, template=self.template, owner=self.rep_nasr, created_by=self.rep_nasr,
            date=today, status='planned', is_planned=True, approval_status='approved'
        )
        res_missing_reason = self.client.post(reverse('visit_action', args=[v_planned.pk, 'start']), {
            'latitude': '30.200000',
            'longitude': '31.500000',
            'force_bypass_location': '1',
            'bypass_reason': '',
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(res_missing_reason.status_code, 400)

        # Within tolerance ignores submitted bypass flag -> normal verified start
        res_in_range = self.client.post(reverse('visit_action', args=[v_planned.pk, 'start']), {
            'latitude': '30.056100',
            'longitude': '31.330100',
            'force_bypass_location': '1',
            'bypass_reason': 'سبب طويل لن يستخدم داخل النطاق',
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(res_in_range.status_code, 200)
        v_planned.refresh_from_db()
        self.assertTrue(v_planned.location_verified)
        self.assertFalse(v_planned.gps_forced_start)

    # ------------------------------------------------------------------
    # Req F: Atomic Unplanned Visit Create + Immediate Start
    # ------------------------------------------------------------------
    def test_req_f_atomic_unplanned_visit_create_and_rollback(self):
        today = timezone.localdate()
        future_str = (today + datetime.timedelta(days=5)).strftime('%Y-%m-%d')
        q_start = VisitTemplateQuestion.objects.create(
            template=self.template, text_ar='سؤال بداية الزيارة', stage='start_only', question_type='text', is_required=True
        )

        self.client.force_login(self.rep_nasr)
        self.rep_role.permissions.remove(ErpPermission.objects.get(codename='activities:visits/bypass_gps'))
        self.rep_nasr.clear_perm_cache()

        # 1. Missing required start_only answer -> full rollback (0 visits, 0 notifications)
        with self.captureOnCommitCallbacks(execute=True):
            res_missing_q = self.client.post(reverse('visit_create'), {
                'contact': self.c_nasr.id,
                'template': self.template.id,
                'date': future_str,
                'latitude': '30.056100',
                'longitude': '31.330100',
            })
        self.assertEqual(res_missing_q.status_code, 200)
        self.assertEqual(Visit.objects.count(), 0)
        self.assertEqual(Notification.objects.count(), 0)

        # 2. Out-of-range GPS without bypass -> full rollback (0 visits, 0 notifications)
        with self.captureOnCommitCallbacks(execute=True):
            res_bad_gps = self.client.post(reverse('visit_create'), {
                'contact': self.c_nasr.id,
                'template': self.template.id,
                'date': future_str,
                'latitude': '30.500000',
                'longitude': '31.800000',
                f'question_{q_start.id}': 'جاهز للزيارة',
            })
        self.assertEqual(res_bad_gps.status_code, 200)
        self.assertEqual(Visit.objects.count(), 0)
        self.assertEqual(Notification.objects.count(), 0)

        # 3. Valid GPS + answer + future date -> creates & starts atomically with locked today date
        with self.captureOnCommitCallbacks(execute=True):
            res_ok = self.client.post(reverse('visit_create'), {
                'contact': self.c_nasr.id,
                'template': self.template.id,
                'date': future_str,
                'latitude': '30.056100',
                'longitude': '31.330100',
                'device_accuracy': '12',
                f'question_{q_start.id}': 'بدء زيارة مباشرة',
            })
        self.assertEqual(res_ok.status_code, 302)
        v = Visit.objects.get()
        self.assertFalse(v.is_planned)
        self.assertEqual(v.date, today)
        self.assertEqual(v.status, 'started')
        self.assertIsNotNone(v.started_at)
        self.assertEqual(v.approval_status, 'approved')
        self.assertEqual(v.questionnaire_answers.get(str(q_start.id)), 'بدء زيارة مباشرة')

    # ------------------------------------------------------------------
    # Req G: Single Open Visit per Owner + Reconciliation Helper
    # ------------------------------------------------------------------
    def test_req_g_single_open_visit_enforced_across_all_roles_and_reconciled(self):
        today = timezone.localdate()
        self.loc.verify_visits = False
        self.loc.save()

        # SuperAdmin CANNOT hold two open visits either (zero role bypass)
        v_sa1 = create_and_start_unplanned_visit(
            self.superadmin, self.c_nasr, self.template, owner=self.superadmin
        )
        self.assertEqual(v_sa1.status, 'started')

        with self.assertRaises(ValidationError):
            create_and_start_unplanned_visit(
                self.superadmin, self.c_nasr_lead, self.template, owner=self.superadmin
            )

        # Planned visit start also blocked while open visit exists
        v_sa_planned = Visit.objects.create(
            contact=self.c_nasr_lead, template=self.template, owner=self.superadmin, created_by=self.superadmin,
            date=today, status='planned', is_planned=True, approval_status='approved'
        )
        with self.assertRaises(ValidationError):
            start_visit(v_sa_planned, self.superadmin)

        # Different owner can hold their own open visit simultaneously
        v_rep = create_and_start_unplanned_visit(
            self.rep_nasr, self.c_nasr, self.template, owner=self.rep_nasr
        )
        self.assertEqual(v_rep.status, 'started')

        # Visit.clean() rejects a second open visit for same owner
        dup_candidate = Visit(
            contact=self.c_nasr_lead, owner=self.superadmin, date=today, status='started', ended_at=None
        )
        with self.assertRaises(ValidationError):
            dup_candidate.clean()

        # DB UniqueConstraint rejects raw second open visit for same owner (inside savepoint)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Visit.objects.create(
                    contact=self.c_nasr_lead, owner=self.superadmin, date=today, status='started', ended_at=None
                )

        # Ending open visit allows starting the next one
        v_sa1.status = 'finished'
        v_sa1.ended_at = timezone.now()
        v_sa1.save(update_fields=['status', 'ended_at'])
        v_sa2 = start_visit(v_sa_planned, self.superadmin)
        self.assertEqual(v_sa2.status, 'started')

        # Test migration reconciliation helper directly (idempotent with 1 open visit)
        mig_mod = importlib.import_module('activities.migrations.0025_reconcile_and_enforce_single_open_visit')
        now = timezone.now()
        v_new = Visit.objects.create(contact=self.c_dokki, owner=self.mgr_giza, date=today, status='started', started_at=now)
        self.assertEqual(mig_mod.reconcile_duplicate_open_visits(Visit, ApprovalAuditLog, SecurityAuditLog), 0)
        v_new.refresh_from_db()
        self.assertEqual(v_new.status, 'started')

    # ------------------------------------------------------------------
    # Req H: Planned-Visits Customer / Lead Filter
    # ------------------------------------------------------------------
    def test_req_h_planned_visits_contact_status_filter(self):
        self.client.force_login(self.rep_nasr)

        # Empty -> returns customer + lead, excludes inactive
        res_all = self.client.get(reverse('planned_visits_list'), {'action': 'load_contacts', 'format': 'json'})
        self.assertEqual(res_all.status_code, 200)
        names_all = {c['name'] for c in res_all.json()['contacts']}
        self.assertEqual(names_all, {self.c_nasr.name, self.c_nasr_lead.name})

        # contact_status=customer -> customer only
        res_cust = self.client.get(reverse('planned_visits_list'), {
            'action': 'load_contacts', 'format': 'json', 'contact_status': 'customer'
        })
        self.assertEqual({c['id'] for c in res_cust.json()['contacts']}, {self.c_nasr.id})

        # contact_status=lead -> lead only + works with select_all_ids & search
        res_lead = self.client.get(reverse('planned_visits_list'), {
            'action': 'select_all_ids', 'format': 'json', 'contact_status': 'lead', 'contact_search': 'الأمل'
        })
        self.assertEqual([c['id'] for c in res_lead.json()['contacts']], [self.c_nasr_lead.id])

        # contact_status=inactive is ignored and never exposes inactive records
        res_ina = self.client.get(reverse('planned_visits_list'), {
            'action': 'load_contacts', 'format': 'json', 'contact_status': 'inactive'
        })
        ids_ina = {c['id'] for c in res_ina.json()['contacts']}
        self.assertNotIn(self.c_inactive.id, ids_ina)

        # SSR drawer renders contact_status dropdown
        res_ssr = self.client.get(reverse('planned_visits_list'), {'contact_status': 'lead'})
        self.assertContains(res_ssr, 'name="contact_status"')
        self.assertContains(res_ssr, '<option value="lead" selected>')

        # Direct POST bulk_add for an inactive contact is rejected (400)
        res_ina_post = self.client.post(reverse('planned_visits_bulk_add'), {
            'date': (timezone.localdate() + datetime.timedelta(days=3)).strftime('%Y-%m-%d'),
            'template_id': self.template.id,
            'contact_ids': [self.c_inactive.id],
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(res_ina_post.status_code, 400)

    # ------------------------------------------------------------------
    # Req I: Visit vs Planned-Visit Notifications
    # ------------------------------------------------------------------
    def test_req_i_visit_vs_plan_notifications(self):
        self.loc.verify_visits = False
        self.loc.save()
        today = timezone.localdate()
        tomorrow_str = (today + datetime.timedelta(days=1)).strftime('%Y-%m-%d')
        day_after_str = (today + datetime.timedelta(days=2)).strftime('%Y-%m-%d')

        self.client.force_login(self.rep_nasr)

        # 1. Standalone unplanned visit -> emits 1 visit_created notification to Cairo manager/superadmin
        Notification.objects.all().delete()
        with self.captureOnCommitCallbacks(execute=True):
            res_single = self.client.post(reverse('visit_create'), {
                'contact': self.c_nasr.id,
                'template': self.template.id,
                'date': today.strftime('%Y-%m-%d'),
            })
        self.assertEqual(res_single.status_code, 302)
        self.assertTrue(Notification.objects.filter(event_code='activities.visit_created', recipient=self.mgr_cairo).exists())
        self.assertFalse(Notification.objects.filter(event_code='activities.visit_created', recipient=self.mgr_giza).exists())

        # 2. Planned bulk plan with 1 visit -> ONLY 1 plan_submitted notification, ZERO individual visit notifications
        Notification.objects.all().delete()
        with self.captureOnCommitCallbacks(execute=True):
            res_plan1 = self.client.post(reverse('planned_visits_bulk_add'), {
                'date': tomorrow_str,
                'template_id': self.template.id,
                'contact_ids': [self.c_nasr.id],
            }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(res_plan1.status_code, 200)
        self.assertEqual(Notification.objects.filter(event_code='activities.plan_submitted', recipient=self.mgr_cairo).count(), 1)
        self.assertEqual(Notification.objects.filter(event_code='activities.visit_created').count(), 0)
        self.assertEqual(Notification.objects.filter(event_code='activities.visit_pending_approval').count(), 0)

        # 3. Planned bulk plan with 2 visits -> STILL ONLY 1 plan_submitted notification, ZERO visit notifications
        Notification.objects.all().delete()
        with self.captureOnCommitCallbacks(execute=True):
            res_plan2 = self.client.post(reverse('planned_visits_bulk_add'), {
                'date': day_after_str,
                'template_id': self.template.id,
                'contact_ids': [self.c_nasr.id, self.c_nasr_lead.id],
            }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(res_plan2.status_code, 200)
        self.assertEqual(Notification.objects.filter(event_code='activities.plan_submitted', recipient=self.mgr_cairo).count(), 1)
        self.assertEqual(Notification.objects.filter(event_code__in=['activities.visit_created', 'activities.visit_pending_approval']).count(), 0)
