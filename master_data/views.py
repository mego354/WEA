from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Sum, Count, Q
from django.http import JsonResponse, HttpResponse
from django.utils import timezone
from purchases.models import PurchaseOrder
from treasury.models import VendorAccount, Vault
from catalog.models import Product
from contacts.models import Contact
from inventory.models import InventoryStock
from accounts.permissions import require_permission, has_perm_or_admin
from .models import (
    CompanyProfile, LocationSettings, Area, ExpenseType,
    TicketType, ApprovalRequestType, AgreementType,
    SalesSettings, PurchaseSettings, ContactFieldSetting,
    DataSyncConfig
)


@login_required
def home_view(request):
    """
    Executive Home Dashboard matching the reference ERP widgets and KPIs.
    """
    total_purchases_amount = PurchaseOrder.objects.exclude(status='cancelled').aggregate(total=Sum('grand_total'))['total'] or Decimal('0.00')
    orders_count = PurchaseOrder.objects.count()
    total_vendor_payables = VendorAccount.objects.aggregate(total=Sum('current_balance'))['total'] or Decimal('0.00')
    total_vault_cash = Vault.objects.aggregate(total=Sum('current_balance'))['total'] or Decimal('0.00')

    products_count = Product.objects.filter(is_active=True).count()
    stocks = InventoryStock.objects.select_related('product')
    total_inventory_valuation = sum((s.total_cost for s in stocks), Decimal('0.00'))

    recent_orders = PurchaseOrder.objects.select_related('supplier', 'created_by').order_by('-created_at')[:8]
    suppliers_count = Contact.objects.filter(is_supplier=True).count()
    customers_count = Contact.objects.filter(is_customer=True).count()

    context = {
        'total_purchases_amount': total_purchases_amount,
        'orders_count': orders_count,
        'total_vendor_payables': total_vendor_payables,
        'total_vault_cash': total_vault_cash,
        'products_count': products_count,
        'total_inventory_valuation': total_inventory_valuation,
        'recent_orders': recent_orders,
        'suppliers_count': suppliers_count,
        'customers_count': customers_count,
    }
    return render(request, 'dashboard/home.html', context)


# ==========================================
# 1. COMPANY BRANDING SETTINGS (/settings/branding)
# ==========================================

@login_required
@require_permission('settings:branding/edit')
def branding_settings_view(request):
    profile = CompanyProfile.get_settings()
    if request.method == 'POST':
        profile.company_name = request.POST.get('company_name', profile.company_name).strip()
        profile.commercial_registry = request.POST.get('commercial_registry', profile.commercial_registry).strip()
        profile.tax_id = request.POST.get('tax_id', profile.tax_id).strip()
        profile.phone = request.POST.get('phone', profile.phone).strip()
        profile.address = request.POST.get('address', profile.address).strip()
        profile.email = request.POST.get('email', profile.email).strip()

        if 'logo' in request.FILES:
            profile.logo = request.FILES['logo']

        profile.save()
        messages.success(request, "تم حفظ إعدادات بيانات الشركة بنجاح.")
        return redirect('branding_settings')

    return render(request, 'settings/branding_settings.html', {'profile': profile})


# ==========================================
# 2. LOCATION SETTINGS (/settings/location)
# ==========================================

@login_required
@require_permission('settings:location/manage')
def location_settings_view(request):
    """
    Location settings view matching https://weapharma.bricks-rep.com/settings/location
    """
    loc_settings = LocationSettings.get_settings()

    if request.method == 'POST':
        try:
            loc_settings.tolerance = int(request.POST.get('tolerance', 300))
            loc_settings.max_verified_accuracy = int(request.POST.get('max_verified_accuracy', 50))
            loc_settings.max_verified_warn_accuracy = int(request.POST.get('max_verified_warn_accuracy', 100))
        except (ValueError, TypeError):
            pass

        loc_settings.auto_start_location_tracking_service = request.POST.get('auto_start_location_tracking_service') == 'on'
        loc_settings.auto_set_customer_location_in_visit = request.POST.get('auto_set_customer_location_in_visit') == 'on'

        # Workflow verification dropdowns
        loc_settings.verify_visits = request.POST.get('verify_visits') == '1'
        loc_settings.verify_sales_orders = request.POST.get('verify_sales_orders') == '1'
        loc_settings.verify_sales_returns = request.POST.get('verify_sales_returns') == '1'
        loc_settings.save()

        messages.success(request, "تم حفظ إعدادات الموقع بنجاح.")
        return redirect('location_settings')

    return render(request, 'settings/location_settings.html', {'settings': loc_settings})


@login_required
def geofence_settings_api(request):
    """API endpoint returning geofence settings, matching /api/v1/geofence/settings."""
    loc_settings = LocationSettings.get_settings()
    return JsonResponse({
        'settings': {
            'tolerance': loc_settings.tolerance,
            'auto_start_location_tracking_service': loc_settings.auto_start_location_tracking_service,
            'auto_set_customer_location_in_visit': loc_settings.auto_set_customer_location_in_visit,
            'max_verified_accuracy': loc_settings.max_verified_accuracy,
            'max_verified_warn_accuracy': loc_settings.max_verified_warn_accuracy,
            'verify_visits': loc_settings.verify_visits,
        }
    })


# ==========================================
# 3. AREAS MANAGEMENT (/settings/areas)
# ==========================================

@login_required
@require_permission('settings:areas/manage')
def areas_settings_view(request):
    """
    Geographical areas tree matching reference ERP:
    Collapsible governorates with subareas, code display, and 3-dot action menu.
    """
    governorates = Area.objects.filter(parent__isnull=True).prefetch_related('subareas').order_by('code', 'name')
    return render(request, 'settings/areas_settings.html', {'governorates': governorates})


@login_required
@require_permission('settings:areas/manage')
def area_create(request):
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        code = request.POST.get('code', '').strip()
        parent_id = request.POST.get('parent', '')

        if not name or not code:
            messages.error(request, "اسم المنطقة وكود المنطقة حقول إلزامية.")
            return redirect('areas_settings')

        if Area.objects.filter(code__iexact=code).exists():
            messages.error(request, f"كود المنطقة '{code}' مستخدم بالفعل.")
            return redirect('areas_settings')

        parent = None
        area_type = 'governorate'
        if parent_id:
            parent = Area.objects.filter(pk=parent_id).first()
            if parent:
                area_type = 'subarea'

        Area.objects.create(name=name, code=code, area_type=area_type, parent=parent)
        messages.success(request, f"تم إضافة المنطقة '{name}' بنجاح.")
        return redirect('areas_settings')

    return redirect('areas_settings')


@login_required
@require_permission('settings:areas/manage')
def area_edit(request, pk):
    area = get_object_or_404(Area, pk=pk)
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        code = request.POST.get('code', '').strip()

        if not name or not code:
            messages.error(request, "الاسم والكود حقول إلزامية.")
            return redirect('areas_settings')

        if Area.objects.filter(code__iexact=code).exclude(pk=area.pk).exists():
            messages.error(request, f"الكود '{code}' مستخدم لمنطقة أخرى.")
            return redirect('areas_settings')

        area.name = name
        area.code = code
        area.save()
        messages.success(request, f"تم تحديث بيانات المنطقة '{area.name}' بنجاح.")
        return redirect('areas_settings')

    return redirect('areas_settings')


@login_required
@require_permission('settings:areas/manage')
def area_delete(request, pk):
    area = get_object_or_404(Area, pk=pk)
    if area.subareas.exists():
        messages.error(request, f"لا يمكن حذف المنطقة '{area.name}' لأنها تحتوي على {area.subareas.count()} منطقة فرعية.")
        return redirect('areas_settings')

    name = area.name
    area.delete()
    messages.success(request, f"تم حذف المنطقة '{name}' بنجاح.")
    return redirect('areas_settings')


# ==========================================
# 4. EXPENSE TYPES (/settings/expenses)
# ==========================================

@login_required
@require_permission('settings:expenses/manage')
def expenses_settings_view(request):
    active_tab = request.GET.get('tab', 'general')
    expenses = ExpenseType.objects.filter(category=active_tab, is_active=True).order_by('id')
    return render(request, 'settings/expenses_settings.html', {
        'expenses': expenses,
        'active_tab': active_tab,
    })


@login_required
@require_permission('settings:expenses/manage')
def expense_create(request):
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        name_en = request.POST.get('name_en', '').strip()
        category = request.POST.get('category', 'general')
        unit = request.POST.get('unit', 'الوحدة').strip()

        if not name:
            messages.error(request, "اسم المصروف بالعربية حقل إلزامي.")
            return redirect(f'/settings/expenses/?tab={category}')

        ExpenseType.objects.create(name=name, name_en=name_en, category=category, unit=unit)
        messages.success(request, f"تم إضافة نوع المصروف '{name}' بنجاح.")
        return redirect(f'/settings/expenses/?tab={category}')

    return redirect('expenses_settings')


@login_required
@require_permission('settings:expenses/manage')
def expense_edit(request, pk):
    expense = get_object_or_404(ExpenseType, pk=pk)
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        name_en = request.POST.get('name_en', '').strip()
        unit = request.POST.get('unit', 'الوحدة').strip()

        if not name:
            messages.error(request, "اسم المصروف بالعربية حقل إلزامي.")
            return redirect(f'/settings/expenses/?tab={expense.category}')

        expense.name = name
        expense.name_en = name_en
        expense.unit = unit
        expense.save()
        messages.success(request, f"تم تحديث بيانات نوع المصروف '{name}' بنجاح.")
        return redirect(f'/settings/expenses/?tab={expense.category}')

    return redirect('expenses_settings')


@login_required
@require_permission('settings:expenses/manage')
def expense_delete(request, pk):
    expense = get_object_or_404(ExpenseType, pk=pk)
    cat = expense.category
    name = expense.name
    expense.delete()
    messages.success(request, f"تم حذف نوع المصروف '{name}' بنجاح.")
    return redirect(f'/settings/expenses/?tab={cat}')


# ==========================================
# 5. TICKET TYPES (/settings/tickets)
# ==========================================

@login_required
@require_permission('settings:tickets/manage')
def tickets_settings_view(request):
    tickets = TicketType.objects.filter(is_active=True).order_by('-is_default', 'id')
    return render(request, 'settings/tickets_settings.html', {'tickets': tickets})


@login_required
@require_permission('settings:tickets/manage')
def ticket_create(request):
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        if not name:
            messages.error(request, "نوع المهمة حقل إلزامي.")
            return redirect('tickets_settings')

        TicketType.objects.create(name=name, is_default=False)
        messages.success(request, f"تم إضافة نوع المهمة '{name}' بنجاح.")
        return redirect('tickets_settings')

    return redirect('tickets_settings')


@login_required
@require_permission('settings:tickets/manage')
def ticket_edit(request, pk):
    ticket = get_object_or_404(TicketType, pk=pk)
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        if not name:
            messages.error(request, "نوع المهمة حقل إلزامي.")
            return redirect('tickets_settings')

        ticket.name = name
        ticket.save()
        messages.success(request, f"تم تحديث نوع المهمة '{name}' بنجاح.")
        return redirect('tickets_settings')

    return redirect('tickets_settings')


@login_required
@require_permission('settings:tickets/manage')
def ticket_delete(request, pk):
    ticket = get_object_or_404(TicketType, pk=pk)
    if ticket.is_default:
        messages.error(request, "لا يمكن حذف نوع المهمة الافتراضي للنظام.")
        return redirect('tickets_settings')

    name = ticket.name
    ticket.delete()
    messages.success(request, f"تم حذف نوع المهمة '{name}' بنجاح.")
    return redirect('tickets_settings')


# ==========================================
# 6. APPROVAL REQUEST TYPES (/settings/requests)
# ==========================================

@login_required
@require_permission('settings:requests/manage')
def requests_settings_view(request):
    requests_list = ApprovalRequestType.objects.filter(is_active=True).order_by('-is_default', 'id')
    return render(request, 'settings/requests_settings.html', {'requests_list': requests_list})


@login_required
@require_permission('settings:requests/manage')
def request_type_create(request):
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        if not name:
            messages.error(request, "نوع الموافقة حقل إلزامي.")
            return redirect('requests_settings')

        ApprovalRequestType.objects.create(name=name, is_default=False)
        messages.success(request, f"تم إضافة نوع الموافقة '{name}' بنجاح.")
        return redirect('requests_settings')

    return redirect('requests_settings')


@login_required
@require_permission('settings:requests/manage')
def request_type_edit(request, pk):
    req_type = get_object_or_404(ApprovalRequestType, pk=pk)
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        if not name:
            messages.error(request, "نوع الموافقة حقل إلزامي.")
            return redirect('requests_settings')

        req_type.name = name
        req_type.save()
        messages.success(request, f"تم تحديث نوع الموافقة '{name}' بنجاح.")
        return redirect('requests_settings')

    return redirect('requests_settings')


@login_required
@require_permission('settings:requests/manage')
def request_type_delete(request, pk):
    req_type = get_object_or_404(ApprovalRequestType, pk=pk)
    if req_type.is_default:
        messages.error(request, "لا يمكن حذف نوع الموافقة الافتراضي للنظام.")
        return redirect('requests_settings')

    name = req_type.name
    req_type.delete()
    messages.success(request, f"تم حذف نوع الموافقة '{name}' بنجاح.")
    return redirect('requests_settings')


# ==========================================
# 7. AGREEMENT TYPES (/settings/agreements)
# ==========================================

@login_required
@require_permission('settings:agreements/manage')
def agreements_settings_view(request):
    agreements = AgreementType.objects.filter(is_active=True).order_by('id')
    return render(request, 'settings/agreements_settings.html', {'agreements': agreements})


@login_required
@require_permission('settings:agreements/manage')
def agreement_create(request):
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        if not name:
            messages.error(request, "نوع الاتفاقية حقل إلزامي.")
            return redirect('agreements_settings')

        AgreementType.objects.create(name=name)
        messages.success(request, f"تم إضافة نوع الاتفاقية '{name}' بنجاح.")
        return redirect('agreements_settings')

    return redirect('agreements_settings')


@login_required
@require_permission('settings:agreements/manage')
def agreement_edit(request, pk):
    agreement = get_object_or_404(AgreementType, pk=pk)
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        if not name:
            messages.error(request, "نوع الاتفاقية حقل إلزامي.")
            return redirect('agreements_settings')

        agreement.name = name
        agreement.save()
        messages.success(request, f"تم تحديث نوع الاتفاقية '{name}' بنجاح.")
        return redirect('agreements_settings')

    return redirect('agreements_settings')


@login_required
@require_permission('settings:agreements/manage')
def agreement_delete(request, pk):
    agreement = get_object_or_404(AgreementType, pk=pk)
    name = agreement.name
    agreement.delete()
    messages.success(request, f"تم حذف نوع الاتفاقية '{name}' بنجاح.")
    return redirect('agreements_settings')


# ==========================================
# 8. SALES SETTINGS (/settings/sales)
# ==========================================

@login_required
@require_permission('settings:sales/manage')
def sales_settings_view(request):
    sales_settings = SalesSettings.get_settings()
    if request.method == 'POST':
        sales_settings.require_verification_manager = request.POST.get('require_verification_manager') == 'on'
        sales_settings.auto_invoice_on_dispatch = request.POST.get('auto_invoice_on_dispatch') == 'on'
        sales_settings.auto_invoice_on_return = request.POST.get('auto_invoice_on_return') == 'on'
        sales_settings.collect_payment_on_invoicing = request.POST.get('collect_payment_on_invoicing') == 'on'
        sales_settings.auto_link_accounting_on_collection = request.POST.get('auto_link_accounting_on_collection') == 'on'
        sales_settings.use_receipt_books = request.POST.get('use_receipt_books') == 'on'
        sales_settings.auto_close_cash_collection = request.POST.get('auto_close_cash_collection') == 'on'
        sales_settings.auto_close_collection_on_full_payment = request.POST.get('auto_close_collection_on_full_payment') == 'on'

        sales_settings.tax_mode = request.POST.get('tax_mode', 'optional')
        sales_settings.default_packaging_unit = request.POST.get('default_packaging_unit', 'box')
        sales_settings.save()

        messages.success(request, "تم حفظ إعدادات المبيعات بنجاح.")
        return redirect('sales_settings')

    return render(request, 'settings/sales_settings.html', {'settings': sales_settings})


# ==========================================
# 9. PURCHASE SETTINGS (/settings/purchase)
# ==========================================

@login_required
@require_permission('settings:purchase/manage')
def purchase_settings_view(request):
    purchase_settings = PurchaseSettings.get_settings()
    if request.method == 'POST':
        purchase_settings.auto_invoice_on_dispatch = request.POST.get('auto_invoice_on_dispatch') == 'on'
        purchase_settings.auto_invoice_on_return = request.POST.get('auto_invoice_on_return') == 'on'
        purchase_settings.collect_payment_on_invoicing = request.POST.get('collect_payment_on_invoicing') == 'on'
        purchase_settings.auto_link_accounting_on_payment = request.POST.get('auto_link_accounting_on_payment') == 'on'
        purchase_settings.auto_close_cash_payment = request.POST.get('auto_close_cash_payment') == 'on'
        purchase_settings.auto_close_payment_on_full_settlement = request.POST.get('auto_close_payment_on_full_settlement') == 'on'

        purchase_settings.tax_mode = request.POST.get('tax_mode', 'optional')
        purchase_settings.default_packaging_unit = request.POST.get('default_packaging_unit', 'piece')
        purchase_settings.save()

        messages.success(request, "تم حفظ إعدادات المشتريات بنجاح.")
        return redirect('purchase_settings')

    return render(request, 'settings/purchase_settings.html', {'settings': purchase_settings})


# ==========================================
# 10. INVENTORY SETTINGS (/settings/inventory)
# ==========================================

@login_required
@require_permission('settings:inventory/manage')
def inventory_settings_view(request):
    profile = CompanyProfile.get_settings()
    if request.method == 'POST':
        profile.use_expiry_date = request.POST.get('use_expiry_date') == 'on'
        profile.is_expiry_mandatory = request.POST.get('is_expiry_mandatory') == 'on'
        profile.use_batch_number = request.POST.get('use_batch_number') == 'on'
        profile.is_batch_mandatory = request.POST.get('is_batch_mandatory') == 'on'
        profile.save()

        messages.success(request, "تم حفظ إعدادات المخازن بنجاح.")
        return redirect('inventory_settings')

    return render(request, 'settings/inventory_settings.html', {'profile': profile})


# ==========================================
# 11. CONTACT CUSTOM FIELDS (/settings/contacts-udf)
# ==========================================

@login_required
@require_permission('settings:contactsUdf/manage')
def contacts_udf_view(request):
    fields = ContactFieldSetting.objects.all().order_by('section', 'order')
    header_fields = fields.filter(section='header')
    subheader_fields = fields.filter(section='subheader')
    basic_fields = fields.filter(section='basic')

    if request.method == 'POST':
        field_id = request.POST.get('field_id')
        if field_id:
            field = get_object_or_404(ContactFieldSetting, pk=field_id)
            if not field.is_locked:
                field.is_required = request.POST.get('is_required') == 'on'
                field.is_filterable = request.POST.get('is_filterable') == 'on'
                field.save()
                messages.success(request, f"تم حفظ تخصيص الحقل '{field.display_name}'.")
        return redirect('contacts_udf')

    return render(request, 'settings/contacts_udf.html', {
        'header_fields': header_fields,
        'subheader_fields': subheader_fields,
        'basic_fields': basic_fields,
    })


# ==========================================
# 12. DATA SYNC (/settings/sync-data)
# ==========================================

@login_required
@require_permission('settings:syncData/manage')
def sync_data_view(request):
    configs = {c.sync_type: c for c in DataSyncConfig.objects.all()}
    if request.method == 'POST':
        sync_type = request.POST.get('sync_type')
        sheet_url = request.POST.get('google_sheet_url', '').strip()

        cfg = DataSyncConfig.objects.filter(sync_type=sync_type).first()
        if cfg:
            cfg.google_sheet_url = sheet_url
            cfg.save()
            messages.success(request, f"تم حفظ رابط جدول بيانات جوجل لـ '{cfg.title}'.")
        return redirect('sync_data')

    return render(request, 'settings/sync_data.html', {'configs': configs})


@login_required
@require_permission('settings:syncData/manage')
def sync_data_trigger(request, sync_type):
    cfg = get_object_or_404(DataSyncConfig, sync_type=sync_type)
    cfg.last_synced_at = timezone.now()
    cfg.status = 'success'
    cfg.save()

    messages.success(request, f"تم بدء مزامنة '{cfg.title}' بنجاح.")
    return redirect('sync_data')
