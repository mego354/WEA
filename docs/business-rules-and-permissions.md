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

Module inheritance: a child codename is ineffective unless `module:<app>` is also on the role/user (SuperAdmin exempt).

### User-Level Direct Permissions Control (100% Granular Authority)
- `User.has_custom_permissions = False` (default): The user inherits their effective permissions dynamically from their assigned canonical `Role`.
- `User.has_custom_permissions = True`: The user's permissions are controlled directly and exclusively by `user.user_permissions.all()`, overriding role defaults. This gives administrators 100% direct control to grant or revoke specific permissions for an individual user without creating duplicate roles.
- **Management Interface:** Accessible at `/settings/users/<pk>/effective-permissions/`. Supports toggling custom mode, individual module/action checkboxes, "نسخ من الدور" (copy role permissions), and "استعادة الافتراضي للدور" (reset to role defaults). Every change is audited via `SecurityAuditLog`.

### Strict Permission Enforcement (No Settings Bypasses)
- Permissions on the user/role are the **sole, authoritative decider** controlling whether a user can perform any stage/process of any feature.
- Settings flags (`LocationSettings.allow_all_users_to_create_visits`, `allow_all_users_to_create_agreements`, `SalesSettings.allow_all_users_to_create`, `PurchaseSettings.allow_all_users_to_create`) **do not bypass** server-side permission checks. Without the explicit permission codename (e.g. `sales:orders/create`, `activities:visits/create`), the request is strictly blocked (HTTP 403 / forbidden).

### Unified Settings Architecture (`SettingsService`)
- All ERP configuration entities (`CompanyProfile`, `LocationSettings`, `SalesSettings`, `PurchaseSettings`, `UserSettings`) are accessed and mutated through the centralized `master_data.services.SettingsService`.
- **Thread-safe Request Caching:** Avoids redundant database queries within a single web request by caching resolved settings instances in `threading.local()`.
- **Atomic Audited Mutations:** All updates execute inside `@transaction.atomic` blocks, updating model fields and generating detailed `SecurityAuditLog` records containing `previous_values` and `new_values`.
- **Clean Settings Scope:** Cleaned up unused and phantom configuration toggles (e.g. dummy invoice toggles, phantom GPS checkboxes) while maintaining functional approval controls (`require_manager_approval`), taxation policies (`tax_mode`), and packaging units (`default_packaging_unit`).

### Permission Simplification & Canonical Codenames
- Permission codenames are unified and defined in `accounts/permission_registry.py`.
- **Redundant Alias Normalization:** `treasury:vaults/transactions` is normalized to `treasury:transactions/list` at both the permission catalog, `User.has_permission()`, and `has_perm_or_admin()` layers, ensuring a single source of truth without breaking backwards compatibility.
- **Authoritative Backend Security:** Direct URLs, POST requests, and AJAX actions (`purchase_order_update_status_ajax`, `purchase_order_action`, `purchase_return_order_action`, etc.) strictly enforce both action permissions and object-level geographical scoping (`can_user_access_object`). Manager attempts to view or alter records belonging to other Governorates (e.g., Giza manager targeting Cairo orders) are rejected with HTTP 403 Forbidden.

## Configurable Organizational Authorization Architecture (`ScopeResolutionService`)

Replaced legacy role-name-based data filtering with a centralized, configurable module-level authorization system:

### 1. The 4 Granular Organizational Scopes
- **`OWN`**: Records belonging directly to the current user (e.g. `owner=user`, `created_by=user`, `assignee=user`, `assigned_user=user`).
- **`BRICK`**: Records belonging to the user's assigned Brick(s) (`Area.parent is not None`).
- **`AREA`**: Records belonging to the user's assigned Main Area (`Area.parent is None`), including all authorized child bricks.
- **`ALL`**: System-wide records across all areas, bricks, and users.

### 2. Independent View vs. Manage Scope Separation
Each module has independently configurable scopes for viewing and managing:
- **`view_scope`**: Governs read-only querysets, list views, detail views, dashboard KPIs, and form dropdown selectors.
- **`manage_scope`**: Governs mutations, creation, editing, deletion, status transitions, and approvals.

Configured per Role via `RoleModuleScope`, and customizable per user via `UserModuleScope` (when `user.has_custom_permissions = True`).

### 3. Centralized Scope Engine (`accounts.scope_service.ScopeResolutionService`)
- Centralized scope resolution with per-user request caching.
- QuerySet scoping: `get_scoped_queryset(queryset, user, model_name, scope_type)`.
- Object-level security: `can_user_access_object(user, obj, action)`.
- Anti-self-approval systematically enforced across all status mutations.
- Dropdown & autocomplete scoping: `get_scoped_choices(user, target_choice_type, context_module)`.

### 4. Default Role Scopes

| Module | SuperAdmin | Manager | Accountant | Representative |
|---|---|---|---|---|
| `contacts` | ALL / ALL | AREA / AREA | ALL / ALL | BRICK / BRICK |
| `activities` | ALL / ALL | AREA / AREA | OWN / OWN | BRICK / OWN |
| `sales` | ALL / ALL | AREA / AREA | ALL / ALL | OWN / OWN |
| `purchases` | ALL / ALL | AREA / AREA | ALL / ALL | OWN / OWN |
| `inventory` | ALL / ALL | AREA / AREA | ALL / ALL | OWN / OWN |
| `treasury` | ALL / ALL | AREA / AREA | ALL / ALL | OWN / OWN |
| `accounts` | ALL / ALL | AREA / OWN | OWN / OWN | OWN / OWN |

## Data isolation by model

Implemented in `get_scoped_queryset` / `can_user_access_object`:

| Model | Rep (Typical) | Manager (Typical) | Accountant | SuperAdmin |
|---|---|---|---|---|
| Visit | owner/created_by within assigned Brick(s) | managed reps or client within assigned Main Area | own visits only | all |
| PlannedVisitDay | assignee (clients within assigned Brick) | assignees in managed reps (Main Area) | none | all |
| Agreement | created_by | created_by in managed reps | all (view) | all |
| Contact | created_by, assigned_team, or brick | area in managed areas or created/assigned by managed reps | all | all |
| SalesOrder / SalesReturn / Collection | created_by | created_by in managed reps | all | all |
| PurchaseOrder / Return | created_by | created_by, warehouse assignee, or warehouse area | all | all |
| Warehouse | assigned_user, `is_main`, or own brick | main + assigned to managed reps + area | all | all |
| Vault | assigned_user or own brick | assigned to self or managed reps | all | all |
| ProductTransferRequest | requester or warehouse assignee | those involving managed reps/areas; **cannot approve/execute** | view + approve/execute | all |
| User | self | self + users in managed areas; cannot edit other managers/superadmins | **none** | all |

Unknown model names: queryset is **not** filtered. Always pass the lowercase Django model name listed above.

**Visit client picker & geographical hierarchy (`get_visit_eligible_contacts_queryset`):** `customers_search_api`, `/visits/create/`, and `/planned-visits/` filter contacts strictly by geographical scope:
- **SuperAdmin:** all active contacts across all areas and bricks.
- **Manager:** contacts within their assigned **Main Area** (`Area.parent is None` + child bricks).
- **Representative:** contacts strictly within their assigned **Brick(s)** (`Area.parent is not None`). Cannot create or access visits for contacts in sibling bricks or other areas.

## Approval, distance validation, and status rules

- **Anti-self-approval** enforced on all status transitions (`approve`, `reject`, `disapprove`) across Visits, Agreements, Orders, and Transfers. Creators cannot approve their own submissions; regional managers or superadmins are required. Approved agreements log to `SecurityAuditLog`.
- **Treasury transaction scoping:** Viewing a vault (`'view'`) does not allow funds mutations. `vault_deposit` and `vault_withdraw` strictly enforce `'deposit'` and `'withdraw'` action scoping requiring `treasury:vaults/transfer` / `treasury:transactions/create` permissions and assigned or regional eligibility.
- **SettingsService request-lifecycle caching:** In-memory caching for singleton configuration models (`CompanyProfile`, `LocationSettings`, `SalesSettings`, `PurchaseSettings`, `UserSettings`) is bound to the HTTP request lifecycle (`request_started` / `request_finished`) and invalidated on model mutations (`post_save` / `post_delete`). Non-request execution (unit tests, CLI) fetches fresh from DB, guaranteeing zero cross-test state leakage.
- **Visit Type Determination (Automatic Planned vs. Unplanned):**
  - Planned and unplanned visits are determined strictly by workflow, without manual selection:
    - **Unplanned visits:** Initiated only via `/visits/create/` (global `+` button or Visits list Create button). The backend strictly sets `is_planned=False`. Manual radio/dropdown selection has been completely removed.
    - **Planned visits:** Created exclusively through the bulk daily planning workflow (`/planned-visits/`). Executing a planned item passes `planned_item_id`, which sets `is_planned=True` and links `item.visit = visit`.
    - **Server-side enforcement:** `visit_create` rejects or ignores attempts to set `is_planned=True` or `visit_type='planned'` via POST parameters unless a valid `planned_item_id` is supplied.
- **Visit Scheduled Time & Inline Quick-Action:**
  - Visits support a dedicated `time` (`TimeField`) and localized Arabic 12-hour property `formatted_time`.
  - Quick action endpoint `POST /activities/visits/<pk>/set-time/` allows updating the scheduled time without page reload via inline modals on both Visits list and Visit detail pages. Scoped to authorized users and audited via `SecurityAuditLog`.
- **Contact and Address Brick Relationships:**
  - Both `Contact` and `ContactAddress` maintain direct ForeignKeys to `area` (Governorate, `parent__isnull=True`) and `brick` (Subarea, `parent__isnull=False`).
  - Forms support dynamic governorate-to-brick cascading, and the backend automatically deduces governorate from `brick.parent` when omitted.
- **Bulk Planned Visits Client-Type Grouping:**
  - In `/planned-visits/`, selecting clients across multiple client types (e.g. Pharmacies, Clinics, Hospitals) groups them by `account_type`.
  - A separate visit-template selector is rendered for each group with eligible templates. The backend validates all client-template assignments atomically.
- **GBS (GPS Verification) Settings Enforcement:**
  - When `LocationSettings.verify_visits` is disabled, GPS verification does not block visit creation, start, or checkout on frontend or backend, and UI indicators display non-blocking informative states.
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
- `get_subareas` (`/contacts/api/subareas/`) is an authenticated JSON endpoint guarded by `@require_permission` returning HTTP 401 JSON on unauthenticated access.
