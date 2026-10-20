import os
import sys
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, r'c:\D\Cooding\GENERAL\new\ERP')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()

from django.test import Client
from django.contrib.auth import get_user_model
from contacts.models import Contact
from sales.models import SalesOrder, Collection
from activities.models import Visit, PlannedVisitDay

User = get_user_model()
admin_user = User.objects.filter(is_superuser=True).first()
if not admin_user:
    admin_user = User.objects.create_superuser('wea.pharm2020@gmail.com', 'wea.pharm2020@gmail.com', 'Wea@4444')

client = Client()
client.force_login(admin_user)

routes_to_test = [
    # Core & Dashboard
    ('Home / Dashboard', '/'),
    ('Home Alias', '/home/'),
    
    # Contacts
    ('Contacts List', '/contacts/'),
    ('Contacts Card View', '/contacts/?view=cards'),
    ('Contacts Search', '/contacts/?search=صيدلية'),
    ('Contacts Filter Category', '/contacts/?category=A'),
    ('Contacts Create Page', '/contacts/create/'),
    
    # Catalog
    ('Catalog Products', '/catalog/'),
    ('Catalog Search', '/catalog/?q=Steps'),
    ('Product Categories', '/product-categories/'),
    
    # Purchases
    ('Purchase Orders', '/purchase-orders/'),
    ('Purchase Orders Filter', '/purchase-orders/?status=pending'),
    ('Purchase Return Orders', '/purchase-return-orders/'),
    ('Vendor Payments', '/vendor-payments/'),
    ('Accounting Vendors', '/accounting/vendors/'),
    
    # Sales
    ('Sales Orders', '/sales/'),
    ('Collections List', '/sales/collections/'),
    ('Customer Accounts', '/sales/customers/'),
    
    # Inventory
    ('Inventory Stock', '/inventory/'),
    ('Warehouses List', '/inventory/warehouses/'),
    ('Inventory Memos', '/inventory/memos/'),
    
    # Treasury
    ('Vaults List', '/treasury/vaults/'),
    
    # Activities & Visits
    ('Agreements List', '/agreements/'),
    ('Planned Visits', '/planned-visits/'),
    ('Visits Log', '/visits/'),
    ('Visit Templates Settings', '/settings/visits/templates/'),
    
    # Settings & Users
    ('Users Management', '/users/'),
    ('Roles Management', '/roles/'),
    ('Areas Settings', '/settings/areas/'),
    ('Branding Settings', '/settings/branding/'),
    ('Location Settings', '/settings/location/'),
    
    # APIs
    ('Customer Search API', '/api/customers/search/?q=اسامه'),
    ('Visit Templates API', '/activities/api/templates/'),
    ('Geofence Settings API', '/api/v1/geofence/settings'),
]

first_contact = Contact.objects.first()
if first_contact:
    routes_to_test.append(('Contact Detail Overview', f'/contacts/{first_contact.pk}/'))
    routes_to_test.append(('Contact Detail Tab Addresses', f'/contacts/{first_contact.pk}/?tab=addresses'))
    routes_to_test.append(('Contact Detail Tab Transactions', f'/contacts/{first_contact.pk}/?tab=transactions'))
    routes_to_test.append(('Contact Edit', f'/contacts/{first_contact.pk}/edit/'))
    routes_to_test.append(('Visit Create with Contact', f'/visits/create/?contact_id={first_contact.pk}'))

first_visit = Visit.objects.first()
if first_visit:
    routes_to_test.append(('Visit Detail', f'/visits/{first_visit.pk}/'))
    routes_to_test.append(('Visit Edit', f'/visits/{first_visit.pk}/edit/'))

first_order = SalesOrder.objects.first()
if first_order:
    routes_to_test.append(('Sales Order Detail', f'/sales/{first_order.pk}/'))

print(f"=== TESTING COMPLETE ERP APP FLOW ({len(routes_to_test)} ENDPOINTS) ===")

passed = 0
failed = 0

for name, url in routes_to_test:
    try:
        response = client.get(url, follow=True)
        status = response.status_code
        if status in [200, 302]:
            passed += 1
            print(f" [PASS] {status} - {name:<32} -> {url}")
        else:
            failed += 1
            print(f" [FAIL] {status} - {name:<32} -> {url}")
    except Exception as e:
        failed += 1
        print(f" [ERROR] {name:<32} -> {url}: {e}")

print(f"\nResults: {passed} PASSED, {failed} FAILED out of {len(routes_to_test)} routes.")
