from django.db import migrations


def deactivate_duplicate_question(apps, schema_editor):
    VisitTemplateQuestion = apps.get_model('activities', 'VisitTemplateQuestion')
    # Safely deactivate any duplicate outcome question matching 'هل كان يوم ناجح'
    VisitTemplateQuestion.objects.filter(
        text_ar__icontains='هل كان يوم ناجح'
    ).update(is_active=False)


def reverse_deactivate_duplicate_question(apps, schema_editor):
    VisitTemplateQuestion = apps.get_model('activities', 'VisitTemplateQuestion')
    VisitTemplateQuestion.objects.filter(
        text_ar__icontains='هل كان يوم ناجح'
    ).update(is_active=True)


class Migration(migrations.Migration):

    dependencies = [
        ('activities', '0006_visit_bypass_reason_visit_bypassed_at_and_more'),
    ]

    operations = [
        migrations.RunPython(
            deactivate_duplicate_question,
            reverse_deactivate_duplicate_question
        ),
    ]
