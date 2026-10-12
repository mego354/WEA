from django.urls import path
from . import views

urlpatterns = [
    path('', views.products_list, name='products_list'),
    path('create/', views.product_create, name='product_create'),
    path('export/', views.products_export, name='products_export'),
    path('categories/', views.categories_list, name='categories_list'),
    path('categories/<int:pk>/edit/', views.category_edit, name='category_edit'),
    path('categories/<int:pk>/delete/', views.category_delete, name='category_delete'),
    path('<int:pk>/', views.product_detail, name='product_detail'),
    path('<int:pk>/edit/', views.product_edit, name='product_edit'),
    path('<int:pk>/delete/', views.product_delete, name='product_delete'),
]

