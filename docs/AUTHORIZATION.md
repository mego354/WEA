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

### Direct User-Level Permissions Authority (`User.has_custom_permissions`)

- **Role Inheritance (`has_custom_permissions=False`)**: The user dynamically inherits all permissions and module scopes defined by their assigned `Role`.
- **Granular User Authority (`has_custom_permissions=True`)**: The user's permissions are controlled directly and exclusively by `user.user_permissions.all()`, overriding role defaults. Administrators can grant or revoke any specific action without creating duplicate roles.
- **Dedicated Management Interface**: Managed at `/settings/users/<pk>/effective-permissions/`. Supports copying role presets, toggling custom mode, and restoring defaults with full `SecurityAuditLog` tracking.

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
| `activities` | ALL / ALL | AREA / AREA | OWN / OWN | BRICK / OWN |
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

### Representative Brick Scoping (`get_visit_eligible_contacts_queryset`)

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

---

## 6. Operational Permissions Matrix

| Operational Capability | SuperAdmin | Manager | Accountant | Representative |
|---|---|---|---|---|
| User & Role RBAC Management | Yes | Subordinate Reps Only | No | Self Profile Only |
| Audit Log UI | Yes (`settings:auditLogs/view`) | If granted | If granted | No |
| Contact Directory | All Areas | Assigned Main Area | All Areas | Assigned Brick(s) |
| Visit Creation | Yes | Yes | If granted | Own (Assigned Brick) |
| Visit Deletion (Unended Only) | Yes | If granted (`activities:visits/delete`) | If granted | Own Unended (If granted / setting enabled) |
| Visit Questionnaire Answers Edit | Yes | Own Created/Assigned Only | Own Created/Assigned Only | Own Created/Assigned Only |
| Visit Approval | Yes | Subordinates (Not Self) | No | No |
| Sales Order Creation | Yes | Yes | If granted | Own Warehouse |
| Sales Order Approval | Yes | Subordinates (Not Self) | View Only | No |
| Purchase Order Approval | Yes | Subordinates (Not Self) | View Only | No |
| Inventory Stock In / Out | Yes | If role in settings | Yes | If role in settings |
| Transfer Request | Yes | If role in settings | Yes | If role in settings |
| Transfer Approval & Execution | Yes | No | Yes | No |
| Vault Deposits & Withdrawals | Yes | Subordinates + Perm | Yes | Own Vault |

