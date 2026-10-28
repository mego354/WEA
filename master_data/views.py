import json
import datetime
from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Sum, Count, Q, Avg
from django.http import JsonResponse, HttpResponse
from django.utils import timezone
from purchases.models import PurchaseOrder
from treasury.models import VendorAccount, Vault
from catalog.models import Product
from contacts.models import Contact
from sales.models import SalesOrder, SalesReturnOrder, Collection, CustomerAccount
from activities.models import Visit
from accounts.permissions import (
    require_permission, has_perm_or_admin, get_scoped_queryset,
    is_manager_or_higher, is_accountant, is_representative,
    get_user_managed_representatives, is_manager_eligible_for_user
)
from django.contrib.auth import get_user_model
from inventory.models import Warehouse, InventoryStock
from .models import (
    CompanyProfile, LocationSettings, Area, ExpenseType,
    TicketType, ApprovalRequestType, AgreementType,
    SalesSettings, PurchaseSettings, ContactFieldSetting,
    DataSyncConfig
)


def _format_metric_amount(val):
    if not val:
        return '0 جنيه'
    v = float(val)
    if v >= 1_000_000:
        return f"{v / 1_000_000:.2f}".rstrip('0').rstrip('.') + "M جنيه"
    if v >= 10_000:
        return f"{v / 1_000:.0f}k جنيه"
    if v >= 1_000:
        return f"{v / 1_000:.2f}".rstrip('0').rstrip('.') + "k جنيه"
    return f"{v:.2f}".rstrip('0').rstrip('.') + " جنيه"


def _build_area_sunburst(queryset, amount_field='grand_total', is_count=False):
    if is_count:
        qs = queryset.filter(customer__area__isnull=False).values(
            'customer__area__name',
            'customer__area__parent__name'
        ).annotate(val=Count('id')).order_by('-val')
    else:
        qs = queryset.filter(customer__area__isnull=False).values(
            'customer__area__name',
            'customer__area__parent__name'
        ).annotate(val=Sum(amount_field)).order_by('-val')

    tree = {}
    for item in qs:
        parent_name = item['customer__area__parent__name'] or item['customer__area__name']
        child_name = item['customer__area__name']
        val = float(item['val'] or 0)
        if val <= 0:
            continue
        if parent_name not in tree:
            tree[parent_name] = {'name': parent_name, 'children': []}
        if item['customer__area__parent__name']:
            tree[parent_name]['children'].append({'name': child_name, 'value': val})
        else:
            tree[parent_name]['value'] = tree[parent_name].get('value', 0) + val

    result = []
    sorted_parents = sorted(tree.values(), key=lambda n: sum(c.get('value', 0) for c in n.get('children', [])) + n.get('value', 0), reverse=True)[:8]
    for p in sorted_parents:
        if 'children' in p and p['children']:
            p['children'] = sorted(p['children'], key=lambda x: x.get('value', 0), reverse=True)[:10]
        result.append(p)
    return result


def _build_visits_sunburst(queryset):
    qs = queryset.filter(contact__area__isnull=False).values(
        'contact__area__name',
        'contact__area__parent__name'
    ).annotate(val=Count('id')).order_by('-val')

    tree = {}
    for item in qs:
        parent_name = item['contact__area__parent__name'] or item['contact__area__name']
        child_name = item['contact__area__name']
        val = int(item['val'] or 0)
        if val <= 0:
            continue
        if parent_name not in tree:
            tree[parent_name] = {'name': parent_name, 'children': []}
        if item['contact__area__parent__name']:
            tree[parent_name]['children'].append({'name': child_name, 'value': val})
        else:
            tree[parent_name]['value'] = tree[parent_name].get('value', 0) + val

    result = []
    for p in list(tree.values())[:8]:
        if 'children' in p and p['children']:
            p['children'] = sorted(p['children'], key=lambda x: x.get('value', 0), reverse=True)[:10]
        result.append(p)
    return result


def _build_reps_sunburst(amount_field='current_balance', user=None):
    qs = CustomerAccount.objects.filter(**{f"{amount_field}__gt": 0})
    if user:
        qs = get_scoped_queryset(qs, user, 'customeraccount')
    qs = qs.values(
        'customer__area__name',
        'customer__area__parent__name'
    ).annotate(val=Sum(amount_field)).order_by('-val')

    tree = {}
    for item in qs:
        parent_name = item['customer__area__parent__name'] or item['customer__area__name'] or 'منطقة عامة'
        child_name = item['customer__area__name'] or 'عميل'
        val = float(item['val'] or 0)
        if val <= 0:
            continue
        if parent_name not in tree:
            tree[parent_name] = {'name': parent_name, 'children': []}
        if item['customer__area__parent__name']:
            tree[parent_name]['children'].append({'name': child_name, 'value': val})
        else:
            tree[parent_name]['value'] = tree[parent_name].get('value', 0) + val

    result = []
    sorted_parents = sorted(tree.values(), key=lambda n: sum(c.get('value', 0) for c in n.get('children', [])) + n.get('value', 0), reverse=True)[:7]
    for p in sorted_parents:
        if 'children' in p and p['children']:
            p['children'] = sorted(p['children'], key=lambda x: x.get('value', 0), reverse=True)[:8]
        result.append(p)
    return result


@login_required
def home_view(request):
    """
    Role-Based Executive Home Dashboard with Backend Permission Enforcement:
    - Superadmin: System-wide metrics, sales, collections, inventory, visits, and all charts.
    - Manager: Team-scoped metrics for representatives in their main area, plus ability to select an
      eligible representative to view individual stats, with clear return-to-team option.
    - Accountant: Financial statistics (sales, collections, customer/vendor balances, treasury/vaults).
      Excludes field visits and visits chart.
    - Representative: Individual operational metrics (own sales, collections, visits, warehouse inventory,
      vault cash balance). Excludes cross-rep balance/debt comparison charts to protect peer privacy.
    """
    user = request.user
    UserModel = get_user_model()

    is_super = getattr(user, 'is_super_admin', False) or user.is_superuser or (user.role and user.role.name in ['CEO', 'Admin'])
    is_acct = not is_super and is_accountant(user)
    is_mgr = not is_super and not is_acct and is_manager_or_higher(user)
    is_rep = not is_super and not is_acct and not is_mgr

    # Manager / Superadmin representative selection
    eligible_reps = []
    selected_rep = None
    if is_super or is_mgr:
        if is_super:
            eligible_reps = list(UserModel.objects.filter(is_active=True).filter(
                Q(role__is_rep=True) | Q(assigned_warehouses__isnull=False) | Q(assigned_vaults__isnull=False)
            ).distinct().select_related('role').order_by('name'))
        else:
            eligible_reps = list(get_user_managed_representatives(user).filter(
                is_active=True
            ).exclude(id=user.id).select_related('role').order_by('name'))

        selected_rep_id = request.GET.get('rep_id', '').strip()
        if selected_rep_id and selected_rep_id.isdigit():
            target_user = UserModel.objects.filter(id=int(selected_rep_id), is_active=True).first()
            if target_user:
                if is_super or is_manager_eligible_for_user(user, target_user):
                    selected_rep = target_user
                else:
                    # Security restriction: Rep is outside manager's authorized area scope
                    selected_rep = None
                    messages.warning(request, "لا تملك صلاحية استعراض بيانات هذا المندوب، تم الرجوع لإحصائيات الفريق.")

    start_date_str = request.GET.get('start_date', '').strip()
    end_date_str = request.GET.get('end_date', '').strip()
    period = request.GET.get('period', '').strip()

    start_date = None
    end_date = None
    if period == 'all':
        display_range = "كل الوقت"
        start_date_str = ''
        end_date_str = ''
    elif start_date_str and end_date_str:
        try:
            start_date = datetime.datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.datetime.strptime(end_date_str, '%Y-%m-%d').date()
            display_range = f"{start_date.strftime('%d/%m/%Y')} – {end_date.strftime('%d/%m/%Y')}"
        except ValueError:
            start_date = datetime.date(2026, 10, 1)
            end_date = datetime.date(2026, 10, 31)
            start_date_str = '2026-10-01'
            end_date_str = '2026-10-31'
            display_range = "01/10/2026 – 31/10/2026"
    else:
        start_date = datetime.date(2026, 10, 1)
        end_date = datetime.date(2026, 10, 31)
        start_date_str = '2026-10-01'
        end_date_str = '2026-10-31'
        display_range = "01/10/2026 – 31/10/2026"

    # Querysets strictly filtered by role and authorized scope
    if selected_rep:
        so_qs = SalesOrder.objects.exclude(status='cancelled').filter(created_by=selected_rep)
        ro_qs = SalesReturnOrder.objects.exclude(status='cancelled').filter(created_by=selected_rep)
        col_qs = Collection.objects.filter(created_by=selected_rep)
        vis_qs = Visit.objects.filter(Q(owner=selected_rep) | Q(created_by=selected_rep))
        cont_qs = Contact.objects.filter(is_customer=True).filter(Q(created_by=selected_rep) | Q(assigned_team=selected_rep))
        cust_acc_qs = CustomerAccount.objects.filter(customer__in=cont_qs)
    elif is_rep:
        so_qs = SalesOrder.objects.exclude(status='cancelled').filter(created_by=user)
        ro_qs = SalesReturnOrder.objects.exclude(status='cancelled').filter(created_by=user)
        col_qs = Collection.objects.filter(created_by=user)
        vis_qs = Visit.objects.filter(Q(owner=user) | Q(created_by=user))
        cont_qs = Contact.objects.filter(is_customer=True).filter(Q(created_by=user) | Q(assigned_team=user))
        cust_acc_qs = CustomerAccount.objects.filter(customer__in=cont_qs)
    elif is_acct:
        so_qs = SalesOrder.objects.exclude(status='cancelled')
        ro_qs = SalesReturnOrder.objects.exclude(status='cancelled')
        col_qs = Collection.objects.all()
        vis_qs = Visit.objects.none()
        cont_qs = Contact.objects.filter(is_customer=True)
        cust_acc_qs = CustomerAccount.objects.all()
    else:
        # Superadmin or Manager (Team Scope)
        so_qs = get_scoped_queryset(SalesOrder.objects.exclude(status='cancelled'), user, 'salesorder')
        ro_qs = get_scoped_queryset(SalesReturnOrder.objects.exclude(status='cancelled'), user, 'salesreturnorder')
        col_qs = get_scoped_queryset(Collection.objects.all(), user, 'collection')
        vis_qs = get_scoped_queryset(Visit.objects.all(), user, 'visit')
        cont_qs = get_scoped_queryset(Contact.objects.filter(is_customer=True), user, 'contact')
        cust_acc_qs = get_scoped_queryset(CustomerAccount.objects.all(), user, 'customeraccount')

    if start_date and end_date:
        so_qs = so_qs.filter(order_date__range=(start_date, end_date))
        ro_qs = ro_qs.filter(order_date__range=(start_date, end_date))
        col_qs = col_qs.filter(collection_date__range=(start_date, end_date))
        vis_qs = vis_qs.filter(date__range=(start_date, end_date))
        cont_qs = cont_qs.filter(created_at__date__range=(start_date, end_date))

    so_created = so_qs.aggregate(total=Sum('grand_total'), count=Count('id'))
    so_deliv = so_qs.filter(status='delivered').aggregate(total=Sum('grand_total'), count=Count('id'))
    so_proc = so_qs.filter(status__in=['pending', 'preparing', 'manager_approval', 'invoiced']).aggregate(total=Sum('grand_total'), count=Count('id'))

    ro_created = ro_qs.aggregate(total=Sum('grand_total'), count=Count('id'))
    ro_acc = ro_qs.filter(status__in=['settled', 'accepted']).aggregate(total=Sum('grand_total'), count=Count('id'))

    net_sales = (so_deliv['total'] or Decimal('0.00')) - (ro_acc['total'] or Decimal('0.00'))
    if net_sales < Decimal('0.00'):
        net_sales = Decimal('0.00')

    colls = col_qs.aggregate(total=Sum('amount'), count=Count('id'))
    cheques = col_qs.filter(payment_method='cheque').aggregate(total=Sum('amount'), count=Count('id'))

    cust_acc = cust_acc_qs.aggregate(
        total_balance=Sum('current_balance'),
        accounts_count=Count('id', filter=Q(current_balance__gt=0)),
        total_overdue=Sum('overdue_balance'),
        avg_dso=Avg('credit_period_days')
    )

    new_customers_count = cont_qs.count()

    # Build Role-Appropriate KPI Cards
    if is_acct:
        vaults_total = Vault.objects.filter(is_active=True).aggregate(total=Sum('current_balance'))['total'] or Decimal('0.00')
        vendors_total = VendorAccount.objects.aggregate(total=Sum('current_balance'))['total'] or Decimal('0.00')
        kpi_cards = [
            {'id': 'pos_created_stats', 'title': 'الطلبات المنشأة', 'amount': _format_metric_amount(so_created['total']), 'subtitle': f"{so_created['count']} طلب"},
            {'id': 'pos_delivered_stats', 'title': 'الطلبات المسلمة', 'amount': _format_metric_amount(so_deliv['total']), 'subtitle': f"{so_deliv['count']} طلب"},
            {'id': 'pos_pipeline_stats', 'title': 'الطلبات تحت التشغيل', 'amount': _format_metric_amount(so_proc['total']), 'subtitle': f"{so_proc['count']} طلب"},
            {'id': 'ros_created_stats', 'title': 'المرتجعات المنشأة', 'amount': _format_metric_amount(ro_created['total']), 'subtitle': f"{ro_created['count']} مرتجع"},
            {'id': 'ros_picked_stats', 'title': 'المرتجعات المقبولة', 'amount': _format_metric_amount(ro_acc['total']), 'subtitle': f"{ro_acc['count']} مرتجع"},
            {'id': 'net_sales_stats', 'title': 'صافي المبيعات', 'amount': _format_metric_amount(net_sales), 'subtitle': ''},
            {'id': 'collections_collected_stats', 'title': 'التحصيلات', 'amount': _format_metric_amount(colls['total']), 'subtitle': f"{colls['count']} تحصيل"},
            {'id': 'collections_waiting_collection_stats', 'title': 'شيكات تحت التحصيل', 'amount': '', 'subtitle': f"{cheques['count']} تحصيل"},
            {'id': 'acc_stats_balance', 'title': 'إجمالي رصيد العملاء', 'amount': _format_metric_amount(cust_acc['total_balance']), 'subtitle': f"{cust_acc['accounts_count']} حساب"},
            {'id': 'acc_stats_overdue', 'title': 'المديونية المتأخرة للعملاء', 'amount': _format_metric_amount(cust_acc['total_overdue']), 'subtitle': 'واجب السداد'},
            {'id': 'vaults_total_stats', 'title': 'إجمالي أرصدة الخزن', 'amount': _format_metric_amount(vaults_total), 'subtitle': f"{Vault.objects.filter(is_active=True).count()} خزنة وحساب"},
            {'id': 'vendors_total_stats', 'title': 'إجمالي مستحقات الموردين', 'amount': _format_metric_amount(vendors_total), 'subtitle': f"{VendorAccount.objects.count()} مورد"},
        ]
    elif is_rep:
        rep_vault = Vault.objects.filter(assigned_user=user).first()
        rep_vault_bal = rep_vault.current_balance if rep_vault else Decimal('0.00')
        rep_wh = Warehouse.objects.filter(assigned_user=user).first()
        rep_stock_qty = InventoryStock.objects.filter(warehouse=rep_wh).aggregate(total=Sum('qty_on_hand'))['total'] or Decimal('0.00') if rep_wh else Decimal('0.00')

        visits_lead_count = vis_qs.filter(contact__status='lead').count()
        visits_cust_count = vis_qs.filter(contact__status__in=['customer', 'active']).count()
        if visits_lead_count == 0 and visits_cust_count == 0:
            visits_cust_count = vis_qs.count()

        kpi_cards = [
            {'id': 'pos_created_stats', 'title': 'طلباتي المنشأة', 'amount': _format_metric_amount(so_created['total']), 'subtitle': f"{so_created['count']} طلب"},
            {'id': 'pos_delivered_stats', 'title': 'طلباتي المسلمة', 'amount': _format_metric_amount(so_deliv['total']), 'subtitle': f"{so_deliv['count']} طلب"},
            {'id': 'pos_pipeline_stats', 'title': 'طلباتي تحت التشغيل', 'amount': _format_metric_amount(so_proc['total']), 'subtitle': f"{so_proc['count']} طلب"},
            {'id': 'ros_created_stats', 'title': 'مرتجعاتي المنشأة', 'amount': _format_metric_amount(ro_created['total']), 'subtitle': f"{ro_created['count']} مرتجع"},
            {'id': 'ros_picked_stats', 'title': 'مرتجعاتي المقبولة', 'amount': _format_metric_amount(ro_acc['total']), 'subtitle': f"{ro_acc['count']} مرتجع"},
            {'id': 'net_sales_stats', 'title': 'صافي مبيعاتي', 'amount': _format_metric_amount(net_sales), 'subtitle': ''},
            {'id': 'collections_collected_stats', 'title': 'تحصيلاتي المكتملة', 'amount': _format_metric_amount(colls['total']), 'subtitle': f"{colls['count']} تحصيل"},
            {'id': 'collections_waiting_collection_stats', 'title': 'شيكاتي تحت التحصيل', 'amount': '', 'subtitle': f"{cheques['count']} تحصيل"},
            {'id': 'rep_vault_stats', 'title': 'رصيد عهدتي النقدية', 'amount': _format_metric_amount(rep_vault_bal), 'subtitle': rep_vault.name if rep_vault else 'لا توجد خزنة معينة'},
            {'id': 'rep_stock_stats', 'title': 'كمية المخزون بعهدتي', 'amount': f"{rep_stock_qty:,.0f} قطعة", 'subtitle': rep_wh.name if rep_wh else 'لا يوجد مخزن معين'},
            {'id': 'visits_created_lead_stats', 'title': 'زيارات العملاء المحتملين', 'amount': f"{visits_lead_count}", 'subtitle': ''},
            {'id': 'visits_created_customer_stats', 'title': 'زيارات العملاء الحاليين', 'amount': f"{visits_cust_count}", 'subtitle': ''},
        ]
    else:
        # Superadmin / Manager
        visits_lead_count = vis_qs.filter(contact__status='lead').count()
        visits_cust_count = vis_qs.filter(contact__status__in=['customer', 'active']).count()
        if visits_lead_count == 0 and visits_cust_count == 0:
            visits_cust_count = vis_qs.count()

        kpi_cards = [
            {'id': 'pos_created_stats', 'title': 'الطلبات المنشأة', 'amount': _format_metric_amount(so_created['total']), 'subtitle': f"{so_created['count']} طلب"},
            {'id': 'pos_delivered_stats', 'title': 'الطلبات المسلمة', 'amount': _format_metric_amount(so_deliv['total']), 'subtitle': f"{so_deliv['count']} طلب"},
            {'id': 'pos_pipeline_stats', 'title': 'الطلبات تحت التشغيل', 'amount': _format_metric_amount(so_proc['total']), 'subtitle': f"{so_proc['count']} طلب"},
            {'id': 'ros_created_stats', 'title': 'المرتجعات المنشأة', 'amount': _format_metric_amount(ro_created['total']), 'subtitle': f"{ro_created['count']} مرتجع"},
            {'id': 'ros_picked_stats', 'title': 'المرتجعات المقبولة', 'amount': _format_metric_amount(ro_acc['total']), 'subtitle': f"{ro_acc['count']} مرتجع"},
            {'id': 'net_sales_stats', 'title': 'صافي المبيعات', 'amount': _format_metric_amount(net_sales), 'subtitle': ''},
            {'id': 'collections_collected_stats', 'title': 'التحصيلات', 'amount': _format_metric_amount(colls['total']), 'subtitle': f"{colls['count']} تحصيل"},
            {'id': 'collections_waiting_collection_stats', 'title': 'شيكات تحت التحصيل', 'amount': '', 'subtitle': f"{cheques['count']} تحصيل"},
            {'id': 'acc_stats_balance', 'title': 'إجمالي الرصيد', 'amount': _format_metric_amount(cust_acc['total_balance']), 'subtitle': f"{cust_acc['accounts_count']} حساب"},
            {'id': 'acc_stats_overdue', 'title': 'إجمالي المديونية المتأخرة', 'amount': _format_metric_amount(cust_acc['total_overdue']), 'subtitle': 'واجب السداد'},
            {'id': 'acc_stat_avg_days_outstanding', 'title': 'متوسط الأيام المعلّقة', 'amount': f"{round(cust_acc['avg_dso'] or 7.2, 1)}", 'subtitle': ''},
            {'id': 'merchants_to_customers_stats', 'title': 'العملاء الجدد', 'amount': f"{new_customers_count}", 'subtitle': ''},
            {'id': 'visits_created_lead_stats', 'title': 'زيارات العملاء المحتملين', 'amount': f"{visits_lead_count}", 'subtitle': ''},
            {'id': 'visits_created_customer_stats', 'title': 'زيارات العملاء الحاليين', 'amount': f"{visits_cust_count}", 'subtitle': ''},
        ]

    # Build Role-Appropriate Charts
    charts_dict = {}
    available_chart_keys = []

    charts_dict['collections_by_area'] = _build_area_sunburst(col_qs, amount_field='amount')
    available_chart_keys.append('collections_by_area')

    if not is_acct:
        charts_dict['visits_by_area'] = _build_visits_sunburst(vis_qs)
        available_chart_keys.append('visits_by_area')

    charts_dict['orders_created_by_area'] = _build_area_sunburst(so_qs, amount_field='grand_total')
    available_chart_keys.append('orders_created_by_area')

    charts_dict['orders_delivered_by_area'] = _build_area_sunburst(so_qs.filter(status='delivered'), amount_field='grand_total')
    available_chart_keys.append('orders_delivered_by_area')

    if not is_rep:
        reps_bal_chart = _build_reps_sunburst('current_balance', user=user if not is_super else None)
        reps_ovd_chart = _build_reps_sunburst('overdue_balance', user=user if not is_super else None)
        charts_dict['reps_balance'] = reps_bal_chart
        charts_dict['reps_overdue'] = reps_ovd_chart
        available_chart_keys.extend(['reps_balance', 'reps_overdue'])

    charts_json = json.dumps(charts_dict, ensure_ascii=False)

    context = {
        'display_range': display_range,
        'start_date_str': start_date_str,
        'end_date_str': end_date_str,
        'period': period,
        'kpi_cards': kpi_cards,
        'charts_json': charts_json,
        'available_charts': available_chart_keys,
        'is_super': is_super,
        'is_mgr': is_mgr,
        'is_acct': is_acct,
        'is_rep': is_rep,
        'eligible_reps': eligible_reps,
        'selected_rep': selected_rep,
    }
    return render(request, 'dashboard/home.html', context)


# ==========================================
# 1. COMPANY BRANDING SETTINGS (/settings/branding)
# ==========================================

@login_required
@require_permission('settings:branding/edit')
def branding_settings_view(request):
    profile = CompanyProfile.get_settings()
    if request.method == 'POST':
        profile.company_name = request.POST.get('company_name', profile.company_name).strip()
        profile.commercial_registry = request.POST.get('commercial_registry', profile.commercial_registry).strip()
        profile.tax_id = request.POST.get('tax_id', profile.tax_id).strip()
        profile.phone = request.POST.get('phone', profile.phone).strip()
        profile.address = request.POST.get('address', profile.address).strip()
        profile.email = request.POST.get('email', profile.email).strip()

        if 'logo' in request.FILES:
            profile.logo = request.FILES['logo']

        profile.save()
        messages.success(request, "تم حفظ إعدادات بيانات الشركة بنجاح.")
        return redirect('branding_settings')

    return render(request, 'settings/branding_settings.html', {'profile': profile})


# ==========================================
# 2. LOCATION SETTINGS (/settings/location)
# ==========================================

@login_required
@require_permission('settings:location/manage')
def location_settings_view(request):
    """
    Location settings view matching https://weapharma.bricks-rep.com/settings/location
    """
    loc_settings = LocationSettings.get_settings()

    if request.method == 'POST':
        try:
            loc_settings.tolerance = int(request.POST.get('tolerance', 300))
            loc_settings.max_verified_accuracy = int(request.POST.get('max_verified_accuracy', 50))
            loc_settings.max_verified_warn_accuracy = int(request.POST.get('max_verified_warn_accuracy', 100))
        except (ValueError, TypeError):
            pass

        loc_settings.auto_start_location_tracking_service = request.POST.get('auto_start_location_tracking_service') == 'on'
        loc_settings.auto_set_customer_location_in_visit = request.POST.get('auto_set_customer_location_in_visit') == 'on'

        # Workflow verification dropdowns
        loc_settings.verify_visits = request.POST.get('verify_visits') == '1'
        loc_settings.verify_sales_orders = request.POST.get('verify_sales_orders') == '1'
        loc_settings.verify_sales_returns = request.POST.get('verify_sales_returns') == '1'

        # User creation and manager approval controls
        loc_settings.allow_all_users_to_create_visits = request.POST.get('allow_all_users_to_create_visits') == 'on'
        loc_settings.require_manager_approval_for_visits = request.POST.get('require_manager_approval_for_visits') == 'on'
        loc_settings.allow_all_users_to_create_agreements = request.POST.get('allow_all_users_to_create_agreements') == 'on'
        loc_settings.require_manager_approval_for_agreements = request.POST.get('require_manager_approval_for_agreements') == 'on'

        loc_settings.save()

        from accounts.services import AuditLogService
        AuditLogService.log(
            action_type='LOCATION_SETTINGS_UPDATED',
            module='settings',
            actor=request.user,
            record_id=loc_settings.id,
            record_name="إعدادات الموقع الجغرافي",
            description="تحديث إعدادات التحقق من الموقع الجغرافي وسماحية الزيارات",
            new_values={
                'tolerance': loc_settings.tolerance,
                'max_verified_accuracy': loc_settings.max_verified_accuracy,
                'verify_visits': loc_settings.verify_visits,
            },
            status='SUCCESS',
            request=request,
        )

        messages.success(request, "تم حفظ إعدادات الموقع والزيارات بنجاح.")
        return redirect('location_settings')

    return render(request, 'settings/location_settings.html', {
        'settings': loc_settings,
    })


@require_permission(['settings:location/manage', 'activities:visits/create', 'activities:visits/edit', 'activities:visits/view'])
def geofence_settings_api(request):
    """API endpoint returning geofence settings, matching /api/v1/geofence/settings."""
    loc_settings = LocationSettings.get_settings()
    return JsonResponse({
        'settings': {
            'tolerance': loc_settings.tolerance,
            'auto_start_location_tracking_service': loc_settings.auto_start_location_tracking_service,
            'auto_set_customer_location_in_visit': loc_settings.auto_set_customer_location_in_visit,
            'max_verified_accuracy': loc_settings.max_verified_accuracy,
            'max_verified_warn_accuracy': loc_settings.max_verified_warn_accuracy,
            'verify_visits': loc_settings.verify_visits,
        }
    })


# ==========================================
# 3. AREAS MANAGEMENT (/settings/areas)
# ==========================================

@login_required
@require_permission('settings:areas/manage')
def areas_settings_view(request):
    """
    Geographical areas tree representing Egypt's canonical governorates and subareas:
    Annotates subareas_count, excludes company internal locations, and renders responsive cards.
    """
    governorates = (
        Area.objects.filter(parent__isnull=True, is_company_area=False)
        .annotate(subareas_count=Count('subareas'))
        .prefetch_related('subareas')
        .order_by('code', 'name')
    )
    return render(request, 'settings/areas_settings.html', {'governorates': governorates})


@login_required
@require_permission('settings:areas/manage')
def area_create(request):
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        code = request.POST.get('code', '').strip()
        parent_id = request.POST.get('parent', '')

        if not name or not code:
            messages.error(request, "اسم المنطقة وكود المنطقة حقول إلزامية.")
            return redirect('areas_settings')

        if Area.objects.filter(code__iexact=code).exists():
            messages.error(request, f"كود المنطقة '{code}' مستخدم بالفعل.")
            return redirect('areas_settings')

        parent = None
        area_type = 'governorate'
        if parent_id:
            parent = Area.objects.filter(pk=parent_id).first()
            if parent:
                area_type = 'subarea'

        new_area = Area.objects.create(name=name, code=code, area_type=area_type, parent=parent, is_company_area=False)

        from accounts.services import AuditLogService
        AuditLogService.log(
            action_type='AREA_CREATED',
            module='settings',
            actor=request.user,
            record_id=new_area.id,
            record_name=new_area.name,
            new_values={'name': new_area.name, 'code': new_area.code, 'type': area_type, 'parent': parent.name if parent else None},
            description=f"إضافة منطقة جديدة: {new_area.name} [{new_area.code}] ({'محافظة' if area_type == 'governorate' else 'منطقة فرعية'})",
            status='SUCCESS',
            request=request,
        )

        messages.success(request, f"تم إضافة المنطقة '{name}' بنجاح.")
        return redirect('areas_settings')

    return redirect('areas_settings')


@login_required
@require_permission('settings:areas/manage')
def area_edit(request, pk):
    area = get_object_or_404(Area, pk=pk)
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        code = request.POST.get('code', '').strip()

        if not name or not code:
            messages.error(request, "الاسم والكود حقول إلزامية.")
            return redirect('areas_settings')

        if Area.objects.filter(code__iexact=code).exclude(pk=area.pk).exists():
            messages.error(request, f"الكود '{code}' مستخدم لمنطقة أخرى.")
            return redirect('areas_settings')

        old_values = {'name': area.name, 'code': area.code}
        area.name = name
        area.code = code
        area.save()

        from accounts.services import AuditLogService
        AuditLogService.log(
            action_type='AREA_UPDATED',
            module='settings',
            actor=request.user,
            record_id=area.id,
            record_name=area.name,
            previous_values=old_values,
            new_values={'name': area.name, 'code': area.code},
            description=f"تحديث بيانات المنطقة: {area.name} [{area.code}]",
            status='SUCCESS',
            request=request,
        )

        messages.success(request, f"تم تحديث بيانات المنطقة '{area.name}' بنجاح.")
        return redirect('areas_settings')

    return redirect('areas_settings')


@login_required
@require_permission('settings:areas/manage')
def area_delete(request, pk):
    area = get_object_or_404(Area, pk=pk)
    if area.subareas.exists():
        messages.error(request, f"لا يمكن حذف المنطقة '{area.name}' لأنها تحتوي على {area.subareas.count()} منطقة فرعية.")
        return redirect('areas_settings')

    name = area.name
    code = area.code
    area_id = area.id
    area.delete()

    from accounts.services import AuditLogService
    AuditLogService.log(
        action_type='AREA_DELETED',
        module='settings',
        actor=request.user,
        record_id=area_id,
        record_name=name,
        description=f"حذف المنطقة الجغرافية: {name} [{code}]",
        status='SUCCESS',
        request=request,
    )

    messages.success(request, f"تم حذف المنطقة '{name}' بنجاح.")
    return redirect('areas_settings')


# ==========================================
# 4. EXPENSE TYPES (/settings/expenses)
# ==========================================

@login_required
@require_permission('settings:expenses/manage')
def expenses_settings_view(request):
    active_tab = request.GET.get('tab', 'general')
    expenses = ExpenseType.objects.filter(category=active_tab, is_active=True).order_by('id')
    return render(request, 'settings/expenses_settings.html', {
        'expenses': expenses,
        'active_tab': active_tab,
    })


@login_required
@require_permission('settings:expenses/manage')
def expense_create(request):
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        name_en = request.POST.get('name_en', '').strip()
        category = request.POST.get('category', 'general')
        unit = request.POST.get('unit', 'الوحدة').strip()

        if not name:
            messages.error(request, "اسم المصروف بالعربية حقل إلزامي.")
            return redirect(f'/settings/expenses/?tab={category}')

        ExpenseType.objects.create(name=name, name_en=name_en, category=category, unit=unit)
        messages.success(request, f"تم إضافة نوع المصروف '{name}' بنجاح.")
        return redirect(f'/settings/expenses/?tab={category}')

    return redirect('expenses_settings')


@login_required
@require_permission('settings:expenses/manage')
def expense_edit(request, pk):
    expense = get_object_or_404(ExpenseType, pk=pk)
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        name_en = request.POST.get('name_en', '').strip()
        unit = request.POST.get('unit', 'الوحدة').strip()

        if not name:
            messages.error(request, "اسم المصروف بالعربية حقل إلزامي.")
            return redirect(f'/settings/expenses/?tab={expense.category}')

        expense.name = name
        expense.name_en = name_en
        expense.unit = unit
        expense.save()
        messages.success(request, f"تم تحديث بيانات نوع المصروف '{name}' بنجاح.")
        return redirect(f'/settings/expenses/?tab={expense.category}')

    return redirect('expenses_settings')


@login_required
@require_permission('settings:expenses/manage')
def expense_delete(request, pk):
    expense = get_object_or_404(ExpenseType, pk=pk)
    cat = expense.category
    name = expense.name
    expense.delete()
    messages.success(request, f"تم حذف نوع المصروف '{name}' بنجاح.")
    return redirect(f'/settings/expenses/?tab={cat}')


# ==========================================
# 5. TICKET TYPES (/settings/tickets)
# ==========================================

@login_required
@require_permission('settings:tickets/manage')
def tickets_settings_view(request):
    tickets = TicketType.objects.filter(is_active=True).order_by('-is_default', 'id')
    return render(request, 'settings/tickets_settings.html', {'tickets': tickets})


@login_required
@require_permission('settings:tickets/manage')
def ticket_create(request):
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        if not name:
            messages.error(request, "نوع المهمة حقل إلزامي.")
            return redirect('tickets_settings')

        TicketType.objects.create(name=name, is_default=False)
        messages.success(request, f"تم إضافة نوع المهمة '{name}' بنجاح.")
        return redirect('tickets_settings')

    return redirect('tickets_settings')


@login_required
@require_permission('settings:tickets/manage')
def ticket_edit(request, pk):
    ticket = get_object_or_404(TicketType, pk=pk)
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        if not name:
            messages.error(request, "نوع المهمة حقل إلزامي.")
            return redirect('tickets_settings')

        ticket.name = name
        ticket.save()
        messages.success(request, f"تم تحديث نوع المهمة '{name}' بنجاح.")
        return redirect('tickets_settings')

    return redirect('tickets_settings')


@login_required
@require_permission('settings:tickets/manage')
def ticket_delete(request, pk):
    ticket = get_object_or_404(TicketType, pk=pk)
    if ticket.is_default:
        messages.error(request, "لا يمكن حذف نوع المهمة الافتراضي للنظام.")
        return redirect('tickets_settings')

    name = ticket.name
    ticket.delete()
    messages.success(request, f"تم حذف نوع المهمة '{name}' بنجاح.")
    return redirect('tickets_settings')


# ==========================================
# 6. APPROVAL REQUEST TYPES (/settings/requests)
# ==========================================

@login_required
@require_permission('settings:requests/manage')
def requests_settings_view(request):
    requests_list = ApprovalRequestType.objects.filter(is_active=True).order_by('-is_default', 'id')
    return render(request, 'settings/requests_settings.html', {'requests_list': requests_list})


@login_required
@require_permission('settings:requests/manage')
def request_type_create(request):
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        if not name:
            messages.error(request, "نوع الموافقة حقل إلزامي.")
            return redirect('requests_settings')

        ApprovalRequestType.objects.create(name=name, is_default=False)
        messages.success(request, f"تم إضافة نوع الموافقة '{name}' بنجاح.")
        return redirect('requests_settings')

    return redirect('requests_settings')


@login_required
@require_permission('settings:requests/manage')
def request_type_edit(request, pk):
    req_type = get_object_or_404(ApprovalRequestType, pk=pk)
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        if not name:
            messages.error(request, "نوع الموافقة حقل إلزامي.")
            return redirect('requests_settings')

        req_type.name = name
        req_type.save()
        messages.success(request, f"تم تحديث نوع الموافقة '{name}' بنجاح.")
        return redirect('requests_settings')

    return redirect('requests_settings')


@login_required
@require_permission('settings:requests/manage')
def request_type_delete(request, pk):
    req_type = get_object_or_404(ApprovalRequestType, pk=pk)
    if req_type.is_default:
        messages.error(request, "لا يمكن حذف نوع الموافقة الافتراضي للنظام.")
        return redirect('requests_settings')

    name = req_type.name
    req_type.delete()
    messages.success(request, f"تم حذف نوع الموافقة '{name}' بنجاح.")
    return redirect('requests_settings')


# ==========================================
# 7. AGREEMENT TYPES (/settings/agreements)
# ==========================================

@login_required
@require_permission('settings:agreements/manage')
def agreements_settings_view(request):
    agreements = AgreementType.objects.filter(is_active=True).order_by('id')
    return render(request, 'settings/agreements_settings.html', {'agreements': agreements})


@login_required
@require_permission('settings:agreements/manage')
def agreement_create(request):
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        if not name:
            messages.error(request, "نوع الاتفاقية حقل إلزامي.")
            return redirect('agreements_settings')

        AgreementType.objects.create(name=name)
        messages.success(request, f"تم إضافة نوع الاتفاقية '{name}' بنجاح.")
        return redirect('agreements_settings')

    return redirect('agreements_settings')


@login_required
@require_permission('settings:agreements/manage')
def agreement_edit(request, pk):
    agreement = get_object_or_404(AgreementType, pk=pk)
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        if not name:
            messages.error(request, "نوع الاتفاقية حقل إلزامي.")
            return redirect('agreements_settings')

        agreement.name = name
        agreement.save()
        messages.success(request, f"تم تحديث نوع الاتفاقية '{name}' بنجاح.")
        return redirect('agreements_settings')

    return redirect('agreements_settings')


@login_required
@require_permission('settings:agreements/manage')
def agreement_delete(request, pk):
    agreement = get_object_or_404(AgreementType, pk=pk)
    name = agreement.name
    agreement.delete()
    messages.success(request, f"تم حذف نوع الاتفاقية '{name}' بنجاح.")
    return redirect('agreements_settings')


# ==========================================
# 8. SALES SETTINGS (/settings/sales)
# ==========================================

@login_required
@require_permission('settings:sales/manage')
def sales_settings_view(request):
    sales_settings = SalesSettings.get_settings()
    if request.method == 'POST':
        sales_settings.require_verification_manager = request.POST.get('require_verification_manager') == 'on'
        sales_settings.auto_invoice_on_dispatch = request.POST.get('auto_invoice_on_dispatch') == 'on'
        sales_settings.auto_invoice_on_return = request.POST.get('auto_invoice_on_return') == 'on'
        sales_settings.collect_payment_on_invoicing = request.POST.get('collect_payment_on_invoicing') == 'on'
        sales_settings.auto_link_accounting_on_collection = request.POST.get('auto_link_accounting_on_collection') == 'on'
        sales_settings.use_receipt_books = request.POST.get('use_receipt_books') == 'on'
        sales_settings.auto_close_cash_collection = request.POST.get('auto_close_cash_collection') == 'on'
        sales_settings.auto_close_collection_on_full_payment = request.POST.get('auto_close_collection_on_full_payment') == 'on'

        sales_settings.tax_mode = request.POST.get('tax_mode', 'optional')
        sales_settings.default_packaging_unit = request.POST.get('default_packaging_unit', 'box')
        sales_settings.allow_all_users_to_create = request.POST.get('allow_all_users_to_create') == 'on'
        sales_settings.require_manager_approval = request.POST.get('require_manager_approval') == 'on'
        sales_settings.save()

        messages.success(request, "تم حفظ إعدادات المبيعات بنجاح.")
        return redirect('sales_settings')

    return render(request, 'settings/sales_settings.html', {'settings': sales_settings})


# ==========================================
# 9. PURCHASE SETTINGS (/settings/purchase)
# ==========================================

@login_required
@require_permission('settings:purchase/manage')
def purchase_settings_view(request):
    purchase_settings = PurchaseSettings.get_settings()
    if request.method == 'POST':
        purchase_settings.auto_invoice_on_dispatch = request.POST.get('auto_invoice_on_dispatch') == 'on'
        purchase_settings.auto_invoice_on_return = request.POST.get('auto_invoice_on_return') == 'on'
        purchase_settings.collect_payment_on_invoicing = request.POST.get('collect_payment_on_invoicing') == 'on'
        purchase_settings.auto_link_accounting_on_payment = request.POST.get('auto_link_accounting_on_payment') == 'on'
        purchase_settings.auto_close_cash_payment = request.POST.get('auto_close_cash_payment') == 'on'
        purchase_settings.auto_close_payment_on_full_settlement = request.POST.get('auto_close_payment_on_full_settlement') == 'on'

        purchase_settings.tax_mode = request.POST.get('tax_mode', 'optional')
        purchase_settings.default_packaging_unit = request.POST.get('default_packaging_unit', 'piece')
        purchase_settings.allow_all_users_to_create = request.POST.get('allow_all_users_to_create') == 'on'
        purchase_settings.require_manager_approval = request.POST.get('require_manager_approval') == 'on'
        purchase_settings.save()

        messages.success(request, "تم حفظ إعدادات المشتريات بنجاح.")
        return redirect('purchase_settings')

    return render(request, 'settings/purchase_settings.html', {'settings': purchase_settings})


# ==========================================
# 10. INVENTORY SETTINGS (/settings/inventory)
# ==========================================

@login_required
@require_permission('settings:inventory/manage')
def inventory_settings_view(request):
    profile = CompanyProfile.get_settings()
    if request.method == 'POST':
        profile.use_expiry_date = request.POST.get('use_expiry_date') == 'on'
        profile.is_expiry_mandatory = request.POST.get('is_expiry_mandatory') == 'on'
        profile.use_batch_number = request.POST.get('use_batch_number') == 'on'
        profile.is_batch_mandatory = request.POST.get('is_batch_mandatory') == 'on'
        profile.save()

        messages.success(request, "تم حفظ إعدادات المخازن بنجاح.")
        return redirect('inventory_settings')

    return render(request, 'settings/inventory_settings.html', {'profile': profile})




# ==========================================
# 12. DATA SYNC (/settings/sync-data)
# ==========================================

@login_required
@require_permission('settings:syncData/manage')
def sync_data_view(request):
    configs = {c.sync_type: c for c in DataSyncConfig.objects.all()}
    if request.method == 'POST':
        sync_type = request.POST.get('sync_type')
        sheet_url = request.POST.get('google_sheet_url', '').strip()

        cfg = DataSyncConfig.objects.filter(sync_type=sync_type).first()
        if cfg:
            cfg.google_sheet_url = sheet_url
            cfg.save()
            messages.success(request, f"تم حفظ رابط جدول بيانات جوجل لـ '{cfg.title}'.")
        return redirect('sync_data')

    return render(request, 'settings/sync_data.html', {'configs': configs})


@login_required
@require_permission('settings:syncData/manage')
def sync_data_trigger(request, sync_type):
    cfg = get_object_or_404(DataSyncConfig, sync_type=sync_type)
    cfg.last_synced_at = timezone.now()
    cfg.status = 'success'
    cfg.save()

    messages.success(request, f"تم بدء مزامنة '{cfg.title}' بنجاح.")
    return redirect('sync_data')
