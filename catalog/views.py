from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q
from .models import Product, ProductCategory


@login_required
def products_list(request):
    search = request.GET.get('search', '').strip()
    category_id = request.GET.get('category')

    qs = Product.objects.select_related('category').all()

    if category_id:
        qs = qs.filter(category_id=category_id)

    if search:
        qs = qs.filter(
            Q(name__icontains=search) |
            Q(sku_code__icontains=search) |
            Q(description__icontains=search)
        )

    categories = ProductCategory.objects.all()

    context = {
        'products': qs,
        'categories': categories,
        'selected_category': category_id,
        'search_query': search,
        'total_count': qs.count()
    }
    return render(request, 'catalog/products_list.html', context)


@login_required
def product_create(request):
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        sku_code = request.POST.get('sku_code', '').strip()
        category_id = request.POST.get('category')
        retail_price = request.POST.get('retail_price') or '0.00'
        default_purchase_cost = request.POST.get('default_purchase_cost') or '0.00'
        tax_percentage = request.POST.get('tax_percentage') or '0.00'
        unit = request.POST.get('unit') or 'عبوة'
        description = request.POST.get('description', '').strip()
        sellable = request.POST.get('sellable') == 'on'

        if not name or not sku_code or not category_id:
            messages.error(request, "يرجى ملء جميع الحقول الإلزامية (الاسم، كود الصنف، والتصنيف).")
            return redirect('products_list')

        category = get_object_or_404(ProductCategory, id=category_id)

        product = Product.objects.create(
            name=name,
            sku_code=sku_code,
            category=category,
            retail_price=Decimal(retail_price),
            default_purchase_cost=Decimal(default_purchase_cost),
            tax_percentage=Decimal(tax_percentage),
            unit=unit,
            description=description,
            sellable=sellable,
            created_by=request.user
        )

        messages.success(request, f"تم إنشاء المنتج '{product.name}' بنجاح ({product.sku_code}).")
        return redirect('products_list')

    return redirect('products_list')


@login_required
def categories_list(request):
    categories = ProductCategory.objects.all()
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        code = request.POST.get('code', '').strip()
        description = request.POST.get('description', '').strip()
        if name and code:
            ProductCategory.objects.create(name=name, code=code, description=description)
            messages.success(request, f"تم إنشاء التصنيف '{name}' بنجاح.")
        return redirect('categories_list')

    return render(request, 'catalog/categories_list.html', {'categories': categories})
