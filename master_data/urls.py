from django.urls import path
from . import views

urlpatterns = [
    path('', views.home_view, name='home'),
    path('settings/branding/', views.branding_settings_view, name='branding_settings'),
]
