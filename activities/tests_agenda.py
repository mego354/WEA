import datetime
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.utils import timezone

from accounts.models import Role, Permission
from master_data.models import Area
from contacts.models import Contact
from activities.models import (
    Visit, VisitTemplate, PlannedVisitDay, PlannedVisitItem, AgendaTodo
)

User = get_user_model()


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

