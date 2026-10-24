# Visit Settings and Permissions Specification

## 1. Overview & Architecture
This document details the security architecture, permission matrix, authorization boundaries, and settings management for the Visits Module in `Bricks Rep`.

The module enforces strict role-based access control (RBAC), distinguishing between administrative managers and field medical representatives to prevent privilege escalation, tampered assignments, and unauthorized settings manipulation.

---

## 2. Role Definitions & Access Boundaries

| Role Name | Identifier | Key Responsibilities & Capabilities |
|---|---|---|
| **Superuser / Super Admin** | `is_superuser`, `is_super_admin` | Global administrative control, audit logging, template creation/editing, location/photo bypass authorization, representative assignment overrides. |
| **Area Manager / Supervisor** | `is_area_manager`, `can_manage_approvals` | Approving/disapproving representative visits, viewing evidence photos across assigned territories, managing team schedules. Cannot alter global template configurations unless granted staff status. |
| **Field Medical Representative** | `is_rep=True` (Standard User) | Checking into accounts, answering questionnaires, taking live location photos, completing visits. Strictly locked to self-assignment. Forbidden from modifying template schemas, bypassing GPS/photos, or accessing other reps' private evidence photos. |

---

## 3. Comprehensive Permission Matrix

| Operation / Endpoint | Field Medical Rep | Area Manager | Superuser / Admin | Backend Enforcement Location |
|---|:---:|:---:|:---:|---|
| **View Visits List** (`/visits/`) | Assigned / Own Visits | Team / Area Visits | All Visits | `activities.views.visits_list` |
| **Create Visit Record** (`/visits/create/`) | ✅ (Self-assigned only) | ✅ | ✅ | `activities.forms.VisitForm` & `visit_create` |
| **Override Assigned Rep** | ❌ **FORBIDDEN** | ✅ | ✅ | `VisitForm.clean()`, `can_assign_other_representative` |
| **Answer / Complete Visit** (`/visits/<id>/`) | ✅ (Own visits) | ✅ | ✅ | `activities.views.visit_detail` |
| **Bypass GPS / Photo Verification** | ❌ **FORBIDDEN** | ❌ (Unless authorized) | ✅ (Audited) | `activities.services.verify_visit_location` |
| **View Location Photo Evidence** | ✅ (Own visits) | ✅ (Team visits) | ✅ (All visits) | `activities.views.visit_evidence_photo` (403 if unauthorized) |
| **Approve / Disapprove Visit** | ❌ **FORBIDDEN** | ✅ | ✅ | `activities.views.visit_action`, `can_manage_approvals` |
| **View Visit Templates** | ✅ (Active only) | ✅ | ✅ | `activities.views.visit_templates_list` |
| **Create / Edit Visit Template** | ❌ **FORBIDDEN** | ❌ (Staff only) | ✅ | `visit_template_create`, `visit_template_edit` |
| **Toggle Template Status** | ❌ **FORBIDDEN** | ❌ | ✅ | `visit_template_toggle_status` |
| **Manage Question Builder** | ❌ **FORBIDDEN** | ❌ | ✅ | `template_question_add`, `template_question_edit` |

---

## 4. Security Controls & Tamper Resistance

### 4.1 Representative Assignment Locking
When creating a visit, representatives cannot spoof another representative's ID:
```python
def can_assign_other_representative(user):
    if not user.is_authenticated:
        return False
    if user.is_superuser or user.is_staff or getattr(user, 'is_super_admin', False):
        return True
    if user.role and (user.role.is_area_manager or any(t in (user.role.name or '').lower() for t in ['manager', 'admin', 'supervisor'])):
        return True
    return False
```
In `VisitForm`:
- If `not can_assign_other_representative(user)`, the `owner` field is disabled in HTML and forced to `user` in `clean()`.
- Tampered POST requests with `owner=<other_user_id>` are automatically overridden on the server.

### 4.2 Protected Evidence Photo Endpoint (`/visits/<pk>/evidence/photo/`)
Evidence photos contain sensitive location and field activity data. They are not served through open static URLs:
```python
@login_required
def visit_evidence_photo(request, pk):
    visit = get_object_or_404(Visit, pk=pk)
    if not visit.location_photo:
        raise Http404("لا توجد صورة إثبات مسجلة.")
    
    user = request.user
    can_view = (
        user.is_superuser or
        getattr(user, 'is_super_admin', False) or
        visit.owner_id == user.pk or
        visit.created_by_id == user.pk or
        (user.role and user.role.is_area_manager) or
        can_manage_approvals(user)
    )
    if not can_view:
        return HttpResponseForbidden("غير مصرح لك بالوصول إلى صورة الإثبات الخاصة بمستخدم آخر.")
    
    content_type, _ = mimetypes.guess_type(visit.location_photo.name)
    return FileResponse(visit.location_photo.open('rb'), content_type=content_type or 'image/jpeg')
```

### 4.3 Superuser Location Bypass Audit Trail
When an authorized administrator bypasses location or photo capture, client flags are ignored. The backend independently verifies user privileges and persists an audit record:
- `visit.bypassed_by = user`
- `visit.bypassed_at = timezone.now()`
- `visit.bypass_reason = "ضعف إشارة GPS داخل العيادة وتم التحقق هاتفياً"`
- `visit.verification_status = 'force_bypassed'`
