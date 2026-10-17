# Strict Reference-Parity Audit: Visit Registration, Unified Workflows, and Location Verification

## 1. Executive Summary
This document presents the reverse-engineering audit comparing the live reference ERP (`https://weapharma.bricks-rep.com`) with the local Django ERP (`WEA Pharma ERP`).

Target systems audited:
1. **Visit Registration (“تسجيل الزيارة”) Customer Selection**
2. **Unified Visit-Registration Workflow across All Entry Points**
3. **Location Verification Subsystem & Configuration (Places/Settings, Contacts, Users, and Visits)**

---

## 2. Live Reference ERP Investigation Evidence

### 2.1 Customer Selector Mechanism & API
- **Live Endpoint**: `POST /api/v1/visits/contacts/list`
- **Request Payload**: `{"pagination":{}, "limit": 100, "offset": 0, "q": "", "preloads": {"contact": true}}`
- **Scoping & Business Rules**:
  - Filter: `contact_business_relation = ['customer']`
  - Filter: `contact_inactive = false`
  - Representative Scoping: For medical reps, contacts are scoped to assigned contacts (`assigned_team=user` or `created_by=user` or user area). Managers and administrators can access all active customers across the tenant.
- **UI & UX Interaction in Reference (`app-visit-create-customer-selection`)**:
  - Interactive searchable combobox (`mat-select` / typeahead) with search placeholder `بحث...`.
  - Item formatting: `[Code] Name` (e.g., `[E2425] صيدلية د. جمال المرج`, `[#16436] رفعت فتحى رمضان`).
  - Upon selecting a customer, a rich customer dossier badge appears containing:
    1. Avatar initials (e.g., `صج`, `رف`)
    2. Code & Name: `[E2425] صيدلية د. جمال المرج`
    3. Navigation / directions icon (`directions`)
    4. Business tags: `شخص` / `مؤسسة`, `عميل`
    5. Customer category (`تصنيف العميل`: A, B, C)
    6. Specialty (`التخصص`: Pharmacy, Pediatric, etc.)
    7. Preview button (`معاينة`) opening contact overview
    8. Address and geographic territory
    9. Visit template selector (`قالب الزيارة`: `اختر قالب الزيارة`)
    10. Submit button (`تسجيل الزيارة`), disabled until a visit template is chosen.

### 2.2 Unified Workflow & Entry Points
Every entry point in the reference routes to this single canonical registration process:
1. **Floating Action Button (FAB Action 1)**: `تسجيل زيارة خارج الخطة` opens the canonical modal dialog (`app-visit-create-customer-selection`).
2. **Visits List (`/visits`)**: Create button triggers the same canonical registration modal/flow.
3. **Planned Visits (`/planned-visits`)**: Executing or starting a scheduled visit item passes `contact_id` and `template_id` into the canonical workflow with customer and template prefilled.
4. **Contact Details (`/contacts/<id>`)**: Contact dossier action initiates the canonical registration workflow with that specific customer preselected.

### 2.3 Location Verification & Settings Architecture
- **Location Settings Page**: `https://weapharma.bricks-rep.com/settings/location` (Navbar label: `gps_fixed اعدادات الموقع`).
- **Configuration API**: `GET /api/v1/geofence/settings`
- **Observed Reference Values**:
  ```json
  {
    "settings": {
      "tolerance": 300,
      "auto_start_location_tracking_service": true,
      "auto_set_customer_location_in_visit": true,
      "max_verified_accuracy": 50,
      "max_verified_warn_accuracy": 100
    }
  }
  ```
- **Workflow Verification Controls**:
  - `الزيارات`: Location Verification enabled (`التحقق من الموقع`).
  - Sales orders, purchase orders, returns, and collections: Disabled (`تعطيل التحقق`).
- **Superuser-Only Permissions**:
  - Permission tags: `"customers:customers/bypassLocation"`, `"geofence:settings/write"`, `"geofence:verifySettings/write"`, `"global:locationSettings/setTolerance"`.
  - Only `SuperAdmin` / `is_superuser` accounts can access `/settings/location` or modify `bypass_location_verification`. Ordinary representatives and staff are strictly barred on both backend and UI.
- **Visit Location Verification Behavior (Observed on live visit #154829)**:
  - Compares visit GPS check-in against saved customer coordinates using Haversine distance.
  - Live inspection captured real badge:
    - Distance: `المسافة 631.90 m`
    - Completion status: `حالة الاستكمال: تم تجاهل التحقق بالقوة` (Forced bypass)
    - Location status: `حالة الموقع: بعيد جدا عن الموقع المحدد` (Out of tolerance radius)
    - Icon: `gpp_maybe`
  - When within tolerance (<= 300m): status is `ضمن النطاق المحدد` with icon `gpp_good`.
  - When customer has no saved location and `auto_set_customer_location_in_visit` is true: visit automatically sets customer GPS coordinates on first check-in and marks visit as verified.

---

## 3. Local Behavior Before Repair & Root Causes

### 3.1 Defect 1: “تسجيل الزيارة” Customer Selector Empty / Broken
- **Root Cause**:
  1. `templates/layouts/base.html` attempted to fetch `/contacts/api/search/?q=`, which did not exist (returned 404). As a result, `loadUnplannedContacts()` caught an error and rendered `"لم يتم العثور على عملاء"`.
  2. In `activities/views.py`, `visit_create` used standard `VisitForm` with an unfiltered HTML `<select>` without role-based queryset scoping, search capability, or autocomplete.
  3. No dedicated API existed to handle customer search, code formatting, and location status metadata.

### 3.2 Defect 2: Fragmented Visit Registration Workflows
- **Root Cause**:
  1. Planned visits execution (`planned_visit_item_execute`) bypassed the visit registration form entirely, creating visits blindly via backend shortcut.
  2. Contact detail view had no "تسجيل زيارة" action button to launch visit creation with prefilled customer context.
  3. FAB Quick-Add modal and `/visits/create/` were disconnected, using different HTML templates and incomplete forms.

### 3.3 Defect 3: Missing Location Verification Subsystem & Settings
- **Root Cause**:
  1. No `LocationSettings` model existed in `master_data/models.py`.
  2. No `/settings/location/` view, form, or route existed.
  3. `User` model in `accounts/models.py` lacked `bypass_location_verification` attribute and superuser-only access controls.
  4. `Visit` model in `activities/models.py` had basic fields (`latitude`, `longitude`, `location_verified`) but lacked distance computation, location status, verification status, and device accuracy fields.
  5. `visit_detail.html` had no location verification badge, distance display, or coordinates comparison.

---

## 4. Affected Models, Views, APIs, and Templates

| Component | File | Required Changes |
|-----------|------|------------------|
| Location Settings Model | `master_data/models.py` | Add `LocationSettings` model with tolerance (300m), accuracy thresholds, auto-save toggle, and workflow verification flags. |
| User Permissions | `accounts/models.py`, `accounts/views.py` | Add `bypass_location_verification` field to `User`. Enforce superuser-only restrictions. |
| Customer Location Properties | `contacts/models.py` | Add `latitude`, `longitude`, and `set_location()` helpers to `Contact` synced with `ContactAddress`. |
| Customer Search API | `contacts/views.py`, `contacts/urls.py` | Implement role-scoped `/api/customers/search/` with name, code, area, and location metadata. |
| Visit Model & Geolocation | `activities/models.py` | Add `distance`, `location_status`, `verification_status`, `device_accuracy`, and Haversine verification logic. |
| Canonical Registration View | `activities/views.py`, `activities/forms.py` | Refactor `visit_create` as the single canonical registration endpoint accepting `contact_id`, `template_id`, `planned_item_id`. |
| Canonical Registration Template | `templates/activities/visit_form.html` | Build unified, reactive visit registration UI matching reference (searchable customer selector, rich customer card, template dropdown, GPS capture). |
| Location Settings Template & View | `master_data/views.py`, `templates/settings/location_settings.html` | Build superuser-restricted location settings interface matching `/settings/location`. |
| Visit Detail Location Card | `templates/activities/visit_detail.html` | Render location verification card matching reference (`gpp_good`/`gpp_maybe`, distance, completion status, location status). |
| Contact Detail Visit Action | `templates/contacts/contact_detail.html` | Add "تسجيل زيارة" action button prefilling customer context into canonical registration. |
| Planned Visits Execution | `activities/views.py`, `templates/activities/planned_visits_list.html` | Route "بدء الزيارة" into canonical registration with prefilled contact and template. |
| Global FAB Quick-Add | `templates/layouts/base.html` | Wire Action 1 to the canonical visit registration workflow with working customer search. |
