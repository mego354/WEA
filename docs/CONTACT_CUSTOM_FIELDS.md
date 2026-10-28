# Contact Custom Fields (User Defined Fields - UDF)

## 1. Executive Summary

The Contact User Defined Fields (UDF) subsystem enables system administrators to dynamically define, configure, and manage custom attributes for contacts without modifying the physical database schema. Custom fields seamlessly integrate into contact creation, contact editing, and the contact detail overview tab.

---

## 2. Architecture & Data Model

### `ContactFieldSetting` Model (`master_data/models.py`)

Defines the metadata and constraints for each custom field:

| Field | Type | Description |
|---|---|---|
| `field_key` | `SlugField(max_length=60, unique=True)` | Programmatic dictionary key stored in contact records. |
| `display_name` | `CharField(max_length=150)` | Arabic label shown in forms and detail pages. |
| `display_name_en` | `CharField(max_length=150, blank=True)` | English label. |
| `field_type` | `CharField(choices=FIELD_TYPE_CHOICES)` | Field data type (see Section 3). |
| `choices` | `JSONField(default=list, blank=True)` | List of selectable choices for single and multi-choice types. |
| `help_text` | `CharField(max_length=255, blank=True)` | Helper tooltip text displayed beneath input fields. |
| `section` | `CharField(choices=['basic', 'financial', 'operational'])` | Organizational category for form grouping. |
| `order` | `PositiveIntegerField(default=10)` | Display sort order. |
| `is_required` | `BooleanField(default=False)` | Enforces mandatory completion. |
| `is_active` | `BooleanField(default=True)` | Toggle to activate or deactivate without deleting history. |

### `Contact.custom_values` (`contacts/models.py`)

Each contact stores field values inside `custom_values = models.JSONField(default=dict, blank=True)`.
Example payload:
```json
{
  "license_number": "LIC-998877",
  "is_vip_customer": true,
  "annual_capacity": 500,
  "payment_terms_choice": "كاش",
  "preferred_days": ["السبت", "الثلاثاء"]
}
```

---

## 3. Supported Field Types

The system supports 7 distinct field types, each rendered with specialized controls:

1. **`text` (نص قصير):** Standard single-line text input (`<input type="text">`).
2. **`textarea` (نص متعدد الأسطر):** Multi-line textarea for notes, terms, or clinical comments.
3. **`number` (رقمي):** Numeric input (`<input type="number">`), automatically parsed to integer or float.
4. **`date` (تاريخ):** Date picker input (`<input type="date">`), formatted in `YYYY-MM-DD`.
5. **`boolean` (نعم / لا):** Modern toggle switch or checkbox. Saved as `True` / `False` and displayed as `نعم` / `لا`.
6. **`single_choice` (اختيار من متعدد - فردي):** Dropdown select or radio list based on configured choices.
7. **`multi_choice` (اختيارات متعددة):** Multi-select checkbox group; stored as a list of strings.

---

## 4. Settings Management Interface (`/settings/contacts-udf/`)

Located at `/settings/contacts-udf/` (`templates/settings/contacts_udf.html`):
- **Field Creation & Editing Modal:** Enables specifying name, key, field type, order, section, and help text.
- **Dynamic Choice Editor:** Real-time tag input allowing administrators to add, order, and remove choices for choice-based fields.
- **Deactivation & Deletion:** Safe deletion or deactivation with audit trail (`AuditLogService.log(module='custom_fields', ...)`).
- **Security:** Restricted to users with `settings:contactsUdf/manage` permission.

---

## 5. Contact Form & Detail Page Integration

1. **Extraction Utility (`contacts/views.py`):**
   `extract_custom_values_from_post(request, active_settings)` automatically sanitizes POST data prefixed with `custom_`:
   - Checkbox presence translates to `True`, absence to `False`.
   - Numeric fields are cast to valid numbers.
   - Multiselect fields are accumulated into lists.
2. **Form Rendering (`contact_create.html` & `contact_edit.html`):**
   Iterates through active field settings, prefilling existing values on edit.
3. **Overview Display (`contact_detail.html`):**
   Rendered in the Overview tab under the dedicated "الحقول المخصصة" accordion card:
   - Formatted badges for booleans (`نعم` in green, `لا` in slate).
   - Clean definition lists with Arabic labels.

---

## 6. Automated Test Coverage

Unit tests in `contacts/tests_udf_todos_timeline.py`:
- `test_contact_custom_fields_in_detail_view`: Confirms context formatting and boolean display values.
- `test_contact_create_with_custom_fields`: Confirms correct JSON parsing on creation.
- `test_contact_edit_with_custom_fields`: Confirms update handling and audit logging.
