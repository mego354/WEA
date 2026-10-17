# Implementation Task List: Visit Registration, Unified Workflows, and Location Verification

## Phase 1: Data Models & Migrations
- [x] 1.1 Add `LocationSettings` model in `master_data/models.py` with tolerance (default 300m), accuracy thresholds (50m, 100m), auto-save toggle, and workflow verification flags.
- [x] 1.2 Add `bypass_location_verification` and `can_bypass_location` property to `User` in `accounts/models.py`.
- [x] 1.3 Add convenience properties `latitude`, `longitude`, `has_saved_location`, and `set_location()` to `Contact` in `contacts/models.py` referencing `ContactAddress` with getter and setter support.
- [x] 1.4 Enhance `Visit` model in `activities/models.py` with `distance`, `location_status`, `verification_status`, `device_accuracy`, and `customer_latitude/longitude_snapshot`.
- [x] 1.5 Generate and run Django migrations (`accounts.0002`, `activities.0003`, `master_data.0002`).

## Phase 2: Customer Selection & Search API
- [x] 2.1 Implement `customers_search_api` in `contacts/views.py` with role-based scoping (Rep vs Manager/Admin), name/code/serial search, and rich contact metadata (coordinates, tags, categories).
- [x] 2.2 Wire routes in `contacts/urls.py` and `config/urls.py` (`/contacts/api/search/`, `/api/customers/search/`, `/api/v1/visits/contacts/list`).
- [x] 2.3 Verify API responses and role-based permission enforcement.

## Phase 3: Unified Visit-Registration Workflow & UI
- [x] 3.1 Upgrade `VisitForm` in `activities/forms.py` to support customer scoping, template selection, and geolocation fields.
- [x] 3.2 Update `visit_create` in `activities/views.py` to act as canonical registration handler supporting `contact_id`, `template_id`, `planned_item_id`, and GPS verification.
- [x] 3.3 Redesign `templates/activities/visit_form.html` with:
  - Interactive searchable typeahead customer selector with debounce, code tags, and empty/loading states.
  - Rich customer card on selection (Avatar initials, code, category, specialty, address, saved GPS).
  - Visit template dropdown matching reference.
  - Browser geolocation capture (`navigator.geolocation`) with manual fallback.
  - Real-time client-side Haversine distance feedback.
  - Anti-duplicate submission protection.
- [x] 3.4 Wire all entry points to canonical workflow:
  - Global FAB Action 1 ("تسجيل زيارة خارج الخطة") in `templates/layouts/base.html` -> routes to `/visits/create/?contact_id=...`.
  - Visits list ("+ تسجيل زيارة") in `templates/activities/visits_list.html` -> `/visits/create/`.
  - Planned visits ("بدء الزيارة") in `templates/activities/planned_visits_list.html` -> redirects to canonical form with context and marks item executed on submission.
  - Contact dossier ("تسجيل زيارة") in `templates/contacts/contact_detail.html` -> adds dedicated action button and 3-dots menu item linking to `/visits/create/?contact_id=...`.

## Phase 4: Location Verification Subsystem & Superuser Controls
- [x] 4.1 Implement `location_settings_view` in `master_data/views.py` restricted to superusers (`is_superuser` or `is_super_admin`).
- [x] 4.2 Create `templates/settings/location_settings.html` matching reference ERP layout and styling.
- [x] 4.3 Add navbar menu link `gps_fixed اعدادات الموقع` under Settings, visible only to superusers.
- [x] 4.4 Add `bypass_location_verification` control in `accounts/views.py` (`/auth/users/<pk>/toggle-bypass-location/`), strictly restricted to superusers on backend and UI.
- [x] 4.5 Implement Haversine distance verification engine in `activities/services.py`:
  - Calculate distance against contact GPS.
  - Auto-set customer location on first check-in if configured.
  - Set `location_verified`, `verification_status` (`verified`, `force_bypassed`, `unverified`), and `location_status` (`ضمن النطاق المحدد`, `بعيد جدا عن الموقع المحدد`).
- [x] 4.6 Update `templates/activities/visit_detail.html` with location verification card matching reference layout (shield icon, distance in meters, completion status, location status, Google Maps link).

## Phase 5: Verification & Quality Assurance
- [x] 5.1 Run automated test suite (`python test_e2e_workflows.py`, `python manage.py test activities`). All tests pass 100%.
- [x] 5.2 Add specific unit & E2E tests for customer scoping, unified workflow entry points, location verification, and superuser permission barriers (`test_visit_location_e2e.py`).
- [x] 5.3 Run responsive viewport tests across 320, 360, 375, 390, 430, 768, 1024, 1366, and 1920 px (`test_responsive_viewports.py`).
- [x] 5.4 Update audit and test plan documents with final verification statuses.
