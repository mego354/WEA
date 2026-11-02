# Settings, Users, and Permissions Implementation TODO

> **Project**: WEA Pharma ERP  
> **Status Reporting Date**: October 2026  
> **Target Parity**: 100% Verified Parity with Reference ERP  
> **Explicit Exclusions**: Calls (`/settings/calls`) and Assessments (`/settings/assessments`) are strictly excluded.

---

## Task Matrix & Implementation Tracking

| Task ID | Feature / Page | Priority | Dependencies | Related Models | Required CRUD | Acceptance Criteria | Implementation Status | Testing Status | Notes / Uncertainty |
|---|---|---|---|---|---|---|---|---|---|
| **AUTH-01** | Authorization Foundation & Permission Mixin | **P0** | Django Auth | `User`, `Role`, `Permission` | Read, Verify | Backend checks strictly enforce permissions; SuperUser retained. | COMPLETED | PASSED | Reusable mixin & decorator |
| **USER-01** | User Accounts Directory (`/settings/users`) | **P0** | `Role`, `User` | `User`, `Role` | List, Search, Filter, Export | Table matches reference columns (الاسم, البريد الإلكتروني, مفعل, الدور). | COMPLETED | PASSED | Search & export enabled |
| **USER-02** | Add User Modal (`إضافة مستخدم جديد`) | **P0** | `User`, `Role` | `User`, `Role` | Create | Fields match: الاسم*, البريد الإلكتروني*, الكود, كلمة المرور*, الدور*. Client & server validation. | COMPLETED | PASSED | Validated against reference modal |
| **USER-03** | User Edit & Password Management | **P0** | `User`, `Role` | `User`, `Role` | Update, Reset PW | Edit user name, email, role, code, toggle active status. Cannot deactivate last superadmin. | COMPLETED | PASSED | Safeguards verified |
| **USER-04** | User Location Bypass Toggle | **P0** | `User` | `User` | Update | SuperAdmin can toggle location bypass per user with feedback. | COMPLETED | PASSED | Backend restricted to admin |
| **ROLE-01** | Roles List (`/settings/roles`) | **P0** | `Role` | `Role`, `Permission` | List, Duplicate, Delete | Table matches reference columns (المعرف, الاسم, مفعل, إجراءات). Top button `إنشاء دور`. | COMPLETED | PASSED | Pencil edit & duplicate actions |
| **ROLE-02** | Role Edit Dossier (`/settings/roles/edit/<id>`) | **P0** | `Role`, `Permission` | `Role`, `RoleTag`, `Permission` | Update, Manage Perms | Toggles (سوبر, فريق المبيعات, مدير منطقة, مندوب, مفعل, إلخ), Tags dropdown, Permissions Matrix. | COMPLETED | PASSED | Presets (أدمن, افتراضي, قراءة فقط) |
| **ROLE-03** | Create & Duplicate Role | **P0** | `Role` | `Role`, `Permission` | Create, Copy | Allows creating new custom roles or duplicating existing roles with all permissions. | COMPLETED | PASSED | Copy permissions deeply |
| **SET-01** | Company Branding (`/settings/branding`) | **P1** | `CompanyProfile` | `CompanyProfile` | Read, Update | Form fields: الاسم, تليفون, العنوان, المعرف الضريبي, معلومات الاتصال, شعار الشركة. | COMPLETED | PASSED | Upload & preview |
| **SET-02** | Location Settings (`/settings/location`) | **P1** | `LocationSettings`| `LocationSettings` | Read, Update | Tolerance, max accuracy, warn accuracy, auto-tracking toggles, and workflow verification dropdowns. | COMPLETED | PASSED | Parity with reference |
| **SET-03** | Geographical Areas (`/settings/areas`) | **P1** | `Area` | `Area` | List, Create, Edit, Delete | Hierarchical cards with subareas, 3-dot menu actions (Edit, Delete, Add Subarea). | COMPLETED | PASSED | Tree navigation |
| **SET-04** | Expense Types (`/settings/expenses`) | **P1** | `ExpenseType` | `ExpenseType` | List, Create, Edit, Delete | Tabs: مصروفات عامة & مصروفات للزيارات فقط. Item cards with Unit, Delete, Edit. | COMPLETED | PASSED | Seeded reference types |
| **SET-05** | Ticket Settings (`/settings/tickets`) | **P2** | `TicketType` | `TicketType` | List, Create, Edit, Delete | Task types list with default badge or delete/edit controls. Top button `اضف نوع جديد`. | COMPLETED | PASSED | Preloaded default Task |
| **SET-06** | Approval Settings (`/settings/requests`) | **P2** | `ApprovalRequestType`| `ApprovalRequestType`| List, Create, Edit, Delete | Request categories: Absent day, Off day, Admin work, Area manager plan, etc. | COMPLETED | PASSED | Seeded reference types |
| **SET-07** | Agreement Types (`/settings/agreements`) | **P2** | `AgreementType` | `AgreementType` | List, Create, Edit, Delete | Agreement types: Conference, Cash money, Devices, Gifts, RTD, Rx, Others. | COMPLETED | PASSED | Seeded reference types |
| **SET-08** | Sales Settings (`/settings/sales`) | **P1** | `SalesSettings` | `SalesSettings` | Read, Update | Workflow automation toggles, tax mode dropdown, packaging unit dropdown, print template. | COMPLETED | PASSED | Auto-invoicing toggles |
| **SET-09** | Purchase Settings (`/settings/purchase`) | **P1** | `PurchaseSettings`| `PurchaseSettings`| Read, Update | Workflow automation toggles, tax mode dropdown, packaging unit dropdown, payment closing. | COMPLETED | PASSED | Auto-invoicing toggles |
| **SET-10** | Inventory Settings (`/settings/inventory`)| **P1** | `InventorySettings`| `InventorySettings`| Read, Update | Toggles: Batch tracking, Batch mandatory, Expiry tracking, Expiry mandatory. | COMPLETED | PASSED | Linked to CompanyProfile |
| **SET-11** | Contact Custom Fields (`/settings/contacts-udf`)| **P2** | `ContactFieldSetting`| `ContactFieldSetting`| Read, Update | Info card header, subheader, basic info. Status badges (مغلق, مطلوب, مدمج, قابلة للتصفية). | COMPLETED | PASSED | Matches reference |
| **SET-12** | Data Sync (`/settings/sync-data`) | **P2** | `DataSyncConfig`| `DataSyncConfig` | Read, Update, Sync | Google Sheets URLs for Contacts, Products, Areas with Sync Now, Delete, Edit actions. | COMPLETED | PASSED | Safe read-only config |
| **NAV-01** | Settings Sidebar Navigation & Parity | **P0** | Base Layout | N/A | Navigation | Sidebar submenus match reference ERP titles, order, icons, and permission awareness. | COMPLETED | PASSED | Active indicators |
| **EXCL-01**| Calls (`/settings/calls`) | **N/A** | **EXCLUDED** | N/A | None | Excluded from scope per prompt requirements. Do NOT implement. | EXCLUDED | EXCLUDED | Explicitly excluded |
| **EXCL-02**| Assessments (`/settings/assessments`) | **N/A** | **EXCLUDED** | N/A | None | Excluded from scope per prompt requirements. Do NOT implement. | EXCLUDED | EXCLUDED | Explicitly excluded |
