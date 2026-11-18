"""
Post-delete signals for unified media lifecycle cleanup (R2 / local storage).
Ensures deleting a parent record cleans up its ERPAttachments and FileField/ImageField objects
only AFTER the database transaction commits and only when reference count == 0.
"""

from django.contrib.contenttypes.models import ContentType
from django.db.models.signals import post_delete
from django.dispatch import receiver

from master_data.media_service import schedule_storage_deletion


@receiver(post_delete)
def cleanup_erp_attachments_on_parent_delete(sender, instance, **kwargs):
    from master_data.models import ERPAttachment, CompanyProfile

    app_label = getattr(sender._meta, 'app_label', '')
    if app_label not in {'sales', 'purchases', 'inventory', 'treasury', 'contacts', 'catalog', 'accounts', 'master_data'}:
        return
    if sender is ERPAttachment:
        key = instance.storage_key or (instance.file.name if instance.file else '')
        if key:
            schedule_storage_deletion(key, size_bytes=instance.file_size_bytes or 0)
        return

    # Clean up direct ImageField/FileField on specific models
    if app_label == 'catalog' and sender._meta.model_name == 'product':
        if getattr(instance, 'thumbnail', None) and instance.thumbnail.name:
            schedule_storage_deletion(instance.thumbnail.name)
    elif sender is CompanyProfile:
        if getattr(instance, 'logo', None) and instance.logo.name:
            schedule_storage_deletion(instance.logo.name)
    elif app_label == 'accounts' and sender._meta.model_name == 'user':
        if getattr(instance, 'avatar', None) and instance.avatar.name:
            schedule_storage_deletion(instance.avatar.name)

    # Clean up any GenericForeignKey ERPAttachments linked to this deleted record
    if instance.pk is not None:
        ct = ContentType.objects.get_for_model(sender, for_concrete_model=False)
        for att in ERPAttachment.objects.filter(content_type=ct, object_id=instance.pk):
            key = att.storage_key or (att.file.name if att.file else '')
            sz = att.file_size_bytes or 0
            att.delete()
            if key:
                schedule_storage_deletion(key, size_bytes=sz)
