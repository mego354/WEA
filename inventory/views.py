from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q, Count, Sum, F, ExpressionWrapper, DecimalField
from django.http import JsonResponse
from django.core.exceptions import ValidationError

from master_data.excel_utils import export_to_excel_response
from master_data.pagination_utils import paginate_queryset
from master_data.search_utils import filter_by_arabic_search
from master_data.validation_utils import parse_positive_integer_quantity
from accounts.permissions import (
    require_permission, has_perm_or_admin, render_forbidden_response,
    get_scoped_queryset, can_user_access_object, is_accountant, is_manager_or_higher,
    can_user_perform_stock_in, can_user_perform_stock_out, can_user_perform_transfer,
    get_visible_assignees_queryset
)
from accounts.services import is_representative, get_representative_warehouse
from catalog.models import Product
from .models import (
    Warehouse, InventoryStock, InventoryLot, InventoryMemo,
    ProductTransferRequest, ProductTransferRequestItem
)
from .services import ProductTransferService, InventoryMemoService, AuditLogService, WarehouseService


@require_permission('inventory:stocks/view')
def inventory_stock_list(request):
    from master_data.filter_utils import parse_multi_int, parse_multi_str
    from catalog.models import ProductCategory

    selected_warehouse_ids = parse_multi_int(request.GET, 'warehouse')
    warehouse_id = str(selected_warehouse_ids[0]) if len(selected_warehouse_ids) == 1 else ''
    selected_category_ids = parse_multi_int(request.GET, 'category')
    selected_stock_statuses = [s for s in parse_multi_str(request.GET, 'stock_status') if s in ('low_stock', 'out_of_stock', 'in_stock')]
    stock_status = selected_stock_statuses[0] if len(selected_stock_statuses) == 1 else ''
    search = request.GET.get('search', '').strip()

    qs = InventoryStock.objects.select_related('warehouse', 'product', 'product__category').order_by('warehouse__name', 'product__name')
    qs = get_scoped_queryset(qs, request.user, 'inventorystock')

    active_filters = []

    if selected_warehouse_ids:
        qs = qs.filter(warehouse_id__in=selected_warehouse_ids)
        for wh in Warehouse.objects.filter(id__in=selected_warehouse_ids):
            active_filters.append({'label': 'المخزن', 'value': wh.name, 'param': 'warehouse', 'remove_value': str(wh.id)})

    if selected_category_ids:
        qs = qs.filter(product__category_id__in=selected_category_ids)
        for cat in ProductCategory.objects.filter(id__in=selected_category_ids):
            active_filters.append({'label': 'التصنيف', 'value': cat.name, 'param': 'category', 'remove_value': str(cat.id)})

    if selected_stock_statuses:
        qs = qs.annotate(
            avail=ExpressionWrapper(F('qty_on_hand') - F('qty_reserved'), output_field=DecimalField(max_digits=12, decimal_places=2))
        )
        stock_q = Q()
        ss_labels = {'low_stock': 'مخزون منخفض (≤ 5)', 'out_of_stock': 'نفد المخزون', 'in_stock': 'متوفر بالمخزن'}
        if 'low_stock' in selected_stock_statuses:
            stock_q |= Q(avail__gt=0, avail__lte=5)
        if 'out_of_stock' in selected_stock_statuses:
            stock_q |= Q(avail__lte=0)
        if 'in_stock' in selected_stock_statuses:
            stock_q |= Q(avail__gt=0)
        qs = qs.filter(stock_q)
        for ss in selected_stock_statuses:
            active_filters.append({'label': 'الحالة', 'value': ss_labels.get(ss, ss), 'param': 'stock_status', 'remove_value': ss})

    if search:
        qs = filter_by_arabic_search(qs, search, ['product__name', 'product__sku_code'])
        active_filters.append({'label': f'بحث: {search}', 'param': 'search'})

    # Scoped warehouses available for filter dropdown
    warehouses = get_scoped_queryset(Warehouse.objects.filter(is_active=True), request.user, 'warehouse').order_by('name')

    # Real scoped statistics matching active filters
    stock_aggregates = qs.aggregate(
        total_items=Count('id'),
        total_qty_on_hand=Sum('qty_on_hand'),
        total_qty_reserved=Sum('qty_reserved'),
    )
    tot_on_hand = stock_aggregates['total_qty_on_hand'] or Decimal('0.00')
    tot_reserved = stock_aggregates['total_qty_reserved'] or Decimal('0.00')
    tot_available = max(Decimal('0.00'), tot_on_hand - tot_reserved)

    total_cost_val = qs.annotate(
        val=ExpressionWrapper(F('qty_on_hand') * F('product_cost'), output_field=DecimalField(max_digits=14, decimal_places=2))
    ).aggregate(tot=Sum('val'))['tot'] or Decimal('0.00')

    low_stock_count = qs.annotate(
        avail=ExpressionWrapper(F('qty_on_hand') - F('qty_reserved'), output_field=DecimalField(max_digits=12, decimal_places=2))
    ).filter(avail__lte=5).count()

    stats = {
        'total_items': stock_aggregates['total_items'] or 0,
        'total_qty_on_hand': tot_on_hand,
        'total_qty_available': tot_available,
        'total_cost_value': total_cost_val,
        'low_stock_count': low_stock_count,
    }

    paginator, page_obj = paginate_queryset(request, qs, default_per_page=25, max_per_page=100)

    categories = ProductCategory.objects.all().order_by('name')
    warehouse_options = [{'value': str(w.id), 'label': w.name} for w in warehouses]
    selected_wh_str = [str(x) for x in selected_warehouse_ids]
    selected_warehouse_items = [o for o in warehouse_options if o['value'] in selected_wh_str]

    category_options = [{'value': str(c.id), 'label': c.name} for c in categories]
    selected_cat_str = [str(x) for x in selected_category_ids]
    selected_category_items = [o for o in category_options if o['value'] in selected_cat_str]

    stock_status_options = [
        {'value': 'in_stock', 'label': 'متوفر بالمخزن'},
        {'value': 'low_stock', 'label': 'مخزون منخفض (≤ 5)'},
        {'value': 'out_of_stock', 'label': 'نفد المخزون'},
    ]
    selected_ss_items = [o for o in stock_status_options if o['value'] in selected_stock_statuses]

    context = {
        'stocks': page_obj.object_list,
        'page_obj': page_obj,
        'paginator': paginator,
        'warehouses': warehouses,
        'warehouse_options': warehouse_options,
        'selected_warehouse_items': selected_warehouse_items,
        'selected_warehouse_ids': selected_wh_str,
        'category_options': category_options,
        'selected_category_items': selected_category_items,
        'selected_category_ids': selected_cat_str,
        'stock_status_options': stock_status_options,
        'selected_ss_items': selected_ss_items,
        'selected_stock_statuses': selected_stock_statuses,
        'selected_warehouse_id': warehouse_id,
        'selected_stock_status': stock_status,
        'search_query': search,
        'active_filters': active_filters,
        'total_count': paginator.count,
        'stats': stats,
    }
    return render(request, 'inventory/stock_list.html', context)


@require_permission('inventory:stocks/export')
def inventory_stock_export(request):
    warehouse_id = request.GET.get('warehouse')
    search = request.GET.get('search', '').strip()

    qs = InventoryStock.objects.select_related('warehouse', 'product', 'product__category').order_by('warehouse__name', 'product__name')
    qs = get_scoped_queryset(qs, request.user, 'inventorystock')

    if warehouse_id:
        qs = qs.filter(warehouse_id=warehouse_id)

    stock_status = request.GET.get('stock_status')
    if stock_status == 'low_stock':
        qs = qs.annotate(
            avail=ExpressionWrapper(F('qty_on_hand') - F('qty_reserved'), output_field=DecimalField(max_digits=12, decimal_places=2))
        ).filter(avail__gt=0, avail__lte=5)
    elif stock_status == 'out_of_stock':
        qs = qs.annotate(
            avail=ExpressionWrapper(F('qty_on_hand') - F('qty_reserved'), output_field=DecimalField(max_digits=12, decimal_places=2))
        ).filter(avail__lte=0)
    elif stock_status == 'in_stock':
        qs = qs.annotate(
            avail=ExpressionWrapper(F('qty_on_hand') - F('qty_reserved'), output_field=DecimalField(max_digits=12, decimal_places=2))
        ).filter(avail__gt=0)

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
        {'header': 'الكمية الفعلية بالمخزن', 'key': lambda s: int(s.qty_on_hand), 'format': '#,##0', 'width': 20, 'align': 'right'},
        {'header': 'الكمية المحجوزة', 'key': lambda s: int(s.qty_reserved), 'format': '#,##0', 'width': 18, 'align': 'right'},
        {'header': 'الكمية المتاحة للبيع', 'key': lambda s: int(s.qty_available), 'format': '#,##0', 'width': 20, 'align': 'right'},
        {'header': 'سعر تكلفة الوحدة', 'key': lambda s: float(s.product_cost), 'format': '#,##0.00', 'width': 18, 'align': 'right'},
        {'header': 'إجمالي قيمة التكلفة', 'key': lambda s: float(s.total_cost), 'format': '#,##0.00', 'width': 20, 'align': 'right'},
        {'header': 'سعر البيع للجمهور', 'key': lambda s: float(s.product.retail_price) if s.product.retail_price else 0.0, 'format': '#,##0.00', 'width': 18, 'align': 'right'},
        {'header': 'تاريخ آخر حركة', 'key': lambda s: s.updated_at.strftime('%Y-%m-%d %H:%M') if s.updated_at else '', 'width': 20, 'align': 'center'},
    ]

    return export_to_excel_response(qs, columns, filename="inventory_stock_export", sheet_title="أرصدة المخزون")


@require_permission(['inventory:warehouses/manage', 'inventory:stocks/view'])
def warehouses_list(request):
    """
    List of warehouses scoped by manager region or rep ownership.
    Provides advanced filter drawer, real-time scoped statistics, and CRUD actions.
    """
    if not has_perm_or_admin(request.user, ['inventory:warehouses/manage', 'inventory:stocks/view']):
        return render_forbidden_response(request, "لا تملك صلاحية عرض قائمة المخازن.")

    from master_data.filter_utils import parse_multi_str, parse_single_int, resolve_scoped_area_brick_filters
    search = request.GET.get('search', '').strip()
    selected_wh_types = [t for t in parse_multi_str(request.GET, 'type') if t in ('main', 'rep', 'standard')]
    wh_type = selected_wh_types[0] if len(selected_wh_types) == 1 else ''
    status = request.GET.get('status', '').strip()
    main_area_ids, brick_ids, selected_main_areas_chips, selected_bricks_chips = resolve_scoped_area_brick_filters(
        request, 'inventory',
        area_params=('main_area', 'area', 'area_id', 'governorate'),
        brick_params=('brick', 'brick_id'),
    )
    area_id = str(main_area_ids[0]) if len(main_area_ids) == 1 else ''
    assigned_user_int = parse_single_int(request.GET, 'assigned_user')
    assigned_user_id = str(assigned_user_int) if assigned_user_int else ''

    qs = Warehouse.objects.select_related('manager', 'assigned_user', 'area', 'area__parent').all().order_by('-is_main', 'name')
    qs = get_scoped_queryset(qs, request.user, 'warehouse')

    active_filters = []
    if search:
        qs = filter_by_arabic_search(qs, search, ['name', 'code'])
        active_filters.append({'label': 'بحث', 'value': search, 'param': 'search'})

    if selected_wh_types:
        wh_q = Q()
        wt_labels = {'main': 'مستودع رئيسي', 'rep': 'عهدة مندوب', 'standard': 'مخزن فرعي عادي'}
        if 'main' in selected_wh_types:
            wh_q |= Q(is_main=True)
        if 'rep' in selected_wh_types:
            wh_q |= Q(is_rep_warehouse=True)
        if 'standard' in selected_wh_types:
            wh_q |= Q(is_main=False, is_rep_warehouse=False)
        qs = qs.filter(wh_q)
        for wt in selected_wh_types:
            active_filters.append({'label': 'النوع', 'value': wt_labels.get(wt, wt), 'param': 'type', 'remove_value': wt})

    if status == 'active':
        qs = qs.filter(is_active=True)
        active_filters.append({'label': 'الحالة', 'value': 'نشط', 'param': 'status'})
    elif status == 'inactive':
        qs = qs.filter(is_active=False)
        active_filters.append({'label': 'الحالة', 'value': 'معطل', 'param': 'status'})

    from master_data.models import Area
    if main_area_ids:
        qs = qs.filter(Q(area_id__in=main_area_ids) | Q(area__parent_id__in=main_area_ids))
        for a_chip in selected_main_areas_chips:
            active_filters.append({'label': 'المنطقة', 'value': a_chip['name'], 'param': 'main_area', 'remove_value': str(a_chip['id'])})
    if brick_ids:
        qs = qs.filter(area_id__in=brick_ids)
        for b_chip in selected_bricks_chips:
            active_filters.append({'label': 'الخط الجغرافي / Brick', 'value': b_chip['name'], 'param': 'brick', 'remove_value': str(b_chip['id'])})

    from django.contrib.auth import get_user_model
    UserModel = get_user_model()
    if assigned_user_id:
        qs = qs.filter(assigned_user_id=assigned_user_id)
        u_obj = UserModel.objects.filter(id=assigned_user_id).first()
        active_filters.append({'label': 'المسؤول', 'value': u_obj.get_full_name() or u_obj.username if u_obj else assigned_user_id, 'param': 'assigned_user'})

    # If POST to warehouses_list: create warehouse from modal
    if request.method == 'POST':
        if not has_perm_or_admin(request.user, 'inventory:warehouses/manage'):
            return render_forbidden_response(request, "لا تملك صلاحية إنشاء مخزن جديد.")
        try:
            wh = WarehouseService.create_warehouse(request.POST, request.user, request=request)
            messages.success(request, f"تم إنشاء المخزن '{wh.name}' بنجاح.")
        except ValidationError as e:
            messages.error(request, str(e.message if hasattr(e, 'message') else e))
        except Exception as e:
            messages.error(request, f"حدث خطأ أثناء حفظ المخزن: {e}")
        return redirect('warehouses_list')

    paginator, page_obj = paginate_queryset(request, qs, default_per_page=24, max_per_page=100)

    # Dedicated real scoped statistics cards matching active filters
    wh_agg = qs.aggregate(
        total_warehouses=Count('id'),
        main_warehouses=Count('id', filter=Q(is_main=True)),
        rep_warehouses=Count('id', filter=Q(is_rep_warehouse=True)),
        active_warehouses=Count('id', filter=Q(is_active=True)),
    )
    stats = {
        'total_warehouses': wh_agg['total_warehouses'] or 0,
        'main_warehouses': wh_agg['main_warehouses'] or 0,
        'rep_warehouses': wh_agg['rep_warehouses'] or 0,
        'active_warehouses': wh_agg['active_warehouses'] or 0,
    }

    from accounts.scope_service import ScopeResolutionService
    areas = ScopeResolutionService.get_scoped_choices(request.user, 'governorates')
    assignees = get_visible_assignees_queryset(request.user, 'inventory')

    wh_type_options = [
        {'value': 'main', 'label': 'مستودع رئيسي مركزي'},
        {'value': 'rep', 'label': 'مخزن عهدة مندوب'},
        {'value': 'standard', 'label': 'مخزن فرعي عادي'},
    ]
    selected_wh_type_items = [o for o in wh_type_options if o['value'] in selected_wh_types]

    context = {
        'warehouses': page_obj.object_list,
        'page_obj': page_obj,
        'paginator': paginator,
        'search_query': search,
        'wh_type_options': wh_type_options,
        'selected_wh_type_items': selected_wh_type_items,
        'selected_wh_types': selected_wh_types,
        'selected_main_areas_chips': selected_main_areas_chips,
        'selected_bricks_chips': selected_bricks_chips,
        'selected_type': wh_type,
        'selected_status': status,
        'selected_area': area_id,
        'selected_assigned_user': assigned_user_id,
        'active_filters': active_filters,
        'total_count': paginator.count,
        'stats': stats,
        'areas': areas,
        'assignees': assignees,
        'can_manage_warehouses': has_perm_or_admin(request.user, 'inventory:warehouses/manage'),
    }
    return render(request, 'inventory/warehouses_list.html', context)


@require_permission('inventory:warehouses/export')
def warehouses_export(request):
    """Export filtered and scoped warehouses to Excel."""
    from master_data.filter_utils import parse_multi_str, parse_single_int, resolve_scoped_area_brick_filters
    search = request.GET.get('search', '').strip()
    selected_wh_types = [t for t in parse_multi_str(request.GET, 'type') if t in ('main', 'rep', 'standard')]
    wh_type = selected_wh_types[0] if len(selected_wh_types) == 1 else ''
    status = request.GET.get('status', '').strip()
    main_area_ids, brick_ids, selected_main_areas_chips, selected_bricks_chips = resolve_scoped_area_brick_filters(
        request, 'inventory',
        area_params=('main_area', 'area', 'area_id', 'governorate'),
        brick_params=('brick', 'brick_id'),
    )
    area_id = str(main_area_ids[0]) if len(main_area_ids) == 1 else ''
    assigned_user_int = parse_single_int(request.GET, 'assigned_user')
    assigned_user_id = str(assigned_user_int) if assigned_user_int else ''

    qs = Warehouse.objects.select_related('manager', 'assigned_user', 'area', 'area__parent').all().order_by('-is_main', 'name')
    qs = get_scoped_queryset(qs, request.user, 'warehouse')

    if search:
        qs = filter_by_arabic_search(qs, search, ['name', 'code'])
    if wh_type == 'main':
        qs = qs.filter(is_main=True)
    elif wh_type == 'rep':
        qs = qs.filter(is_rep_warehouse=True)
    elif wh_type == 'standard':
        qs = qs.filter(is_main=False, is_rep_warehouse=False)
    if status == 'active':
        qs = qs.filter(is_active=True)
    elif status == 'inactive':
        qs = qs.filter(is_active=False)
    if area_id:
        qs = qs.filter(Q(area_id=area_id) | Q(area__parent_id=area_id))
    if assigned_user_id:
        qs = qs.filter(assigned_user_id=assigned_user_id)

    columns = [
        {'header': 'الكود', 'key': 'code', 'width': 16, 'align': 'center'},
        {'header': 'اسم المخزن', 'key': 'name', 'width': 28, 'align': 'right'},
        {'header': 'النوع', 'key': lambda w: 'رئيسي' if w.is_main else ('عهدة مندوب' if w.is_rep_warehouse else 'فرعي'), 'width': 16, 'align': 'center'},
        {'header': 'المنطقة', 'key': lambda w: w.area.name if w.area else '', 'width': 20, 'align': 'right'},
        {'header': 'المسؤول', 'key': lambda w: (w.assigned_user.name or w.assigned_user.username) if w.assigned_user else '', 'width': 22, 'align': 'right'},
        {'header': 'الحالة', 'key': lambda w: 'نشط' if w.is_active else 'معطل', 'width': 12, 'align': 'center'},
    ]
    return export_to_excel_response(
        qs,
        columns,
        filename="warehouses_export",
        sheet_title="المخازن",
        report_title="دليل المخازن ومراكز التوزيع",
        user=request.user,
    )


@require_permission('inventory:warehouses/manage')
def warehouse_create(request):
    """
    Dedicated view for creating a new warehouse with location picker and scoping.
    """
    from accounts.scope_service import ScopeResolutionService
    if request.method == 'POST':
        try:
            wh = WarehouseService.create_warehouse(request.POST, request.user, request=request)
            messages.success(request, f"تم إنشاء المخزن '{wh.name}' بنجاح.")
            return redirect('warehouses_list')
        except ValidationError as e:
            messages.error(request, str(e.message if hasattr(e, 'message') else e))
        except Exception as e:
            messages.error(request, f"حدث خطأ أثناء حفظ المخزن: {e}")

    areas = ScopeResolutionService.get_scoped_choices(request.user, 'governorates')
    assignees = get_visible_assignees_queryset(request.user, 'inventory')
    return render(request, 'inventory/warehouse_form.html', {
        'is_create': True,
        'areas': areas,
        'assignees': assignees,
    })


@require_permission('inventory:warehouses/manage')
def warehouse_edit(request, pk):
    """
    Edit warehouse details, linked custodian/user, area, coordinates, and operational flags.
    """
    from accounts.scope_service import ScopeResolutionService
    warehouse = get_object_or_404(Warehouse, pk=pk)
    if not can_user_access_object(request.user, warehouse, 'edit'):
        return render_forbidden_response(request, "لا تملك صلاحية تعديل بيانات هذا المخزن.")

    if request.method == 'POST':
        try:
            wh = WarehouseService.update_warehouse(warehouse, request.POST, request.user, request=request)
            messages.success(request, f"تم تحديث بيانات المخزن '{wh.name}' بنجاح.")
            return redirect('warehouses_list')
        except ValidationError as e:
            messages.error(request, str(e.message if hasattr(e, 'message') else e))
        except Exception as e:
            messages.error(request, f"حدث خطأ أثناء تحديث بيانات المخزن: {e}")

    areas = ScopeResolutionService.get_scoped_choices(request.user, 'governorates')
    assignees = get_visible_assignees_queryset(request.user, 'inventory')
    return render(request, 'inventory/warehouse_form.html', {
        'is_create': False,
        'warehouse': warehouse,
        'areas': areas,
        'assignees': assignees,
    })


@require_permission(['inventory:warehouses/manage', 'inventory:warehouses/delete'])
def warehouse_delete(request, pk):
    """
    Safely delete an empty warehouse with strict foreign key & stock protection.
    """
    if request.method != 'POST':
        return render_forbidden_response(request, "طريقة الطلب غير مسموح بها.")

    warehouse = get_object_or_404(Warehouse, pk=pk)
    if not can_user_access_object(request.user, warehouse, 'delete'):
        return render_forbidden_response(request, "لا تملك صلاحية حذف هذا المخزن.")

    try:
        WarehouseService.delete_warehouse(warehouse, request.user, request=request)
        messages.success(request, "تم حذف المخزن بنجاح.")
    except ValidationError as e:
        messages.error(request, str(e.message if hasattr(e, 'message') else e))
    except Exception as e:
        messages.error(request, f"تعذر حذف المخزن: {e}")

    return redirect('warehouses_list')


@require_permission('inventory:memos/manage')
def inventory_memos_list(request):
    search = request.GET.get('search', '').strip()
    warehouse_id = request.GET.get('warehouse')
    memo_type = request.GET.get('memo_type')

    qs = InventoryMemo.objects.select_related('warehouse', 'created_by').annotate(
        items_count=Count('items')
    ).prefetch_related('items__product').order_by('-created_at')
    qs = get_scoped_queryset(qs, request.user, 'inventorymemo')

    active_filters = []

    if warehouse_id:
        qs = qs.filter(warehouse_id=warehouse_id)
        wh = Warehouse.objects.filter(id=warehouse_id).first()
        active_filters.append({'label': f'المخزن: {wh.name if wh else warehouse_id}', 'param': 'warehouse'})

    if memo_type in ['inward', 'outward']:
        qs = qs.filter(memo_type=memo_type)
        type_label = 'إذن إضافة' if memo_type == 'inward' else 'إذن صرف / خصم'
        active_filters.append({'label': f'النوع: {type_label}', 'param': 'memo_type'})

    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    if date_from:
        qs = qs.filter(created_at__date__gte=date_from)
        active_filters.append({'label': f'من تاريخ: {date_from}', 'param': 'date_from'})
    if date_to:
        qs = qs.filter(created_at__date__lte=date_to)
        active_filters.append({'label': f'إلى تاريخ: {date_to}', 'param': 'date_to'})

    if search:
        qs = filter_by_arabic_search(qs, search, ['memo_number', 'statement'])
        active_filters.append({'label': f'بحث: {search}', 'param': 'search'})

    warehouses = get_scoped_queryset(Warehouse.objects.filter(is_active=True), request.user, 'warehouse').order_by('name')

    paginator, page_obj = paginate_queryset(request, qs, default_per_page=25, max_per_page=100)

    can_stock_in = can_user_perform_stock_in(request.user)
    can_stock_out = can_user_perform_stock_out(request.user)
    can_transfer = can_user_perform_transfer(request.user)

    context = {
        'memos': page_obj.object_list,
        'page_obj': page_obj,
        'paginator': paginator,
        'warehouses': warehouses,
        'selected_warehouse_id': warehouse_id,
        'selected_memo_type': memo_type,
        'selected_date_from': date_from,
        'selected_date_to': date_to,
        'search_query': search,
        'active_filters': active_filters,
        'total_count': paginator.count,
        'can_stock_in': can_stock_in,
        'can_stock_out': can_stock_out,
        'can_transfer': can_transfer,
    }
    return render(request, 'inventory/memos_list.html', context)


@require_permission('inventory:memos/export')
def inventory_memos_export(request):
    """Export filtered and scoped inventory memos to Excel."""
    search = request.GET.get('search', '').strip()
    warehouse_id = request.GET.get('warehouse')
    memo_type = request.GET.get('memo_type')
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')

    qs = InventoryMemo.objects.select_related('warehouse', 'created_by').annotate(
        items_count=Count('items')
    ).order_by('-created_at')
    qs = get_scoped_queryset(qs, request.user, 'inventorymemo')

    if warehouse_id:
        qs = qs.filter(warehouse_id=warehouse_id)
    if memo_type in ['inward', 'outward']:
        qs = qs.filter(memo_type=memo_type)
    if date_from:
        qs = qs.filter(created_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(created_at__date__lte=date_to)
    if search:
        qs = filter_by_arabic_search(qs, search, ['memo_number', 'statement'])

    columns = [
        {'header': 'رقم الإذن', 'key': 'memo_number', 'width': 18, 'align': 'center'},
        {'header': 'نوع الحركة', 'key': lambda m: 'إذن إضافة' if m.memo_type == 'inward' else 'إذن صرف / خصم', 'width': 18, 'align': 'center'},
        {'header': 'المخزن', 'key': lambda m: m.warehouse.name if m.warehouse else '', 'width': 24, 'align': 'right'},
        {'header': 'البيان والسبب', 'key': lambda m: m.statement or '', 'width': 32, 'align': 'right'},
        {'header': 'عدد الأصناف', 'key': lambda m: int(m.items_count or 0), 'format': '#,##0', 'width': 14, 'align': 'center'},
        {'header': 'تاريخ التنفيذ', 'key': lambda m: m.created_at.strftime('%Y-%m-%d %H:%M') if m.created_at else '', 'width': 20, 'align': 'center'},
        {'header': 'المسئول', 'key': lambda m: (m.created_by.name or m.created_by.username) if m.created_by else '', 'width': 22, 'align': 'right'},
        {'header': 'الحالة', 'key': lambda m: m.get_status_display() if hasattr(m, 'get_status_display') else m.status, 'width': 14, 'align': 'center'},
    ]
    return export_to_excel_response(
        qs,
        columns,
        filename="inventory_memos_export",
        sheet_title="أذونات المخزن",
        report_title="سجل أذونات الحركات المخزنية",
        user=request.user,
    )


@login_required
def inventory_memo_create(request):
    memo_type = (
        request.POST.get('memo_type') if request.method == 'POST' else None
    ) or request.GET.get('memo_type', 'inward')
    if memo_type not in ['inward', 'outward']:
        memo_type = 'inward'

    if memo_type == 'inward':
        if not can_user_perform_stock_in(request.user):
            return render_forbidden_response(request, "غير مصرح لك بإنشاء إذن إضافة مخزني.")
    else:
        if not can_user_perform_stock_out(request.user):
            return render_forbidden_response(request, "غير مصرح لك بإنشاء إذن صرف مخزني.")

    scoped_warehouses = get_scoped_queryset(Warehouse.objects.filter(is_active=True), request.user, 'warehouse').order_by('name')
    products = Product.objects.filter(is_active=True).order_by('name')

    from master_data.models import CompanyProfile
    profile = CompanyProfile.get_settings()

    def render_memo_form_error(err_text, status_code=400):
        messages.error(request, err_text)
        sub_items = []
        for idx, p_id in enumerate(product_ids):
            if not p_id:
                continue
            sub_items.append({
                'product_id': p_id,
                'quantity': quantities[idx] if idx < len(quantities) else '1',
                'unit_cost': unit_costs[idx] if idx < len(unit_costs) else '0',
                'batch_number': batches[idx] if idx < len(batches) else '',
                'expiry_date': expiries[idx] if idx < len(expiries) else '',
            })
        ctx = {
            'memo_type': memo_type,
            'warehouses': scoped_warehouses,
            'products': products,
            'profile': profile,
            'form_data': {
                'warehouse': warehouse_id,
                'statement': statement,
                'notes': notes,
            },
            'submitted_items': sub_items,
        }
        return render(request, 'inventory/memo_create.html', ctx, status=status_code)

    if request.method == 'POST':
        warehouse_id = request.POST.get('warehouse')
        statement = request.POST.get('statement', '').strip()
        notes = request.POST.get('notes', '').strip()
        memo_type = request.POST.get('memo_type', memo_type)

        product_ids = request.POST.getlist('product_id[]')
        quantities = request.POST.getlist('quantity[]')
        unit_costs = request.POST.getlist('unit_cost[]')
        batches = request.POST.getlist('batch_number[]')
        expiries = request.POST.getlist('expiry_date[]')

        if not warehouse_id:
            return render_memo_form_error("يرجى اختيار المخزن.")

        warehouse = get_object_or_404(Warehouse, id=warehouse_id)

        if not can_user_access_object(request.user, warehouse, 'operate'):
            return render_forbidden_response(request, "غير مصرح لك بإجراء حركة على هذا المخزن.")

        items_data = []
        try:
            for i, p_id in enumerate(product_ids):
                if not p_id:
                    continue
                qty_val = quantities[i] if i < len(quantities) else ''
                cost_val = unit_costs[i] if i < len(unit_costs) else '0'
                batch_val = batches[i] if i < len(batches) else ''
                expiry_val = expiries[i] if i < len(expiries) else None

                qty_dec = parse_positive_integer_quantity(qty_val)

                try:
                    cost_dec = Decimal(str(cost_val)) if cost_val else Decimal('0.00')
                except Exception:
                    cost_dec = Decimal('0.00')

                items_data.append({
                    'product': int(p_id),
                    'quantity': qty_dec,
                    'unit_cost': cost_dec,
                    'batch_number': batch_val,
                    'expiry_date': expiry_val or None,
                })
        except ValidationError as e:
            return render_memo_form_error(str(e.message if hasattr(e, 'message') else e))

        if not items_data:
            return render_memo_form_error("يرجى إضافة صنف واحد على الأقل.")

        try:
            memo = InventoryMemoService.create_memo(
                warehouse=warehouse,
                memo_type=memo_type,
                statement=statement,
                items_data=items_data,
                user=request.user,
                notes=notes
            )
            if request.FILES.getlist('attachments'):
                from master_data.media_service import store_attachments_from_request
                store_attachments_from_request(memo, request)
            type_label = "إذن الإضافة" if memo_type == 'inward' else "إذن الصرف"
            messages.success(request, f"تم إنشاء وتنفيذ {type_label} بنجاح برقم {memo.memo_number}.")
            return redirect('inventory_memo_detail', pk=memo.pk)
        except ValidationError as e:
            return render_memo_form_error(str(e.message if hasattr(e, 'message') else e))

    context = {
        'memo_type': memo_type,
        'warehouses': scoped_warehouses,
        'products': products,
        'profile': profile,
    }
    return render(request, 'inventory/memo_create.html', context)


@require_permission('inventory:memos/manage')
def inventory_memo_detail(request, pk):
    memo = get_object_or_404(
        InventoryMemo.objects.select_related('warehouse', 'created_by').prefetch_related('items__product'),
        pk=pk
    )
    if not can_user_access_object(request.user, memo, 'view'):
        return render_forbidden_response(request, "لا يمكنك عرض هذا الإذن المخزني خارج نطاق منطقتك الجغرافية أو صلاحيتك.")

    context = {
        'memo': memo,
        'items': memo.items.all(),
    }
    return render(request, 'inventory/memo_detail.html', context)


# ==============================================================================
# PRODUCT TRANSFERS BETWEEN WAREHOUSES IN THE SAME MAIN AREA
# ==============================================================================

@require_permission('inventory:transfers/list')
def product_transfers_list(request):
    """
    List of product transfer requests scoped by user role and main area.
    Integrated into existing inventory/warehouse navigation.
    """
    status_filter = request.GET.get('status', 'all')
    search = request.GET.get('search', '').strip()

    qs = ProductTransferRequest.objects.select_related(
        'requesting_user', 'destination_warehouse', 'destination_warehouse__assigned_user',
        'source_warehouse', 'source_warehouse__assigned_user', 'approved_by', 'executed_by'
    ).prefetch_related('items__product').order_by('-created_at')

    qs = get_scoped_queryset(qs, request.user, 'producttransferrequest')

    active_filters = []
    if status_filter != 'all':
        qs = qs.filter(status=status_filter)
        status_labels = dict(ProductTransferRequest.STATUS_CHOICES)
        active_filters.append({'label': f'الحالة: {status_labels.get(status_filter, status_filter)}', 'param': 'status'})

    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    if date_from:
        qs = qs.filter(created_at__date__gte=date_from)
        active_filters.append({'label': f'من تاريخ: {date_from}', 'param': 'date_from'})
    if date_to:
        qs = qs.filter(created_at__date__lte=date_to)
        active_filters.append({'label': f'إلى تاريخ: {date_to}', 'param': 'date_to'})

    if search:
        qs = filter_by_arabic_search(
            qs, search,
            ['reference_number', 'requesting_user__username', 'requesting_user__first_name', 'requesting_user__last_name', 'destination_warehouse__name', 'source_warehouse__name']
        )
        active_filters.append({'label': f'بحث: {search}', 'param': 'search'})

    paginator, page_obj = paginate_queryset(request, qs, default_per_page=25, max_per_page=100)

    is_super = request.user.is_superuser or getattr(request.user, 'is_super_admin', False)
    can_approve = is_super or has_perm_or_admin(request.user, 'inventory:transfers/approve')

    context = {
        'transfers': page_obj.object_list,
        'page_obj': page_obj,
        'paginator': paginator,
        'current_status': status_filter,
        'selected_date_from': date_from,
        'selected_date_to': date_to,
        'search_query': search,
        'active_filters': active_filters,
        'total_count': paginator.count,
        'can_approve': can_approve,
    }
    return render(request, 'inventory/product_transfers_list.html', context)


@require_permission('inventory:transfers/export')
def product_transfers_export(request):
    """Export filtered and scoped product transfer requests to Excel."""
    status_filter = request.GET.get('status', 'all')
    search = request.GET.get('search', '').strip()
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')

    qs = ProductTransferRequest.objects.select_related(
        'requesting_user', 'destination_warehouse', 'source_warehouse', 'approved_by', 'executed_by'
    ).order_by('-created_at')
    qs = get_scoped_queryset(qs, request.user, 'producttransferrequest')

    if status_filter != 'all':
        qs = qs.filter(status=status_filter)
    if date_from:
        qs = qs.filter(created_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(created_at__date__lte=date_to)
    if search:
        qs = filter_by_arabic_search(
            qs, search,
            ['reference_number', 'requesting_user__username', 'requesting_user__first_name', 'requesting_user__last_name', 'destination_warehouse__name', 'source_warehouse__name']
        )

    columns = [
        {'header': 'رقم الطلب', 'key': 'reference_number', 'width': 18, 'align': 'center'},
        {'header': 'من مخزن', 'key': lambda t: t.source_warehouse.name if t.source_warehouse else '', 'width': 24, 'align': 'right'},
        {'header': 'إلى مخزن', 'key': lambda t: t.destination_warehouse.name if t.destination_warehouse else '', 'width': 24, 'align': 'right'},
        {'header': 'مقدم الطلب', 'key': lambda t: (t.requesting_user.name or t.requesting_user.username) if t.requesting_user else '', 'width': 22, 'align': 'right'},
        {'header': 'الحالة', 'key': lambda t: t.get_status_display(), 'width': 16, 'align': 'center'},
        {'header': 'تاريخ الإنشاء', 'key': lambda t: t.created_at.strftime('%Y-%m-%d %H:%M') if t.created_at else '', 'width': 20, 'align': 'center'},
    ]
    return export_to_excel_response(
        qs,
        columns,
        filename="product_transfers_export",
        sheet_title="التحويلات المخزنية",
        report_title="سجل طلبات التحويل المخزني",
        user=request.user,
    )


@require_permission('inventory:transfers/create')
def product_transfer_create(request):
    """
    Creates a new product transfer request from a warehouse in the same main area.
    If current user is a representative, their destination warehouse is resolved and locked on server.
    """
    is_super = request.user.is_superuser or getattr(request.user, 'is_super_admin', False)

    # Resolve default destination warehouse for representative
    user_rep_wh = get_representative_warehouse(request.user) if is_representative(request.user) else None

    dest_warehouses = get_scoped_queryset(Warehouse.objects.filter(is_active=True), request.user, 'warehouse')
    dest_main_area = user_rep_wh.main_area if user_rep_wh else None

    # Available source warehouses (reps may request from Main or non-rep regional hubs in their main area, never peer rep custody warehouses)
    if user_rep_wh:
        all_active_whs = Warehouse.objects.filter(is_active=True, is_rep_warehouse=False).select_related('area', 'assigned_user')
        source_warehouses = [
            w for w in all_active_whs
            if w.id != user_rep_wh.id and (
                w.is_main or (w.main_area and dest_main_area and w.main_area.id == dest_main_area.id)
            )
        ]
    else:
        source_warehouses = get_scoped_queryset(Warehouse.objects.filter(is_active=True), request.user, 'warehouse')

    products = Product.objects.filter(is_active=True).order_by('name')

    def render_transfer_form_error(err_text):
        messages.error(request, err_text)
        sub_items = []
        for idx, p_id in enumerate(product_ids):
            if not p_id:
                continue
            sub_items.append({
                'product_id': p_id,
                'quantity': quantities[idx] if idx < len(quantities) else '1',
                'batch_number': batches[idx] if idx < len(batches) else '',
            })
        ctx = {
            'dest_warehouses': dest_warehouses,
            'user_rep_wh': user_rep_wh,
            'source_warehouses': source_warehouses,
            'products': products,
            'form_data': {
                'source_warehouse': source_wh_id,
                'destination_warehouse': dest_wh_id,
                'notes': notes,
            },
            'submitted_items': sub_items,
        }
        return render(request, 'inventory/product_transfer_create.html', ctx)

    if request.method == 'POST':
        source_wh_id = request.POST.get('source_warehouse')
        dest_wh_id = request.POST.get('destination_warehouse')
        notes = request.POST.get('notes', '').strip()

        # Parse submitted line items early so error recovery never fails with UnboundLocalError
        product_ids = request.POST.getlist('products[]')
        quantities = request.POST.getlist('quantities[]')
        batches = request.POST.getlist('batches[]') if 'batches[]' in request.POST else []

        # Resolve destination warehouse
        if dest_wh_id:
            destination_warehouse = get_object_or_404(Warehouse, id=dest_wh_id)
        elif user_rep_wh:
            destination_warehouse = user_rep_wh
        else:
            return render_transfer_form_error("يرجى اختيار مخزن الاستلام.")

        if not source_wh_id:
            return render_transfer_form_error("يرجى اختيار المخزن المحول منه.")

        source_warehouse = get_object_or_404(Warehouse, id=source_wh_id)

        items_data = []
        try:
            for i, p_id in enumerate(product_ids):
                if not p_id:
                    continue
                qty_val = quantities[i] if i < len(quantities) else ''
                qty_dec = parse_positive_integer_quantity(qty_val)

                batch_val = batches[i] if i < len(batches) else ''
                items_data.append({
                    'product': int(p_id),
                    'quantity': qty_dec,
                    'batch_number': batch_val
                })
        except ValidationError as e:
            return render_transfer_form_error(str(e.message if hasattr(e, 'message') else e))

        if not items_data:
            return render_transfer_form_error("يرجى إضافة صنف واحد على الأقل.")

        try:
            transfer_req = ProductTransferService.create_request(
                requesting_user=request.user,
                destination_warehouse=destination_warehouse,
                source_warehouse=source_warehouse,
                items_data=items_data,
                notes=notes
            )
            if request.FILES.getlist('attachments'):
                from master_data.media_service import store_attachments_from_request
                store_attachments_from_request(transfer_req, request)
            messages.success(request, f"تم إنشاء طلب التحويل المخزني بنجاح ({transfer_req.reference_number}) وهو قيد المراجعة والاعتماد.")
            return redirect('product_transfer_detail', pk=transfer_req.pk)
        except ValidationError as e:
            return render_transfer_form_error(str(e.message if hasattr(e, 'message') else e))

    context = {
        'dest_warehouses': dest_warehouses,
        'user_rep_wh': user_rep_wh,
        'source_warehouses': source_warehouses,
        'products': products,
    }
    return render(request, 'inventory/product_transfer_create.html', context)


@login_required
@require_permission('inventory:transfers/view')
def product_transfer_detail(request, pk):
    """
    Detail page for a product transfer request showing approval status,
    items, linked inventory memos, and execution controls.
    """
    transfer_req = get_object_or_404(
        ProductTransferRequest.objects.select_related(
            'requesting_user', 'destination_warehouse', 'destination_warehouse__assigned_user',
            'source_warehouse', 'source_warehouse__assigned_user',
            'approved_by', 'executed_by', 'outward_memo', 'inward_memo'
        ).prefetch_related('items__product'),
        pk=pk
    )

    if not can_user_access_object(request.user, transfer_req, 'view'):
        return render_forbidden_response(request, "لا يمكنك عرض هذا الطلب خارج نطاق منطقتك الجغرافية أو صلاحيتك.")

    is_super = request.user.is_superuser or getattr(request.user, 'is_super_admin', False)
    has_approval_perm = is_super or has_perm_or_admin(request.user, 'inventory:transfers/approve')
    has_execute_perm = is_super or has_perm_or_admin(request.user, 'inventory:transfers/execute')

    # Approval and execution permission checks
    can_approve = has_approval_perm and transfer_req.status == 'pending' and (is_super or transfer_req.requesting_user_id != request.user.id)
    can_reject = has_approval_perm and transfer_req.status in ['pending', 'approved']
    can_execute = has_execute_perm and transfer_req.status == 'approved'
    can_cancel = (transfer_req.requesting_user_id == request.user.id or is_super or has_perm_or_admin(request.user, 'inventory:transfers/cancel')) and transfer_req.status in ['pending', 'approved']

    context = {
        'transfer': transfer_req,
        'items': transfer_req.items.all(),
        'can_approve': can_approve,
        'can_reject': can_reject,
        'can_execute': can_execute,
        'can_cancel': can_cancel,
    }
    return render(request, 'inventory/product_transfer_detail.html', context)


@login_required
def product_transfer_action(request, pk, action):
    """
    Action endpoint to approve, reject, cancel, or execute an inter-warehouse transfer.
    Strictly enforced via permissions.
    """
    transfer_req = get_object_or_404(ProductTransferRequest, pk=pk)
    is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'application/json' in request.headers.get('accept', '')

    is_super = request.user.is_superuser or getattr(request.user, 'is_super_admin', False)

    action_perm_map = {
        'approve': 'inventory:transfers/approve',
        'reject': 'inventory:transfers/approve',
        'execute': 'inventory:transfers/execute',
        'cancel': 'inventory:transfers/cancel',
    }
    needed_perm = action_perm_map.get(action)
    if action == 'cancel' and transfer_req.requesting_user_id == request.user.id:
        pass  # Creator allowed to cancel pending transfer
    elif needed_perm and not has_perm_or_admin(request.user, needed_perm):
        return render_forbidden_response(request, f"ليس لديك صلاحية لتنفيذ هذا الإجراء ({needed_perm})", perm_codename=needed_perm)

    if not can_user_access_object(request.user, transfer_req, action):
        return render_forbidden_response(request, "لا يمكنك اتخاذ هذا الإجراء خارج نطاق صلاحيتك أو مخازنك المصرح بها.")

    try:
        if action == 'approve':
            if not is_super and transfer_req.requesting_user_id == request.user.id:
                messages.error(request, "لا يمكن لمقدم طلب التحويل اعتماده بنفسه (مبدأ الرقابة الثنائية).")
                return redirect('product_transfer_detail', pk=transfer_req.pk)
            notes = request.POST.get('approval_notes', '').strip()
            ProductTransferService.approve_request(transfer_req, request.user, notes=notes)
            msg = f"تم اعتماد طلب التحويل المخزني {transfer_req.reference_number} بنجاح. الطلب الآن جاهز للتنفيذ المخزني."
            if is_ajax:
                return JsonResponse({'success': True, 'message': msg, 'status': transfer_req.status})
            messages.success(request, msg)

        elif action == 'reject':
            reason = request.POST.get('rejection_reason', '').strip() or request.POST.get('reason', '').strip()
            if not reason:
                msg = "يرجى كتابة سبب رفض طلب التحويل."
                if is_ajax:
                    return JsonResponse({'success': False, 'message': msg}, status=400)
                messages.error(request, msg)
                return redirect('product_transfer_detail', pk=transfer_req.pk)
            ProductTransferService.reject_request(transfer_req, request.user, reason=reason)
            msg = f"تم رفض طلب التحويل المخزني {transfer_req.reference_number}."
            if is_ajax:
                return JsonResponse({'success': True, 'message': msg, 'status': transfer_req.status})
            messages.error(request, msg)

        elif action == 'cancel':
            reason = request.POST.get('cancellation_reason', '').strip()
            ProductTransferService.cancel_request(transfer_req, request.user, reason=reason)
            msg = f"تم إلغاء طلب التحويل المخزني {transfer_req.reference_number}."
            if is_ajax:
                return JsonResponse({'success': True, 'message': msg, 'status': transfer_req.status})
            messages.warning(request, msg)

        elif action == 'execute':
            ProductTransferService.execute_transfer(transfer_req, request.user)
            msg = f"تم تنفيذ التحويل المخزني {transfer_req.reference_number} بنجاح، وتم خصم وإضافة الكميات وتوليد أذونات المخازن المقابلة."
            if is_ajax:
                return JsonResponse({'success': True, 'message': msg, 'status': transfer_req.status})
            messages.success(request, msg)

        else:
            messages.error(request, "إجراء غير معروف.")

    except ValidationError as e:
        err_msg = str(e.message if hasattr(e, 'message') else e)
        if is_ajax:
            return JsonResponse({'success': False, 'message': err_msg}, status=400)
        messages.error(request, err_msg)

    return redirect('product_transfer_detail', pk=transfer_req.pk)


@require_permission([
    'inventory:stocks/view',
    'sales:orders/create',
    'sales:orders/edit',
    'inventory:transfers/create',
    'inventory:memos/manage',
    'purchases:orders/create'
])
def inventory_warehouse_stock_api(request):
    """
    Returns available product stock for a given warehouse.
    Enforces warehouse data-scope access check.
    """
    warehouse_id = request.GET.get('warehouse_id') or request.GET.get('warehouse')
    if not warehouse_id or not str(warehouse_id).isdigit():
        return JsonResponse({'error': 'يرجى تحديد المخزن.'}, status=400)

    warehouse = get_object_or_404(Warehouse, id=int(warehouse_id))
    if not can_user_access_object(request.user, warehouse, 'view'):
        return JsonResponse({'error': 'غير مصرح لك بالوصول لبيانات هذا المخزن.'}, status=403)

    stocks = InventoryStock.objects.filter(warehouse=warehouse).select_related('product')
    stocks_map = {s.product_id: s for s in stocks}

    products = Product.objects.filter(is_active=True).order_by('name')
    results = []
    for p in products:
        st = stocks_map.get(p.id)
        qty_on_hand = st.qty_on_hand if st else Decimal('0.00')
        qty_reserved = st.qty_reserved if st else Decimal('0.00')
        qty_available = max(Decimal('0.00'), qty_on_hand - qty_reserved)
        results.append({
            'id': p.id,
            'name': p.name,
            'sku': p.sku_code,
            'price': str(p.retail_price or '0.00'),
            'cost': str(st.product_cost if st and st.product_cost else (p.default_purchase_cost or '0.00')),
            'qty_on_hand': float(qty_on_hand),
            'qty_reserved': float(qty_reserved),
            'qty_available': float(qty_available),
        })

    return JsonResponse({
        'warehouse_id': warehouse.id,
        'warehouse_name': warehouse.name,
        'count': len(results),
        'products': results
    })
