from django.urls import path
from django.shortcuts import redirect
from . import views

urlpatterns = [
    path('', views.home_view, name='home'),
    path('settings/', lambda request: redirect('users_list'), name='settings_root'),

    # Company Branding
    path('settings/branding/', views.branding_settings_view, name='branding_settings'),

    # Location Settings & Geofence API
    path('settings/location/', views.location_settings_view, name='location_settings'),
    path('api/v1/geofence/settings', views.geofence_settings_api, name='geofence_settings_api'),

    # Areas & Territories
    path('settings/areas/', views.areas_settings_view, name='areas_settings'),
    path('settings/areas/add/', views.area_create, name='area_create'),
    path('settings/areas/<int:pk>/edit/', views.area_edit, name='area_edit'),
    path('settings/areas/<int:pk>/delete/', views.area_delete, name='area_delete'),

    # Expense Types
    path('settings/expenses/', views.expenses_settings_view, name='expenses_settings'),
    path('settings/expenses/add/', views.expense_create, name='expense_create'),
    path('settings/expenses/<int:pk>/edit/', views.expense_edit, name='expense_edit'),
    path('settings/expenses/<int:pk>/delete/', views.expense_delete, name='expense_delete'),

    # Ticket Types
    path('settings/tickets/', views.tickets_settings_view, name='tickets_settings'),
    path('settings/tickets/add/', views.ticket_create, name='ticket_create'),
    path('settings/tickets/<int:pk>/edit/', views.ticket_edit, name='ticket_edit'),
    path('settings/tickets/<int:pk>/delete/', views.ticket_delete, name='ticket_delete'),

    # Approval Request Types
    path('settings/requests/', views.requests_settings_view, name='requests_settings'),
    path('settings/requests/add/', views.request_type_create, name='request_type_create'),
    path('settings/requests/<int:pk>/edit/', views.request_type_edit, name='request_type_edit'),
    path('settings/requests/<int:pk>/delete/', views.request_type_delete, name='request_type_delete'),

    # Agreement Types
    path('settings/agreements/', views.agreements_settings_view, name='agreements_settings'),
    path('settings/agreements/add/', views.agreement_create, name='agreement_type_create'),
    path('settings/agreements/<int:pk>/edit/', views.agreement_edit, name='agreement_type_edit'),
    path('settings/agreements/<int:pk>/delete/', views.agreement_delete, name='agreement_type_delete'),

    # Workflow Settings
    path('settings/sales/', views.sales_settings_view, name='sales_settings'),
    path('settings/purchase/', views.purchase_settings_view, name='purchase_settings'),
    path('settings/inventory/', views.inventory_settings_view, name='inventory_settings'),

    # Custom Fields & Data Sync
    path('settings/contacts-udf/', views.contacts_udf_view, name='contacts_udf'),
    path('settings/sync-data/', views.sync_data_view, name='sync_data'),
    path('settings/sync-data/<str:sync_type>/sync/', views.sync_data_trigger, name='sync_data_trigger'),
]
