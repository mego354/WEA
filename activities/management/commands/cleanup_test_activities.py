from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.services import AuditLogService
from activities.models import (
    Agreement,
    ApprovalAuditLog,
    PlannedVisitDay,
    PlannedVisitItem,
    Visit,
    VisitExpense,
    VisitPlan,
    VisitSampleItem,
)
from master_data.models import ERPAttachment
from reports.models import CoachingEvaluation


class Command(BaseCommand):
    help = (
        "Safely clean up explicitly approved test Agreement, Visit, and PlannedVisitDay records. "
        "Runs in DRY-RUN mode by default; pass --execute to apply deletions."
    )

    def add_arguments(self, parser):
        parser.add_argument("--agreement-ids", nargs="*", type=int, default=[], help="Explicit Agreement PKs to delete.")
        parser.add_argument("--visit-ids", nargs="*", type=int, default=[], help="Explicit Visit PKs to delete.")
        parser.add_argument("--planned-day-ids", nargs="*", type=int, default=[], help="Explicit PlannedVisitDay PKs to delete.")
        parser.add_argument("--execute", action="store_true", help="Actually execute deletions (default is dry-run).")

    def handle(self, *args, **options):
        agr_ids = options["agreement_ids"]
        vis_ids = options["visit_ids"]
        day_ids = options["planned_day_ids"]
        execute = options["execute"]

        if not (agr_ids or vis_ids or day_ids):
            self.stdout.write(self.style.WARNING("No IDs supplied. Nothing to inspect or delete."))
            return

        agreements = list(Agreement.objects.filter(pk__in=agr_ids))
        visits = list(Visit.objects.filter(pk__in=vis_ids))
        days = list(PlannedVisitDay.objects.filter(pk__in=day_ids))

        matched_agr_ids = [a.id for a in agreements]
        matched_vis_ids = [v.id for v in visits]
        matched_day_ids = [d.id for d in days]

        agr_logs = ApprovalAuditLog.objects.filter(agreement_id__in=matched_agr_ids).count()
        vis_logs = ApprovalAuditLog.objects.filter(visit_id__in=matched_vis_ids).count()
        linked_items = PlannedVisitItem.objects.filter(visit_id__in=matched_vis_ids).count()
        day_items_qs = PlannedVisitItem.objects.filter(plan_day_id__in=matched_day_ids)
        day_items = day_items_qs.count()
        sample_items = VisitSampleItem.objects.filter(visit_id__in=matched_vis_ids).count()
        visit_expenses = VisitExpense.objects.filter(visit_id__in=matched_vis_ids).count()
        coaching_evals = CoachingEvaluation.objects.filter(visit_id__in=matched_vis_ids).count()
        related_plan_ids = list(
            PlannedVisitItem.objects.filter(
                plan__isnull=False,
            ).filter(
                plan_day_id__in=matched_day_ids
            ).values_list("plan_id", flat=True).distinct()
        )
        related_plans = VisitPlan.objects.filter(id__in=related_plan_ids).count()

        ct_agr = ContentType.objects.get_for_model(Agreement)
        ct_vis = ContentType.objects.get_for_model(Visit)
        att_agr = ERPAttachment.objects.filter(content_type=ct_agr, object_id__in=matched_agr_ids).count()
        att_vis = ERPAttachment.objects.filter(content_type=ct_vis, object_id__in=matched_vis_ids).count()

        self.stdout.write("=== CLEANUP SUMMARY ===")
        self.stdout.write(f"  Agreements: {len(agreements)} (ApprovalAuditLog: {agr_logs}, Attachments: {att_agr})")
        self.stdout.write(
            f"  Visits: {len(visits)} (ApprovalAuditLog: {vis_logs}, Linked PlannedVisitItems: {linked_items}, "
            f"Samples: {sample_items}, Expenses: {visit_expenses}, CoachingEvaluations: {coaching_evals}, Attachments: {att_vis})"
        )
        self.stdout.write(
            f"  PlannedVisitDays: {len(days)} (PlannedVisitItems: {day_items}, Linked VisitPlans: {related_plans})"
        )
        self.stdout.write("  Note: Historical SecurityAuditLog entries remain permanently preserved.")

        if not execute:
            self.stdout.write(self.style.SUCCESS("DRY-RUN complete. No database records were modified. Pass --execute to apply."))
            return

        with transaction.atomic():
            if matched_agr_ids:
                ERPAttachment.objects.filter(content_type=ct_agr, object_id__in=matched_agr_ids).delete()
                Agreement.objects.filter(pk__in=matched_agr_ids).delete()
            if matched_vis_ids:
                ERPAttachment.objects.filter(content_type=ct_vis, object_id__in=matched_vis_ids).delete()
                if not matched_day_ids:
                    PlannedVisitItem.objects.filter(visit_id__in=matched_vis_ids).update(visit=None, is_executed=False)
                Visit.objects.filter(pk__in=matched_vis_ids).delete()
            if matched_day_ids:
                PlannedVisitDay.objects.filter(pk__in=matched_day_ids).delete()

            AuditLogService.log(
                action_type="TEST_DATA_CLEANUP",
                module="activities",
                description=(
                    f"Approved test data cleanup: agreements={matched_agr_ids}, visits={matched_vis_ids}, planned_days={matched_day_ids}"
                ),
            )

        self.stdout.write(self.style.SUCCESS("Cleanup executed successfully inside atomic transaction."))
