from django.urls import path
from . import views_performance

urlpatterns = [
    path('', views_performance.performance_overview, name='performance_root'),
    path('overview/', views_performance.performance_overview, name='performance_overview'),
    path('overview/export/', views_performance.performance_overview_export, name='performance_overview_export'),
    path('overview/accounts-api/', views_performance.performance_overview_accounts_api, name='performance_overview_accounts_api'),
    path('overview/contacts-search/', views_performance.performance_contacts_search_api, name='performance_contacts_search_api'),
    path('analysis/', views_performance.performance_analysis, name='performance_analysis'),
    path('analysis/export/', views_performance.performance_analysis_export, name='performance_analysis_export'),
    path('daily/', views_performance.performance_daily, name='performance_daily'),
    path('daily/export/', views_performance.performance_daily_export, name='performance_daily_export'),
    path('detailed/', views_performance.performance_detailed, name='performance_detailed'),
    path('detailed/export/', views_performance.performance_detailed_export, name='performance_detailed_export'),
]
