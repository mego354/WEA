# Activities Module Page & Submenu Inventory

This inventory documents all discovered pages, submenus, navigation paths, actions, and UI components under the **Activities (`الأنشطة`)** tab in the reference ERP (`https://weapharma.bricks-rep.com`).

---

## 1. Activities Tab Hierarchy

The Activities navigation item in the main sidebar contains 4 submenus:

| Submenu Label (Arabic) | Label (English) | URL Path | Description & Purpose |
| :--- | :--- | :--- | :--- |
| **خطة الزيارات** | Planned Visits | `/planned-visits` | Day-by-day visit planner, calendar view, representative assignment, customer drawer & scheduling. |
| **الزيارات** | Visits | `/visits` | Log of all executed and planned visits, check-in/out tracking, questionnaires, approval workflow. |
| **المكالمات** | Calls | `/calls` | Telesales / phone call activity log, call questionnaires, customer calls. |
| **الاتفاقيات** | Agreements | `/agreements` | Customer financial & commercial agreements (Cash money, Devices, RTD, Rx, Conferences, Gifts, Others). |

---

## 2. Planned Visits (`خطة الزيارات`) — Detailed Inventory

### 2.1 Route & Layout
- **URL:** `/planned-visits`
- **Page Title:** `خطة الزيارات`
- **Layout Architecture:**
  - **Top Bar:**
    - Back button (`arrow_back`)
    - Assignee Dropdown (`المسئول *`): select medical representative (e.g., `Dr.wael Atta (CEO)`, `Mohamed Elbadry (Imbaba)`, etc.)
    - Date Range Picker (`المدة`): default interval (e.g., current month or 15 days, e.g., `15/10/2026 - 31/10/2026`)
    - Menu button (`more_vert`)
  - **Left Sidebar Drawer (`تنقية العملاء` - Customer Filtering):**
    - Filter Sets dropdown (`مجموعة الفلاتر المختارة`)
    - Toggle inactive accounts (`إظهار الغير فعال`: لا / نعم)
    - Main Area (`المنطقة الرئيسية`) dropdown
    - Sub-area (`المنطقة`) dropdown
    - Group (`المجموعة`) dropdown
    - Customer Status (`حالة العميل`) dropdown
    - Organization (`المؤسسة`)
    - Contact Type (`النوع`: Individual / Facility)
    - Business Relation (`علاقة العمل`: Customer)
    - Category / Rank (`تصنيف العميل`: A, B, C)
    - Specialty (`التخصص`: Pediatrics, IM, Ortho, etc.)
    - Action buttons: `فلتر` (Apply Filter), `اعادة تعيين` (Reset), `مسح` (Clear)
  - **Main Content Area (Day Cards Timeline):**
    - Day Accordion Cards for each date in the selected range (e.g. `الخميس 15/10/2026`, `الجمعة 16/10/2026`, ...)
    - Day Status Badge: `غير مخططة` (Unplanned - gray badge) if no visits scheduled; count badge `N زيارات` when scheduled.
    - Day Plan Actions: Add visit to day, Reorder visits, View visits.
    - Visit Card inside Day: Contact code & name, Specialty, Area, Status (`مخططة` / `منتهية`), Actions.
  - **Floating Action Button (FAB):**
    - `+` (Add Planned Visit Modal): Select Date, Assignee, Contact, Template, Order.

---

## 3. Visits (`الزيارات`) — Detailed Inventory

### 3.1 Route & Layout
- **URL:** `/visits`
- **Page Title:** `الزيارات`
- **Header Controls:**
  - View switchers: `view_agenda` (Card / Timeline view) and `table_chart` (Data table view).
  - Export Button: `تصدير البيانات` (Excel export).
  - Filter toggle button: `filter_list` (shows active filter count badge).
  - Column Settings: `settings`.
- **Search & Filters Drawer/Bar:**
  - Search input: `بحث search` (Quick search by contact name, code, rep name).
  - Saved Filter Groups: `مجموعة الفلاتر المختارة`.
  - Date Range: `التاريخ` (From - To).
  - Assignee: `المسئول` (User dropdown).
  - Status: `الحالة` (`مخططة` Planned, `بدأت` Started, `منتهية` Finished).
  - Approval Status: `حالة الموافقة` (`معلقة` Pending, `معتمدة` Approved, `مرفوضة` Disapproved).
- **Table Columns (Comprehensive Header Inventory):**
  1. `زيارة` (Serial #)
  2. `جهة الاتصال` (Customer code & name)
  3. `التاريخ` (Visit date)
  4. `بدأ في` (Started at timestamp)
  5. `انتهى في` (Ended at timestamp)
  6. `المدة` (Duration in min / sec)
  7. `المسؤول` (Medical rep)
  8. `المنطقة` (Subarea / Area)
  9. `التخصص` (Doctor / Contact specialty)
  10. `نوع الاكونت` (Account type: Clinic, Pharmacy, Drug Store, etc.)
  11. `تصنيف العميل` (Class: A, B, C)
  12. `زيارة ناجحة` (Is Successful: True/False)
  13. `زيارة مزدوجة` (Double visit with manager: True/False)
  14. `الحالة` (Status badge)
  15. `حالة الموافقة` (Approval status badge)
  16. `المنتجات المشروحة` (Samples / Products detailed)
  17. `إجراءات` (Row actions: View Details, Approve, Disapprove).

### 3.2 Visit Details & Dossier Page / Modal
- **URL:** `/visits/<id>/`
- **Tabs / Sections:**
  - **Overview:** Serial, Date, Status, Rep, Contact, Address, Mode (`checkin_checkout`), Duration, Geofence / Location verification.
  - **Questionnaire & Feedback:** Answers to template questions (narrative, single choice, true/false).
  - **Samples (`العينات`):** Products sampled, warehouse batch, quantities distributed.
  - **Expenses (`المصروفات`):** Associated visit expenses and amounts.
  - **Approval Actions:** Manager Approve / Disapprove buttons with note input.

---

## 4. Agreements (`الاتفاقيات`) — Detailed Inventory

### 4.1 Route & Layout
- **URL:** `/agreements`
- **Page Title:** `الاتفاقيات`
- **Header Controls:**
  - Total records count and aggregate amount (e.g., `المجموع: XXX,XXX ج.م`).
  - `تصدير البيانات` (Export Excel data).
  - `+ إضافة اتفاقية` (Create new agreement button).
  - Filter toggle button: `filter_list`.
  - Pagination controls: `First page`, `Previous page`, `Next page`, `Last page`.
- **Search & Filters Drawer/Bar:**
  - Search input: `بحث search` (Searches title, serial number, contact name).
  - Saved Filter Groups: `مجموعة الفلاتر المختارة`.
  - Date range: `التاريخ` (Agreement date from - to).
  - Created date range: `انشئ فى`.
  - Inactive toggle: `إظهار الغير فعال` (Yes / No).
  - Assignee: `مسئول جهة الاتصال` (Dropdown of representatives/managers).
  - Agreement Type: `النوع` (Conference, Cash money, Devices, Gifts, RTD, Rx, Others).
  - Status: `الحالة` (New, Approved, Disapproved, Done).
- **Table Columns (RTL):**
  1. `#` (Serial Number: `#222`)
  2. `عميل` (Customer: `[Code] Name`)
  3. `العنوان` (Agreement title/subject)
  4. `النوع` (Agreement Type: Cash Money, Devices, etc.)
  5. `المبلغ` (Amount: e.g. `2000`)
  6. `التاريخ` (Date: `DD/MM/YYYY`)
  7. `المنشئ` (Created by: Name & Role)
  8. `الحالة` (Status badge: New, Approved, Disapproved, Done)
  9. `إجراءات` (Actions menu: View, Edit, Approve, Disapprove, Mark as Done, Delete).

### 4.2 Agreement Create & Edit Modal / Page
- **Fields:**
  - Customer (`عميل *`): Autocomplete / searchable dropdown from `contacts.Contact`.
  - Title (`العنوان *`): Text input.
  - Type (`النوع *`): Dropdown from `AgreementType`.
  - Amount (`المبلغ *`): Decimal numeric input with currency symbol.
  - Date (`التاريخ *`): Date picker.
  - Description / Terms (`الوصف`): Rich text / textarea editor for agreement terms.
  - Attachments: Upload file capability.

---

## 5. Calls (`المكالمات`) — Inventory
- **URL:** `/calls`
- **Purpose:** Telesales / remote call activities.
- **Fields:** Rep, Customer, Call timestamp, Duration, Call outcome/template, Notes.
