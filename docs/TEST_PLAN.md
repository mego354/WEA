# Comprehensive ERP QA & Test Plan

> **System**: Enterprise ERP  
> **Testing Scope**: Functional Workflows, Mathematical Precision, Security Boundaries, and UI Regression.

---

## 1. Testing Strategy & Pyramid

1. **Unit Tests (Django `TestCase` / `pytest`)**:
   - Model validation rules.
   - Calculation engines (Tax, Line item discounts, Order discounts, Shipping fees).
   - Stock balance recalculation (Weighted average cost).
2. **Integration & Workflow Tests**:
   - End-to-end Purchase Order lifecycle: Draft $\rightarrow$ Approved $\rightarrow$ Picked (Warehouse memo generated & stock incremented) $\rightarrow$ Settled (Vendor ledger invoice posted) $\rightarrow$ Payment issued $\rightarrow$ Installment settled.
   - Reversal workflow: Undo invoice $\rightarrow$ verify ledger and balance restoration.
3. **Security & Permission Tests**:
   - Role enforcement (Purchasing clerk attempting to post accounting invoice).
   - Unauthorized API access (anonymous or non-privileged user).
   - Horizontal privilege testing (Area Manager attempting to access foreign territory).
4. **Browser & UI Verification (Playwright / Browser Subagent)**:
   - Visual verification of Arabic RTL layout, Cairo typography, and `#27bebe` teal styling.
   - Dynamic form interactions (adding/removing purchase line items, auto-calculating totals).
   - Modal drawer opening and closing.

---

## 2. Test Cases Matrix

| Test ID | Module | Scenario | Expected Outcome |
|---|---|---|---|
| **TC-AUTH-01** | Auth | Valid login credentials | User authenticated, redirected to `/home`, session initialized. |
| **TC-AUTH-02** | Auth | Invalid password | 401 error message, no session created, form re-rendered with error. |
| **TC-AUTH-03** | Auth | Unauthenticated access to `/purchase-orders` | Redirect to `/auth/login?next=/purchase-orders`. |
| **TC-CONT-01** | Contacts | Create new supplier contact | Contact created with relation `vendor`, vendor account initialized with 0 balance. |
| **TC-CONT-02** | Contacts | Filter contacts by `vendor` | Only contacts with `is_supplier=True` displayed in list. |
| **TC-PROD-01** | Catalog | Create product with SKU and Price | Product saved, searchable in purchase order item select. |
| **TC-PO-01** | Purchases | Draft purchase order creation | Order created with status `Pending`, financial calculations match line items. |
| **TC-PO-02** | Purchases | Financial calculation check | Grand Total = (Subtotal - Item Discounts - Order Discount) * Tax + Shipping. |
| **TC-PO-03** | Purchases | Order Approval | Status transitions to `Approved`, logged in audit history. |
| **TC-PO-04** | Purchases | Stock Receipt (`Picked`) | `InventoryMemo` created, `qty_on_hand` increased in target warehouse, batch & expiry stored. |
| **TC-PO-05** | Purchases | Invoicing (`Settled`) | `VendorTransaction` credit posted to supplier ledger, supplier balance increased, invoice installment created. |
| **TC-PO-06** | Purchases | Undo Invoicing | Reverts accounting transaction, restores supplier balance, order reverts to `Picked`. |
| **TC-PAY-01** | Treasury | Issue Vendor Payment | Vault balance deducted, supplier ledger debited, installment closed, balance updated. |
| **TC-PAY-02** | Treasury | Insufficient Vault Balance | Validation error raised preventing cash withdrawal beyond available balance. |
| **TC-PERM-01** | RBAC | Junior Clerk attempts invoice post | 403 Forbidden returned; action blocked. |
| **TC-UI-01** | UI | Responsive layout check | Sidebar collapses on mobile, table horizontal scrolls smoothly, cards stack cleanly. |

---

## 3. Automation Execution Commands

```bash
# Run all unit and integration tests
python manage.py test

# Run specific module test suites
python manage.py test accounts
python manage.py test contacts
python manage.py test purchases
python manage.py test treasury

# Run browser automated verification script
python tests/browser_verification.py
```
