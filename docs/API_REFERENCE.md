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

### 3.2 Scheduled Visit Time Quick Action (`set_visit_time_api`)
- **URL**: `/activities/visits/<pk>/set-time/`
- **Method**: `POST`
- **Permission**: `@require_permission('activities:visits/edit')`
- **Payload (`application/x-www-form-urlencoded` or JSON)**:
  - `time` (string `HH:MM`, required): New 24-hour time.
- **Response Format**:
  ```json
  {
    "success": true,
    "time": "14:30",
    "formatted_time": "02:30 م"
  }
  ```

### 3.3 Planned Visits Selection & Bulk Creation
- `GET /planned-visits/?action=select_all_ids` (with active filters): returns `{ "success": true, "total_count": N, "contacts": [{"id": 1, "account_type": "..."}] }` across all filtered scoped results.
- `GET /planned-visits/?action=load_contacts&show_all=1`: returns all matching scoped contacts in one batch for "عرض جميع العملاء المؤهلين".
- `POST /planned-visits/bulk-add/`: atomically creates `PlannedVisitDay`, `PlannedVisitItem`, and linked `Visit(status='planned', is_planned=True)` records, returning `created_visit_ids`.

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
- **Re-approval Behavior**:
  - Setting answers triggers immediate re-approval: sets `approval_status = 'pending'`, `waiting_for_reapproval = True`, and resets `approved_by` and `approved_at` to `None`.
  - Records diff in `ApprovalAuditLog(action='answers_updated', approval_required=True, changes={...})` and `SecurityAuditLog(action='VISIT_ANSWERS_UPDATED')`.
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

### 4.2 Sales Order Client Scoping
- **Create & Edit Views**: `POST /sales/orders/create/` and `POST /sales/orders/<pk>/edit/`
  - Enforces object-level access check on submitted `customer` (`can_user_access_object(request.user, customer, 'view')`). Prevent selecting clients outside the representative's assigned Brick or manager's assigned Main Area.

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
