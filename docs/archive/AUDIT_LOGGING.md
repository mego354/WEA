# Comprehensive Audit Logging Documentation

## 1. Executive Summary

The WEA ERP platform implements an append-only, centralized audit logging infrastructure providing complete traceability of all operational, financial, and security actions across all system modules. The subsystem is driven by `SecurityAuditLog` in `accounts/models.py` and managed exclusively through the centralized `AuditLogService` in `accounts/services.py`.

---

## 2. Architecture & Data Model

### `SecurityAuditLog` Model (`accounts/models.py`)

The `SecurityAuditLog` model is append-only and immutable. It captures structured details for any state-changing event:

| Field | Type | Description |
|---|---|---|
| `actor` | `ForeignKey(User, null=True, on_delete=SET_NULL)` | The user who initiated the event, or `None` if automated by the system. |
| `module` | `CharField(max_length=50, choices=MODULE_CHOICES)` | The system subsystem (e.g. `auth`, `accounts`, `contacts`, `custom_fields`, `todos`, `timeline`, `visits`, `templates`, `catalog`, `inventory`, `sales`, `purchases`, `treasury`, `areas`, `settings`). |
| `action_type` | `CharField(max_length=100)` | Standardized event action code (e.g. `LOGIN`, `USER_CREATED`, `CONTACT_UPDATED`, `TODO_TOGGLED`, `SETTINGS_UPDATED`). |
| `record_id` | `CharField(max_length=100, blank=True)` | Primary key or ID of the affected entity. |
| `record_name` | `CharField(max_length=255, blank=True)` | Human-readable name or title of the affected entity. |
| `target_user` | `ForeignKey(User, null=True, blank=True)` | Specific user affected (e.g. password resets, role changes). |
| `target_role` | `ForeignKey(Role, null=True, blank=True)` | Specific role modified. |
| `description` | `TextField` | Plain Arabic explanation of the event for human audit review. |
| `previous_values` | `JSONField(null=True, blank=True)` | Snapshot of state prior to modification. |
| `new_values` | `JSONField(null=True, blank=True)` | Snapshot of state after modification. |
| `status` | `CharField(choices=['SUCCESS', 'FAILURE', 'WARNING'])` | Execution outcome status. |
| `reason` | `TextField(blank=True)` | Explanation or failure reason. |
| `ip_address` | `GenericIPAddressField(null=True, blank=True)` | Client IP address of the requester. |
| `user_agent` | `TextField(blank=True)` | Client browser user agent string. |
| `created_at` | `DateTimeField(auto_now_add=True, db_index=True)` | Exact timestamp of event creation. |

---

## 3. `AuditLogService` Central API

All logging operations across all Django apps must go through `AuditLogService.log(...)`:

```python
from accounts.services import AuditLogService

AuditLogService.log(
    action='CONTACT_UPDATED',       # or action_type='...'
    module='contacts',
    user=request.user,              # or actor=...
    record_id=contact.id,
    record_name=contact.name,
    description=f"تحديث بيانات جهة الاتصال {contact.name}",
    previous_values=old_data,
    new_values=new_data,
    status='SUCCESS',
    request=request                 # automatically extracts IP & User-Agent
)
```

### Automatic Sensitive Data Redaction
Before saving `previous_values` and `new_values`, `AuditLogService._sanitize_values(data)` recursively traverses the dictionaries/lists and replaces sensitive keys with `[REDACTED]`. Redacted keys include:
- `password`, `old_password`, `new_password`, `confirm_password`
- `token`, `access_token`, `refresh_token`, `api_key`, `secret`, `secret_key`
- `credit_card`, `pin`, `cvv`

---

## 4. Audit Log Viewer (`/settings/audit-logs/`)

The audit logs interface (`templates/accounts/audit_logs.html`) offers comprehensive investigation capabilities:

1. **Filtering & Search:**
   - **Module filter:** Dropdown of all registered system modules.
   - **Action filter:** Dropdown of specific operational action types.
   - **User filter:** Filter events executed by a specific staff member.
   - **Date range filter:** `date_from` and `date_to` bounds.
   - **Free-text search (`q`):** Full-text search across `description`, `record_name`, `record_id`, `reason`, and actor names.
2. **Server-Side Pagination:** 25 entries per page with full query parameter retention.
3. **Previous vs. New Values Diff Modal:**
   - Clicking "عرض" opens `#auditDetailModal`.
   - Fetches JSON from `audit_log_detail` (`/settings/audit-logs/<pk>/`).
   - Visual side-by-side comparison: Previous values highlighted in rose red, New values highlighted in emerald green.
4. **Mobile Responsive Layout:**
   - Desktop: Dense, sortable, styled table with horizontal scroll prevention.
   - Mobile (`< 768px`): Fluid, touch-friendly card list displaying module badges, actor, timestamp, description, and details button.

---

## 5. Security & Permission Controls

- Accessible strictly to users with `settings:auditLogs/view` or `settings:rbac/view` permissions (SuperAdmin and authorized managers).
- Non-repudiation: `SecurityAuditLog` instances are append-only; update and delete operations are disallowed via application routing.
- Unit test verification in `accounts/tests_audit_logging.py`:
  - `test_audit_log_service_creation_and_redaction`
  - `test_audit_logs_view_filtering`
  - `test_audit_log_detail_api`

---

## 6. Bilingual Human-Readable Action Labels (`نوع العملية`)

The audit log interface displays clear, human-readable Arabic (and English) labels in the `نوع العملية` column, replacing ambiguous color-only indicators:

1. **Bilingual Action Registry (`SecurityAuditLog.ACTION_LABELS`):**
   - Maps every canonical action type to Arabic and English descriptions:
     - `USER_CREATED` / `CREATE`: `إنشاء مستخدم` / `Create User`
     - `USER_UPDATED` / `UPDATE`: `تعديل مستخدم` / `Update User`
     - `USER_DEACTIVATED` / `DELETE`: `تعطيل مستخدم` / `Deactivate User`
     - `LOGIN`: `تسجيل دخول` / `Login`
     - `LOGOUT`: `تسجيل خروج` / `Logout`
     - `PASSWORD_RESET`: `إعادة تعيين كلمة المرور` / `Password Reset`
     - `ROLE_CREATED` / `ROLE_UPDATED`: `إنشاء دور` / `تعديل دور`
     - `AREA_CREATED` / `AREA_UPDATED`: `إنشاء منطقة` / `تعديل منطقة`
     - `SETTINGS_UPDATED`: `تحديث الإعدادات` / `Update Settings`
     - `TRANSFER_APPROVED` / `TRANSFER_EXECUTED`: `اعتماد تحويل` / `تنفيذ تحويل`
     - `IMPORT` / `EXPORT`: `استيراد بيانات` / `تصدير بيانات`
2. **Safe Fallback Mechanism:**
   - Any legacy or unmapped code dynamically transforms into a readable capitalized string (e.g., `CUSTOM_ACTION` -> `Custom Action`) with a fallback badge, preventing blank values or broken rows.
3. **Secondary Visual Color Indicators:**
   - Soft colored dots remain alongside the text as secondary visual cues (green for creation/success, amber for edits, red for deletions/deactivations, blue for auth/security events).
4. **Canonical Code Filtering:**
   - Filtering in views and URLs strictly uses canonical action codes (e.g., `?action=USER_CREATED`), while the UI renders localized labels on table rows, mobile cards, filter chips, and detail inspection modals.

