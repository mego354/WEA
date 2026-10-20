import os, sys, datetime
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, r'c:\D\Cooding\GENERAL\new\ERP')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()
from django.db.models import Sum, Count, Q
from decimal import Decimal
from sales.models import SalesOrder, SalesReturnOrder, Collection, CustomerAccount
from contacts.models import Contact
from activities.models import Visit

start_date = datetime.date(2026, 10, 1)
end_date = datetime.date(2026, 10, 31)

so_created = SalesOrder.objects.filter(order_date__range=(start_date, end_date)).aggregate(total=Sum('grand_total'), count=Count('id'))
so_deliv = SalesOrder.objects.filter(status='delivered', order_date__range=(start_date, end_date)).aggregate(total=Sum('grand_total'), count=Count('id'))
so_proc = SalesOrder.objects.filter(status__in=['pending', 'preparing', 'manager_approval', 'invoiced'], order_date__range=(start_date, end_date)).aggregate(total=Sum('grand_total'), count=Count('id'))
ret_created = SalesReturnOrder.objects.filter(order_date__range=(start_date, end_date)).aggregate(total=Sum('grand_total'), count=Count('id'))
ret_acc = SalesReturnOrder.objects.filter(status__in=['settled', 'accepted'], order_date__range=(start_date, end_date)).aggregate(total=Sum('grand_total'), count=Count('id'))
colls = Collection.objects.filter(collection_date__range=(start_date, end_date)).aggregate(total=Sum('amount'), count=Count('id'))

print("October 2026 Metrics:")
print("  Orders Created:", so_created)
print("  Orders Delivered:", so_deliv)
print("  Orders Processing:", so_proc)
print("  Returns Created:", ret_created)
print("  Returns Accepted:", ret_acc)
print("  Collections:", colls)
