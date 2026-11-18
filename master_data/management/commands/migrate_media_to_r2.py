"""Safely migrate existing local media files to Cloudflare R2 when R2_ENABLED=True."""

import os
from django.conf import settings
from django.core.files.base import File
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand

from accounts.models import User
from catalog.models import Product
from contacts.models import ContactAttachment
from master_data.models import CompanyProfile, ERPAttachment
from purchases.models import PurchaseOrderAttachment


class Command(BaseCommand):
    help = "Migrates existing local MEDIA_ROOT files to configured Cloudflare R2 storage."

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Preview files without uploading.')

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        if not getattr(settings, 'R2_ENABLED', False) and not dry_run:
            self.stderr.write(self.style.ERROR("R2_ENABLED is False. Set CLOUDFLARE_R2_* env vars or use --dry-run."))
            return

        media_root = str(settings.MEDIA_ROOT)
        keys = set()
        for qs, attr in [
            (CompanyProfile.objects.exclude(logo=''), 'logo'),
            (Product.objects.exclude(thumbnail=''), 'thumbnail'),
            (User.objects.exclude(avatar=''), 'avatar'),
            (ContactAttachment.objects.all(), 'file'),
            (PurchaseOrderAttachment.objects.all(), 'file'),
            (ERPAttachment.objects.all(), 'file'),
        ]:
            for obj in qs:
                f = getattr(obj, attr, None)
                if f and getattr(f, 'name', ''):
                    keys.add(f.name)

        uploaded = 0
        skipped = 0
        for key in sorted(keys):
            local_path = os.path.join(media_root, key.replace('/', os.sep))
            if not os.path.exists(local_path):
                skipped += 1
                continue
            if dry_run:
                self.stdout.write(f"[DRY-RUN] Would upload: {key}")
                uploaded += 1
                continue
            if not default_storage.exists(key):
                with open(local_path, 'rb') as fp:
                    default_storage.save(key, File(fp, name=key))
                uploaded += 1
            else:
                skipped += 1

        self.stdout.write(self.style.SUCCESS(f"Done. Uploaded: {uploaded}, Skipped: {skipped}."))
