from django.urls import path
from . import views_performance

urlpatterns = [
    path('', views_performance.performance_overview, name='performance_root'),
    path('overview/', views_performance.performance_overview, name='performance_overview'),
    path('analysis/', views_performance.performance_analysis, name='performance_analysis'),
    path('analysis/export/', views_performance.performance_analysis_export, name='performance_analysis_export'),
    path('daily/', views_performance.performance_daily, name='performance_daily'),
    path('daily/export/', views_performance.performance_daily_export, name='performance_daily_export'),
    path('detailed/', views_performance.performance_detailed, name='performance_detailed'),
    path('detailed/export/', views_performance.performance_detailed_export, name='performance_detailed_export'),
]
