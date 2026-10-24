# Super Administrator Operational Guide: Settings, Roles, and Permission Management

**Project:** WEA Pharma ERP  
**Audience:** Authorized Super Administrators  
**Target Reference URL:** `https://weapharma.bricks-rep.com/home`  
**Security Level:** HIGH / SUPERADMIN ONLY

---

## 1. Introduction

This guide provides operational instructions for authorized Super Administrators to manage users, roles, access permissions, and security audit logs in the WEA Pharma ERP application.

All administrative controls are located under the **الإعدادات (Settings)** menu in the desktop sidebar and mobile navigation drawer.

---

## 2. Navigating the Security & Permissions Console

Super Administrators have exclusive access to three specialized security consoles:

1. **إدارة الأدوار والصلاحيات (Roles & Permissions Matrix)**: `/auth/roles/`
2. **فحص الصلاحيات الفعلية (Effective Permissions Inspector)**: `/auth/users/<id>/effective-permissions/`
3. **سجل التدقيق الأمني (Security Audit Log)**: `/settings/audit-logs/`

---

## 3. Managing Roles & the Hierarchical Permission Matrix

### 3.1. Creating a New Role (`/auth/roles/create/`)
1. Navigate to **الإعدادات -> أدوار المستخدمين** and click **إنشاء دور جديد**.
2. **المعرف البرمجي للدور (Role Code)**: Enter a unique ASCII identifier (e.g., `RegionalCoordinator`).
3. **المسمى الوظيفي (Display Name)**: Enter the official Arabic title (e.g., `منسق إقليمي`).
4. **سمات الدور والعلامات الوظيفية (Role Attributes & Flags)**:
   - **سوبر (مدير نظام أعلى)**: Toggle ON only for top system administrators. Bypasses all restrictions.
   - **فريق المبيعات**: Assigns user to sales operations, pipeline targets, and team reports.
   - **مندوب ميداني**: Designates user as a field representative, activating GPS geofencing and visit execution.
   - **مدير لمنطقة رئيسية**: Confines management visibility to an authorized governorate/main area.
   - **تابع لمنطقة فرعية**: Confines field operations to an assigned sector/district.
   - **يملك خزينة نقدية**: Authorizes user to hold an operational cash vault for collections and expenses.
5. **مصفوفة الصلاحيات الهرمية (Hierarchical Permission Matrix)**:
   - Use the **بحث في الصلاحيات** bar to quickly filter permissions by keyword or module.
   - Click any module header (e.g., `موديول المشتريات`) to expand or collapse its subpages and actions.
   - **مفتاح الموديول الرئيسي (Master Module Switch)**: Toggling the main module switch grants or revokes the entire module. Disabling this switch automatically revokes and unchecks all child actions.
   - **أزرار الضبط السريع (Presets)**: Use `عرض فقط` (Read-only view), `كامل الصلاحيات` (All actions), or `إلغاء التحديد` to rapidly configure access.
6. Click **حفظ بيانات وصلاحيات الدور** in the sticky bottom action bar.

### 3.2. Editing an Existing Role (`/auth/roles/<id>/edit/`)
- Adjust display name, attributes, or individual checkboxes.
- All changes take effect immediately across all active user sessions; cached permissions are invalidated instantly.

### 3.3. Safe Role Deletion Rules
- **System Roles (`is_system=True`)**: Protected by law; the system will block any deletion attempt to preserve core business workflows.
- **Roles in Active Use**: If any user is currently assigned to the role, the deletion request is rejected with a descriptive warning instructing the administrator to reassign those users first.

---

## 4. User Account & Privilege Administration

### 4.1. Creating Users (`/auth/users/create/`)
- Enter Name, Username, Email, Phone, and Branch.
- Select the assigned **الدور الوظيفي (Role)** from the dropdown. The user immediately inherits the exact permission set defined by that role.
- If assigning geographic boundaries, select the user's **المنطقة الرئيسية (Main Area)** and **المنطقة الفرعية (Sub Area)**.

### 4.2. Password Reset Modal (`/auth/users/<id>/reset-password/`)
- Super Administrators can reset forgotten passwords directly from the user list.
- Every password reset event is permanently recorded in the **Security Audit Log** with the acting administrator's username, client IP, and target user ID.

### 4.3. Superadmin Lockout Protection
- The ERP actively guards the system against accidental administrative lockout.
- If only one active superadmin account remains, attempts to deactivate, delete, or demote that user will be intercepted with an error:
  `"لا يمكن إلغاء تفعيل أو حذف مدير النظام الوحيد المتبقي منعاً لغلق النظام."`

---

## 5. Inspecting User Effective Access (`/auth/users/<id>/effective-permissions/`)

When troubleshooting permission discrepancies or conducting access audits:
1. Navigate to **المستخدمون (Users List)**.
2. Click the **فحص الصلاحيات الفعلية** action icon on any user row.
3. The dossier screen displays:
   - User account status, role, and sovereign superadmin status.
   - Assigned functional flags (`مندوب`, `مدير منطقة`, `فريق مبيعات`).
   - Geographic scope and assigned branch.
   - A complete card-based visual matrix showing every module, subpage, and action with active status pills (`مفعلة` vs `غير مفعلة`).

---

## 6. Reviewing Security Audit Logs (`/settings/audit-logs/`)

The security audit log provides an immutable record of all security-sensitive operations:

- **Recorded Actions**:
  - `ROLE_CREATED`, `ROLE_UPDATED`, `ROLE_DELETED`
  - `USER_CREATED`, `USER_UPDATED`, `USER_STATUS_TOGGLED`
  - `PASSWORD_RESET`
  - `PERMISSIONS_SEEDED`
- **Filtering & Search**:
  - Search by actor username, target user name, or client IP address.
  - Filter by action type using the dropdown selector.
- **Mobile Responsive**:
  - Displays as an enterprise data table on desktop screens (`>= 768px`) and transitions into compact audit cards on mobile screens (`< 768px`).
