"""
Centralized Settings Architecture and Service Layer for WEA Pharma ERP.
Provides unified, cached, secure, and audited access to all singleton configuration models:
- CompanyProfile (Branding, Legal, Currency, Inventory batch/expiry policies, Warehouse operational roles)
- LocationSettings (GPS Geofence, Distance thresholds, Visit verification, Distance bypass roles)
- SalesSettings (Manager approval requirement, Tax mode, Default packaging unit)
- PurchaseSettings (Manager approval requirement, Tax mode, Default packaging unit)
- UserSettings (Representative warehouse & cash treasury auto-provisioning)
"""

import threading
from decimal import Decimal
from django.db import transaction
from django.core.exceptions import ValidationError
from django.core.signals import request_started, request_finished
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from master_data.models import CompanyProfile, LocationSettings, SalesSettings, PurchaseSettings
from accounts.models import UserSettings, Role
from accounts.services import AuditLogService

# Thread-local storage for request-level caching
_thread_locals = threading.local()


@receiver(request_started)
def _on_request_started(sender, **kwargs):
    _thread_locals.in_request = True
    if hasattr(_thread_locals, 'settings_cache'):
        _thread_locals.settings_cache.clear()
    else:
        _thread_locals.settings_cache = {}


@receiver(request_finished)
def _on_request_finished(sender, **kwargs):
    _thread_locals.in_request = False
    if hasattr(_thread_locals, 'settings_cache'):
        _thread_locals.settings_cache.clear()


class SettingsService:
    """
    Centralized, high-performance service for accessing and updating ERP settings.
    Implements in-memory caching to eliminate repeated database queries across the request lifecycle.
    """

    @classmethod
    def _get_cache(cls, request=None):
        if request is not None:
            if not hasattr(request, '_settings_cache'):
                request._settings_cache = {}
            return request._settings_cache
        if getattr(_thread_locals, 'in_request', False):
            if not hasattr(_thread_locals, 'settings_cache'):
                _thread_locals.settings_cache = {}
            return _thread_locals.settings_cache
        return None

    @classmethod
    def clear_cache(cls, key: str = None):
        """Invalidates the in-memory settings cache."""
        if hasattr(_thread_locals, 'settings_cache') and _thread_locals.settings_cache:
            if key:
                _thread_locals.settings_cache.pop(key, None)
            else:
                _thread_locals.settings_cache.clear()

    # --------------------------------------------------------------------------
    # 1. READ / ACCESS METHODS
    # --------------------------------------------------------------------------

    @classmethod
    def get_company_profile(cls, force_refresh: bool = False, request=None) -> CompanyProfile:
        cache = cls._get_cache(request=request)
        if cache is not None and not force_refresh and 'company_profile' in cache:
            return cache['company_profile']
        profile, _ = CompanyProfile.objects.get_or_create(id=1)
        if cache is not None:
            cache['company_profile'] = profile
        return profile

    @classmethod
    def get_location_settings(cls, force_refresh: bool = False, request=None) -> LocationSettings:
        cache = cls._get_cache(request=request)
        if cache is not None and not force_refresh and 'location_settings' in cache:
            return cache['location_settings']
        loc_settings, _ = LocationSettings.objects.get_or_create(id=1)
        if cache is not None:
            cache['location_settings'] = loc_settings
        return loc_settings

    @classmethod
    def get_sales_settings(cls, force_refresh: bool = False, request=None) -> SalesSettings:
        cache = cls._get_cache(request=request)
        if cache is not None and not force_refresh and 'sales_settings' in cache:
            return cache['sales_settings']
        sales_settings, _ = SalesSettings.objects.get_or_create(id=1)
        if cache is not None:
            cache['sales_settings'] = sales_settings
        return sales_settings

    @classmethod
    def get_purchase_settings(cls, force_refresh: bool = False, request=None) -> PurchaseSettings:
        cache = cls._get_cache(request=request)
        if cache is not None and not force_refresh and 'purchase_settings' in cache:
            return cache['purchase_settings']
        pur_settings, _ = PurchaseSettings.objects.get_or_create(id=1)
        if cache is not None:
            cache['purchase_settings'] = pur_settings
        return pur_settings

    @classmethod
    def get_user_settings(cls, force_refresh: bool = False, request=None) -> UserSettings:
        cache = cls._get_cache(request=request)
        if cache is not None and not force_refresh and 'user_settings' in cache:
            return cache['user_settings']
        u_settings, _ = UserSettings.objects.get_or_create(id=1)
        if cache is not None:
            cache['user_settings'] = u_settings
        return u_settings

    # --------------------------------------------------------------------------
    # 2. AUDITED MUTATION METHODS
    # --------------------------------------------------------------------------

    @classmethod
    @transaction.atomic
    def update_company_profile(cls, user, data, files=None, request=None) -> CompanyProfile:
        """Updates company branding and legal details with audit logging."""
        profile = cls.get_company_profile(force_refresh=True)
        old_values = {
            'company_name': profile.company_name,
            'commercial_registry': profile.commercial_registry,
            'tax_id': profile.tax_id,
            'phone': profile.phone,
            'address': profile.address,
            'email': profile.email,
            'currency': profile.currency,
        }

        profile.company_name = data.get('company_name', profile.company_name).strip()
        profile.commercial_registry = data.get('commercial_registry', profile.commercial_registry).strip()
        profile.tax_id = data.get('tax_id', profile.tax_id).strip()
        profile.phone = data.get('phone', profile.phone).strip()
        profile.address = data.get('address', profile.address).strip()
        profile.email = data.get('email', profile.email).strip()
        profile.currency = data.get('currency', profile.currency).strip() or 'EGP'

        if files and 'logo' in files:
            profile.logo = files['logo']

        profile.save()
        cls.clear_cache('company_profile')

        new_values = {
            'company_name': profile.company_name,
            'commercial_registry': profile.commercial_registry,
            'tax_id': profile.tax_id,
            'phone': profile.phone,
            'address': profile.address,
            'email': profile.email,
            'currency': profile.currency,
        }

        AuditLogService.log(
            action_type='SETTINGS_UPDATED',
            module='settings',
            actor=user,
            record_id=profile.id,
            record_name="بيانات وهوية الشركة",
            description="تحديث بيانات وهوية الشركة ومعلومات الفاتورة الرسمية",
            previous_values=old_values,
            new_values=new_values,
            status='SUCCESS',
            request=request,
        )
        return profile

    @classmethod
    @transaction.atomic
    def update_location_settings(cls, user, data, request=None) -> LocationSettings:
        """Updates location and distance governance settings with audit logging."""
        loc = cls.get_location_settings(force_refresh=True)
        old_values = {
            'tolerance': loc.tolerance,
            'max_verified_accuracy': loc.max_verified_accuracy,
            'max_verified_warn_accuracy': loc.max_verified_warn_accuracy,
            'verify_visits': loc.verify_visits,
            'auto_start_location_tracking_service': loc.auto_start_location_tracking_service,
            'auto_set_customer_location_in_visit': loc.auto_set_customer_location_in_visit,
            'allow_template_distance_override': loc.allow_template_distance_override,
            'verify_unplanned_visit_distance': loc.verify_unplanned_visit_distance,
            'verify_end_visit_distance': loc.verify_end_visit_distance,
            'bypass_reason_mandatory': loc.bypass_reason_mandatory,
            'distance_bypass_requires_approval': loc.distance_bypass_requires_approval,
            'require_manager_approval_for_visits': loc.require_manager_approval_for_visits,
            'allow_visit_deletion_before_end': loc.allow_visit_deletion_before_end,
            'require_manager_approval_for_agreements': loc.require_manager_approval_for_agreements,
        }

        try:
            loc.tolerance = max(10, int(data.get('tolerance', loc.tolerance)))
            loc.max_verified_accuracy = max(5, int(data.get('max_verified_accuracy', loc.max_verified_accuracy)))
            loc.max_verified_warn_accuracy = max(10, int(data.get('max_verified_warn_accuracy', loc.max_verified_warn_accuracy)))
        except (ValueError, TypeError):
            pass

        loc.auto_start_location_tracking_service = data.get('auto_start_location_tracking_service') in ('on', '1', 'true', True)
        loc.auto_set_customer_location_in_visit = data.get('auto_set_customer_location_in_visit') in ('on', '1', 'true', True)
        loc.verify_visits = data.get('verify_visits') in ('on', '1', 'true', True)
        loc.allow_template_distance_override = data.get('allow_template_distance_override') in ('on', '1', 'true', True)
        loc.verify_unplanned_visit_distance = data.get('verify_unplanned_visit_distance') in ('on', '1', 'true', True)
        loc.verify_end_visit_distance = data.get('verify_end_visit_distance') in ('on', '1', 'true', True)
        loc.bypass_reason_mandatory = data.get('bypass_reason_mandatory') in ('on', '1', 'true', True)
        loc.distance_bypass_requires_approval = data.get('distance_bypass_requires_approval') in ('on', '1', 'true', True)

        if 'require_manager_approval_for_visits' in data or 'distance_governance_submitted' in data:
            loc.require_manager_approval_for_visits = data.get('require_manager_approval_for_visits') in ('on', '1', 'true', True)
        if 'allow_visit_deletion_before_end' in data or 'distance_governance_submitted' in data:
            loc.allow_visit_deletion_before_end = data.get('allow_visit_deletion_before_end') in ('on', '1', 'true', True)
        if 'require_manager_approval_for_agreements' in data or 'distance_governance_submitted' in data:
            loc.require_manager_approval_for_agreements = data.get('require_manager_approval_for_agreements') in ('on', '1', 'true', True)

        loc.save()

        # Update M2M bypass roles if provided
        if 'roles_can_bypass_distance_creation' in data or 'roles_can_bypass_distance_ending' in data or 'distance_governance_submitted' in data:
            creation_roles = [int(r) for r in data.getlist('roles_can_bypass_distance_creation') if str(r).isdigit()] if hasattr(data, 'getlist') else []
            ending_roles = [int(r) for r in data.getlist('roles_can_bypass_distance_ending') if str(r).isdigit()] if hasattr(data, 'getlist') else []
            loc.roles_can_bypass_distance_creation.set(creation_roles)
            loc.roles_can_bypass_distance_ending.set(ending_roles)

        cls.clear_cache('location_settings')

        new_values = {
            'tolerance': loc.tolerance,
            'max_verified_accuracy': loc.max_verified_accuracy,
            'max_verified_warn_accuracy': loc.max_verified_warn_accuracy,
            'verify_visits': loc.verify_visits,
            'auto_start_location_tracking_service': loc.auto_start_location_tracking_service,
            'auto_set_customer_location_in_visit': loc.auto_set_customer_location_in_visit,
            'allow_template_distance_override': loc.allow_template_distance_override,
            'verify_unplanned_visit_distance': loc.verify_unplanned_visit_distance,
            'verify_end_visit_distance': loc.verify_end_visit_distance,
            'bypass_reason_mandatory': loc.bypass_reason_mandatory,
            'distance_bypass_requires_approval': loc.distance_bypass_requires_approval,
            'require_manager_approval_for_visits': loc.require_manager_approval_for_visits,
            'allow_visit_deletion_before_end': loc.allow_visit_deletion_before_end,
            'require_manager_approval_for_agreements': loc.require_manager_approval_for_agreements,
        }

        AuditLogService.log(
            action_type='LOCATION_SETTINGS_UPDATED',
            module='settings',
            actor=user,
            record_id=loc.id,
            record_name="إعدادات الموقع الجغرافي والزيارات",
            description="تحديث إعدادات التحقق من الموقع الجغرافي وسماحية الزيارات وسياسات التجاوز",
            previous_values=old_values,
            new_values=new_values,
            status='SUCCESS',
            request=request,
        )
        return loc

    @classmethod
    @transaction.atomic
    def update_sales_settings(cls, user, data, request=None) -> SalesSettings:
        """Updates sales policies and approval controls with audit logging."""
        sales = cls.get_sales_settings(force_refresh=True)
        old_values = {
            'require_manager_approval': sales.require_manager_approval,
            'tax_mode': sales.tax_mode,
            'default_packaging_unit': sales.default_packaging_unit,
        }

        # Active configuration fields
        sales.require_manager_approval = data.get('require_manager_approval') in ('on', '1', 'true', True)
        if data.get('tax_mode'):
            sales.tax_mode = data.get('tax_mode')
        if data.get('default_packaging_unit'):
            sales.default_packaging_unit = data.get('default_packaging_unit')

        # Model field backward-compatibility for legacy toggles if present in data
        for bool_field in [
            'require_verification_manager', 'auto_invoice_on_dispatch', 'auto_invoice_on_return',
            'collect_payment_on_invoicing', 'auto_link_accounting_on_collection',
            'auto_close_cash_collection', 'auto_close_collection_on_full_payment', 'use_receipt_books',
            'allow_all_users_to_create'
        ]:
            if bool_field in data:
                setattr(sales, bool_field, data.get(bool_field) in ('on', '1', 'true', True))

        sales.save()
        cls.clear_cache('sales_settings')

        new_values = {
            'require_manager_approval': sales.require_manager_approval,
            'tax_mode': sales.tax_mode,
            'default_packaging_unit': sales.default_packaging_unit,
        }

        AuditLogService.log(
            action_type='SALES_SETTINGS_UPDATED',
            module='settings',
            actor=user,
            record_id=sales.id,
            record_name="إعدادات المبيعات",
            description="تحديث إعدادات وسياسات المبيعات والاعتماد",
            previous_values=old_values,
            new_values=new_values,
            status='SUCCESS',
            request=request,
        )
        return sales

    @classmethod
    @transaction.atomic
    def update_purchase_settings(cls, user, data, request=None) -> PurchaseSettings:
        """Updates purchase policies and approval controls with audit logging."""
        purch = cls.get_purchase_settings(force_refresh=True)
        old_values = {
            'require_manager_approval': purch.require_manager_approval,
            'tax_mode': purch.tax_mode,
            'default_packaging_unit': purch.default_packaging_unit,
        }

        # Active configuration fields
        purch.require_manager_approval = data.get('require_manager_approval') in ('on', '1', 'true', True)
        if data.get('tax_mode'):
            purch.tax_mode = data.get('tax_mode')
        if data.get('default_packaging_unit'):
            purch.default_packaging_unit = data.get('default_packaging_unit')

        # Model field backward-compatibility for legacy toggles if present in data
        for bool_field in [
            'auto_invoice_on_dispatch', 'auto_invoice_on_return', 'auto_close_cash_payment',
            'auto_link_accounting_on_payment', 'auto_close_payment_on_full_settlement',
            'use_receipt_books', 'allow_all_users_to_create'
        ]:
            if bool_field in data:
                setattr(purch, bool_field, data.get(bool_field) in ('on', '1', 'true', True))

        purch.save()
        cls.clear_cache('purchase_settings')

        new_values = {
            'require_manager_approval': purch.require_manager_approval,
            'tax_mode': purch.tax_mode,
            'default_packaging_unit': purch.default_packaging_unit,
        }

        AuditLogService.log(
            action_type='PURCHASE_SETTINGS_UPDATED',
            module='settings',
            actor=user,
            record_id=purch.id,
            record_name="إعدادات المشتريات",
            description="تحديث إعدادات وسياسات المشتريات والاعتماد",
            previous_values=old_values,
            new_values=new_values,
            status='SUCCESS',
            request=request,
        )
        return purch

    @classmethod
    @transaction.atomic
    def update_inventory_settings(cls, user, data, request=None) -> CompanyProfile:
        """Updates inventory batch/expiry policies and warehouse operational roles."""
        profile = cls.get_company_profile(force_refresh=True)
        old_values = {
            'use_batch_number': profile.use_batch_number,
            'use_expiry_date': profile.use_expiry_date,
            'is_batch_mandatory': profile.is_batch_mandatory,
            'is_expiry_mandatory': profile.is_expiry_mandatory,
            'roles_can_stock_in': list(profile.roles_can_stock_in.values_list('id', flat=True)),
            'roles_can_stock_out': list(profile.roles_can_stock_out.values_list('id', flat=True)),
            'roles_can_transfer': list(profile.roles_can_transfer.values_list('id', flat=True)),
        }

        profile.use_batch_number = data.get('use_batch_number') in ('on', '1', 'true', True)
        profile.use_expiry_date = data.get('use_expiry_date') in ('on', '1', 'true', True)
        profile.is_batch_mandatory = data.get('is_batch_mandatory') in ('on', '1', 'true', True)
        profile.is_expiry_mandatory = data.get('is_expiry_mandatory') in ('on', '1', 'true', True)
        profile.save()

        if hasattr(data, 'getlist'):
            roles_stock_in = [int(r) for r in data.getlist('roles_can_stock_in') if str(r).isdigit()]
            roles_stock_out = [int(r) for r in data.getlist('roles_can_stock_out') if str(r).isdigit()]
            roles_transfer = [int(r) for r in data.getlist('roles_can_transfer') if str(r).isdigit()]
            profile.roles_can_stock_in.set(roles_stock_in)
            profile.roles_can_stock_out.set(roles_stock_out)
            profile.roles_can_transfer.set(roles_transfer)

        cls.clear_cache('company_profile')

        new_values = {
            'use_batch_number': profile.use_batch_number,
            'use_expiry_date': profile.use_expiry_date,
            'is_batch_mandatory': profile.is_batch_mandatory,
            'is_expiry_mandatory': profile.is_expiry_mandatory,
            'roles_can_stock_in': list(profile.roles_can_stock_in.values_list('id', flat=True)),
            'roles_can_stock_out': list(profile.roles_can_stock_out.values_list('id', flat=True)),
            'roles_can_transfer': list(profile.roles_can_transfer.values_list('id', flat=True)),
        }

        AuditLogService.log(
            action_type='INVENTORY_SETTINGS_UPDATED',
            module='settings',
            actor=user,
            record_id=profile.id,
            record_name="إعدادات وسياسات المخازن",
            description="تحديث سياسات التشغيلات والصلاحيات وأذونات المخازن والتحويلات",
            previous_values=old_values,
            new_values=new_values,
            status='SUCCESS',
            request=request,
        )
        return profile

    @classmethod
    @transaction.atomic
    def update_user_settings(cls, user, data, request=None) -> UserSettings:
        """Updates representative resource auto-provisioning settings with audit logging."""
        u_settings = cls.get_user_settings(force_refresh=True)
        old_values = {
            'auto_create_rep_warehouse': u_settings.auto_create_rep_warehouse,
            'auto_create_rep_treasury': u_settings.auto_create_rep_treasury,
        }

        u_settings.auto_create_rep_warehouse = data.get('auto_create_rep_warehouse') in ('on', '1', 'true', True)
        u_settings.auto_create_rep_treasury = data.get('auto_create_rep_treasury') in ('on', '1', 'true', True)
        u_settings.save()
        cls.clear_cache('user_settings')

        new_values = {
            'auto_create_rep_warehouse': u_settings.auto_create_rep_warehouse,
            'auto_create_rep_treasury': u_settings.auto_create_rep_treasury,
        }

        AuditLogService.log(
            action_type='SETTINGS_UPDATED',
            module='settings',
            actor=user,
            record_id=u_settings.id,
            record_name="إعدادات موارد المستخدمين",
            description="تحديث إعدادات التخصيص التلقائي لمخازن وخزن المناديب",
            previous_values=old_values,
            new_values=new_values,
            status='SUCCESS',
            request=request,
        )
        return u_settings


def _on_settings_model_changed(sender, **kwargs):
    SettingsService.clear_cache()


for _model_cls in (CompanyProfile, LocationSettings, SalesSettings, PurchaseSettings, UserSettings):
    post_save.connect(_on_settings_model_changed, sender=_model_cls)
    post_delete.connect(_on_settings_model_changed, sender=_model_cls)

