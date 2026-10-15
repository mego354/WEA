from django.urls import path
from . import views

urlpatterns = [
    path('', views.sales_orders_list, name='sales_orders_list'),
    path('export/', views.sales_orders_export, name='sales_orders_export'),
    path('create/', views.sales_order_create, name='sales_order_create'),
    path('<int:pk>/', views.sales_order_detail, name='sales_order_detail'),
    path('<int:pk>/action/<str:action>/', views.sales_order_action, name='sales_order_action'),
    path('collections/', views.collections_list, name='collections_list'),
    path('collections/export/', views.collections_export, name='collections_export'),
    path('collections/create/', views.collection_create, name='collection_create'),
    path('customers/', views.accounting_customers_list, name='accounting_customers_list'),
    path('customer-transactions/', views.customer_transactions_list, name='customer_transactions_list'),
]
