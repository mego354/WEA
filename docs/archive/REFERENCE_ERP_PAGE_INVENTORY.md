# Reference ERP Page Inventory

> **System**: Bricks Rep / WEA Pharma ERP  
> **Source Base URL**: `https://weapharma.bricks-rep.com/`  
> **Analysis Date**: October 2026  
> **Discovery Method**: Safe, Non-Mutating Read-Only Crawler & Protocol Inspection (Playwright & API Reverse Engineering)

---

## Priority Classification Framework

- **P0 (Critical / Core Foundation & Transactions)**: Authentication, User & Role RBAC, Master Contacts (Suppliers & Customers), Master Products/Catalog, Purchase Orders, Purchase Invoices, Stock Receipts, Supplier Ledger & Payments.
- **P1 (Important Business Functionality)**: Sales Orders, Sales Invoices, Customer Collections & Balances, Warehouses & Basic Stock Transfers/Memos, Cash Safes/Vaults & Cash Transactions, Core Financial & Stock Reports.
- **P2 (Secondary Functionality)**: Purchase Returns, Sales Returns, Bundles & Price Lists, Stock Adjustments, Expense Management, Activity Logging & Auditing.
- **P3 (Nice-to-Have / Low Priority / Mobile Field Specific)**: Rep Geofencing & GPS tracking, Rep Visit Check-in/Check-out Questionnaires, Rep Call Logs, Rep Annual Off-Days, Rep Daily Targets, Troubleshooting logs.

---

## 1. Authentication & System Foundation

### 1.1 Login Page
- **Module**: Authentication
- **Submodule**: Security & Session
- **Page Name**: تسجيل الدخول (Login)
- **URL / Path**: `/auth/login?returnUrl=%2Fhome`
- **Purpose**: Authenticate enterprise users via email and password; generate JWT access session.
- **Navigation Location**: Direct entrypoint / Redirect on unauthenticated request.
- **Main Entities Displayed**: Login form with email and password inputs, show/hide password toggle, Login button, branding logo.
- **Available Actions**: Enter credentials, Toggle password visibility, Submit credentials (`POST /api/v1/auth/signin`), Redirect to dashboard.
- **Filters**: None.
- **Search**: None.
- **Table Columns**: N/A.
- **Forms**:
  - `email`: Text input, email formatted.
  - `current-password`: Password input with reveal toggle.
- **Important Fields**: `email`, `password`.
- **Relationships**: Authenticates `User`, returns JWT bearer token associated with `Role` and `Workspace`.
- **Statuses**: Authenticated, Invalid Credentials (401), Session Expired.
- **User Roles with Access**: All active users.
- **Mutation Type**: Mutation (Session creation only; non-destructive).
- **Implementation Priority**: **P0**

### 1.2 User Profile & Session Refresh
- **Module**: Authentication
- **Submodule**: Session Management
- **Page Name**: بيانات الحساب والملف الشخصي (User Session & Profile)
- **URL / Path**: `/api/v1/users/current`, `/api/v1/auth/refresh`
- **Purpose**: Retrieve current user profile, avatar, workspace locale (Currency `EGP`, Timezone `Africa/Cairo`), role attributes, and 800+ granular permission keys.
- **Navigation Location**: Top Header Profile Avatar & User Dropdown.
- **Main Entities Displayed**: User avatar, user name (e.g. `Dr.wael Atta (CEO)`), Role title (`SuperAdmin`), unread notifications count badge (`105`).
- **Available Actions**: View profile, Switch language (`ar` / `en`), Logout.
- **Implementation Priority**: **P0**

---

## 2. User Management & Access Control (RBAC)

### 2.1 Roles & Permissions List
- **Module**: Settings / الإعدادات
- **Submodule**: Access Control / الصلاحيات
- **Page Name**: الصلاحيات والأدوار (Roles & Permissions)
- **URL / Path**: `/settings/roles`
- **Purpose**: Define, inspect, and configure user roles, role tags, and granular module permissions.
- **Navigation Location**: Sidebar -> الإعدادات -> الصلاحيات (`/settings/roles`)
- **Main Entities Displayed**: System roles (`SuperAdmin`, `Accountant`, `Sales Manager`, `Medical Rep`, etc.), user counts per role, role descriptions.
- **Available Actions**: Add New Role (`اضف دور جديد`), Edit Role (`edit`), View Role Permissions, Delete Custom Role.
- **Filters**: Search role by name.
- **Table Columns**:
  - اسم الدور (Role Name)
  - التوصيف (Description)
  - عدد المستخدمين (Assigned Users Count)
  - نوع الدور (Role Type / System vs Custom)
  - تاريخ الإنشاء (Created At)
  - إجراءات (Actions Menu)
- **Relationships**: `Role` has many `Users`, `Role` has granular `Permissions` (dictionary of permission strings: e.g. `purchase:purchaseOrders/create`).
- **Statuses**: System Locked vs Customizable.
- **User Roles with Access**: SuperAdmin.
- **Mutation Type**: Contains mutation controls (Add/Edit role).
- **Implementation Priority**: **P0**

### 2.2 User Management
- **Module**: Settings / الإعدادات
- **Submodule**: Users / المستخدمون
- **Page Name**: إدارة المستخدمين (User Accounts)
- **URL / Path**: `/settings/users`
- **Purpose**: Manage enterprise staff, managers, accountants, warehouse keepers, and field reps.
- **Navigation Location**: Sidebar -> الإعدادات -> المستخدمون (`/settings/users`)
- **Main Entities Displayed**: User accounts, contact details, assigned role, active/inactive status, assigned branch/area.
- **Available Actions**: Add User (`اضف مستخدم`), Edit User, Activate/Deactivate, Reset Password, Filter by Role/Status.
- **Filters**: Status (Active/Inactive), Role, Branch/Governorate.
- **Table Columns**:
  - المستخدم (User Name & Avatar)
  - البريد الإلكتروني (Email)
  - رقم الهاتف (Mobile)
  - الدور الوظيفي (Role)
  - الحالة (Status: Active / Inactive)
  - تاريخ الإنشاء (Created At)
  - إجراءات (Actions)
- **Forms**:
  - Name, Email, Mobile, Password, Role Dropdown, Area/Branch Multi-select, Avatar Upload.
- **Relationships**: Belongs to `Role`, belongs to `Workspace`, manages `Areas` / `Vaults` / `Warehouses`.
- **User Roles with Access**: SuperAdmin, HR/Admin Manager.
- **Implementation Priority**: **P0**

---

## 3. Contacts Master Data (Suppliers & Customers)

### 3.1 Contacts Directory
- **Module**: Contacts / جهات الاتصال
- **Submodule**: Contacts Directory
- **Page Name**: جهات الاتصال (Contacts Directory)
- **URL / Path**: `/contacts`
- **Purpose**: Master registry of all business parties: Suppliers (موردين), Pharmacies & Clinics (عملاء / صيدليات), Wholesalers, and Institutions.
- **Navigation Location**: Sidebar -> جهات الاتصال (`/contacts`)
- **Main Entities Displayed**: Contact records (8,890+ records in reference system), business relation tags (`vendor`, `customer`), serial numbers (`#16456`), assigned territory areas, contact ranks, credit limits.
- **Available Actions**:
  - إضافة جهة اتصال (Add Contact)
  - تصدير البيانات (Export Excel/CSV)
  - تصفية / فلتر (Filter drawer with presets: e.g. `موردين` / `عملاء`)
  - طباعة (Print)
  - عرض التفاصيل (View Details Modal / Page)
- **Filters**:
  - علاقة العمل (Business Relation: `vendor`, `customer`)
  - المنطقة / المحافظة (Area / Governorate)
  - الحالة (Status: Active, Lead, Inactive)
  - الرتبة (Rank / Tier: A, B, C)
  - البحث بالاسم أو الكود أو الهاتف
- **Table Columns**:
  - رقم المسلسل (Serial Number: `#16456`)
  - الاسم (Contact / Facility Name)
  - نوع الحساب (Individual / Company)
  - علاقة العمل (Business Relation: مورد / عميل)
  - المنطقة (Area / Subarea: محافظة الجيزة / المناشى)
  - العنوان الرئيسي (Main Address)
  - الهاتف (Mobile / Phone)
  - الحالة (Status: Active / Lead)
  - إجراءات (Actions)
- **Forms**:
  - Name, Contact Type (`individual` | `company`), Business Relation (`customer`, `vendor`), Mobile, Phone, Email, Area Dropdown, Street Address, Tax ID, Commercial Register, Credit Limit, Payment Terms / Due Days.
- **Relationships**:
  - Has many `Addresses`
  - Has one `VendorAccount` (in Supplier Accounting)
  - Has one `CustomerAccount` (in Customer Accounting)
  - Has many `PurchaseOrders` (if vendor)
  - Has many `SalesOrders` (if customer)
- **User Roles with Access**: SuperAdmin, Accountant, Sales Manager, Rep.
- **Implementation Priority**: **P0**

### 3.2 Supplier Accounts (Vendor Accounting)
- **Module**: Purchases & Accounting / المشتريات والحسابات
- **Submodule**: حسابات الموردين (Vendor Accounts)
- **Page Name**: حسابات الموردين (Vendor Statements & Balances)
- **URL / Path**: `/accounting/vendors`
- **Purpose**: Financial tracking of all supplier credit limits, outstanding debts, days overdue, and aged payable balances.
- **Navigation Location**: Sidebar -> المشتريات -> حسابات الموردين (`/accounting/vendors`)
- **Main Entities Displayed**: Supplier ledger accounts, current balance, credit limits, overdue debt amounts and dates.
- **Available Actions**: إنشاء عملية جديدة (New Manual Voucher/Adjustment), كشف حساب (Statement of Account), تصدير (Export), فلترة (Filter).
- **Table Columns**:
  - اسم الحساب (Vendor Account Name)
  - حد الائتمان (Credit Limit)
  - مدة الائتمان (Credit Days)
  - الرصيد (Current Balance EGP)
  - قيمة أقدم مديونية (Oldest Open Debt Amount)
  - تاريخ أقدم مديونية (Oldest Open Debt Date)
  - قيمة المديونية المتأخرة (Overdue Amount)
  - تاريخ المديونية المتأخرة (Overdue Date)
  - تاريخ آخر عملية (Last Transaction Date)
  - أيام المبيعات المعلّقة (Days Outstanding)
- **Implementation Priority**: **P0**

### 3.3 Supplier Transactions (Vendor Ledger Transactions)
- **Module**: Purchases & Accounting / المشتريات والحسابات
- **Submodule**: عمليات الموردين (Vendor Ledger Transactions)
- **Page Name**: عمليات الموردين (Vendor Transaction Records)
- **URL / Path**: `/accounting/vendor-transactions`
- **Purpose**: Granular double-entry debit/credit ledger records for supplier invoices, payments, adjustments, and returns.
- **Navigation Location**: Sidebar -> المشتريات -> عمليات الموردين (`/accounting/vendor-transactions`)
- **Main Entities Displayed**: Ledger vouchers, reason (`purchase`, `purchase_payments`, `adjustment`), debit, credit, balance.
- **Table Columns**:
  - اسم الحساب (Vendor Account Name)
  - التاريخ (Transaction Date)
  - توصيف (Description / Invoice or Payment ref)
  - مديونية متأخرة؟ (Is Overdue?)
  - تاريخ الاستحقاق (Due Date)
  - دائن (Credit: Invoice amount owed to supplier)
  - مدين (Debit: Payment made to supplier)
  - الرصيد (Running Balance)
  - ملاحظة (Notes)
  - انشئ فى (Created At)
  - انشئ بواسطة (Created By User)
  - المديونية (Debt details)
  - الأيام المعلّقة (Days Pending)
- **Implementation Priority**: **P0**

---

## 4. Products Master Data & Catalog

### 4.1 Products Registry
- **Module**: Products / المنتجات
- **Submodule**: Catalog / قائمة المنتجات
- **Page Name**: المنتجات (Products Catalog)
- **URL / Path**: `/products`
- **Purpose**: Maintain pharmaceutical and cosmetic products, SKU codes, retail prices, purchase costs, tax rates, packaging, and thumbnails.
- **Navigation Location**: Sidebar -> المنتجات -> المنتجات (`/products`)
- **Main Entities Displayed**: Products, category tag, SKU code (`GE1`), retail price, default cost, stock availability, active status.
- **Available Actions**: إضافة منتج (Add Product), تعديل (Edit), تصدير (Export), فلترة (Filter), إلغاء التفعيل (Deactivate).
- **Filters**: Category, In Stock (Yes/No), Sellable (Yes/No), Search by Name/Code.
- **Table Columns**:
  - الصورة (Thumbnail Image)
  - الاسم (Product Name)
  - الكود (SKU Code)
  - التصنيف (Category)
  - سعر البيع (Retail Price EGP)
  - التكلفة الافتراضية (Default Cost EGP)
  - نسبة الضريبة (Tax Percentage)
  - في المخزن (In Stock status)
  - قابل للبيع (Sellable status)
  - إجراءات (Actions)
- **Forms**:
  - Product Name (Arabic/English), SKU Code, Category Dropdown, Retail Price, Tax Percentage (0% or standard), Description, Sellable Checkbox, Main Image / Thumbnail upload, Default Unit/Packaging.
- **Relationships**:
  - Belongs to `ProductCategory`
  - Has many `InventoryStock` entries across warehouses
  - Has many `PurchaseOrderItems`
  - Has many `SalesOrderItems`
- **Implementation Priority**: **P0**

### 4.2 Product Categories
- **Module**: Products / المنتجات
- **Submodule**: Categories / التصنيفات
- **Page Name**: التصنيفات (Product Categories)
- **URL / Path**: `/product-categories`
- **Purpose**: Group products into medical/commercial categories (e.g. `WEA`, `Cosmetics`, `Antibiotics`).
- **Navigation Location**: Sidebar -> المنتجات -> التصنيفات (`/product-categories`)
- **Table Columns**:
  - الاسم (Category Name)
  - الكود (Category Code)
  - التوصيف (Description)
  - انشئ فى (Created At)
  - إجراءات (Actions)
- **Implementation Priority**: **P0**

---

## 5. Purchases (P0 Core Transaction Engine)

### 5.1 Purchase Orders Listing
- **Module**: Purchases / المشتريات
- **Submodule**: Purchase Orders / أوامر المشتريات
- **Page Name**: أوامر المشتريات (Purchase Orders)
- **URL / Path**: `/purchase-orders`
- **Purpose**: Central hub for purchasing from manufacturers and suppliers. Lists all purchase orders, tracking warehouse receipts and invoice settlements.
- **Navigation Location**: Sidebar -> المشتريات -> الطلبات (`/purchase-orders`)
- **Main Entities Displayed**: Orders list, order numbers (`#16`), supplier name, total amount, status (`Pending`, `Approved`, `Picked`, `Settled`, `Rejected`, `Split`), creator, area.
- **Available Actions**:
  - أمر مشتريات جديد (New Purchase Order)
  - تصدير البيانات (Export Excel)
  - اطبع (Print Batch)
  - فلتر (Filters Drawer)
  - عرض تفاصيل الطلب (Click order row to view detail page)
- **Filters**:
  - الحالة (Status: Pending, Approved, Picked, Settled, Rejected, Split)
  - المورد (Supplier / Contact)
  - نطاق التاريخ (Date range: From / To)
  - المنشئ (Created By User)
  - المنطقة (Area)
- **Table Columns**:
  - رقم المسلسل (Order Serial: `#16`)
  - الاسم (Supplier Name)
  - المنطقة (Area / Territory)
  - انشئ فى (Created At Date/Time)
  - المنشئ (Created By User & Role)
  - الحالة (Status Badge: Settled, Picked, Pending, etc.)
  - اجمالى القيمة (Total Grand Amount EGP)
  - مسئول التوصيل (Delivery / Receiving Agent)
  - وقت التوصيل (Delivery Time)
- **Relationships**: Belongs to `Contact` (Supplier), created by `User`, links to `InventoryMemo` (on stock receipt), links to `VendorTransaction` (on invoice).
- **Implementation Priority**: **P0**

### 5.2 Purchase Order Detail & Lifecycle View
- **Module**: Purchases / المشتريات
- **Submodule**: Purchase Order View
- **Page Name**: تفاصيل أمر الشراء (Purchase Order Details & Actions)
- **URL / Path**: `/purchase-orders/{id}`
- **Purpose**: Complete order dossier displaying line items, batch numbers, expiry dates, supplier address, financial calculation summary, stock receipt memo, linked vendor accounting invoice, attachments, and state transition actions.
- **Navigation Location**: Accessible by clicking any row in `/purchase-orders`.
- **Main Entities Displayed**:
  - Order Header: Serial `#16`, Supplier Name, Status Badge (`Settled`), Creator, Date.
  - Line Items Table: Product name, SKU, Quantity, Unit Purchase Price, Batch Number, Expiry Date, Subtotal, Discounts, Total.
  - Price Summary Card: Subtotal before tax, Tax Amount, Custom Discounts, Shipping Fees (`400 EGP`), Grand Total (`58,849.20 EGP`).
  - Linked Accounting Card: Invoice Transaction ID, Invoice Date, Due Date, Total Amount, Closed Amount, Open Balance.
  - Linked Warehouse Memo Card: Memo ID, Warehouse Name, Stocked At timestamp.
  - Attachments Card: Supplier tax invoices (JPEG/PDF), voice notes, file download links.
- **Available Actions**:
  - Status Dropdown (`Pending` -> `Approved` -> `Picked` [Stock into inventory] -> `Settled` [Post invoice])
  - الغاء الفاتورة / Undo Invoice (Reverts accounting transaction back to Picked)
  - طباعة (Print official Purchase Order / Receipt Voucher)
  - تعديل (Edit Order - allowed in Pending status)
  - إلغاء (Cancel Order / Uncancel)
  - فصل الطلب (Split Order)
  - إرفاق ملف / صورة فاتورة المورد (Upload Attachment)
- **Implementation Priority**: **P0**

### 5.3 Purchase Order Creation Form
- **Module**: Purchases / المشتريات
- **Submodule**: New Order
- **Page Name**: أمر مشتريات جديد (Create Purchase Order)
- **URL / Path**: `/purchase-orders/create` (or modal form)
- **Purpose**: Create a new purchase order draft with a selected supplier, target warehouse, line items, batch/expiry info, and price adjustments.
- **Forms**:
  - Supplier Select (Search contacts with relation `vendor`)
  - Target Warehouse Select
  - Order Date & Delivery Due Date
  - Items Dynamic Repeater:
    - Product Select
    - Quantity
    - Unit Cost Price
    - Batch Number (Optional / Mandatory per settings)
    - Expiry Date (Optional / Mandatory per settings)
    - Item Discount (Percentage or Fixed)
  - Order-level Custom Discount
  - Shipping Fees
  - Notes / Memo
- **Validation**: Requires valid supplier, at least 1 item, positive quantity and price.
- **Implementation Priority**: **P0**

### 5.4 Vendor Payments (المدفوعات)
- **Module**: Purchases & Accounting / المشتريات
- **Submodule**: Vendor Payments / المدفوعات
- **Page Name**: المدفوعات (Supplier Payments)
- **URL / Path**: `/vendor-payments`
- **Purpose**: Record payments made to suppliers against open purchase invoices, linking cash vaults/safes to vendor ledgers.
- **Navigation Location**: Sidebar -> المشتريات -> المدفوعات (`/vendor-payments`)
- **Main Entities Displayed**: Payment serial, supplier name, amount paid, payment method (Cash / Cheque / Bank Transfer), paying vault/safe, status (`Pending`, `Cleared`), creator.
- **Available Actions**:
  - مدفوعة جديدة (New Vendor Payment)
  - تصدير البيانات (Export)
  - ربط بالحسابات (Link to Accounting)
  - طباعة سند صرف (Print Payment Voucher)
- **Table Columns**:
  - رقم المسلسل (Serial Number: `#10027`)
  - الاسم (Supplier Name)
  - المنطقة (Area)
  - انشئ فى (Payment Date)
  - المبلغ (Paid Amount EGP)
  - المنشئ (Paid By User)
  - الخزنة / وسيلة الدفع (Vault / Method: Cash / Cheque)
  - الحالة (Status: Cleared / Pending)
- **Relationships**: Debits `VendorAccount`, credits `Vault` (Cash Safe), generates `Settlement` records linking to open `PurchaseOrder` invoice installments.
- **Implementation Priority**: **P0**

### 5.5 Vendor Payment Requests (طلبات الدفع)
- **Module**: Purchases / المشتريات
- **Submodule**: Payment Requests / طلبات الدفع
- **Page Name**: طلبات الدفع (Vendor Payment Requests)
- **URL / Path**: `/vendor-payment-requests`
- **Purpose**: Internal workflow allowing purchasing staff to request payment approval from management/finance before releasing funds.
- **Table Columns**: Serial, Supplier, Area, Created At, Creator, Status (`Open`, `Done`, `Rejected`), Amount, Method, Responsible Person, Execution Date.
- **Implementation Priority**: **P1**

### 5.6 Purchase Return Orders (أوامر إرجاع المشتريات)
- **Module**: Purchases / المشتريات
- **Submodule**: Returns / المرتجعات
- **Page Name**: أوامر إرجاع المشتريات (Purchase Return Orders)
- **URL / Path**: `/purchase-return-orders`
- **Purpose**: Handle defective or expired goods returned to suppliers, decrementing inventory and generating debit notes on vendor accounts.
- **Table Columns**: Serial, Supplier, Area, Created At, Creator, Status (`Pending`, `Approved`, `Delivered` [Unstocked], `Settled` [Debit note invoiced]), Total Amount, Receiving Responsible, Receiving Time.
- **Implementation Priority**: **P2**

---

## 6. Warehouses & Inventory Management

### 6.1 Warehouses Registry
- **Module**: Inventory / المخازن
- **Submodule**: Warehouses / قائمة المخازن
- **Page Name**: المخازن (Warehouses Directory)
- **URL / Path**: `/inventory/warehouses`
- **Purpose**: Manage physical and regional storage locations (Main Warehouse, Van/Rep Mobile Warehouses, Quarantine, Returns Warehouse).
- **Table Columns**:
  - مخزن (Warehouse Name: e.g. `المخزن الرئيسي بضاعه`)
  - نوع المخزن (Warehouse Types: `sales`, `purchase`, `salesReturns`, `purchaseReturns`)
  - انشئ فى (Created At)
  - الحالة (Active: True/False)
  - إجراءات (Actions)
- **Implementation Priority**: **P1**

### 6.2 Inventory Stock Balances
- **Module**: Inventory / المخازن
- **Submodule**: Stock Balances / أرصدة المخزون
- **Page Name**: المخزون (Inventory Stock Balances)
- **URL / Path**: `/inventory/stock`
- **Purpose**: Real-time multi-warehouse stock levels, reserved quantities, available quantities, batches, expiration dates, unit costs, and total valuation.
- **Table Columns**:
  - المخزن (Warehouse Name)
  - الكود (SKU Code)
  - التصنيف (Category)
  - المنتج (Product Name)
  - تاريخ الصلاحية (Expiry Date)
  - التكلفة (Unit Cost EGP)
  - رقم التشغيل (Batch Number)
  - فى المخزن (Quantity on Hand)
  - محجوز (Reserved Quantity)
  - متاح (Available Quantity = On Hand - Reserved)
  - إجمالي التكلفة (Total Stock Cost = Qty * Cost)
  - سعر الوحدة (Unit Retail Price)
  - قيمة البيع (Total Retail Value)
- **Implementation Priority**: **P1**

### 6.3 Inventory Memos (Stock In & Stock Out Vouchers)
- **Module**: Inventory / المخازن
- **Submodule**: Memos / أذونات المخزن
- **Page Name**: الأذونات (Inventory In/Out Memos)
- **URL / Path**: `/inventory/memo`
- **Purpose**: Formal stock movement vouchers: Stock In (إذن إضافة) and Stock Out (إذن صرف/خصم) triggered by purchases, sales, or adjustments.
- **Table Columns**: Memo #, Memo Type (إضافة / خصم), Reason/Statement, Warehouse, Status (`Applied`, `Draft`, `Cancelled`), Created At, Notes.
- **Implementation Priority**: **P1**

### 6.4 Inventory Transfers (التحويلات بين المخازن)
- **Module**: Inventory / المخازن
- **Submodule**: Transfers / تحويلات المخازن
- **Page Name**: التحويلات (Warehouse Stock Transfers)
- **URL / Path**: `/inventory/transfer-memo`
- **Purpose**: Transfer products between main warehouse and mobile sales vans or branch warehouses.
- **Implementation Priority**: **P2**

---

## 7. Sales & Accounts Receivable

### 7.1 Sales Orders (أوامر البيع)
- **Module**: Sales / المبيعات
- **Submodule**: Sales Orders
- **Page Name**: أوامر البيع (Sales Orders)
- **URL / Path**: `/sales-orders`
- **Purpose**: Process customer orders from clinics, pharmacies, and wholesale buyers.
- **Workflow Lifecycle**: `Pending` -> `Manager Approval` -> `Preparing` (Reserves Stock) -> `Delivered` (Unstocks from Inventory) -> `Invoiced` (Debits Customer Account).
- **Table Columns**: Serial `#`, Customer Name, Area, Created At, Creator, Status (`Invoiced`, `Delivered`, `Preparing`, `Pending`), Total Amount, Delivery Agent, Delivery Time.
- **Implementation Priority**: **P1**

### 7.2 Customer Collections (التحصيلات)
- **Module**: Sales & Finance / المبيعات
- **Submodule**: Collections / التحصيلات
- **Page Name**: التحصيلات (Customer Debt Collections)
- **URL / Path**: `/collections`
- **Purpose**: Record cash and cheque collections from customers, updating customer account balances and receiving cash into vaults.
- **Table Columns**: Serial `#`, Customer Name, Amount EGP, Created At, Area, Account Type, Creator, Notes.
- **Implementation Priority**: **P1**

### 7.3 Customer Accounts (حسابات العملاء)
- **Module**: Sales & Accounting / المبيعات
- **Submodule**: Customer Accounts / حسابات العملاء
- **Page Name**: حسابات العملاء (Customer Statements & Aging)
- **URL / Path**: `/accounting/customers`
- **Purpose**: Monitor customer credit limits, overdue invoices, and accounts receivable aging.
- **Table Columns**: Customer Account Name, Credit Limit, Credit Days, Current Balance, Oldest Open Debt, Overdue Debt Amount, Overdue Date, Last Transaction Date, Days Outstanding.
- **Implementation Priority**: **P1**

---

## 8. Treasury, Safes & Cash Accounts (الخزن والمالية)

### 8.1 Cash Safes & Vaults
- **Module**: Treasury / الخزن
- **Submodule**: Vaults / الخزائن
- **Page Name**: الخزن (Treasury Cash Accounts & Safes)
- **URL / Path**: `/accounting/vaults/vaults`
- **Purpose**: Manage enterprise cash vaults: Main Company Safe, Branch Safes, Bank Accounts, and Individual Rep Petty Cash Safes.
- **Table Columns**:
  - اسم الخزنة (Vault / Account Name: e.g. `خزنة مندوب بني سويف`, `الخزنة الرئيسية`)
  - نوع الخزنة (Type: `cash`, `bank`)
  - مفعل (Is Active: True/False)
  - تابعة لمستخدم (Assigned User Safe: Yes/No)
  - المسئول (Assigned Custodian User)
  - الرصيد (Current Cash Balance EGP)
  - تاريخ اخر عملية (Last Transaction Date)
- **Implementation Priority**: **P1**

### 8.2 Vault Transactions (حركات الخزينة)
- **Module**: Treasury / الخزن
- **Submodule**: Transactions / حركات الخزن
- **Page Name**: العمليات (Cash Deposits, Withdrawals & Expenses)
- **URL / Path**: `/accounting/vaults/transactions`
- **Purpose**: Record all inflows (Collections, Capital deposits) and outflows (Vendor payments, Operating expenses, Petty cash withdrawals).
- **Implementation Priority**: **P1**

### 8.3 Vault Transfers (التحويلات بين الخزن)
- **Module**: Treasury / الخزن
- **Submodule**: Transfers / تحويلات النقدية
- **Page Name**: التحويلات (Cash Transfers between Safes)
- **URL / Path**: `/accounting/vaults/transfers`
- **Purpose**: Handing over cash from field sales reps into branch or main company safes.
- **Implementation Priority**: **P1**

---

## 9. Business Settings & Configuration

### 9.1 Company Branding & Invoicing Setup
- **Module**: Settings / الإعدادات
- **Submodule**: Branding / بيانات الشركة
- **Page Name**: بيانات الشركة (Company Profile & Invoice Headers)
- **URL / Path**: `/settings/branding`
- **Purpose**: Configure enterprise legal name (`WEA`), phones, corporate address, commercial registration (`184791`), tax card (`978-339-684`), logo, and tax settings.
- **Implementation Priority**: **P0**

### 9.2 Purchase Settings
- **Module**: Settings / الإعدادات
- **Submodule**: Purchase Settings
- **Page Name**: إعدادات المشتريات (Purchasing Policies)
- **URL / Path**: `/settings/purchase`
- **Purpose**: Global rules: Require batch number, require expiry date, default payment terms, auto-invoicing rules.
- **Implementation Priority**: **P0**

### 9.3 Inventory Settings
- **Module**: Settings / الإعدادات
- **Submodule**: Inventory Settings
- **Page Name**: إعدادات المخازن (Inventory Configurations)
- **URL / Path**: `/settings/inventory`
- **Purpose**: Configure batch tracking flags (`use_batch_number: true`), expiration tracking (`use_expiry_date: true`), negative stock prevention.
- **Implementation Priority**: **P0**

---

## 10. Reports & Analytics

### 10.1 Reports Dashboard
- **Module**: Reports / التقارير
- **Submodule**: Analytics & Statements
- **Page Name**: التقارير (Reports Center)
- **URL / Path**: `/reports`
- **Purpose**: Executive summaries: Purchase vs Sales analysis, Vendor balances statement, Customer aging statement, Stock valuation report, Cash flow summary.
- **Implementation Priority**: **P1**
