import os, sys
sys.path.insert(0, r'C:\D\Cooding\GENERAL\cpp\ERP')
sys.stdout.reconfigure(encoding='utf-8')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()

from activities.models import Visit, PlannedVisitDay, PlannedVisitItem, Agreement
from contacts.models import Contact
from sales.models import SalesOrder
from purchases.models import PurchaseOrder
from treasury.models import Vault

def print_fields(model):
    print(f"=== {model.__name__} ===")
    for f in model._meta.get_fields():
        if not f.is_relation or f.many_to_one or f.one_to_one:
            rel = f" -> {f.related_model.__name__}" if getattr(f, 'related_model', None) else ""
            print(f"  {f.name} ({f.get_internal_type() if hasattr(f, 'get_internal_type') else type(f).__name__}){rel}")

for m in [Visit, PlannedVisitDay, PlannedVisitItem, Agreement, Contact, SalesOrder, PurchaseOrder, Vault]:
    print_fields(m)
