# Settings, Users, and Permissions Test Plan

> **System**: WEA Pharma ERP  
> **Target Scope**: Settings, Users, and RBAC Permissions Parity  
> **Test Environment**: Local Django Instance (`py manage.py test` & live HTTP requests)  
> **Exclusions**: Calls and Assessments are excluded from testing and scope.

---

## 1. Test Objectives

1. Verify 100% functional parity for all in-scope Settings tabs and User/Role management.
2. Ensure strict backend authorization enforcement preventing unauthorized access via direct URL or POST requests.
3. Guarantee that the existing local superuser account retains full administrative access and cannot be accidentally deleted or deactivated.
4. Verify visual and styling parity with the reference application.

---

## 2. Test Suite Matrix

### Suite 1: Authentication & Superuser Retention
- **TC-AUTH-01**: Existing superuser (`wea.pharm2020@gmail.com`) can authenticate successfully.
- **TC-AUTH-02**: Superuser has unrestricted access to all `/settings/*` and `/users/*` routes.
- **TC-AUTH-03**: Last active superuser cannot be deactivated or deleted via the UI or API.

### Suite 2: Users Management
- **TC-USER-01**: User directory `/settings/users` renders all existing users with columns: `الاسم`, `البريد الإلكتروني`, `مفعل`, `الدور`.
- **TC-USER-02**: Search filter dynamically finds users by name, email, or code.
- **TC-USER-03**: Add User modal opens, validates required fields (`الاسم*`, `البريد الإلكتروني*`, `كلمة المرور*`, `الدور*`), and submits successfully.
- **TC-USER-04**: Duplicate email registration is rejected with a clear Arabic validation error.
- **TC-USER-05**: User activation toggle updates `is_active` correctly.
- **TC-USER-06**: SuperAdmin can toggle `bypass_location_verification` on staff users.

### Suite 3: Roles and Permissions
- **TC-ROLE-01**: Roles list `/settings/roles` displays all active system roles with code, name, and active status.
- **TC-ROLE-02**: Role creation creates a custom role with custom name and attributes.
- **TC-ROLE-03**: Role duplication copies all attributes, tags, and permissions to a new role instance.
- **TC-ROLE-04**: Role edit `/settings/roles/edit/<id>` saves updated attributes (`is_sales_team`, `is_area_manager`, `is_rep`, etc.).
- **TC-ROLE-05**: Role edit saves functional tags (`customers:customers/bypassLocation`, `accounting:vaults/assignable`, etc.).
- **TC-ROLE-06**: Quick permission presets (`أدمن`, `افتراضي`, `قراءة فقط`) toggle appropriate permissions.

### Suite 4: Backend Authorization Enforcement
- **TC-SEC-01**: Unauthenticated requests to any `/settings/*` route redirect to `/login/`.
- **TC-SEC-02**: Restricted user without `settings:settings/view` receives HTTP 403 Forbidden or redirect on `/settings/*`.
- **TC-SEC-03**: Restricted user cannot POST to `/settings/users/add/` or `/settings/roles/create/`.
- **TC-SEC-04**: Navigation links in sidebar are hidden when the user lacks the corresponding module permissions.

### Suite 5: In-Scope Settings Pages CRUD
- **TC-SET-01 (Branding)**: Updating company profile (`/settings/branding`) updates name, tax ID, phone, address, and logo.
- **TC-SET-02 (Location)**: Updating location settings (`/settings/location`) updates tolerance meters and workflow verification dropdowns.
- **TC-SET-03 (Areas)**: Adding a new governorate and subarea in `/settings/areas` renders properly in the tree.
- **TC-SET-04 (Expenses)**: Adding, editing, and deleting an expense type in General and Visit tabs in `/settings/expenses`.
- **TC-SET-05 (Tickets)**: Adding and editing a task type in `/settings/tickets`.
- **TC-SET-06 (Approvals)**: Adding and editing an approval request category in `/settings/requests`.
- **TC-SET-07 (Agreements)**: Adding and editing an agreement type in `/settings/agreements`.
- **TC-SET-08 (Sales Settings)**: Updating sales workflow toggles, tax mode, and packaging unit in `/settings/sales`.
- **TC-SET-09 (Purchase Settings)**: Updating purchase workflow toggles, tax mode, and packaging unit in `/settings/purchase`.
- **TC-SET-10 (Inventory Settings)**: Updating batch and expiry toggles in `/settings/inventory`.
- **TC-SET-11 (Contacts UDF)**: Viewing and configuring contact card custom fields in `/settings/contacts-udf`.
- **TC-SET-12 (Data Sync)**: Viewing and updating Google Sheets URLs in `/settings/sync-data`.

---

## 3. Automated Test Execution Plan & Verified Results

Automated test cases in `accounts/tests.py` and `master_data/tests.py` run through Django test runner:
```bash
py manage.py test accounts master_data
```

### Verified Test Run Summary:
- **Scope**: Accounts (Users, Roles, RBAC permissions, safeguards) & Master Data (All 12 Settings pages, singletons, APIs, and CRUD operations).
- **Accounts & Master Data Tests**: 34/34 passed (`Ran 34 tests in 17.832s - OK`).
- **Complete ERP Suite Tests**: 106/106 passed (`Ran 106 tests in 55.957s - OK`).
- **Regressions**: 0 regressions detected.
- **Backend Authorization**: Verified 403 Forbidden / redirect on all `/settings/*` and mutation endpoints for unauthorized users.
- **SuperAdmin Protection**: Verified that the last active SuperAdmin cannot be deactivated or deleted.
- **Reference ERP Integrity**: Verified untouched (zero mutation requests made to weapharma.bricks-rep.com).

