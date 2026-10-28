from django.urls import path
from . import views

urlpatterns = [
    path('', views.purchase_orders_list, name='purchase_orders_list'),
    path('create/', views.purchase_order_create, name='purchase_order_create'),
    path('export/', views.purchase_orders_export, name='purchase_orders_export'),
    path('returns/', views.purchase_return_orders_list, name='purchase_return_orders_list'),
    path('returns/create/', views.purchase_return_order_create, name='purchase_return_order_create'),
    path('returns/export/', views.purchase_return_orders_export, name='purchase_return_orders_export'),
    path('returns/<int:pk>/', views.purchase_return_order_detail, name='purchase_return_order_detail'),
    path('returns/<int:pk>/action/<str:action>/', views.purchase_return_order_action, name='purchase_return_order_action'),
    path('returns/<int:pk>/print/', views.purchase_return_order_print, name='purchase_return_order_print'),
    path('<int:pk>/', views.purchase_order_detail, name='purchase_order_detail'),
    path('<int:pk>/edit/', views.purchase_order_edit, name='purchase_order_edit'),
    path('<int:pk>/split/', views.purchase_order_split, name='purchase_order_split'),
    path('<int:pk>/action/<str:action>/', views.purchase_order_action, name='purchase_order_action'),
    path('<int:pk>/status/update/', views.purchase_order_update_status_ajax, name='purchase_order_update_status_ajax'),
    path('<int:pk>/comments/add/', views.purchase_order_add_comment, name='purchase_order_add_comment'),
    path('<int:pk>/attachments/upload/', views.purchase_order_upload_attachment, name='purchase_order_upload_attachment'),
    path('<int:pk>/print/', views.purchase_order_print, name='purchase_order_print'),

]
