# Comprehensive Authorization Architecture Investigation

**Document Version:** 1.0.0  
**Repository:** WEA Pharma ERP  
**Analysis Date:** November 2026  
**Status:** Investigation & Architectural Redesign (Analysis Only — Codebase Untouched)

---

## Executive Summary

An in-depth, line-by-line architectural inspection of the WEA Pharma ERP codebase has confirmed that the system currently suffers from a fundamental architectural flaw: **data visibility and operational access are heavily coupled to hardcoded role names, display name substrings, and static role boolean switches rather than configurable, module-based authorization policies.**

Key findings include:
1. **Hardcoded Role-Name Checks**: The core permission layer (`accounts/permissions.py`), services, and views determine managerial, accounting, and representative status by evaluating Python strings (`'ceo'`, `'admin'`, `'superadmin'`, `'manager'`, `'accountant'`, `'rep'`, `'medical_rep'`) and display name Arabic substrings (`'مدير'`, `'مشرف'`, `'محاسب'`, `'مندوب'`).
2. **Organizational Scoping Contradictions**: Different layers apply conflicting scopes to the same entities. For instance, the **Contacts list view** restricts sales representatives strictly to their own created/assigned contacts (`created_by=user | assigned_team=user`), while the **Customer Search Autocomplete API** (`customers_search_api`) returns all contacts in the representative's assigned Brick. Concurrently, the **Contact Detail view** denies access (HTTP 403) to a representative trying to view a customer in their Brick if it was created by another representative.
3. **Supplier/Vendor Scoping Failure**: Because `Contact` serves as both Customer and Supplier, supplier dropdowns in Purchases and Treasury mistakenly apply geographical/rep scoping to corporate suppliers, rendering manufacturers and company-wide vendors invisible to regional managers and staff.
4. **Form Dropdown Data Leakage**: Forms for creating and editing contacts, visits, warehouses, and vaults load global, unscoped querysets (e.g. `Area.objects.filter(parent__isnull=True)`), exposing nationwide governorates and sibling bricks to restricted representatives without backend validation upon submission.
5. **Rigid Resource Allocation**: Representatives are hardcoded to access only a single auto-provisioned warehouse and vault, with no configurable override for regional warehouse sharing or multi-rep cash management.
6. **Absence of Configurable Data Scopes**: There is no database or administrative mechanism to configure whether a role can view or manage records at the `OWN`, `BRICK`, `AREA`, or `ALL` scope. All scoping logic is hardcoded in an 1,152-line procedural file (`accounts/permissions.py`).

---

## 1. Existing Architecture Overview

The application is built on Django 5.x using server-rendered templates (Tailwind CSS, Cairo font, Arabic RTL) and session-based authentication. There is no Django REST Framework or Celery.

### App Breakdown & Core Responsibilities
- **`accounts`**: Custom user (`accounts.User`), roles (`accounts.Role`), role tags (`accounts.RoleTag`), enterprise audit trail (`accounts.SecurityAuditLog`), and permission infrastructure (`accounts/permissions.py`, `accounts/permission_registry.py`).
- **`master_data`**: Geographic hierarchy (`Area`), company profile (`CompanyProfile`), application-wide settings (`LocationSettings`, `SalesSettings`, `PurchaseSettings`, `UserSettings`), executive dashboard (`home_view`).
- **`contacts`**: Customers and vendors (`Contact`, `ContactAddress`), comments, attachments, todos, timeline activities (`ContactActivity`), and user-defined fields (`ContactFieldSetting`).
- **`catalog`**: Product catalog (`Product`, `ProductCategory`), volume discount tiers, and price lists.
- **`activities`**: Field operations (`Visit`, `PlannedVisitDay`, `PlannedVisitItem`, `VisitSampleItem`, `VisitExpense`), templates (`VisitTemplate`, `VisitTemplateQuestion`), commercial agreements (`Agreement`), workflow history (`ApprovalAuditLog`), and agenda (`AgendaTodo`).
- **`sales`**: Sales workflow (`SalesOrder`, `SalesOrderItem`, `SalesReturnOrder`, `SalesReturnOrderItem`), collections (`Collection`), and customer ledgers (`CustomerAccount`, `CustomerTransaction`).
- **`purchases`**: Procurement workflow (`PurchaseOrder`, `PurchaseOrderItem`, `PurchaseReturnOrder`, `PurchaseOrderAttachment`, `PurchaseOrderComment`).
- **`inventory`**: Distribution centers (`Warehouse`), stock balances (`InventoryStock`, `InventoryLot`), manual inventory adjustments (`InventoryMemo`, `InventoryMemoItem`), and inter-branch transfers (`ProductTransferRequest`, `ProductTransferRequestItem`).
- **`treasury`**: Cash vaults and bank accounts (`Vault`, `VaultTransaction`), supplier ledgers (`VendorAccount`, `VendorTransaction`, `VendorInstallment`, `Settlement`), and vendor disbursements (`VendorPayment`).

---

## 2. Existing User and Role Structure

### The `accounts.User` Model
`accounts.User` inherits from `django.contrib.auth.models.AbstractUser`.
- `role`: ForeignKey to `accounts.Role` (nullable).
- `assigned_areas`: ManyToManyField to `master_data.Area`.
- `bypass_location_verification`: Boolean flag for GPS override.
- `has_custom_permissions`: Boolean flag. When `True`, the user bypasses role permissions and relies strictly on `user.user_permissions`.
- `is_super_admin`: Evaluates `self.is_superuser or (self.role and (self.role.is_super or self.role.name.lower() == 'superadmin'))`.

### The `accounts.Role` Model
The role model acts as a container for Django permissions with multiple hardcoded boolean flags:
- `is_super`: Grants company-wide administrative bypass.
- `is_sales_team`: Marks participation in sales planning.
- `is_area_manager`: Identifies managerial status for a main area.
- `is_sub_area_manager`: Identifies managerial status for a sub-area.
- `is_rep`: Identifies a sales/medical representative.
- `can_hold_vault`: Indicates cash custody eligibility.
- `has_sales_targets`: Compatibility flag for sales target calculations.
- `is_contact_manager`: Flag for managing contacts.
- `is_main_area_bound`: Flag indicating restriction to main area.
- `is_sub_area_bound`: Flag indicating restriction to subarea.
- `permissions`: ManyToManyField to `django.contrib.auth.models.Permission`.
- `tags`: ManyToManyField to `accounts.RoleTag`.

---

## 3. Actual Area, Brick, and Representative Relationships

### The `master_data.Area` Model
A single, self-referencing model represents the geographic hierarchy:
```python
class Area(models.Model):
    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=150)
    area_type = models.CharField(max_length=20, choices=[('governorate', 'محافظة'), ('subarea', 'منطقة / مركز')])
    parent = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='subareas')
    is_company_area = models.BooleanField(default=False)
```
- **Governorate / Main Area**: Rows where `parent is None` and `area_type == 'governorate'`.
- **Brick / Subarea**: Rows where `parent is not None` and `area_type == 'subarea'`.

### Traversal and Assignment Realities
1. **User Assignment**: Users are assigned to `Area` objects via `User.assigned_areas` (ManyToMany).
2. **Main Area Resolution (`get_main_area`)**:
   ```python
   def get_main_area(area):
       curr = area
       while getattr(curr, 'parent_id', None):
           curr = curr.parent
       return curr
   ```
   Traverses upward until `parent is None`.
3. **Manager Area Resolution (`get_user_managed_areas`)**:
   - For superadmins: `Area.objects.all()`.
   - For managers (`is_manager_or_higher`): Computes root governorates, then fetches all areas where `id in roots`, `parent in roots`, or `parent__parent in roots`.
   - For representatives: Evaluates `Q(id__in=assigned_area_ids) | Q(parent_id__in=assigned_area_ids)`.
4. **Manager-to-Representative Eligibility (`is_manager_eligible_for_user`)**:
   - Compares the intersection of `get_user_main_areas(manager)` and `get_user_main_areas(target_user)`.
   - If the root governorate IDs intersect, eligibility is granted.
   - **Flaw**: A manager assigned to a specific brick (e.g., Nasr City) is resolved to the root (Cairo), thereby granting managerial oversight across all other Cairo bricks (Maadi, Heliopolis, New Cairo) regardless of organizational boundaries.
   - **Reporting Hierarchy Missing**: There is no direct `manager` or `reports_to` ForeignKey on `User`. Management is inferred solely through geographical governorate intersection.

---

## 4. Current Authorization Implementation

The authorization system operates through three primary mechanisms:
1. **View-Level Permissions**: `@require_permission('codename')` checks whether the user's role or direct permissions contain the requested action. SuperAdmins bypass this check. Module inheritance requires `module:<name>` to be active.
2. **Queryset Scoping**: `get_scoped_queryset(queryset, user, model_name)` inspects `model_name` and branches into hardcoded conditional blocks based on `is_accountant`, `is_manager_or_higher`, `is_medical_rep`, and role names.
3. **Object-Level Checks**: `can_user_access_object(user, obj, action)` enforces IDOR protection using the same hardcoded helper functions.

---

## 5. Complete Inventory of Hardcoded Role-Name & Type Checks

| Location | Hardcoded Code / Pattern | Architectural Consequence |
|---|---|---|
| `accounts/permissions.py:28-30` | `name_l in ['ceo', 'admin', 'superadmin', 'manager', 'area_manager', 'sub_area_manager', 'purchasingmanager']` or any keyword `['manager', 'director', 'supervisor', 'مدير', 'مشرف', 'رئيس']` | Grants manager authority based on string matching on role name or title rather than explicit permissions or scopes. |
| `accounts/permissions.py:307-309` | `'accountant' in name_l or 'bookkeeper' in name_l or 'محاسب' in disp_l or 'حسابات' in disp_l` | Hardcodes global view access for any role containing the word "accountant" or "محاسب". |
| `accounts/permissions.py:318-327` | `name_l in ['rep', 'medical_rep'] or 'rep' in name_l or 'مندوب' in disp_l` | Hardcodes representative restrictions to roles matching rep strings. |
| `accounts/permissions.py:339-340` | `name_l == 'rep'` | Restricts standard sales rep logic by literal role key. |
| `accounts/permissions.py:352-353` | `name_l == 'medical_rep'` | Branches contact visibility to include activities only for literal `'medical_rep'`. |
| `accounts/permissions.py:383, 415, 451, 498, 552, 584, 620, 850` | `role.name in ['superadmin', 'SuperAdmin', 'CEO', 'Admin']` | Grants company-wide access to arbitrary role names without `is_superuser` or `is_super`. |
| `accounts/permissions.py:663, 671, 690, 698, 706, 721, 733, 747, 755, 763, 782, 794, 802, 810, 818` | `if is_accountant(user): return queryset` | Grants unconstrained global table access to accountant roles across 15 models regardless of territory. |
| `accounts/permissions.py:818` | `if is_accountant(user): return queryset.none()` | Hardcodes an empty queryset for accountants on User list, regardless of administrative permissions. |
| `accounts/permissions.py:1032-1033` | Hardcoded block: `Approving and executing inter-warehouse transfers is strictly superadmin / accountant; return False` | Area managers are strictly blocked from approving transfers even inside their own governorate and even if granted `inventory:transfers/approve`. |
| `master_data/views.py:157-160` | `is_super = ...; is_acct = not is_super and is_accountant(user); is_mgr = ...; is_rep = not is_super and not is_acct and not is_mgr` | Dashboard KPI metrics and charts branch into mutually exclusive silos based on role identity rather than module scopes. |
| `master_data/views.py:237` | `vis_qs = Visit.objects.none()` for `is_acct` | Hardcodes that accountants can never see visits on the dashboard. |
| `master_data/views.py:224-232` | `is_rep` branches: `filter(created_by=user)` for SO, RO, Collections, Visits, Contacts, POs, Vendor Payments | Representatives are hardcoded to OWN scope across all dashboard metrics without configuration options. |
| `sales/services.py:78` | `if not sales_settings.require_manager_approval or is_manager_or_higher(user): order.status = 'manager_approval'` | Auto-approves sales orders created by any user who matches `is_manager_or_higher`, violating anti-self-approval. |
| `purchases/services.py:57` | `if not purchase_settings.require_manager_approval or is_manager_or_higher(user): order.status = 'approved'` | Auto-approves purchase orders created by any user matching `is_manager_or_higher`, violating anti-self-approval. |
| `sales/views.py:249, 337, 473, 563` | `is_rep = is_representative(request.user)` | If true, locks warehouse selection to the representative's single assigned default warehouse. |
| `inventory/views.py:398, 422` | `can_approve = is_super or is_accountant(request.user) ...; user_rep_wh = ... if is_representative(...)` | Couples transfer permissions and warehouse form choices to role name checks. |
| `activities/views.py:78` | `if user.role and (user.role.is_area_manager or user.role.is_sub_area_manager):` | Restricts representative assignment delegation in agreements by role boolean switch. |
| `activities/views.py:479, 851, 1012, 1184, 1231, 3315, 3516, 3538, 3562` | `(request.user.role and request.user.role.is_manager_role)` | Hardcodes planned visit and agenda visibility to `is_manager_role`. |
| `activities/views.py:2287, 2389` | `is_lower_user = not is_manager_or_higher(request.user)` | Re-approval invalidation on visit edit is tied to `is_manager_or_higher` string check instead of permissions or data scope. |

---

## 6. Incorrect Organizational Filtering & Cross-Module Contradictions

### A. The Contacts List vs. Visit Picker vs. Autocomplete Discrepancy
- **Contacts List (`contacts/views.py:43`)**: Uses `get_scoped_queryset(..., 'contact')`. For representatives, line 678 in `accounts/permissions.py` enforces:
  ```python
  return queryset.filter(Q(created_by=user) | Q(assigned_team=user)).distinct()
  ```
  This is strictly **OWN** scope. Contacts in the representative's brick created by other reps or imported by admin are **completely hidden**.
- **Customer Search API (`contacts/views.py:1758`)**: Uses `get_visit_eligible_contacts_queryset(qs, request.user)`. Lines 517-522 in `accounts/permissions.py` enforce:
  ```python
  return queryset.filter(Q(brick__in=managed_areas) | Q(area__in=managed_areas) | ...).distinct()
  ```
  This is **BRICK** scope.
- **Sales Order Create View (`sales/views.py:343`)**: Passes `customers = get_scoped_queryset(..., 'contact')` (OWN scope) into the initial template context, but frontend autocomplete fetches from `customers_search_api` (BRICK scope).
- **Result**: The user sees only their own customers when opening the page, but searching exposes customers in the Brick. If the user clicks on a customer created by a colleague in the same Brick, `contact_detail` and `contact_edit` throw a **403 Forbidden** error because `can_user_access_object(..., 'contact')` checks `created_by == user`.

### B. Supplier Scoping Leakage
- `Contact` has `is_supplier=True` and `is_customer=True`.
- In `purchases/views.py` (lines 78, 177, 276, 720) and `treasury/views.py` (lines 75, 170, 201, 243):
  ```python
  suppliers = get_scoped_queryset(Contact.objects.filter(is_supplier=True), request.user, 'contact')
  ```
- This passes `model_name='contact'`, which evaluates:
  ```python
  # For Manager:
  Q(brick__in=managed_areas) | Q(area__in=managed_areas) | Q(created_by__in=managed_reps)
  ```
- **Result**: Corporate suppliers (e.g. pharmaceutical factories in Cairo) are completely invisible to branch managers in Alexandria or Giza, making it impossible to submit purchase orders or log vendor payments.

### C. Product Stock Visibility in Catalog
- In `catalog/views.py:283` (`product_detail`):
  ```python
  stocks = InventoryStock.objects.filter(product=product).select_related('warehouse')
  total_stock = sum((s.qty_on_hand for s in stocks), Decimal('0.00'))
  ```
- **Result**: Product detail queries `InventoryStock` directly without passing through `get_scoped_queryset(..., 'inventorystock')`. A representative or regional supervisor in Aswan sees stock balances across all warehouses nationwide (Cairo Main, Alexandria Hub, Mansoura, etc.).

---

## 7. Module-by-Module Ownership & Organizational Relationship Analysis

```
                              ┌──────────────────────────────────┐
                              │           Area (Root)            │
                              │       parent is NULL (Gov)       │
                              └─────────────────┬────────────────┘
                                                │
                                    ┌───────────┴───────────┐
                                    ▼                       ▼
                         ┌──────────────────────┐┌──────────────────────┐
                         │   Area (Subarea)     ││   Area (Subarea)     │
                         │    Brick 1 (Nasr)    ││    Brick 2 (Maadi)   │
                         └──────────┬───────────┘└──────────┬───────────┘
                                    │                       │
                       ┌────────────┴────────────┐          │
                       ▼                         ▼          ▼
            ┌─────────────────────┐    ┌─────────────────────┐
            │  Contact (Customer) │    │  User (Rep / Mgr)   │
            │  area = Cairo       │    │  assigned_areas M2M │
            │  brick = Nasr City  │    └──────────┬──────────┘
            └──────────┬──────────┘               │
                       │             ┌────────────┴────────────┐
                       ▼             ▼                         ▼
            ┌─────────────────────┐┌──────────────────┐┌──────────────────┐
            │  Visit / SalesOrder ││ Warehouse (Assoc)││  Vault (Assoc)   │
            │  customer = Contact ││ user = Rep       ││  user = Rep      │
            │  created_by = User  ││ area = Brick     ││  (No Area FK!)   │
            └─────────────────────┘└──────────────────┘└──────────────────┘
```

### 1. Contacts Module
- **Primary Models**: `Contact`, `ContactAddress`, `ContactTodo`, `ContactComment`, `ContactAttachment`, `ContactActivity`.
- **Direct Ownership**: `created_by` (ForeignKey to `User`), `assigned_team` (ManyToManyField to `User`).
- **Organizational Placement**: Direct ForeignKeys to `area` (Governorate, `parent is None`) and `brick` (Subarea, `parent is not None`). `ContactAddress` also maintains `area` and `brick` ForeignKeys.
- **Inheritance**: `ContactTodo`, `ContactComment`, `ContactAttachment`, and `ContactActivity` inherit organizational placement directly through `contact`.
- **Mutability & History**: If a contact's `brick` or `area` is updated, child records inherit the change. Historical snapshots are not stored on transaction tables.

### 2. Activities & Field Operations Module
- **Primary Models**: `Visit`, `PlannedVisitDay`, `PlannedVisitItem`, `VisitTemplate`, `Agreement`.
- **Direct Ownership**:
  - `Visit`: `owner` (ForeignKey to `User`), `created_by` (ForeignKey to `User`).
  - `PlannedVisitDay`: `assignee` (ForeignKey to `User`), `created_by` (ForeignKey to `User`).
  - `Agreement`: `created_by` (ForeignKey to `User`).
- **Organizational Placement**:
  - Inherited through `contact.area` and `contact.brick`.
  - `Visit` stores coordinates (`latitude`, `longitude`, `customer_latitude_snapshot`, `customer_longitude_snapshot`), but **lacks snapshot ForeignKeys** for `area` or `brick`.
- **Inheritance**: `PlannedVisitItem` inherits through `contact` and `plan_day.assignee`. `VisitSampleItem` and `VisitExpense` inherit through `visit`.

### 3. Sales Module
- **Primary Models**: `SalesOrder`, `SalesOrderItem`, `SalesReturnOrder`, `SalesReturnOrderItem`, `Collection`, `CustomerAccount`, `CustomerTransaction`.
- **Direct Ownership**: `created_by` (User FK), `approved_by` (User FK).
- **Organizational Placement**: Inherited from `customer.brick`, `customer.area`, and `source_warehouse.area`.
- **Flaw**: Neither `SalesOrder` nor `SalesReturnOrder` snapshots the representative's assigned Brick or Area at the moment of order placement.

### 4. Purchases Module
- **Primary Models**: `PurchaseOrder`, `PurchaseOrderItem`, `PurchaseReturnOrder`, `PurchaseOrderAttachment`, `PurchaseOrderComment`.
- **Direct Ownership**: `created_by` (User FK), `approved_by` (User FK).
- **Organizational Placement**: Inherited from `target_warehouse.area`. `supplier` is a corporate contact.
- **Flaw**: Scoping purchase orders to `supplier.area` causes failures when suppliers operate nationally.

### 5. Inventory Module
- **Primary Models**: `Warehouse`, `InventoryStock`, `InventoryLot`, `InventoryMemo`, `InventoryMemoItem`, `ProductTransferRequest`, `ProductTransferRequestItem`.
- **Direct Ownership**: `Warehouse.assigned_user` (User FK), `Warehouse.manager` (User FK), `InventoryMemo.created_by` (User FK), `ProductTransferRequest.requesting_user` (User FK).
- **Organizational Placement**: `Warehouse.area` (Area FK, can be Governorate or Brick). `InventoryStock` and `InventoryMemo` inherit through `warehouse`.
- **Flaw**: `Warehouse` does not distinguish between governorate and brick in separate fields.

### 6. Treasury Module
- **Primary Models**: `Vault`, `VaultTransaction`, `VendorAccount`, `VendorTransaction`, `VendorInstallment`, `Settlement`, `VendorPayment`.
- **Direct Ownership**: `Vault.assigned_user` (User FK), `VaultTransaction.created_by` (User FK), `VendorPayment.created_by` (User FK).
- **Organizational Placement**:
  - **Severe Defect**: `Vault` has **no Area or Brick ForeignKey**. Its territory is inferred exclusively by looking up `assigned_user.assigned_areas`.
  - If a branch vault is assigned to no user (`assigned_user is None`), it becomes unreachable by regional supervisors.

### 7. Product Catalog Module
- **Primary Models**: `Product`, `ProductCategory`, `ProductVolumeDiscountTier`, `ProductPriceList`.
- **Direct Ownership**: `Product.created_by` (User FK).
- **Organizational Placement**: Global enterprise entity. No geographical restriction applies to product specifications or pricing rules, but stock balances are inventory entities that require warehouse-level scoping.

---

## 8. Target Authorization Architecture

```
┌────────────────────────────────────────────────────────────────────────┐
│                        ROLE AUTHORIZATION DOSSIER                      │
│                                                                        │
│  Role Identity: [ Commercial Sales Supervisor ]   is_active: [x]       │
├────────────────────────────────────────────────────────────────────────┤
│  MODULE DATA SCOPES (Configurable per module):                         │
│                                                                        │
│  Module        View Scope     Manage Scope   Approval Scope            │
│  ────────────  ─────────────  ─────────────  ────────────────────────  │
│  Contacts      [ AREA      ▼] [ BRICK     ▼] [ N/A                  ]  │
│  Visits        [ AREA      ▼] [ OWN       ▼] [ AREA (Anti-Self)   ▼]  │
│  Sales Orders  [ AREA      ▼] [ OWN       ▼] [ AREA (Anti-Self)   ▼]  │
│  Purchases     [ OWN       ▼] [ OWN       ▼] [ NONE               ▼]  │
│  Inventory     [ AREA      ▼] [ OWN       ▼] [ NONE               ▼]  │
│  Treasury      [ OWN       ▼] [ OWN       ▼] [ NONE               ▼]  │
├────────────────────────────────────────────────────────────────────────┤
│  ACTION PERMISSIONS (Granular Capability Toggles):                     │
│  [x] sales:orders/create   [x] sales:orders/view   [ ] sales:orders/approve│
└────────────────────────────────────────────────────────────────────────┘
```

### A. Separation of Concerns
1. **Role Identity**: Purely organizational metadata (`name`, `display_name`, `description`). No business logic or permissions may inspect `role.name` or role title strings.
2. **Module Action Permissions**: Fine-grained capabilities (`view`, `create`, `edit`, `delete`, `approve`, `reject`, `export`, `manage`) registered in `permission_registry.py`.
3. **Data Access Scope**: The geographic and ownership boundary within which those capabilities can be exercised (`OWN`, `BRICK`, `AREA`, `ALL`).

### B. Supported Data Scopes
- **`OWN`**: Records directly created by or assigned to the authenticated user (`created_by=user`, `owner=user`, `assignee=user`, `assigned_user=user`, or `user in assigned_team`).
- **`BRICK`**: Records whose primary organizational unit is an Area where `parent is not None` matching the user's assigned Brick(s), or whose related customer/warehouse belongs to those Bricks.
- **`AREA`**: Records whose organizational unit belongs to the user's root Main Area (`parent is None`), including all sub-bricks under that governorate.
- **`ALL`**: System-wide, company-level data visibility.

### C. Read Scope vs. Manage Scope vs. Approvals
- **View Scope (`view_scope`)**: Dictates record visibility on list pages, detail views, report calculations, dashboard aggregations, export routines, and autocomplete dropdowns.
- **Manage Scope (`manage_scope`)**: Dictates record creation, updating, status changes, and deletion.
  - A user cannot modify an object unless:
    1. They possess the required action permission (e.g. `sales:orders/edit`).
    2. The object falls within their `manage_scope`.
- **Approval Scoping**:
  - Approval is an executive mutation governed by:
    1. The explicit action permission (e.g. `sales:orders/approve`).
    2. The **Anti-Self-Approval** rule: `record.created_by != user and record.owner != user`.
    3. The record falling within the approver's `manage_scope` (or designated approval scope).

### D. New Model Schema: `RoleModuleScope`
```python
class RoleModuleScope(models.Model):
    SCOPE_CHOICES = [
        ('own', 'سجلات المستخدم فقط (Own)'),
        ('brick', 'سجلات الخط الجغرافي المعين (Brick)'),
        ('area', 'سجلات المنطقة الرئيسية والمحافظة (Area)'),
        ('all', 'كافة سجلات النظام (All)'),
    ]

    MODULE_CHOICES = [
        ('contacts', 'جهات الاتصال (العملاء والموردين)'),
        ('activities', 'الأنشطة الميدانية والزيارات'),
        ('sales', 'المبيعات والطلبات والتحصيلات'),
        ('purchases', 'المشتريات وأوامر التوريد'),
        ('inventory', 'المخازن والمخزون'),
        ('treasury', 'الخزينة والمالية'),
        ('catalog', 'المنتجات والكتالوج'),
        ('accounts', 'المستخدمين والأدوار'),
    ]

    role = models.ForeignKey('accounts.Role', on_delete=models.CASCADE, related_name='module_scopes')
    module = models.CharField(max_length=50, choices=MODULE_CHOICES)
    view_scope = models.CharField(max_length=20, choices=SCOPE_CHOICES, default='own')
    manage_scope = models.CharField(max_length=20, choices=SCOPE_CHOICES, default='own')

    class Meta:
        unique_together = ('role', 'module')
        verbose_name = "نطاق بيانات الموديول للدور"
        verbose_name_plural = "نطاقات بيانات الموديولات للأدوار"
```

For users with `User.has_custom_permissions = True`, a matching `UserModuleScope` table (or dynamic fallback) enables direct user-level scope overrides without creating redundant roles.

---

## 9. Form Dropdowns, Autocomplete, and Filter Security

### Current Flaws
1. **Unscoped Area & Brick Selectors**: `contacts/views.py:render_create_form` passes `Area.objects.filter(parent__isnull=True)` and `Area.objects.filter(parent__isnull=False)` directly into the template.
2. **Unvalidated Form Submissions**: `contact_create` and `contact_edit` accept arbitrary `area` and `brick` IDs from `request.POST` without verifying whether those areas are within the user's authorized scope.
3. **Subareas Endpoint Leakage**: `/contacts/api/subareas/?area_id=` returns all subareas of any requested `area_id` without checking if the user is assigned to that area.
4. **Autocomplete Asymmetry**: `customers_search_api` hardcodes visit eligibility instead of checking the calling module's scope.

### Required Architecture
All form choices, filter panels, and search APIs must be scoped server-side using a unified `ScopeResolutionService`:
- When a user with `BRICK` scope opens a form, governorate dropdowns contain only their assigned brick's parent governorate, and brick dropdowns contain only their assigned bricks.
- When an Area Manager opens a form, governorates are limited to their assigned Main Area(s), and bricks are limited to the children of those Main Areas.
- POST submissions must validate that `submitted_brick in user_authorized_bricks` and `submitted_area in user_authorized_areas`. Unauthorized submissions must be rejected with HTTP 403 or form validation errors.

---

## 10. Performance, Security, and Quality Considerations

### Performance & Query Overhead
1. **N+1 Queries in Existing Traversal**: Resolving `get_user_main_areas` performs repeated while-loop parent lookups for each assigned area.
   - **Remedy**: Cache resolved main area IDs and brick IDs on `request.user` for the lifecycle of the HTTP request, or use an indexed lookup.
2. **Missing Database Indexes**:
   - `Contact.brick` lacks a compound index with `is_customer`.
   - `SalesOrder` and `PurchaseOrder` lack indexed geographic tracking fields.
3. **Queryset Composition**: Scoping queries must use single-query `Q` object composition (`filter(Q(brick_id__in=brick_ids) | Q(created_by=user))`) and avoid evaluating QuerySets in Python memory (`list(...)`).

### Security Vulnerabilities (IDOR & Privilege Escalation)
1. **Direct URL Manipulation**: If a representative guesses a `pk` for an order outside their scope, `get_object_or_404(SalesOrder, pk=pk)` in un-scoped views currently relies solely on `can_user_access_object`. Detail views must load from `get_scoped_queryset(SalesOrder.objects.all(), request.user, 'salesorder')`.
2. **Anti-Self-Approval Enforcement**: Must be enforced systematically in the mutation service layer (`@transaction.atomic`), preventing bypass through direct POST requests.
3. **Warehouse / Vault Resource Forgery**: Sales and collection endpoints must verify that the submitted `source_warehouse` or `vault` belongs to the user's authorized scope before executing stock deductions or cash postings.

---

## 11. Module-by-Module Matrix

| Module | Main Models | Record Ownership | Organizational Relationship | Current Access Logic | Identified Problems | Proposed Access Scopes | Required CRUD Permissions | Related Pages & APIs | Required Tests |
|---|---|---|---|---|---|---|---|---|---|
| **Contacts** | `Contact`, `ContactAddress`, `ContactTodo`, `ContactComment`, `ContactAttachment`, `ContactActivity` | `created_by`, `assigned_team` | `area` (Gov), `brick` (Subarea) | Hardcoded `is_accountant` (all), `is_rep` (own only), `is_manager` (main area) | List view uses OWN scope while Autocomplete uses BRICK scope; form dropdowns leak nationwide areas; suppliers are incorrectly scoped as customers | **Rep:** BRICK view, BRICK/OWN manage.<br>**Mgr:** AREA view, AREA manage.<br>**Global:** ALL view, ALL manage. | `contacts:contacts/list`, `view`, `create`, `edit`, `delete`, `export`, `import` | `/contacts/`, `/contacts/<pk>/`, `/contacts/create/`, `/contacts/<pk>/edit/`, `/contacts/api/subareas/`, `/contacts/api/search/` | List isolation by brick, cross-rep brick sharing, supplier global accessibility, form dropdown restrictions |
| **Activities (Visits)** | `Visit`, `PlannedVisitDay`, `PlannedVisitItem`, `VisitTemplate`, `Agreement` | `owner`, `created_by`, `assignee` | Inherited from `contact.area` and `contact.brick` | Rep (own only), Manager (managed reps or area contacts). Tied to `is_manager_or_higher` | Post-approval edit re-approval relies on string check; templates restricted by rigid role M2M; agenda hardcoded to `is_manager_role` | **Rep:** OWN/BRICK view, OWN manage.<br>**Mgr:** AREA view, AREA manage, AREA approve.<br>**Global:** ALL view, ALL manage. | `activities:visits/list`, `view`, `create`, `edit`, `approve`, `evidence`, `export`, `activities:planned/list`, `manage`, `activities:agreements/*` | `/visits/`, `/visits/<pk>/`, `/visits/create/`, `/planned-visits/`, `/agenda/`, `/activities/visits/<pk>/action/` | Rep seeing own visits only, manager approving visits across area bricks, anti-self-approval enforcement |
| **Sales** | `SalesOrder`, `SalesOrderItem`, `SalesReturnOrder`, `Collection`, `CustomerAccount`, `CustomerTransaction` | `created_by`, `approved_by` | Inherited from `customer.brick`, `customer.area`, `source_warehouse.area` | Rep (own created), Manager (managed reps), Accountant (all). Tied to `is_rep` and `is_accountant` | Reps locked to single warehouse; managers auto-approved on create; customer selector in create view uses OWN while autocomplete uses BRICK | **Rep:** OWN view, OWN manage.<br>**Mgr:** AREA view, OWN manage, AREA approve.<br>**Acct:** ALL view, ALL invoice/manage.<br>**Global:** ALL. | `sales:orders/list`, `view`, `create`, `edit`, `approve`, `unstock`, `invoice`, `cancel`, `export`, `sales:collections/*`, `sales:customers/*` | `/sales/orders/`, `/sales/orders/<pk>/`, `/sales/orders/create/`, `/sales/collections/`, `/sales/customers/accounting/` | Rep order isolation, manager regional approval, anti-self-approval on manager create, collection vault validation |
| **Purchases** | `PurchaseOrder`, `PurchaseOrderItem`, `PurchaseReturnOrder`, `PurchaseOrderAttachment` | `created_by`, `approved_by` | Inherited from `target_warehouse.area`. Corporate supplier | Rep (own created), Manager (warehouse area / managed reps), Accountant (all) | Suppliers filtered through contact territorial logic, hiding national vendors; managers auto-approved on creation; hardcoded `is_accountant` | **Staff:** OWN view, OWN manage.<br>**Mgr:** AREA view, OWN manage, AREA approve.<br>**Acct:** ALL view, ALL invoice/settle.<br>**Global:** ALL. | `purchases:orders/list`, `view`, `create`, `edit`, `approve`, `stock`, `invoice`, `cancel`, `export`, `purchases:returns/*` | `/purchases/`, `/purchases/<pk>/`, `/purchases/create/`, `/purchases/<pk>/edit/`, `/purchases/<pk>/status/update/` | Corporate supplier visibility across all branches, manager approval in warehouse area, anti-self-approval |
| **Inventory** | `Warehouse`, `InventoryStock`, `InventoryLot`, `InventoryMemo`, `ProductTransferRequest` | `Warehouse.assigned_user`, `Warehouse.manager`, `InventoryMemo.created_by`, `ProductTransferRequest.requesting_user` | `Warehouse.area` (Area FK). Stocks and memos inherit from warehouse | Reps view assigned + main; managers view area warehouses; transfers approval hardcoded to accountant/superadmin | Area managers forbidden from approving intra-governorate transfers; catalog product detail leaks nationwide warehouse stock; warehouse lacks explicit brick vs area distinction | **Rep:** OWN/BRICK view, OWN operate.<br>**Mgr:** AREA view, AREA operate, AREA approve transfers.<br>**Global:** ALL view, ALL manage. | `inventory:stocks/view`, `export`, `inventory:warehouses/manage`, `inventory:memos/manage`, `inventory:transfers/list`, `view`, `create`, `approve`, `execute`, `cancel` | `/inventory/stocks/`, `/inventory/warehouses/`, `/inventory/memos/`, `/inventory/transfers/`, `/catalog/products/<pk>/` | Product detail stock scoping, intra-area transfer approval by regional manager, stock-in/out memo scoping |
| **Treasury** | `Vault`, `VaultTransaction`, `VendorAccount`, `VendorTransaction`, `VendorPayment` | `Vault.assigned_user`, `VaultTransaction.created_by`, `VendorPayment.created_by` | Inferred through `assigned_user.assigned_areas` (No direct Area FK on Vault) | Rep (own vault), Manager (managed reps' vaults), Accountant (all) | Vault has no Area FK; unassigned branch safes invisible to managers; viewing vault allows transfer if perm held; rep locked to single vault | **Rep:** OWN view, OWN transfer.<br>**Mgr:** AREA view, AREA supervise.<br>**Acct:** ALL view, ALL manage/reconcile.<br>**Global:** ALL. | `treasury:treasury/view`, `treasury:reports/view`, `treasury:vaults/view`, `manage`, `transfer`, `treasury:transactions/*`, `treasury:payments/*` | `/treasury/vaults/`, `/treasury/vaults/<pk>/`, `/treasury/transactions/`, `/treasury/payments/`, `/treasury/payments/create/` | Vault isolation by user/area, manager visibility of branch vaults, deposit/withdraw authorization |
| **Catalog** | `Product`, `ProductCategory`, `ProductVolumeDiscountTier`, `ProductPriceList` | `created_by` | Global catalog | Gated by permissions; stock detail unscoped | Product detail page shows stocks across all company warehouses to unauthorized reps | **All Roles:** ALL view.<br>**Admin:** ALL manage. *(Stock lines scoped by inventory view_scope)* | `catalog:products/list`, `view`, `create`, `edit`, `delete`, `export`, `import`, `catalog:categories/*` | `/catalog/products/`, `/catalog/products/<pk>/`, `/catalog/products/create/`, `/catalog/categories/` | Product catalog viewing, warehouse stock line scoping on product detail |
| **Accounts** | `User`, `Role`, `RoleTag`, `SecurityAuditLog` | `User.id` | `User.assigned_areas` M2M | Rep (self), Manager (managed area reps), Accountant (none), SuperAdmin (all) | User edit uses `is_manager_or_higher` and role name checks; accountant hardcoded to none; no direct reporting manager field | **Staff:** OWN view.<br>**Mgr:** AREA view, AREA manage (reps only).<br>**SuperAdmin:** ALL view, ALL manage. | `users:users/list`, `create`, `edit`, `delete`, `export`, `view`, `system:rbac/manage`, `settings:rbac/view`, `settings:auditLogs/view` | `/settings/users/`, `/settings/users/<pk>/`, `/settings/roles/`, `/settings/roles/<pk>/edit/`, `/settings/audit-logs/` | Manager user management restricted to area reps, privilege escalation prevention, role scope configuration |
| **Dashboard** | N/A (Aggregates across all models) | N/A | Regional aggregation via `master_data/views.py` | Hardcoded flags: `is_super`, `is_acct`, `is_mgr`, `is_rep` | Siloed statistics; accountant forced to `Visit.objects.none()`; representative forced to `created_by=user` on sales and purchases | Scopes resolved dynamically per module: SOs use `sales.view_scope`, Visits use `activities.view_scope`, etc. | `master_data` dashboard view permission | `/`, `/home/` | Dashboard metrics matching scoped querysets, rep privacy preservation, manager team rollups |

---

## 12. Database Relationship Deficiencies & Required Migrations

### Deficiencies Identified
1. **Missing Data Scope Storage**: No table links `Role` to its per-module `view_scope` and `manage_scope`.
2. **Missing Direct Territory on `Vault`**: `Vault` links only to `assigned_user`, with no `area` ForeignKey. Branch vaults without an assigned representative cannot be scoped to an Area.
3. **Missing Historical Snapshots on Transactions**: `SalesOrder`, `PurchaseOrder`, and `Visit` do not snapshot `area` or `brick` at transaction time. Reassigning a customer's brick retroactively shifts historical report figures.
4. **Ambiguous `Warehouse.area`**: `Warehouse` has a single `area` ForeignKey that points either to a governorate or a brick, creating inconsistent filtering logic.
5. **Missing Direct Manager Field on `User`**: User hierarchy is inferred indirectly via area intersection rather than an explicit `reports_to` relationship.

### Required Migrations
1. **Create `RoleModuleScope` Model**:
   - `role`: ForeignKey to `accounts.Role`.
   - `module`: CharField (`contacts`, `activities`, `sales`, `purchases`, `inventory`, `treasury`, `catalog`, `accounts`).
   - `view_scope`: CharField (`own`, `brick`, `area`, `all`).
   - `manage_scope`: CharField (`own`, `brick`, `area`, `all`).
   - `unique_together = ('role', 'module')`.
2. **Add `area` ForeignKey to `treasury.Vault`**:
   - `area`: ForeignKey to `master_data.Area` (null=True, blank=True).
3. **Data Migration**:
   - Seed default `RoleModuleScope` records for the 5 canonical roles:
     - `superadmin`: `ALL` view, `ALL` manage across all modules.
     - `manager`: `AREA` view, `AREA` manage on contacts/visits; `AREA` view, `OWN` manage on sales/purchases/treasury.
     - `accountant`: `ALL` view on sales/purchases/treasury/inventory; `OWN` view on visits/contacts.
     - `rep` & `medical_rep`: `BRICK` view, `BRICK` manage on contacts; `OWN` view, `OWN` manage on visits/sales/purchases/treasury.
   - Backfill `Vault.area` from `assigned_user.assigned_areas.first()`.

---

## 13. Testing Status and Test Gap Analysis

### Baseline Test Run Status
- Executed: `python manage.py test accounts`
- Result: **90 passed in 79.5s (0 failures, 0 errors)**.
- Note: Debug print statement active on line 628 of `accounts/permissions.py` (`print(managed_areas, managed_reps)`).

### Existing Test Suite Breakdown
- `accounts/tests_data_scoping.py`: Tests main-area isolation and ABAC.
- `accounts/tests_area_approvals.py`: Tests manager eligibility by governorate intersection.
- `accounts/tests_roles_consolidation.py`: Verifies the 5 canonical role keys.
- `activities/tests_approval_and_regional.py`: Tests visit approvals and regional boundaries.
- `inventory/tests_transfers.py`: Tests warehouse transfer requests.
- `treasury/tests_treasury_rbac_and_stats.py`: Tests vault isolation.

### Critical Missing Tests
1. **Configurable Scope Matrix Tests**: Zero tests currently verify that changing a role's scope from `OWN` to `BRICK` or `AREA` dynamically alters QuerySets without changing the role name.
2. **Form Dropdown Data Leakage Tests**: No tests assert that `render_create_form` or `contact_create` excludes sibling bricks or unassigned governorates.
3. **Autocomplete vs. List Scoping Parity Tests**: No tests verify that customer autocomplete results match the user's contact list visibility.
4. **Supplier vs. Customer Scoping Tests**: No tests verify that non-superusers can see national suppliers in purchase orders and vendor payments.
5. **Catalog Product Stock Leaks**: No tests check that product detail stock lines are scoped to the user's authorized warehouses.
6. **Cross-Area POST Mutation Rejection (IDOR)**: Insufficient test coverage for forged `area_id`, `warehouse_id`, or `vault_id` values submitted in POST payloads.

---

## 14. Unclear Business Rules Requiring Clarification

The following architectural and business questions must be clarified by the project owner:

1. **Brick vs. Area Contact Creation Authority**:
   - When a Representative has `Contacts: BRICK` scope, can they create contacts only in their assigned Brick(s), or also in any Brick within their supervisor's Main Area?
2. **Cross-Brick Customer Detailing in Multi-Rep Governorates**:
   - If two representatives operate in different Bricks under the same Cairo Governorate (e.g. Nasr City and Maadi), can the Nasr City rep view or record visits for a Maadi customer if instructed by the Cairo Area Manager?
3. **Corporate Supplier Organizational Classification**:
   - Should `Supplier` contacts remain completely exempt from geographical scoping (i.e. global `ALL` scope for all users with purchasing/treasury permissions), or do regional suppliers exist that must be bound to specific Governorates?
4. **Multiple Assigned Warehouses for Representatives**:
   - Is a representative strictly limited to exactly one default warehouse, or should the new architecture permit representatives to hold or draw stock from multiple regional warehouses?
5. **Intra-Governorate Transfer Approvals**:
   - Should an Area Manager have authority to approve inter-warehouse transfer requests between two warehouses that both belong to their assigned Governorate, or must transfer approval remain strictly reserved for SuperAdmin and Accountant?
6. **Post-Approval Invalidation Trigger**:
   - When an approved visit is edited, should re-approval be required for **any** field modification, or only for sensitive operational fields (e.g. date, customer, GPS bypass reason, template questions)?

---

## 15. Conclusion & Architectural Recommendation

The WEA Pharma ERP requires an architectural refactoring from **name-based hardcoded authorization** to a **unified, configurable, module-based scoping engine**.

The recommended design preserves existing URL contracts, UI components, and the 5 canonical roles while introducing a `RoleModuleScope` configuration table and a centralized `ScopeResolutionService`. This eliminates procedural string checks, fixes cross-module visibility contradictions, prevents form dropdown leakage, and empowers administrators to adjust organizational data access dynamically through the role management interface.

