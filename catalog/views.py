import csv
from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q
from django.core.paginator import Paginator
from django.http import HttpResponse, JsonResponse
from .models import Product, ProductCategory, ProductVolumeDiscountTier, ProductPriceList
from inventory.models import InventoryStock



@login_required
def products_list(request):
    search = request.GET.get('search', '').strip()
    category_id = request.GET.get('category')
    sellable_filter = request.GET.get('sellable')
    min_price = request.GET.get('min_price')
    max_price = request.GET.get('max_price')

    qs = Product.objects.select_related('category').all().order_by('name')

    active_filters_count = 0

    if category_id:
        qs = qs.filter(category_id=category_id)
        active_filters_count += 1

    if sellable_filter in ['true', '1', 'yes']:
        qs = qs.filter(sellable=True)
        active_filters_count += 1
    elif sellable_filter in ['false', '0', 'no']:
        qs = qs.filter(sellable=False)
        active_filters_count += 1

    if min_price:
        try:
            qs = qs.filter(retail_price__gte=Decimal(min_price))
            active_filters_count += 1
        except Exception:
            pass

    if max_price:
        try:
            qs = qs.filter(retail_price__lte=Decimal(max_price))
            active_filters_count += 1
        except Exception:
            pass

    if search:
        qs = qs.filter(
            Q(name__icontains=search) |
            Q(sku_code__icontains=search) |
            Q(barcode__icontains=search) |
            Q(description__icontains=search)
        )

    categories = ProductCategory.objects.all().order_by('name')

    # Pagination: 40 per page matching reference ERP
    page_size = int(request.GET.get('page_size', 40))
    paginator = Paginator(qs, page_size)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    context = {
        'products': page_obj.object_list,
        'page_obj': page_obj,
        'paginator': paginator,
        'categories': categories,
        'selected_category': category_id,
        'sellable_filter': sellable_filter,
        'min_price': min_price,
        'max_price': max_price,
        'search_query': search,
        'active_filters_count': active_filters_count,
        'total_count': qs.count(),
    }
    return render(request, 'catalog/products_list.html', context)


@login_required
def product_create(request):
    categories = ProductCategory.objects.all().order_by('name')
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        sku_code = request.POST.get('sku_code', '').strip()
        category_id = request.POST.get('category')
        barcode = request.POST.get('barcode', '').strip()
        retail_price = request.POST.get('retail_price') or '0.00'
        default_purchase_cost = request.POST.get('default_purchase_cost') or '0.00'
        tax_percentage = request.POST.get('tax_percentage') or '0.00'
        unit = request.POST.get('unit') or 'عبوة'
        description = request.POST.get('description', '').strip()
        sellable = request.POST.get('sellable') in ['on', 'true', '1']
        has_volume_discounts = request.POST.get('has_volume_discounts') in ['on', 'true', '1']
        packing_boxes = request.POST.get('packing_boxes', '').strip()
        packing_cartons = request.POST.get('packing_cartons', '').strip()

        if not name or not sku_code:
            messages.error(request, "يرجى ملء الاسم وكود المنتج (SKU).")
            return render(request, 'catalog/product_form.html', {
                'categories': categories,
                'is_create': True
            })

        category = ProductCategory.objects.filter(id=category_id).first() if category_id else categories.first()
        if not category:
            category = ProductCategory.objects.create(name='WEA', code='WEA')

        thumbnail = request.FILES.get('thumbnail')

        product = Product.objects.create(
            name=name,
            sku_code=sku_code,
            category=category,
            barcode=barcode,
            retail_price=Decimal(retail_price),
            default_purchase_cost=Decimal(default_purchase_cost),
            tax_percentage=Decimal(tax_percentage),
            unit=unit,
            description=description,
            sellable=sellable,
            has_volume_discounts=has_volume_discounts,
            packing_boxes=packing_boxes,
            packing_cartons=packing_cartons,
            thumbnail=thumbnail,
            created_by=request.user
        )

        # Volume discount tiers
        if has_volume_discounts:
            min_qtys = request.POST.getlist('volume_min_qty[]')
            disc_pcts = request.POST.getlist('volume_disc_pct[]')
            for mq, dp in zip(min_qtys, disc_pcts):
                if mq and dp:
                    try:
                        ProductVolumeDiscountTier.objects.create(
                            product=product,
                            min_quantity=Decimal(mq),
                            discount_percentage=Decimal(dp)
                        )
                    except Exception:
                        pass

        # Price lists
        pl_names = request.POST.getlist('price_list_name[]')
        pl_prices = request.POST.getlist('price_list_price[]')
        for pln, plp in zip(pl_names, pl_prices):
            if pln and plp:
                try:
                    ProductPriceList.objects.create(
                        product=product,
                        name=pln.strip(),
                        price=Decimal(plp)
                    )
                except Exception:
                    pass

        messages.success(request, f"تم إنشاء المنتج '{product.name}' بنجاح ({product.sku_code}).")
        return redirect('products_list')

    return render(request, 'catalog/product_form.html', {
        'categories': categories,
        'is_create': True
    })


@login_required
def product_edit(request, pk):
    product = get_object_or_404(Product, pk=pk)
    categories = ProductCategory.objects.all().order_by('name')

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        sku_code = request.POST.get('sku_code', '').strip()
        category_id = request.POST.get('category')
        barcode = request.POST.get('barcode', '').strip()
        retail_price = request.POST.get('retail_price') or '0.00'
        default_purchase_cost = request.POST.get('default_purchase_cost') or '0.00'
        tax_percentage = request.POST.get('tax_percentage') or '0.00'
        unit = request.POST.get('unit') or 'عبوة'
        description = request.POST.get('description', '').strip()
        sellable = request.POST.get('sellable') in ['on', 'true', '1']
        has_volume_discounts = request.POST.get('has_volume_discounts') in ['on', 'true', '1']
        packing_boxes = request.POST.get('packing_boxes', '').strip()
        packing_cartons = request.POST.get('packing_cartons', '').strip()

        if name:
            product.name = name
        if sku_code:
            product.sku_code = sku_code
        if category_id:
            category = ProductCategory.objects.filter(id=category_id).first()
            if category:
                product.category = category

        product.barcode = barcode
        product.retail_price = Decimal(retail_price)
        product.default_purchase_cost = Decimal(default_purchase_cost)
        product.tax_percentage = Decimal(tax_percentage)
        product.unit = unit
        product.description = description
        product.sellable = sellable
        product.has_volume_discounts = has_volume_discounts
        product.packing_boxes = packing_boxes
        product.packing_cartons = packing_cartons

        if request.FILES.get('thumbnail'):
            product.thumbnail = request.FILES['thumbnail']

        product.save()

        # Update volume discount tiers
        product.volume_discounts.all().delete()
        if has_volume_discounts:
            min_qtys = request.POST.getlist('volume_min_qty[]')
            disc_pcts = request.POST.getlist('volume_disc_pct[]')
            for mq, dp in zip(min_qtys, disc_pcts):
                if mq and dp:
                    try:
                        ProductVolumeDiscountTier.objects.create(
                            product=product,
                            min_quantity=Decimal(mq),
                            discount_percentage=Decimal(dp)
                        )
                    except Exception:
                        pass

        # Update price lists
        product.price_lists.all().delete()
        pl_names = request.POST.getlist('price_list_name[]')
        pl_prices = request.POST.getlist('price_list_price[]')
        for pln, plp in zip(pl_names, pl_prices):
            if pln and plp:
                try:
                    ProductPriceList.objects.create(
                        product=product,
                        name=pln.strip(),
                        price=Decimal(plp)
                    )
                except Exception:
                    pass

        messages.success(request, f"تم تحديث بيانات المنتج '{product.name}' بنجاح.")
        return redirect('products_list')

    return render(request, 'catalog/product_form.html', {
        'product': product,
        'categories': categories,
        'is_create': False
    })



@login_required
def product_detail(request, pk):
    product = get_object_or_404(
        Product.objects.select_related('category', 'created_by').prefetch_related('volume_discounts', 'price_lists'),
        pk=pk
    )
    stocks = InventoryStock.objects.filter(product=product).select_related('warehouse')
    total_stock = sum((s.qty_on_hand for s in stocks), Decimal('0.00'))

    context = {
        'product': product,
        'stocks': stocks,
        'total_stock': total_stock,
        'volume_discounts': product.volume_discounts.all(),
        'price_lists': product.price_lists.all(),
    }
    return render(request, 'catalog/product_detail.html', context)


@login_required
def product_delete(request, pk):
    product = get_object_or_404(Product, pk=pk)
    if request.method == 'POST':
        name = product.name
        code = product.sku_code
        product.delete()
        messages.success(request, f"تم حذف المنتج '{name}' ({code}) بنجاح.")
        return redirect('products_list')
    return redirect('product_detail', pk=pk)


@login_required
def products_export(request):
    search = request.GET.get('search', '').strip()
    category_id = request.GET.get('category')
    sellable_filter = request.GET.get('sellable')

    qs = Product.objects.select_related('category').all().order_by('name')

    if category_id:
        qs = qs.filter(category_id=category_id)
    if sellable_filter in ['true', '1']:
        qs = qs.filter(sellable=True)
    elif sellable_filter in ['false', '0']:
        qs = qs.filter(sellable=False)
    if search:
        qs = qs.filter(
            Q(name__icontains=search) |
            Q(sku_code__icontains=search) |
            Q(barcode__icontains=search)
        )

    response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
    response['Content-Disposition'] = 'attachment; filename="products_export.csv"'
    writer = csv.writer(response)
    writer.writerow(['الاسم', 'الكود', 'التصنيف', 'السعر', 'قيمة الضريبة', 'متاح للبيع', 'باركود', 'تاريخ الإنشاء'])

    for p in qs:
        writer.writerow([
            p.name,
            p.sku_code,
            p.category.name if p.category else '',
            f"{p.retail_price:,.2f}",
            f"{p.tax_percentage}%",
            'نعم' if p.sellable else 'لا',
            p.barcode or '',
            p.created_at.strftime('%Y-%m-%d %H:%M') if p.created_at else ''
        ])

    return response


@login_required
def categories_list(request):
    categories = ProductCategory.objects.all().order_by('name')
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        code = request.POST.get('code', '').strip()
        description = request.POST.get('description', '').strip()
        if name and code:
            ProductCategory.objects.create(name=name, code=code, description=description)
            messages.success(request, f"تم إنشاء التصنيف '{name}' بنجاح.")
        else:
            messages.error(request, "يرجى إدخال اسم التصنيف والكود.")
        return redirect('categories_list')

    return render(request, 'catalog/categories_list.html', {'categories': categories})


@login_required
def category_edit(request, pk):
    cat = get_object_or_404(ProductCategory, pk=pk)
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        code = request.POST.get('code', '').strip()
        description = request.POST.get('description', '').strip()
        if name and code:
            cat.name = name
            cat.code = code
            cat.description = description
            cat.save()
            messages.success(request, f"تم تحديث بيانات التصنيف '{cat.name}' بنجاح.")
        else:
            messages.error(request, "يرجى إدخال اسم التصنيف والكود.")
        return redirect('categories_list')
    return redirect('categories_list')


@login_required
def category_delete(request, pk):
    cat = get_object_or_404(ProductCategory, pk=pk)
    if request.method == 'POST':
        if cat.products.exists():
            messages.error(request, f"لا يمكن حذف التصنيف '{cat.name}' لوجود منتجات مرتبطة به.")
        else:
            cat_name = cat.name
            cat.delete()
            messages.success(request, f"تم حذف التصنيف '{cat_name}' بنجاح.")
    return redirect('categories_list')

