# Visit Permissions & Authorization Architecture

**Project:** WEA Pharma ERP  
**Module:** Activities Subsystem (`activities`)  
**Specification:** Role-Based Access Control, Regional Scoping & Dual-Control Anti-Self-Approval  

---

## 1. Permission Matrix by Role

| Action / Capability | Sales Representative (`sales_rep`) | Area / Sub-Area Manager (`manager`) | Superuser / SuperAdmin (`admin`) |
| :--- | :---: | :---: | :---: |
| **View Visit Directory** | Assigned Visits Only | Regional Scoped (Own Area/Sub-Area) | All Visits Enterprise-wide |
| **Create Planned / Unplanned Visit** | Yes (Locked to Self) | Yes (Can assign any rep in area) | Yes (Can assign any rep) |
| **Approve / Reject Visits** | ❌ Forbidden | ✅ Allowed (within regional scope) | ✅ Allowed Enterprise-wide |
| **Approve Own Visit (Self-Approval)** | ❌ Strictly Blocked | ❌ Strictly Blocked (Dual-Control) | ✅ Allowed for root admin |
| **Start Visit (Check-in)** | Yes (Assigned rep only) | Assigned rep only (or superuser override) | Yes |
| **Submit Answers / Save Draft** | Yes (Assigned rep only) | Assigned rep only (or superuser override) | Yes |
| **End Visit (Check-out)** | Yes (Assigned rep only) | Assigned rep only (or superuser override) | Yes |
| **Bypass GPS / Location Verification** | ❌ Blocked (unless explicit flag set) | ❌ Blocked (unless explicit flag set) | ✅ Allowed |
| **Manage Visit Templates** | ❌ Forbidden (HTTP 403) | ✅ Allowed (with perm `activities:templates/manage`) | ✅ Allowed |

---

## 2. Core Security & Authorization Rules

### A. Dual-Control Anti-Self-Approval Rule
- **Policy:** In accordance with financial and operational dual-control integrity, **no user can approve their own submitted visit record**, regardless of their managerial title.
- **Enforcement:** Implemented in `accounts/permissions.py:can_user_access_object()`:
  ```python
  if action in ('approve', 'disapprove', 'reject'):
      if obj.owner == user or getattr(obj, 'created_by', None) == user:
          if not (user.is_superuser or getattr(user, 'is_super_admin', False)):
              return False
  ```
- **Auditing:** Attempts to self-approve are logged in security audit logs.

### B. Regional Territorial Scoping
- **Policy:** Managers can only view, review, approve, or reject visits that belong to customers located within their designated `assigned_areas` or `assigned_sub_areas`.
- **Enforcement:**
  - Evaluated via `accounts/permissions.py:check_regional_access(user, contact)`.
  - Superusers and enterprise executives bypass regional restrictions.

### C. Representative Assignment Locking
- **Policy:** When creating a visit, a field representative cannot assign the visit to another representative. Only managers and administrators have delegation authority.
- **Enforcement:** Evaluated via `can_assign_other_representative(request.user)`. If false, `visit.owner = request.user` is enforced server-side regardless of POST payload.

### D. GPS Location Enforcement & Bypass Authorization
- **Policy:** Field representatives must be physically located within the configured distance tolerance (e.g. 150 meters) of the customer's coordinates when starting and completing a visit.
- **Bypass Rule:** Only users with `can_bypass_location=True` (or Superusers) can submit a bypass flag. A non-empty `bypass_reason` is mandatory, and the override is logged in `ApprovalAuditLog` with `verification_status='force_bypassed'`.
