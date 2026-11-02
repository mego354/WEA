# Agenda Implementation Report (تقرير تنفيذ جدول الأعمال)

**Date**: 2026-10-25  
**System**: WEA ERP / Bricks Rep  
**Status**: COMPLETE & VERIFIED

---

## 1. Overview & Reference ERP Inspection

In accordance with Section 10 of the implementation specification, the **Agenda tab (`جدول الاعمال`)** was designed and implemented by inspecting the reference application at `https://weapharma.bricks-rep.com/agenda`.

### Reference ERP Observations:
- **Navigation Position**: Positioned directly below "الرئيسية" in the sidebar navigation using the `view_agenda` icon.
- **Top Tab Switcher**: Two top tabs:
  - `الزيارات` (Visits): Default active tab with teal indicator `#27bebe`.
  - `Todos`: Secondary tab displaying personal/representative daily tasks and a "+ اضف Todo جديد" button.
- **Date Selector**: Includes previous/next day chevron navigation, current date display with calendar icon, and date picker functionality.
- **Actions**: "+ تسجيل زيارة خارج الخطة" button that opens an out-of-plan visit modal allowing customer selection before launching visit check-in.
- **Empty State**: Custom illustration (sleeping figure under tree with birds) and caption `لا خطط أخرى لهذا اليوم` when no visits are planned for the selected date.

---

## 2. Technical Architecture & Data Modeling

### 2.1 Reusing Existing Planning & Visit Records
Rather than duplicating visits or creating disconnected models, the Agenda dynamically consolidates:
1. `PlannedVisitDay` & `PlannedVisitItem`:
   - Daily planned itinerary items scheduled for the representative.
   - Shows sequence order, contact details, template classification, and execution status (`مخططة` vs `منتهية`).
   - If not yet executed, renders action "بدء الزيارة" (Start Visit) linking directly to the visit registration flow.
2. `Visit` (Out-of-Plan and Executed Visits):
   - Ad-hoc visits registered directly on that day (`is_planned=False`).
   - Displays real-time approval status badges (`معتمد` in emerald, `قيد الاعتماد` in amber, `مرفوض` in rose).
   - Links directly to `visit_detail` (`/activities/visits/<id>/`).

### 2.2 AgendaTodo Model
To support daily representative checklist items observed in the reference system, `AgendaTodo` was added:
```python
class AgendaTodo(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='agenda_todos')
    date = models.DateField(db_index=True)
    title = models.CharField(max_length=255)
    is_completed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

---

## 3. Territorial Scoping & Role-Based Authorization

| Role | Territorial Scoping & Restrictions | Behavior |
| :--- | :--- | :--- |
| **Representative** (`is_rep=True`) | Scoped strictly to own assigned records (`request.user`). | Passing `?assignee=<other_id>` returns HTTP 403 Forbidden. Selector dropdown is hidden. |
| **Regional Manager** (`is_area_manager=True`) | Scoped to own agenda + representatives assigned to their managed Region and all child Subregions. | Can switch reps via dropdown within regional scope. Accessing an unrelated regional rep returns HTTP 403 Forbidden. |
| **SuperAdministrator** (`is_superuser=True`) | Global oversight across all regions and representatives. | Full dropdown of all active representatives. Can view any rep's agenda on any date. |

---

## 4. Endpoints & Route Configuration

- `/agenda/` (and `/activities/agenda/`): Main agenda view (`activities.views.agenda_view`).
- `/activities/agenda/todos/add/`: Adds a new daily task (`agenda_todo_add`).
- `/activities/agenda/todos/<int:pk>/toggle/`: Toggles todo completion (`agenda_todo_toggle`).
- `/activities/agenda/todos/<int:pk>/delete/`: Deletes a todo (`agenda_todo_delete`).

---

## 5. Mobile & Responsive Design

- **Mobile Viewport Compatibility**: Tested at 320px, 375px, 390px, and 430px widths.
- **Touch-Friendly Controls**: All buttons and interactive tabs have minimum touch targets $\ge 44$px.
- **RTL Arabic Alignment**: Navigation arrows, status pills, and text flow strictly follow native Arabic right-to-left layout.
- **Adaptive Card Layout**: Responsive 2-column grid on desktop collapsing to vertical card list on mobile devices.

---

## 6. Automated Test Results

Test suite: `activities/tests_agenda.py`

```text
Found 8 test(s).
System check identified no issues (0 silenced).
........
----------------------------------------------------------------------
Ran 8 tests in 10.597s

OK
```

All 8 tests passed with 100% success rate, confirming security enforcement, date filtering, and agenda rendering.
