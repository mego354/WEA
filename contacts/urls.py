from django.urls import path
from . import views

urlpatterns = [
    path('', views.contacts_list, name='contacts_list'),
    path('create/', views.contact_create, name='contact_create'),
    path('export/', views.contacts_export, name='contacts_export'),
    path('import/', views.contacts_import, name='contacts_import'),
    path('import/template/', views.contacts_import_template, name='contacts_import_template'),
    path('api/subareas/', views.get_subareas, name='contact_subareas_api'),
    path('api/search/', views.customers_search_api, name='customers_search_api'),
    
    # Detail and Overview
    path('<int:pk>/', views.contact_detail, name='contact_detail'),
    path('<int:pk>/overview/', views.contact_detail, name='contact_detail_overview'),
    path('<int:pk>/edit/', views.contact_edit, name='contact_edit'),
    path('<int:pk>/delete/', views.contact_delete, name='contact_delete'),
    path('<int:pk>/status/', views.contact_update_status, name='contact_update_status'),
    
    # Detail sub-actions
    path('<int:pk>/comments/', views.contact_add_comment, name='contact_add_comment'),
    path('<int:pk>/todos/create/', views.contact_create_todo, name='contact_create_todo'),
    path('<int:pk>/todos/<int:todo_id>/toggle/', views.contact_toggle_todo, name='contact_toggle_todo'),
    path('<int:pk>/attachments/upload/', views.contact_upload_attachment, name='contact_upload_attachment'),
    path('<int:pk>/addresses/add/', views.contact_add_address, name='contact_add_address'),
    path('<int:pk>/addresses/<int:address_id>/delete/', views.contact_delete_address, name='contact_delete_address'),
]
