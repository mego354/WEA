from django.db import migrations


def forwards_consolidate_areas(apps, schema_editor):
    Area = apps.get_model('master_data', 'Area')
    Contact = apps.get_model('contacts', 'Contact')
    ContactAddress = apps.get_model('contacts', 'ContactAddress')
    
    # Use raw connection / schema editor for through table accounts_user_assigned_areas
    connection = schema_editor.connection

    # 1. CONSOLIDATE CAIRO (560 -> 326)
    cairo_canonical = Area.objects.filter(pk=326).first()
    cairo_duplicate = Area.objects.filter(pk=560).first()

    if cairo_canonical and cairo_duplicate:
        # Merge Maadi (562 under 560 -> 371 under 326)
        maadi_canonical = Area.objects.filter(pk=371).first()
        if maadi_canonical:
            Contact.objects.filter(brick_id=562).update(brick_id=371)
            ContactAddress.objects.filter(brick_id=562).update(brick_id=371)

        # Re-parent all other child bricks under 560 to 326
        Area.objects.filter(parent_id=560).exclude(pk=562).update(parent=cairo_canonical)

        # Remap contacts and addresses from area 560 -> 326
        Contact.objects.filter(area_id=560).update(area=cairo_canonical)
        ContactAddress.objects.filter(area_id=560).update(area=cairo_canonical)

        # Remap user assigned areas through table
        with connection.cursor() as cursor:
            # Delete assignments to 560 where user is already assigned to 326
            cursor.execute("""
                DELETE FROM accounts_user_assigned_areas
                WHERE area_id = 560 AND user_id IN (
                    SELECT user_id FROM accounts_user_assigned_areas WHERE area_id = 326
                )
            """)
            # Update any remaining assignments
            cursor.execute("UPDATE accounts_user_assigned_areas SET area_id = 326 WHERE area_id = 560")

        # Delete merged Maadi duplicate 562 if no references
        Area.objects.filter(pk=562).delete()
        # Delete duplicate Cairo 560
        Area.objects.filter(pk=560).delete()

    # 2. CONSOLIDATE GIZA (563 -> 315)
    giza_canonical = Area.objects.filter(pk=315).first()
    giza_duplicate = Area.objects.filter(pk=563).first()

    if giza_canonical and giza_duplicate:
        # Merge Mohandessin (565 under 563 -> 423 under 315)
        mohandessin_canonical = Area.objects.filter(pk=423).first()
        if mohandessin_canonical:
            Contact.objects.filter(brick_id=565).update(brick_id=423)
            ContactAddress.objects.filter(brick_id=565).update(brick_id=423)

        # Merge Dokki (564 under 563 -> 454 under 315) if exists
        dokki_canonical = Area.objects.filter(pk=454).first()
        if dokki_canonical:
            Contact.objects.filter(brick_id=564).update(brick_id=454)
            ContactAddress.objects.filter(brick_id=564).update(brick_id=454)
            Area.objects.filter(pk=564).delete()

        # Re-parent all other child bricks under 563 to 315
        Area.objects.filter(parent_id=563).exclude(pk=565).update(parent=giza_canonical)

        # Remap contacts and addresses from area 563 -> 315
        Contact.objects.filter(area_id=563).update(area=giza_canonical)
        ContactAddress.objects.filter(area_id=563).update(area=giza_canonical)

        # Remap user assigned areas through table
        with connection.cursor() as cursor:
            cursor.execute("""
                DELETE FROM accounts_user_assigned_areas
                WHERE area_id = 563 AND user_id IN (
                    SELECT user_id FROM accounts_user_assigned_areas WHERE area_id = 315
                )
            """)
            cursor.execute("UPDATE accounts_user_assigned_areas SET area_id = 315 WHERE area_id = 563")

        # Delete merged Mohandessin duplicate 565
        Area.objects.filter(pk=565).delete()
        # Delete duplicate Giza 563
        Area.objects.filter(pk=563).delete()

    # 3. CONSOLIDATE ALEXANDRIA (566 -> 541)
    alex_canonical = Area.objects.filter(pk=541).first()
    alex_duplicate = Area.objects.filter(pk=566).first()

    if alex_canonical and alex_duplicate:
        # Re-parent Smouha (567) to 541
        Area.objects.filter(parent_id=566).update(parent=alex_canonical)
        Contact.objects.filter(area_id=566).update(area=alex_canonical)
        ContactAddress.objects.filter(area_id=566).update(area=alex_canonical)
        with connection.cursor() as cursor:
            cursor.execute("""
                DELETE FROM accounts_user_assigned_areas
                WHERE area_id = 566 AND user_id IN (
                    SELECT user_id FROM accounts_user_assigned_areas WHERE area_id = 541
                )
            """)
            cursor.execute("UPDATE accounts_user_assigned_areas SET area_id = 541 WHERE area_id = 566")
        Area.objects.filter(pk=566).delete()


def backwards_noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('master_data', '0009_companyprofile_roles_can_stock_in_and_more'),
        ('contacts', '0008_sync_contact_areas_from_addresses'),
    ]

    operations = [
        migrations.RunPython(forwards_consolidate_areas, backwards_noop),
    ]

