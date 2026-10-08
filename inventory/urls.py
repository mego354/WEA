from django.urls import path
from . import views

urlpatterns = [
    path('', views.inventory_stock_list, name='inventory_stock_list'),
    path('warehouses/', views.warehouses_list, name='warehouses_list'),
    path('memos/', views.inventory_memos_list, name='inventory_memos_list'),
]
