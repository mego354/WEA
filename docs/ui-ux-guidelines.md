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
- Sidebar is **off-canvas from the right** (`translate-x-full` until opened) with `#sidebar-overlay`.
- **Bottom navigation** (`lg:hidden`, `h-16`): Home, Contacts, Products, Purchases (each gated by module permission).
- Main padding: `p-3 sm:p-4 lg:p-6` and `pb-24 lg:pb-6` so content clears the bottom nav and FAB.
- FAB quick-add: `bottom-20 lg:bottom-6` (sits above bottom nav). Opens a bottom sheet, not a desktop-only hover menu.
- Touch targets: about **44×44 CSS pixels** (`min-h-[44px]`, `min-w-[44px]`).
- Prevent **page-level** horizontal overflow (`max-w-full` on `<main>`). Tables may scroll **inside** a card (`overflow-x-auto`), not the whole viewport.
- Inputs: correct `type` (`tel`, `email`, `number`, `date`); grouping with Arabic labels; server validation remains authoritative.
- Modals/sheets must be usable with a finger (full-width on narrow, `max-w-lg mx-auto` sheets).
- Avoid hover-only actions. Always provide a tap control.
- Keep RTL: drawer from the right, `text-right`, logical padding (`pr`/`pl` not assumed LTR).
- Currency/dates: EGP, Africa/Cairo, Arabic copy.

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
