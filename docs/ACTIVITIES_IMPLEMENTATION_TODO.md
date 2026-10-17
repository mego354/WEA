# Activities Module Implementation & Parity Task Tracker

**Document Version:** 3.0  
**Status Key:** `NOT STARTED` | `IN PROGRESS` | `BLOCKED` | `FIXED — NOT VERIFIED` | `VERIFIED`  
**Overall Completion:** 100% (9 of 9 Tasks Verified)

---

## Task Items

### TASK-01: Remove Unwanted "Calls" Functionality (DISC-01)
- **Reference Behavior:** In scope are Visits, Planned Visits, Agreements under Activities. No "Calls to Actives" module exists in scope.
- **Current Local Behavior:** Removed completely. `CallActivity` model dropped via migration `activities/migrations/0002_delete_callactivity.py`. Routes `calls/` and `calls/export/` removed from `activities/urls.py`. Views removed from `activities/views.py`. `templates/activities/calls_list.html` deleted.
- **Affected Files:**
  - `activities/models.py`
  - `activities/urls.py`
  - `activities/views.py`
  - `templates/layouts/base.html`
  - `templates/activities/calls_list.html`
  - `activities/tests.py`
  - `test_e2e_workflows.py`
- **Priority:** P0
- **Implementation Status:** VERIFIED
- **Verification Status:** VERIFIED
- **Verification Evidence:** `GET /calls/` returns HTTP 404 Not Found. Django test suite and `test_e2e_workflows.py` pass with 0 errors.

---

### TASK-02: Implement Bottom-Left Floating Action Button (FAB) & Quick-Add Bottom Sheet (DISC-02, DISC-08)
- **Reference Behavior:** Circular 56x56px teal button `#27BEBE` at `bottom: 16px; left: 16px;` globally on all pages. Clicking it opens a Material Bottom Sheet (`app-quick-add`) with dark backdrop and 5 options:
  1. `room` -> تسجيل زيارة خارج الخطة
  2. `shopping_cart` -> امر بيع جديد
  3. `refresh` -> مرتجع جديد
  4. `receipt` -> تحصيل جديد
  5. `الغاء` (Cancel with red text, closes bottom sheet)
- **Current Local Behavior:** Implemented in `templates/layouts/base.html` with exact teal styling (`#27bebe`), box shadow matching reference, and bottom sheet drawer with all 5 options. Removed conflicting ad-hoc FAB from `templates/activities/planned_visits_list.html`.
- **Affected Files:**
  - `templates/layouts/base.html`
  - `templates/activities/planned_visits_list.html`
- **Priority:** P0
- **Implementation Status:** VERIFIED
- **Verification Status:** VERIFIED
- **Verification Evidence:** Playwright responsive tests verified FAB click opens bottom sheet across all 9 viewports (320px to 1920px). Screenshots saved in `scratch/responsive_audit/`.

---

### TASK-03: Implement Unplanned Visit Customer Selection Dialog (DISC-03)
- **Reference Behavior:** Clicking "تسجيل زيارة خارج الخطة" from FAB opens `app-visit-create-customer-selection` dialog with customer search; selecting customer navigates to or initiates the visit.
- **Current Local Behavior:** Implemented modal `#unplanned-visit-modal` in `base.html` triggered by Action 1 of Quick-Add sheet. Reps can search contacts and launch `/visits/create/?contact_id=<id>`.
- **Affected Files:**
  - `templates/layouts/base.html`
  - `activities/views.py`
  - `templates/activities/visits_list.html`
- **Priority:** P1
- **Implementation Status:** VERIFIED
- **Verification Status:** VERIFIED
- **Verification Evidence:** Playwright tests confirm opening the dialog and filtering contacts across mobile and desktop viewports. Unit and E2E tests pass.

---

### TASK-04: Activities Navigation Menu Parity (DISC-04)
- **Reference Behavior:**
  - Header: `timeline` - `الأنشطة`
  - Subitems:
    1. `calendar_today` - `خطة الزيارات`
    2. `room` - `الزيارات`
    3. `handshake` - `الاتفاقيات`
- **Current Local Behavior:** Submenu contains strictly the 3 reference items in exact order with exact icons (`calendar_today`, `room`, `handshake`).
- **Affected Files:**
  - `templates/layouts/base.html`
- **Priority:** P1
- **Implementation Status:** VERIFIED
- **Verification Status:** VERIFIED
- **Verification Evidence:** Verified in DOM inspection across all pages and viewports.

---

### TASK-05: Agreements Toolbar Action & Header Parity (DISC-05, DISC-06)
- **Reference Behavior:** Table headers: `#`, `عميل`, `العنوان`, `النوع`, `المبلغ`, `التاريخ`, `المنشئ`, `الحالة`. Row selection exposes `تغيير الحالة` (Change Status) in toolbar. Soft status badge colors.
- **Current Local Behavior:** Table contains row checkboxes, select-all header checkbox, exact column ordering, soft status badges (new, approved, disapproved, done). Selecting rows displays `تغيير الحالة` toolbar dropdown connected to `agreements_bulk_status` endpoint.
- **Affected Files:**
  - `templates/activities/agreements_list.html`
  - `activities/views.py`
  - `activities/urls.py`
- **Priority:** P1
- **Implementation Status:** VERIFIED
- **Verification Status:** VERIFIED
- **Verification Evidence:** `test_agreements_bulk_status` passed in `activities/tests.py` and section 11 of `test_e2e_workflows.py`.

---

### TASK-06: Visits Table Columns, Filters & Card View Parity (DISC-07)
- **Reference Behavior:** Table with 15 standard columns (`زيارة`, `جهة الاتصال`, `التاريخ`, `بدأ في`, `انتهى في`, `المنطقة`, `التخصص`, `تصنيف العميل`, `نوع الاكونت`, `زيارة ناجحة`, `المنتجات المشروحة`, `المدة`, `المسؤول`, `الحالة`, `زيارة مزدوجة`). Drawer filters match reference. Card view switchable.
- **Current Local Behavior:** Visits list table aligned with reference column ordering and badges. View toggle between `table_chart` and `view_agenda` cards functional. Filter drawer aligned.
- **Affected Files:**
  - `templates/activities/visits_list.html`
  - `activities/views.py`
- **Priority:** P1
- **Implementation Status:** VERIFIED
- **Verification Status:** VERIFIED
- **Verification Evidence:** Verified with unit tests, E2E tests, and Playwright screenshots across viewports.

---

### TASK-07: Backend Permissions & Role-Based Access Control (DISC-10)
- **Reference Behavior:** Medical Reps cannot approve visits or agreements. District/Area Managers and SuperAdmin can approve.
- **Current Local Behavior:** Implemented `can_manage_approvals(user)` in `activities/views.py`. Enforced on `visit_action`, `agreement_action`, and `agreements_bulk_status`. Reps attempting status changes receive flash warning and are blocked.
- **Affected Files:**
  - `activities/views.py`
  - `templates/activities/agreement_detail.html`
  - `templates/activities/visit_detail.html`
- **Priority:** P0
- **Implementation Status:** VERIFIED
- **Verification Status:** VERIFIED
- **Verification Evidence:** Tested with `test_rep_permissions_restriction` in `activities/tests.py` and section 12 in `test_e2e_workflows.py`.

---

### TASK-08: Responsive Parity Across Screen Sizes (DISC-09)
- **Reference Behavior:** Flawless presentation from 320px to 1920px. On mobile, FAB stays accessible without colliding with bottom bar. Modals scroll vertically without breaking viewport. Zero horizontal page overflow.
- **Current Local Behavior:** Verified with Playwright across all 9 required viewports:
  - 320 × 640 (iPhone SE / compact)
  - 360 × 800 (Android compact)
  - 375 × 812 (iPhone X)
  - 390 × 844 (iPhone 12/14)
  - 430 × 932 (iPhone 15 Pro Max)
  - 768 × 1024 (iPad portrait)
  - 1024 × 768 (iPad landscape)
  - 1366 × 768 (Laptop HD)
  - 1920 × 1080 (Desktop FHD)
- **Affected Files:**
  - `templates/layouts/base.html`
  - `templates/activities/visits_list.html`
  - `templates/activities/planned_visits_list.html`
  - `templates/activities/agreements_list.html`
- **Priority:** P2
- **Implementation Status:** VERIFIED
- **Verification Status:** VERIFIED
- **Verification Evidence:** `scratch/verify_responsive.py` executed: 54 screenshots produced, 0 horizontal overflow errors detected.

---

### TASK-09: Automated & Playwright Regression Verification
- **Reference Behavior:** All unit tests, workflow simulations, and browser visual comparisons pass with 0 errors.
- **Current Local Behavior:** All tests pass with 100% success rate:
  - `python manage.py test activities` (5 tests OK in 2.8s)
  - `python test_e2e_workflows.py` (13 sections 100% PASS)
  - `python scratch/verify_responsive.py` (9 viewports 100% PASS)
- **Affected Files:**
  - `activities/tests.py`
  - `test_e2e_workflows.py`
  - `scratch/verify_responsive.py`
- **Priority:** P1
- **Implementation Status:** VERIFIED
- **Verification Status:** VERIFIED
- **Verification Evidence:** Logs confirm 0 failures across all test suites.
