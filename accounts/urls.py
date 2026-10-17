from django.urls import path
from . import views

urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('users/', views.users_list, name='users_list'),
    path('users/<int:pk>/toggle-bypass-location/', views.user_toggle_bypass_location, name='user_toggle_bypass_location'),
    path('roles/', views.roles_list, name='roles_list'),

]
