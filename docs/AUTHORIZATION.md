# Authorization, Scopes, and Permissions

This document specifies the enterprise authorization model, organizational data scoping architecture, and server-side security enforcement rules for WEA Pharma ERP.

---

## 1. Core Principles

1. **Server-Side Enforcement**: Authorization is strictly enforced in Python backend views and domain services. Hiding a navigation link or disabling an HTML button is only a UX convenience and never an access boundary.
2. **Authoritative Permissions Registry**: Permissions are registered in `accounts/permission_registry.py` under hierarchical codenames (e.g. `module:contacts`, `contacts:contacts/create`). A child permission is ineffective unless its parent module permission is also assigned.
3. **Configurable Module Scopes (`OWN`, `BRICK`, `AREA`, `ALL`)**: All organizational data filtering is executed through `accounts.scope_service.ScopeResolutionService`. Hardcoded role-name checks are prohibited from controlling data access.
4. **Anti-Self-Approval**: Under no circumstances may any user approve, reject, or validate their own visit, sales order, purchase order, agreement, or inventory transfer.
5. **No Settings Bypasses**: Settings flags (e.g. `allow_all_users_to_create_visits`) expand operational eligibility for authorized users, but never grant permission without explicit permission codenames or bypass geographical data boundaries.

---

## 2. Canonical Roles and Direct User Authority

### The 5 Canonical Roles

| Role Key | Arabic Display Name | Role Flags | Primary Responsibility |
|---|---|---|---|
| `superadmin` | مدير النظام الأعلى | `is_super=True` | System-wide administrative access, unrestricted scoping across all modules. |
| `manager` | مدير منطقة | `is_area_manager=True` | Supervises representatives and manages records across assigned Main Area(s). |
| `accountant` | محاسب | None | Comprehensive view of finance, sales, purchases, and stock; approves inventory transfers. |
| `rep` | مندوب مبيعات | `is_rep=True` | Commercial representative; manages own clients, orders, vault, and assigned warehouse. |
| `medical_rep` | مندوب دعاية طبية | `is_rep=True` | Medical representative; conducts doctor visits within assigned Brick(s). |

### Role-Exclusive Authority (Single Source of Truth)

- **Role Settings (`settings/roles/`)** is the sole UI and authority for managing permissions, `RoleModuleScope` (`view_scope` / `manage_scope`), and `RoleNotificationRule` (3-tab interface).
- Individual per-user permission overrides (`/settings/users/<pk>/effective-permissions/`) have been completely removed. `User.get_effective_permission_codenames()` and `ScopeResolutionService.get_user_scope()` resolve permissions and scopes strictly from the user's assigned `Role` (with SuperAdmin/superuser explicit bypasses).

---

## 3. Configurable Module Scopes Architecture (`ScopeResolutionService`)

Data isolation does not rely on hardcoded role names. It is resolved centrally through `accounts.scope_service.ScopeResolutionService`.

### The 4 Granular Organizational Scopes

1. **`OWN`**:
   - Access is restricted exclusively to records directly owned, created, or assigned to the user:
     - `owner=user`, `created_by=user`, `assignee=user`, or `assigned_user=user`.
2. **`BRICK`**:
   - Access is restricted to records associated with the user's assigned Brick(s) (`Area.parent is not None`).
   - Sibling bricks within the same governorate remain inaccessible.
3. **`AREA`**:
   - Access extends to all records within the user's assigned Main Area(s) (`Area.parent is None`), including all constituent child bricks.
4. **`ALL`**:
   - Unrestricted system-wide access across all governorates, bricks, and users.

### Independent `view_scope` vs. `manage_scope`

Each module has two independently configurable scopes:
- **`view_scope`**: Governs read querysets, lists, detail views, dashboard statistics, and dropdown selectors.
- **`manage_scope`**: Governs mutation operations, creation, edits, deletion, status changes, and approvals.

### Default Canonical Scopes Matrix

| Module | SuperAdmin | Manager | Accountant | Representative |
|---|---|---|---|---|
| `contacts` | ALL / ALL | AREA / AREA | ALL / ALL | BRICK / BRICK |
| `activities` | ALL / ALL | AREA / AREA | OWN / OWN | OWN / OWN |
| `sales` | ALL / ALL | AREA / AREA | ALL / ALL | OWN / OWN |
| `purchases` | ALL / ALL | AREA / AREA | ALL / ALL | OWN / OWN |
| `inventory` | ALL / ALL | AREA / AREA | ALL / ALL | OWN / OWN |
| `treasury` | ALL / ALL | AREA / AREA | ALL / ALL | OWN / OWN |
| `accounts` | ALL / ALL | AREA / OWN | OWN / OWN | OWN / OWN |

*Format: `view_scope / manage_scope`*

---

## 4. Territorial Hierarchy & Managerial Oversight

```text
Governorate / Main Area (Area.parent IS NULL)
  ├── Brick / Subarea (Area.parent = Governorate)
  │     ├── Representative 1 (Assigned: Brick A)
  │     └── Representative 2 (Assigned: Brick B)
  └── Brick / Subarea (Area.parent = Governorate)
        └── Representative 3 (Assigned: Brick C)
```

### Manager Oversight Rules (`is_manager_eligible_for_user`)

1. **Root Main Area Intersection**:
   - Managerial oversight is calculated by finding the canonical root Main Area (`get_main_area`) of both the manager and the target representative.
   - If the sets of root main areas intersect, the manager is authorized to supervise that representative.
   - *Example*: A manager assigned to Governorate Cairo can manage representatives assigned to Nasr City, Maadi, or Heliopolis.
   - *Cross-Governorate Isolation*: A manager assigned to Giza cannot view or supervise Cairo representatives or records.
2. **Fail Closed**:
   - If a manager or target user has no assigned areas, `is_manager_eligible_for_user` evaluates to `False`.

### Representative Brick Scoping (`get_visit_eligible_contacts_queryset(qs, user)`)

- In visit creation (`/visits/create/`), bulk planning (`/planned-visits/`), and client search API (`customers_search_api`):
  - **SuperAdmin**: Can select active clients across the entire country.
  - **Manager**: Can select clients across their assigned Main Area(s) and all child bricks.
  - **Representative**: Scoped strictly to clients located within their assigned **Brick(s)**. Sibling bricks in the same governorate are rejected.

---

## 5. Server-Side Enforcement Patterns

Every view and AJAX endpoint must enforce authorization using standard patterns:

### 1. View Decorator / Action Permission
```python
@require_permission('activities:visits/create')
def visit_create(request):
    ...
```

### 2. Scoped QuerySets (Lists, Tables, Exports)
```python
queryset = get_scoped_queryset(Visit.objects.all(), request.user, 'visit')
```

### 3. Object-Level Access (Detail, Edit, Status Mutation)
```python
visit = get_object_or_404(get_scoped_queryset(Visit.objects.all(), request.user, 'visit'), pk=pk)
if not can_user_access_object(request.user, visit, 'edit'):
    raise PermissionDenied("غير مصرح لك بتعديل هذه الزيارة")
```

### 4. Fail-Closed Scope Architecture (`ScopeResolutionService`)
- When querying any model that is not explicitly mapped or recognized in `MODEL_MODULE_MAP`, `ScopeResolutionService` fails closed by returning `queryset.none()` for all non-superusers.
- This guarantees zero-trust protection against data leaks for newly introduced models or unmapped tables.

### 5. Assignee Scoping Parity (`get_visible_assignees_queryset`)
- Both Planned Visits (`/planned-visits/`) and Agenda (`/agenda/`) resolve visible users using the unified helper `get_visible_assignees_queryset(user, module='activities')`.
- **SuperAdmin**: Returns all active users in the system.
- **Area Manager**: Returns all active users who share at least one canonical root Main Area (`get_main_area()`) with the manager.
- **Representative**: Returns exclusively `[request.user]`. Representatives cannot see or select peers across any area.

---

## 6. Operational Permissions Matrix

| Operational Capability | SuperAdmin | Manager | Accountant | Representative |
|---|---|---|---|---|
| User & Role RBAC Management | Yes | Subordinate Reps Only | No | Self Profile Only |
| Audit Log UI | Yes (`settings:auditLogs/view`) | If granted | If granted | No |
| Contact Directory | All Areas | Assigned Main Area | All Areas | Assigned Brick(s) |
| Visit Creation (Unplanned) | Yes | Yes (Auto-approved, Atomic start) | If granted (Auto-approved, Atomic start) | Own (Assigned Brick, Auto-approved, Atomic start) |
| Visit Planning & Bulk Plans | Yes | Subordinates (Auto-approved) | If granted | Own (Assigned Brick, Pending manager approval) |
| Visit & Plan Approval | Yes | Subordinates in Main Area (Not Self) | No | No |
| Visit Deletion (Any Stage) | Yes | If granted (`activities:visits/delete`) | If granted (`activities:visits/delete`) | Own Scoped (If granted `activities:visits/delete`) |
| Visit Questionnaire Answers Edit | Yes | Own Created Only (`activities:visits/edit_answers`) | Own Created Only (`activities:visits/edit_answers`) | Own Created Only (`activities:visits/edit_answers`) |
| GPS Distance Bypass | Yes | If granted (`activities:visits/bypass_gps`) | No | If granted (`activities:visits/bypass_gps`) |
| GPS Suspicious / Fake Location Visibility & Filter | Yes (`activities:visits/view_gps_suspicion`) | If granted (`activities:visits/view_gps_suspicion`) | If granted (`activities:visits/view_gps_suspicion`) | No (never exposed to rep without permission) |
| Agreement Creation & Edit | Yes | Subordinates (`activities:agreements/create`, `_edit`) | If granted | Own (Assigned Brick) |
| Agreement Deletion | Yes (`activities:agreements/delete`) | Subordinates | If granted | Own |
| Agreement Completion (`done`) | Yes (`activities:agreements/approve`) | Subordinates (Not Self) | No | No |
| Sales Order Creation | Yes | Yes (Immediate stock deduction + customer debit) | If granted | Own Warehouse |
| Sales Order Edit | Yes (`sales:orders/edit`) | Subordinates (Blocked if collections exist) | No | Own (Blocked if collections exist) |
| Sales Order Deletion | Yes (`sales:orders/delete`) | If granted (Blocked if collections exist) | If granted | No |
| Sales Order Payment Status | Yes (`sales:orders/manage_payment_status`) | If granted (`sales:orders/manage_payment_status`) | If granted (`sales:orders/manage_payment_status`) | No |
| Sales Return Creation | Yes (`sales:returns/create`) | Yes (Immediate restocking + customer credit) | If granted | Own Orders |
| Sales Return Deletion | Yes (`sales:returns/delete`) | If granted | If granted | No |
| Customer Accounts (`/sales/customers/accounts/`) & Export | Yes | Assigned Main Area (`sales:customers/accounting`, `_export`) | All (`sales:customers/accounting`, `_export`) | If granted (Own/Brick scoped via `sales` scope) |
| Customer Transactions (`/sales/customer-transactions/`) & Export | Yes | Assigned Main Area (`sales:customers/transactions`, `_export`) | All (`sales:customers/transactions`, `_export`) | If granted (Own/Brick scoped via `sales` scope) |
| Purchase Order Creation | Yes (`purchases:orders/create`) | Yes (Immediate stock inward + vendor credit) | If granted | No |
| Purchase Order Deletion | Yes (`purchases:orders/delete`) | If granted (Blocked if payments/returns exist) | If granted | No |
| Purchase Order Payment Status | Yes (`purchases:orders/manage_payment_status`) | If granted (`purchases:orders/manage_payment_status`) | If granted (`purchases:orders/manage_payment_status`) | No |
| Purchase Return Creation | Yes (`purchases:returns/create`) | Yes (Immediate stock deduction + vendor debit) | If granted | No |
| Purchase Return Deletion | Yes (`purchases:returns/delete`) | If granted | If granted | No |
| Vendor Payment Request Creation | Redirects to Treasury Payment (`treasury:payments/create`) | Redirects | Redirects | No |
| Vendor Payment Request Approval | Yes | Subordinates (Not Self) | View Only | No |
| Vendor Payment Request Execution | Yes | No | Yes | No |
| Warehouse Creation & Editing | Yes (`inventory:warehouses/manage`) | If granted (Assigned Main Area / Subareas) | No | No |
| Warehouse Deletion | Yes (`inventory:warehouses/delete`) | If granted (Blocked if stock > 0, memos, or orders exist) | No | No |
| Vault Creation & Editing | Yes (`treasury:vaults/manage`) | If granted (Assigned Main Area / Subareas) | If granted (`treasury:vaults/manage`) | No |
| Vault Deletion | Yes (`treasury:vaults/delete`) | If granted (Blocked if balance != 0, transactions, or payments exist) | No | No |
| User Profile Linked Assets Assignment | Yes (`accounts:users/edit`) | Subordinate Reps (Scoped warehouses & vaults) | No | No |
| Inventory Stock In / Out (Memos) | Yes | If granted (`inventory:memos/manage`) | Yes (`inventory:memos/manage`) | Own Custody Warehouse (`inventory:memos/manage`) |
| Transfer Request | Yes | Yes (`inventory:transfers/create`) | Yes (`inventory:transfers/create`) | Own Custody Warehouse (`inventory:transfers/create`) |
| Transfer Approval & Execution | Yes | No | Yes (`inventory:transfers/approve`) | No |
| Vault Deposits & Withdrawals | Yes | Subordinates + Perm | Yes | Own Vault |
| Performance Overview & Analysis | Yes | Assigned Main Area (`performance:overview/view`, `performance:analysis/view`) | If granted | Own Performance (`performance:overview/view`) |
| Performance Daily & Detailed | Yes | Assigned Main Area (`performance:daily/view`, `performance:detailed/view`) | If granted | Own Daily Activity (`performance:daily/view`) |
| Reports Hub & Financial Reports | Yes | Assigned Main Area | All Financials (`reports:financial/view`, `reports:sales/view`) | No |
| Sales & Inventory Reports | Yes | Assigned Main Area | All Supply Chain & Sales (`reports:inventory/view`, `reports:sales/view`) | Own Sales (`reports:sales/view`) |
| Activities & Samples Reports | Yes | Assigned Main Area | If granted | Own Activities (`reports:activities/view`) |


| Cloudflare R2 Storage Settings (`/settings/storage/`) | Yes (`settings:storage/manage`, SuperAdmin-gated) | No | No | No |
| Transaction Attachments Upload / View / Delete | Yes | Scoped (`can_user_access_object`) | Scoped | Own / Scoped |
| Order / Return PDF Export | Yes | Scoped (`sales:orders/pdf`, `sales:returns/pdf`, `purchases:orders/pdf`, `purchases:returns/pdf`) | Scoped | Own / Scoped |
| Customer & Vendor Account Statement PDF | Yes | Scoped (`sales:statements/pdf`, `purchases:statements/pdf`) | Scoped | Own / Scoped |
