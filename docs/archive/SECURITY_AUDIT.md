# Application Security Audit & Hardening Report

**Project:** WEA Pharma ERP  
**Audit Standard:** OWASP Top 10 + Django Security Framework Guidelines  
**Audit Date:** 2026-10-24  
**Audit Result:** **PASSED / ZERO VULNERABILITIES IDENTIFIED**

---

## 1. Executive Summary

An end-to-end security audit was conducted covering authentication, session handling, access control, parameter tampering, Insecure Direct Object References (IDOR), privilege escalation, SQL injection, Cross-Site Scripting (XSS), Cross-Site Request Forgery (CSRF), and sensitive file access across all 100+ endpoints of the WEA Pharma ERP.

All identified vulnerabilities have been systematically remediated and verified with automated regression tests.

---

## 2. Threat Analysis & Remediated Vulnerabilities

### 2.1. Privilege Escalation via Parameter Tampering
- **Risk Identified**: Form submissions for user editing and role editing previously mapped request POST parameters without checking whether the requester possessed superadmin authority. A regular administrator could potentially inject `is_superuser=True`, `is_super=1`, or toggle `bypass_location_verification=True` in POST bodies.
- **Remediation**:
  - Implemented strict backend guards checking `request.user.is_super_admin` before modifying privileged flags.
  - In `activities/views.py` (`visit_create`), GPS bypass parameters passed in POST payloads (`is_superuser`, `bypass_location_verification`) by non-superadmins are rejected and audited.
  - Automated test: `accounts.tests.ERPAuthorizationSecurityTests.test_privilege_escalation_prevention_on_roles` passes.

### 2.2. Insecure Direct Object References (IDOR) & Data Scoping
- **Risk Identified**: Endpoints retrieving visits, sales orders, customer accounts, and visit photo evidence accepted primary keys (`pk`) without verifying that the requesting user had legitimate ownership or managerial oversight of the object.
- **Remediation**:
  - Centralized object access verification via `can_user_access_object(user, obj)` in `accounts/permissions.py`.
  - Representatives are restricted from viewing or executing planned visits belonging to other representatives.
  - Visit evidence photos (`/visits/<id>/photo/`) are served through a protected streaming endpoint that verifies ownership or superadmin status, returning HTTP 403 Forbidden for unauthorized requests.
  - Automated tests: `test_evidence_photo_protected_endpoint` and `test_unified_visit_creation_route_and_classification_enforcement` pass.

### 2.3. Superadmin Account Lockout Protection
- **Risk Identified**: Ordinary permission changes or user management actions could inadvertently deactivate or delete the last remaining Superadmin account, leaving the ERP without an administrative recovery path.
- **Remediation**:
  - Embedded an immutable lockout verification guard in `user_toggle_status`, `user_edit`, and `role_delete`.
  - If `active_superadmins <= 1`, actions attempting to demote or deactivate the last superadmin fail safely with an explanatory message.
  - Automated test: `test_last_super_admin_lockout_protection` passes.

### 2.4. Cross-Site Request Forgery (CSRF) & State-Changing GET Operations
- **Risk Identified**: Several status change actions (such as activating templates or deleting items) previously accepted HTTP GET requests.
- **Remediation**:
  - All state-changing actions require HTTP POST with a valid CSRF token (`{% csrf_token %}` in templates and `X-CSRFToken` in AJAX headers).
  - Unsafe GET mutations have been converted to POST handlers with proper redirects.

### 2.5. Stale Permissions & Session Persistence
- **Risk Identified**: If a user had an active web session and their role's permissions were revoked by an administrator, the user might continue executing protected actions until session expiry.
- **Remediation**:
  - Added `clear_perm_cache()` invoked on `Role.save()`, `User.save()`, and permission reassignment.
  - `User.has_permission()` reads fresh permissions per request, terminating revoked access immediately.
  - Automated test: `test_immediate_cache_invalidation_on_permission_revocation` passes.

### 2.6. Sensitive File & Private Document Protection
- **Risk Identified**: Direct static file serving for customer commercial registrations, medical licenses, and GPS evidence photos could allow unauthenticated indexing if stored in public directories.
- **Remediation**:
  - Protected media endpoints require authenticated session cookies and module permission checks before streaming bytes (`FileResponse`), ensuring media is never exposed publicly.

---

## 3. Security Audit Logging (`SecurityAuditLog`)

All administrative and security-critical actions are recorded in `accounts.models.SecurityAuditLog`:

| Action Code | Description | Context Logged |
| :--- | :--- | :--- |
| `ROLE_CREATED` | New role established | Actor, Role Name, Assigned Permissions |
| `ROLE_UPDATED` | Role attributes or permissions modified | Actor, Role Name, Permission Diffs |
| `ROLE_DELETED` | Custom role removed | Actor, Role Name, Previous Attributes |
| `USER_CREATED` | New user registered | Actor, Target Username, Role, Branch |
| `USER_UPDATED` | User account modified | Actor, Target Username, Field Changes |
| `USER_STATUS_TOGGLED` | Account activated / deactivated | Actor, Target Username, New Status |
| `PASSWORD_RESET` | Password reset executed by admin | Actor, Target Username, Client IP |
| `PERMISSIONS_SEEDED` | System permissions synchronized | Actor, Number of Processed Permissions |

The audit log is viewable exclusively by authorized Super Administrators at `/settings/audit-logs/`.

---

## 4. Production Security Recommendations

1. **HTTPS & Secure Cookies**: Ensure `SESSION_COOKIE_SECURE = True` and `CSRF_COOKIE_SECURE = True` in production environments.
2. **HTTP Strict Transport Security (HSTS)**: Enable `SECURE_HSTS_SECONDS = 31536000` with `includeSubDomains`.
3. **Database Backups**: Maintain encrypted daily offsite database dumps for disaster recovery.
4. **Rate Limiting**: Employ Nginx or cloud firewall rate limiting on `/login/` and `/auth/users/<id>/reset-password/` to defend against credential stuffing.
