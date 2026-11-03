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
| `contacts` | Customers/vendors, UDF, todos, timeline, Excel import/export, customer search APIs |
| `catalog` | Products, categories, volume discounts, Excel import/export |
| `inventory` | Warehouses, stock, lots, memos, inter-warehouse transfer requests |
| `purchases` | Purchase orders/returns, stock receive, vendor invoice settlement |
| `treasury` | Vaults, deposits/withdrawals/transfers, vendor payments and ledgers |
| `sales` | Sales orders, collections, customer accounts/transactions |
| `activities` | Visits, planned visits, agreements, visit templates, agenda, approval hub |

Business mutations for sales, purchases, treasury, and stock transfers belong in `*/services.py` with `@transaction.atomic`. HTTP views authenticate, authorize, validate input, call services, and render templates. Shared UI: `templates/layouts/base.html` (Tailwind CDN, Cairo, Material Symbols, Leaflet). Full map: [`docs/architecture.md`](docs/architecture.md).

### Request flow

Browser/AJAX → `config/urls.py` (includes plus **reference-ERP URL aliases**) → app `urls.py` → `@require_permission` / `get_scoped_queryset` / `can_user_access_object` → view or service → model save → `AuditLogService` and/or `ApprovalAuditLog`.

## C. Mandatory business and permission rules

Enforced in `accounts/permissions.py` and `accounts.User.has_permission`. Details: [`docs/business-rules-and-permissions.md`](docs/business-rules-and-permissions.md).

1. **Superadmin** (`User.is_superuser` or active role `name='superadmin'` / `role.is_super`): system-wide access to records and admin functions. Role/RBAC screens and audit log UI remain SuperAdmin-gated.
2. **Managers**: access representatives, customers, and records whose **canonical root main area** (governorate, `Area.parent is None`) intersects the manager's assigned areas (including all child bricks inside that main area). Sub-area equality is **not** required for managers. A Cairo manager may supervise Nasr City and Maadi reps. A Giza manager must not see Cairo records. Managers with **no** assigned main area fail closed (empty scope).
3. **Representatives** (`rep`, `medical_rep`): own created/assigned records only, and for visit creation/planning are restricted to customers in their assigned **Brick(s)** (`Area.parent is not None`). No peer-rep access inside the same area.
4. **Accountant**: broad **view** of financial, sales, purchase, treasury, and inventory records; not user-admin; transfer **approval/execute** is SuperAdmin/accountant (plus `inventory:transfers/approve`).
5. **Server-side enforcement**: `@require_permission`, `has_perm_or_admin`, `get_scoped_queryset`, `can_user_access_object`, `get_visit_eligible_contacts_queryset`. Hiding a sidebar link is not authorization.
6. **Data isolation**: never return another area's or user's records merely because an ID is known.
7. **Consistency**: same scope on list, detail, create, update, delete, export, approval, and related operations.
8. **Auditability**: mutations must write `SecurityAuditLog` via `AuditLogService` (and visit/order workflow history via `ApprovalAuditLog` where that model is used).
9. **No unauthorized bypasses**: SuperAdmin exceptions must stay explicit. Settings flags such as `allow_all_users_to_create_visits` grant **create/list permission**, not cross-area data.
10. **Anti-self-approval**: a user cannot approve/reject their own visit, order, or transfer.
11. **Post-approval editing**: when a Representative edits an already-approved visit, approval is automatically invalidated (`approval_status='pending'`, `waiting_for_reapproval=True`) while preserving prior `ApprovalAuditLog` history.

**Visit customer picker scoping:** `customers_search_api` scopes active customers via `get_visit_eligible_contacts_queryset(request.user)` (all areas for SuperAdmin, Main Area + child bricks for Manager, assigned Bricks for Representative). Contact **list/detail** uses `get_scoped_queryset`.

## D. Code quality principles

- Keep code readable. Prefer Django patterns already used (function views + services + a few forms).
- DRY without speculative layers. Do not add DRF, Celery, or a new CSS framework.
- Put HTTP in views, rules in `accounts.permissions`, multi-step mutations in services, persistence in models.
- Validate on the server. Use the ORM. Wrap multi-table writes in `transaction.atomic`.
- No unused imports, duplicate URL **names**, hardcoded production secrets, or swallowed exceptions without logging.
- Preserve Arabic RTL, teal brand (`#27bebe`), and mobile patterns in [`docs/ui-ux-guidelines.md`](docs/ui-ux-guidelines.md).
- **Product Owner UI Preference**: Strict preference for simple, clean, compact UI without verbose notes, paragraphs, or oversized components. Present data concisely using icons and simple text. Avoid full-page refreshes on drawer/filter operations.
- Coding detail: [`docs/coding-standards.md`](docs/coding-standards.md).

## E. Mandatory completion checklist

Before reporting done, verify:

- [ ] Business workflows still match existing status machines
- [ ] Permissions and data isolation (including IDOR on `pk` URLs)
- [ ] Audit logs on mutation paths you touched
- [ ] Tests run (`python manage.py test <labels>`) — report real results
- [ ] API JSON consumers still match [`docs/api-contracts.md`](docs/api-contracts.md)
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
| Apps, URLs, services, workflows | [`docs/architecture.md`](docs/architecture.md) |
| Roles, areas, approvals, matrix | [`docs/business-rules-and-permissions.md`](docs/business-rules-and-permissions.md) |
| Templates, Tailwind, mobile | [`docs/ui-ux-guidelines.md`](docs/ui-ux-guidelines.md) |
| Style, ORM, security coding | [`docs/coding-standards.md`](docs/coding-standards.md) |
| Test layout and commands | [`docs/testing-strategy.md`](docs/testing-strategy.md) |
| `SecurityAuditLog` / `ApprovalAuditLog` | [`docs/audit-logging.md`](docs/audit-logging.md) |
| JSON/AJAX endpoints | [`docs/api-contracts.md`](docs/api-contracts.md) |
| Local/prod operations | [`docs/maintenance-and-deployment.md`](docs/maintenance-and-deployment.md) |

Historical notes (not the contract): [`docs/archive/`](docs/archive/README.md).
