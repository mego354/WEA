import csv
from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q, Count
from django.core.paginator import Paginator
from django.http import HttpResponse, JsonResponse
from .models import Product, ProductCategory, ProductVolumeDiscountTier, ProductPriceList
from inventory.models import InventoryStock



from master_data.pagination_utils import paginate_queryset


@login_required
def products_list(request):
    search = request.GET.get('search', '').strip()
    category_id = request.GET.get('category')
    sellable_filter = request.GET.get('sellable')
    min_price = request.GET.get('min_price')
    max_price = request.GET.get('max_price')

    qs = Product.objects.select_related('category').all().order_by('name')

    active_filters = []

    if category_id:
        qs = qs.filter(category_id=category_id)
        cat_obj = ProductCategory.objects.filter(pk=category_id).first()
        if cat_obj:
            active_filters.append({'label': 'التصنيف', 'value': cat_obj.name, 'param': 'category'})

    if sellable_filter in ['true', '1', 'yes']:
        qs = qs.filter(sellable=True)
        active_filters.append({'label': 'متاح للبيع', 'value': 'نعم', 'param': 'sellable'})
    elif sellable_filter in ['false', '0', 'no']:
        qs = qs.filter(sellable=False)
        active_filters.append({'label': 'متاح للبيع', 'value': 'لا', 'param': 'sellable'})

    if min_price:
        try:
            qs = qs.filter(retail_price__gte=Decimal(min_price))
            active_filters.append({'label': 'السعر من', 'value': f"{min_price} ج.م", 'param': 'min_price'})
        except Exception:
            pass

    if max_price:
        try:
            qs = qs.filter(retail_price__lte=Decimal(max_price))
            active_filters.append({'label': 'السعر إلى', 'value': f"{max_price} ج.م", 'param': 'max_price'})
        except Exception:
            pass

    if search:
        qs = qs.filter(
            Q(name__icontains=search) |
            Q(sku_code__icontains=search) |
            Q(barcode__icontains=search) |
            Q(description__icontains=search)
        )
        active_filters.append({'label': 'بحث', 'value': search, 'param': 'search'})

    categories = ProductCategory.objects.all().order_by('name')

    # Safe bounded server-side pagination (default 25)
    paginator, page_obj = paginate_queryset(request, qs, default_per_page=25)

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
        'active_filters_count': len(active_filters),
        'active_filters': active_filters,
        'total_count': paginator.count,
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

from master_data.excel_utils import (
    export_to_excel_response,
    generate_excel_template_response,
    ExcelImportParser,
    parse_decimal_safe,
    parse_boolean_safe,
)
from django.db import transaction


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

    columns = [
        {'header': 'الكود (SKU)', 'key': 'sku_code', 'width': 18, 'align': 'center'},
        {'header': 'اسم المنتج', 'key': 'name', 'width': 35, 'align': 'right'},
        {'header': 'التصنيف', 'key': lambda p: p.category.name if p.category else '', 'width': 22, 'align': 'right'},
        {'header': 'سعر البيع', 'key': lambda p: float(p.retail_price) if p.retail_price is not None else 0.0, 'format': '#,##0.00', 'width': 16, 'align': 'right'},
        {'header': 'تكلفة الشراء', 'key': lambda p: float(p.default_purchase_cost) if p.default_purchase_cost is not None else 0.0, 'format': '#,##0.00', 'width': 16, 'align': 'right'},
        {'header': 'نسبة الضريبة %', 'key': lambda p: float(p.tax_percentage) if p.tax_percentage is not None else 0.0, 'format': '0.00"%"', 'width': 15, 'align': 'center'},
        {'header': 'متاح للبيع', 'key': lambda p: 'نعم' if p.sellable else 'لا', 'width': 14, 'align': 'center'},
        {'header': 'الباركود', 'key': lambda p: p.barcode or '', 'width': 20, 'align': 'center'},
        {'header': 'الوحدة', 'key': lambda p: p.unit or '', 'width': 12, 'align': 'center'},
        {'header': 'تاريخ الإنشاء', 'key': lambda p: p.created_at.strftime('%Y-%m-%d %H:%M') if p.created_at else '', 'width': 20, 'align': 'center'},
    ]

    return export_to_excel_response(qs, columns, filename="products_export", sheet_title="المنتجات")


@login_required
def product_import_template(request):
    columns = [
        {'header': 'كود المنتج (SKU)', 'width': 18},
        {'header': 'اسم المنتج', 'width': 35},
        {'header': 'التصنيف', 'width': 20},
        {'header': 'سعر البيع للجمهور', 'width': 18},
        {'header': 'سعر تكلفة الشراء', 'width': 18},
        {'header': 'نسبة الضريبة', 'width': 15},
        {'header': 'متاح للبيع', 'width': 12},
        {'header': 'الباركود', 'width': 20},
        {'header': 'الوحدة', 'width': 12},
        {'header': 'الوصف', 'width': 30},
    ]
    sample_rows = [
        ['MED-001', 'أوجمنتين 1 جم أقراص', 'مضادات حيوية', 110.00, 85.00, 14.0, 'نعم', '6221234567890', 'علبة', 'مضاد حيوي واسع المجال'],
        ['MED-002', 'بانادول إكسترا 500 مجم', 'مسكنات', 45.00, 32.50, 0.0, 'نعم', '6221234567891', 'شريط', 'مسكن للآلام وخافض للحرارة'],
    ]
    return generate_excel_template_response(columns, sample_rows=sample_rows, filename="products_import_template", sheet_title="نموذج المنتجات")


@login_required
def product_import(request):
    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'preview':
            excel_file = request.FILES.get('excel_file')
            if not excel_file:
                messages.error(request, "يرجى اختيار ملف Excel للرفع.")
                return render(request, 'catalog/product_import.html', {'preview_mode': False})

            column_mapping = {
                'sku_code': ['كود المنتج (sku)', 'كود المنتج', 'sku', 'sku_code', 'الكود', 'كود'],
                'name': ['اسم المنتج', 'الاسم', 'name', 'product_name'],
                'category': ['التصنيف', 'القسم', 'category', 'category_name'],
                'retail_price': ['سعر البيع للجمهور', 'سعر البيع', 'السعر', 'retail_price', 'price'],
                'default_purchase_cost': ['سعر تكلفة الشراء', 'تكلفة الشراء', 'سعر الشراء', 'purchase_cost', 'cost'],
                'tax_percentage': ['نسبة الضريبة', 'الضريبة', 'tax', 'tax_percentage'],
                'sellable': ['متاح للبيع', 'قابل للبيع', 'sellable', 'active'],
                'barcode': ['الباركود', 'باركود', 'barcode'],
                'unit': ['الوحدة', 'unit'],
                'description': ['الوصف', 'ملاحظات', 'description'],
            }

            parser = ExcelImportParser(excel_file, column_mapping)
            if not parser.parse():
                for err in parser.errors:
                    messages.error(request, err)
                return render(request, 'catalog/product_import.html', {'preview_mode': False})

            existing_skus = set(Product.objects.values_list('sku_code', flat=True))

            preview_rows = []
            seen_skus = set()
            new_count = 0
            update_count = 0
            invalid_count = 0

            for r in parser.rows_data:
                row_errors = []
                sku = str(r.get('sku_code') or '').strip()
                name = str(r.get('name') or '').strip()

                if not sku:
                    row_errors.append("كود المنتج (SKU) مطلوب")
                if not name:
                    row_errors.append("اسم المنتج مطلوب")

                if sku:
                    if sku in seen_skus:
                        row_errors.append("كود مكرر داخل نفس الملف")
                    else:
                        seen_skus.add(sku)

                is_existing = bool(sku and sku in existing_skus)
                is_valid = len(row_errors) == 0

                if not is_valid:
                    invalid_count += 1
                elif is_existing:
                    update_count += 1
                else:
                    new_count += 1

                preview_rows.append({
                    'row_num': r.get('__row_num__'),
                    'sku_code': sku,
                    'name': name,
                    'category': r.get('category') or '',
                    'retail_price': str(r.get('retail_price') or '0.00'),
                    'default_purchase_cost': str(r.get('default_purchase_cost') or '0.00'),
                    'tax_percentage': str(r.get('tax_percentage') or '0'),
                    'sellable': str(r.get('sellable') or 'نعم'),
                    'barcode': str(r.get('barcode') or ''),
                    'unit': str(r.get('unit') or 'علبة'),
                    'description': str(r.get('description') or ''),
                    'is_valid': is_valid,
                    'is_existing': is_existing,
                    'errors': row_errors,
                })

            valid_count = len(preview_rows) - invalid_count
            request.session['product_import_data'] = preview_rows

            context = {
                'preview_mode': True,
                'total_rows': len(preview_rows),
                'valid_count': valid_count,
                'invalid_count': invalid_count,
                'new_count': new_count,
                'update_count': update_count,
                'preview_rows': preview_rows[:100],
                'total_preview_count': min(len(preview_rows), 100),
            }
            return render(request, 'catalog/product_import.html', context)

        elif action == 'execute':
            import_mode = request.POST.get('import_mode', 'create_and_update')
            rows_data = request.session.get('product_import_data', [])

            if not rows_data:
                messages.error(request, "انتهت صلاحية جلسة الاستيراد أو لا توجد بيانات. يرجى إعادة رفع الملف.")
                return redirect('product_import')

            created_count = 0
            updated_count = 0
            skipped_count = 0

            cats_map = {c.name.strip().lower(): c for c in ProductCategory.objects.all()}

            try:
                with transaction.atomic():
                    for r in rows_data:
                        if not r.get('is_valid'):
                            skipped_count += 1
                            continue

                        sku = r['sku_code']
                        name = r['name']
                        cat_name = r.get('category', '').strip()
                        cat_obj = None

                        if cat_name:
                            cat_key = cat_name.lower()
                            if cat_key in cats_map:
                                cat_obj = cats_map[cat_key]
                            else:
                                code_slug = cat_name[:10].upper().replace(' ', '-')
                                cat_obj = ProductCategory.objects.create(name=cat_name, code=f"CAT-{code_slug}")
                                cats_map[cat_key] = cat_obj

                        retail_price = parse_decimal_safe(r.get('retail_price'), Decimal('0.00'))
                        cost = parse_decimal_safe(r.get('default_purchase_cost'), Decimal('0.00'))
                        tax_pct = parse_decimal_safe(r.get('tax_percentage'), Decimal('0.00'))
                        sellable = parse_boolean_safe(r.get('sellable'), True)
                        barcode = r.get('barcode', '').strip()
                        unit = r.get('unit', '').strip() or 'علبة'
                        desc = r.get('description', '').strip()

                        prod = Product.objects.filter(sku_code=sku).first()

                        if prod:
                            if import_mode in ['create_and_update', 'update_only']:
                                prod.name = name
                                if cat_obj:
                                    prod.category = cat_obj
                                prod.retail_price = retail_price
                                prod.default_purchase_cost = cost
                                prod.tax_percentage = tax_pct
                                prod.sellable = sellable
                                if barcode:
                                    prod.barcode = barcode
                                if unit:
                                    prod.unit = unit
                                if desc:
                                    prod.description = desc
                                prod.save()
                                updated_count += 1
                            else:
                                skipped_count += 1
                        else:
                            if import_mode in ['create_and_update', 'create_only']:
                                Product.objects.create(
                                    sku_code=sku,
                                    name=name,
                                    category=cat_obj,
                                    retail_price=retail_price,
                                    default_purchase_cost=cost,
                                    tax_percentage=tax_pct,
                                    sellable=sellable,
                                    barcode=barcode,
                                    unit=unit,
                                    description=desc,
                                )
                                created_count += 1
                            else:
                                skipped_count += 1

                request.session.pop('product_import_data', None)
                messages.success(
                    request,
                    f"اكتملت عملية الاستيراد بنجاح! تم إنشاء {created_count} منتج جديد، "
                    f"وتحديث {updated_count} منتج، وتخطي {skipped_count} سجل."
                )
                return redirect('products_list')

            except Exception as e:
                messages.error(request, f"حدث خطأ أثناء حفظ البيانات وتم التراجع عن كافة العمليات: {str(e)}")
                return redirect('product_import')

    return render(request, 'catalog/product_import.html', {'preview_mode': False})


@login_required
def categories_list(request):
    search = request.GET.get('search', '').strip()
    categories = ProductCategory.objects.annotate(products_count=Count('products')).all().order_by('name')

    active_filters = []
    if search:
        categories = categories.filter(
            Q(name__icontains=search) |
            Q(code__icontains=search) |
            Q(description__icontains=search)
        )
        active_filters.append({'label': 'بحث', 'value': search, 'param': 'search'})

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

    paginator, page_obj = paginate_queryset(request, categories, default_per_page=25)

    return render(request, 'catalog/categories_list.html', {
        'categories': page_obj.object_list,
        'page_obj': page_obj,
        'paginator': paginator,
        'search_query': search,
        'active_filters': active_filters,
    })


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

