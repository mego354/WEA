from django.urls import path
from . import views

urlpatterns = [
    path('', views.home_view, name='home'),
    path('settings/branding/', views.branding_settings_view, name='branding_settings'),
    path('settings/location/', views.location_settings_view, name='location_settings'),
    path('api/v1/geofence/settings', views.geofence_settings_api, name='geofence_settings_api'),

]
