# WEA Pharma ERP — Agent Engineering Contract

This file is the **mandatory entry point** for every AI coding task. Read it before changing code. It describes how this repository actually works, not a generic Django template.

Detailed guides live in [`docs/`](docs/README.md). If this contract and a detailed guide disagree, **inspect the code**, then update both documents together.

## A. Mandatory instructions

1. Read this file before making changes.
2. Read the relevant documents in [`docs/README.md`](docs/README.md) before modifying a feature (architecture, permissions, UI, audit, API, tests, or deployment).
3. Inspect the existing implementation (models, views, services, templates, URL names, tests) before editing it.
4. Identify affected apps, models, APIs, permissions, templates, tests, and related workflows before changing anything.
5. Follow established project patterns unless there is a documented reason to improve them.
6. Do not create parallel implementations of existing functionality.
7. Do not invent models, fields, routes, permission rules, or API behavior.
8. Do not silently change business rules or existing data.
9. Do not remove a feature simply because it appears unused; search URL names, templates, signals, admin, management commands, and imports first.
10. Update documentation, API contracts, and tests whenever behavior or architecture changes.
11. Run relevant tests and checks before reporting completion.
12. Never claim that a test passed if it was not executed successfully.
13. Report incomplete work, known risks, and unverified assumptions.

## B. Project architecture (actual)

Django project package: `config`. Custom user: `accounts.User`. UI language: Arabic RTL (`LANGUAGE_CODE = 'ar'`). Currency: EGP. Time zone: `Africa/Cairo`. Local database: SQLite (`db.sqlite3`). No Django REST Framework, Celery, or pytest configuration is installed.

### Apps

| App | Responsibility |
|---|---|
| `accounts` | Users, canonical roles, permission registry, RBAC/ABAC helpers, security audit log, login |
| `master_data` | Areas (governorate → subarea), company profile, location/sales/purchase settings, dashboard/home, geocoding |
| `contacts` | Customers/vendors, canonical English statuses (`customer`, `lead`, `inactive`), `sync_contact_statuses`, UDF, todos, timeline, Excel import/export, search APIs |
| `catalog` | Products, categories, volume discounts, Excel import/export |
| `inventory` | Warehouses, stock, lots, memos, inter-warehouse transfer requests |
| `purchases` | Purchase orders/returns, stock receive, vendor invoice settlement |
| `treasury` | Vaults, deposits/withdrawals/transfers, vendor payments and ledgers |
| `sales` | Sales orders, sales returns, collections, customer accounts/transactions |
| `activities` | Visits, planned visits, visit plans, agreements, visit templates, agenda, approval hub, GPS integrity |
| `reports` | Performance analytics dashboards and 8 standalone financial/operational Excel & print reports |
| `notifications` | Centralized Capacitor-ready notification system (61 events across 11 apps, Role Settings rules, 4-layer DataScope, `/api/v1/notifications/` & device registration) |

Business mutations for sales, purchases, treasury, and stock transfers belong in `*/services.py` with `@transaction.atomic`. HTTP views authenticate, authorize, validate input, call services, and render templates. Shared UI: `templates/layouts/base.html` (Tailwind CDN, Cairo, Material Symbols, Leaflet). Full map: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

### Request flow

Browser/AJAX → `config/urls.py` (includes plus **reference-ERP URL aliases**) → app `urls.py` → `@require_permission` / `get_scoped_queryset` / `can_user_access_object` → view or service → model save → `AuditLogService` and/or `ApprovalAuditLog`.

## C. Mandatory business and permission rules

Enforced in `accounts.scope_service.ScopeResolutionService`, `accounts.permissions`, and `accounts.User.has_permission`. Details: [`docs/AUTHORIZATION.md`](docs/AUTHORIZATION.md) and [`docs/BUSINESS_LOGIC.md`](docs/BUSINESS_LOGIC.md).

1. **Configurable Module Scopes (`OWN`, `BRICK`, `AREA`, `ALL`)**: All organizational data access is resolved through `ScopeResolutionService` based on configurable `view_scope` and `manage_scope` per module (stored in `RoleModuleScope` and managed exclusively via Role Settings; individual per-user effective-permissions overrides have been removed). Hardcoded role-name checks must never control data access or authorization.
2. **Superadmin** (`User.is_superuser` or active role `name='superadmin'` / `role.is_super`): system-wide access to records and admin functions. Role/RBAC screens and audit log UI remain SuperAdmin-gated.
3. **Managers**: access representatives, customers, and records whose **canonical root main area** (governorate, `Area.parent is None`) intersects the manager's assigned areas (including all child bricks inside that main area). Sub-area equality is **not** required for managers. A Cairo manager may supervise Nasr City and Maadi reps. A Giza manager must not see Cairo records. Managers with **no** assigned main area fail closed (empty scope).
4. **Representatives** (`rep`, `medical_rep`): own created/assigned records only, and for visit creation/planning are restricted to customers in their assigned **Brick(s)** (`Area.parent is not None`). No peer-rep access inside the same area.
5. **Accountant**: broad **view** of financial, sales, purchase, treasury, and inventory records; not user-admin; transfer **approval/execute** is governed by `inventory:transfers/approve` and module manage scope.
6. **Server-side enforcement**: `@require_permission`, `has_perm_or_admin`, `get_scoped_queryset`, `can_user_access_object`, `get_visit_eligible_contacts_queryset`. Hiding a sidebar link is not authorization.
7. **Data isolation**: never return another area's or user's records merely because an ID is known.
8. **Consistency**: same scope on list, detail, create, update, delete, export, approval, and related operations.
9. **Auditability**: mutations must write `SecurityAuditLog` via `AuditLogService` (and visit/order workflow history via `ApprovalAuditLog` where that model is used).
10. **No unauthorized bypasses**: SuperAdmin exceptions must stay explicit. Settings flags such as `allow_all_users_to_create_visits` grant **create/list permission**, not cross-area data.
11. **Anti-self-approval**: a user cannot approve/reject their own visit, order, or transfer.
12. **Post-approval editing**: when a Representative edits an already-approved visit, approval is automatically invalidated (`approval_status='pending'`, `waiting_for_reapproval=True`) while preserving prior `ApprovalAuditLog` history.
13. **Visit & Planned-Item Deletion (Any Stage)**: authorized users holding `activities:visits/delete` (`حذف الزيارات`) within object-level DataScope may delete visits at any lifecycle stage (`planned`, `started`, `finished`, `cancelled`), decoupled from `LocationSettings`. Deletion removes linked `PlannedVisitItem`s and empty parent `VisitPlan`s, cleans up unshared attachments/`Visit.photo`, and preserves the snapshot + `ApprovalAuditLog` history in `SecurityAuditLog`. Deleting items in `/planned-visits/` is allowed regardless of `pending` approval, and deleting an item whose linked visit has started or finished additionally requires `activities:visits/delete`.
14. **Atomic Unplanned Visits & Single Open Visit per Owner**: unplanned `POST /visits/create/` locks `date=timezone.localdate()` and atomically creates + starts (`create_and_start_unplanned_visit`), rolling back completely on any failure. Partial DB `UniqueConstraint` (`unique_open_visit_per_owner`) + service locks enforce at most one open visit (`status='started'`, `ended_at IS NULL`) per `visit.owner` across all roles (zero bypass).
15. **GPS Bypass & Visit/Plan Notifications**: GPS bypass is gated exclusively on `activities:visits/bypass_gps` (`gps_request_exception` is unwired). Standalone visit creation emits 1 visit notification (`activities.visit_created` or `activities.visit_pending_approval`); bulk planning suppresses per-visit notifications and emits 1 `activities.plan_submitted` notification.
16. **Visit Address Selection & No Auto-Saved GPS**: Visits bind to a specific `contacts.ContactAddress` (`Visit.contact_address`, validated server-side to belong to `visit.contact`) with immutable snapshots (`contact_address_title`, `contact_address_text`, `customer_latitude_snapshot`, `customer_longitude_snapshot`) used consistently for both Start and End GPS verification. When the selected address has no GPS coordinates, the system **never** auto-saves device coordinates onto any `ContactAddress` or `Contact` (authorized `activities:visits/bypass_gps` is required when verification is enabled).
17. **Mutually Exclusive Agenda Sections**: `/agenda/` organizes visits into two non-overlapping sections: `زيارات اليوم` (top — all unfinished planned/started/unplanned visits) and `الزيارات الفعلية` (bottom — all finished visits). Every visit appears in at most one section (`today_visits_count + actual_visits_count == total_visits_count`); cancelled visits are excluded from both.
18. **Customer-Only Sales & Unplanned Visit Selectors + Preserved Historical Leads**: `ScopeResolutionService.get_scoped_choices(user, 'customers', ...)` and `sales_customers_search_api` return ONLY `is_customer=True, status='customer'` (excluding `lead` and `inactive`). Unplanned visit creation (`VisitForm` when not editing and without `planned_item_id`, `customers_search_api?customers_only=1`, and `create_and_start_unplanned_visit`) also strictly requires `status='customer'`, while Planned Visits (`get_visit_eligible_contacts_queryset` / default `customers_search_api`) continue allowing `lead`. New Sales Orders strictly require `status='customer'`; editing an existing historical `lead` Sales Order allows keeping its current `lead` customer (rejecting switches to other `lead`/`inactive` contacts); Sales Returns and Collections against legitimate historical `lead` orders/balances remain permitted while rejecting `inactive` or history-less `lead` contacts.
19. **Account-Level Financial Single Source of Truth, Non-Cash Settlements & Manual `payment_status`**: `CustomerAccount` + `CustomerTransaction` (receivables, including `due_this_month_balance`) and `VendorAccount` + `VendorTransaction` (payables) are the sole authoritative sources of debt (`Contact.total_outstanding_balance` reads `CustomerAccount.current_balance`). Independent per-order debt UI/filters/PDF lines and per-order collection/payment caps have been removed. `SalesOrder.payment_status` and `PurchaseOrder.payment_status` are 100% manually controlled and never auto-modified by collections, payments, or settlements. Non-cash account settlements (`CustomerAccountService.record_settlement` / `reverse_settlement` and `TreasuryService.record_vendor_settlement` / `reverse_vendor_settlement`) adjust account balances via `reason='settlement'` with strictly **zero vault/cash/inventory impact**. Collections may be deposited into any active authorized vault regardless of `payment_method` (`cash`, `cheque`, `bank_transfer`). Safe financial reconstruction from verified `wea data/*.xlsx` files is handled by `python manage.py reconstruct_wea_financials` (defaults to `--dry-run`; requires `--apply --confirm-reset` and creates a verified SQLite backup + `SalesReturnOrderItem` JSON snapshot before any reset).

**Visit customer picker scoping:** `customers_search_api` excludes `status='inactive'` (and filters strictly to `status='customer'` when `customers_only=1` or `status=customer` is passed, as used by unplanned visit creation), returns ordered `addresses[]` per contact, and scopes contacts via `get_visit_eligible_contacts_queryset(qs, request.user)` (all areas for SuperAdmin, Main Area + child bricks for Manager, assigned Bricks for Representative). Text search matches `name`, `code`, `mobile`, `specialty`, and numeric `serial_num` (`area__name` and `brick__name` are excluded). Contact **list/detail** uses `get_scoped_queryset`.

## D. Code quality principles

- Keep code readable. Prefer Django patterns already used (function views + services + a few forms).
- DRY without speculative layers. Do not add DRF, Celery, or a new CSS framework.
- Put HTTP in views, rules in `accounts.permissions`, multi-step mutations in services, persistence in models.
- Validate on the server. Use the ORM. Wrap multi-table writes in `transaction.atomic`.
- No unused imports, duplicate URL **names**, hardcoded production secrets, or swallowed exceptions without logging.
- Preserve Arabic RTL, teal brand (`#27bebe`), and mobile patterns in [`docs/UI_UX_GUIDE.md`](docs/UI_UX_GUIDE.md).
- **Product Owner UI Preference**: Strict preference for simple, clean, compact UI without verbose notes, paragraphs, or oversized components. Present data concisely using icons and simple text. Avoid full-page refreshes on drawer/filter operations.
- Coding detail: [`docs/CODING_STANDARDS.md`](docs/CODING_STANDARDS.md).

## E. Mandatory completion checklist

Before reporting done, verify:

- [ ] Business workflows still match existing status machines
- [ ] Permissions and data isolation (including IDOR on `pk` URLs)
- [ ] Audit logs on mutation paths you touched
- [ ] Tests run (`python manage.py test <labels>`) — report real results
- [ ] API JSON consumers still match [`docs/API_REFERENCE.md`](docs/API_REFERENCE.md)
- [ ] Mobile + desktop UI if templates/CSS/JS changed
- [ ] Docs updated
- [ ] Migrations safe (no destructive surprise)
- [ ] Security/performance (N+1, `select_related`, scoped querysets)
- [ ] Remaining limitations stated

## Authoritative documents

| When | Read |
|---|---|
| Any task | This file |
| Index | [`docs/README.md`](docs/README.md) |
| Apps, URLs, services, workflows | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) |
| Roles, areas, scopes, matrix | [`docs/AUTHORIZATION.md`](docs/AUTHORIZATION.md) |
| Workflows, lifecycles, audits | [`docs/BUSINESS_LOGIC.md`](docs/BUSINESS_LOGIC.md) |
| Templates, Tailwind, mobile | [`docs/UI_UX_GUIDE.md`](docs/UI_UX_GUIDE.md) |
| Style, ORM, security coding | [`docs/CODING_STANDARDS.md`](docs/CODING_STANDARDS.md) |
| Test layout and commands | [`docs/TESTING.md`](docs/TESTING.md) |
| JSON/AJAX endpoints | [`docs/API_REFERENCE.md`](docs/API_REFERENCE.md) |
| Notifications & Capacitor deep linking | [`docs/notifications-deep-linking.md`](docs/notifications-deep-linking.md) |
| Local/prod operations | [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) |
