# Visit Template Data Model & Schema (هيكل ونموذج بيانات قوالب الزيارات)

> **Module**: `activities`  
> **Target Models**: `VisitTemplate`, `VisitTemplateQuestion`, `Visit`, `PlannedVisitItem`

---

## 1. Entity Relationship Diagram (ERD)

```mermaid
erDiagram
    VisitTemplate ||--o{ VisitTemplateQuestion : "has questions"
    VisitTemplate ||--o{ Visit : "used in"
    VisitTemplate ||--o{ PlannedVisitItem : "assigned to"
    VisitTemplate }o--o{ Role : "restricted to"
    Visit ||--o{ Product : "detailed products"
    Visit ||--o{ VisitSampleItem : "samples"
    Visit ||--o{ VisitExpense : "expenses"

    VisitTemplate {
        int id PK
        string name UK
        string display_name_ar
        string display_name_en
        boolean active
        string mode
        boolean allow_unplanned
        boolean auto_approve_unplanned
        boolean enable_product_detailing
        boolean enable_double_visit_assessment_only
        string visit_outcome_mode
        boolean auto_end_visit
        boolean has_special_location_settings
        int special_tolerance
        json restrict_account_types
        json customer_classifications
        json specialties
    }

    VisitTemplateQuestion {
        int id PK
        int template_id FK
        string text_ar
        string text_en
        string question_type
        json options
        boolean is_required
        boolean is_conditional
        int conditional_parent_id FK
        string conditional_trigger_value
        string stage
        int order
        boolean is_active
    }

    Visit {
        int id PK
        int serial_num UK
        int contact_id FK
        int template_id FK
        int owner_id FK
        boolean is_planned
        string status
        string approval_status
        boolean is_successful
        boolean doubled
        json questionnaire_answers
        datetime started_at
        datetime ended_at
        int duration
    }
```

---

## 2. Field Specifications

### `VisitTemplate` Model Attributes
| Field | Type | Description |
|---|---|---|
| `name` | `CharField(100, unique=True)` | Internal slug / code identifier |
| `display_name_ar` | `CharField(150)` | Arabic display title |
| `display_name_en` | `CharField(150)` | English display title |
| `active` | `BooleanField(default=True)` | Active status switch |
| `mode` | `CharField(50, default='checkin_checkout')` | Mode (`checkin_checkout`, `normal`) |
| `allow_unplanned` | `BooleanField(default=True)` | Enable unplanned visits |
| `auto_approve_unplanned` | `BooleanField(default=True)` | Auto-approval for unplanned visits |
| `enable_product_detailing`| `BooleanField(default=True)` | Render product detailing section |
| `enable_double_visit_assessment_only` | `BooleanField(default=False)` | Assessment double visit toggle |
| `visit_outcome_mode` | `CharField(50, default='enabled_auto_approve_unsuccessful')` | Outcome mode |
| `auto_end_visit` | `BooleanField(default=False)` | Auto-end visit toggle |
| `has_special_location_settings` | `BooleanField(default=False)` | Special GPS settings toggle |
| `special_tolerance` | `PositiveIntegerField(default=300)` | Special GPS radius in meters |
| `restricted_roles` | `ManyToManyField(Role)` | Role constraints |
| `restrict_account_types` | `JSONField(default=list)` | Target account types (Clinic, Pharmacy, etc.) |
| `customer_classifications` | `JSONField(default=list)` | Target customer tiers |
| `specialties` | `JSONField(default=list)` | Target specialties |

### `VisitTemplateQuestion` Model Attributes
| Field | Type | Description |
|---|---|---|
| `template` | `ForeignKey(VisitTemplate, on_delete=CASCADE)` | Parent template |
| `text_ar` | `CharField(255)` | Question title (Arabic) |
| `text_en` | `CharField(255, blank=True)` | Question title (English) |
| `question_type` | `CharField(50, choices=...)` | `single_choice`, `multiple_choice`, `text`, `textarea`, `number`, `date`, `rating` |
| `options` | `JSONField(default=list)` | Options list: `[{'text_ar': ..., 'text_en': ..., 'value': ...}]` |
| `is_required` | `BooleanField(default=True)` | Mandatory validation flag |
| `is_conditional` | `BooleanField(default=False)` | Conditional display flag |
| `conditional_parent` | `ForeignKey('self', null=True)` | Triggering question |
| `conditional_trigger_value` | `CharField(255, blank=True)` | Value triggering visibility |
| `stage` | `CharField(50, default='all')` | `all`, `start_only`, `end_only` |
| `order` | `PositiveIntegerField(default=1)` | Display order index |
| `is_active` | `BooleanField(default=True)` | Active question switch |

### `Visit` Model Updates
- `detailed_products`: `ManyToManyField('catalog.Product', blank=True, related_name='detailed_in_visits')`
- `questionnaire_answers`: `JSONField(default=dict, blank=True)` (Stores question answers by question ID or title).
- `visit_outcome`: `CharField(max_length=50, blank=True, default='')`
