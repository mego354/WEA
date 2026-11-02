# Unified Visit Creation Workflow (`/visits/create/`)

## 1. Overview
The visit creation workflow has been unified under a single canonical route:
- **Canonical Route:** `/visits/create/` (URL name: `visit_create`)

Both **Planned Visits** (from itinerary plans) and **Unplanned Visits** (from the quick-action floating `+` button) utilize this shared controller, shared form, and unified business logic.

---

## 2. Architecture & Entry Points

```mermaid
graph TD
    A[Planned Visits /planned-visits/] -->|Click 'بدء الزيارة'| B[planned_visit_item_execute]
    B -->|Validate Ownership & Redirect| C[/visits/create/?contact_id=X&planned_item_id=Y]
    D[Floating '+' Quick Add Button] -->|Click 'زيارة خارج الخطة'| E[/visits/create/]
    
    C --> F[Canonical Visit Creation View `visit_create`]
    E --> F
    
    F -->|Validation & Security Checks| G[Create Visit Record in DB]
    G -->|Planned Linkage| H[Link plan_item.visit & set is_executed=True]
    G -->|Post-Creation Navigation| I[Redirect to /visits/<id>/ Detail & Answering]
```

### 2.1 Planned Visits Entry Point
1. **Initiation**: Rep navigates to `activities/planned-visits/` (`planned_visits_list`).
2. **Execution Action**: Rep clicks "بدء الزيارة" on a scheduled item (`PlannedVisitItem`).
3. **Execution Endpoint**: Requests `activities/planned-items/<pk>/execute/` (`planned_visit_item_execute`).
4. **Security & Authorization**:
   - The view verifies that the requesting user is either the assigned representative of the plan or has managerial/superuser privileges (`General Manager`, `Sales Manager`, `District Manager`).
   - If unauthorized, access is denied with a descriptive error message and redirected back to `planned_visits_list`.
5. **Redirection**: Redirects with 302 to:
   `/visits/create/?contact_id=<contact.id>&planned_item_id=<item.pk>`

### 2.2 Unplanned Visits Entry Point
1. **Initiation**: Rep clicks the floating action `+` button in the navigation bar/drawer and chooses "تسجيل زيارة خارج الخطة".
2. **Direct Route**: Navigates directly to `/visits/create/` without `planned_item_id`.
3. **Behavior**:
   - The form initializes in unplanned mode.
   - Form ribbon and badges prominently display `زيارة خارج الخطة` (`bg-purple-50 text-purple-700`).
   - Any eligible customer and template can be selected.

---

## 3. Shared Controller & Business Logic (`activities/views.py`)

The unified view `visit_create` handles both GET and POST requests:

### 3.1 Server-Side Validation & Tamper Protection
- **Ownership Verification**: If `planned_item_id` is supplied in the query string or POST payload:
  ```python
  plan_item = PlannedVisitItem.objects.select_related('plan_day', 'contact', 'template').get(pk=planned_item_id)
  if not is_manager_or_super and plan_item.plan_day.assignee != request.user:
      messages.error(request, "غير مصرح لك بتسجيل أو تنفيذ خطة زيارة تابعة لمندوب آخر.")
      return redirect('visits_list')
  ```
- **Duplicate Execution Prevention**: If `plan_item.is_executed` is already true or `plan_item.visit` exists, the user is safely redirected to the existing visit without creating a duplicate record.
- **Classification Lock**: `visit.is_planned = bool(planned_item_id)`. Tampering with client-side flags cannot alter the classification.

### 3.2 Representative Assignment
- **Standard Users**: Always assigned as the visit owner (`request.user`).
- **Superusers & Managers**: Allowed to reassign the visit to any active representative via `VisitForm.owner`.

### 3.3 Eligibility & Template Constraints
- Accounts are filtered by type (`clinic`, `pharmacy`, `hospital`, etc.).
- Visit templates are restricted to matching account types unless configured for `all`.
- Verification policies (GPS distance, device accuracy, photo requirements) are enforced uniformly.

### 3.4 Creation Before Answering
- In accordance with the system lifecycle, the visit record is created first.
- If linked to a planned item, `plan_item.is_executed = True` and `plan_item.visit = visit` are saved atomically in a database transaction.
- The user is immediately redirected to `/visits/<id>/` where questionnaire answers, detailing metrics, and checkout can proceed.

---

## 4. UI Indicators on Creation Form (`templates/activities/visit_form.html`)

- **Planned Visit Banner**:
  - Displays a blue badge `زيارة مخططة`.
  - Informs the user of the scheduled plan date and target account.
  - Automatically locks the customer selection to the planned account.
- **Unplanned Visit Banner**:
  - Displays a purple badge `زيارة خارج الخطة`.
  - Informs the user that this is an ad-hoc visit.
- **Customer Selector**:
  - Client names are rendered without codes (e.g. `صيدلية النور` instead of `[PH001] صيدلية النور`).
  - Search by code is supported internally while displaying only clean customer names.
- **Streamlined Workflow**:
  - Duplicate questions (`هل كان يوم ناجح ؟`) and obsolete sample distribution inputs (`توزيع عينة طبية`) are completely omitted from the active form.
