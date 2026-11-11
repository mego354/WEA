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
   - **Centralized Active Navigation**: Inspects `window.location.pathname`, identifies the matching item, applies active teal styling (`bg-teal-50 text-[#27bebe] font-bold border-r-2 border-[#27bebe]`), auto-expands the parent accordion, rotates the chevron icon (`rotate-180`), highlights the parent category button, and smoothly auto-scrolls the active link into view.
   - **Accordion State Persistence**: User-expanded/collapsed accordions are saved in `localStorage ('wea_sidebar_expanded')` and restored on subsequent page loads.
2. **Mobile**:
   - Slide-over drawer for secondary links and settings.
   - Fixed bottom navigation bar for high-frequency actions (Home, Visits, Orders, Clients, Profile).
   - Bottom-right Floating Action Button (FAB) triggering a bottom sheet for rapid creation (New Visit, New Order, New Client).
   - **Mobile Topbar Refresh Button**: Fixed in the header (`lg:hidden min-w-[44px] min-h-[44px]`) next to notifications for instant page reloading on mobile touch devices.

---

## 4. Drawers & Filter Preservation

### Client Filter Drawer (`#customer-drawer`)
- Filters and selection drawers operate via asynchronous AJAX without full page reloads.
- **Incremental Batch Loading**: Supports loading clients in 10-item increments (`action=load_contacts`) with deduplication.
- **State & Selection Persistence across Reload**:
  - Drawer open/closed state (`wea_planned_drawer_open`), selected contact IDs (`wea_planned_selected_ids`), and scheduled date (`wea_planned_bulk_date`) are persisted in `sessionStorage`.
  - On page refresh or back-navigation, the drawer reopens automatically, selections are restored, and eligible template groups reload without stale or lost data.
  - Upon successful plan submission, cached session storage entries are cleanly purged.
- **Pagination (`smart_page_range`)**: Compact pagination showing current, neighbor, first, last, and `'...'` ellipsis.

---

## 5. Table Standards & Column Customization

1. **Column Manager (`table_column_manager.js`)**:
   - Interactive column visibility picker (`#column-picker-dropdown`).
   - Preferences saved in browser `localStorage` keyed by page route.
   - Column reordering and visibility updates apply without page reloads.
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

