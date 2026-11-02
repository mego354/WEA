# Testing strategy

## Runner

The project uses **Django's test runner** and the default database from `config/settings.py` (SQLite in this checkout).

```bash
python manage.py test
python manage.py test accounts sales.tests inventory.tests_transfers
python manage.py test tests_erp_audit
```

There is no `pytest.ini`. Do not assume PostgreSQL behavior under SQLite.

**Discovery:** `manage.py test` with no labels loads tests from **installed apps** (`tests.py`, `test*.py`, `tests/` packages). Modules at the **repository root** (`tests_erp_audit.py`, `test_e2e_workflows.py`, `test_responsive_viewports.py`, `test_visit_location_e2e.py`) run only when named explicitly.

`scratch/test_*.py` and Playwright scripts are **not** part of CI unless you invoke them yourself. `seed_test_users.py` is a seeder, not a test.

## File layout (current)

Large apps already split tests by concern. That is allowed. Do not smash everything into one unreadably large `tests.py`.

| Location | Role |
|---|---|
| `accounts/tests.py` | User/role views, models |
| `accounts/tests_data_scoping.py` | ABAC / main-area isolation |
| `accounts/tests_area_approvals.py` | Manager eligibility |
| `accounts/tests_audit_logging.py` | `AuditLogService` + audit UI |
| `accounts/tests_roles_consolidation.py` | Canonical five roles |
| `accounts/tests_rep_provisioning.py` | Auto warehouse/vault |
| `accounts/tests_user_dedicated_pages.py` | User pages / location bypass |
| `accounts/tests_geographic_areas_selector.py` | Area selector |
| `activities/tests.py` plus `tests_agenda`, `tests_approval_and_regional`, `tests_suggested_products`, `tests_user_workflows` | Visits/approvals, dynamic distance thresholds, planned vs unplanned distance validation, completion distance exceptions & manager bypass, post-approval editing re-approval & timeline (`build_visit_timeline`), 3-tier geographical hierarchy (Superadmin / Manager Main Area / Rep Brick), and bulk daily planned visit scheduling (`VisitManagementImprovementsTestCase`) |
| `sales/tests.py`, `sales/tests_rep_sales.py` | Sales |
| `inventory/tests.py`, `inventory/tests_transfers.py` | Stock / transfers |
| `treasury/tests.py`, `treasury/tests_treasury_rbac_and_stats.py` | Vaults |
| `contacts/tests.py`, `contacts/tests_udf_todos_timeline.py` | Contacts |
| `purchases/tests.py`, `catalog/tests.py` | CRUD/export |
| `master_data/tests.py`, `tests_egypt_areas.py`, `tests_dashboard_roles.py`, `tests_admin.py`, `test_pagination_filters.py` | Settings/dashboard |
| `tests_erp_audit.py` (root) | Cross-app purchase/sales/treasury audit |

When adding tests: put them next to the existing file for that concern. Create `tests/` packages only if a single file exceeds ~800 lines and splitting helps.

## Required categories

Cover, where the feature exists:

1. Model constraints and status transitions
2. Authentication and `@require_permission` (403/401)
3. Manager limited to same **main area** (including different sub-areas)
4. SuperAdmin global access
5. Cross-area / cross-rep isolation (IDOR on `/<pk>/`)
6. CRUD validation
7. JSON API shape for endpoints you change
8. `SecurityAuditLog` / `ApprovalAuditLog` on success (and failed authz where relevant)
9. `transaction.atomic` rollback on service `ValidationError`
10. Cross-app workflows (order → stock → ledger)
11. Filters, pagination, Excel export
12. Template/mobile only if you have a browser runner
13. Regression for the bug you just fixed

Use `TestCase` + Django `Client`. Create canonical `Role` rows with `Role.ROLE_*` constants. Prefer real ORM over mocking services.

## Consolidation policy

- Keep security, scoping, and audit tests even if they overlap slightly.
- Merge only when two classes assert the same path with weaker copies.
- Never delete a failing test to “clean up”; fix the product or mark the limitation in docs.

## Reporting

State command, pass/fail counts, and whether failures existed before your change (baseline). Never claim green without running.
