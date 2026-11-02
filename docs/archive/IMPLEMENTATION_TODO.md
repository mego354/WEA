# ERP Implementation Todo & Roadmap

**Project:** WEA Pharma ERP  
**Tracking Date:** 2026-10-24  
**Overall Status:** 100% COMPLETED  
**Status Legend:**  
- `[ ] NOT STARTED`  
- `[/] IN PROGRESS`  
- `[X] COMPLETED`  
- `[!] BLOCKED`  

## Phase 17: Audit Log Labels, Persistent Areas UI, Obsolete Features Removal, Database Role Consolidation, App-Wide Data Scoping & Hierarchical Area Selector (2026-10-28)

- [X] **TASK-01: Fix `نوع العملية` in Audit Logs**:
  - Implemented bilingual mapping dictionary `ACTION_LABELS` on `SecurityAuditLog`.
  - Added methods `get_action_type_display(lang='ar')`, `get_label_for_action(code, lang='ar')`, and properties `action_type_display` and `action_type_display_en`.
  - Updated desktop table, mobile cards, active filter chips, and diff modal in `templates/accounts/audit_logs.html` and `accounts/views.py`.
  - Maintained colored dot indicator as a secondary visual cue, with safe fallbacks for legacy/unmapped action codes.
  - Tested and verified: `accounts.tests_audit_logging` (3 tests pass).

- [X] **TASK-02: Fix Three-Dot Action Menu in `settings/areas/`**:
  - Identified root cause: `overflow-hidden` on `.area-card` clipped dropdowns when subareas were collapsed (card height ~56px).
  - Removed `overflow-hidden`, applied rounded corner utilities, anchored dropdown to `start-0` with `z-50`, and elevated open card's z-index dynamically in `toggleAreaMenu`.
  - Isolated expand/collapse button and three-dot button events with `event.stopPropagation()`.
  - Tested and verified: `master_data.tests_egypt_areas` (3 tests pass).

- [X] **TASK-03: Completely Remove `home/settings/contacts-udf/`**:
  - Removed sidebar link from `templates/layouts/base.html`.
  - Removed URL route `settings/contacts-udf/` from `master_data/urls.py`.
  - Removed `contacts_udf_view` from `master_data/views.py`.
  - Deleted obsolete template `templates/settings/contacts_udf.html`.
  - Preserved underlying `ContactFieldSetting` model and contacts data integrity.
  - Tested and verified: `master_data.tests.test_contacts_udf_url_not_found` asserting HTTP 404 (18 tests pass).

- [X] **TASK-04: Consolidate User Types & Update Development Database**:
  - Verified development database `db.sqlite3` and created full snapshot backup `backups/db_backup_codex_task_20261028_033053.sqlite3`.
  - Migrated historical audit logs referencing obsolete roles by copying role names to `record_name` and setting `target_role=None`.
  - Deleted all 16 obsolete role rows from `accounts_role`. Exactly 5 canonical roles remain: `superadmin`, `manager`, `accountant`, `rep`, `medical_rep`.
  - 18 active users retained, 0 users deleted, all business history and credentials preserved.
  - Tested and verified: `accounts.tests_roles_consolidation` (5 tests pass).

- [X] **TASK-05: Remove `المكالمات` (Calls) from Contact Activities**:
  - Removed the Calls card from the Activities tab in `templates/contacts/contact_detail.html`.
  - Preserved visits, agreements, and timeline events; preserved `ContactActivity` data model.
  - Tested and verified: `contacts.tests_udf_todos_timeline` (6 tests pass).

- [X] **TASK-06: Remove `أمر مشتريات جديد` from Top-Left Navbar**:
  - Removed purchase order creation action from top navbar in `templates/layouts/base.html`.
  - Kept purchase order creation workflow intact on `/purchases/orders/` and `/purchases/orders/create/`.
  - Layout remains balanced and aligned in both RTL and LTR.
  - Tested and verified: `purchases.tests` (16 tests pass).

- [X] **TASK-07: Enforce App-Wide Data Access by Role & Organizational Scope**:
  - Reinforced backend ABAC/RBAC scoping in `accounts/permissions.py`:
    - `rep`: strictly own records (`created_by=user`, `owner=user`), no peer leakage in same area.
    - `medical_rep`: strictly own records plus shared assigned contacts/products.
    - `manager`: records of reps belonging to the same root main area across all secondary sub-areas; anti-self-approval rule; fail-secure behavior when unassigned.
    - `accountant`: broad visibility across financial and accounting scopes.
    - `superadmin`: global unrestricted visibility.
  - Enforced `get_scoped_queryset` across sales collections, accounting customers, customer transactions, and treasury vaults.
  - Tested and verified: `accounts.tests_data_scoping` (6 tests pass) & `activities.tests_approval_and_regional` (17 tests pass).

- [X] **TASK-08: Redesign Geographic Area Selector for New & Edited Users**:
  - Created reusable accessible component: `templates/components/geographic_area_selector.html`.
  - Grouped governorates and subareas with Arabic labels, search input, chips summary, live count badge, and select/clear all.
  - Integrated server-side validation (`validate_assigned_areas_for_user`) preventing managers from assigning areas outside their main area scope.
  - Tested and verified: `accounts.tests_geographic_areas_selector` (4 tests pass).

## Phase 16: Enterprise Role Consolidation, Centralized Audit Logging, Egypt Areas, Contact UDF, Todos & Timeline (2026-10-28)

- [X] **TASK-01: User Role Consolidation to 5 Canonical Roles**:
  - Defined canonical role keys (`superadmin`, `manager`, `accountant`, `rep`, `medical_rep`) in `accounts/models.py`.
  - Migrated all 18 existing users into canonical roles preserving all transactions, credentials, and business links.
  - Deactivated 21 obsolete/duplicate roles (`is_active=False`) without breaking referential integrity.
  - Enforced `Role.get_supported_roles()` in user forms, admin, and views.
  - Unit tests verified: `accounts/tests_roles_consolidation.py` (5 tests passing).

- [X] **TASK-02: Comprehensive Append-Only Audit Logging & Diff Inspection**:
  - Implemented centralized `AuditLogService` with recursive sensitive data redaction to `[REDACTED]`.
  - Added `module`, `record_id`, `record_name`, `previous_values`, `new_values`, `status`, `reason` to `SecurityAuditLog`.
  - Created `/settings/audit-logs/` with server-side pagination, module/action/user/date/search filters, and side-by-side previous vs new values diff modal.
  - Instrumented auth, accounts, contacts, UDF, areas, and settings actions.
  - Unit tests verified: `accounts/tests_audit_logging.py` (3 tests passing).

- [X] **TASK-03: Visit Suggested Products Relocation to Visit Templates**:
  - Moved "المنتجات المقترحة للزيارات الميدانية" out of `settings/location/` into Visit Templates (`templates/activities/visit_template_form.html`).
  - Restricted suggested products strictly to active sellable catalog items (`sellable=True, is_active=True`).
  - Removed Card 4 from `templates/settings/location_settings.html` and cleaned up `master_data/views.py`.
  - Unit tests verified: `activities/tests_suggested_products.py` (3 tests passing).

- [X] **TASK-04: Egypt 27 Governorates & Company Internal Areas Isolation**:
  - Added `is_company_area` and `name_en` to `Area` model (`master_data/models.py`).
  - Flagged 14 company facilities/warehouses with `is_company_area=True` preserving all database relations.
  - Implemented management command `setup_egypt_areas.py` standardizing Egypt's official 27 governorates.
  - Updated `areas_settings_view` to annotate `subareas_count=Count('subareas')` and filter company facilities.
  - Unit tests verified: `master_data/tests_egypt_areas.py` (3 tests passing).

- [X] **TASK-05: Contact Custom Fields (UDF) Multi-Type Architecture**:
  - Enhanced `ContactFieldSetting` (`master_data/models.py`) with support for all 7 types (`text`, `textarea`, `number`, `date`, `boolean`, `single_choice`, `multi_choice`).
  - Added `Contact.custom_values` (`JSONField`) in `contacts/models.py`.
  - Implemented full CRUD management in `contacts_udf_view` (`templates/settings/contacts_udf.html`).
  - Integrated custom fields into contact creation, editing, and Overview accordion card in `contact_detail.html`.
  - Unit tests verified: `contacts/tests_udf_todos_timeline.py` (custom fields tests).

- [X] **TASK-06: Contact TODOs Blank Page Fix & Asynchronous (AJAX) UX**:
  - Resolved blank page on `contacts/<id>/overview/?tab=todos` caused by tab case-sensitivity and unhandled redirects.
  - Implemented tab normalization: `raw_tab.lower().strip()`, defaulting invalid tabs safely to `'overview'`.
  - Added dedicated endpoints: `contact_create_todo`, `contact_toggle_todo`, `contact_delete_todo` supporting both AJAX JSON and fallback redirects.
  - Asynchronous checkbox toggling, task creation, and instant deletion without page reloads.
  - Unit tests verified: `contacts/tests_udf_todos_timeline.py` (TODO tests).

- [X] **TASK-07: Contact Timeline Top-5 Display & Paginated Modal Dialog**:
  - Overview tab displays the top 5 most recent activities (`recent_timeline = activities[:5]`) with activity-type badges and timestamps.
  - "عرض الكل" button opens `#timelineModal` with debounced search, activity-type filtering, and date range filters.
  - Implemented server-side paginated JSON endpoint: `contact_timeline_events` (`/contacts/<pk>/timeline/events/`).
  - Unit tests verified: `contacts/tests_udf_todos_timeline.py` (timeline tests).

- [X] **TASK-08: Complete Automated Test Suite & Health Check**:
  - 19 out of 19 tests passing across all 5 test modules with 0 errors and 0 failures.
  - Django system check: `python manage.py check` reports 0 issues.

---

## Phase 15: Visit Lifecycle Standardization, Template Simplification, Role Restrictions & Subsystem Audit (2026-10-27)

- [X] **TASK-01**: **Unified Visit Lifecycle State Machine**:
  - Implemented single workflow for all visits: Creation (`planned`) $\to$ Manager Approval (`approved`) $\to$ Rep Start / Check-in (`started`) $\to$ Detailing / Questionnaire Drafts $\to$ Rep End / Check-out (`finished`).
  - Added domain services in `activities/services.py`: `can_start_visit()`, `start_visit()`, `can_submit_answers()`, `save_visit_answers()`, `can_end_visit()`, `end_visit()`.
  - Atomic database transactions with `select_for_update()` to prevent concurrency conflicts.
  - Duration calculated strictly server-side: `(ended_at - started_at).total_seconds()`.

- [X] **TASK-02**: **Removal of Obsolete Visit Template Settings**:
  - Safely removed 4 obsolete configurable settings: `mode`, `visit_outcome_mode`, `auto_approve_unplanned`, and `auto_end_visit`.
  - Cleaned up models, admin definitions, forms, views, API serializers, and template fragments.
  - Generated and executed clean migration: `activities/migrations/0012_remove_obsolete_visittemplate_settings.py`.
  - Verified historical records intact (19 visits, 6 templates, audit logs, GPS coordinates, photos).

- [X] **TASK-03**: **Redesign & Hardening of Restricted Roles**:
  - Redesigned Accordion 3 in `templates/activities/visit_template_form.html` with real-time search, "Select All", "Deselect All", counter badges, and removable pill tags.
  - Clarified default-open semantics (empty = all roles permitted; non-empty = assigned active roles only).
  - Enforced role restrictions server-side across `VisitTemplate.is_user_eligible()`, `/api/visit-templates/`, `visit_create`, `start_visit`, `save_visit_answers`, and `end_visit`.
  - Touch-accessible targets ($\ge 44\text{px}$) optimized for mobile viewports (375px, 390px, 430px).

- [X] **TASK-04**: **Code Quality Audit & Dead Code Removal**:
  - Removed 144 lines of unreachable dead code in `activities/approvals_views.py`.
  - Cleaned up unused imports, dead feature flags, and redundant template snippets.
  - Preserved dual-control anti-self-approval rule and regional manager scoping.

- [X] **TASK-05**: **Automated Test Suite & Verification**:
  - 100% of tests passing across the entire activities test suite (89/89 tests passed in 91s).
  - Django system checks verified (`python manage.py check`: 0 silenced issues).
  - Clean migrations confirmed (`python manage.py showmigrations activities`).

---

## Phase 14: Final Codex Implementation — Unified Visit Lifecycle, Product Eligibility, Mobile UX & Repository Cleanup (2026-10-26)

- [X] **TASK-01**: **Unified Visit Lifecycle (Create First, Answer Later)**:
  - Ensured visit creation (`/visits/create/` or executing a planned item from `/planned-visits/`) does not require answering template questionnaire up-front.
  - Representatives start visits, answer template questions, and detail products at their convenience.
  - Completing visits preserves existing manager approvals and questionnaire answers.
  - Only approved visits can be dispatched to the field Agenda.

- [X] **TASK-02**: **Product Eligibility Enforcement (Sellable Only)**:
  - Products not intended for sale (`sellable=False` or `is_active=False`) are strictly filtered via `Product.get_eligible_for_visits()`.
  - Discarded on backend during `visit_create`, `visit_edit`, and `visit_detail`.
  - Historical product detailing records on existing visits are preserved even if products later become non-sellable.

- [X] **TASK-03**: **Configurable Product Suggestions in Settings & UI**:
  - Global configuration added to `LocationSettings` (`master_data/models.py`) with `enable_product_suggestions` and `suggested_products` (restricted to sellable).
  - Configurable card added to `templates/settings/location_settings.html`.
  - Template-specific suggestions added to `VisitTemplate` (`activities/models.py`).
  - Suggested products highlighted on `templates/activities/visit_detail.html` with amber accents and `★ مقترح` badge.

- [X] **TASK-04**: **Mobile-First UX Audit (17 Screens Tested across 320px–1920px)**:
  - Verified zero horizontal overflow on ultra-small (320px), standard (360px, 375px, 390px, 430px), tablet (768px, 1024px), and desktop.
  - Touch targets adhere to $\ge 44\text{px} \times 44\text{px}$.
  - Full viewport audit automated in `test_responsive_viewports.py`.

- [X] **TASK-05**: **Automated Test Suite & Repository Cleanup**:
  - Comprehensive user workflows suite `activities.tests_user_workflows` updated with 11 tests covering all user kinds, single/double visits, planned/unplanned, product eligibility, and suggestions.
  - Total test suite: 194 tests across all apps passing with 100% success (0 failures, 0 errors).
  - Added clean `.gitignore`, removed temporary debug scripts, reconciled repository git status.

---

## Phase 13: Regional Tab Excision & In-View Approvals on Agenda and Visits Routes (2026-10-25)

- [X] **TASK-01**: **Complete Regional Route & View Excision**:
  - Removed `regional/` tab and dashboard link from sidebar navigation (`templates/layouts/base.html`).
  - Removed `regional/` routes from `activities/urls.py` and `config/urls.py`.
  - Deleted `activities/regional_views.py` and `templates/regional/regional_dashboard.html`.
  - Replaced regional dashboard links in `templates/approvals/approvals_hub.html` with canonical link to `agenda`.
  - Verified no dangling imports or broken references across the entire codebase.

- [X] **TASK-02**: **Support Next URL Preservation in `visit_action`**:
  - Updated `activities/views.py:visit_action` to extract `next_url = request.POST.get('next') or request.GET.get('next')`.
  - Standardized redirect helper `get_redirect()` ensuring users remain on their source page (`/agenda/` or `/visits/`) after approving or declining.

- [X] **TASK-03**: **Agenda In-View Visit Approvals (`/agenda/`)**:
  - Annotated each visit in `agenda_visits` with `can_approve` based on manager role, anti-self-approval rule, and regional territorial scoping.
  - Added green Approve button and red Decline button to visit card footer in `templates/activities/agenda.html` when `can_approve` is true and visit is finished.
  - Implemented `agenda-reject-modal` with mandatory rejection reason and form targeting `/activities/visits/<id>/action/disapprove/`.

- [X] **TASK-04**: **Visits List In-View Visit Approvals (`/visits/`)**:
  - Updated `activities/views.py:visits_list` to annotate `user_can_approve` on each visit in the paginated queryset.
  - Added quick Approve and Decline action buttons to Table view (Actions column) and Card view (card footer) in `templates/activities/visits_list.html`.
  - Implemented `visit-list-reject-modal` with mandatory rejection notes and next redirect.

- [X] **TASK-05**: **Security & Integrity Enforcement**:
  - Dual-control anti-self-approval rule strictly enforced: managers cannot approve or reject their own visits.
  - Cross-regional isolation strictly enforced: managers cannot approve or reject visits of representatives outside their assigned territory.
  - Rejection requires an explicit Arabic rationale.

- [X] **TASK-06**: **Automated Testing & QA Verification**:
  - Added automated test cases in `activities/tests_agenda.py`:
    - `test_manager_can_approve_subordinate_visit_from_agenda`
    - `test_manager_can_decline_subordinate_visit_from_agenda`
    - `test_manager_can_approve_and_decline_from_visits_list`
    - `test_anti_self_approval_and_cross_region_security`
  - Ran test suite with 24 tests passing (100% pass).

---

## Phase 12: Approval Workflow Rectification, In-View Item Approvals Integration, and Agenda Tab Implementation (2026-10-25)

- [X] **TASK-01**: **Audit & Reference ERP Inspection**:
  - Inspected authorized reference application at `https://weapharma.bricks-rep.com/home` in read-only mode using browser subagent.
  - Inspected `/agenda` layout, date picker, `Todos` and `الزيارات` tabs, out-of-plan modal, and visit cards.
  - Verified item approval behavior on Visits, Sales Orders, and Purchase Orders.
- [X] **TASK-02**: **Removal of Standalone Approvals Tab**:
  - Removed "الموافقات والاعتمادات" navigation link from sidebar (`templates/layouts/base.html`).
  - Replaced approvals hub links in `templates/regional/regional_dashboard.html` with direct list links and status filters.
  - Implemented canonical HTTP 302 redirect in `activities/approvals_views.py:approvals_hub` to prevent broken bookmarks.
- [X] **TASK-03**: **Purchase Order Approval Infrastructure**:
  - Added `approved_by`, `approved_at`, and `rejection_reason` to `PurchaseOrder` model in `purchases/models.py`.
  - Applied migrations `purchases.0004_purchaseorder_approved_at_...` and `activities.0009_approvalauditlog_purchase_order_...`.
  - Implemented `approve_order`, `reject_order` (mandatory reason), `resubmit_order` in `purchases/services.py:PurchaseOrderService`.
  - Added downstream inventory receipt lock: `PurchaseOrderService.stock_order` strictly enforces `status == 'approved'`.
- [X] **TASK-04**: **In-View Detail Approval Integration**:
  - Integrated approval actions, rejection modal, resubmission button, and audit trail into `templates/purchases/purchase_order_detail.html`.
  - Integrated approval actions and rejection modal into `templates/activities/visit_detail.html`.
  - Verified approval actions on `templates/sales/sales_order_detail.html`.
- [X] **TASK-05**: **List View Status Visibility and Mobile Cards**:
  - Added status badge pills and mobile card layout to `templates/purchases/purchase_orders_list.html`.
  - Added `rejected` status filter and mobile card layout to `templates/sales/sales_orders_list.html`.
  - Added approval status indicators and URL filter `?approval_status=` to `templates/activities/visits_list.html`.
- [X] **TASK-06**: **Database State Reconciliation**:
  - Safely reconciled inconsistent development database records (Visit #3 and PO #43) without deleting historical data.
- [X] **TASK-07**: **Dual-Control Anti-Self-Approval Enforcement**:
  - Barred creators from approving their own visits, sales orders, or purchase orders unless sovereign superadmin.
- [X] **TASK-08**: **Verification Gate Sign-Off**:
  - Authored formal verification report in `docs/APPROVAL_WORKFLOW_VERIFICATION.md` after passing all approval test suites.
- [X] **TASK-09**: **Agenda Tab Implementation (`جدول الاعمال`)**:
  - Created `activities.views.agenda_view` mapped to `/agenda/` and `/activities/agenda/`.
  - Positioned `جدول الاعمال` in sidebar navigation directly under `الرئيسية`.
  - Implemented dual tabs: `الزيارات` and `Todos` (`AgendaTodo` model).
  - Implemented previous/next date chevron navigation and date input picker.
  - Implemented out-of-plan registration modal (`زيارة خارج الخطة`).
  - Implemented empty state illustration matching reference ERP (`لا خطط أخرى لهذا اليوم`).
  - Enforced territorial scoping: Reps restricted to own agenda (403 on cross-rep query); Managers scoped to region/subregions; SuperAdmin universal access.
- [X] **TASK-10**: **Automated Test Suites & QA**:
  - Authored `activities/tests_approval_and_regional.py` (12 tests, 100% pass).
  - Authored `activities/tests_agenda.py` (8 tests, 100% pass).
  - Full module regression suite: 79 tests in `activities`, `purchases`, and `sales` passed with zero errors.

---

## Phase 11: Role-Based Visit Templates, Regional Manager Approvals, and Secure Mobile Workflows (2026-10-24)

- [X] **TASK-01**: **Role-Based Visit Template Compatibility Engine**:
  - Implemented normalized canonical account type mapping and bidirectional aliases (`ACCOUNT_TYPE_ALIASES`) in `VisitTemplate`.
  - Implemented `is_contact_eligible(contact)` and `is_user_eligible(user)` methods.
  - Enforced server-side compatibility checks in `VisitForm.clean()`, `visit_create`, `visit_edit`, `planned_visit_add_item`, and dynamic API `/activities/api/templates/`.
  - Frontend auto-filtering in `visit_form.html` (`filterTemplatesByCustomer`) immediately purges incompatible templates upon contact selection.
  - Documented in `docs/VISIT_TEMPLATE_COMPATIBILITY.md`.
- [X] **TASK-02**: **Regional Hierarchy & Scoping Architecture**:
  - Established territorial boundary rules for `governorate` and `subarea` entities.
  - Implemented `get_user_managed_areas`, `get_user_managed_representatives`, `get_scoped_queryset`, and `can_user_access_object` in `accounts/permissions.py`.
  - Strict horizontal data isolation: foreign region visits, orders, and financials are invisible and inaccessible across regional managers.
  - Super Administrator retains universal oversight across all territories.
  - Documented in `docs/REGIONAL_ACCESS_CONTROL.md`.
- [X] **TASK-03**: **Visit Approval & Resubmission Lifecycle**:
  - Visits transition to `manager_approval = 'pending'` upon representative completion.
  - Regional managers approve or reject via `/visits/<id>/action/`.
  - Rejection enforces mandatory non-empty Arabic rationale.
  - Representatives receive high-contrast alert banner with rejection reason and one-tap resubmission workflow (`manager_approval = 'pending'`).
  - Documented in `docs/APPROVAL_WORKFLOWS.md`.
- [X] **TASK-04**: **Sales Order Approval & Downstream Enforcement**:
  - Sales orders enter `status = 'pending_approval'`.
  - Implemented `approve_order`, `reject_order` (mandatory reason), and `resubmit_order` in `SalesOrderService`.
  - Downstream enforcement: `prepare_order`, `deliver_order`, and `invoice_order` strictly verify `status == 'approved'`, raising `ValidationError` if unapproved.
- [X] **TASK-05**: **Centralized Approvals Hub & Regional Command Center**:
  - Unified Approvals Hub (`/approvals/`) supporting Visits, Sales Orders, and Audit History tabs.
  - Scoped multi-parameter filtering (representative, area, status, date, search) and server-side pagination.
  - Regional Manager Dashboard (`/regional/`) with territory selector, 4-stat KPI grid, and managed representative performance matrix.
- [X] **TASK-06**: **Security Hardening & Anti-Tampering**:
  - Prevented self-approval: managers cannot approve their own visits or sales orders.
  - Complete immutable audit logging via `ApprovalAuditLog` tracking all lifecycle transitions.
  - Documented in `docs/SECURITY_REVIEW.md`.
- [X] **TASK-07**: **Mobile-App UI & Responsive Design**:
  - Dual-view rendering: dense desktop tables vs. touch-friendly card layouts on mobile ($\le 768$px).
  - Validated across 320px, 375px, 390px, 430px, 768px, 1024px, and 1440px viewports with touch targets $\ge 44$px and Arabic RTL support.
  - Documented in `docs/UI_TEST_REPORT.md`.
- [X] **TASK-08**: **Automated Tests & Quality Assurance**:
  - Authored comprehensive test suite `activities/tests_approval_and_regional.py` (10 tests, 100% pass).
  - All 59 activities tests and 2 sales tests passed cleanly with zero regressions.

---

## Phase 10: Complete Permission Management, Settings Integration, Security Hardening, and Mobile UI (2026-10-24)

- [X] **TASK-01**: **Application Audit & Route Inventory**:
  - Audited all 100+ application routes across `purchases`, `sales`, `catalog`, `contacts`, `activities`, `inventory`, `treasury`, `master_data`, and `accounts`.
  - Cataloged 104 standardized granular permissions in `accounts/permission_registry.py`.
  - Authored comprehensive route and gap analysis in `docs/PERMISSION_AUDIT.md`.
- [X] **TASK-02**: **Centralized Permission Architecture**:
  - Implemented declarative RBAC + ABAC architecture with hierarchical module inheritance rules.
  - Revoking `module:<name>` automatically revokes all child subpage and action permissions in `User.has_permission()`.
  - Documented complete architecture in `docs/PERMISSION_ARCHITECTURE.md`.
- [X] **TASK-03**: **Super Administrator Settings Console**:
  - Created role management list (`/auth/roles/`) matching reference ERP.
  - Implemented dynamic hierarchical permission matrix form (`/auth/roles/create/`, `/auth/roles/<id>/edit/`) with live search, collapsible module accordions, presets, and sticky save bar.
  - Implemented user effective permissions inspector (`/auth/users/<id>/effective-permissions/`) for debugging inherited vs granted access.
  - Authored operational guide in `docs/SETTINGS_PERMISSION_GUIDE.md`.
- [X] **TASK-04**: **Backend Security & Privilege Escalation Hardening**:
  - Isolated sovereign administrative privileges to `is_super_admin` (`is_superuser` or active role with `is_super=True`).
  - Protected against privilege escalation via parameter tampering in user and role endpoints.
  - Implemented immutable lockout protection preventing deletion/deactivation of the last active superadmin.
  - Implemented `SecurityAuditLog` tracking all role, permission, user status, and password changes.
  - Implemented immediate in-memory cache invalidation via `clear_perm_cache()`.
  - Authored full security assessment in `docs/SECURITY_AUDIT.md`.
- [X] **TASK-05**: **Application-Wide Route Enforcement**:
  - Hardened all routes across `purchases`, `sales`, `catalog`, `contacts`, `activities`, `inventory`, `treasury`, and `master_data` with `@require_permission()` or `@require_super_admin()`.
  - Documented route mapping in `docs/ROUTE_PERMISSION_MATRIX.md`.
- [X] **TASK-06**: **Mobile-First Responsive Parity**:
  - Audited viewports across 320px, 375px, 390px, 430px, 768px, 1024px, and 1440px.
  - Built dual-view rendering for audit logs (desktop table vs. mobile cards).
  - Built mobile-optimized accordions, touch checkboxes (min 44px), and sticky action bars for permission management.
  - Updated mobile audit in `docs/MOBILE_RESPONSIVENESS_AUDIT.md`.
- [X] **TASK-07**: **Automated Tests & Quality Assurance**:
  - Built comprehensive `ERPAuthorizationSecurityTests` with 9 test cases in `accounts/tests.py`.
  - Verified 154/154 automated tests passing across the entire Django test suite (`python manage.py test`).
  - Authored execution report in `docs/PERMISSION_TEST_REPORT.md`.

---

## Phase 9: Unify Visit Creation, Remove Duplicate Questions, and Standardize Client Display (2026-10-22)

- [X] **TASK-01**: **Remove Duplicate Outcome Question (`هل كان يوم ناجح ؟ *`)**:
  - Safely deactivated question in DB via migration `activities/migrations/0007_deactivate_duplicate_outcome_question.py` (`is_active=False`).
  - Implemented `VisitTemplate.get_active_questions()` filtering active questions and excluding redundant outcome items.
  - Removed question from seeds (`seed_activities.py`, `scratch/seed_visit_templates.py`).
  - Preserved historical answers and audit records.
- [X] **TASK-02**: **Completely Remove `توزيع عينة طبية (اختياري)` from Active Workflow**:
  - Removed sample inputs (`sample_product`, `sample_quantity`) from `templates/activities/visit_form.html`.
  - Removed backend creation processing from `visit_create` in `activities/views.py`.
  - Safeguarded historical audit records: `VisitSampleItem` retained; sample distribution audit table in `visit_detail.html` displayed conditionally `{% if visit.samples.exists %}`.
- [X] **TASK-03**: **Unified Visit Creation Route (`/visits/create/`)**:
  - Canonical route: `/visits/create/` (URL name `visit_create`).
  - Planned visits entry point: `planned_visit_item_execute` validates rep authorization and redirects to `/visits/create/?contact_id=...&planned_item_id=...`.
  - Unplanned visits entry point: Floating `+` action navigates directly to `/visits/create/`.
  - Shared controller, form validation, representative locking, eligibility checks, and duplicate submission interception.
- [X] **TASK-04**: **Preserve and Display Planned/Unplanned Classification**:
  - Persisted indexed boolean `Visit.is_planned`.
  - Prominent Arabic badges: `زيارة مخططة` (blue) vs `زيارة خارج الخطة` (purple) displayed across creation forms, lists, cards, detail pages, and answering screens.
  - Added source schedule indicator to visit detail view when linked to a `PlannedVisitItem`.
- [X] **TASK-05**: **Standardize Client Display (Names Without Codes)**:
  - `Contact.__str__` and `Contact.display_tag` return `self.name` without brackets or codes.
  - `CustomerModelChoiceField.label_from_instance` returns `obj.name`.
  - Search API returns clean `display_tag`; internal search by code preserved.
  - Cleaned all templates: `visits_list.html`, `planned_visits_list.html`, `visit_form.html`, `visit_detail.html`, and `customer_selection_modal.html`.
- [X] **TASK-06**: **Automated Tests & Quality Assurance**:
  - Added test cases covering question removal, active sample deprecation, unified creation route, authorization enforcement, and clean client display.
  - Full suite of 49/49 tests passing: `py manage.py test activities`.
  - Browser UI verified across Desktop (1440px), Tablet (768px), Mobile Large (430px, 390px, 375px), and Mobile Mini (320px).
- [X] **TASK-07**: **Complete Documentation**:
  - Authored `docs/VISIT_CREATION_WORKFLOW.md`.
  - Authored `docs/VISIT_QUESTION_CONFIGURATION.md`.
  - Updated `docs/VISIT_CLASSIFICATION.md`.
  - Updated `docs/IMPLEMENTATION_TODO.md`.

---

## Phase 8: Visit Templates, Workflows, Permissions, and Location Verification (2026-10-22)

- [X] **TASK-01**: **Fix Visit Template Account-Type Restrictions**:
  - Normalized `ACCOUNT_TYPE_CHOICES` to canonical Title-Case format matching `Contact.account_type`.
  - Added case-insensitive aliases in choices to support legacy inputs and APIs.
  - Implemented `is_account_type_eligible()` and `is_contact_eligible()` on `VisitTemplate`.
  - Fixed edit restoration: checkboxes now properly restore checked state when editing templates in `/settings/visits/templates/<pk>/edit/`.
  - Enforced eligibility validation on backend in `VisitForm.clean()` and `visit_create`.
  - Applied dynamic filtering in `/api/templates/` and client-side JavaScript.
- [X] **TASK-02**: **Audit & Enforce Visit Settings and Permissions**:
  - Implemented RBAC separating ordinary representative capabilities from administrative settings.
  - Representatives cannot create, edit, toggle, or delete visit templates (HTTP 403 / redirect).
  - Managers retain visit approval/disapproval permissions.
  - Created comprehensive documentation and permission matrix in `docs/VISIT_SETTINGS_AND_PERMISSIONS.md`.
- [X] **TASK-03**: **Standardize Visit Lifecycle (Create First, Answer Later)**:
  - Decoupled visit creation from questionnaire answering.
  - `visit_create` persists visit with `status='started'` and minimal required data (customer, template, locked rep, check-in GPS).
  - Redirects to `/visits/<pk>/` where reps answer questionnaire items, record detailing, and take photo evidence.
  - Implemented `action='save_draft'` (keeps status 'started') and `action='complete'` (transitions to 'finished').
  - Required questions and photo evidence validated upon completion; answers preserved on validation error.
  - Anti-duplicate protection prevents rapid double submissions.
- [X] **TASK-04**: **Explicit Planned vs Unplanned Classification**:
  - Utilized persistent boolean `Visit.is_planned` (indexed).
  - Explicit assignment via `planned_item_id` (planned) vs ad-hoc routes (unplanned).
  - Added Arabic badges: `زيارة مخططة` (blue) and `زيارة خارج الخطة` (purple).
  - Added filter pills and slide-over drawer filter `plan_type=planned` / `plan_type=unplanned`.
- [X] **TASK-05**: **Lock Representative Assignment to Authenticated User**:
  - Standard representatives are automatically locked to `request.user` (`disabled=True` + forced in `clean()`).
  - Client-side tampering with `owner` parameter is rejected/overridden by the server.
  - Superusers/managers retain selector to assign other representatives.
- [X] **TASK-06**: **Location Photo Capture & Audited Superuser Bypass**:
  - Added `location_photo`, `photo_captured_at`, `bypassed_by`, `bypassed_at`, `bypass_reason` to `Visit`.
  - Mobile-friendly camera file input (`accept="image/*" capture="environment"`) with live preview and retake.
  - Backend validation in `activities.services.validate_and_save_photo_evidence` (10MB limit, image integrity check, UUID filename).
  - Protected endpoint `/visits/<pk>/evidence/photo/` streams file to authorized users, returns 403 to unauthorized reps.
  - Authorized superuser bypass path records audit log (`bypassed_by`, `bypassed_at`, `bypass_reason`).
- [X] **TASK-07**: **Restrict المنتجات المشروحة to 3 Template Types**:
  - Implemented `VisitTemplate.is_product_detailing_supported()` restricting detailing strictly to:
    1. Single visit — doctor / DR visit
    2. Single visit — pharmacy visit
    3. Healthy day
  - Detailing section hidden in frontend and cleared in backend for all other template types.
- [X] **TASK-08**: **Automated Tests & Quality Assurance**:
  - Added `VisitWorkflowsAndPermissionsComprehensiveTestCase` covering all requirements.
  - All 45/45 activities tests passing (`py manage.py test activities`).
  - Verified in browser automation across viewports: 320px, 375px, 390px, 430px, 768px, 1440px.
- [X] **TASK-09**: **Complete Documentation**:
  - Generated all 8 required markdown documents in `docs/`.

---

## Phase 7: Data Replacement, Full App Flow Testing & Reference Home Page Parity (2026-10-20)

- [X] **FIX-01**: Fix "تسجيل زيارة خارج الخطة" (Unplanned Visit) button JS syntax error in `templates/components/customer_selection_modal.html` and Arabic decimal comma localization in `templates/activities/visit_form.html`.
- [X] **FIX-02**: Fix Dual Floating Action Button (FAB) collision on all screen sizes (320px, 375px, 390px, 430px, 1280px) with `deltaY = 72px` vertical stacking.
- [X] **DATA-06**: Verified SQLite backup creation (`backups/db_backup_import_20261020_064920.sqlite3`).
- [X] **DATA-07**: Complete import of all 5 business data files from `data_folder/` (Contacts: 8,876, Orders: 7,088, Collections: 6,676, Agreements: 209, Returns: 270, Canonical Products).
- [X] **DATA-08**: Customer accounts balance computation (`CustomerAccount` balance & overdue debt populated from actual transaction history).
- [X] **FLOW-08**: Execute full application flow verification across all modules: 42/42 routes returned HTTP 200 OK (`scratch/test_whole_app_flow.py`).
- [X] **FLOW-09**: Execute Playwright end-to-end UI smoke tests: 25/25 user workflows passed (`scratch/run_full_ui_smoke_test.py`).
- [X] **HOME-01**: Inspect reference ERP home page DOM, layout, KPIs, and charts (`https://weapharma.bricks-rep.com/home`).
- [X] **HOME-02**: Implement Date Range Selector with quick period filters and active month default in `master_data/views.py` and `templates/dashboard/home.html`.
- [X] **HOME-03**: Implement all 14 reference KPI cards with exact Arabic titles, order, units (`k جنيه`), and formatting.
- [X] **HOME-04**: Implement all 6 reference sunburst hierarchy charts (`type: 'sunburst'`) using local Apache ECharts bundle (`static/libs/echarts.min.js`).
- [X] **HOME-05**: Responsive layout testing and screenshot verification on Mobile (375px), Tablet (768px), Laptop (1280px), Desktop (1600px).
- [X] **TEST-03**: Run full Django test suite (`python manage.py test`): 131/131 tests passed with zero regressions.

---

## Phase 6: Visit Templates & Lifecycle Integration (قوالب الزيارات)

- [X] **DATA-01**: Extend `VisitTemplate` model with full settings and constraints matching Reference ERP.
- [X] **DATA-02**: Create `VisitTemplateQuestion` model with field types, options, required, conditional logic, and lifecycle stages.
- [X] **DATA-03**: Update `Visit` model with `detailed_products` ManyToMany and visit outcome tracking.
- [X] **DATA-04**: Generate and execute database migrations.
- [X] **DATA-05**: Seed all 6 standard reference visit templates and their exact questions.
- [X] **CRUD-01**: Implement `/settings/visits/templates` listing view and template matching reference screenshot (`media_1792386023336.png`).
- [X] **CRUD-02**: Implement template creation view and template (`/settings/visits/templates/create`).
- [X] **CRUD-03**: Implement template edit view and template (`/settings/visits/templates/<id>/edit`).
- [X] **CRUD-04**: Implement template preview view (`/settings/visits/templates/<id>/preview`).
- [X] **CRUD-05**: Implement question builder API/endpoints (add question, edit, delete, reorder).
- [X] **CRUD-06**: Implement template deletion safeguard (prevent deleting active templates with visits).
- [X] **NAV-01**: Add `قوالب الزيارات` link to Settings submenu in `templates/layouts/base.html`.
- [X] **FLOW-01**: Integrate template selection in Planned Visits (`PlannedVisitItem`).
- [X] **FLOW-02**: Integrate template selection and account type filtering in Unplanned Visits (`visit_create`).
- [X] **FLOW-03**: Implement dynamic questionnaire form rendering (single choice, text, textarea, conditional triggers).
- [X] **FLOW-04**: Implement Product Detailing (`المنتجات المشروحة`) selection and persistence.
- [X] **FLOW-05**: Implement Representative Lifecycle: Check-in (start_only stage), In-progress, and Completion/Check-out.
- [X] **FLOW-06**: Render questionnaire answers and detailed products in Visit Detail (`visit_detail`).
- [X] **FLOW-07**: Support editing visit answers while preserving historical integrity (`visit_edit`).
- [X] **TEST-01**: Write comprehensive automated tests in `activities/tests.py`.
- [X] **TEST-02**: Verify 100% test pass with zero regressions.


---

## Phase 1: Reusable Excel Core Utilities

- [X] `master_data/excel_utils.py` implementation:
  - [X] `export_to_excel_response()`:
    - [X] Openpyxl workbook generation with correct MIME type `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`.
    - [X] Styled header row: `#27BEBE` brand teal, white bold Cairo/Calibri text, height 26pt.
    - [X] Automatic column width calculation with safety padding.
    - [X] Right-to-Left (RTL) worksheet view enabled (`ws.sheet_view.rightToLeft = True`).
    - [X] Excel formula injection sanitization: prefix leading `=`, `+`, `-`, `@` with single quote.
    - [X] Correct data formatting (numbers as numbers, dates as dates, currency as `#,##0.00`).
  - [X] `generate_excel_template_response()`:
    - [X] Styled downloadable sample templates with column descriptions and example rows.
  - [X] `export_error_report_response()`:
    - [X] Downloadable Excel error reports for import rejections with row and error specifications.
  - [X] `ExcelImportParser` / Helpers:
    - [X] File validation (file size < 10MB, extension `.xlsx`, zip header magic bytes).
    - [X] Flexible column header mapping (Arabic & English column aliases).
    - [X] Data extraction and type parsing (`parse_decimal_safe`, `parse_boolean_safe`).
    - [X] Preview generation (total rows, valid rows, invalid rows, duplicates, planned actions).
    - [X] Multi-behavior execution (`create_only`, `update_only`, `create_and_update`).
    - [X] Atomic database transaction execution with rollback on critical failure.

---

## Phase 2: Convert All CSV Data Exports to Genuine Excel (.xlsx)

- [X] **Catalog Products Export**:
  - [X] Replaced CSV logic in `catalog/views.py::products_export` with `export_to_excel_response`.
  - [X] Preserves active filters (search query, category, sellable status, price ranges).
  - [X] Updated UI button in `templates/catalog/products_list.html` to "تصدير إلى Excel" (.xlsx).
  - [X] Updated tests in `catalog/tests.py`.
- [X] **Contacts (Customers & Suppliers) Export**:
  - [X] Replaced CSV logic in `contacts/views.py::contacts_export` with `export_to_excel_response`.
  - [X] Preserves active filters (relation: vendor/customer/all, search query, area, status).
  - [X] Updated UI button in `templates/contacts/contacts_list.html` to "تصدير إلى Excel" (.xlsx).
  - [X] Updated tests in `contacts/tests.py`.
- [X] **Purchases Orders Export**:
  - [X] Replaced CSV logic in `purchases/views.py::purchase_orders_export` with `export_to_excel_response`.
  - [X] Preserves active filters (status, supplier, search query).
  - [X] Updated UI button in `templates/purchases/purchase_orders_list.html` to "تصدير إلى Excel" (.xlsx).
  - [X] Updated tests in `purchases/tests.py`.
- [X] **Purchases Return Orders Export**:
  - [X] Replaced CSV logic in `purchases/views.py::purchase_return_orders_export` with `export_to_excel_response`.
  - [X] Preserves active filters (status, supplier, search query).
  - [X] Updated UI button in `templates/purchases/purchase_return_orders.html` to "تصدير إلى Excel" (.xlsx).
  - [X] Updated tests in `purchases/tests.py`.
- [X] **New Active Modules Excel Exports**:
  - [X] Sales Orders Export: `sales/views.py::sales_orders_export` + URL `/sales/export/` + button in `templates/sales/sales_orders_list.html`.
  - [X] Collections Export: `sales/views.py::collections_export` + URL `/sales/collections/export/` + button in `templates/sales/collections_list.html`.
  - [X] Inventory Stock Export: `inventory/views.py::inventory_stock_export` + URL `/inventory/export/` + button in `templates/inventory/stock_list.html`.
  - [X] Vendor Payments Export: `treasury/views.py::vendor_payments_export` + URL `/treasury/payments/export/` + button in `templates/treasury/vendor_payments_list.html`.

---

## Phase 3: Comprehensive Excel Import Workflows

- [X] **Catalog Products Import**:
  - [X] Endpoint `/catalog/import/` (GET upload form & preview, POST upload & atomic execute).
  - [X] Template download `/catalog/import/template/` (download `.xlsx` template).
  - [X] Upload UI with drag & drop or file selector.
  - [X] Multi-step preview modal / page with validation report and row-by-row status.
  - [X] Behavior selector: `create_only`, `update_only`, `create_and_update`.
  - [X] Atomic transactional execution & detailed results summary.
  - [X] Added "استيراد Excel" button to `templates/catalog/products_list.html`.
  - [X] Unit tests added to `catalog/tests.py`.
- [X] **Contacts (Customers & Suppliers) Import**:
  - [X] Endpoint `/contacts/import/` (GET upload form & preview, POST upload & atomic execute).
  - [X] Template download `/contacts/import/template/` (download `.xlsx` template).
  - [X] Multi-step preview with address/area parsing, customer/vendor accounts auto-linking.
  - [X] Behavior selector: `create_only`, `update_only`, `create_and_update`.
  - [X] Atomic transactional execution & detailed results summary.
  - [X] Added "استيراد Excel" button to `templates/contacts/contacts_list.html`.
  - [X] Unit tests added to `contacts/tests.py`.

---

## Phase 4: Mobile Responsiveness Transformation Across All Pages

- [X] **Shared Layout & Navigation (`templates/layouts/base.html`)**:
  - [X] Mobile navigation drawer with offscreen slide (`translate-x-full lg:translate-x-0`).
  - [X] Dark blurred backdrop overlay (`#sidebar-overlay`) with click-to-close handler.
  - [X] Mobile bottom navigation bar for smartphone viewports (`lg:hidden`) with 5 core tabs.
  - [X] Responsive main padding (`p-3 sm:p-4 lg:p-6`) and bottom padding (`pb-24 lg:pb-6`).
  - [X] 44×44px touch targets for navigation and header buttons.
- [X] **Catalog Views**:
  - [X] `products_list.html`: Responsive filter toolbar, bounded scroll table, touch actions.
  - [X] `product_detail.html`: Responsive cards, stacked layout on mobile.
  - [X] `product_form.html`: Full-width inputs on `< md`, touchable buttons.
  - [X] `product_import.html`: Responsive drag-drop dropzone, preview cards and table.
  - [X] `categories_list.html`: Responsive category grid and modal.
- [X] **Contacts Views**:
  - [X] `contacts_list.html`: Responsive filter pill tabs, bounded table, touch actions.
  - [X] `contacts_import.html`: Responsive drag-drop dropzone, preview cards and table.
  - [X] `contact_create.html` & `contact_edit.html`: Responsive horizontal tab bar, stacked fields.
  - [X] `contact_detail.html`: Responsive customer dossier cards, touch dropdown menus.
- [X] **Purchases Views**:
  - [X] `purchase_orders_list.html`: Bounded scroll table, filter pills, touch actions.
  - [X] `purchase_order_create.html`: Responsive line item card repeater on small viewports.
  - [X] `purchase_order_detail.html`: Header actions wrapping, responsive tabs.
  - [X] `purchase_return_orders.html`: Bounded scroll table, touch actions.
  - [X] `purchase_return_order_create.html`: Responsive line items on small viewports.
  - [X] `purchase_return_order_detail.html`: Responsive return order dossier.
- [X] **Sales Views**:
  - [X] `sales_orders_list.html`: Bounded table, responsive filters, Excel export.
  - [X] `sales_order_create.html`: Responsive item rows.
  - [X] `sales_order_detail.html`: Responsive summary cards.
  - [X] `collections_list.html` & `collection_create.html`: Bounded table, full-width inputs, Excel export.
  - [X] `accounting_customers_list.html` & `customer_transactions_list.html`: Responsive ledgers.
- [X] **Treasury Views**:
  - [X] `vendor_payments_list.html` & `vendor_payment_create.html`: Responsive tables, forms, Excel export.
  - [X] `vendor_payment_requests_list.html`, `accounting_vendors_list.html`, `vendor_transactions_list.html`.
  - [X] `vaults_list.html` & `vault_transactions_list.html`: Responsive vault cards and ledger.
- [X] **Inventory Views**:
  - [X] `stock_list.html`: Bounded table, batch pill badges, Excel export.
  - [X] `warehouses_list.html`, `memos_list.html`: Bounded tables and responsive grids.
- [X] **Accounts & Settings Views**:
  - [X] `login.html`: Touch-friendly login card.
  - [X] `users_list.html` & `roles_list.html`: Responsive user management.
  - [X] `branding_settings.html`: Responsive settings form.

---

## Phase 5: Testing, Validation & QA

- [X] Update existing unit tests (`catalog/tests.py`, `contacts/tests.py`, `purchases/tests.py`).
- [X] Add unit tests for `sales/tests.py`, `inventory/tests.py`, and `treasury/tests.py`.
- [X] Run full Django test suite (`python manage.py test`): **48/48 PASSED (100% OK)**.
- [X] Run end-to-end workflow verification (`python test_e2e_workflows.py`): **31 Pages + 8 Excel Exports + 2 Templates + 2 Import Pages PASSED (100% OK)**.
- [X] Verified Viewports across 320px, 375px, 390px, 430px, 768px, 1024px, and Desktop.
- [X] Deliver documentation:
  - [X] `docs/EXCEL_IMPORT_EXPORT_AUDIT.md`
  - [X] `docs/MOBILE_RESPONSIVENESS_AUDIT.md`
  - [X] `docs/IMPLEMENTATION_TODO.md`
  - [X] `docs/IMPLEMENTATION_REPORT.md`

---

## Phase 7: Full-App Pagination, Performance, Filtering, Navigation & Mobile Audit

- [X] **PAG-01**: Implement reusable pagination engine `master_data/pagination_utils.py` with safe bounded parameters (default 25, max 100) and graceful exception recovery.
- [X] **PAG-02**: Implement template tags `{% url_replace %}`, `{% url_remove_param %}`, and `{% smart_page_range %}` in `master_data/templatetags/erp_tags.py`.
- [X] **PAG-03**: Create reusable RTL Arabic pagination UI component `templates/components/pagination.html` with range indicator, bounded `per_page` dropdown (15, 25, 50, 100), numbered buttons, and mobile indicator.
- [X] **FILT-01**: Create reusable active filter chip component `templates/components/active_filters.html` with individual dismiss buttons and a "Clear All" reset link.
- [X] **FILT-02**: Standardize active filter arrays and toolbars across all 18 major data list views.
- [X] **MOD-01**: Upgrade Accounts module (`users_list`, `roles_list`) with `select_related`, `prefetch_related`, pagination, and filter chips.
- [X] **MOD-02**: Upgrade Catalog module (`products_list`, `categories_list`) with Count annotations eliminating N+1, pagination, and filter chips.
- [X] **MOD-03**: Upgrade Contacts module (`contacts_list`) in both Table and Card view modes.
- [X] **MOD-04**: Upgrade Purchases module (`purchase_orders_list`, `purchase_return_orders_list`).
- [X] **MOD-05**: Upgrade Inventory module (`inventory_stock_list`, `warehouses_list`, `inventory_memos_list` with `items_count` annotation).
- [X] **MOD-06**: Upgrade Treasury module (`vendor_payments_list`, `accounting_vendors_list`, `vendor_transactions_list`, `vaults_list`, `vault_transactions_list`).
- [X] **MOD-07**: Upgrade Sales module (`sales_orders_list`, `collections_list`, `accounting_customers_list`, `customer_transactions_list`).
- [X] **MOD-08**: Upgrade Activities module (`agreements_list`, `visits_list`, `visit_templates_list`).
- [X] **PERF-01**: Halved database count query overhead by replacing redundant `qs.count()` calls with `paginator.count`.
- [X] **PERF-02**: Eliminated N+1 query loops across template iterations using `.annotate(Count(...))` and `select_related`/`prefetch_related`.
- [X] **MOB-01**: Audited responsive layout and touch ergonomics across all mandatory viewports: 320px, 375px, 390px, 430px, 768px, 1024px, 1440px.
- [X] **MOB-02**: Verified zero full-page horizontal overflow; tables scroll smoothly inside bounded container boxes.
- [X] **MOB-03**: Verified mobile bottom navigation and slide-over drawer behavior on touch devices.
- [X] **TEST-01**: Added automated unit test suite `master_data/test_pagination_filters.py` (14/14 tests PASSED).
- [X] **TEST-02**: Ran full existing project regression suite (117/117 tests PASSED with 100% OK).
- [X] **DOC-01**: Created `docs/APP_UX_PERFORMANCE_AUDIT.md`.
- [X] **DOC-02**: Created `docs/PAGINATION_AND_FILTERS.md`.
- [X] **DOC-03**: Created `docs/MOBILE_RESPONSIVE_GUIDE.md`.
- [X] **DOC-04**: Created `docs/PERFORMANCE_FINDINGS.md`.
- [X] **DOC-05**: Updated `docs/IMPLEMENTATION_TODO.md`.

---

## Phase 8: Visit & Contact UI Fixes, Full UI Smoke Tests & Data Reimport

- [X] **BUG-01**: Investigate and fix "تسجيل زيارة خارج الخطة" button:
  - [X] Fixed JS syntax error in `templates/components/customer_selection_modal.html` line 400 (missing closing brace `}`).
  - [X] Replaced fragile inline `${JSON.stringify(c)}` attribute with safe in-memory `Map` lookup (`selectUnifiedCustomerById`).
  - [X] Fixed Arabic comma decimal localization syntax error in `templates/activities/visit_form.html` (lines 391-392) using `Number("{{ ...|stringformat:'s' }}")`.
  - [X] Verified complete flow: Global Quick-Add -> Unplanned Visit Modal -> Customer Search & Selection -> Redirect to `/visits/create/?contact_id=...`.
- [X] **BUG-02**: Fix overlapping floating action plus buttons:
  - [X] Removed hardcoded bottom-left inline style in `templates/layouts/base.html` line 422.
  - [X] Implemented consistent responsive vertical-stacking: Global FAB at `fixed bottom-20 lg:bottom-6 left-4 lg:left-6 z-40` clearing mobile nav.
  - [X] Placed page-level create button in `templates/contacts/contacts_list.html` at `fixed bottom-[9.5rem] lg:bottom-24 left-4 lg:left-6 z-30` with `person_add` icon and emerald theme.
  - [X] Applied identical stacking rule to `products_list.html` and `purchase_orders_list.html`.
  - [X] Verified zero overlap across 320px, 375px, 390px, 430px, and 1280px viewports with Playwright bounding-box math.
- [X] **SMOKE-01**: Build and execute comprehensive Playwright UI smoke test suite covering all modules and CRUD operations:
  - [X] Auth & Navigation (Login, Dashboard, KPI cards).
  - [X] Contacts CRUD (List, Search & Filter preservation, Create test contact, Read, Edit, Delete safeguard).
  - [X] Catalog & Products (Products list, Categories list).
  - [X] Purchases & Suppliers (Purchase Orders list, Return Orders list, Vendor Payments).
  - [X] Activities & Visits (Planned visits calendar, Visits log, Unplanned visit form submission, Template auto-selection, Geolocation handling).
  - [X] Settings (Users list, Roles list, Visit templates).
  - [X] Mobile viewport responsiveness (320px, 375px, 390px, 430px).
- [X] **DATA-01**: Inspect and analyze source files in `data_folder/`:
  - [X] `لستة العملاء.xlsx` (8,876 customer records, 42 columns).
  - [X] `اوامر البيع.xlsx` (12,516 lines, 7,088 unique orders, 72 columns).
  - [X] `التحصيلات.xlsx` (6,676 collection receipts, 24 columns).
  - [X] `الاتفاقيات.xlsx` (211 customer agreements, 13 columns).
  - [X] `المرتجعات.xlsx` (432 return items, 270 return orders, 56 columns).
- [X] **DATA-02**: Create comprehensive source-to-model mapping specification (`docs/DATA_IMPORT_MAPPING.md`).
- [X] **DATA-03**: Create verified pre-replacement database backups:
  - [X] `backups/db_pre_replacement_20261020_064511.sqlite3` (8,605,696 bytes, integrity check: ok).
  - [X] `backups/db_backup_import_20261020_064920.sqlite3` (8,605,696 bytes, integrity check: ok).
- [X] **DATA-04**: Execute safe atomic local data replacement (`python manage.py import_excel_data --confirm`):
  - [X] Replaced only business data within import scope inside single atomic transaction (`transaction.atomic`).
  - [X] Preserved migrations, permissions, content types, superuser, vaults, warehouses, and baseline suppliers.
  - [X] Safely renumbered baseline suppliers with positive integers to prevent unique constraint collisions.
  - [X] Updated superuser password to `Wea@4444` and verified authentication.
- [X] **TEST-01**: Run full post-import Django automated regression test suite: 131/131 tests PASSED with 100% OK.
- [X] **TEST-02**: Run post-import Playwright UI smoke tests verifying all workflows against replaced dataset: 25/25 PASSED with 100% OK.
- [X] **DOC-01**: Created `docs/UI_SMOKE_TEST_REPORT.md`.
- [X] **DOC-02**: Created `docs/DATA_IMPORT_MAPPING.md`.
- [X] **DOC-03**: Created `docs/DATA_IMPORT_REPORT.md`.
- [X] **DOC-04**: Updated `docs/IMPLEMENTATION_TODO.md`.

---

## Phase 9: Representative Warehouses, Treasuries, Transfers & Area-Based Approvals

- [X] **DB-01**: Created local SQLite backup `backups/db_backup_pre_rep_warehouses_20261027.sqlite3` (9,936,896 bytes).
- [X] **MOD-01**: Created `UserSettings` singleton model in `accounts.models` with `auto_create_rep_warehouse` and `auto_create_rep_treasury` toggles.
- [X] **MOD-02**: Extended `inventory.Warehouse` with `assigned_user`, `is_rep_warehouse`, and `area` fields (`inventory.migrations.0002`).
- [X] **MOD-03**: Added `ProductTransferRequest` and `ProductTransferRequestItem` models in `inventory.models` supporting references, approvals, and dual inventory memo linkages.
- [X] **MOD-04**: Extended `treasury.Vault` with `is_rep_vault` field (`treasury.migrations.0002`).
- [X] **SRV-01**: Implemented `ensure_representative_resources` in `accounts.services` with `select_for_update()` transaction locking, automatic code formatting (`WH-REP-####`, `VAULT-REP-####`), and area alignment.
- [X] **SRV-02**: Connected `post_save` on `User` and `m2m_changed` on `User.assigned_areas.through` in `accounts.signals` to automatically provision resources and synchronize territories.
- [X] **CMD-01**: Implemented idempotent management command `backfill_representative_resources` with `--dry-run` preview; successfully backfilled all existing representatives without altering balances.
- [X] **AUTH-01**: Standardized manager eligibility across all approvals based strictly on Root Main Area canonical traversal (`get_main_area()`).
- [X] **AUTH-02**: Implemented anti-self-approval and fail-secure access control in `accounts.permissions`.
- [X] **AUTH-03**: Scoped querysets (`get_scoped_queryset`) across warehouses, vaults, stock, memos, transfer requests, and orders to main area for managers and own resources for representatives.
- [X] **AUTH-04**: Implemented strict read-only protection on representative treasuries in `can_user_access_object`: managers can inspect balances/movements but cannot deposit, withdraw, transfer, adjust, or delete.
- [X] **FLOW-01**: Implemented `ProductTransferService` in `inventory.services` with same-main-area validation, accountant/superadmin approval requirement, pessimistic row locking (`select_for_update()`), atomic stock movements, and dual inventory memo generation.
- [X] **FLOW-02**: Enforced server-side representative warehouse assignment in `sales.services` and `sales.views`, ignoring client-forged warehouse IDs.
- [X] **FLOW-03**: Enforced same-main-area manager approval and reservation release on order rejection in `sales.services`.
- [X] **UI-01**: Implemented Users Settings view and template (`templates/accounts/users_settings.html`) with toggles, policy documentation, diagnostic counters, and backfill action.
- [X] **UI-02**: Added transfer requests UI (`product_transfers_list.html`, `product_transfer_create.html`, `product_transfer_detail.html`) and embedded entry point in `warehouses_list.html`.
- [X] **UI-03**: Embedded representative ownership and main area badges in `users_list.html`, `warehouses_list.html`, and `vaults_list.html`.
- [X] **UI-04**: Zero new application tabs or sidebar items added (verified in `templates/layouts/base.html`).
- [X] **TEST-01**: Added comprehensive test suite `accounts/tests_rep_provisioning.py` (5/5 PASSED).
- [X] **TEST-02**: Added comprehensive test suite `inventory/tests_transfers.py` (5/5 PASSED).
- [X] **TEST-03**: Added comprehensive test suite `sales/tests_rep_sales.py` (3/3 PASSED).
- [X] **TEST-04**: Added comprehensive test suite `accounts/tests_area_approvals.py` (7/7 PASSED).
- [X] **TEST-05**: Ran full test suite across `accounts`, `inventory`, `sales`, `treasury`: 49/49 PASSED with 100% OK.
- [X] **TEST-06**: Ran full regression test suite across `activities` visit workflows and agenda: 29/29 PASSED with 100% OK.
- [X] **DOC-01**: Created `docs/REPRESENTATIVE_WAREHOUSES_AND_TREASURIES.md`.
- [X] **DOC-02**: Created `docs/INTER_WAREHOUSE_PRODUCT_REQUESTS.md`.
- [X] **DOC-03**: Created `docs/AREA_BASED_MANAGER_PERMISSIONS.md`.
- [X] **DOC-04**: Created `docs/INVENTORY_AND_SALES_APPROVALS.md`.
- [X] **DOC-05**: Created `docs/MANAGER_OPERATIONAL_VISIBILITY.md`.
- [X] **DOC-06**: Updated `docs/IMPLEMENTATION_TODO.md`.

---

## Phase 10: Mobile Navigation, Responsive Tables, Persistent Column Preferences & Role-Based Dashboards

- [X] **NAV-01**: Removed redundant bottom navigation drawer icon on small screens in `templates/layouts/base.html`, preserving top-right mobile toggle button (`id="mobileMenuToggle"`) as the single entry point.
- [X] **NAV-02**: Verified 4 remaining functional bottom navigation tabs (Home, Contacts, Products, Purchases) remain evenly distributed without blank space.
- [X] **USER-01**: Fixed user names overflowing in navigation menu and profile drawer across small screens and RTL/LTR layouts:
  - Applied `overflow-hidden min-w-0 flex-1` to user info containers.
  - Added `truncate` and `title` tooltip attributes on user name and role name elements.
  - Added `shrink-0` on user avatars and logout button to prevent compression.
- [X] **TAB-01**: Created reusable client-side Table Column Manager in `static/js/table_column_manager.js`:
  - `localStorage` persistence keyed by `erp_table_cols_{table_id}_v1`.
  - Immediate DOM visibility synchronization between headers (`th`) and rows (`td`).
  - "Show All" (`showAll`) and "Reset to Defaults" (`resetDefaults`) actions.
  - Locked required/identifying columns (`required: true`) that cannot be hidden.
  - Safe fallback to defaults if storage is unavailable or corrupted.
- [X] **TAB-02**: Created reusable table column picker component in `templates/components/table_column_picker.html`.
- [X] **TAB-03**: Audited and upgraded 17 data tables with responsive containers (`overflow-x-auto scrollbar-thin`), explicit minimum widths (`min-w-[750px]` - `min-w-[1000px]`), column visibility tags (`data-col-table`, `data-col`), and column picker integration:
  - Contacts (`contacts_list.html`)
  - Sales Orders (`sales_orders_list.html`)
  - Collections (`collections_list.html`)
  - Accounting Customers (`accounting_customers_list.html`)
  - Inventory Stock (`stock_list.html`)
  - Inventory Memos (`memos_list.html`)
  - Product Transfers (`product_transfers_list.html`)
  - Purchase Orders (`purchase_orders_list.html`)
  - Purchase Return Orders (`purchase_return_orders.html`)
  - Vaults (`vaults_list.html`)
  - Vault Transactions (`vault_transactions_list.html`)
  - Vendor Payments (`vendor_payments_list.html`)
  - Accounting Vendors (`accounting_vendors_list.html`)
  - Visits (`visits_list.html`)
  - Agreements (`agreements_list.html`)
  - Products (`products_list.html`)
  - Users (`users_list.html`)
- [X] **DASH-01**: Implemented role-based dashboard cards and chart datasets in `master_data/views.py`:
  - **SuperAdmin**: System-wide operational and financial metrics (14 cards) and all 6 visualization charts.
  - **Accountant**: Financial metrics only (10 cards) and 5 financial charts; field visit cards and visits-by-area chart strictly omitted.
  - **Representative**: Own operational pipeline metrics (rep warehouse stock value, rep vault balance, own sales, collections, visits); cross-rep comparison charts (`reps_balance`, `reps_overdue`) strictly omitted to preserve peer privacy.
  - **Manager**: Main-area team operational statistics with representative selector.
- [X] **DASH-02**: Implemented Manager Representative Selector in `templates/dashboard/home.html` top controls:
  - Integrated directly into existing dashboard page (zero new tabs added).
  - Backend validation against `is_manager_eligible_for_user`: cross-area attempts safely rejected with automatic fallback to team scope.
  - Active representative banner indicator with one-click return to team scope ("العودة لإحصائيات الفريق كامل").
  - Preserves date filters seamlessly across rep selection changes.
- [X] **TEST-01**: Created comprehensive automated test suite `master_data/tests_dashboard_roles.py` (9/9 tests PASSED with 100% OK).
- [X] **TEST-02**: Verified regression safety across area approvals and regional permissions suites (24/24 tests PASSED with 100% OK).
- [X] **DOC-01**: Created `docs/RESPONSIVE_TABLES.md`.
- [X] **DOC-02**: Created `docs/TABLE_COLUMN_PREFERENCES.md`.
- [X] **DOC-03**: Created `docs/DASHBOARD_ROLE_PERMISSIONS.md`.
- [X] **DOC-04**: Updated `docs/IMPLEMENTATION_TODO.md`.




