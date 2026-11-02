# Reference ERP Permissions Architecture

> **System**: Bricks Rep / WEA Pharma ERP  
> **Source Base URL**: `https://weapharma.bricks-rep.com/`  
> **Analysis Date**: October 2026  
> **Discovery Source**: Live inspection of `GET /api/v1/users/current`, `GET /api/v1/settings/roles`, and JWT claims.

---

## 1. Reference Architecture Overview

The reference ERP employs an enterprise-grade **Hierarchical Role-Based Access Control (RBAC)** model layered with **Attribute-Based Scoping (ABAC)** for geographic territories and functional responsibilities.

### 1.1 Core Components
1. **User Account**: Contains basic profile, mobile, email, assigned `Role`, assigned `Workspace`, and locale (`Africa/Cairo`, `EGP`).
2. **Role Attributes (`attrs`)**:
   - `is_sales_team`: Flags whether the role participates in sales targets and visit plans.
   - `is_area_manager`: Governs supervisory visibility over whole governorates/areas.
   - `is_sub_area_manager`: Governs supervisory visibility over subareas/districts.
   - `is_rep`: Identifies field medical/sales representatives with location tracking.
   - `is_area_assignable`: Whether territory areas can be bound to this role's users.
   - `is_sales_target_assignable`: Whether monthly sales quotas apply to this role.
3. **Role Functional Tags (`tags`)**:
   - `accounting:vaults/assignable`: Eligible to hold a designated petty cash safe/vault.
   - `customers:customers/bypassLocation`: Can create or invoice customers outside geofence.
   - `expenses:expenses/assignable`: Eligible to submit expense claims.
   - `locationTracking:users/trackable`: Enables GPS tracking on mobile.
   - `sales:receiptBooks/assignable`: Eligible to hold receipt coupon books.
   - `tickets:todos/restrictOwner`: Restricted to seeing only own tasks.
4. **Granular Permissions Matrix (818 distinct permissions)**:
   - Formatted as `<domain>:<resource>/<action>` or `workflowActions:execute/<Entity>/*/<action>`.

---

## 2. Standard Enterprise User Types & Roles

| Role Identifier | Role Title (Arabic) | Typical Responsibilities | Scoping / Restrictions |
|---|---|---|---|
| **SuperAdmin** | مدير النظام الأعلى | Complete enterprise access across all workspaces, modules, settings, and accounting overrides. | Global (Unrestricted) |
| **General Manager / CEO** | المدير العام | Executive dashboards, high-level approvals, company reports, audit trails. | Global |
| **Chief Accountant** | رئيس الحسابات | Customer & vendor ledgers, invoicing, payments, cash vaults, financial statements, settlement reversals. | All financial data |
| **Warehouse Keeper** | أمين المخزن | Goods receipt (stocking purchase orders), stock dispatch (delivery memos), physical counts, transfers. | Assigned warehouse(s) |
| **Purchasing Officer** | مسئول المشتريات | Purchase order drafting, vendor management, price lists, order tracking. | Procurement domain |
| **Sales Manager** | مدير المبيعات | Order approvals, rep quotas, sales territories, price lists, discounts. | Territory/Team scope |
| **Area Supervisor** | مشرف منطقة | Reviewing rep visit plans, approving sales orders, monitoring collection quotas. | Assigned Governorate |
| **Medical / Sales Rep** | مندوب دعاية ومبيعات | Creating customer orders, field collections, customer visits, daily agenda. | Assigned Subarea & Rep Vault |

---

## 3. Permission Categories Breakdown

Based on our analysis of all 818 live permission strings, the ERP groups permissions into the following functional categories:

### 3.1 Purchasing Module (`purchase`) — 98 Permissions
- **Listing & Details**:
  - `purchase:purchaseOrders/list`: View purchase orders list.
  - `purchase:purchaseOrders/get`: View single order dossier.
  - `purchase:purchaseOrders/viewTotalAmounts`: View financial values and grand totals (can be hidden from junior clerks).
- **Mutations & Edits**:
  - `purchase:purchaseOrders/create`: Create new purchase order.
  - `purchase:purchaseOrders/edit`: Modify order items, quantities, or suppliers.
  - `purchase:purchaseOrders/delete`: Delete draft orders.
  - `purchase:purchaseOrders/editItemPrice`: Modify unit cost per item.
  - `purchase:purchaseOrders/setItemDiscount`: Grant discounts on line items.
  - `purchase:purchaseOrders/setCustomDiscount`: Grant order-level discount.
  - `purchase:purchaseOrders/setPurchaseOrderShippingFees`: Modify shipping fees.
  - `purchase:purchaseOrders/split`: Split an order into multiple partial delivery orders.
  - `purchase:purchaseOrders/hold`: Place order on operational hold.
  - `purchase:purchaseOrders/cancel`: Cancel order.
- **Inventory Integration**:
  - `purchase:purchaseOrders:inventory/stock`: Confirm goods receipt into warehouse (`Picked`).
  - `purchase:purchaseOrders:inventory/revertMemo`: Revert goods receipt memo.
- **Accounting Integration**:
  - `purchase:purchaseOrders:accounting/invoice`: Post invoice to vendor credit ledger (`Settled`).
  - `purchase:purchaseOrders:accounting/undoInvoice`: Revert posted vendor invoice.
  - `purchase:purchaseOrders:accounting/setCustomDates`: Override transaction and due dates.
- **Attachments & Media**:
  - `purchase:purchaseOrders:attachments/upload`, `download`, `delete`.
- **Supplier Accounting**:
  - `accounting:vendorAccounting:accountTransactions/create`, `edit`, `delete`, `export`.
  - `purchase:vendorPayments/create`, `edit`, `delete`, `link`.

### 3.2 Inventory & Warehousing (`inventory`) — 34 Permissions
- `inventory:warehouses/read`, `create`, `edit`, `delete`: Warehouse registry.
- `inventory:stocks/read`, `export`: View stock levels, batches, and expirations.
- `inventory:stocks/readCost`: View product acquisition costs and valuations (restricted to management/accounting).
- `inventory:memos/create`, `edit`, `apply`, `revert`: Inward (إضافة) and Outward (خصم) stock vouchers.
- `inventory:transfers/create`, `apply`, `revert`: Inter-warehouse transfers.
- `inventory:stockTakes/count`, `review`, `apply`: Physical stock counts and inventory reconciliation.

### 3.3 Sales & Accounts Receivable (`sales`) — 106 Permissions
- `sales:salesOrders/list`, `get`, `create`, `edit`, `delete`, `cancel`, `split`.
- `sales:salesOrders/viewTotalAmounts`: View sales revenue and pricing.
- `sales:salesOrders/editItemPrice`, `setItemDiscount`, `setCustomDiscountAmount`: Pricing & discount authority.
- `sales:salesOrders:inventory/reserve`: Reserve stock upon approval (`Preparing`).
- `sales:salesOrders:inventory/unstock`: Deduct stock from warehouse upon dispatch (`Delivered`).
- `sales:salesOrders:accounting/invoice`: Debit customer ledger (`Invoiced`).
- `sales:salesOrders:accounting/undoInvoice`: Revert customer invoice.
- `sales:collections/create`, `edit`, `delete`, `link`: Debt collections from customers.
- `customerAccounting:accountTransactions/create`, `edit`, `delete`, `export`: Customer ledger entries.

### 3.4 Treasury & Cash Safes (`accounting:vaults`) — 23 Permissions
- `accounting:vaults:vaults/read`, `create`, `edit`, `delete`, `export`: Vault registry.
- `accounting:vaults:transactions/read`, `create`, `edit`, `delete`: Cash receipts and payouts.
- `accounting:vaults:transfers/read`, `create`, `edit`, `delete`, `linkToAccounting`: Cash handovers between vaults.
- `accounting:vaults:transfers/setCustomDates`: Historical transaction date entry.

### 3.5 Contacts & Master Data (`contacts`, `customers`) — 41 Permissions
- `contacts:contacts/read`, `create`, `edit`, `delete`, `export`: Master contact management.
- `contacts:contacts/showProductsSales`: View customer purchasing history.
- `customers:customers/setCode`: Assign formal ERP account code to customer/vendor.
- `customers:customers/setLocation`, `removeLocation`: Manage GPS coordinates for field visits.

### 3.6 System & RBAC Administration (`system`, `users`) — 17 Permissions
- `users:users/list`, `get`, `create`, `edit`, `delete`, `activate`, `deactivate`: User provisioning.
- `users:users/manage`: Assign roles and branch associations.
- `system:rbac/manage`: Configure permission flags and role templates.
- `system:manageUDF`: Define custom fields (User-Defined Fields) on Contacts and Orders.
- `settings:branding/edit`: Company name, tax IDs, commercial register, logo.

### 3.7 State Machine Workflow Actions (`workflowActions`) — 281 Permissions
These govern specific status transition rights:
- `workflowActions:execute/PurchaseOrders/*/change_status/to_approved`
- `workflowActions:execute/PurchaseOrders/*/stock/stock__to_picked`
- `workflowActions:execute/PurchaseOrders/*/invoice/invoice__to_settled`
- `workflowActions:execute/PurchaseOrders/*/undo_invoice/stock__to_picked`
- `workflowActions:execute/PurchaseOrders/*/cancel|PurchaseOrders:status:pending`
- `workflowActions:execute/SalesOrders/*/change_status/pending_to_manager_approval`
- `workflowActions:execute/SalesOrders/*/change_status/preparing_to_delivered`
- `workflowActions:execute/SalesOrders/*/invoice|*`
- `workflowActions:execute/PurchasePayments/*/link_accounting|*`

---

## 4. Equivalent Django Permission Design for the New Application

To achieve clean, maintainable Django architecture without brittle hardcoded strings, we implement a two-tiered authorization architecture:

### Tier 1: Django Model & Granular Permissions
Using standard Django `auth.Permission` combined with custom permissions on Models:
```python
class Meta:
    permissions = [
        ("can_approve_purchase_order", "Can approve purchase orders"),
        ("can_stock_purchase_order", "Can receive goods into warehouse"),
        ("can_invoice_purchase_order", "Can post purchase order invoice to ledger"),
        ("can_undo_invoice_purchase_order", "Can revert posted purchase invoice"),
        ("can_view_purchase_costs", "Can view purchase cost prices and valuation"),
        ("can_manage_vendor_accounting", "Can manage supplier accounting transactions"),
        ("can_transfer_vault_cash", "Can transfer cash between vaults"),
    ]
```

### Tier 2: Custom Role & Scope Decorators / Mixins
```python
class RequirePermissionMixin:
    """Class-based view mixin ensuring user has required permission string."""
    required_permission = None
    ...

class ScopedDataQuerySetMixin:
    """Filters querysets according to user role:
       - SuperAdmin / Accountant: Global access
       - Area Manager: Filter by user.assigned_areas
       - Rep: Filter by user.id or user.assigned_subareas
    """
```
