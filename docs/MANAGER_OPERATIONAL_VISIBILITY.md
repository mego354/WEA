# Manager Operational Visibility and Scope Controls

## 1. Zero New Navigation Overhead Rule

To prevent navigation fragmentation and cognitive overload:
> **Zero new application tabs, sidebar items, or navigation links were introduced.**

All manager oversight capabilities are seamlessly embedded directly into existing modules:
- **Inventory & Warehouses**: `/inventory/warehouses/`, `/inventory/stock/`, `/inventory/transfers/`
- **Activities & Visits**: `/activities/visits/`, `/activities/approvals/`, `/activities/agenda/`
- **Treasury & Finance**: `/treasury/vaults/`, `/treasury/vaults/<id>/`, `/treasury/transactions/`
- **Sales & Orders**: `/sales/orders/`, `/sales/collections/`

---

## 2. Main-Area Scoped Operational Oversight

When an Area Manager navigates the ERP, backend query scoping (`get_scoped_queryset`) filters records dynamically based on the manager's assigned root main areas:

### 1. Warehouse Oversight (`/inventory/warehouses/`)
Managers can inspect:
- **Warehouse Identification**: Name, code, designated representative owner (`المسؤول: {اسم المندوب}`).
- **Geographic Area**: Main governorate and district tags.
- **Stock Levels & Valuation**: Quantities, reserved quantities, available stock in `/inventory/stock/`.
- **Transfer Requests**: Pending and historical inter-warehouse product requests in `/inventory/transfers/`.
- **Stock Movements**: Inward and outward memos associated with representative operations.

### 2. Visit Oversight (`/activities/visits/`)
Managers can inspect:
- **Visit Scheduling**: Planned vs unplanned visits across all sub-areas under their root governorate.
- **Real-Time Execution**: Check-in / check-out timestamps and calculated duration.
- **Field Data**: Questionnaire responses, template answers, uploaded customer notes, and verification data.
- **Visit Approval**: Instant single-click or batch approval via the central Approvals Hub.

### 3. Treasury Oversight (`/treasury/vaults/`)
Managers can inspect:
- **Vault Identification**: Representative cash vault code and designated representative owner.
- **Live Cash Balance**: Real-time balance computed by the accounting ledger.
- **Collection History**: Customer collection receipts, voucher numbers, and deposit dates.
- **Transaction Audit Trail**: Detailed line-by-line audit of movements via `/treasury/vaults/<id>/`.

---

## 3. Strict Read-Only Protection on Treasuries

> [!CAUTION]
> **Visibility does NOT grant financial transaction authority.**

A manager's ability to inspect a representative's cash treasury is strictly supervisory. Under no circumstances may a manager:
- Deposit cash into a representative's vault.
- Withdraw funds from a representative's vault.
- Execute inter-vault transfers.
- Adjust cash balances or delete transactions.

### Enforcement Mechanism
This policy is enforced at the Django model and view permission layer in `accounts.permissions.can_user_access_object`:

```python
if model_name == 'vault' and action in ['deposit', 'withdraw', 'transfer', 'adjust', 'edit', 'delete']:
    if getattr(obj, 'is_rep_vault', False):
        if not user.is_superuser:
            return False  # Strict read-only: Managers can view, but cannot move funds
```

Any direct POST or API call attempting financial operations on representative vaults by a manager is blocked and returns an authorization error.

---

## 4. Mobile Responsiveness and Cross-Device Layouts

All updated pages are responsive and mobile-friendly:
- **Compact Data Cards**: Complex tabular data folds into readable stacked cards on narrow viewports.
- **Touch-Friendly Buttons**: Action triggers and approval buttons feature 44px minimum touch targets.
- **Viewport Testing**: Verified across 375px (iPhone SE), 390px (iPhone 13/14), 430px (iPhone Pro Max), and desktop screens (1440px).
- **Zero Page Overflow**: Tables and grids scroll within bounded containers without triggering window-level horizontal layout breaks.
