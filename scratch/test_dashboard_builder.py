import os, sys, datetime, json
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, r'c:\D\Cooding\GENERAL\new\ERP')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django; django.setup()

from django.db.models import Sum, Count, Q, Avg
from decimal import Decimal
from sales.models import SalesOrder, SalesReturnOrder, Collection, CustomerAccount
from contacts.models import Contact
from activities.models import Visit
from master_data.models import Area

def format_metric_amount(val):
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

def build_area_sunburst_data(queryset, amount_field='grand_total', is_count=False):
    """
    Builds a 2-level hierarchical tree for ECharts sunburst:
    Level 1: Governorate / Parent Area
    Level 2: Sub-area / District
    """
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
    # Sort parents by total sum
    def parent_sum(node):
        return sum(c.get('value', 0) for c in node.get('children', [])) + node.get('value', 0)

    sorted_parents = sorted(tree.values(), key=parent_sum, reverse=True)[:8]
    for p in sorted_parents:
        # Keep top 8 children per parent to avoid clutter
        if 'children' in p and p['children']:
            p['children'] = sorted(p['children'], key=lambda x: x.get('value', 0), reverse=True)[:10]
            if not p['children']:
                del p['children']
        result.append(p)
    return result

def build_visits_sunburst_data(queryset):
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

def build_reps_sunburst_data(amount_field='current_balance'):
    """
    Builds tree for reps:
    Level 1: Rep / Team
    Level 2: Customer Area or Top Customer Account
    """
    qs = CustomerAccount.objects.filter(**{f"{amount_field}__gt": 0}).values(
        'customer__area__name',
        'customer__area__parent__name'
    ).annotate(val=Sum(amount_field)).order_by('-val')

    # Fallback to areas if rep assignment is centralized
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
    for p in sorted(tree.values(), key=lambda n: sum(c.get('value', 0) for c in n.get('children', [])) + n.get('value', 0), reverse=True)[:7]:
        if 'children' in p and p['children']:
            p['children'] = sorted(p['children'], key=lambda x: x.get('value', 0), reverse=True)[:8]
        result.append(p)
    return result

print("Testing dashboard builders...")
colls_tree = build_area_sunburst_data(Collection.objects.all(), amount_field='amount')
print("Collections Tree:", len(colls_tree))
visits_tree = build_visits_sunburst_data(Visit.objects.all())
print("Visits Tree:", len(visits_tree))
orders_tree = build_area_sunburst_data(SalesOrder.objects.all(), amount_field='grand_total')
print("Orders Tree:", len(orders_tree))
deliv_tree = build_area_sunburst_data(SalesOrder.objects.filter(status='delivered'), amount_field='grand_total')
print("Deliv Tree:", len(deliv_tree))
rep_bal_tree = build_reps_sunburst_data('current_balance')
print("Rep Bal Tree:", len(rep_bal_tree))
rep_ovd_tree = build_reps_sunburst_data('overdue_balance')
print("Rep Overdue Tree:", len(rep_ovd_tree))

print("JSON Serialization Test:")
json_str = json.dumps({
    'colls': colls_tree,
    'visits': visits_tree,
    'orders': orders_tree,
    'deliv': deliv_tree,
    'reps_bal': rep_bal_tree,
    'reps_ovd': rep_ovd_tree
}, ensure_ascii=False)
print("Success! JSON length:", len(json_str))
