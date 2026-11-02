# Excel Import/Export Comprehensive Audit & Technical Specification

**Project:** WEA Pharma ERP  
**Audit & Implementation Date:** 2026-10-15  
**Author:** Antigravity Senior Engineering Team  
**Scope:** Complete inventory of all existing export endpoints, buttons, formats, import capabilities, missing import/export workflows, and the technical specification for genuine `.xlsx` Excel processing using `openpyxl`.  
**Status:** **100% AUDITED & IMPLEMENTED**

---

## 1. Executive Summary

A comprehensive code and template audit of the entire ERP repository was conducted.  
1. **Replaced Exports:** All legacy CSV endpoints producing `text/csv` were completely upgraded to genuine `.xlsx` Excel format via a centralized, secure openpyxl engine (`master_data.excel_utils`).
2. **Newly Added Exports:** Excel exports were introduced to all previously uncovered core business modules (Sales Orders, Collections, Inventory Stock, Vendor Payments).
3. **Full 6-Step Web Import Workflows:** Implemented for Products and Contacts (Customers/Suppliers) with file validation, column mapping, live dry-run preview, mode selection (`create_only`, `update_only`, `create_and_update`), atomic database transactions, error summaries, and downloadable sample templates.
4. **Security & Formatting:** Right-to-Left (RTL) Arabic worksheet layout enabled, `#27bebe` brand teal styling, formula injection defense, numeric/date preservation, and permission enforcement.

---

## 2. Complete Inventory of Export Endpoints & Templates

### A. All Active Excel (.xlsx) Export Endpoints

| Module | URL Name | Endpoint | Previous Format | Current Format | Status | Security & Formatting |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Catalog** | `products_export` | `/catalog/export/` | CSV (`text/csv`) | **Excel (.xlsx)** | **COMPLETED** | Styled teal `#27bebe` headers, RTL view, formula injection sanitization, numeric price/cost, active filters preserved. |
| **Contacts** | `contacts_export` | `/contacts/export/` | CSV (`text/csv`) | **Excel (.xlsx)** | **COMPLETED** | Styled teal headers, RTL view, mobile/phone preservation, credit limits as numbers, active search/relation filters. |
| **Purchases** | `purchase_orders_export` | `/purchases/export/` | CSV (`text/csv`) | **Excel (.xlsx)** | **COMPLETED** | Formatted dates, numeric grand totals, supplier details, status in Arabic, filter preservation. |
| **Purchases** | `purchase_return_orders_export` | `/purchases/returns/export/` | CSV (`text/csv`) | **Excel (.xlsx)** | **COMPLETED** | Return order numbers, return dates, warehouse, net totals as numbers, status preservation. |
| **Sales** | `sales_orders_export` | `/sales/export/` | *None* | **Excel (.xlsx)** | **COMPLETED** | Order number, customer name, date, warehouse, grand total, status, and creator. |
| **Sales** | `collections_export` | `/sales/collections/export/` | *None* | **Excel (.xlsx)** | **COMPLETED** | Collection serial, customer name, vault, amount (EGP), payment method, date. |
| **Inventory** | `inventory_stock_export` | `/inventory/export/` | *None* | **Excel (.xlsx)** | **COMPLETED** | Product name, SKU, warehouse, on-hand qty, reserved qty, unit cost, total valuation. |
| **Treasury** | `vendor_payments_export` | `/treasury/payments/export/` | *None* | **Excel (.xlsx)** | **COMPLETED** | Payment voucher serial, supplier name, vault, amount (EGP), payment method, status. |

### B. UI Export & Import Buttons Inventory

| Template | Action | Previous Label | Current Label | Link Target | Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `templates/catalog/products_list.html` | Export | `تصدير CSV` | `تصدير إلى Excel` | `{% url 'products_export' %}` | **COMPLETED** |
| `templates/catalog/products_list.html` | Import | *None* | `استيراد Excel` | `{% url 'product_import' %}` | **COMPLETED** |
| `templates/contacts/contacts_list.html` | Export | `تصدير البيانات` | `تصدير إلى Excel` | `{% url 'contacts_export' %}` | **COMPLETED** |
| `templates/contacts/contacts_list.html` | Import | *None* | `استيراد Excel` | `{% url 'contacts_import' %}` | **COMPLETED** |
| `templates/purchases/purchase_orders_list.html` | Export | `تصدير CSV` | `تصدير إلى Excel` | `{% url 'purchase_orders_export' %}` | **COMPLETED** |
| `templates/purchases/purchase_return_orders.html` | Export | `تصدير CSV` | `تصدير إلى Excel` | `{% url 'purchase_return_orders_export' %}` | **COMPLETED** |
| `templates/sales/sales_orders_list.html` | Export | *None* | `تصدير إلى Excel` | `{% url 'sales_orders_export' %}` | **COMPLETED** |
| `templates/sales/collections_list.html` | Export | *None* | `تصدير إلى Excel` | `{% url 'collections_export' %}` | **COMPLETED** |
| `templates/inventory/stock_list.html` | Export | *None* | `تصدير إلى Excel` | `{% url 'inventory_stock_export' %}` | **COMPLETED** |
| `templates/treasury/vendor_payments_list.html` | Export | *None* | `تصدير إلى Excel` | `{% url 'vendor_payments_export' %}` | **COMPLETED** |

---

## 3. Inventory of Import Functionality

### A. Implemented Web Excel Import Modules

1. **Catalog (Products Import Workflow)**:
   - **Upload & Execute URL:** `/catalog/import/` (`product_import`)
   - **Downloadable Sample Template:** `/catalog/import/template/` (`product_import_template`)
   - **Target Models:** `catalog.models.Product`, `catalog.models.ProductCategory`
   - **Supported Columns:** SKU Code, Product Name, Category, Retail Price, Purchase Cost, Tax %, Sellable, Barcode, Unit, Description.
   - **Validation Rules:**
     - SKU Code and Product Name required.
     - Decimal numbers validated for retail price, purchase cost, and tax percentage.
     - Auto category creation or assignment by name/code.
     - Duplicate detection within uploaded workbook and against existing database.
   - **Execution Modes:** `create_and_update` (default), `create_only`, `update_only`.
   - **Status:** **COMPLETED & VERIFIED**

2. **Contacts (Customers & Suppliers Import Workflow)**:
   - **Upload & Execute URL:** `/contacts/import/` (`contacts_import`)
   - **Downloadable Sample Template:** `/contacts/import/template/` (`contacts_import_template`)
   - **Target Models:** `contacts.models.Contact`, `contacts.models.ContactAddress`, `master_data.models.Area`, `sales.models.CustomerAccount`, `treasury.models.VendorAccount`
   - **Supported Columns:** Serial Number, Name, Relation Type (عميل / مورد / كلاهما), Mobile, Phone, Area, Detailed Street Address, Credit Limit, Category, Specialty, Tax ID, Code.
   - **Validation Rules:**
     - Contact Name required.
     - Duplicate mobile or serial numbers detected and flagged.
     - Auto Area resolution and creation.
     - Automatic initialization of `CustomerAccount` for customers and `VendorAccount` for suppliers.
   - **Execution Modes:** `create_and_update` (default), `create_only`, `update_only`.
   - **Status:** **COMPLETED & VERIFIED**

---

## 4. Technical Architecture: Reusable Excel Core

All operations leverage `master_data/excel_utils.py`:

- **MIME Type:** `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`
- **File Extension:** `.xlsx`
- **Security / Formula Injection Defense:**
  - Prefixes `'` to any string starting with `=`, `+`, `-`, `@`, `\t`, `\r`.
- **RTL Support:**
  - Sets `ws.sheet_view.rightToLeft = True` natively for Arabic spreadsheet users.
- **Styling Standards:**
  - Header Row: Background `#27BEBE` (Teal), Font White Bold Cairo/Calibri, Centered, Height 26pt.
  - Alternating Rows: Clean white and subtle slate tint `#F8FAFC`.
  - Borders: Thin light-gray borders (`#E2E8F0`).
  - Auto Column Width: Dynamic based on maximum cell content length + padding.
- **Transactional Integrity:**
  - Wrapped inside `transaction.atomic()` ensuring zero partial data corruption upon any unexpected failure.
