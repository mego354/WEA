# API contracts (as implemented)

There is **no** Django REST Framework. “APIs” are Django views returning `JsonResponse` (and a few POST handlers that also accept HTML).

Common envelopes:

**401**
```json
{"error": "Unauthenticated", "detail": "يجب تسجيل الدخول أولاً للوصول إلى هذا المورد."}
```

**403**
```json
{"error": "PermissionDenied", "detail": "...", "perm_codename": "sales:orders/create"}
```

or SuperAdmin-only `{"error": "Forbidden", "detail": "..."}`.

Session cookie + CSRF for POST. `require_permission` treats the request as API if `X-Requested-With: XMLHttpRequest`, path starts with `/api/`, or `Accept` contains `application/json`.

---

### `GET|POST /contacts/api/search/`  
### `GET|POST /api/customers/search/`  
### `GET|POST /api/v1/visits/contacts/list`

**Name:** `customers_search_api` (and aliases).  
**Auth:** logged in + any of contacts list/view, visits create/list, planned, sales create/list, agreements create/list.  
**Purpose:** customer picker for visits/sales.  
**Query/body:** `q`, `limit` (default 100), optional `id`.  
**Scope:** Scoped via `get_visit_eligible_contacts_queryset(request.user)` — Superadmin sees all active customers, Manager sees customers in their assigned Main Area (governorate) and child bricks, Representative sees customers in their assigned Brick(s) (`Area.parent is not None`).  
**Success:** JSON list of contacts (`results`: id, name, code, area, latitude, longitude, …) as built in `contacts.views.customers_search_api`.  
**Audit:** read-only, no audit row.

---

### `GET /contacts/api/subareas/?area_id=`

**Name:** `contact_subareas_api`.  
**Auth:** login required.  
**Success:** `{"subareas": [{"id": 1, "name": "..."}, ...]}`. Empty list if `area_id` missing.

---

### `GET /api/v1/geofence/settings` (also under `/home/` prefix)

**Name:** `geofence_settings_api`.  
**Auth:** `settings:location/manage` **or** visit create/edit/view.  
**Success:**
```json
{"settings": {
  "tolerance": 300,
  "allow_template_distance_override": true,
  "verify_unplanned_visit_distance": true,
  "verify_end_visit_distance": true,
  "bypass_reason_mandatory": true,
  "distance_bypass_requires_approval": true,
  "auto_start_location_tracking_service": true,
  "auto_set_customer_location_in_visit": true,
  "max_verified_accuracy": 50,
  "max_verified_warn_accuracy": 100,
  "verify_visits": true
}}
```

---

### `GET /api/geocoding/search/?q=`  
### `GET /api/geocoding/reverse/?lat=&lon=`

**Auth:** `@login_required`.  
**Purpose:** proxy to Google Geocoding (if `GOOGLE_MAPS_API_KEY`) else Nominatim.  
**Success search:** `{"results": [{"lat": 0.0, "lon": 0.0, "display_name": "..."}]}`.  
**Limitation:** failures return empty `results` (or `[]`).

---

### `GET /activities/api/templates/` (and `/api/templates/` via empty include)

**Name:** `visit_templates_api`.  
**Auth:** visit create/list, planned list, or template manage.  
**Query:** `contact_id` (single), `contact_ids` (comma-separated IDs for bulk group common template calculation), `account_type`.  
**Success:** array of templates in both `templates` and `results` keys with questions and distance metadata (`has_special_location_settings`, `special_tolerance`, `effective_tolerance`), after `VisitTemplate.is_user_eligible` / `is_contact_eligible`. For bulk requests (`contact_ids`), calculates the common eligible template intersection across all specified contacts.  
**Do not** return templates the user is not eligible for.

---

### `GET /planned-visits/?action=load_contacts&offset=&limit=`

**Name:** `planned_visits_list` (AJAX Incremental Contact Loader).  
**Auth:** `@require_permission('activities:planned/list')`.  
**Purpose:** Incremental 10-batch loading for bulk planning drawer without duplicate clients.  
**Query:** `action=load_contacts`, `offset` (default 0), `limit` (default 10, max 50), and filter parameters (`contact_search`, `account_type`, `main_area`, `area`, `customer_category`).  
**Success:**
```json
{
  "success": true,
  "total_count": 45,
  "offset": 10,
  "limit": 10,
  "has_more": true,
  "contacts": [
    {
      "id": 101,
      "name": "صيدلية الإسكندرية الكبرى",
      "code": "ALX001",
      "account_type": "Pharmacy",
      "customer_category": "A",
      "specialty": "Community Pharmacy",
      "area_name": "الرمل",
      "parent_area_name": "الإسكندرية"
    }
  ]
}
```

---

### `GET /visits/api/check-duplicate/?contact_id=&date=`

**Name:** `visit_check_duplicate_api`.  
**Auth:** `@require_permission('activities:visits/create', 'activities:visits/edit', 'activities:visits/list')`.  
**Purpose:** Pre-checks whether an active visit already exists for the given `contact_id` and `date` (for duplicate confirmation prompt).  
**Success:**
```json
{
  "has_duplicate": true,
  "count": 1,
  "visits": [{"id": 12, "status_ar": "منتهية", "is_planned": false, "owner_name": "..."}]
}
```

---

### `POST /planned-visits/bulk-add/`

**Name:** `planned_visits_bulk_add`.  
**Auth:** `@require_permission('activities:planned/manage')`.  
**Purpose:** Bulk schedule planned visits for multiple selected customers on a single date while enforcing geographical hierarchy (`get_visit_eligible_contacts_queryset`), mandatory template selection (`template_id` required and eligible), date validation (`date >= today`, past dates strictly rejected), and skipping duplicate customers already scheduled on that date.  
**Success (AJAX):**
```json
{
  "success": true,
  "created_count": 5,
  "skipped_duplicates_count": 1,
  "message": "..."
}
```
**Audit:** Writes `BULK_PLANNED_VISITS_CREATED` via `AuditLogService.log`.

---

### `GET /settings/audit-logs/<pk>/detail/`

**Name:** `audit_log_detail`.  
**Auth:** audit view permission.  
**Success:** JSON of one `SecurityAuditLog` (previous/new values for the modal).  
**Side effects:** none.

---

### `POST /purchases/<pk>/status/update/`

**Name:** `purchase_order_update_status_ajax`.  
**Auth:** purchase edit/approve per view.  
**Purpose:** AJAX status update; must remain consistent with `PurchaseOrderService` transitions and audit.

Other HTML-only POST endpoints (visit action, sales action, transfer action, vault reverse) are not public APIs; they return redirects or HTML. If you add JSON for them, document request/response here and update the caller together.

## Pagination / filtering

List **pages** use querystring `page`, `q`/`search`, status, area filters and `master_data.pagination_utils.paginate_queryset`. JSON pickers use `limit`, not page tokens.

## Inconsistencies (do not silently “normalize”)

- Three URLs share `customers_search_api`.
- Geofence path has **no trailing slash** (`api/v1/geofence/settings`) — Django `APPEND_SLASH` may still redirect GET.
- Some APIs use `{error, detail}`, others `{subareas}` / `{results}` / `{settings}` with no wrapper.
