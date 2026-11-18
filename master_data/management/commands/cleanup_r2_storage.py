"""Retry pending storage deletions and optionally sweep orphaned R2/local objects."""

from django.core.management.base import BaseCommand
from master_data.media_service import _execute_physical_delete
from master_data.models import PendingStorageDeletion


class Command(BaseCommand):
    help = "Retries failed physical deletions in PendingStorageDeletion."

    def handle(self, *args, **options):
        pending = list(PendingStorageDeletion.objects.all())
        if not pending:
            self.stdout.write(self.style.SUCCESS("No pending storage deletions."))
            return

        for item in pending:
            _execute_physical_delete(item.storage_key)

        remaining = PendingStorageDeletion.objects.count()
        self.stdout.write(
            self.style.SUCCESS(f"Processed {len(pending)} pending deletions. Remaining: {remaining}.")
        )
