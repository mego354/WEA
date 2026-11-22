"""
Generic Global Excel Import Views (Upload -> Preview/Validate -> Error Report -> Confirm Commit).
Serves all 10 approved first-wave entities while strictly excluding Users.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse

from accounts.permissions import has_perm_or_admin, render_forbidden_response

from .excel_import_engine import ImportBatchStore
from .excel_importers import get_importer_class


def _get_authorized_importer(request, entity: str):
    importer_cls = get_importer_class(entity)
    if importer_cls is None:
        raise Http404("نوع الاستيراد غير مدعوم.")
    if not has_perm_or_admin(request.user, importer_cls.permission_codename):
        return None, render_forbidden_response(
            request,
            importer_cls.permission_codename,
            f"عذراً، لا تمتلك صلاحية استيراد Excel لـ {importer_cls.title_ar}.",
        )
    return importer_cls(request.user), None


@login_required
def excel_import_template_view(request, entity: str):
    importer, denied = _get_authorized_importer(request, entity)
    if denied:
        return denied
    return importer.generate_template_response()


@login_required
def excel_import_errors_view(request, entity: str, batch_id: str):
    importer, denied = _get_authorized_importer(request, entity)
    if denied:
        return denied
    batch_data = ImportBatchStore.load_batch(batch_id, request.user.id, importer.entity_key)
    if not batch_data:
        messages.error(request, "انتهت صلاحية دفعة المعاينة أو غير موجودة. يرجى رفع الملف مجدداً.")
        return redirect('excel_import', entity=importer.entity_key)
    return importer.generate_error_report_response(batch_data)


@login_required
def excel_import_view(request, entity: str):
    importer, denied = _get_authorized_importer(request, entity)
    if denied:
        return denied

    step = 'upload'
    batch_id = request.GET.get('batch') or request.POST.get('batch_id') or ''
    batch_data = None
    commit_result = None

    if request.method == 'POST':
        action = request.POST.get('action', 'upload')

        if action == 'cancel':
            if batch_id:
                ImportBatchStore.delete_batch(batch_id)
            messages.info(request, "تم إلغاء عملية الاستيراد.")
            return redirect('excel_import', entity=importer.entity_key)

        elif action == 'upload':
            uploaded = request.FILES.get('excel_file')
            if not uploaded:
                messages.error(request, "يرجى اختيار ملف Excel (.xlsx) قبل المتابعة.")
            else:
                parsed, err_msg = importer.parse_and_validate_upload(uploaded)
                if err_msg:
                    messages.error(request, err_msg)
                else:
                    new_batch_id = ImportBatchStore.save_batch(request.user.id, importer.entity_key, parsed)
                    return redirect(f"{reverse('excel_import', kwargs={'entity': importer.entity_key})}?batch={new_batch_id}")

        elif action == 'confirm':
            batch_data = ImportBatchStore.load_batch(batch_id, request.user.id, importer.entity_key)
            if not batch_data:
                messages.error(request, "انتهت صلاحية جلسة المعاينة. يرجى رفع الملف مرة أخرى.")
                return redirect('excel_import', entity=importer.entity_key)

            allow_partial = request.POST.get('allow_partial') in ('1', 'on', 'true')
            try:
                commit_result = importer.execute_commit(batch_data, allow_partial=allow_partial, request=request)
                ImportBatchStore.delete_batch(batch_id)
                step = 'done'
                messages.success(
                    request,
                    f"تم تنفيذ الاستيراد بنجاح: إنشاء {commit_result['created']} وتحديث {commit_result['updated']} سجل.",
                )
            except Exception as exc:
                messages.error(request, str(exc))
                step = 'preview'

    if step != 'done' and batch_id:
        if batch_data is None:
            batch_data = ImportBatchStore.load_batch(batch_id, request.user.id, importer.entity_key)
        if batch_data:
            step = 'preview'

    preview_page = None
    filter_mode = request.GET.get('filter', 'all')
    if step == 'preview' and batch_data:
        rows = batch_data.get('rows', [])
        if filter_mode == 'valid':
            rows = [r for r in rows if r.get('is_valid')]
        elif filter_mode == 'invalid':
            rows = [r for r in rows if not r.get('is_valid')]
        paginator = Paginator(rows, 50)
        preview_page = paginator.get_page(request.GET.get('page', 1))

    try:
        back_url = reverse(importer.back_url_name)
    except Exception:
        back_url = '/'

    return render(request, 'master_data/excel_import.html', {
        'importer': importer,
        'columns': importer.columns,
        'step': step,
        'batch_id': batch_id,
        'batch': batch_data,
        'filter_mode': filter_mode,
        'preview_page': preview_page,
        'commit_result': commit_result,
        'back_url': back_url,
    })
