from django.urls import path
from . import views

urlpatterns = [
    path('', views.inventory_stock_list, name='inventory_stock_list'),
    path('export/', views.inventory_stock_export, name='inventory_stock_export'),
    path('warehouses/', views.warehouses_list, name='warehouses_list'),
    path('warehouses/export/', views.warehouses_export, name='warehouses_export'),
    path('warehouses/create/', views.warehouse_create, name='warehouse_create'),
    path('warehouses/<int:pk>/edit/', views.warehouse_edit, name='warehouse_edit'),
    path('warehouses/<int:pk>/delete/', views.warehouse_delete, name='warehouse_delete'),
    path('memos/', views.inventory_memos_list, name='inventory_memos_list'),
    path('memos/export/', views.inventory_memos_export, name='inventory_memos_export'),
    path('memos/create/', views.inventory_memo_create, name='inventory_memo_create'),
    path('memos/<int:pk>/', views.inventory_memo_detail, name='inventory_memo_detail'),
    path('transfers/', views.product_transfers_list, name='product_transfers_list'),
    path('transfers/export/', views.product_transfers_export, name='product_transfers_export'),
    path('transfers/create/', views.product_transfer_create, name='product_transfer_create'),
    path('transfers/<int:pk>/', views.product_transfer_detail, name='product_transfer_detail'),
    path('transfers/<int:pk>/action/<str:action>/', views.product_transfer_action, name='product_transfer_action'),
    path('api/warehouse-stock/', views.inventory_warehouse_stock_api, name='inventory_warehouse_stock_api'),
]