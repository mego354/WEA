from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q, Sum, Count
from django.core.exceptions import ValidationError
from django.utils import timezone

from django.core.paginator import Paginator
from master_data.pagination_utils import paginate_queryset
from master_data.models import Area
from contacts.constants import CUSTOMER_CATEGORIES
from contacts.views import contact_detail, contact_create, contact_edit
from .models import SalesOrder, SalesOrderItem, CustomerAccount, CustomerTransaction, Collection
from .services import SalesOrderService, CollectionService
from contacts.models import Contact
from catalog.models import Product
from inventory.models import Warehouse
from treasury.models import Vault
from accounts.permissions import (
    require_permission, has_perm_or_admin, render_forbidden_response,
    get_scoped_queryset, can_user_access_object
)


@require_permission('sales:orders/list')
def sales_orders_list(request):
    status_filter = request.GET.get('status', 'all')
    customer_filter = request.GET.get('customer')
    search = request.GET.get('search', '').strip()

    qs = SalesOrder.objects.select_related('customer', 'customer__area', 'source_warehouse', 'created_by').all().order_by('-order_date', '-id')
    qs = get_scoped_queryset(qs, request.user, 'salesorder')

    active_filters = []

    if status_filter != 'all':
        if status_filter in ['manager_approval', 'approved']:
            qs = qs.filter(status__in=['manager_approval', 'approved'])
        else:
            qs = qs.filter(status=status_filter)
        status_labels = dict(SalesOrder.STATUS_CHOICES)
        active_filters.append({'label': f'الحالة: {status_labels.get(status_filter, status_filter)}', 'param': 'status'})

    if customer_filter:
        qs = qs.filter(customer_id=customer_filter)
        c_obj = Contact.objects.filter(id=customer_filter).first()
        active_filters.append({'label': f'العميل: {c_obj.name if c_obj else customer_filter}', 'param': 'customer'})

    if search:
        qs = qs.filter(
            Q(order_number__icontains=search) |
            Q(serial_num__icontains=search) |
            Q(customer__name__icontains=search)
        )
        active_filters.append({'label': f'بحث: {search}', 'param': 'search'})

    paginator, page_obj = paginate_queryset(request, qs, default_per_page=25, max_per_page=100)

    # Scoped customer filter options (top 50 active)
    customers = Contact.objects.filter(is_customer=True).order_by('name')[:50]

    # Dedicated real scoped statistics cards (excludes cancelled/rejected)
    scoped_all = get_scoped_queryset(SalesOrder.objects.exclude(status='rejected'), request.user, 'salesorder')
    stats = {
        'total_orders': scoped_all.count(),
        'total_value': scoped_all.aggregate(total=Sum('grand_total'))['total'] or Decimal('0.00'),
        'invoiced_value': scoped_all.filter(status='invoiced').aggregate(total=Sum('grand_total'))['total'] or Decimal('0.00'),
        'pending_count': scoped_all.filter(status__in=['pending', 'manager_approval']).count(),
    }

    context = {
        'orders': page_obj.object_list,
        'page_obj': page_obj,
        'paginator': paginator,
        'current_status': status_filter,
        'selected_customer': customer_filter,
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
        notes = request.POST.get('notes', '').strip()

        # Parse item rows
        product_ids = request.POST.getlist('product_id[]')
        quantities = request.POST.getlist('quantity[]')
        unit_prices = request.POST.getlist('unit_price[]')

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

            items_data.append({
                'product': prod,
                'quantity': qty,
                'unit_price': price,
            })

        from accounts.services import is_representative, get_representative_warehouse
        is_rep = is_representative(request.user)
        rep_wh = get_representative_warehouse(request.user) if is_rep else None

        if is_rep:
            if not rep_wh:
                messages.error(request, "لم يتم تعيين مخزن عهدة افتراضي لحساب المندوب الخاص بك. يرجى مراجعة إدارة النظام.")
                return redirect('sales_order_create')
            warehouse = rep_wh
        else:
            if not warehouse_id:
                messages.error(request, "يرجى تحديد المخزن.")
                return redirect('sales_order_create')
            warehouse = get_object_or_404(Warehouse, id=warehouse_id)
            if warehouse.assigned_user and not (request.user.is_superuser or getattr(request.user, 'is_super_admin', False)):
                from accounts.permissions import is_manager_eligible_for_user
                if not is_manager_eligible_for_user(request.user, warehouse.assigned_user):
                    return render_forbidden_response(request, "لا يمكنك إجراء مبيعات من مخزن يتبع مندوباً خارج منطقتك الرئيسية.")

        if not customer_id:
            messages.error(request, "يرجى تحديد العميل.")
            return redirect('sales_order_create')

        customer = get_object_or_404(Contact, id=customer_id)

        try:
            order = SalesOrderService.create_order(
                customer=customer,
                source_warehouse=warehouse,
                order_date=order_date,
                items_data=items_data,
                user=request.user,
                delivery_date=delivery_date,
                due_date=due_date,
                notes=notes
            )
            messages.success(request, f"تم إنشاء أمر البيع بنجاح ({order.order_number}) بإجمالي {order.grand_total:,.2f} ج.م.")
            return redirect('sales_order_detail', pk=order.pk)
        except ValidationError as e:
            messages.error(request, str(e.message if hasattr(e, 'message') else e))
            return redirect('sales_order_create')

    from accounts.services import is_representative, get_representative_warehouse
    is_rep = is_representative(request.user)
    user_rep_wh = get_representative_warehouse(request.user) if is_rep else None

    customers = get_scoped_queryset(Contact.objects.filter(is_customer=True), request.user, 'contact')
    if user_rep_wh:
        warehouses = Warehouse.objects.filter(id=user_rep_wh.id)
    else:
        warehouses = get_scoped_queryset(Warehouse.objects.filter(is_active=True), request.user, 'warehouse')
    products = Product.objects.filter(is_active=True)

    context = {
        'customers': customers,
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

    if order.status in ['preparing', 'delivered', 'invoiced', 'cancelled']:
        messages.error(request, f"لا يمكن تعديل أمر البيع في حالته الحالية ({order.get_status_display()}).")
        return redirect('sales_order_detail', pk=order.pk)

    if request.method == 'POST':
        customer_id = request.POST.get('customer')
        warehouse_id = request.POST.get('warehouse')
        order_date = request.POST.get('order_date')
        delivery_date = request.POST.get('delivery_date') or None
        due_date = request.POST.get('due_date') or None
        notes = request.POST.get('notes', '').strip()

        product_ids = request.POST.getlist('product_id[]')
        quantities = request.POST.getlist('quantity[]')
        unit_prices = request.POST.getlist('unit_price[]')

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
            items_data.append({
                'product': prod,
                'quantity': qty,
                'unit_price': price,
            })

        from accounts.services import is_representative, get_representative_warehouse
        is_rep = is_representative(request.user)
        rep_wh = get_representative_warehouse(request.user) if is_rep else None

        if is_rep:
            if not rep_wh:
                messages.error(request, "لم يتم تعيين مخزن عهدة افتراضي لحساب المندوب الخاص بك.")
                return redirect('sales_order_edit', pk=order.pk)
            warehouse = rep_wh
        else:
            if not warehouse_id:
                messages.error(request, "يرجى تحديد المخزن.")
                return redirect('sales_order_edit', pk=order.pk)
            warehouse = get_object_or_404(Warehouse, id=warehouse_id)
            if warehouse.assigned_user and not (request.user.is_superuser or getattr(request.user, 'is_super_admin', False)):
                from accounts.permissions import is_manager_eligible_for_user
                if not is_manager_eligible_for_user(request.user, warehouse.assigned_user):
                    return render_forbidden_response(request, "لا يمكنك إجراء مبيعات من مخزن يتبع مندوباً خارج منطقتك الرئيسية.")

        if not customer_id:
            messages.error(request, "يرجى تحديد العميل.")
            return redirect('sales_order_edit', pk=order.pk)

        customer = get_object_or_404(Contact, id=customer_id)

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
                notes=notes
            )
            messages.success(request, f"تم تعديل أمر البيع بنجاح ({order.order_number}) بإجمالي {order.grand_total:,.2f} ج.م.")
            return redirect('sales_order_detail', pk=order.pk)
        except ValidationError as e:
            messages.error(request, str(e.message if hasattr(e, 'message') else e))
            return redirect('sales_order_edit', pk=order.pk)

    from accounts.services import is_representative, get_representative_warehouse
    is_rep = is_representative(request.user)
    user_rep_wh = get_representative_warehouse(request.user) if is_rep else None

    customers = get_scoped_queryset(Contact.objects.filter(is_customer=True), request.user, 'contact')
    if user_rep_wh:
        warehouses = Warehouse.objects.filter(id=user_rep_wh.id)
    else:
        warehouses = get_scoped_queryset(Warehouse.objects.filter(is_active=True), request.user, 'warehouse')
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
    can_edit = has_perm_or_admin(request.user, 'sales:orders/edit') and can_user_access_object(request.user, order, 'edit')
    is_owner = (order.created_by_id == request.user.id)
    can_resubmit = is_owner and order.status == 'rejected'

    approval_history = order.approval_history.select_related('actor').order_by('-created_at')

    return render(request, 'sales/sales_order_detail.html', {
        'order': order,
        'can_approve': can_approve,
        'can_edit': can_edit,
        'can_resubmit': can_resubmit,
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
                return redirect(request.META.get('HTTP_REFERER', f'/sales/{order.pk}/'))

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

    return redirect(request.META.get('HTTP_REFERER', f'/sales/{order.pk}/'))


@require_permission('sales:collections/list')
def collections_list(request):
    search = request.GET.get('search', '').strip()
    customer_id = request.GET.get('customer')
    vault_id = request.GET.get('vault')

    qs = Collection.objects.select_related('customer', 'vault', 'created_by').order_by('-serial_num')
    qs = get_scoped_queryset(qs, request.user, 'collection')

    active_filters = []

    if customer_id:
        qs = qs.filter(customer_id=customer_id)
        c_obj = Contact.objects.filter(id=customer_id).first()
        active_filters.append({'label': f'العميل: {c_obj.name if c_obj else customer_id}', 'param': 'customer'})

    if vault_id:
        qs = qs.filter(vault_id=vault_id)
        v_obj = Vault.objects.filter(id=vault_id).first()
        active_filters.append({'label': f'الخزنة: {v_obj.name if v_obj else vault_id}', 'param': 'vault'})

    if search:
        qs = qs.filter(
            Q(serial_num__icontains=search) |
            Q(customer__name__icontains=search) |
            Q(notes__icontains=search)
        )
        active_filters.append({'label': f'بحث: {search}', 'param': 'search'})

    customers = get_scoped_queryset(Contact.objects.filter(is_customer=True), request.user, 'contact').order_by('name')[:50]
    vaults = get_scoped_queryset(Vault.objects.filter(is_active=True), request.user, 'vault').order_by('name')

    paginator, page_obj = paginate_queryset(request, qs, default_per_page=25, max_per_page=100)

    # Dedicated real scoped statistics cards
    scoped_col = get_scoped_queryset(Collection.objects.all(), request.user, 'collection')
    now = timezone.now()
    stats = {
        'total_count': scoped_col.count(),
        'total_amount': scoped_col.aggregate(total=Sum('amount'))['total'] or Decimal('0.00'),
        'month_amount': scoped_col.filter(collection_date__year=now.year, collection_date__month=now.month).aggregate(total=Sum('amount'))['total'] or Decimal('0.00'),
        'vaults_count': scoped_col.values('vault').distinct().count(),
    }

    context = {
        'collections': page_obj.object_list,
        'page_obj': page_obj,
        'paginator': paginator,
        'customers': customers,
        'vaults': vaults,
        'search_query': search,
        'selected_customer_id': customer_id,
        'selected_vault_id': vault_id,
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
            order_info = f" لأمر بيع {sales_order.order_number}" if sales_order else ""
            messages.success(request, f"تم تسجيل سند التحصيل #{col.serial_num} بنجاح بمبلغ {col.amount:,.2f} ج.م من العميل {customer.name}{order_info}.")
            return redirect('collections_list')
        except ValidationError as e:
            messages.error(request, str(e.message if hasattr(e, 'message') else e))
            return redirect('collection_create')

    customers = get_scoped_queryset(Contact.objects.filter(is_customer=True), request.user, 'contact')
    vaults = get_scoped_queryset(Vault.objects.filter(is_active=True), request.user, 'vault')
    initial_customer = request.GET.get('customer_id')
    initial_order = request.GET.get('order_id')

    if initial_order and not initial_customer:
        ord_obj = SalesOrder.objects.filter(id=initial_order).first()
        if ord_obj:
            initial_customer = ord_obj.customer_id

    # Open sales orders for dropdown linking
    orders_qs = SalesOrder.objects.exclude(status='cancelled').select_related('customer').order_by('-order_date')
    orders_qs = get_scoped_queryset(orders_qs, request.user, 'salesorder')

    context = {
        'customers': customers,
        'vaults': vaults,
        'orders': orders_qs,
        'selected_customer_id': int(initial_customer) if initial_customer and str(initial_customer).isdigit() else None,
        'selected_order_id': int(initial_order) if initial_order and str(initial_order).isdigit() else None,
    }
    return render(request, 'sales/collection_create.html', context)


@require_permission(['contacts:contacts/list', 'sales:orders/list', 'sales:customers/accounting'])
def sales_customers_list(request):
    """
    Sales Customer Directory & Profiles (دليل وبيانات العملاء).
    Fully scoped by user role and geographic territory.
    """
    search = request.GET.get('search', '').strip() or request.GET.get('q', '').strip()
    status = request.GET.get('status', 'all').strip()
    area_id = request.GET.get('area_id', '').strip()
    category = request.GET.get('category', 'all').strip()

    qs = Contact.objects.filter(is_customer=True).select_related('area', 'customer_account', 'created_by').prefetch_related('addresses__area')
    qs = get_scoped_queryset(qs, request.user, 'contact')

    if status and status != 'all':
        qs = qs.filter(status=status)
    if area_id:
        qs = qs.filter(Q(area_id=area_id) | Q(addresses__area_id=area_id)).distinct()
    if category and category != 'all':
        qs = qs.filter(customer_category=category)

    if search:
        qs = qs.filter(
            Q(name__icontains=search) |
            Q(serial_num__icontains=search) |
            Q(mobile__icontains=search) |
            Q(phone__icontains=search) |
            Q(code__icontains=search) |
            Q(contact_person__icontains=search) |
            Q(tax_id__icontains=search)
        ).distinct()

    qs = qs.order_by('name')

    # Dedicated scoped statistics
    base_scoped = get_scoped_queryset(Contact.objects.filter(is_customer=True), request.user, 'contact')
    stats = {
        'total_customers': base_scoped.count(),
        'active_customers': base_scoped.filter(status__in=['active', 'customer']).count(),
        'lead_customers': base_scoped.filter(status='lead').count(),
        'total_receivable': CustomerAccount.objects.filter(customer__in=base_scoped, current_balance__gt=0).aggregate(tot=Sum('current_balance'))['tot'] or Decimal('0.00'),
    }

    paginator, page_obj = paginate_queryset(request, qs, default_per_page=25)

    governorates = Area.objects.filter(area_type='governorate', is_company_area=False).order_by('name')
    if not governorates.exists():
        governorates = Area.objects.filter(is_company_area=False).order_by('name')

    categories = [c[0] if isinstance(c, (list, tuple)) else c for c in CUSTOMER_CATEGORIES]

    context = {
        'customers': page_obj.object_list,
        'page_obj': page_obj,
        'paginator': paginator,
        'total_count': paginator.count,
        'stats': stats,
        'search_query': search,
        'current_status': status,
        'current_area_id': area_id,
        'current_category': category,
        'governorates': governorates,
        'categories': categories,
    }
    return render(request, 'sales/customers_list.html', context)


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
    search = request.GET.get('search', '').strip()
    qs = CustomerAccount.objects.select_related('customer', 'customer__area').order_by('-current_balance')
    qs = get_scoped_queryset(qs, request.user, 'customeraccount')

    active_filters = []
    if search:
        qs = qs.filter(
            Q(customer__name__icontains=search) |
            Q(customer__code__icontains=search)
        )
        active_filters.append({'label': f'بحث: {search}', 'param': 'search'})

    base_scoped = get_scoped_queryset(CustomerAccount.objects.all(), request.user, 'customeraccount')
    account_stats = {
        'total_customers': base_scoped.count(),
        'total_receivable': base_scoped.filter(current_balance__gt=0).aggregate(tot=Sum('current_balance'))['tot'] or Decimal('0.00'),
        'total_overdue': base_scoped.filter(overdue_balance__gt=0).aggregate(tot=Sum('overdue_balance'))['tot'] or Decimal('0.00'),
        'total_credit_limit': base_scoped.aggregate(tot=Sum('credit_limit'))['tot'] or Decimal('0.00'),
    }

    paginator, page_obj = paginate_queryset(request, qs, default_per_page=25, max_per_page=100)

    context = {
        'accounts': page_obj.object_list,
        'page_obj': page_obj,
        'paginator': paginator,
        'search_query': search,
        'active_filters': active_filters,
        'total_count': paginator.count,
        'stats': account_stats,
    }
    return render(request, 'sales/accounting_customers_list.html', context)


@require_permission('sales:customers/transactions')
def customer_transactions_list(request):
    """
    Customer Ledger Transactions (عمليات العملاء).
    """
    customer_id = request.GET.get('customer_id')
    search = request.GET.get('search', '').strip()

    qs = CustomerTransaction.objects.select_related('account', 'account__customer', 'created_by').order_by('-serial')
    scoped_contacts = get_scoped_queryset(Contact.objects.all(), request.user, 'contact')
    qs = qs.filter(account__customer__in=scoped_contacts)

    active_filters = []

    if customer_id:
        qs = qs.filter(account__customer_id=customer_id)
        c_obj = Contact.objects.filter(id=customer_id).first()
        active_filters.append({'label': f'العميل: {c_obj.name if c_obj else customer_id}', 'param': 'customer_id'})

    if search:
        qs = qs.filter(
            Q(serial__icontains=search) |
            Q(description__icontains=search) |
            Q(account__customer__name__icontains=search)
        )
        active_filters.append({'label': f'بحث: {search}', 'param': 'search'})

    customers = scoped_contacts.filter(is_customer=True).order_by('name')[:50]

    base_scoped_tx = CustomerTransaction.objects.filter(account__customer__in=scoped_contacts)
    tx_stats = {
        'total_count': base_scoped_tx.count(),
        'total_debit': base_scoped_tx.aggregate(tot=Sum('debit'))['tot'] or Decimal('0.00'),
        'total_credit': base_scoped_tx.aggregate(tot=Sum('credit'))['tot'] or Decimal('0.00'),
    }
    tx_stats['net_balance'] = tx_stats['total_debit'] - tx_stats['total_credit']

    paginator, page_obj = paginate_queryset(request, qs, default_per_page=25, max_per_page=100)

    context = {
        'transactions': page_obj.object_list,
        'page_obj': page_obj,
        'paginator': paginator,
        'customers': customers,
        'selected_customer_id': customer_id,
        'search_query': search,
        'active_filters': active_filters,
        'total_count': paginator.count,
        'stats': tx_stats,
    }
    return render(request, 'sales/customer_transactions_list.html', context)


from master_data.excel_utils import export_to_excel_response


@require_permission('sales:orders/export')
def sales_orders_export(request):
    status_filter = request.GET.get('status', 'all')
    customer_filter = request.GET.get('customer')
    search = request.GET.get('search', '').strip()

    qs = SalesOrder.objects.select_related('customer', 'customer__area', 'source_warehouse', 'created_by').all().order_by('-serial_num')
    qs = get_scoped_queryset(qs, request.user, 'salesorder')

    if status_filter != 'all':
        qs = qs.filter(status=status_filter)
    if customer_filter:
        qs = qs.filter(customer_id=customer_filter)
    if search:
        qs = qs.filter(
            Q(order_number__icontains=search) |
            Q(serial_num__icontains=search) |
            Q(customer__name__icontains=search)
        )

    columns = [
        {'header': 'رقم أمر البيع', 'key': 'order_number', 'width': 18, 'align': 'center'},
        {'header': 'العميل', 'key': lambda o: o.customer.name, 'width': 35, 'align': 'right'},
        {'header': 'المنطقة', 'key': lambda o: o.customer.area.name if o.customer.area else '', 'width': 20, 'align': 'right'},
        {'header': 'المخزن المنصرف منه', 'key': lambda o: o.source_warehouse.name if o.source_warehouse else '', 'width': 22, 'align': 'right'},
        {'header': 'تاريخ الطلب', 'key': lambda o: o.order_date.strftime('%Y-%m-%d') if o.order_date else '', 'width': 16, 'align': 'center'},
        {'header': 'الحالة', 'key': lambda o: o.get_status_display(), 'width': 18, 'align': 'center'},
        {'header': 'إجمالي القيمة', 'key': lambda o: float(o.grand_total) if o.grand_total is not None else 0.0, 'format': '#,##0.00', 'width': 18, 'align': 'right'},
        {'header': 'المنشئ', 'key': lambda o: o.created_by.get_full_name() or o.created_by.username if o.created_by else '', 'width': 22, 'align': 'right'},
        {'header': 'ملاحظات', 'key': lambda o: o.notes or '', 'width': 30, 'align': 'right'},
    ]

    return export_to_excel_response(qs, columns, filename="sales_orders_export", sheet_title="أوامر البيع")


@require_permission('sales:collections/export')
def collections_export(request):
    customer_id = request.GET.get('customer')
    qs = Collection.objects.select_related('customer', 'vault', 'created_by').order_by('-serial_num')
    qs = get_scoped_queryset(qs, request.user, 'collection')
    if customer_id:
        qs = qs.filter(customer_id=customer_id)

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

    return export_to_excel_response(qs, columns, filename="collections_export", sheet_title="التحصيلات النقدية")

