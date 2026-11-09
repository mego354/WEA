from django.db import migrations


def backfill_bricks(apps, schema_editor):
    Contact = apps.get_model('contacts', 'Contact')
    ContactAddress = apps.get_model('contacts', 'ContactAddress')
    Area = apps.get_model('master_data', 'Area')

    # 1. Backfill Contact records
    for contact in Contact.objects.select_related('area', 'area__parent').all():
        updated = False
        if contact.area and contact.area.parent_id:
            # Current area is actually a subarea/brick
            contact.brick = contact.area
            contact.area = contact.area.parent
            updated = True
        if updated:
            contact.save(update_fields=['area', 'brick'])

    # 2. Backfill ContactAddress records
    for addr in ContactAddress.objects.select_related('area', 'area__parent').all():
        updated = False
        if addr.area and addr.area.parent_id:
            addr.brick = addr.area
            addr.area = addr.area.parent
            updated = True
        elif addr.sub_area and addr.area and not addr.brick:
            matched_brick = Area.objects.filter(parent_id=addr.area_id, name__iexact=addr.sub_area.strip()).first()
            if matched_brick:
                addr.brick = matched_brick
                updated = True
        if updated:
            addr.save(update_fields=['area', 'brick'])


def reverse_backfill(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('contacts', '0006_contact_brick_contactaddress_brick_and_more'),
        ('master_data', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(backfill_bricks, reverse_backfill),
    ]

