from django.urls import path
from . import views

# Versioned Capacitor-ready API mounted at /api/v1/notifications/
urlpatterns = [
    path('', views.api_notifications_list, name='api_v1_notifications_list'),
    path('unread-count/', views.api_notifications_unread_count, name='api_v1_notifications_unread_count'),
    path('summary/', views.api_notifications_summary, name='api_v1_notifications_summary'),
    path('diagnostics/', views.api_push_diagnostics, name='api_v1_notifications_diagnostics'),
    path('test-push/', views.api_send_test_push, name='api_v1_notifications_test_push'),
    path('<int:pk>/', views.api_notification_detail, name='api_v1_notification_detail'),
    path('<int:pk>/read/', views.api_notification_mark_read, name='api_v1_notification_mark_read'),
    path('read-all/', views.api_notifications_mark_all_read, name='api_v1_notifications_mark_all_read'),
    path('devices/register/', views.api_device_register, name='api_v1_notifications_device_register'),
    path('devices/unregister/', views.api_device_unregister, name='api_v1_notifications_device_unregister'),
]
