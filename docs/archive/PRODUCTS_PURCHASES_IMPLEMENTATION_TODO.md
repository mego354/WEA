# Products & Purchases Implementation Master TODO

> **System**: WEA Pharma / Bricks Rep ERP  
> **Source Base URL**: `https://weapharma.bricks-rep.com/`  
> **Scope**: Products (`المنتجات`) and Purchases (`المشتريات`) Complete Parity  
> **Status**: Living Execution Tracker  

---

## 1. Priority P0: Core Products, Procurement & Return Workflows

### 1.1 Products Catalog & Categories (P0)
- [x] **Page Audit & Inventory**: Documented catalog columns, filters, form fields, and category modal in `PRODUCTS_PURCHASES_PAGE_INVENTORY.md`. `[COMPLETED]`
- [x] **Products List View (`/products/`)**:
  - [x] Dense RTL AG-Grid layout with teal `#27bebe` branding. `[COMPLETED]`
  - [x] Name with thumbnail, SKU code, Category badge, Retail price, Tax, Sellable checkmark, Barcode. `[COMPLETED]`
  - [x] Action menu (`more_vert`) for details, edit, deactivate. `[COMPLETED]`
  - [x] Slide-out filter drawer with category, price range, sellable toggle. `[COMPLETED]`
  - [x] Pagination (40 per page, range indicator). `[COMPLETED]`
  - [x] CSV Export endpoint (`/products/export/`). `[COMPLETED]`
- [x] **Product Creation & Edit (`/products/create/`, `/products/<id>/edit/`)**:
  - [x] Name, Category, SKU, Barcode, Retail Price, Tax %, Default Cost, Unit, Sellable switch. `[COMPLETED]`
  - [x] Volume Discounts toggle and configuration. `[COMPLETED]`
  - [x] Packaging fields (Boxes, Cartons). `[COMPLETED]`
  - [x] Image file upload and preview. `[COMPLETED]`
- [x] **Product Category Management (`/product-categories/`)**:
  - [x] Listing categories with code, name, description, timestamps. `[COMPLETED]`
  - [x] Create category modal dialog with AJAX/POST submission. `[COMPLETED]`
  - [x] Edit category modal dialog and Delete category with safety check. `[COMPLETED]`
- [x] **Product Detail View (`/products/<id>/`)**:
  - [x] Basic detail view with catalog specs. `[COMPLETED]`
  - [x] Fix `s.quantity_on_hand` bug to use `s.qty_on_hand` for warehouse breakdown. `[COMPLETED]`
  - [x] Display packaging breakdown, volume discounts, and price lists. `[COMPLETED]`

---

### 1.2 Purchase Orders Procurement Engine (P0)
- [x] **Purchase Orders List (`/purchase-orders/`)**:
  - [x] Columns: Serial `#`, Supplier, Area, Created At, Creator, Status, Grand Total, Delivery Agent, Delivery Time. `[COMPLETED]`
  - [x] Color-coded badges for statuses: `Pending`, `Approved`, `Picked`, `Settled`, `Rejected`, `Split`, `Cancelled`. `[COMPLETED]`
  - [x] Slide-out filter drawer (Supplier, status, date range). `[COMPLETED]`
  - [x] CSV Data export (`/purchase-orders/export/`). `[COMPLETED]`
- [x] **Purchase Order Creation Flow (`/purchase-orders/create/`)**:
  - [x] Supplier selection with search. `[COMPLETED]`
  - [x] Destination warehouse selection. `[COMPLETED]`
  - [x] Dynamic item repeater (Product, Unit cost, Quantity, Batch, Expiry, Discount %). `[COMPLETED]`
  - [x] Order discount %, shipping fees, and live total calculation. `[COMPLETED]`
  - [x] Transactional creation and validation. `[COMPLETED]`
- [x] **Purchase Order Dossier & Lifecycle (`/purchase-orders/<id>/`)**:
  - [x] Order summary header with status dropdown and Undo Invoice button. `[COMPLETED]`
  - [x] Line items table with batch numbers and expiration dates. `[COMPLETED]`
  - [x] Linked Warehouse Inward Memo card. `[COMPLETED]`
  - [x] Linked Accounting card with invoice status and settlement history. `[COMPLETED]`
  - [x] Supplier financial card with balance and credit limit. `[COMPLETED]`
  - [x] File attachments upload and comments stream. `[COMPLETED]`
  - [x] Official printable receipt voucher (`/purchase-orders/<id>/print/`). `[COMPLETED]`
  - [x] Split Order modal dialog and execution. `[COMPLETED]`
- [x] **Procurement Services & Inventory/Accounting Integration**:
  - [x] Manager approval transition (`approved`). `[COMPLETED]`
  - [x] Physical goods receipt stocking (`picked`) with weighted average cost calculation. `[COMPLETED]`
  - [x] Double-entry invoice posting (`settled`) creating `VendorTransaction` and `VendorInstallment`. `[COMPLETED]`
  - [x] Undo Invoice (`الغاء الفاتورة`) reverting to `picked` with offsetting reversal entry. `[COMPLETED]`
  - [x] Order cancellation before stocking. `[COMPLETED]`

---

### 1.3 Purchase Return Orders Module (P0 - Immediate Parity Goal)
- [x] **Database Architecture**:
  - [x] Create `PurchaseReturnOrder` model with serials, supplier, warehouse, status, and financial totals. `[COMPLETED]`
  - [x] Create `PurchaseReturnOrderItem` model with product, quantity, unit price, batch, and expiry. `[COMPLETED]`
  - [x] Database migrations execution (`purchases.0003`). `[COMPLETED]`
- [x] **Business Services (`PurchaseReturnOrderService`)**:
  - [x] `create_return_order`: Validate supplier, warehouse, items, quantities, and totals. `[COMPLETED]`
  - [x] `approve_return_order`: Advance from `pending` to `approved`. `[COMPLETED]`
  - [x] `deliver_return_order` (Physical Unstocking):
    - Generate outward `InventoryMemo` (`MEMO-OUT-RO-{serial}`).
    - Decrement `InventoryStock.qty_on_hand` at the originating warehouse.
    - Decrement `InventoryLot.quantity` for the batch.
    - Validate sufficient stock available before unstocking. `[COMPLETED]`
  - [x] `settle_return_order` (Financial Debit Note):
    - Generate Debit transaction in `VendorTransaction` (`reason='purchase_return'`).
    - Decrement `VendorAccount.current_balance`.
    - Set status to `settled`. `[COMPLETED]`
  - [x] `cancel_return_order`: Cancellation before unstocking. `[COMPLETED]`
- [x] **Views & Templates**:
  - [x] `purchase_return_orders_list` view & template matching reference ERP. `[COMPLETED]`
  - [x] `purchase_return_order_create` form with items repeater and live totals. `[COMPLETED]`
  - [x] `purchase_return_order_detail` view with status dropdown, linked memo, debit note, and items. `[COMPLETED]`
  - [x] `purchase_return_order_action` status update dispatcher. `[COMPLETED]`
  - [x] `purchase_return_order_print` printable return voucher. `[COMPLETED]`
  - [x] `purchase_return_order_export` CSV export. `[COMPLETED]`

---

## 2. Priority P1: Supplier Accounts, Ledger, Payments & Requests

- [x] **Vendor Payments (`/vendor-payments/`)**:
  - [x] List payments with serial, supplier, amount, vault, creator. `[COMPLETED]`
  - [x] Issue new payment deducting `Vault` and crediting `VendorAccount`. `[COMPLETED]`
- [x] **Vendor Payment Requests (`/vendor-payment-requests/`)**:
  - [x] List payment requests with status (`Open`, `Done`, `Rejected`). `[COMPLETED]`
  - [x] Request creation and approval workflow. `[COMPLETED]`
- [x] **Supplier Accounts (`/accounting/vendors/`)**:
  - [x] Aged balances, overdue amounts, credit limits, credit days. `[COMPLETED]`
  - [x] Statement of account view. `[COMPLETED]`
- [x] **Supplier Transactions (`/accounting/vendor-transactions/`)**:
  - [x] Double-entry debit/credit ledger records. `[COMPLETED]`
  - [x] Filter by date, supplier, transaction reason. `[COMPLETED]`

---

## 3. Priority P2: Secondary Actions & Enhancements

- [x] **Split Purchase Order (`فصل الطلب`)**:
  - [x] Split action dialog on Purchase Order detail. `[COMPLETED]`
  - [x] Generate child order with split lines and adjust parent order. `[COMPLETED]`
- [x] **Product Volume Discount Tiers Model**:
  - [x] Relational tier table for quantity brackets (`ProductVolumeDiscountTier`). `[COMPLETED]`
  - [x] Dynamic repeater on product create/edit form. `[COMPLETED]`
- [x] **Product Price Lists Repeater**:
  - [x] Custom pricing tier per customer rank (`ProductPriceList`). `[COMPLETED]`
  - [x] Dynamic repeater and persistence. `[COMPLETED]`

---

## 4. Priority P3: Low-Priority / Polish

- [x] Breadcrumb navigation exact alignment. `[COMPLETED]`
- [x] Navigation bar submenus mapping 100% of discovered pages. `[COMPLETED]`

