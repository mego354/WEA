from django.db import migrations


def seed_performance_report_permissions_forward(apps, schema_editor):
    Permission = apps.get_model('auth', 'Permission')
    ContentType = apps.get_model('contenttypes', 'ContentType')
    Role = apps.get_model('accounts', 'Role')

    visit_ct, _ = ContentType.objects.get_or_create(app_label='activities', model='visit')
    settings_ct, _ = ContentType.objects.get_or_create(app_label='master_data', model='companyprofile')

    overview_export, _ = Permission.objects.update_or_create(
        codename='performance:overview/export',
        defaults={
            'name': 'تصدير نظرة عامة على الأداء وتقارير الزيارات إلى Excel',
            'content_type': visit_ct,
        },
    )
    report_groups_manage, _ = Permission.objects.update_or_create(
        codename='settings:reportGroups/manage',
        defaults={
            'name': 'إدارة وتكوين مجموعات أنواع الحسابات في تقارير الأداء والزيارات',
            'content_type': settings_ct,
        },
    )

    for role in Role.objects.filter(name__in=['superadmin', 'SuperAdmin']):
        role.permissions.add(overview_export, report_groups_manage)

    for role in Role.objects.filter(name='manager'):
        role.permissions.add(overview_export)


def seed_performance_report_permissions_backward(apps, schema_editor):
    Permission = apps.get_model('auth', 'Permission')
    Permission.objects.filter(
        codename__in=['performance:overview/export', 'settings:reportGroups/manage']
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0012_update_visit_delete_permission_label'),
        ('master_data', '0013_accounttypereportgroup'),
    ]

    operations = [
        migrations.RunPython(
            seed_performance_report_permissions_forward,
            seed_performance_report_permissions_backward,
        ),
    ]
