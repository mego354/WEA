from django.urls import path
from . import views

urlpatterns = [
    # Agreements
    path('agreements/', views.agreements_list, name='agreements_list'),
    path('agreements/bulk-status/', views.agreements_bulk_status, name='agreements_bulk_status'),
    path('agreements/create/', views.agreement_create, name='agreement_create'),
    path('agreements/export/', views.agreements_export, name='agreements_export'),
    path('agreements/<int:pk>/', views.agreement_detail, name='agreement_detail'),
    path('agreements/<int:pk>/edit/', views.agreement_edit, name='agreement_edit'),
    path('agreements/<int:pk>/delete/', views.agreement_delete, name='agreement_delete'),
    path('agreements/<int:pk>/action/<str:action>/', views.agreement_action, name='agreement_action'),

    # Planned Visits
    path('planned-visits/', views.planned_visits_list, name='planned_visits_list'),
    path('planned-visits/add-item/', views.planned_visit_add_item, name='planned_visit_add_item'),
    path('planned-visits/export/', views.planned_visits_export, name='planned_visits_export'),
    path('planned-visits/item/<int:pk>/delete/', views.planned_visit_item_delete, name='planned_visit_item_delete'),
    path('planned-visits/item/<int:pk>/execute/', views.planned_visit_item_execute, name='planned_visit_item_execute'),

    # Visits
    path('visits/', views.visits_list, name='visits_list'),
    path('visits/create/', views.visit_create, name='visit_create'),
    path('visits/export/', views.visits_export, name='visits_export'),
    path('visits/<int:pk>/', views.visit_detail, name='visit_detail'),
    path('visits/<int:pk>/edit/', views.visit_edit, name='visit_edit'),
    path('visits/<int:pk>/action/<str:action>/', views.visit_action, name='visit_action'),

    # APIs
    path('api/templates/', views.visit_templates_api, name='visit_templates_api'),
]

