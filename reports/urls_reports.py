from django.urls import path
from . import views_reports

urlpatterns = [
    # Reports Hub
    path('', views_reports.reports_hub, name='reports_hub'),

    # 1. AR Aging
    path('ar-aging/', views_reports.report_ar_aging, name='report_ar_aging'),
    path('ar-aging/export/', views_reports.report_ar_aging_export, name='report_ar_aging_export'),
    path('ar-aging/print/', views_reports.report_ar_aging_print, name='report_ar_aging_print'),

    # 2. Customers Trial Balance
    path('trial-balance/', views_reports.report_trial_balance, name='report_trial_balance'),
    path('trial-balance/export/', views_reports.report_trial_balance_export, name='report_trial_balance_export'),
    path('trial-balance/print/', views_reports.report_trial_balance_print, name='report_trial_balance_print'),

    # 3. Agreements Achievement & ROI
    path('agreements-roi/', views_reports.report_agreements_roi, name='report_agreements_roi'),
    path('agreements-roi/export/', views_reports.report_agreements_roi_export, name='report_agreements_roi_export'),

    # 4. Customer 360 Summary
    path('customer-360/', views_reports.report_customer_360, name='report_customer_360'),
    path('customer-360/export/', views_reports.report_customer_360_export, name='report_customer_360_export'),

    # 5. Delivery Status & Stock Availability
    path('delivery-stock/', views_reports.report_delivery_stock, name='report_delivery_stock'),
    path('delivery-stock/export/', views_reports.report_delivery_stock_export, name='report_delivery_stock_export'),

    # 6. Net Item Sales & Profitability
    path('net-sales/', views_reports.report_net_sales, name='report_net_sales'),
    path('net-sales/export/', views_reports.report_net_sales_export, name='report_net_sales_export'),

    # 7. Item Purchases & Vendor Analytics
    path('item-purchases/', views_reports.report_item_purchases, name='report_item_purchases'),
    path('item-purchases/export/', views_reports.report_item_purchases_export, name='report_item_purchases_export'),

    # 8. Item Sales by Customer
    path('item-sales-by-customer/', views_reports.report_item_sales_by_customer, name='report_item_sales_by_customer'),
    path('item-sales-by-customer/export/', views_reports.report_item_sales_by_customer_export, name='report_item_sales_by_customer_export'),
]
