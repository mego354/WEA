"""
Views for Cloudflare R2 Storage Settings / Pricing Calculator and Unified ERP Attachments.
Enforces strict RBAC permissions, DataScope (can_user_access_object), and AuditLogService.
"""

import logging
from decimal import Decimal, InvalidOperation

from django.apps import apps
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.files.storage import default_storage
from django.http import FileResponse, Http404, HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from accounts.permissions import can_user_access_object, has_perm_or_admin, render_forbidden_response, require_permission
from accounts.services import AuditLogService
from master_data.media_service import (
    ATTACHMENT_MODEL_MAP,
    _execute_physical_delete,
    delete_attachment,
    record_r2_operation,
    store_attachments_from_request,
)
from master_data.models import ERPAttachment, PendingStorageDeletion, R2StorageConfig

logger = logging.getLogger(__name__)


def _resolve_parent_object(user, model_key, object_id, *, perm_mode='view'):
    """
    Resolves parent model instance and verifies RBAC permission + DataScope.
    Returns (obj, config_tuple) or (None, forbidden_response).
    """
    cfg = ATTACHMENT_MODEL_MAP.get(model_key)
    if not cfg:
        raise Http404("نوع السجل غير مدعوم للمرفقات.")

    app_label, model_name, scope_key, view_perms, edit_perms, delete_perms = cfg
    if perm_mode == 'view':
        req_perms = view_perms
        obj_mode = 'view'
    elif perm_mode == 'delete':
        req_perms = delete_perms
        obj_mode = 'edit'
    else:
        req_perms = edit_perms
        obj_mode = 'edit'

    if not has_perm_or_admin(user, req_perms):
        return None, None, req_perms

    model_cls = apps.get_model(app_label, model_name)
    obj = get_object_or_404(model_cls, pk=object_id)

    if not can_user_access_object(user, obj, obj_mode):
        return None, cfg, req_perms

    return obj, cfg, None


@login_required
@require_permission('settings:storage/manage')
def r2_storage_settings_view(request):
    """Cloudflare R2 Configuration Status, Usage Metrics & Monthly Pricing Calculator."""
    cfg = R2StorageConfig.get_settings()

    if request.method == 'POST':
        action = request.POST.get('action', 'save_pricing')
        if action == 'recalculate':
            from django.db.models import Sum
            agg = ERPAttachment.objects.aggregate(total_bytes=Sum('file_size_bytes'))
            total_bytes = int(agg['total_bytes'] or 0)
            total_objs = ERPAttachment.objects.values('storage_key').distinct().count()
            cfg.tracked_storage_bytes = total_bytes
            cfg.tracked_objects_count = total_objs
            cfg.updated_by = request.user
            cfg.save(update_fields=['tracked_storage_bytes', 'tracked_objects_count', 'updated_by', 'updated_at'])
            messages.success(request, "تمت إعادة احتساب مساحة وعدد المرفقات من قاعدة البيانات بنجاح.")
            return redirect('r2_storage_settings')

        if action == 'retry_deletions':
            pending = list(PendingStorageDeletion.objects.all()[:100])
            for p in pending:
                _execute_physical_delete(p.storage_key)
            remaining = PendingStorageDeletion.objects.count()
            messages.success(request, f"تمت معالجة طابور الحذف المعلق. المتبقي: {remaining}.")
            return redirect('r2_storage_settings')

        # Save pricing assumptions
        try:
            cfg.free_storage_gb = Decimal(request.POST.get('free_storage_gb', cfg.free_storage_gb))
            cfg.free_class_a_ops = max(0, int(request.POST.get('free_class_a_ops', cfg.free_class_a_ops)))
            cfg.free_class_b_ops = max(0, int(request.POST.get('free_class_b_ops', cfg.free_class_b_ops)))
            cfg.price_per_gb_month_usd = Decimal(request.POST.get('price_per_gb_month_usd', cfg.price_per_gb_month_usd))
            cfg.price_per_million_class_a_usd = Decimal(request.POST.get('price_per_million_class_a_usd', cfg.price_per_million_class_a_usd))
            cfg.price_per_million_class_b_usd = Decimal(request.POST.get('price_per_million_class_b_usd', cfg.price_per_million_class_b_usd))
            cfg.egress_price_per_gb_usd = Decimal(request.POST.get('egress_price_per_gb_usd', cfg.egress_price_per_gb_usd))
            cfg.usd_to_egp_rate = Decimal(request.POST.get('usd_to_egp_rate', cfg.usd_to_egp_rate))
            cfg.updated_by = request.user
            cfg.save()

            AuditLogService.log(
                actor=request.user,
                action_type='STORAGE_SETTINGS_UPDATED',
                module='master_data',
                record_id=str(cfg.pk),
                record_name='Cloudflare R2 Pricing Config',
                description='تحديث افتراضات تسعير التخزين السحابي Cloudflare R2',
                request=request,
            )
            messages.success(request, "تم حفظ افتراضات التسعير لـ Cloudflare R2 بنجاح.")
            return redirect('r2_storage_settings')
        except (InvalidOperation, ValueError, TypeError):
            messages.error(request, "يرجى إدخال قيم رقمية صحيحة لافتراضات التسعير.")

    estimate = cfg.calculate_cost_estimate()

    # Optional simulator values from GET query params
    sim_storage = request.GET.get('sim_storage_gb', '').strip()
    sim_a = request.GET.get('sim_class_a', '').strip()
    sim_b = request.GET.get('sim_class_b', '').strip()
    sim_egress = request.GET.get('sim_egress_gb', '').strip()
    sim_estimate = None
    if any([sim_storage, sim_a, sim_b, sim_egress]):
        try:
            sim_estimate = cfg.calculate_cost_estimate(
                storage_gb=Decimal(sim_storage) if sim_storage else None,
                class_a_ops=int(sim_a) if sim_a else None,
                class_b_ops=int(sim_b) if sim_b else None,
                egress_gb=Decimal(sim_egress) if sim_egress else None,
            )
        except (InvalidOperation, ValueError, TypeError):
            pass

    r2_enabled = getattr(settings, 'R2_ENABLED', False)
    bucket_name = getattr(settings, 'CLOUDFLARE_R2_BUCKET_NAME', '')
    custom_domain = getattr(settings, 'CLOUDFLARE_R2_CUSTOM_DOMAIN', '')

    return render(request, 'settings/r2_storage_settings.html', {
        'cfg': cfg,
        'estimate': estimate,
        'sim_estimate': sim_estimate,
        'sim_inputs': {
            'sim_storage_gb': sim_storage,
            'sim_class_a': sim_a,
            'sim_class_b': sim_b,
            'sim_egress_gb': sim_egress,
        },
        'r2_enabled': r2_enabled,
        'bucket_name': bucket_name if r2_enabled else '',
        'custom_domain': custom_domain if r2_enabled else '',
        'max_upload_mb': getattr(settings, 'MEDIA_MAX_UPLOAD_SIZE_MB', 10),
        'pending_deletions_count': PendingStorageDeletion.objects.count(),
        'total_attachments_count': ERPAttachment.objects.count(),
    })


@login_required
@require_POST
def erp_attachment_upload(request, model_key, object_id):
    """Upload one or more image/PDF attachments to any supported ERP record."""
    obj, cfg, denied_perms = _resolve_parent_object(request.user, model_key, object_id, perm_mode='edit')
    if obj is None:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': 'غير مصرح برفع مرفقات لهذا السجل.'}, status=403)
        return render_forbidden_response(request, denied_perms[0] if denied_perms else 'settings:storage/manage', 'غير مصرح برفع مرفقات لهذا السجل.')

    try:
        created = store_attachments_from_request(obj, request, field_name='attachments')
        if not created and request.FILES.get('file'):
            created = store_attachments_from_request(obj, request, field_name='file')

        for att in created:
            AuditLogService.log(
                actor=request.user,
                action_type='ATTACHMENT_UPLOADED',
                module='master_data',
                record_id=str(att.pk),
                record_name=att.original_filename,
                description=f"رفع مرفق '{att.original_filename}' على {model_key} #{object_id}",
                request=request,
            )

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': True,
                'uploaded': len(created),
                'attachments': [
                    {
                        'id': a.pk,
                        'filename': a.original_filename,
                        'size': a.size_display,
                        'is_image': a.is_image,
                        'is_pdf': a.is_pdf,
                        'view_url': reverse('erp_attachment_view', args=[a.pk]),
                        'download_url': reverse('erp_attachment_download', args=[a.pk]),
                        'delete_url': reverse('erp_attachment_delete', args=[a.pk]),
                    }
                    for a in created
                ],
            })
        if created:
            messages.success(request, f"تم رفع {len(created)} مرفق بنجاح.")
        else:
            messages.warning(request, "لم يتم اختيار ملفات جديدة أو أن الملف مرفوع مسبقاً.")
    except ValidationError as e:
        msg = e.messages[0] if getattr(e, 'messages', None) else str(e)
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': msg}, status=400)
        messages.error(request, msg)

    next_url = request.POST.get('next') or request.META.get('HTTP_REFERER') or '/'
    return redirect(next_url)


@login_required
def erp_attachments_list_api(request, model_key, object_id):
    """Scoped JSON API returning attachments for a transaction (used by list row modal)."""
    obj, cfg, denied_perms = _resolve_parent_object(request.user, model_key, object_id, perm_mode='view')
    if obj is None:
        return JsonResponse({'error': 'غير مصرح'}, status=403)

    ct = ContentType.objects.get_for_model(obj.__class__)
    atts = ERPAttachment.objects.filter(content_type=ct, object_id=obj.pk).select_related('uploaded_by')
    can_upload = has_perm_or_admin(request.user, cfg[4]) and can_user_access_object(request.user, obj, 'edit')
    can_delete = has_perm_or_admin(request.user, cfg[5]) and can_user_access_object(request.user, obj, 'edit')

    return JsonResponse({
        'attachments': [
            {
                'id': a.pk,
                'filename': a.original_filename,
                'title': a.title,
                'size': a.size_display,
                'is_image': a.is_image,
                'is_pdf': a.is_pdf,
                'uploaded_by': (a.uploaded_by.name or a.uploaded_by.username) if a.uploaded_by else '-',
                'created_at': a.created_at.strftime('%Y-%m-%d %H:%M') if a.created_at else '',
                'view_url': reverse('erp_attachment_view', args=[a.pk]),
                'download_url': reverse('erp_attachment_download', args=[a.pk]),
                'delete_url': reverse('erp_attachment_delete', args=[a.pk]),
            }
            for a in atts
        ],
        'can_upload': can_upload,
        'can_delete': can_delete,
        'upload_url': reverse('erp_attachment_upload', args=[model_key, object_id]),
    })


def _serve_protected_attachment(request, attachment_id, *, as_download=False):
    att = get_object_or_404(ERPAttachment.objects.select_related('content_type'), pk=attachment_id)
    model_key = att.content_type.model
    obj, cfg, denied_perms = _resolve_parent_object(request.user, model_key, att.object_id, perm_mode='view')
    if obj is None:
        return render_forbidden_response(request, denied_perms[0] if denied_perms else 'module:master_data', 'غير مصرح لك بالوصول إلى هذا المرفق.')

    key = att.storage_key or (att.file.name if att.file else '')
    if not key or not default_storage.exists(key):
        raise Http404("الملف غير موجود في التخزين.")

    record_r2_operation(class_b_ops=1)

    if getattr(settings, 'R2_ENABLED', False) and not as_download:
        # Redirect to short-lived presigned URL only after full RBAC + DataScope validation
        signed_url = default_storage.url(key)
        return HttpResponseRedirect(signed_url)

    f = default_storage.open(key, 'rb')
    resp = FileResponse(f, content_type=att.mime_type or 'application/octet-stream')
    disp = 'attachment' if as_download else 'inline'
    resp['Content-Disposition'] = f'{disp}; filename="{att.original_filename}"'
    return resp


@login_required
def erp_attachment_view(request, attachment_id):
    return _serve_protected_attachment(request, attachment_id, as_download=False)


@login_required
def erp_attachment_download(request, attachment_id):
    return _serve_protected_attachment(request, attachment_id, as_download=True)


@login_required
@require_POST
def erp_attachment_delete(request, attachment_id):
    att = get_object_or_404(ERPAttachment.objects.select_related('content_type'), pk=attachment_id)
    model_key = att.content_type.model
    obj, cfg, denied_perms = _resolve_parent_object(request.user, model_key, att.object_id, perm_mode='delete')
    if obj is None:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': 'غير مصرح بحذف هذا المرفق.'}, status=403)
        return render_forbidden_response(request, denied_perms[0] if denied_perms else 'module:master_data', 'غير مصرح بحذف هذا المرفق.')

    delete_attachment(att, request.user, request=request)
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': True})
    messages.success(request, "تم حذف المرفق بنجاح.")
    next_url = request.POST.get('next') or request.META.get('HTTP_REFERER') or '/'
    return redirect(next_url)
