from django.urls import path
from . import views

urlpatterns = [
    path('payments/', views.vendor_payments_list, name='vendor_payments_list'),
    path('payments/export/', views.vendor_payments_export, name='vendor_payments_export'),
    path('payments/create/', views.vendor_payment_create, name='vendor_payment_create'),
    path('payment-requests/', views.vendor_payment_requests_list, name='vendor_payment_requests_list'),
    path('vendors/', views.accounting_vendors_list, name='accounting_vendors_list'),
    path('vendor-transactions/', views.vendor_transactions_list, name='vendor_transactions_list'),
    path('vaults/', views.vaults_list, name='vaults_list'),
    path('vault-transactions/', views.vault_transactions_list, name='vault_transactions_list'),
]
