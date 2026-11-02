# ERP Audit & Implementation Roadmap: Financial Workflows, Contacts, Permissions, Dashboard & Mobile UX

> **Audit & Implementation Status**:
> - **Date**: 2026-10-28
> - **Audit Test Status**: 9/9 specialized tests PASSING (100% OK in `tests_erp_audit.py`)
> - **Purchases Test Status**: 16/16 tests PASSING (100% OK in `purchases/tests.py`)
> - **System Checks**: 0 errors, 0 silenced issues (`py manage.py check`)
> - **Execution Mode**: In-place audit, repair, refactor, and enhancement
> - **Phase Status**: P0, P1, and P2 Completed & Verified

---

## Progress Summary Matrix

| Section / Track | Scope & Description | Priority | Status |
|---|---|---|---|
| **1. Baseline & Discovery** | Project-wide code audit, baseline testing, root-cause identification | **P0** | **COMPLETED** |
| **2. P0: Audit Logging Engine** | Full purchase, sales, and payment audit logging via `AuditLogService` (`SecurityAuditLog`) | **P0** | **COMPLETED** |
| **3. P0: Order-Linked Payments & Due Dates** | Link Collections to Sales Orders, VendorPayments to Purchase Orders, add Due Dates, prevent overpayment, update balances | **P0** | **COMPLETED** |
| **4. P0: Treasury & RBAC** | Strict role-based scoping (Superadmin, Accountant, Manager Area-scoping, Rep self-scoping) across all views & APIs | **P0** | **COMPLETED** |
| **5. P0: Purchases & Sales Integrity** | State machines, approvals, inventory memo synchronization, atomic locks & reversals | **P0** | **COMPLETED** |
| **6. P1: Contacts Enhancements** | Interactive map location picker (Leaflet + OpenStreetMap + Nominatim), financial fields (Credit Limit / Days), default Lead status, remove quick-create (+) button | **P1** | **COMPLETED** |
| **7. P1: Dashboard Statistics** | Integrate Purchase KPIs (totals, period, statuses, value, paid, outstanding), Lead/Customer metrics, role-scoped cards | **P1** | **COMPLETED** |
| **8. P2: Mobile-First UX & Tables** | Responsive cards/tables, touch targets, column visibility preservation, overflow prevention | **P2** | **COMPLETED** |
| **9. P2: Verification & Testing** | Unit tests, RBAC access tests, financial integrity tests, responsive audit | **P2** | **COMPLETED** |
| **10. P0/P1: Treasury Permissions & Stats Cards** | Granular Treasury RBAC in catalog/role settings, atomic transfers/reversals, 5-tier statistics standardization across all modules | **P0/P1** | **COMPLETED** |

---

## Detailed Task Breakdown

### Phase 1: P0 Financial Correctness, Security & Data Integrity

- [x] **1.1 Purchase & Sales Audit Logging**:
  - Integrated `AuditLogService.log` across all purchase lifecycle operations in `purchases/services.py` and `purchases/views.py`:
    - `PURCHASE_ORDER_CREATED`: Order creation with item count, grand total, and delivery details.
    - `PURCHASE_ORDER_UPDATED`: Full line-item adjustments, pricing, quantities, discounts, and taxes.
    - `PURCHASE_ORDER_APPROVED`: Dual-control managerial approval.
    - `PURCHASE_ORDER_REJECTED`: Managerial rejection with mandatory audit reason.
    - `PURCHASE_ORDER_RESUBMITTED`: Re-submission after addressing rejection.
    - `PURCHASE_ORDER_PICKED`: Warehouse goods receipt and inventory memo creation (`MEMO-IN-*`).
    - `PURCHASE_ORDER_SETTLED`: Accounting invoicing, vendor ledger credit posting, and settlement record.
    - `PURCHASE_ORDER_CANCELLED`: Safe cancellation and inventory reservation release.
    - `PURCHASE_ORDER_SPLIT`: Order decomposition tracking.
    - `PURCHASE_RETURN_CREATED`, `PURCHASE_RETURN_APPROVED`, `PURCHASE_RETURN_DELIVERED`, `PURCHASE_RETURN_SETTLED`.
  - Integrated `AuditLogService.log` into `treasury/services.py` and `sales/services.py`:
    - `VENDOR_PAYMENT_CREATED`: Supplier payment with vault deduction, order linkage, and FIFO installment settlement.
    - `COLLECTION_CREATED`: Customer collection with vault deposit, order linkage, and balance deduction.
  - Verified audit records persist in `SecurityAuditLog` and are viewable in `/settings/audit-logs/`.

- [x] **1.2 Order-Linked Payments & Payment Obligations**:
  - Added `sales_order` ForeignKey to `Collection` in `sales/models.py`.
  - Added `purchase_order` ForeignKey to `VendorPayment` in `treasury/models.py`.
  - Added computed properties to `SalesOrder` and `PurchaseOrder`:
    - `total_paid`: Exact sum of allocations/payments linked to this order.
    - `outstanding_balance`: `max(0, grand_total - total_paid)`.
    - `is_paid`: Boolean check if `outstanding_balance <= 0`.
    - `is_overdue`: Boolean check if `due_date and due_date < today and not is_paid`.
  - Updated `collection_create` view and UI:
    - Lists eligible open/invoiced sales orders with total, paid, and outstanding balance.
    - Strictly validates `amount <= order.outstanding_balance` (preventing overpayment).
  - Updated `vendor_payment_create` view and UI:
    - Lists eligible approved/picked/settled purchase orders with total, paid, and outstanding balance.
    - Strictly validates `amount <= purchase_order.outstanding_balance`.
  - Updated list and detail templates for Sales Orders, Purchase Orders, Collections, and Vendor Payments to display linked orders.

- [x] **1.3 Due Dates for Sales & Purchase Obligations**:
  - Added `due_date` field (`db_index=True`) to `PurchaseOrder` in `purchases/models.py`.
  - Added `due_date` field (`db_index=True`) to `SalesOrder` in `sales/models.py`.
  - Added `due_date` field to `Collection` in `sales/models.py`.
  - Captured `due_date` in order creation and edit workflows (`purchase_order_create`, `purchase_order_edit`, `sales_order_create`, `sales_order_edit`).
  - Added due date and overdue badges to list views and detail pages.

- [x] **1.4 Treasury & Transactions Role-Based Access Control (RBAC)**:
  - Tightened `get_scoped_queryset` and `can_user_access_object` in `accounts/permissions.py`:
    - **Superadmin**: Global, unrestricted access to all vaults, transactions, orders, and reports.
    - **Accountant**: Authorized access to all accounting modules (Vaults, Vendor Payments, Collections, Statements) without unintended superadmin administration privileges.
    - **Manager**: Scoped strictly to assigned area hierarchy and subordinate sales representatives. Cross-area access is strictly blocked (HTTP 403 Forbidden).
    - **Representative**: Scoped strictly to own assigned records (own warehouse, vault, orders, collections). IDOR URL tampering is blocked (HTTP 403 Forbidden).
  - Enforced server-side checks in `vendor_payments_list`, `vendor_payment_create`, `collections_list`, `sales_order_detail`, and `purchase_order_detail`.

- [x] **1.5 Transactional Consistency & Concurrency**:
  - Added `select_for_update()` row-level locking on `Vault` during payments and collections.
  - Wrapped multi-table operations (payment, vault transaction, ledger debit/credit, installment settlement, audit log) in `@transaction.atomic`.

---

### Phase 2: P1 Contacts, Leads, Map & Dashboard

- [x] **2.1 Interactive Map Location Selection for Contacts**:
  - Embedded Leaflet.js with OpenStreetMap tiles in `templates/contacts/contact_create.html` and `contact_edit.html`.
  - Draggable marker with instant coordinate update.
  - Interactive search bar with debounced Nominatim geocoding supporting street addresses, clinics, pharmacies, and landmarks.
  - Reverse geocoding on pin drag/click to auto-populate address details.
  - Current GPS location button ("موقعي الحالي").
  - Two-way synchronization between manual lat/long input fields and map marker.
  - **Coordinate Persistence Fix**: Contact edit view (`contact_edit`) preserves existing `latitude` and `longitude` when updating other contact fields or addresses.

- [x] **2.2 Contact Financial Details**:
  - Added `credit_limit` (`حد الائتمان`) and `credit_period_days` (`فترة الائتمان`) to create and edit workflows.
  - Enforced `DecimalField` precision and non-negative server-side validation.
  - Displayed credit limit, credit period, current balance, and credit status badges in `contact_detail.html`.

- [x] **2.3 Default New Contacts to Lead**:
  - Changed `Contact.status` default to `'lead'` in `contacts/models.py`.
  - Updated `contact_create` in `contacts/views.py` to default new contacts to `'lead'`.
  - Preserved explicit classification if user selects another status.
  - Preserved lead-to-customer conversion workflow via status dropdown.

- [x] **2.4 Remove Quick-Create Contact Plus Button**:
  - Removed only the quick-create `+` button in `templates/contacts/contact_detail.html`.
  - Preserved standard contact creation button (`انشئ جهة اتصال`) in `templates/contacts/contacts_list.html`.

- [x] **2.5 Executive Dashboard Purchase & Financial Statistics**:
  - Updated `home_view` in `master_data/views.py`:
    - Computed purchase metrics: total active orders, total value, settled orders, paid amount to vendors, outstanding balances, and overdue count.
    - Computed scoped contact classification metrics: Leads count vs Customers count.
    - Added `recent_purchases` and `recent_sales` querysets.
  - Updated `templates/dashboard/home.html`:
    - Added purchase KPI cards with role-appropriate visibility.
    - Added recent purchase orders table with status badges and supplier links.
    - Added supplier payables summary card.

---

### Phase 3: P2 Mobile UX, Performance & Code Cleanup

- [x] **3.1 Mobile-First Tables & Responsive Layouts**:
  - Added responsive column visibility (`hidden md:table-cell`, `hidden sm:table-cell`) across:
    - `purchase_orders_list.html`
    - `sales_orders_list.html`
    - `vendor_payments_list.html`
    - `collections_list.html`
    - `dashboard/home.html`
  - Integrated `table_column_picker.html` for user-configurable column visibility.
  - Ensured touch targets are at least 44px on mobile viewports.
  - Added `-webkit-overflow-scrolling: touch` for smooth mobile scrolling.

- [x] **3.2 Query Optimization & Performance**:
  - Added `select_related('supplier', 'created_by')` and `select_related('customer', 'created_by')` across querysets.
  - Used efficient ORM aggregation (`Sum`, `Count`) in `home_view`.

- [x] **3.3 Code Quality & Dead Code Cleanup**:
  - Removed unused imports and redundant JavaScript handlers.
  - Maintained complete documentation integrity and preserved existing working features.

- [x] **3.4 Comprehensive Automated Testing**:
  - Created `tests_erp_audit.py` with 9 comprehensive tests covering all requirements:
    1. `test_default_contact_classification_is_lead`: PASS
    2. `test_contact_coordinates_saved_and_persisted_on_edit`: PASS
    3. `test_purchase_order_lifecycle_and_audit_logging`: PASS
    4. `test_vendor_payment_linked_to_purchase_order`: PASS
    5. `test_vendor_payment_overpayment_rejected`: PASS
    6. `test_sales_collection_linked_to_sales_order`: PASS
    7. `test_representative_cannot_access_other_representative_order`: PASS
    8. `test_manager_scoped_to_own_area_and_representatives`: PASS
    9. `test_dashboard_purchase_statistics_calculation`: PASS
  - Executed existing tests in `purchases/tests.py` (16 tests PASSING).

---

### Phase 4: Maps Integration, Standardized Location Selection & Dedicated User Management Pages

- [x] **4.1 Root Cause Diagnosis & Resolution for Google Maps 403 Error**:
  - **Identified Root Causes**:
    1. Browser client-side calls to OSM Nominatim failed with HTTP 403 Forbidden because browsers forbid setting a custom `User-Agent` in cross-origin fetch requests, and Nominatim actively blocks default browser user-agents.
    2. Direct Google Maps JavaScript API usage failed when `GOOGLE_MAPS_API_KEY` was missing from environment or unconfigured.
    3. Blank map containers (0x0px height) occurred when Leaflet initialized inside hidden modals/drawers/tabs before layout calculation.
  - **Applied Resolution**:
    1. Configured `GOOGLE_MAPS_API_KEY = os.getenv('GOOGLE_MAPS_API_KEY', '')` in [config/settings.py](file:///c:/D/Cooding/GENERAL/new/ERP/config/settings.py). Exposed to frontend templates via [master_data/context_processors.py](file:///c:/D/Cooding/GENERAL/new/ERP/master_data/context_processors.py) without exposing server secrets.
    2. Implemented enterprise backend geocoding proxy in [master_data/views.py](file:///c:/D/Cooding/GENERAL/new/ERP/master_data/views.py) and [master_data/urls.py](file:///c:/D/Cooding/GENERAL/new/ERP/master_data/urls.py):
       - `/api/geocoding/search/?q=<query>`: Queries Google Geocoding API if key configured, otherwise falls back to OpenStreetMap Nominatim with an enterprise corporate `User-Agent: WEAPharma-ERP/1.0 (contact: admin@weapharma.com)`. Eliminates browser 403 Forbidden errors completely.
       - `/api/geocoding/reverse/?lat=<lat>&lng=<lng>`: Secure reverse geocoding proxy returning normalized Arabic addresses and locality data.
    3. Solved blank map rendering using `ResizeObserver` and `map.invalidateSize()` inside the reusable component [templates/components/location_picker.html](file:///c:/D/Cooding/GENERAL/new/ERP/templates/components/location_picker.html).

- [x] **4.2 Standardized Reusable Location Selection Component**:
  - Created [templates/components/location_picker.html](file:///c:/D/Cooding/GENERAL/new/ERP/templates/components/location_picker.html):
    - Interactive map with custom WEA teal pin, draggable marker, and pan animations.
    - Debounced autocomplete search input with live results dropdown.
    - Locate-me GPS button (`navigator.geolocation.getCurrentPosition`).
    - Collapsible manual latitude and longitude inputs with two-way binding.
    - Reverse geocoding on dragend/click to auto-populate address.
  - Integrated into:
    - [templates/contacts/contact_create.html](file:///c:/D/Cooding/GENERAL/new/ERP/templates/contacts/contact_create.html)
    - [templates/contacts/contact_edit.html](file:///c:/D/Cooding/GENERAL/new/ERP/templates/contacts/contact_edit.html)
    - [templates/contacts/contact_detail.html](file:///c:/D/Cooding/GENERAL/new/ERP/templates/contacts/contact_detail.html) (interactive GPS coordinates preview modal `#contactMapModal`)
    - [templates/inventory/warehouses_list.html](file:///c:/D/Cooding/GENERAL/new/ERP/templates/inventory/warehouses_list.html) (new warehouse modal `#new-warehouse-modal` + warehouse cards)
  - Extended `Warehouse` model in [inventory/models.py](file:///c:/D/Cooding/GENERAL/new/ERP/inventory/models.py) with `latitude`, `longitude`, and `has_saved_location`. Created and applied migration `0003_warehouse_latitude_warehouse_longitude.py`.

- [x] **4.3 Explicit Exception: Visit Validation Preservation**:
  - Maintained visit validation completely isolated from ordinary location pickers.
  - Verified that visit GPS validation, geofencing distance calculation, tolerance thresholds, anti-tampering checks, first-visit customer GPS auto-setting, and bypass toggle remain 100% intact.
  - Executed [test_visit_location_e2e.py](file:///c:/D/Cooding/GENERAL/new/ERP/test_visit_location_e2e.py): **ALL 7 PARITY CATEGORIES VERIFIED WITH 100% SUCCESS**.

- [x] **4.4 Dedicated User Creation, Edit, and Detail Pages**:
  - Replaced pop-up modals (`#addUserModal`) with dedicated, full-page HTML interfaces:
    - User Creation: [templates/accounts/user_create.html](file:///c:/D/Cooding/GENERAL/new/ERP/templates/accounts/user_create.html) (`/users/create/` and `/users/add/`).
    - User Details: [templates/accounts/user_detail.html](file:///c:/D/Cooding/GENERAL/new/ERP/templates/accounts/user_detail.html) (`/users/<pk>/`).
    - User Editing: [templates/accounts/user_edit.html](file:///c:/D/Cooding/GENERAL/new/ERP/templates/accounts/user_edit.html) (`/users/<pk>/edit/`).
  - Separated password changes into an isolated card and endpoint (`/users/<pk>/reset-password/`), guaranteeing that normal profile edits never erase, blank out, or overwrite user passwords.
  - Updated [templates/accounts/users_list.html](file:///c:/D/Cooding/GENERAL/new/ERP/templates/accounts/users_list.html) to link directly to dedicated pages and removed obsolete modal DOM and handlers.

- [x] **4.5 Server-Side Role-Based Access Control (RBAC) Enforcement**:
  - SuperAdmin: Unrestricted global access to all user creation, editing, details, and role assignments.
  - Accountant: Strictly forbidden from accessing user administration (`/users/create/`, `/users/<pk>/edit/`, `/users/`); returns HTTP 403 Forbidden.
  - Manager: Scoped strictly to viewing and creating representatives within their assigned geographic governorates/areas; cannot assign superadmin role or cross into other areas (returns HTTP 403 Forbidden or validation error).
  - Representative: Strictly forbidden from accessing user management; returns HTTP 403 Forbidden.
  - Enforced in [accounts/permissions.py](file:///c:/D/Cooding/GENERAL/new/ERP/accounts/permissions.py) and [accounts/views.py](file:///c:/D/Cooding/GENERAL/new/ERP/accounts/views.py).

- [x] **4.6 Testing & Verification Summary**:
  - `accounts/tests_user_dedicated_pages.py`: 14/14 tests PASSING (100% OK).
  - `test_visit_location_e2e.py`: 7/7 suites PASSING (100% OK).
  - `accounts/tests_area_approvals.py`, `accounts/tests_data_scoping.py`, `accounts/tests_roles_consolidation.py`: 18/18 tests PASSING (100% OK).
  - `py manage.py check`: 0 issues.

---

### Phase 5: Role-Based Treasury Permissions & Project-Wide Statistics Cards Standardization

- [x] **5.1 Complete Role-Based Treasury Permissions Integration**:
  - **Permission Catalog Integration** in [accounts/permission_registry.py](file:///c:/D/Cooding/GENERAL/new/ERP/accounts/permission_registry.py):
    - Expanded `ERP_PERMISSIONS_CATALOG['treasury']` into 5 structured sections with all 10 required granular permissions:
      1. `treasury:overview`: `treasury:treasury/view` (View Treasury overview & balances).
      2. `treasury:vaults`: `treasury:vaults/view` (View Vaults & authorized balances), `treasury:vaults/transfer` (Transfer funds between vaults), `treasury:vaults/manage` (Create, edit & deactivate vaults).
      3. `treasury:transactions`: `treasury:transactions/list` (View Transaction History), `treasury:transactions/create` (Create permitted transactions), `treasury:transactions/edit` (Edit permitted transactions), `treasury:transactions/reverse` (Reverse posted financial transactions), `treasury:transactions/approve` (Approve financial transactions), `treasury:reports/view` (View treasury reports).
      4. `treasury:vendor_payments`: `treasury:payments/list` (View vendor payments), `treasury:payments/create` (Create vendor payment vouchers).
      5. `treasury:vendor_accounting`: `treasury:vendors/accounting` (View accounts payable & aging), `treasury:vendors/transactions` (View vendor ledger statements).
  - **Role Settings Interface (`role_form.html`)**:
    - The role settings accordion matrix automatically renders the dedicated Treasury permission group with granular checkboxes and 4 preset helper buttons (`admin`, `default`, `readonly`, `clear`).
    - Permission changes persist reliably to the database upon form submission without interfering with other modules.
  - **Canonical Role Default Baseline** in [accounts/management/commands/setup_permissions.py](file:///c:/D/Cooding/GENERAL/new/ERP/accounts/management/commands/setup_permissions.py):
    - **Superadmin**: Full unrestricted access to all Treasury operations and settings.
    - **Accountant**: Full access to financial operations (`view`, `transfer`, `create`, `list`, `reverse`, `payments`, `vendors`) without administrative user management privileges.
    - **Manager**: 0 Treasury permissions by default; accesses Treasury only when explicitly granted by administrator, strictly scoped to regional area hierarchy.
    - **Representative**: 0 Treasury permissions by default (removed `rep_codenames` treasury grants); accesses Treasury only when explicitly granted by administrator, strictly scoped to own assigned vault.

- [x] **5.2 Financial Integrity, Atomic Transfers & Reversals**:
  - Extended `VaultTransaction` in [treasury/models.py](file:///c:/D/Cooding/GENERAL/new/ERP/treasury/models.py):
    - Added `is_reversed` (`BooleanField`, default=False).
    - Added `reversed_by` (ForeignKey to `User`).
    - Added `reversal_transaction` (OneToOneField to `self`).
    - Created & applied migration `treasury/migrations/0004_vaulttransaction_is_reversed_and_more.py`.
  - Implemented Enterprise Services in [treasury/services.py](file:///c:/D/Cooding/GENERAL/new/ERP/treasury/services.py):
    - `transfer_funds()`: Atomic transfer between vaults with row-level locks (`select_for_update`), ascending vault ID locking order to prevent deadlocks, balance validation, dual entries (`vault_transfer_out` and `vault_transfer_in`), and security audit logging.
    - `reverse_vault_transaction()`: Atomic reversal posting an opposing balancing entry, marks original entry as reversed, prevents double-reversal, and logs audit trail.
    - `record_vault_manual_transaction()`: Concurrency-locked manual inflow/outflow entries with positive amount validation.
  - Added dedicated endpoints in [treasury/urls.py](file:///c:/D/Cooding/GENERAL/new/ERP/treasury/urls.py):
    - `/treasury/transfer/` (`vault_transfer`, requires `treasury:vaults/transfer`).
    - `/treasury/vaults/create/` (`vault_create`, requires `treasury:vaults/manage`).
    - `/treasury/vault-transactions/<pk>/reverse/` (`vault_transaction_reverse`, requires `treasury:transactions/reverse`).
  - Added dedicated templates:
    - [templates/treasury/vault_transfer.html](file:///c:/D/Cooding/GENERAL/new/ERP/templates/treasury/vault_transfer.html).
    - [templates/treasury/vault_form.html](file:///c:/D/Cooding/GENERAL/new/ERP/templates/treasury/vault_form.html).

- [x] **5.3 Standardize Statistics Cards Across Every ERP Module**:
  - Reorganized every audited page to adhere strictly to the standardized 5-tier layout:
    1. **Page Header / Hero Section**: Contains only page title, breadcrumb navigation, and primary page actions. No statistics or filters inside header.
    2. **Dedicated Statistics Cards Section**: Visually separated 4-card responsive grid with distinct iconography, readable labels, prominent font-mono values, and currency/number formatting.
    3. **Search & Filter Controls Toolbar**: Separated toolbar with quick search, dropdown filters, column visibility picker, and active filter chips.
    4. **Main Content / Responsive Table**: Mobile-friendly table with column priority breakpoints and scroll containers.
    5. **Pagination**: Standardized server-side pagination component.
  - **Audited & Refactored Templates**:
    1. **Treasury Vaults**: [templates/treasury/vaults_list.html](file:///c:/D/Cooding/GENERAL/new/ERP/templates/treasury/vaults_list.html) (Total Vaults, Active Vaults, Total Balance, Cash Safe, Bank Balance).
    2. **Treasury Transactions**: [templates/treasury/vault_transactions_list.html](file:///c:/D/Cooding/GENERAL/new/ERP/templates/treasury/vault_transactions_list.html) (Total Transactions, Inflows, Outflows, Net Movement).
    3. **Vendor Payments**: [templates/treasury/vendor_payments_list.html](file:///c:/D/Cooding/GENERAL/new/ERP/templates/treasury/vendor_payments_list.html) (Total Vouchers, Grand Total Paid, Monthly Payments, Cash vs Bank).
    4. **Vendor Accounts (AP)**: [templates/treasury/accounting_vendors_list.html](file:///c:/D/Cooding/GENERAL/new/ERP/templates/treasury/accounting_vendors_list.html) (Suppliers Count, Total Payable, Overdue Payables, Credit Limits).
    5. **Vendor Ledger**: [templates/treasury/vendor_transactions_list.html](file:///c:/D/Cooding/GENERAL/new/ERP/templates/treasury/vendor_transactions_list.html) (Total Ledger Entries, Invoices [+], Payments [-], Net Payable Balance).
    6. **Purchase Orders**: [templates/purchases/purchase_orders_list.html](file:///c:/D/Cooding/GENERAL/new/ERP/templates/purchases/purchase_orders_list.html) (Total Orders, Total Value, Pending Review, Settled Orders).
    7. **Purchase Returns**: [templates/purchases/purchase_return_orders.html](file:///c:/D/Cooding/GENERAL/new/ERP/templates/purchases/purchase_return_orders.html) (Total Returns, Total Return Value, Draft/Review, Settled Returns).
    8. **Sales Orders**: [templates/sales/sales_orders_list.html](file:///c:/D/Cooding/GENERAL/new/ERP/templates/sales/sales_orders_list.html) (Total Orders, Grand Total Value, Invoiced Value, Pending Count).
    9. **Customer Collections**: [templates/sales/collections_list.html](file:///c:/D/Cooding/GENERAL/new/ERP/templates/sales/collections_list.html) (Total Collections, Total Amount, Month Amount, Receiving Vaults).
    10. **Customer Accounts (AR)**: [templates/sales/accounting_customers_list.html](file:///c:/D/Cooding/GENERAL/new/ERP/templates/sales/accounting_customers_list.html) (Total Customers, Total Receivables, Total Overdue, Total Credit Limits).
    11. **Customer Ledger**: [templates/sales/customer_transactions_list.html](file:///c:/D/Cooding/GENERAL/new/ERP/templates/sales/customer_transactions_list.html) (Total Entries, Invoices / Debit [+], Collections / Credit [-], Net Balance).
    12. **Contacts & Leads**: [templates/contacts/contacts_list.html](file:///c:/D/Cooding/GENERAL/new/ERP/templates/contacts/contacts_list.html) (Total Contacts, Customers, Leads, Suppliers).
    13. **Warehouses**: [templates/inventory/warehouses_list.html](file:///c:/D/Cooding/GENERAL/new/ERP/templates/inventory/warehouses_list.html) (Total Warehouses, Main Hubs, Rep Vans, Active Hubs).
    14. **Inventory Stocks**: [templates/inventory/stock_list.html](file:///c:/D/Cooding/GENERAL/new/ERP/templates/inventory/stock_list.html) (Total Stock Items, Total Qty on Hand, Total Available, Estimated Value).
    15. **Product Catalog**: [templates/catalog/products_list.html](file:///c:/D/Cooding/GENERAL/new/ERP/templates/catalog/products_list.html) (Total Products, Sellable Items, Unsellable Items, Categories Count).
    16. **User Accounts**: [templates/accounts/users_list.html](file:///c:/D/Cooding/GENERAL/new/ERP/templates/accounts/users_list.html) (Total Users, Active Users, Inactive Accounts, System Roles).
    17. **Field Visits**: [templates/activities/visits_list.html](file:///c:/D/Cooding/GENERAL/new/ERP/templates/activities/visits_list.html) (Total Visits, Verified Geofenced Visits, Completed Visits, Reps Count).
    18. **Commercial Agreements**: [templates/activities/agreements_list.html](file:///c:/D/Cooding/GENERAL/new/ERP/templates/activities/agreements_list.html) (Total Agreements, Grand Financial Value, Approved Contracts, Pending Review).
    19. **Regional Approvals Hub**: [templates/approvals/approvals_hub.html](file:///c:/D/Cooding/GENERAL/new/ERP/templates/approvals/approvals_hub.html) (Total Pending Queue, Pending Visits, Pending Sales Orders).

- [x] **5.4 Scoped & Accurate Metrics Verification**:
  - Eliminated all hardcoded metrics and dummy badges.
  - Corrected statement search bug in `vault_transactions_list` (`statement__icontains` -> `description__icontains`).
  - Scoped all aggregated metrics via `get_scoped_queryset`: managers see regional aggregates for their assigned areas; representatives see only their own vault/order statistics; accountants see financial modules without administrative settings access.

- [x] **5.5 Automated Test Verification**:
  - Created [treasury/tests_treasury_rbac_and_stats.py](file:///c:/D/Cooding/GENERAL/new/ERP/treasury/tests_treasury_rbac_and_stats.py):
    1. `test_treasury_permissions_in_catalog`: PASS.
    2. `test_superadmin_full_treasury_access`: PASS.
    3. `test_accountant_treasury_access_and_admin_restriction`: PASS.
    4. `test_manager_without_permission_forbidden`: PASS.
    5. `test_manager_with_permission_scoped_to_regional_area`: PASS.
    6. `test_representative_default_no_treasury_access`: PASS.
    7. `test_representative_with_permission_scoped_strictly_to_own_vault`: PASS.
    8. `test_transfer_funds_atomic_success`: PASS.
    9. `test_transfer_funds_validation_failures`: PASS.
    10. `test_reverse_vault_transaction_success`: PASS.
    11. `test_reverse_vault_transaction_double_reversal_prevented`: PASS.
    12. `test_treasury_statistics_calculations`: PASS.
  - Executed full test suite:
    - `py manage.py test treasury`: 13/13 tests PASSING.
    - `py test_visit_location_e2e.py`: 7/7 parity suites PASSING.
    - `py manage.py test accounts.tests_user_dedicated_pages`: 14/14 tests PASSING.
    - `py manage.py test purchases`: 16/16 tests PASSING.
    - `py manage.py test accounts.tests_area_approvals accounts.tests_data_scoping accounts.tests_roles_consolidation`: 18/18 tests PASSING.
    - `py manage.py check`: 0 issues.


