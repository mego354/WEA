import datetime
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.utils import timezone

from accounts.permissions import require_permission, get_scoped_queryset
from accounts.models import User
from master_data.models import Area
from .services import (
    parse_date_range,
    get_ar_aging_report_data,
    get_trial_balance_report_data,
    get_agreements_roi_report_data,
    get_customer_360_report_data,
    get_delivery_stock_availability_report_data,
    get_net_sales_profitability_report_data,
    get_item_purchases_report_data,
    get_item_sales_by_customer_report_data,
    export_to_excel_response,
)


REPORTS_METADATA = [
    {'code': 'ar_aging', 'title': 'أعمار الديون (AR Aging)', 'url_name': 'report_ar_aging', 'category': 'financial', 'perm': 'reports:financial/view'},
    {'code': 'trial_balance', 'title': 'ميزان المراجعة للعملاء (Trial Balance)', 'url_name': 'report_trial_balance', 'category': 'financial', 'perm': 'reports:financial/view'},
    {'code': 'net_sales', 'title': 'صافي مبيعات الأصناف وربحية المنتجات', 'url_name': 'report_net_sales', 'category': 'sales', 'perm': 'reports:sales/view'},
    {'code': 'customer_360', 'title': 'ملخص العميل الشامل (Customer 360)', 'url_name': 'report_customer_360', 'category': 'sales', 'perm': 'reports:sales/view'},
    {'code': 'item_sales_by_customer', 'title': 'مبيعات الأصناف حسب العملاء', 'url_name': 'report_item_sales_by_customer', 'category': 'sales', 'perm': 'reports:sales/view'},
    {'code': 'delivery_stock', 'title': 'متابعة التسليمات وتوفر المخزون', 'url_name': 'report_delivery_stock', 'category': 'inventory', 'perm': 'reports:inventory/view'},
    {'code': 'item_purchases', 'title': 'مشتريات الأصناف والموردين', 'url_name': 'report_item_purchases', 'category': 'inventory', 'perm': 'reports:inventory/view'},
    {'code': 'agreements_roi', 'title': 'تحقيق الاتفاقيات وعائد الاستثمار (ROI)', 'url_name': 'report_agreements_roi', 'category': 'activities', 'perm': 'reports:activities/view'},
]


@login_required
@require_permission('reports:hub/view')
def reports_hub(request):
    """
    Main Reports Hub listing the 13 standalone business and financial reports grouped into:
    - Financial & Accounting
    - Sales & Commercial
    - Supply Chain & Logistics
    - Medical Activities & Promotions
    """
    return render(request, 'reports/reports_hub.html', {'reports': REPORTS_METADATA})


# ==============================================================================
# REPORT 1: AR AGING (أعمار الديون)
# ==============================================================================

@login_required
@require_permission('reports:financial/view')
def report_ar_aging(request):
    area_id = request.GET.get('area')
    brick_id = request.GET.get('brick')
    rep_id = request.GET.get('rep')
    overdue_only = request.GET.get('overdue_only') == '1'

    filters = {
        'area_id': area_id,
        'brick_id': brick_id,
        'rep_id': rep_id,
        'overdue_only': overdue_only,
    }
    data = get_ar_aging_report_data(request.user, filters)

    areas = get_scoped_queryset(Area.objects.filter(parent__isnull=True), request.user)
    reps = get_scoped_queryset(User.objects.filter(is_active=True), request.user).filter(role__is_sales_team=True)

    context = {
        'rows': data['rows'],
        'summary': data['summary'],
        'areas': areas,
        'reps': reps,
        'selected_area': int(area_id) if area_id and area_id.isdigit() else '',
        'selected_rep': int(rep_id) if rep_id and rep_id.isdigit() else '',
        'overdue_only': overdue_only,
    }
    return render(request, 'reports/report_ar_aging.html', context)


@login_required
@require_permission('reports:financial/export')
def report_ar_aging_export(request):
    data = get_ar_aging_report_data(request.user, request.GET)
    headers = [
        "كود العميل", "اسم العميل", "التصنيف", "المنطقة / المربع", "المندوب",
        "الحد الائتماني", "إجمالي المديونية", "إجمالي المتأخرات", "متأخر (1-30 يوم)",
        "متأخر (31-60 يوم)", "متأخر (61-90 يوم)", "متأخر (91-120 يوم)", "متأخر (>120 يوم)"
    ]
    rows = [
        [
            r['code'], r['customer_name'], r['category'], r['brick'], r['rep_name'],
            r['credit_limit'], r['current_balance'], r['overdue_balance'],
            r['bucket_1_30'], r['bucket_31_60'], r['bucket_61_90'], r['bucket_91_120'], r['bucket_over_120']
        ]
        for r in data['rows']
    ]
    summary_row = [
        "الإجمالي", "", "", "", "", "",
        data['summary']['total_receivables'], data['summary']['total_overdue'],
        data['summary']['bucket_1_30'], data['summary']['bucket_31_60'],
        data['summary']['bucket_61_90'], data['summary']['bucket_91_120'], data['summary']['bucket_over_120']
    ]
    return export_to_excel_response("AR_Aging_Report", "أعمار الديون", headers, rows, summary_row)


@login_required
@require_permission('reports:financial/view')
def report_ar_aging_print(request):
    data = get_ar_aging_report_data(request.user, request.GET)
    return render(request, 'reports/report_ar_aging_print.html', {'rows': data['rows'], 'summary': data['summary']})


# ==============================================================================
# REPORT 2: CUSTOMERS TRIAL BALANCE (ميزان المراجعة للعملاء)
# ==============================================================================

@login_required
@require_permission('reports:financial/view')
def report_trial_balance(request):
    period = request.GET.get('period', 'this_month')
    start_str = request.GET.get('start_date')
    end_str = request.GET.get('end_date')
    area_id = request.GET.get('area')

    start_date, end_date, _, _, period_label = parse_date_range(period, start_str, end_str)
    data = get_trial_balance_report_data(request.user, start_date, end_date, {'area_id': area_id})

    areas = get_scoped_queryset(Area.objects.filter(parent__isnull=True), request.user)

    context = {
        'rows': data['rows'],
        'summary': data['summary'],
        'period': period,
        'period_label': period_label,
        'start_date': start_date.isoformat(),
        'end_date': end_date.isoformat(),
        'areas': areas,
        'selected_area': int(area_id) if area_id and area_id.isdigit() else '',
    }
    return render(request, 'reports/report_trial_balance.html', context)


@login_required
@require_permission('reports:financial/export')
def report_trial_balance_export(request):
    start_date, end_date, _, _, _ = parse_date_range(request.GET.get('period'), request.GET.get('start_date'), request.GET.get('end_date'))
    data = get_trial_balance_report_data(request.user, start_date, end_date, request.GET)

    headers = ["كود العميل", "اسم العميل", "التصنيف", "التخصص", "المنطقة", "الرصيد الافتتاحي (ج.م)", "إجمالي المدين / مبيعات (ج.م)", "إجمالي الدائن / تحصيلات (ج.م)", "رصيد الإقفال الحالي (ج.م)"]
    rows = [
        [r['code'], r['name'], r['category'], r['specialty'], r['brick'], r['opening_balance'], r['debit'], r['credit'], r['closing_balance']]
        for r in data['rows']
    ]
    summary_row = [
        "الإجمالي العام", "", "", "", "",
        data['summary']['total_opening'], data['summary']['total_debit'], data['summary']['total_credit'], data['summary']['total_closing']
    ]
    return export_to_excel_response(f"Trial_Balance_{start_date}_{end_date}", "ميزان المراجعة للعملاء", headers, rows, summary_row)


@login_required
@require_permission('reports:financial/view')
def report_trial_balance_print(request):
    start_date, end_date, _, _, _ = parse_date_range(request.GET.get('period'), request.GET.get('start_date'), request.GET.get('end_date'))
    data = get_trial_balance_report_data(request.user, start_date, end_date, request.GET)
    return render(request, 'reports/report_trial_balance_print.html', {'rows': data['rows'], 'summary': data['summary'], 'start_date': start_date, 'end_date': end_date})


# ==============================================================================
# REPORT 3: AGREEMENTS ACHIEVEMENT & ROI (تحقيق الاتفاقيات وعائد الاستثمار)
# ==============================================================================

@login_required
@require_permission('reports:activities/view')
def report_agreements_roi(request):
    period = request.GET.get('period', 'year')
    start_str = request.GET.get('start_date')
    end_str = request.GET.get('end_date')

    start_date, end_date, _, _, period_label = parse_date_range(period, start_str, end_str)
    data = get_agreements_roi_report_data(request.user, start_date, end_date)

    context = {
        'rows': data['rows'],
        'summary': data['summary'],
        'period': period,
        'period_label': period_label,
        'start_date': start_date.isoformat(),
        'end_date': end_date.isoformat(),
    }
    return render(request, 'reports/report_agreements_roi.html', context)


@login_required
@require_permission('reports:activities/export')
def report_agreements_roi_export(request):
    start_date, end_date, _, _, _ = parse_date_range(request.GET.get('period', 'year'), request.GET.get('start_date'), request.GET.get('end_date'))
    data = get_agreements_roi_report_data(request.user, start_date, end_date)

    headers = ["رقم الاتفاقية", "العنوان", "العميل", "النوع", "المندوب", "تاريخ الاتفاقية", "الميزانية المعتمدة (ج.م)", "المبيعات المحققة (ج.م)", "نسبة التحقيق %", "عائد الاستثمار ROI %", "الحالة"]
    rows = [
        [r['serial_num'], r['title'], r['customer_name'], r['type_name'], r['rep_name'], r['date'], r['budget'], r['actual_sales'], f"{r['ach_pct']}%", f"{r['roi_pct']}%", r['status']]
        for r in data['rows']
    ]
    summary_row = ["الإجمالي", "", "", "", "", "", data['summary']['total_budget'], data['summary']['total_actual_sales'], f"{data['summary']['overall_ach_pct']}%", f"{data['summary']['overall_roi_pct']}%", ""]
    return export_to_excel_response(f"Agreements_ROI_{start_date}_{end_date}", "تحقيق الاتفاقيات", headers, rows, summary_row)


# ==============================================================================
# REPORT 5: CUSTOMER 360 (ملخص العملاء 360)
# ==============================================================================

@login_required
@require_permission('reports:sales/view')
def report_customer_360(request):
    period = request.GET.get('period', 'this_month')
    start_date, end_date, _, _, period_label = parse_date_range(period, request.GET.get('start_date'), request.GET.get('end_date'))
    area_id = request.GET.get('area')

    data = get_customer_360_report_data(request.user, start_date, end_date, {'area_id': area_id})
    areas = get_scoped_queryset(Area.objects.filter(parent__isnull=True), request.user)

    context = {
        'rows': data['rows'],
        'summary': data['summary'],
        'period': period,
        'period_label': period_label,
        'start_date': start_date.isoformat(),
        'end_date': end_date.isoformat(),
        'areas': areas,
        'selected_area': int(area_id) if area_id and area_id.isdigit() else '',
    }
    return render(request, 'reports/report_customer_360.html', context)


@login_required
@require_permission('reports:sales/export')
def report_customer_360_export(request):
    start_date, end_date, _, _, _ = parse_date_range(request.GET.get('period'), request.GET.get('start_date'), request.GET.get('end_date'))
    data = get_customer_360_report_data(request.user, start_date, end_date, request.GET)

    headers = [
        "كود العميل", "الاسم", "نوع الحساب", "التصنيف", "التخصص", "المحافظة", "المربع",
        "المندوب", "الزيارات", "أوامر البيع", "إجمالي المبيعات", "صافي المبيعات",
        "المرتجعات", "التحصيلات", "الرصيد المدين", "الديون المتأخرة", "الحد الائتماني", "نسبة الاستهلاك %"
    ]
    rows = [
        [
            r['code'], r['name'], r['account_type'], r['category'], r['specialty'], r['governorate'], r['brick'],
            r['rep_name'], r['visits_cnt'], r['orders_cnt'], r['gross_sales'], r['net_sales'],
            r['returns_total'], r['collections_total'], r['balance'], r['overdue'], r['credit_limit'], f"{r['util_pct']}%"
        ]
        for r in data['rows']
    ]
    summary_row = [
        "الإجمالي", "", "", "", "", "", "", "", "", "", "",
        data['summary']['total_net_sales'], "", data['summary']['total_collections'], data['summary']['total_debt'], "", "", ""
    ]
    return export_to_excel_response(f"Customer_360_{start_date}_{end_date}", "ملخص العملاء 360", headers, rows, summary_row)


# ==============================================================================
# REPORT 6: BUNDLES & PROMOTIONS (أداء العروض والخصومات)
# ==============================================================================

@login_required
@require_permission('reports:inventory/view')
def report_delivery_stock(request):
    from inventory.models import Warehouse
    warehouse_id = request.GET.get('warehouse_id')
    data = get_delivery_stock_availability_report_data(request.user, filters={'warehouse_id': warehouse_id})
    warehouses = get_scoped_queryset(Warehouse.objects.filter(is_active=True), request.user, 'warehouse').order_by('name')
    return render(request, 'reports/report_delivery_stock.html', {
        'rows': data['rows'],
        'summary': data['summary'],
        'warehouses': warehouses,
        'selected_warehouse': warehouse_id,
    })


@login_required
@require_permission('reports:inventory/export')
def report_delivery_stock_export(request):
    warehouse_id = request.GET.get('warehouse_id')
    data = get_delivery_stock_availability_report_data(request.user, filters={'warehouse_id': warehouse_id})
    headers = ["كود الصنف", "اسم الصنف", "الكمية المطلوبة (طلبيات معلقة)", "المتاح بالمخزن (On-Hand)", "المحجوز", "الرصيد الحر المتاح", "حالة التوفر", "الطلبيات المتأثرة"]
    rows = [
        [r['code'], r['name'], r['ordered_qty'], r['on_hand'], r['reserved'], r['available'], r['status'], r['impacted_orders']]
        for r in data['rows']
    ]
    return export_to_excel_response("Stock_Availability_Delivery", "توفر المخزون والتسليمات", headers, rows)


# ==============================================================================
# REPORT 9: NET ITEM SALES & PROFITABILITY (صافي المبيعات وربحية الأصناف)
# ==============================================================================

@login_required
@require_permission('reports:sales/view')
def report_net_sales(request):
    period = request.GET.get('period', 'this_month')
    start_date, end_date, _, _, period_label = parse_date_range(period, request.GET.get('start_date'), request.GET.get('end_date'))
    data = get_net_sales_profitability_report_data(request.user, start_date, end_date)

    context = {
        'rows': data['rows'],
        'summary': data['summary'],
        'period': period,
        'period_label': period_label,
        'start_date': start_date.isoformat(),
        'end_date': end_date.isoformat(),
    }
    return render(request, 'reports/report_net_sales.html', context)


@login_required
@require_permission('reports:sales/export')
def report_net_sales_export(request):
    start_date, end_date, _, _, _ = parse_date_range(request.GET.get('period'), request.GET.get('start_date'), request.GET.get('end_date'))
    data = get_net_sales_profitability_report_data(request.user, start_date, end_date)

    headers = [
        "كود الصنف", "اسم الصنف", "الكمية المسلمة", "المبيعات المسلمة", "كمية المرتجعات",
        "قيمة المرتجعات", "صافي الكمية المباعة", "صافي قيمة المبيعات (ج.م)", "تكلفة الوحدة (ج.م)",
        "إجمالي تكلفة المبيعات COGS", "مجمل الربح (ج.م)", "هامش الربح %", "السعر الرسمي للجمهور"
    ]
    rows = [
        [
            r['code'], r['name'], r['delivered_qty'], r['delivered_sales'], r['return_qty'],
            r['return_val'], r['net_qty'], r['net_sales'], r['unit_cost'],
            r['cogs'], r['gross_profit'], f"{r['margin_pct']}%", r['retail_price']
        ]
        for r in data['rows']
    ]
    summary_row = [
        "الإجمالي العام", "", "", data['summary']['total_gross_sales'], "", "", "",
        data['summary']['total_net_sales'], "", data['summary']['total_cogs'],
        data['summary']['total_gross_profit'], f"{data['summary']['overall_margin_pct']}%", ""
    ]
    return export_to_excel_response(f"Net_Sales_Profitability_{start_date}_{end_date}", "صافي مبيعات الأصناف والربحية", headers, rows, summary_row)


# ==============================================================================
# REPORT 10: ITEM PURCHASES & VENDOR ANALYTICS (مشتريات الأصناف وتحليلات الموردين)
# ==============================================================================

@login_required
@require_permission('reports:inventory/view')
def report_item_purchases(request):
    period = request.GET.get('period', 'this_month')
    start_date, end_date, _, _, period_label = parse_date_range(period, request.GET.get('start_date'), request.GET.get('end_date'))
    data = get_item_purchases_report_data(request.user, start_date, end_date)

    context = {
        'rows': data['rows'],
        'summary': data['summary'],
        'period': period,
        'period_label': period_label,
        'start_date': start_date.isoformat(),
        'end_date': end_date.isoformat(),
    }
    return render(request, 'reports/report_item_purchases.html', context)


@login_required
@require_permission('reports:inventory/export')
def report_item_purchases_export(request):
    start_date, end_date, _, _, _ = parse_date_range(request.GET.get('period'), request.GET.get('start_date'), request.GET.get('end_date'))
    data = get_item_purchases_report_data(request.user, start_date, end_date)

    headers = ["كود الصنف", "اسم الصنف", "المورد", "الكمية المشتراة", "إجمالي المنصرف (ج.م)", "متوسط سعر الشراء للوحدة", "الرصيد الحالي بالمخزن"]
    rows = [
        [r['code'], r['name'], r['supplier_name'], r['quantity'], r['spend'], r['avg_cost'], r['current_stock']]
        for r in data['rows']
    ]
    summary_row = ["الإجمالي", "", "", "", data['summary']['total_spend'], "", ""]
    return export_to_excel_response(f"Item_Purchases_{start_date}_{end_date}", "مشتريات الأصناف والموردين", headers, rows, summary_row)


# ==============================================================================
# REPORT 11: ITEM SALES BY CUSTOMER (مبيعات الأصناف حسب العملاء)
# ==============================================================================

@login_required
@require_permission('reports:sales/view')
def report_item_sales_by_customer(request):
    period = request.GET.get('period', 'this_month')
    start_date, end_date, _, _, period_label = parse_date_range(period, request.GET.get('start_date'), request.GET.get('end_date'))
    data = get_item_sales_by_customer_report_data(request.user, start_date, end_date)

    context = {
        'rows': data['rows'],
        'summary': data['summary'],
        'period': period,
        'period_label': period_label,
        'start_date': start_date.isoformat(),
        'end_date': end_date.isoformat(),
    }
    return render(request, 'reports/report_item_sales_by_customer.html', context)


@login_required
@require_permission('reports:sales/export')
def report_item_sales_by_customer_export(request):
    start_date, end_date, _, _, _ = parse_date_range(request.GET.get('period'), request.GET.get('start_date'), request.GET.get('end_date'))
    data = get_item_sales_by_customer_report_data(request.user, start_date, end_date)

    headers = ["كود الصنف", "اسم الصنف", "اسم العميل", "المنطقة / المحافظة", "الكمية المباعة", "الصافي (ج.م)"]
    rows = [
        [r['product_code'], r['product_name'], r['customer_name'], r['area_name'], r['quantity'], r['net_amount']]
        for r in data['rows']
    ]
    summary_row = ["الإجمالي", "", "", "", "", data['summary']['total_amount']]
    return export_to_excel_response(f"Item_Sales_By_Customer_{start_date}_{end_date}", "مبيعات الأصناف حسب العملاء", headers, rows, summary_row)
