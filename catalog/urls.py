from django.urls import path
from . import views

urlpatterns = [
    path('', views.products_list, name='products_list'),
    path('create/', views.product_create, name='product_create'),
    path('categories/', views.categories_list, name='categories_list'),
]
