# App-Wide Role and Organizational Scope Data Access Control

## 1. Executive Summary

This document specifies the backend-enforced Attribute-Based and Role-Based Access Control (ABAC/RBAC) model implemented across the WEA Pharma ERP application. Access control is strictly enforced on the server for all list endpoints, search queries, filter operations, detail URLs (preventing Insecure Direct Object References — IDOR), exports, dashboard statistics, and client dropdown selectors.

Data is never sent to the browser and merely hidden via CSS or JavaScript; unpermitted records are completely excluded from database querysets before evaluation.

---

## 2. Core Access Control Matrix

| Role | Core Business Scope | Data Visibility Rules | Execution / Modification Boundaries |
|---|---|---|---|
| **Superadmin** (`superadmin`) | Enterprise-wide Administration | Global visibility into all application records, configurations, audit trails, and financial accounts across all geographic areas. | Full administrative, approval, execution, and configuration authority. |
| **Accountant** (`accountant`) | Corporate Accounting & Treasury | Broad visibility into all sales orders, sales returns, purchase orders, collections, customer statements, vendor statements, vaults, and inventory movements. | Read/audit access across financial scopes; cannot modify user roles, alter system security settings, or perform superadmin-only actions. |
| **Manager** (`manager`) | Regional Operations Management | Accesses operational records (visits, sales orders, collections, agreements, targets) belonging to representatives assigned to the manager's **same root main area** (governorate), across all secondary sub-areas. | Can approve/reject subordinate visits, orders, and agreements. **Anti-Self-Approval:** Cannot approve or reject their own submissions. Read-only oversight over subordinate rep vaults and warehouses (cannot withdraw or execute transactions). |
| **Rep** (`rep`) | Commercial Sales Operations | **Strictly own records.** Can only view, search, filter, and export records they created or were assigned to (`created_by=user`, `owner=user`, assigned vault/warehouse). | Cannot view or access records of peer representatives, even if assigned to the same city or sub-area. Cannot approve or reject operations. |
| **Medical Rep** (`medical_rep`) | Scientific Detailing & Relations | **Strictly own records**, with legitimate shared contact access for assigned scientific work (`created_by=user`, `owner=user`, or in `contact.assigned_team`). | Cannot access peer sales orders or transactions. Operational work restricted to medical visits, samples, and scientific agreements. |

---

## 3. Organizational Hierarchy & Main Area Traversal

Regional hierarchy in WEA ERP is rooted in the `master_data.Area` model:
- **Root Main Area (Governorate / منطقة رئيسية):** Top-level area where `parent is None` (e.g. القاهرة, الجيزة, الإسكندرية).
- **Secondary Sub-Areas (منطقة فرعية / مركز):** Child areas where `parent_id` points to the root main area (e.g. مدينة نصر, المعادي under Cairo; الدقي, الهرم under Giza).

### Canonical Main Area Resolution:
```python
def get_main_area(area):
    """Traverses parent links until the root main area is reached."""
    if not area:
        return None
    curr = area
    while getattr(curr, 'parent_id', None):
        curr = curr.parent
    return curr
```

### Manager Main Area Scoping:
1. **Sub-Area Independence:** A manager assigned to a main area (e.g. القاهرة) has management authority over a representative in "مدينة نصر" and another representative in "المعادي", because both sub-areas resolve to the same root main area.
2. **Main Area Isolation:** A manager assigned to "القاهرة" has zero access to records of representatives in "الدقي" (الجيزة) or "سموحة" (الإسكندرية).
3. **Fail-Secure Rule:** If a manager has no valid root main area assigned (`get_user_main_areas(user)` is empty), access fails securely: `get_user_managed_representatives(user)` returns `User.objects.none()`, ensuring unconfigured managers never gain accidental global access.

---

## 4. Module Scoping Implementations

All querysets pass through `get_scoped_queryset(queryset, user, model_name)`:

### 1. Visits (`activities:models:Visit`)
- `rep` & `medical_rep`: `Q(owner=user) | Q(created_by=user)`.
- `manager`: `Q(owner__in=managed_reps) | Q(created_by__in=managed_reps)`.
- `superadmin`: Unrestricted.

### 2. Planned Visit Days (`activities:models:PlannedVisitDay`)
- `rep` & `medical_rep`: `assignee=user`.
- `manager`: `assignee__in=managed_reps`.
- `superadmin`: Unrestricted.

### 3. Agreements (`activities:models:Agreement`)
- `rep` & `medical_rep`: `created_by=user`.
- `manager`: `created_by__in=managed_reps`.
- `accountant`: Broad visibility across all agreements (`return queryset`).
- `superadmin`: Unrestricted.

### 4. Contacts (`contacts:models:Contact`)
- `rep`: `Q(created_by=user) | Q(assigned_team=user)`.
- `medical_rep`: `Q(created_by=user) | Q(assigned_team=user) | Q(activities__performed_by=user)`.
- `manager`: `Q(area__in=managed_areas) | Q(created_by__in=managed_reps) | Q(assigned_team__in=managed_reps)`.
- `accountant` & `superadmin`: Unrestricted.

### 5. Sales Orders & Sales Returns (`sales:models:SalesOrder`)
- `rep` & `medical_rep`: `created_by=user` (reps cannot view orders created by peers in the same area).
- `manager`: `created_by__in=managed_reps`.
- `accountant`: Broad financial visibility (`return queryset`).
- `superadmin`: Unrestricted.

### 6. Collections (`sales:models:Collection`)
- `rep` & `medical_rep`: `created_by=user`.
- `manager`: `created_by__in=managed_reps`.
- `accountant`: Broad financial visibility (`return queryset`).
- `superadmin`: Unrestricted.

### 7. Customer Accounts & Ledger (`sales:models:CustomerAccount`, `CustomerTransaction`)
- `rep`: Filtered strictly to accounts of authorized contacts.
- `manager`: Filtered to customers in managed areas or managed reps.
- `accountant`: Broad visibility across all ledger entries (`return queryset`).

### 8. Warehouses & Stock Movements (`inventory:models:Warehouse`, `InventoryStock`)
- `rep`: Assigned representative warehouse plus main company warehouse (read catalog).
- `manager`: Main warehouses, plus warehouses of subordinate reps in their main area, plus warehouses geographically situated in their managed areas.
- `accountant`: Full visibility across all warehouses.

### 9. Vaults & Treasury (`treasury:models:Vault`, `VaultTransaction`)
- `rep`: Strictly assigned personal rep vault (`assigned_user=user`).
- `manager`: Central company vaults, plus vaults of subordinate reps in their main area (**Read-Only oversight**; cannot deposit, withdraw, transfer, or adjust).
- `accountant`: Full visibility across all corporate and field vaults.

---

## 5. Object-Level Enforcement (`can_user_access_object`)

Guards against Insecure Direct Object References (IDOR):
1. **Anti-Self-Approval Rule:**
   ```python
   if action in ['approve', 'reject', 'disapprove']:
       if owner_id == user.id:
           return False
   ```
2. **Direct URL Validation:** When a representative attempts to browse `GET /sales/99/` or `POST /activities/visits/105/approve/`, `can_user_access_object` validates permissions before returning template context or executing state transitions.
3. **HTTP 403 Forbidden Response:** Unauthorized browser requests render the secure `403.html` template; unauthorized AJAX/fetch requests return JSON with `{"error": "PermissionDenied"}` and HTTP status 403.

---

## 6. Automated Unit & Regression Tests

Automated test suites in `accounts/tests_data_scoping.py`:
- `test_rep_data_scoping_strict_ownership`: Verifies reps cannot see peer records in the same main area.
- `test_manager_main_area_scoping`: Verifies manager accesses reps in different sub-areas of the same main area, but is blocked from other main areas.
- `test_manager_without_area_fails_securely`: Verifies unassigned managers receive empty querysets.
- `test_accountant_broad_financial_visibility`: Verifies complete financial visibility.
- `test_superadmin_unrestricted_access`: Verifies global visibility.
- `test_anti_self_approval`: Verifies managers cannot approve their own submissions.
