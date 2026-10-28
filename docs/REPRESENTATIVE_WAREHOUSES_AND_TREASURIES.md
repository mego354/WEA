# Representative Warehouses and Treasuries Architecture

## 1. Overview and Core Objectives

In this enterprise ERP system, field representatives (Medical Representatives, Commercial Representatives, etc.) handle inventory samples and commercial stock, as well as cash collections from customers. To ensure end-to-end auditability and strict accountability:
1. Every representative is assigned their own designated **Default Warehouse** (for physical and sample stock).
2. Every representative is assigned their own designated **Default Treasury / Vault** (for cash receipts and collections).
3. Resource provisioning is automated upon representative creation and configurable via the centralized **Users Settings** interface.
4. An idempotent backfill mechanism provisions resources for pre-existing representatives without altering existing financial balances or transaction history.

---

## 2. Configuration & Users Settings (`UserSettings`)

### Model Definition
The configuration is stored in the database via the `UserSettings` singleton model in `accounts.models`:

- `auto_create_rep_warehouse` (BooleanField, default=True): Automatically provisions a representative warehouse when a new representative is registered.
- `auto_create_rep_treasury` (BooleanField, default=True): Automatically provisions a representative cash vault when a new representative is registered.
- `default_warehouse_prefix` (CharField, default="WH-REP-"): Prefix used for generating unique warehouse codes.
- `default_treasury_prefix` (CharField, default="VAULT-REP-"): Prefix used for generating unique vault codes.
- `updated_at`, `updated_by`: Full audit trail tracking configuration modifications.

### Administration & Access Control
- The configuration interface is available at `/users/settings/` and `/settings/users/settings/`.
- Restricted exclusively to **SuperAdmins** (`request.user.is_superuser`). Regular users, accountants, and area managers receive an authorization error (HTTP 403 / permission denied).
- Disabling either setting prevents automatic provisioning for newly created representatives. A prominent notice in the UI documents the operational consequences of disabling automatic creation.
- A live diagnostic dashboard displays the total count of representatives, the number of representatives equipped with warehouses and treasuries, and any missing allocations.
- A manual **Backfill Action** button allows authorized administrators to preview and trigger provisioning for any unprovisioned representatives on demand.

---

## 3. Representative Identification Logic

To prevent erroneously provisioning warehouses and cash vaults for administrative, managerial, or non-representative staff, `accounts.services.is_representative(user)` evaluates user roles using strict domain criteria:

1. **Role Matching**: Checks whether the user's role is marked as `is_sales_team=True` or matches representative naming patterns (e.g. `MedicalRep`, `مندوب`, `مبيعات`).
2. **Managerial Exclusion**: Explicitly excludes users with managerial permissions (`is_area_manager=True`, `is_manager_role=True`) or managerial titles (`مدير`, `مشرف`, `supervisor`, `manager`, `director`).
3. **SuperAdmin Exclusion**: Superusers and administrators are never classified as field representatives.

---

## 4. Automatic Resource Provisioning Architecture

### Provisioning Service (`accounts.services.ensure_representative_resources`)
The resource provisioning logic is centralized in `ensure_representative_resources(user, create_warehouse=None, create_treasury=None)`:
- Executes within a database transaction (`transaction.atomic()`).
- Uses `select_for_update()` to prevent race conditions during concurrent user creation or profile updates.
- Evaluates `UserSettings.get_settings()` if explicit override flags are not supplied.

#### Warehouse Creation Specifications
- **Code Generation**: Sequential formatting `WH-REP-{user.id:04d}` (e.g., `WH-REP-0012`).
- **Name**: `مخزن المندوب - {user.get_full_name()}`.
- **Attributes**: `is_rep_warehouse=True`, `is_active=True`, `assigned_user=user`.
- **Area Association**: Inherits the primary assigned area of the representative (main governorate or secondary district) to ensure correct regional filtering.

#### Treasury / Vault Creation Specifications
- **Code Generation**: Sequential formatting `VAULT-REP-{user.id:04d}` (e.g., `VAULT-REP-0012`).
- **Name**: `خزينة المندوب - {user.get_full_name()}`.
- **Attributes**: `is_rep_vault=True`, `is_active=True`, `assigned_user=user`, `balance=0.00`.
- **Financial Integrity**: Never manufactures synthetic opening balances. Initial balance is strictly zero, and subsequent movements are recorded through verified collection receipts and accounting vouchers.

### Signal Handling (`accounts.signals`)
- **`post_save` on `User`**: Triggered when a representative user is created or updated. If `created=True`, automatically invokes `ensure_representative_resources`.
- **`m2m_changed` on `User.assigned_areas.through`**: When assigned territories or sub-areas change, updates the representative's warehouse `area` attribute to preserve regional alignment.
- **Recursive Save Prevention**: Handled via `update_fields` or direct filter updates, preventing infinite signal recursion loops.

---

## 5. Idempotent Backfill Management Command

A dedicated CLI command is provided for safe, auditable backfilling of existing representatives:

```bash
# Preview unprovisioned representatives (dry-run)
python manage.py backfill_representative_resources --dry-run

# Execute idempotent backfill
python manage.py backfill_representative_resources
```

### Safety Guarantees
1. **Zero Balance Alteration**: Existing cash balances, journal vouchers, and stock movements remain completely untouched.
2. **Pre-existing Resource Detection**: If a representative already owns a warehouse (`assigned_user=user`) or vault, the backfiller logs the existing mapping and skips creation.
3. **Audit Logging**: Outputs structured summary metrics indicating total representatives analyzed, warehouses created, treasuries created, and skipped records.
