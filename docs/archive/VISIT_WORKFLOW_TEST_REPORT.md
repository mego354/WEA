# Visit Workflow QA & Test Report

## 1. Test Suite Summary
- **Test Framework**: Django Test Runner / `django.test.TestCase`
- **Total Test Cases**: **45 Automated Tests**
- **Test Results**: **45 PASSED, 0 FAILED, 0 ERRORS**
- **Execution Time**: ~39 seconds
- **Browser Automation Verification**: Verified across desktop (`1440px`), tablet (`768px`), and mobile viewports (`430px`, `390px`, `375px`, `320px`).

---

## 2. Automated Test Coverage Breakdown

### 2.1 Template Settings & Restrictions (`VisitTemplatesManagementTestCase`)
- `test_visit_templates_list_view`: Verifies listing of active templates and permission segregation.
- `test_template_create_and_edit`: Tests creating a template restricted to `['Pharmacy']`, editing to `['Pharmacy', 'Store']`, and verifying persistence across reloads.
- `test_template_preview_view`: Validates rendering of questions in preview mode.
- `test_template_toggle_status`: Tests activation and deactivation toggle endpoint.
- `test_unauthorized_user_cannot_modify_template_settings`: Verifies 403 / redirect when a non-manager attempts template alteration.

### 2.2 Template Account-Type Eligibility (`VisitTemplatesWorkflowIntegrationTestCase` & `VisitWorkflowsAndPermissionsComprehensiveTestCase`)
- `test_account_type_restrictions_persistence_and_enforcement`:
  - Pharmacy-only template accepts `Contact(account_type='Pharmacy')`.
  - Rejects `Contact(account_type='Clinic')` and `Contact(account_type='Hospital')` with Arabic validation message.
  - Clinics & Hospitals template accepts clinics and hospitals, rejecting pharmacies.
- `test_visit_templates_api_filters_by_account_type`:
  - Querying `/api/templates/?contact_id=<clinic>` returns only doctor templates.
  - Querying `/api/templates/?contact_id=<pharmacy>` returns only pharmacy templates.

### 2.3 Visit Lifecycle: Create First, Answer Later (`VisitWorkflowsAndPermissionsComprehensiveTestCase`)
- `test_create_first_answer_later_lifecycle`:
  - Creation form submits minimal data -> creates visit with `status='started'`.
  - Redirects to `/visits/<id>/`.
  - Saving draft updates answers, retains `status='started'`.
  - Completing with photo evidence and GPS transitions status to `'finished'` and sets `ended_at`.
- `test_unplanned_visit_validation_enforces_required_fields`:
  - Validates that required questionnaire items must be completed before `action='complete'`.
  - Preserves answers when validation errors occur.
- `test_duplicate_submission_protection`:
  - Prevents rapid double-clicks from creating duplicate started visits.

### 2.4 Planned vs Unplanned Classification
- `test_planned_and_unplanned_classification_and_filters`:
  - Verifies persistent boolean `is_planned`.
  - Verifies badges `زيارة مخططة` and `زيارة خارج الخطة`.
  - Tests filtering `/visits/?plan_type=planned` and `/visits/?plan_type=unplanned`.

### 2.5 Locked Representative Assignment
- `test_representative_assignment_locked_for_field_reps`:
  - Standard representative submitting tampered `owner_id` has it overridden by the server to authenticated user.
- `test_superuser_can_assign_other_representative`:
  - Authorized superuser/manager can assign another valid representative.

### 2.6 Location & Photo Evidence
- `test_evidence_photo_protected_endpoint`:
  - Protected endpoint serves image to owner and manager (200).
  - Blocks unauthorized representative with 403 Forbidden.
- `test_superuser_bypass_audit_trail`:
  - Superuser bypass sets `verification_status='force_bypassed'`.
  - Records `bypassed_by`, `bypassed_at`, and `bypass_reason`.
- `test_gps_matrix_1_through_9`:
  - Complete 9-point geofence matrix testing within tolerance (300m), out-of-tolerance, missing GPS, customer auto-capture, and direct API tampering.

### 2.7 Product Detailing Restriction
- `test_product_detailing_strictly_restricted_to_three_templates`:
  - Detailed products permitted and saved for: (1) Single DR, (2) Single Pharmacy, (3) Healthy Day.
  - Cleared and rejected for unsupported templates (Coaching, General).

---

## 3. Browser Automation & Mobile Viewport Matrix

| Screen / Workflow | Viewport | Verified Behavior | Status |
|---|---|---|:---:|
| Template Settings (`/settings/visits/templates/`) | 1440x900 | Clean table layout, active badges, action dropdowns | PASS |
| Template Edit (`/settings/visits/templates/1/edit/`) | 1440x900 | Checkboxes restored for `صيدلية (Pharmacy)`, no clipping | PASS |
| Template Edit | 375x812 | Dual-column responsive grid, touch-friendly checkboxes | PASS |
| Visits List (`/visits/`) | 1440x900 | Planned/Unplanned filter pills, plan type badges, camera icon | PASS |
| Visits List | 390x844 | Cards view automatically active, no horizontal overflow | PASS |
| Visits List | 320x568 | Compact chips, touch targets >= 44px, RTL alignment | PASS |
| Visit Create (`/visits/create/`) | 1440x900 | Customer typeahead, locked representative badge, GPS card | PASS |
| Visit Create | 375x812 | Full-width submit button "بدء الزيارة والانتقال للاستبيان" | PASS |
| Visit Detail / Answering (`/visits/<id>/`) | 1440x900 | Active banner, survey questions, photo card, sticky bar | PASS |
| Visit Detail / Answering | 390x844 | Camera trigger with live preview, responsive action bar | PASS |
| Visit Detail / Answering | 320x568 | No overflow, clean typography, accessible cancel/save | PASS |
| Evidence Photo (`/visits/<id>/evidence/photo/`) | Any | Protected stream, 403 for unauthorized users | PASS |
