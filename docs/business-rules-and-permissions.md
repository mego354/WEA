# Business rules and permissions (as implemented)

Source of truth in code: `accounts/models.py` (`User`, `Role`), `accounts/permissions.py`, `accounts/permission_registry.py`, plus settings flags on `LocationSettings`, `SalesSettings`, `PurchaseSettings`.

## Organizational hierarchy

```text
Company (WEA Pharma)
 └── Main area / governorate   Area.parent is NULL
      └── Sub-area / district  Area.parent_id = governorate
           └── Users assigned via User.assigned_areas (M2M)
```

Eligibility for **managerial oversight and approvals** uses **root main area intersection**, not sub-area equality.

- Manager assigned to Cairo (or to Maadi under Cairo) **may** manage a rep assigned only to Nasr City (also under Cairo).
- Manager assigned to Giza **must not** manage Cairo reps.
- If the manager or the target user has **no resolvable main area**, `is_manager_eligible_for_user` returns `False` (fail closed), except SuperAdmin.

`get_user_managed_areas` for managers includes the root and children up to two parent hops (`parent`, `parent__parent`).

## Canonical roles

| `Role.name` | Display | Typical flags | Scope |
|---|---|---|---|
| `superadmin` | مدير النظام الأعلى | `is_super` | All records; all registered permissions |
| `manager` | مدير | `is_area_manager` | Reps and records in intersecting main areas |
| `accountant` | محاسب | — | Broad **view** of financial/stock/sales/purchases; no user admin |
| `rep` | مندوب مبيعات | `is_rep` | Own created/assigned records; own vault/warehouse |
| `medical_rep` | مندوب دعاية طبية | `is_rep` | Own records; contacts also via `assigned_team` or visits performed |

`User.is_super_admin`: active user and (`is_superuser` or role `is_super` or role name `superadmin`).

Legacy role names (`ceo`, `admin`, `area_manager`, …) still appear in `is_manager_or_higher` / `Role.is_manager_role`. Do not add new aliases; migrate toward the five canonical keys (`migrate_to_canonical_roles`).

## Server-side enforcement

Every page and JSON endpoint must use at least:

1. `@require_permission('module:entity/action')` (or SuperAdmin-only decorator).
2. `get_scoped_queryset(qs, user, 'modelname')` on lists/exports.
3. `can_user_access_object(user, obj, action)` on detail/mutate (and `get_object_or_404` on a **scoped** queryset, not the global table).

Module inheritance: a child codename is ineffective unless `module:<app>` is also on the role (SuperAdmin exempt).

Settings-controlled **permission** shortcuts (not data-scope shortcuts):

- `LocationSettings.allow_all_users_to_create_visits` → visit list/create/planned perms
- `LocationSettings.allow_all_users_to_create_agreements`
- `SalesSettings.allow_all_users_to_create`
- `PurchaseSettings.allow_all_users_to_create`

## Data isolation by model

Implemented in `get_scoped_queryset` / `can_user_access_object`:

| Model | Rep | Manager | Accountant | SuperAdmin |
|---|---|---|---|---|
| Visit | owner or created_by, and client within assigned Brick(s) | owners/creators in managed reps or client within assigned Main Area | own visits only (not global) | all |
| PlannedVisitDay | assignee (clients within assigned Brick) | assignees in managed reps (clients within Main Area) | (falls through — pass model name) | all |
| Agreement | created_by | created_by in managed reps | all (view) | all |
| Contact | created_by or assigned_team; medical_rep also activities | area in managed areas or created/assigned by managed reps | all | all |
| SalesOrder / SalesReturn / Collection | created_by | created_by in managed reps | all | all |
| PurchaseOrder / Return | created_by | created_by, warehouse assignee, or warehouse area | all | all |
| Warehouse | assigned_user or `is_main` | main + assigned to managed reps + area | all | all |
| Vault | assigned_user | assigned to self or managed reps | all | all |
| ProductTransferRequest | requester or warehouse assignee | those involving managed reps/areas; **cannot approve/execute** | view + approve/execute | all |
| User | self | self + users in managed areas; cannot edit other managers/superadmins | **none** | all |

Unknown model names: queryset is **not** filtered. Always pass the lowercase Django model name listed above.

**Visit client picker & geographical hierarchy (`get_visit_eligible_contacts_queryset`):** `customers_search_api`, `/visits/create/`, and `/planned-visits/` filter contacts strictly by geographical scope:
- **SuperAdmin:** all active contacts across all areas and bricks.
- **Manager:** contacts within their assigned **Main Area** (`Area.parent is None` + child bricks).
- **Representative:** contacts strictly within their assigned **Brick(s)** (`Area.parent is not None`). Cannot create or access visits for contacts in sibling bricks or other areas.

## Approval, distance validation, and status rules

- **Anti-self-approval** on `approve` / `reject` / `disapprove` (and transfer approve unless SuperAdmin).
- **Visits approval & post-approval editing:** `LocationSettings.require_manager_approval_for_visits` (default True). Start requires `approval_status='approved'` (`can_start_visit`). If an already-approved visit is edited by a lower-level user (Representative), approval is automatically invalidated (`approval_status='pending'`, `waiting_for_reapproval=True`), preserving prior `ApprovalAuditLog` records and requiring manager reapproval.
- **Visit Templates role restrictions and client filtering:**
  - `VisitTemplate.restricted_roles`: Restricts templates to specific user roles (`is_user_eligible(user)`). Unrestricted templates are accessible to all authorized roles.
  - Client-first template availability: Users must select the client(s) first. Available templates dynamically filter by both user role and client account type (`is_contact_eligible(contact)`). For bulk planning across multiple clients, the system calculates the common eligible template intersection across all selected clients.
  - Mandatory template selection: Selecting a template is mandatory across individual planned, bulk planned, and unplanned visits. Submissions without a valid eligible template are rejected on both frontend and backend.
- **Visit Date Validation (No Past Dates):** Under no circumstances can any visit (individual planned, bulk planned, unplanned) be scheduled or created in the past (`visit_date < timezone.now().date()`). Rejected on backend validation and date pickers (`min="{{ today_str }}"`).
- **Bulk daily planning via drawer:** Integrated into the existing left-side client filter drawer (`#customer-drawer`) without modal popups. Features incremental 10-batch client loading (`action=load_contacts`) with deduplication and selection preservation across batches.
- **Visit completion required questions enforcement:** When ending/completing a visit, `can_end_visit` and `end_visit` strictly verify that all active required questions in the template (including active conditional questions) have non-empty answers before allowing checkout. Submit/finish button dynamically disables in UI until all required answers are completed.
- **Visit distance validation (`LocationSettings` & `verify_visit_location`):**
  - Dynamic allowed distance: `LocationSettings.tolerance` (default 300m) or `VisitTemplate.special_tolerance` when `LocationSettings.allow_template_distance_override` is enabled and `template.has_special_location_settings` is True.
  - **Creation:** Mandatory for **unplanned** visits (`verify_unplanned_visit_distance=True`); **not required** when creating **planned** visits.
  - **Completion (End Visit):** Mandatory for both planned and unplanned visits (`verify_end_visit_distance=True`).
  - **Bypass & exceptions:** Managers and SuperAdmins (and roles configured in `roles_can_bypass_distance_creation` / `roles_can_bypass_distance_ending`) can bypass distance restrictions directly without additional approval (`verification_status='force_bypassed'`). Representatives outside the threshold can request an exception (`request_distance_exception=1`) with a mandatory `bypass_reason`, which submits the visit for manager approval (`approval_status='pending'`, `requires_approval_due_to_distance=True`).
- Sales/purchases: `require_manager_approval` on their settings models.
- **Warehouse Operations (Stock In / Stock Out / Transfers):**
  - Controlled by role and configurable settings via `CompanyProfile`:
    - `roles_can_stock_in`: User roles permitted to create Stock In memos (`can_user_perform_stock_in`). SuperAdmin and Accountant have full operational access.
    - `roles_can_stock_out`: User roles permitted to create Stock Out memos (`can_user_perform_stock_out`). SuperAdmin and Accountant have full operational access.
    - `roles_can_transfer`: User roles permitted to request warehouse transfers (`can_user_perform_transfer`). SuperAdmin and Accountant have full operational access.
  - Warehouse scoping: Users can only operate on warehouses they have authorized access to (`can_user_access_object(user, warehouse, 'operate')` or `'view'`). Superadmin can operate on all warehouses.
  - Transfer requests require:
    1. Source and destination warehouses must be different.
    2. Both warehouses must be accessible to the user.
    3. Both warehouses must belong to the same canonical root Main Area (`governorate`), unless the requester is SuperAdmin.
    4. Source warehouse available stock (`qty_on_hand - qty_reserved`) must be strictly greater than or equal to the transferred quantity.
    5. Transferred quantities must be strictly positive.
    6. Transfer execution is atomic and creates balanced inward and outward inventory memos.
- Main warehouses: reps/managers may **view** (`is_main`); edit/delete reserved for SuperAdmin/admin paths.
- Vault: viewing a rep vault ≠ deposit/withdraw; those need `treasury:vaults/transfer` and eligibility.

## Financial and inventory integrity

- Prefer status transitions (`cancelled`, `rejected`) over deleting posted orders.
- Stock and vault balances change only inside service transactions with row locks where implemented (`select_for_update()`).
- **Sales Stock Validation:**
  - On sales order creation and preparation/delivery, available stock (`qty_on_hand - qty_reserved`) is strictly verified in the selected warehouse.
  - Concurrency safety: `prepare_order` and `deliver_order` acquire row locks with `select_for_update()`.
  - Negative or zero quantities, discounts outside allowed bounds (0-100% or exceeding order subtotal), and negative shipping fees are rejected.
- **Purchases Validation:**
  - Supplier must be active and valid.
  - Positive quantities and non-negative unit prices enforced.
  - Discount percentages bounded 0-100%, non-negative shipping.
  - Stock addition happens during `stock_order` / `pick_order` with row-level locks and weighted average cost recalculation.
  - Return orders validate available stock deducting reservations before debiting stock.
- Collections post to vault + customer ledger via `sales`/`treasury` services.
- Purchase `picked` creates inventory memo; `settled` posts vendor ledger.

## Permission matrix (operations)

`SA` = SuperAdmin, `Mgr` = manager in same main area, `Acc` = accountant, `Rep` = owning representative. Empty = denied unless an explicit extra Django permission is granted on the role.

| Operation | SA | Mgr | Acc | Rep |
|---|---|---|---|---|
| Role / RBAC matrix | Yes | No | No | No |
| Audit log UI | Yes (perm `settings:auditLogs/view`) | If granted | If granted | No |
| User list (scoped) | All | Area reps | No | Self |
| Create/edit users in area | Yes | Area reps only | No | No |
| Contact list (scoped) | All | Area | All | Own/assigned |
| Visit create | Yes | Yes | If perm/settings | Own |
| Visit approve | Yes | Eligible reps, not self | No* | No |
| Sales order approve | Yes | Eligible, not self | View | Own create |
| Purchase approve | Yes | Eligible | View | Own create |
| Warehouse Stock In | Yes | If role in settings | Yes | If role in settings |
| Warehouse Stock Out | Yes | If role in settings | Yes | If role in settings |
| Transfer request | Yes | If role in settings | Yes | If role in settings |
| Transfer approve/execute | Yes | No | Yes | No |
| Vault deposit/withdraw | Yes | Eligible + perm | Yes | Own vault |
| Catalog products | Yes | If module perm | If module perm | If module perm |
| Company/location settings | Yes | If `settings:*` perm | If perm | No |

\*Accountant is not `is_manager_or_higher`; visit approve uses `can_manage_approvals` which is managers **or** `activities:visits/approve` permission.

Exact codenames: `accounts/permission_registry.py`.

## Unresolved / verify in code if changing

- CEO/Admin **role name** still grants company-wide querysets without `is_super_admin`.
- `customers_search_api` vs contact ABAC (documented exception).
- `get_subareas` is a small JSON helper; it is login-required but not module-scoped beyond authentication.
