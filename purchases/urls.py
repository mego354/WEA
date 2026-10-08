from django.urls import path
from . import views

urlpatterns = [
    path('', views.purchase_orders_list, name='purchase_orders_list'),
    path('create/', views.purchase_order_create, name='purchase_order_create'),
    path('<int:pk>/', views.purchase_order_detail, name='purchase_order_detail'),
    path('<int:pk>/action/<str:action>/', views.purchase_order_action, name='purchase_order_action'),
    path('<int:pk>/print/', views.purchase_order_print, name='purchase_order_print'),
]
