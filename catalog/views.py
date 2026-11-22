import csv
from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q, Count, ProtectedError
from django.core.paginator import Paginator
from django.http import HttpResponse, JsonResponse
from .models import Product, ProductCategory, ProductVolumeDiscountTier, ProductPriceList
from inventory.models import InventoryStock
from accounts.permissions import require_permission, has_perm_or_admin, render_forbidden_response


from master_data.pagination_utils import paginate_queryset
from master_data.search_utils import filter_by_arabic_search


@require_permission('catalog:products/list')
def products_list(request):
    from master_data.filter_utils import parse_multi_int
    search = request.GET.get('search', '').strip()
    selected_category_ids = parse_multi_int(request.GET, 'category')
    category_id = str(selected_category_ids[0]) if len(selected_category_ids) == 1 else ''
    sellable_filter = request.GET.get('sellable')
    min_price = request.GET.get('min_price')
    max_price = request.GET.get('max_price')

    qs = Product.objects.select_related('category').all().order_by('name')

    active_filters = []

    if selected_category_ids:
        qs = qs.filter(category_id__in=selected_category_ids)
        for cat_obj in ProductCategory.objects.filter(pk__in=selected_category_ids):
            active_filters.append({'label': 'التصنيف', 'value': cat_obj.name, 'param': 'category', 'remove_value': str(cat_obj.id)})

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
        qs = filter_by_arabic_search(qs, search, ['name', 'sku_code', 'barcode', 'description'])
        active_filters.append({'label': 'بحث', 'value': search, 'param': 'search'})

    categories = ProductCategory.objects.all().order_by('name')

    # Safe bounded server-side pagination (default 25)
    paginator, page_obj = paginate_queryset(request, qs, default_per_page=25)

    prod_agg = qs.aggregate(
        total_products=Count('id'),
        sellable_products=Count('id', filter=Q(sellable=True)),
        unsellable_products=Count('id', filter=Q(sellable=False)),
        categories_count=Count('category', distinct=True),
    )
    stats = {
        'total_products': prod_agg['total_products'] or 0,
        'sellable_products': prod_agg['sellable_products'] or 0,
        'unsellable_products': prod_agg['unsellable_products'] or 0,
        'categories_count': prod_agg['categories_count'] or 0,
    }

    category_options = [{'value': str(c.id), 'label': c.name} for c in categories]
    selected_category_str = [str(x) for x in selected_category_ids]
    selected_category_items = [o for o in category_options if o['value'] in selected_category_str]

    context = {
        'products': page_obj.object_list,
        'page_obj': page_obj,
        'paginator': paginator,
        'categories': categories,
        'category_options': category_options,
        'selected_category_items': selected_category_items,
        'selected_categories': selected_category_str,
        'selected_category': category_id,
        'sellable_filter': sellable_filter,
        'min_price': min_price,
        'max_price': max_price,
        'search_query': search,
        'active_filters_count': len(active_filters),
        'active_filters': active_filters,
        'total_count': paginator.count,
        'stats': stats,
    }
    return render(request, 'catalog/products_list.html', context)


@require_permission('catalog:products/create')
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
        if thumbnail:
            from django.core.exceptions import ValidationError
            from master_data.media_service import validate_uploaded_file
            try:
                validate_uploaded_file(thumbnail, images_only=True)
            except ValidationError as e:
                msg = e.messages[0] if getattr(e, 'messages', None) else str(e)
                messages.error(request, msg)
                return redirect('product_create')

        try:
            retail_dec = Decimal(retail_price)
            cost_dec = Decimal(default_purchase_cost)
            tax_dec = Decimal(tax_percentage)
            if retail_dec < 0 or cost_dec < 0 or tax_dec < 0 or tax_dec > 100:
                messages.error(request, "الأسعار والتكاليف يجب أن تكون موجبة والضريبة بين 0% و 100%.")
                return redirect('product_create')
        except Exception:
            messages.error(request, "يرجى إدخال قيم رقمية صحيحة للسعر والتكلفة والضريبة.")
            return redirect('product_create')

        product = Product.objects.create(
            name=name,
            sku_code=sku_code,
            category=category,
            barcode=barcode,
            retail_price=retail_dec,
            default_purchase_cost=cost_dec,
            tax_percentage=tax_dec,
            unit=unit,
            description=description,
            sellable=sellable,
            has_volume_discounts=has_volume_discounts,
            packing_boxes=packing_boxes,
            packing_cartons=packing_cartons,
            thumbnail=thumbnail,
            created_by=request.user
        )
        from accounts.services import AuditLogService
        AuditLogService.log(
            action_type='PRODUCT_CREATED',
            module='catalog',
            actor=request.user,
            record_id=product.id,
            record_name=product.name,
            description=f"إنشاء صنف جديد: {product.name} ({product.sku_code})",
            request=request,
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


@require_permission('catalog:products/edit')
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

        try:
            retail_dec = Decimal(retail_price)
            cost_dec = Decimal(default_purchase_cost)
            tax_dec = Decimal(tax_percentage)
            if retail_dec < 0 or cost_dec < 0 or tax_dec < 0 or tax_dec > 100:
                messages.error(request, "الأسعار والتكاليف يجب أن تكون موجبة والضريبة بين 0% و 100%.")
                return redirect('product_edit', pk=product.pk)
        except Exception:
            messages.error(request, "يرجى إدخال قيم رقمية صحيحة للسعر والتكلفة والضريبة.")
            return redirect('product_edit', pk=product.pk)

        product.barcode = barcode
        product.retail_price = retail_dec
        product.default_purchase_cost = cost_dec
        product.tax_percentage = tax_dec
        product.unit = unit
        if 'description' in request.POST:
            product.description = description
        product.sellable = sellable
        product.has_volume_discounts = has_volume_discounts
        product.packing_boxes = packing_boxes
        product.packing_cartons = packing_cartons

        clear_thumbnail = request.POST.get('clear_thumbnail') == '1'
        if clear_thumbnail:
            from master_data.media_service import clear_model_file
            clear_model_file(product, 'thumbnail')
        elif request.FILES.get('thumbnail'):
            from django.core.exceptions import ValidationError
            from master_data.media_service import replace_model_file
            try:
                replace_model_file(product, 'thumbnail', request.FILES['thumbnail'])
            except ValidationError as e:
                msg = e.messages[0] if getattr(e, 'messages', None) else str(e)
                messages.error(request, msg)
                return redirect('product_edit', pk=product.pk)

        product.save()
        from accounts.services import AuditLogService
        AuditLogService.log(
            action_type='PRODUCT_UPDATED',
            module='catalog',
            actor=request.user,
            record_id=product.id,
            record_name=product.name,
            description=f"تحديث بيانات المنتج: {product.name} ({product.sku_code})",
            request=request,
        )

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



@require_permission('catalog:products/view')
def product_detail(request, pk):
    product = get_object_or_404(
        Product.objects.select_related('category', 'created_by').prefetch_related('volume_discounts', 'price_lists'),
        pk=pk
    )
    from accounts.permissions import get_scoped_queryset, has_perm_or_admin
    can_view_stock = has_perm_or_admin(request.user, 'inventory:stocks/view')
    if can_view_stock:
        stocks = get_scoped_queryset(
            InventoryStock.objects.filter(product=product).select_related('warehouse'),
            request.user,
            'inventorystock'
        )
        total_stock = sum((s.qty_on_hand for s in stocks), Decimal('0.00'))
    else:
        stocks = InventoryStock.objects.none()
        total_stock = Decimal('0.00')

    context = {
        'product': product,
        'stocks': stocks,
        'total_stock': total_stock,
        'can_view_stock': can_view_stock,
        'volume_discounts': product.volume_discounts.all(),
        'price_lists': product.price_lists.all(),
    }
    return render(request, 'catalog/product_detail.html', context)


@require_permission('catalog:products/delete')
def product_delete(request, pk):
    product = get_object_or_404(Product, pk=pk)
    if request.method == 'POST':
        name = product.name
        code = product.sku_code
        try:
            product.delete()
            messages.success(request, f"تم حذف المنتج '{name}' ({code}) بنجاح.")
            return redirect('products_list')
        except ProtectedError:
            messages.error(request, f"لا يمكن حذف المنتج '{name}' ({code}) لوجود حركات مخزنية أو فواتير أو طلبيات مرتبطة به.")
            return redirect('product_detail', pk=pk)
    return redirect('product_detail', pk=pk)


from master_data.excel_utils import (
    export_to_excel_response,
    generate_excel_template_response,
    ExcelImportParser,
    parse_decimal_safe,
    parse_boolean_safe,
)
from django.db import transaction


@require_permission('catalog:products/export')
def products_export(request):
    search = request.GET.get('search', '').strip()
    category_id = request.GET.get('category')
    sellable_filter = request.GET.get('sellable')
    min_price = request.GET.get('min_price', '').strip()
    max_price = request.GET.get('max_price', '').strip()

    qs = Product.objects.select_related('category').all().order_by('name')

    if category_id:
        qs = qs.filter(category_id=category_id)
    if sellable_filter in ['true', '1']:
        qs = qs.filter(sellable=True)
    elif sellable_filter in ['false', '0']:
        qs = qs.filter(sellable=False)
    if min_price:
        try:
            qs = qs.filter(retail_price__gte=Decimal(min_price))
        except Exception:
            pass
    if max_price:
        try:
            qs = qs.filter(retail_price__lte=Decimal(max_price))
        except Exception:
            pass
    if search:
        qs = filter_by_arabic_search(qs, search, ['name', 'sku_code', 'barcode', 'description'])

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

    return export_to_excel_response(
        qs,
        columns,
        filename="products_export",
        sheet_title="المنتجات",
        report_title="دليل المنتجات والأصناف",
        user=request.user,
    )


@require_permission('catalog:products/import')
def product_import_template(request):
    from master_data.excel_views import excel_import_template_view
    return excel_import_template_view(request, entity='products')


@require_permission('catalog:products/import')
def product_import(request):
    from master_data.excel_views import excel_import_view
    return excel_import_view(request, entity='products')


@require_permission('catalog:categories/list')
def categories_list(request):
    search = request.GET.get('search', '').strip()
    categories = ProductCategory.objects.annotate(products_count=Count('products')).all().order_by('name')

    active_filters = []
    if search:
        categories = filter_by_arabic_search(categories, search, ['name', 'code', 'description'])
        active_filters.append({'label': 'بحث', 'value': search, 'param': 'search'})

    if request.method == 'POST':
        if not has_perm_or_admin(request.user, ['catalog:categories/create', 'catalog:categories/edit']):
            return render_forbidden_response(request, "ليس لديك صلاحية إنشاء تصنيفات منتجات.")
        name = request.POST.get('name', '').strip()
        code = request.POST.get('code', '').strip()
        description = request.POST.get('description', '').strip()
        if name and code:
            if ProductCategory.objects.filter(Q(name=name) | Q(code=code)).exists():
                messages.error(request, "يوجد تصنيف بنفس الاسم أو الكود بالفعل.")
            else:
                cat = ProductCategory.objects.create(name=name, code=code, description=description)
                from accounts.services import AuditLogService
                AuditLogService.log(
                    action_type='CATEGORY_CREATED',
                    module='catalog',
                    actor=request.user,
                    record_id=cat.id,
                    record_name=cat.name,
                    description=f"إنشاء تصنيف منتج: {cat.name} ({cat.code})",
                    request=request,
                )
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


@require_permission('catalog:categories/export')
def categories_export(request):
    search = request.GET.get('search', '').strip()
    categories = ProductCategory.objects.annotate(products_count=Count('products')).all().order_by('name')
    if search:
        categories = filter_by_arabic_search(categories, search, ['name', 'code', 'description'])

    columns = [
        {'header': 'الاسم', 'key': 'name', 'width': 30, 'align': 'right'},
        {'header': 'الكود', 'key': 'code', 'width': 16, 'align': 'center'},
        {'header': 'التوصيف', 'key': lambda c: c.description or '', 'width': 36, 'align': 'right'},
        {'header': 'عدد المنتجات', 'key': lambda c: int(c.products_count or 0), 'format': '#,##0', 'width': 15, 'align': 'center'},
        {'header': 'تاريخ الإنشاء', 'key': lambda c: c.created_at.strftime('%Y-%m-%d %H:%M') if c.created_at else '', 'width': 20, 'align': 'center'},
    ]
    return export_to_excel_response(
        categories,
        columns,
        filename="categories_export",
        sheet_title="التصنيفات",
        report_title="تصنيفات المنتجات",
        user=request.user,
    )


@require_permission('catalog:categories/edit')
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


@require_permission('catalog:categories/delete')
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

