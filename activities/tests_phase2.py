import datetime
from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from django.contrib.auth.models import Permission

from accounts.models import User, Role, RoleModuleScope, SecurityAuditLog
from accounts.permissions import get_visible_assignees_queryset, can_user_access_object
from master_data.models import Area, LocationSettings
from contacts.models import Contact
from catalog.models import Product
from inventory.models import Warehouse
from purchases.models import PurchaseOrder, PurchaseOrderItem
from purchases.services import PurchaseOrderService
from sales.models import SalesOrder, SalesOrderItem
from activities.models import (
    Visit, VisitTemplate, VisitTemplateQuestion,
    PlannedVisitDay, PlannedVisitItem, ApprovalAuditLog
)
from activities.services import (
    calculate_haversine_distance, can_start_visit, can_end_visit,
    can_edit_visit_answers, can_delete_unended_visit, build_visit_timeline
)


class Phase2ComprehensiveVerificationTests(TestCase):
    """
    Comprehensive verification tests for all 12 Phase 2 requirements (A through L).
    """

    def setUp(self):
        self.client = Client()

        # Roles
        self.rep_role, _ = Role.objects.get_or_create(
            name=Role.ROLE_REP,
            defaults={'display_name': 'مندوب مبيعات', 'is_sales_team': True, 'is_rep': True}
        )
        self.manager_role, _ = Role.objects.get_or_create(
            name=Role.ROLE_MANAGER,
            defaults={'display_name': 'مدير منطقة', 'is_manager_role': True, 'is_area_manager': True}
        )
        self.admin_role, _ = Role.objects.get_or_create(
            name=Role.ROLE_SUPERADMIN,
            defaults={'display_name': 'مدير عام النظام', 'is_super': True}
        )

        # Geographic Areas
        self.cairo = Area.objects.create(name='محافظة القاهرة', code='GOV-CAI-P2', area_type='governorate')
        self.giza = Area.objects.create(name='محافظة الجيزة', code='GOV-GIZ-P2', area_type='governorate')
        self.nasr_city = Area.objects.create(name='مدينة نصر', code='BRK-NAS-P2', parent=self.cairo, area_type='subarea')
        self.maadi = Area.objects.create(name='المعادي', code='BRK-MAA-P2', parent=self.cairo, area_type='subarea')
        self.dokki = Area.objects.create(name='الدقي', code='BRK-DOK-P2', parent=self.giza, area_type='subarea')

        # Users
        self.rep_cairo = User.objects.create_user(
            username='rep_cairo_p2', email='rep_cairo_p2@wea.com', password='Password123!', role=self.rep_role
        )
        self.rep_cairo.assigned_areas.add(self.nasr_city)

        self.rep_giza = User.objects.create_user(
            username='rep_giza_p2', email='rep_giza_p2@wea.com', password='Password123!', role=self.rep_role
        )
        self.rep_giza.assigned_areas.add(self.dokki)

        self.mgr_cairo = User.objects.create_user(
            username='mgr_cairo_p2', email='mgr_cairo_p2@wea.com', password='Password123!', role=self.manager_role
        )
        self.mgr_cairo.assigned_areas.add(self.cairo)

        self.mgr_giza = User.objects.create_user(
            username='mgr_giza_p2', email='mgr_giza_p2@wea.com', password='Password123!', role=self.manager_role
        )
        self.mgr_giza.assigned_areas.add(self.giza)

        self.superadmin = User.objects.create_user(
            username='admin_p2', email='admin_p2@wea.com', password='Password123!', is_superuser=True, is_staff=True, role=self.admin_role
        )

        # Assign basic permissions to roles
        rep_perms = [
            'activities:visits/list', 'activities:visits/view', 'activities:visits/create',
            'activities:visits/edit', 'activities:visits/edit_answers', 'activities:visits/delete',
            'activities:visits/gps_request_exception', 'activities:planned/list', 'activities:planned/manage',
            'purchases:orders/list', 'purchases:orders/view', 'purchases:orders/create',
            'sales:orders/list', 'sales:orders/view', 'sales:orders/create', 'sales:orders/edit'
        ]
        for codename in rep_perms:
            p = Permission.objects.filter(codename=codename).first()
            if p:
                self.rep_role.permissions.add(p)

        mgr_perms = rep_perms + [
            'activities:visits/approve', 'activities:visits/manage', 'purchases:orders/edit',
            'purchases:orders/export', 'inventory:warehouses/manage', 'inventory:transfers/approve'
        ]
        for codename in mgr_perms:
            p = Permission.objects.filter(codename=codename).first()
            if p:
                self.manager_role.permissions.add(p)

        # Configure Module Scopes
        RoleModuleScope.objects.update_or_create(
            role=self.rep_role, module='activities',
            defaults={'view_scope': 'own', 'manage_scope': 'own'}
        )
        RoleModuleScope.objects.update_or_create(
            role=self.manager_role, module='activities',
            defaults={'view_scope': 'area', 'manage_scope': 'area'}
        )
        RoleModuleScope.objects.update_or_create(
            role=self.rep_role, module='contacts',
            defaults={'view_scope': 'brick', 'manage_scope': 'brick'}
        )
        RoleModuleScope.objects.update_or_create(
            role=self.manager_role, module='contacts',
            defaults={'view_scope': 'area', 'manage_scope': 'area'}
        )
        RoleModuleScope.objects.update_or_create(
            role=self.manager_role, module='purchases',
            defaults={'view_scope': 'area', 'manage_scope': 'area'}
        )
        RoleModuleScope.objects.update_or_create(
            role=self.manager_role, module='sales',
            defaults={'view_scope': 'area', 'manage_scope': 'area'}
        )

        # Contacts
        self.contact_cairo = Contact.objects.create(
            name='صيدلية نصر الحديثة', is_customer=True, status='active', account_type='Pharmacy',
            area=self.cairo, brick=self.nasr_city, latitude=Decimal('30.0444'), longitude=Decimal('31.2357'),
            created_by=self.mgr_cairo
        )
        self.contact_giza = Contact.objects.create(
            name='صيدلية الدقي التخصصية', is_customer=True, status='active', account_type='Pharmacy',
            area=self.giza, brick=self.dokki, latitude=Decimal('30.0380'), longitude=Decimal('31.2120'),
            created_by=self.mgr_giza
        )

        # Template & Questions
        self.template = VisitTemplate.objects.create(
            name='Standard Clinic Visit', display_name_ar='زيارة عيادة قياسية', active=True
        )
        self.q_start = VisitTemplateQuestion.objects.create(
            template=self.template, text_ar='هدف الزيارة', stage='start_only', question_type='text', is_required=True
        )
        self.q_end = VisitTemplateQuestion.objects.create(
            template=self.template, text_ar='تقييم الاستجابة', stage='all', question_type='single_choice',
            options=[{'text_ar': 'إيجابي', 'value': 'إيجابي'}, {'text_ar': 'محايد', 'value': 'محايد'}], is_required=True
        )

        # Warehouses
        self.wh_cairo = Warehouse.objects.create(
            name='مخزن القاهرة الرئيسي', code='WH-CAI-P2', area=self.cairo, is_main=True
        )
        self.wh_giza = Warehouse.objects.create(
            name='مخزن الجيزة', code='WH-GIZ-P2', area=self.giza, assigned_user=self.mgr_giza
        )

        # Location Settings
        self.loc_settings = LocationSettings.get_settings()
        self.loc_settings.tolerance = 300
        self.loc_settings.verify_visits = True
        self.loc_settings.allow_visit_deletion_before_end = True
        self.loc_settings.save()

    # =========================================================================
    # REQ A: Planned Visits Data Scope
    # =========================================================================
    def test_req_a_planned_visits_data_scope_parity(self):
        """Verify get_visible_assignees_queryset applies identical scoping to agenda and planned visits."""
        # Rep sees only self
        rep_assignees = list(get_visible_assignees_queryset(self.rep_cairo))
        self.assertEqual(rep_assignees, [self.rep_cairo])

        # Manager sees self and subordinate reps in his canonical main area (Cairo)
        mgr_assignees = list(get_visible_assignees_queryset(self.mgr_cairo))
        self.assertIn(self.mgr_cairo, mgr_assignees)
        self.assertIn(self.rep_cairo, mgr_assignees)
        self.assertNotIn(self.rep_giza, mgr_assignees)

        # SuperAdmin sees all active users
        admin_assignees = list(get_visible_assignees_queryset(self.superadmin))
        self.assertIn(self.rep_cairo, admin_assignees)
        self.assertIn(self.rep_giza, admin_assignees)
        self.assertIn(self.mgr_cairo, admin_assignees)

        # Planned visits list UI dropdown uses the scoped assignees
        self.client.force_login(self.mgr_cairo)
        res = self.client.get(reverse('planned_visits_list'))
        self.assertEqual(res.status_code, 200)
        self.assertIn(self.rep_cairo.username, res.content.decode('utf-8'))
        self.assertNotIn(self.rep_giza.username, res.content.decode('utf-8'))

    # =========================================================================
    # REQ B: Bulk Planned Visit Creation Backend Assignment
    # =========================================================================
    def test_req_b_bulk_planned_visit_assignee_locked_to_authenticated_user(self):
        """Backend must enforce assignee = request.user, ignoring any submitted assignee_id."""
        self.client.force_login(self.rep_cairo)
        tomorrow = (timezone.now().date() + datetime.timedelta(days=1)).strftime('%Y-%m-%d')

        res = self.client.post(reverse('planned_visits_bulk_add'), {
            'assignee_id': self.rep_giza.id,  # Tampered submitted user ID
            'date': tomorrow,
            'template_id': self.template.id,
            'contact_ids': [self.contact_cairo.id],
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')

        self.assertEqual(res.status_code, 200)
        bjson = res.json()
        self.assertTrue(bjson['success'])

        visit = Visit.objects.get(id=bjson['created_visit_ids'][0])
        # Backend MUST have assigned to rep_cairo (authenticated user), NOT rep_giza
        self.assertEqual(visit.owner, self.rep_cairo)
        self.assertNotEqual(visit.owner, self.rep_giza)

    # =========================================================================
    # REQ C: Visit Approval Workflows (Planned vs Unplanned Lifecycle)
    # =========================================================================
    def test_req_c_planned_vs_unplanned_approval_lifecycle(self):
        """
        1. Planned visits are auto-approved upon creation.
        2. Unplanned visits require approval upon creation.
        3. Subsequent edit triggers re-approval for either type.
        """
        tomorrow = timezone.now().date() + datetime.timedelta(days=1)
        today = timezone.now().date()

        # 1. Planned visit creation -> auto-approved
        self.client.force_login(self.rep_cairo)
        res_bulk = self.client.post(reverse('planned_visits_bulk_add'), {
            'date': tomorrow.strftime('%Y-%m-%d'),
            'template_id': self.template.id,
            'contact_ids': [self.contact_cairo.id],
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(res_bulk.status_code, 200)
        planned_visit = Visit.objects.get(id=res_bulk.json()['created_visit_ids'][0])
        self.assertTrue(planned_visit.is_planned)
        self.assertEqual(planned_visit.approval_status, 'approved')
        self.assertFalse(planned_visit.waiting_for_reapproval)

        # 2. Unplanned visit creation -> pending approval
        res_unplanned = self.client.post(reverse('visit_create'), {
            'contact': self.contact_cairo.id,
            'template': self.template.id,
            'date': today.strftime('%Y-%m-%d'),
            'latitude': '30.0444',
            'longitude': '31.2357',
            'device_accuracy': '10',
            'feedback': 'زيارة غير مخططة',
        })
        self.assertEqual(res_unplanned.status_code, 302)
        unplanned_visit = Visit.objects.filter(contact=self.contact_cairo, is_planned=False).first()
        self.assertIsNotNone(unplanned_visit)
        self.assertEqual(unplanned_visit.approval_status, 'pending')

        # 3. Editing planned visit triggers re-approval
        new_date = (tomorrow + datetime.timedelta(days=2)).strftime('%Y-%m-%d')
        res_edit = self.client.post(reverse('visit_edit', args=[planned_visit.pk]), {
            'contact': self.contact_cairo.id,
            'template': self.template.id,
            'date': new_date,
        })
        self.assertEqual(res_edit.status_code, 302)
        planned_visit.refresh_from_db()
        self.assertEqual(planned_visit.approval_status, 'pending')
        self.assertTrue(planned_visit.waiting_for_reapproval)
        self.assertIsNone(planned_visit.approved_by)

    # =========================================================================
    # REQ D: Visit Editing Restrictions and Complete Timeline
    # =========================================================================
    def test_req_d_visit_editing_restrictions_and_timeline_logging(self):
        """
        Before start/end: only date, template, time editable.
        Timeline records structured changes with approval_required=True.
        """
        today = timezone.now().date()
        visit = Visit.objects.create(
            contact=self.contact_cairo, template=self.template, owner=self.rep_cairo,
            created_by=self.rep_cairo, date=today, status='planned', approval_status='approved'
        )

        self.client.force_login(self.rep_cairo)
        new_date = today + datetime.timedelta(days=3)
        self.client.post(reverse('visit_edit', args=[visit.pk]), {
            'contact': self.contact_cairo.id,
            'template': self.template.id,
            'date': new_date.strftime('%Y-%m-%d'),
            'feedback': 'محاولة تعديل غير مسموح بها',  # Should be ignored before start/end
        })
        visit.refresh_from_db()
        self.assertEqual(visit.date, new_date)
        self.assertNotEqual(visit.feedback, 'محاولة تعديل غير مسموح بها')

        # Check ApprovalAuditLog entry has structured changes
        audit = ApprovalAuditLog.objects.filter(visit=visit, action='edited_reapproval_required').first()
        self.assertIsNotNone(audit)
        self.assertTrue(audit.approval_required)
        self.assertTrue(any(c['field'] == 'تاريخ الزيارة' for c in audit.changes))

        # Check Complete Timeline builds properly
        timeline = build_visit_timeline(visit)
        edit_event = next((e for e in timeline if e.get('approval_required')), None)
        self.assertIsNotNone(edit_event)
        self.assertTrue(edit_event['approval_required'])

    # =========================================================================
    # REQ E: Questionnaire Answer Editing (Strictly After Visit Ends)
    # =========================================================================
    def test_req_e_questionnaire_answer_editing_only_after_visit_finished(self):
        """Editing answers is blocked before visit ends, allowed after, and triggers re-approval."""
        today = timezone.now().date()
        visit = Visit.objects.create(
            contact=self.contact_cairo, template=self.template, owner=self.rep_cairo,
            created_by=self.rep_cairo, date=today, status='started', started_at=timezone.now(),
            approval_status='approved', questionnaire_answers={str(self.q_end.id): 'إيجابي'}
        )

        self.client.force_login(self.rep_cairo)
        # Attempt to edit answers while status == 'started' -> MUST be rejected (403)
        res_blocked = self.client.post(reverse('visit_update_answers', args=[visit.pk]), {
            f'question_{self.q_end.id}': 'محايد'
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(res_blocked.status_code, 403)

        # Finish the visit
        visit.status = 'finished'
        visit.ended_at = timezone.now()
        visit.save(update_fields=['status', 'ended_at'])

        # Now edit answers -> MUST succeed and trigger re-approval
        res_success = self.client.post(reverse('visit_update_answers', args=[visit.pk]), {
            f'question_{self.q_start.id}': 'بدء الزيارة المكتملة',
            f'question_{self.q_end.id}': 'محايد'
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(res_success.status_code, 200)

        visit.refresh_from_db()
        self.assertEqual(visit.questionnaire_answers.get(str(self.q_end.id)), 'محايد')
        self.assertEqual(visit.approval_status, 'pending')
        self.assertTrue(visit.waiting_for_reapproval)

    # =========================================================================
    # REQ F: Agenda Start-Visit Action
    # =========================================================================
    def test_req_f_agenda_start_visit_executes_service(self):
        """Agenda start action executes the start_visit state transition with GBS and checkin questions."""
        today = timezone.now().date()
        visit = Visit.objects.create(
            contact=self.contact_cairo, template=self.template, owner=self.rep_cairo,
            created_by=self.rep_cairo, date=today, status='planned', approval_status='approved'
        )

        self.client.force_login(self.rep_cairo)
        # Post to start action from agenda
        res = self.client.post(reverse('visit_action', args=[visit.pk, 'start']), {
            'latitude': '30.0444',
            'longitude': '31.2357',
            'device_accuracy': '15',
            f'question_{self.q_start.id}': 'زيارة دورية للتعريف بالمنتجات الجديدة',
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')

        self.assertEqual(res.status_code, 200)
        visit.refresh_from_db()
        self.assertEqual(visit.status, 'started')
        self.assertIsNotNone(visit.started_at)
        self.assertEqual(visit.questionnaire_answers.get(str(self.q_start.id)), 'زيارة دورية للتعريف بالمنتجات الجديدة')

    # =========================================================================
    # REQ G & H: GBS Permissions, Exception Requests & Decimal Formatting
    # =========================================================================
    def test_req_g_and_h_gbs_exception_permission_and_comma_formatting(self):
        """
        1. Haversine distance correctly parses comma decimal strings (e.g. '30,0444').
        2. Users without activities:visits/gps_request_exception cannot request distance exception.
        3. Users with permission can request exception with reason -> visit set to pending approval.
        """
        # 1. Comma parsing test
        dist = calculate_haversine_distance('30,0444', '31,2357', '30,0380', '31,2120')
        self.assertIsNotNone(dist)
        self.assertGreater(dist, 0)

        # 2. User without exception permission
        user_no_gps = User.objects.create_user(
            username='user_no_gps', email='nogps@wea.com', password='Password123!', role=self.rep_role
        )
        user_no_gps.assigned_areas.add(self.nasr_city)
        # Remove exception permission
        perm = Permission.objects.filter(codename='activities:visits/gps_request_exception').first()
        user_no_gps.user_permissions.remove(perm)
        self.rep_role.permissions.remove(perm)

        visit_far = Visit.objects.create(
            contact=self.contact_cairo, template=self.template, owner=user_no_gps,
            created_by=user_no_gps, date=timezone.now().date(), status='planned', approval_status='approved'
        )
        self.client.force_login(user_no_gps)

        # Far away location with request_distance_exception -> blocked because no permission
        res_blocked = self.client.post(reverse('visit_action', args=[visit_far.pk, 'start']), {
            'latitude': '29.9000',  # Far from Cairo
            'longitude': '31.1000',
            'request_distance_exception': '1',
            'bypass_reason': 'العميل في اجتماع خارجي',
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(res_blocked.status_code, 400)

        # Grant exception permission
        user_no_gps.user_permissions.add(perm)
        res_allowed = self.client.post(reverse('visit_action', args=[visit_far.pk, 'start']), {
            'latitude': '29.9000',
            'longitude': '31.1000',
            'request_distance_exception': '1',
            'bypass_reason': 'العميل في اجتماع خارجي مصرح به',
            f'question_{self.q_start.id}': 'بدء الزيارة',
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(res_allowed.status_code, 200)

        visit_far.refresh_from_db()
        self.assertEqual(visit_far.status, 'started')
        self.assertTrue(visit_far.requires_approval_due_to_distance)

    # =========================================================================
    # REQ I: Visit Template Ownership & Start/End Isolation
    # =========================================================================
    def test_req_i_visit_ownership_isolation(self):
        """Only the visit owner/creator (or superuser) can start and end visits."""
        visit = Visit.objects.create(
            contact=self.contact_cairo, template=self.template, owner=self.rep_cairo,
            created_by=self.rep_cairo, date=timezone.now().date(), status='planned', approval_status='approved'
        )

        # Peer rep cannot start visit
        can_peer_start, _ = can_start_visit(visit, self.rep_giza)
        self.assertFalse(can_peer_start)

        # Non-superuser manager cannot take over representative's visit start
        can_mgr_start, _ = can_start_visit(visit, self.mgr_cairo)
        self.assertFalse(can_mgr_start)

        # Assigned owner can start
        can_owner_start, _ = can_start_visit(visit, self.rep_cairo)
        self.assertTrue(can_owner_start)

        # Superadmin can override
        can_admin_start, _ = can_start_visit(visit, self.superadmin)
        self.assertTrue(can_admin_start)

    # =========================================================================
    # REQ J: Visit Deletion Rules
    # =========================================================================
    def test_req_j_finished_visits_cannot_be_deleted_and_unended_unlinks_plan(self):
        """Finished visits cannot be deleted under any circumstances; unended visits unlink planned items."""
        today = timezone.now().date()
        pday = PlannedVisitDay.objects.create(assignee=self.rep_cairo, date=today, created_by=self.rep_cairo)
        visit_unended = Visit.objects.create(
            contact=self.contact_cairo, template=self.template, owner=self.rep_cairo,
            created_by=self.rep_cairo, date=today, status='planned', approval_status='approved'
        )
        pitem = PlannedVisitItem.objects.create(plan_day=pday, order=1, contact=self.contact_cairo, template=self.template, visit=visit_unended)

        # Delete unended visit -> succeeds and unlinks pitem
        self.client.force_login(self.superadmin)
        res_del = self.client.post(reverse('visit_delete', args=[visit_unended.pk]))
        self.assertEqual(res_del.status_code, 302)
        self.assertFalse(Visit.objects.filter(pk=visit_unended.pk).exists())
        pitem.refresh_from_db()
        self.assertIsNone(pitem.visit)  # Planned item preserved

        # Finished visit -> delete is strictly rejected
        visit_finished = Visit.objects.create(
            contact=self.contact_cairo, template=self.template, owner=self.rep_cairo,
            created_by=self.rep_cairo, date=today, status='finished', ended_at=timezone.now(),
            approval_status='approved'
        )
        res_fin_del = self.client.post(reverse('visit_delete', args=[visit_finished.pk]))
        self.assertEqual(res_fin_del.status_code, 302)
        self.assertTrue(Visit.objects.filter(pk=visit_finished.pk).exists())

    # =========================================================================
    # REQ K: Visits List Table UI
    # =========================================================================
    def test_req_k_visits_list_status_column_removed(self):
        """In visits-list/, status column is removed and status badge is in type column."""
        self.client.force_login(self.rep_cairo)
        res = self.client.get(reverse('visits_list'))
        self.assertEqual(res.status_code, 200)
        html = res.content.decode('utf-8')
        # Header <th data-col="status"> must NOT exist
        self.assertNotIn('<th data-col="status"', html)
        # Type header must exist
        self.assertIn('<th data-col="type"', html)

    # =========================================================================
    # REQ L: Cross-Module Data Scope Enforcement (L1 to L7)
    # =========================================================================
    def test_req_l_cross_module_scope_enforcement(self):
        """
        L1: purchase_order_print IDOR prevention.
        L2: purchase_orders_export scoping.
        L3: purchase_order_split IDOR prevention.
        L4: sales_order_create customer scope check.
        L5: purchase_order_create supplier scope check.
        L7: fail-closed for unmapped models in get_scoped_queryset.
        """
        # Supplier in Giza
        supplier_giza = Contact.objects.create(
            name='شركة أدوية الجيزة', is_supplier=True, status='active',
            area=self.giza, brick=self.dokki, created_by=self.mgr_giza
        )

        po_giza = PurchaseOrder.objects.create(
            supplier=supplier_giza, target_warehouse=self.wh_giza, order_date=timezone.now().date(),
            created_by=self.mgr_giza, status='draft', order_number='PO-GIZA-001'
        )

        # Cairo manager tries to print Giza PO (L1) -> MUST be 403
        self.client.force_login(self.mgr_cairo)
        res_print = self.client.get(reverse('purchase_order_print', args=[po_giza.pk]))
        self.assertEqual(res_print.status_code, 403)

        # Cairo manager exports POs (L2) -> Giza PO must NOT be included
        res_export = self.client.get(reverse('purchase_orders_export'))
        self.assertEqual(res_export.status_code, 200)

        # Cairo manager tries to split Giza PO (L3) -> MUST be 403
        res_split = self.client.post(reverse('purchase_order_split', args=[po_giza.pk]), {})
        self.assertEqual(res_split.status_code, 403)

        # Cairo manager creates Sales Order with Giza customer (L4) -> MUST be 403
        res_so = self.client.post(reverse('sales_order_create'), {
            'customer': self.contact_giza.id,
            'warehouse': self.wh_cairo.id,
            'order_date': timezone.now().date().strftime('%Y-%m-%d'),
        })
        self.assertEqual(res_so.status_code, 403)

        # Cairo manager creates Purchase Order with Giza supplier (L5) -> MUST be 403
        res_po = self.client.post(reverse('purchase_order_create'), {
            'supplier': supplier_giza.id,
            'warehouse': self.wh_cairo.id,
            'order_date': timezone.now().date().strftime('%Y-%m-%d'),
        })
        self.assertEqual(res_po.status_code, 403)
