from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q, Count
from master_data.excel_utils import export_to_excel_response
from master_data.pagination_utils import paginate_queryset
from .models import Warehouse, InventoryStock, InventoryLot, InventoryMemo


@login_required
def inventory_stock_list(request):
    warehouse_id = request.GET.get('warehouse')
    search = request.GET.get('search', '').strip()

    qs = InventoryStock.objects.select_related('warehouse', 'product', 'product__category').order_by('warehouse__name', 'product__name')

    active_filters = []

    if warehouse_id:
        qs = qs.filter(warehouse_id=warehouse_id)
        wh = Warehouse.objects.filter(id=warehouse_id).first()
        active_filters.append({'label': f'المخزن: {wh.name if wh else warehouse_id}', 'param': 'warehouse'})

    if search:
        qs = qs.filter(
            Q(product__name__icontains=search) |
            Q(product__sku_code__icontains=search)
        )
        active_filters.append({'label': f'بحث: {search}', 'param': 'search'})

    warehouses = Warehouse.objects.filter(is_active=True).order_by('name')

    paginator, page_obj = paginate_queryset(request, qs, default_per_page=25, max_per_page=100)

    context = {
        'stocks': page_obj.object_list,
        'page_obj': page_obj,
        'paginator': paginator,
        'warehouses': warehouses,
        'selected_warehouse_id': warehouse_id,
        'search_query': search,
        'active_filters': active_filters,
        'total_count': paginator.count,
    }
    return render(request, 'inventory/stock_list.html', context)


@login_required
def inventory_stock_export(request):
    warehouse_id = request.GET.get('warehouse')
    search = request.GET.get('search', '').strip()

    qs = InventoryStock.objects.select_related('warehouse', 'product', 'product__category').order_by('warehouse__name', 'product__name')

    if warehouse_id:
        qs = qs.filter(warehouse_id=warehouse_id)

    if search:
        qs = qs.filter(
            Q(product__name__icontains=search) |
            Q(product__sku_code__icontains=search)
        )

    columns = [
        {'header': 'المخزن', 'key': lambda s: s.warehouse.name, 'width': 22, 'align': 'right'},
        {'header': 'كود المنتج (SKU)', 'key': lambda s: s.product.sku_code, 'width': 18, 'align': 'center'},
        {'header': 'اسم المنتج', 'key': lambda s: s.product.name, 'width': 35, 'align': 'right'},
        {'header': 'التصنيف', 'key': lambda s: s.product.category.name if s.product.category else '', 'width': 20, 'align': 'right'},
        {'header': 'الكمية الفعلية بالمخزن', 'key': lambda s: float(s.qty_on_hand), 'format': '#,##0.00', 'width': 20, 'align': 'right'},
        {'header': 'الكمية المحجوزة', 'key': lambda s: float(s.qty_reserved), 'format': '#,##0.00', 'width': 18, 'align': 'right'},
        {'header': 'الكمية المتاحة للبيع', 'key': lambda s: float(s.qty_available), 'format': '#,##0.00', 'width': 20, 'align': 'right'},
        {'header': 'سعر تكلفة الوحدة', 'key': lambda s: float(s.product_cost), 'format': '#,##0.00', 'width': 18, 'align': 'right'},
        {'header': 'إجمالي قيمة التكلفة', 'key': lambda s: float(s.total_cost), 'format': '#,##0.00', 'width': 20, 'align': 'right'},
        {'header': 'سعر البيع للجمهور', 'key': lambda s: float(s.product.retail_price) if s.product.retail_price else 0.0, 'format': '#,##0.00', 'width': 18, 'align': 'right'},
        {'header': 'تاريخ آخر حركة', 'key': lambda s: s.updated_at.strftime('%Y-%m-%d %H:%M') if s.updated_at else '', 'width': 20, 'align': 'center'},
    ]

    return export_to_excel_response(qs, columns, filename="inventory_stock_export", sheet_title="أرصدة المخزون")


@login_required
def warehouses_list(request):
    search = request.GET.get('search', '').strip()
    qs = Warehouse.objects.select_related('manager').all().order_by('name')

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        code = request.POST.get('code', '').strip()
        address = request.POST.get('address', '').strip()
        if name and code:
            Warehouse.objects.create(name=name, code=code, address=address)
            messages.success(request, f"تم إنشاء المخزن '{name}' بنجاح.")
        return redirect('warehouses_list')

    active_filters = []
    if search:
        qs = qs.filter(Q(name__icontains=search) | Q(code__icontains=search))
        active_filters.append({'label': f'بحث: {search}', 'param': 'search'})

    paginator, page_obj = paginate_queryset(request, qs, default_per_page=25, max_per_page=100)

    context = {
        'warehouses': page_obj.object_list,
        'page_obj': page_obj,
        'paginator': paginator,
        'search_query': search,
        'active_filters': active_filters,
        'total_count': paginator.count,
    }
    return render(request, 'inventory/warehouses_list.html', context)


@login_required
def inventory_memos_list(request):
    search = request.GET.get('search', '').strip()
    warehouse_id = request.GET.get('warehouse')
    memo_type = request.GET.get('memo_type')

    qs = InventoryMemo.objects.select_related('warehouse', 'created_by').annotate(
        items_count=Count('items')
    ).prefetch_related('items__product').order_by('-created_at')

    active_filters = []

    if warehouse_id:
        qs = qs.filter(warehouse_id=warehouse_id)
        wh = Warehouse.objects.filter(id=warehouse_id).first()
        active_filters.append({'label': f'المخزن: {wh.name if wh else warehouse_id}', 'param': 'warehouse'})

    if memo_type in ['inward', 'outward']:
        qs = qs.filter(memo_type=memo_type)
        type_label = 'إذن إضافة' if memo_type == 'inward' else 'إذن صرف / خصم'
        active_filters.append({'label': f'النوع: {type_label}', 'param': 'memo_type'})

    if search:
        qs = qs.filter(
            Q(memo_number__icontains=search) |
            Q(statement__icontains=search)
        )
        active_filters.append({'label': f'بحث: {search}', 'param': 'search'})

    warehouses = Warehouse.objects.filter(is_active=True).order_by('name')

    paginator, page_obj = paginate_queryset(request, qs, default_per_page=25, max_per_page=100)

    context = {
        'memos': page_obj.object_list,
        'page_obj': page_obj,
        'paginator': paginator,
        'warehouses': warehouses,
        'selected_warehouse_id': warehouse_id,
        'selected_memo_type': memo_type,
        'search_query': search,
        'active_filters': active_filters,
        'total_count': paginator.count,
    }
    return render(request, 'inventory/memos_list.html', context)
