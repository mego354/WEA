# Visit Registration, Unified Workflows, and Location Verification Test Plan

## 1. Overview
This test plan defines the test cases, expected results, actual results, and verification status for the repair of:
1. Customer selection in visit registration.
2. Canonical visit registration workflow across all entry points.
3. Location verification settings, permissions, and visit geolocation checks.
4. Responsive layouts (320px to 1920px).

---

## 2. Test Cases and Verification Matrix

| Test ID | Area | Test Case Description | Expected Result | Actual Result | Status |
|---------|------|------------------------|-----------------|---------------|--------|
| TC-VR-01 | Customer Selector | Medical Rep requests customer search API (`/contacts/api/search/?q=`) | Returns only active customers assigned to the rep or in rep's area with code, category, specialty, address, and location. | Scoped to assigned team / creator; returns serialized customer dict with coordinates, address, and code tag. | **VERIFIED** |
| TC-VR-02 | Customer Selector | Manager/Admin requests customer search API | Returns all active customers across all areas. | Superuser / manager gets full customer catalog; inactive customers excluded. | **VERIFIED** |
| TC-VR-03 | Customer Selector | Search by customer code (`ALX001`, `DOC...`, `#...`) and name in Arabic | Autocomplete returns filtered matches instantly. Empty state handles zero results gracefully. | Debounced AJAX typeahead filters by Arabic name, code, serial, mobile, and area; empty state shows user-friendly message. | **VERIFIED** |
| TC-VR-04 | Customer Selector | Customer is selected in visit registration form | Shows rich customer dossier card (Avatar initials, Code, Name, tags, category, specialty, address, saved GPS status). | Renders initials circle avatar, `[Code] Name`, category badge, specialty, area, and GPS status pill. | **VERIFIED** |
| TC-VR-05 | Template Selection | Customer is selected; visit template dropdown is populated | Template selection enables "تسجيل الزيارة" button. Matches reference templates (`Single visit (DR)`, etc.). | Dropdown renders active templates; binds template id to visit creation. | **VERIFIED** |
| TC-UW-01 | Unified Workflow | FAB Quick-Add Action 1 ("تسجيل زيارة خارج الخطة") is clicked | Opens canonical visit registration modal / page with full customer search and template selection. | Modal lists customers from search API and routes directly to `/visits/create/?contact_id=...`. | **VERIFIED** |
| TC-UW-02 | Unified Workflow | Visits list "+ تسجيل زيارة" button is clicked | Opens canonical visit registration page/form. | Routes to `/visits/create/` with full typeahead customer search and GPS capture. | **VERIFIED** |
| TC-UW-03 | Unified Workflow | Planned visit item "بدء الزيارة" is clicked | Opens canonical registration form with customer and template prefilled; submission marks `PlannedVisitItem` as executed. | Redirects to `/visits/create/?contact_id=...&planned_item_id=...`; submitting creates visit and marks `item.is_executed=True`. | **VERIFIED** |
| TC-UW-04 | Unified Workflow | Contact detail "تسجيل زيارة" action is clicked | Opens canonical registration form with customer prefilled. | Button on dossier links to `/visits/create/?contact_id=...` with customer card pre-rendered. | **VERIFIED** |
| TC-UW-05 | Unified Workflow | Duplicate submission prevention | Disables submit button on click and prevents duplicate visit records. | Button disables with spinner text; backend rejects duplicate submission within 60s and redirects to existing visit. | **VERIFIED** |
| TC-LV-01 | Location Settings | Superuser accesses `/settings/location/` | View renders settings form (tolerance=300m, max accuracy=50m/100m, auto-save customer GPS toggle, verification switches). | Form loads with default 300m tolerance and toggles; POST updates settings model in database. | **VERIFIED** |
| TC-LV-02 | Location Settings | Non-superuser attempts to access `/settings/location/` | HTTP 403 / access denied redirect. Nav link is hidden in menu. | Non-superuser redirected to `/` with error message; menu link is wrapped with `request.user.is_superuser`. | **VERIFIED** |
| TC-LV-03 | User Settings | Superuser edits user's `bypass_location_verification` | Setting is saved. Non-superuser cannot view or modify this field. | Superuser toggles `/auth/users/<pk>/toggle-bypass-location/`; non-superuser attempt is blocked on backend. | **VERIFIED** |
| TC-LV-04 | Geolocation Check | Check-in within tolerance ($d \le 300\text{m}$) | `location_verified=True`, `location_status="ضمن النطاق المحدد"`, icon `gpp_good`. | Distance calculated via Haversine (e.g. 24.19m); verified status set and saved. | **VERIFIED** |
| TC-LV-05 | Geolocation Check | Check-in out of tolerance ($d > 300\text{m}$) without bypass | `location_verified=False`, `location_status="بعيد جدا عن الموقع المحدد"`, icon `gpp_maybe`. | Distance 180km calculated; `location_verified=False`, `verification_status="unverified"`. | **VERIFIED** |
| TC-LV-06 | Geolocation Check | Check-in out of tolerance with superuser / bypass enabled | `location_verified=True`, `verification_status="force_bypassed"` (`تم تجاهل التحقق بالقوة`), icon `gpp_maybe`. | Distance > 300m allowed for bypass user; badge displays "تم تجاهل التحقق بالقوة" matching reference visit #154829. | **VERIFIED** |
| TC-LV-07 | Geolocation Check | First visit check-in for customer with no saved location | Auto-saves customer coordinates from check-in GPS (`auto_set_customer_location_in_visit=True`), marks verified. | Contact coordinates updated on `ContactAddress` and `Contact.latitude/longitude`, `has_saved_location=True`. | **VERIFIED** |
| TC-LV-08 | Visit Dossier | Visit detail view (`/visits/<id>/`) | Renders location verification card with distance (e.g. `631.90 m`), completion status, and location status. | Renders shield icon (`gpp_good`/`gpp_maybe`), distance in meters, completion status, location status, and Google Maps link. | **VERIFIED** |
| TC-UI-01 | Responsive | Viewport test at 320px, 360px, 375px, 390px, 430px | 0 horizontal overflow; clean customer card and modal layout. | Mobile bottom navbar active, responsive form grid stacks cleanly, touch buttons $\ge 44$px. | **VERIFIED** |
| TC-UI-02 | Responsive | Viewport test at 768px, 1024px, 1366px, 1920px | Proper desktop grid and dialog width. | Sidebar visible, 2-column details grid, right column verification card layout preserved. | **VERIFIED** |
