from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from decimal import Decimal
from master_data.models import Area
from accounts.models import Role
from contacts.models import Contact
from sales.models import SalesOrder, Collection, CustomerAccount
from activities.models import Visit
from inventory.models import Warehouse
from treasury.models import Vault
from accounts.permissions import (
    get_scoped_queryset, can_user_access_object, is_manager_eligible_for_user
)

User = get_user_model()


class AppWideDataScopingTests(TestCase):
    def setUp(self):
        self.client = Client()

        # Roles
        self.superadmin_role, _ = Role.objects.get_or_create(
            name=Role.ROLE_SUPERADMIN,
            defaults={'display_name': 'مدير النظام الأعلى', 'is_super': True, 'is_system': True, 'is_active': True}
        )
        self.manager_role, _ = Role.objects.get_or_create(
            name=Role.ROLE_MANAGER,
            defaults={'display_name': 'مدير', 'is_area_manager': True, 'is_system': True, 'is_active': True}
        )
        self.accountant_role, _ = Role.objects.get_or_create(
            name=Role.ROLE_ACCOUNTANT,
            defaults={'display_name': 'محاسب', 'is_system': True, 'is_active': True}
        )
        self.rep_role, _ = Role.objects.get_or_create(
            name=Role.ROLE_REP,
            defaults={'display_name': 'مندوب مبيعات', 'is_rep': True, 'is_system': True, 'is_active': True}
        )
        self.medical_rep_role, _ = Role.objects.get_or_create(
            name=Role.ROLE_MEDICAL_REP,
            defaults={'display_name': 'مندوب دعاية طبية', 'is_rep': True, 'is_system': True, 'is_active': True}
        )

        # Geographic Areas Hierarchy
        # Main Area 1: Cairo (القاهرة)
        self.cairo = Area.objects.create(code='CAI', name='القاهرة', area_type='governorate', is_company_area=False)
        self.nasr_city = Area.objects.create(code='NASR', name='مدينة نصر', area_type='subarea', parent=self.cairo, is_company_area=False)
        self.maadi = Area.objects.create(code='MAADI', name='المعادي', area_type='subarea', parent=self.cairo, is_company_area=False)

        # Main Area 2: Giza (الجيزة)
        self.giza = Area.objects.create(code='GIZ', name='الجيزة', area_type='governorate', is_company_area=False)
        self.dokki = Area.objects.create(code='DOK', name='الدقي', area_type='subarea', parent=self.giza, is_company_area=False)
        self.haram = Area.objects.create(code='HAR', name='الهرم', area_type='subarea', parent=self.giza, is_company_area=False)

        # Users
        # 1. Superadmin
        self.superadmin = User.objects.create_superuser(
            username='super@wea.com', email='super@wea.com', password='Password123!',
            name='Super Admin', role=self.superadmin_role
        )

        # 2. Accountant
        self.accountant = User.objects.create_user(
            username='acct@wea.com', email='acct@wea.com', password='Password123!',
            name='Chief Accountant', role=self.accountant_role
        )

        # 3. Manager Cairo (assigned to Cairo main area)
        self.mgr_cairo = User.objects.create_user(
            username='mgr_cairo@wea.com', email='mgr_cairo@wea.com', password='Password123!',
            name='Manager Cairo', role=self.manager_role
        )
        self.mgr_cairo.assigned_areas.add(self.cairo)

        # 4. Manager Giza (assigned to Giza main area)
        self.mgr_giza = User.objects.create_user(
            username='mgr_giza@wea.com', email='mgr_giza@wea.com', password='Password123!',
            name='Manager Giza', role=self.manager_role
        )
        self.mgr_giza.assigned_areas.add(self.giza)

        # 5. Manager Without Area (unassigned)
        self.mgr_no_area = User.objects.create_user(
            username='mgr_no_area@wea.com', email='mgr_no_area@wea.com', password='Password123!',
            name='Manager No Area', role=self.manager_role
        )

        # 6. Rep 1 Cairo (Nasr City subarea)
        self.rep_cairo_1 = User.objects.create_user(
            username='rep_cairo1@wea.com', email='rep_cairo1@wea.com', password='Password123!',
            name='Rep Cairo NasrCity', role=self.rep_role
        )
        self.rep_cairo_1.assigned_areas.add(self.nasr_city)

        # 7. Rep 2 Cairo (Maadi subarea - same main area, different secondary area)
        self.rep_cairo_2 = User.objects.create_user(
            username='rep_cairo2@wea.com', email='rep_cairo2@wea.com', password='Password123!',
            name='Rep Cairo Maadi', role=self.rep_role
        )
        self.rep_cairo_2.assigned_areas.add(self.maadi)

        # 8. Rep Giza (Dokki subarea)
        self.rep_giza = User.objects.create_user(
            username='rep_giza@wea.com', email='rep_giza@wea.com', password='Password123!',
            name='Rep Giza Dokki', role=self.rep_role
        )
        self.rep_giza.assigned_areas.add(self.dokki)

        # 9. Medical Rep Cairo
        self.med_rep_cairo = User.objects.create_user(
            username='med_rep@wea.com', email='med_rep@wea.com', password='Password123!',
            name='Medical Rep Cairo', role=self.medical_rep_role
        )
        self.med_rep_cairo.assigned_areas.add(self.nasr_city)

        # Contacts
        self.contact_cairo = Contact.objects.create(
            name='صيدلية مصر - مدينة نصر', area=self.nasr_city, is_customer=True,
            created_by=self.rep_cairo_1
        )
        self.contact_giza = Contact.objects.create(
            name='صيدلية النيل - الدقي', area=self.dokki, is_customer=True,
            created_by=self.rep_giza
        )

        # Warehouses
        self.wh_cairo = Warehouse.objects.create(code='WH-CAI', name='مخزن القاهرة الرئيسي', area=self.cairo, is_main=True, is_active=True)
        self.wh_giza = Warehouse.objects.create(code='WH-GIZ', name='مخزن الجيزة', area=self.giza, is_main=False, is_active=True)

        # Sales Orders
        self.order_cairo_1 = SalesOrder.objects.create(
            order_number='SO-C1', customer=self.contact_cairo, source_warehouse=self.wh_cairo,
            created_by=self.rep_cairo_1, grand_total=Decimal('1000.00'), status='pending'
        )
        self.order_cairo_2 = SalesOrder.objects.create(
            order_number='SO-C2', customer=self.contact_cairo, source_warehouse=self.wh_cairo,
            created_by=self.rep_cairo_2, grand_total=Decimal('2000.00'), status='pending'
        )
        self.order_giza = SalesOrder.objects.create(
            order_number='SO-G1', customer=self.contact_giza, source_warehouse=self.wh_giza,
            created_by=self.rep_giza, grand_total=Decimal('3000.00'), status='pending'
        )

        # Collections
        self.vault_cairo_1 = Vault.objects.create(
            name='خزنة مندوب نصر', assigned_user=self.rep_cairo_1, current_balance=Decimal('500.00'), is_active=True
        )
        self.vault_giza = Vault.objects.create(
            name='خزنة مندوب الدقي', assigned_user=self.rep_giza, current_balance=Decimal('700.00'), is_active=True
        )
        self.col_cairo_1 = Collection.objects.create(
            serial_num=101, customer=self.contact_cairo, vault=self.vault_cairo_1,
            amount=Decimal('500.00'), created_by=self.rep_cairo_1
        )
        self.col_giza = Collection.objects.create(
            serial_num=102, customer=self.contact_giza, vault=self.vault_giza,
            amount=Decimal('700.00'), created_by=self.rep_giza
        )

        # Visits
        self.visit_cairo_1 = Visit.objects.create(
            serial_num=501, contact=self.contact_cairo,
            owner=self.rep_cairo_1, created_by=self.rep_cairo_1, status='finished'
        )
        self.visit_cairo_2 = Visit.objects.create(
            serial_num=502, contact=self.contact_cairo,
            owner=self.rep_cairo_2, created_by=self.rep_cairo_2, status='finished'
        )
        self.visit_giza = Visit.objects.create(
            serial_num=503, contact=self.contact_giza,
            owner=self.rep_giza, created_by=self.rep_giza, status='finished'
        )

    def test_rep_data_scoping_strict_ownership(self):
        """A sales representative sees strictly their own records, not peers in the same or other areas."""
        # Sales Orders
        scoped_so = get_scoped_queryset(SalesOrder.objects.all(), self.rep_cairo_1, 'salesorder')
        self.assertIn(self.order_cairo_1, scoped_so)
        self.assertNotIn(self.order_cairo_2, scoped_so)  # Peer in same main area (different subarea) forbidden
        self.assertNotIn(self.order_giza, scoped_so)     # Rep in other main area forbidden

        # Collections
        scoped_col = get_scoped_queryset(Collection.objects.all(), self.rep_cairo_1, 'collection')
        self.assertIn(self.col_cairo_1, scoped_col)
        self.assertNotIn(self.col_giza, scoped_col)

        # Visits
        scoped_vis = get_scoped_queryset(Visit.objects.all(), self.rep_cairo_1, 'visit')
        self.assertIn(self.visit_cairo_1, scoped_vis)
        self.assertNotIn(self.visit_cairo_2, scoped_vis)
        self.assertNotIn(self.visit_giza, scoped_vis)

        # Object-level check
        self.assertTrue(can_user_access_object(self.rep_cairo_1, self.order_cairo_1, 'view'))
        self.assertFalse(can_user_access_object(self.rep_cairo_1, self.order_cairo_2, 'view'))
        self.assertFalse(can_user_access_object(self.rep_cairo_1, self.order_giza, 'view'))

    def test_manager_main_area_scoping(self):
        """A manager sees records of reps in their main area across sub-areas, but NOT other main areas."""
        # Manager Cairo sees reps in Nasr City and Maadi (both under Cairo)
        scoped_so = get_scoped_queryset(SalesOrder.objects.all(), self.mgr_cairo, 'salesorder')
        self.assertIn(self.order_cairo_1, scoped_so)
        self.assertIn(self.order_cairo_2, scoped_so)
        self.assertNotIn(self.order_giza, scoped_so)  # Giza is a different main area!

        # Visits
        scoped_vis = get_scoped_queryset(Visit.objects.all(), self.mgr_cairo, 'visit')
        self.assertIn(self.visit_cairo_1, scoped_vis)
        self.assertIn(self.visit_cairo_2, scoped_vis)
        self.assertNotIn(self.visit_giza, scoped_vis)

        # Manager Giza sees Giza rep, not Cairo reps
        scoped_so_giza = get_scoped_queryset(SalesOrder.objects.all(), self.mgr_giza, 'salesorder')
        self.assertIn(self.order_giza, scoped_so_giza)
        self.assertNotIn(self.order_cairo_1, scoped_so_giza)
        self.assertNotIn(self.order_cairo_2, scoped_so_giza)

        # Object level checks
        self.assertTrue(can_user_access_object(self.mgr_cairo, self.order_cairo_1, 'view'))
        self.assertTrue(can_user_access_object(self.mgr_cairo, self.order_cairo_2, 'view'))
        self.assertFalse(can_user_access_object(self.mgr_cairo, self.order_giza, 'view'))

    def test_manager_without_area_fails_securely(self):
        """A manager without a valid main-area assignment fails securely and sees no reps."""
        scoped_so = get_scoped_queryset(SalesOrder.objects.all(), self.mgr_no_area, 'salesorder')
        self.assertEqual(scoped_so.count(), 0)

        scoped_vis = get_scoped_queryset(Visit.objects.all(), self.mgr_no_area, 'visit')
        self.assertEqual(scoped_vis.count(), 0)

        self.assertFalse(can_user_access_object(self.mgr_no_area, self.order_cairo_1, 'view'))
        self.assertFalse(can_user_access_object(self.mgr_no_area, self.order_giza, 'view'))

    def test_accountant_broad_financial_visibility(self):
        """Accountant sees all sales orders and collections across all areas, but cannot approve/tamper."""
        scoped_so = get_scoped_queryset(SalesOrder.objects.all(), self.accountant, 'salesorder')
        self.assertEqual(scoped_so.count(), 3)
        self.assertIn(self.order_cairo_1, scoped_so)
        self.assertIn(self.order_cairo_2, scoped_so)
        self.assertIn(self.order_giza, scoped_so)

        scoped_col = get_scoped_queryset(Collection.objects.all(), self.accountant, 'collection')
        self.assertEqual(scoped_col.count(), 2)

        self.assertTrue(can_user_access_object(self.accountant, self.order_cairo_1, 'view'))
        self.assertTrue(can_user_access_object(self.accountant, self.order_giza, 'view'))

    def test_superadmin_unrestricted_access(self):
        """Superadmin has global unrestricted access to all records."""
        scoped_so = get_scoped_queryset(SalesOrder.objects.all(), self.superadmin, 'salesorder')
        self.assertEqual(scoped_so.count(), 3)

        scoped_vis = get_scoped_queryset(Visit.objects.all(), self.superadmin, 'visit')
        self.assertEqual(scoped_vis.count(), 3)

        self.assertTrue(can_user_access_object(self.superadmin, self.order_cairo_1, 'view'))
        self.assertTrue(can_user_access_object(self.superadmin, self.order_giza, 'view'))

    def test_anti_self_approval(self):
        """No user can approve or reject their own submitted visit or transaction."""
        # Manager Cairo visit created by themselves
        visit_mgr = Visit.objects.create(
            serial_num=504, contact=self.contact_cairo,
            owner=self.mgr_cairo, created_by=self.mgr_cairo, status='planned'
        )
        self.assertFalse(can_user_access_object(self.mgr_cairo, visit_mgr, 'approve'))
        self.assertFalse(can_user_access_object(self.mgr_cairo, visit_mgr, 'reject'))
        # But can view it
        self.assertTrue(can_user_access_object(self.mgr_cairo, visit_mgr, 'view'))
