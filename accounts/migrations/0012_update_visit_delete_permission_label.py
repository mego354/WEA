from django.db import migrations


def update_visit_delete_label_forward(apps, schema_editor):
    Permission = apps.get_model('auth', 'Permission')
    Permission.objects.filter(codename='activities:visits/delete').update(name='حذف الزيارات')


def update_visit_delete_label_backward(apps, schema_editor):
    Permission = apps.get_model('auth', 'Permission')
    Permission.objects.filter(codename='activities:visits/delete').update(name='حذف الزيارات غير المنتهية')


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0011_seed_phase2_permissions'),
    ]

    operations = [
        migrations.RunPython(update_visit_delete_label_forward, update_visit_delete_label_backward),
    ]
