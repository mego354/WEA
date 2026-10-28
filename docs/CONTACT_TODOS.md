# Contact TODOs Subsystem & Blank-Page Resolution

## 1. Executive Summary

This document describes the root cause and complete resolution of the contact TODO page turning blank upon performing user actions (such as adding, checking, or deleting tasks) at `contacts/<id>/overview/?tab=todos`. It also outlines the enhanced asynchronous (AJAX) task management architecture.

---

## 2. Root Cause Analysis

Investigation identified three interrelated flaws causing the blank screen:

1. **Tab Case-Sensitivity & White-listing Mismatch:**
   - The UI and redirection links alternately requested `?tab=Todos` (capitalized) and `?tab=todos` (lowercase).
   - In `contact_detail` (`contacts/views.py`), tab selection was checked via strict string matching without `.lower()`. An unhandled tab name led to rendering an empty tab container without fallback content or context variables.
2. **Missing Action Handler & Route Disconnect:**
   - The deletion action triggered an unhandled exception (`AttributeError: module 'contacts.views' has no attribute 'contact_delete_todo'`), which returned HTTP 500 or an uncaught server error displayed as a blank page.
3. **Synchronous Full-Page Reload Jumps:**
   - Every checkbox toggle submitted a standard HTTP form that redirected back to the URL without tab parameters, stripping query parameters and causing navigation disorientations and scroll jumps.

---

## 3. Implementation & Resolution

### A. Robust Tab Normalization (`contacts/views.py`)

In `contact_detail`:
```python
ALLOWED_TABS = ['overview', 'activities', 'sales', 'purchases', 'attachments', 'todos', 'tasks']
raw_tab = request.GET.get('tab', 'overview')
active_tab = raw_tab.lower().strip() if raw_tab else 'overview'
if active_tab not in ALLOWED_TABS:
    active_tab = 'overview'
```
Any variant (`?tab=Todos`, `?tab=TODOS`, `?tab=todos`) is guaranteed to normalize cleanly to `'todos'`.

### B. Dedicated Action Endpoints (`contacts/urls.py` & `contacts/views.py`)

Three distinct endpoints were implemented to handle TODO lifecycle:

1. **`contact_create_todo(request, pk)`** (`/contacts/<pk>/todos/create/`):
   - Accepts title, due date, priority, and notes.
   - Creates `ContactTodo`.
   - Records `SecurityAuditLog(module='todos', action_type='TODO_CREATED')`.
   - Returns `{status: 'ok', todo: {...}}` for AJAX, or redirects to `?tab=todos`.
2. **`contact_toggle_todo(request, pk, todo_id)`** (`/contacts/<pk>/todos/<todo_id>/toggle/`):
   - Flips `is_completed` boolean and timestamps completion.
   - Records `SecurityAuditLog(module='todos', action_type='TODO_TOGGLED')`.
   - Returns `{status: 'ok', is_completed: true/false}` for AJAX, or redirects to `?tab=todos`.
3. **`contact_delete_todo(request, pk, todo_id)`** (`/contacts/<pk>/todos/<todo_id>/delete/`):
   - Deletes `ContactTodo`.
   - Records `SecurityAuditLog(module='todos', action_type='TODO_DELETED')`.
   - Returns `{status: 'ok'}` for AJAX, or redirects to `?tab=todos`.

### C. Seamless Asynchronous (AJAX) Frontend

In `templates/contacts/contact_detail.html`:
- Checkbox toggle triggers `fetch()` asynchronously:
  - Updates UI instantly without full-page reloads.
  - Applies strike-through styling to completed tasks.
- Inline task creation dynamically appends new items to the DOM.
- Instant task deletion with smooth element removal.
- Filter switch ("اظهر المنتهي") toggles completed items without network delay.

---

## 4. Automated Unit Test Verification

Covered in `contacts/tests_udf_todos_timeline.py` (`test_contact_todos_no_blank_page_and_ajax_support`):
1. Creation redirects strictly to `?tab=todos`.
2. AJAX toggle returns JSON `{status: 'ok', is_completed: true}`.
3. Synchronous toggle redirects strictly to `?tab=todos`.
4. Rendering with `?tab=todos` displays list without blanking.
5. Case normalization of `?tab=Todos` renders cleanly.
6. AJAX deletion removes task from database and returns HTTP 200.
