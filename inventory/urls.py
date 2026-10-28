from django.urls import path
from . import views

urlpatterns = [
    path('', views.inventory_stock_list, name='inventory_stock_list'),
    path('export/', views.inventory_stock_export, name='inventory_stock_export'),
    path('warehouses/', views.warehouses_list, name='warehouses_list'),
    path('memos/', views.inventory_memos_list, name='inventory_memos_list'),
    path('transfers/', views.product_transfers_list, name='product_transfers_list'),
    path('transfers/create/', views.product_transfer_create, name='product_transfer_create'),
    path('transfers/<int:pk>/', views.product_transfer_detail, name='product_transfer_detail'),
    path('transfers/<int:pk>/action/<str:action>/', views.product_transfer_action, name='product_transfer_action'),
]
