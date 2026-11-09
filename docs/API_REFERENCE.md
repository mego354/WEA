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
  - `governorate_id` (integer, required): ID of the parent governorate.
- **Response Format**:
  ```json
  [
    {
      "id": 12,
      "name": "حي الدقي",
      "code": "DOKKI-01"
    },
    {
      "id": 15,
      "name": "حي المهندسين",
      "code": "MOHAND-01"
    }
  ]
  ```

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

