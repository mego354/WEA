from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('master_data.urls')),
    path('home/', include('master_data.urls')),
    path('auth/', include('accounts.urls')),
    path('contacts/', include('contacts.urls')),
    path('catalog/', include('catalog.urls')),
    path('purchases/', include('purchases.urls')),
    path('inventory/', include('inventory.urls')),
    path('treasury/', include('treasury.urls')),
    path('sales/', include('sales.urls')),
]
