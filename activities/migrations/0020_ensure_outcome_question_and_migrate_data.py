from django.db import migrations


def ensure_outcome_question_and_migrate_plans(apps, schema_editor):
    VisitTemplate = apps.get_model('activities', 'VisitTemplate')
    VisitTemplateQuestion = apps.get_model('activities', 'VisitTemplateQuestion')
    VisitPlan = apps.get_model('activities', 'VisitPlan')
    PlannedVisitDay = apps.get_model('activities', 'PlannedVisitDay')

    # 1. Ensure Question #1 is the outcome question for every template
    for tmpl in VisitTemplate.objects.all():
        # Check if outcome question already exists
        existing_outcome_q = VisitTemplateQuestion.objects.filter(
            template=tmpl,
            text_ar__icontains='نتيجة الزيارة'
        ).first()

        if existing_outcome_q:
            # Shift others if needed so existing_outcome_q can be order 1
            if existing_outcome_q.order != 1:
                # Find if another question has order 1
                q1 = VisitTemplateQuestion.objects.filter(template=tmpl, order=1).exclude(id=existing_outcome_q.id).first()
                if q1:
                    max_order = tmpl.questions.count() + 2
                    q1.order = max_order
                    q1.save(update_fields=['order'])
            existing_outcome_q.order = 1
            existing_outcome_q.stage = 'end_only'
            existing_outcome_q.question_type = 'single_choice'
            existing_outcome_q.options = [
                {'text_ar': 'زيارة ناجحة (Successful)', 'value': 'successful'},
                {'text_ar': 'زيارة غير ناجحة (Unsuccessful)', 'value': 'unsuccessful'}
            ]
            existing_outcome_q.is_required = True
            existing_outcome_q.is_active = True
            existing_outcome_q.save()
        else:
            # Shift all questions in this template by +1
            questions = list(VisitTemplateQuestion.objects.filter(template=tmpl).order_by('-order'))
            for q in questions:
                q.order = q.order + 1
                q.save(update_fields=['order'])

            # Create Question #1
            VisitTemplateQuestion.objects.create(
                template=tmpl,
                order=1,
                text_ar='نتيجة الزيارة',
                text_en='Visit Outcome',
                question_type='single_choice',
                options=[
                    {'text_ar': 'زيارة ناجحة (Successful)', 'value': 'successful'},
                    {'text_ar': 'زيارة غير ناجحة (Unsuccessful)', 'value': 'unsuccessful'}
                ],
                stage='end_only',
                is_required=True,
                is_active=True
            )

    # 2. Migrate existing PlannedVisitDay items to VisitPlan
    for pvd in PlannedVisitDay.objects.all():
        plan_id = f"PLN-{pvd.date.strftime('%Y%m%d')}-{pvd.id}"
        plan, _ = VisitPlan.objects.get_or_create(
            plan_id=plan_id,
            defaults={
                'assignee': pvd.assignee,
                'date': pvd.date,
                'comment': '',
                'approval_status': 'approved' if pvd.status == 'completed' else 'pending',
                'created_by': pvd.created_by,
            }
        )
        for item in pvd.planned_items.all():
            if not item.plan_id:
                item.plan = plan
                item.save(update_fields=['plan'])
            if item.visit and not item.visit.plan_id:
                item.visit.plan = plan
                item.visit.save(update_fields=['plan'])


def reverse_migration(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('activities', '0019_add_visit_plan_and_fields'),
    ]

    operations = [
        migrations.RunPython(
            ensure_outcome_question_and_migrate_plans,
            reverse_migration
        ),
    ]
