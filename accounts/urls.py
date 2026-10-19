from django.urls import path
from . import views

urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),

    # Users Management
    path('users/', views.users_list, name='users_list'),
    path('users/add/', views.user_create, name='user_create'),
    path('users/<int:pk>/edit/', views.user_edit, name='user_edit'),
    path('users/<int:pk>/reset-password/', views.user_reset_password, name='user_reset_password'),
    path('users/<int:pk>/toggle-status/', views.user_toggle_status, name='user_toggle_status'),
    path('users/<int:pk>/toggle-bypass-location/', views.user_toggle_bypass_location, name='user_toggle_bypass_location'),
    path('users/export/', views.users_export, name='users_export'),

    # Roles & Permissions Management
    path('roles/', views.roles_list, name='roles_list'),
    path('roles/create/', views.role_create, name='role_create'),
    path('roles/<int:pk>/edit/', views.role_edit, name='role_edit'),
    path('roles/<int:pk>/duplicate/', views.role_duplicate, name='role_duplicate'),
    path('roles/<int:pk>/delete/', views.role_delete, name='role_delete'),
]
