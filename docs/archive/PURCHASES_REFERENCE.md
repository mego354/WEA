# Purchases Module Reference Specification

> **System**: WEA Pharma / Bricks Rep ERP  
> **Source URL**: `https://weapharma.bricks-rep.com/purchase-orders`  
> **Inspection Mode**: Read-Only Browser Crawler & Automated DOM Inspection  
> **Date**: October 2026  

---

## 1. Menu & Navigation Hierarchy

- **Parent Menu**: `storefront المشتريات` (Expandable accordion with `add`/`remove` icon)
  - **Submenu 1**: `shopping_cart الطلبات` -> `/purchase-orders` (Purchase Orders)
  - **Submenu 2**: `refresh المرتجعات` -> `/purchase-return-orders` (Purchase Return Orders)
  - **Submenu 3**: `receipt المدفوعات` -> `/vendor-payments` (Vendor Payments)
  - **Submenu 4**: `request_quote طلبات الدفع` -> `/vendor-payment-requests` (Vendor Payment Requests)
  - **Submenu 5**: `attach_money حسابات الموردين` -> `/accounting/vendors` (Supplier Statements & Accounts)
  - **Submenu 6**: `receipt_long عمليات الموردين` -> `/accounting/vendor-transactions` (Supplier Ledger Transactions)

---

## 2. Page Specifications

### 2.1 Purchase Orders Listing (`/purchase-orders`)

- **URL**: `https://weapharma.bricks-rep.com/purchase-orders`
- **Page Title**: `أوامر المشتريات`
- **Color Accent**: Teal `#27bebe`
- **Top Actions**:
  - `أمر مشتريات جديد` (New Purchase Order button - Primary teal `#27bebe`)
  - `تصدير البيانات` (Export CSV/Excel button)
  - `اطبع` (Print button)
  - `filter_list 3` (Filter button with active filters badge count)
  - `view_agenda`, `table_chart` (View switchers)
  - `settings` (Column settings)
- **Table Headers (RTL column order)**:
  1. **رقم المسلسل (Serial Number)**: e.g. `#16`, `#15`.
  2. **الاسم (Supplier Name)**: e.g. `مصنع اورجانيك للمكملات الغذائية بنها`.
  3. **المنطقة (Area)**: Supplier territory / city.
  4. **انشئ فى (Created At)**: Timestamp (e.g. `04/10/2026 10:51 ص`).
  5. **المنشئ (Created By)**: User name and role (e.g. `Accountant`).
  6. **الحالة (Status)**: Badge:
     - `Pending` (Grey / Yellow)
     - `Approved` (Blue)
     - `Picked` (Purple - دخل المخزن)
     - `Settled` (Green - تم الترحيل للحسابات)
     - `Rejected` (Red)
     - `Split` (Orange)
  7. **اجمالى القيمة (Total Grand Value)**: Currency (e.g. `58,849.20 جنيه`).
  8. **مسئول التوصيل (Delivery Agent)**: Assigned rep / keeper.
  9. **وقت التوصيل (Delivery Time)**: Scheduled delivery timestamp.
- **Default Filters (sfql)**:
  - `contact_inactive: true`
  - `is_canceled: false`
  - `is_split: false`
- **Slide-out Filter Drawer**:
  - Preset filter dropdown
  - Supplier search / multi-select
  - Status multi-select (`Pending`, `Approved`, `Picked`, `Settled`, `Rejected`, `Split`)
  - Date Range (`من تاريخ` - `إلى تاريخ`)
  - Creator user dropdown
  - Area dropdown

### 2.2 Purchase Order Detail Page (`/purchase-orders/{id}`)

- **URL Pattern**: `https://weapharma.bricks-rep.com/purchase-orders/{id}`
- **Page Title**: `#{serial} - أمر مشتريات - Bricks Rep`
- **Header Layout**:
  - Status pill badge (e.g. `دخل المخزن` / `Picked`)
  - Order Serial (`#16`)
  - Supplier Avatar initials (e.g. `ما` for مصنع اورجانيك)
  - Supplier display name: `[#16115] مصنع اورجانيك للمكملات الغذائية بنها`
  - Status Dropdown: `expand_more Settled` (Options: `Pending`, `Approved`, `Picked`, `Settled`, `Rejected`, `Split`)
  - Visibility button: `visibility_off`
  - Undo invoice button: `attach_money الغاء الفاتورة` (Reverts accounting transaction)
  - Action icons: `print`, `timeline`, `edit`, `more_vert`
- **Split Layout Structure**:
  - **Center Column**:
    1. **Line Items Table**:
       - `#` (Row index)
       - `الكود` (Product SKU, e.g. `GE1`)
       - `التصنيف` (Category, e.g. `WEA`)
       - `الصنف` (Product name, e.g. `Geron`)
       - `الكمية` (Quantity, e.g. `3,109`)
       - `سعر القطعة` (Unit purchase price, e.g. `18.80 EGP`)
       - `خصم القطعة` (Discount %, e.g. `0%`)
       - `إجمالي السعر` (Subtotal, e.g. `58,449.20 EGP`)
       - `رقم التشغيل` (Batch Number, e.g. `269222`)
       - `تاريخ الصلاحية` (Expiry Date, e.g. `26/09/2028`)
       - `ملاحظة` (Line note, e.g. `غير متوفر`)
    2. **Financial Summary Card**:
       - `إجمالي السعر`: Subtotal before extra fees
       - `الصافي بعد الخصومات`: Net after line discounts
       - `بعد مصاريف الشحن 400 جنيه`: Shipping adjustments
       - `الإجمالي النهائي`: Final grand total
       - `عدد القطع`: Total units count
    3. **Linked Accounting Card (الحسابات)**:
       - Invoice timestamp: `تم اصدار فاتورة في 04/10/2026 10:54 ص`
       - Total value, Paid amount, Outstanding debt
       - Settlement payments table (Transactions linked to this invoice)
    4. **Attachments Card (المرفقات)**:
       - Voice note recorder icon `mic`, file upload icon `attach_file`
       - Document preview with `download` and `delete` buttons
    5. **Comments Stream (التعليقات)**:
       - User comments and discussion
  - **Right Sidebar Accordions**:
    1. `تفاصيل أساسية`: Creator, Warehouse link (`inventory الاذن #8996`), created time
    2. `معلومات التوصيل`: Delivery agent, address
    3. `حساب المورد`: Overdue debt, current balance, credit limit, link to vendor statement (`معاينة`)
    4. `جهة الاتصال`: Supplier profile, phones, addresses, and related branches
    5. `بيانات التعديل`: Audit timestamps

### 2.3 Purchase Order Creation Form (`/purchase-orders/create`)

- **URL**: `https://weapharma.bricks-rep.com/purchase-orders/create`
- **Two-Step Dynamic Flow**:
  - **Step 1**: Searchable supplier selector (`جهة الاتصال: بحث...`).
  - **Step 2 (Revealed on Supplier Selection)**:
    - Target warehouse selector (`مخزن الاستلام`)
    - Order date & Delivery due date
    - Dynamic line item repeater:
      - Product dropdown
      - Unit cost price
      - Quantity
      - Item discount
      - Batch number
      - Expiry date
    - Custom order discount & Shipping fees
    - Internal notes
    - Save draft / submit buttons

### 2.4 Vendor Payments (`/vendor-payments`)

- **URL**: `https://weapharma.bricks-rep.com/vendor-payments`
- **Page Title**: `المدفوعات`
- **Top Actions**: `مدفوعة جديدة`, `تصدير البيانات`, `filter_list`
- **Table Headers (RTL)**:
  1. `رقم المسلسل` (Serial `#10027`)
  2. `الاسم` (Supplier Name)
  3. `المنطقة` (Area)
  4. `انشئ فى` (Date)
  5. `المبلغ` (Amount EGP)
  6. `المنشئ` (Created by)
- **New Vendor Payment Modal**:
  - Fields: Supplier, Amount, Vault/Safe, Payment Method, Date, Notes.

### 2.5 Vendor Statements & Accounts (`/accounting/vendors`)

- **URL**: `https://weapharma.bricks-rep.com/accounting/vendors`
- **Page Title**: `حسابات الموردين`
- **Table Headers (RTL)**:
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

### 2.6 Vendor Transactions (`/accounting/vendor-transactions`)

- **URL**: `https://weapharma.bricks-rep.com/accounting/vendor-transactions`
- **Page Title**: `عمليات الموردين`
- **Table Headers (RTL)**:
  1. `اسم الحساب`, 2. `التاريخ`, 3. `توصيف`, 4. `مديونية متأخرة؟`, 5. `تاريخ الاستحقاق`, 6. `دائن`, 7. `مدين`, 8. `الرصيد`, 9. `ملاحظة`, 10. `انشئ فى`, 11. `انشئ بواسطة`, 12. `المديونية`, 13. `الأيام المعلّقة`
