from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from accounts.services import is_representative, ensure_representative_resources

User = get_user_model()


class Command(BaseCommand):
    help = "Idempotently backfill default Warehouses and Treasuries (Vaults) for existing representatives."

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Preview representatives missing warehouses/treasuries without making database modifications.'
        )
        parser.add_argument(
            '--user-id',
            type=int,
            help='Target a specific user ID for backfill.'
        )

    def handle(self, *args, **options):
        import sys
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8')

        dry_run = options['dry_run']
        user_id = options.get('user_id')

        self.stdout.write(self.style.NOTICE("=" * 65))
        self.stdout.write(self.style.NOTICE(f"REPRESENTATIVE RESOURCE BACKFILL {'(DRY RUN PREVIEW)' if dry_run else '(ACTIVE EXECUTION)'}"))
        self.stdout.write(self.style.NOTICE("=" * 65))

        qs = User.objects.filter(is_active=True).select_related('role').prefetch_related('assigned_areas')
        if user_id:
            qs = qs.filter(id=user_id)

        rep_users = [u for u in qs if is_representative(u)]

        self.stdout.write(f"Total active users evaluated: {qs.count()}")
        self.stdout.write(f"Representatives identified: {len(rep_users)}")
        self.stdout.write("-" * 65)

        missing_wh = 0
        missing_vault = 0
        created_wh_count = 0
        created_vault_count = 0

        for rep in rep_users:
            current_wh = rep.get_default_warehouse()
            current_vault = rep.get_default_treasury()

            wh_status = f"Exists: {current_wh.name} ({current_wh.code})" if current_wh else self.style.WARNING("MISSING")
            vault_status = f"Exists: {current_vault.name} (Bal: {current_vault.current_balance})" if current_vault else self.style.WARNING("MISSING")

            needs_wh = current_wh is None
            needs_vault = current_vault is None

            if needs_wh:
                missing_wh += 1
            if needs_vault:
                missing_vault += 1

            self.stdout.write(f"Rep #{rep.id} [{rep.username}] ({rep.name or 'No name'}):")
            self.stdout.write(f"  - Warehouse: {wh_status}")
            self.stdout.write(f"  - Treasury:  {vault_status}")

            if not dry_run and (needs_wh or needs_vault):
                wh, vault, c_wh, c_v = ensure_representative_resources(rep)
                if c_wh:
                    created_wh_count += 1
                    self.stdout.write(self.style.SUCCESS(f"    [CREATED WH] -> {wh.name} ({wh.code})"))
                if c_v:
                    created_vault_count += 1
                    self.stdout.write(self.style.SUCCESS(f"    [CREATED VAULT] -> {vault.name}"))

        self.stdout.write("-" * 65)
        self.stdout.write(f"Summary: {missing_wh} representatives lack warehouse, {missing_vault} lack treasury.")
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN completed. No database changes were applied."))
        else:
            self.stdout.write(self.style.SUCCESS(f"BACKFILL completed. Created {created_wh_count} warehouses, {created_vault_count} treasuries."))
