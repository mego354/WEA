import io
import json
import sys

from django.core.management.base import BaseCommand

from master_data.wea_integration_service import WeaDataIntegrationService

if sys.platform == 'win32':
    if hasattr(sys.stdout, 'buffer'):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    if hasattr(sys.stderr, 'buffer'):
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')


class Command(BaseCommand):
    help = "Idempotently integrates all WEA Pharma Excel workbooks into the existing ERP database."

    def add_arguments(self, parser):
        parser.add_argument('--wea-dir', type=str, default='wea data', help='Directory containing WEA Excel files')
        parser.add_argument('--data-dir', type=str, default='data_folder', help='Directory containing users.xlsx')
        parser.add_argument('--dry-run', action='store_true', help='Run full import & reconciliation then roll back')

    def handle(self, *args, **options):
        svc = WeaDataIntegrationService(
            wea_dir=options['wea_dir'],
            data_dir=options['data_dir'],
        )
        mode = 'DRY RUN (ROLLED BACK)' if options['dry_run'] else 'LIVE COMMIT'
        self.stdout.write(self.style.MIGRATE_HEADING(f"=== WEA ERP DATA INTEGRATION ({mode}) ==="))

        result = svc.run(dry_run=options['dry_run'])

        self.stdout.write("\n--- IMPORT STATISTICS ---")
        for k, v in sorted(result['stats'].items()):
            self.stdout.write(f"  {k:<42}: {v:,}")

        self.stdout.write("\n--- RECONCILIATION SUMMARY ---")
        all_ok = True
        for k, v in result['reconciliation'].items():
            ok = v['match']
            if not ok:
                all_ok = False
            style = self.style.SUCCESS if ok else self.style.ERROR
            self.stdout.write(style(f"  {k:<25}: {v}"))

        if result['discrepancies']:
            self.stdout.write(self.style.WARNING("\n--- DOCUMENTED DISCREPANCIES / APPROVED EXCEPTIONS ---"))
            for d in result['discrepancies']:
                self.stdout.write(f"  * {d}")

        if result['warnings']:
            self.stdout.write(self.style.WARNING("\n--- WARNINGS ---"))
            for w in result['warnings']:
                self.stdout.write(f"  ! {w}")

        if all_ok:
            self.stdout.write(self.style.SUCCESS("\n[OK] ALL 9 FINANCIAL & INVENTORY RECONCILIATION CHECKS MATCHED 100%!"))
        else:
            self.stdout.write(self.style.ERROR("\n[FAIL] ONE OR MORE RECONCILIATION CHECKS FAILED!"))
