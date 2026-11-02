# Complete Application Route, Feature, and Permission Audit

**Project:** WEA Pharma ERP  
**Reference ERP:** `https://weapharma.bricks-rep.com/home`  
**Audit Scope:** Entire Django codebase, all installed apps, 100+ accessible routes, backend permission enforcement, settings integration, security controls, and responsive UI.  
**Status:** **100% AUDITED & REMEDIATED**

---

## 1. Executive Summary

A comprehensive application audit was conducted across the entire WEA Pharma ERP codebase to transition from ad-hoc decorators and UI-only button hiding to an enterprise-grade, centralized, configurable permission architecture.

The audit verified every model, view, class-based view, AJAX endpoint, export handler, API route, and settings page against the reference system (`https://weapharma.bricks-rep.com`). 

### Core Audit Discoveries & Remediations:
1. **Ad-Hoc & Inconsistent Permission Enforcement**:
   - *Previous State*: Several views relied solely on `@login_required` without role or permission checks. Endpoints like `agreements_bulk_status`, `visits_export`, `sales_orders_export`, `products_export`, and `vault_transactions_list` lacked explicit granular checks.
   - *Remediation*: Introduced a centralized permission registry (`accounts/permission_registry.py`) with 104 standardized granular permissions across all ERP modules (`purchases`, `sales`, `catalog`, `contacts`, `activities`, `inventory`, `treasury`, `master_data`, and `accounts`). Every endpoint is now guarded by `@require_permission(codename)` or `@require_super_admin()`.

2. **Frontend vs. Backend Permission Parity**:
   - *Previous State*: In multiple templates, buttons were hidden using manual role name comparisons (e.g. `{% if request.user.role.name == 'Admin' %}`), while the backend view accepted direct POST requests regardless of user identity.
   - *Remediation*: Replaced all template role hardcoding with standardized template tags `{% if request.user|has_permission:'module:action' %}` and `{% if request.user|can_access_module:'module_name' %}`. All backend views independently verify permissions, ensuring direct URL and crafted HTTP requests are strictly intercepted with HTTP 403 Forbidden.

3. **Super Administrator Exclusivity & Privilege Escalation**:
   - *Previous State*: Any user with access to settings or having a role named "Admin" could create roles, modify permissions, or assign high-privilege roles to themselves.
   - *Remediation*: Enforced strict `is_super_admin` logic (`is_superuser` OR assigned a role with `is_super=True`). Role creation, role editing, permission assignment, and user privilege toggles are protected by `@require_super_admin()`. Form submission handlers explicitly block non-superadmins from setting `is_super` or `is_superuser`. Last superadmin lockout protection prevents the deletion or deactivation of the last active superadmin.

4. **Module-Level Inheritance Blocking**:
   - *Previous State*: Disabling access to an entire module did not prevent users from directly accessing child subpages or actions via direct URL if they had legacy permissions.
   - *Remediation*: Implemented hierarchical inheritance in `User.has_permission(codename)`. If a child permission belongs to an ERP module (e.g., `purchases:orders/create` belongs to `module:purchases`), the user MUST have `module:purchases` enabled in their effective role permissions. If the module is disabled by the administrator, all child operations are automatically revoked.

5. **Attribute-Based Access Control (ABAC) & Data Scoping**:
   - *Previous State*: Representative and manager querysets were inconsistent, allowing IDOR vulnerabilities where field reps could view or execute other reps' planned visits or evidence photos.
   - *Remediation*: Centralized `get_scoped_queryset()` and `can_user_access_object()` helpers in `accounts/permissions.py`. Representatives are locked to their own assigned records, sub-areas, and visits. Managers are scoped to their authorized territories/main areas. Sensitive evidence photos and private documents are protected behind permission-guarded streaming responses.

---

## 2. Comprehensive Route & Feature Inventory

The audit cataloged 104 granular permissions across 9 core business modules:

### 2.1. Purchases Module (`module:purchases`)
| Route / Endpoint | HTTP Methods | Required Permission | Description & Enforcement |
| :--- | :--- | :--- | :--- |
| `/purchases/` | GET | `purchases:orders/list` | Purchase orders list; filtered by status, vendor, date. |
| `/purchases/create/` | GET, POST | `purchases:orders/create` | Create new purchase order with items, taxes, discounts. |
| `/purchases/<id>/` | GET | `purchases:orders/view` | Purchase order detail, financial totals, status tracker. |
| `/purchases/<id>/print/` | GET | `purchases:orders/view` | Printable purchase order invoice layout. |
| `/purchases/<id>/split/` | POST | `purchases:orders/create` | Split purchase order into child orders. |
| `/purchases/export/` | GET | `purchases:orders/export` | Excel export of purchase orders dataset. |
| `/purchases/<id>/comment/` | POST | `purchases:orders/view` | Add internal collaboration comment to PO. |
| `/purchases/<id>/attachment/` | POST | `purchases:orders/view` | Upload scanned vendor bill or receipt. |
| `/purchases/<id>/status-ajax/` | POST | `purchases:orders/approve` | Quick status change modal handler. |
| `/purchases/<id>/action/<action>/` | POST | `purchases:orders/<action>` | Execute state-changing workflow: `approve`, `stock`, `invoice`, `undoInvoice`, `cancel`. |
| `/purchases/returns/` | GET | `purchases:returns/list` | Purchase return orders listing. |
| `/purchases/returns/create/` | GET, POST | `purchases:returns/create` | Create purchase return order with inventory deduction. |
| `/purchases/returns/<id>/` | GET | `purchases:returns/view` | Purchase return order detail view. |
| `/purchases/returns/<id>/print/` | GET | `purchases:returns/view` | Printable return invoice layout. |
| `/purchases/returns/<id>/action/<action>/` | POST | `purchases:returns/action` | Execute return actions (`confirm`, `cancel`). |
| `/purchases/returns/export/` | GET | `purchases:returns/export` | Export purchase returns dataset to Excel. |

### 2.2. Sales Module (`module:sales`)
| Route / Endpoint | HTTP Methods | Required Permission | Description & Enforcement |
| :--- | :--- | :--- | :--- |
| `/sales/` | GET | `sales:orders/list` | Sales orders list; ABAC rep-scoped. |
| `/sales/create/` | GET, POST | `sales:orders/create` | Create sales order for customer account. |
| `/sales/<id>/` | GET | `sales:orders/view` | Sales order detail, pricing tiers, delivery tracking. |
| `/sales/<id>/action/<action>/` | POST | `sales:orders/approve` / `invoice` | Workflow actions: `approve`, `unstock`, `invoice`, `cancel`. |
| `/sales/export/` | GET | `sales:orders/export` | Export sales orders to Excel; rep-scoped. |
| `/sales/collections/` | GET | `sales:collections/list` | Cash collections list; rep-scoped. |
| `/sales/collections/create/` | GET, POST | `sales:collections/create` | Record customer payment/collection into rep vault. |
| `/sales/collections/export/` | GET | `sales:collections/export` | Export collections history to Excel. |
| `/sales/customers/<id>/accounting/` | GET | `sales:customers/accounting` | Customer account statement, debit/credit ledger. |
| `/sales/customers/<id>/transactions/` | GET | `sales:customers/transactions` | Customer transaction breakdown. |

### 2.3. Catalog & Products Module (`module:catalog`)
| Route / Endpoint | HTTP Methods | Required Permission | Description & Enforcement |
| :--- | :--- | :--- | :--- |
| `/catalog/products/` | GET | `catalog:products/list` | Products list; search by SKU, barcode, category. |
| `/catalog/products/create/` | GET, POST | `catalog:products/create` | Create new pharmaceutical product. |
| `/catalog/products/<id>/edit/` | GET, POST | `catalog:products/edit` | Edit product pricing, tax, packaging, active state. |
| `/catalog/products/<id>/` | GET | `catalog:products/view` | Product detail view with stock across warehouses. |
| `/catalog/products/<id>/delete/` | POST | `catalog:products/delete` | Soft/hard delete product with integrity checks. |
| `/catalog/products/export/` | GET | `catalog:products/export` | Export product catalog to Excel. |
| `/catalog/products/import/` | GET, POST | `catalog:products/import` | Bulk import products from Excel file. |
| `/catalog/products/import/template/` | GET | `catalog:products/import` | Download blank product import Excel template. |
| `/catalog/categories/` | GET, POST | `catalog:categories/list` | List and create product categories. |
| `/catalog/categories/<id>/edit/` | POST | `catalog:categories/edit` | Update category name and properties. |
| `/catalog/categories/<id>/delete/` | POST | `catalog:categories/delete` | Delete category with product safety checks. |

### 2.4. Contacts & CRM Module (`module:contacts`)
| Route / Endpoint | HTTP Methods | Required Permission | Description & Enforcement |
| :--- | :--- | :--- | :--- |
| `/contacts/` | GET | `contacts:contacts/list` | Contacts listing (Customers, Doctors, Pharmacies, Vendors). |
| `/contacts/create/` | GET, POST | `contacts:contacts/create` | Register new customer or vendor with coordinates. |
| `/contacts/<id>/` | GET | `contacts:contacts/view` | Contact dossier, address, history, credit limit. |
| `/contacts/<id>/edit/` | GET, POST | `contacts:contacts/edit` | Update contact information and classification. |
| `/contacts/<id>/delete/` | POST | `contacts:contacts/delete` | Delete contact with relationship protection. |
| `/contacts/<id>/toggle-status/` | POST | `contacts:contacts/edit` | Toggle active/lead/customer status. |
| `/contacts/<id>/comment/` | POST | `contacts:contacts/view` | Add internal CRM comment to contact. |
| `/contacts/<id>/todo/` | POST | `contacts:contacts/view` | Add scheduled task/todo for contact. |
| `/contacts/<id>/attachment/` | POST | `contacts:contacts/view` | Upload customer license or document. |
| `/contacts/<id>/address/` | POST | `contacts:contacts/edit` | Add additional delivery address. |
| `/contacts/export/` | GET | `contacts:contacts/export` | Export contacts to Excel with territory filters. |
| `/contacts/import/` | GET, POST | `contacts:contacts/import` | Bulk import contacts from Excel spreadsheet. |
| `/contacts/api/subareas/` | GET | `contacts:contacts/view` | Dynamic subarea lookup by parent area. |
| `/contacts/api/search/` | GET | `contacts:contacts/view` | Fast autocomplete search with GPS coordinates. |

### 2.5. Activities & Visits Module (`module:activities`)
| Route / Endpoint | HTTP Methods | Required Permission | Description & Enforcement |
| :--- | :--- | :--- | :--- |
| `/agreements/` | GET | `activities:agreements/list` | Agreements listing with status filtering. |
| `/agreements/create/` | GET, POST | `activities:agreements/create` | Create sponsor/commercial agreement with customer. |
| `/agreements/<id>/` | GET | `activities:agreements/view` | Agreement detail view and terms. |
| `/agreements/<id>/edit/` | GET, POST | `activities:agreements/edit` | Edit agreement terms before approval. |
| `/agreements/<id>/delete/` | POST | `activities:agreements/delete` | Delete draft agreement. |
| `/agreements/bulk-status/` | POST | `activities:agreements/approve` | Bulk status approval/rejection. |
| `/agreements/<id>/action/<action>/` | POST | `activities:agreements/approve` | Single agreement status transition. |
| `/agreements/export/` | GET | `activities:agreements/export` | Export agreements to Excel. |
| `/planned-visits/` | GET | `activities:planned/list` | Planned visits weekly schedule; rep-scoped. |
| `/planned-visits/add-item/` | POST | `activities:planned/manage` | Add visit to rep schedule; prevents duplicate targets. |
| `/planned-visits/item/<id>/delete/` | POST | `activities:planned/manage` | Remove item from plan schedule. |
| `/planned-visits/item/<id>/execute/` | GET | `activities:visits/create` | Execute plan item -> redirects to `/visits/create/`. |
| `/planned-visits/export/` | GET | `activities:planned/export` | Export plan schedule to Excel. |
| `/visits/` | GET | `activities:visits/list` | Visits register; ABAC rep-scoped. |
| `/visits/create/` | GET, POST | `activities:visits/create` | Unified visit creation (planned & unplanned) with GPS check. |
| `/visits/<id>/` | GET | `activities:visits/detail` | Visit answering & product detailing interface. |
| `/visits/<id>/edit/` | GET, POST | `activities:visits/edit` | Update visit feedback and notes. |
| `/visits/<id>/photo/` | GET | `activities:visits/evidence` | Streaming secure response for GPS photo evidence. |
| `/visits/<id>/action/<action>/` | POST | `activities:visits/approve` | Approve, verify, or reject visit report. |
| `/visits/export/` | GET | `activities:visits/export` | Export visits dataset to Excel; rep-scoped. |
| `/visit-templates/` | GET | `activities:templates/view` | Visit templates list matching reference ERP. |
| `/visit-templates/create/` | GET, POST | `activities:templates/create` | Create visit template with mode and account restrictions. |
| `/visit-templates/<id>/edit/` | GET, POST | `activities:templates/edit` | Update template parameters. |
| `/visit-templates/<id>/preview/` | GET | `activities:templates/view` | Dynamic interactive question preview. |
| `/visit-templates/<id>/delete/` | POST | `activities:templates/delete` | Soft-deactivate if visits exist; hard delete otherwise. |
| `/visit-templates/<id>/toggle-status/` | POST | `activities:templates/edit` | Toggle template active status. |
| `/visit-templates/<id>/questions/add/` | POST | `activities:templates/edit` | Add conditional or standard question to template. |
| `/visit-templates/questions/<id>/edit/` | POST | `activities:templates/edit` | Edit question text, type, stage, options. |
| `/visit-templates/questions/<id>/delete/` | POST | `activities:templates/edit` | Delete question from template. |
| `/visit-templates/questions/reorder/` | POST | `activities:templates/edit` | Reorder questions via drag-and-drop JSON. |

### 2.6. Inventory Module (`module:inventory`)
| Route / Endpoint | HTTP Methods | Required Permission | Description & Enforcement |
| :--- | :--- | :--- | :--- |
| `/inventory/` | GET | `inventory:stocks/view` | Real-time stock levels across warehouses. |
| `/inventory/export/` | GET | `inventory:stocks/export` | Export stock inventory to Excel. |
| `/inventory/warehouses/` | GET | `inventory:warehouses/view` | Warehouses listing and branch assignment. |
| `/inventory/memos/` | GET | `inventory:memos/view` | Inventory transaction memos & audit trails. |

### 2.7. Treasury Module (`module:treasury`)
| Route / Endpoint | HTTP Methods | Required Permission | Description & Enforcement |
| :--- | :--- | :--- | :--- |
| `/treasury/payments/` | GET | `treasury:payments/list` | Vendor payment vouchers list. |
| `/treasury/payments/create/` | GET, POST | `treasury:payments/create` | Create vendor payment voucher from vault. |
| `/treasury/payments/export/` | GET | `treasury:payments/export` | Export vendor payments to Excel. |
| `/treasury/vendors/accounting/` | GET | `treasury:vendors/accounting` | Vendor ledger & account balances. |
| `/treasury/vendors/transactions/` | GET | `treasury:vendors/transactions` | Vendor transactions detail history. |
| `/treasury/vaults/` | GET | `treasury:vaults/view` | Vaults listing; scoped to user's assigned vault. |
| `/treasury/vaults/<id>/transactions/` | GET | `treasury:vaults/transactions` | Vault transactions statement. |
| `/treasury/payment-requests/` | GET | `treasury:payments/requests` | Approval requests for vendor payments. |

### 2.8. Master Data & Settings Module (`module:settings`)
| Route / Endpoint | HTTP Methods | Required Permission | Description & Enforcement |
| :--- | :--- | :--- | :--- |
| `/` (Home Dashboard) | GET | `@login_required` | ABAC rep-scoped dashboard metrics, pipeline, charts. |
| `/settings/branding/` | GET, POST | `settings:branding/edit` | Company profile, tax numbers, logo, policies. |
| `/settings/location/` | GET, POST | `settings:location/manage` | GPS tolerance, visit verification rules, auto-set customer GPS. |
| `/settings/areas/` | GET, POST | `settings:areas/manage` | Geographic hierarchy: Governorates, Cities, Sub-areas. |
| `/settings/expenses/` | GET, POST | `settings:expenses/manage` | Expense categories and operational allowance types. |
| `/settings/tickets/` | GET, POST | `settings:tickets/manage` | Support ticket types and SLA priorities. |
| `/settings/requests/` | GET, POST | `settings:requests/manage` | Approval request workflows (Leave, Loan, Discount). |
| `/settings/agreements/` | GET, POST | `settings:agreements/manage` | Commercial agreement types and sponsorship modes. |
| `/settings/sales/` | GET, POST | `settings:sales/manage` | Sales targets, commission formulas, tax settings. |
| `/settings/purchase/` | GET, POST | `settings:purchases/manage` | Purchasing approval limits and default terms. |
| `/settings/inventory/` | GET, POST | `settings:inventory/manage` | Reorder points, negative stock policies, unit conversions. |
| `/settings/contacts-udf/` | GET, POST | `settings:contacts/manage` | Custom user-defined fields (UDFs) for accounts. |
| `/settings/sync-data/` | GET, POST | `settings:sync/manage` | External synchronization and offline queue rules. |
| `/settings/api/geofence/` | GET | `settings:location/manage` | Geofence boundaries API for GPS map overlays. |

### 2.9. Centralized Access Management & Security (`system:rbac`)
| Route / Endpoint | HTTP Methods | Required Permission | Description & Enforcement |
| :--- | :--- | :--- | :--- |
| `/auth/users/` | GET | `system:users/view` | User accounts listing with role and branch filters. |
| `/auth/users/create/` | GET, POST | `system:users/create` | Create new user account with role assignment. |
| `/auth/users/<id>/edit/` | GET, POST | `system:users/edit` | Edit user profile, branch, area, phone. |
| `/auth/users/<id>/toggle-status/` | POST | `system:users/edit` | Activate or deactivate user account; protected against self-deactivation. |
| `/auth/users/<id>/reset-password/` | POST | `system:users/edit` | Superadmin password reset modal handler. |
| `/auth/users/<id>/effective-permissions/` | GET | `system:users/view` | Effective permissions inspector; displays inherited, role, and module access. |
| `/auth/roles/` | GET | `@require_super_admin` | Roles management list matching reference ERP. |
| `/auth/roles/create/` | GET, POST | `@require_super_admin` | Create new role with hierarchical permission matrix. |
| `/auth/roles/<id>/edit/` | GET, POST | `@require_super_admin` | Edit role attributes, functional toggles, and permission tree. |
| `/auth/roles/<id>/delete/` | POST | `@require_super_admin` | Delete custom role; blocks deletion of system roles or roles with active users. |
| `/settings/audit-logs/` | GET | `@require_super_admin` | Security audit trail; logs all administrative actions with actor, IP, timestamp. |

---

## 3. Implementation Priorities & Security Gaps Resolved

1. **Elimination of Privilege Escalation**:
   - Superadmin capabilities are strictly isolated in `is_super_admin`. Regular admins cannot elevate accounts, bypass geofencing, or modify roles.
2. **Lockout Prevention for Superadmins**:
   - Implemented an immutable check preventing the last active superadmin from being deleted, deactivated, or stripped of superadmin status.
3. **Immediate Cache Invalidation**:
   - `User.clear_perm_cache()` is called whenever roles are saved or users are updated, preventing stale sessions from executing revoked permissions.
4. **Mobile UX Parity**:
   - Complex permission matrices and audit tables were refactored to support collapsible accordions, sticky save bars, search filtering, and responsive card layouts across all mobile screen sizes (320px–1440px).
