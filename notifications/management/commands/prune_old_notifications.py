from django.core.management.base import BaseCommand
from notifications.services import NotificationService


class Command(BaseCommand):
    help = "Prunes notifications older than N days (default: 90 days retention policy)."

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=90, help='Retention window in days (default: 90).')

    def handle(self, *args, **options):
        deleted = NotificationService.prune_old_notifications(days=options['days'])
        self.stdout.write(self.style.SUCCESS(f"Pruned {deleted} notifications older than {options['days']} days."))
