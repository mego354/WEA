# ERP Master Implementation Roadmap & TODO

> **Status Dashboard**:
> - **COMPLETED**: 
>   - Phase 0 — Foundation & Architecture (Django Project, DB, Layout, Tailwind CSS, RBAC)
>   - Phase 1 — Master Data: Areas, Company Branding, Contacts (Suppliers & Customers)
>   - Phase 2 — Catalog: Products, Categories, Units, Pricing
>   - Phase 3 — Purchasing Engine (P0 Core): Purchase Orders, State Machine, Inward Memos, Invoicing, Print View
>   - Phase 4 — Treasury & Supplier Accounting (P0 Core): Cash Vaults, Vendor Ledgers, Disbursements, FIFO Settlements
>   - Phase 5 — Warehousing & Multi-Stock (P1): Warehouses, Real-time Stock, Inward/Outward Memos
>   - Phase 6 — Sales & Accounts Receivable (P1): Sales Orders Lifecycle, Stock Reservations, Delivery, Customer Ledgers, Collections
>   - Phase 7 — Executive Analytics: Real-time Dashboard KPIs, Financial Statements, Stock Valuation
>   - Verification: Automated E2E Workflows Test & Interactive Browser Tour (100% PASS)
> - **IN PROGRESS**: None
> - **NOT STARTED**: 
>   - Phase 8 — Secondary Workflows: Returns, Price Lists, Bundles, Adjustments (P2)
>   - Phase 9 — Field Activities & GPS Rep Tracking (P3)
> - **BLOCKED**: None

---

## Progress Overview

| Phase | Description | Priority | Status |
|---|---|---|---|
| **Phase 0** | Foundation: Django Project, DB, Layout, Tailwind CSS, RBAC | **P0** | **COMPLETED** |
| **Phase 1** | Master Data: Areas, Company Branding, Contacts (Suppliers/Customers) | **P0** | **COMPLETED** |
| **Phase 2** | Catalog: Products, Categories, Units, Pricing | **P0** | **COMPLETED** |
| **Phase 3** | Purchasing Engine: Purchase Orders, Lifecycle, Stocking, Invoicing | **P0** | **COMPLETED** |
| **Phase 4** | Treasury & Supplier Accounting: Vaults, Vendor Ledger, Payments, Settlements | **P0** | **COMPLETED** |
| **Phase 5** | Warehousing: Warehouses, Multi-warehouse stock, In/Out Memos | **P1** | **COMPLETED** |
| **Phase 6** | Sales & Distribution: Orders, Reservations, Invoicing, Collections | **P1** | **COMPLETED** |
| **Phase 7** | Reports & Analytics: Statements, Valuation, Executive KPIs | **P1** | **COMPLETED** |
| **Phase 8** | Secondary: Returns, Price Lists, Bundles, Adjustments | **P2** | **NOT STARTED** |
| **Phase 9** | Field Activities & GPS Rep Tracking (Optional/Extended) | **P3** | **NOT STARTED** |

---

## Detailed Task Breakdown

### Phase 0 — Foundation & Architecture
- [x] **0.1 Complete Discovery & Reverse-Engineering**: Map live pages, APIs, permissions, UI styles without mutations on reference ERP.
- [x] **0.2 Django Project Scaffold**: Initialize Django project with modular app structure (`accounts`, `master_data`, `contacts`, `catalog`, `purchases`, `inventory`, `treasury`, `sales`).
- [x] **0.3 Database Configuration**: MySQL engine (`enterprise_erp`) with PyMySQL and proper utf8mb4 encoding.
- [x] **0.4 Enterprise Design System**: Base HTML template with Cairo font, `#27bebe` teal brand tokens, collapsible sidebar, top navigation bar, Material icons, RTL support.
- [x] **0.5 Authentication & RBAC**: Custom User model, Role model, login/logout views, session management, permission decorators.

### Phase 1 — Master Data & Contacts (P0)
- [x] **1.1 Territory Master**: Areas & Governorates hierarchical models, list view, and API selector.
- [x] **1.2 Company Branding & Settings**: Company profile, tax numbers, logo, purchase & inventory global policies (`branding_settings.html`).
- [x] **1.3 Master Contacts**: Contact model supporting both suppliers and customers.
- [x] **1.4 Contact Directory UI**: List table with badges, search by name/serial, filter by relation (`vendor` vs `customer`), address modal (`contacts_list.html`).
- [x] **1.5 Supplier Statements**: Initial balance setup, credit limits, contact dossier view.

### Phase 2 — Catalog Master Data (P0)
- [x] **2.1 Categories**: Product categories with codes and descriptions (`categories_list.html`).
- [x] **2.2 Products**: SKU codes, retail prices, purchase costs, tax percentages, units (`products_list.html`).
- [x] **2.3 Catalog UI**: Product directory table, search, category filter, product creation form.

### Phase 3 — Purchasing Engine (P0 Core)
- [x] **3.1 Purchase Order Models**: `PurchaseOrder`, `PurchaseOrderItem`, financial calculation engine (Subtotal, Discounts, Tax, Shipping Fees, Grand Total).
- [x] **3.2 Purchase Order UI**: Order list view matching reference ERP table columns (`رقم المسلسل`, `الاسم`, `المنطقة`, `الحالة`, `اجمالى القيمة`, `المنشئ`).
- [x] **3.3 Purchase Order Creation Form**: Dynamic order line item builder with instant client-side and server-side calculation (`purchase_order_create.html`).
- [x] **3.4 Order Dossier Detail Page**: Complete detail page with status pill, supplier address, items table, and summary cards (`purchase_order_detail.html`).
- [x] **3.5 Order Lifecycle State Machine**:
  - `Pending` $\rightarrow$ `Approved` (Management approval)
  - `Approved` $\rightarrow$ `Picked` (Warehouse goods receipt & stock increment)
  - `Picked` $\rightarrow$ `Settled` (Vendor invoice posting)
  - `Settled` $\rightarrow$ `Picked` (Undo invoice reversal)
  - `Cancel` / `Uncancel`
- [x] **3.6 Inward Warehouse Memo Integration**: Automatically generate `InventoryMemo` when order is marked `Picked`.
- [x] **3.7 Print Template**: Clean invoice printing view for purchase orders (`purchase_order_print.html`).

### Phase 4 — Treasury & Supplier Accounting (P0 Core)
- [x] **4.1 Cash Vaults**: `Vault` model (Main Safe, Branch Safes, Rep Safes) with balance tracking (`vaults_list.html`).
- [x] **4.2 Vendor Ledger**: `VendorAccount` and `VendorTransaction` models for immutable double-entry credit/debit records (`vendor_transactions_list.html`).
- [x] **4.3 Automatic Invoicing**: When PO is settled, post credit transaction and create `VendorInstallment`.
- [x] **4.4 Vendor Payments**: Disbursement voucher form, deduct funds from selected vault, post debit to vendor ledger, match and create `Settlement` records (`vendor_payment_create.html`).
- [x] **4.5 Supplier Statement & Aging UI**: Statement view displaying running balances, open invoices, and overdue amounts (`accounting_vendors_list.html`).

### Phase 5 — Warehousing & Multi-Stock (P1)
- [x] **5.1 Warehouses Registry**: Warehouse listing and modal creation (`warehouses_list.html`).
- [x] **5.2 Inventory Balances**: Real-time stock view with on-hand, reserved, available, lot batches, and expiry dates (`stock_list.html`).
- [x] **5.3 Inventory Memos**: Inward (إضافة) and Outward (خصم) official vouchers (`memos_list.html`).

### Phase 6 — Sales & Accounts Receivable (P1)
- [x] **6.1 Sales Order Lifecycle**: `Pending` $\rightarrow$ `Manager Approval` $\rightarrow$ `Preparing` (Reserve stock) $\rightarrow$ `Delivered` (Unstock) $\rightarrow$ `Invoiced` (`sales_orders_list.html`, `sales_order_create.html`, `sales_order_detail.html`).
- [x] **6.2 Customer Collections**: Customer collections voucher, deposit to vault, credit customer ledger (`collections_list.html`, `collection_create.html`).
- [x] **6.3 Customer Balances & Statements**: Detailed ledger and running balance view (`accounting_customers_list.html`, `customer_transactions_list.html`).

### Phase 7 — Reports & Executive Analytics (P1)
- [x] **7.1 Executive Dashboard**: Real-time KPI summaries for purchases, payables, vault cash, stock valuation, and recent orders (`home.html`).
- [x] **7.2 Stock Valuation**: Automated calculation of weighted average cost and inventory valuation.
- [x] **7.3 Cash & Ledger Integrity**: Double-entry ledger audit trail for both suppliers and customers.
