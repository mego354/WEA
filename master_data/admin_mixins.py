"""
4-Category Django Admin Deletion Policy Mixins for WEA Pharma ERP.
Preserves all 33 database PROTECT constraints while preventing raw ProtectedError crashes,
enforcing immutable financial/inventory/audit ledgers, routing complex deletions through
official domain services, and logging every Admin deletion to SecurityAuditLog.

Categories:
  1. SafeCascadeAdminMixin           — Safe auxiliary/dependent models (audited).
  2. ProtectedMasterAdminMixin       — Master/reference models (checks blockers, no raw 500, audited).
  3. ControlledServiceDeleteAdminMixin — Routes deletion through official ERP services (no bulk delete).
  4. ImmutableAdminMixin / SingletonSettingsAdminMixin — Deletion strictly disabled in Django Admin.
"""

from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models.deletion import Collector, ProtectedError

from accounts.services import AuditLogService


def _audit_admin_delete(request, obj, note=''):
    try:
        AuditLogService.log(
            actor=getattr(request, 'user', None),
            request=request,
            module=obj._meta.app_label,
            action_type='ADMIN_RECORD_DELETED',
            record_id=str(getattr(obj, 'pk', '')),
            record_name=str(obj)[:200],
            description=f"[Django Admin] حذف {obj._meta.verbose_name}: {obj}" + (f" ({note})" if note else ""),
        )
    except Exception:
        pass


def _summarize_protected_blockers(obj) -> str:
    """Inspects reverse PROTECT relationships via Django's Collector without deleting anything."""
    collector = Collector(using='default')
    try:
        collector.collect([obj])
        return ''
    except ProtectedError as exc:
        counts = {}
        for rel_obj in exc.protected_objects:
            label = str(rel_obj._meta.verbose_name_plural)
            counts[label] = counts.get(label, 0) + 1
        summary = '، '.join(f"{k} ({v})" for k, v in counts.items())
        return f"لا يمكن حذف '{obj}' لارتباطه بسجلات محمية: {summary}."


class SafeCascadeAdminMixin:
    """Category 1: Safe dependent/auxiliary models — cascade allowed with audit logging."""
    admin_deletion_category = 'category_1_safe_cascade'

    def delete_model(self, request, obj):
        _audit_admin_delete(request, obj, 'Category 1 Safe Cascade')
        super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        for obj in queryset:
            _audit_admin_delete(request, obj, 'Category 1 Bulk Cascade')
        super().delete_queryset(request, queryset)


class ProtectedMasterAdminMixin:
    """Category 2: Master/reference records — respects PROTECT, shows clear Arabic blocker summary."""
    admin_deletion_category = 'category_2_protected_master'

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop('delete_selected', None)
        return actions

    def get_custom_delete_blocker(self, request, obj) -> str:
        return ''

    def delete_model(self, request, obj):
        custom_err = self.get_custom_delete_blocker(request, obj)
        if custom_err:
            messages.error(request, custom_err)
            return
        blocker = _summarize_protected_blockers(obj)
        if blocker:
            messages.error(request, blocker)
            return
        try:
            _audit_admin_delete(request, obj, 'Category 2 Protected Master')
            super().delete_model(request, obj)
        except ProtectedError:
            messages.error(request, _summarize_protected_blockers(obj) or f"لا يمكن حذف '{obj}' لوجود سجلات مرتبطة.")

    def delete_queryset(self, request, queryset):
        blocked = 0
        deleted = 0
        for obj in queryset:
            if self.get_custom_delete_blocker(request, obj) or _summarize_protected_blockers(obj):
                blocked += 1
                continue
            try:
                _audit_admin_delete(request, obj, 'Category 2 Protected Master')
                obj.delete()
                deleted += 1
            except ProtectedError:
                blocked += 1
        if blocked:
            messages.warning(request, f"تم تخطي {blocked} سجل لوجود ارتباطات محمية، وحذف {deleted} سجل غير مرتبط.")


class ControlledServiceDeleteAdminMixin:
    """Category 3: Complex lifecycle records — deletion must run through official ERP services."""
    admin_deletion_category = 'category_3_controlled_service'

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop('delete_selected', None)
        return actions

    def perform_service_delete(self, request, obj):
        raise NotImplementedError("Subclasses must implement perform_service_delete(request, obj)")

    def delete_model(self, request, obj):
        try:
            self.perform_service_delete(request, obj)
            _audit_admin_delete(request, obj, 'Category 3 Service Delete')
        except (ValidationError, PermissionDenied, ProtectedError, ValueError) as exc:
            msg = '; '.join(exc.messages) if hasattr(exc, 'messages') else str(exc)
            messages.error(request, f"تعذر حذف '{obj}': {msg}")

    def delete_queryset(self, request, queryset):
        raise PermissionDenied("الحذف الجماعي غير مسموح لهذا النموذج؛ يجب حذف كل سجل منفرداً عبر منطق الأعمال.")


class ImmutableAdminMixin:
    """Category 4A: Immutable financial, inventory ledger, line-item, and audit log records."""
    admin_deletion_category = 'category_4_immutable'

    def has_delete_permission(self, request, obj=None):
        return False

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop('delete_selected', None)
        return actions

    def delete_model(self, request, obj):
        raise PermissionDenied(f"حذف سجلات '{obj._meta.verbose_name_plural}' ممنوع نهائياً حفاظاً على سلامة السجل المحاسبي والتدقيقي.")

    def delete_queryset(self, request, queryset):
        raise PermissionDenied("حذف هذه السجلات ممنوع نهائياً حفاظاً على سلامة السجل المحاسبي والتدقيقي.")


class SingletonSettingsAdminMixin(ImmutableAdminMixin):
    """Category 4B: Singleton system settings — deletion disabled and extra creation prevented."""
    admin_deletion_category = 'category_4_singleton'

    def has_add_permission(self, request):
        if self.model.objects.exists():
            return False
        return super().has_add_permission(request)
