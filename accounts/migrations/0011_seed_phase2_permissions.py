from django.db import migrations
from django.core.management import call_command


def forward_seed_phase2_permissions(apps, schema_editor):
    call_command('setup_permissions', no_audit=True)


def reverse_seed_phase2_permissions(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0010_seed_role_module_scopes'),
        ('activities', '0018_approvalauditlog_payment_request_and_more'),
        ('purchases', '0006_purchasereturnorder_approved_at_and_more'),
        ('sales', '0006_salesreturnorder_approved_at_and_more'),
        ('treasury', '0006_vendorpaymentrequest'),
    ]

    operations = [
        migrations.RunPython(forward_seed_phase2_permissions, reverse_seed_phase2_permissions),
    ]
