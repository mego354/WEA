import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from decimal import Decimal
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.core.management import call_command
import io

from accounts.models import Role, UserSettings
from accounts.services import (
    ensure_representative_resources, is_representative,
    get_representative_warehouse, get_representative_treasury
)
from master_data.models import Area
from inventory.models import Warehouse
from treasury.models import Vault

User = get_user_model()


class RepresentativeProvisioningTests(TestCase):
    """
    Automated test suite verifying:
    1. Automatic warehouse and treasury provisioning for representatives
    2. Settings toggle controls (auto_create_rep_warehouse / auto_create_rep_treasury)
    3. Idempotency upon repeated saves and profile edits
    4. Safe, non-destructive backfill command preserving existing balances
    """

    def setUp(self):
        # Create Main Area (Governorate) & Subarea
        self.cairo_main = Area.objects.create(code='CAI', name='القاهرة', area_type='governorate', parent=None)
        self.nasr_city = Area.objects.create(code='CAI-NC', name='مدينة نصر', area_type='subarea', parent=self.cairo_main)

        # Get or create Roles
        self.rep_role, _ = Role.objects.get_or_create(
            name='MedicalRep', defaults={'display_name': 'مندوب دعاية طبية', 'is_rep': True, 'is_sales_team': True}
        )
        self.rep_role.is_rep = True
        self.rep_role.is_sales_team = True
        self.rep_role.save()

        self.direct_sales_role, _ = Role.objects.get_or_create(
            name='DirectSalesRep', defaults={'display_name': 'مندوب مبيعات مباشر', 'is_rep': True, 'is_sales_team': True}
        )
        self.direct_sales_role.is_rep = True
        self.direct_sales_role.is_sales_team = True
        self.direct_sales_role.save()

        self.mgr_role, _ = Role.objects.get_or_create(
            name='AreaManager', defaults={'display_name': 'مدير منطقة', 'is_area_manager': True, 'is_sales_team': True, 'is_rep': False}
        )
        self.mgr_role.is_area_manager = True
        self.mgr_role.is_sales_team = True
        self.mgr_role.is_rep = False
        self.mgr_role.save()

        # Ensure settings are enabled by default
        self.settings = UserSettings.get_settings()
        self.settings.auto_create_rep_warehouse = True
        self.settings.auto_create_rep_treasury = True
        self.settings.save()

    def test_rep_role_identification(self):
        """Test is_representative accurately detects representatives and excludes managers."""
        rep = User.objects.create_user(username='test_rep1', role=self.rep_role)
        mgr = User.objects.create_user(username='test_mgr1', role=self.mgr_role)

        self.assertTrue(is_representative(rep))
        self.assertFalse(is_representative(mgr))

    def test_automatic_warehouse_and_treasury_creation(self):
        """Creating a representative automatically creates dedicated warehouse and treasury."""
        rep = User.objects.create_user(
            username='rep_auto1',
            first_name='أحمد',
            last_name='علي',
            role=self.rep_role
        )
        rep.assigned_areas.add(self.nasr_city)

        # Retrieve designated resources
        wh = get_representative_warehouse(rep)
        vault = get_representative_treasury(rep)

        self.assertIsNotNone(wh)
        self.assertIsNotNone(vault)
        self.assertTrue(wh.is_rep_warehouse)
        self.assertEqual(wh.assigned_user, rep)
        self.assertEqual(wh.area, self.nasr_city)
        self.assertEqual(wh.main_area, self.cairo_main)
        self.assertTrue(vault.is_rep_vault)
        self.assertEqual(vault.assigned_user, rep)

    def test_settings_toggle_disables_creation(self):
        """Disabling settings prevents automatic creation for new representatives."""
        self.settings.auto_create_rep_warehouse = False
        self.settings.auto_create_rep_treasury = False
        self.settings.save()

        rep = User.objects.create_user(
            username='rep_manual1',
            role=self.direct_sales_role
        )

        wh = get_representative_warehouse(rep)
        vault = get_representative_treasury(rep)

        self.assertIsNone(wh)
        self.assertIsNone(vault)

    def test_repeated_saves_do_not_create_duplicates(self):
        """Repeated saves and profile updates do NOT duplicate warehouse or treasury."""
        rep = User.objects.create_user(
            username='rep_idemp1',
            role=self.rep_role
        )

        wh1 = get_representative_warehouse(rep)
        v1 = get_representative_treasury(rep)

        # Profile edits
        rep.first_name = 'محمود'
        rep.email = 'm@example.com'
        rep.save()

        # Re-run explicit ensure_representative_resources
        wh2, v2, created_wh, created_v = ensure_representative_resources(rep)

        self.assertFalse(created_wh)
        self.assertFalse(created_v)
        self.assertEqual(wh1.pk, wh2.pk)
        self.assertEqual(v1.pk, v2.pk)
        self.assertEqual(Warehouse.objects.filter(assigned_user=rep).count(), 1)
        self.assertEqual(Vault.objects.filter(assigned_user=rep).count(), 1)

    def test_backfill_management_command_idempotence(self):
        """Backfill command safely provisions missing resources and preserves existing balances."""
        self.settings.auto_create_rep_warehouse = False
        self.settings.auto_create_rep_treasury = False
        self.settings.save()

        # Create rep without resources
        rep = User.objects.create_user(
            username='rep_backfill1',
            role=self.rep_role
        )
        rep.assigned_areas.add(self.nasr_city)

        # Pre-create a vault with a custom balance to test preservation
        existing_vault = Vault.objects.create(
            name="خزنة عهدة قديمة",
            assigned_user=rep,
            current_balance=Decimal('7500.00'),
            is_rep_vault=True
        )

        # Re-enable settings
        self.settings.auto_create_rep_warehouse = True
        self.settings.auto_create_rep_treasury = True
        self.settings.save()

        # Run backfill
        out = io.StringIO()
        call_command('backfill_representative_resources', stdout=out)

        # Refresh
        existing_vault.refresh_from_db()
        self.assertEqual(existing_vault.current_balance, Decimal('7500.00'))

        # Warehouse should have been created
        wh = get_representative_warehouse(rep)
        self.assertIsNotNone(wh)
        self.assertEqual(wh.assigned_user, rep)

        # Re-run backfill to verify 0 new created
        out2 = io.StringIO()
        call_command('backfill_representative_resources', stdout=out2)
        output_str = out2.getvalue()
        self.assertIn("Created 0 warehouses, 0 treasuries", output_str)
