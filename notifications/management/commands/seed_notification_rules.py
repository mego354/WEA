from django.core.management.base import BaseCommand
from notifications.services import NotificationService


class Command(BaseCommand):
    help = "Seeds default RoleNotificationRule rows for all active roles across all 54 notification events."

    def add_arguments(self, parser):
        parser.add_argument('--overwrite', action='store_true', help='Overwrite existing rule settings with defaults.')

    def handle(self, *args, **options):
        count = NotificationService.seed_default_rules(overwrite=options['overwrite'])
        self.stdout.write(self.style.SUCCESS(f"Seeded {count} RoleNotificationRule records."))
