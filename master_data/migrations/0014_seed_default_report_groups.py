from django.db import migrations


def seed_default_report_groups_forward(apps, schema_editor):
    AccountTypeReportGroup = apps.get_model('master_data', 'AccountTypeReportGroup')
    if AccountTypeReportGroup.objects.exists():
        return

    AccountTypeReportGroup.objects.create(
        name='الصيدليات',
        code='pharmacies',
        account_types=['Pharmacy'],
        display_order=1,
        icon='local_pharmacy',
        is_active=True,
    )
    AccountTypeReportGroup.objects.create(
        name='المنشآت الطبية',
        code='medical-facilities',
        account_types=['Clinic', 'Polyclinic'],
        display_order=2,
        icon='stethoscope',
        is_active=True,
    )


def seed_default_report_groups_backward(apps, schema_editor):
    AccountTypeReportGroup = apps.get_model('master_data', 'AccountTypeReportGroup')
    AccountTypeReportGroup.objects.filter(code__in=['pharmacies', 'medical-facilities']).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('master_data', '0013_accounttypereportgroup'),
    ]

    operations = [
        migrations.RunPython(
            seed_default_report_groups_forward,
            seed_default_report_groups_backward,
        ),
    ]
