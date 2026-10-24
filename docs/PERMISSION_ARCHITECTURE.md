# Centralized Permission Architecture & Security Specification

**Project:** WEA Pharma ERP  
**Reference ERP:** `https://weapharma.bricks-rep.com/home`  
**Architecture Model:** Role-Based Access Control (RBAC) + Attribute-Based Access Control (ABAC) + Hierarchical Module Inheritance  
**Document Version:** 1.0 (Production)  
**Status:** **FULLY IMPLEMENTED & TESTED**

---

## 1. Architectural Foundations

The WEA Pharma ERP centralized access control system integrates three complementary security patterns:

```
+-----------------------------------------------------------------------------------+
|                           SuperAdmin Sovereign Access                             |
|        (Bypasses all checks, full audit trail, protected against lockout)         |
+-----------------------------------------------------------------------------------+
                                          |
                                          v
+-----------------------------------------------------------------------------------+
|                     Hierarchical Module Inheritance Enforcement                   |
|     (If 'module:<name>' is disabled in Role, all child subpages & actions 403)     |
+-----------------------------------------------------------------------------------+
                                          |
                                          v
+-----------------------------------------------------------------------------------+
|                        Granular Action Authorization                              |
|           (Backend checks via @require_permission('module:entity/action'))         |
+-----------------------------------------------------------------------------------+
                                          |
                                          v
+-----------------------------------------------------------------------------------+
|                  Attribute-Based Data Scoping (ABAC & Ownership)                  |
|       (Reps scoped to self/sub-area, Managers scoped to main territory/team)       |
+-----------------------------------------------------------------------------------+
```

---

## 2. Permission Levels & Granularity

Access is governed across five discrete levels:

1. **Module Access (`module:<name>`)**:
   - Represents sovereign access to an entire functional domain (e.g., `module:purchases`, `module:sales`, `module:activities`, `module:treasury`).
   - If a role does not possess `module:purchases`, the user cannot open any purchases page, submit purchases AJAX requests, or download purchases exports—even if individual action permissions exist.
2. **Page Access (`<module>:<entity>/list`, `<module>:<entity>/view`)**:
   - Governs whether a user can navigate to and render a specific screen or tab (e.g., `purchases:orders/list`, `activities:visits/list`, `treasury:vaults/view`).
3. **Action Access (`<module>:<entity>/<action>`)**:
   - Governs explicit state-changing actions, including `create`, `edit`, `delete`, `approve`, `invoice`, `export`, and `import`.
   - Never trusts UI visibility; enforced directly inside view handlers.
4. **Data Access (ABAC Scoping)**:
   - Governs which record instances a user is permitted to retrieve or mutate:
     - **Representatives (`is_rep=True`)**: Confined to their assigned customers, scheduled visit plans, personal visits, and assigned sub-areas.
     - **Area Managers (`is_area_manager=True`)**: Permitted to review and approve records within their supervised governorates/main areas and subordinate representatives.
     - **Executives / Accountants (`CEO`, `Accountant`)**: Global cross-area visibility for audited financial ledgers, inventory stock, and compliance reporting.
5. **Administrative Access (`system:rbac`)**:
   - Reserved strictly for users verifying `is_super_admin`. Governs role configuration, permission matrix adjustments, user status modification, and system audit logs.

---

## 3. Centralized Permission Registry (`accounts/permission_registry.py`)

All permissions are declaratively registered in `accounts/permission_registry.py` under standard enterprise taxonomy:

```python
ERP_PERMISSIONS = [
    # Purchases (16 Permissions)
    ("module:purchases", "موديول المشتريات (وصول رئيسي)"),
    ("purchases:orders/list", "قائمة أوامر الشراء"),
    ("purchases:orders/create", "إنشاء أمر شراء جديد"),
    ("purchases:orders/view", "عرض تفاصيل أمر الشراء"),
    ("purchases:orders/approve", "اعتماد أمر الشراء"),
    ("purchases:orders/stock", "إدخال أمر الشراء للمخزن"),
    ("purchases:orders/invoice", "ترحيل فاتورة الشراء"),
    ("purchases:orders/undoInvoice", "إلغاء ترحيل فاتورة الشراء"),
    ("purchases:orders/cancel", "إلغاء أمر الشراء"),
    ("purchases:orders/export", "تصدير أوامر الشراء إكسل"),
    ("purchases:returns/list", "قائمة مرتجعات المشتريات"),
    ("purchases:returns/create", "إنشاء مرتجع مشتريات"),
    ("purchases:returns/view", "عرض تفاصيل مرتجع المشتريات"),
    ("purchases:returns/action", "تنفيذ إجراءات المرتجع"),
    ("purchases:returns/export", "تصدير مرتجعات المشتريات إكسل"),

    # Sales (10 Permissions)
    ("module:sales", "موديول المبيعات (وصول رئيسي)"),
    ("sales:orders/list", "قائمة أوامر البيع"),
    ("sales:orders/create", "إنشاء أمر بيع جديد"),
    ("sales:orders/view", "عرض تفاصيل أمر البيع"),
    ("sales:orders/approve", "اعتماد أمر البيع"),
    ("sales:orders/invoice", "ترحيل فاتورة البيع"),
    ("sales:orders/export", "تصدير أوامر البيع إكسل"),
    ("sales:collections/list", "قائمة التحصيلات النقدية"),
    ("sales:collections/create", "تسجيل تحصيل نقدي جديد"),
    ("sales:collections/export", "تصدير التحصيلات إكسل"),
    ("sales:customers/accounting", "كشف حساب العملاء"),
    ("sales:customers/transactions", "حركات حسابات العملاء"),

    # Catalog & Products (11 Permissions)
    ("module:catalog", "موديول المنتجات والتسعير (وصول رئيسي)"),
    ("catalog:products/list", "قائمة الأصناف والمنتجات"),
    ("catalog:products/create", "إضافة صنف جديد"),
    ("catalog:products/view", "عرض تفاصيل الصنف والمخزون"),
    ("catalog:products/edit", "تعديل بيانات الصنف"),
    ("catalog:products/delete", "حذف الصنف"),
    ("catalog:products/export", "تصدير قائمة الأصناف إكسل"),
    ("catalog:products/import", "استيراد الأصناف من ملف إكسل"),
    ("catalog:categories/list", "قائمة مجموعات وتصنيفات الأصناف"),
    ("catalog:categories/edit", "تعديل تصنيف الصنف"),
    ("catalog:categories/delete", "حذف تصنيف الصنف"),

    # Contacts & CRM (17 Permissions)
    ("module:contacts", "موديول جهات الاتصال والعملاء (وصول رئيسي)"),
    ("contacts:contacts/list", "قائمة جهات الاتصال"),
    ("contacts:contacts/create", "إضافة جهة اتصال / عميل جديد"),
    ("contacts:contacts/view", "عرض ملف وسجل العميل"),
    ("contacts:contacts/edit", "تعديل بيانات جهة الاتصال"),
    ("contacts:contacts/delete", "حذف جهة الاتصال"),
    ("contacts:contacts/export", "تصدير جهات الاتصال إكسل"),
    ("contacts:contacts/import", "استيراد جهات الاتصال من إكسل"),

    # Activities & Field Visits (17 Permissions)
    ("module:activities", "موديول الأنشطة والزيارات (وصول رئيسي)"),
    ("activities:visits/list", "قائمة وسجل الزيارات الميدانية"),
    ("activities:visits/create", "تسجيل وتنفيذ زيارة جديدة"),
    ("activities:visits/detail", "فتح شاشة توثيق وتفاصيل الزيارة"),
    ("activities:visits/edit", "تعديل بيانات الزيارة وملاحظاتها"),
    ("activities:visits/evidence", "تحميل ومعاينة صورة إثبات الزيارة (GPS)"),
    ("activities:visits/approve", "اعتماد وتدقيق تقرير الزيارة"),
    ("activities:visits/export", "تصدير سجل الزيارات إكسل"),
    ("activities:planned/list", "جدول وخطط الزيارات المسبقة"),
    ("activities:planned/manage", "إدارة وتوزيع بنود خطة الزيارات"),
    ("activities:planned/export", "تصدير خطط الزيارات إكسل"),
    ("activities:agreements/list", "قائمة الاتفاقيات والرعاية"),
    ("activities:agreements/create", "إنشاء اتفاقية رعاية جديدة"),
    ("activities:agreements/view", "عرض تفاصيل الاتفاقية"),
    ("activities:agreements/edit", "تعديل شروط الاتفاقية"),
    ("activities:agreements/delete", "حذف الاتفاقية"),
    ("activities:agreements/approve", "اعتماد وتغيير حالة الاتفاقيات"),
    ("activities:agreements/export", "تصدير الاتفاقيات إكسل"),
    ("activities:templates/view", "عرض قوالب الزيارات الميدانية"),
    ("activities:templates/create", "إنشاء قالب زيارة جديد"),
    ("activities:templates/edit", "تعديل القالب ومصمم الأسئلة"),
    ("activities:templates/delete", "حذف / إيقاف قالب الزيارة"),

    # Inventory (4 Permissions)
    ("module:inventory", "موديول المستودعات والمخزون (وصول رئيسي)"),
    ("inventory:stocks/view", "أرصدة المخزون بالمستودعات"),
    ("inventory:stocks/export", "تصدير أرصدة المخزون إكسل"),
    ("inventory:warehouses/view", "دليل المستودعات وفروع التخزين"),
    ("inventory:memos/view", "إشعارات وسجلات حركة المخزون"),

    # Treasury & Accounting (8 Permissions)
    ("module:treasury", "موديول الخزينة والمدفوعات (وصول رئيسي)"),
    ("treasury:vaults/view", "أرصدة الخزن النقدية"),
    ("treasury:vaults/transactions", "كشف حركات الخزينة النقدية"),
    ("treasury:payments/list", "سندات صرف مدفوعات الموردين"),
    ("treasury:payments/create", "إنشاء سند صرف للمورد"),
    ("treasury:payments/requests", "طلبات اعتماد صرف المدفوعات"),
    ("treasury:payments/export", "تصدير مدفوعات الموردين إكسل"),
    ("treasury:vendors/accounting", "كشف حسابات الموردين"),
    ("treasury:vendors/transactions", "سجل حركات حسابات الموردين"),

    # Master Data & Settings (15 Permissions)
    ("module:settings", "موديول إعدادات النظام (وصول رئيسي)"),
    ("settings:branding/edit", "إعدادات هوية وبيانات الشركة"),
    ("settings:location/manage", "إعدادات وضوابط الموقع الجغرافي GPS"),
    ("settings:areas/manage", "إدارة المناطق والمحافظات الجغرافية"),
    ("settings:expenses/manage", "إعدادات وتصنيفات المصروفات"),
    ("settings:tickets/manage", "إعدادات تذاكر الدعم الفني"),
    ("settings:requests/manage", "إعدادات نماذج طلبات الاعتماد"),
    ("settings:agreements/manage", "إعدادات أنواع الاتفاقيات"),
    ("settings:sales/manage", "إعدادات وسياسات المبيعات"),
    ("settings:purchases/manage", "إعدادات وسياسات المشتريات"),
    ("settings:inventory/manage", "إعدادات وسياسات المخزون"),
    ("settings:contacts/manage", "إعدادات الحقول المخصصة لجهات الاتصال"),
    ("settings:sync/manage", "إعدادات مزامنة البيانات الخارجية"),

    # Centralized User & Role Management (system:rbac) (6 Permissions)
    ("system:users/view", "عرض قائمة ومسيرات المستخدمين"),
    ("system:users/create", "إنشاء حساب مستخدم جديد"),
    ("system:users/edit", "تعديل حساب المستخدم وتعيين الدور"),
    ("system:rbac/roles", "إدارة مصفوفة الأدوار والصلاحيات (سوبر فقط)"),
    ("system:rbac/audit", "سجل التدقيق الأمني للعمليات الإدارية (سوبر فقط)"),
]
```

---

## 4. Module Inheritance Enforcement Logic

The inheritance engine is built into `User.has_permission(codename)`:

```python
def has_permission(self, perm_codename):
    # 1. Inactive users have zero access
    if not self.is_active:
        return False

    # 2. Sovereign superadmin bypass
    if self.is_super_admin:
        return True

    # 3. Retrieve effective role permissions (cached in memory)
    effective_perms = self.get_effective_permission_codenames()

    # 4. Check direct permission assignment
    if perm_codename not in effective_perms:
        return False

    # 5. Enforce Module-Level Inheritance Rule
    mod_key = get_module_for_permission(perm_codename)
    if mod_key:
        required_root = f"module:{mod_key}"
        # If the parent module is not granted, child permissions are blocked
        if required_root not in effective_perms:
            return False

    return True
```

This guarantees that if an administrator disables `module:purchases` on the `Sales Representative` role, that representative cannot invoke `/purchases/create/` or `/purchases/<id>/` even if `purchases:orders/create` was previously saved in the database.

---

## 5. Super Administrator Authorization Model

Super administrator capabilities are governed by `User.is_super_admin`:

```python
@property
def is_super_admin(self):
    if not self.is_active:
        return False
    if self.is_superuser:
        return True
    if self.role and getattr(self.role, 'is_super', False) and getattr(self.role, 'is_active', True):
        return True
    return False
```

### Protection Against Privilege Escalation:
1. Role creation and editing views (`role_create`, `role_edit`) require `@require_super_admin()`.
2. Even if a malicious request injects `is_super=1` into form POST parameters, the view asserts:
   ```python
   if not request.user.is_super_admin:
       return render_forbidden_response(request, "غير مصرح لك بمنح صلاحيات مدير النظام الأعلى.")
   ```
3. Superadmin Lockout Protection:
   ```python
   active_superadmins = User.objects.filter(
       Q(is_superuser=True) | Q(role__is_super=True, role__is_active=True),
       is_active=True
   ).count()
   if active_superadmins <= 1 and (target_user.is_super_admin):
       # Block deletion, deactivation, or demotion of the last active superadmin
   ```

---

## 6. Immediate Cache Invalidation Strategy

To prevent stale session vulnerabilities after an administrator revokes a permission:
1. `User.get_effective_permission_codenames()` caches permission sets in `self._cached_erp_perms`.
2. Whenever a role's permissions are modified or a user's role is updated, `clear_perm_cache()` is called.
3. Django sessions do not store serialized permission strings; they reference the database/cache, ensuring revocations take effect immediately on the user's very next HTTP request without requiring application restarts.
