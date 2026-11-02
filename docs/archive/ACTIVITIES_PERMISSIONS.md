# Activities Module Permissions & Access Control

This document defines the permission rules, user roles, scoping restrictions, and backend enforcement discovered in the reference ERP (`weapharma.bricks-rep.com`).

---

## 1. Discovered Roles & Hierarchies

From `/api/v1/users` and `/api/v1/users/current`, the system defines:

| Role Name | Display Name | Permissions Scope | Record Visibility Scope |
| :--- | :--- | :--- | :--- |
| **SuperAdmin / Admin** | System Administrator | Full access to all modules, settings, approval actions, and all areas. | Company-wide |
| **AreaManager** | Area Manager | Can view all reps in assigned geographic area/governorate. Approve visits, plans, agreements. | Governorate / Area |
| **DistrictManager** | District Manager | Manages team of Medical Reps. Can schedule plans, approve/disapprove visits & agreements. | District / Lines |
| **MedicalRep** | Medical Representative | Field rep. Creates unplanned visits, executes planned visits, drafts agreements. | Assigned Contacts & Own Visits |

---

## 2. Granular Permissions Matrix

| Action | MedicalRep | DistrictManager | AreaManager | Admin / Super |
| :--- | :---: | :---: | :---: | :---: |
| **View Planned Visits** | Own only | Assigned Team | Assigned Area | All |
| **Create / Edit Planned Visits** | Yes (Own) | Yes (Team) | Yes | Yes |
| **Delete Planned Visits** | If draft/unexecuted | Yes | Yes | Yes |
| **View Visits Listing** | Own only | Assigned Team | Assigned Area | All |
| **Execute / Start Visit** | Yes | Yes | Yes | Yes |
| **Edit Finished Visit** | Disallowed | Disallowed | Restricted | Yes |
| **Approve / Disapprove Visit** | No | **Yes** | **Yes** | **Yes** |
| **View Agreements Listing** | Own created / territory | Team | Area | All |
| **Create Agreement** | Yes | Yes | Yes | Yes |
| **Edit Agreement** | If status = `new` | If status = `new` | Yes | Yes |
| **Approve / Disapprove Agreement** | No | **Yes** | **Yes** | **Yes** |
| **Mark Agreement as Done** | No | **Yes** | **Yes** | **Yes** |
| **Export Data (Excel)** | Yes (Scoped) | Yes (Team) | Yes (Area) | Yes (All) |

---

## 3. Backend Enforcement & Scoping Rules

1. **Queryset Scoping Rule:**
   - If user is `MedicalRep`, filter `Q(owner=request.user) | Q(created_by=request.user)`.
   - If user is `DistrictManager`, filter by reps reporting to this manager or users in the manager's assigned subareas.
   - If user is `AreaManager` or `Admin`, include all records in area or company-wide.
2. **Action Security Rule:**
   - Only managers and admins can POST to approval endpoints (`/agreements/<id>/approve/`, `/visits/<id>/approve/`). Any attempt by a rep returns `403 Forbidden`.
   - Edits on finalized records (`status='done'` on agreements or `status='finished'` on visits) are rejected with validation errors.
