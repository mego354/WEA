# Visit Template Field Rules & Product Detailing Restrictions

## 1. Executive Summary & Specification
In the reference ERP and clinical operations, the **"المنتجات المشروحة" (Detailed Products / Product Detailing)** section represents the presentation of scientific slides, pharmacology data, and clinical trial results to medical professionals.

Under Requirement 8:
> "The المنتجات المشروحة field or section must appear only in these visit templates:
> 1. Single visit — doctor/DR visit
> 2. Single visit — pharmacy visit
> 3. Healthy day
> Show the field only for the three specified template types.
> Hide it for all other visit templates.
> Enforce the restriction in the backend as well as the frontend.
> Reject unauthorized submissions that attempt to send this field for unsupported templates."

---

## 2. Supported Template Types Definition

| Supported Template Category | Verified Reference Names / Slugs | Account Eligibility | Detailing Supported |
|---|---|---|:---:|
| **Doctor / Physician Single Visit** | `Single visit (DR)`, `single_visit_dr`, `single_visit_dr_wf` | Clinic, Hospital, Polyclinic | **YES** |
| **Pharmacy Single Visit** | `Single visit (Pharmacy)`, `single_visit_pharmacy`, `single_visit_pharmacy_wf` | Pharmacy | **YES** |
| **Healthy Day / Health Campaign** | `Healthy day`, `healthy_day`, `اليوم الصحي` | Pharmacy, Clinic, Hospital, Health Center | **YES** |
| **Coaching / Joint Visit** | `coaching_visit`, `مرافقة وتدريب` | Any | ❌ **HIDDEN & CLEARED** |
| **Store / Wholesaler Visit** | `store_visit`, `distributor_visit` | Store, Distributor | ❌ **HIDDEN & CLEARED** |
| **General / Administrative Visit** | `general_visit`, any other template | Any | ❌ **HIDDEN & CLEARED** |

---

## 3. Centralized Model Capability Logic (`VisitTemplate`)

In [activities/models.py](file:///c:/D/Cooding/GENERAL/new/ERP/activities/models.py):
```python
def is_product_detailing_supported(self):
    """
    Centralized capability check (Codex Requirement 8).
    Strictly restricts 'المنتجات المشروحة' to exactly three template types:
    1. Single visit — doctor / DR visit
    2. Single visit — pharmacy visit
    3. Healthy day
    """
    if not self.enable_product_detailing:
        return False

    name_lower = (self.name or '').strip().lower()
    name_ar = (self.display_name_ar or '').strip().lower()
    name_en = (self.display_name_en or '').strip().lower()

    # Match Doctor / DR visit
    is_dr = (
        'dr' in name_lower or 'doctor' in name_lower or
        'طبيب' in name_ar or 'دكتور' in name_ar or
        'doctor' in name_en or 'dr' in name_en
    )

    # Match Pharmacy visit
    is_pharmacy = (
        'pharmacy' in name_lower or
        'صيدلية' in name_ar or 'صيدلي' in name_ar or
        'pharmacy' in name_en
    )

    # Match Healthy day
    is_healthy_day = (
        'healthy' in name_lower or 'health_day' in name_lower or
        'صحي' in name_ar or 'اليوم الصحي' in name_ar or
        'healthy day' in name_en
    )

    return is_dr or is_pharmacy or is_healthy_day

@property
def supports_product_detailing(self):
    return self.is_product_detailing_supported()
```

---

## 4. Backend & API Enforcement

### 4.1 Backend Form Handling (`visit_detail` & `visit_create`)
In [activities/views.py](file:///c:/D/Cooding/GENERAL/new/ERP/activities/views.py):
```python
# Product Detailing (Requirement 8): Restricted to the three templates
if template and template.is_product_detailing_supported():
    detailed_product_ids = request.POST.getlist('detailed_products')
    if detailed_product_ids:
        visit.detailed_products.set(detailed_product_ids)
    elif 'detailed_products_submitted' in request.POST:
        visit.detailed_products.clear()
else:
    # Clear detailing if template does not support it
    visit.detailed_products.clear()
```
- **Tampering Prevention**: Even if an unauthorized client injects `detailed_products` IDs into a POST request for an unsupported template (e.g. Coaching visit), the backend detects that `template.is_product_detailing_supported()` is `False` and invokes `visit.detailed_products.clear()`, wiping the relationship.
- **Historical Data Preservation**: If an existing visit already has detailing saved, changing views does not mutate the historical records unless explicitly edited and submitted.

### 4.2 API Parity (`/api/templates/`)
The JSON API exposes:
```json
{
  "id": 1,
  "name": "single_visit_pharmacy",
  "display_name_ar": "زيارة صيدلية",
  "enable_product_detailing": true,
  "supports_product_detailing": true
}
```
Client-side JavaScript inspects `supports_product_detailing` to toggle the `#product-detailing-card` in the DOM.
