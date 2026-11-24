from django.db import migrations, models


CANONICAL_CONTACT_STATUS_MAP = {
    'lead': 'lead',
    'عميل محتمل': 'lead',
    'inactive': 'inactive',
    'غير نشط': 'inactive',
    'معطل': 'inactive',
    'customer': 'customer',
    'active': 'customer',
    'supplier': 'customer',
    'vendor': 'customer',
    'عميل': 'customer',
    'عميل معتمد': 'customer',
    'نشط': 'customer',
    'مورد': 'customer',
}


def normalize_contact_statuses_forward(apps, schema_editor):
    Contact = apps.get_model('contacts', 'Contact')
    distinct_statuses = list(Contact.objects.values_list('status', flat=True).distinct())
    for raw_status in distinct_statuses:
        normalized_key = (raw_status or '').strip().lower()
        target_status = CANONICAL_CONTACT_STATUS_MAP.get(normalized_key, 'customer')
        if raw_status != target_status:
            Contact.objects.filter(status=raw_status).update(status=target_status)


class Migration(migrations.Migration):

    dependencies = [
        ('contacts', '0010_migrate_leads_and_populate_communications'),
    ]

    operations = [
        migrations.RunPython(normalize_contact_statuses_forward, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='contact',
            name='status',
            field=models.CharField(
                choices=[('customer', 'Customer'), ('lead', 'Lead'), ('inactive', 'Inactive')],
                default='customer',
                max_length=20,
                verbose_name='الحالة',
            ),
        ),
    ]
