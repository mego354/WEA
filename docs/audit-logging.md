# Audit logging

Audit logging is a business requirement. Two models exist on purpose.

## 1. Enterprise trail — `accounts.SecurityAuditLog`

Written **only** through `accounts.services.AuditLogService.log`.

| Field | Role |
|---|---|
| `actor` | User (null = system) |
| `module` | `auth`, `accounts`, `contacts`, `visits`, `templates`, `catalog`, `inventory`, `sales`, `purchases`, `treasury`, `areas`, `settings`, … |
| `action_type` | Code (`LOGIN`, `SALES_ORDER_APPROVED`, `STOCK_TRANSFER_APPROVED`, …) |
| `record_id` / `record_name` | Target identity |
| `target_user` / `target_role` | When a person/role is the subject |
| `description` | Arabic human text |
| `previous_values` / `new_values` | JSON snapshots (passwords/tokens redacted) |
| `status` | `SUCCESS` / `FAILURE` / `WARNING` |
| `reason` | Rejection/bypass notes |
| `ip_address` / `user_agent` | From `request` when passed |
| `created_at` | Auto |

`AuditLogService.log` catches database errors, logs them with `logger.error`, and returns `None`. **Limitation:** a failed audit does **not** roll back the business transaction. Do not wrap audit in a way that silently drops financial mutations without an error log.

Redaction keys include `password`, `token`, `api_key`, `secret`, `credit_card`, `cvv`, etc. (`REDACTED_KEYS` in `accounts/services.py`).

### Immutability

- Django admin: add/change/delete disabled (`accounts.admin.SecurityAuditLogAdmin`).
- App UI: `audit_logs_list` / `audit_log_detail` (JSON for the diff modal). Gated by `settings:auditLogs/view` (SuperAdmin in practice).
- Ordinary users must not get a delete API. Do not add one.

### Viewer

`/settings/audit-logs/` (also `/auth/audit-logs/` because of dual include). Filters: module, action, user, date range, `q`. Pagination 25. Detail endpoint returns JSON for the modal.

## 2. Workflow trail — `activities.ApprovalAuditLog`

Per visit / sales order / purchase order: `created`, `submitted`, `approved`, `rejected`, `resubmitted`, `status_changed`, `sent_to_agenda`, `edited_reapproval_required`, `distance_bypass`, `distance_exception_requested`, `cancelled`. Used by the approvals hub, visit creation/editing, visit start/end, and the unified visit timeline (`build_visit_timeline`).

This is **not** a substitute for `SecurityAuditLog`. Dual-write when a workflow action is also a business mutation (approve order, start/end visit, create/edit visit, bypass distance, request distance exception).

## 3. Coverage (implemented)

| Area | Mechanism |
|---|---|
| Login / logout / failed login | `accounts.views` → `AuditLogService` |
| Users, roles, password reset, bypass toggle | `accounts.views` |
| Permission seed | `setup_permissions` |
| Contacts, todos, comments, attachments, import/export | `contacts.views` |
| Areas | `master_data.views` |
| Sales order lifecycle + collections | `sales/services.py` |
| Purchase order/return lifecycle | `purchases/services.py` |
| Vault deposit/withdraw/transfer, vendor payments | `treasury/services.py` |
| Inter-warehouse transfer create/approve/reject/execute | `inventory/services.py` `ProductTransferService` |
| Catalog product create/update/delete | `catalog/views.py` |
| Visit create / edit / post-approval re-approval / distance bypass / distance exception / start / end / approve / reject | `activities/views.py` & `activities/services.py` write **both** `ApprovalAuditLog` and `AuditLogService` (`VISIT_CREATED`, `VISIT_UPDATED`, `VISIT_EDITED_REAPPROVAL_REQUIRED`, `VISIT_DISTANCE_BYPASSED`, `VISIT_DISTANCE_EXCEPTION_REQUESTED`, `VISIT_APPROVED`, `VISIT_REJECTED`) |
| Bulk daily planned visit scheduling | `activities/views.py` (`planned_visits_bulk_add`) writes `BULK_PLANNED_VISITS_CREATED` to `AuditLogService` |
| Location & distance validation settings | `master_data/views.py` (`location_settings_view`) writes `SETTINGS_UPDATED` to `AuditLogService` |

## 4. Gaps (known)

- Visit **create / approve / reject** primarily `ApprovalAuditLog` in views; enterprise `VISIT_*` codes exist on `SecurityAuditLog` but are not used on every view branch.
- Django **admin** edits of business models are not automatically mirrored to `SecurityAuditLog`.
- `sync_data_trigger` does not log a real import (it only timestamps config).
- Excel exports should log `BULK_EXPORT` where not yet called.
- No request correlation id field (use `ip_address` + timestamp).
- `AuditLogService` duplicate `import logging` leftover was removed; keep a single logger.

When you add a mutation path (including management commands), call `AuditLogService.log(..., request=request)` inside the same `atomic` block **after** the successful write, or `status='FAILURE'` when you reject before write.

## 5. Policy

- Do not let users edit history.
- Financial/stock: reverse/cancel entries rather than DELETE rows.
- Do not log the same event twice from view **and** service; prefer the service.
- Approval hub may write `ApprovalAuditLog` **and** the service writes `SecurityAuditLog` — different audiences.
