import os
import sys
import inspect

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

import django
django.setup()

import accounts.views as acc_v
import catalog.views as cat_v
import contacts.views as con_v
import purchases.views as pur_v
import inventory.views as inv_v
import treasury.views as tre_v
import sales.views as sal_v
import activities.views as act_v
import master_data.views as mas_v

views_to_check = [
    ('accounts.users_list', acc_v.users_list),
    ('accounts.roles_list', acc_v.roles_list),
    ('catalog.products_list', cat_v.products_list),
    ('catalog.categories_list', cat_v.categories_list),
    ('contacts.contacts_list', con_v.contacts_list),
    ('purchases.purchase_orders_list', pur_v.purchase_orders_list),
    ('purchases.purchase_return_orders_list', pur_v.purchase_return_orders_list),
    ('inventory.inventory_stock_list', inv_v.inventory_stock_list),
    ('inventory.warehouses_list', inv_v.warehouses_list),
    ('inventory.inventory_memos_list', inv_v.inventory_memos_list),
    ('treasury.vendor_payments_list', tre_v.vendor_payments_list),
    ('treasury.vendor_payment_requests_list', tre_v.vendor_payment_requests_list),
    ('treasury.accounting_vendors_list', tre_v.accounting_vendors_list),
    ('treasury.vendor_transactions_list', tre_v.vendor_transactions_list),
    ('treasury.vaults_list', tre_v.vaults_list),
    ('treasury.vault_transactions_list', tre_v.vault_transactions_list),
    ('sales.sales_orders_list', sal_v.sales_orders_list),
    ('sales.collections_list', sal_v.collections_list),
    ('sales.accounting_customers_list', sal_v.accounting_customers_list),
    ('sales.customer_transactions_list', sal_v.customer_transactions_list),
    ('activities.agreements_list', act_v.agreements_list),
    ('activities.visits_list', act_v.visits_list),
    ('activities.visit_templates_list', act_v.visit_templates_list),
]

for name, fn in views_to_check:
    src = inspect.getsource(fn)
    has_pag = 'Paginator' in src
    has_sel = 'select_related' in src
    has_pref = 'prefetch_related' in src
    print(f"{name:<42} | Pag: {str(has_pag):<5} | Sel: {str(has_sel):<5} | Pref: {str(has_pref):<5}")
