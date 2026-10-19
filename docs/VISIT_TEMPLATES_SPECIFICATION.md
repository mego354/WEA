# Visit Templates Specification (مواصفات قوالب الزيارات)

> **System**: WEA Pharma ERP (Bricks Rep Architecture)  
> **Reference Route**: `/settings/visits/templates`  
> **Inspection Date**: October 2026  
> **Safety Status**: 100% Read-only verification on Reference ERP; all mutations local.

---

## 1. Overview & Architecture

Visit Templates (`قوالب الزيارات`) are the configurable core of field activity reporting in the ERP. They govern:
1. **Visit Modes**: Single-stage vs Checkin/Checkout lifecycle.
2. **Applicability Rules**: Which representatives (roles) and customer categories (Clinics, Pharmacies, Hospitals, Stores, Distributors) can use the template.
3. **Questionnaires**: Structured questions presented to the representative during check-in or visit completion.
4. **Product Detailing (`المنتجات المشروحة`)**: Whether medical representatives detail pharmaceutical products during the visit.
5. **Visit Outcomes (`نتيجة الزيارة`)**: Tracking whether the visit was successful or unsuccessful with automatic approval rules.
6. **Location Validation Overrides**: Specialized geofence tolerance overrides per template type.

---

## 2. Reference ERP Template Inventory (All 6 Standard Templates)

| # | Template Name (en) | Display Name (ar) | Target Accounts | Mode | Product Detailing | Key Questions & Fields |
|---|---|---|---|---|---|---|
| **1** | `Single visit (DR)` | `Single visit (DR)` | Clinic, Hospital, Health Unit, Dispensary, Polyclinic, Center | Checkin/Checkout | Yes (Active) | 1. `? Did you meet the Dr` (Radio: Yes/No)<br>2. `? What happened int he visit` (Conditional: Yes)<br>3. `? Reason for not visiting` (Conditional: No)<br>4. `Dr need` (Conditional: Yes) |
| **2** | `Single visit (Pharmacy)` | `Single visit (Pharmacy)` | Pharmacy | Checkin/Checkout | Yes (Active) | 1. `Feedback about all products` (Yes/No)<br>2. `Accurate feedback ( Dr & Prdouct & Rate )` (Yes/No)<br>3. `Competitors feedback` (Yes/No) |
| **3** | `Coaching visit (DR)` | `Coaching visit (DR)` | Clinic, Hospital | Checkin/Checkout (Doubled) | Yes (Active) | 1. `? Did you meet the Dr` (Yes/No)<br>2. `Set an objective for the visit` (Start only ▶)<br>3. `Evaluation / Feedback` (Textarea) |
| **4** | `Coaching visit (Pharmacy)` | `Coaching visit (Pharmacy)` | Pharmacy | Checkin/Checkout (Doubled) | Yes (Active) | 1. `Feedback about all products` (Yes/No)<br>2. `Accurate feedback ( Dr & Prdouct & Rate )` (Yes/No)<br>3. `Competitors feedback` (Yes/No) |
| **5** | `Store & Distributor visit` | `Store & Distributor visit` | Store, Distributor | Checkin/Checkout | No | 1. `Stock check` (Yes/No)<br>2. `Collection / Order details` (Textarea) |
| **6** | `Healthy day` | `Healthy day` | All Accounts | Checkin/Checkout | No | 1. `هل كان يوم ناجح ؟` (Yes/No, Start only ▶)<br>2. `ما هى نتائج اليوم ( روشتات & بيع ) ؟` (Textarea) |

---

## 3. Template Configuration & Form Fields

### A. General Information
- `name`: Internal unique system identifier (slug/code).
- `display_name_en`: Display name in English (Required).
- `display_name_ar`: Display name in Arabic (Required).
- `active`: Boolean switch (`مفعل`).

### B. Settings Accordion (`الإعدادات`)
- `mode`: Dropdown (`Checkin and Checkout` or `Normal`).
- `allow_unplanned`: Switch (`تفعيل تسجيل زيارات خارج خطة الزيارات`) - allows using this template in unplanned visits.
- `auto_approve_unplanned`: Switch (`موافقة تلقائية للزيارات المنشأة خارج خطة الزيارات`) - automatically approves visits logged outside plan.
- `enable_product_detailing`: Switch (`تفعيل شرح المنتجات`) - renders the pharmaceutical product detailing selector in the visit form.
- `enable_double_visit_assessment_only`: Switch (`تفعيل التقييمات للزيارات المزدوجة فقط`).
- `visit_outcome_mode`: Dropdown (`معطل` / `Enabled, auto approve unsuccessful` / `Enabled`).
- `auto_end_visit`: Switch (`إنهاء الزيارة تلقائياً`).

### C. Location Verification Accordion (`التحقق من الموقع`)
- `has_special_location_settings`: Switch (`اعدادات خاصة للتحقق من الموقع`).
- `special_tolerance`: Custom geofence tolerance radius in meters (e.g. 500m).

### D. Constraints Accordion (`القيود`)
- `restricted_roles`: Multiselect for user roles allowed to select this template.
- `business_relationship`: Filter for contact business relationship.
- `contact_type`: Filter for contact types.
- `account_types`: Multiselect for contact account types (`Clinic`, `Pharmacy`, `Hospital`, `Center`, `Store`, `Distributor`).
- `customer_classifications`: Filter for customer tiers (`A`, `B`, `C`).
- `specialties`: Multiselect for medical specialties (`Gynaecology`, `Pediatrics`, `Cardiology`, etc.).
- `customer_status`: Customer status filter.

### E. Question Builder (`استبيان الزيارة`)
Each question contains:
- `text_ar`: Question title in Arabic (Required).
- `text_en`: Question title in English (Required).
- `question_type`: Single choice (`اختيار واحد من متعدد`), Multiple choice (`اختيار متعدد`), Short text (`نص قصير`), Long text (`نص طويل`), Number (`رقم`), Date (`تاريخ`), Rating (`تقييم`).
- `options`: List of `{text_ar, text_en, value}` for choice types.
- `is_required`: Boolean switch (`مطلوب`).
- `is_conditional`: Boolean switch (`مشروط 👁`).
- `conditional_parent`: Parent question selector.
- `conditional_trigger_value`: Parent value that triggers visibility (e.g. `Yes`).
- `stage`: Lifecycle stage when question is answered:
  - `all`: Throughout visit lifecycle.
  - `start_only`: Check-in / Start visit only (`البدء فقط ▶`).
  - `end_only`: Check-out / Completion only (`الإنهاء فقط ■`).
- `order`: Numeric sort order.

---

## 4. Implementation & Testing Status

- **Status**: 100% Implemented & Verified.
- **Reference Parity**: Verified against `https://weapharma.bricks-rep.com/settings/visits/templates` with 0 online mutations.
- **Automated Tests**:
  - `activities/tests.py`: 35 tests, including `VisitTemplatesManagementTestCase` and `VisitTemplatesWorkflowIntegrationTestCase`.
  - Full ERP test suite: 117 tests passing with 0 errors and 0 failures.
- **Responsive & Mobile Viewports**: Verified at 375px, 390px, 430px, and desktop with zero horizontal overflow and full RTL alignment.

