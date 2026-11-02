# Visit Template Configuration & Role Restrictions

**Project:** WEA Pharma ERP  
**Module:** Activities Subsystem (`activities`)  
**Specification:** Supported Template Configuration, Role Restrictions & Obsolete Settings Removal  

---

## 1. Supported Visit Template Settings

The Visit Template create and edit interface (`/activities/templates/create/` and `/activities/templates/<id>/edit/`) is organized into focused, intuitive sections:

### A. General Information (معلومات القالب العامة)
- **`name`** (رمز / معرف القالب الإنجليزي): Unique alphanumeric slug identifier (e.g. `doctor_clinic_visit`, `pharmacy_regular`).
- **`display_name_ar`** (اسم القالب بالعربية): User-facing display name in Arabic.
- **`description`** (الوصف / تعليمات المندوب): Optional guidance displayed to representatives during visit execution.
- **`active`** (حالة التفعيل): Boolean toggle controlling whether the template appears in visit creation screens.

### B. Customer Account Types (أنواع حسابات العملاء المصرح بها)
- **`restrict_account_types`** (`JSONField`): List of permitted customer account types (e.g., `clinic`, `pharmacy`, `hospital`, `dental`).
- **Validation:** When set, visits using this template can only be registered for contacts matching these account types. Validated both in the frontend selector and server-side in `VisitTemplate.is_contact_eligible(contact)`.

### C. Execution & Detailing Options (خيارات التنفيذ والترويج)
- **`allow_unplanned`** (السماح بالزيارات خارج الخطة): Boolean toggle allowing this template to be used for unplanned/ad-hoc visits. (Note: unplanned visits still require manager approval).
- **`enable_product_detailing`** (تفعيل الترويج الدوائي للأصناف): When enabled, representatives can select and detail eligible sellable products.
- **`suggested_products`** (`ManyToManyField`): Optional curated list of recommended sellable products highlighted with `★ مقترح` badges during detailing.

### D. Restricted Roles (الأدوار الوظيفية المصرح لها)
- **`restricted_roles`** (`ManyToManyField` to `accounts.Role`): Configures which employee roles are authorized to use this template.
- **Semantics:**
  - **Empty Selection (الافتراضي):** The template is available to **all active employee roles** in the organization.
  - **Specific Roles Selected:** Only active users possessing one of the selected roles (or Superusers / SuperAdmins) can view, create, or execute visits with this template.
- **UI Component Features:**
  - Search filter input to quickly find roles in large organizations.
  - "تحديد الكل" (Select All) and "إلغاء التحديد" (Deselect All) convenience actions.
  - Live selection counter badge (`X دور محدد`).
  - Scrollable badge pill display of currently selected roles with instant removal.
  - Mobile touch-friendly targets ($\ge 44\text{px}$ minimum height).
  - Clear explainer card explaining default-open semantics.

---

## 2. Removed Obsolete Configuration Options

The following 4 configurable options were removed from the template interface and data model because they contradicted the standardized, auditable visit lifecycle:

| Removed Setting | Model Field | Rationale for Removal |
| :--- | :--- | :--- |
| **Check-in / Check-out Mode** | `mode` (`checkin_checkout`, `instant`, etc.) | **Contradiction:** All visits must follow explicit representative check-in and check-out to capture accurate timestamps and calculate server-side duration. Configurable bypasses created inconsistent audit data. |
| **Configurable Visit Outcomes** | `visit_outcome_mode` | **Contradiction:** All visits follow the unified state machine (`planned` $\to$ `started` $\to$ `finished`). Templates must not configure alternate outcome branches or bypass standard completion. (Historical visit outcomes on `Visit.visit_outcome` remain intact for reporting). |
| **Auto-Approve Unplanned Visits** | `auto_approve_unplanned` | **Contradiction:** Every visit (planned and unplanned) requires manager approval before starting. Automatic approval bypassed regional manager oversight and dual-control rules. |
| **Auto-End Visit** | `auto_end_visit` | **Contradiction:** Every visit must be explicitly concluded by the representative. Automatically ending a visit on question submission or modal dismiss prevented proper check-out GPS verification and corrupted visit duration calculations. |

---

## 3. Server-Side Enforcement of Role Restrictions

The Restricted Roles configuration is enforced strictly across all operations:

1. **Template Directory & Selectors:**
   - `VisitTemplate.is_user_eligible(user)` checks role assignment:
     ```python
     def is_user_eligible(self, user):
         if not user or not user.is_authenticated:
             return False
         if user.is_superuser or getattr(user, 'is_super_admin', False):
             return True
         if not self.restricted_roles.exists():
             return True
         user_role = getattr(user, 'role', None)
         if not user_role or not user_role.is_active:
             return False
         return self.restricted_roles.filter(id=user_role.id).exists()
     ```
2. **API Endpoint (`/api/visit-templates/`):**
   - Templates are filtered by `is_user_eligible(request.user)`. Unauthorized templates are omitted from JSON results.
3. **Visit Creation (`/activities/visits/create/`):**
   - Rejects submissions if `not template.is_user_eligible(request.user)` with HTTP 400 validation error.
4. **Visit Check-in / Start (`start_visit` service):**
   - Validates template role eligibility before allowing transition to `started`.
5. **Answer Submission & Detailing (`save_visit_answers` service):**
   - Rejects answer submission if the user's role does not match template restrictions.
6. **Visit Check-out / End (`end_visit` service):**
   - Enforces template role eligibility prior to completing the visit.

---

## 4. Suggested Products Migration to Visit Templates

### Context & Rationale
Previously, "المنتجات المقترحة للزيارات الميدانية" were erroneously placed inside Location Settings (`/settings/location/`). This violated domain separation, as location settings manage GPS coordinate tolerances, Wi-Fi verification, and mock-location detection. Product suggestions belong naturally to Visit Templates, where detailing requirements vary by medical specialty and visit objective.

### Key Changes
1. **Relocated from Location Settings:**
   - Card 4 ("المنتجات المقترحة للزيارات الميدانية") completely removed from `templates/settings/location_settings.html`.
   - Associated POST processing removed from `master_data/views.py` (`location_settings_view`), with audit logging retained.
2. **Integrated into Visit Template Form:**
   - Accordion 4 ("المنتجات المقترحة للزيارات الميدانية") added to `templates/activities/visit_template_form.html`.
   - Features real-time search, counter badges, select all / deselect all, and clear display pills.
3. **Product Eligibility Enforcement:**
   - Restricted strictly to sellable and active products (`Product.objects.filter(sellable=True, is_active=True)`).
   - Backend verification method: `VisitTemplate.get_eligible_suggested_products()`.
   - Unit tests verified in `activities/tests_suggested_products.py`.
