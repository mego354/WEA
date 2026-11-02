# User Geographic Area Assignments & Hierarchical Selector

## 1. Executive Summary

This document describes the redesigned Geographic Area Selection system for user management in WEA Pharma ERP (accessible at Add New User and `settings/users/<pk>/edit/`).

The previous implementation relied on a raw HTML multi-select dropdown requiring desktop keyboard shortcuts (`Ctrl+Click`) and displaying unformatted records. The new implementation introduces an accessible, hierarchical, searchable component (`templates/components/geographic_area_selector.html`) backed by strict server-side validation and managerial boundary enforcement.

---

## 2. Interface Design & User Experience (UX)

### Key Capabilities:
1. **Readable Arabic Hierarchy:**
   - Clearly separates root Main Areas (Governorates / محافظات) from child Sub-Areas (مراكز / مناطق).
   - Displays canonical Arabic area names, codes, and type badges (`[CAI]`, `[NASR]`, `محافظة`).
   - Explains scoping semantics: *"تحديد المحافظة الرئيسية يمنح إشرافاً شاملاً على جميع مناطقها الفرعية"* (Selecting a main area includes organizational oversight across all child sub-areas).
2. **Instant Search by Name:**
   - Real-time client-side search filtering by Arabic and English names/codes.
   - Automatically expands matched governorates so nested subareas are immediately accessible.
3. **Selected Areas Summary (Pill Tags):**
   - Active selections are rendered as interactive chips at the top of the selector.
   - Clicking `×` on any chip immediately unchecks the area without requiring manual tree navigation.
4. **Bulk Actions & Counter:**
   - "تحديد الكل" (Selects all visible areas matching current search filter).
   - "مسح التحديد" (Clears all selections).
   - Dynamic counter badge (e.g. `3 محددة`).
5. **Mobile Responsiveness & RTL Layout:**
   - Touch targets designed for minimum 44px height.
   - Native Right-to-Left (RTL) alignment with clean micro-interactions.
   - Zero horizontal overflow on viewports at 375px, 390px, 430px, and desktop.

---

## 3. Component Architecture & Integration

The selector is implemented as a reusable component:
`templates/components/geographic_area_selector.html`

### Invocation Syntax:
```django
{% include 'components/geographic_area_selector.html' with selector_id='edit_user' hierarchical_areas=hierarchical_areas selected_area_ids=selected_area_ids %}
```

### Context Parameters:
- `selector_id`: Namespace prefix preventing DOM ID and function collisions when multiple forms or modals exist on the same page.
- `hierarchical_areas`: Root `Area` queryset with prefetched `subareas`.
- `selected_area_ids`: List of integer IDs corresponding to the user's current assignments (`target_user.assigned_areas.values_list('id', flat=True)`).

---

## 4. Server-Side Security & Validation

The backend does not rely on client-side constraints:

```python
def validate_assigned_areas_for_user(request_user, area_ids):
    """
    1. Validates all IDs are valid integers.
    2. Verifies all IDs exist in master_data.Area.
    3. If request_user is a manager (not superadmin), verifies all submitted
       IDs belong strictly to the manager's authorized main area scope.
    """
```

### Validation Rules:
1. **Non-Existent / Invalid IDs:** If client submits bogus IDs, the request fails with `"توجد مناطق جغرافية غير صالحة أو غير موجودة بالنظام"`.
2. **Manager Boundary Escalation:** If an area manager attempts to assign areas outside their main area, the request fails with `"لا تمتلك الصلاحية لتعيين مناطق جغرافية خارج نطاق مسؤوليتك الإدارية المعتمدة"`.
3. **Superadmin Scope:** Superadmins maintain unrestricted ability to assign any active geographic area in the system.

---

## 5. Automated Unit Tests

Verified via `accounts/tests_geographic_areas_selector.py`:
- `test_get_hierarchical_areas_for_superadmin_and_manager`: Verifies hierarchy prefetching and manager scope isolation.
- `test_validate_assigned_areas_server_side`: Tests valid, invalid, non-integer, and unauthorized cross-area submissions.
- `test_user_edit_page_renders_hierarchical_selector`: Verifies template rendering and pre-selection of existing areas.
- `test_user_edit_post_updates_areas_safely`: Verifies end-to-end POST updating `user.assigned_areas` and recording audit logs.
