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

    # 4. Calls & Telesales
    path('calls/', views_reports.report_calls, name='report_calls'),
    path('calls/export/', views_reports.report_calls_export, name='report_calls_export'),

    # 5. Customer 360 Summary
    path('customer-360/', views_reports.report_customer_360, name='report_customer_360'),
    path('customer-360/export/', views_reports.report_customer_360_export, name='report_customer_360_export'),

    # 6. Bundles & Promotions
    path('promotions/', views_reports.report_promotions, name='report_promotions'),
    path('promotions/export/', views_reports.report_promotions_export, name='report_promotions_export'),

    # 7. Order Deliveries & Logistics
    path('order-deliveries/', views_reports.report_order_deliveries, name='report_order_deliveries'),
    path('order-deliveries/export/', views_reports.report_order_deliveries_export, name='report_order_deliveries_export'),
    path('order-deliveries/print/', views_reports.report_order_deliveries_print, name='report_order_deliveries_print'),

    # 8. Delivery Status & Stock Availability
    path('delivery-stock/', views_reports.report_delivery_stock, name='report_delivery_stock'),
    path('delivery-stock/export/', views_reports.report_delivery_stock_export, name='report_delivery_stock_export'),

    # 9. Net Item Sales & Profitability
    path('net-sales/', views_reports.report_net_sales, name='report_net_sales'),
    path('net-sales/export/', views_reports.report_net_sales_export, name='report_net_sales_export'),

    # 10. Item Purchases & Vendor Analytics
    path('item-purchases/', views_reports.report_item_purchases, name='report_item_purchases'),
    path('item-purchases/export/', views_reports.report_item_purchases_export, name='report_item_purchases_export'),

    # 11. Item Sales by Customer
    path('item-sales-by-customer/', views_reports.report_item_sales_by_customer, name='report_item_sales_by_customer'),
    path('item-sales-by-customer/export/', views_reports.report_item_sales_by_customer_export, name='report_item_sales_by_customer_export'),

    # 12. Sales & Collection Target Achievement
    path('target-achievement/', views_reports.report_target_achievement, name='report_target_achievement'),
    path('target-achievement/export/', views_reports.report_target_achievement_export, name='report_target_achievement_export'),

    # 13. Medical Samples Tracking
    path('samples/', views_reports.report_samples, name='report_samples'),
    path('samples/export/', views_reports.report_samples_export, name='report_samples_export'),
]
