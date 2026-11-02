# Role-Based Dashboard Content, Statistics, and Manager Scoping

## 1. Overview & Security Mandate
The main dashboard (`home_view` in `master_data/views.py`) serves as the central operational hub for executive management, finance, regional managers, and field representatives.

### Strict Authorization Rule
Dashboard visibility is enforced on the **backend**. Unauthorized metrics, cards, and chart datasets are **never** calculated or sent to the client browser and merely hidden with CSS or JavaScript.

---

## 2. Role Scopes Matrix

| Role | Operational Scope | KPI Cards Visible | Visualizations / Charts | Representative Selector |
| :--- | :--- | :--- | :--- | :--- |
| **SuperAdmin / CEO** | System-Wide (All Governorates & Reps) | 14 Cards: Full Sales, Returns, Net Sales, Collections, Cheques, Customer Balance, Overdue Debt, DSO, New Customers, Vault Totals, Vendor Balances, Lead Visits, Customer Visits | All 6 Charts: Collections by Area, Visits by Area, Orders Created, Orders Delivered, Reps Customer Balance, Reps Overdue Debt | Active (Can inspect all active sales reps) |
| **Accountant** | System-Wide Financials Only | 10 Financial Cards: Orders Created, Orders Delivered, Processing, Sales Returns, Accepted Returns, Net Sales, Collections, Cheques, Vaults Total, Vendors Total | 5 Financial Charts: Collections by Area, Orders Created by Area, Orders Delivered by Area, Reps Balance, Reps Overdue Debt. **Visits by Area is strictly omitted!** | None (Accountants inspect accounting registers) |
| **Area Manager** | Main Area & Subregions (e.g. Cairo) | 14 Cards: Scoped to manager's authorized team or selected representative | 6 Charts: Scoped to team or selected representative | Active (Can select reps whose main area matches the manager's main area) |
| **Sales Representative** | Own Operations Only | 5 Rep-Focused Cards: Rep Vault Balance, Rep Warehouse Stock Value, Net Sales, Collections, Visits | Up to 4 Operational Charts. **Reps Customer Balance and Reps Overdue Debt are strictly omitted** to preserve peer privacy | None (Representative inspects own operational pipeline) |

---

## 3. Manager Representative Selector & Backend Enforcement

### Eligibility Rule (Main Area Invariance)
Under regional ERP rules:
- An Area Manager manages representatives who share the **same root main area** (governorate), regardless of whether individual sub-areas differ.
- The manager's eligible reps list is generated via:
  ```python
  eligible_reps = list(get_user_managed_representatives(user).filter(
      is_active=True
  ).exclude(id=user.id).select_related('role').order_by('name'))
  ```

### Anti-Tampering & Horizontal Privilege Escalation Protection
When a `rep_id` query parameter is submitted (`/home/?rep_id=123`):
1. The backend resolves the requested target user.
2. The backend enforces `is_manager_eligible_for_user(request.user, target_user)`.
3. If the representative belongs to a different main area (e.g. Alexandria manager attempting to query a Cairo rep):
   - Access is **immediately denied**.
   - The selection safely reverts to `selected_rep = None` (team scope).
   - A security warning message is displayed: `"لا تملك صلاحية استعراض بيانات هذا المندوب، تم الرجوع لإحصائيات الفريق."`
4. When authorized:
   - All KPI metric queries (orders, collections, visits, vaults, stock) filter specifically by `target_user`.
   - The active filter banner informs the manager: `"يتم الآن استعراض إحصائيات المندوب: [الاسم] ([الدور])"`.
   - A single-click return button `"العودة لإحصائيات الفريق كامل"` resets the view to team-level aggregates without page reloads or adding redundant tabs.
