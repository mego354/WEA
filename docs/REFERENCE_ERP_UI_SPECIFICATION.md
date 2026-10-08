# Reference ERP UI & Styling Specification

> **System**: Bricks Rep / WEA Pharma ERP  
> **Source Base URL**: `https://weapharma.bricks-rep.com/`  
> **Analysis Date**: October 2026  
> **Design Framework Origin**: Angular Material Design Components (MDC) with Enterprise RTL / Cairo Typography

---

## 1. Visual Language & Design Tokens

### 1.1 Color Palette

| Token Name | Hex Code | RGB | Role / Usage |
|---|---|---|---|
| **Primary Brand (Teal)** | `#27bebe` | `rgb(39, 190, 190)` | Primary buttons, active sidebar highlights, brand headers, key badges. |
| **Primary Brand Hover** | `#20a3a3` | `rgb(32, 163, 163)` | Hover state for primary buttons and interactive accents. |
| **Primary Brand Dark** | `#1a7f7f` | `rgb(26, 127, 127)` | Focus rings, active states, pressed button backgrounds. |
| **Background (Main App)** | `#f8fafc` | `rgb(248, 250, 252)` | Canvas background for main content area. |
| **Surface / Card Background**| `#ffffff` | `rgb(255, 255, 255)` | Data cards, tables, modals, drawer surfaces. |
| **Sidebar Background** | `#ffffff` | `rgb(255, 255, 255)` | Permanent left/right navigation drawer. |
| **Border Subtle** | `#e2e8f0` | `rgb(226, 232, 240)` | Card borders, table cell dividers, form input borders. |
| **Border Active / Focus** | `#27bebe` | `rgb(39, 190, 190)` | Form input focus ring, selected row outline. |
| **Text Primary** | `#0f172a` | `rgb(15, 23, 42)` | Page titles, table headers, primary data text. |
| **Text Secondary / Muted** | `#64748b` | `rgb(100, 116, 139)` | Subtitles, helper text, empty states, timestamp labels. |
| **Success Green** | `#10b981` | `rgb(16, 185, 129)` | Settled status, positive balances, active badges. |
| **Warning Orange / Amber** | `#f59e0b` | `rgb(245, 158, 11)` | Pending status, overdue alerts, hold state. |
| **Danger Red** | `#ef4444` | `rgb(239, 68, 68)` | Rejected status, cancellations, delete buttons, debt overdue. |
| **Info Blue** | `#3b82f6` | `rgb(59, 130, 246)` | Approved status, Picked status, informational toasts. |

### 1.2 Typography & Font Hierarchy
- **Font Family**: `'Cairo', system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif`
- **Fallback**: Cairo is loaded via Google Fonts; supports both Arabic and English seamlessly.
- **Font Weights**:
  - `400` (Regular): Table cells, form values, body paragraphs.
  - `500` (Medium): Form labels, table headers, button labels, badge texts.
  - `600` (Semi-bold): Section headers, metric card numbers, modal titles.
  - `700` (Bold): Main page headers (`h1`), grand totals, company branding.
- **Scale**:
  - Page Title: `22px` (`1.375rem`), weight `700`
  - Card / Section Header: `16px` (`1rem`), weight `600`
  - Table Header (`th`): `13px` (`0.8125rem`), weight `600`, uppercase/subtle color `#475569`
  - Table Cell (`td`): `14px` (`0.875rem`), weight `400`, color `#0f172a`
  - Micro / Badge Text: `12px` (`0.75rem`), weight `500`

---

## 2. Layout & Shell Architecture

### 2.1 Overall Layout Dimensions
- **Sidebar**:
  - Width: `280px` – `300px` (Computed: `301px` in reference system).
  - Position: Fixed on the side (Right side in Arabic RTL, Left side in LTR).
  - Background: Pure White (`#ffffff`) with subtle 1px border (`#e2e8f0`) or soft elevation shadow (`0 1px 3px rgba(0,0,0,0.05)`).
- **Top Header Bar**:
  - Height: `64px`.
  - Contents:
    - Sidebar toggle burger button (mobile/desktop collapse).
    - Page title or Breadcrumb trail.
    - Right/Left utilities: Unread notifications bell with counter pill (`105`), User avatar with dropdown, Language switcher (`عربي` / `EN`), Logout icon.
- **Main Content Container**:
  - Background: `#f8fafc`.
  - Padding: `24px` horizontal and vertical.
  - Max-width: Fluid container with responsive gutter (`px-4 sm:px-6 lg:px-8`).

---

## 3. Component Design Specifications

### 3.1 Primary Buttons
- **Style**: Raised pill or rounded rectangle (`rounded-lg`, border-radius `8px`).
- **Background**: `#27bebe` (Teal), text `#ffffff`.
- **Hover**: `#20a3a3` with subtle elevation increase.
- **Icon + Label**: Left/Right Material symbol icon + Arabic label (e.g., `+ أمر مشتريات جديد`).
- **Padding**: `8px 16px` (`py-2 px-4`).
- **Font Size**: `14px`, weight `500`.

### 3.2 Secondary / Outlined Buttons
- **Style**: Transparent background, 1px solid border `#cbd5e1`.
- **Text**: `#334155`.
- **Hover**: Background `#f1f5f9`.
- **Usage**: `تصدير البيانات` (Export Excel), `اطبع` (Print), `إلغاء` (Cancel).

### 3.3 Status Badges (Pills)
- Rounded full pill (`rounded-full`, padding `4px 12px`, text size `12px`, weight `600`):
  - **Settled / مكتمل**: Background `#ecfdf5`, Text `#059669`, Border `#a7f3d0`
  - **Picked / تم الاستلام**: Background `#eff6ff`, Text `#2563eb`, Border `#bfdbfe`
  - **Approved / معتمد**: Background `#f0fdf4`, Text `#16a34a`, Border `#bbf7d0`
  - **Pending / معلق**: Background `#fffbeb`, Text `#d97706`, Border `#fde68a`
  - **Rejected / مرفوض**: Background `#fef2f2`, Text `#dc2626`, Border `#fecaca`
  - **Split / مقسم**: Background `#f5f3ff`, Text `#7c3aed`, Border `#ddd6fe`

### 3.4 Data Tables (Core ERP Pattern)
- **Container**: Elevated white card (`bg-white rounded-xl shadow-sm border border-slate-200 overflow-hidden`).
- **Header Row (`th`)**:
  - Background: `#f8fafc`.
  - Border bottom: `1px solid #e2e8f0`.
  - Text color: `#475569`.
  - Font size: `13px`, weight `600`.
  - Padding: `12px 16px`.
  - Text align: Right (for Arabic RTL).
- **Body Row (`td`)**:
  - Background: `#ffffff`, alternate hover `#f8fafc`.
  - Border bottom: `1px solid #f1f5f9`.
  - Padding: `14px 16px`.
  - Font size: `14px`.
  - Action column: Three-dots icon dropdown (`more_vert`) or direct view icon.
- **Empty State**:
  - Illustrated or icon container (`inbox` icon) with message: "لا توجد بيانات متاحة" (No data available).
- **Pagination Footer**:
  - Rows per page dropdown (`10`, `25`, `50`, `100`).
  - Page range indicator (e.g. `1 - 25 من 181`).
  - Next / Previous chevron buttons.

### 3.5 Filter Drawer / Bar
- Collapsible drawer or inline expander:
  - Date Range Picker (From / To).
  - Search input with clear icon.
  - Multi-select dropdowns for Status, Supplier/Customer, Warehouse, Area.
  - "تطبيق الفلتر" (Apply Filter) & "إعادة ضبط" (Reset) buttons.

### 3.6 Form Controls & Inputs
- **Inputs & Selects**:
  - Border: `1px solid #cbd5e1`, rounded `8px`.
  - Background: `#ffffff`.
  - Focus Ring: `2px solid #27bebe` with zero outline offset.
  - Padding: `10px 14px`.
  - Labels: Clean floating or top-aligned labels, font size `13px`, color `#475569`, weight `500`.
  - Required marker: Red asterisk (`*`).

### 3.7 Modals & Slide-over Panels
- Backdrop: `rgba(15, 23, 42, 0.45)` with backdrop blur `2px`.
- Card: `rounded-2xl shadow-2xl bg-white`.
- Header: Title, subtitle, close icon button (`close`).
- Footer: Actions pinned to bottom with border-top `1px solid #e2e8f0`.
