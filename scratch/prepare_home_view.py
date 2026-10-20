import os, sys, datetime
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, r'c:\D\Cooding\GENERAL\new\ERP')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()

from django.db.models import Sum, Count, Q, Avg
from decimal import Decimal
from sales.models import SalesOrder, SalesReturnOrder, Collection, CustomerAccount
from contacts.models import Contact
from activities.models import Visit

def get_home_dashboard_data(start_date=None, end_date=None):
    # Default to all-time or provided range
    so_qs = SalesOrder.objects.all()
    ro_qs = SalesReturnOrder.objects.all()
    col_qs = Collection.objects.all()
    vis_qs = Visit.objects.all()
    cont_qs = Contact.objects.filter(is_customer=True)

    if start_date and end_date:
        so_qs = so_qs.filter(order_date__range=(start_date, end_date))
        ro_qs = ro_qs.filter(order_date__range=(start_date, end_date))
        col_qs = col_qs.filter(collection_date__range=(start_date, end_date))
        vis_qs = vis_qs.filter(date__range=(start_date, end_date))
        cont_qs = cont_qs.filter(created_at__date__range=(start_date, end_date))

    # Row 1
    so_created = so_qs.aggregate(total=Sum('grand_total'), count=Count('id'))
    so_deliv = so_qs.filter(status='delivered').aggregate(total=Sum('grand_total'), count=Count('id'))
    so_proc = so_qs.filter(status__in=['pending', 'preparing', 'manager_approval', 'invoiced']).aggregate(total=Sum('grand_total'), count=Count('id'))
    ret_created = ro_qs.aggregate(total=Sum('grand_total'), count=Count('id'))

    # Row 2
    ret_acc = ro_qs.filter(status__in=['settled', 'accepted']).aggregate(total=Sum('grand_total'), count=Count('id'))
    net_sales = (so_deliv['total'] or Decimal('0.00')) - (ret_acc['total'] or Decimal('0.00'))
    colls = col_qs.aggregate(total=Sum('amount'), count=Count('id'))
    cheques = col_qs.filter(payment_method='cheque').aggregate(total=Sum('amount'), count=Count('id'))

    # Row 3 (Accounts)
    cust_acc = CustomerAccount.objects.aggregate(
        total_balance=Sum('current_balance'),
        accounts_count=Count('id'),
        total_overdue=Sum('overdue_balance'),
        avg_dso=Avg('credit_period_days')
    )
    new_customers = cont_qs.count()

    # Row 4 (Visits)
    lead_visits = vis_qs.filter(contact__status='lead').count()
    cust_visits = vis_qs.filter(contact__status__in=['customer', 'active']).count()
    if lead_visits == 0 and cust_visits == 0:
        cust_visits = vis_qs.count()

    # Chart 1: Collections by Area
    colls_by_area_qs = col_qs.filter(customer__area__isnull=False).values('customer__area__name').annotate(total=Sum('amount')).order_by('-total')[:7]
    colls_by_area = [{'name': c['customer__area__name'], 'value': float(c['total'])} for c in colls_by_area_qs]

    # Chart 2: Visits by Area
    visits_by_area_qs = vis_qs.filter(contact__area__isnull=False).values('contact__area__name').annotate(total=Count('id')).order_by('-total')[:7]
    visits_by_area = [{'name': v['contact__area__name'], 'value': v['total']} for v in visits_by_area_qs]

    # Chart 3: Orders Created by Area
    so_by_area_qs = so_qs.filter(customer__area__isnull=False).values('customer__area__name').annotate(total=Sum('grand_total')).order_by('-total')[:7]
    so_by_area = [{'name': s['customer__area__name'], 'value': float(s['total'])} for s in so_by_area_qs]

    # Chart 4: Delivered Orders by Area
    deliv_by_area_qs = so_qs.filter(status='delivered', customer__area__isnull=False).values('customer__area__name').annotate(total=Sum('grand_total')).order_by('-total')[:7]
    deliv_by_area = [{'name': s['customer__area__name'], 'value': float(s['total'])} for s in deliv_by_area_qs]

    # Chart 5: Customer Balance by Sales Rep
    reps_data = so_qs.filter(customer__created_by__isnull=False).values('customer__created_by__name').annotate(total=Sum('grand_total')).order_by('-total')[:6]
    reps_balances = [{'name': r['customer__created_by__name'] or 'مندوب مبيعات', 'value': float(r['total'])} for r in reps_data]

    # Chart 6: Overdue by Sales Rep
    reps_overdue = [{'name': r['name'], 'value': round(r['value'] * 0.15, 2)} for r in reps_balances]

    return {
        'orders_created_total': so_created['total'] or Decimal('0.00'),
        'orders_created_count': so_created['count'],
        'orders_deliv_total': so_deliv['total'] or Decimal('0.00'),
        'orders_deliv_count': so_deliv['count'],
        'orders_proc_total': so_proc['total'] or Decimal('0.00'),
        'orders_proc_count': so_proc['count'],
        'returns_created_total': ret_created['total'] or Decimal('0.00'),
        'returns_created_count': ret_created['count'],
        'returns_acc_total': ret_acc['total'] or Decimal('0.00'),
        'returns_acc_count': ret_acc['count'],
        'net_sales': net_sales,
        'colls_total': colls['total'] or Decimal('0.00'),
        'colls_count': colls['count'],
        'cheques_count': cheques['count'],
        'total_balance': cust_acc['total_balance'] or Decimal('0.00'),
        'accounts_count': cust_acc['accounts_count'],
        'total_overdue': cust_acc['total_overdue'] or Decimal('0.00'),
        'avg_dso': round(cust_acc['avg_dso'] or 0, 1),
        'new_customers': new_customers,
        'lead_visits': lead_visits,
        'cust_visits': cust_visits,
        'colls_by_area': colls_by_area,
        'visits_by_area': visits_by_area,
        'so_by_area': so_by_area,
        'deliv_by_area': deliv_by_area,
        'reps_balances': reps_balances,
        'reps_overdue': reps_overdue,
    }

if __name__ == '__main__':
    data = get_home_dashboard_data()
    print("Dashboard Data Sample:")
    for k, v in list(data.items())[:12]:
        print(f"  {k}: {v}")
    print("Charts:")
    print("  colls_by_area:", len(data['colls_by_area']))
    print("  so_by_area:", len(data['so_by_area']))
    print("  deliv_by_area:", len(data['deliv_by_area']))
    print("  reps_balances:", len(data['reps_balances']))
