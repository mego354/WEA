# Reference ERP Products & Purchases Page Inventory

> **System**: WEA Pharma / Bricks Rep ERP  
> **Source URL**: `https://weapharma.bricks-rep.com/`  
> **Inspection Mode**: Safe Read-Only Browser Audit & Protocol Inspection  
> **Scope**: Products (`المنتجات`) and Purchases (`المشتريات`) Modules  
> **Status**: Comprehensive Inventory & Audit  

---

## 1. Executive Summary & Scope Overview

The reference ERP system (`Bricks Rep` / `WEA Pharma`) organizes commercial, pharmaceutical, warehouse, and financial operations under a responsive Arabic RTL Angular Material interface.
The **Products** and **Purchases** domains represent the backbone of inventory replenishment, supplier management, and catalog indexing.

### Menu Tree & Route Map

```
├── store المنتجات (Products)
│   ├── store المنتجات -> /products (Products Catalog)
│   └── category التصنيفات -> /product-categories (Product Categories)
│
└── storefront المشتريات (Purchases)
    ├── shopping_cart الطلبات -> /purchase-orders (Purchase Orders)
    ├── refresh المرتجعات -> /purchase-return-orders (Purchase Return Orders)
    ├── receipt المدفوعات -> /vendor-payments (Vendor Payments)
    ├── request_quote طلبات الدفع -> /vendor-payment-requests (Vendor Payment Requests)
    ├── attach_money حسابات الموردين -> /accounting/vendors (Supplier Statements & Accounts)
    └── receipt_long عمليات الموردين -> /accounting/vendor-transactions (Supplier Ledger Transactions)
```

---

## 2. Products Module Inventory

### 2.1 Products Catalog Listing
- **Page Name**: `المنتجات` (Products List)
- **Reference URL**: `https://weapharma.bricks-rep.com/products`
- **Local Route**: `/products/` (Alias for `/catalog/`)
- **Primary Color / Theme**: Teal `#27bebe`
- **Layout & Structure**:
  - Top Action Header:
    - Title: `المنتجات` with badge indicator `{{ count }} صنف`
    - Search input (`بحث بالاسم أو الكود...`)
    - Filter Button (`filter_list` with active filter badge)
    - Export Data (`تصدير البيانات` -> CSV / Excel)
    - Primary CTA Button (`انشئ منتج` in `#27bebe` with `+` icon)
  - Grid / Data Table (Dense layout, RTL):
    1. **الصورة (Image / Thumbnail)**: Product preview or placeholder icon
    2. **الاسم (Product Name)**: Primary label with clinical/commercial description snippet
    3. **الكود (Code / SKU)**: Unique SKU (e.g. `GE1`, `LE1`, `PU1`, `7000`)
    4. **التصنيف (Category)**: Category badge (e.g. `WEA`, `Packing materials`)
    5. **السعر (Retail Price)**: Formatted currency with unit (e.g. `140.000 جنيه`)
    6. **قيمة الضريبة (Tax Value)**: Percentage (e.g. `0%`, `14%`)
    7. **متاح للبيع (Sellable)**: Active checkmark pill or dash
    8. **باركود (Barcode)**: Barcode string or empty
    9. **إجراءات (Actions)**: Context menu `more_vert` (View Details, Edit, Deactivate / Delete)
  - Pagination Controls:
    - Items per page selector: `20`, `40`, `100` (Default: 40)
    - Range indicator: `1 – X of Y`
    - Navigation: First, Prev, Next, Last
  - Slide-out Filter Drawer:
    - Category selector
    - Sellable status toggle (`All` / `Yes` / `No`)
    - In-stock availability toggle
    - Price range (Min / Max)
    - Reset & Apply buttons
- **Priority**: **P0**

### 2.2 Product Create & Edit Forms
- **Page Name**: `انشئ منتج` / `تعديل المنتج` (Product Create / Edit)
- **Reference URL**: `https://weapharma.bricks-rep.com/products/create`
- **Local Route**: `/products/create/` and `/products/<id>/edit/`
- **Top Bar**:
  - Title & Subtitle: "أدخل بيانات المنتج والتسعير والتعبئة وتصنيف الكتالوج"
  - Actions: `إلغاء` (Cancel link) and `حفظ` (Save button in `#27bebe`)
- **Form Sections & Fields**:
  1. **المعلومات الأساسية والتسعير (Basic Info & Pricing)**:
     - `الاسم`: Text, required.
     - `التصنيف`: Select dropdown (searchable), required.
     - `الكود (SKU)`: Unique SKU code, required.
     - `باركود`: Barcode string, optional.
     - `السعر (ج.م)`: Retail price (Decimal), required.
     - `قيمة الضريبة %`: Tax percentage (Decimal), required (default: 0).
     - `تكلفة الشراء الافتراضية (ج.م)`: Default purchase unit cost (Decimal).
     - `الوحدة`: Unit description (e.g. `عبوة (Pack)`).
     - `متاح للبيع`: Toggle switch (default: true for commercial items).
     - `الوصف`: Clinical & commercial pharmacology notes.
  2. **خصومات الكمية (Volume Discounts)**:
     - Toggle: `تفعيل خصومات الكمية`
     - Repeater rows: Minimum quantity (`الحد الأدنى للكمية`), Discount percentage (`نسبة الخصم %`), Discount amount.
  3. **قوائم الأسعار (Price Lists)**:
     - Button: `+ إضافة قائمة أسعار`
     - Repeater rows: Price list name, custom rate.
  4. **التعبئة (Packaging & Units)**:
     - `تعبئة العلب`: Units per box (e.g. 10 packs).
     - `تعبئة الكراتين`: Units per carton (e.g. 50 packs).
  5. **صور المنتج (Product Images)**:
     - File upload dropzone with image preview and delete button.
- **Priority**: **P0**

### 2.3 Product Categories Page
- **Page Name**: `التصنيفات` (Product Categories)
- **Reference URL**: `https://weapharma.bricks-rep.com/product-categories`
- **Local Route**: `/product-categories/` (Alias for `/catalog/categories/`)
- **Top Bar**: Title, category count badge, `إنشاء تصنيف` (Create Category button).
- **Table Columns**:
  1. `الاسم` (Category Name)
  2. `الكود` (Category Code)
  3. `التوصيف` (Description)
  4. `انشئ فى` (Creation Date & Time)
  5. `إجراءات` (Edit, Delete)
- **Category Modal**:
  - Modal title: `إنشاء تصنيف` / `تعديل التصنيف`
  - Fields: `اسم التصنيف` (Required), `الكود` (Required), `التوصيف` (Optional)
  - Buttons: `إلغاء`, `حفظ`
- **Priority**: **P0**

---

## 3. Purchases Module Inventory

### 3.1 Purchase Orders Listing
- **Page Name**: `أوامر المشتريات` (Purchase Orders List)
- **Reference URL**: `https://weapharma.bricks-rep.com/purchase-orders`
- **Local Route**: `/purchase-orders/`
- **Top Actions**:
  - Title: `أوامر المشتريات` with count badge
  - `أمر مشتريات جديد` (New Purchase Order button in `#27bebe`)
  - `تصدير البيانات` (Export CSV)
  - `اطبع` (Print)
  - `filter_list` (Filter button with active counter badge)
- **Table Columns (RTL)**:
  1. **رقم المسلسل**: Serial number (e.g. `#16`, `#15`)
  2. **الاسم**: Supplier name (e.g. `مصنع اورجانيك للمكملات الغذائية`)
  3. **المنطقة**: Supplier area / governorate (e.g. `بنها`, `القاهرة`)
  4. **انشئ فى**: Timestamp formatted (e.g. `04/10/2026 10:51 ص`)
  5. **المنشئ**: Creator user name and role
  6. **الحالة**: Status badge:
     - `Pending` (قيد الانتظار - Amber)
     - `Approved` (معتمد - Green)
     - `Picked` (دخل المخزن - Blue)
     - `Settled` (تم الترحيل للحسابات - Emerald)
     - `Rejected` (مرفوض - Red)
     - `Split` (مقسم - Purple)
     - `Cancelled` (ملغي - Gray)
  7. **اجمالى القيمة**: Formatted grand total (e.g. `58,849.20 جنيه`)
  8. **مسئول التوصيل**: Receiving / Delivery agent
  9. **وقت التوصيل**: Delivery scheduled time
- **Filters Drawer**:
  - Supplier select
  - Status multi-select
  - Date range (`من تاريخ` - `إلى تاريخ`)
  - Warehouse select
- **Priority**: **P0**

### 3.2 Purchase Order Detail & Lifecycle Dossier
- **Page Name**: `تفاصيل أمر الشراء` (Purchase Order Detail)
- **Reference URL**: `https://weapharma.bricks-rep.com/purchase-orders/{id}`
- **Local Route**: `/purchase-orders/<id>/`
- **Header Layout**:
  - Status badge (e.g. `دخل المخزن` / `تم الترحيل للحسابات`)
  - Order Serial `#16`
  - Supplier avatar & title
  - Quick status dropdown (`expand_more` to transition between stages)
  - Undo Invoice button (`الغاء الفاتورة`)
  - Action buttons: Print, Timeline, Edit, Cancel, Split
- **Center Column**:
  1. **Line Items Table**:
     - `#` (Row index)
     - `الكود` (Product SKU)
     - `التصنيف` (Category)
     - `الصنف` (Product name)
     - `الكمية` (Quantity)
     - `سعر القطعة` (Unit cost price)
     - `خصم القطعة` (Discount %)
     - `إجمالي السعر` (Subtotal)
     - `رقم التشغيل` (Batch Number)
     - `تاريخ الصلاحية` (Expiry Date)
     - `ملاحظة` (Line note)
  2. **Financial Summary Card**:
     - Total items subtotal
     - Line items discounts total
     - Order-level custom discount
     - Shipping fees (`مصاريف الشحن`)
     - Tax amount
     - Final Grand Total (`الإجمالي النهائي`)
     - Total units count
  3. **Linked Accounting Card (الحسابات)**:
     - Invoicing status & timestamp
     - Total invoiced amount, Paid amount, Remaining debt
     - Settlement payment records table
  4. **Linked Warehouse Receipt Card (إذن المخزن)**:
     - Inward Memo number (`MEMO-IN-{serial}`)
     - Warehouse name
     - Goods received timestamp
  5. **Attachments Card (المرفقات)**:
     - Upload file (tax invoice PDF / scan)
     - Audio recording icon
     - Download & delete links
  6. **Comments Stream (التعليقات)**:
     - Discussion thread with user avatars and timestamps
- **Right Sidebar**:
  - Basic details (Creator, Warehouse link, Creation time)
  - Delivery information (Agent, Address)
  - Supplier financial snapshot (Current balance, Credit limit, Statement link)
  - Supplier contact card (Phones, addresses, commercial details)
  - Audit log
- **Priority**: **P0**

### 3.3 Purchase Order Creation Flow
- **Page Name**: `أمر مشتريات جديد` (New Purchase Order)
- **Reference URL**: `https://weapharma.bricks-rep.com/purchase-orders/create`
- **Local Route**: `/purchase-orders/create/`
- **Flow**:
  - Step 1: Searchable Supplier selector (`جهة الاتصال: مورد`)
  - Step 2:
    - Target receiving warehouse selector
    - Order date & Delivery due date
    - Dynamic line items repeater:
      - Product selection
      - Unit cost price
      - Quantity
      - Item discount %
      - Batch number
      - Expiry date
      - Subtotal live calculation
    - Order-level custom discount % and Shipping fees
    - Internal notes
    - Save draft / submit
- **Priority**: **P0**

### 3.4 Purchase Return Orders Listing & Lifecycle
- **Page Name**: `أوامر إرجاع المشتريات` (Purchase Return Orders)
- **Reference URL**: `https://weapharma.bricks-rep.com/purchase-return-orders`
- **Local Route**: `/purchase-return-orders/`
- **Top Actions**:
  - Title: `أوامر إرجاع المشتريات`
  - `أمر إرجاع مشتريات جديد` (New Purchase Return Order button)
  - `تصدير البيانات` (Export CSV)
  - `اطبع` (Print)
  - `filter_list`
- **Table Columns (RTL)**:
  1. **رقم المسلسل**: Return serial number (e.g. `#RO-1`)
  2. **الاسم**: Supplier name
  3. **المنطقة**: Supplier area / city
  4. **انشئ فى**: Timestamp
  5. **المنشئ**: Created by user
  6. **الحالة**: Status badge:
     - `Pending` (قيد الانتظار)
     - `Approved` (معتمد)
     - `Delivered` / `Picked` (خرج من المخزن - Stock deducted)
     - `Settled` (تم الترحيل للحسابات - Debit note posted)
     - `Cancelled` (ملغي)
  7. **اجمالى القيمة**: Return total amount
  8. **مسئول الاستلام**: Receiving agent / carrier
  9. **وقت الاستلام**: Return handover time
- **Return Order Detail View**:
  - Detailed line items, batch & expiry
  - Status progression: Pending -> Approved -> Delivered (generates outward `InventoryMemo`, decrements `InventoryStock` and `InventoryLot`) -> Settled (creates Debit Note in `VendorTransaction`, decrements `VendorAccount.current_balance`)
- **Priority**: **P0**

### 3.5 Vendor Payments (المدفوعات)
- **Page Name**: `المدفوعات` (Supplier Payments)
- **Reference URL**: `https://weapharma.bricks-rep.com/vendor-payments`
- **Local Route**: `/vendor-payments/` (Alias for `/treasury/payments/`)
- **Table Columns**:
  1. `رقم المسلسل` (Serial `#10027`)
  2. `الاسم` (Supplier Name)
  3. `المنطقة` (Area)
  4. `انشئ فى` (Date)
  5. `المبلغ` (Amount EGP)
  6. `المنشئ` (Created by)
  7. `الخزنة / وسيلة الدفع` (Vault / Method)
  8. `الحالة` (Status)
- **New Vendor Payment Modal / Form**:
  - Supplier select, Amount, Safe/Vault select, Method, Date, Notes.
- **Priority**: **P1**

### 3.6 Vendor Payment Requests (طلبات الدفع)
- **Page Name**: `طلبات الدفع` (Vendor Payment Requests)
- **Reference URL**: `https://weapharma.bricks-rep.com/vendor-payment-requests`
- **Local Route**: `/vendor-payment-requests/`
- **Table Columns**:
  1. Serial, 2. Supplier, 3. Area, 4. Created At, 5. Creator, 6. Status (`Open`, `Done`, `Rejected`), 7. Amount, 8. Method, 9. Responsible Person, 10. Execution Date.
- **Priority**: **P1**

### 3.7 Supplier Statements & Accounts (حسابات الموردين)
- **Page Name**: `حسابات الموردين` (Vendor Statements & Balances)
- **Reference URL**: `https://weapharma.bricks-rep.com/accounting/vendors`
- **Local Route**: `/accounting/vendors/` (Alias for `/treasury/vendors/`)
- **Table Columns**:
  1. `اسم الحساب`
  2. `حد الائتمان`
  3. `مدة الائتمان`
  4. `الرصيد`
  5. `قيمة أقدم مديونية`
  6. `تاريخ أقدم مديونية`
  7. `قيمة المديونية المتأخرة`
  8. `تاريخ المديونية المتأخرة`
  9. `تاريخ اخر عملية`
  10. `أيام المبيعات المعلّقة`
- **Priority**: **P1**

### 3.8 Supplier Ledger Transactions (عمليات الموردين)
- **Page Name**: `عمليات الموردين` (Vendor Ledger Transactions)
- **Reference URL**: `https://weapharma.bricks-rep.com/accounting/vendor-transactions`
- **Local Route**: `/accounting/vendor-transactions/` (Alias for `/treasury/vendor-transactions/`)
- **Table Columns**:
  1. `اسم الحساب`, 2. `التاريخ`, 3. `توصيف`, 4. `مديونية متأخرة؟`, 5. `تاريخ الاستحقاق`, 6. `دائن`, 7. `مدين`, 8. `الرصيد`, 9. `ملاحظة`, 10. `انشئ فى`, 11. `انشئ بواسطة`, 12. `المديونية`, 13. `الأيام المعلّقة`.
- **Priority**: **P1**

---

## 4. Priority Mapping Summary

| Priority | Module | Page / Feature | Status | Parity Target |
|:---:|:---|:---|:---:|:---|
| **P0** | Products | `/products/` Catalog List & Filters | IN PROGRESS | Table, Filter Drawer, Export, Pagination |
| **P0** | Products | `/products/create/` & Edit Form | IN PROGRESS | Form layout, volume discounts, packaging |
| **P0** | Products | `/product-categories/` List & Modals | IN PROGRESS | Full CRUD modal workflows |
| **P0** | Purchases | `/purchase-orders/` List & Filters | COMPLETED | Status filters, search, export, pagination |
| **P0** | Purchases | `/purchase-orders/<id>/` Dossier | COMPLETED | Lines, summary, accounting, memos, attachments |
| **P0** | Purchases | `/purchase-orders/create/` Flow | COMPLETED | Dynamic repeater, live totals, warehouse select |
| **P0** | Purchases | `/purchase-return-orders/` Returns | NOT STARTED | Full return model, unstocking, debit notes |
| **P1** | Purchases | `/vendor-payments/` Supplier Payments | COMPLETED | Linked to cash vault & open purchase invoices |
| **P1** | Purchases | `/vendor-payment-requests/` | COMPLETED | Approval workflow for purchasing staff |
| **P1** | Purchases | `/accounting/vendors/` Accounts | COMPLETED | Overdue debt, credit days, running balance |
| **P1** | Purchases | `/accounting/vendor-transactions/` | COMPLETED | Granular double-entry supplier ledger |
| **P2** | Purchases | Split Order (`فصل الطلب`) | NOT STARTED | Order splitting into sub-orders |
| **P2** | Products | Product Price Lists Repeater | NOT STARTED | Custom price tier per customer/tier |
