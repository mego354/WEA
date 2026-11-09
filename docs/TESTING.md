# Testing Strategy & Reference

This document details the test suite structure, execution workflows, standards, and coverage inventory for WEA Pharma ERP.

---

## 1. Consolidated Test Architecture

The test suite is structured following a strict rule: **exactly one primary test file per Django app**:

```text
ERP/
├── accounts/tests.py        # 104 tests (RBAC, Scopes, Audit, Provisioning, Scoped Querysets)
├── activities/tests.py      # 114 tests (Visits, Templates, GPS, Agenda, Approvals, Agreements)
├── catalog/tests.py         #  16 tests (Products, Categories, Discounts, Packaging)
├── contacts/tests.py        #  21 tests (Contacts, UDF, Todos, Timeline, Subareas API)
├── inventory/tests.py       #  14 tests (Warehouses, Stock, Lots, Transfers, Memos)
├── master_data/tests.py     #  51 tests (Areas, Dashboard Stats, Settings, Pagination, Filters)
├── purchases/tests.py       #  19 tests (Purchase Orders, Receiving, Supplier Payments)
├── sales/tests.py           #  12 tests (Sales Orders, Collections, Rep Scoping)
└── treasury/tests.py        #  20 tests (Vaults, Cash Transactions, Deposit/Withdraw Auth)
---------------------------------------------------------------------------------
Total: 9 Consolidated Test Files, 371 Total Behavioral Tests (100% Passing)
```

---

## 2. Test Execution Commands

### Run Entire Test Suite
```bash
python manage.py test
```

### Run Specific App Test File
```bash
python manage.py test accounts
python manage.py test activities
python manage.py test contacts
python manage.py test sales
```

### Run Specific Test Case Class
```bash
python manage.py test activities.tests.AgreementWorkflowTests
python manage.py test accounts.tests.ConfigurableAuthorizationScopeTests
```

### Run Individual Test Method
```bash
python manage.py test activities.tests.AgreementWorkflowTests.test_agreement_anti_self_approval_and_audit
```

---

## 3. Testing Standards & Quality Requirements

1. **Deterministic Test Isolation**:
   - Every test runs inside a database transaction that rolls back automatically upon completion (`django.test.TestCase`).
   - Zero dependence on pre-existing development or production databases.
2. **Real Business Workflows**:
   - Tests execute real status transitions, permissions resolution, and calculations rather than asserting trivial mock states.
3. **No External Network Calls**:
   - Geocoding, Google Maps APIs, and external web services are strictly mocked or bypassed in test environments.
4. **Comprehensive Scoping Verification**:
   - Every module verifies data isolation across roles (SuperAdmin, Manager, Accountant, Representative) and confirms that IDOR attacks on URL `pk` endpoints fail closed with HTTP 403 or 404.
5. **Audit Trail Verification**:
   - Mutation tests assert the creation of corresponding `SecurityAuditLog` or `ApprovalAuditLog` records.

---

## 4. Test Class Coverage Map

| App | Test Classes | Test Responsibilities |
|---|---|---|
| `accounts` | `AccountsModelTests`, `UserManagementViewTests`, `RoleManagementViewTests`, `ERPAuthorizationSecurityTests`, `AreaBasedApprovalsAndVisibilityTests`, `AuditLoggingTests`, `ConfigurableAuthorizationScopeTests`, `AppWideDataScopingTests`, `GeographicAreaSelectorTests`, `SettingsServiceArchitectureTests`, `PermissionSimplificationTests`, `OrganizationalDataScopingAndSecurityTests`, `RepresentativeProvisioningTests`, `UserRoleConsolidationTests`, `UserDedicatedPagesAndLocationTests`, `UserPermissionsGranularControlTestCase` | Authentication, canonical roles, 4 configurable scopes (`OWN`, `BRICK`, `AREA`, `ALL`), `view_scope` vs `manage_scope`, direct user authority (`has_custom_permissions`), representative warehouse/vault auto-provisioning, audit logging. |
| `activities` | `ActivitiesModuleTestCase`, `VisitAndLocationParityTestCase`, `VisitTemplatesManagementTestCase`, `VisitTemplatesWorkflowIntegrationTestCase`, `VisitWorkflowsAndPermissionsComprehensiveTestCase`, `VisitManagementImprovementsTestCase`, `RefinedVisitRequirementsTestCase`, `GPSValidationAndToleranceTestCase`, `AgendaWorkflowTests`, `RoleBasedTemplatesAndRegionalApprovalsTestCase`, `VisitSuggestedProductsTests`, `ComprehensiveUserWorkflowsTestCase`, `VisitsScopeGbsTests`, `AgreementWorkflowTests` | Visit lifecycles, planned vs unplanned auto-detection, GPS tolerance & geofencing, bypass exception handling, scheduled time quick actions, template role restrictions, mandatory questions, representative post-approval editing invalidation, anti-self-approval on agreements. |
| `catalog` | `ProductCatalogModelTests`, `ProductManagementViewTests`, `ProductCategoryTests`, `VolumeDiscountTests` | Products, SKU codes, categories, pricing, volume discounts, sellable flags, packaging units. |
| `contacts` | `ContactModelTests`, `ContactViewsTests`, `CustomerSearchAPITests`, `ContactUDFTodoTimelineTests`, `ContactERPIntegrationTests` | Client directory, doctor classifications, UDF custom fields, todos, interaction timeline, subareas API scoping. |
| `inventory` | `InventoryModelTests`, `WarehouseViewTests`, `ProductTransferRequestTests`, `InterWarehouseTransferWorkflowTests` | Warehouses, stock levels, lot tracking, same-main-area transfer workflows, available stock validation, Stock In/Out memos. |
| `master_data` | `AreaModelTests`, `CompanyProfileTests`, `DashboardAndSettingsTests`, `AreaManagementTests`, `DashboardRolePermissionsTests`, `EgyptAreasStructureTests`, `PaginationAndFiltersTests`, `DashboardStatsAndLifecycleTests` | Two-level territorial hierarchy (Governorate / Brick), company settings, executive dashboard KPI calculations, `SettingsService` request caching. |
| `purchases` | `PurchaseOrderModelTests`, `PurchaseOrderViewsTests`, `PurchaseOrderLifecycleTests`, `VendorPaymentSettlementTests` | Purchase order creation, pricing validation, supplier approval, stock receiving memos, vendor ledger settlement. |
| `sales` | `SalesOrderModelTests`, `SalesOrderViewsTests`, `SalesOrderWorkflowTests`, `RepresentativeSalesScopingTests` | Sales orders, discounts, taxes, rep warehouse stock validation, delivery transactions, collections into cash vaults. |
| `treasury` | `VaultModelTests`, `VaultViewsTests`, `TreasuryTransactionTests`, `TreasuryRbacAndStatsTests`, `VaultAuthorizationSecurityTests` | Cash vaults, deposits, withdrawals, internal transfers, balance locking (`select_for_update`), deposit/withdraw permissions. |

