from django.urls import path
from . import views

urlpatterns = [
    path('', views.notifications_inbox, name='notifications_inbox'),
    path('<int:pk>/open/', views.notification_open, name='notification_open'),
    # API aliases under /notifications/api/
    path('api/', views.api_notifications_list, name='notifications_api_list'),
    path('api/unread-count/', views.api_notifications_unread_count, name='notifications_api_unread_count'),
    path('api/summary/', views.api_notifications_summary, name='notifications_api_summary'),
    path('api/<int:pk>/', views.api_notification_detail, name='notifications_api_detail'),
    path('api/<int:pk>/read/', views.api_notification_mark_read, name='notifications_api_mark_read'),
    path('api/read-all/', views.api_notifications_mark_all_read, name='notifications_api_mark_all_read'),
    path('api/devices/register/', views.api_device_register, name='notifications_api_device_register'),
    path('api/devices/unregister/', views.api_device_unregister, name='notifications_api_device_unregister'),
]
