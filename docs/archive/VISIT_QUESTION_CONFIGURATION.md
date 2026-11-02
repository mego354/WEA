# Visit Question Configuration & Feature Deprecation

## 1. Overview
This document specifies the deprecation and deactivation of duplicate visit questions, removal of obsolete sample distribution elements, and standardization of client display formatting across the ERP.

---

## 2. Removal of Duplicate Outcome Question: `هل كان يوم ناجح ؟ *`

### 2.1 The Problem
In the visit completion workflow, the section `نتيجة الزيارة (Visit Outcome)` contained a redundant question:
- `هل كان يوم ناجح ؟ *` (Question ID: 16 in database seeds)

This question duplicated the native visit success field (`visit.is_successful`), causing user confusion and redundant data entry.

### 2.2 Resolution & Safe Deactivation
1. **Database Migration (`activities/migrations/0007_deactivate_duplicate_outcome_question.py`)**:
   - Executes a non-destructive data update setting `is_active=False` for any `VisitTemplateQuestion` whose Arabic text matches `هل كان يوم ناجح`.
   - **Audit Preservation**: No historical records or `VisitAnswer` instances were deleted. Past audits and report histories remain intact.
2. **Model Level Filtering (`activities/models.py`)**:
   - Added method `get_active_questions(self)` to `VisitTemplate`:
     ```python
     def get_active_questions(self):
         """Returns active questions excluding obsolete duplicate outcome questions."""
         return self.questions.filter(is_active=True).exclude(text_ar__icontains='هل كان يوم ناجح')
     ```
   - Templates and views now invoke `template.get_active_questions()` when rendering questionnaires.
3. **Seed Clean-Up**:
   - Cleaned `activities/management/commands/seed_activities.py` and `scratch/seed_visit_templates.py` to prevent reintroduction during fresh deployments.
4. **Validation Logic**:
   - Removed any required-field checks or frontend JS constraints tied specifically to this question.

---

## 3. Deprecation of Active Medical Sample Distribution: `توزيع عينة طبية (اختياري)`

### 3.1 The Problem
The active visit creation form included an optional section for distributing medical samples during initial check-in. This feature was deprecated in favor of warehouse requisition and inventory transfer modules.

### 3.2 Resolution & Safeguards
1. **Frontend Removal (`templates/activities/visit_form.html`)**:
   - Removed Section 4 (Sample distribution inputs `sample_product` and `sample_quantity`).
   - Removed associated frontend event listeners and validation handlers.
2. **Backend Processing (`activities/views.py`)**:
   - Removed `VisitSampleItem.objects.create` calls from `visit_create`.
   - If legacy payloads submit `sample_product`, it is safely ignored without breaking the request.
3. **Historical Audit Preservation (`templates/activities/visit_detail.html`)**:
   - The `VisitSampleItem` database model remains intact to ensure zero data loss.
   - In `visit_detail.html`, the samples table is rendered conditionally:
     ```html
     {% if visit.samples.exists %}
     <div class="bg-white rounded-2xl border border-slate-200 p-5">
         <h3 class="text-xs font-bold text-slate-800">العينات الطبية المسلمة (سجل تدقيق)</h3>
         ...
     </div>
     {% endif %}
     ```
   - Historical visits with past sample distributions continue to render accurately in audit views.

---

## 4. Client Name Display Standardization (Names Without Codes)

### 4.1 Requirement
All client and account selectors, cards, table lists, and detail headers must display client names **only**, without appended or prepended account codes (e.g., `صيدلية النور` instead of `[PH001] صيدلية النور` or `صيدلية النور - PH001`).

### 4.2 Implementation Details
1. **Model Representation (`contacts/models.py`)**:
   - `Contact.__str__` updated to return `self.name`.
   - `Contact.display_tag` updated to return `self.name`.
2. **Form Selectors (`activities/forms.py`)**:
   - `CustomerModelChoiceField.label_from_instance` updated to return `obj.name`.
3. **Search API (`contacts/views.py`)**:
   - `customers_search_api` returns `'display_tag': c.name`.
   - Internal search by code (`c.code`) remains fully functional in database lookups.
4. **Templates & Modals**:
   - `templates/activities/visit_form.html`: Typeahead dropdown and dossier card show `c.name`.
   - `templates/components/customer_selection_modal.html`: Search results display clean customer name.
   - `templates/activities/visits_list.html`: Removed `[{{ v.contact.code }}]` column decoration.
   - `templates/activities/planned_visits_list.html`: Removed code prefixes from planned items and itinerary drawer.
   - `templates/activities/visit_detail.html`: Removed code banner from customer info panel.
