import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from decimal import Decimal
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone

from master_data.models import Area
from accounts.models import Role
from contacts.models import Contact
from catalog.models import Product, ProductCategory
from inventory.models import Warehouse, InventoryStock, ProductTransferRequest
from treasury.models import Vault
from activities.models import Visit
from sales.models import SalesOrder
from accounts.permissions import (
    is_manager_eligible_for_user, is_manager_eligible_for_area,
    get_user_managed_areas, get_user_managed_representatives,
    get_scoped_queryset, can_user_access_object
)

User = get_user_model()


class AreaBasedApprovalsAndVisibilityTests(TestCase):
    """
    Automated test suite verifying:
    1. Standardized Manager Eligibility based strictly on Main Area (Governorate root)
    2. Cross-subarea approval within same main area is permitted
    3. Cross-main-area approval is strictly rejected
    4. Anti-self-approval enforcement
    5. Manager operational visibility over warehouses, visits, and treasuries
    6. Read-only treasury visibility (no unauthorized transaction authority)
    """

    def setUp(self):
        # 1. Geographic Hierarchy:
        # Cairo Governorate (Root) -> Subareas: Nasr City, Maadi, Heliopolis
        self.cairo_main = Area.objects.create(code='CAI', name='القاهرة', area_type='governorate', parent=None)
        self.nasr_city = Area.objects.create(code='CAI-NC', name='مدينة نصر', area_type='subarea', parent=self.cairo_main)
        self.maadi = Area.objects.create(code='CAI-MD', name='المعادي', area_type='subarea', parent=self.cairo_main)
        self.heliopolis = Area.objects.create(code='CAI-HL', name='مصر الجديدة', area_type='subarea', parent=self.cairo_main)

        # Giza Governorate (Root) -> Subarea: Dokki
        self.giza_main = Area.objects.create(code='GIZ', name='الجيزة', area_type='governorate', parent=None)
        self.dokki = Area.objects.create(code='GIZ-DK', name='الدقي', area_type='subarea', parent=self.giza_main)

        # 2. Roles:
        self.rep_role, _ = Role.objects.get_or_create(name='MedicalRep', defaults={'display_name': 'مندوب دعاية', 'is_rep': True})
        self.rep_role.is_rep = True
        self.rep_role.save()

        self.mgr_role, _ = Role.objects.get_or_create(name='AreaManager', defaults={'display_name': 'مدير منطقة', 'is_area_manager': True, 'is_rep': False})
        self.mgr_role.is_area_manager = True
        self.mgr_role.is_rep = False
        self.mgr_role.save()

        # 3. Users:
        # Manager Cairo is assigned to Cairo Main (Governorate)
        self.mgr_cairo = User.objects.create_user(username='mgr_cairo', role=self.mgr_role)
        self.mgr_cairo.assigned_areas.add(self.cairo_main)

        # Manager Giza is assigned to Giza Main
        self.mgr_giza = User.objects.create_user(username='mgr_giza', role=self.mgr_role)
        self.mgr_giza.assigned_areas.add(self.giza_main)

        # Rep Cairo 1 is assigned to Nasr City (subarea in Cairo)
        self.rep_cairo1 = User.objects.create_user(username='rep_cairo1', role=self.rep_role)
        self.rep_cairo1.assigned_areas.add(self.nasr_city)

        # Rep Cairo 2 is assigned to Maadi (subarea in Cairo)
        self.rep_cairo2 = User.objects.create_user(username='rep_cairo2', role=self.rep_role)
        self.rep_cairo2.assigned_areas.add(self.maadi)

        # Rep Giza is assigned to Dokki (subarea in Giza)
        self.rep_giza = User.objects.create_user(username='rep_giza', role=self.rep_role)
        self.rep_giza.assigned_areas.add(self.dokki)

        # 4. Resources:
        self.wh_rep1 = Warehouse.objects.create(
            name='مخزن مندوب نصر سيتي', code='WH-REP-1', assigned_user=self.rep_cairo1,
            area=self.nasr_city, is_rep_warehouse=True
        )
        self.wh_rep_giza = Warehouse.objects.create(
            name='مخزن مندوب الدقي', code='WH-REP-G', assigned_user=self.rep_giza,
            area=self.dokki, is_rep_warehouse=True
        )

        self.vault_rep1 = Vault.objects.create(
            name='خزنة مندوب نصر سيتي', assigned_user=self.rep_cairo1,
            current_balance=Decimal('5000.00'), is_rep_vault=True
        )
        self.vault_rep_giza = Vault.objects.create(
            name='خزنة مندوب الدقي', assigned_user=self.rep_giza,
            current_balance=Decimal('3000.00'), is_rep_vault=True
        )

        # 5. Contacts & Visits:
        self.contact_cairo = Contact.objects.create(name='عيادة النور', area=self.nasr_city)
        self.visit_cairo = Visit.objects.create(
            serial_num=8801, owner=self.rep_cairo1, contact=self.contact_cairo,
            date=timezone.now().date(), status='finished', approval_status='pending'
        )

    def test_manager_eligibility_across_subareas_in_same_main_area(self):
        """Cairo Manager has eligibility over reps in Nasr City and Maadi because both belong to Cairo."""
        self.assertTrue(is_manager_eligible_for_user(self.mgr_cairo, self.rep_cairo1))
        self.assertTrue(is_manager_eligible_for_user(self.mgr_cairo, self.rep_cairo2))

    def test_manager_eligibility_fails_across_different_main_areas(self):
        """Cairo Manager has NO eligibility over Giza rep, and Giza Manager has NO eligibility over Cairo reps."""
        self.assertFalse(is_manager_eligible_for_user(self.mgr_cairo, self.rep_giza))
        self.assertFalse(is_manager_eligible_for_user(self.mgr_giza, self.rep_cairo1))

    def test_anti_self_approval(self):
        """Managers cannot approve their own operations."""
        self.assertFalse(is_manager_eligible_for_user(self.mgr_cairo, self.mgr_cairo))

    def test_manager_managed_representatives_scope(self):
        """get_user_managed_representatives returns all reps belonging to manager's main area."""
        cairo_reps = list(get_user_managed_representatives(self.mgr_cairo).values_list('id', flat=True))
        self.assertIn(self.rep_cairo1.id, cairo_reps)
        self.assertIn(self.rep_cairo2.id, cairo_reps)
        self.assertNotIn(self.rep_giza.id, cairo_reps)

    def test_manager_warehouse_visibility(self):
        """Cairo manager can view warehouses of Cairo reps, but cannot view Giza rep warehouse."""
        scoped_whs = list(get_scoped_queryset(Warehouse.objects.all(), self.mgr_cairo, 'warehouse').values_list('id', flat=True))
        self.assertIn(self.wh_rep1.id, scoped_whs)
        self.assertNotIn(self.wh_rep_giza.id, scoped_whs)

        # Object level access
        self.assertTrue(can_user_access_object(self.mgr_cairo, self.wh_rep1, 'view'))
        self.assertFalse(can_user_access_object(self.mgr_cairo, self.wh_rep_giza, 'view'))

    def test_manager_treasury_visibility_without_transaction_authority(self):
        """Cairo manager can view Cairo rep's vault balance, but CANNOT execute transactions or adjustments."""
        scoped_vaults = list(get_scoped_queryset(Vault.objects.all(), self.mgr_cairo, 'vault').values_list('id', flat=True))
        self.assertIn(self.vault_rep1.id, scoped_vaults)
        self.assertNotIn(self.vault_rep_giza.id, scoped_vaults)

        # Manager has read access
        self.assertTrue(can_user_access_object(self.mgr_cairo, self.vault_rep1, 'view'))

        # Manager has NO transaction authority over rep vault
        self.assertFalse(can_user_access_object(self.mgr_cairo, self.vault_rep1, 'deposit'))
        self.assertFalse(can_user_access_object(self.mgr_cairo, self.vault_rep1, 'withdraw'))
        self.assertFalse(can_user_access_object(self.mgr_cairo, self.vault_rep1, 'transfer'))
        self.assertFalse(can_user_access_object(self.mgr_cairo, self.vault_rep1, 'edit'))
        self.assertFalse(can_user_access_object(self.mgr_cairo, self.vault_rep1, 'delete'))

    def test_visit_approval_by_same_main_area_manager(self):
        """Cairo manager can approve Cairo visit; Giza manager cannot."""
        self.assertTrue(can_user_access_object(self.mgr_cairo, self.visit_cairo, 'approve'))
        self.assertFalse(can_user_access_object(self.mgr_giza, self.visit_cairo, 'approve'))

        # Rep cannot approve own visit
        self.assertFalse(can_user_access_object(self.rep_cairo1, self.visit_cairo, 'approve'))
