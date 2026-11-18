"""
Unified, strictly-scoped Smart Search Suggestions API for all ERP list views.
"""

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse

from accounts.permissions import has_perm_or_admin, get_scoped_queryset
from master_data.search_utils import filter_by_arabic_search, parse_search_limit


@login_required
def list_suggestions_api(request):
    """
    GET /api/list-suggestions/?module=<module>&q=<query>&limit=10
    Returns strictly scoped, permission-checked suggestions for list view search bars.
    """
    module = (request.GET.get('module') or '').strip().lower()
    q = (request.GET.get('q') or '').strip()
    limit = parse_search_limit(request, default=10, maximum=15)

    if not module or not q:
        return JsonResponse({'results': [], 'count': 0})

    results = []

    if module == 'sales_orders':
        if not has_perm_or_admin(request.user, 'sales:orders/list'):
            return JsonResponse({'error': 'غير مصرح'}, status=403)
        from sales.models import SalesOrder
        qs = get_scoped_queryset(
            SalesOrder.objects.select_related('customer').order_by('-id'),
            request.user,
            'salesorder',
        )
        qs = filter_by_arabic_search(qs, ['order_number', 'customer__name'], q, raw_fields=['order_number'], numeric_id_field='serial_num')
        for obj in qs[:limit]:
            results.append({
                'value': obj.order_number,
                'label': f"{obj.order_number} — {obj.customer.name}",
                'subtext': f"{obj.order_date} | {obj.grand_total:,.2f} ج.م",
            })

    elif module == 'sales_returns':
        if not has_perm_or_admin(request.user, 'sales:returns/list'):
            return JsonResponse({'error': 'غير مصرح'}, status=403)
        from sales.models import SalesReturnOrder
        qs = get_scoped_queryset(
            SalesReturnOrder.objects.select_related('customer').order_by('-id'),
            request.user,
            'salesreturnorder',
        )
        qs = filter_by_arabic_search(qs, ['order_number', 'customer__name'], q, raw_fields=['order_number'], numeric_id_field='serial_num')
        for obj in qs[:limit]:
            results.append({
                'value': obj.order_number,
                'label': f"{obj.order_number} — {obj.customer.name}",
                'subtext': f"{obj.order_date} | {obj.grand_total:,.2f} ج.م",
            })

    elif module == 'collections':
        if not has_perm_or_admin(request.user, 'sales:collections/list'):
            return JsonResponse({'error': 'غير مصرح'}, status=403)
        from sales.models import Collection
        qs = get_scoped_queryset(
            Collection.objects.select_related('customer', 'vault').order_by('-id'),
            request.user,
            'collection',
        )
        qs = filter_by_arabic_search(qs, ['customer__name', 'notes'], q, numeric_id_field='serial_num')
        for obj in qs[:limit]:
            results.append({
                'value': str(obj.serial_num),
                'label': f"#{obj.serial_num} — {obj.customer.name}",
                'subtext': f"{obj.amount:,.2f} ج.م | {obj.vault.name}",
            })

    elif module in ('contacts', 'customers'):
        if not has_perm_or_admin(request.user, 'contacts:contacts/list'):
            return JsonResponse({'error': 'غير مصرح'}, status=403)
        from contacts.models import Contact
        qs = get_scoped_queryset(
            Contact.objects.select_related('area', 'brick').order_by('name'),
            request.user,
            'contact',
        )
        if module == 'customers':
            qs = qs.filter(is_customer=True)
        qs = filter_by_arabic_search(qs, ['name', 'code', 'mobile', 'phone'], q, raw_fields=['code', 'mobile', 'phone'], numeric_id_field='serial_num')
        for obj in qs[:limit]:
            results.append({
                'value': obj.name,
                'label': obj.name,
                'subtext': " | ".join(p for p in [obj.code, obj.mobile, obj.area.name if obj.area else ''] if p),
            })

    elif module == 'purchase_orders':
        if not has_perm_or_admin(request.user, 'purchases:orders/list'):
            return JsonResponse({'error': 'غير مصرح'}, status=403)
        from purchases.models import PurchaseOrder
        qs = get_scoped_queryset(
            PurchaseOrder.objects.select_related('supplier').order_by('-id'),
            request.user,
            'purchaseorder',
        )
        qs = filter_by_arabic_search(qs, ['order_number', 'supplier__name'], q, raw_fields=['order_number'], numeric_id_field='serial_num')
        for obj in qs[:limit]:
            results.append({
                'value': obj.order_number,
                'label': f"{obj.order_number} — {obj.supplier.name}",
                'subtext': f"{obj.order_date} | {obj.grand_total:,.2f} ج.م",
            })

    elif module == 'purchase_returns':
        if not has_perm_or_admin(request.user, 'purchases:returns/list'):
            return JsonResponse({'error': 'غير مصرح'}, status=403)
        from purchases.models import PurchaseReturnOrder
        qs = get_scoped_queryset(
            PurchaseReturnOrder.objects.select_related('supplier').order_by('-id'),
            request.user,
            'purchasereturnorder',
        )
        qs = filter_by_arabic_search(qs, ['order_number', 'supplier__name'], q, raw_fields=['order_number'], numeric_id_field='serial_num')
        for obj in qs[:limit]:
            results.append({
                'value': obj.order_number,
                'label': f"{obj.order_number} — {obj.supplier.name}",
                'subtext': f"{obj.order_date} | {obj.grand_total:,.2f} ج.م",
            })

    elif module == 'products':
        if not has_perm_or_admin(request.user, 'catalog:products/list'):
            return JsonResponse({'error': 'غير مصرح'}, status=403)
        from catalog.models import Product
        qs = filter_by_arabic_search(
            Product.objects.select_related('category').order_by('name'),
            ['name', 'sku_code', 'barcode'],
            q,
            raw_fields=['sku_code', 'barcode'],
        )
        for obj in qs[:limit]:
            results.append({
                'value': obj.name,
                'label': f"{obj.name} ({obj.sku_code})",
                'subtext': f"{obj.category.name if obj.category else ''} | {obj.retail_price:,.2f} ج.م",
            })

    elif module == 'inventory_stocks':
        if not has_perm_or_admin(request.user, 'inventory:stocks/view'):
            return JsonResponse({'error': 'غير مصرح'}, status=403)
        from inventory.models import InventoryStock
        qs = get_scoped_queryset(
            InventoryStock.objects.select_related('product', 'warehouse').order_by('product__name'),
            request.user,
            'inventorystock',
        )
        qs = filter_by_arabic_search(qs, ['product__name', 'product__sku_code', 'warehouse__name'], q, raw_fields=['product__sku_code'])
        for obj in qs[:limit]:
            results.append({
                'value': obj.product.name,
                'label': f"{obj.product.name} ({obj.product.sku_code})",
                'subtext': f"{obj.warehouse.name} | متاح: {int(obj.qty_available)}",
            })

    elif module == 'inventory_memos':
        if not has_perm_or_admin(request.user, 'inventory:memos/manage'):
            return JsonResponse({'error': 'غير مصرح'}, status=403)
        from inventory.models import InventoryMemo
        qs = get_scoped_queryset(
            InventoryMemo.objects.select_related('warehouse').order_by('-id'),
            request.user,
            'inventorymemo',
        )
        qs = filter_by_arabic_search(qs, ['memo_number', 'statement', 'warehouse__name'], q, raw_fields=['memo_number'])
        for obj in qs[:limit]:
            results.append({
                'value': obj.memo_number,
                'label': f"{obj.memo_number} — {obj.warehouse.name}",
                'subtext': obj.statement[:50],
            })

    elif module == 'product_transfers':
        if not has_perm_or_admin(request.user, 'inventory:transfers/list'):
            return JsonResponse({'error': 'غير مصرح'}, status=403)
        from inventory.models import ProductTransferRequest
        qs = get_scoped_queryset(
            ProductTransferRequest.objects.select_related('source_warehouse', 'destination_warehouse').order_by('-id'),
            request.user,
            'producttransferrequest',
        )
        qs = filter_by_arabic_search(qs, ['reference_number', 'source_warehouse__name', 'destination_warehouse__name'], q, raw_fields=['reference_number'])
        for obj in qs[:limit]:
            results.append({
                'value': obj.reference_number,
                'label': obj.reference_number,
                'subtext': f"{obj.source_warehouse.name} → {obj.destination_warehouse.name}",
            })

    elif module == 'warehouses':
        if not has_perm_or_admin(request.user, ['inventory:warehouses/manage', 'inventory:stocks/view']):
            return JsonResponse({'error': 'غير مصرح'}, status=403)
        from inventory.models import Warehouse
        qs = get_scoped_queryset(Warehouse.objects.select_related('area').order_by('name'), request.user, 'warehouse')
        qs = filter_by_arabic_search(qs, ['name', 'code'], q, raw_fields=['code'])
        for obj in qs[:limit]:
            results.append({
                'value': obj.name,
                'label': f"{obj.name} ({obj.code})",
                'subtext': obj.area.name if obj.area else '',
            })

    elif module == 'vaults':
        if not has_perm_or_admin(request.user, 'treasury:vaults/view'):
            return JsonResponse({'error': 'غير مصرح'}, status=403)
        from treasury.models import Vault
        qs = get_scoped_queryset(Vault.objects.select_related('assigned_user').order_by('name'), request.user, 'vault')
        qs = filter_by_arabic_search(qs, ['name'], q, numeric_id_field='serial_num')
        for obj in qs[:limit]:
            results.append({
                'value': obj.name,
                'label': obj.name,
                'subtext': f"{obj.current_balance:,.2f} ج.م",
            })

    elif module == 'visits':
        if not has_perm_or_admin(request.user, 'activities:visits/list'):
            return JsonResponse({'error': 'غير مصرح'}, status=403)
        from activities.models import Visit
        qs = get_scoped_queryset(Visit.objects.select_related('contact', 'owner').order_by('-id'), request.user, 'visit')
        qs = filter_by_arabic_search(qs, ['contact__name', 'contact__code', 'owner__name'], q, raw_fields=['contact__code'], numeric_id_field='serial_num')
        for obj in qs[:limit]:
            results.append({
                'value': obj.contact.name,
                'label': f"#{obj.serial_num} — {obj.contact.name}",
                'subtext': f"{obj.date} | {obj.owner.name or obj.owner.username}",
            })

    elif module == 'agreements':
        if not has_perm_or_admin(request.user, 'activities:agreements/list'):
            return JsonResponse({'error': 'غير مصرح'}, status=403)
        from activities.models import Agreement
        qs = get_scoped_queryset(Agreement.objects.select_related('customer').order_by('-id'), request.user, 'agreement')
        qs = filter_by_arabic_search(qs, ['title', 'customer__name', 'customer__code'], q, raw_fields=['customer__code'], numeric_id_field='serial_num')
        for obj in qs[:limit]:
            results.append({
                'value': obj.title,
                'label': f"#{obj.serial_num} — {obj.title}",
                'subtext': f"{obj.customer.name} | {obj.amount:,.2f} ج.م",
            })

    elif module == 'users':
        if not has_perm_or_admin(request.user, 'users:users/list'):
            return JsonResponse({'error': 'غير مصرح'}, status=403)
        from accounts.models import User
        qs = get_scoped_queryset(User.objects.select_related('role').order_by('name'), request.user, 'user')
        qs = filter_by_arabic_search(qs, ['name', 'username', 'email', 'code'], q, raw_fields=['username', 'code'])
        for obj in qs[:limit]:
            results.append({
                'value': obj.name or obj.username,
                'label': f"{obj.name or obj.username} (@{obj.username})",
                'subtext': obj.role.display_name if obj.role else '',
            })

    elif module in ('vendor_payments', 'vendor_payment_requests'):
        perm = 'treasury:payments/list' if module == 'vendor_payments' else 'treasury:payments/requests'
        if not has_perm_or_admin(request.user, perm):
            return JsonResponse({'error': 'غير مصرح'}, status=403)
        from treasury.models import VendorPayment, VendorPaymentRequest
        model_cls = VendorPayment if module == 'vendor_payments' else VendorPaymentRequest
        m_key = 'vendorpayment' if module == 'vendor_payments' else 'vendorpaymentrequest'
        qs = get_scoped_queryset(model_cls.objects.select_related('supplier').order_by('-id'), request.user, m_key)
        qs = filter_by_arabic_search(qs, ['supplier__name'], q, numeric_id_field='serial_num')
        for obj in qs[:limit]:
            results.append({
                'value': obj.supplier.name,
                'label': f"#{obj.serial_num} — {obj.supplier.name}",
                'subtext': f"{obj.amount:,.2f} ج.م",
            })

    elif module == 'vendor_transactions':
        if not has_perm_or_admin(request.user, 'treasury:vendors/transactions'):
            return JsonResponse({'error': 'غير مصرح'}, status=403)
        from contacts.models import Contact
        from treasury.models import VendorTransaction
        scoped_suppliers = get_scoped_queryset(Contact.objects.filter(is_supplier=True), request.user, 'contact')
        qs = VendorTransaction.objects.select_related('account__supplier').filter(account__supplier__in=scoped_suppliers).order_by('-serial')
        qs = filter_by_arabic_search(qs, ['description', 'account__supplier__name'], q, numeric_id_field='serial')
        for obj in qs[:limit]:
            results.append({
                'value': obj.account.supplier.name,
                'label': f"#{obj.serial} — {obj.account.supplier.name}",
                'subtext': obj.description or '',
            })

    elif module == 'categories':
        if not has_perm_or_admin(request.user, 'catalog:categories/list'):
            return JsonResponse({'error': 'غير مصرح'}, status=403)
        from catalog.models import ProductCategory
        qs = ProductCategory.objects.order_by('name')
        qs = filter_by_arabic_search(qs, ['name', 'code', 'description'], q, raw_fields=['code'])
        for obj in qs[:limit]:
            results.append({
                'value': obj.name,
                'label': f"{obj.name} ({obj.code})",
                'subtext': obj.description or '',
            })

    elif module == 'roles':
        if not has_perm_or_admin(request.user, ['settings:rbac/view', 'system:rbac/manage']):
            return JsonResponse({'error': 'غير مصرح'}, status=403)
        from accounts.models import Role
        qs = Role.objects.order_by('display_name')
        qs = filter_by_arabic_search(qs, ['display_name', 'name'], q, raw_fields=['name'])
        for obj in qs[:limit]:
            results.append({
                'value': obj.display_name,
                'label': f"{obj.display_name} ({obj.name})",
                'subtext': 'مفعل' if obj.is_active else 'معطل',
            })

    elif module == 'audit_logs':
        if not has_perm_or_admin(request.user, ['settings:auditLogs/view', 'settings:rbac/view']):
            return JsonResponse({'error': 'غير مصرح'}, status=403)
        from django.db.models import Q
        from accounts.models import SecurityAuditLog
        qs = SecurityAuditLog.objects.select_related('actor').order_by('-created_at').filter(
            Q(description__icontains=q) | Q(record_name__icontains=q) | Q(actor__name__icontains=q) | Q(actor__username__icontains=q)
        )
        for obj in qs[:limit]:
            actor_name = (obj.actor.name or obj.actor.username) if obj.actor else 'النظام'
            results.append({
                'value': obj.record_name or actor_name,
                'label': f"{obj.get_action_type_display()} — {actor_name}",
                'subtext': (obj.description or '')[:60],
            })

    return JsonResponse({'results': results, 'count': len(results)})
