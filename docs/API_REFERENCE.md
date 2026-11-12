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

---

## 4. Settings & Operational Endpoints

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
