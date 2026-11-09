# Codex Implementation Prompt: Configurable Module-Based Authorization Architecture

**Task Objective:** Refactor the WEA Pharma ERP authorization engine from hardcoded role-name checks into a configurable, module-based authorization architecture with granular data access scopes (`OWN`, `BRICK`, `AREA`, `ALL`).

**Engineering Contract Reference:** `AGENTS.md` and `docs/AUTHORIZATION_INVESTIGATION.md`. Inspect code before modifying. Preserve Arabic RTL, teal brand tokens, URL names, and JSON contracts.

---

## CONTEXT & CORE ARCHITECTURAL DIRECTIVE

The current codebase hardcodes organizational data visibility based on Python string comparisons (`'ceo'`, `'admin'`, `'superadmin'`, `'manager'`, `'accountant'`, `'rep'`, `'medical_rep'`) and display name substrings (`'مدير'`, `'مشرف'`, `'محاسب'`, `'مندوب'`) inside `accounts/permissions.py`, `accounts/services.py`, and multiple views.

You must eliminate all hardcoded role-name authorization branches. Replace them with:
1. **Configurable Module Scopes (`RoleModuleScope`)**: Each role has an administratively configurable `view_scope` and `manage_scope` (`own`, `brick`, `area`, `all`) per ERP module.
2. **Centralized Scope Resolution Service (`ScopeResolutionService`)**: A single, authoritative service resolving user scopes, building scoped querysets, evaluating object-level mutations, and filtering form dropdowns.
3. **Decoupled Actions & Approvals**: Separate action permissions (registered codenames) from data scopes. Enforce anti-self-approval systematically across all workflow mutations.
4. **Zero Form Data Leakage**: Form dropdowns and autocompletes must be filtered server-side to the user's authorized territory.

---

## 1. MODELS & DATABASE SCHEMA MODIFICATIONS

### A. New Model: `accounts.RoleModuleScope`
Add to `accounts/models.py`:
```python
class RoleModuleScope(models.Model):
    SCOPE_OWN = 'own'
    SCOPE_BRICK = 'brick'
    SCOPE_AREA = 'area'
    SCOPE_ALL = 'all'

    SCOPE_CHOICES = [
        (SCOPE_OWN, 'سجلات المستخدم فقط (Own)'),
        (SCOPE_BRICK, 'سجلات الخط الجغرافي المعين (Brick)'),
        (SCOPE_AREA, 'سجلات المنطقة الرئيسية والمحافظة (Area)'),
        (SCOPE_ALL, 'كافة سجلات النظام (All)'),
    ]

    MODULE_CONTACTS = 'contacts'
    MODULE_ACTIVITIES = 'activities'
    MODULE_SALES = 'sales'
    MODULE_PURCHASES = 'purchases'
    MODULE_INVENTORY = 'inventory'
    MODULE_TREASURY = 'treasury'
    MODULE_CATALOG = 'catalog'
    MODULE_ACCOUNTS = 'accounts'

    MODULE_CHOICES = [
        (MODULE_CONTACTS, 'جهات الاتصال (العملاء والموردين)'),
        (MODULE_ACTIVITIES, 'الأنشطة الميدانية والزيارات والاتفاقيات'),
        (MODULE_SALES, 'المبيعات والطلبات والتحصيلات'),
        (MODULE_PURCHASES, 'المشتريات وأوامر التوريد'),
        (MODULE_INVENTORY, 'المخازن والمخزون والتحويلات'),
        (MODULE_TREASURY, 'الخزينة والمالية والمدفوعات'),
        (MODULE_CATALOG, 'دليل المنتجات والكتالوج'),
        (MODULE_ACCOUNTS, 'المستخدمين وإدارة الأدوار'),
    ]

    role = models.ForeignKey('Role', on_delete=models.CASCADE, related_name='module_scopes', verbose_name="الدور الوظيفي")
    module = models.CharField(max_length=50, choices=MODULE_CHOICES, verbose_name="الموديول")
    view_scope = models.CharField(max_length=20, choices=SCOPE_CHOICES, default=SCOPE_OWN, verbose_name="نطاق العرض والاستعراض")
    manage_scope = models.CharField(max_length=20, choices=SCOPE_CHOICES, default=SCOPE_OWN, verbose_name="نطاق التعديل والإدارة")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "نطاق بيانات الموديول للدور"
        verbose_name_plural = "نطاقات بيانات الموديولات للأدوار"
        unique_together = ('role', 'module')
        ordering = ['role', 'module']

    def __str__(self):
        return f"{self.role.display_name} - {self.get_module_display()} [عرض: {self.view_scope} / إدارة: {self.manage_scope}]"
```

### B. User-Level Scope Override (`UserModuleScope` or Direct Property)
To respect `User.has_custom_permissions`:
- Add `accounts.UserModuleScope` with fields `(user, module, view_scope, manage_scope)` (or let `ScopeResolutionService` inspect custom scopes when `has_custom_permissions=True`).

### C. Relationship Corrections
1. **`treasury.Vault`**:
   - Add direct ForeignKey to Area:
     ```python
     area = models.ForeignKey('master_data.Area', on_delete=models.SET_NULL, null=True, blank=True, related_name='vaults', verbose_name="المنطقة الجغرافية / الفرع")
     ```
2. **`accounts.Role`**:
   - Retain existing boolean fields (`is_super`, `is_area_manager`, `is_rep`, etc.) for backwards compatibility, but decouple all authorization logic from them. `is_super` and `Role.ROLE_SUPERADMIN` remain reserved strictly for SuperAdmin system bypass.
3. **Data Migrations**:
   - Create a data migration seeding default `RoleModuleScope` records for the 5 canonical roles:
     - `superadmin`: `view_scope='all'`, `manage_scope='all'` across all 8 modules.
     - `manager`:
       - `contacts`: `view_scope='area'`, `manage_scope='area'`
       - `activities`: `view_scope='area'`, `manage_scope='area'`
       - `sales`: `view_scope='area'`, `manage_scope='own'`
       - `purchases`: `view_scope='area'`, `manage_scope='own'`
       - `inventory`: `view_scope='area'`, `manage_scope='area'`
       - `treasury`: `view_scope='area'`, `manage_scope='own'`
       - `catalog`: `view_scope='all'`, `manage_scope='own'`
       - `accounts`: `view_scope='area'`, `manage_scope='area'`
     - `accountant`:
       - `contacts`: `view_scope='all'`, `manage_scope='own'`
       - `activities`: `view_scope='own'`, `manage_scope='own'`
       - `sales`: `view_scope='all'`, `manage_scope='all'`
       - `purchases`: `view_scope='all'`, `manage_scope='all'`
       - `inventory`: `view_scope='all'`, `manage_scope='all'`
       - `treasury`: `view_scope='all'`, `manage_scope='all'`
       - `catalog`: `view_scope='all'`, `manage_scope='own'`
       - `accounts`: `view_scope='own'`, `manage_scope='own'`
     - `rep` & `medical_rep`:
       - `contacts`: `view_scope='brick'`, `manage_scope='brick'`
       - `activities`: `view_scope='own'`, `manage_scope='own'`
       - `sales`: `view_scope='own'`, `manage_scope='own'`
       - `purchases`: `view_scope='own'`, `manage_scope='own'`
       - `inventory`: `view_scope='own'`, `manage_scope='own'`
       - `treasury`: `view_scope='own'`, `manage_scope='own'`
       - `catalog`: `view_scope='all'`, `manage_scope='own'`
       - `accounts`: `view_scope='own'`, `manage_scope='own'`
   - Data migration backfills `Vault.area` from `assigned_user.assigned_areas.first()`.

---

## 2. CENTRALIZED SCOPE RESOLUTION SERVICE

Create `accounts/scope_service.py` (and export through `accounts.permissions` for backward compatibility):

```python
class ScopeResolutionService:
    """
    Authoritative, centralized scoping and data-access service for WEA Pharma ERP.
    Eliminates all procedural role-name checks.
    """

    @classmethod
    def get_user_scope(cls, user, module: str, scope_type: str = 'view') -> str:
        """
        Resolves effective scope ('own', 'brick', 'area', 'all') for a user in a module.
        SuperAdmin always resolves to 'all'.
        """
        ...

    @classmethod
    def get_user_bricks(cls, user):
        """Returns QuerySet of Area objects that are subareas (parent__isnull=False) assigned to the user."""
        ...

    @classmethod
    def get_user_main_areas(cls, user):
        """Returns QuerySet of root Area objects (parent__isnull=True) assigned to the user or resolved from assigned bricks."""
        ...

    @classmethod
    def get_user_managed_areas(cls, user):
        """Returns all Area objects under user's scope (Main Areas + child Bricks)."""
        ...

    @classmethod
    def get_user_managed_subordinates(cls, user):
        """Returns QuerySet of Users who fall within the current user's territory scope."""
        ...

    @classmethod
    def get_scoped_queryset(cls, queryset, user, model_name: str = None, scope_type: str = 'view'):
        """
        Filters QuerySet based on user's configured module scope (own/brick/area/all).
        """
        ...

    @classmethod
    def can_user_access_object(cls, user, obj, action: str = 'view') -> bool:
        """
        Object-level IDOR and mutation checker.
        Validates anti-self-approval, view_scope, manage_scope, and action permission.
        """
        ...

    @classmethod
    def get_scoped_choices(cls, user, target_model_name: str, context_module: str = None):
        """
        Returns authorized QuerySets for form choices (Areas, Bricks, Customers, Suppliers, Warehouses, Vaults).
        """
        ...
```

### Clean Scoping Logic per Model

1. **`Contact`**:
   - If `contact.is_supplier and not contact.is_customer`: Corporate suppliers are **global** (`ALL` scope) for purchasing and treasury purposes.
   - `OWN`: `created_by=user | assigned_team=user`.
   - `BRICK`: `brick__in=user_bricks | addresses__brick__in=user_bricks`.
   - `AREA`: `area__in=user_main_areas | brick__parent__in=user_main_areas | addresses__area__in=user_main_areas | addresses__brick__parent__in=user_main_areas`.
   - `ALL`: Unrestricted.

2. **`Visit`**:
   - `OWN`: `owner=user | created_by=user`.
   - `BRICK`: `contact__brick__in=user_bricks`.
   - `AREA`: `contact__area__in=user_main_areas | contact__brick__parent__in=user_main_areas | owner__in=managed_subordinates`.
   - `ALL`: Unrestricted.

3. **`SalesOrder` & `SalesReturnOrder`**:
   - `OWN`: `created_by=user`.
   - `BRICK`: `customer__brick__in=user_bricks | source_warehouse__area__in=user_bricks`.
   - `AREA`: `customer__area__in=user_main_areas | customer__brick__parent__in=user_main_areas | source_warehouse__area__in=user_main_areas | created_by__in=managed_subordinates`.
   - `ALL`: Unrestricted.

4. **`PurchaseOrder` & `PurchaseReturnOrder`**:
   - `OWN`: `created_by=user`.
   - `BRICK`: `target_warehouse__area__in=user_bricks`.
   - `AREA`: `target_warehouse__area__in=user_main_areas | target_warehouse__area__parent__in=user_main_areas | created_by__in=managed_subordinates`.
   - `ALL`: Unrestricted.

5. **`Warehouse`**:
   - `OWN`: `assigned_user=user | manager=user`.
   - `BRICK`: `area__in=user_bricks`.
   - `AREA`: `area__in=user_main_areas | area__parent__in=user_main_areas | assigned_user__in=managed_subordinates`.
   - `ALL`: Unrestricted. (`is_main=True` warehouses remain viewable as distribution hubs).

6. **`Vault`**:
   - `OWN`: `assigned_user=user`.
   - `BRICK`: `area__in=user_bricks`.
   - `AREA`: `area__in=user_main_areas | area__parent__in=user_main_areas | assigned_user__in=managed_subordinates`.
   - `ALL`: Unrestricted.

7. **`ProductTransferRequest`**:
   - `OWN`: `requesting_user=user | source_warehouse__assigned_user=user | destination_warehouse__assigned_user=user`.
   - `BRICK`: Warehouses in `user_bricks`.
   - `AREA`: Requester or warehouses in `user_main_areas`.
   - `ALL`: Unrestricted.

8. **`User`**:
   - `OWN`: `pk=user.pk`.
   - `BRICK`: `assigned_areas__in=user_bricks`.
   - `AREA`: `assigned_areas__in=user_managed_areas`.
   - `ALL`: Unrestricted.

---

## 3. REMOVE HARDCODED ROLE-NAME CHECKS

Systematically purge and refactor:
1. **`accounts/permissions.py`**:
   - Deprecate `is_manager_or_higher`, `is_accountant`, `is_representative`, `is_rep`, `is_medical_rep`.
   - Replace internal implementations of `get_scoped_queryset`, `can_user_access_object`, `get_visit_eligible_contacts_queryset` to call `ScopeResolutionService`.
   - Remove string checks against `'ceo'`, `'admin'`, `'superadmin'`, `'manager'`, `'accountant'`, `'rep'`, `'medical_rep'`, `'مندوب'`, `'محاسب'`, `'مدير'`.
   - Clean up debug statements (e.g. line 628: `print(managed_areas, managed_reps)`).
2. **`master_data/views.py` (`home_view`)**:
   - Delete lines 157-160 (`is_super = ...; is_acct = ...; is_mgr = ...; is_rep = ...`).
   - Querysets for SO, RO, Collections, Visits, Contacts, POs, and Vendor Payments must use `ScopeResolutionService.get_scoped_queryset(..., user, model_name, scope_type='view')`.
3. **`sales/services.py` & `purchases/services.py`**:
   - Remove `is_manager_or_higher(user)` auto-approval bypass.
   - Enforce anti-self-approval: a manager creating an order cannot approve it. Orders requiring approval must enter pending state regardless of creator's rank.
4. **`sales/views.py` & `inventory/views.py`**:
   - Remove `is_rep = is_representative(request.user)`.
   - Replace warehouse dropdown queryset with `ScopeResolutionService.get_scoped_choices(request.user, 'warehouse')`.
5. **`activities/views.py`**:
   - Replace `is_manager_role` in `planned_visits_list` and `agenda` with `ScopeResolutionService.get_user_scope(request.user, 'activities') in ['area', 'all']`.
   - Replace `is_lower_user = not is_manager_or_higher(request.user)` with permission check `not request.user.has_permission('activities:visits/approve')`.

---

## 4. FORM DROPDOWNS & AUTOCOMPLETE REFACTORING

1. **`contacts/views.py` (`render_create_form`, `contact_edit`)**:
   - Replace `Area.objects.filter(parent__isnull=True)` with `ScopeResolutionService.get_scoped_choices(request.user, 'governorates')`.
   - Replace `Area.objects.filter(parent__isnull=False)` with `ScopeResolutionService.get_scoped_choices(request.user, 'bricks')`.
   - In `contact_create` and `contact_edit` POST: Validate that submitted `area` and `brick` are within `ScopeResolutionService.get_scoped_choices(request.user, 'bricks')`. Reject unauthorized IDs with form error / HTTP 403.
2. **`contacts/views.py` (`get_subareas`)**:
   - Filter subareas by user's authorized scope:
     ```python
     authorized_bricks = ScopeResolutionService.get_user_bricks(request.user)
     qs = Area.objects.filter(parent_id=area_id)
     if ScopeResolutionService.get_user_scope(request.user, 'contacts') == 'brick':
         qs = qs.filter(id__in=authorized_bricks)
     ```
3. **`contacts/views.py` (`customers_search_api`)**:
   - Determine calling context or default to `contacts` module `view_scope`.
   - Scopes customer results using `ScopeResolutionService.get_scoped_queryset(qs, request.user, 'contact', scope_type='view')`.
4. **`catalog/views.py` (`product_detail`)**:
   - Scope stocks:
     ```python
     stocks = ScopeResolutionService.get_scoped_queryset(
         InventoryStock.objects.filter(product=product).select_related('warehouse'),
         request.user,
         'inventorystock'
     )
     ```

---

## 5. ROLE SETTINGS UI & CONFIGURATION INTERFACE

### In `templates/accounts/role_form.html` & `accounts/views.py` (`role_create`, `role_edit`):
1. **Module Scopes Configuration Section**:
   Render a clean, compact responsive table for Module Data Scopes:
   ```html
   <div class="bg-white rounded-xl border border-slate-200/90 shadow-xs p-6 space-y-4">
       <h2 class="text-lg font-bold text-[#27bebe] flex items-center gap-2">
           <span class="material-symbols-outlined">dataset</span>
           <span>نطاقات بيانات الموديولات (Module Data Access Scopes)</span>
       </h2>
       <p class="text-xs text-slate-500">حدد مستوى البيانات الجغرافية والتنظيمية المسموح لهذا الدور باستعراضها وإدارتها لكل موديول.</p>

       <div class="overflow-x-auto">
           <table class="w-full text-xs text-right border-collapse">
               <thead>
                   <tr class="border-b border-slate-200 bg-slate-50/70 text-slate-700">
                       <th class="py-2.5 px-3 font-bold">الموديول</th>
                       <th class="py-2.5 px-3 font-bold">نطاق الاستعراض والعرض (View Scope)</th>
                       <th class="py-2.5 px-3 font-bold">نطاق التعديل والإدارة (Manage Scope)</th>
                   </tr>
               </thead>
               <tbody class="divide-y divide-slate-100">
                   {% for mod_key, mod_name in modules_list %}
                   <tr class="hover:bg-slate-50/50">
                       <td class="py-2.5 px-3 font-bold text-slate-800">{{ mod_name }}</td>
                       <td class="py-2.5 px-3">
                           <select name="scope_view_{{ mod_key }}" class="px-3 py-1.5 bg-slate-50 border border-slate-300 rounded-lg text-xs">
                               <option value="own">سجلات المستخدم فقط (Own)</option>
                               <option value="brick">سجلات الخط الجغرافي المعين (Brick)</option>
                               <option value="area">سجلات المحافظة / المنطقة الرئيسية (Area)</option>
                               <option value="all">كافة سجلات النظام (All)</option>
                           </select>
                       </td>
                       <td class="py-2.5 px-3">
                           <select name="scope_manage_{{ mod_key }}" class="px-3 py-1.5 bg-slate-50 border border-slate-300 rounded-lg text-xs">
                               <option value="own">سجلات المستخدم فقط (Own)</option>
                               <option value="brick">سجلات الخط الجغرافي المعين (Brick)</option>
                               <option value="area">سجلات المحافظة / المنطقة الرئيسية (Area)</option>
                               <option value="all">كافة سجلات النظام (All)</option>
                           </select>
                       </td>
                   </tr>
                   {% endfor %}
               </tbody>
           </table>
       </div>
   </div>
   ```
2. **Form Processing (`role_create`, `role_edit`)**:
   - Extract `scope_view_<module>` and `scope_manage_<module>`.
   - Update or create `RoleModuleScope` records inside `transaction.atomic`.
   - Audit scope changes to `SecurityAuditLog`.

---

## 6. IMPLEMENTATION ORDER BASED ON DEPENDENCIES

Execute the refactoring in the following exact sequence:

```
Step 1: Models & Migrations
  └── accounts/models.py (RoleModuleScope, Vault.area)
  └── makemigrations accounts treasury
  └── Data migration for default canonical scopes & Vault.area

Step 2: Scope Resolution Service
  └── accounts/scope_service.py (ScopeResolutionService)
  └── Wire accounts/permissions.py proxies

Step 3: Contacts & Geocoding Scoping
  └── contacts/views.py (list, create, edit, get_subareas, customers_search_api)
  └── Form choice filtering

Step 4: Activities & Visits Scoping
  └── activities/views.py (visits, planned visits, agenda, agreements, visit_action)
  └── Remove is_manager_role checks

Step 5: Sales & Purchases Scoping
  └── sales/views.py & sales/services.py
  └── purchases/views.py & purchases/services.py
  └── Decouple suppliers from territory scoping; enforce anti-self-approval

Step 6: Inventory & Treasury Scoping
  └── inventory/views.py & inventory/services.py
  └── treasury/views.py & treasury/services.py
  └── catalog/views.py (product stock scoping)

Step 7: Role Management UI & Effective Permissions
  └── accounts/views.py (role_create, role_edit, user_effective_permissions)
  └── templates/accounts/role_form.html

Step 8: Dashboard Scoping
  └── master_data/views.py (home_view)
  └── Replace hardcoded role silos with dynamic module querysets

Step 9: Testing & Verification
  └── Run full test suite (`python manage.py test`)
  └── Add comprehensive scope test cases
```

---

## 7. MEASURABLE ACCEPTANCE CRITERIA

1. **Zero Role-Name Authorization Checks**:
   - Searching the codebase for string-based role inspections (`role.name in [...]`, `role.name.lower() == 'rep'`, `is_manager_or_higher`, `is_accountant`) returns zero functional authorization dependencies.
2. **Dynamic Scope Adaptation**:
   - Changing a role's `contacts` scope from `OWN` to `BRICK` in the UI immediately allows representatives with that role to see all contacts in their brick on `/contacts/` without code changes.
3. **Contacts List & Autocomplete Parity**:
   - Contacts visible in `/contacts/` match the contacts returned by `customers_search_api` for the same user.
4. **Corporate Supplier Accessibility**:
   - Branch managers in Giza or Alexandria can select national suppliers in purchase orders and vendor payments.
5. **No Form Dropdown Leakage**:
   - Representatives opening contact creation or visit scheduling cannot see or select governorates or bricks outside their authorized scope.
6. **Anti-Self-Approval Integrity**:
   - Managers creating sales orders, purchase orders, or visits cannot approve their own submissions.
7. **Performance & Clean Baseline**:
   - No N+1 regressions. All existing 90 accounts tests and all module tests pass green (`python manage.py test`).

