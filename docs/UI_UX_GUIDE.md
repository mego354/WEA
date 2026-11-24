# UI & UX Guidelines

This document outlines the user interface specifications, front-end architecture, and interaction patterns for WEA Pharma ERP.

---

## 1. Core Design Philosophy

- **Product Owner UI Preference**: Strict preference for simple, clean, compact UI without verbose notes, paragraphs, or oversized components. Present data concisely using icons and simple text. Avoid full-page refreshes on drawer/filter operations.
- **Enterprise Density**: High information density suited for operational workflows, pharmaceutical sales representatives, and warehouse operators.
- **Arabic RTL Native**: First-class Right-to-Left layout (`dir="rtl"`, `lang="ar"`), using the modern **Cairo** typeface.
- **Brand Identity**: Primary teal brand color (`#27bebe` / `brand.500`), paired with neutral grays (`slate`/`zinc`) and semantic status tokens.

---

## 2. Color Palette & Semantic Tokens

| Token | Hex / Class | Usage |
|---|---|---|
| `brand-500` | `#27bebe` | Primary brand accent, primary CTA buttons, active navigation states. |
| `brand-600` | `#209e9e` | Button hover and active states. |
| `brand-50` | `#f0fbfb` | Active navigation highlights, subtle card accents. |
| `success` | `emerald-600` | Approved status, completed visits, stock additions, positive balances. |
| `warning` | `amber-500` | Pending approval, exception requested, distance warning, low stock. |
| `danger` | `rose-600` | Rejected, disapproved, out of stock, cancelled orders. |
| `neutral-surface` | `bg-white` / `bg-slate-50` | Table rows, card containers, dropdown menus. |

---

## 3. Responsive Navigation Architecture

```text
[ Desktop View (lg+) ]
┌───────────────────────────┬──────────────────────────────────────────┐
│ Main Content Area         │ Sticky Right Sidebar                     │
│ (Tables, KPI Cards, Forms)│ - Navigation links with Material Symbols │
│                           │ - User profile & quick branch switcher   │
└───────────────────────────┴──────────────────────────────────────────┘

[ Mobile View (< lg) ]
┌──────────────────────────────────────────────────────────────────────┐
│ Top Bar: Brand Logo + Area Selector + Hamburger Drawer Trigger       │
├──────────────────────────────────────────────────────────────────────┤
│ Scrollable Content Area                                              │
├──────────────────────────────────────────────────────────────────────┤
│ Bottom Navigation Bar: Home | Visits | Orders | Clients | Profile    │
│ Floating Action Button (FAB): Quick Creation Sheet                   │
└──────────────────────────────────────────────────────────────────────┘
```

1. **Desktop**: Fixed right sidebar with collapsible sections, top breadcrumbs, and user menu.
   - **Deterministic Active Navigation (`resolve_active_nav` + `initSidebarActiveState`)**: Server-side URL resolution in `master_data/templatetags/erp_tags.py` (`resolve_active_nav` mapping URL names across aliases plus ordered longest-prefix fallback) stamps `data-erp-active-link="1"` strictly on the matching route inside `#sidebar-nav-scroll` (preventing substring collisions such as `/settings/agreements/` vs `/agreements/` or `/settings/visits/templates/` vs `/visits/`). Client-side `initSidebarActiveState()` collapses all unrelated sections, highlights the active item (`bg-teal-50 text-[#27bebe] font-bold border-r-2 border-[#27bebe]`), expands ancestor submenus recursively (`rotate-180`), highlights parent category buttons, and centers the active link inside `#sidebar-nav-scroll` via `scrollSidebarActiveToCenter`.
   - **Accordion Focus**: Opening a menu section collapses unrelated sibling sections so the sidebar stays compact and focused.
2. **Mobile**:
   - Slide-over drawer for secondary links and settings (re-runs `initSidebarActiveState()` and auto-centers the active item in `#sidebar-nav-scroll` on open).
   - Fixed bottom navigation bar for high-frequency actions (Home, Visits, Orders, Clients, Profile) aligned with `active_nav`.
   - Bottom-right Floating Action Button (FAB) triggering a bottom sheet for rapid creation (New Visit, New Order, New Client).
   - **Mobile Topbar Refresh Button**: Fixed in the header (`lg:hidden min-w-[44px] min-h-[44px]`) next to notifications for instant page reloading on mobile touch devices.

---

## 4. Drawers & Filter Preservation

### Client Filter Drawer & Shared Area/Brick Multiselect
- **Centralized Global Loader (`window.ERPLoader`)**: Renders a centered full-viewport spinner overlay covering underlying content during full-page navigations and async fetch/filter/bulk operations, with `try/finally` error cleanup and bfcache `pageshow` recovery. Fast keystroke typeaheads opt out via `X-Skip-Global-Loader`.
- **Shared Area/Brick Multiselect (`area_brick_multiselect.html` / `area_brick_multiselect.js`)**: Shared across Bulk Planned Visits, Visits List, Agreements List, Sales Orders List, and Contacts List. Opens immediately on focus/click to display authorized options, caches responses in memory with `AbortController` cancellation, preserves multi-selection chips, and clears orphaned bricks when a parent area is removed.
- **Shared Generic Choice Multiselect (`choice_multiselect.html` / `choice_multiselect.js` & `account_type_multiselect.html` / `account_type_multiselect.js`)**: Standardized multi-select chip dropdown with Arabic-normalized search (`matchesNormalizedArabic`), keyboard navigation, and individual/clear-all chip removal.
- **Standardized Backend Filter Parsing (`master_data/filter_utils.py`) & Chip Removal (`url_remove_param`)**: `parse_multi_int`, `parse_multi_str`, `parse_single_int`, and `resolve_scoped_area_brick_filters` enforce scope validation and prevent malformed-ID errors; `url_remove_param` supports `value=` for removing individual multi-select chips in `active_filters.html`.
- **Display All & Select All Results**: Supports loading all matching clients in one action (`show_all=1`), selecting all matching filtered results across pages (`action=select_all_ids`), and filtering by `contact_status` (`Customer` / `Lead`) inside the `/planned-visits/` drawer with clear full-selection vs individual-count indicators.
- **State & Selection Persistence across Reload**:
  - Drawer open/closed state (`wea_planned_drawer_open`), selected contact IDs (`wea_planned_selected_ids`), and scheduled date (`wea_planned_bulk_date`) are persisted in `sessionStorage`.
  - Upon successful plan submission, cached session storage entries are cleanly purged.
- **Pagination (`smart_page_range`)**: Compact pagination showing current, neighbor, first, last, and `'...'` ellipsis.
- **List Statistics Cards**: Always computed from the active filtered, scoped queryset on every list page (`contacts`, `visits`, `agreements`, `sales`, `purchases`, `inventory`, `treasury`, `catalog`, `accounts`).

---

## 5. Table Standards & Column Customization

1. **Column Manager (`table_column_manager.js`)**:
   - Interactive column visibility picker (`#col-picker-dropdown` via `templates/components/table_column_picker.html`) enabled across all operational list views, reports, and performance tables.
   - Desktop/tablet renders icon + `"الأعمدة"` label; mobile renders compact icon-only button with RTL viewport-collision flipping (`left`/`right` auto-flip) to prevent clipping.
   - Required columns support both `data-required="true"` and `data-col-required="true"`; column visibility toggles use inline `style.display='none'` so responsive Tailwind classes are preserved.
   - Preferences saved in browser `localStorage` keyed by table ID / route.
2. **List Smart Search (`static/js/list_smart_search.js`)**:
   - Automatically attaches debounced (`220ms`) scoped suggestions via `GET /api/list-suggestions/?module=<module>&q=<query>` to any list search `<input data-smart-search-module="...">`.
3. **Excel Exports (`master_data/excel_utils.py`)**:
   - Unified `.xlsx` exports include dynamic `CompanyProfile` branding headers (company name, contact info, report title, export timestamp/user) and respect active list filters and user data scope.
2. **Horizontal Scrolling & Pinning**:
   - Tables wrap in `overflow-x-auto`.
   - First column (checkbox/ID) and trailing action column (buttons) can be pinned with sticky positioning.
   - Cells use `whitespace-nowrap` with compact vertical padding (`py-2.5 px-3`).

---

## 6. Forms & Inline Modals

- **Unified Deletion Confirmation Modal (`confirm_delete_modal.html`)**:
  - Global reusable confirmation popup modeled after the Catalog Categories standard.
  - Replaces all inconsistent native browser `confirm(...)` dialogs across the application.
  - Displays red warning icon, item identifier, irreversible action warning, optional related-records alert, and double-submit protection.
  - Supports non-destructive reversals (e.g. treasury reversals, purchase cancellations) with customizable button colors and icons via `showConfirmDeleteModal({ ... })`.
- **Context-Preserving Modals**: Quick actions (e.g. Set Visit Time, Distance Exception Reason, Void Order) open compact centered modals without navigating away from the list or detail view.
- **Client-First Template Cascading**: In visit forms, selecting the client automatically queries eligible templates via AJAX, preventing selection of incompatible templates.
- **Territorial Cascading Dropdowns**: Selecting a Governorate dynamically updates the Brick/Subarea selector with child areas.
- **Submit Button State Management**: Form submit buttons automatically disable and display a loading spinner upon submission to prevent accidental duplicate requests.
- **Reusable Smart Search Combobox (`static/js/smart_select.js` / `window.ERPSmartSelect`)**:
  - Automatically enhances `<select data-smart-select="true">` across Sales, Purchases, and Treasury create/edit forms, list filter bars/drawers, and modals.
  - Supports instant client-side Arabic-normalized filtering (`window.normalizeArabicSearch`, `window.matchesNormalizedArabic`: `أ/إ/آ/ا`, `ة/ه`, `ى/ي`, diacritics stripped, collapsed spaces) and optional debounced (`220ms`) remote endpoint lookups (`data-search-url`) with `AbortController`, in-memory query cache, and `X-Skip-Global-Loader: 1`.
  - Preserves native `<select>` `name`, `value`, `required` validation (without focusability errors), `change` events (including filter auto-submit and cascading order dropdowns via `MutationObserver` and `window.ERPSmartSelect.refresh(...)`), keyboard navigation (`ArrowDown`/`ArrowUp`/`Enter`/`Escape`), and viewport collision flipping for desktop and mobile RTL screens.


- **Unified Viewport-Safe Row Action Menu (`static/js/row_action_menu.js`, `templates/components/row_action_menu.html`)**:
  - Replaces inline multi-button clusters and native `confirm(...)` dialogs in list tables with a fixed-position (`z-[110]`) RTL `more_vert` dropdown portal so menus are never clipped inside `overflow-x-auto` tables. Applies `preventScroll: true` focus, a 150ms post-open scroll grace guard so mobile/touch scroll jitter never dismisses freshly opened menus, and layers `#global-confirm-delete-modal` at `z-[120]` above the portal.
- **Unified Questionnaire Renderer (`templates/activities/_questionnaire_field.html`)**:
  - Shared mobile/desktop partial rendering all template question types—including searchable `suggested_products` widgets with count badges and `<question>_present` empty-submit markers—uniformly across template preview, active visit completion, and the finished-visit Edit Answers modal.
- **Unified Detail Page Action Menu (`templates/components/detail_action_menu.html`)**:
  - Keeps primary workflow state-transition buttons visible in detail headers while grouping secondary actions (PDF export, print, edit, cancel, delete) inside a `more_vert` dropdown.
- **Unified Transaction Attachments (`attachments_uploader.html`, `attachments_gallery.html`, `attachments_modal.html`)**:
  - Supports multi-file image/PDF uploads on create/edit forms, inline galleries on detail pages, and a shared modal (`openAttachmentsModal`) for list-only records (`Collection`, `VendorPayment`, `VaultTransaction`).
- **Standardized Contacts-Style Filter Drawer Toggle (`templates/components/filter_drawer_toggle.html`, `.erp-filter-drawer`, `toggleErpFilterDrawer`)**:
  - All operational list pages use the compact `filter_list` drawer toggle button with a top-right circular active-filter count badge (`data-filter-badge`) and a left-docked slide-out `.erp-filter-drawer` (`320px`, `max-w-[92vw]`) featuring a `"فلتر"` header badge, `arrow_forward` close button, backdrop click dismissal, and `Escape` key handler.
- **Unified Compact Date Range Filter (`templates/components/date_range_filter.html`, `static/js/date_range_filter.js`, `master_data/date_filter_utils.py`)**:
  - Placed inside the standardized Filter Drawer (or report filter bar) with a collapsible summary header (`data-drf-toggle`) and quick preset pills (`all_time`, `today`, `yesterday`, `last_7_days`, `last_30_days`, `this_month`, `last_month`, `quarter`, `this_year`/`year`, `custom`).
  - Vertical `من تاريخ` and `إلى تاريخ` date inputs (`data-drf-custom-box`) are revealed **only** when `فترة مخصصة` (`custom`) is selected, preventing horizontal overflow and unexpected form auto-submission inside drawers.
  - Transactional list pages default to `all_time`; Reports, Performance views, and `/home/` default to `this_month`.
- **Unified Responsive Tables Across Desktop & Mobile**:
  - All list views that render tables (`sales`, `purchases`, `sales_returns`, `purchase_returns`, `visits`, `contacts` table mode, `audit_logs`, accounting ledgers, inventory, treasury, and financial/analytical reports) remain scrollable `overflow-x-auto` tables on mobile (`< 768px`) with the exact same columns, information, column visibility picker (`table_column_manager.js`), and viewport-safe `more_vert` (`openRowActionMenu`) actions — never swapping to truncated mobile-only card layouts (`view=cards` is removed from `visits`) or hiding columns via `hidden md:table-cell`.
- **Global Non-Blocking RTL Toast Stack (`templates/components/toast_container.html`, `window.ERPToast`)**:
  - Replaces native blocking browser `alert(...)` calls with accessible RTL toast notifications (`ERPToast.error`, `ERPToast.warning`, `ERPToast.success`, `ERPToast.info`).
- **Arabic Terminology & Currency Standardization**:
  - Clean Arabic page titles and headings without redundant English parentheticals or duplicate `- WEA Pharma ERP` / `- Bricks Rep` suffixes (`base.html` appends `- WEA Pharma ERP` centrally).
  - Currency is standardized to `ج.م` across all views, cards, tables, charts, and print templates. Standard technical abbreviations (`PDF`, `Excel`, `SKU`, `GPS`, `R2`) are preserved.
- **Bottom-Only Form Primary Submit Actions**:
  - Create/edit forms and active visit completion forms (`visit_detail.html`) place primary submit actions at the bottom below all questions and fields across desktop, tablet, and mobile (with `save_draft` and unanswered-question client-side notices removed).
- **Inventory Memo Form Consistency (`templates/inventory/memo_create.html`)**:
  - Uses the unified white `ملخص الإجماليات` breakdown card, responsive desktop-table / mobile-card item rows with `md:hidden` mobile cost fields, generous column widths (`min-w-[260px]` product, `min-w-[145px]` expiry date), and read-only stock-cost display for outward memos.
- **Configurable PDF Invoices & Account Statements (`templates/components/pdf_export_modal.html`, `master_data/pdf_service.py`)**:
  - A4 RTL ReportLab PDFs with Arabic reshaping/BiDi, `CompanyProfile` branding, page numbers (`صفحة X من Y`), section toggles for orders/returns, and opening/running/closing balance statements.
