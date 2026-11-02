# Activities Module Reference-Parity Audit Report

**Date of Audit:** October 16, 2026  
**Reference ERP:** `https://weapharma.bricks-rep.com` (Workspace: `weapharma`, Version: `26.10.13-84efe84`)  
**Auditor:** Senior ERP Reverse Engineer, Django Engineer, Business Analyst & QA Automation Specialist  
**Safety Protocol:** Strict Read-Only inspection on reference ERP. Zero mutations on production records. All mutations & CRUD verification conducted locally.

---

## 1. Executive Summary & Discrepancy Classification

This audit documents every functional, visual, layout, CRUD, workflow, data model, and permission discrepancy between the reference ERP system and the local Django ERP codebase for the **Activities (`الأنشطة`)** domain, covering:
1. **Activities Navigation & Submenu Structure**
2. **Bottom-Left Floating Action Button (FAB) & Quick-Add Bottom Sheet**
3. **Visits Module (`الزيارات`)**
4. **Planned Visits Planner (`خطة الزيارات`)**
5. **Agreements Module (`الاتفاقيات`)**
6. **Unwanted Calls Scope Removal (`المكالمات`)**

### Priority Severity Definitions:
- **P0**: Incorrect or missing business behavior, data integrity issues, incorrect CRUD, permissions failures, or workflows that cannot be completed.
- **P1**: Missing fields, incorrect forms, wrong menu structure, broken navigation, incorrect actions, unwanted features, or significant layout mismatches.
- **P2**: Responsive issues, incorrect spacing, typography, tables, modal dimensions, icons, and visual differences.
- **P3**: Minor cosmetic discrepancies.

---

## 2. Discrepancy Inventory

| ID | Module / Area | Discrepancy Description | Priority | Reference Behavior | Local Behavior | Corrective Action Required | Status |
| :--- | :--- | :--- | :---: | :--- | :--- | :--- | :---: |
| **DISC-01** | Scope & Navigation | Unwanted "Calls" module introduced | **P0** | No "Calls to Actives" workflow exists in scope. Reference has Visits, Planned Visits, Agreements. | Local has `/calls/`, `CallActivity` model, views, templates, navigation entries. | Completely remove Calls module from navigation, URLs, views, models (via safe migration), templates, and tests. | **VERIFIED** |
| **DISC-02** | Global UI / FAB | Bottom-Left Floating + Button Behavior | **P0** | Floating button at `bottom: 16px; left: 16px;` opens a Material Bottom Sheet (`app-quick-add`) with 5 actions (Unplanned Visit, Sales Order, Return, Collection, Cancel). | Local had no global FAB; had only a page-specific button on planned visits opening a day modal. | Implement global FAB in `base.html` at `bottom: 16px; left: 16px;` that opens bottom sheet with all 5 verified actions. | **VERIFIED** |
| **DISC-03** | FAB / Workflow | Unplanned Visit Creation Modal | **P1** | Action 1 in FAB opens `app-visit-create-customer-selection` dialog to select a customer and launch unplanned visit. | Unplanned visit was only accessible via top button on `/visits/create/`. | Add customer selection modal triggered by FAB action 1 to initiate unplanned visits directly. | **VERIFIED** |
| **DISC-04** | Activities Navigation | Navigation menu icon and items | **P1** | Menu has `timeline` (الأنشطة), with subitems: `calendar_today` (خطة الزيارات), `room` (الزيارات), `handshake` (الاتفاقيات). | Submenu had 4 items including `المكالمات`, and used `directions_walk` for visits. | Clean submenu to exactly 3 items with exact icons and active route styling. | **VERIFIED** |
| **DISC-05** | Agreements | Bulk Status Change Action | **P1** | Selecting row(s) reveals `تغيير الحالة` (Change Status) button in action toolbar. | Local only had individual view links in table row, no toolbar status transition action. | Add table row selection and `تغيير الحالة` action in top action bar for New/Approved/Disapproved/Done. | **VERIFIED** |
| **DISC-06** | Agreements | Table Header Ordering & Aesthetics | **P2** | Columns in RTL order: `#`, `عميل`, `العنوان`, `النوع`, `المبلغ`, `التاريخ`, `المنشئ`, `الحالة`. | Local had extra summary metric badges on top and actions column. | Match exact reference column ordering, formatting, and responsive table wrapper. | **VERIFIED** |
| **DISC-07** | Visits | Table Header Ordering & Columns | **P1** | Table contains serial #, contact, date, start time, end time, area, specialty, classification, account type, success, duration, rep, status. | Local table had hardcoded status/approval badge styling and lacked some quick filter alignments. | Align table headers, status badge classes, and filter drawer labels with reference. | **VERIFIED** |
| **DISC-08** | Planned Visits | Ad-hoc FAB Conflict | **P1** | Page uses the global FAB. Day scheduling is handled via timeline add action or day cards. | Local `planned_visits_list.html` had a conflicting ad-hoc `fixed bottom-8 left-8` button. | Remove the conflicting ad-hoc FAB from `planned_visits_list.html` so the global FAB operates cleanly. | **VERIFIED** |
| **DISC-09** | Responsive Design | Viewport Parity (320px to 1920px) | **P2** | On mobile (<1024px), bottom nav is present; FAB stays at `bottom: 16px; left: 16px;` or floats neatly; modals fit screen. | On small viewports (320px - 390px), horizontal overflow could occur with wide tables or nested drawers. | Add responsive table scrolling, modal max-height with auto overflow, and ensure FAB does not obscure critical mobile nav elements. | **VERIFIED** |
| **DISC-10** | Permissions | Backend Role Authorization | **P0** | SuperAdmin/Managers have approve/disapprove rights; Reps can only draft agreements and conduct visits. | Some views lacked strict backend decorator checks, relying on template conditionals. | Enforce backend permissions on all action endpoints (`agreement_action`, `visit_action`, planning actions). | **VERIFIED** |

---

## 3. Page-by-Page Audit Details

### 3.1 Activities Submenu Navigation
- **Reference Menu Name & Hierarchy:**
  - Level 1: `الأنشطة` (Activities) — Icon: `timeline`
  - Level 2:
    1. `خطة الزيارات` (Planned Visits) — Icon: `calendar_today` — Destination: `/planned-visits`
    2. `الزيارات` (Visits) — Icon: `room` — Destination: `/visits`
    3. `الاتفاقيات` (Agreements) — Icon: `handshake` — Destination: `/agreements`
- **Local Menu Name & Hierarchy (Pre-Repair):**
    1. `خطة الزيارات` — `/planned-visits/`
    2. `الزيارات` — `/visits/`
    3. `المكالمات` (Unwanted Calls feature) — `/calls/`
    4. `الاتفاقيات` — `/agreements/`
- **Discrepancy:** Unwanted `المكالمات` item present. Incorrect icon `directions_walk` used for visits instead of `room`.
- **Corrective Action:** Remove `المكالمات` link entirely. Update visits icon to `room`. Keep clean 3-item hierarchy.

---

### 3.2 Bottom-Left Floating + Button (FAB) & Quick-Add Bottom Sheet
- **Reference Button Specification:**
  - **Tag:** `<button mat-fab color="primary" class="mdc-fab mat-mdc-fab mat-primary">`
  - **Container:** `<div class="quick-add" style="right: unset; left: 1rem; bottom: 1rem;">`
  - **Dimensions:** 56px × 56px (`border-radius: 50%`)
  - **Color:** `#27BEBE` (Brand Teal), white icon `add` (24px)
  - **Box Shadow:** `0 3px 5px -1px rgba(0,0,0,0.2), 0 6px 10px 0 rgba(0,0,0,0.14), 0 1px 18px 0 rgba(0,0,0,0.12)`
  - **Z-Index:** 1000
  - **Behavior on Click:** Opens Material Bottom Sheet (`app-quick-add`) with dark backdrop overlay (`rgba(0,0,0,0.4)`).
  - **Options in Bottom Sheet (in exact order):**
    1. `room` — **تسجيل زيارة خارج الخطة** (Opens customer selection dialog to start an unplanned visit)
    2. `shopping_cart` — **امر بيع جديد** (Navigates to new sales order creation)
    3. `refresh` — **مرتجع جديد** (Navigates to new return order creation)
    4. `receipt` — **تحصيل جديد** (Navigates to new collection creation)
    5. **الغاء** (Cancel button styled with `color-warn` / red, closes the bottom sheet)
- **Local Pre-Repair Behavior:**
  - No global FAB existed in `templates/layouts/base.html`.
  - A single ad-hoc FAB was placed on `planned_visits_list.html` hardcoded to open a date planning modal.
- **Corrective Action:**
  - Build the global FAB in `templates/layouts/base.html`.
  - Implement the sliding bottom sheet modal with all 5 verified actions.
  - Implement the "زيارة خارج الخطة" customer picker modal to seamlessly launch unplanned visit logging.
  - Remove the conflicting ad-hoc button from `planned_visits_list.html`.

---

### 3.3 Visits Page (`/visits`)
- **Reference Page Title:** `الزيارات`
- **Reference Action Bar:**
  - View toggles: `view_agenda` (cards) & `table_chart` (table)
  - Filter button with active filter counter badge
  - Export button: `تصدير البيانات` (Teal raised button)
  - Settings icon button
- **Reference Table Columns (RTL):**
  1. `زيارة` (Visit serial #)
  2. `جهة الاتصال` (Contact name & code)
  3. `التاريخ` (Date)
  4. `بدأ في` (Start time)
  5. `انتهى في` (End time)
  6. `المنطقة` (Area)
  7. `التخصص` (Specialty)
  8. `تصنيف العميل` (Classification)
  9. `نوع الاكونت` (Account type)
  10. `زيارة ناجحة` (Success status boolean icon)
  11. `المنتجات المشروحة` (Sample/detailed products)
  12. `المدة` (Duration formatted mm:ss)
  13. `المسؤول` (Owner/Rep)
  14. `الحالة` (Finished / Started / Planned)
  15. `زيارة مزدوجة` (Doubled boolean)
- **Reference Filters in Drawer:**
  - Search (`بحث`)
  - Selected filter set (`مجموعة الفلاتر المختارة`)
  - Date (`التاريخ`)
  - Owner / Rep (`المسئول`)
  - Status (`الحالة`)
  - Approval Status (`حالة الموافقة`)
- **Corrective Action:**
  - Ensure local table aligns with the 15 reference columns and clean formatting.
  - Maintain card view toggle (`?view=cards`) with beautiful cards.
  - Connect manager approval actions (`approve`, `disapprove`) with feedback notes.
  - Integrate with the FAB unplanned visit workflow.

---

### 3.4 Planned Visits Page (`/planned-visits`)
- **Reference Page Title:** `خطة الزيارات`
- **Reference Layout & Components:**
  - Header with back navigation, Rep selector (`المسئول`), and Date range (`المدة`).
  - Day-by-day accordion list (`الجمعة 16/10/2026`, `السبت 17/10/2026` ...).
  - Status badge per day (`غير مخططة`, `مكتملة`, etc.).
  - Side filter drawer ("تنقية العملاء"):
    - Filter set (`مجموعة الفلاتر المختارة`)
    - Show inactive (`إظهار الغير فعال`)
    - Main Area, Sub Area, Group
    - Customer Status, Organization, Type, Business Relation (`عميل`), Classification, Specialty, Account Type, AM/PM, KOL, Hide already planned (`اخفاء المعين في خطة`).
    - Buttons: `فلتر`, `اعادة تعيين`, `مسح`.
- **Local Pre-Repair Behavior:**
  - Implemented calendar and day accordions with customer drawer.
  - Had an ad-hoc bottom-left FAB that conflicted with the global FAB.
- **Corrective Action:**
  - Remove conflicting ad-hoc FAB.
  - Ensure contact drag/quick-add to day schedules seamlessly.
  - One-click execution from planned item to active visit (`is_planned=True`, `status='started'`).

---

### 3.5 Agreements Page (`/agreements`)
- **Reference Page Title:** `الاتفاقيات`
- **Reference Table Columns (RTL):**
  1. `#` (Serial number)
  2. `عميل` (Customer name & code)
  3. `العنوان` (Title)
  4. `النوع` (Type: Cash money, Conference, Devices, Gifts, RTD, Rx, Others)
  5. `المبلغ` (Amount in EGP)
  6. `التاريخ` (Date)
  7. `المنشئ` (Creator name & role)
  8. `الحالة` (Status: New, Approved, Disapproved, Done)
- **Reference Actions:**
  - Row selection activates `تغيير الحالة` (Change Status) in action toolbar.
  - `تصدير البيانات` (Export data).
- **Corrective Action:**
  - Add `تغيير الحالة` action in top action bar when agreement rows are selected.
  - Ensure status badge colors match reference:
    - New: Soft Blue (`#e0f2fe` / text `#0369a1`)
    - Approved: Soft Green (`#dcfce7` / text `#15803d`)
    - Disapproved: Soft Red (`#fee2e2` / text `#b91c1c`)
    - Done: Soft Slate/Gray (`#f1f5f9` / text `#475569`)
  - Retain quick create modal and edit views.

---

### 3.6 Unwanted "Calls" Cleanup Plan
- **Files to Remove/Clean:**
  1. `activities/urls.py`: Delete `calls/` and `calls/export/` routes.
  2. `activities/views.py`: Delete `calls_list` and `calls_export` view functions.
  3. `activities/models.py`: Remove `CallActivity` model; run safe `makemigrations activities` to drop `CallActivity` without affecting any other tables.
  4. `templates/activities/calls_list.html`: Remove unwanted template file.
  5. `templates/layouts/base.html`: Remove `calls_list` navigation link from sidebar.
  6. `activities/tests.py`: Remove `test_calls_module`.
  7. `test_e2e_workflows.py`: Clean up call testing steps.
  8. Documentation: Update reports and TODOs.
