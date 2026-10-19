# Users and Permissions Specification

> **System**: WEA Pharma ERP  
> **Module**: RBAC, User Administration, and Server-Side Authorization  
> **Source Base URL**: `https://weapharma.bricks-rep.com/`  
> **Analysis Date**: October 2026

---

## 1. Authorization Architecture Overview

The system implements enterprise-grade **Role-Based Access Control (RBAC)** integrated with **Attribute-Based Scoping (ABAC)**. Authorization is strictly enforced on the server for all endpoints, views, mutations, and APIs.

### 1.1 Fundamental Entities

```
+-----------------------------------+
|               User                |
+-----------------------------------+
| - id: Primary Key                 |
| - username: string                |
| - name: string (Full Name)        |
| - email: string (Unique)          |
| - code: string (Optional ID)      |
| - mobile: string                  |
| - role: ForeignKey(Role)          |
| - is_active: boolean              |
| - is_superuser: boolean           |
| - bypass_location_verification    |
| - assigned_areas: M2M(Area)       |
+-----------------+-----------------+
                  |
                  v Belongs to
+-----------------------------------+
|               Role                |
+-----------------------------------+
| - id: Primary Key                 |
| - name: string (Unique Code)      |
| - display_name: string            |
| - description: text               |
| - is_system: boolean              |
| - is_active: boolean              |
| - is_sales_team: boolean          |
| - is_area_manager: boolean        |
| - is_sub_area_manager: boolean    |
| - is_rep: boolean                 |
| - can_hold_vault: boolean         |
| - has_sales_targets: boolean      |
| - is_contact_manager: boolean     |
| - is_main_area_bound: boolean     |
| - is_sub_area_bound: boolean      |
| - tags: M2M(RoleTag)              |
| - permissions: M2M(Permission)    |
+-----------------------------------+
```

---

## 2. Standard Enterprise System Roles

| Role Identifier | Arabic Display Name | Role Category | Key Responsibilities |
|---|---|---|---|
| `SuperAdmin` | مدير النظام الأعلى | System Superuser | Full system administration, global accounting, user management, system settings. |
| `Admin` | مدير النظام | System Admin | System administration, user management, territory management, general settings. |
| `CEO` | المدير العام | Executive | Company-wide view, high-level reporting, executive approvals. |
| `Accountant` | محاسب | Financial | Treasury, cash vaults, customer/vendor accounting, invoicing, journal entries. |
| `Bookkeeper` | كاتب حسابات | Financial | Transaction entries, payment recording, ledger inquiries. |
| `AreaManager` | مدير منطقة | Supervisory Sales | Approving sales orders, monitoring field reps, viewing area reports. |
| `DistrictManager` | مدير قطاع | Supervisory Sales | Managing subarea reps, visit planning, quota tracking. |
| `DirectSalesRep` | مندوب مبيعات مباشر | Field Operations | Taking customer sales orders, field collections, stock dispatch. |
| `MedicalRep` | مندوب دعاية طبية | Field Operations | Field visits, customer relationship building, sample requests. |
| `DirectSuperSalesRep`| مندوب مبيعات متميز | Field Operations | Field sales, priority customer accounts, collection handling. |
| `KeyAccountSupervisor`| مشرف حسابات رئيسية | Commercial | Managing institutional contracts, major hospital & chain accounts. |
| `KeyAccountRep` | مندوب حسابات رئيسية | Commercial | Servicing high-volume key accounts. |
| `HRManager` | مدير الموارد البشرية | Administration | Employee attendance, requests, staff directory. |
| `CarDriver` | سائق سيارة توزيع | Logistics | Stock delivery, customer receipt vouchers. |
| `LineAdmin` | مدير خط | Operational | Managing specific product line divisions. |
| `LineSalesManager` | مدير مبيعات خط | Operational | Sales targets for dedicated product lines. |

---

## 3. Role Functional Tags (`RoleTag`)

Functional tags grant cross-cutting operational capabilities across modules:
1. `customers:customers/bypassLocation`: Exempts user from geographic GPS geofence checks during transactions.
2. `accounting:vaults/assignable`: Qualifies the user to be assigned a dedicated petty cash safe/vault.
3. `expenses:expenses/assignable`: Qualifies the user to submit expense claims and reimbursement requests.
4. `locationTracking:users/trackable`: Enables background mobile GPS tracking during working hours.
5. `sales:receiptBooks/assignable`: Authorizes user to hold serial receipt coupon books for cash collections.
6. `tickets:todos/restrictOwner`: Restricts user visibility in task lists strictly to their own assigned tasks.

---

## 4. Granular Permissions Architecture

Permissions are grouped by domain modules matching the reference system:

### 4.1 Modules and Granular Keys

#### A. Settings & System Administration (`settings`, `system`, `users`)
- `settings:settings/view`: View settings navigation and dashboard.
- `settings:branding/edit`: Update company name, tax ID, legal address, and logo.
- `settings:location/manage`: Update GPS radius tolerances and workflow verification rules.
- `settings:areas/manage`: Add, edit, or delete geographical areas and governorates.
- `settings:expenses/manage`: Add, edit, or delete general and visit expense types.
- `settings:tickets/manage`: Configure default and custom task types.
- `settings:requests/manage`: Configure approval request categories.
- `settings:agreements/manage`: Configure contract and agreement types.
- `settings:sales/manage`: Configure sales automation, taxes, and packaging units.
- `settings:purchase/manage`: Configure purchase automation, taxes, and packaging units.
- `settings:inventory/manage`: Configure batch and expiry mandatory policies.
- `settings:contactsUdf/manage`: Configure user-defined custom fields for contacts.
- `settings:syncData/manage`: Configure Google Sheets data synchronization.
- `users:users/list`: View user accounts directory.
- `users:users/create`: Create new user accounts.
- `users:users/edit`: Modify user credentials, status, and role.
- `users:users/delete`: Deactivate or delete user accounts.
- `system:rbac/manage`: Create, edit, duplicate, and assign roles and permissions.

#### B. Accounting & Treasury (`accounting`, `vaults`)
- `accounting:vaults/view`: View cash safes and current balances.
- `accounting:vaults/manage`: Create and edit vaults.
- `accounting:transactions/create`: Record cash receipts and payouts.
- `accounting:transfers/manage`: Cash transfers between vaults.
- `accounting:vendorAccounting/manage`: Manage supplier ledger entries.
- `accounting:customerAccounting/manage`: Manage customer debit/credit ledgers.

#### C. Purchasing & Inward Logistics (`purchase`)
- `purchase:orders/list`: View purchase orders directory.
- `purchase:orders/create`: Draft new purchase orders.
- `purchase:orders/edit`: Modify quantities, prices, or line items.
- `purchase:orders/approve`: Approve draft purchase orders.
- `purchase:orders/stock`: Receive goods into warehouse.
- `purchase:orders/invoice`: Post purchase invoice to vendor ledger.
- `purchase:returns/manage`: Create and process purchase returns.

#### D. Sales & Outward Logistics (`sales`)
- `sales:orders/list`: View sales orders directory.
- `sales:orders/create`: Draft new sales orders.
- `sales:orders/approve`: Approve sales orders.
- `sales:orders/unstock`: Dispatch goods from warehouse.
- `sales:orders/invoice`: Post sales invoice to customer ledger.
- `sales:collections/manage`: Record customer payments and debt settlements.

#### E. Inventory & Warehouses (`inventory`)
- `inventory:warehouses/manage`: Warehouse registry CRUD.
- `inventory:stocks/view`: Inspect stock levels and valuations.
- `inventory:transfers/manage`: Stock transfers between warehouses.
- `inventory:stockTakes/manage`: Physical stock counts and reconciliations.

#### F. Contacts & Master Data (`contacts`, `customers`)
- `contacts:contacts/list`: View contacts master directory.
- `contacts:contacts/create`: Create new customer or supplier.
- `contacts:contacts/edit`: Modify contact info, credit limits, or terms.
- `contacts:contacts/export`: Export contacts to Excel/CSV.

---

## 5. Server-Side Enforcement Mechanisms

### 5.1 Reusable Permission Decorators & Mixins

```python
# Reusable authorization utility
def has_user_permission(user, perm_codename):
    """
    Checks if a user has a specific permission codename,
    with SuperAdmin / superuser automatic override.
    """
    if not user.is_authenticated:
        return False
    if user.is_superuser or getattr(user, 'is_super_admin', False):
        return True
    if not user.is_active:
        return False
    if user.role and user.role.is_active:
        return user.role.permissions.filter(codename=perm_codename).exists()
    return False
```

### 5.2 Server-Side Direct URL & API Protection
- Every Settings view is wrapped with `@login_required` and server-side role/permission validation.
- Unauthorized requests to views redirect to the home dashboard or return HTTP 403 Forbidden with an Arabic error message:  
  `"عذراً، لا تمتلك الصلاحية الكافية للوصول إلى هذه الصفحة."`
- API endpoints return JSON: `{"error": "Unauthorized", "detail": "Permission denied"}` with status 403.

### 5.3 UI Navigation Visibility
- Navigation menus, buttons (`اضف مستخدم`, `إنشاء دور`, etc.), and action links are conditionally rendered based on permissions, while backend checks guarantee that hidden controls cannot be executed via direct URL invocation or POST requests.
