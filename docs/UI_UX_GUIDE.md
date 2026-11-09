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
2. **Mobile**:
   - Slide-over drawer for secondary links and settings.
   - Fixed bottom navigation bar for high-frequency actions (Home, Visits, Orders, Clients, Profile).
   - Bottom-right Floating Action Button (FAB) triggering a bottom sheet for rapid creation (New Visit, New Order, New Client).

---

## 4. Drawers & Filter Preservation

### Client Filter Drawer (`#customer-drawer`)
- Filters and selection drawers operate via asynchronous AJAX without full page reloads.
- **Incremental Batch Loading**: Supports loading clients in 10-item increments (`action=load_contacts`) with deduplication.
- **State Preservation**: Client selections across previous batches and searches are strictly preserved in JavaScript memory and hidden form inputs.
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

- **Context-Preserving Modals**: Quick actions (e.g. Set Visit Time, Distance Exception Reason, Void Order) open compact centered modals without navigating away from the list or detail view.
- **Client-First Template Cascading**: In visit forms, selecting the client automatically queries eligible templates via AJAX, preventing selection of incompatible templates.
- **Territorial Cascading Dropdowns**: Selecting a Governorate dynamically updates the Brick/Subarea selector with child areas.
- **Submit Button State Management**: Form submit buttons automatically disable and display a loading spinner upon submission to prevent accidental duplicate requests.

