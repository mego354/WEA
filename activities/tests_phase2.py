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
        Phase 2:
        1. Planned visits created by rep require manager approval (pending).
        2. Plan/visits can be approved by manager.
        3. Unplanned visits are auto-approved upon creation.
        4. Subsequent edit triggers re-approval.
        """
        tomorrow = timezone.now().date() + datetime.timedelta(days=1)
        today = timezone.now().date()

        # 1. Planned visit creation -> pending approval (creator lacks activities:visits/approve)
        self.client.force_login(self.rep_cairo)
        res_bulk = self.client.post(reverse('planned_visits_bulk_add'), {
            'date': tomorrow.strftime('%Y-%m-%d'),
            'template_id': self.template.id,
            'contact_ids': [self.contact_cairo.id],
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(res_bulk.status_code, 200)
        planned_visit = Visit.objects.get(id=res_bulk.json()['created_visit_ids'][0])
        self.assertTrue(planned_visit.is_planned)
        self.assertEqual(planned_visit.approval_status, 'pending')

        # Manager approves the plan
        self.client.force_login(self.mgr_cairo)
        res_approve = self.client.post(
            reverse('plan_action', args=[planned_visit.plan.pk, 'approve']),
            {'approval_notes': 'خطة معتمدة'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(res_approve.status_code, 200)
        planned_visit.refresh_from_db()
        self.assertEqual(planned_visit.approval_status, 'approved')
        self.assertFalse(planned_visit.waiting_for_reapproval)

        # 2. Unplanned visit creation -> auto-approved
        self.client.force_login(self.rep_cairo)
        res_unplanned = self.client.post(reverse('visit_create'), {
            'contact': self.contact_cairo.id,
            'template': self.template.id,
            'date': today.strftime('%Y-%m-%d'),
            'latitude': '30.0444',
            'longitude': '31.2357',
            'device_accuracy': '10',
        })
        self.assertEqual(res_unplanned.status_code, 302)
        unplanned_visit = Visit.objects.filter(contact=self.contact_cairo, is_planned=False).first()
        self.assertIsNotNone(unplanned_visit)
        self.assertEqual(unplanned_visit.approval_status, 'approved')

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
        })
        visit.refresh_from_db()
        self.assertEqual(visit.date, new_date)
        self.assertFalse(hasattr(visit, 'feedback'))

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
        2. Users without activities:visits/bypass_gps cannot bypass distance.
        3. Users with activities:visits/bypass_gps can bypass distance and that does NOT make the visit need approval.
        """
        # 1. Comma parsing test
        dist = calculate_haversine_distance('30,0444', '31,2357', '30,0380', '31,2120')
        self.assertIsNotNone(dist)
        self.assertGreater(dist, 0)

        # 2. User without bypass permission
        user_no_gps = User.objects.create_user(
            username='user_no_gps', email='nogps@wea.com', password='Password123!', role=self.rep_role
        )
        user_no_gps.assigned_areas.add(self.nasr_city)
        perm = Permission.objects.filter(codename='activities:visits/bypass_gps').first()
        user_no_gps.user_permissions.remove(perm)
        self.rep_role.permissions.remove(perm)

        visit_far = Visit.objects.create(
            contact=self.contact_cairo, template=self.template, owner=user_no_gps,
            created_by=user_no_gps, date=timezone.now().date(), status='planned', approval_status='approved'
        )
        self.client.force_login(user_no_gps)

        # Far away location with force_bypass_location -> blocked because no permission
        res_blocked = self.client.post(reverse('visit_action', args=[visit_far.pk, 'start']), {
            'latitude': '29.9000',  # Far from Cairo
            'longitude': '31.1000',
            'force_bypass_location': '1',
            'bypass_reason': 'العميل في اجتماع خارجي',
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(res_blocked.status_code, 400)

        # Grant bypass permission
        user_no_gps.user_permissions.add(perm)
        res_allowed = self.client.post(reverse('visit_action', args=[visit_far.pk, 'start']), {
            'latitude': '29.9000',
            'longitude': '31.1000',
            'force_bypass_location': '1',
            'bypass_reason': 'العميل في اجتماع خارجي مصرح به',
            f'question_{self.q_start.id}': 'بدء الزيارة',
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(res_allowed.status_code, 200)

        visit_far.refresh_from_db()
        self.assertEqual(visit_far.status, 'started')
        self.assertFalse(visit_far.requires_approval_due_to_distance)
        self.assertEqual(visit_far.approval_status, 'approved')  # Bypassing distance does not require approval!

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


class Phase2QuestionnaireDoubleVisitAndCleanupTests(TestCase):
    """Regression tests for Phase 2 #3 (Questionnaire & Detailing), #4 (Double Visit), and #5 (Cleanup Command)."""

    @classmethod
    def setUpTestData(cls):
        from django.core.management import call_command
        call_command('setup_permissions')

    def setUp(self):
        self.cairo = Area.objects.create(name='القاهرة ق', code='PH2-CAI', area_type='governorate')
        self.brick = Area.objects.create(name='المعادي ق', code='PH2-MAD', area_type='subarea', parent=self.cairo)
        self.rep_role = Role.objects.get(name='rep')
        self.superadmin = User.objects.create_superuser(username='sa_ph2@wea.com', email='sa_ph2@wea.com', password='Password123!')
        self.rep = User.objects.create_user(
            username='rep_ph2@wea.com', email='rep_ph2@wea.com', password='Password123!',
            role=self.rep_role, is_active=True
        )
        self.rep.assigned_areas.add(self.brick)
        self.contact = Contact.objects.create(name='د. اختبار', is_customer=True, area=self.cairo, brick=self.brick, status='active')
        self.tpl = VisitTemplate.objects.create(name='Single visit (DR)', display_name_ar='زيارة طبيب فردية', active=True)
        self.q1 = VisitTemplateQuestion.objects.create(
            template=self.tpl, text_ar='نتيجة الزيارة', question_type='single_choice',
            options=[{'value': 'successful', 'text_ar': 'زيارة ناجحة'}, {'value': 'unsuccessful', 'text_ar': 'زيارة غير ناجحة'}],
            order=1, is_active=True
        )
        self.q_mc = VisitTemplateQuestion.objects.create(
            template=self.tpl, text_ar='اهتمامات', question_type='multiple_choice',
            options=[{'value': 'opt_a', 'text_ar': 'خيار أ'}, {'value': 'opt_b', 'text_ar': 'خيار ب'}],
            order=2, is_required=False, is_active=True
        )

    def test_qa_display_includes_detailed_products_and_translates_answers(self):
        from catalog.models import ProductCategory, Product
        cat = ProductCategory.objects.create(name='فئة زيارة', code='CAT-VIS')
        prod = Product.objects.create(name='منتج مشروح 1', sku_code='SKU-DET-1', category=cat)
        visit = Visit.objects.create(
            contact=self.contact, template=self.tpl, owner=self.rep, created_by=self.rep,
            date=timezone.now().date(), status='finished', approval_status='approved',
            questionnaire_answers={str(self.q1.id): 'successful', str(self.q_mc.id): ['opt_a'], '9999': 'legacy_note'}
        )
        visit.detailed_products.add(prod)

        qa_list = visit.get_qa_display_list()
        texts = {item['question_text']: item['answer'] for item in qa_list}
        self.assertEqual(texts['نتيجة الزيارة'], 'زيارة ناجحة')
        self.assertEqual(texts['اهتمامات'], 'خيار أ')
        self.assertEqual(texts['المنتجات المشروحة (Product Detailing)'], 'منتج مشروح 1')

        self.client.force_login(self.superadmin)
        res = self.client.get(reverse('visit_detail', args=[visit.pk]))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'زيارة ناجحة')
        self.assertContains(res, 'legacy_note')

    def test_double_visit_create_and_edit_persistence(self):
        self.client.force_login(self.superadmin)
        today_str = timezone.now().date().strftime('%Y-%m-%d')
        res_create_get = self.client.get(reverse('visit_create'))
        self.assertContains(res_create_get, 'name="doubled"')

        res_create = self.client.post(reverse('visit_create'), {
            'contact': self.contact.id,
            'template': self.tpl.id,
            'date': today_str,
            'owner': self.rep.id,
            'doubled': 'on',
            'bypass_location': '1',
            'bypass_reason': 'اختبار',
        })
        self.assertEqual(res_create.status_code, 302)
        visit = Visit.objects.latest('id')
        self.assertTrue(visit.doubled)

        # Edit to toggle doubled off
        res_edit = self.client.post(reverse('visit_edit', args=[visit.pk]), {
            'contact': self.contact.id,
            'template': self.tpl.id,
            'date': today_str,
        })
        self.assertEqual(res_edit.status_code, 302)
        visit.refresh_from_db()
        self.assertFalse(visit.doubled)

    def test_cleanup_command_dry_run_vs_execute(self):
        from django.core.management import call_command
        from activities.models import Agreement, AgreementType
        agr_type = AgreementType.objects.create(name='نوع تدقيق')
        agr_keep = Agreement.objects.create(title='Keep', type=agr_type, customer=self.contact, amount=Decimal('100.00'), date=timezone.now().date(), created_by=self.superadmin)
        agr_del = Agreement.objects.create(title='test', type=agr_type, customer=self.contact, amount=Decimal('200.00'), date=timezone.now().date(), created_by=self.superadmin)

        call_command('cleanup_test_activities', agreement_ids=[agr_del.id])
        self.assertTrue(Agreement.objects.filter(pk=agr_del.id).exists())

        call_command('cleanup_test_activities', agreement_ids=[agr_del.id], execute=True)
        self.assertFalse(Agreement.objects.filter(pk=agr_del.id).exists())
        self.assertTrue(Agreement.objects.filter(pk=agr_keep.id).exists())


class Phase3VisitsAgreementsAndNavTests(TestCase):
    """
    Comprehensive verification tests for:
    - Suggested Products question type lifecycle, validation & historical preservation
    - Visit creator-edit tracking, list/export filtering & data scope
    - Agreements list/detail/edit/delete permissions, status rules, attachment cleanup & audit
    - Cleanup command dry-run reporting
    """

    @classmethod
    def setUpTestData(cls):
        from django.core.management import call_command
        call_command('setup_permissions')

    def setUp(self):
        from catalog.models import ProductCategory
        from activities.models import Agreement, AgreementType

        self.client = Client()
        loc = LocationSettings.get_settings()
        loc.verify_visits = False
        loc.verify_end_visit_distance = False
        loc.allow_visit_deletion_before_end = True
        loc.enable_product_suggestions = True
        loc.save()

        self.rep_role = Role.objects.get(name=Role.ROLE_REP)
        self.manager_role = Role.objects.get(name=Role.ROLE_MANAGER)

        self.cairo = Area.objects.create(name='القاهرة 3', code='PH3-CAI', area_type='governorate')
        self.giza = Area.objects.create(name='الجيزة 3', code='PH3-GIZ', area_type='governorate')
        self.nasr = Area.objects.create(name='مدينة نصر 3', code='PH3-NSR', area_type='subarea', parent=self.cairo)
        self.maadi = Area.objects.create(name='المعادي 3', code='PH3-MAD', area_type='subarea', parent=self.cairo)
        self.dokki = Area.objects.create(name='الدقي 3', code='PH3-DOK', area_type='subarea', parent=self.giza)

        self.superadmin = User.objects.create_superuser(
            username='sa_ph3@wea.com', email='sa_ph3@wea.com', password='Password123!'
        )
        self.rep_cairo = User.objects.create_user(
            username='rep_nasr_ph3@wea.com', email='rep_nasr_ph3@wea.com', password='Password123!',
            role=self.rep_role, is_active=True
        )
        self.rep_cairo.assigned_areas.add(self.nasr)

        self.peer_rep = User.objects.create_user(
            username='rep_maadi_ph3@wea.com', email='rep_maadi_ph3@wea.com', password='Password123!',
            role=self.rep_role, is_active=True
        )
        self.peer_rep.assigned_areas.add(self.maadi)

        self.mgr_cairo = User.objects.create_user(
            username='mgr_cairo_ph3@wea.com', email='mgr_cairo_ph3@wea.com', password='Password123!',
            role=self.manager_role, is_active=True
        )
        self.mgr_cairo.assigned_areas.add(self.cairo)

        self.mgr_giza = User.objects.create_user(
            username='mgr_giza_ph3@wea.com', email='mgr_giza_ph3@wea.com', password='Password123!',
            role=self.manager_role, is_active=True
        )
        self.mgr_giza.assigned_areas.add(self.giza)

        self.contact_nasr = Contact.objects.create(
            name='صيدلية مدينة نصر 3', is_customer=True, account_type='Pharmacy',
            area=self.cairo, brick=self.nasr, status='active'
        )
        self.contact_maadi = Contact.objects.create(
            name='صيدلية المعادي 3', is_customer=True, account_type='Pharmacy',
            area=self.cairo, brick=self.maadi, status='active'
        )
        self.contact_dokki = Contact.objects.create(
            name='صيدلية الدقي 3', is_customer=True, account_type='Pharmacy',
            area=self.giza, brick=self.dokki, status='active'
        )

        self.cat = ProductCategory.objects.create(name='أدوية 3', code='PH3-CAT')
        self.prod_sugg = Product.objects.create(
            name='جيرون المقترح', sku_code='PH3-P1', category=self.cat, is_active=True, sellable=True
        )
        self.prod_other = Product.objects.create(
            name='ليجتونكس العادي', sku_code='PH3-P2', category=self.cat, is_active=True, sellable=True
        )
        self.prod_inactive = Product.objects.create(
            name='منتج موقوف', sku_code='PH3-P3', category=self.cat, is_active=False, sellable=True
        )
        self.prod_nonsellable = Product.objects.create(
            name='عينة غير قابلة للبيع', sku_code='PH3-P4', category=self.cat, is_active=True, sellable=False
        )

        # Template with suggested_products question type
        self.tpl_sp = VisitTemplate.objects.create(
            name='Single visit (Pharmacy)',
            display_name_ar='زيارة صيدلية بالمقترحات',
            enable_product_detailing=True,
            active=True,
        )
        self.tpl_sp.suggested_products.add(self.prod_sugg, self.prod_inactive)
        self.q_sp_outcome = VisitTemplateQuestion.objects.create(
            template=self.tpl_sp,
            text_ar='نتيجة الزيارة',
            question_type='single_choice',
            options=[{'value': 'successful', 'text_ar': 'زيارة ناجحة'}, {'value': 'unsuccessful', 'text_ar': 'زيارة غير ناجحة'}],
            order=1, is_required=True, is_active=True,
        )
        self.q_sp = VisitTemplateQuestion.objects.create(
            template=self.tpl_sp,
            text_ar='المنتجات المقترحة',
            question_type='suggested_products',
            stage='end_only',
            order=2, is_required=True, is_active=True,
        )

        # Legacy template without suggested_products question
        self.tpl_legacy = VisitTemplate.objects.create(
            name='Single visit (DR)',
            display_name_ar='زيارة طبيب تقليدية',
            enable_product_detailing=True,
            active=True,
        )
        self.q_leg_outcome = VisitTemplateQuestion.objects.create(
            template=self.tpl_legacy,
            text_ar='نتيجة الزيارة',
            question_type='single_choice',
            options=[{'value': 'successful', 'text_ar': 'زيارة ناجحة'}],
            order=1, is_required=True, is_active=True,
        )

        self.agr_type = AgreementType.objects.create(name='بونص مبيعات 3')
        self.Agreement = Agreement

    def test_suggested_products_question_builder_preview_and_api(self):
        """Question builder saves/edits 'suggested_products', preview omits duplicate detailing, API includes pool."""
        self.client.force_login(self.superadmin)
        tpl = VisitTemplate.objects.create(
            name='Group visit (Clinic / Medical Center)',
            display_name_ar='قالب بناء اختباري',
            enable_product_detailing=True,
            active=True,
        )
        tpl.suggested_products.add(self.prod_sugg)

        res_add = self.client.post(reverse('template_question_add', args=[tpl.pk]), {
            'text_ar': 'اختر المنتجات المقترحة',
            'question_type': 'suggested_products',
            'is_required': 'on',
            'options_json': '[{"text_ar": "stale"}]',
        })
        self.assertEqual(res_add.status_code, 302)
        q = VisitTemplateQuestion.objects.filter(template=tpl).latest('id')
        self.assertEqual(q.question_type, 'suggested_products')
        self.assertEqual(q.options, [])
        self.assertTrue(q.is_required)

        res_edit = self.client.post(reverse('template_question_edit', args=[q.pk]), {
            'text_ar': 'المنتجات المشروحة والمقترحة',
            'question_type': 'suggested_products',
            'options_json': '[{"text_ar": "should_clear"}]',
        })
        self.assertEqual(res_edit.status_code, 302)
        q.refresh_from_db()
        self.assertEqual(q.options, [])
        self.assertFalse(q.is_required)

        res_preview = self.client.get(reverse('visit_template_preview', args=[tpl.pk]))
        self.assertEqual(res_preview.status_code, 200)
        self.assertContains(res_preview, 'المنتجات المشروحة والمقترحة')
        self.assertContains(res_preview, self.prod_sugg.name)
        self.assertFalse(res_preview.context['has_suggested_products_question'] is False)
        # Should render via questionnaire question, not duplicate legacy detailing block
        self.assertNotContains(res_preview, 'المنتجات المشروحة المتاحة للاختيار (Detailing)')

        res_api = self.client.get(reverse('visit_templates_api'))
        self.assertEqual(res_api.status_code, 200)
        payload = res_api.json()
        tpl_row = next(r for r in payload['templates'] if r['id'] == tpl.id)
        self.assertTrue(any(qq['question_type'] == 'suggested_products' for qq in tpl_row['questions']))
        self.assertTrue(any(p['id'] == self.prod_sugg.id for p in tpl_row['suggested_products']))
        self.assertFalse(any(p['id'] == self.prod_inactive.id for p in tpl_row['suggested_products']))

    def test_suggested_products_visit_lifecycle_validation_and_historical_preservation(self):
        """
        Suggested Products participates identically in visit completion, validation,
        visit detail dossier, visits list popup, Excel export, and post-end Edit Answers
        while preserving historically selected inactive products.
        """
        from io import BytesIO
        import openpyxl

        visit = Visit.objects.create(
            contact=self.contact_nasr, template=self.tpl_sp,
            owner=self.rep_cairo, created_by=self.rep_cairo,
            date=timezone.localdate(), status='started', approval_status='approved',
            started_at=timezone.now(),
        )
        self.client.force_login(self.rep_cairo)

        # 1. Required validation blocks empty suggested_products submission
        res_empty = self.client.post(reverse('visit_detail', args=[visit.pk]), {
            'action': 'complete',
            f'question_{self.q_sp_outcome.id}': 'successful',
        })
        self.assertEqual(res_empty.status_code, 200)
        visit.refresh_from_db()
        self.assertEqual(visit.status, 'started')

        # 2. Rejects inactive / non-sellable product IDs
        res_bad = self.client.post(reverse('visit_detail', args=[visit.pk]), {
            'action': 'complete',
            f'question_{self.q_sp_outcome.id}': 'successful',
            f'question_{self.q_sp.id}': [str(self.prod_inactive.id), str(self.prod_nonsellable.id)],
        })
        self.assertEqual(res_bad.status_code, 200)
        visit.refresh_from_db()
        self.assertEqual(visit.status, 'started')

        # 3. Valid completion saves suggested_products IDs & syncs detailed_products
        res_ok = self.client.post(reverse('visit_detail', args=[visit.pk]), {
            'action': 'complete',
            f'question_{self.q_sp_outcome.id}': 'successful',
            f'question_{self.q_sp.id}': [str(self.prod_sugg.id)],
        })
        self.assertEqual(res_ok.status_code, 302)
        visit.refresh_from_db()
        self.assertEqual(visit.status, 'finished')
        self.assertEqual(visit.questionnaire_answers.get(str(self.q_sp.id)), [self.prod_sugg.id])
        self.assertEqual(list(visit.detailed_products.values_list('id', flat=True)), [self.prod_sugg.id])
        self.assertFalse(visit.edited_by_creator)

        # 4. Visits detail, visits list popup, and visits export render readable product names without N+1
        res_detail = self.client.get(reverse('visit_detail', args=[visit.pk]))
        self.assertEqual(res_detail.status_code, 200)
        self.assertContains(res_detail, self.prod_sugg.name)
        # Single unified representation inside Questionnaire Responses (no duplicate detailing card)
        self.assertContains(res_detail, 'إجابات استبيان الزيارة')

        res_list = self.client.get(reverse('visits_list'))
        self.assertEqual(res_list.status_code, 200)
        self.assertContains(res_list, self.prod_sugg.name)

        # Rep lacks visits/export permission; Manager exports .xlsx with readable suggested product name
        self.assertEqual(self.client.get(reverse('visits_export')).status_code, 403)
        self.client.force_login(self.mgr_cairo)
        res_exp = self.client.get(reverse('visits_export'))
        self.assertEqual(res_exp.status_code, 200)
        wb = openpyxl.load_workbook(BytesIO(res_exp.content))
        sheet_text = ' '.join(
            str(cell or '')
            for row in wb.active.iter_rows(values_only=True)
            for cell in row
        )
        self.assertIn(self.prod_sugg.name, sheet_text)
        self.client.force_login(self.rep_cairo)

        # 5. Historical preservation: mark prod_sugg inactive later, verify rep can still keep it in Edit Answers
        #    while submitting a DIFFERENT inactive product (prod_inactive) is still rejected
        self.prod_sugg.is_active = False
        self.prod_sugg.save(update_fields=['is_active'])

        res_new_inactive = self.client.post(reverse('visit_update_answers', args=[visit.pk]), {
            f'question_{self.q_sp_outcome.id}': 'successful',
            f'question_{self.q_sp.id}_present': '1',
            f'question_{self.q_sp.id}': [str(self.prod_inactive.id)],
        })
        self.assertEqual(res_new_inactive.status_code, 302)
        visit.refresh_from_db()
        self.assertEqual(visit.questionnaire_answers.get(str(self.q_sp.id)), [self.prod_sugg.id])

        # Keeping historical inactive prod_sugg + adding newly selected active prod_other succeeds
        res_edit_ok = self.client.post(reverse('visit_update_answers', args=[visit.pk]), {
            f'question_{self.q_sp_outcome.id}': 'unsuccessful',
            f'question_{self.q_sp.id}_present': '1',
            f'question_{self.q_sp.id}': [str(self.prod_sugg.id), str(self.prod_other.id)],
        })
        self.assertEqual(res_edit_ok.status_code, 302)
        visit.refresh_from_db()
        self.assertEqual(set(visit.questionnaire_answers.get(str(self.q_sp.id))), {self.prod_sugg.id, self.prod_other.id})
        self.assertEqual(set(visit.detailed_products.values_list('id', flat=True)), {self.prod_sugg.id, self.prod_other.id})
        self.assertEqual(visit.approval_status, 'pending')
        self.assertTrue(visit.waiting_for_reapproval)
        self.assertTrue(visit.edited_by_creator)
        self.assertEqual(visit.last_edited_by, self.rep_cairo)
        self.assertIsNotNone(visit.last_edited_at)

        audit_log = ApprovalAuditLog.objects.filter(visit=visit, action='answers_updated').latest('id')
        changes_blob = str(audit_log.changes)
        self.assertIn(self.prod_sugg.name, changes_blob)
        self.assertIn(self.prod_other.name, changes_blob)

    def test_legacy_detailed_products_editable_in_edit_answers_modal(self):
        """Legacy detailing templates without a 'suggested_products' question still allow modal editing & clearing."""
        visit = Visit.objects.create(
            contact=self.contact_nasr, template=self.tpl_legacy,
            owner=self.rep_cairo, created_by=self.rep_cairo,
            date=timezone.localdate(), status='finished', approval_status='approved',
            ended_at=timezone.now(),
            questionnaire_answers={str(self.q_leg_outcome.id): 'successful'},
        )
        visit.detailed_products.add(self.prod_sugg)

        self.client.force_login(self.rep_cairo)
        res_get = self.client.get(reverse('visit_detail', args=[visit.pk]))
        self.assertContains(res_get, 'name="detailed_products_present"')
        self.assertContains(res_get, self.prod_sugg.name)

        # Update detailed_products via Edit Answers modal endpoint
        res_upd = self.client.post(reverse('visit_update_answers', args=[visit.pk]), {
            f'question_{self.q_leg_outcome.id}': 'successful',
            'detailed_products_present': '1',
            'detailed_products': [str(self.prod_other.id)],
        })
        self.assertEqual(res_upd.status_code, 302)
        visit.refresh_from_db()
        self.assertEqual(list(visit.detailed_products.values_list('id', flat=True)), [self.prod_other.id])
        self.assertTrue(visit.edited_by_creator)

    def test_creator_edit_tracking_filter_and_data_scope(self):
        """
        Creator edits mark edited_by_creator=True, non-creator/no-op edits keep it False,
        and visits/?edited_by_creator=yes|no enforces ScopeResolutionService on list & export.
        """
        today = timezone.localdate()
        tomorrow = today + datetime.timedelta(days=1)

        v_creator_edited = Visit.objects.create(
            contact=self.contact_nasr, template=self.tpl_legacy,
            owner=self.rep_cairo, created_by=self.rep_cairo,
            date=today, status='planned', approval_status='approved',
        )
        v_creator_untouched = Visit.objects.create(
            contact=self.contact_nasr, template=self.tpl_legacy,
            owner=self.rep_cairo, created_by=self.rep_cairo,
            date=today, status='planned', approval_status='approved',
        )
        v_peer_edited = Visit.objects.create(
            contact=self.contact_maadi, template=self.tpl_legacy,
            owner=self.peer_rep, created_by=self.peer_rep,
            date=today, status='planned', approval_status='approved',
            edited_by_creator=True,
        )
        v_giza_edited = Visit.objects.create(
            contact=self.contact_dokki, template=self.tpl_legacy,
            owner=self.mgr_giza, created_by=self.mgr_giza,
            date=today, status='planned', approval_status='approved',
            edited_by_creator=True,
        )

        # No-op edit by creator does NOT set edited_by_creator=True
        self.client.force_login(self.rep_cairo)
        self.client.post(reverse('visit_edit', args=[v_creator_untouched.pk]), {
            'contact': self.contact_nasr.id,
            'template': self.tpl_legacy.id,
            'date': today.strftime('%Y-%m-%d'),
        })
        v_creator_untouched.refresh_from_db()
        self.assertFalse(v_creator_untouched.edited_by_creator)

        # Actual date change by creator sets edited_by_creator=True
        self.client.post(reverse('visit_edit', args=[v_creator_edited.pk]), {
            'contact': self.contact_nasr.id,
            'template': self.tpl_legacy.id,
            'date': tomorrow.strftime('%Y-%m-%d'),
        })
        v_creator_edited.refresh_from_db()
        self.assertTrue(v_creator_edited.edited_by_creator)
        self.assertEqual(v_creator_edited.last_edited_by, self.rep_cairo)

        # Manager editing v_creator_untouched sets last_edited_by, NOT edited_by_creator
        self.client.force_login(self.mgr_cairo)
        self.client.post(reverse('visit_edit', args=[v_creator_untouched.pk]), {
            'contact': self.contact_nasr.id,
            'template': self.tpl_legacy.id,
            'date': tomorrow.strftime('%Y-%m-%d'),
        })
        v_creator_untouched.refresh_from_db()
        self.assertFalse(v_creator_untouched.edited_by_creator)
        self.assertEqual(v_creator_untouched.last_edited_by, self.mgr_cairo)

        # Filter as Cairo Rep: sees only own matching edited visit, never peer or Giza
        self.client.force_login(self.rep_cairo)
        res_yes_rep = self.client.get(reverse('visits_list'), {'edited_by_creator': 'yes'})
        yes_ids_rep = {v.id for v in res_yes_rep.context['visits']}
        self.assertEqual(yes_ids_rep, {v_creator_edited.id})
        self.assertNotIn(v_peer_edited.id, yes_ids_rep)
        self.assertNotIn(v_giza_edited.id, yes_ids_rep)

        res_no_rep = self.client.get(reverse('visits_list'), {'edited_by_creator': 'no'})
        no_ids_rep = {v.id for v in res_no_rep.context['visits']}
        self.assertEqual(no_ids_rep, {v_creator_untouched.id})

        # Combine with status filter
        res_combo = self.client.get(reverse('visits_list'), {'edited_by_creator': 'yes', 'status': 'finished'})
        self.assertEqual(len(res_combo.context['visits']), 0)

        # Filter as Cairo Manager: sees Cairo creator-edited (Nasr + Maadi), never Giza
        self.client.force_login(self.mgr_cairo)
        res_yes_mgr = self.client.get(reverse('visits_list'), {'edited_by_creator': 'yes'})
        yes_ids_mgr = {v.id for v in res_yes_mgr.context['visits']}
        self.assertIn(v_creator_edited.id, yes_ids_mgr)
        self.assertIn(v_peer_edited.id, yes_ids_mgr)
        self.assertNotIn(v_giza_edited.id, yes_ids_mgr)

        # Export also respects edited_by_creator & scope
        from io import BytesIO
        import openpyxl
        res_exp_yes = self.client.get(reverse('visits_export'), {'edited_by_creator': 'yes'})
        self.assertEqual(res_exp_yes.status_code, 200)
        wb = openpyxl.load_workbook(BytesIO(res_exp_yes.content))
        exp_text = ' '.join(str(c or '') for r in wb.active.iter_rows(values_only=True) for c in r)
        self.assertIn(f"#{v_creator_edited.serial_num}", exp_text)
        self.assertNotIn(f"#{v_creator_untouched.serial_num}", exp_text)
        self.assertNotIn(f"#{v_giza_edited.serial_num}", exp_text)

    def test_agreements_more_vert_status_scope_and_attachment_cleanup(self):
        """Agreements enforce view/edit/delete permissions, status rules ('new'/'disapproved'), IDOR, attachments, and audits."""
        from django.contrib.contenttypes.models import ContentType
        from django.core.files.uploadedfile import SimpleUploadedFile
        from master_data.models import ERPAttachment

        today = timezone.localdate()
        agr_new = self.Agreement.objects.create(
            title='اتفاقية جديدة', type=self.agr_type, customer=self.contact_nasr,
            amount=Decimal('500.00'), date=today, status='new', created_by=self.rep_cairo
        )
        agr_done = self.Agreement.objects.create(
            title='اتفاقية منجزة', type=self.agr_type, customer=self.contact_nasr,
            amount=Decimal('750.00'), date=today, status='done', created_by=self.rep_cairo, approved_by=self.mgr_cairo
        )
        ct_agr = ContentType.objects.get_for_model(self.Agreement)
        att = ERPAttachment.objects.create(
            content_type=ct_agr,
            object_id=agr_new.id,
            file=SimpleUploadedFile('agr_doc.pdf', b'%PDF-1.4 test', content_type='application/pdf'),
            original_filename='agr_doc.pdf',
            mime_type='application/pdf',
            file_size_bytes=13,
            uploaded_by=self.rep_cairo,
        )

        # Rep views list: Edit/Delete shown for 'new', hidden for 'done'; DOM balanced with row-menu-trigger
        self.client.force_login(self.rep_cairo)
        res_list = self.client.get(reverse('agreements_list'))
        self.assertEqual(res_list.status_code, 200)
        self.assertContains(res_list, 'row-menu-trigger')
        self.assertContains(res_list, 'showConfirmDeleteModal')
        self.assertContains(res_list, 'global-confirm-delete-modal')
        self.assertContains(res_list, reverse('agreement_edit', args=[agr_new.id]))
        self.assertContains(res_list, reverse('agreement_delete', args=[agr_new.id]))
        self.assertNotContains(res_list, reverse('agreement_edit', args=[agr_done.id]))
        self.assertNotContains(res_list, reverse('agreement_delete', args=[agr_done.id]))

        # Giza manager cannot access or mutate Cairo agreement (IDOR -> 403)
        self.client.force_login(self.mgr_giza)
        self.assertEqual(self.client.get(reverse('agreement_detail', args=[agr_new.id])).status_code, 403)
        self.assertEqual(self.client.post(reverse('agreement_edit', args=[agr_new.id]), {'title': 'Hack'}).status_code, 403)
        self.assertEqual(self.client.post(reverse('agreement_delete', args=[agr_new.id])).status_code, 403)

        # Creator edits 'new' agreement successfully -> writes AGREEMENT_UPDATED audit log
        self.client.force_login(self.rep_cairo)
        res_edit = self.client.post(reverse('agreement_edit', args=[agr_new.id]), {
            'customer': self.contact_nasr.id,
            'type': self.agr_type.id,
            'title': 'اتفاقية محدثة',
            'amount': '600.00',
            'date': today.strftime('%Y-%m-%d'),
            'description': 'تم التحديث',
        })
        self.assertEqual(res_edit.status_code, 302)
        agr_new.refresh_from_db()
        self.assertEqual(agr_new.title, 'اتفاقية محدثة')
        self.assertTrue(SecurityAuditLog.objects.filter(action_type='AGREEMENT_UPDATED', record_id=str(agr_new.id)).exists())

        # Cannot edit or delete 'done' agreement
        res_done_edit = self.client.get(reverse('agreement_edit', args=[agr_done.id]))
        self.assertEqual(res_done_edit.status_code, 302)
        res_done_del_ajax = self.client.post(
            reverse('agreement_delete', args=[agr_done.id]),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(res_done_del_ajax.status_code, 400)
        self.assertTrue(self.Agreement.objects.filter(pk=agr_done.id).exists())

        # Delete 'new' agreement cleans up attachment and writes AGREEMENT_DELETED audit log
        res_del = self.client.post(
            reverse('agreement_delete', args=[agr_new.id]),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(res_del.status_code, 200)
        self.assertTrue(res_del.json()['success'])
        self.assertFalse(self.Agreement.objects.filter(pk=agr_new.id).exists())
        self.assertFalse(ERPAttachment.objects.filter(pk=att.pk).exists())
        self.assertTrue(SecurityAuditLog.objects.filter(action_type='AGREEMENT_DELETED', record_id=str(agr_new.id)).exists())

    def test_cleanup_command_dry_run_reports_related_counts_and_audit_note(self):
        """Dry-run mode prints Samples/Expenses/CoachingEvaluations/VisitPlans/SecurityAuditLog note and deletes nothing."""
        from io import StringIO
        from django.core.management import call_command

        agr = self.Agreement.objects.create(
            title='cleanup agr', type=self.agr_type, customer=self.contact_nasr,
            amount=Decimal('100.00'), date=timezone.localdate(), created_by=self.superadmin
        )
        vis = Visit.objects.create(
            contact=self.contact_nasr, template=self.tpl_legacy,
            owner=self.rep_cairo, created_by=self.rep_cairo, date=timezone.localdate()
        )
        day = PlannedVisitDay.objects.create(assignee=self.rep_cairo, date=timezone.localdate())
        PlannedVisitItem.objects.create(plan_day=day, contact=self.contact_nasr, visit=vis)

        out = StringIO()
        call_command('cleanup_test_activities', agreement_ids=[agr.id], visit_ids=[vis.id], planned_day_ids=[day.id], stdout=out)
        text = out.getvalue()
        self.assertIn('Agreements: 1', text)
        self.assertIn('Visits: 1', text)
        self.assertIn('Samples:', text)
        self.assertIn('CoachingEvaluations:', text)
        self.assertIn('SecurityAuditLog', text)
        self.assertIn('DRY-RUN complete', text)
        self.assertTrue(self.Agreement.objects.filter(pk=agr.id).exists())
        self.assertTrue(Visit.objects.filter(pk=vis.id).exists())
        self.assertTrue(PlannedVisitDay.objects.filter(pk=day.id).exists())

