# Complete Route-to-Permission Mapping Matrix

**Project:** WEA Pharma ERP  
**Coverage Standard:** 100% of discovered application routes  
**Status:** **ALL ROUTES VERIFIED & TESTED**

---

## 1. Route Permission Matrix

| # | Route Pattern | View Name / Handler | Required Permission | Enforcement Location | Test Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Purchases App** | | | | | |
| 1 | `/purchases/` | `purchases_list` | `purchases:orders/list` | `@require_permission` | **PASSED** |
| 2 | `/purchases/create/` | `purchase_create` | `purchases:orders/create` | `@require_permission` | **PASSED** |
| 3 | `/purchases/<id>/` | `purchase_detail` | `purchases:orders/view` | `@require_permission` | **PASSED** |
| 4 | `/purchases/<id>/print/` | `purchase_print` | `purchases:orders/view` | `@require_permission` | **PASSED** |
| 5 | `/purchases/<id>/split/` | `purchase_split` | `purchases:orders/create` | `@require_permission` | **PASSED** |
| 6 | `/purchases/export/` | `purchases_export` | `purchases:orders/export` | `@require_permission` | **PASSED** |
| 7 | `/purchases/<id>/comment/` | `purchase_add_comment` | `purchases:orders/view` | `@require_permission` | **PASSED** |
| 8 | `/purchases/<id>/attachment/` | `purchase_upload_attachment` | `purchases:orders/view` | `@require_permission` | **PASSED** |
| 9 | `/purchases/<id>/status-ajax/` | `purchase_status_ajax` | `purchases:orders/approve` | `@require_permission` | **PASSED** |
| 10 | `/purchases/<id>/action/approve/` | `purchase_action` | `purchases:orders/approve` | `@require_permission` | **PASSED** |
| 11 | `/purchases/<id>/action/stock/` | `purchase_action` | `purchases:orders/stock` | `@require_permission` | **PASSED** |
| 12 | `/purchases/<id>/action/invoice/` | `purchase_action` | `purchases:orders/invoice` | `@require_permission` | **PASSED** |
| 13 | `/purchases/<id>/action/undoInvoice/` | `purchase_action` | `purchases:orders/undoInvoice` | `@require_permission` | **PASSED** |
| 14 | `/purchases/<id>/action/cancel/` | `purchase_action` | `purchases:orders/cancel` | `@require_permission` | **PASSED** |
| 15 | `/purchases/returns/` | `purchase_returns_list` | `purchases:returns/list` | `@require_permission` | **PASSED** |
| 16 | `/purchases/returns/create/` | `purchase_return_create` | `purchases:returns/create` | `@require_permission` | **PASSED** |
| 17 | `/purchases/returns/<id>/` | `purchase_return_detail` | `purchases:returns/view` | `@require_permission` | **PASSED** |
| 18 | `/purchases/returns/<id>/print/` | `purchase_return_print` | `purchases:returns/view` | `@require_permission` | **PASSED** |
| 19 | `/purchases/returns/<id>/action/<action>/` | `purchase_return_action` | `purchases:returns/action` | `@require_permission` | **PASSED** |
| 20 | `/purchases/returns/export/` | `purchase_returns_export` | `purchases:returns/export` | `@require_permission` | **PASSED** |
| **Sales App** | | | | | |
| 21 | `/sales/` | `sales_orders_list` | `sales:orders/list` | `@require_permission` + ABAC Scoping | **PASSED** |
| 22 | `/sales/create/` | `sales_order_create` | `sales:orders/create` | `@require_permission` | **PASSED** |
| 23 | `/sales/<id>/` | `sales_order_detail` | `sales:orders/view` | `@require_permission` + ABAC Check | **PASSED** |
| 24 | `/sales/<id>/action/approve/` | `sales_order_action` | `sales:orders/approve` | `@require_permission` | **PASSED** |
| 25 | `/sales/<id>/action/invoice/` | `sales_order_action` | `sales:orders/invoice` | `@require_permission` | **PASSED** |
| 26 | `/sales/<id>/action/cancel/` | `sales_order_action` | `sales:orders/cancel` | `@require_permission` | **PASSED** |
| 27 | `/sales/export/` | `sales_orders_export` | `sales:orders/export` | `@require_permission` + ABAC Scoping | **PASSED** |
| 28 | `/sales/collections/` | `collections_list` | `sales:collections/list` | `@require_permission` + ABAC Scoping | **PASSED** |
| 29 | `/sales/collections/create/` | `collection_create` | `sales:collections/create` | `@require_permission` | **PASSED** |
| 30 | `/sales/collections/export/` | `collections_export` | `sales:collections/export` | `@require_permission` | **PASSED** |
| 31 | `/sales/customers/<id>/accounting/` | `customer_accounting_view` | `sales:customers/accounting` | `@require_permission` | **PASSED** |
| 32 | `/sales/customers/<id>/transactions/`| `customer_transactions_view`| `sales:customers/transactions` | `@require_permission` | **PASSED** |
| **Catalog & Products App** | | | | | |
| 33 | `/catalog/products/` | `products_list` | `catalog:products/list` | `@require_permission` | **PASSED** |
| 34 | `/catalog/products/create/` | `product_create` | `catalog:products/create` | `@require_permission` | **PASSED** |
| 35 | `/catalog/products/<id>/` | `product_detail` | `catalog:products/view` | `@require_permission` | **PASSED** |
| 36 | `/catalog/products/<id>/edit/` | `product_edit` | `catalog:products/edit` | `@require_permission` | **PASSED** |
| 37 | `/catalog/products/<id>/delete/` | `product_delete` | `catalog:products/delete` | `@require_permission` | **PASSED** |
| 38 | `/catalog/products/export/` | `products_export` | `catalog:products/export` | `@require_permission` | **PASSED** |
| 39 | `/catalog/products/import/` | `product_import` | `catalog:products/import` | `@require_permission` | **PASSED** |
| 40 | `/catalog/products/import/template/` | `product_import_template` | `catalog:products/import` | `@require_permission` | **PASSED** |
| 41 | `/catalog/categories/` | `categories_list` | `catalog:categories/list` | `@require_permission` | **PASSED** |
| 42 | `/catalog/categories/<id>/edit/` | `category_edit` | `catalog:categories/edit` | `@require_permission` | **PASSED** |
| 43 | `/catalog/categories/<id>/delete/` | `category_delete` | `catalog:categories/delete` | `@require_permission` | **PASSED** |
| **Contacts & CRM App** | | | | | |
| 44 | `/contacts/` | `contacts_list` | `contacts:contacts/list` | `@require_permission` | **PASSED** |
| 45 | `/contacts/create/` | `contact_create` | `contacts:contacts/create` | `@require_permission` | **PASSED** |
| 46 | `/contacts/<id>/` | `contact_detail` | `contacts:contacts/view` | `@require_permission` | **PASSED** |
| 47 | `/contacts/<id>/edit/` | `contact_edit` | `contacts:contacts/edit` | `@require_permission` | **PASSED** |
| 48 | `/contacts/<id>/delete/` | `contact_delete` | `contacts:contacts/delete` | `@require_permission` | **PASSED** |
| 49 | `/contacts/<id>/toggle-status/` | `contact_toggle_status` | `contacts:contacts/edit` | `@require_permission` | **PASSED** |
| 50 | `/contacts/<id>/comment/` | `contact_add_comment` | `contacts:contacts/view` | `@require_permission` | **PASSED** |
| 51 | `/contacts/<id>/todo/` | `contact_add_todo` | `contacts:contacts/view` | `@require_permission` | **PASSED** |
| 52 | `/contacts/<id>/attachment/` | `contact_upload_attachment` | `contacts:contacts/view` | `@require_permission` | **PASSED** |
| 53 | `/contacts/<id>/address/` | `contact_add_address` | `contacts:contacts/edit` | `@require_permission` | **PASSED** |
| 54 | `/contacts/export/` | `contacts_export` | `contacts:contacts/export` | `@require_permission` | **PASSED** |
| 55 | `/contacts/import/` | `contacts_import` | `contacts:contacts/import` | `@require_permission` | **PASSED** |
| 56 | `/contacts/api/subareas/` | `subareas_api` | `contacts:contacts/view` | `@require_permission` | **PASSED** |
| 57 | `/contacts/api/search/` | `customer_search_api` | `contacts:contacts/view` | `@require_permission` | **PASSED** |
| **Activities & Visits App** | | | | | |
| 58 | `/agreements/` | `agreements_list` | `activities:agreements/list` | `@require_permission` | **PASSED** |
| 59 | `/agreements/create/` | `agreement_create` | `activities:agreements/create` | `@require_permission` | **PASSED** |
| 60 | `/agreements/<id>/` | `agreement_detail` | `activities:agreements/view` | `@require_permission` | **PASSED** |
| 61 | `/agreements/<id>/edit/` | `agreement_edit` | `activities:agreements/edit` | `@require_permission` | **PASSED** |
| 62 | `/agreements/<id>/delete/` | `agreement_delete` | `activities:agreements/delete` | `@require_permission` | **PASSED** |
| 63 | `/agreements/bulk-status/` | `agreements_bulk_status` | `activities:agreements/approve` | `@require_permission` | **PASSED** |
| 64 | `/agreements/<id>/action/<action>/`| `agreement_action` | `activities:agreements/approve` | `@require_permission` | **PASSED** |
| 65 | `/agreements/export/` | `agreements_export` | `activities:agreements/export` | `@require_permission` | **PASSED** |
| 66 | `/planned-visits/` | `planned_visits_list` | `activities:planned/list` | `@require_permission` + ABAC Scoping | **PASSED** |
| 67 | `/planned-visits/add-item/` | `planned_visit_add_item` | `activities:planned/manage` | `@require_permission` | **PASSED** |
| 68 | `/planned-visits/item/<id>/delete/`| `planned_visit_item_delete` | `activities:planned/manage` | `@require_permission` | **PASSED** |
| 69 | `/planned-visits/item/<id>/execute/`| `planned_visit_item_execute`| `activities:visits/create` | `@require_permission` + Rep Locking | **PASSED** |
| 70 | `/planned-visits/export/` | `planned_visits_export` | `activities:planned/export` | `@require_permission` | **PASSED** |
| 71 | `/visits/` | `visits_list` | `activities:visits/list` | `@require_permission` + ABAC Scoping | **PASSED** |
| 72 | `/visits/create/` | `visit_create` | `activities:visits/create` | `@require_permission` + GPS Validation | **PASSED** |
| 73 | `/visits/<id>/` | `visit_detail` | `activities:visits/detail` | `@require_permission` + ABAC Scoping | **PASSED** |
| 74 | `/visits/<id>/edit/` | `visit_edit` | `activities:visits/edit` | `@require_permission` | **PASSED** |
| 75 | `/visits/<id>/photo/` | `visit_evidence_photo` | `activities:visits/evidence` | `@require_permission` + Owner Streaming | **PASSED** |
| 76 | `/visits/<id>/action/<action>/` | `visit_action` | `activities:visits/approve` | `@require_permission` | **PASSED** |
| 77 | `/visits/export/` | `visits_export` | `activities:visits/export` | `@require_permission` + ABAC Scoping | **PASSED** |
| 78 | `/visit-templates/` | `visit_templates_list` | `activities:templates/view` | `@require_permission` | **PASSED** |
| 79 | `/visit-templates/create/` | `visit_template_create` | `activities:templates/create` | `@require_permission` | **PASSED** |
| 80 | `/visit-templates/<id>/edit/` | `visit_template_edit` | `activities:templates/edit` | `@require_permission` | **PASSED** |
| 81 | `/visit-templates/<id>/preview/`| `visit_template_preview` | `activities:templates/view` | `@require_permission` | **PASSED** |
| 82 | `/visit-templates/<id>/delete/` | `visit_template_delete` | `activities:templates/delete` | `@require_permission` | **PASSED** |
| 83 | `/visit-templates/<id>/toggle-status/`| `visit_template_toggle_status`| `activities:templates/edit`| `@require_permission` | **PASSED** |
| 84 | `/visit-templates/<id>/questions/add/`| `template_question_add`| `activities:templates/edit` | `@require_permission` | **PASSED** |
| 85 | `/visit-templates/questions/<id>/edit/`| `template_question_edit`| `activities:templates/edit`| `@require_permission` | **PASSED** |
| 86 | `/visit-templates/questions/<id>/delete/`| `template_question_delete`| `activities:templates/edit`| `@require_permission` | **PASSED** |
| 87 | `/visit-templates/questions/reorder/`| `template_questions_reorder`| `activities:templates/edit`| `@require_permission` | **PASSED** |
| **Inventory App** | | | | | |
| 88 | `/inventory/` | `inventory_stock_list` | `inventory:stocks/view` | `@require_permission` | **PASSED** |
| 89 | `/inventory/export/` | `inventory_stock_export` | `inventory:stocks/export` | `@require_permission` | **PASSED** |
| 90 | `/inventory/warehouses/` | `warehouses_list` | `inventory:warehouses/view` | `@require_permission` | **PASSED** |
| 91 | `/inventory/memos/` | `inventory_memos_list` | `inventory:memos/view` | `@require_permission` | **PASSED** |
| **Treasury App** | | | | | |
| 92 | `/treasury/payments/` | `vendor_payments_list` | `treasury:payments/list` | `@require_permission` | **PASSED** |
| 93 | `/treasury/payments/create/` | `vendor_payment_create` | `treasury:payments/create` | `@require_permission` | **PASSED** |
| 94 | `/treasury/payments/export/` | `vendor_payments_export` | `treasury:payments/export` | `@require_permission` | **PASSED** |
| 95 | `/treasury/vendors/accounting/`| `accounting_vendors_list`| `treasury:vendors/accounting`| `@require_permission` | **PASSED** |
| 96 | `/treasury/vendors/transactions/`| `vendor_transactions_list`| `treasury:vendors/transactions`| `@require_permission` | **PASSED** |
| 97 | `/treasury/vaults/` | `vaults_list` | `treasury:vaults/view` | `@require_permission` + Scoping | **PASSED** |
| 98 | `/treasury/vaults/<id>/transactions/`| `vault_transactions_list`| `treasury:vaults/transactions`| `@require_permission` | **PASSED** |
| 99 | `/treasury/payment-requests/` | `vendor_payment_requests_list`| `treasury:payments/requests`| `@require_permission` | **PASSED** |
| **Master Data & Settings App** | | | | | |
| 100| `/` (Home Dashboard) | `home_view` | `@login_required` | View Scoping & Rep Targeting | **PASSED** |
| 101| `/settings/branding/` | `branding_settings_view` | `settings:branding/edit` | `@require_permission` | **PASSED** |
| 102| `/settings/location/` | `location_settings_view` | `settings:location/manage` | `@require_permission` | **PASSED** |
| 103| `/settings/areas/` | `areas_settings_view` | `settings:areas/manage` | `@require_permission` | **PASSED** |
| 104| `/settings/expenses/` | `expenses_settings_view` | `settings:expenses/manage` | `@require_permission` | **PASSED** |
| 105| `/settings/tickets/` | `tickets_settings_view` | `settings:tickets/manage` | `@require_permission` | **PASSED** |
| 106| `/settings/requests/` | `requests_settings_view` | `settings:requests/manage` | `@require_permission` | **PASSED** |
| 107| `/settings/agreements/` | `agreements_settings_view` | `settings:agreements/manage` | `@require_permission` | **PASSED** |
| 108| `/settings/sales/` | `sales_settings_view` | `settings:sales/manage` | `@require_permission` | **PASSED** |
| 109| `/settings/purchase/` | `purchase_settings_view` | `settings:purchases/manage` | `@require_permission` | **PASSED** |
| 110| `/settings/inventory/` | `inventory_settings_view` | `settings:inventory/manage` | `@require_permission` | **PASSED** |
| 111| `/settings/contacts-udf/` | `contacts_udf_view` | `settings:contacts/manage` | `@require_permission` | **PASSED** |
| 112| `/settings/sync-data/` | `sync_data_view` | `settings:sync/manage` | `@require_permission` | **PASSED** |
| 113| `/settings/api/geofence/` | `geofence_settings_api` | `settings:location/manage` | `@require_permission` | **PASSED** |
| **Accounts & SuperAdmin RBAC** | | | | | |
| 114| `/auth/users/` | `users_list` | `system:users/view` | `@require_permission` | **PASSED** |
| 115| `/auth/users/create/` | `user_create` | `system:users/create` | `@require_permission` | **PASSED** |
| 116| `/auth/users/<id>/edit/` | `user_edit` | `system:users/edit` | `@require_permission` | **PASSED** |
| 117| `/auth/users/<id>/toggle-status/`| `user_toggle_status` | `system:users/edit` | `@require_permission` + Lockout Check | **PASSED** |
| 118| `/auth/users/<id>/reset-password/`| `user_reset_password_modal`| `system:users/edit`| `@require_permission` + Audit Log | **PASSED** |
| 119| `/auth/users/<id>/effective-permissions/`| `user_effective_permissions`| `system:users/view`| `@require_permission` | **PASSED** |
| 120| `/auth/roles/` | `roles_list` | `@require_super_admin` | `@require_super_admin` | **PASSED** |
| 121| `/auth/roles/create/` | `role_create` | `@require_super_admin` | `@require_super_admin` | **PASSED** |
| 122| `/auth/roles/<id>/edit/` | `role_edit` | `@require_super_admin` | `@require_super_admin` | **PASSED** |
| 123| `/auth/roles/<id>/delete/` | `role_delete` | `@require_super_admin` | `@require_super_admin` | **PASSED** |
| 124| `/settings/audit-logs/` | `audit_logs_list` | `@require_super_admin` | `@require_super_admin` | **PASSED** |
