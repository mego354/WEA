from django.urls import path, include

urlpatterns = [
    path('performance/', include('reports.urls_performance')),
    path('reports/', include('reports.urls_reports')),
]
