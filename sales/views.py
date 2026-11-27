from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import F, Q, Sum, Count
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.http import JsonResponse
from django.urls import reverse

from django.core.paginator import Paginator
from master_data.pagination_utils import paginate_queryset
from master_data.excel_utils import export_to_excel_response
from master_data.models import Area
from contacts.constants import CUSTOMER_CATEGORIES
from contacts.views import contact_detail, contact_create, contact_edit
from .models import (
    SalesOrder, SalesOrderItem, CustomerAccount, CustomerTransaction, Collection,
    SalesReturnOrder, SalesReturnOrderItem
)
from .services import (
    SalesOrderService, CollectionService,
    SalesReturnOrderService, build_sales_return_timeline
)
from master_data.search_utils import (
    filter_by_arabic_search,
    parse_search_limit,
    get_bounded_select_options,
    serialize_contact_option,
    serialize_warehouse_option,
    serialize_vault_option,
)
from contacts.models import Contact
from catalog.models import Product
from inventory.models import Warehouse
from treasury.models import Vault
from accounts.permissions import (
    require_permission, has_perm_or_admin, render_forbidden_response,
    get_scoped_queryset, can_user_access_object
)
from accounts.scope_service import ScopeResolutionService


@require_permission('sales:orders/list')
def sales_orders_list(request):
    from master_data.filter_utils import (
        parse_multi_str,
        parse_single_int,
        resolve_scoped_area_brick_filters,
        build_contact_area_q,
        build_contact_brick_q,
    )
    from master_data.date_filter_utils import resolve_date_range

    status_choices_dict = dict(SalesOrder.STATUS_CHOICES)
    payment_choices_dict = dict(SalesOrder.PAYMENT_STATUS_CHOICES)
    selected_statuses = [s for s in parse_multi_str(request.GET, 'status') if s in status_choices_dict]
    selected_payment_statuses = [p for p in parse_multi_str(request.GET, 'payment_status') if p in payment_choices_dict]
    payment_status_filter = selected_payment_statuses[0] if len(selected_payment_statuses) == 1 else 'all'

    customer_id_int = parse_single_int(request.GET, 'customer')
    customer_filter = str(customer_id_int) if customer_id_int else ''
    search = request.GET.get('search', '').strip()
    parsed_from, parsed_to, active_preset, date_from, date_to = resolve_date_range(request, default_preset='all_time')
    total_min = request.GET.get('total_min', '').strip()
    total_max = request.GET.get('total_max', '').strip()
    remaining_min = request.GET.get('remaining_min', '').strip()
    remaining_max = request.GET.get('remaining_max', '').strip()

    qs = SalesOrder.objects.select_related('customer', 'customer__area', 'customer__brick', 'source_warehouse', 'created_by').all().order_by('-order_date', '-id')
    qs = get_scoped_queryset(qs, request.user, 'salesorder')
    qs = SalesOrder.with_payment_totals(qs)

    active_filters = []

    if selected_statuses:
        qs = qs.filter(status__in=selected_statuses)
        for s in selected_statuses:
            active_filters.append({'label': 'حالة الطلب', 'value': status_choices_dict.get(s, s), 'param': 'status', 'remove_value': s})

    if selected_payment_statuses:
        qs = qs.filter(payment_status__in=selected_payment_statuses)
        for ps in selected_payment_statuses:
            active_filters.append({'label': 'حالة السداد', 'value': payment_choices_dict.get(ps, ps), 'param': 'payment_status', 'remove_value': ps})

    if customer_id_int:
        qs = qs.filter(customer_id=customer_id_int)
        c_obj = ScopeResolutionService.get_scoped_choices(request.user, 'customers', 'sales').filter(id=customer_id_int).first()
        active_filters.append({'label': 'العميل', 'value': c_obj.name if c_obj else customer_filter, 'param': 'customer'})

    main_area_ids, brick_ids, selected_main_areas_chips, selected_bricks_chips = resolve_scoped_area_brick_filters(
        request, 'sales',
        area_params=('main_area', 'area_id', 'governorate'),
        brick_params=('brick', 'brick_id', 'area'),
    )
    if main_area_ids:
        qs = qs.filter(build_contact_area_q(main_area_ids, prefix='customer', include_addresses=False))
        for a_chip in selected_main_areas_chips:
            active_filters.append({'label': 'المنطقة الرئيسية', 'value': a_chip['name'], 'param': 'main_area', 'remove_value': str(a_chip['id'])})
    if brick_ids:
        qs = qs.filter(build_contact_brick_q(brick_ids, prefix='customer', include_addresses=False))
        for b_chip in selected_bricks_chips:
            active_filters.append({'label': 'الخط الجغرافي / Brick', 'value': b_chip['name'], 'param': 'brick', 'remove_value': str(b_chip['id'])})

    if parsed_from:
        qs = qs.filter(order_date__gte=parsed_from)
        active_filters.append({'label': 'من تاريخ', 'value': date_from, 'param': 'date_from'})

    if parsed_to:
        qs = qs.filter(order_date__lte=parsed_to)
        active_filters.append({'label': 'إلى تاريخ', 'value': date_to, 'param': 'date_to'})

    # Financial Total Amount Range Filters (Requirement B1)
    if total_min:
        try:
            val_min = Decimal(total_min)
            qs = qs.filter(grand_total__gte=val_min)
            active_filters.append({'label': 'الحد الأدنى للقيمة', 'value': f'{val_min:,.2f} ج.م', 'param': 'total_min'})
        except Exception:
            total_min = ''

    if total_max:
        try:
            val_max = Decimal(total_max)
            qs = qs.filter(grand_total__lte=val_max)
            active_filters.append({'label': 'الحد الأقصى للقيمة', 'value': f'{val_max:,.2f} ج.م', 'param': 'total_max'})
        except Exception:
            total_max = ''

    # Remaining Outstanding Balance Range Filters (Requirement B1)
    if remaining_min:
        try:
            rem_min = Decimal(remaining_min)
            qs = qs.filter(grand_total__gte=F('_annotated_total_paid') + rem_min)
            active_filters.append({'label': 'الحد الأدنى للمتبقي', 'value': f'{rem_min:,.2f} ج.م', 'param': 'remaining_min'})
        except Exception:
            remaining_min = ''

    if remaining_max:
        try:
            rem_max = Decimal(remaining_max)
            qs = qs.filter(grand_total__lte=F('_annotated_total_paid') + rem_max)
            active_filters.append({'label': 'الحد الأقصى للمتبقي', 'value': f'{rem_max:,.2f} ج.م', 'param': 'remaining_max'})
        except Exception:
            remaining_max = ''

    if search:
        qs = filter_by_arabic_search(qs, search, ['order_number', 'serial_num', 'customer__name'])
        active_filters.append({'label': 'بحث', 'value': search, 'param': 'search'})

    paginator, page_obj = paginate_queryset(request, qs, default_per_page=25, max_per_page=100)

    # Scoped bounded customer filter options (selected customer preserved for smart search)
    customers = get_bounded_select_options(
        ScopeResolutionService.get_scoped_choices(request.user, 'customers', 'sales'),
        selected_id=customer_filter,
        limit=100,
    )

    # Dedicated real scoped statistics cards matching filtered queryset
    agg = qs.aggregate(
        total_orders=Count('id'),
        total_value=Sum('grand_total'),
        total_collected=Sum('_annotated_total_paid'),
    )
    tot_val = agg['total_value'] or Decimal('0.00')
    tot_col = agg['total_collected'] or Decimal('0.00')
    tot_rem = max(Decimal('0.00'), tot_val - tot_col)
    stats = {
        'total_orders': agg['total_orders'] or 0,
        'total_value': tot_val,
        'total_collected': tot_col,
        'total_remaining': tot_rem,
        'invoiced_value': tot_val,
        'pending_count': 0,
    }

    order_status_options = [{'value': k, 'label': v} for k, v in SalesOrder.STATUS_CHOICES]
    selected_order_status_items = [o for o in order_status_options if o['value'] in selected_statuses]
    payment_status_options = [{'value': k, 'label': v} for k, v in SalesOrder.PAYMENT_STATUS_CHOICES]
    selected_payment_status_items = [o for o in payment_status_options if o['value'] in selected_payment_statuses]

    context = {
        'orders': page_obj.object_list,
        'page_obj': page_obj,
        'paginator': paginator,
        'current_payment_status': payment_status_filter,
        'payment_statuses': SalesOrder.PAYMENT_STATUS_CHOICES,
        'order_status_options': order_status_options,
        'selected_order_status_items': selected_order_status_items,
        'selected_statuses': selected_statuses,
        'payment_status_options': payment_status_options,
        'selected_payment_status_items': selected_payment_status_items,
        'selected_payment_statuses': selected_payment_statuses,
        'selected_main_areas_chips': selected_main_areas_chips,
        'selected_bricks_chips': selected_bricks_chips,
        'active_preset': active_preset,
        'date_from': date_from,
        'date_to': date_to,
        'selected_customer': customer_filter,
        'selected_date_from': date_from,
        'selected_date_to': date_to,
        'selected_total_min': total_min,
        'selected_total_max': total_max,
        'selected_remaining_min': remaining_min,
        'selected_remaining_max': remaining_max,
        'search_query': search,
        'customers': customers,
        'active_filters': active_filters,
        'total_count': paginator.count,
        'stats': stats,
    }
    return render(request, 'sales/sales_orders_list.html', context)


@require_permission('sales:orders/create')
def sales_order_create(request):
    if request.method == 'POST':
        customer_id = request.POST.get('customer')
        warehouse_id = request.POST.get('warehouse')
        order_date = request.POST.get('order_date')
        delivery_date = request.POST.get('delivery_date') or None
        due_date = request.POST.get('due_date') or None
        custom_discount_percentage = request.POST.get('custom_discount_percentage') or '0.00'
        shipping_fees = request.POST.get('shipping_fees') or '0.00'
        notes = request.POST.get('notes', '').strip()

        # Parse item rows
        product_ids = request.POST.getlist('product_id[]')
        quantities = request.POST.getlist('quantity[]')
        unit_prices = request.POST.getlist('unit_price[]')
        discounts = request.POST.getlist('discount_percentage[]')

        items_data = []
        for i in range(len(product_ids)):
            p_id = product_ids[i]
            if not p_id:
                continue
            prod = Product.objects.filter(id=p_id).first()
            if not prod:
                continue
            qty = Decimal(quantities[i] or '1')
            price = Decimal(unit_prices[i] or '0')
            disc = Decimal(discounts[i] or '0') if i < len(discounts) else Decimal('0')

            items_data.append({
                'product': prod,
                'quantity': qty,
                'unit_price': price,
                'discount_percentage': disc,
            })

        from accounts.services import is_representative, get_representative_warehouse
        is_rep = is_representative(request.user)
        user_rep_wh = get_representative_warehouse(request.user) if is_rep else None

        def render_form_error(err_text):
            messages.error(request, err_text)
            sub_data = {
                'customer': customer_id,
                'warehouse': warehouse_id,
                'order_date': order_date,
                'delivery_date': delivery_date,
                'due_date': due_date,
                'custom_discount_percentage': custom_discount_percentage,
                'shipping_fees': shipping_fees,
                'notes': notes,
            }
            sub_items = []
            for idx, p_id in enumerate(product_ids):
                if not p_id:
                    continue
                sub_items.append({
                    'product_id': p_id,
                    'quantity': quantities[idx] if idx < len(quantities) else '1',
                    'unit_price': unit_prices[idx] if idx < len(unit_prices) else '0',
                    'discount_percentage': discounts[idx] if idx < len(discounts) else '0',
                })
            customers_qs = ScopeResolutionService.get_scoped_choices(request.user, 'customers', 'sales')
            customers = get_bounded_select_options(customers_qs, selected_id=customer_id, limit=100)
            warehouses = ScopeResolutionService.get_scoped_choices(request.user, 'warehouses', 'sales')
            products = Product.objects.filter(is_active=True, sellable=True)
            ctx = {
                'customers': customers,
                'selected_customer_id': int(customer_id) if customer_id and str(customer_id).isdigit() else None,
                'warehouses': warehouses,
                'user_rep_wh': user_rep_wh,
                'is_rep': is_rep,
                'products': products,
                'form_data': sub_data,
                'submitted_items': sub_items,
            }
            return render(request, 'sales/sales_order_create.html', ctx)

        if user_rep_wh:
            if warehouse_id and str(warehouse_id) != str(user_rep_wh.id):
                forged_wh = get_object_or_404(Warehouse, id=warehouse_id)
                if not can_user_access_object(request.user, forged_wh, 'operate'):
                    return render_forbidden_response(request, "لا يمكنك إجراء مبيعات من مخزن خارج نطاق صلاحيتك.")
            warehouse = user_rep_wh
        elif warehouse_id:
            warehouse = get_object_or_404(Warehouse, id=warehouse_id)
            if not can_user_access_object(request.user, warehouse, 'operate'):
                return render_forbidden_response(request, "لا يمكنك إجراء مبيعات من مخزن خارج نطاق صلاحيتك.")
        else:
            return render_form_error("يرجى تحديد المخزن.")

        if not customer_id:
            return render_form_error("يرجى تحديد العميل.")

        customer = get_object_or_404(Contact, id=customer_id)
        if not can_user_access_object(request.user, customer, 'view'):
            return render_forbidden_response(request, "غير مصرح لك بإنشاء أمر بيع لعميل خارج نطاق منطقتك الجغرافية.")
        if not customer.is_customer or customer.status != 'customer':
            return render_form_error("يمكن إنشاء أمر بيع للعملاء المعتمدين فقط (حالة: عميل).")

        try:
            order = SalesOrderService.create_order(
                customer=customer,
                source_warehouse=warehouse,
                order_date=order_date,
                items_data=items_data,
                user=request.user,
                delivery_date=delivery_date,
                due_date=due_date,
                custom_discount_percentage=Decimal(custom_discount_percentage),
                shipping_fees=Decimal(shipping_fees),
                notes=notes
            )
            if request.FILES.getlist('attachments'):
                from master_data.media_service import store_attachments_from_request
                store_attachments_from_request(order, request)
            messages.success(request, f"تم إنشاء أمر البيع بنجاح ({order.order_number}) بإجمالي {order.grand_total:,.2f} ج.م.")
            return redirect('sales_order_detail', pk=order.pk)
        except ValidationError as e:
            return render_form_error(str(e.message if hasattr(e, 'message') else e))

    from accounts.services import is_representative, get_representative_warehouse
    is_rep = is_representative(request.user)
    user_rep_wh = get_representative_warehouse(request.user) if is_rep else None

    raw_selected_customer = request.GET.get('customer') or request.GET.get('customer_id')
    customers_qs = ScopeResolutionService.get_scoped_choices(request.user, 'customers', 'sales')
    customers = get_bounded_select_options(customers_qs, selected_id=raw_selected_customer, limit=100)
    selected_customer_id = None
    if raw_selected_customer and str(raw_selected_customer).isdigit():
        candidate_cid = int(raw_selected_customer)
        if any(c.id == candidate_cid for c in customers):
            selected_customer_id = candidate_cid
    warehouses = ScopeResolutionService.get_scoped_choices(request.user, 'warehouses', 'sales')
    products = Product.objects.filter(is_active=True, sellable=True)

    context = {
        'customers': customers,
        'selected_customer_id': selected_customer_id,
        'warehouses': warehouses,
        'user_rep_wh': user_rep_wh,
        'is_rep': is_rep,
        'products': products,
    }
    return render(request, 'sales/sales_order_create.html', context)


@require_permission('sales:orders/edit')
def sales_order_edit(request, pk):
    order = get_object_or_404(
        SalesOrder.objects.select_related('customer', 'source_warehouse').prefetch_related('items__product'),
        pk=pk
    )
    if not can_user_access_object(request.user, order, 'edit'):
        return render_forbidden_response(request, "لا يمكنك تعديل هذا الطلب خارج نطاق منطقتك الجغرافية أو صلاحياتك.")

    if order.status == 'cancelled':
        messages.error(request, "لا يمكن تعديل أمر بيع ملغي.")
        return redirect('sales_order_detail', pk=order.pk)

    if order.collections.exists():
        messages.error(request, "لا يمكن تعديل أمر البيع لوجود تحصيلات مسجلة عليه بالفعل.")
        return redirect('sales_order_detail', pk=order.pk)

    if request.method == 'POST':
        customer_id = request.POST.get('customer')
        warehouse_id = request.POST.get('warehouse')
        order_date = request.POST.get('order_date')
        delivery_date = request.POST.get('delivery_date') or None
        due_date = request.POST.get('due_date') or None
        custom_discount_percentage = request.POST.get('custom_discount_percentage') or '0.00'
        shipping_fees = request.POST.get('shipping_fees') or '0.00'
        notes = request.POST.get('notes', '').strip()

        product_ids = request.POST.getlist('product_id[]')
        quantities = request.POST.getlist('quantity[]')
        unit_prices = request.POST.getlist('unit_price[]')
        discounts = request.POST.getlist('discount_percentage[]')

        items_data = []
        for i in range(len(product_ids)):
            p_id = product_ids[i]
            if not p_id:
                continue
            prod = Product.objects.filter(id=p_id).first()
            if not prod:
                continue
            qty = Decimal(quantities[i] or '1')
            price = Decimal(unit_prices[i] or '0')
            disc = Decimal(discounts[i] or '0') if i < len(discounts) else Decimal('0')

            items_data.append({
                'product': prod,
                'quantity': qty,
                'unit_price': price,
                'discount_percentage': disc,
            })

        from accounts.services import get_representative_warehouse
        rep_wh = get_representative_warehouse(request.user)

        if warehouse_id:
            warehouse = get_object_or_404(Warehouse, id=warehouse_id)
            if not can_user_access_object(request.user, warehouse, 'operate'):
                return render_forbidden_response(request, "لا يمكنك إجراء مبيعات من مخزن خارج نطاق صلاحيتك.")
        elif rep_wh:
            warehouse = rep_wh
        else:
            warehouse = order.source_warehouse

        def render_form_error(err_text):
            messages.error(request, err_text)
            sub_items = []
            for idx, p_id in enumerate(product_ids):
                if not p_id:
                    continue
                sub_items.append({
                    'product_id': p_id,
                    'quantity': quantities[idx] if idx < len(quantities) else '1',
                    'unit_price': unit_prices[idx] if idx < len(unit_prices) else '0',
                    'discount_percentage': discounts[idx] if idx < len(discounts) else '0',
                })
            customers = get_bounded_select_options(
                ScopeResolutionService.get_scoped_choices(request.user, 'customers', 'sales'),
                selected_id=customer_id,
                limit=100,
            )
            if order.customer and order.customer.status != 'inactive' and not any(c.id == order.customer_id for c in customers):
                customers = [order.customer] + list(customers)
            warehouses = get_bounded_select_options(
                ScopeResolutionService.get_scoped_choices(request.user, 'warehouses', 'sales'),
                selected_id=warehouse_id,
                limit=100,
            )
            from accounts.services import is_representative, get_representative_warehouse
            is_rep_ctx = is_representative(request.user)
            user_rep_wh_ctx = get_representative_warehouse(request.user) if is_rep_ctx else None
            products = Product.objects.filter(is_active=True, sellable=True)
            ctx = {
                'order': order,
                'customers': customers,
                'warehouses': warehouses,
                'user_rep_wh': user_rep_wh_ctx,
                'is_rep': is_rep_ctx,
                'products': products,
                'form_data': {
                    'customer': customer_id,
                    'warehouse': warehouse_id,
                    'order_date': order_date,
                    'delivery_date': delivery_date,
                    'due_date': due_date,
                    'custom_discount_percentage': custom_discount_percentage,
                    'shipping_fees': shipping_fees,
                    'notes': notes,
                },
                'submitted_items': sub_items,
            }
            return render(request, 'sales/sales_order_edit.html', ctx)

        if not customer_id:
            return render_form_error("يرجى تحديد العميل.")

        customer = get_object_or_404(Contact, id=customer_id)
        if not can_user_access_object(request.user, customer, 'view'):
            return render_forbidden_response(request, "غير مصرح لك بإنشاء أمر بيع لعميل خارج نطاق منطقتك الجغرافية.")
        if not customer.is_customer or customer.status == 'inactive' or (customer.pk != order.customer_id and customer.status != 'customer'):
            return render_form_error("لا يمكن ربط أمر البيع إلا بعميل فعلي (Customer) نشط.")

        try:
            order = SalesOrderService.update_order(
                order=order,
                customer=customer,
                source_warehouse=warehouse,
                order_date=order_date,
                items_data=items_data,
                user=request.user,
                delivery_date=delivery_date,
                due_date=due_date,
                custom_discount_percentage=Decimal(custom_discount_percentage),
                shipping_fees=Decimal(shipping_fees),
                notes=notes
            )
            if request.FILES.getlist('attachments'):
                from master_data.media_service import store_attachments_from_request
                store_attachments_from_request(order, request)
            messages.success(request, f"تم تعديل أمر البيع بنجاح ({order.order_number}) بإجمالي {order.grand_total:,.2f} ج.م.")
            return redirect('sales_order_detail', pk=order.pk)
        except ValidationError as e:
            return render_form_error(str(e.message if hasattr(e, 'message') else e))

    from accounts.services import is_representative, get_representative_warehouse
    is_rep = is_representative(request.user)
    user_rep_wh = get_representative_warehouse(request.user) if is_rep else None

    customers = get_bounded_select_options(
        ScopeResolutionService.get_scoped_choices(request.user, 'customers', 'sales'),
        selected_id=order.customer_id,
        limit=100,
    )
    if order.customer and order.customer.status != 'inactive' and not any(c.id == order.customer_id for c in customers):
        customers = [order.customer] + list(customers)
    warehouses = get_bounded_select_options(
        ScopeResolutionService.get_scoped_choices(request.user, 'warehouses', 'sales'),
        selected_id=order.source_warehouse_id,
        limit=100,
    )
    products = Product.objects.filter(is_active=True)

    context = {
        'order': order,
        'customers': customers,
        'warehouses': warehouses,
        'user_rep_wh': user_rep_wh,
        'is_rep': is_rep,
        'products': products,
    }
    return render(request, 'sales/sales_order_edit.html', context)


@require_permission('sales:orders/view')
def sales_order_detail(request, pk):
    order = get_object_or_404(
        SalesOrder.objects.select_related(
            'customer', 'customer__area', 'source_warehouse', 'created_by', 'approved_by', 'memo'
        ).prefetch_related('items__product'),
        pk=pk
    )
    if not can_user_access_object(request.user, order, 'view'):
        return render_forbidden_response(request, "لا يمكنك عرض هذا الطلب خارج نطاق منطقتك الجغرافية أو صلاحيتك.")

    can_approve = has_perm_or_admin(request.user, 'sales:orders/approve') and can_user_access_object(request.user, order, 'approve')
    can_edit = (
        has_perm_or_admin(request.user, 'sales:orders/edit') and
        can_user_access_object(request.user, order, 'edit') and
        order.status != 'cancelled' and
        not order.collections.exists()
    )
    can_delete = (
        has_perm_or_admin(request.user, 'sales:orders/delete') and
        can_user_access_object(request.user, order, 'delete') and
        not order.collections.exists()
    )
    is_owner = (order.created_by_id == request.user.id)
    can_resubmit = is_owner and order.status == 'rejected'

    approval_history = order.approval_history.select_related('actor').order_by('-created_at')

    can_manage_payment = has_perm_or_admin(request.user, 'sales:orders/manage_payment_status')

    return render(request, 'sales/sales_order_detail.html', {
        'order': order,
        'can_approve': can_approve,
        'can_edit': can_edit,
        'can_delete': can_delete,
        'can_resubmit': can_resubmit,
        'can_manage_payment': can_manage_payment,
        'payment_status_choices': SalesOrder.PAYMENT_STATUS_CHOICES,
        'approval_history': approval_history,
    })


@login_required
def sales_order_action(request, pk, action):
    action_perm_map = {
        'approve': 'sales:orders/approve',
        'reject': 'sales:orders/approve',
        'disapprove': 'sales:orders/approve',
        'resubmit': 'sales:orders/create',
        'prepare': 'sales:orders/unstock',
        'deliver': 'sales:orders/unstock',
        'invoice': 'sales:orders/invoice',
        'cancel': 'sales:orders/cancel',
    }
    needed_perm = action_perm_map.get(action, 'sales:orders/edit')
    if not has_perm_or_admin(request.user, needed_perm):
        return render_forbidden_response(request, f"ليس لديك صلاحية لتنفيذ هذا الإجراء ({needed_perm})", perm_codename=needed_perm)

    order = get_object_or_404(SalesOrder, pk=pk)

    # Scoping and self-approval checks
    if action in ['approve', 'reject', 'disapprove']:
        if not can_user_access_object(request.user, order, action):
            if order.created_by_id == request.user.id and not (request.user.is_superuser or getattr(request.user, 'is_super_admin', False)):
                messages.error(request, "لا يمكن للمندوب اعتماد أو رفض أمر البيع الخاص به كمنشئ أو مسؤول.")
                return redirect('sales_order_detail', pk=order.pk)
            return render_forbidden_response(request, "لا يمكنك اعتماد أو رفض هذا الطلب خارج نطاق منطقتك الجغرافية أو صلاحيتك.")
    else:
        if not can_user_access_object(request.user, order, 'edit'):
            return render_forbidden_response(request, "لا يمكنك تعديل هذا الطلب خارج نطاق منطقتك الجغرافية أو صلاحيتك.")

    is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'application/json' in request.headers.get('accept', '')

    try:
        if action == 'approve':
            notes = request.POST.get('approval_notes', '') or request.POST.get('notes', '')
            SalesOrderService.approve_order(order, request.user, notes=notes)
            msg = f"تم اعتماد أمر البيع {order.order_number} بنجاح."
            if is_ajax:
                return JsonResponse({'success': True, 'message': msg, 'status': order.status})
            messages.success(request, msg)

        elif action in ['reject', 'disapprove']:
            reason = request.POST.get('rejection_reason', '') or request.POST.get('reason', '') or request.POST.get('approval_notes', '')
            if not (reason or '').strip():
                msg = "يرجى توضيح سبب رفض أمر البيع."
                if is_ajax:
                    return JsonResponse({'success': False, 'message': msg}, status=400)
                messages.error(request, msg)
                return redirect('sales_order_detail', pk=order.pk)

            SalesOrderService.reject_order(order, request.user, reason=reason)
            msg = f"تم رفض أمر البيع {order.order_number}."
            if is_ajax:
                return JsonResponse({'success': True, 'message': msg, 'status': order.status})
            messages.error(request, msg)

        elif action == 'resubmit':
            SalesOrderService.resubmit_order(order, request.user)
            msg = f"تمت إعادة تقديم أمر البيع {order.order_number} للاعتماد بنجاح."
            if is_ajax:
                return JsonResponse({'success': True, 'message': msg, 'status': order.status})
            messages.success(request, msg)

        elif action == 'prepare':
            SalesOrderService.prepare_order(order, request.user)
            messages.success(request, f"تم حجز البضاعة بالمخزن وتغيير حالة الطلب إلى (جاري التجهيز).")
        elif action == 'deliver':
            SalesOrderService.deliver_order(order, request.user)
            messages.success(request, f"تم تسليم أمر البيع {order.order_number} وتوليد إذن صرف المخزن بنجاح.")
        elif action == 'invoice':
            SalesOrderService.invoice_order(order, request.user)
            messages.success(request, f"تم ترحيل فاتورة المبيعات للحسابات وإثبات مديونية العميل {order.customer.name}.")
        elif action == 'cancel':
            SalesOrderService.cancel_order(order, request.user)
            messages.warning(request, f"تم إلغاء أمر البيع {order.order_number}.")
        else:
            messages.error(request, "إجراء غير معروف.")
    except ValidationError as e:
        err_msg = str(e.message if hasattr(e, 'message') else e)
        if is_ajax:
            return JsonResponse({'success': False, 'message': err_msg}, status=400)
        messages.error(request, err_msg)

    from django.utils.http import url_has_allowed_host_and_scheme
    referer = request.META.get('HTTP_REFERER', '')
    if referer and url_has_allowed_host_and_scheme(referer, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return redirect(referer)
    return redirect('sales_order_detail', pk=order.pk)


@require_permission('sales:orders/manage_payment_status')
def sales_order_update_payment_status(request, pk):
    order = get_object_or_404(SalesOrder, pk=pk)
    if not can_user_access_object(request.user, order, 'edit'):
        return render_forbidden_response(request, "لا يمكنك الوصول لهذا الطلب خارج نطاق صلاحيتك.")

    if request.method == 'POST':
        new_status = (request.POST.get('payment_status') or '').strip()
        notes = (request.POST.get('notes') or '').strip()
        try:
            SalesOrderService.update_payment_status(order, new_status, request.user, notes=notes)
            messages.success(request, f"تم تحديث حالة السداد لأمر البيع {order.order_number} بنجاح إلى '{order.payment_status_display_ar}'.")
        except ValidationError as e:
            messages.error(request, str(e.message if hasattr(e, 'message') else e))

    return redirect('sales_order_detail', pk=order.pk)


@require_permission('sales:orders/delete')
def sales_order_delete(request, pk):
    order = get_object_or_404(SalesOrder, pk=pk)
    if not can_user_access_object(request.user, order, 'delete'):
        return render_forbidden_response(request, "لا يمكنك حذف هذا الطلب خارج نطاق اختصاصك أو منطقتك الجغرافية.")

    if request.method != 'POST':
        messages.error(request, "طريقة طلب غير صالحة للحذف. يلزم استخدام POST.")
        return redirect('sales_order_detail', pk=pk)

    try:
        SalesOrderService.delete_order(order, request.user)
        messages.success(request, f"تم حذف أمر البيع {order.order_number} بنجاح وعكس الحركات المخزنية والمالية.")
        return redirect('sales_orders_list')
    except ValidationError as e:
        messages.error(request, str(e.message if hasattr(e, 'message') else e))
        return redirect('sales_order_detail', pk=pk)


@require_permission('sales:collections/list')
def collections_list(request):
    from master_data.filter_utils import (
        parse_multi_int,
        parse_multi_str,
        parse_single_int,
        resolve_scoped_area_brick_filters,
        build_contact_area_q,
        build_contact_brick_q,
    )
    from master_data.date_filter_utils import resolve_date_range

    search = request.GET.get('search', '').strip()
    customer_id_int = parse_single_int(request.GET, 'customer')
    customer_id = str(customer_id_int) if customer_id_int else ''
    selected_vault_ids = parse_multi_int(request.GET, 'vault')
    vault_id = str(selected_vault_ids[0]) if len(selected_vault_ids) == 1 else ''
    pm_choices = Collection._meta.get_field('payment_method').choices
    method_labels = dict(pm_choices)
    selected_payment_methods = [m for m in parse_multi_str(request.GET, 'payment_method') if m in method_labels]
    payment_method = selected_payment_methods[0] if len(selected_payment_methods) == 1 else ''
    parsed_from, parsed_to, active_preset, date_from, date_to = resolve_date_range(request, default_preset='all_time')

    qs = Collection.objects.select_related('customer', 'customer__area', 'customer__brick', 'vault', 'created_by').order_by('-serial_num')
    qs = get_scoped_queryset(qs, request.user, 'collection')

    active_filters = []

    if customer_id_int:
        qs = qs.filter(customer_id=customer_id_int)
        c_obj = ScopeResolutionService.get_scoped_choices(request.user, 'customers', 'sales').filter(id=customer_id_int).first()
        active_filters.append({'label': 'العميل', 'value': c_obj.name if c_obj else customer_id, 'param': 'customer'})

    if selected_vault_ids:
        auth_vaults = list(ScopeResolutionService.get_scoped_choices(request.user, 'vaults', 'sales').filter(id__in=selected_vault_ids))
        auth_v_ids = [v.id for v in auth_vaults]
        if auth_v_ids:
            qs = qs.filter(vault_id__in=auth_v_ids)
            for v_obj in auth_vaults:
                active_filters.append({'label': 'الخزنة', 'value': v_obj.name, 'param': 'vault', 'remove_value': str(v_obj.id)})
        else:
            qs = qs.none()

    if selected_payment_methods:
        qs = qs.filter(payment_method__in=selected_payment_methods)
        for pm in selected_payment_methods:
            active_filters.append({'label': 'طريقة التحصيل', 'value': method_labels.get(pm, pm), 'param': 'payment_method', 'remove_value': pm})

    main_area_ids, brick_ids, selected_main_areas_chips, selected_bricks_chips = resolve_scoped_area_brick_filters(
        request, 'sales',
        area_params=('main_area', 'area_id', 'governorate'),
        brick_params=('brick', 'brick_id', 'area'),
    )
    if main_area_ids:
        qs = qs.filter(build_contact_area_q(main_area_ids, prefix='customer', include_addresses=False))
        for a_chip in selected_main_areas_chips:
            active_filters.append({'label': 'المنطقة الرئيسية', 'value': a_chip['name'], 'param': 'main_area', 'remove_value': str(a_chip['id'])})
    if brick_ids:
        qs = qs.filter(build_contact_brick_q(brick_ids, prefix='customer', include_addresses=False))
        for b_chip in selected_bricks_chips:
            active_filters.append({'label': 'الخط الجغرافي / Brick', 'value': b_chip['name'], 'param': 'brick', 'remove_value': str(b_chip['id'])})

    if parsed_from:
        qs = qs.filter(collection_date__gte=parsed_from)
        active_filters.append({'label': 'من تاريخ', 'value': date_from, 'param': 'date_from'})

    if parsed_to:
        qs = qs.filter(collection_date__lte=parsed_to)
        active_filters.append({'label': 'إلى تاريخ', 'value': date_to, 'param': 'date_to'})

    if search:
        qs = filter_by_arabic_search(qs, search, ['serial_num', 'customer__name', 'notes'])
        active_filters.append({'label': 'بحث', 'value': search, 'param': 'search'})

    customers = get_bounded_select_options(
        ScopeResolutionService.get_scoped_choices(request.user, 'customers', 'sales'),
        selected_id=customer_id,
        limit=100,
    )
    vaults = ScopeResolutionService.get_scoped_choices(request.user, 'vaults', 'sales')

    paginator, page_obj = paginate_queryset(request, qs, default_per_page=25, max_per_page=100)

    # Dedicated real scoped statistics cards matching active filters
    now = timezone.now()
    col_agg = qs.aggregate(
        total_count=Count('id'),
        total_amount=Sum('amount'),
        month_amount=Sum('amount', filter=Q(collection_date__year=now.year, collection_date__month=now.month)),
        vaults_count=Count('vault', distinct=True),
    )
    stats = {
        'total_count': col_agg['total_count'] or 0,
        'total_amount': col_agg['total_amount'] or Decimal('0.00'),
        'month_amount': col_agg['month_amount'] or Decimal('0.00'),
        'vaults_count': col_agg['vaults_count'] or 0,
    }

    vault_options = [{'value': str(v.id), 'label': v.name} for v in vaults]
    selected_vault_str = [str(x) for x in selected_vault_ids]
    selected_vault_items = [o for o in vault_options if o['value'] in selected_vault_str]
    pm_options = [{'value': k, 'label': v} for k, v in pm_choices]
    selected_pm_items = [o for o in pm_options if o['value'] in selected_payment_methods]

    context = {
        'collections': page_obj.object_list,
        'page_obj': page_obj,
        'paginator': paginator,
        'customers': customers,
        'vaults': vaults,
        'vault_options': vault_options,
        'selected_vault_items': selected_vault_items,
        'selected_vault_ids': selected_vault_str,
        'pm_options': pm_options,
        'selected_pm_items': selected_pm_items,
        'selected_payment_methods': selected_payment_methods,
        'selected_main_areas_chips': selected_main_areas_chips,
        'selected_bricks_chips': selected_bricks_chips,
        'active_preset': active_preset,
        'date_from': date_from,
        'date_to': date_to,
        'search_query': search,
        'selected_customer_id': customer_id,
        'selected_vault_id': vault_id,
        'selected_payment_method': payment_method,
        'selected_date_from': date_from,
        'selected_date_to': date_to,
        'active_filters': active_filters,
        'total_count': paginator.count,
        'stats': stats,
    }
    return render(request, 'sales/collections_list.html', context)


@require_permission('sales:collections/create')
def collection_create(request):
    if request.method == 'POST':
        customer_id = request.POST.get('customer')
        vault_id = request.POST.get('vault')
        amount = request.POST.get('amount')
        sales_order_id = request.POST.get('sales_order')
        collection_date = request.POST.get('collection_date') or None
        due_date = request.POST.get('due_date') or None
        payment_method = request.POST.get('payment_method', 'cash')
        notes = request.POST.get('notes', '').strip()

        if not customer_id or not vault_id or not amount:
            messages.error(request, "يرجى ملء جميع الحقول المطلوبة (العميل، الخزنة، والمبلغ).")
            return redirect('collection_create')

        customer = get_object_or_404(Contact, id=customer_id)
        vault = get_object_or_404(Vault, id=vault_id)

        if not can_user_access_object(request.user, customer, 'view'):
            return render_forbidden_response(request, "لا يمكنك تسجيل تحصيل لعميل خارج نطاقك الجغرافي أو صلاحياتك.")
        if not can_user_access_object(request.user, vault, 'deposit'):
            return render_forbidden_response(request, "لا يمكنك الإيداع في خزنة غير مخصصة لك.")

        sales_order = None
        if sales_order_id:
            sales_order = get_object_or_404(SalesOrder, id=sales_order_id)
            if not can_user_access_object(request.user, sales_order, 'view'):
                return render_forbidden_response(request, "لا يمكنك تسجيل تحصيل لأمر بيع خارج نطاق صلاحياتك.")

        from .services import validate_sales_customer_eligibility
        try:
            validate_sales_customer_eligibility(customer, allow_historical_lead=True, sales_order=sales_order)
        except ValidationError as e:
            messages.error(request, str(e.message if hasattr(e, 'message') else e))
            return redirect('collection_create')

        try:
            col = CollectionService.record_collection(
                customer=customer,
                vault=vault,
                amount=Decimal(amount),
                user=request.user,
                payment_method=payment_method,
                notes=notes,
                sales_order=sales_order,
                collection_date=collection_date,
                due_date=due_date
            )
            if request.FILES.getlist('attachments'):
                from master_data.media_service import store_attachments_from_request
                store_attachments_from_request(col, request)
            order_info = f" لأمر بيع {sales_order.order_number}" if sales_order else ""
            messages.success(request, f"تم تسجيل سند التحصيل #{col.serial_num} بنجاح بمبلغ {col.amount:,.2f} ج.م من العميل {customer.name}{order_info}.")
            return redirect('collections_list')
        except ValidationError as e:
            messages.error(request, str(e.message if hasattr(e, 'message') else e))
            return redirect('collection_create')

    initial_customer = request.GET.get('customer_id') or request.GET.get('customer')
    initial_order = request.GET.get('order_id')

    if initial_order and not initial_customer:
        ord_obj = SalesOrder.objects.filter(id=initial_order).first()
        if ord_obj and can_user_access_object(request.user, ord_obj, 'view'):
            initial_customer = ord_obj.customer_id

    customers = get_bounded_select_options(
        ScopeResolutionService.get_scoped_choices(request.user, 'customers', 'sales'),
        selected_id=initial_customer,
        limit=100,
    )
    vaults = ScopeResolutionService.get_scoped_choices(request.user, 'vaults', 'sales')

    # Never dump thousands of SalesOrders into the HTML DOM.
    # Only preload bounded orders for the initially selected customer (or selected_order_id);
    # customer switching fetches scoped orders dynamically via sales_orders_search_api.
    selected_customer_id = int(initial_customer) if initial_customer and str(initial_customer).isdigit() else None
    selected_order_id = int(initial_order) if initial_order and str(initial_order).isdigit() else None

    selected_customer_account = None
    if selected_customer_id:
        cust_obj = ScopeResolutionService.get_scoped_choices(request.user, 'customers', 'sales').filter(id=selected_customer_id).first()
        if not cust_obj:
            # Preserve historical Lead settlement when navigating from an existing order or balance
            from .services import has_historical_sales_activity
            cand_cust = Contact.objects.filter(id=selected_customer_id, is_customer=True, status='lead').first()
            if cand_cust and can_user_access_object(request.user, cand_cust, 'view') and has_historical_sales_activity(cand_cust):
                cust_obj = cand_cust
                if not any(c.id == cand_cust.id for c in customers):
                    customers = [cand_cust] + list(customers)
        if cust_obj:
            selected_customer_account = CustomerAccount.get_or_create_for_customer(cust_obj)
            orders_qs = SalesOrder.with_payment_totals(
                SalesOrder.objects.filter(customer_id=selected_customer_id)
                .exclude(status__in=['cancelled', 'rejected'])
                .select_related('customer')
                .order_by('-order_date', '-id')
            )
            orders_qs = get_scoped_queryset(orders_qs, request.user, 'salesorder')
            preloaded_orders = []
            for o in orders_qs[:50]:
                if o.outstanding_balance > Decimal('0.00') or (selected_order_id and o.id == selected_order_id):
                    preloaded_orders.append(o)
            if selected_order_id and not any(o.id == selected_order_id for o in preloaded_orders):
                sel_o = get_scoped_queryset(
                    SalesOrder.with_payment_totals(SalesOrder.objects.filter(id=selected_order_id).select_related('customer')),
                    request.user,
                    'salesorder'
                ).first()
                if sel_o:
                    preloaded_orders.insert(0, sel_o)
        else:
            preloaded_orders = []
    else:
        preloaded_orders = []

    context = {
        'customers': customers,
        'vaults': vaults,
        'orders': preloaded_orders,
        'selected_customer_id': selected_customer_id,
        'selected_order_id': selected_order_id,
        'selected_customer_balance': selected_customer_account.current_balance if selected_customer_account else None,
        'selected_customer_overdue': selected_customer_account.overdue_balance if selected_customer_account else None,
        'selected_customer_name': selected_customer_account.customer.name if selected_customer_account else '',
    }
    return render(request, 'sales/collection_create.html', context)


@require_permission(['contacts:contacts/list', 'sales:orders/list', 'sales:customers/accounting'])
def sales_customers_list(request):
    """
    Canonical redirect: /sales/customers/ redirects to the unified Contacts directory
    pre-filtered to customers (relation=customer), preserving any active filter query params.
    """
    params = request.GET.copy()
    params['relation'] = 'customer'
    if 'main_area' in params and 'area_id' not in params:
        params.setlist('area_id', params.getlist('main_area'))
        del params['main_area']
    if 'brick' in params and 'brick_id' not in params:
        params.setlist('brick_id', params.getlist('brick'))
        del params['brick']
    return redirect(f"{reverse('contacts_list')}?{params.urlencode()}")


@require_permission(['contacts:contacts/create', 'sales:orders/create'])
def sales_customer_create(request):
    """
    Create a new customer in sales context.
    """
    if request.method == 'GET' and 'relation' not in request.GET:
        get_copy = request.GET.copy()
        get_copy['relation'] = 'customer'
        request.GET = get_copy
    return contact_create(request)


@require_permission(['contacts:contacts/view', 'sales:orders/list', 'sales:customers/accounting'])
def sales_customer_detail(request, pk):
    """
    View customer profile with full detail, tabs, balances, and history.
    """
    return contact_detail(request, pk=pk)


@require_permission(['contacts:contacts/edit', 'sales:orders/create'])
def sales_customer_edit(request, pk):
    """
    Edit existing customer record with authorization checks and audit logging.
    """
    return contact_edit(request, pk=pk)


@require_permission('sales:customers/accounting')
def accounting_customers_list(request):
    """
    Customer Statements & Balances (حسابات العملاء).
    """
    from master_data.filter_utils import (
        parse_single_int,
        resolve_scoped_area_brick_filters,
        build_contact_area_q,
        build_contact_brick_q,
    )

    search = request.GET.get('search', '').strip()
    customer_id_int = parse_single_int(request.GET, 'customer_id', 'customer')
    customer_id = str(customer_id_int) if customer_id_int else ''

    main_area_ids, brick_ids, selected_main_areas_chips, selected_bricks_chips = resolve_scoped_area_brick_filters(
        request, 'sales',
        area_params=('main_area', 'area', 'area_id', 'governorate'),
        brick_params=('brick', 'brick_id'),
    )
    area_id = str(main_area_ids[0]) if len(main_area_ids) == 1 else ''

    qs = CustomerAccount.objects.select_related('customer', 'customer__area', 'customer__brick').order_by('-current_balance')
    qs = get_scoped_queryset(qs, request.user, 'customeraccount')

    active_filters = []

    if customer_id_int:
        qs = qs.filter(customer_id=customer_id_int)
        c_acc = qs.first()
        c_label = c_acc.customer.name if c_acc else customer_id
        param_name = 'customer_id' if request.GET.get('customer_id') else 'customer'
        active_filters.append({'label': 'العميل', 'value': c_label, 'param': param_name})

    if main_area_ids:
        qs = qs.filter(build_contact_area_q(main_area_ids, prefix='customer', include_addresses=False))
        for a_chip in selected_main_areas_chips:
            active_filters.append({'label': 'المنطقة الرئيسية', 'value': a_chip['name'], 'param': 'main_area', 'remove_value': str(a_chip['id'])})
    if brick_ids:
        qs = qs.filter(build_contact_brick_q(brick_ids, prefix='customer', include_addresses=False))
        for b_chip in selected_bricks_chips:
            active_filters.append({'label': 'الخط الجغرافي / Brick', 'value': b_chip['name'], 'param': 'brick', 'remove_value': str(b_chip['id'])})

    if search:
        qs = filter_by_arabic_search(qs, search, ['customer__name', 'customer__code'])
        active_filters.append({'label': 'بحث', 'value': search, 'param': 'search'})

    acc_agg = qs.aggregate(
        total_customers=Count('id'),
        total_receivable=Sum('current_balance', filter=Q(current_balance__gt=0)),
        total_overdue=Sum('overdue_balance', filter=Q(overdue_balance__gt=0)),
        total_credit_limit=Sum('credit_limit'),
    )
    account_stats = {
        'total_customers': acc_agg['total_customers'] or 0,
        'total_receivable': acc_agg['total_receivable'] or Decimal('0.00'),
        'total_overdue': acc_agg['total_overdue'] or Decimal('0.00'),
        'total_credit_limit': acc_agg['total_credit_limit'] or Decimal('0.00'),
    }

    paginator, page_obj = paginate_queryset(request, qs, default_per_page=25, max_per_page=100)
    customers = get_bounded_select_options(
        ScopeResolutionService.get_scoped_choices(request.user, 'customers', 'sales'),
        selected_id=customer_id,
        limit=100,
    )

    context = {
        'accounts': page_obj.object_list,
        'page_obj': page_obj,
        'paginator': paginator,
        'customers': customers,
        'selected_customer_id': customer_id,
        'selected_area_id': area_id,
        'selected_main_areas_chips': selected_main_areas_chips,
        'selected_bricks_chips': selected_bricks_chips,
        'search_query': search,
        'active_filters': active_filters,
        'total_count': paginator.count,
        'stats': account_stats,
    }
    return render(request, 'sales/accounting_customers_list.html', context)


@require_permission('sales:customers/accounting_export')
def accounting_customers_export(request):
    """Export Customer Statements & Balances to Excel (respecting all active filters & DataScope)."""
    from master_data.filter_utils import (
        parse_single_int,
        resolve_scoped_area_brick_filters,
        build_contact_area_q,
        build_contact_brick_q,
    )
    search = request.GET.get('search', '').strip()
    customer_id_int = parse_single_int(request.GET, 'customer_id', 'customer')
    main_area_ids, brick_ids, _, _ = resolve_scoped_area_brick_filters(
        request, 'sales',
        area_params=('main_area', 'area', 'area_id', 'governorate'),
        brick_params=('brick', 'brick_id'),
    )
    qs = CustomerAccount.objects.select_related('customer', 'customer__area', 'customer__brick').order_by('-current_balance')
    qs = get_scoped_queryset(qs, request.user, 'customeraccount')

    if customer_id_int:
        qs = qs.filter(customer_id=customer_id_int)
    if main_area_ids:
        qs = qs.filter(build_contact_area_q(main_area_ids, prefix='customer', include_addresses=False))
    if brick_ids:
        qs = qs.filter(build_contact_brick_q(brick_ids, prefix='customer', include_addresses=False))
    if search:
        qs = filter_by_arabic_search(qs, search, ['customer__name', 'customer__code'])

    columns = [
        {'header': 'كود العميل', 'key': lambda a: a.customer.code or '', 'width': 16, 'align': 'center'},
        {'header': 'اسم العميل', 'key': lambda a: a.customer.name, 'width': 35, 'align': 'right'},
        {'header': 'المنطقة', 'key': lambda a: a.customer.area.name if a.customer.area else '', 'width': 20, 'align': 'right'},
        {'header': 'الرصيد المدين المستحق', 'key': lambda a: float(a.current_balance or 0), 'format': '#,##0.00', 'width': 20, 'align': 'right'},
        {'header': 'المديونية المتأخرة', 'key': lambda a: float(a.overdue_balance or 0), 'format': '#,##0.00', 'width': 20, 'align': 'right'},
        {'header': 'واجب السداد الشهر الحالي', 'key': lambda a: float(a.due_this_month_balance or 0), 'format': '#,##0.00', 'width': 22, 'align': 'right'},
        {'header': 'حد الائتمان', 'key': lambda a: float(a.credit_limit or 0), 'format': '#,##0.00', 'width': 18, 'align': 'right'},
        {'header': 'فترة الائتمان (أيام)', 'key': 'credit_period_days', 'width': 18, 'align': 'center'},
        {'header': 'تاريخ آخر معاملة', 'key': lambda a: a.last_transaction_date.strftime('%Y-%m-%d') if a.last_transaction_date else '', 'width': 18, 'align': 'center'},
    ]
    return export_to_excel_response(
        qs,
        columns,
        filename="customer_accounts_export",
        sheet_title="حسابات العملاء",
        report_title="كشف أرصدة وحسابات العملاء",
        user=request.user,
    )


@require_permission('sales:customers/zero_balance')
def accounting_customer_zero_balance(request, pk):
    """Non-cash account zeroing (تصفير الحساب) for CustomerAccount — zero vault impact, preserves order payment_status."""
    if request.method != 'POST':
        return redirect('accounting_customers_list')

    account = get_object_or_404(CustomerAccount.objects.select_related('customer'), pk=pk)
    if not can_user_access_object(request.user, account, 'manage'):
        return render_forbidden_response(request, "غير مصرح لك بتصفير رصيد حساب عميل خارج نطاق اختصاصك.")

    reason_note = (request.POST.get('reason') or '').strip()
    is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'application/json' in request.headers.get('accept', '')

    from .services import CustomerAccountService
    try:
        tx, prev_bal = CustomerAccountService.zero_balance(
            customer=account.customer,
            user=request.user,
            reason_note=reason_note,
            request=request,
        )
        msg = f"تم تصفير رصيد حساب العميل {account.customer.name} (من {prev_bal:,.2f} ج.م إلى 0.00 ج.م) بدون التأثير على أي خزنة."
        if is_ajax:
            return JsonResponse({'success': True, 'message': msg, 'new_balance': '0.00', 'transaction_serial': tx.serial})
        messages.success(request, msg)
    except ValidationError as e:
        err_msg = str(e.message if hasattr(e, 'message') else e)
        if is_ajax:
            return JsonResponse({'success': False, 'message': err_msg}, status=400)
        messages.error(request, err_msg)

    return redirect('accounting_customers_list')


@require_permission('sales:customers/zero_balance')
def accounting_customer_settle(request, pk):
    """Non-cash customer account settlement / adjustment — zero vault impact, preserves order payment_status."""
    if request.method != 'POST':
        return redirect('accounting_customers_list')

    account = get_object_or_404(CustomerAccount.objects.select_related('customer'), pk=pk)
    if not can_user_access_object(request.user, account, 'manage'):
        return render_forbidden_response(request, "غير مصرح لك بتسوية حساب عميل خارج نطاق اختصاصك.")

    amount_raw = (request.POST.get('amount') or '').strip()
    direction = (request.POST.get('direction') or 'credit').strip()
    reason_note = (request.POST.get('reason') or '').strip()
    reference = (request.POST.get('reference') or '').strip()
    is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'application/json' in request.headers.get('accept', '')

    from .services import CustomerAccountService
    try:
        amount = Decimal(amount_raw)
    except Exception:
        err_msg = "يرجى إدخال مبلغ تسوية صحيح."
        if is_ajax:
            return JsonResponse({'success': False, 'message': err_msg}, status=400)
        messages.error(request, err_msg)
        return redirect('accounting_customers_list')

    try:
        tx, prev_bal = CustomerAccountService.record_settlement(
            customer=account.customer,
            amount=amount,
            direction=direction,
            user=request.user,
            reason_note=reason_note,
            reference=reference,
            request=request,
        )
        msg = (
            f"تم تسجيل تسوية غير نقدية للعميل {account.customer.name} بمبلغ {amount:,.2f} ج.م "
            f"(الرصيد: {prev_bal:,.2f} ← {tx.running_balance:,.2f} ج.م، بدون تأثير على الخزن)."
        )
        if is_ajax:
            return JsonResponse({
                'success': True,
                'message': msg,
                'new_balance': str(tx.running_balance),
                'transaction_serial': tx.serial,
            })
        messages.success(request, msg)
    except ValidationError as e:
        err_msg = e.messages[0] if getattr(e, 'messages', None) else str(e)
        if is_ajax:
            return JsonResponse({'success': False, 'message': err_msg}, status=400)
        messages.error(request, err_msg)

    return redirect('accounting_customers_list')


@require_permission('sales:customers/zero_balance')
def customer_settlement_reverse(request, pk):
    """Reverses a non-cash customer settlement/adjustment transaction (zero vault impact)."""
    if request.method != 'POST':
        return redirect('customer_transactions_list')

    tx = get_object_or_404(CustomerTransaction.objects.select_related('account', 'account__customer'), pk=pk)
    if not can_user_access_object(request.user, tx.account, 'manage'):
        return render_forbidden_response(request, "غير مصرح لك بعكس تسوية لعميل خارج نطاق اختصاصك.")

    reason_note = (request.POST.get('reason') or '').strip()
    from .services import CustomerAccountService
    try:
        rev_tx = CustomerAccountService.reverse_settlement(
            tx_id=tx.pk,
            user=request.user,
            reason_note=reason_note,
            request=request,
        )
        messages.success(request, f"تم عكس قيد التسوية #{tx.serial} بنجاح (قيد العكس #{rev_tx.serial}).")
    except ValidationError as e:
        err_msg = e.messages[0] if getattr(e, 'messages', None) else str(e)
        messages.error(request, err_msg)

    next_url = request.POST.get('next') or request.META.get('HTTP_REFERER')
    if next_url and next_url.startswith('/'):
        return redirect(next_url)
    return redirect('customer_transactions_list')


@require_permission('sales:customers/transactions')
def customer_transactions_list(request):
    """
    Customer Ledger Transactions (عمليات العملاء).
    """
    from master_data.filter_utils import (
        parse_single_int,
        resolve_scoped_area_brick_filters,
        build_contact_area_q,
        build_contact_brick_q,
    )
    from master_data.date_filter_utils import resolve_date_range

    customer_id_int = parse_single_int(request.GET, 'customer_id', 'customer')
    customer_id = str(customer_id_int) if customer_id_int else ''
    tx_type = request.GET.get('type')
    parsed_from, parsed_to, active_preset, date_from, date_to = resolve_date_range(request, default_preset='all_time')
    search = request.GET.get('search', '').strip()

    qs = get_scoped_queryset(
        CustomerTransaction.objects.select_related(
            'account', 'account__customer', 'account__customer__area', 'account__customer__brick', 'created_by'
        ).order_by('-serial'),
        request.user,
        'customertransaction',
    )
    scoped_contacts = get_scoped_queryset(Contact.objects.all(), request.user, 'contact')

    active_filters = []

    if customer_id_int:
        qs = qs.filter(account__customer_id=customer_id_int)
        c_obj = scoped_contacts.filter(id=customer_id_int).first()
        active_filters.append({'label': 'العميل', 'value': c_obj.name if c_obj else customer_id, 'param': 'customer_id'})

    if tx_type in ['debit', 'credit']:
        qs = qs.filter(transaction_type=tx_type)
        tx_label = 'مدين (فاتورة)' if tx_type == 'debit' else 'دائن (تحصيل / مرتجع)'
        active_filters.append({'label': 'النوع', 'value': tx_label, 'param': 'type'})

    main_area_ids, brick_ids, selected_main_areas_chips, selected_bricks_chips = resolve_scoped_area_brick_filters(
        request, 'sales',
        area_params=('main_area', 'area_id', 'governorate'),
        brick_params=('brick', 'brick_id', 'area'),
    )
    if main_area_ids:
        qs = qs.filter(build_contact_area_q(main_area_ids, prefix='account__customer', include_addresses=False))
        for a_chip in selected_main_areas_chips:
            active_filters.append({'label': 'المنطقة الرئيسية', 'value': a_chip['name'], 'param': 'main_area', 'remove_value': str(a_chip['id'])})
    if brick_ids:
        qs = qs.filter(build_contact_brick_q(brick_ids, prefix='account__customer', include_addresses=False))
        for b_chip in selected_bricks_chips:
            active_filters.append({'label': 'الخط الجغرافي / Brick', 'value': b_chip['name'], 'param': 'brick', 'remove_value': str(b_chip['id'])})

    if parsed_from:
        qs = qs.filter(transaction_date__gte=parsed_from)
        active_filters.append({'label': 'من تاريخ', 'value': date_from, 'param': 'date_from'})

    if parsed_to:
        qs = qs.filter(transaction_date__lte=parsed_to)
        active_filters.append({'label': 'إلى تاريخ', 'value': date_to, 'param': 'date_to'})

    if search:
        qs = filter_by_arabic_search(qs, search, ['serial', 'description', 'account__customer__name'])
        active_filters.append({'label': 'بحث', 'value': search, 'param': 'search'})

    customers = get_bounded_select_options(
        ScopeResolutionService.get_scoped_choices(request.user, 'customers', 'sales'),
        selected_id=customer_id,
        limit=100,
    )

    tx_agg = qs.aggregate(
        total_count=Count('id'),
        total_debit=Sum('debit'),
        total_credit=Sum('credit'),
    )
    tx_stats = {
        'total_count': tx_agg['total_count'] or 0,
        'total_debit': tx_agg['total_debit'] or Decimal('0.00'),
        'total_credit': tx_agg['total_credit'] or Decimal('0.00'),
    }
    tx_stats['net_balance'] = tx_stats['total_debit'] - tx_stats['total_credit']

    paginator, page_obj = paginate_queryset(request, qs, default_per_page=25, max_per_page=100)

    context = {
        'transactions': page_obj.object_list,
        'page_obj': page_obj,
        'paginator': paginator,
        'customers': customers,
        'selected_customer_id': customer_id,
        'selected_type': tx_type,
        'selected_main_areas_chips': selected_main_areas_chips,
        'selected_bricks_chips': selected_bricks_chips,
        'active_preset': active_preset,
        'date_from': date_from,
        'date_to': date_to,
        'selected_date_from': date_from,
        'selected_date_to': date_to,
        'search_query': search,
        'active_filters': active_filters,
        'total_count': paginator.count,
        'stats': tx_stats,
    }
    return render(request, 'sales/customer_transactions_list.html', context)


@require_permission('sales:customers/transactions_export')
def customer_transactions_export(request):
    """Export Customer Ledger Transactions to Excel (exact filter parity with list view)."""
    from master_data.filter_utils import (
        parse_single_int,
        resolve_scoped_area_brick_filters,
        build_contact_area_q,
        build_contact_brick_q,
    )
    from master_data.date_filter_utils import resolve_date_range

    customer_id_int = parse_single_int(request.GET, 'customer_id', 'customer')
    tx_type = request.GET.get('type')
    reason_filter = request.GET.get('reason', '').strip()
    parsed_from, parsed_to, _, _, _ = resolve_date_range(request, default_preset='all_time')
    search = request.GET.get('search', '').strip()
    main_area_ids, brick_ids, _, _ = resolve_scoped_area_brick_filters(
        request, 'sales',
        area_params=('main_area', 'area_id', 'governorate'),
        brick_params=('brick', 'brick_id', 'area'),
    )

    qs = get_scoped_queryset(
        CustomerTransaction.objects.select_related('account', 'account__customer', 'account__customer__area', 'account__customer__brick', 'created_by').order_by('-serial'),
        request.user,
        'customertransaction',
    )

    if customer_id_int:
        qs = qs.filter(account__customer_id=customer_id_int)
    if tx_type in ['debit', 'credit']:
        qs = qs.filter(transaction_type=tx_type)
    if reason_filter and reason_filter != 'all':
        qs = qs.filter(reason=reason_filter)
    if main_area_ids:
        qs = qs.filter(build_contact_area_q(main_area_ids, prefix='account__customer', include_addresses=False))
    if brick_ids:
        qs = qs.filter(build_contact_brick_q(brick_ids, prefix='account__customer', include_addresses=False))
    if parsed_from:
        qs = qs.filter(transaction_date__gte=parsed_from)
    if parsed_to:
        qs = qs.filter(transaction_date__lte=parsed_to)
    if search:
        qs = filter_by_arabic_search(qs, search, ['serial', 'description', 'account__customer__name'])

    columns = [
        {'header': 'رقم الإشعار', 'key': 'serial', 'width': 14, 'align': 'center'},
        {'header': 'تاريخ الحركة', 'key': lambda t: t.transaction_date.strftime('%Y-%m-%d') if t.transaction_date else '', 'width': 16, 'align': 'center'},
        {'header': 'العميل', 'key': lambda t: t.account.customer.name, 'width': 35, 'align': 'right'},
        {'header': 'البيان', 'key': 'description', 'width': 35, 'align': 'right'},
        {'header': 'مدين (ج.م)', 'key': lambda t: float(t.debit or 0), 'format': '#,##0.00', 'width': 18, 'align': 'right'},
        {'header': 'دائن (ج.م)', 'key': lambda t: float(t.credit or 0), 'format': '#,##0.00', 'width': 18, 'align': 'right'},
        {'header': 'الرصيد بعد الحركة', 'key': lambda t: float(t.running_balance or 0), 'format': '#,##0.00', 'width': 18, 'align': 'right'},
        {'header': 'المسؤول', 'key': lambda t: t.created_by.get_full_name() or t.created_by.username if t.created_by else '', 'width': 20, 'align': 'right'},
    ]
    return export_to_excel_response(
        qs,
        columns,
        filename="customer_transactions_export",
        sheet_title="عمليات العملاء",
        report_title="سجل حركات وعمليات العملاء",
        user=request.user,
    )


@require_permission('sales:orders/export')
def sales_orders_export(request):
    from master_data.filter_utils import (
        parse_multi_str,
        parse_single_int,
        resolve_scoped_area_brick_filters,
        build_contact_area_q,
        build_contact_brick_q,
    )
    from master_data.date_filter_utils import resolve_date_range

    status_choices_dict = dict(SalesOrder.STATUS_CHOICES)
    selected_statuses = [s for s in parse_multi_str(request.GET, 'status') if s in status_choices_dict]
    payment_status_filter = request.GET.get('payment_status', 'all')
    customer_id_int = parse_single_int(request.GET, 'customer')
    search = request.GET.get('search', '').strip()
    parsed_from, parsed_to, _, _, _ = resolve_date_range(request, default_preset='all_time')
    total_min = request.GET.get('total_min', '').strip()
    total_max = request.GET.get('total_max', '').strip()
    main_area_ids, brick_ids, _, _ = resolve_scoped_area_brick_filters(
        request, 'sales',
        area_params=('main_area', 'area_id', 'governorate'),
        brick_params=('brick', 'brick_id', 'area'),
    )

    qs = SalesOrder.objects.select_related('customer', 'customer__area', 'customer__brick', 'source_warehouse', 'created_by').all().order_by('-order_date', '-id')
    qs = get_scoped_queryset(qs, request.user, 'salesorder')

    if selected_statuses:
        qs = qs.filter(status__in=selected_statuses)
    if payment_status_filter != 'all' and payment_status_filter in dict(SalesOrder.PAYMENT_STATUS_CHOICES):
        qs = qs.filter(payment_status=payment_status_filter)
    if customer_id_int:
        qs = qs.filter(customer_id=customer_id_int)
    if main_area_ids:
        qs = qs.filter(build_contact_area_q(main_area_ids, prefix='customer', include_addresses=False))
    if brick_ids:
        qs = qs.filter(build_contact_brick_q(brick_ids, prefix='customer', include_addresses=False))
    if parsed_from:
        qs = qs.filter(order_date__gte=parsed_from)
    if parsed_to:
        qs = qs.filter(order_date__lte=parsed_to)
    if total_min:
        try:
            qs = qs.filter(grand_total__gte=Decimal(total_min))
        except Exception:
            pass
    if total_max:
        try:
            qs = qs.filter(grand_total__lte=Decimal(total_max))
        except Exception:
            pass
    if search:
        qs = filter_by_arabic_search(qs, search, ['order_number', 'serial_num', 'customer__name'])

    columns = [
        {'header': 'رقم أمر البيع', 'key': 'order_number', 'width': 18, 'align': 'center'},
        {'header': 'العميل', 'key': lambda o: o.customer.name, 'width': 35, 'align': 'right'},
        {'header': 'المنطقة', 'key': lambda o: o.customer.area.name if o.customer.area else '', 'width': 20, 'align': 'right'},
        {'header': 'المخزن المنصرف منه', 'key': lambda o: o.source_warehouse.name if o.source_warehouse else '', 'width': 22, 'align': 'right'},
        {'header': 'تاريخ الطلب', 'key': lambda o: o.order_date.strftime('%Y-%m-%d') if o.order_date else '', 'width': 16, 'align': 'center'},
        {'header': 'الحالة', 'key': lambda o: o.status_display_ar, 'width': 18, 'align': 'center'},
        {'header': 'حالة السداد', 'key': lambda o: o.payment_status_display_ar, 'width': 16, 'align': 'center'},
        {'header': 'إجمالي القيمة', 'key': lambda o: float(o.grand_total) if o.grand_total is not None else 0.0, 'format': '#,##0.00', 'width': 18, 'align': 'right'},
        {'header': 'المنشئ', 'key': lambda o: (o.created_by.name or o.created_by.username) if o.created_by else '', 'width': 22, 'align': 'right'},
        {'header': 'ملاحظات', 'key': lambda o: o.notes or '', 'width': 30, 'align': 'right'},
    ]

    return export_to_excel_response(
        qs,
        columns,
        filename="sales_orders_export",
        sheet_title="أوامر البيع",
        report_title="تقرير أوامر البيع",
        user=request.user,
    )


@require_permission('sales:collections/export')
def collections_export(request):
    from master_data.filter_utils import (
        parse_single_int,
        resolve_scoped_area_brick_filters,
        build_contact_area_q,
        build_contact_brick_q,
    )
    from master_data.date_filter_utils import resolve_date_range

    search = request.GET.get('search', '').strip()
    customer_id_int = parse_single_int(request.GET, 'customer', 'customer_id')
    vault_id_int = parse_single_int(request.GET, 'vault')
    payment_method = request.GET.get('payment_method')
    parsed_from, parsed_to, _, _, _ = resolve_date_range(request, default_preset='all_time')
    main_area_ids, brick_ids, _, _ = resolve_scoped_area_brick_filters(
        request, 'sales',
        area_params=('main_area', 'area_id', 'governorate'),
        brick_params=('brick', 'brick_id', 'area'),
    )

    qs = Collection.objects.select_related('customer', 'customer__area', 'customer__brick', 'vault', 'created_by').order_by('-serial_num')
    qs = get_scoped_queryset(qs, request.user, 'collection')
    if customer_id_int:
        qs = qs.filter(customer_id=customer_id_int)
    if vault_id_int:
        qs = qs.filter(vault_id=vault_id_int)
    if payment_method and payment_method != 'all':
        qs = qs.filter(payment_method=payment_method)
    if main_area_ids:
        qs = qs.filter(build_contact_area_q(main_area_ids, prefix='customer', include_addresses=False))
    if brick_ids:
        qs = qs.filter(build_contact_brick_q(brick_ids, prefix='customer', include_addresses=False))
    if parsed_from:
        qs = qs.filter(collection_date__gte=parsed_from)
    if parsed_to:
        qs = qs.filter(collection_date__lte=parsed_to)
    if search:
        qs = filter_by_arabic_search(qs, search, ['serial_num', 'customer__name', 'notes'])

    columns = [
        {'header': 'رقم السند', 'key': lambda c: f"#{c.serial_num}", 'width': 14, 'align': 'center'},
        {'header': 'العميل', 'key': lambda c: c.customer.name, 'width': 35, 'align': 'right'},
        {'header': 'الخزنة / الحساب', 'key': lambda c: c.vault.name, 'width': 25, 'align': 'right'},
        {'header': 'المبلغ المحصل', 'key': lambda c: float(c.amount) if c.amount is not None else 0.0, 'format': '#,##0.00', 'width': 18, 'align': 'right'},
        {'header': 'طريقة الدفع', 'key': lambda c: c.get_payment_method_display(), 'width': 16, 'align': 'center'},
        {'header': 'تاريخ وساعة السند', 'key': lambda c: c.created_at.strftime('%Y-%m-%d %H:%M') if c.created_at else '', 'width': 20, 'align': 'center'},
        {'header': 'المحصل', 'key': lambda c: c.created_by.get_full_name() or c.created_by.username if c.created_by else '', 'width': 22, 'align': 'right'},
        {'header': 'ملاحظات', 'key': lambda c: c.notes or '', 'width': 30, 'align': 'right'},
    ]

    return export_to_excel_response(
        qs,
        columns,
        filename="collections_export",
        sheet_title="التحصيلات النقدية",
        report_title="سجل التحصيلات النقدية",
        user=request.user,
    )


@require_permission('sales:returns/list')
def sales_return_orders_list(request):
    from master_data.filter_utils import (
        parse_multi_str,
        parse_single_int,
        resolve_scoped_area_brick_filters,
        build_contact_area_q,
        build_contact_brick_q,
    )
    from master_data.date_filter_utils import resolve_date_range

    customer_id_int = parse_single_int(request.GET, 'customer')
    customer_filter = str(customer_id_int) if customer_id_int else ''
    status_choices_dict = dict(SalesReturnOrder.STATUS_CHOICES)
    selected_statuses = [s for s in parse_multi_str(request.GET, 'status') if s in status_choices_dict]
    search = request.GET.get('search', '').strip()
    parsed_from, parsed_to, active_preset, date_from, date_to = resolve_date_range(request, default_preset='all_time')
    total_min = request.GET.get('total_min', '').strip()
    total_max = request.GET.get('total_max', '').strip()

    qs = SalesReturnOrder.objects.select_related(
        'customer', 'customer__area', 'customer__brick', 'sales_order', 'target_warehouse', 'created_by'
    ).all().order_by('-serial_num')
    qs = get_scoped_queryset(qs, request.user, 'salesreturnorder')

    active_filters = []

    if selected_statuses:
        qs = qs.filter(status__in=selected_statuses)
        for s in selected_statuses:
            active_filters.append({'label': 'الحالة', 'value': status_choices_dict.get(s, s), 'param': 'status', 'remove_value': s})

    if customer_id_int:
        qs = qs.filter(customer_id=customer_id_int)
        c_obj = ScopeResolutionService.get_scoped_choices(request.user, 'customers', 'sales').filter(id=customer_id_int).first()
        active_filters.append({'label': 'العميل', 'value': c_obj.name if c_obj else customer_filter, 'param': 'customer'})

    main_area_ids, brick_ids, selected_main_areas_chips, selected_bricks_chips = resolve_scoped_area_brick_filters(
        request, 'sales',
        area_params=('main_area', 'area_id', 'governorate'),
        brick_params=('brick', 'brick_id', 'area'),
    )
    if main_area_ids:
        qs = qs.filter(build_contact_area_q(main_area_ids, prefix='customer', include_addresses=False))
        for a_chip in selected_main_areas_chips:
            active_filters.append({'label': 'المنطقة الرئيسية', 'value': a_chip['name'], 'param': 'main_area', 'remove_value': str(a_chip['id'])})
    if brick_ids:
        qs = qs.filter(build_contact_brick_q(brick_ids, prefix='customer', include_addresses=False))
        for b_chip in selected_bricks_chips:
            active_filters.append({'label': 'الخط الجغرافي / Brick', 'value': b_chip['name'], 'param': 'brick', 'remove_value': str(b_chip['id'])})

    if parsed_from:
        qs = qs.filter(order_date__gte=parsed_from)
        active_filters.append({'label': 'من تاريخ', 'value': date_from, 'param': 'date_from'})

    if parsed_to:
        qs = qs.filter(order_date__lte=parsed_to)
        active_filters.append({'label': 'إلى تاريخ', 'value': date_to, 'param': 'date_to'})

    if total_min:
        try:
            val_min = Decimal(total_min)
            qs = qs.filter(grand_total__gte=val_min)
            active_filters.append({'label': f'الحد الأدنى للقيمة: {val_min:,.2f} ج.م', 'param': 'total_min'})
        except Exception:
            total_min = ''

    if total_max:
        try:
            val_max = Decimal(total_max)
            qs = qs.filter(grand_total__lte=val_max)
            active_filters.append({'label': f'الحد الأقصى للقيمة: {val_max:,.2f} ج.م', 'param': 'total_max'})
        except Exception:
            total_max = ''

    if search:
        qs = filter_by_arabic_search(qs, search, ['order_number', 'serial_num', 'customer__name', 'sales_order__order_number'])
        active_filters.append({'label': f'بحث: {search}', 'param': 'search'})

    customers = get_bounded_select_options(
        ScopeResolutionService.get_scoped_choices(request.user, 'customers', 'sales'),
        selected_id=customer_filter,
        limit=100,
    )

    ret_agg = qs.aggregate(
        total_orders=Count('id'),
        total_value=Sum('grand_total'),
    )
    return_stats = {
        'total_orders': ret_agg['total_orders'] or 0,
        'total_value': ret_agg['total_value'] or Decimal('0.00'),
    }

    paginator, page_obj = paginate_queryset(request, qs, default_per_page=25, max_per_page=100)

    status_options = [{'value': k, 'label': v} for k, v in SalesReturnOrder.STATUS_CHOICES]
    selected_status_items = [o for o in status_options if o['value'] in selected_statuses]

    context = {
        'returns': page_obj.object_list,
        'page_obj': page_obj,
        'paginator': paginator,
        'status_options': status_options,
        'selected_status_items': selected_status_items,
        'selected_statuses': selected_statuses,
        'selected_main_areas_chips': selected_main_areas_chips,
        'selected_bricks_chips': selected_bricks_chips,
        'active_preset': active_preset,
        'selected_customer': customer_filter,
        'selected_date_from': date_from,
        'selected_date_to': date_to,
        'selected_total_min': total_min,
        'selected_total_max': total_max,
        'search_query': search,
        'date_from': date_from,
        'date_to': date_to,
        'customers': customers,
        'active_filters': active_filters,
        'active_filters_count': len(active_filters),
        'total_count': paginator.count,
        'stats': return_stats,
    }
    return render(request, 'sales/sales_return_orders_list.html', context)


@require_permission('sales:returns/delete')
def sales_return_order_delete(request, pk):
    return_order = get_object_or_404(SalesReturnOrder, pk=pk)
    if not can_user_access_object(request.user, return_order, 'delete'):
        return render_forbidden_response(request, "لا يمكنك حذف هذا المرتجع خارج نطاق اختصاصك أو منطقتك الجغرافية.")

    if request.method != 'POST':
        messages.error(request, "طريقة طلب غير صالحة للحذف. يلزم استخدام POST.")
        return redirect('sales_return_order_detail', pk=pk)

    try:
        SalesReturnOrderService.delete_return_order(return_order, request.user)
        messages.success(request, f"تم حذف أمر مرتجع المبيعات {return_order.order_number} بنجاح وعكس الحركات المخزنية والمالية.")
        return redirect('sales_return_orders_list')
    except ValidationError as e:
        messages.error(request, str(e.message if hasattr(e, 'message') else e))
        return redirect('sales_return_order_detail', pk=pk)


@require_permission('sales:returns/create')
def sales_return_order_create(request):
    if request.method == 'POST':
        order_id = request.POST.get('sales_order')
        warehouse_id = request.POST.get('warehouse')
        order_date = request.POST.get('order_date') or timezone.now().date()
        notes = request.POST.get('notes', '').strip()

        if not order_id:
            messages.error(request, "يرجى تحديد أمر البيع المراد عمل مرتجع له.")
            return redirect('sales_return_order_create')

        sales_order = get_object_or_404(SalesOrder, id=order_id)
        if not can_user_access_object(request.user, sales_order, 'view'):
            return render_forbidden_response(request, "غير مصرح لك بعمل مرتجع لأمر بيع خارج نطاقك الجغرافي.")

        warehouse = None
        if warehouse_id:
            warehouse = get_object_or_404(Warehouse, id=warehouse_id)
            if not can_user_access_object(request.user, warehouse, 'operate'):
                return render_forbidden_response(request, "غير مصرح لك بالاستلام في هذا المخزن.")

        orig_item_ids = request.POST.getlist('original_item_id[]')
        quantities = request.POST.getlist('quantity[]')
        conditions = request.POST.getlist('condition[]')
        batch_numbers = request.POST.getlist('batch_number[]')
        expiry_dates = request.POST.getlist('expiry_date[]')

        items_data = []
        for i in range(len(orig_item_ids)):
            item_id = orig_item_ids[i]
            if not item_id:
                continue
            qty_str = quantities[i] if i < len(quantities) else '0'
            try:
                qty = Decimal(qty_str)
            except Exception:
                continue
            if qty <= Decimal('0.00'):
                continue

            cond = conditions[i] if i < len(conditions) else 'resalable'
            batch = batch_numbers[i] if i < len(batch_numbers) else ''
            exp = expiry_dates[i] if (i < len(expiry_dates) and expiry_dates[i]) else None

            items_data.append({
                'original_item_id': item_id,
                'quantity': qty,
                'condition': cond,
                'batch_number': batch,
                'expiry_date': exp,
            })

        def render_return_form_error(err_text):
            messages.error(request, err_text)
            eligible_orders_qs = get_scoped_queryset(
                SalesOrder.objects.filter(status__in=['delivered', 'invoiced']).select_related('customer').order_by('-order_date'),
                request.user,
                'salesorder',
            )
            eligible_orders = get_bounded_select_options(
                eligible_orders_qs,
                selected_id=sales_order.id if sales_order else None,
                limit=50,
            )
            warehouses = ScopeResolutionService.get_scoped_choices(request.user, 'warehouses', 'sales')
            order_items_payload = []
            if sales_order:
                for item in sales_order.items.select_related('product').all():
                    ret_sum = SalesReturnOrderItem.objects.filter(
                        order__sales_order=sales_order,
                        original_item=item
                    ).exclude(order__status__in=['cancelled', 'rejected']).aggregate(s=Sum('quantity'))['s'] or Decimal('0.00')
                    rem_qty = max(Decimal('0.00'), item.quantity - ret_sum)
                    # Find submitted quantity if any
                    sub_qty = Decimal('0.00')
                    sub_cond = 'resalable'
                    for itm_sub in items_data:
                        if str(itm_sub['original_item_id']) == str(item.id):
                            sub_qty = itm_sub['quantity']
                            sub_cond = itm_sub['condition']
                            break
                    order_items_payload.append({
                        'item': item,
                        'returned_so_far': ret_sum,
                        'remaining_returnable': rem_qty,
                        'submitted_quantity': sub_qty,
                        'submitted_condition': sub_cond,
                    })
            ctx = {
                'selected_order': sales_order,
                'order_items_payload': order_items_payload,
                'eligible_orders': eligible_orders,
                'warehouses': warehouses,
                'form_data': {
                    'warehouse': warehouse_id,
                    'order_date': order_date,
                    'notes': notes,
                }
            }
            return render(request, 'sales/sales_return_order_create.html', ctx)

        if not items_data:
            return render_return_form_error("يرجى تحديد صنف واحد على الأقل بكمية صالحة للإرجاع.")

        try:
            return_order = SalesReturnOrderService.create_return_order(
                sales_order=sales_order,
                target_warehouse=warehouse,
                order_date=order_date,
                items_data=items_data,
                user=request.user,
                notes=notes
            )
            if request.FILES.getlist('attachments'):
                from master_data.media_service import store_attachments_from_request
                store_attachments_from_request(return_order, request)
            messages.success(request, f"تم إنشاء إشعار مرتجع المبيعات {return_order.order_number} بنجاح وهو بانتظار الاعتماد.")
            return redirect('sales_return_order_detail', pk=return_order.pk)
        except ValidationError as e:
            return render_return_form_error(str(e.message if hasattr(e, 'message') else e))

    # GET request
    order_id = request.GET.get('order_id')
    selected_order = None
    order_items_payload = []
    if order_id:
        selected_order = SalesOrder.objects.filter(id=order_id, status__in=['delivered', 'invoiced']).first()
        if selected_order and can_user_access_object(request.user, selected_order, 'view'):
            for item in selected_order.items.select_related('product').all():
                ret_sum = SalesReturnOrderItem.objects.filter(
                    order__sales_order=selected_order,
                    original_item=item
                ).exclude(order__status__in=['cancelled', 'rejected']).aggregate(s=Sum('quantity'))['s'] or Decimal('0.00')
                rem_qty = max(Decimal('0.00'), item.quantity - ret_sum)
                order_items_payload.append({
                    'item': item,
                    'returned_so_far': ret_sum,
                    'remaining_returnable': rem_qty,
                })

    eligible_orders_qs = get_scoped_queryset(
        SalesOrder.objects.filter(status__in=['delivered', 'invoiced']).select_related('customer').order_by('-order_date'),
        request.user,
        'salesorder',
    )
    eligible_orders = get_bounded_select_options(
        eligible_orders_qs,
        selected_id=selected_order.id if selected_order else None,
        limit=50,
    )
    warehouses = ScopeResolutionService.get_scoped_choices(request.user, 'warehouses', 'sales')

    context = {
        'selected_order': selected_order,
        'order_items_payload': order_items_payload,
        'eligible_orders': eligible_orders,
        'warehouses': warehouses,
    }
    return render(request, 'sales/sales_return_order_create.html', context)


@require_permission('sales:returns/view')
def sales_return_order_detail(request, pk):
    return_order = get_object_or_404(
        SalesReturnOrder.objects.select_related(
            'customer', 'customer__area', 'sales_order', 'target_warehouse', 'created_by', 'approved_by', 'memo'
        ).prefetch_related('items__product', 'items__original_item'),
        pk=pk
    )
    if not can_user_access_object(request.user, return_order, 'view'):
        return render_forbidden_response(request, "غير مصرح لك بعرض هذا المرتجع خارج نطاقك الجغرافي.")

    role_name = getattr(request.user.role, 'name', '') if hasattr(request.user, 'role') and request.user.role else ''

    can_approve = (
        has_perm_or_admin(request.user, 'sales:returns/approve') and
        can_user_access_object(request.user, return_order, 'approve') and
        return_order.status == 'pending'
    )
    can_deliver = (
        has_perm_or_admin(request.user, 'inventory:transfers/approve') and
        can_user_access_object(request.user, return_order, 'operate') and
        return_order.status == 'approved'
    )
    can_settle = (
        (has_perm_or_admin(request.user, 'sales:orders/manage') or role_name in ['superadmin', 'accountant']) and
        return_order.status == 'delivered'
    )
    can_cancel = (
        (has_perm_or_admin(request.user, 'sales:returns/delete') or return_order.created_by_id == request.user.id) and
        return_order.status in ['pending', 'approved']
    )

    can_delete = (
        has_perm_or_admin(request.user, 'sales:returns/delete') and
        can_user_access_object(request.user, return_order, 'delete')
    )

    timeline_events = build_sales_return_timeline(return_order)

    context = {
        'return_order': return_order,
        'items': return_order.items.all(),
        'can_approve': can_approve,
        'can_deliver': can_deliver,
        'can_settle': can_settle,
        'can_cancel': can_cancel,
        'can_delete': can_delete,
        'timeline_events': timeline_events,
    }
    return render(request, 'sales/sales_return_order_detail.html', context)


@login_required
def sales_return_order_action(request, pk, action):
    if request.method != 'POST':
        messages.error(request, "طريقة الطلب غير صالحة. يجب إرسال الإجراءات عبر طلب آمن (POST).")
        return redirect('sales_return_order_detail', pk=pk)

    return_order = get_object_or_404(SalesReturnOrder, pk=pk)

    try:
        if action == 'approve':
            if not has_perm_or_admin(request.user, 'sales:returns/approve'):
                return render_forbidden_response(request, "ليس لديك صلاحية اعتماد مرتجعات المبيعات.", perm_codename='sales:returns/approve')
            if not can_user_access_object(request.user, return_order, 'approve'):
                messages.error(request, "لا يمكنك اعتماد مرتجع مبيعات قمت بإنشائه بنفسك أو يقع خارج نطاق إدارتك.")
                return redirect('sales_return_order_detail', pk=pk)
            notes = request.POST.get('approval_notes', '')
            SalesReturnOrderService.approve_return_order(return_order, request.user, notes=notes)
            messages.success(request, f"تم اعتماد مرتجع المبيعات {return_order.order_number} بنجاح.")

        elif action == 'reject':
            if not has_perm_or_admin(request.user, 'sales:returns/approve'):
                return render_forbidden_response(request, "ليس لديك صلاحية رفض مرتجعات المبيعات.", perm_codename='sales:returns/approve')
            if not can_user_access_object(request.user, return_order, 'reject'):
                messages.error(request, "لا يمكنك رفض مرتجع مبيعات قمت بإنشائه بنفسك أو يقع خارج نطاق إدارتك.")
                return redirect('sales_return_order_detail', pk=pk)
            reason = request.POST.get('rejection_reason', '').strip()
            if not reason:
                messages.error(request, "يرجى كتابة سبب رفض المرتجع.")
                return redirect('sales_return_order_detail', pk=pk)
            SalesReturnOrderService.reject_return_order(return_order, request.user, reason=reason)
            messages.warning(request, f"تم رفض مرتجع المبيعات {return_order.order_number}.")

        elif action == 'deliver':
            if not has_perm_or_admin(request.user, 'inventory:transfers/approve'):
                return render_forbidden_response(request, "ليس لديك صلاحية استلام بضاعة المرتجع بالمخزن.", perm_codename='inventory:transfers/approve')
            if not can_user_access_object(request.user, return_order, 'operate'):
                return render_forbidden_response(request, "غير مصرح لك باستلام مرتجع خارج نطاقك.")
            SalesReturnOrderService.deliver_return_order(return_order, request.user)
            messages.success(request, f"تم استلام بضاعة المرتجع بالمخزن وتوليد إذن الإضافة المخزني بنجاح.")

        elif action == 'settle':
            if not has_perm_or_admin(request.user, ['sales:orders/manage', 'sales:returns/approve']):
                return render_forbidden_response(request, "ليس لديك صلاحية ترحيل إشعار دائن المرتجع بالحسابات.", perm_codename='sales:orders/manage')
            if not can_user_access_object(request.user, return_order, 'manage'):
                return render_forbidden_response(request, "غير مصرح لك بترحيل مرتجع خارج نطاقك.")
            SalesReturnOrderService.settle_return_order(return_order, request.user)
            messages.success(request, f"تم ترحيل إشعار الدائن للحسابات وتخفيض مديونية العميل {return_order.customer.name} بنجاح.")

        elif action == 'cancel':
            is_creator = (return_order.created_by_id == request.user.id)
            can_cancel = is_creator or (
                has_perm_or_admin(request.user, 'sales:returns/delete')
                and can_user_access_object(request.user, return_order, 'delete')
            )
            if not can_cancel:
                return render_forbidden_response(request, "ليس لديك صلاحية إلغاء هذا المرتجع.", perm_codename='sales:returns/delete')
            reason = request.POST.get('rejection_reason', '') or request.POST.get('reason', 'إلغاء يدوي')
            SalesReturnOrderService.cancel_return_order(return_order, request.user, reason=reason)
            messages.warning(request, f"تم إلغاء مرتجع المبيعات {return_order.order_number}.")

        else:
            messages.error(request, "إجراء غير معروف.")
    except ValidationError as e:
        messages.error(request, str(e.message if hasattr(e, 'message') else e))

    return redirect('sales_return_order_detail', pk=pk)


@require_permission('sales:returns/export')
@require_permission('sales:returns/view')
def sales_return_orders_export(request):
    from master_data.date_filter_utils import resolve_date_range

    status_filter = request.GET.get('status', 'all')
    customer_filter = request.GET.get('customer')
    main_area = request.GET.get('main_area', '').strip()
    brick = request.GET.get('brick', '').strip()
    search = request.GET.get('search', '').strip()
    date_from, date_to, _, _, _ = resolve_date_range(request, default_preset='all_time')

    qs = SalesReturnOrder.objects.select_related('customer', 'customer__area', 'customer__brick', 'sales_order', 'target_warehouse', 'created_by').order_by('-serial_num')
    qs = get_scoped_queryset(qs, request.user, 'salesreturnorder')

    if status_filter != 'all':
        qs = qs.filter(status=status_filter)
    if customer_filter:
        qs = qs.filter(customer_id=customer_filter)
    if main_area and main_area.isdigit():
        qs = qs.filter(
            Q(customer__area_id=int(main_area))
            | Q(customer__area__parent_id=int(main_area))
            | Q(customer__brick__parent_id=int(main_area))
        )
    if brick and brick.isdigit():
        qs = qs.filter(Q(customer__brick_id=int(brick)) | Q(customer__area_id=int(brick)))
    if date_from:
        qs = qs.filter(order_date__gte=date_from)
    if date_to:
        qs = qs.filter(order_date__lte=date_to)
    if search:
        qs = filter_by_arabic_search(qs, search, ['order_number', 'serial_num', 'customer__name', 'sales_order__order_number'])

    columns = [
        {'header': 'رقم المرتجع', 'key': 'order_number', 'width': 18, 'align': 'center'},
        {'header': 'أمر البيع الأصلي', 'key': lambda r: r.sales_order.order_number if r.sales_order else '-', 'width': 18, 'align': 'center'},
        {'header': 'العميل', 'key': lambda r: r.customer.name, 'width': 35, 'align': 'right'},
        {'header': 'مخزن الاستلام', 'key': lambda r: r.target_warehouse.name if r.target_warehouse else '-', 'width': 22, 'align': 'right'},
        {'header': 'تاريخ المرتجع', 'key': lambda r: r.order_date.strftime('%Y-%m-%d') if r.order_date else '', 'width': 16, 'align': 'center'},
        {'header': 'الحالة', 'key': lambda r: r.status_display_ar, 'width': 20, 'align': 'center'},
        {'header': 'عدد الأصناف', 'key': 'items_count', 'width': 14, 'align': 'center'},
        {'header': 'إجمالي المرتجع (ج.م)', 'key': lambda r: float(r.grand_total) if r.grand_total is not None else 0.0, 'format': '#,##0.00', 'width': 18, 'align': 'right'},
        {'header': 'المنشئ', 'key': lambda r: r.created_by.get_full_name() or r.created_by.username if r.created_by else '', 'width': 22, 'align': 'right'},
        {'header': 'ملاحظات', 'key': lambda r: r.notes or '', 'width': 30, 'align': 'right'},
    ]

    return export_to_excel_response(qs, columns, filename="sales_returns_export", sheet_title="مرتجعات المبيعات")


@require_permission('sales:returns/view')
def sales_return_order_print(request, pk):
    return_order = get_object_or_404(
        SalesReturnOrder.objects.select_related(
            'customer', 'customer__area', 'sales_order', 'target_warehouse', 'created_by', 'approved_by'
        ).prefetch_related('items__product', 'items__original_item'),
        pk=pk
    )
    if not can_user_access_object(request.user, return_order, 'view'):
        return render_forbidden_response(request, "غير مصرح لك بطباعة هذا المرتجع خارج نطاقك الجغرافي.")
    return render(request, 'sales/sales_return_order_print.html', {'return_order': return_order})


@login_required
def sales_eligible_orders_api(request):
    search = request.GET.get('q', '').strip()
    customer_id = request.GET.get('customer_id')

    qs = SalesOrder.objects.filter(status__in=['delivered', 'invoiced']).select_related('customer', 'source_warehouse')
    qs = get_scoped_queryset(qs, request.user, 'salesorder')

    if customer_id:
        qs = qs.filter(customer_id=customer_id)

    if search:
        qs = filter_by_arabic_search(qs, search, ['order_number', 'customer__name'])

    results = []
    for order in qs[:30]:
        results.append({
            'id': order.id,
            'order_number': order.order_number,
            'customer_name': order.customer.name,
            'customer_id': order.customer_id,
            'warehouse_id': order.source_warehouse_id,
            'warehouse_name': order.source_warehouse.name if order.source_warehouse else '',
            'order_date': str(order.order_date),
            'grand_total': str(order.grand_total),
        })
    return JsonResponse({'orders': results})


@login_required
def sales_order_return_details_api(request, order_id):
    order = get_object_or_404(SalesOrder.objects.select_related('customer', 'source_warehouse'), id=order_id)
    if not can_user_access_object(request.user, order, 'view'):
        return JsonResponse({'error': 'غير مصرح لك بعرض تفاصيل هذا الطلب.'}, status=403)

    items_data = []
    for itm in order.items.select_related('product').all():
        ret_sum = SalesReturnOrderItem.objects.filter(
            order__sales_order=order,
            original_item=itm
        ).exclude(order__status__in=['cancelled', 'rejected']).aggregate(s=Sum('quantity'))['s'] or Decimal('0.00')
        rem_qty = max(Decimal('0.00'), itm.quantity - ret_sum)
        items_data.append({
            'item_id': itm.id,
            'product_id': itm.product_id,
            'product_name': itm.product.name,
            'product_code': itm.product.sku_code,
            'unit_price': str(itm.unit_price),
            'discount_percentage': str(itm.discount_percentage),
            'tax_percentage': str(itm.tax_percentage),
            'original_quantity': str(itm.quantity),
            'returned_so_far': str(ret_sum),
            'remaining_returnable': str(rem_qty),
            'batch_number': getattr(itm, 'batch_number', ''),
            'expiry_date': str(getattr(itm, 'expiry_date', '')) if getattr(itm, 'expiry_date', None) else '',
        })

    return JsonResponse({
        'order_id': order.id,
        'order_number': order.order_number,
        'customer_name': order.customer.name,
        'customer_id': order.customer_id,
        'warehouse_id': order.source_warehouse_id,
        'warehouse_name': order.source_warehouse.name if order.source_warehouse else '',
        'items': items_data
    })


@require_permission([
    'sales:orders/list',
    'sales:orders/create',
    'sales:orders/edit',
    'sales:collections/list',
    'sales:collections/create',
    'sales:returns/list',
    'sales:customers/transactions',
    'sales:customers/accounting',
])
def sales_customers_search_api(request):
    """Scoped Arabic-normalized smart-search API for Sales customer selectors."""
    q = (request.GET.get('q') or request.GET.get('search') or '').strip()
    scope_model = (request.GET.get('scope_model') or '').strip().lower()
    limit = parse_search_limit(request)

    if scope_model == 'customeraccount':
        scoped_acc_customer_ids = get_scoped_queryset(
            CustomerAccount.objects.all(), request.user, 'customeraccount'
        ).values_list('customer_id', flat=True)
        qs = Contact.objects.filter(
            id__in=scoped_acc_customer_ids, is_customer=True, status='customer'
        ).select_related('area', 'brick').order_by('name')
    else:
        qs = ScopeResolutionService.get_scoped_choices(request.user, 'customers', 'sales')
    if q:
        qs = filter_by_arabic_search(
            qs,
            ['name', 'area__name', 'brick__name'],
            q,
            raw_fields=['code', 'mobile', 'serial_num'],
            numeric_id_field='serial_num',
        )

    total_count = qs.count()
    results = [serialize_contact_option(c) for c in qs[:limit]]
    return JsonResponse({'results': results, 'count': len(results), 'total_count': total_count})


@require_permission([
    'sales:orders/list',
    'sales:returns/list',
    'sales:returns/create',
    'sales:collections/list',
    'sales:collections/create',
])
def sales_orders_search_api(request):
    """Scoped Arabic-normalized smart-search API for Sales Order selectors."""
    q = (request.GET.get('q') or request.GET.get('search') or '').strip()
    customer_id = request.GET.get('customer_id') or request.GET.get('customer')
    for_return = request.GET.get('for_return')
    unpaid_only = str(request.GET.get('unpaid_only', '')).strip().lower() in ('1', 'true', 'yes', 'on')
    include_order_id = request.GET.get('include_order_id') or request.GET.get('selected_order_id')
    limit = parse_search_limit(request)

    qs = get_scoped_queryset(
        SalesOrder.with_payment_totals(
            SalesOrder.objects.exclude(status__in=['cancelled', 'rejected'])
            .select_related('customer', 'source_warehouse', 'created_by')
            .order_by('-order_date', '-id')
        ),
        request.user,
        'salesorder'
    )
    if for_return:
        qs = qs.filter(status__in=['delivered', 'invoiced'])
    if customer_id and str(customer_id).isdigit():
        qs = qs.filter(customer_id=int(customer_id))
    if unpaid_only:
        qs = qs.exclude(payment_status__in=['paid', 'returned'])
    if q:
        qs = filter_by_arabic_search(
            qs,
            ['order_number', 'customer__name', 'source_warehouse__name'],
            q,
            raw_fields=['order_number', 'serial_num'],
            numeric_id_field='serial_num',
        )

    customer_balance_payload = None
    if customer_id and str(customer_id).isdigit():
        cust_obj = get_scoped_queryset(Contact.objects.filter(id=int(customer_id), is_customer=True), request.user, 'contact').first()
        if cust_obj:
            acc = CustomerAccount.get_or_create_for_customer(cust_obj)
            customer_balance_payload = {
                'customer_id': cust_obj.id,
                'customer_name': cust_obj.name,
                'current_balance': f"{(acc.current_balance or Decimal('0.00')):.2f}",
                'overdue_balance': f"{(acc.overdue_balance or Decimal('0.00')):.2f}",
                'credit_limit': f"{(acc.credit_limit or Decimal('0.00')):.2f}",
            }

    def _serialize_order(o):
        bal = o.outstanding_balance
        paid = o.total_paid
        returned = o.total_returned
        due_str = o.due_date.isoformat() if o.due_date else ''
        due_part = f" • استحقاق: {due_str}" if due_str else ''
        return {
            'id': o.id,
            'name': f"{o.order_number} ({o.customer.name})",
            'text': f"أمر بيع {o.order_number} - الإجمالي: {o.grand_total:,.2f} ج.م - المتبقي: {bal:,.2f} ج.م{due_part}",
            'subtext': f"{o.customer.name} • {o.order_date} • {o.status_display_ar} • المتبقي: {bal:,.2f} ج.م",
            'order_number': o.order_number,
            'customer_id': o.customer_id,
            'customer_name': o.customer.name,
            'warehouse_id': o.source_warehouse_id,
            'grand_total': f"{(o.grand_total or Decimal('0.00')):.2f}",
            'paid_amount': f"{paid:.2f}",
            'returned_amount': f"{returned:.2f}",
            'outstanding_balance': f"{bal:.2f}",
            'payment_status': o.payment_status,
            'payment_status_display': o.payment_status_display_ar,
            'due_date': due_str,
        }

    results = []
    seen_ids = set()
    fetch_cap = max(limit * 2, 100) if unpaid_only else limit
    for o in qs[:fetch_cap]:
        if unpaid_only and o.outstanding_balance <= Decimal('0.00'):
            continue
        results.append(_serialize_order(o))
        seen_ids.add(o.id)
        if len(results) >= limit:
            break

    if include_order_id and str(include_order_id).isdigit():
        inc_id = int(include_order_id)
        if inc_id not in seen_ids:
            inc_obj = get_scoped_queryset(
                SalesOrder.with_payment_totals(
                    SalesOrder.objects.filter(id=inc_id).select_related('customer', 'source_warehouse')
                ),
                request.user,
                'salesorder',
            ).first()
            if inc_obj and (not customer_id or str(inc_obj.customer_id) == str(customer_id)):
                results.insert(0, _serialize_order(inc_obj))

    total_count = qs.count()
    return JsonResponse({
        'results': results,
        'count': len(results),
        'total_count': total_count,
        'customer_account': customer_balance_payload,
    })


@require_permission([
    'sales:collections/create',
    'sales:collections/list',
    'sales:customers/accounting',
    'sales:orders/list',
])
def sales_customer_balance_api(request, pk):
    """Returns authoritative overall CustomerAccount balance for a scoped customer."""
    customer = get_object_or_404(Contact, pk=pk, is_customer=True)
    if not can_user_access_object(request.user, customer, 'view'):
        return JsonResponse({'error': 'غير مصرح لك بعرض رصيد هذا العميل.'}, status=403)
    acc = CustomerAccount.get_or_create_for_customer(customer)
    return JsonResponse({
        'customer_id': customer.id,
        'customer_name': customer.name,
        'current_balance': f"{(acc.current_balance or Decimal('0.00')):.2f}",
        'overdue_balance': f"{(acc.overdue_balance or Decimal('0.00')):.2f}",
        'credit_limit': f"{(acc.credit_limit or Decimal('0.00')):.2f}",
        'last_transaction_date': acc.last_transaction_date.isoformat() if acc.last_transaction_date else '',
    })


@require_permission([
    'sales:orders/list',
    'sales:orders/create',
    'sales:orders/edit',
    'sales:returns/create',
])
def sales_warehouses_search_api(request):
    """Scoped smart-search API for Sales warehouse selectors."""
    q = (request.GET.get('q') or request.GET.get('search') or '').strip()
    limit = parse_search_limit(request)

    qs = ScopeResolutionService.get_scoped_choices(request.user, 'warehouses', 'sales')
    if q:
        qs = filter_by_arabic_search(
            qs,
            ['name', 'area__name', 'assigned_user__name'],
            q,
            raw_fields=['code'],
        )

    total_count = qs.count()
    results = [serialize_warehouse_option(wh) for wh in qs[:limit]]
    return JsonResponse({'results': results, 'count': len(results), 'total_count': total_count})


@require_permission([
    'sales:collections/list',
    'sales:collections/create',
])
def sales_vaults_search_api(request):
    """Scoped smart-search API for Sales vault selectors."""
    q = (request.GET.get('q') or request.GET.get('search') or '').strip()
    limit = parse_search_limit(request)

    qs = ScopeResolutionService.get_scoped_choices(request.user, 'vaults', 'sales')
    if q:
        qs = filter_by_arabic_search(
            qs,
            ['name', 'assigned_user__name'],
            q,
            raw_fields=['serial_num', 'assigned_user__username'],
            numeric_id_field='serial_num',
        )

    total_count = qs.count()
    results = [serialize_vault_option(v) for v in qs[:limit]]
    return JsonResponse({'results': results, 'count': len(results), 'total_count': total_count})



