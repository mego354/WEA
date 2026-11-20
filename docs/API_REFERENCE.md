# API & AJAX Reference

This document provides specifications for the JSON and AJAX endpoints exposed by WEA Pharma ERP.

---

## 1. Authentication and Authorization

All API endpoints require active session authentication (`request.user.is_authenticated`).
Unauthorized requests return HTTP 401 Unauthorized or HTTP 403 Forbidden with `{ "error": "غير مصرح" }`.

---

## 2. Customer & Area Endpoints

### 2.1 Customer Search (`customers_search_api`)
- **URLs**:
  - `/api/customers/search/`
  - `/api/v1/visits/contacts/list` (Reference ERP Alias)
- **Method**: `GET`
- **Scoping**: Strictly scoped via `get_visit_eligible_contacts_queryset(request.user)`.
- **Query Parameters**:
  - `q` (string, optional): Search query (name, code, phone).
  - `type` (string, optional): Filter by account type (`pharmacy`, `clinic`, `hospital`, etc.).
- **Response Format**:
  ```json
  [
    {
      "id": 104,
      "name": "صيدلية النور",
      "code": "CUST-00104",
      "account_type": "pharmacy",
      "governorate": "القاهرة",
      "brick": "مدينة نصر",
      "latitude": 30.0543,
      "longitude": 31.3412
    }
  ]
  ```

### 2.2 Subareas / Bricks API (`get_subareas`)
- **URL**: `/contacts/api/subareas/`
- **Method**: `GET`
- **Permission**: `@require_permission('contacts:contacts/list')`
- **Query Parameters**:
  - `area_id` or `governorate_id` (integer, required): ID of the parent governorate.
- **Response Format**:
  ```json
  {
    "success": true,
    "subareas": [
      {
        "id": 12,
        "name": "حي الدقي",
        "code": "DOKKI-01"
      }
    ]
  }
  ```

### 2.3 Contact Communication Methods CRUD
- **Add**: `POST /contacts/<pk>/communication-methods/add/`
  - Body: `method_type` (mobile, phone, email, whatsapp, website, other), `value`, `label`, `is_primary`.
  - AJAX response: `{"success": true, "method": {...}}`.
- **Edit**: `POST /contacts/<pk>/communication-methods/<method_id>/edit/`
  - Body: `method_type`, `value`, `label`, `is_primary`.
  - AJAX response: `{"success": true, "method": {...}}`.
- **Delete**: `POST /contacts/<pk>/communication-methods/<method_id>/delete/`
  - AJAX response: `{"success": true, "deleted_id": ...}`.

### 2.4 Egyptian Geocoding Search Proxy (`geocoding_search_api`)
- **URL**: `/api/geocoding/search/`
- **Method**: `GET`
- **Permission**: Login required (`@login_required`)
- **Query Parameters**:
  - `q` (string, required): Location or area search term.
- **Response Format**:
  ```json
  {
    "results": [
      {
        "lat": 30.0444,
        "lon": 31.2357,
        "display_name": "الدقي، محافظة الجيزة، مصر",
        "address": {
          "road": "شارع مصدق",
          "suburb": "الدقي",
          "city": "الجيزة",
          "state": "محافظة الجيزة",
          "country": "مصر"
        }
      }
    ]
  }
  ```

### 2.5 Scoped Area & Brick Multiselect APIs
- **Contacts Areas / Bricks**:
  - `GET /contacts/api/areas/?q=...` (`contacts_search_areas_api`)
  - `GET /contacts/api/bricks/?q=...&main_area=...` (`contacts_search_bricks_api`)
- **Planned Visits Areas / Bricks**:
  - `GET /planned-visits/api/areas/?q=...` (`planned_visits_search_areas_api`)
  - `GET /planned-visits/api/bricks/?q=...&main_area=...` (`planned_visits_search_bricks_api`)
- **Behavior**:
  - Opening either multiselect with empty `q` immediately returns authorized choices up to safe limits.
  - Passing `main_area` restricts Bricks to children within selected Main Areas (still strictly intersected with user scope).
  - Without `main_area`, returns all Bricks within the user's authorized scope without expanding a rep's brick to sibling bricks in the same governorate.

---

## 3. Activities & Visits Endpoints

### 3.1 Visit Duplicate Check (`visit_check_duplicate_api`)
- **URL**: `/activities/visits/check-duplicate/`
- **Method**: `GET`
- **Permission**: `@require_permission('activities:visits/create')`
- **Query Parameters**:
  - `customer_id` (integer, required): Target client ID.
  - `date` (string `YYYY-MM-DD`, required): Scheduled visit date.
- **Response Format**:
  ```json
  {
    "duplicate": true,
    "existing_visit_id": 412,
    "message": "توجد زيارة مسجلة بالفعل لهذا العميل في نفس التاريخ"
  }
  ```

### 3.2 Visit Plan Action Endpoint (`plan_action`)
- **URL**: `POST /planned-visits/plan/<pk>/action/<action>/` (or `/plans/<pk>/action/<action>/`)
- **Method**: `POST`
- **Actions**: `approve`, `disapprove`
- **Permission**: `@require_permission('activities:visits/approve')` plus scoped data access
- **Payload (`application/x-www-form-urlencoded` or JSON)**:
  - `approval_notes` (string, optional): Decision notes
- **Response Format**:
  ```json
  {
    "success": true,
    "approval_status": "approved",
    "message": "تم اعتماد الخطة رقم PLAN-20261117-0001 بنجاح (10 زيارات)."
  }
  ```

### 3.3 Planned Visits Selection & Bulk Creation
- `GET /planned-visits/?action=select_all_ids` (with active filters): returns `{ "success": true, "total_count": N, "contacts": [{"id": 1, "account_type": "..."}] }` across all filtered scoped results.
- `GET /planned-visits/?action=load_contacts&show_all=1`: returns all matching scoped contacts in one batch for "عرض جميع العملاء المؤهلين".
- `POST /planned-visits/bulk-add/`: atomically creates a `VisitPlan` entity (with unique `plan_id` and plan-level comment), `PlannedVisitDay`, `PlannedVisitItem`, and linked `Visit(status='planned', is_planned=True)` records. Visits are created as `pending` approval if the creator lacks `activities:visits/approve`. Returns `plan_id`, `created_count`, and `created_visit_ids`.

### 3.4 Unended Visit Deletion (`visit_delete`)
- **URL**: `POST /visits/<pk>/delete/`
- **Permission**: Controlled by `LocationSettings.allow_visit_deletion_before_end` and `activities:visits/delete` (`can_delete_unended_visit`) plus object-level scope (`can_user_access_object(request.user, visit, 'delete')`).
- **Behavior**: Deletes only visits that have not ended (`status != 'finished'` and `ended_at is None`) and writes `VISIT_DELETED` to `SecurityAuditLog`. Returns `{ "success": true, "message": "...", "redirect_url": "/visits/" }` for AJAX requests.

### 3.5 Visit Questionnaire Answers Update (`visit_update_answers`)
- **URLs**:
  - `POST /activities/visits/<pk>/update-answers/`
  - `POST /visits/<pk>/update-answers/` (Reference ERP Alias)
  - `POST /visits/<pk>/answers/edit/` (Legacy Alias)
- **Permissions Required**: `@require_permission(['activities:visits/edit_answers', 'activities:visits/edit'])` and `can_edit_visit_answers(request.user, visit)`
- **Restrictions**:
  - Visit must be ended (`visit.status == 'finished'` and `visit.ended_at is not None`). Editing answers on unended visits is strictly forbidden.
  - User must be the visit owner/creator (`visit.owner_id == request.user.id or visit.created_by_id == request.user.id`) or SuperAdmin.
- **Re-approval Behavior & Creator Edit Tracking**:
  - Supports `question_<id>` answers across all question types including `suggested_products` (with `<question>_present=1` marker for clearing multiselects) and legacy `detailed_products` (`detailed_products_present=1` when template has no `suggested_products` question).
  - Validates submitted product IDs against eligible sellable active products unioned with existing historical selections on that visit.
  - Updating answers triggers immediate re-approval (`approval_status = 'pending'`, `waiting_for_reapproval = True`, clears `approved_by`/`approved_at`), updates `last_edited_by`/`last_edited_at` (and `edited_by_creator=True` when `visit.created_by_id == request.user.id`), and writes readable diffs to `ApprovalAuditLog(action='answers_updated')` and `SecurityAuditLog(action='VISIT_ANSWERS_UPDATED')`.
- **Response Format**:
  - AJAX: `{ "success": true, "message": "تم تحديث إجابات الاستبيان بنجاح، والزيارة بانتظار إعادة الاعتماد" }`
  - Standard POST: Redirects to `/activities/visits/<pk>/` with success flash message.

### 3.6 Visit Action Workflow (`visit_action`)
- **URL**: `POST /activities/visits/<pk>/action/<action_type>/` (where `action_type` in `start`, `end`, `cancel`)
- **Method**: `POST`
- **Actions**:
  - `start`: Starts an unstarted visit (`status='planned'|'unplanned'`).
    - Validates GBS coordinates against client coordinates within tolerance (unless distance bypass is authorized for the user's role).
    - Checks `request_distance_exception`: strictly verified against `settings.can_user_request_distance_exception(user)`. If requested, flags `is_distance_exception_requested=True` and enforces manager approval upon visit end.
    - Handles start-only question answers.
    - Transitions `status='in_progress'`, sets `started_at=now()`, `start_latitude`, `start_longitude`.
    - Both Agenda and Visit Detail view use this unified endpoint.
  - `end`: Ends an in-progress visit (`status='in_progress'`).
    - Validates end GBS coordinates and end questionnaire answers.
    - Transitions `status='finished'`, sets `ended_at=now()`.
    - Evaluates approval: if unplanned, or distance exception requested, or questionnaire answered, flags for approval (`pending`); if planned without exceptions, auto-approves (`approved`).
  - `cancel`: Legacy cancellation action (retained for backward compatibility; unended visits are deleted via `/visits/<pk>/delete/` per Requirement J).

### 3.7 Agreements CRUD & Lifecycle Endpoints
- **List & Filters**: `GET /activities/agreements/`
  - Scoped via `get_scoped_queryset(Agreement.objects.all(), request.user, 'agreement')`.
  - Filters: `customer`, `status` (`new`, `done`, `disapproved`), `amount_min`, `amount_max`, `date_from`, `date_to`, `governorate`, `brick`.
- **Status Action**: `POST /activities/agreements/<pk>/action/<action>/`
  - Actions: `done` (mark agreement done/completed), `reopen` (reopen to `new`).
  - Permission: `@require_permission('activities:agreements/approve')` and `can_user_access_object(request.user, agreement, action)`.
  - Anti-self-approval: Creators cannot approve or complete their own agreements.
- **Edit**: `GET|POST /activities/agreements/<pk>/edit/`
  - Permission: `@require_permission('activities:agreements/edit')`, `can_user_access_object(request.user, agreement, 'view'/'edit')`, and `agreement.status in ('new', 'disapproved')`.
- **Delete**: `POST /activities/agreements/<pk>/delete/`
  - Permission: `@require_permission('activities:agreements/delete')`, `can_user_access_object(request.user, agreement, 'view'/'delete')`, and `agreement.status in ('new', 'disapproved')`.
  - Removes linked `ERPAttachment` rows atomically and writes `AGREEMENT_DELETED` to `SecurityAuditLog`. Returns `{ "success": true, "redirect_url": "/agreements/" }` for AJAX callers (or HTTP 400 JSON if status is finalized).

### 3.8 Visits Templates API & Creator-Edit Filter
- **Templates API (`visit_templates_api`)**: `GET /activities/api/templates/?contact_id=...`
  - Includes active questions (with `'suggested_products'`) and `suggested_products: [{id, name, sku_code}]` pool resolved via `VisitTemplate.get_suggested_products_pool()`.
- **Visits List & Export Creator-Edit Filter**: `GET /visits/` and `GET /visits/export/`
  - Query parameter `edited_by_creator=yes|no` filters by `Visit.edited_by_creator` within `ScopeResolutionService` and combines cleanly with search, status, approval, date, area/brick, and pagination parameters.

---

## 4. Purchases & Sales Scoped Endpoints

### 4.1 Purchase Order Print & Export Protection
- **Print View**: `GET /purchases/orders/<pk>/print/`
  - Enforces `can_user_access_object(request.user, order, 'view')`. Attempts to access out-of-scope purchase orders return HTTP 403 Forbidden.
- **Export View**: `GET /purchases/orders/export/`
  - Applies `get_scoped_queryset(qs, request.user, 'purchaseorder')`. Exports only orders authorized within the user's module scope.
- **Split View**: `GET|POST /purchases/orders/<pk>/split/`
  - Enforces `can_user_access_object(request.user, order, 'edit')`. Out-of-scope access returns HTTP 403.
- **Create & Edit Views**: `POST /purchases/orders/create/` and `POST /purchases/orders/<pk>/edit/`
  - Enforces object-level access checks on submitted `supplier` (`can_user_access_object(request.user, supplier, 'view')`) and `warehouse` (`can_user_access_object(request.user, warehouse, 'operate')`).
- **Delete View**: `POST /purchases/orders/<pk>/delete/`
  - Permission: `@require_permission('purchases:orders/delete')` and `can_user_access_object(request.user, order, 'delete')`.
  - Verifies no payments, settled installments, or return orders exist before safely reversing stock, lot allocations, and vendor balance.
- **Payment Status Update**: `POST /purchases/orders/<pk>/update-payment-status/`
  - Permission: `@require_permission('purchases:orders/manage_payment_status')` and `can_user_access_object(request.user, order, 'edit')`.
  - Updates operational status (`credit`, `partial`, `paid`, `returned`) with `ApprovalAuditLog` and `SecurityAuditLog` entries.
- **Payment Request Redirection**: `GET /purchases/orders/payment-requests/create/`
  - Automatically redirects (HTTP 302) with query parameters (`?supplier=...&purchase_order=...`) to `/treasury/payments/create/`.

### 4.2 Sales Order Client & Warehouse Scoping, Payment Status Update, and Deletion
- **Create & Edit Views**: `POST /sales/orders/create/` and `POST /sales/orders/<pk>/edit/`
  - Enforces object-level access check on submitted `customer` (`can_user_access_object(request.user, customer, 'view')`). Prevents selecting clients outside the representative's assigned Brick or manager's assigned Main Area.
  - Enforces object-level access check on submitted `warehouse` (`can_user_access_object(request.user, warehouse, 'operate')`). Prevents unauthorized warehouse submissions.
  - Edit view blocks changes if collections exist (`order.collections.exists()`).
- **Delete View**: `POST /sales/orders/<pk>/delete/`
  - Permission: `@require_permission('sales:orders/delete')` and `can_user_access_object(request.user, order, 'delete')`.
  - Strictly blocks deletion if collections exist. Atomically restores deducted inventory, reverses customer account debt, deletes memo and transaction, and logs `SALES_ORDER_DELETED`.
- **Payment Status Update**: `POST /sales/orders/<int:pk>/update-payment-status/`
  - **Permission**: `@require_permission('sales:orders/manage_payment_status')`
  - **Scope**: validates `can_user_access_object(request.user, order, 'edit')`
  - **Payload (`application/x-www-form-urlencoded` or JSON)**:
    - `payment_status` (string, required): `credit` (آجل), `partial` (جزئي), `paid` (مدفوع بالكامل), `returned` (مرتجع)
    - `notes` (string, optional): Update note
  - **Response Format**:
    ```json
    {
      "success": true,
      "payment_status": "paid",
      "payment_status_display": "مدفوع بالكامل",
      "message": "تم تحديث حالة السداد بنجاح"
    }
    ```

### 4.3 Sales Return Order APIs
- **Delete View**: `POST /sales/returns/<pk>/delete/`
  - Permission: `@require_permission('sales:returns/delete')` and `can_user_access_object(request.user, return_order, 'delete')`.
  - Atomically deducts restocked inventory, reverts customer credit, deletes memo and transaction, and logs `SALES_RETURN_DELETED`.
- **Eligible Delivered Orders API**: `GET /sales/api/eligible-orders/`
  - **Permission**: `@login_required`, scoped via `get_scoped_queryset(..., 'salesorder')`.
  - **Query Parameters**:
    - `customer_id` (integer, optional): Filter orders by customer ID.
    - `q` (string, optional): Search query (order number, customer name).
  - **Response Format**:
    ```json
    {
      "results": [
        {
          "id": 142,
          "order_number": "SO-501",
          "customer_name": "صيدلية السلامة",
          "customer_id": 88,
          "warehouse_id": 3,
          "warehouse_name": "مخزن القاهرة الرئيسي",
          "order_date": "2026-11-10",
          "grand_total": "4800.00"
        }
      ]
    }
    ```
- **Order Details for Return API**:
  - **URLs**: `GET /sales/api/orders/<int:order_id>/return-details/` and `GET /sales/api/order-details/<int:order_id>/`
  - **Permission**: `@login_required`, validates object-level access (`can_user_access_object(..., 'view')`).
  - **Response Format**:
    ```json
    {
      "order_id": 142,
      "order_number": "SO-501",
      "customer_id": 88,
      "customer_name": "صيدلية السلامة",
      "warehouse_id": 3,
      "warehouse_name": "مخزن القاهرة الرئيسي",
      "items": [
        {
          "product_id": 10,
          "product_name": "بانادول إكسترا",
          "product_code": "PAN-EXT-500",
          "original_quantity": 50.0,
          "returned_quantity": 10.0,
          "remaining_returnable": 40.0,
          "unit_price": 45.0,
          "discount": 0.0,
          "tax_rate": 14.0
        }
      ]
    }
    ```

### 4.4 Purchase Return Order APIs
- **Delete View**: `POST /purchases/returns/<pk>/delete/`
  - Permission: `@require_permission('purchases:returns/delete')` and `can_user_access_object(request.user, return_order, 'delete')`.
  - Atomically restores deducted stock and lot quantities to the warehouse, restores vendor accounts payable balance, deletes debit transaction and memo, and logs `PURCHASE_RETURN_DELETED`.
- **Order Details for Return API**: `GET /purchases/api/orders/<int:order_id>/return-details/`
  - **Permission**: `@login_required`, validates object-level access (`can_user_access_object(..., 'view')`).
  - **Response Format**:
    ```json
    {
      "order_id": 42,
      "order_number": "PO-202611-001",
      "supplier_id": 5,
      "supplier_name": "شركة الأدوية المتحدة",
      "warehouse_id": 2,
      "warehouse_name": "المخزن المركزي",
      "items": [
        {
          "product_id": 10,
          "product_name": "بانادول إكسترا",
          "product_code": "PAN-EXT-500",
          "original_quantity": 100.0,
          "returned_quantity": 20.0,
          "remaining_returnable": 80.0,
          "unit_cost": 25.5
        }
      ]
    }
    ```

### 4.5 Inventory Stock API
- **Warehouse Available Stock API**: `GET /inventory/api/warehouse-stock/?warehouse_id=<id>`
  - **URL**: `/inventory/api/warehouse-stock/`
  - **Permission**: `@login_required`, validates object-level access (`can_user_access_object(request.user, warehouse, 'view')`).
  - **Query Parameters**:
    - `warehouse_id` (integer, required): ID of the warehouse.
  - **Response Format**:
    ```json
    {
      "warehouse_id": 2,
      "warehouse_name": "المخزن المركزي",
      "count": 15,
      "products": {
        "10": {
          "product_name": "بانادول إكسترا",
          "sku_code": "PAN-EXT-500",
          "qty_available": 120.0,
          "qty_on_hand": 120.0,
          "qty_reserved": 0.0
        }
      }
    }
    ```

### 4.6 Warehouse CRUD Endpoints
- **Warehouse Create**: `GET|POST /inventory/warehouses/add/`
  - **Permission**: `inventory:warehouses/manage`
  - **POST Payload**: `name`, `code`, `area`, `address`, `assigned_user`, `manager`, `latitude`, `longitude`, `is_main`, `is_rep_warehouse`, `is_active`
- **Warehouse Edit**: `GET|POST /inventory/warehouses/<pk>/edit/`
  - **Permission**: `inventory:warehouses/manage` + `can_user_access_object(request.user, warehouse, 'edit')`
- **Warehouse Delete**: `POST /inventory/warehouses/<pk>/delete/`
  - **Permission**: `inventory:warehouses/delete` (or `manage`) + `can_user_access_object(request.user, warehouse, 'delete')`
  - Validates stock on hand = 0, no memos, transfers, or orders.

### 4.7 Vault CRUD Endpoints
- **Vault Create**: `GET|POST /treasury/vaults/add/`
  - **Permission**: `treasury:vaults/manage`
  - **POST Payload**: `name`, `vault_type`, `area`, `assigned_user`, `initial_balance`, `is_rep_vault`, `is_active`
  - Posts initial opening balance transaction atomically if `initial_balance > 0`.
- **Vault Edit**: `GET|POST /treasury/vaults/<pk>/edit/`
  - **Permission**: `treasury:vaults/manage` + `can_user_access_object(request.user, vault, 'edit')`
- **Vault Delete**: `POST /treasury/vaults/<pk>/delete/`
  - **Permission**: `treasury:vaults/delete` (or `manage`) + `can_user_access_object(request.user, vault, 'delete')`
  - Validates current balance = 0, no transactions, vendor payments, or collections.

---

## 5. Settings & Operational Endpoints

### 4.1 Geofence Settings API (`geofence_settings_api`)
- **URL**: `/settings/api/geofence/`
- **Method**: `GET` / `POST`
- **Permission**: `@require_super_admin`
- **Response Format (GET)**:
  ```json
  {
    "tolerance": 300,
    "verify_visits": true,
    "verify_unplanned_visit_distance": true,
    "verify_end_visit_distance": true,
    "allow_template_distance_override": true
  }
  ```

### 4.2 Purchase Order Status AJAX (`purchase_order_update_status_ajax`)
- **URL**: `/purchases/orders/update-status/`
- **Method**: `POST`
- **Permission**: `@require_permission('purchases:orders/approve')`
- **Payload**:
  - `order_id` (integer, required)
  - `status` (string, required)
- **Response Format**:
  ```json
  {
    "success": true,
    "new_status": "approved",
    "message": "تم اعتماد طلب الشراء بنجاح"
  }
  ```

---

## 6. Performance & Reports Export Endpoints

All performance and reporting views provide standard OpenXML Excel downloads (`.xlsx`) and formatted print views, respecting the requester's data scope:

- **Performance Analytical Export**: `GET /performance/analysis/export/?period=...&area=...`
  - Permission: `performance:analysis/export`
- **Performance Daily Activity Export**: `GET /performance/daily/export/?date=YYYY-MM-DD`
  - Permission: `performance:daily/export`
- **Performance Detailed Matrix Export**: `GET /performance/detailed/export/?period=...&area=...`
  - Permission: `performance:detailed/export`
- **AR Aging Export & Print**: `GET /reports/ar-aging/export/` & `GET /reports/ar-aging/print/`
  - Permission: `reports:financial/export`
- **Trial Balance Export & Print**: `GET /reports/trial-balance/export/` & `GET /reports/trial-balance/print/`
  - Permission: `reports:financial/export`
- **Target Achievement Export**: `GET /reports/target-achievement/export/`
  - Permission: `reports:financial/export`
- **Net Sales & Profitability Export**: `GET /reports/net-sales/export/`
  - Permission: `reports:sales/export`
- **Customer 360 Export**: `GET /reports/customer-360/export/`
  - Permission: `reports:sales/export`
- **Promotions Export**: `GET /reports/promotions/export/`
  - Permission: `reports:sales/export`
- **Item Sales by Customer Export**: `GET /reports/item-sales-by-customer/export/`
  - Permission: `reports:sales/export`
- **Order Deliveries Export & Print**: `GET /reports/order-deliveries/export/` & `GET /reports/order-deliveries/print/`
  - Permission: `reports:inventory/export`
- **Delivery Stock Availability Export**: `GET /reports/delivery-stock/export/`
  - Permission: `reports:inventory/export`
- **Item Purchases Export**: `GET /reports/item-purchases/export/`
  - Permission: `reports:inventory/export`
- **Agreements ROI Export**: `GET /reports/agreements-roi/export/`
  - Permission: `reports:activities/export`
- **Calls & Telesales Export**: `GET /reports/calls/export/`
  - Permission: `reports:activities/export`
- **Medical Samples Export**: `GET /reports/samples/export/`
  - Permission: `reports:activities/export`

---

## 7. Smart Search Combobox Endpoints (`Sales`, `Purchases`, `Treasury`)

All smart-search endpoints enforce `@require_permission([...])`, use `ScopeResolutionService.get_scoped_choices(...)`, normalize Arabic queries via `master_data.search_utils.filter_by_arabic_search`, clamp `limit` (`1..50`, default `30`), and return `{"results": [...], "count": <int>}`. Background requests include `X-Skip-Global-Loader: 1` (and matching paths in `templates/layouts/base.html`).

### 7.1 Sales Smart Search & Customer Accounting Endpoints
- `GET /sales/api/search/customers/?q=<query>&scope_model=<optional>&limit=30` (`sales_customers_search_api`)
  - **Permissions**: `sales:orders/list`, `sales:orders/create`, `sales:orders/edit`, `sales:collections/list`, `sales:collections/create`, `sales:returns/list`, `sales:customers/transactions`, `sales:customers/accounting`
  - **Scope**: Active (`status != 'inactive'`, `is_customer=True`) scoped via `ScopeResolutionService.get_scoped_choices(user, 'customers', 'sales')`. Passing `scope_model=customeraccount` scopes results to customers present in `get_scoped_queryset(CustomerAccount.objects.all(), user, 'customeraccount')`.
  - **Fields searched**: Normalized `name`, `area__name`, `brick__name` + raw `code`, `mobile`, `serial_num` (plus exact numeric `serial_num`).
  - **Item keys**: `id`, `text`, `name`, `serial_num`, `code`, `mobile`, `area`, `brick`, `subtext`
- `GET /sales/api/search/orders/?customer=<id>&q=<query>&unpaid_only=1&limit=50` (`sales_orders_search_api`)
  - **Permissions**: `sales:collections/create`, `sales:collections/list`, `sales:orders/list`, `sales:returns/create`
  - **Scope**: Uses `SalesOrder.with_payment_totals(...)` (SQL-annotated paid totals eliminating N+1 queries) and `get_scoped_queryset(..., user, 'salesorder')`; filters out cancelled/rejected orders and optionally unpaid (`unpaid_only=1`) and by `customer`.
  - **Item keys**: `id`, `order_number`, `customer_id`, `grand_total`, `outstanding_balance`, `due_date`, `text`, `subtext`
- `GET /sales/api/search/warehouses/?q=<query>&limit=30` (`sales_warehouses_search_api`)
  - **Permissions**: `sales:orders/list`, `sales:orders/create`, `sales:orders/edit`, `sales:returns/create`
  - **Item keys**: `id`, `text`, `name`, `code`, `subtext`
- `GET /sales/api/search/vaults/?q=<query>&limit=30` (`sales_vaults_search_api`)
  - **Permissions**: `sales:collections/list`, `sales:collections/create`
  - **Item keys**: `id`, `text`, `name`, `serial_num`, `balance`, `subtext`
- **Customer Accounts & Transactions Exports**:
  - `GET /sales/customers/accounts/export/?search=...&customer=...&area=...` (`accounting_customers_export`) — Permission: `sales:customers/accounting_export`
  - `GET /sales/customer-transactions/export/?search=...&customer_id=...&type=...` (`customer_transactions_export`) — Permission: `sales:customers/transactions_export`

### 7.2 Purchases & Treasury Smart Search Endpoints
- `GET /purchases/api/search/suppliers/?q=<query>&limit=30` (`purchases_suppliers_search_api`)
  - **Permissions**: `purchases:orders/*`, `purchases:returns/*`, `treasury:payments/*`, `treasury:payment_requests/*`, `treasury:vendors/*`
  - **Scope**: Active (`status != 'inactive'`, `is_supplier=True`) scoped via `ScopeResolutionService.get_scoped_choices(user, 'suppliers', 'purchases')`, including corporate company-area suppliers (`is_supplier=True, area__is_company_area=True`) while keeping territorial suppliers isolated by area/brick.
- `GET /purchases/api/search/warehouses/?q=<query>&limit=30` (`purchases_warehouses_search_api`)
  - **Permissions**: `purchases:orders/list`, `purchases:orders/create`, `purchases:orders/edit`, `purchases:returns/create`
- `GET /purchases/api/search/vaults/?q=<query>&limit=30` (`purchases_vaults_search_api`)
  - **Permissions**: `treasury:payments/*`, `treasury:payment_requests/*`, `treasury:vaults/view`, `treasury:vaults/transfer`, `treasury:transactions/list`, `treasury:transactions/create`

---

## 8. Unified List Smart Search & New Export Endpoints

- **List Search Suggestions**: `GET /api/list-suggestions/?module=<module>&q=<query>&limit=10` (`list_suggestions_api`)
  - **Modules**: `sales_orders`, `sales_returns`, `collections`, `customers`, `purchase_orders`, `purchase_returns`, `products`, `inventory_stocks`, `inventory_memos`, `product_transfers`, `warehouses`, `vaults`, `visits`, `agreements`, `users`, `vendor_payments`, `vendor_payment_requests`, `vendor_transactions`, `categories`, `roles`, `audit_logs`.
  - **Security**: Enforces module read permission (`403` on unauthorized), `get_scoped_queryset`, and Arabic-normalized partial matching.
- **Additional Scoped Excel Exports**:
  - `GET /accounts/users/export/` (`users_export`, `users:users/export`)
  - `GET /accounts/audit-logs/export/` (`audit_logs_export`, `settings:auditLogs/export`)
  - `GET /catalog/categories/export/` (`categories_export`, `catalog:categories/export`)
  - `GET /inventory/warehouses/export/` (`warehouses_export`, `inventory:warehouses/export`)
  - `GET /inventory/memos/export/` (`inventory_memos_export`, `inventory:memos/export`)
  - `GET /inventory/transfers/export/` (`product_transfers_export`, `inventory:transfers/export`)
  - `GET /treasury/vaults/export/` (`vaults_export`, `treasury:vaults/export`)
  - `GET /treasury/vault-transactions/export/` (`vault_transactions_export`, `treasury:transactions/export`)
  - `GET /treasury/vendors/export/` (`accounting_vendors_export`, `treasury:vendors/accounting_export`)
  - `GET /treasury/vendor-transactions/export/` (`vendor_transactions_export`, `treasury:vendors/transactions_export`)




## Attachments, Storage & PDF Endpoints

- `GET/POST /settings/storage/` — SuperAdmin Cloudflare R2 pricing calculator & cleanup tools (`r2_storage_settings`).
- `POST /attachments/<model_key>/<int:object_id>/upload/` — Upload images/PDFs onto a scoped ERP record (`erp_attachment_upload`).
- `GET /attachments/<model_key>/<int:object_id>/list/` — JSON attachment list for modal display (`erp_attachment_list_json`).
- `GET /attachments/<int:pk>/view/` & `/attachments/<int:pk>/download/` — Protected inline/attachment file delivery (`erp_attachment_view`, `erp_attachment_download`).
- `POST /attachments/<int:pk>/delete/` — Reference-counted attachment deletion (`erp_attachment_delete`).
- `GET /sales/<int:pk>/pdf/` — Customizable Sales Order PDF (`sales_order_pdf`).
- `GET /sales/returns/<int:pk>/pdf/` — Customizable Sales Return PDF (`sales_return_order_pdf`).
- `GET /sales/customers/<int:pk>/statement/pdf/` — Customer Account Statement PDF (`customer_statement_pdf`).
- `GET /purchases/<int:pk>/pdf/` — Customizable Purchase Order PDF (`purchase_order_pdf`).
- `GET /purchases/returns/<int:pk>/pdf/` — Customizable Purchase Return PDF (`purchase_return_order_pdf`).
- `GET /purchases/vendors/<int:pk>/statement/pdf/` — Supplier Account Statement PDF (`vendor_statement_pdf`).
