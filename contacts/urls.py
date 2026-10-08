from django.urls import path
from . import views

urlpatterns = [
    path('', views.contacts_list, name='contacts_list'),
    path('create/', views.contact_create, name='contact_create'),
]
