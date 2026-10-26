# Visit Product Eligibility & Configurable Suggestions Verification

## 1. Overview and Core Requirements

In accordance with enterprise ERP business rules:
1. **Sellable Only Selection**: Products not intended for sale (`sellable=False` or `is_active=False`) must **never** be selectable for new visit-related operations (visit creation, editing, product detailing, or template suggestions).
2. **Configurable Product Suggestions**: Field representatives benefit from suggested product highlights during customer detailing. These suggestions must be centrally configurable via:
   - **Global Level**: `/settings/location/` (under "المنتجات المقترحة للزيارات الميدانية").
   - **Template Level**: `/settings/visits/templates/<id>/edit/` (for template-specific promotional focus).
   - Only eligible, active, sellable products can be selected as suggestions.
3. **Historical Data Preservation**: If an existing visit historically detailed a product that is subsequently deactivated or marked non-sellable (`sellable=False`), the historical record remains intact and visible on the visit detail page without data loss or integrity violations.

---

## 2. Technical Architecture & Implementation

### A. Authoritative Model Filtering (`catalog/models.py`)
A centralized class method was implemented on `Product`:
```python
@classmethod
def get_eligible_for_visits(cls):
    """
    Returns products eligible for visit operations: active and intended for sale.
    Excludes non-sellable promotional items, samples, or inactive lines.
    """
    return cls.objects.filter(is_active=True, sellable=True).order_by('name')
```

### B. Global & Template Suggestion Settings
- **`LocationSettings` (`master_data/models.py`)**:
  - `enable_product_suggestions`: Boolean toggle to enable/disable product recommendation cards.
  - `suggested_products`: `ManyToManyField('catalog.Product', limit_choices_to={'is_active': True, 'sellable': True})`.
  - `get_eligible_suggested_products()`: Helper filtering to active, sellable suggestions.
- **`VisitTemplate` (`activities/models.py`)**:
  - `suggested_products`: `ManyToManyField('catalog.Product', limit_choices_to={'is_active': True, 'sellable': True})`.
  - `get_eligible_suggested_products()`: Template-specific helper filtering.

### C. Server-Side Enforcement in Views & Forms (`activities/views.py`, `master_data/views.py`)
- **`visit_create` & `visit_edit`**:
  - Validates `detailed_products` against `Product.get_eligible_for_visits()`.
  - Unsellable product IDs submitted maliciously or erroneously are discarded on the server.
- **`visit_detail`**:
  - Collects `suggested_product_ids` from template suggestions and global settings.
  - Generates the allowed product list: `Product.get_eligible_for_visits() | historical_ids`.
  - On submission of `detailed_products` / completion, allowed IDs = eligible IDs + historical IDs, guaranteeing historical integrity while forbidding new non-sellable attachments.
- **`location_settings_view`**:
  - Validates submitted product suggestions against `Product.get_eligible_for_visits()`.

### D. UI / UX Design (`templates/activities/visit_detail.html`, `templates/settings/location_settings.html`)
- Suggested products are styled with amber accent borders, subtle amber background rings, and a prominent badge:
  `★ مقترح (Suggested)`
- Selection controls have 44px min-height touch targets for comfortable mobile interaction.

---

## 3. Automated Test Verification

Full test coverage has been added to `activities/tests_user_workflows.py`:

| Test Name | Verification Focus | Result |
| :--- | :--- | :--- |
| `test_product_eligibility_in_visits` | Non-sellable & inactive products excluded from `get_eligible_for_visits()`, cannot be detailed on `visit_create` or `visit_detail`. | **PASSED** |
| `test_configurable_product_suggestions` | Settings UI saves suggestions, filters non-sellable, injects `suggested_product_ids` into `visit_detail` context. | **PASSED** |
| `test_historical_non_sellable_products_preserved` | Historical visit detailing preserved even after product is marked `sellable=False`. | **PASSED** |

Execution Command:
```bash
py manage.py test activities.tests_user_workflows
```
Result: **11/11 tests PASSED (0 failures, 0 errors)**.
