# Core Business Logic & Workflows

This document describes the business rules, transaction invariants, lifecycle status machines, and financial/inventory logic implemented in WEA Pharma ERP.

---

## 1. Field Visit Lifecycle (`activities`)

```mermaid
stateDiagram-v2
    [*] --> Planned : Bulk Planning (/planned-visits/)
    [*] --> Unplanned : Direct Creation (/visits/create/)
    
    Planned --> PendingApproval : Created (Requires Manager Approval)
    Unplanned --> PendingApproval : Created (Within Tolerance OR Exception Requested)
    
    PendingApproval --> Approved : Manager Approves (visit_action)
    PendingApproval --> Disapproved : Manager Rejects
    
    Approved --> InProgress : Start Visit (start_visit)
    Approved --> PendingApproval : Rep Edits (waiting_for_reapproval=True)
    
    InProgress --> Completed : Checkout / End Visit (end_visit)
    Completed --> [*]
```

### 1.1 Automatic Planned vs. Unplanned Determination
- **Zero Ambiguity**: Manual selection of planned vs. unplanned visit type has been eliminated.
- **Unplanned Visits**: Initiated only via `/visits/create/` (e.g. from the global navigation `+` button). The backend automatically sets `is_planned=False`.
- **Planned Visits**: Generated exclusively via bulk daily planning (`/planned-visits/bulk-add/`). When executed, the representative provides `planned_item_id`, setting `is_planned=True` and linking `item.visit = visit`.

### 1.2 GPS Distance Validation & Geofencing
- **Configurable Allowed Distance**:
  - Global default: `LocationSettings.tolerance` (default 300 meters).
  - Template override: If `LocationSettings.allow_template_distance_override` is enabled and `VisitTemplate.has_special_location_settings=True`, the template's `special_tolerance` takes precedence.
- **Creation Validation**:
  - Mandatory for **unplanned** visits (`LocationSettings.verify_unplanned_visit_distance=True`).
  - **Not enforced** on creation for **planned** visits (since planned visits are scheduled ahead of time).
- **Completion Validation (End Visit)**:
  - Mandatory for both planned and unplanned visits (`LocationSettings.verify_end_visit_distance=True`).
- **Bypass & Exception Handling**:
  - **SuperAdmins and Managers**: Can directly force-bypass distance restrictions (`verification_status='force_bypassed'`).
  - **Representatives**: When outside the geofence, reps cannot directly bypass. They must request an exception (`request_distance_exception=1`) with a mandatory text `bypass_reason`. This flags `requires_approval_due_to_distance=True` and marks `approval_status='pending'`.

### 1.3 In-Progress Visit Editing & Smart Reapproval
- **Status Locking**: Visits that have ended (`status == 'finished'`) are strictly locked from modification to preserve audit integrity and historical records.
- **In-Progress Editing**: Visits in progress (`status in ['planned', 'draft', 'started']`) may be edited by authorized users.
- **Smart Reapproval Triggering**:
  - When an already-approved visit (`approval_status='approved'`) is edited by a representative and critical fields change (`date`, `contact`, `template`, `owner`, `doubled`, `questionnaire_answers`, or `detailed_products`):
    - Approval is immediately revoked: `approval_status = 'pending'`.
    - The flag `waiting_for_reapproval = True` is set.
    - Previous `ApprovalAuditLog` records are preserved, and an `edited_reapproval_required` log is appended.
    - The visit cannot proceed to execution until an authorized manager re-approves it.
  - When edited by an authorized manager/supervisor, approval is retained (`approval_status='approved'`) and an `edited_by_manager` entry is recorded in `ApprovalAuditLog`.

### 1.4 Visit Start Workflow & Questionnaire Stages
- **Separation of Stages**:
  - `start_only`: Check-in questions answered when starting the visit (e.g. site open status, arrival observations).
  - `end_only` / `all`: Completion questions answered when documenting and concluding the visit (e.g. detailing outcome, objections, sample delivery).
- **Check-In Validation**:
  - Required `start_only` questions are validated server-side during the `start_visit` mutation.
  - Successful start transitions the visit to `status = 'started'`, sets `started_at`, and populates `visit.questionnaire_answers`.
- **Elimination of Duplicate Start**:
  - Once started, the active visit dossier immediately renders the completion form and the "End Visit" (`complete`) action.
  - The "Start Visit" button is hidden once active, and duplicate start POST requests redirect safely without state degradation.

### 1.5 Scheduled Time & Quick Actions
- Visits maintain a dedicated `time` (`TimeField`) and localized Arabic 12-hour property `formatted_time`.
- An inline AJAX modal endpoint (`POST /activities/visits/<pk>/set-time/`) allows adjusting scheduled visit times without a page refresh, audited via `SecurityAuditLog`.

### 1.6 Visit Templates & Mandatory Questions
- **Role Restrictions**: Templates can be restricted to specific roles (`restricted_roles`). Unrestricted templates are available to all authorized roles.
- **Client-First Filtering**: Available templates dynamically filter based on the selected contact's account type (`is_contact_eligible(contact)`).
- **Mandatory Completion Validation**: When ending a visit (`can_end_visit`), every required question in the template (including active conditional questions) must have non-empty answers.

---

## 2. Data Integrity, Foreign Key Protection & Unified Deletions
- **Protected Relations (`ProtectedError`)**: Physical deletion of core entities (Products, Contacts, Areas, Roles) is protected by foreign key constraints. If related records exist (e.g. stock movements, invoices, visits, subareas, users), deletion is prevented and a clear, descriptive Arabic error message is displayed.
- **Audit Trails & Reversals**: Financial transactions (e.g. `VaultTransaction`) and inventory documents are never hard-deleted; instead, business logic requires financial reversal (`vault_transaction_reverse`) creating an explicit reversing entry and balancing the ledger.
- **Global Confirmation Standard**: All deletion and reversal actions trigger the unified modal (`showConfirmDeleteModal`) rather than native browser alerts.

---

## 2. Sales Order Lifecycle (`sales`)

```mermaid
stateDiagram-v2
    [*] --> Pending : Rep Creates Order
    Pending --> ManagerApproval : Submitted (SalesSettings.require_manager_approval)
    ManagerApproval --> Preparing : Manager Approves
    ManagerApproval --> Rejected : Manager Rejects
    Preparing --> Delivered : Warehouse Delivers (Stock Decremented)
    Delivered --> Invoiced : Invoicing & Customer Ledger Debited
    Invoiced --> [*]
```

### 2.1 Available Stock Validation
- On order creation and delivery, the system strictly validates that available warehouse stock (`qty_on_hand - qty_reserved`) is greater than or equal to the ordered quantity.
- Sales by representatives are strictly constrained to their designated representative warehouse (`rep.get_default_warehouse()`).

### 2.2 Pricing, Discounts, and Taxes
- **Line-Item Discounts**: Verified to be between 0% and 100%.
- **Order-Level Discounts**: Verified not to exceed subtotal.
- **Shipping Fees**: Strictly non-negative.
- **Taxation Modes**: Inclusive or Exclusive based on `CompanyProfile.tax_mode`.

### 2.3 Atomic Delivery & Financial Ledger
- Order delivery executes inside `@transaction.atomic` using `select_for_update()` row locks on `InventoryStock`.
- Delivery generates a balanced outward inventory memo.
- Invoicing records the balance on `CustomerAccount` via `CustomerTransaction`.
- Customer payments (`Collection`) credit the customer ledger and debit the representative's cash vault (`rep.get_default_treasury()`).

---

## 3. Purchase Order Lifecycle (`purchases`)

```mermaid
stateDiagram-v2
    [*] --> Pending : Purchase Order Created
    Pending --> Approved : Manager / SuperAdmin Approves
    Pending --> Rejected : Rejected
    Approved --> Picked : Warehouse Receives Stock (Memos + Stock Added)
    Picked --> Settled : Vendor Ledger Recorded & Invoiced
    Settled --> [*]
```

### 3.1 Supplier Validation and Costing
- Suppliers must be active vendor contacts.
- Unit prices must be non-negative; quantities must be strictly positive.
- When an order is marked as `picked` / received:
  - Inventory stock is increased inside `@transaction.atomic`.
  - The product's weighted average unit cost is recalculated:
    $$\text{New Cost} = \frac{(\text{Current Qty} \times \text{Current Cost}) + (\text{Received Qty} \times \text{Purchase Price})}{\text{Current Qty} + \text{Received Qty}}$$
  - A permanent Stock In memo is recorded.

### 3.2 Vendor Settlement & Treasury Payments
- Settling a purchase order creates a liability entry on the vendor ledger (`VendorAccount`).
- Payments to vendors (`VendorPayment`) are disbursed from authorized cash vaults, validating sufficient vault balance and generating `SecurityAuditLog` entries.

---

## 4. Multi-Warehouse Inventory Transfers (`inventory`)

```mermaid
stateDiagram-v2
    [*] --> Pending : Rep / Manager Requests Transfer
    Pending --> Approved : SuperAdmin / Accountant Approves
    Pending --> Rejected : Rejected
    Approved --> Transferred : Stock Moved Atomically (Paired In/Out Memos)
    Transferred --> [*]
```

### Transfer Invariants
1. **Different Warehouses**: Source and destination warehouses must be distinct.
2. **Same Main Area Boundary**: Unless requested by SuperAdmin, both warehouses must belong to the same canonical root Main Area (`Area.parent is None`). Cross-governorate unauthorized transfers are blocked.
3. **Available Stock Reservation**: Source warehouse available stock (`qty_on_hand - qty_reserved`) must strictly cover the transferred quantity.
4. **Accountant / SuperAdmin Authority**: Area managers cannot approve transfers; execution is reserved for SuperAdmin and Accountant roles.
5. **Atomic Execution**: Creates matched Stock Out (source) and Stock In (destination) inventory memos inside `@transaction.atomic`.

---

## 5. Treasury Operations (`treasury`)

- **Cash Vaults (`Vault`)**: Each representative has a dedicated cash vault for collections. Central vaults hold corporate funds.
- **Deposit / Withdraw Operations**: Viewing a vault does not grant funds mutation rights. Deposits and withdrawals require `treasury:vaults/transfer` or `treasury:transactions/create` permissions.
- **Concurrency Safety**: Vault balances are locked using `select_for_update()` during deposits, withdrawals, and collections.
- **Negative Balance Prevention**: Withdrawals and outgoing transfers cannot exceed current vault balance.

---

## 6. Contacts, Communication Methods & Geographic Scoping (`contacts`, `master_data`)

- **Universal Customer Classification**: All organizational and individual contacts are classified as customers (`status='customer'`, `is_customer=True`). Legacy 'lead' classification is retired from contact workflows, and customer financial accounts (`CustomerAccount`) are guaranteed for all customer contacts.
- **Communication Methods CRUD (`ContactCommunicationMethod`)**: Complete CRUD support in contact overview and edit screens for communication types (`mobile`, `phone`, `email`, `whatsapp`, `website`, `other`). Marking a communication method as primary automatically synchronizes with primary contact fields (`mobile`, `phone`, `email`, `website`).
- **Unified Geographic Hierarchy**: Strict 2-level hierarchy where Governorate (`parent is None`) contains Bricks/Sub-areas (`parent is not None`). Duplicate governorates (Cairo/Giza) are unified and deduplicated.
- **Multi-Area & Multi-Brick Selection**: Planned visits bulk planning drawer supports multiple governorate and multiple brick selection with cascading dependency filtering.
- **Resilient Egyptian Geocoding (GBS)**: Address and location lookups are constrained to Egypt (`countrycodes=eg`, Egypt bounding box, `addressdetails=1`), with multi-tier fallback (Google Maps -> Nominatim Egypt -> Photon Komoot -> Local database Area matching). Result selection emits `erp:location-selected` event to auto-populate administrative address fields.
- **Filtered Statistics**: Metric cards and list counters dynamically reflect active filters (search, status, relation, area, brick) evaluated over the filtered queryset prior to pagination.

