from django.contrib import admin
from django.urls import path, include
import catalog.views as catalog_views
import purchases.views as purchases_views
import treasury.views as treasury_views
import contacts.views as contacts_views


import accounts.views as accounts_views


urlpatterns = [
    path('admin/', admin.site.urls),
    path('login/', accounts_views.login_view, name='login_root_alias'),
    path('logout/', accounts_views.logout_view, name='logout_root_alias'),
    path('auth/', include('accounts.urls')),
    path('settings/', include('accounts.urls')),
    path('users/', accounts_views.users_list, name='users_list_root_alias'),
    path('roles/', accounts_views.roles_list, name='roles_list_root_alias'),
    path('', include('master_data.urls')),
    path('home/', include('master_data.urls')),
    path('contacts/', include('contacts.urls')),
    path('catalog/', include('catalog.urls')),
    path('purchases/', include('purchases.urls')),
    path('inventory/', include('inventory.urls')),
    path('treasury/', include('treasury.urls')),
    path('sales/', include('sales.urls')),
    path('activities/', include('activities.urls')),
    path('', include('activities.urls')),

    # Reference ERP URL Parity Aliases
    path('products/', include('catalog.urls')),
    path('product-categories/', catalog_views.categories_list, name='product_categories_alias'),
    path('purchase-orders/', include('purchases.urls')),
    path('purchase-return-orders/', purchases_views.purchase_return_orders_list, name='purchase_return_orders_alias'),
    path('purchase-return-orders/create/', purchases_views.purchase_return_order_create, name='purchase_return_order_create_alias'),
    path('purchase-return-orders/export/', purchases_views.purchase_return_orders_export, name='purchase_return_orders_export_alias'),
    path('purchase-return-orders/<int:pk>/', purchases_views.purchase_return_order_detail, name='purchase_return_order_detail_alias'),
    path('purchase-return-orders/<int:pk>/action/<str:action>/', purchases_views.purchase_return_order_action, name='purchase_return_order_action_alias'),
    path('purchase-return-orders/<int:pk>/print/', purchases_views.purchase_return_order_print, name='purchase_return_order_print_alias'),

    path('vendor-payments/', treasury_views.vendor_payments_list, name='vendor_payments_alias'),
    path('vendor-payments/create/', treasury_views.vendor_payment_create, name='vendor_payment_create_alias'),
    path('vendor-payment-requests/', treasury_views.vendor_payment_requests_list, name='vendor_payment_requests_alias'),
    path('accounting/vendors/', treasury_views.accounting_vendors_list, name='accounting_vendors_alias'),
    path('accounting/vendor-transactions/', treasury_views.vendor_transactions_list, name='vendor_transactions_alias'),

    # Customer and Visit Search API Parity
    path('api/customers/search/', contacts_views.customers_search_api, name='customers_search_global_api'),
    path('api/v1/visits/contacts/list', contacts_views.customers_search_api, name='visits_contacts_list_reference_api'),
]

