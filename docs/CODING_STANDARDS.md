# Coding Standards & Guidelines

This document establishes the mandatory software engineering standards, patterns, and security practices for WEA Pharma ERP.

---

## 1. Architectural Patterns & Layering

```text
[ View Layer ] (app/views.py)
  - Handle HTTP requests, parsing GET/POST parameters
  - Enforce permissions (@require_permission)
  - Scope querysets (get_scoped_queryset)
  - Delegate mutations to Service Layer
  - Return HTTP response / JSON / Render template

[ Service Layer ] (app/services.py)
  - Encapsulate business invariants & domain logic
  - Multi-table writes wrapped in @transaction.atomic
  - Concurrency locking with select_for_update()
  - Emit SecurityAuditLog and ApprovalAuditLog records

[ Persistence Layer ] (app/models.py)
  - Database schema definitions, ForeignKeys, indexes
  - Model properties, string representations (__str__)
  - Zero cross-app business mutations in save() methods
```

---

## 2. Security & Data Isolation Standards

1. **Insecure Direct Object Reference (IDOR) Prevention**:
   - Never query models by `pk` globally without scoping:
     ```python
     # INCORRECT (Vulnerable to IDOR)
     order = get_object_or_404(SalesOrder, pk=pk)

     # CORRECT (Strictly Scoped)
     scoped_orders = get_scoped_queryset(SalesOrder.objects.all(), request.user, 'salesorder')
     order = get_object_or_404(scoped_orders, pk=pk)
     ```
2. **Access Control**:
   - Every view must enforce action permissions via `@require_permission('module:entity/action')`.
   - Every mutation must verify object authorization with `can_user_access_object(request.user, obj, action)`.
3. **Anti-Self-Approval**:
   - Workflows must programmatically reject self-approval:
     ```python
     if obj.created_by == request.user and not request.user.is_superuser:
         raise PermissionDenied("لا يمكن للمستخدم اعتماد طلبه الخاص.")
     ```
4. **Input Validation**:
   - Always validate numbers (e.g. positive quantities, 0-100% discount limits, non-negative shipping).
   - Never trust frontend role or scope parameters.

---

## 3. Database & Concurrency Guidelines

1. **Atomic Transactions**:
   - All state transitions and multi-record writes must be decorated with `@transaction.atomic`.
2. **Row Locking (`select_for_update`)**:
   - Financial ledger postings, cash vault debits/credits, and inventory stock deductions must acquire row-level locks using `select_for_update()` to prevent race conditions:
     ```python
     stock = InventoryStock.objects.select_for_update().get(warehouse=wh, product=prod)
     ```
3. **N+1 Query Prevention**:
   - Every list view must optimize querysets using `select_related` for ForeignKeys and `prefetch_related` for ManyToMany relationships:
     ```python
     queryset = queryset.select_related('customer', 'source_warehouse', 'created_by').prefetch_related('items__product')
     ```

---

## 4. Code Cleanliness & Maintenance

1. **No Unused Imports**: Keep imports organized (Standard library → Django → Third-party → Local app).
2. **No Duplicate URL Names**: URL names must be unique across the project to ensure unambiguous `reverse()` lookups.
3. **No Swallowed Exceptions**: Never use bare `except:` or empty `pass` blocks. Log errors with Python's `logging` module or surface user-friendly validation errors.
4. **Preserve Documentation Integrity**: When modifying business rules, models, or permissions, update the authoritative documentation in `docs/` simultaneously.

