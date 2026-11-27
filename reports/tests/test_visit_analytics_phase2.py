import calendar
import datetime
import io
import json
from decimal import Decimal

import openpyxl
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import connection
from django.test import Client, RequestFactory, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role, SecurityAuditLog, User
from activities.models import PlannedVisitDay, PlannedVisitItem, Visit
from contacts.models import Contact
from master_data.date_filter_utils import get_week_bounds_sat_to_fri, resolve_date_range
from master_data.models import AccountTypeReportGroup, Area
from master_data.services import SettingsService
from reports.services import (
    get_customer_360_report_data,
    get_performance_analysis_data,
    get_performance_detailed_matrix,
)
from reports.visit_analytics import (
    UNCLASSIFIED_GROUP_CODE,
    VisitAnalyticsService,
    resolve_performance_filters,
)
from sales.models import CustomerAccount, SalesOrder


class Phase2VisitAnalyticsAndSettingsTests(TestCase):
    """
    Comprehensive test suite verifying all 5 confirmed business rules, configurable
    AccountTypeReportGroup settings, DataScope isolation, security/fuzzing defenses,
    selective Excel export, dashboard sunburst accuracy, and O(1) query scaling.
    """

    @classmethod
    def setUpTestData(cls):
        call_command('setup_permissions', no_audit=True)

        cls.super_role = Role.objects.get(name=Role.ROLE_SUPERADMIN)
        cls.mgr_role = Role.objects.get(name=Role.ROLE_MANAGER)
        cls.rep_role = Role.objects.get(name=Role.ROLE_REP)
        cls.med_role = Role.objects.get(name=Role.ROLE_MEDICAL_REP)
        cls.acct_role = Role.objects.get(name=Role.ROLE_ACCOUNTANT)

        # Geography: Cairo (Nasr City, Maadi) vs Giza (Dokki)
        cls.cairo = Area.objects.create(name='القاهرة تحليلات', code='CAI-ANL', area_type='governorate')
        cls.nasr = Area.objects.create(name='مدينة نصر تحليلات', code='NSR-ANL', area_type='subarea', parent=cls.cairo)
        cls.maadi = Area.objects.create(name='المعادي تحليلات', code='MAA-ANL', area_type='subarea', parent=cls.cairo)

        cls.giza = Area.objects.create(name='الجيزة تحليلات', code='GIZ-ANL', area_type='governorate')
        cls.dokki = Area.objects.create(name='الدقي تحليلات', code='DOK-ANL', area_type='subarea', parent=cls.giza)

        # Users
        cls.superadmin = User.objects.create_superuser(
            username='sa_anl@wea.com', email='sa_anl@wea.com', password='Password123!',
            name='سوبر أدمن التحليلات', role=cls.super_role,
        )
        cls.cairo_mgr = User.objects.create_user(
            username='mgr_cai_anl@wea.com', email='mgr_cai_anl@wea.com', password='Password123!',
            name='مدير القاهرة', role=cls.mgr_role,
        )
        cls.cairo_mgr.assigned_areas.add(cls.cairo)

        cls.giza_mgr = User.objects.create_user(
            username='mgr_giz_anl@wea.com', email='mgr_giz_anl@wea.com', password='Password123!',
            name='مدير الجيزة', role=cls.mgr_role,
        )
        cls.giza_mgr.assigned_areas.add(cls.giza)

        cls.rep_cai = User.objects.create_user(
            username='rep_cai_anl@wea.com', email='rep_cai_anl@wea.com', password='Password123!',
            name='مندوب مدينة نصر', role=cls.rep_role,
        )
        cls.rep_cai.assigned_areas.add(cls.nasr)

        cls.rep_peer = User.objects.create_user(
            username='rep_peer_anl@wea.com', email='rep_peer_anl@wea.com', password='Password123!',
            name='مندوب زميل نصر', role=cls.rep_role,
        )
        cls.rep_peer.assigned_areas.add(cls.nasr)

        # Multi-area rep assigned to BOTH Cairo (Nasr City) and Giza (Dokki)
        cls.rep_multi = User.objects.create_user(
            username='rep_multi_anl@wea.com', email='rep_multi_anl@wea.com', password='Password123!',
            name='مندوب متعدد المحافظات', role=cls.med_role,
        )
        cls.rep_multi.assigned_areas.add(cls.nasr, cls.dokki)

        cls.accountant = User.objects.create_user(
            username='acc_anl@wea.com', email='acc_anl@wea.com', password='Password123!',
            name='محاسب التحليلات', role=cls.acct_role,
        )

        # Ensure default seeded report groups exist
        AccountTypeReportGroup.objects.all().delete()
        cls.grp_pharm = AccountTypeReportGroup.objects.create(
            name='الصيدليات', code='pharmacies', account_types=['Pharmacy'],
            display_order=1, icon='local_pharmacy', is_active=True,
        )
        cls.grp_med = AccountTypeReportGroup.objects.create(
            name='المنشآت الطبية', code='medical-facilities', account_types=['Clinic', 'Polyclinic'],
            display_order=2, icon='stethoscope', is_active=True,
        )

        # Accounts in Cairo (Nasr City):
        # 1. Pharmacy Customer (with formula-injection-like name to test sanitization)
        cls.c_pharm = Contact.objects.create(
            name='=SUM(1,2) صيدلية الشفاء', is_customer=True, status='customer',
            account_type='Pharmacy', area=cls.cairo, brick=cls.nasr, created_by=cls.rep_cai,
        )
        cls.c_pharm.assigned_team.add(cls.rep_cai)

        # 2. Clinic Lead (active lead — included by default!)
        cls.c_clinic_lead = Contact.objects.create(
            name='عيادة الأمل التخصصية', is_customer=True, status='lead',
            account_type='Clinic', area=cls.cairo, brick=cls.nasr, created_by=cls.rep_cai,
        )
        cls.c_clinic_lead.assigned_team.add(cls.rep_cai)

        # 3. Polyclinic Customer (unvisited!)
        cls.c_poly_unvis = Contact.objects.create(
            name='مجمع عيادات السلام', is_customer=True, status='customer',
            account_type='Polyclinic', area=cls.cairo, brick=cls.nasr, created_by=cls.rep_cai,
        )
        cls.c_poly_unvis.assigned_team.add(cls.rep_cai)

        # 4. Hospital Customer (unclassified account_type -> goes to أنواع أخرى غير مصنفة)
        cls.c_hosp = Contact.objects.create(
            name='مستشفى النيل المركزي', is_customer=True, status='customer',
            account_type='Hospital', area=cls.cairo, brick=cls.nasr, created_by=cls.rep_cai,
        )
        cls.c_hosp.assigned_team.add(cls.rep_cai)

        # 5. Inactive Customer (must be EXCLUDED from Eligible Accounts!)
        cls.c_inactive = Contact.objects.create(
            name='صيدلية مغلقة قديمة', is_customer=True, status='inactive',
            account_type='Pharmacy', area=cls.cairo, brick=cls.nasr, created_by=cls.rep_cai,
        )

        # 6. Giza Pharmacy Customer (for cross-area isolation tests)
        cls.c_giza = Contact.objects.create(
            name='صيدلية الدقي بالجيزة', is_customer=True, status='customer',
            account_type='Pharmacy', area=cls.giza, brick=cls.dokki, created_by=cls.rep_multi,
        )
        cls.c_giza.assigned_team.add(cls.rep_multi)

        # Fixed test month: 2026-06-01 .. 2026-06-30 (30 calendar days)
        cls.d_start = datetime.date(2026, 6, 1)
        cls.d_end = datetime.date(2026, 6, 30)

        # Visits for rep_cai in June 2026:
        # V1: Planned Completed (approved) on Jun 2 -> c_pharm
        Visit.objects.create(
            owner=cls.rep_cai, created_by=cls.rep_cai, contact=cls.c_pharm,
            date=datetime.date(2026, 6, 2), is_planned=True, status='finished',
            approval_status='approved', duration=600,
        )
        # V2: Unplanned Completed (pending re-approval / distance exception -> MUST COUNT per confirmed Rule 1!) on Jun 2 -> c_pharm (2nd visit same day & same contact)
        Visit.objects.create(
            owner=cls.rep_cai, created_by=cls.rep_cai, contact=cls.c_pharm,
            date=datetime.date(2026, 6, 2), is_planned=False, status='finished',
            approval_status='pending', waiting_for_reapproval=True,
            requires_approval_due_to_distance=True, duration=300,
        )
        # V3: Planned Completed on Jun 5 -> c_clinic_lead
        Visit.objects.create(
            owner=cls.rep_cai, created_by=cls.rep_cai, contact=cls.c_clinic_lead,
            date=datetime.date(2026, 6, 5), is_planned=True, status='finished',
            approval_status='approved', duration=900,
        )
        # V4: Planned Incomplete (unstarted 'planned') on Jun 10 -> c_poly_unvis
        Visit.objects.create(
            owner=cls.rep_cai, created_by=cls.rep_cai, contact=cls.c_poly_unvis,
            date=datetime.date(2026, 6, 10), is_planned=True, status='planned',
            approval_status='approved',
        )
        # V5: Planned Incomplete ('started', open) on Jun 11 -> c_hosp
        Visit.objects.create(
            owner=cls.rep_cai, created_by=cls.rep_cai, contact=cls.c_hosp,
            date=datetime.date(2026, 6, 11), is_planned=True, status='started',
            approval_status='approved',
        )
        # V6: Legacy unlinked PlannedVisitItem (no Visit row!) on Jun 12 -> c_poly_unvis
        pday = PlannedVisitDay.objects.create(assignee=cls.rep_cai, date=datetime.date(2026, 6, 12), created_by=cls.cairo_mgr)
        PlannedVisitItem.objects.create(plan_day=pday, contact=cls.c_poly_unvis, order=1, is_executed=False, visit=None)

        # V7: Cancelled visit on Jun 15 -> MUST BE EXCLUDED from completed, incomplete, and working days
        Visit.objects.create(
            owner=cls.rep_cai, created_by=cls.rep_cai, contact=cls.c_hosp,
            date=datetime.date(2026, 6, 15), is_planned=True, status='cancelled',
            approval_status='approved',
        )
        # V8: Disapproved finished visit on Jun 16 -> MUST BE EXCLUDED from completed, working days, and visited accounts
        Visit.objects.create(
            owner=cls.rep_cai, created_by=cls.rep_cai, contact=cls.c_hosp,
            date=datetime.date(2026, 6, 16), is_planned=False, status='finished',
            approval_status='disapproved',
        )

        # Multi-area rep visit in Giza (Jun 8) -> MUST NOT leak to Cairo Manager!
        Visit.objects.create(
            owner=cls.rep_multi, created_by=cls.rep_multi, contact=cls.c_giza,
            date=datetime.date(2026, 6, 8), is_planned=False, status='finished',
            approval_status='approved', duration=420,
        )

    def setUp(self):
        self.client = Client()
        self.rf_factory = RequestFactory()
        SettingsService.clear_cache()

    def test_confirmed_business_rules_analytics_bundle(self):
        req = self.rf_factory.get(
            '/performance/overview/',
            {'period': 'custom', 'start_date': '2026-06-01', 'end_date': '2026-06-30', 'rep': str(self.rep_cai.id)},
        )
        req.user = self.cairo_mgr
        rf = resolve_performance_filters(req)
        bundle = VisitAnalyticsService.get_analytics_bundle(self.cairo_mgr, rf)

        # Qualifying Completed: V1 (planned), V2 (unplanned pending re-approval), V3 (planned) = 3
        self.assertEqual(bundle['planned_completed'], 2)
        # Planned Incomplete: V4 ('planned') + V5 ('started') + V6 (unlinked PlannedVisitItem) = 3
        self.assertEqual(bundle['planned_incomplete'], 3)
        self.assertEqual(bundle['planned_total'], 5)
        self.assertEqual(bundle['plan_completion_pct'], 40.0)
        self.assertEqual(bundle['unplanned_completed'], 1)
        self.assertEqual(bundle['total_completed_visits'], 3)

        # Working days: Jun 2 (V1+V2 -> 1 day) + Jun 5 (V3 -> 1 day) = 2 distinct days!
        # Jun 10/11/12/15/16 have zero qualifying completed visits -> NOT counted
        self.assertEqual(bundle['working_days'], 2)
        self.assertEqual(bundle['calendar_days'], 30)
        self.assertEqual(bundle['avg_visits_per_working_day'], 1.5)
        self.assertEqual(bundle['avg_visits_per_calendar_day'], 0.1)

        # Eligible Accounts in Nasr City (excluding c_inactive): c_pharm, c_clinic_lead, c_poly_unvis, c_hosp = 4
        acc = bundle['accounts_summary']
        self.assertEqual(acc['eligible_accounts'], 4)
        # Visited distinct accounts: c_pharm (visited twice -> 1) + c_clinic_lead (1) = 2
        self.assertEqual(acc['visited_accounts'], 2)
        self.assertEqual(acc['unvisited_accounts'], 2)
        self.assertEqual(acc['visited_accounts'] + acc['unvisited_accounts'], acc['eligible_accounts'])
        self.assertEqual(acc['coverage_pct'], 50.0)

        # Continuous daily series: all 30 calendar days including 0-visit days
        self.assertEqual(len(bundle['daily_series']), 30)
        jun2 = next(d for d in bundle['daily_series'] if d['date'] == '2026-06-02')
        self.assertEqual(jun2['planned_completed'], 1)
        self.assertEqual(jun2['unplanned_completed'], 1)
        self.assertEqual(jun2['total_completed'], 2)
        jun3 = next(d for d in bundle['daily_series'] if d['date'] == '2026-06-03')
        self.assertEqual(jun3['total_completed'], 0)
        jun12 = next(d for d in bundle['daily_series'] if d['date'] == '2026-06-12')
        self.assertEqual(jun12['planned_incomplete'], 1)

        # Account-Type Groups Reconciliation (zero double counting)
        all_groups = bundle['all_group_rows']
        self.assertEqual([g['name'] for g in all_groups], ['الصيدليات', 'المنشآت الطبية', 'أنواع أخرى غير مصنفة'])
        self.assertEqual(sum(g['planned_completed'] for g in all_groups), bundle['planned_completed'])
        self.assertEqual(sum(g['planned_incomplete'] for g in all_groups), bundle['planned_incomplete'])
        self.assertEqual(sum(g['unplanned_completed'] for g in all_groups), bundle['unplanned_completed'])
        self.assertEqual(sum(g['total_completed'] for g in all_groups), bundle['total_completed_visits'])
        self.assertEqual(sum(g['eligible_accounts'] for g in all_groups), acc['eligible_accounts'])
        self.assertEqual(sum(g['visited_accounts'] for g in all_groups), acc['visited_accounts'])
        self.assertEqual(sum(g['unvisited_accounts'] for g in all_groups), acc['unvisited_accounts'])

    def test_account_status_filter_narrowing(self):
        # Customer only -> excludes c_clinic_lead
        req_cust = self.rf_factory.get(
            '/performance/overview/',
            {'period': 'custom', 'start_date': '2026-06-01', 'end_date': '2026-06-30',
             'rep': str(self.rep_cai.id), 'account_status': 'customer'},
        )
        req_cust.user = self.cairo_mgr
        b_cust = VisitAnalyticsService.get_analytics_bundle(self.cairo_mgr, resolve_performance_filters(req_cust))
        self.assertEqual(b_cust['accounts_summary']['eligible_accounts'], 3)
        self.assertEqual(b_cust['accounts_summary']['visited_accounts'], 1)
        self.assertEqual(b_cust['accounts_summary']['unvisited_accounts'], 2)

        # Lead only -> only c_clinic_lead
        req_lead = self.rf_factory.get(
            '/performance/overview/',
            {'period': 'custom', 'start_date': '2026-06-01', 'end_date': '2026-06-30',
             'rep': str(self.rep_cai.id), 'account_status': 'lead'},
        )
        req_lead.user = self.cairo_mgr
        b_lead = VisitAnalyticsService.get_analytics_bundle(self.cairo_mgr, resolve_performance_filters(req_lead))
        self.assertEqual(b_lead['accounts_summary']['eligible_accounts'], 1)
        self.assertEqual(b_lead['accounts_summary']['visited_accounts'], 1)
        self.assertEqual(b_lead['accounts_summary']['coverage_pct'], 100.0)

    def test_date_range_sat_to_fri_and_full_current_month(self):
        # Wednesday 2026-06-10 -> Sat 2026-06-06 .. Fri 2026-06-12
        ws, we = get_week_bounds_sat_to_fri(datetime.date(2026, 6, 10))
        self.assertEqual(ws, datetime.date(2026, 6, 6))
        self.assertEqual(we, datetime.date(2026, 6, 12))

        # Explicit non-custom preset overrides auto-filled client dates
        req = self.rf_factory.get('/performance/overview/', {'period': 'today', 'start_date': '2026-01-01', 'end_date': '2026-01-31'})
        s, e, preset, _, _ = resolve_date_range(req, default_preset='this_month')
        today = timezone.localdate()
        self.assertEqual(preset, 'today')
        self.assertEqual(s, today)
        self.assertEqual(e, today)

        # Default current month spans 1st -> last day
        req_def = self.rf_factory.get('/performance/overview/')
        s_m, e_m, preset_m, _, _ = resolve_date_range(req_def, default_preset='this_month')
        self.assertEqual(preset_m, 'this_month')
        self.assertEqual(s_m, today.replace(day=1))
        self.assertEqual(e_m, today.replace(day=calendar.monthrange(today.year, today.month)[1]))

    def test_multi_area_rep_does_not_leak_giza_data_to_cairo_manager(self):
        # rep_multi operates in both Cairo and Giza; Cairo Manager must see 0 Giza visits in analysis & detailed
        analysis = get_performance_analysis_data(self.cairo_mgr, self.d_start, self.d_end)
        multi_row = next((r for r in analysis['rep_summary_table'] if r['rep_id'] == self.rep_multi.id), None)
        if multi_row:
            self.assertEqual(multi_row['total_visits'], 0)

        detailed = get_performance_detailed_matrix(self.cairo_mgr, self.d_start, self.d_end)
        multi_det = next((r for r in detailed['matrix_rows'] if r['rep_id'] == self.rep_multi.id), None)
        if multi_det:
            self.assertEqual(multi_det['total_visits'], 0)

        # Customer 360 uses completed visits only (V7 cancelled & V8 disapproved excluded for c_hosp)
        c360 = get_customer_360_report_data(self.cairo_mgr, self.d_start, self.d_end)
        hosp_row = next((r for r in c360['rows'] if r['name'] == self.c_hosp.name), None)
        self.assertIsNotNone(hosp_row)
        self.assertEqual(hosp_row['visits_cnt'], 0)

    def test_security_tampered_and_malformed_query_params(self):
        # 1. Peer rep attempting to probe another rep or Giza area or Giza contact
        self.client.force_login(self.rep_peer)
        r_probe = self.client.get(
            reverse('performance_overview_accounts_api'),
            {'period': 'custom', 'start_date': '2026-06-01', 'end_date': '2026-06-30', 'rep': str(self.rep_cai.id)},
        )
        self.assertEqual(r_probe.status_code, 200)
        self.assertEqual(r_probe.json()['total_count'], 0)

        r_giza_c = self.client.get(
            reverse('performance_overview_accounts_api'),
            {'contact_id': str(self.c_giza.id)},
        )
        self.assertEqual(r_giza_c.status_code, 200)
        self.assertEqual(r_giza_c.json()['total_count'], 0)

        # 2. Malformed non-numeric tokens must never cause HTTP 500 across performance & reports
        self.client.force_login(self.superadmin)
        for url_name in ('performance_overview', 'performance_analysis', 'performance_detailed', 'report_trial_balance', 'report_customer_360'):
            res = self.client.get(reverse(url_name), {'area': 'abc', 'rep': 'xyz', 'brick': 'bad', 'contact_id': 'nope'})
            self.assertEqual(res.status_code, 200, f"Malformed query crashed {url_name}")

        # 3. Export permission enforced separately from view permission (rep has view, NOT export)
        self.client.force_login(self.rep_cai)
        self.assertEqual(self.client.get(reverse('performance_overview')).status_code, 200)
        self.assertEqual(self.client.get(reverse('performance_overview_export')).status_code, 403)

        # 4. Report-groups settings permission enforced (manager & rep denied; superadmin allowed)
        self.client.force_login(self.cairo_mgr)
        self.assertEqual(self.client.get(reverse('report_groups_settings')).status_code, 403)
        self.client.force_login(self.superadmin)
        self.assertEqual(self.client.get(reverse('report_groups_settings')).status_code, 200)

    def test_selective_excel_export_sanitization_and_audit(self):
        self.client.force_login(self.cairo_mgr)
        # Empty selective export rejected safely
        res_empty = self.client.get(
            reverse('performance_overview_export'),
            {'selective': '1', 'period': 'custom', 'start_date': '2026-06-01', 'end_date': '2026-06-30'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(res_empty.status_code, 400)

        # Valid selective export with specific sections only
        res = self.client.get(
            reverse('performance_overview_export'),
            {
                'selective': '1',
                'period': 'custom',
                'start_date': '2026-06-01',
                'end_date': '2026-06-30',
                'rep': str(self.rep_cai.id),
                'sections': ['summary', 'groups', 'visited_accounts'],
            },
        )
        self.assertEqual(res.status_code, 200)
        self.assertIn('spreadsheetml', res['Content-Type'])

        wb = openpyxl.load_workbook(io.BytesIO(res.content))
        self.assertEqual(wb.sheetnames, ['ملخص الأداء', 'مجموعات الحسابات', 'الحسابات المزارة'])
        # Unselected sheets excluded
        self.assertNotIn('الحسابات غير المزارة', wb.sheetnames)
        self.assertNotIn('النشاط اليومي', wb.sheetnames)

        # Formula injection sanitized on '=SUM(1,2) صيدلية الشفاء'
        ws_vis = wb['الحسابات المزارة']
        names_col = [ws_vis.cell(row=r, column=2).value for r in range(6, ws_vis.max_row + 1)]
        self.assertTrue(any(str(v).startswith("'=SUM(1,2)") for v in names_col))
        # Giza customer NOT in Cairo manager's export
        self.assertFalse(any('الدقي' in str(v) for v in names_col))

        # Audit log recorded
        self.assertTrue(
            SecurityAuditLog.objects.filter(action_type='REPORT_EXPORTED', actor=self.cairo_mgr).exists()
        )

    def test_report_groups_settings_validation_and_crud(self):
        # Duplicate account type across active groups blocked by validation
        dup = AccountTypeReportGroup(name='مجموعة مكررة', account_types=['Pharmacy'], display_order=5, is_active=True)
        with self.assertRaises(ValidationError):
            dup.full_clean()

        # Creating a valid non-overlapping group via UI works & logs audit
        self.client.force_login(self.superadmin)
        res_create = self.client.post(
            reverse('report_group_create'),
            {'name': 'المستشفيات', 'display_order': '3', 'icon': 'local_hospital', 'is_active': 'on', 'account_types': ['Hospital']},
        )
        self.assertEqual(res_create.status_code, 302)
        hosp_grp = AccountTypeReportGroup.objects.get(name='المستشفيات')
        self.assertEqual(hosp_grp.account_types, ['Hospital'])
        self.assertTrue(SecurityAuditLog.objects.filter(action_type='REPORT_GROUP_CREATED', record_id=hosp_grp.pk).exists())

        # Reorder & Toggle
        self.client.post(reverse('report_group_reorder', args=[hosp_grp.pk]), {'direction': 'up'})
        hosp_grp.refresh_from_db()
        self.assertEqual(hosp_grp.display_order, 2)

        self.client.post(reverse('report_group_toggle', args=[hosp_grp.pk]))
        hosp_grp.refresh_from_db()
        self.assertFalse(hosp_grp.is_active)

    def test_dashboard_sunburst_hierarchy_and_completed_visits(self):
        # Add CustomerAccount balance on c_pharm so reps_balance groups by rep_cai (NOT area!)
        acc_p, _ = CustomerAccount.objects.get_or_create(customer=self.c_pharm)
        acc_p.current_balance = Decimal('4500.00')
        acc_p.overdue_balance = Decimal('1000.00')
        acc_p.save()

        self.client.force_login(self.cairo_mgr)
        res = self.client.get(reverse('home'), {'period': 'custom', 'start_date': '2026-06-01', 'end_date': '2026-06-30'})
        self.assertEqual(res.status_code, 200)
        charts = json.loads(res.context['charts_json'])

        # visits_by_area must show Governorate ('القاهرة تحليلات') -> Brick ('مدينة نصر تحليلات') with completed visits ONLY (3, not 7!)
        vis_tree = charts['visits_by_area']
        cai_node = next((n for n in vis_tree if n['name'] == 'القاهرة تحليلات'), None)
        self.assertIsNotNone(cai_node)
        self.assertTrue(any(ch['name'] == 'مدينة نصر تحليلات' and ch['value'] == 3 for ch in cai_node.get('children', [])))

        # reps_balance must group by representative name ('مندوب مدينة نصر')
        reps_tree = charts['reps_balance']
        self.assertTrue(any(n['name'] == 'مندوب مدينة نصر' for n in reps_tree))

        # Dashboard visit KPI cards count completed visits only (cust=2, lead=1)
        cards = {c['id']: c['amount'] for c in res.context['kpi_cards']}
        self.assertEqual(cards['visits_created_customer_stats'], '2')
        self.assertEqual(cards['visits_created_lead_stats'], '1')

    def test_query_complexity_is_constant_with_representative_count(self):
        # Measure SQL query count with current reps
        with CaptureQueriesContext(connection) as ctx_small:
            get_performance_analysis_data(self.superadmin, self.d_start, self.d_end)
            get_performance_detailed_matrix(self.superadmin, self.d_start, self.d_end)

        # Add 10 additional representatives
        for idx in range(10):
            u = User.objects.create_user(
                username=f'scale_rep_{idx}@wea.com', email=f'scale_rep_{idx}@wea.com',
                password='Password123!', name=f'مندوب قياس {idx}', role=self.rep_role,
            )
            u.assigned_areas.add(self.nasr)

        with CaptureQueriesContext(connection) as ctx_large:
            get_performance_analysis_data(self.superadmin, self.d_start, self.d_end)
            get_performance_detailed_matrix(self.superadmin, self.d_start, self.d_end)

        # Query count must stay constant (O(1)), not grow by 10x reps!
        self.assertEqual(len(ctx_small), len(ctx_large))
        self.assertLessEqual(len(ctx_large), 45)
