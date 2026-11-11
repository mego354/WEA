from django.db import migrations


def forwards_migrate_leads_and_communications(apps, schema_editor):
    Contact = apps.get_model('contacts', 'Contact')
    ContactCommunicationMethod = apps.get_model('contacts', 'ContactCommunicationMethod')

    # 1. Update all existing leads to customer
    leads = Contact.objects.filter(status='lead')
    leads.update(status='customer', is_customer=True)

    # Also ensure any contacts with is_customer=False are marked is_customer=True
    Contact.objects.filter(is_customer=False).update(is_customer=True)

    # 2. Populate ContactCommunicationMethod from existing scalar fields
    comms_to_create = []
    # Process in batches
    for c in Contact.objects.all().iterator(chunk_size=1000):
        if c.mobile:
            comms_to_create.append(
                ContactCommunicationMethod(
                    contact=c,
                    method_type='mobile',
                    value=c.mobile,
                    label='الموبايل الرئيسي',
                    is_primary=True
                )
            )
        if c.phone:
            comms_to_create.append(
                ContactCommunicationMethod(
                    contact=c,
                    method_type='phone',
                    value=c.phone,
                    label='الهاتف الأرضي',
                    is_primary=True
                )
            )
        if c.email:
            comms_to_create.append(
                ContactCommunicationMethod(
                    contact=c,
                    method_type='email',
                    value=c.email,
                    label='البريد الإلكتروني',
                    is_primary=True
                )
            )
        if c.website:
            comms_to_create.append(
                ContactCommunicationMethod(
                    contact=c,
                    method_type='website',
                    value=c.website,
                    label='الموقع الإلكتروني',
                    is_primary=True
                )
            )
        if len(comms_to_create) >= 2000:
            ContactCommunicationMethod.objects.bulk_create(comms_to_create)
            comms_to_create = []

    if comms_to_create:
        ContactCommunicationMethod.objects.bulk_create(comms_to_create)

    # 3. Provision CustomerAccount records for any customers that don't have one
    try:
        CustomerAccount = apps.get_model('sales', 'CustomerAccount')
        existing_acc_contact_ids = set(CustomerAccount.objects.values_list('customer_id', flat=True))
        missing_accounts = []
        for c in Contact.objects.filter(is_customer=True).iterator(chunk_size=1000):
            if c.id not in existing_acc_contact_ids:
                missing_accounts.append(
                    CustomerAccount(
                        customer=c,
                        account_number=f"ACC-{c.serial_num:06d}" if c.serial_num else f"ACC-CUST-{c.id:06d}",
                        current_balance=0.00,
                        credit_limit=c.credit_limit or 0.00,
                        is_active=True
                    )
                )
                if len(missing_accounts) >= 2000:
                    CustomerAccount.objects.bulk_create(missing_accounts)
                    missing_accounts = []
        if missing_accounts:
            CustomerAccount.objects.bulk_create(missing_accounts)
    except Exception:
        pass


def backwards_noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('contacts', '0009_alter_contact_is_customer_alter_contact_status_and_more'),
        ('sales', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(forwards_migrate_leads_and_communications, backwards_noop),
    ]

