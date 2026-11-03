import threading
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth import get_user_model

_local = threading.local()


@receiver(post_save, sender=get_user_model())
def handle_representative_created(sender, instance, created, **kwargs):
    """
    Automatically creates designated warehouse and treasury for newly created
    representatives or users whose role becomes a representative, according to UserSettings.
    Safely guarded against recursion and repeated saves on profile edits.
    """
    if getattr(_local, 'in_rep_provisioning', False):
        return

    from .services import is_representative, ensure_representative_resources

    # Provision automatically if user is a representative and either newly created
    # or missing designated warehouse/treasury resources
    if is_representative(instance):
        wh = instance.get_default_warehouse()
        vault = instance.get_default_treasury()
        if created or wh is None or vault is None:
            try:
                _local.in_rep_provisioning = True
                ensure_representative_resources(instance)
            finally:
                _local.in_rep_provisioning = False


from django.db.models.signals import m2m_changed


@receiver(m2m_changed, sender=get_user_model().assigned_areas.through)
def handle_representative_areas_changed(sender, instance, action, **kwargs):
    """
    Synchronizes warehouse area whenever a representative's assigned areas are updated.
    """
    if action in ['post_add', 'post_remove', 'post_clear']:
        from .services import is_representative, get_representative_warehouse
        if is_representative(instance):
            wh = get_representative_warehouse(instance)
            if wh and instance.assigned_areas.exists():
                area = instance.assigned_areas.first()
                if wh.area_id != area.id:
                    wh.area = area
                    wh.save(update_fields=['area'])
