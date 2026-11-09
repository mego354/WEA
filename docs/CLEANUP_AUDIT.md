# WEA Pharma ERP — Cleanup Audit & Inventory

**Date:** November 2026  
**Auditor:** Antigravity Pairing Agent  
**Repository:** WEA Pharma ERP  
**Reference Document:** `AGENTS.md`

---

## 1. Executive Summary

This document establishes the initial inventory, risk analysis, and migration plan prior to performing any deletions, file relocations, or test consolidations across the repository.

The goal of this cleanup is to transition the repository to a clean, production-grade layout by:
1. Deleting obsolete development artifacts, prototype directories (`scratch/`), untracked migration caches (`migration/`), and outdated database backups (`backups/`).
2. Consolidating fragmented Django test suites into **one primary `tests.py` per app**, eliminating redundant tests while preserving comprehensive behavioral coverage.
3. Consolidating the documentation tree from over 85 fragmented/archived files into a concise set of 9 authoritative, actively maintained documents in `docs/`.
4. Removing confirmed dead templates and ad-hoc scripts.
5. Updating all internal imports, URL routes, configuration links, and documentation cross-references.

---

## 2. Current Repository Structure & Inventory

```
ERP/
├── accounts/                  # Users, canonical roles, RBAC/ABAC scope resolution, security audit
│   ├── management/commands/   # Permission sync, role migration, rep resource backfill
│   ├── migrations/            # Django migrations (PRESERVED)
│   └── 11 test files          # tests.py + 10 specialized tests_* files (PROPOSED FOR CONSOLIDATION)
├── activities/                # Field visits, agendas, agreements, visit templates, approvals
│   ├── management/commands/   # Seed activities command
│   ├── migrations/            # Django migrations (PRESERVED)
│   └── 6 test files           # tests.py + 5 specialized tests_* files (PROPOSED FOR CONSOLIDATION)
├── catalog/                   # Products, categories, volume discounts
│   ├── migrations/            # Django migrations (PRESERVED)
│   └── tests.py               # Single test file (PRESERVED & ENHANCED)
├── contacts/                  # Customers, vendors, addresses, UDFs, timeline
│   ├── migrations/            # Django migrations (PRESERVED)
│   └── 2 test files           # tests.py, tests_udf_todos_timeline.py (PROPOSED FOR CONSOLIDATION)
├── inventory/                 # Warehouses, stock lots, memos, transfers
│   ├── migrations/            # Django migrations (PRESERVED)
│   └── 3 test files           # tests.py, tests_transfers.py, tests_warehouse_operations.py (CONSOLIDATE)
├── master_data/               # Areas (Egypt governorates & bricks), company settings, dashboard
│   ├── management/commands/   # Egypt areas setup, Excel data import
│   ├── migrations/            # Django migrations (PRESERVED)
│   └── 5 test files           # tests.py, tests_admin.py, tests_dashboard_roles.py, etc. (CONSOLIDATE)
├── purchases/                 # Purchase orders, returns, vendor settlement
│   ├── migrations/            # Django migrations (PRESERVED)
│   └── tests.py               # Single test file (PRESERVED & ENHANCED)
├── sales/                     # Sales orders, collections, customer statements
│   ├── migrations/            # Django migrations (PRESERVED)
│   └── 3 test files           # tests.py, tests_rep_sales.py, tests_sales_workflow.py (CONSOLIDATE)
├── treasury/                  # Cash vaults, transactions, deposits/withdrawals, vendor payments
│   ├── migrations/            # Django migrations (PRESERVED)
│   └── 2 test files           # tests.py, tests_treasury_rbac_and_stats.py (CONSOLIDATE)
├── config/                    # Django project core (settings, URLs, ASGI, WSGI)
├── templates/                 # 93 HTML templates across apps & shared components
├── static/                    # Custom CSS/JS (table_column_manager.js) and libs (echarts.min.js)
├── media/                     # Uploaded avatars, product images, visit evidence photos (PRESERVED)
├── data_folder/               # Directory for user-supplied business Excel files (PRESERVED)
├── backups/                   # 14 old sqlite database dumps (~94 MB) (PROPOSED FOR DELETION)
├── scratch/                   # 342 temporary screenshots, JSON dumps, ad-hoc scripts (DELETE)
├── migration/                 # 508 untracked Edge browser cache files, temp dumps (DELETE)
├── docs/                      # Active guides + 74 archived documents (PROPOSED FOR CONSOLIDATION)
│   └── archive/               # Historical notes and implementation plans (DELETE AFTER TRANSFER)
└── Root files:
    ├── AGENTS.md              # Core engineering contract (PRESERVED & UPDATED)
    ├── manage.py              # Django CLI entrypoint (PRESERVED)
    ├── db.sqlite3             # Active local development database (PRESERVED)
    ├── .gitignore             # Git ignore configuration (PRESERVED & UPDATED)
    ├── seed_*.py              # 3 root data seed scripts (PRESERVED)
    ├── tests_erp_audit.py     # Cross-app integration test suite (CONSOLIDATE INTO APPS)
    └── test_*.py              # 5 ad-hoc playwright/smoke scripts (REMOVE OBSOLETE SCRIPTS)
```

---

## 3. Inventory of Files Reviewed & Proposed Actions

### A. Folders and Files Proposed for Deletion

| Path / Pattern | Type | Count | Size | Reason for Deletion |
|---|---|---|---|---|
| `scratch/` | Directory | 342 files | ~15.2 MB | Temporary development folder used during design prototyping. Designs and views are now fully implemented in production templates. Contains obsolete screenshots and exploratory scripts. |
| `migration/` | Directory | 508 files | ~44.2 MB | Untracked temporary directory containing dumped Edge browser user profile, cache, and old migration scrape artifacts. |
| `backups/` | Directory | 14 files | ~94.1 MB | Outdated local SQLite database dumps from October 2026 (`db_backup_*.sqlite3`). Redundant, untracked/historical, wasting repository storage. |
| `docs/archive/` | Directory | 74 files | ~0.7 MB | Historical task checklists, old implementation todos, obsolete UI audits. All relevant rules are captured in active documentation. |
| `docs/AUTHORIZATION_INVESTIGATION.md` | File | 1 file | ~47 KB | Intermediate planning document for authorization refactoring. Refactoring is complete and tested. |
| `docs/AUTHORIZATION_IMPLEMENTATION_PROMPT.md` | File | 1 file | ~21 KB | Historical instruction prompt for the authorization refactoring task. |
| `templates/dashboard/branding_settings.html` | File | 1 file | ~4 KB | Obsolete duplicate of `templates/settings/branding_settings.html`. Never rendered by any view. |
| `templates/approvals/approvals_hub.html` | File | 1 file | ~32 KB | Obsolete template from discontinued standalone approvals page. `approvals_hub` view now executes canonical 302 redirects to domain detail pages. |
| `test_browser_workflow_perms.py` | File | 1 file | ~26 KB | Ad-hoc Playwright script left at root; not part of Django test runner. |
| `test_hero_and_kanban_browser.py` | File | 1 file | ~12 KB | Ad-hoc Playwright script left at root; not part of Django test runner. |
| `test_responsive_viewports.py` | File | 1 file | ~3 KB | Ad-hoc viewport check script with hardcoded test client calls. |
| `test_visit_location_e2e.py` | File | 1 file | ~14 KB | Ad-hoc manual verification script operating on development database. |
| `test_e2e_workflows.py` | File | 1 file | ~27 KB | Ad-hoc manual verification script with hardcoded credentials and database mutation. |
| Root `__pycache__/` | Directory | 6 files | ~0.1 MB | Generated Python bytecode at repository root. |

### B. Test Files Proposed for Consolidation

Target: **Exactly one primary `tests.py` file per Django app** (`app_name/tests.py`).

| App | Existing Test Files | Target File | Action & Scope |
|---|---|---|---|
| `accounts` | `tests.py`, `tests_area_approvals.py`, `tests_audit_logging.py`, `tests_configurable_scopes.py`, `tests_data_scoping.py`, `tests_geographic_areas_selector.py`, `tests_refactored_settings_and_scope.py`, `tests_rep_provisioning.py`, `tests_roles_consolidation.py`, `tests_user_dedicated_pages.py`, `tests_user_permissions_control.py` | `accounts/tests.py` | Consolidate into structured test classes (`AuthenticationTests`, `RoleAndScopeTests`, `DataScopingTests`, `PermissionControlTests`, `AuditLoggingTests`, `UserViewTests`). Remove old files. |
| `activities` | `tests.py`, `tests_agenda.py`, `tests_approval_and_regional.py`, `tests_suggested_products.py`, `tests_user_workflows.py`, `tests_visits_scope_gbs.py` | `activities/tests.py` | Consolidate into structured test classes (`VisitModelAndLifecycleTests`, `VisitPermissionAndScopingTests`, `AgendaTests`, `AgreementAndApprovalTests`, `VisitTemplateTests`). Remove old files. |
| `contacts` | `tests.py`, `tests_udf_todos_timeline.py` + contacts tests from `tests_erp_audit.py` | `contacts/tests.py` | Consolidate customer/vendor tests, UDF, Todos, Timeline, and Subareas API tests into one comprehensive file. Remove `tests_udf_todos_timeline.py`. |
| `inventory` | `tests.py`, `tests_transfers.py`, `tests_warehouse_operations.py` | `inventory/tests.py` | Consolidate warehouse management, stock tracking, inventory memos, and inter-warehouse transfer workflows into `inventory/tests.py`. Remove extra files. |
| `master_data` | `tests.py`, `tests_admin.py`, `tests_dashboard_roles.py`, `tests_egypt_areas.py`, `test_pagination_filters.py` + settings tests from `tests_erp_audit.py` | `master_data/tests.py` | Consolidate governorates/bricks, company profile, location/sales settings, dashboard KPIs, and pagination/filter tests into `master_data/tests.py`. Remove extra files. |
| `purchases` | `tests.py` + PO lifecycle/payment tests from `tests_erp_audit.py` | `purchases/tests.py` | Retain `purchases/tests.py` as primary, incorporate PO lifecycle and vendor payment linking assertions. |
| `sales` | `tests.py`, `tests_rep_sales.py`, `tests_sales_workflow.py` + sales tests from `tests_erp_audit.py` | `sales/tests.py` | Consolidate sales orders, order items, collection workflows, rep isolation, and customer transactions into `sales/tests.py`. Remove extra files. |
| `treasury` | `tests.py`, `tests_treasury_rbac_and_stats.py` + vault tests from `tests_erp_audit.py` | `treasury/tests.py` | Consolidate cash vault operations, deposits/withdrawals, vendor payments, and treasury RBAC into `treasury/tests.py`. Remove extra files. |
| `catalog` | `tests.py` | `catalog/tests.py` | Single file already; verify completeness and maintainability. |
| Root | `tests_erp_audit.py` | Distributed to apps | 13 integration tests distributed into corresponding app `tests.py` files. Root file deleted. |

### C. Documentation Files Proposed for Consolidation

Target documentation structure in `docs/`:

| Source File(s) | Target Active Document | Summary of Contents Preserved |
|---|---|---|
| `docs/README.md` | `docs/README.md` | Project overview, tech stack, architecture summary, local setup, navigation index. |
| `docs/architecture.md` | `docs/ARCHITECTURE.md` | Full app breakdown, services, models, request flow, transaction patterns. |
| `docs/business-rules-and-permissions.md`, `docs/audit-logging.md` | `docs/BUSINESS_LOGIC.md` | Business workflows, order/visit lifecycles, financial rules, audit logging requirements. |
| `docs/AUTHORIZATION_INVESTIGATION.md` (active rules) + scope documentation | `docs/AUTHORIZATION.md` | Configurable module scopes (`OWN`, `BRICK`, `AREA`, `ALL`), canonical roles, `ScopeResolutionService`, server-side enforcement. |
| `docs/ui-ux-guidelines.md` | `docs/UI_UX_GUIDE.md` | Arabic RTL design system, teal branding, compact UI principles, mobile-first responsiveness, components. |
| `docs/coding-standards.md` | `docs/CODING_STANDARDS.md` | Naming, DRY/SOLID, service layer design, query optimization (`select_related`), security standards. |
| `docs/testing-strategy.md` | `docs/TESTING.md` | Test suite architecture, test execution commands, coverage guidelines, isolation standards. |
| `docs/maintenance-and-deployment.md` | `docs/DEPLOYMENT.md` | Local setup, seed commands, production settings, PythonAnywhere deployment, backup/restore. |
| `docs/api-contracts.md` | `docs/API_REFERENCE.md` | JSON contracts for AJAX endpoints (customer search, subareas, geofencing, agenda, table columns). |

---

## 4. Protected Assets & Non-Deletable Resources

The following items are strictly protected and will NOT be deleted or altered:
1. **Django Migrations:** Every migration in all 9 apps (`accounts/migrations/`, `activities/migrations/`, etc.) is retained.
2. **Media Assets:** All user and demo uploads in `media/` (contacts, products, visit evidence) are retained.
3. **Core Static Assets:** `static/js/table_column_manager.js` and `static/libs/echarts.min.js` are retained.
4. **Active Database:** `db.sqlite3` is preserved.
5. **Seed Scripts:** `seed_initial_data.py`, `seed_test_users.py`, and `seed_comprehensive_test_data.py` are preserved.
6. **Data Directory:** `data_folder/` is preserved for Excel imports.
7. **Uncommitted User Changes:** Any unstaged user modifications in git status are strictly respected.

---

## 5. Potential Risks & Mitigation Strategy

| Risk | Mitigation |
|---|---|
| **Test Discovery Failure:** Moving tests to a single `tests.py` might miss tests or break discovery. | Verify that each app's `tests.py` uses standard Django `TestCase` classes. Execute `python manage.py test <app>` individually and then `python manage.py test` to confirm all tests run. |
| **Broken Documentation Links:** Renaming `docs/*.md` might break links in `AGENTS.md` and elsewhere. | Search for all references to `docs/` and update `AGENTS.md`, `README.md`, and internal cross-references to use the new canonical uppercase names. |
| **Import Errors in Consolidated Tests:** Tests from different files may have conflicting helper functions or duplicate names. | Group tests into clearly named classes (`ModelTests`, `ViewTests`, `ScopeTests`, etc.), deduplicate helper methods, and run tests iteratively per app. |
| **IDOR / Scoping Regressions:** Inadvertently removing an authorization test could mask a security hole. | Ensure every scoping test (representative isolation, manager territorial boundary, superadmin bypass, accountant view) is retained and passing. |

