# Coding standards

## Naming and layout

- Apps: plural business domains (`contacts`, `purchases`).
- Models: Django `PascalCase`. Status values: lowercase snake (`pending`, `manager_approval`).
- Permission codenames: `module:<app>` or `<app>:<entity>/<action>` as in `permission_registry.py`.
- URL names: existing snake_case (`sales_order_detail`). Reuse them; do not register a second name for the same path unless an alias already exists for the reference ERP.
- Templates: `templates/<app>/` or shared `templates/components/`, `templates/layouts/`.
- Services: `<App>Service` or domain class (`ProductTransferService`, `AuditLogService`).

## Django components

- **Models:** constraints and simple derived properties. Do not hide multi-table workflows in `save()`. Serial/number allocation already happens in several `save()` methods — keep that consistent if you add similar documents.
- **Managers/querysets:** prefer `get_scoped_queryset` over copying Q objects in every view.
- **Views:** function-based views are the dominant style. Add CBVs only when `RequirePermissionMixin` is a clear win. Do not mass-convert.
- **Forms:** `activities/forms.py` is the main Form usage. Other modules often parse `request.POST`. If you add a form, keep field names compatible with the template.
- **Serializers:** none (no DRF). JSON is built with `JsonResponse` dicts.
- **Signals:** not a primary architecture. Do not add audit signals that recurse on `SecurityAuditLog`.
- **Admin:** operational UI is the custom templates. Admin is for superuser recovery; keep audit logs immutable there.

## Separation of responsibilities

1. View: auth, permission decorator, parse/validate HTTP, call service, message, redirect/render.
2. Service: rules, locking, multi-model writes, audit log.
3. Permissions module: who can see/change which row.
4. Template: presentation only.

## DRY / SOLID

Extract a helper after the **second** copy into an existing module (`accounts.permissions`, `master_data.excel_utils`, `master_data.pagination_utils`). Do not create a new `core/` app for one function.

`is_representative` lives in `accounts.permissions`. Other modules must import it from there.

## Frontend

- Tailwind utilities already in templates. No new CSS framework.
- Keep Arabic copy. Reuse status badge classes from models (`status_badge_class`).
- Page JS in `{% block extra_js %}`. Shared table columns: `table_column_manager.js`.
- CSRF: Django cookie + `{% csrf_token %}` on POST forms; AJAX must send `X-CSRFToken`.

## Validation and errors

- Server-side validation is required. Client checks are optional UX.
- `ValidationError` in services → view catches and `messages.error` or JSON 400.
- 401/403 JSON: `{ "error": "Unauthenticated"|"PermissionDenied"|"Forbidden", "detail": "...", "perm_codename": optional }`.
- Do not `except Exception: pass` on audit, stock, or money paths. Geocoding fallback is an existing exception (log if you touch it).

## ORM and transactions

- `select_related` / `prefetch_related` on list/detail.
- `select_for_update()` when mutating `InventoryStock` or vault balances (already in transfer execute).
- `@transaction.atomic` on multi-step services.
- Parameterized ORM only; no string-built SQL.

## Security

- `DEBUG`, `SECRET_KEY`, `ALLOWED_HOSTS` from environment in production.
- Never log passwords, tokens, session keys (`AuditLogService` redacts known keys via `redact_sensitive_data`).
- CSRF middleware is on. Session auth only.
- Object lookup: scoped queryset or `can_user_access_object` after fetch.
- File uploads: existing ImageFields under `media/`; do not serve user HTML.

## Migrations

- Additive migrations preferred. Do not rewrite old migrations.
- Data migrations for roles/permissions go through management commands (`setup_permissions`).
- SQLite is the default in this checkout; avoid PostgreSQL-only features unless `DATABASES` is changed and documented.

## Dependencies

Declared in `requirements.txt`. Do not add packages for one-off formatting or another REST stack.

## Dead code

Delete only after searching: Python imports, `reverse('name')`, `{% url %}`, `include()`, admin registration, management commands, signals, dynamic `getattr`. `scratch/` is intentionally unmanaged.

## Completion

Match `AGENTS.md` checklist. Run tests for the apps you touched.
