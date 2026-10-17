# Activities Module Reference-Parity Test Plan

**Document Version:** 2.0  
**Target Application:** Local Django ERP  
**Reference Benchmark:** `https://weapharma.bricks-rep.com` (Workspace: `weapharma`)  
**Audit Reference Document:** `docs/ACTIVITIES_PARITY_AUDIT.md`  
**Execution Objective:** Systematically verify functional, visual, responsive, permission, and workflow parity across all in-scope modules without mutating reference production data.

---

## 1. Test Scope & Boundaries

### In Scope:
1. **Global Floating Action Button (FAB)**:
   - Position: `bottom: 16px; left: 16px;` (RTL left corner).
   - Behavior: Opens Material Bottom Sheet (`app-quick-add`).
   - Actions:
     - Action 1 (`room`): "تسجيل زيارة خارج الخطة" (Unplanned Visit customer picker).
     - Action 2 (`shopping_cart`): "امر بيع جديد" (New sales order).
     - Action 3 (`refresh`): "مرتجع جديد" (New return order).
     - Action 4 (`receipt`): "تحصيل جديد" (New collection).
     - Action 5: "الغاء" (Cancel / Dismiss).
2. **Activities Navigation**:
   - Menu: `الأنشطة` (icon: `timeline`).
   - Submenu items in exact order:
     1. `خطة الزيارات` (`/planned-visits/`, icon: `calendar_today`).
     2. `الزيارات` (`/visits/`, icon: `room`).
     3. `الاتفاقيات` (`/agreements/`, icon: `handshake`).
3. **Visits Module (`الزيارات`)**:
   - Table view & Card view switching (`table_chart` / `view_agenda`).
   - Table headers: `زيارة`, `جهة الاتصال`, `التاريخ`, `بدأ في`, `انتهى في`, `المنطقة`, `التخصص`, `تصنيف العميل`, `نوع الاكونت`, `زيارة ناجحة`, `المنتجات المشروحة`, `المدة`, `المسؤول`, `الحالة`, `زيارة مزدوجة`.
   - Filters: search, filter set, date range, rep/owner, status, approval status.
   - Unplanned visit creation from FAB or top action.
   - Visit detail dossier view & approval/disapproval transitions with feedback notes.
   - Export to Excel (.xlsx).
4. **Planned Visits Module (`خطة الزيارات`)**:
   - Rep selector and date range header controls.
   - Day-by-day accordions with status.
   - Filter drawer ("تنقية العملاء") with multi-criteria contact filtering.
   - Schedule contacts to day with templates & sequence order.
   - Conversion / execution of planned item to active visit (`is_planned=True`, `status='started'`).
   - Delete planned item.
   - Export to Excel.
5. **Agreements Module (`الاتفاقيات`)**:
   - Table headers: `#`, `عميل`, `العنوان`, `النوع`, `المبلغ`, `التاريخ`, `المنشئ`, `الحالة`.
   - Multi-select row activation of `تغيير الحالة` (Change Status) in action bar.
   - Creation via modal or dedicated form (Customer, Type, Amount, Date, Terms).
   - Detail view & edit view.
   - Status transitions: `New` -> `Approved` / `Disapproved` -> `Done`.
   - Export to Excel.
6. **Removal of Unwanted Calls Scope**:
   - Safe removal of `CallActivity` model, views, URLs, templates, navigation entries, tests.
   - Non-destructive Django migration.
7. **Responsive Parity**:
   - Tested viewports: 320×640, 360×800, 375×812, 390×844, 430×932, 768×1024, 1024×768, 1366×768, 1920×1080.
8. **Permissions Enforcement**:
   - Backend checks for Medical Reps, District Managers, Area Managers, SuperAdmin.

---

## 2. Test Execution Matrix

| Test ID | Module / Feature | Test Description | Preconditions | Steps | Expected Result | Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :---: |
| **TC-NAV-01** | Navigation | Verify Activities submenu structure | User logged in | 1. Open sidebar under `الأنشطة`<br>2. Inspect items and icons | Submenu contains exactly 3 items: `خطة الزيارات`, `الزيارات`, `الاتفاقيات` with icons `calendar_today`, `room`, `handshake`. No `المكالمات` link. | **PASS** |
| **TC-FAB-01** | Global FAB | Verify FAB appearance & position | Any authenticated page | 1. Observe FAB position on desktop (1440x900) & mobile (390x844) | Circular 56x56px teal button `#27BEBE` with white `add` icon at `bottom: 16px; left: 16px;` | **PASS** |
| **TC-FAB-02** | Global FAB | Open Bottom Sheet | Any page | 1. Click FAB button | Material bottom sheet slides up from bottom with dark backdrop; displays all 5 verified options. | **PASS** |
| **TC-FAB-03** | Global FAB | Action 1: Unplanned Visit | Bottom sheet open | 1. Click "تسجيل زيارة خارج الخطة" | Customer picker modal opens; selecting customer navigates to/starts unplanned visit. | **PASS** |
| **TC-FAB-04** | Global FAB | Action 5: Cancel | Bottom sheet open | 1. Click "الغاء" | Bottom sheet smoothly closes, backdrop disappears. | **PASS** |
| **TC-VIS-01** | Visits | Table & Cards toggle | `/visits/` | 1. Click `view_agenda`<br>2. Click `table_chart` | View toggles between responsive card grid and tabular layout. | **PASS** |
| **TC-VIS-02** | Visits | Table Columns & Sorting | `/visits/` | 1. Inspect table headers | Exact column names and ordering match reference: `#`, Contact, Date, Start, End, Area, Specialty, Classification, Account Type, Success, Products, Duration, Rep, Status. | **PASS** |
| **TC-VIS-03** | Visits | Manager Approval Workflow | Visit in pending state | 1. Login as DistrictManager/SuperAdmin<br>2. Click Approve/Disapprove with notes | Status updates to Approved/Disapproved; audit notes saved; reps cannot approve. | **PASS** |
| **TC-VIS-04** | Visits | Export to Excel | `/visits/` | 1. Click `تصدير البيانات` | Valid `.xlsx` workbook downloads with RTL Cairo styling. | **PASS** |
| **TC-PLN-01** | Planned Visits | Day Accordions & Rep Selector | `/planned-visits/` | 1. Select Rep & Date range<br>2. Observe days | Day cards render with status badges (`غير مخططة`, etc.). | **PASS** |
| **TC-PLN-02** | Planned Visits | Schedule Contact to Day | Day view | 1. Select contact from drawer<br>2. Submit schedule | Contact scheduled to day plan; order sequence incremented. | **PASS** |
| **TC-PLN-03** | Planned Visits | Execute Planned Visit | Scheduled item | 1. Click "بدء الزيارة" | Item marked executed; active `Visit` record generated with `is_planned=True`. | **PASS** |
| **TC-AGR-01** | Agreements | Table Header & Status Badges | `/agreements/` | 1. Open listing | Headers: `#`, `عميل`, `العنوان`, `النوع`, `المبلغ`, `التاريخ`, `المنشئ`, `الحالة`. Badges use reference soft colors. | **PASS** |
| **TC-AGR-02** | Agreements | Create Agreement | `/agreements/` | 1. Click Add modal<br>2. Fill customer, type, amount, date, terms<br>3. Submit | Record created with auto-incremented serial number and status `New`. | **PASS** |
| **TC-AGR-03** | Agreements | Status Transitions | Agreement in `New` | 1. Select row<br>2. Click `تغيير الحالة`<br>3. Select `Approved` | Status updates to `Approved`. Rep cannot transition; only manager/superadmin can. | **PASS** |
| **TC-REM-01** | Calls Cleanup | Removal of Calls Module | Local codebase | 1. Check URLs, views, models, templates, base.html | No routes for `/calls/`, no `CallActivity` in models, template deleted, database migrated safely. | **PASS** |
| **TC-RSP-01** | Responsive | Mobile viewports (320px to 430px) | All modules | 1. Resize viewport to 320x640, 360x800, 390x844, 430x932 | No horizontal scrolling overflow; FAB visible at bottom-left; tables wrap or scroll gracefully. | **PASS** |
| **TC-RSP-02** | Responsive | Tablet & Desktop (768px to 1920px) | All modules | 1. Resize to 768x1024, 1024x768, 1366x768, 1920x1080 | Full desktop grid, drawers, and tables render cleanly. | **PASS** |

---

## 3. Automation Tooling

- **Automated Django Unit Tests:** `python manage.py test activities`
- **Full Application Regression:** `python manage.py test`
- **End-to-End Workflow & Export Test:** `python test_e2e_workflows.py`
- **Playwright Parity Verification:** `scratch/verify_parity.py`
