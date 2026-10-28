# Table Column Visibility and Preferences Persistence Specification

## 1. Overview
Users require personalized column visibility settings across dense data tables to focus on fields relevant to their current operational workflow. To avoid requiring users to reconfigure their table columns every time they navigate or refresh, column visibility preferences are managed on the client side with persistent browser storage.

---

## 2. Architecture & Components

The feature is composed of three synchronized layers:

1. **Shared JavaScript Manager (`static/js/table_column_manager.js`):**
   - Implements `window.TableColumnManager`.
   - Handles storage I/O, column toggling, "Show All", "Reset to Defaults", and DOM synchronization.
2. **Reusable UI Component (`templates/components/table_column_picker.html`):**
   - Clean, accessible dropdown popover with an "الأعمدة" trigger button.
   - Includes individual column checkboxes, locked mandatory indicators, "عرض الكل" (Show all), and "الافتراضي" (Reset to default).
3. **Table Markup (`data-col-table` & `data-col` attributes):**
   - Each responsive table specifies `data-col-table="<unique_table_id>"`.
   - Each `<th>` and `<td>` element specifies `data-col="<stable_column_id>"`.

---

## 3. Storage Specification & Schema

- **Mechanism:** Browser `localStorage`.
- **Storage Key Convention:** `erp_table_cols_{table_id}_v1`
  - Example: `erp_table_cols_sales_orders_table_v1`
- **Isolation:** Stored per table ID and preference schema version (`v1`). Changes in one table cannot overwrite or corrupt another table's settings.
- **Payload Schema:**
  ```json
  {
    "order_number": true,
    "customer": true,
    "order_date": false,
    "grand_total": true,
    "status": true,
    "created_by": false,
    "actions": true
  }
  ```
- **Language Independence:** Keys use stable programmatic identifiers (`order_number`, `customer`) rather than translated labels (`رقم الطلب`, `العميل`), ensuring language switching between Arabic and English never corrupts saved preferences.
- **Fallback & Safety:**
  - If `localStorage` is disabled or corrupted (`JSON.parse` error), `TableColumnManager` safely logs a warning and falls back to default column definitions without throwing an exception or breaking page rendering.
  - Mandatory columns (`required: true`) are locked and cannot be unchecked.

---

## 4. Reset & Defaults Behavior

- **Initial State:** Defined declaratively in each template's column configuration list.
- **Reset to Defaults:**
  - Clicking "الافتراضي" (Reset) removes `erp_table_cols_{table_id}_v1` from `localStorage`.
  - Reapplies the default visibility state across checkboxes and table cells immediately.
- **Show All:**
  - Clicking "عرض الكل" sets all columns (including optional columns) to visible (`true`) and saves the preference.

---

## 5. CSV and Excel Export Behavior

- Server-side exports continue to enforce role-based and regional permissions via `accounts.permissions:get_scoped_queryset`.
- Data export endpoints export full authorized records by default to prevent data omissions during accounting/inventory reconciliation, while respecting user permission boundaries.
