# Visit Template Test Plan (خطة اختبار قوالب الزيارات)

> **Module**: Visit Templates & Visit Lifecycle Integration  
> **Environment**: Local Django Test Suite (`py manage.py test activities`)  
> **Target Status**: 100% Pass with zero regressions

---

## 1. Test Objectives

1. Verify complete CRUD for `/settings/visits/templates` (List, Create, Edit, Delete, Preview, Add/Remove Questions).
2. Verify that all 6 standard reference templates are accurately seeded with questions, options, and constraints.
3. Verify that planned visit creation assigns templates and executed visits inherit the template.
4. Verify that unplanned visit creation filters templates by customer account type.
5. Verify dynamic questionnaire rendering and validation (required questions, conditional logic, product detailing).
6. Verify check-in (start_only stage) vs completion stage logic.
7. Verify visit dossier rendering of answers and historical preservation upon edit.
8. Verify backend authorization and permissions.

---

## 2. Test Suite Matrix

### Suite 1: Template CRUD & Questions
- `test_visit_templates_list_view`: Renders 6 cards with badges, pills, and 3-dot menus.
- `test_visit_template_create`: Creates template with settings, restrictions, and questions.
- `test_visit_template_edit`: Updates template names, settings, and questions.
- `test_visit_template_delete`: Safeguard against deleting templates in active use.
- `test_visit_template_preview`: Renders questionnaire preview with interactive mock buttons.
- `test_question_crud`: Adds single-choice, multiple-choice, text, textarea, and conditional questions.

### Suite 2: Planned Visits Integration
- `test_planned_visit_template_assignment`: Assigns template on `PlannedVisitItem`.
- `test_planned_visit_execution`: Launching visit from planned item loads template and preselected customer.

### Suite 3: Unplanned Visits & Dynamic Questionnaire
- `test_unplanned_visit_template_filtering`: Customers with account_type `Clinic` see `Single visit (DR)`, etc.
- `test_unplanned_visit_questionnaire_validation`: Required questions must be answered.
- `test_conditional_questions`: Answering parent triggers conditional question visibility.
- `test_product_detailing_persistence`: Selected detailed products are saved to `visit.detailed_products`.

### Suite 4: Visit Lifecycle & Representative Confirmation
- `test_start_visit_questions`: Questions with stage `start_only` are captured during check-in.
- `test_finish_visit_submission`: Visit completes with duration, outcome, and answers.
- `test_visit_edit_answers`: Editing a visit updates answers while preserving historical integrity.
- `test_visit_detail_view`: Renders answers cleanly alongside visit information.

### Suite 5: Authorization & Regressions
- `test_unauthorized_user_blocked`: Restricted users cannot access `/settings/visits/templates`.
- `test_full_activities_regression`: Existing agreement, planned visit, and location verification tests continue to pass.
