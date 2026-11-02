# Enterprise ERP Security Specification

> **System**: Enterprise ERP  
> **Framework**: Django 5.x / Python 3.13  
> **Security Baseline**: OWASP Top 10 Enterprise ERP Security Standards

---

## 1. Authentication & Session Security

1. **Password Policies**:
   - Strict password hashing using Django's default PBKDF2 with SHA256 (600,000+ iterations) or Argon2.
   - Minimum 8 characters, requiring mixed alphanumeric characters.
2. **Session Hardening**:
   - `SESSION_COOKIE_HTTPONLY = True` (Prevents XSS session extraction).
   - `SESSION_COOKIE_SAMESITE = 'Lax'`.
   - `SESSION_COOKIE_AGE = 28800` (8 hours standard workday timeout).
   - `CSRF_COOKIE_HTTPONLY = False` (Accessible to AJAX headers), `CSRF_COOKIE_SAMESITE = 'Lax'`.
3. **Protection Against Brute Force**:
   - Rate limiting on `/auth/login` endpoint to block automated credential attacks.

---

## 2. Authorization & Data Isolation (RBAC / ABAC)

1. **Role Enforcement**:
   - Every view is protected via `LoginRequiredMixin` and custom `PermissionRequiredMixin`.
   - Permissions are checked on both UI display (template rendering) and backend view execution.
2. **Horizontal Privilege Escalation Prevention (Multi-Tenant & Area Scoping)**:
   - Field sales reps cannot view or query contacts, orders, or stocks outside their assigned territory (`Area`).
   - QuerySets are automatically filtered at the manager/selector level:
     ```python
     def get_queryset(self):
         qs = super().get_queryset()
         if not self.request.user.role.is_system_admin:
             qs = qs.filter(area__in=self.request.user.assigned_areas.all())
         return qs
     ```
3. **Financial Segregation of Duties**:
   - Purchasing clerks can create purchase orders but cannot settle invoices to the vendor ledger.
   - Only users with `can_manage_vendor_accounting` or `can_invoice_purchase_order` can commit financial transactions.

---

## 3. Financial & Transactional Integrity

1. **Atomic Database Transactions**:
   - Every multi-step workflow (e.g. Stocking a Purchase Order, which increments inventory, generates a memo, and posts an accounting ledger entry) is wrapped in `@transaction.atomic`.
   - If any step fails (e.g. negative stock validation or ledger failure), the entire operation rolls back.
2. **Immutability of Financial Ledgers**:
   - `VendorTransaction` records cannot be updated or deleted directly.
   - Adjustments must be performed through offsetting reversal entries (`reversal` / `credit note` / `undoInvoice`).
3. **Audit Logging**:
   - Every transactional model includes `created_by`, `created_at`, `updated_by`, and `updated_at`.
   - High-impact events (approvals, status changes, manual ledger entries) record audit log entries with user ID, IP address, and previous state.

---

## 4. Input Validation & Protection

1. **SQL Injection**:
   - 100% parameterization via Django ORM. Raw SQL queries are prohibited.
2. **Cross-Site Scripting (XSS)**:
   - Django template auto-escaping enabled by default. User input rendered safely.
3. **Cross-Site Request Forgery (CSRF)**:
   - All state-changing `POST`, `PUT`, and `DELETE` requests require valid `csrf_token`.
4. **File Upload Security**:
   - Attachments (supplier invoices, receipts) validate file extensions (`.jpg`, `.jpeg`, `.png`, `.pdf`) and MIME types. Executable extensions (`.exe`, `.sh`, `.py`, `.php`, `.js`) are strictly rejected.
