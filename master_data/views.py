from decimal import Decimal
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Sum, Count
from purchases.models import PurchaseOrder
from treasury.models import VendorAccount, Vault
from catalog.models import Product
from contacts.models import Contact
from inventory.models import InventoryStock
from .models import CompanyProfile


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
