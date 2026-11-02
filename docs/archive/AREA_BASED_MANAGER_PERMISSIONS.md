# Area-Based Manager Permissions and Centralized Authorization

## 1. The Core Area Hierarchy Rule

The enterprise organizational structure defines geographic areas hierarchically:
- **Main Area (Root Governorate)**: The highest-level territorial jurisdiction (e.g., Cairo, Alexandria, Giza), represented by `parent=None` or `area_type='governorate'`.
- **Secondary Area (District / Sub-Area)**: Operational subdivisions (e.g., Nasr City, Heliopolis, Maadi, Smouha), where `parent` points to the containing main area.

### The Canonical Eligibility Rule
> **Approval and managerial oversight eligibility are determined strictly by Main Area (Root Governorate), NEVER by secondary/sub-area.**

A manager assigned to Cairo can supervise and approve operations of any representative in Cairo, even if the representative is assigned to a different sub-district (e.g., manager assigned to "Nasr City" or "Cairo", representative assigned to "Maadi"). Conversely, a manager assigned to Alexandria has zero jurisdiction over a Cairo representative, regardless of role or secondary area labels.

Inferring area membership from display labels, text matching, or superficial name comparisons is strictly prohibited. Authorization must resolve the canonical database tree.

---

## 2. Canonical Hierarchy Traversal

Located in `accounts.permissions`:

```python
def get_main_area(area):
    """
    Traverse up the area hierarchy to identify the root main area (e.g., Governorate).
    """
    if not area:
        return None
    visited = set()
    current = area
    while current.parent and current.id not in visited:
        visited.add(current.id)
        current = current.parent
    return current
```

### Main Area Sets Resolution
```python
def get_user_main_areas(user):
    """
    Return a set of root main areas associated with a user's assigned areas.
    """
    if not user or not user.is_authenticated:
        return set()
    main_areas = set()
    for area in user.assigned_areas.all():
        root = get_main_area(area)
        if root:
            main_areas.add(root)
    return main_areas
```

---

## 3. Centralized Authorization Engine

All permission checks across views, services, querysets, and APIs rely on a unified suite of functions in `accounts.permissions`:

### 1. `is_manager_eligible_for_user(manager, target_user)`
- **Anti-Self-Approval**: Asserts `manager.id != target_user.id`. A user cannot approve their own operations.
- **SuperAdmin Override**: Superadmins are globally eligible.
- **Role Verification**: Validates that the manager holds a managerial role (`is_area_manager=True`, `is_manager_role=True`, or managerial role title).
- **Main Area Intersection**: Traverses both the manager's and the target user's assigned areas up to their root main areas. If `manager_roots.intersection(target_roots)` is non-empty, the manager is authorized.
- **Fail-Secure Rule**: If either user lacks assigned areas, access is rejected immediately.

### 2. `is_manager_eligible_for_area(manager, area)`
- Resolves the main area of the target `area`.
- Matches against the root main areas of the manager.
- Ensures managers can oversee sub-areas under their root governorate even if not directly assigned to that specific sub-area.

### 3. `get_user_managed_areas(user)`
- Returns all areas within the user's root main areas.
- If a manager is assigned to "Cairo", this returns Cairo and all child districts (Maadi, Nasr City, Heliopolis, etc.).

### 4. `get_user_managed_representatives(user)`
- Evaluates all active representatives whose root main areas intersect with the manager's root main areas.

---

## 5. Scope-Based Queryset Filtering (`get_scoped_queryset`)

Every list view and report applies backend queryset scoping via `get_scoped_queryset(queryset, user, model_name)`:

| Model | SuperAdmin Scope | Area Manager Scope | Representative Scope |
|---|---|---|---|
| `Warehouse` | All warehouses | All warehouses owned by reps in same main area + non-rep warehouses | Own designated warehouse |
| `Vault` | All vaults | All vaults owned by reps in same main area + public vaults | Own designated vault |
| `InventoryStock` | All stock records | Stock in warehouses within same main area | Stock in own designated warehouse |
| `ProductTransferRequest` | All requests | Requests where source or dest rep is in same main area | Requests involving own warehouse |
| `SalesOrder` | All orders | Orders created by reps in same main area | Orders created by self |
| `Visit` | All visits | Visits conducted by reps in same main area | Visits conducted by self |

---

## 6. Granular Object-Level Permissions (`can_user_access_object`)

Secures detail views and action endpoints against URL manipulation or unauthorized ID injection:
- **Main Area Verification**: Confirms target entity or owner belongs to the manager's root main area.
- **Anti-Self-Approval**: Prevents users from approving their own records.
- **Read-Only Treasury Guard**: Specifically blocks managers from executing financial transactions (`deposit`, `withdraw`, `transfer`, `adjust`, `edit`, `delete`) on representative vaults. Managers hold inspection privileges only.
