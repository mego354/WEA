# Products & Purchases QA & Verification Test Plan

> **System**: WEA Pharma / Bricks Rep ERP  
> **Testing Environment**: Local Django Testing Framework + SQLite/MySQL + Django Test Client  
> **Strict Rule**: All testing performed locally. Zero mutations on reference system.  
> **Status**: Comprehensive Test Suite Specification  

---

## 1. Test Strategy & Scope

The testing plan guarantees 100% functional, financial, inventory, and visual parity for all discovered pages in the Products and Purchases modules.

```
┌────────────────────────────────────────────────────────┐
│                   Test Levels                          │
├───────────────────────┬────────────────────────────────┤
│ 1. Unit Tests         │ Calculations, Model constraints│
│ 2. Service Tests      │ State transitions, ORM locks   │
│ 3. View / HTTP Tests  │ Permissions, Status 200, Forms │
│ 4. E2E Workflow Tests │ Full purchase-to-return flow   │
└───────────────────────┴────────────────────────────────┘
```

---

## 2. Test Matrix by Subsystem

### 2.1 Products Catalog Module

| Test ID | Module | Feature Under Test | Expected Behavior |
|:---:|:---|:---|:---|
| `CAT-01` | Catalog | Products List Rendering (`/products/`) | Returns HTTP 200, renders all products, category badges, retail prices, formatted currency. |
| `CAT-02` | Catalog | Products Search & Filter | Filters correctly by name, SKU (`GE1`), category ID, and sellable status boolean. |
| `CAT-03` | Catalog | Product Creation Valid | Submitting valid product creates record in DB with unique SKU code and redirects to catalog. |
| `CAT-04` | Catalog | Product Duplicate SKU | Rejecting duplicate SKU with validation error. |
| `CAT-05` | Catalog | Product Edit & Thumbnail | Updating price, packaging, sellable toggle, and image thumbnail persists cleanly. |
| `CAT-06` | Catalog | Product Detail Stock Breakdown | Renders warehouse stock rows correctly without field error (`qty_on_hand`). |
| `CAT-07` | Catalog | Product Deactivate / Delete | Deletes or deactivates product; preserves foreign key integrity. |
| `CAT-08` | Catalog | Categories CRUD | List, modal create, edit, and delete functionality. |

---

### 2.2 Purchase Orders Module

| Test ID | Module | Feature Under Test | Expected Behavior |
|:---:|:---|:---|:---|
| `PO-01` | Purchases | Orders List Rendering (`/purchase-orders/`) | Returns HTTP 200, renders orders, supplier names, statuses, and grand totals. |
| `PO-02` | Purchases | Orders Filter & Search | Filters by status (`pending`, `picked`, etc.), supplier, and date range. |
| `PO-03` | Purchases | New Order Creation | Dynamic items repeater computes subtotal, item discounts, order discount, and shipping fees. |
| `PO-04` | Purchases | Order Approval Transition | `pending` -> `approved` updates status and audit stamps. |
| `PO-05` | Purchases | Goods Receipt / Stocking (`picked`) | Generates Inward `InventoryMemo`, increments warehouse `InventoryStock.qty_on_hand`, updates weighted average cost, records `InventoryLot`. |
| `PO-06` | Purchases | Invoicing / Settlement (`settled`) | Creates double-entry Credit in `VendorTransaction`, creates `VendorInstallment`, increments `VendorAccount.current_balance`. |
| `PO-07` | Purchases | Undo Invoice (`الغاء الفاتورة`) | Reverts `settled` order to `picked`, creates offsetting Debit adjustment, adjusts vendor balance. |
| `PO-08` | Purchases | Order Cancellation | Prevents cancellation if already stocked or invoiced; allows cancelling draft. |
| `PO-09` | Purchases | PO Print Voucher | Renders official printable purchase order voucher with line items and signatures. |
| `PO-10` | Purchases | PO Comments & Attachments | Adding comment and uploading file persists and links to order. |

---

### 2.3 Purchase Return Orders Module (P0 Parity Target)

| Test ID | Module | Feature Under Test | Expected Behavior |
|:---:|:---|:---|:---|
| `RO-01` | Returns | Return Orders List (`/purchase-return-orders/`) | Displays return orders, suppliers, statuses, and totals. |
| `RO-02` | Returns | Create Return Order | Selects supplier, warehouse, products, batches, and return credit prices; calculates grand total. |
| `RO-03` | Returns | Return Approval | Moves status from `pending` to `approved`. |
| `RO-04` | Returns | Dispatch & Unstocking (`delivered`) | Generates outward `InventoryMemo`, decrements `InventoryStock.qty_on_hand`, decrements `InventoryLot.quantity`. |
| `RO-05` | Returns | Insufficient Stock Guard | Blocks unstocking if warehouse does not hold sufficient quantity on hand. |
| `RO-06` | Returns | Financial Settlement (`settled`) | Creates Debit transaction in `VendorTransaction`, decrements `VendorAccount.current_balance`. |
| `RO-07` | Returns | Return Print & Export | Printable voucher and CSV export endpoints return valid responses. |

---

### 2.4 Supplier Ledger & Treasury Integration (P1)

| Test ID | Module | Feature Under Test | Expected Behavior |
|:---:|:---|:---|:---|
| `TR-01` | Treasury | Vendor Payments List (`/vendor-payments/`) | Renders payments with amounts, methods, and suppliers. |
| `TR-02` | Treasury | Issue Vendor Payment | Deducts cash `Vault`, posts Debit in `VendorTransaction`, allocates to oldest `VendorInstallment`. |
| `TR-03` | Treasury | Vendor Accounts (`/accounting/vendors/`) | Computes running balances, overdue debt, and credit days accurately. |
| `TR-04` | Treasury | Vendor Transactions Ledger | Double-entry running balance consistency ($$\text{Balance}_n = \text{Balance}_{n-1} + \text{Credit} - \text{Debit}$$). |

---

## 3. Automated Test Execution Commands

```bash
# 1. Run all unit and integration tests
py manage.py test

# 2. Run Catalog app tests
py manage.py test catalog

# 3. Run Purchases app tests
py manage.py test purchases

# 4. Run Complete End-to-End Workflow verification script
py test_e2e_workflows.py
```
