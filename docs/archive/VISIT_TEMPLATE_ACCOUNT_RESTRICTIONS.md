# Visit Template Account-Type Restrictions Specification

## 1. Overview & Business Objectives
In the pharmaceutical ERP (`Bricks Rep`), field medical representatives conduct distinct visit workflows depending on the customer's account category. For example:
- A **Pharmacy Visit** focuses on stock audits, availability checks, order collection, and pharmacist detailing.
- A **Clinic/Hospital (Doctor) Visit** focuses on scientific product presentation, medical inquiries, feedback on clinical efficacy, and physician detailing.
- A **Healthy Day** or **Public Health Event** involves screening, patient education, and broad OTC/supplement sampling across clinics, pharmacies, and health centers.

Allowing an incompatible template to be assigned to an account (e.g. attempting to run a pharmacy stock audit template on a private surgical clinic) leads to invalid metrics, representative confusion, and reporting failures.

This document outlines the architecture, database schema, normalization, backend validation, API parity, and frontend filtering governing Visit Template Account-Type Restrictions.

---

## 2. Root Cause Analysis of Pre-existing Defects
During forensic audit of the previous implementation, three primary defects were identified:
1. **Case-Sensitivity Mismatch in Account Type Values**:
   - `Contact.account_type` stored values in canonical Title-Case format (e.g. `Pharmacy`, `Clinic`, `Hospital`, `Store`, `Center`).
   - `VisitTemplateForm` defined `ACCOUNT_TYPE_CHOICES` using all-lowercase keys (e.g. `pharmacy`, `clinic`, `hospital`).
   - Consequently, when opening an existing template in `/settings/visits/templates/<id>/edit/`, Django's `CheckboxSelectMultiple` failed to match `['Pharmacy']` with `pharmacy`, causing all checkboxes to appear unchecked on edit and clearing restrictions upon saving.
2. **Missing Server-Side Enforcement on Creation Paths**:
   - While client-side JavaScript filtered template options in the dropdown, direct POST submissions, API calls, and planned visit execution routes bypassed eligibility checks, allowing users to attach any template to any contact.
3. **Inconsistent Case Normalization Across Model & APIs**:
   - APIs and forms did not normalize casing, leading to divergence between `restrict_account_types=['Pharmacy']` and `contact.account_type='pharmacy'`.

---

## 3. Database Schema & Data Normalization

### 3.1 Model Definition (`VisitTemplate`)
In [activities/models.py](file:///c:/D/Cooding/GENERAL/new/ERP/activities/models.py), the `VisitTemplate` model defines:
```python
class VisitTemplate(models.Model):
    name = models.CharField(max_length=100, unique=True)
    display_name_ar = models.CharField(max_length=255)
    display_name_en = models.CharField(max_length=255, blank=True)
    mode = models.CharField(max_length=30, choices=TEMPLATE_MODE_CHOICES, default='normal')
    restrict_account_types = models.JSONField(
        default=list,
        blank=True,
        help_text="قائمة بأنواع الحسابات المصرح لها باستخدام هذا القالب (e.g. ['Pharmacy', 'Clinic'])"
    )
    ...
```

### 3.2 Canonical Account Types Mapping
The system standardizes on canonical Title-Case names matching `Contact.account_type`:
| Canonical Key | Arabic Display | Description |
|---|---|---|
| `Pharmacy` | صيدلية (Pharmacy) | Retail community & hospital pharmacies |
| `Clinic` | عيادة (Clinic) | Private physician practices & outpatient clinics |
| `Hospital` | مستشفى (Hospital) | Inpatient and specialized hospital centers |
| `Polyclinic` | مجمع عيادات (Polyclinic) | Multi-specialty medical centers |
| `Center` | مركز طبي (Medical Center) | Diagnostic and specialty health centers |
| `Health Unit` | وحدة صحية (Health Unit) | Primary care public health units |
| `Dispensary` | مستوصف (Dispensary) | Local dispensaries and clinics |
| `Distributor` | موزع (Distributor) | Regional supply distributors |
| `Store` | مخزن أدوية (Store) | Pharmaceutical storage depots |
| `Physician` | طبيب (Physician) | Individual physician accounts |
| `Pharmacist` | صيدلي (Pharmacist) | Professional pharmacist accounts |
| `Organization` | مؤسسة (Organization) | Healthcare syndicates, ministries, NGOs |
| `Others` | أخرى (Others) | Non-standard accounts |

### 3.3 Eligibility Evaluation Methods
Centralized on the model to guarantee DRY principles:
```python
def is_account_type_eligible(self, account_type_or_contact):
    """
    Check if a given account type or contact instance is eligible for this template.
    If restrict_account_types is empty, all account types are permitted.
    Comparison is strictly case-insensitive and whitespace-trimmed.
    """
    if not self.restrict_account_types:
        return True
    
    if hasattr(account_type_or_contact, 'account_type'):
        val = account_type_or_contact.account_type
    else:
        val = str(account_type_or_contact)
        
    normalized = str(val or '').strip().lower()
    target_types = [str(t).strip().lower() for t in self.restrict_account_types]
    return normalized in target_types

def is_contact_eligible(self, contact):
    """Convenience helper taking a Contact model instance."""
    if not contact:
        return True
    return self.is_account_type_eligible(contact)
```

---

## 4. Backend Form Validation & Security Enforcement

### 4.1 Form Cleaning (`VisitForm.clean()`)
In [activities/forms.py](file:///c:/D/Cooding/GENERAL/new/ERP/activities/forms.py):
```python
contact = cleaned_data.get('contact')
template = cleaned_data.get('template')
if contact and template:
    if not template.is_contact_eligible(contact):
        allowed_str = ", ".join(template.restrict_account_types) if template.restrict_account_types else "الكل"
        raise forms.ValidationError(
            f"قالب الزيارة '{template.display_name_ar}' غير مخصص لنوع حساب العميل ({contact.account_type or 'غير محدد'}). الأنواع المصرح بها: {allowed_str}."
        )
```

### 4.2 API Parity (`/api/templates/`)
Endpoint `visit_templates_api` in [activities/views.py](file:///c:/D/Cooding/GENERAL/new/ERP/activities/views.py) supports filtering:
- Querying `/api/templates/?contact_id=123` dynamically returns only templates eligible for that contact's account type.
- Exposes `restrict_account_types` array, `supports_product_detailing` boolean, and active question schemas.

---

## 5. UI Integration & Mobile Behavior
- **Template Selector on Create Screen (`/visits/create/`)**:
  - Automatically filters options when a customer is selected.
  - If a template is chosen first, the customer typeahead searches exclusively for eligible account categories.
  - Ineligible choices are disabled and hidden with clear fallback indicators.
- **Settings Screen (`/settings/visits/templates/<id>/edit/`)**:
  - Restores all checked account types on reload.
  - Provides dual-column responsive touch checkboxes for mobile and desktop screens.
