from django.db import migrations


def normalize_dirty_account_types_forward(apps, schema_editor):
    Contact = apps.get_model('contacts', 'Contact')
    Contact.objects.filter(account_type__iexact='nan').update(account_type='')
    Contact.objects.filter(account_type='عيادة').update(account_type='Clinic')


def normalize_dirty_account_types_backward(apps, schema_editor):
    # Deliberately non-destructive: valid canonical 'Clinic' / '' records must not be reverted to dirty values.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('contacts', '0012_contact_contact_cust_stat_atype_idx'),
    ]

    operations = [
        migrations.RunPython(
            normalize_dirty_account_types_forward,
            normalize_dirty_account_types_backward,
        ),
    ]
