from django.db import migrations, models
from django.db.models import Count, F


def reconcile_duplicate_open_visits(VisitModel, ApprovalAuditLogModel, SecurityAuditLogModel=None):
    """
    Generic, idempotent reconciliation for any owner holding > 1 open visit
    (status='started', ended_at IS NULL):
    - Keeps the newest open visit (ordered by started_at DESC NULLS LAST, pk DESC).
    - Marks all older duplicate open visits as status='cancelled' without mutating ended_at.
    - Writes ApprovalAuditLog (and optional SecurityAuditLog) reconciliation records.
    """
    dup_owner_ids = list(
        VisitModel.objects.filter(status='started', ended_at__isnull=True)
        .values('owner_id')
        .annotate(open_cnt=Count('id'))
        .filter(open_cnt__gt=1)
        .values_list('owner_id', flat=True)
    )
    cancelled_count = 0
    for owner_id in dup_owner_ids:
        open_visits = list(
            VisitModel.objects.filter(
                owner_id=owner_id, status='started', ended_at__isnull=True
            ).order_by(F('started_at').desc(nulls_last=True), '-pk')
        )
        if len(open_visits) <= 1:
            continue
        newest = open_visits[0]
        for older in open_visits[1:]:
            prev_started = older.started_at.isoformat() if older.started_at else None
            older.status = 'cancelled'
            older.save(update_fields=['status'])
            reason = (
                f"إلغاء تلقائي لزيارة مفتوحة مكررة قديمة مع الإبقاء على الزيارة الأحدث #{newest.serial_num}"
            )
            ApprovalAuditLogModel.objects.create(
                record_type='visit',
                visit_id=older.pk,
                action='cancelled',
                actor_id=None,
                status_before='started',
                status_after='cancelled',
                reason=reason,
            )
            if SecurityAuditLogModel is not None:
                SecurityAuditLogModel.objects.create(
                    action_type='VISIT_DUPLICATE_OPEN_CANCELLED',
                    module='visits',
                    actor=None,
                    record_id=str(older.pk),
                    record_name=f"Visit #{older.serial_num}",
                    description=reason,
                    previous_values={'status': 'started', 'ended_at': None, 'started_at': prev_started},
                    new_values={'status': 'cancelled', 'ended_at': None, 'kept_visit_id': newest.pk},
                    status='SUCCESS',
                    reason=reason,
                )
            cancelled_count += 1
    return cancelled_count


def forwards_reconcile_open_visits(apps, schema_editor):
    Visit = apps.get_model('activities', 'Visit')
    ApprovalAuditLog = apps.get_model('activities', 'ApprovalAuditLog')
    try:
        SecurityAuditLog = apps.get_model('accounts', 'SecurityAuditLog')
    except LookupError:
        SecurityAuditLog = None
    reconcile_duplicate_open_visits(Visit, ApprovalAuditLog, SecurityAuditLog)


class Migration(migrations.Migration):

    dependencies = [
        ('activities', '0024_visit_creator_edit_tracking_and_suggested_products_qtype'),
    ]

    operations = [
        migrations.RunPython(forwards_reconcile_open_visits, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='visit',
            constraint=models.UniqueConstraint(
                condition=models.Q(('ended_at__isnull', True), ('status', 'started')),
                fields=('owner',),
                name='unique_open_visit_per_owner',
            ),
        ),
    ]
