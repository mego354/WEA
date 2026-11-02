# Visit Classification: Planned vs Unplanned Visits

## 1. Executive Summary
In pharmaceutical territory management, visits are strictly categorized into two operational streams:
1. **Planned Visits (زيارات مخططة)**: Visits scheduled in advance as part of monthly or weekly itinerary plans approved by sales supervisors (`PlannedVisitDay` and `PlannedVisitItem`).
2. **Unplanned Visits (زيارات خارج الخطة)**: Ad-hoc, spontaneous, or urgent visits initiated by representatives to address emergent doctor requests, pharmacy restock needs, or opportunities.

Prior to this update, planned and unplanned visits were visually indistinguishable, causing reporting inaccuracies and making it difficult for supervisors to audit plan adherence versus field flexibility.

This document outlines the database persistence, model relationships, badge styling, UI indicators, and filtering infrastructure distinguishing planned and unplanned visits.

---

## 2. Database Schema & Persistence

### 2.1 Model Representation (`Visit.is_planned`)
In [activities/models.py](file:///c:/D/Cooding/GENERAL/new/ERP/activities/models.py):
```python
class Visit(models.Model):
    is_planned = models.BooleanField(
        default=False,
        db_index=True,
        help_text="تصنيف الزيارة: مخططة ضمن الخطة الشهرية (True) أو زيارة حرة خارج الخطة (False)"
    )
    ...
```
- **Indexed Flag**: `db_index=True` guarantees high-speed filtering across large historical datasets.
- **Explicit Assignment**:
  - In `visit_create`: `visit.is_planned = bool(planned_item_id)`.
  - When executed via planner (`planned_visit_item_execute`), `planned_item_id` is supplied in the URL and hidden input.
  - When created directly from `/visits/create/`, `is_planned` defaults to `False`.
  - Classification is stored permanently in the database record and is never inferred from referrer URLs or mutable buttons.

### 2.2 Model Properties for UI Display
```python
@property
def plan_type_display_ar(self):
    return "زيارة مخططة" if self.is_planned else "زيارة خارج الخطة"

@property
def plan_type_badge_class(self):
    if self.is_planned:
        return "bg-blue-50 text-blue-700 border-blue-200"
    return "bg-purple-50 text-purple-700 border-purple-200"
```

---

## 3. Visual Parity & UI Indicators

### 3.1 Visits List Header Chips
At the top of `/visits/`, count badges display the operational split:
```html
<a href="?plan_type=planned" class="text-xs px-2.5 py-1 bg-blue-50 text-blue-700 font-bold rounded-full border border-blue-200">
    {{ planned_count }} زيارة مخططة
</a>
<a href="?plan_type=unplanned" class="text-xs px-2.5 py-1 bg-purple-50 text-purple-700 font-bold rounded-full border border-purple-200">
    {{ unplanned_count }} خارج الخطة
</a>
```

### 3.2 Table & Cards View
- **Table View**: Dedicated column `النوع` displaying `plan_type_display_ar` badge with distinct border and color coding.
- **Cards View**: Rendered prominently alongside the serial number and approval status badge.
- **Visit Detail Header**: Distinct pill badge showing whether the active or completed visit is planned or unplanned.

---

## 4. Filter Architecture
In `visits_list` view:
- Accepting `plan_type` query parameter:
  - `?plan_type=planned` -> filters `qs.filter(is_planned=True)`
  - `?plan_type=unplanned` -> filters `qs.filter(is_planned=False)`
- Slide-over Filter Drawer:
  - Select input: `تصنيف التخطيط (النوع)` with options:
    - جميع التصنيفات
    - زيارة مخططة (Planned)
    - زيارة خارج الخطة (Unplanned)

---

## 5. Canonical Route Association & Security Checks

### 5.1 Linkage to Planned Item
When executing a visit via the canonical route `/visits/create/?planned_item_id=<id>`:
- The system automatically links the resulting `Visit` to the source `PlannedVisitItem` via `plan_item.visit = visit`.
- `plan_item.is_executed` is set to `True`.
- `visit.is_planned` is permanently stored as `True`.

### 5.2 Security & Ownership Enforcement
- Representatives can only execute plan items assigned to them.
- If a representative tampers with the query parameter or POST payload by supplying another rep's `planned_item_id`, the request is denied with HTTP 302 redirecting to `visits_list` and logging an authorization error.
- Superusers and sales managers retain authorized override capability to execute or reassign any planned visit.
- Duplicate submission protection: if an already-executed plan item ID is resubmitted, the system intercepts the request and redirects directly to the existing visit details without creating duplicates.
