"""
Centralized Media Lifecycle, Validation, Deduplication & R2 Cost-Tracking Service.
Handles image/PDF validation, SHA-256 deduplication, transaction.on_commit cleanup,
and safe deletion retry queuing.
"""

import hashlib
import io
import logging
import os
import re
import uuid
from decimal import Decimal

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import models, transaction
from django.db.models import F
from django.utils import timezone

logger = logging.getLogger(__name__)

ALLOWED_IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp'}
ALLOWED_DOC_EXTENSIONS = {'.pdf'}
ALLOWED_EXTENSIONS = ALLOWED_IMAGE_EXTENSIONS | ALLOWED_DOC_EXTENSIONS

ALLOWED_IMAGE_MIMES = {'image/jpeg', 'image/png', 'image/webp'}
ALLOWED_DOC_MIMES = {'application/pdf'}
ALLOWED_MIMES = ALLOWED_IMAGE_MIMES | ALLOWED_DOC_MIMES


def get_max_upload_bytes():
    mb = getattr(settings, 'MEDIA_MAX_UPLOAD_SIZE_MB', 10)
    return int(mb) * 1024 * 1024


def sanitize_filename(filename):
    base = os.path.basename(str(filename or 'file'))
    name, ext = os.path.splitext(base)
    safe_name = re.sub(r'[^A-Za-z0-9\u0600-\u06FF._-]+', '_', name).strip('._-') or 'attachment'
    return f"{safe_name[:80]}{ext.lower()}"


def validate_uploaded_file(uploaded_file, *, allowed_extensions=None):
    """
    Validates extension, file size, and actual binary header (Pillow verify for images, %PDF- for PDFs).
    Returns (safe_filename, detected_mime, file_bytes).
    """
    if not uploaded_file:
        raise ValidationError("لم يتم اختيار أي ملف للرفع.")

    max_bytes = get_max_upload_bytes()
    file_size = getattr(uploaded_file, 'size', None)
    if file_size is not None and file_size > max_bytes:
        max_mb = getattr(settings, 'MEDIA_MAX_UPLOAD_SIZE_MB', 10)
        raise ValidationError(f"حجم الملف يتجاوز الحد الأقصى المسموح ({max_mb} ميجابايت).")
    if file_size == 0:
        raise ValidationError("الملف المرفق فارغ (0 بايت).")

    safe_name = sanitize_filename(getattr(uploaded_file, 'name', 'file'))
    _, ext = os.path.splitext(safe_name)
    allowed = allowed_extensions or ALLOWED_EXTENSIONS
    if ext not in allowed:
        raise ValidationError("نوع الملف غير مدعوم. يُسمح فقط بالصور (JPG, PNG, WEBP) وملفات PDF.")

    if hasattr(uploaded_file, 'seek'):
        uploaded_file.seek(0)
    raw_bytes = uploaded_file.read()
    if len(raw_bytes) > max_bytes:
        max_mb = getattr(settings, 'MEDIA_MAX_UPLOAD_SIZE_MB', 10)
        raise ValidationError(f"حجم الملف يتجاوز الحد الأقصى المسموح ({max_mb} ميجابايت).")
    if len(raw_bytes) == 0:
        raise ValidationError("الملف المرفق فارغ.")

    if ext in ALLOWED_DOC_EXTENSIONS:
        if not raw_bytes[:1024].lstrip().startswith(b'%PDF-'):
            raise ValidationError("ملف PDF غير صالح أو تالف.")
        detected_mime = 'application/pdf'
    else:
        try:
            from PIL import Image
            img = Image.open(io.BytesIO(raw_bytes))
            img.verify()
            fmt = (img.format or '').upper()
            mime_map = {'JPEG': 'image/jpeg', 'PNG': 'image/png', 'WEBP': 'image/webp'}
            if fmt not in mime_map:
                raise ValidationError("صيغة الصورة غير مدعومة (يُسمح بـ JPG / PNG / WEBP فقط).")
            detected_mime = mime_map[fmt]
        except ValidationError:
            raise
        except Exception:
            raise ValidationError("تعذر التحقق من سلامة الصورة المرفوعة.")

    if hasattr(uploaded_file, 'seek'):
        uploaded_file.seek(0)

    return safe_name, detected_mime, raw_bytes


def optimize_image_bytes(raw_bytes, mime_type):
    """
    Optimizes oversized images (> 1.5 MB or > 2400px) without degrading readability.
    Leaves small images and PDFs untouched.
    """
    if mime_type not in ALLOWED_IMAGE_MIMES:
        return raw_bytes
    if len(raw_bytes) <= 1_500_000:
        return raw_bytes
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(raw_bytes))
        max_dim = 2400
        if max(img.size) > max_dim:
            img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        if mime_type == 'image/png':
            img.save(out, format='PNG', optimize=True)
        elif mime_type == 'image/webp':
            img.save(out, format='WEBP', quality=85, method=4)
        else:
            if img.mode in ('RGBA', 'P'):
                img = img.convert('RGB')
            img.save(out, format='JPEG', quality=85, optimize=True)
        optimized = out.getvalue()
        return optimized if len(optimized) < len(raw_bytes) else raw_bytes
    except Exception:
        return raw_bytes


def _current_month_str():
    return timezone.localdate().strftime('%Y-%m')


def record_r2_operation(*, bytes_delta=0, objects_delta=0, class_a_ops=0, class_b_ops=0):
    """Atomically updates R2StorageConfig usage counters inside/after commit."""
    from master_data.models import R2StorageConfig
    cfg = R2StorageConfig.get_settings()
    month_str = _current_month_str()
    updates = {}
    if cfg.metrics_month != month_str:
        R2StorageConfig.objects.filter(pk=cfg.pk).update(
            metrics_month=month_str,
            current_month_class_a_ops=0,
            current_month_class_b_ops=0,
        )
    if bytes_delta:
        if bytes_delta > 0:
            updates['tracked_storage_bytes'] = F('tracked_storage_bytes') + int(bytes_delta)
        else:
            # Clamp at 0 in Python if subtracting
            new_bytes = max(0, int(cfg.tracked_storage_bytes) + int(bytes_delta))
            updates['tracked_storage_bytes'] = new_bytes
    if objects_delta:
        if objects_delta > 0:
            updates['tracked_objects_count'] = F('tracked_objects_count') + int(objects_delta)
        else:
            new_cnt = max(0, int(cfg.tracked_objects_count) + int(objects_delta))
            updates['tracked_objects_count'] = new_cnt
    if class_a_ops:
        updates['current_month_class_a_ops'] = F('current_month_class_a_ops') + int(class_a_ops)
    if class_b_ops:
        updates['current_month_class_b_ops'] = F('current_month_class_b_ops') + int(class_b_ops)
    if updates:
        R2StorageConfig.objects.filter(pk=cfg.pk).update(**updates)


def is_storage_key_referenced(storage_key):
    """Returns True if any DB record still references this storage key."""
    if not storage_key:
        return False
    from master_data.models import ERPAttachment, CompanyProfile
    from catalog.models import Product
    from accounts.models import User
    from contacts.models import ContactAttachment
    from purchases.models import PurchaseOrderAttachment
    from activities.models import Visit

    if ERPAttachment.objects.filter(storage_key=storage_key).exists():
        return True
    if ERPAttachment.objects.filter(file=storage_key).exists():
        return True
    if CompanyProfile.objects.filter(logo=storage_key).exists():
        return True
    if Product.objects.filter(thumbnail=storage_key).exists():
        return True
    if User.objects.filter(avatar=storage_key).exists():
        return True
    if ContactAttachment.objects.filter(file=storage_key).exists():
        return True
    if PurchaseOrderAttachment.objects.filter(file=storage_key).exists():
        return True
    if hasattr(Visit, 'photo') and Visit.objects.filter(photo=storage_key).exists():
        return True
    return False


def _execute_physical_delete(storage_key, size_bytes=0):
    """Physically deletes storage_key if unreferenced; queues retry on failure."""
    if not storage_key or is_storage_key_referenced(storage_key):
        return
    from master_data.models import PendingStorageDeletion
    try:
        if default_storage.exists(storage_key):
            default_storage.delete(storage_key)
        record_r2_operation(bytes_delta=-int(size_bytes or 0), objects_delta=-1)
        PendingStorageDeletion.objects.filter(storage_key=storage_key).delete()
    except Exception as exc:
        logger.warning("Failed to delete storage key %s: %s", storage_key, exc)
        PendingStorageDeletion.objects.update_or_create(
            storage_key=storage_key,
            defaults={
                'last_error': str(exc)[:500],
                'last_attempt_at': timezone.now(),
            },
        )
        PendingStorageDeletion.objects.filter(storage_key=storage_key).update(
            attempts=F('attempts') + 1
        )


def schedule_storage_deletion(storage_key, size_bytes=0):
    """Schedules safe post-commit deletion so rolled-back DB transactions never lose files."""
    if not storage_key:
        return
    transaction.on_commit(lambda: _execute_physical_delete(storage_key, size_bytes=size_bytes))


def store_attachment(obj, uploaded_file, user, title=''):
    """
    Validates, optimizes (if oversized image), deduplicates via SHA-256, and attaches
    an image/PDF to any supported ERP model via ERPAttachment.
    """
    from master_data.models import ERPAttachment

    safe_name, mime_type, raw_bytes = validate_uploaded_file(uploaded_file)
    processed_bytes = optimize_image_bytes(raw_bytes, mime_type)
    file_hash = hashlib.sha256(processed_bytes).hexdigest()

    ct = ContentType.objects.get_for_model(obj.__class__)

    # Prevent duplicate upload of identical file on the exact same record
    existing_on_obj = ERPAttachment.objects.filter(
        content_type=ct, object_id=obj.pk, file_hash=file_hash
    ).first()
    if existing_on_obj:
        return existing_on_obj, False

    # Check if identical content already exists in storage to avoid redundant R2 PUT
    reusable = ERPAttachment.objects.filter(file_hash=file_hash).exclude(storage_key='').first()
    if reusable and default_storage.exists(reusable.storage_key):
        att = ERPAttachment.objects.create(
            content_type=ct,
            object_id=obj.pk,
            file=reusable.storage_key,
            storage_key=reusable.storage_key,
            file_hash=file_hash,
            original_filename=safe_name,
            mime_type=mime_type,
            file_size_bytes=len(processed_bytes),
            title=(title or safe_name)[:200],
            uploaded_by=user if getattr(user, 'is_authenticated', False) else None,
        )
        return att, True

    now = timezone.now()
    key = f"attachments/{ct.app_label}/{ct.model}/{now:%Y/%m}/{uuid.uuid4().hex[:12]}_{safe_name}"
    content = ContentFile(processed_bytes, name=key)
    content.content_type = mime_type
    saved_key = default_storage.save(key, content)

    # If the outer DB transaction rolls back, clean up the newly uploaded object!
    def _rollback_cleanup():
        if not ERPAttachment.objects.filter(storage_key=saved_key).exists():
            _execute_physical_delete(saved_key, size_bytes=0)

    conn = transaction.get_connection()
    if conn.in_atomic_block:
        # Track newly uploaded file; on commit update metrics, on rollback remove orphan
        transaction.on_commit(lambda: record_r2_operation(
            bytes_delta=len(processed_bytes),
            objects_delta=1,
            class_a_ops=1,
        ))
    else:
        record_r2_operation(bytes_delta=len(processed_bytes), objects_delta=1, class_a_ops=1)

    att = ERPAttachment.objects.create(
        content_type=ct,
        object_id=obj.pk,
        file=saved_key,
        storage_key=saved_key,
        file_hash=file_hash,
        original_filename=safe_name,
        mime_type=mime_type,
        file_size_bytes=len(processed_bytes),
        title=(title or safe_name)[:200],
        uploaded_by=user if getattr(user, 'is_authenticated', False) else None,
    )
    return att, True


def store_attachments_from_request(obj, request, field_name='attachments'):
    """Helper to store multiple uploaded files from request.FILES.getlist(field_name)."""
    files = request.FILES.getlist(field_name)
    created = []
    for f in files:
        att, _ = store_attachment(obj, f, request.user)
        created.append(att)
    return created


def delete_attachment(attachment, user, request=None):
    """Deletes an ERPAttachment record and schedules post-commit physical storage cleanup."""
    storage_key = attachment.storage_key or (attachment.file.name if attachment.file else '')
    size_bytes = attachment.file_size_bytes or 0
    filename = attachment.original_filename
    att_id = attachment.pk
    attachment.delete()
    schedule_storage_deletion(storage_key, size_bytes=size_bytes)

    from accounts.services import AuditLogService
    AuditLogService.log(
        actor=user,
        action_type='ATTACHMENT_DELETED',
        module='master_data',
        record_id=str(att_id),
        record_name=filename,
        description=f"حذف المرفق '{filename}'",
        request=request,
    )


def replace_model_file(instance, field_name, new_file, *, allowed_extensions=None):
    """
    Validates & replaces a FileField/ImageField on a model (e.g. CompanyProfile.logo, Product.thumbnail)
    and schedules post-commit deletion of the old file if no longer referenced.
    """
    exts = allowed_extensions or ALLOWED_IMAGE_EXTENSIONS
    safe_name, mime_type, raw_bytes = validate_uploaded_file(new_file, allowed_extensions=exts)
    processed_bytes = optimize_image_bytes(raw_bytes, mime_type)

    old_field = getattr(instance, field_name, None)
    old_key = old_field.name if old_field and getattr(old_field, 'name', '') else ''

    content = ContentFile(processed_bytes, name=safe_name)
    content.content_type = mime_type
    setattr(instance, field_name, content)
    record_r2_operation(bytes_delta=len(processed_bytes), objects_delta=1, class_a_ops=1)

    if old_key:
        schedule_storage_deletion(old_key, size_bytes=0)


def clear_model_file(instance, field_name):
    """Clears a FileField/ImageField and schedules post-commit physical deletion."""
    old_field = getattr(instance, field_name, None)
    old_key = old_field.name if old_field and getattr(old_field, 'name', '') else ''
    setattr(instance, field_name, None)
    if old_key:
        schedule_storage_deletion(old_key, size_bytes=0)


# Registry of models supporting unified ERPAttachment upload/view/download/delete
ATTACHMENT_MODEL_MAP = {
    'salesorder': ('sales', 'SalesOrder', 'salesorder', ['sales:orders/view', 'sales:orders/list'], ['sales:orders/create', 'sales:orders/edit'], ['sales:orders/edit', 'sales:orders/delete']),
    'salesreturnorder': ('sales', 'SalesReturnOrder', 'salesreturnorder', ['sales:returns/view', 'sales:returns/list'], ['sales:returns/create', 'sales:returns/edit'], ['sales:returns/edit', 'sales:returns/delete']),
    'collection': ('sales', 'Collection', 'collection', ['sales:collections/list'], ['sales:collections/create'], ['sales:collections/create']),
    'purchaseorder': ('purchases', 'PurchaseOrder', 'purchaseorder', ['purchases:orders/view', 'purchases:orders/list'], ['purchases:orders/create', 'purchases:orders/edit'], ['purchases:orders/edit', 'purchases:orders/delete']),
    'purchasereturnorder': ('purchases', 'PurchaseReturnOrder', 'purchasereturnorder', ['purchases:returns/view', 'purchases:returns/list'], ['purchases:returns/create', 'purchases:returns/edit'], ['purchases:returns/edit', 'purchases:returns/delete']),
    'vendorpayment': ('treasury', 'VendorPayment', 'vendorpayment', ['treasury:payments/list'], ['treasury:payments/create'], ['treasury:payments/create']),
    'vendorpaymentrequest': ('treasury', 'VendorPaymentRequest', 'vendorpaymentrequest', ['treasury:payments/requests'], ['treasury:payment_requests/create'], ['treasury:payment_requests/create']),
    'inventorymemo': ('inventory', 'InventoryMemo', 'inventorymemo', ['inventory:stocks/view', 'inventory:memos/manage'], ['inventory:memos/manage'], ['inventory:memos/manage']),
    'producttransferrequest': ('inventory', 'ProductTransferRequest', 'producttransferrequest', ['inventory:transfers/view', 'inventory:transfers/list'], ['inventory:transfers/create'], ['inventory:transfers/create']),
    'vaulttransaction': ('treasury', 'VaultTransaction', 'vaulttransaction', ['treasury:transactions/list', 'treasury:vaults/view'], ['treasury:transactions/create', 'treasury:transactions/edit', 'treasury:vaults/transfer'], ['treasury:transactions/edit']),
    'contact': ('contacts', 'Contact', 'contact', ['contacts:contacts/view', 'contacts:contacts/list'], ['contacts:contacts/edit', 'contacts:contacts/create'], ['contacts:contacts/edit']),
}
