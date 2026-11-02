# Products Module Reference Specification

> **System**: WEA Pharma / Bricks Rep ERP  
> **Source URL**: `https://weapharma.bricks-rep.com/products`  
> **Inspection Mode**: Read-Only Browser Crawler & Automated DOM Inspection  
> **Date**: October 2026  

---

## 1. Menu & Navigation Hierarchy

- **Parent Menu**: `store المنتجات` (Expandable accordion with `add`/`remove` icon)
  - **Submenu 1**: `store المنتجات` -> `/products` (Products Catalog / Directory)
  - **Submenu 2**: `category التصنيفات` -> `/product-categories` (Product Categories)

---

## 2. Page Specifications

### 2.1 Products List Page (`/products`)

- **URL**: `https://weapharma.bricks-rep.com/products`
- **Page Title**: `المنتجات`
- **Color Accent**: Teal `#27bebe`
- **Top Actions**:
  - `انشئ منتج` (Create Product button - Primary teal/cyan with `+` icon)
  - `filter_list` (Filter button with badge for active filter count)
  - `more_vert` (Actions menu: Export CSV/Excel, settings)
- **Table / Grid Structure**:
  - Uses AG-Grid with dense table layout, RTL column orientation:
    1. **الاسم (Name)**: Product name with thumbnail icon / preview image.
    2. **الكود (Code/SKU)**: e.g. `GE1`, `LE1`, `PU1`, `SO1`, `ST1`, `UL1`, `7000`, `4000`, `3000`, `6000`, `5000`, `1000`, `2000`.
    3. **التصنيف (Category)**: Category badge (e.g., `WEA`, `Packing materials`).
    4. **السعر (Retail Price)**: Formatted currency with unit (e.g., `140.000 جنيه`, `120.000 جنيه`, `0.000 جنيه`).
    5. **قيمة الضريبة (Tax Value)**: Percentage (e.g., `0%`).
    6. **متاح للبيع (Sellable)**: Checked icon or unchecked pill.
    7. **باركود (Barcode)**: Barcode string (e.g., `1000` or empty).
    8. **إجراءات (Actions)**: Contextual menu `more_vert` (View Details, Edit, Deactivate).
- **Pagination Footer**:
  - `Items per page: 40` (Dropdown: 20, 40, 100)
  - Range indicator: `1 – 13 of 13`
  - Navigation buttons: `first_page`, `chevron_left`, `chevron_right`, `last_page`.
- **Slide-out Filter Drawer**:
  - Preset filters dropdown
  - Category multi-select
  - Sellable toggle (Yes / No / All)
  - In Stock toggle
  - Price range (Min / Max)
  - Reset & Apply buttons (`اعادة تعيين`, `فلتر`, `مسح`)

### 2.2 Product Creation Form (`/products/create`)

- **URL**: `https://weapharma.bricks-rep.com/products/create`
- **Page Title**: `انشئ منتج`
- **Header Actions**: `حفظ` (Save button)
- **Form Fields & Layout**:
  - **الاسم (Name)**: Text input, required.
  - **التصنيف (Category)**: Searchable dropdown select (`WEA`, `Packing materials`, etc.).
  - **الكود (Code/SKU)**: Text input, required (unique product code).
  - **باركود (Barcode)**: Text input, optional.
  - **السعر (Price)**: Decimal input, required (EGP).
  - **قيمة الضريبة (Tax Value)**: Decimal input / Percentage (default `0%`).
  - **متاح للبيع (Sellable)**: Toggle switch (Checked by default for commercial goods).
- **Advanced Product Sections**:
  1. **خصومات الكمية (Volume Discounts)**:
     - Toggle: `تفعيل خصومات الكمية` ("قم بتفعيل الخيار لإضافة شرائح خصم بناءً على الكمية لهذا المنتج").
     - Tier repeater: Minimum quantity, discount percentage/amount.
  2. **قوائم الأسعار (Price Lists)**:
     - Button: `+ إضافة قائمة أسعار`.
     - Price list selection and custom pricing.
  3. **التعبئة (Packaging & Units)**:
     - **العلب (Boxes/Packs)**: Button `+ إضافة علبة` (Pack units and count).
     - **الكراتين (Cartons)**: Button `+ إضافة كرتونة` (Carton capacity, e.g. 50 packs).
  4. **صور المنتج (Product Images)**:
     - Dropzone: `اسحب الصور هنا أو تصفح` (Drag & drop or file browse).
     - Thumbnail preview and primary image selector.

### 2.3 Product Categories Page (`/product-categories`)

- **URL**: `https://weapharma.bricks-rep.com/product-categories`
- **Page Title**: `التصنيفات`
- **Top Actions**:
  - `إنشاء تصنيف` (Create Category button)
  - `filter_list`
- **Table Columns**:
  1. **الاسم (Name)**: Category name (e.g., `WEA`, `Packing materials`).
  2. **الكود (Code)**: Unique category code.
  3. **التوصيف (Description)**: Detailed description.
  4. **انشئ فى (Created At)**: Timestamp (e.g. `03/09/2025 12:21 م`).
  5. **إجراءات (Actions)**: `more_vert` (Edit, Delete).
- **Create Category Modal**:
  - Dialog title: `إنشاء تصنيف`
  - Fields: `الاسم`, `الكود`, `التوصيف`
  - Buttons: `إلغاء`, `حفظ`

---

## 3. Reference Data Set (13 Observed Products)

| # | Code | Name | Category | Price | Tax | Sellable | Barcode |
|---|---|---|---|---|---|---|---|
| 1 | `GE1` | Geron | WEA | 140.00 EGP | 0% | Yes | - |
| 2 | `LE1` | Legatonexx Spray | WEA | 120.00 EGP | 0% | Yes | - |
| 3 | `PU1` | Putalaxy gel | WEA | 75.00 EGP | 0% | Yes | - |
| 4 | `SO1` | Soriana V.D | WEA | 75.00 EGP | 0% | Yes | - |
| 5 | `ST1` | Steps | WEA | 140.00 EGP | 0% | Yes | - |
| 6 | `UL1` | Ultrahumudin Cream | WEA | 105.00 EGP | 0% | Yes | - |
| 7 | `7000` | تيوب الالترا هيوميدين | Packing materials | 0.00 EGP | 0% | No | - |
| 8 | `4000` | كرتون الترا هيوميدين | Packing materials | 0.00 EGP | 0% | No | - |
| 9 | `3000` | كرتون بيوتالاكسي | Packing materials | 0.00 EGP | 0% | No | - |
| 10 | `6000` | كرتون جيرون | Packing materials | 0.00 EGP | 0% | No | - |
| 11 | `5000` | كرتون ستيبس | Packing materials | 0.00 EGP | 0% | No | - |
| 12 | `1000` | كرتون سوريانا | Packing materials | 0.00 EGP | 0% | No | 1000 |
| 13 | `2000` | كرتون ليجاتونيكس | Packing materials | 0.00 EGP | 0% | No | - |
