# Settings Module Page Inventory

> **System**: WEA Pharma ERP  
> **Reference Base URL**: `https://weapharma.bricks-rep.com/`  
> **Inspection Date**: October 2026  
> **Methodology**: Non-mutating read-only live crawler & DOM inspection with screenshot verification.  
> **Scope Exclusions**: Calls and Assessments are strictly excluded from scope.

---

## 1. Inventory Summary Table

| Index | Page Name (Arabic) | Path / URL | Scope Status | Primary Entity / Model | CRUD Operations Supported | Priority |
|---|---|---|---|---|---|---|
| 1 | المستخدمون (User Accounts) | `/settings/users` | In-Scope | `User`, `Role` | List, Create, Edit, Toggle Status, Password Reset, Export | P0 |
| 2 | أدوار المستخدمين (Roles & Permissions) | `/settings/roles` | In-Scope | `Role`, `Permission` | List, Create, Edit, Duplicate, Delete Custom Roles | P0 |
| 3 | تعديل دور المستخدم (Role Dossier) | `/settings/roles/edit/<id>` | In-Scope | `Role`, `Permission`, `RoleTag` | View, Update Attributes, Assign Tags, Toggle Permissions | P0 |
| 4 | إعدادات الموقع (Location Settings) | `/settings/location` | In-Scope | `LocationSettings` | View, Update GPS Parameters & Workflow Verification | P1 |
| 5 | المناطق (Areas & Territories) | `/settings/areas` | In-Scope | `Area` | Hierarchical List, Create Area, Create Subarea, Edit, Delete | P1 |
| 6 | انواع المصروفات (Expense Types) | `/settings/expenses` | In-Scope | `ExpenseType` | List (General & Visit Tabs), Create, Edit, Delete | P1 |
| 7 | اعدادات المهام (Ticket Settings) | `/settings/tickets` | In-Scope | `TicketType` | List Task Types, Create, Edit, Delete | P2 |
| 8 | اعدادات الموافقات (Approval Settings) | `/settings/requests` | In-Scope | `ApprovalRequestType` | List Request Types, Create, Edit, Delete | P2 |
| 9 | انواع الاتفاقيات (Agreement Types) | `/settings/agreements` | In-Scope | `AgreementType` | List Agreement Types, Create, Edit, Delete | P2 |
| 10 | إعدادات المبيعات (Sales Settings) | `/settings/sales` | In-Scope | `SalesSettings` | View, Update Workflow Automation, Taxes, Packaging | P1 |
| 11 | إعدادات المشتريات (Purchase Settings) | `/settings/purchase` | In-Scope | `PurchaseSettings` | View, Update Invoicing, Payment Closing, Taxes, Packaging | P1 |
| 12 | اعدادات المخازن (Inventory Settings) | `/settings/inventory` | In-Scope | `InventorySettings` | View, Update Batch & Expiry Mandatory Policies | P1 |
| 13 | تخصيص حقول جهات الاتصال (Contacts UDF) | `/settings/contacts-udf` | In-Scope | `ContactFieldSetting` | View, Configure Field Visibility, Requirements, Filterability | P2 |
| 14 | اعدادات بيانات الشركة (Company Branding) | `/settings/branding` | In-Scope | `CompanyProfile` | View, Update Legal Name, Tax ID, Phone, Address, Logo | P1 |
| 15 | مزامنة البيانات (Sync Data) | `/settings/sync-data` | In-Scope | `DataSyncConfig` | View, Configure Google Sheets URLs, Trigger Sync | P2 |
| - | المكالمات (Calls) | `/settings/calls` | **EXCLUDED** | N/A | Excluded from scope per prompt requirements | - |
| - | التقييمات (Assessments) | `/settings/assessments` | **EXCLUDED** | N/A | Excluded from scope per prompt requirements | - |

---

## 2. Page Dossiers

### 2.1 Users (`/settings/users`)
- **Breadcrumb**: الرئيسية / الإعدادات / المستخدمون
- **Title**: `المستخدمون`
- **Actions Bar**:
  - `اضف مستخدم` (Add User button - opens modal)
  - `تصدير البيانات` (Export Data - Excel/CSV)
  - Filter toggle & Search input (`بحث`)
- **Table Columns**:
  1. `الاسم` (Full Name with hyperlink to edit/detail)
  2. `البريد الإلكتروني` (Email address)
  3. `مفعل` (Active status - checkmark badge)
  4. `الدور` (Assigned role title, e.g. `MedicalRep`, `Accountant`, `CEO`, `SuperAdmin`)
- **Add User Modal (`إضافة مستخدم جديد`) Fields**:
  - `الاسم*`: Required text
  - `البريد الإلكتروني*`: Required email
  - `الكود`: Optional user identifier
  - `كلمة المرور*`: Required password
  - `الدور*`: Required select dropdown of active system roles
  - `حفظ`: Submit button (disabled if required fields invalid)
- **Security & Authorization**: SuperAdmin or HR/Admin roles only.

### 2.2 Roles & Permissions (`/settings/roles`)
- **Breadcrumb**: الرئيسية / الإعدادات / أدوار المستخدمين
- **Title**: `أدوار المستخدمين`
- **Actions Bar**: `إنشاء دور` (Create Role)
- **Table Columns**:
  1. `المعرف` (Code/identifier, e.g. `Accountant`, `Admin`, `AreaManager`, `DirectSalesRep`, `SuperAdmin`)
  2. `الاسم` (Display name)
  3. `مفعل` (Active status checkmark)
  4. `إجراءات` (Pencil for Edit, Copy icon for Duplicate)
- **Edit Role Page (`/settings/roles/edit/<id>`)**:
  - `الاسم*`: Role title text
  - **Attributes Switches**:
    - Right Column: `سوبر` (is_super), `مسئول جهات الاتصال` (is_contact_manager), `تابع لمنطقة رئيسية` (is_main_area_bound), `تابع لمنطقة فرعية` (is_sub_area_bound), `مندوب` (is_rep), `مفعل` (is_active)
    - Left Column: `فريق المبيعات` (is_sales_team), `مدير لمنطقة رئيسية` (is_area_manager), `مدير منطقة فرعية` (is_sub_area_manager), `له أهداف مبيعات` (has_sales_targets)
  - **Tags Dropdown (`العلامات`)**:
    - `customers:customers/bypassLocation`
    - `accounting:vaults/assignable`
    - `expenses:expenses/assignable`
    - `locationTracking:users/trackable`
    - `sales:receiptBooks/assignable`
    - `tickets:todos/restrictOwner`
  - **Permissions Matrix (`الصلاحيات`)**:
    - Module blocks: `accounting`, `agreements`, `contacts`, `customers`, `inventory`, `locationTracking`, `purchase`, `sales`, `system`, `tickets`, `users`, `workflowActions`
    - Module header buttons: `أدمن` (All), `افتراضي` (Default), `قراءة فقط` (Read-only), Expand arrow (`>`)

### 2.3 Company Branding (`/settings/branding`)
- **Breadcrumb**: الرئيسية / الإعدادات / اعدادات بيانات الشركة
- **Title**: `اعدادات بيانات الشركة`
- **Fields**:
  - `الاسم`: e.g. "WEA"
  - `تليفون`: e.g. "01111787179 - 01024070412"
  - `العنوان`: e.g. "173 ز - البوابة الأولى- حدائق الأهرام"
  - `المعرف الضريبي`: e.g. "بطاقة ضريبية 978 - 339 - 684"
  - `معلومات الاتصال`: e.g. "Wea.pharm2020@gmail.com"
  - `شعار الشركة`: Logo upload with image preview and change trigger
  - `حفظ`: Save changes button

### 2.4 Location Settings (`/settings/location`)
- **Breadcrumb**: الرئيسية / الإعدادات / اعدادات الموقع
- **Title**: `اعدادات الموقع`
- **General GPS Fields**:
  - `سماحية الموقع`: Meter tolerance (default 300)
  - `الحد الأقصى للدقة المحققة`: Max accuracy (default 50)
  - `الحد الأقصى للدقة المحققة (مع التحذير)`: Warning accuracy threshold (default 100)
  - `تشغيل تلقائي لمتابعة الموقع`: Toggle (default ON)
  - `حفظ موقع العميل بشكل تلقائى مع أول زيارة`: Toggle (default ON)
- **Workflow Location Verification**:
  - `الزيارات*`: Select (التحقق من الموقع / تعطيل التحقق)
  - `اوامر البيع*`: Select (تعطيل التحقق / التحقق من الموقع)
  - `المرتجعات*`: Select (تعطيل التحقق / التحقق من الموقع)

### 2.5 Areas (`/settings/areas`)
- **Breadcrumb**: الرئيسية / الإعدادات / المناطق
- **Title**: `المناطق`
- **Actions Bar**: `منطقة جديدة` (New Area button)
- **Tree Structure**: Collapsible cards displaying area name and code (e.g. `WEA Stores Great cairo [31]`, `محافظة اسوان [23]`), with 3-dot menu: Add Subarea, Edit, Delete.

### 2.6 Expense Types (`/settings/expenses`)
- **Breadcrumb**: الرئيسية / الإعدادات / انواع المصروفات
- **Title**: `انواع المصروفات`
- **Tabs**:
  1. `مصروفات عامة` (General Expenses)
  2. `مصروفات للزيارات فقط` (Visit Expenses)
- **Actions Bar**: `أضف نوع جديد` (Add New Type button)
- **Item Cards**: Delete icon, Edit icon, Name in Arabic & English, Unit label (`الوحدة: `).

### 2.7 Ticket Settings (`/settings/tickets`)
- **Breadcrumb**: الرئيسية / الإعدادات / اعدادات المهام
- **Title**: `اعدادات المهام` - `انواع المهام`
- **Actions Bar**: `اضف نوع جديد` (Add New Type button)
- **Item Cards**: Name, Default badge (`افتراضي`) or action buttons.

### 2.8 Approval Settings (`/settings/requests`)
- **Breadcrumb**: الرئيسية / الإعدادات / اعدادات الموافقات
- **Title**: `اعدادات الموافقات` - `انواع الموافقات`
- **Actions Bar**: `اضف نوع جديد` (Add New Type button)
- **Pre-populated Types**: Absent day, Off day, Admin work, Admin work [AM], Admin work [PM], Area manager plan, Coaching Report, District manager plan.

### 2.9 Agreement Types (`/settings/agreements`)
- **Breadcrumb**: الرئيسية / الإعدادات / انواع الاتفاقيات
- **Title**: `انواع الاتفاقيات`
- **Actions Bar**: `أضف نوع جديد` (Add New Type button)
- **Pre-populated Types**: Conference, Cash money, Devices, Gifts, RTD, Rx, Others.

### 2.10 Sales Settings (`/settings/sales`)
- **Breadcrumb**: الرئيسية / الإعدادات / إعدادات المبيعات
- **Title**: `إعدادات المبيعات`
- **Workflow Automation Switches**:
  - `مسؤول التحقيق مطلوب في أمر البيع`
  - `عمل فاتورة بشكل تلقائي عند الاخراج من المخزن` (default ON)
  - `عمل فاتورة بشكل تلقائي عند الارجاع الى المخزن` (default ON)
  - `تحصيل الدفعة عند فوترة الطلب` (default ON)
  - `ربط بالحسابات تلقائي عند إنشاء التحصيل` (default ON)
  - `استخدم دفاتر إيصالات التحصيلات` (default OFF)
  - `غلق تلقائي لطلب التحصيل النقدي` (default ON)
  - `غلق تلقائي لطلب التحصيل عند السداد كاملا` (default ON)
- **Tax Policy**: `نمط الضريبة*` dropdown (اختياري / إلزامي / معفى)
- **Packaging Unit**: `حجم التعبئة الافتراضي*` dropdown (علبة / شريط / قطعة / كرتونة)
- **Print Templates**: Sales Orders template config

### 2.11 Purchase Settings (`/settings/purchase`)
- **Breadcrumb**: الرئيسية / الإعدادات / إعدادات المشتريات
- **Title**: `إعدادات المشتريات`
- **Workflow Automation Switches**:
  - `عمل فاتورة بشكل تلقائى عند الاخراج من المخزن` (default ON)
  - `عمل فاتورة بشكل تلقائى عند الارجاع الى المخزن` (default ON)
  - `تحصيل الدفعة عند فوترة الطلب` (default OFF)
  - `ربط بالحسابات تلقائى عند إنشاء المدفوعات` (default ON)
  - `إغلاق تلقائي لطلبات الدفع النقدي` (default ON)
  - `إغلاق تلقائي لطلبات الدفع عند السداد كاملا` (default ON)
- **Tax Policy**: `نمط الضريبة*` dropdown (اختياري / إلزامي / معفى)
- **Packaging Unit**: `حجم التعبئة الافتراضي*` dropdown (قطعة / علبة / كرتونة)

### 2.12 Inventory Settings (`/settings/inventory`)
- **Breadcrumb**: الرئيسية / الإعدادات / اعدادات المخازن
- **Title**: `اعدادات المخازن`
- **Policy Switches**:
  - `استخدم تاريخ الصلاحية` (default ON)
  - `تاريخ الصلاحية مطلوب` (default OFF)
  - `استخدم رقم التشغيل` (default ON)
  - `رقم التشغيل مطلوب` (default OFF)

### 2.13 Contact Custom Fields (`/settings/contacts-udf`)
- **Breadcrumb**: الرئيسية / الإعدادات / تخصيص حقول جهات الاتصال
- **Title**: `تخصيص حقول جهات الاتصال`
- **Groups**: Header fields, Subheader fields, Basic info
- **Attributes**: Locked (`مغلق`), Required (`مطلوب`), Filterable (`قابلة للتصفية`), Core (`اساسي`), Builtin (`مدمج`).

### 2.14 Data Sync (`/settings/sync-data`)
- **Breadcrumb**: الرئيسية / الإعدادات / مزامنة البيانات
- **Sections**:
  1. `إستيراد جهات الاتصال` (Google Sheets URL, Sync Now, Delete, Edit)
  2. `إستيراد المنتجات` (Google Sheets URL, Add/Edit)
  3. `مزامنة المناطق` (Google Sheets URL, Sync Now, Delete, Edit)
