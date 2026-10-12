# Products & Purchases UI / UX Specification & Parity System

> **System**: WEA Pharma / Bricks Rep ERP  
> **Source Base**: Angular Material Design RTL Theme  
> **Target Framework**: Django Templates + Tailwind CSS + Vanilla JS + Material Symbols + Cairo Font  
> **Status**: Comprehensive Visual & Interaction Design Specification  

---

## 1. Visual Token Architecture

The user interface reproduces the exact visual language of the reference application: an enterprise RTL layout featuring Cairo typography, clean cards, subtle elevation shadows, and a signature teal brand accent `#27bebe`.

### 1.1 Color Tokens

| Token Name | Hex Code | Tailwind Equivalent | Usage in Reference ERP |
|---|---|---|---|
| **Primary Brand Teal** | `#27bebe` | `brand-500` / `teal-500` | Header accents, primary CTA buttons, active tabs, icon highlights |
| **Primary Dark** | `#1fa8a8` | `brand-600` | Hover states on primary buttons |
| **Accent Dark Blue** | `#201c50` | `slate-900` / `indigo-950`| App headers, dark modal headers, subtle contrasts |
| **Surface Canvas** | `#f8fafc` | `bg-slate-50` | Background canvas for application layout |
| **Card / Panel Surface** | `#ffffff` | `bg-white` | White cards, drawers, dialog modals |
| **Border Soft** | `#e2e8f0` | `border-slate-200` | Card borders, table cell dividers |
| **Text Primary** | `#0f172a` | `text-slate-900` | Headings, table row titles, primary labels |
| **Text Muted** | `#64748b` | `text-slate-500` | Table subheaders, timestamps, secondary labels |

### 1.2 Status Color Mapping

| Transaction Status | Arabic Label | Pill Badge Styling |
|---|---|---|
| `Pending` | قيد الانتظار | `bg-amber-50 text-amber-700 border border-amber-200` |
| `Approved` | معتمد | `bg-green-50 text-green-700 border border-green-200` |
| `Picked` / `Delivered` | دخل المخزن / خرج من المخزن | `bg-blue-50 text-blue-700 border border-blue-200` |
| `Settled` | تم الترحيل للحسابات | `bg-emerald-50 text-emerald-700 border border-emerald-200` |
| `Rejected` | مرفوض | `bg-red-50 text-red-700 border border-red-200` |
| `Split` | مقسم | `bg-purple-50 text-purple-700 border border-purple-200` |
| `Cancelled` | ملغي | `bg-slate-100 text-slate-700 border border-slate-300` |

---

## 2. Typography & Iconography

1. **Font Family**: Google Fonts `Cairo` (`wght@300;400;500;600;700;800`).
   - Body font size: `13px` / `0.8125rem` (`text-xs` / `text-sm`).
   - Table cells: `12px` font with medium weight.
   - Headings: `text-2xl font-black text-[#27bebe] tracking-tight`.
2. **Icons**: Google Material Symbols Outlined.
   - Standard size: `20px` to `24px`.
   - Used for all buttons (`add`, `filter_list`, `download`, `print`, `more_vert`, `shopping_cart`, `store`, `refresh`, `inventory`).

---

## 3. Component Design Specifications

### 3.1 Data Tables & Grid Layout
- **Density**: Compact table rows (`py-3.5 px-4`) to accommodate rich ERP data without horizontal bloating.
- **RTL Alignment**: Text headers and content aligned right; action menus and numeric totals aligned left or center as appropriate.
- **Hover Effects**: Rows transition to `hover:bg-slate-50/80`.
- **Thumbnails**: 36x36px rounded square previews (`rounded-lg object-cover border border-slate-200`).

### 3.2 Action Bars
- Top bar with flex layout:
  - Right: Page title with badge counter pill (e.g. `13 صنف` or `16 أمر`).
  - Left: Search box, filter trigger button with count badge, export button, and primary creation CTA button.

### 3.3 Slide-out Filter Drawers
- Position: Fixed on left or right edge (`fixed inset-y-0 left-0 z-50 w-80 md:w-96 bg-white shadow-2xl`).
- Overlay: Soft dark backdrop (`bg-slate-900/40 backdrop-blur-xs`).
- Header: Title `تصفية النتائج` with close icon `close`.
- Form Controls:
  - Presets select
  - Checkbox groups / toggles
  - Date range inputs
  - Action buttons: `تطبيق الفلتر` (`#27bebe`), `إعادة تعيين` (white button).

### 3.4 Modal Dialogues
- Centered overlay (`fixed inset-0 bg-slate-900/50 backdrop-blur-xs flex items-center justify-center z-50 p-4`).
- Rounded corners (`rounded-2xl`).
- Animated entrance (`animate-in fade-in zoom-in duration-150`).
- Header with clear title and close icon; footer with `إلغاء` and primary `حفظ`.

### 3.5 Dynamic Line Items Repeaters (Orders & Returns)
- Table-based repeater with responsive rows:
  - Searchable Product selector
  - Unit Cost input
  - Quantity input
  - Batch number & Expiry date
  - Line Discount % input
  - Live subtotal recalculation via JavaScript
  - Trash icon button (`delete`) to remove row
  - `+ إضافة صنف جديد` button below table.
