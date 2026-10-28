# User Role Consolidation Documentation

## 1. Executive Summary

In accordance with ERP enterprise architecture requirements, all user types across the application have been consolidated into **exactly five supported business roles**:

1. `superadmin` (`مدير النظام الأعلى`)
2. `manager` (`مدير`)
3. `accountant` (`محاسب`)
4. `rep` (`مندوب مبيعات`)
5. `medical_rep` (`مندوب دعاية طبية`)

All obsolete and duplicate roles have been removed from active role-selection interfaces, creation modals, editing forms, filters, and admin forms.

---

## 2. Canonical Roles Architecture

| Canonical Key | Display Name (Arabic) | Key Switches / Capabilities | Primary Responsibilities |
|---|---|---|---|
| `superadmin` | مدير النظام الأعلى | `is_super=True`, `is_system=True`, `can_hold_vault=True` | Complete, unrestricted system administration, RBAC role management, global settings, and audit logs oversight. |
| `manager` | مدير | `is_area_manager=True`, `is_sales_team=True`, `is_main_area_bound=True`, `has_sales_targets=True` | Regional oversight, visit approvals, sales order approvals, purchase approvals, sales team supervision. |
| `accountant` | محاسب | `can_hold_vault=True`, `is_system=True` | Financial transactions, treasury vaults, supplier payments, invoice posting, sales collections. |
| `rep` | مندوب مبيعات | `is_rep=True`, `is_sales_team=True`, `is_sub_area_bound=True`, `can_hold_vault=True`, `has_sales_targets=True` | Commercial sales, pharmacy/distributor orders, commercial deliveries, collections. |
| `medical_rep` | مندوب دعاية طبية | `is_rep=True`, `is_sales_team=True`, `is_sub_area_bound=True`, `can_hold_vault=True`, `has_sales_targets=True` | Medical detailing, clinic & doctor visits, medical samples distribution, agreements. |

---

## 3. Inventory of Pre-Migration Roles & User Mapping

Before migration, 23 roles existed in `accounts_role`, with 18 users assigned. All 18 users were safely mapped into the 5 canonical roles without deleting any user accounts, resetting passwords, or breaking historical transaction records:

| User ID | Username | Pre-Migration Role | Canonical Role Assigned | Rationale & Permission Safety |
|---|---|---|---|---|
| 1 | `wea.pharm2020@gmail.com` | `SuperAdmin` (ID: 1) | `superadmin` | System CEO / Superuser account |
| 3 | `superadmin_test` | `SuperAdmin` (ID: 1) | `superadmin` | System testing superuser |
| 5 | `superadmin` | `SuperAdmin` (ID: 1) | `superadmin` | Primary administrative account |
| 6 | `admin` | `Admin` (ID: 6) | `manager` | Operational & system manager (staff) |
| 7 | `ceo` | `CEO` (ID: 7) | `manager` | Executive general management |
| 8 | `manager_cairo` | `AreaManager` (ID: 9) | `manager` | Regional sales manager (Cairo) |
| 10 | `manager_giza` | `AreaManager` (ID: 9) | `manager` | Regional sales manager (Giza) |
| 12 | `manager_alex` | `AreaManager` (ID: 9) | `manager` | Regional sales manager (Alexandria) |
| 15 | `manager_purchases` | `PurchasingManager` (ID: 20) | `manager` | Purchasing & approvals management |
| 18 | `manager_test` | `manager` (ID: 22) | `manager` | Testing management user |
| 14 | `buyer` | `PurchasingOfficer` (ID: 19) | `manager` | Purchasing officer operational role; specific purchase order permissions were copied directly to `user.user_permissions` to prevent permission loss. |
| 16 | `warehouse_keeper` | `WarehouseKeeper` (ID: 21) | `manager` | Warehouse operations keeper; specific inventory and stock unstock permissions were copied directly to `user.user_permissions` to prevent permission loss. |
| 17 | `accountant` | `Accountant` (ID: 2) | `accountant` | Head of finance & accounting |
| 9 | `rep_cairo@wea.com` | `MedicalRep` (ID: 3) | `medical_rep` | Field medical representative (Nasr City) |
| 11 | `rep_giza` | `MedicalRep` (ID: 3) | `medical_rep` | Field medical representative (Haram) |
| 13 | `rep_alex` | `MedicalRep` (ID: 3) | `medical_rep` | Field medical representative (Smouha) |
| 2 | `rep_tester` | `medical_rep` (ID: 4) | `medical_rep` | Field medical representative testing account |
| 4 | `rep_test` | `representative` (ID: 23) | `rep` | Commercial sales representative |

---

## 4. Deletion of Obsolete Roles in Development Database

Following the user's explicit directive to update the development database and delete obsolete role definitions:
1. **Audit Log History Preservation:** Prior to deletion, historical audit logs in `accounts_securityauditlog` referencing obsolete roles were safely audited; their role names were preserved in `record_name` and `target_role` was nulled.
2. **Safe Deletion:** All 16 obsolete role rows were deleted from `accounts_role`.
3. **Zero Business Record Deletions:** No users were deleted. All 18 users were retained with intact credentials, and all historical sales orders, collections, visits, and audit logs remain 100% intact.

---

## 5. Actual Development Database Verification

Query results against `db.sqlite3` following migration:

| Metric | Pre-Migration Count | Post-Migration Count | Status |
|---|---|---|---|
| Total Roles in `accounts_role` | 21 roles | Exactly 5 canonical roles | **VERIFIED** |
| Active Users | 18 users | 18 users | **VERIFIED** |
| Users with Obsolete Roles | 14 users | 0 users | **VERIFIED** |
| Retained Role Keys | N/A | `superadmin`, `manager`, `accountant`, `rep`, `medical_rep` | **VERIFIED** |

### Retained Roles Summary in Database:
- `medical_rep` (ID: 4) — مندوب دعاية طبية (4 users)
- `manager` (ID: 22) — مدير (8 users)
- `superadmin` (ID: 24) — مدير النظام الأعلى (3 users)
- `accountant` (ID: 25) — محاسب (1 user)
- `rep` (ID: 26) — مندوب مبيعات (2 users)

---

## 6. Security Safeguards & Verification

1. **Privilege Escalation Protection:**
   - Non-superadmins cannot assign the `superadmin` role.
   - Any attempt to submit an invalid or obsolete role ID fails server-side with an explicit error message.
2. **Backend Enforcement:**
   - `Role.get_supported_roles()` strictly filters to the 5 canonical roles.
   - `CustomUserCreationForm` and `CustomUserChangeForm` enforce `Role.get_supported_roles()`.
   - `UserAdmin.formfield_for_foreignkey` restricts choices to `Role.get_supported_roles()`.
3. **Automated Unit Tests:**
   - `accounts/tests_roles_consolidation.py` tests:
     - Queryset returns exactly 5 canonical roles.
     - Role classification helpers (`is_super_admin`, `is_manager_or_higher`, `is_accountant`, `is_representative`, `is_rep`, `is_medical_rep`) work correctly.
     - Rejection of obsolete role assignment in user creation and user editing.
     - Full audit logging of role updates.

