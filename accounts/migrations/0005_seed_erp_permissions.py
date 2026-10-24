from django.db import migrations
from django.core.management import call_command


def forward_seed_permissions(apps, schema_editor):
    call_command('setup_permissions')


def reverse_seed_permissions(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0004_securityauditlog'),
        ('activities', '0007_deactivate_duplicate_outcome_question'),
        ('catalog', '0003_productvolumediscounttier_productpricelist'),
        ('contacts', '0003_contact_assigned_team_contact_parent_org_and_more'),
        ('inventory', '0001_initial'),
        ('master_data', '0003_agreementtype_approvalrequesttype_and_more'),
        ('purchases', '0003_purchasereturnorder_purchaseorder_parent_order_and_more'),
        ('sales', '0002_salesreturnorder_salesreturnorderitem'),
        ('treasury', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(forward_seed_permissions, reverse_seed_permissions),
    ]
