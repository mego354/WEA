# Visit Subsystem Code Quality Audit & Refactoring Report

**Project:** WEA Pharma ERP  
**Module:** Activities Subsystem (`activities`)  
**Specification:** Code Cleanup, Dead Code Removal & Quality Improvements  

---

## 1. Dead & Unnecessary Code Removed

During this refactoring, a systematic audit of the visit subsystem was conducted:

### A. Unreachable Code in Approvals View
- **File:** `activities/approvals_views.py`
- **Audit Finding:** In `visit_action()` (or `visit_approval_action`), lines 41–184 contained an unreachable 144-line code block situated directly after an unconditional `return redirect(url)` statement.
- **Action Taken:** Completely excised the dead 144 lines, removed obsolete imports (`datetime`, unused models), and cleaned up view handler signatures.

### B. Obsolete Template Model Fields
- **File:** `activities/models.py` (`VisitTemplate`)
- **Audit Finding:** The fields `mode`, `visit_outcome_mode`, `auto_approve_unplanned`, and `auto_end_visit` were creating dead branches and conflicting lifecycle states across views, forms, serializers, and templates.
- **Action Taken:**
  - Safely removed fields from `VisitTemplate` in `activities/models.py`.
  - Cleaned up obsolete kwargs from `activities/admin.py` (`list_display`, `list_filter`).
  - Removed fields from `VisitTemplateForm` (`activities/forms.py`).
  - Generated and applied forward-only database migration `activities/migrations/0012_remove_obsolete_visittemplate_settings.py`.

### C. Obsolete Frontend Logic & Template Fragments
- **Templates Audited:**
  - `templates/activities/visit_template_form.html`: Removed accordion controls and input widgets for the 4 obsolete settings.
  - `templates/activities/visit_templates_list.html`: Removed outdated badge pills rendering `mode` and `auto_approve_unplanned`.
  - `templates/activities/visit_template_preview.html`: Removed `mode` pill and outcome dropdown.
  - `templates/activities/visit_detail.html`: Removed automatic status changes and aligned banner display to active lifecycle.

---

## 2. Refactoring & Architecture Enhancements

### A. Atomic, Concurrency-Safe Lifecycle Services
- **File:** `activities/services.py`
- **Enhancement:** Implemented dedicated domain service functions:
  - `can_start_visit(visit, user)` & `start_visit(...)`
  - `can_submit_answers(visit, user, answers)` & `save_visit_answers(...)`
  - `can_end_visit(visit, user, answers)` & `end_visit(...)`
- **Concurrency Protection:** Uses `select_for_update()` inside `transaction.atomic()` blocks to prevent race conditions during simultaneous check-in, check-out, or status modification requests.
- **Server-Side Timestamp & Duration Authority:** Duration is strictly computed on the server from `(ended_at - started_at).total_seconds()`, preventing client manipulation.

### B. Accessible, Responsive Restricted Roles Component
- **Component:** Redesigned Accordion 3 in `templates/activities/visit_template_form.html`.
- **Features:**
  - Real-time client-side search filter over role display names.
  - Select-all and Deselect-all bulk convenience buttons.
  - Active selection counter badge and removable badge pills.
  - Full touch accessibility ($\ge 44\text{px}$ touch targets).
  - Clean vanilla JavaScript without external library dependencies.

### C. Database Query Optimization
- Enhanced `select_related('contact', 'template', 'owner', 'created_by')` and `prefetch_related('detailed_products')` in `visit_create`, `visit_detail`, and `agenda_view` to eliminate N+1 database queries.

---

## 3. Remaining Technical Debt & Future Recommendations

1. **Client-Side Offline Caching:** Currently, check-in and questionnaire draft submissions require active internet connectivity. A Progressive Web App (PWA) ServiceWorker with IndexedDB could buffer draft submissions in remote clinic areas with spotty cell reception.
2. **Scheduled Visit Reminders:** Background cron job (via Celery or Django-Q) to alert representatives of planned visits scheduled for today that have not yet been started.
