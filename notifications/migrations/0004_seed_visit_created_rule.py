from django.db import migrations


def seed_visit_created_rule(apps, schema_editor):
    Role = apps.get_model('accounts', 'Role')
    RoleNotificationRule = apps.get_model('notifications', 'RoleNotificationRule')

    for role in Role.objects.all():
        role_name = (getattr(role, 'name', '') or '').lower()
        is_enabled = bool(getattr(role, 'is_super', False) or role_name in ('superadmin', 'manager'))
        RoleNotificationRule.objects.get_or_create(
            role=role,
            event_code='activities.visit_created',
            defaults={
                'is_enabled': is_enabled,
                'delivery_mode': 'all_in_scope',
                'same_area_only': True,
                'include_record_owner': False,
                'include_actor': False,
            },
        )


def unseed_visit_created_rule(apps, schema_editor):
    RoleNotificationRule = apps.get_model('notifications', 'RoleNotificationRule')
    RoleNotificationRule.objects.filter(event_code='activities.visit_created').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0012_update_visit_delete_permission_label'),
        ('notifications', '0003_notification_route_key_and_device_uid'),
    ]

    operations = [
        migrations.RunPython(seed_visit_created_rule, unseed_visit_created_rule),
    ]
