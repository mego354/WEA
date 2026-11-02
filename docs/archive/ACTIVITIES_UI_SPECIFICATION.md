# Activities Module UI & Styling Specification

This document specifies the exact visual design, color tokens, layout geometry, typography, responsive behavior, and UI interactions for the Activities module.

---

## 1. Design System Tokens & Brand Standards

| Token | Value | Usage |
| :--- | :--- | :--- |
| **Brand Primary Teal** | `#27bebe` / `rgb(39, 190, 190)` | Active menu links, primary action buttons, focused inputs, table highlights |
| **Brand Hover Teal** | `#1fa8a8` | Button hover states, interactive card hover |
| **Brand Tint Teal** | `#e6f8f8` | Active row highlight, soft badge backgrounds, drawer headers |
| **Dark Slate Header** | `#0f172a` / `#1e293b` | Main headings, modal headers, primary table headers |
| **Body Background** | `#f8fafc` | Global canvas background |
| **Card / Surface** | `#ffffff` | Accordion cards, table surface, modals, drawers |
| **Border Gray** | `#e2e8f0` | Card borders, table cell dividers, input borders |
| **Typography** | `'Cairo', sans-serif` | Clean, modern Arabic typography with correct RTL metrics |

---

## 2. Status Badge Color Matrix

| Module | Status Key | Label (Arabic) | Background | Text Color | Border |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Agreements** | `new` | جديد | `#e0f2fe` | `#0284c7` | `#bae6fd` |
| **Agreements** | `approved` | معتمد | `#dcfce7` | `#16a34a` | `#bbf7d0` |
| **Agreements** | `disapproved` | مرفوض | `#fee2e2` | `#dc2626` | `#fecaca` |
| **Agreements** | `done` | منجز | `#f1f5f9` | `#475569` | `#cbd5e1` |
| **Visits** | `planned` | مخطط لها | `#eff6ff` | `#2563eb` | `#bfdbfe` |
| **Visits** | `started` | جارية الآن | `#fef9c3` | `#ca8a04` | `#fef08a` |
| **Visits** | `finished` | منتهية | `#f0fdf4` | `#15803d` | `#bbf7d0` |
| **Visits Approval** | `pending` | قيد الاعتماد | `#fef3c7` | `#d97706` | `#fde68a` |
| **Visits Approval** | `approved` | معتمدة | `#dcfce7` | `#16a34a` | `#bbf7d0` |
| **Visits Approval** | `disapproved` | مرفوضة | `#fee2e2` | `#dc2626` | `#fecaca` |

---

## 3. Page Layouts & Component Architecture

### 3.1 Planned Visits (`خطة الزيارات`)
- **Structure:**
  - **Header Row:** Title (`خطة الزيارات`), Assignee selector (`المسئول`), Date range picker, Action menu.
  - **Split Grid Layout:**
    - **Filter Drawer (Right side in RTL):** Width 300px, contains customer filters (`تنقية العملاء`), active filter tags, Reset and Apply buttons.
    - **Timeline Content (Left side in RTL):** Responsive day cards list.
  - **Day Accordion Card:**
    - Date Header: Day of week + Date (e.g. `الخميس 15/10/2026`).
    - Status Badge: `غير مخططة` if empty, `N زيارات مخططة` if populated.
    - Visits List: Ordered draggable or sequenced visit items showing Contact Code, Contact Name, Specialty, Action buttons (Execute visit, remove).
    - Add Visit Button: `+ إضافة عميل لليوم`.
  - **Floating Action Button (FAB):** Bottom-left fixed circle `+` button in `#27bebe`.

### 3.2 Visits List (`الزيارات`)
- **Structure:**
  - **Header Bar:** Title `الزيارات`, View toggle (Grid / Table), Export button (`تصدير البيانات`), Filter button with badge (`2`), Column Settings.
  - **Filter Drawer:** Sliding right-hand drawer with quick filters: Search, Date range, Rep, Status, Approval Status.
  - **Data Table:**
    - Bounded table with sticky header (`top: 0`, `z-index: 10`).
    - Alternating row styling or clean white rows with hover tint (`#e6f8f8`).
    - Action dropdown (`more_vert`): View Details, Approve, Disapprove.
  - **Mobile Responsive Layout:**
    - Table switches to stacked cards on viewport `< 768px` displaying Contact Name, Rep, Date, Duration, and Badges with full touch targets >= 44px.

### 3.3 Agreements (`الاتفاقيات`)
- **Structure:**
  - **Metrics Bar:** Total agreements count, Total financial commitments sum (`المجموع: XXX,XXX ج.م`).
  - **Header Action Bar:** Search box, Filter button, Excel Export button, `+ إضافة اتفاقية` primary button.
  - **Agreements Table:** 8 columns matching reference ERP exactly.
  - **Create / Edit Modal:**
    - Modal width: `max-w-2xl`, rounded corners, teal header.
    - Fields: Customer autocomplete, Title, Agreement Type dropdown, Amount input, Date picker, Rich text description.
  - **Detail View:** Dossier view showing full agreement parameters, status history, approval actions.
