from django.db import migrations


def sync_contact_areas(apps, schema_editor):
    Contact = apps.get_model('contacts', 'Contact')
    ContactAddress = apps.get_model('contacts', 'ContactAddress')

    for contact in Contact.objects.all():
        main_addr = ContactAddress.objects.filter(contact=contact, is_main=True).first()
        if not main_addr:
            main_addr = ContactAddress.objects.filter(contact=contact).first()
        if main_addr:
            fields_to_update = []
            if not contact.area and main_addr.area:
                contact.area = main_addr.area
                fields_to_update.append('area')
            if not contact.brick and main_addr.brick:
                contact.brick = main_addr.brick
                fields_to_update.append('brick')
            if fields_to_update:
                contact.save(update_fields=fields_to_update)


def reverse_sync(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('contacts', '0007_backfill_contact_bricks'),
    ]

    operations = [
        migrations.RunPython(sync_contact_areas, reverse_sync),
    ]

