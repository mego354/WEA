from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q, Count
from django.http import JsonResponse
from django.core.exceptions import ValidationError

from master_data.excel_utils import export_to_excel_response
from master_data.pagination_utils import paginate_queryset
from accounts.permissions import (
    require_permission, has_perm_or_admin, render_forbidden_response,
    get_scoped_queryset, can_user_access_object, is_accountant, is_manager_or_higher
)
from accounts.services import is_representative, get_representative_warehouse
from catalog.models import Product
from .models import (
    Warehouse, InventoryStock, InventoryLot, InventoryMemo,
    ProductTransferRequest, ProductTransferRequestItem
)
from .services import ProductTransferService


@require_permission('inventory:stocks/view')
def inventory_stock_list(request):
    warehouse_id = request.GET.get('warehouse')
    search = request.GET.get('search', '').strip()

    qs = InventoryStock.objects.select_related('warehouse', 'product', 'product__category').order_by('warehouse__name', 'product__name')
    qs = get_scoped_queryset(qs, request.user, 'inventorystock')

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

    # Scoped warehouses available for filter dropdown
    warehouses = get_scoped_queryset(Warehouse.objects.filter(is_active=True), request.user, 'warehouse').order_by('name')

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


@require_permission('inventory:stocks/export')
def inventory_stock_export(request):
    warehouse_id = request.GET.get('warehouse')
    search = request.GET.get('search', '').strip()

    qs = InventoryStock.objects.select_related('warehouse', 'product', 'product__category').order_by('warehouse__name', 'product__name')
    qs = get_scoped_queryset(qs, request.user, 'inventorystock')

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
    """
    List of warehouses scoped by manager region or rep ownership.
    Managers see main warehouses + warehouses of reps in their main area.
    """
    if not has_perm_or_admin(request.user, ['inventory:warehouses/manage', 'inventory:stocks/view']):
        return render_forbidden_response(request, "لا تملك صلاحية عرض قائمة المخازن.")

    search = request.GET.get('search', '').strip()
    qs = Warehouse.objects.select_related('manager', 'assigned_user', 'area', 'area__parent').all().order_by('name')
    qs = get_scoped_queryset(qs, request.user, 'warehouse')

    if request.method == 'POST':
        if not has_perm_or_admin(request.user, 'inventory:warehouses/manage'):
            return render_forbidden_response(request, "لا تملك صلاحية إنشاء مخزن جديد.")
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
        'can_manage_warehouses': has_perm_or_admin(request.user, 'inventory:warehouses/manage'),
    }
    return render(request, 'inventory/warehouses_list.html', context)


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

    if search:
        qs = qs.filter(
            Q(memo_number__icontains=search) |
            Q(statement__icontains=search)
        )
        active_filters.append({'label': f'بحث: {search}', 'param': 'search'})

    warehouses = get_scoped_queryset(Warehouse.objects.filter(is_active=True), request.user, 'warehouse').order_by('name')

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


# ==============================================================================
# PRODUCT TRANSFERS BETWEEN WAREHOUSES IN THE SAME MAIN AREA
# ==============================================================================

@login_required
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

    if search:
        qs = qs.filter(
            Q(reference_number__icontains=search) |
            Q(requesting_user__username__icontains=search) |
            Q(requesting_user__first_name__icontains=search) |
            Q(requesting_user__last_name__icontains=search) |
            Q(destination_warehouse__name__icontains=search) |
            Q(source_warehouse__name__icontains=search)
        )
        active_filters.append({'label': f'بحث: {search}', 'param': 'search'})

    paginator, page_obj = paginate_queryset(request, qs, default_per_page=25, max_per_page=100)

    is_super = request.user.is_superuser or getattr(request.user, 'is_super_admin', False)
    can_approve = is_super or is_accountant(request.user) or has_perm_or_admin(request.user, 'inventory:transfers/approve')

    context = {
        'transfers': page_obj.object_list,
        'page_obj': page_obj,
        'paginator': paginator,
        'current_status': status_filter,
        'search_query': search,
        'active_filters': active_filters,
        'total_count': paginator.count,
        'can_approve': can_approve,
    }
    return render(request, 'inventory/product_transfers_list.html', context)


@login_required
def product_transfer_create(request):
    """
    Creates a new product transfer request from a warehouse in the same main area.
    If current user is a representative, their destination warehouse is resolved and locked on server.
    """
    is_super = request.user.is_superuser or getattr(request.user, 'is_super_admin', False)

    # Resolve default destination warehouse for representative
    user_rep_wh = get_representative_warehouse(request.user) if is_representative(request.user) else None

    if request.method == 'POST':
        source_wh_id = request.POST.get('source_warehouse')
        dest_wh_id = request.POST.get('destination_warehouse')
        notes = request.POST.get('notes', '').strip()

        # If user is representative, always enforce their designated warehouse as destination
        if user_rep_wh:
            destination_warehouse = user_rep_wh
        else:
            if not dest_wh_id:
                messages.error(request, "يرجى اختيار مخزن الاستلام.")
                return redirect('product_transfer_create')
            destination_warehouse = get_object_or_404(Warehouse, id=dest_wh_id)

        if not source_wh_id:
            messages.error(request, "يرجى اختيار المخزن المحول منه.")
            return redirect('product_transfer_create')

        source_warehouse = get_object_or_404(Warehouse, id=source_wh_id)

        # Parse submitted line items
        product_ids = request.POST.getlist('products[]')
        quantities = request.POST.getlist('quantities[]')
        batches = request.POST.getlist('batches[]') if 'batches[]' in request.POST else []

        items_data = []
        for i, p_id in enumerate(product_ids):
            if not p_id:
                continue
            qty_val = quantities[i] if i < len(quantities) else '0'
            try:
                qty_dec = Decimal(str(qty_val))
            except Exception:
                qty_dec = Decimal('0.00')

            batch_val = batches[i] if i < len(batches) else ''
            items_data.append({
                'product': int(p_id),
                'quantity': qty_dec,
                'batch_number': batch_val
            })

        if not items_data:
            messages.error(request, "يرجى إضافة صنف واحد على الأقل.")
            return redirect('product_transfer_create')

        try:
            transfer_req = ProductTransferService.create_request(
                requesting_user=request.user,
                destination_warehouse=destination_warehouse,
                source_warehouse=source_warehouse,
                items_data=items_data,
                notes=notes
            )
            messages.success(request, f"تم إنشاء طلب التحويل المخزني بنجاح ({transfer_req.reference_number}) وهو قيد المراجعة والاعتماد.")
            return redirect('product_transfer_detail', pk=transfer_req.pk)
        except ValidationError as e:
            messages.error(request, str(e.message if hasattr(e, 'message') else e))
            return redirect('product_transfer_create')

    # Available destination warehouses
    if user_rep_wh:
        dest_warehouses = [user_rep_wh]
        dest_main_area = user_rep_wh.main_area
    else:
        dest_warehouses = get_scoped_queryset(Warehouse.objects.filter(is_active=True), request.user, 'warehouse')
        dest_main_area = None

    # Available source warehouses: filter to same main area as destination
    all_active_whs = Warehouse.objects.filter(is_active=True).select_related('area', 'assigned_user')
    if dest_main_area:
        # Same main area filter
        source_warehouses = [
            w for w in all_active_whs
            if w.main_area and w.main_area.id == dest_main_area.id and (not user_rep_wh or w.id != user_rep_wh.id)
        ]
    else:
        source_warehouses = all_active_whs

    products = Product.objects.filter(is_active=True).order_by('name')

    context = {
        'dest_warehouses': dest_warehouses,
        'user_rep_wh': user_rep_wh,
        'source_warehouses': source_warehouses,
        'products': products,
    }
    return render(request, 'inventory/product_transfer_create.html', context)


@login_required
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
    is_accountant_user = is_accountant(request.user)
    has_approval_perm = is_super or is_accountant_user or has_perm_or_admin(request.user, 'inventory:transfers/approve')

    # Approval permission checks
    can_approve = has_approval_perm and transfer_req.status == 'pending' and (is_super or transfer_req.requesting_user_id != request.user.id)
    can_reject = has_approval_perm and transfer_req.status in ['pending', 'approved']
    can_execute = has_approval_perm and transfer_req.status == 'approved'
    can_cancel = (transfer_req.requesting_user_id == request.user.id or is_super) and transfer_req.status in ['pending', 'approved']

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
    Strictly enforced on the backend.
    """
    transfer_req = get_object_or_404(ProductTransferRequest, pk=pk)
    is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'application/json' in request.headers.get('accept', '')

    is_super = request.user.is_superuser or getattr(request.user, 'is_super_admin', False)
    is_accountant_user = is_accountant(request.user)
    has_approval_perm = is_super or is_accountant_user or has_perm_or_admin(request.user, 'inventory:transfers/approve')

    try:
        if action == 'approve':
            if not has_approval_perm:
                return render_forbidden_response(request, "صلاحية اعتماد طلب التحويل مقصورة على SuperAdmin والمحاسبين المعتمدين.")
            notes = request.POST.get('approval_notes', '').strip()
            ProductTransferService.approve_request(transfer_req, request.user, notes=notes)
            msg = f"تم اعتماد طلب التحويل المخزني {transfer_req.reference_number} بنجاح. الطلب الآن جاهز للتنفيذ المخزني."
            if is_ajax:
                return JsonResponse({'success': True, 'message': msg, 'status': transfer_req.status})
            messages.success(request, msg)

        elif action == 'reject':
            if not has_approval_perm:
                return render_forbidden_response(request, "صلاحية رفض طلب التحويل مقصورة على SuperAdmin والمحاسبين المعتمدين.")
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
            if not has_approval_perm:
                return render_forbidden_response(request, "صلاحية تنفيذ التحويل ونقل المخزون مقصورة على SuperAdmin والمحاسبين.")
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
