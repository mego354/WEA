# UI / UX guidelines

Apply this document whenever templates, CSS, JavaScript, forms, tables, navigation, dialogs, or user workflows change.

**Do not introduce a second design system.** The live UI is Arabic RTL, teal brand, Tailwind utility classes, Cairo, and Material Symbols.

## A. Existing design system (from `templates/layouts/base.html`)

| Token | Value |
|---|---|
| Primary teal | `#27bebe` (`brand-500`); hover/darker `#1fa8a8` (`brand-600`) |
| Brand scale | 50 `#f0fdfd` … 900 `#185a5a` |
| Page background | `#f8fafc` / `bg-slate-50` |
| Body text | `#0f172a` / `text-slate-800` |
| Font | Cairo 300–800 |
| Icons | Material Symbols Outlined |
| Radius | cards `rounded-xl`, FAB `rounded-full`, quick-add sheet `rounded-t-3xl` |
| Status colors | success emerald, error rose/red, warning amber, info blue/sky, teal for approved |
| Locale chip | `عربي (EGP)` |

Patterns:

- White cards: `bg-white border border-slate-200 rounded-xl shadow-xs`
- Primary button: `bg-brand-500 hover:bg-brand-600 text-white rounded-xl min-h-[44px]`
- Flash messages: branded banners in base layout
- Sidebar active: `bg-brand-50 text-brand-700`
- Pagination: `templates/components/pagination.html`
- Column picker: `templates/components/table_column_picker.html` + `static/js/table_column_manager.js`
- Maps: Leaflet in `templates/components/location_picker.html`

## B. Mobile must feel like an application

Breakpoints already used: `sm`, `md`, `lg` (sidebar and bottom nav switch at **`lg` / 1024px**).

On small screens:

- Do not shrink a desktop spreadsheet page. Re-stack headers, filters, and actions.
- Sidebar is **off-canvas from the right** (`translate-x-full` until opened) with `#sidebar-overlay`. The sidebar uses `h-full h-[100dvh] max-h-screen flex flex-col fixed inset-y-0 right-0 z-50` with a sticky footer housing user profile and a prominent red logout button, plus an explicit mobile navigation item for logout to ensure 100% discoverability.
- **Bottom navigation** (`lg:hidden`, `h-16`): Home, Contacts, Products, Purchases (each gated by module permission).
- Main padding: `p-3 sm:p-4 lg:p-6` and `pb-24 lg:pb-6` so content clears the bottom nav and FAB.
- FAB quick-add: `bottom-20 lg:bottom-6` (sits above bottom nav). Opens a bottom sheet, not a desktop-only hover menu.
- Touch targets: about **44×44 CSS pixels** (`min-h-[44px]`, `min-w-[44px]`).
- Prevent **page-level** horizontal overflow (`max-w-full` on `<main>`). Tables may scroll **inside** a card (`overflow-x-auto`), not the whole viewport.
- Action headers on list pages use `flex-wrap gap-2` to prevent button overflow or horizontal truncation on narrow viewports.
- Inputs: correct `type` (`tel`, `email`, `number`, `date`); grouping with Arabic labels; server validation remains authoritative.
- Modals/sheets must be usable with a finger (full-width on narrow, `max-w-lg mx-auto` sheets).
- Avoid hover-only actions. Always provide a tap control.
- Keep RTL: drawer from the right, `text-right`, logical padding (`pr`/`pl` not assumed LTR).
- Currency/dates: EGP, Africa/Cairo, Arabic copy.

## C. Specialized Mobile & Form Patterns

### 1. Planned Visits Mobile Filter Drawer
- On desktop (`lg+`), the filter panel displays inline on the left side.
- On mobile (`<lg`), the filter panel converts to a slide-over side drawer (`#customer-drawer` with backdrop `#customer-drawer-backdrop`) fixed to the right (`inset-y-0 right-0`).
- The mobile drawer is toggled via a dedicated filter button near the top of the page, featuring an active filter counter badge.
- When open, body scroll is locked (`overflow-hidden`).
- **AJAX Filter Execution (Zero Page Refresh):** Applying or resetting client filters executes asynchronously via AJAX (`action=load_contacts`), immediately updating client cards and available counts without refreshing the page. This keeps the drawer open on mobile, preserves scroll position, and avoids losing filled bulk planning forms or client checkboxes.
- Preserves all filter values, customer selections, and live search.

### 2. Standardized Sales & Purchases Forms
- **Bottom Action Buttons:** Form action buttons (`إلغاء`, `حفظ أمر البيع`, `حفظ أمر الشراء`) are positioned consistently at the bottom of the form across both Sales and Purchases, matching user ergonomic expectations.
- **Order Items Section Titles:** Terminology is standardized to `بنود أمر البيع` for Sales and `بنود أمر الشراء` for Purchases.
- **Responsive Item Tables (Stacked Cards on Mobile):**
  - Table headers are hidden on small screens (`hidden md:table-header-group`).
  - Table rows transform into individual cards (`block md:table-row p-4 md:p-0 rounded-xl md:rounded-none border border-slate-200 md:border-none shadow-xs mb-3 md:mb-0 space-y-2 md:space-y-0`).
  - Cells display visible contextual labels on mobile (`<label class="block md:hidden">`).
  - Product selection inputs and dropdowns maintain full width, eliminating clipped names.
  - Price, quantity, discount, and subtotal columns never collapse or shrink below usable limits.
- **Financial Adjustments:** Real-time client-side calculation cards calculate item discounts, custom discount percentages/amounts, taxes, and shipping fees into a clean summary card.

## D. Product Owner UI Preference: Simple, Compact UI & No Verbose Notes

- **Core Directive:** The product owner strictly prefers a simple, clean, uncluttered user interface across the entire application.
- **No Verbose Helper Notes:** Avoid long explanatory paragraphs, multi-sentence helper texts, and redundant descriptive captions under section headers or inputs.
- **Compact UI Components:** Keep cards, panels, badges, and grids compact to reduce vertical space consumption and minimize scrolling, especially on mobile devices.
- **Icons & Simple Text:** Present metrics, operational data, and statuses using clean icons with concise labels and values (for example, GPS data and distance comparisons formatted in simple, compact 4-item rows with icons rather than oversized multi-card blocks with verbose paragraphs).
- **In-Place Interactivity (No Full-Page Refreshes for Filters):** In drawer, planning, and filter panels, filtering and incremental loading must happen via AJAX without full-page reloads, ensuring mobile users never lose their scroll position or open drawer/modal state.

**Implemented vs desired:** many list pages still wrap `<table>` in `overflow-x-auto` rather than card rows. Contacts list supports `?view=` table/card (`view_mode`). Prefer cards for dense operational lists on `<lg` when you touch that page; do not mechanically convert every table.

## C. Lists and tables

When changing a list page:

1. Keep identity + status visible (name, serial, status pill).
2. Hide secondary columns with `hidden md:table-cell` if the table stays.
3. Or render a `lg:hidden` card stack **and** `hidden lg:block` table — both must call the same actions with the same permission checks.
4. Filters: compact bar or slide-down; preserve querystring on pagination (`components/active_filters.html`).
5. Bulk actions and column picker must work on touch (column manager already persists preferences).

## D. UX rules

- One primary action per screen, placed where the thumb can reach on mobile (header or sticky bar without covering fields).
- Destructive actions: POST + confirmation (existing delete patterns).
- `messages` framework for success/error; JSON `{error, detail}` for AJAX 401/403.
- Disable submit buttons after first post where duplicate documents would be created (orders, collections, transfers).
- Empty states: say what to do next (create, change filter).
- 403 template `templates/403.html` — do not leak other tenants' data in the body.
- Do not restyle a working flow only to make it look “modern”.

## E. UI regression checks

Viewports to check: ~320, 390, 430, 768, 1024, 1440.

Check: overflow, clipped sheets, unreachable FAB, console errors, failed XHR, RTL mirror issues, permission-hidden nav remaining hidden.

Browser automation in this repo: Playwright scripts under `scratch/` and `test_responsive_viewports.py` / `test_e2e_workflows.py` at repo root. They are **not** in `INSTALLED_APPS`; run them explicitly. If you cannot drive a browser, say so and use Django test client + template assertions instead.
