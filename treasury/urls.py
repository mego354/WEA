from django.urls import path
from . import views

urlpatterns = [
    path('payments/', views.vendor_payments_list, name='vendor_payments_list'),
    path('payments/export/', views.vendor_payments_export, name='vendor_payments_export'),
    path('payments/create/', views.vendor_payment_create, name='vendor_payment_create'),
    path('payment-requests/', views.vendor_payment_requests_list, name='vendor_payment_requests_list'),
    path('payment-requests/create/', views.vendor_payment_request_create, name='vendor_payment_request_create'),
    path('payment-requests/export/', views.vendor_payment_requests_export, name='vendor_payment_requests_export'),
    path('payment-requests/<int:pk>/', views.vendor_payment_request_detail, name='vendor_payment_request_detail'),
    path('payment-requests/<int:pk>/action/<str:action>/', views.vendor_payment_request_action, name='vendor_payment_request_action'),
    path('vendors/', views.accounting_vendors_list, name='accounting_vendors_list'),
    path('vendors/export/', views.accounting_vendors_export, name='accounting_vendors_export'),
    path('vendor-transactions/', views.vendor_transactions_list, name='vendor_transactions_list'),
    path('vendor-transactions/export/', views.vendor_transactions_export, name='vendor_transactions_export'),
    path('vaults/', views.vaults_list, name='vaults_list'),
    path('vaults/export/', views.vaults_export, name='vaults_export'),
    path('vaults/<int:pk>/', views.vault_detail, name='vault_detail'),
    path('vaults/create/', views.vault_create, name='vault_create'),
    path('vaults/<int:pk>/edit/', views.vault_edit, name='vault_edit'),
    path('vaults/<int:pk>/delete/', views.vault_delete, name='vault_delete'),
    path('vault-transactions/', views.vault_transactions_list, name='vault_transactions_list'),
    path('vault-transactions/export/', views.vault_transactions_export, name='vault_transactions_export'),
    path('vault-transactions/<int:pk>/reverse/', views.vault_transaction_reverse, name='vault_transaction_reverse'),
    path('transfer/', views.vault_transfer, name='vault_transfer'),
    path('deposit/', views.vault_deposit, name='vault_deposit'),
    path('withdraw/', views.vault_withdraw, name='vault_withdraw'),
]
