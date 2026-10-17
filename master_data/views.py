from decimal import Decimal
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Sum, Count
from django.http import JsonResponse
from purchases.models import PurchaseOrder
from treasury.models import VendorAccount, Vault
from catalog.models import Product
from contacts.models import Contact
from inventory.models import InventoryStock
from .models import CompanyProfile, LocationSettings



@login_required
def home_view(request):
    """
    Executive Home Dashboard matching the reference ERP widgets and KPIs.
    """
    # KPI 1: Purchases Volume
    total_purchases_amount = PurchaseOrder.objects.exclude(status='cancelled').aggregate(total=Sum('grand_total'))['total'] or Decimal('0.00')
    orders_count = PurchaseOrder.objects.count()

    # KPI 2: Supplier Payables / Outstanding Balance
    total_vendor_payables = VendorAccount.objects.aggregate(total=Sum('current_balance'))['total'] or Decimal('0.00')

    # KPI 3: Treasury Cash on Hand
    total_vault_cash = Vault.objects.aggregate(total=Sum('current_balance'))['total'] or Decimal('0.00')

    # KPI 4: Stock Valuation
    products_count = Product.objects.filter(is_active=True).count()
    stocks = InventoryStock.objects.select_related('product')
    total_inventory_valuation = sum((s.total_cost for s in stocks), Decimal('0.00'))

    # Recent Orders
    recent_orders = PurchaseOrder.objects.select_related('supplier', 'created_by').order_by('-created_at')[:8]

    # Suppliers count
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


@login_required
def branding_settings_view(request):
    profile = CompanyProfile.get_settings()
    if request.method == 'POST':
        profile.company_name = request.POST.get('company_name', profile.company_name)
        profile.commercial_registry = request.POST.get('commercial_registry', profile.commercial_registry)
        profile.tax_id = request.POST.get('tax_id', profile.tax_id)
        profile.phone = request.POST.get('phone', profile.phone)
        profile.address = request.POST.get('address', profile.address)
        profile.email = request.POST.get('email', profile.email)
        profile.use_batch_number = request.POST.get('use_batch_number') == 'on'
        profile.use_expiry_date = request.POST.get('use_expiry_date') == 'on'
        profile.save()
        messages.success(request, "تم حفظ إعدادات الشركة وبيانات الفاتورة بنجاح.")
        return redirect('branding_settings')

    return render(request, 'dashboard/branding_settings.html', {'profile': profile})


def is_superuser_or_admin(user):
    return user.is_authenticated and (user.is_superuser or getattr(user, 'is_super_admin', False))


@login_required
def location_settings_view(request):
    """
    Superuser-only Location Settings view matching https://weapharma.bricks-rep.com/settings/location
    """
    if not is_superuser_or_admin(request.user):
        messages.error(request, "عذراً، هذه الإعدادات مخصصة لمدراء النظام فقط (SuperAdmin).")
        return redirect('home')

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
        loc_settings.verify_visits = request.POST.get('verify_visits') == 'on'
        loc_settings.verify_sales_orders = request.POST.get('verify_sales_orders') == 'on'
        loc_settings.verify_sales_returns = request.POST.get('verify_sales_returns') == 'on'
        loc_settings.verify_collections = request.POST.get('verify_collections') == 'on'
        loc_settings.verify_purchase_orders = request.POST.get('verify_purchase_orders') == 'on'
        loc_settings.verify_purchase_returns = request.POST.get('verify_purchase_returns') == 'on'
        loc_settings.save()
        messages.success(request, "تم حفظ إعدادات الموقع والتحقق بنجاح.")
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

