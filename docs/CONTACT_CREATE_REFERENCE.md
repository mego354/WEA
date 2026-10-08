# Reference ERP Specification: Contacts → Create Page

> **Source of Truth**: `https://weapharma.bricks-rep.com/contacts/create`  
> **Inspection Mode**: Strictly Read-Only (Reverse Engineered via Playwright & DOM Analysis)  
> **Date**: October 2026

---

## 1. Page Header & Structure

- **Page Title**: `انشئ جهة اتصال` (Header text color: `#27bebe` Primary Teal, Font: Cairo, Weight: 700, Size: ~24px).
- **Layout Container**:
  - Max Width: `1024px` centered form container.
  - Direction: `RTL` (Right-to-Left).
  - Background: `#f8fafc` / `#ffffff` with subtle borders and shadows.
  - Spacing: Standard Angular Material / Tailwind spacing (`16px` to `24px` padding and margins).

---

## 2. Section 1: معلومات اساسية (Basic Information)

Section Heading: `معلومات اساسية` in `#27bebe` (Teal), font-size `16px`, font-weight `600`.

### Field 1.1: `النوع*` (Contact Type)
- **Position**: Row 1, Column 1 (Right in RTL).
- **Field Type**: Dropdown Select (`mat-select` with outline appearance).
- **Required**: Yes (`*`).
- **Options**:
  1. `مؤسسة` (Organization / Facility) — *Default*
  2. `شخص` (Individual / Person)
- **Validation**: Cannot be empty. Displays red outline and `هذا الحقل مطلوب` if touched and empty.

### Field 1.2: `علاقة العمل*` (Business Relation)
- **Position**: Row 1, Column 2 (Left in RTL).
- **Field Type**: Multi-select Dropdown (`mat-select` multiple with checkboxes).
- **Required**: Yes (`*`).
- **Options**:
  1. `عميل` (Customer)
  2. `مورد` (Supplier)
  3. `أخرى` (Other)
- **Conditional Trigger**:
  - When `عميل` is checked, the 3 **Customer Classification Fields** immediately appear below.

### Conditional Customer Fields (Visible when `علاقة العمل` contains `عميل`):
1. **`تصنيف العميل*` (Customer Category)**:
   - Type: Dropdown Select. Required.
   - Options: `A`, `B`, `C`, `D`, `E`.
2. **`التخصص*` (Specialty)**:
   - Type: Dropdown Select. Required.
   - Options (42 Medical Specialties):
     `Pediatrics`, `Dermatology`, `Nutritionist`, `Neurology`, `Family medicine`, `Psychiatry`, `Orthopedics`, `Oncology`, `General surgeon`, `Plastic surgeon`, `Hematology`, `Nephrology`, `Gynaecology`, `Physiotherapy`, `General practitioner`, `Internal medicine`, `Andrology`, `Ophthalmology`, `Rheumatologist`, `Cardiologist`, `Pulmonologist`, `ENT`, `Bariatricians`, `Pharmacist`, `Pulmonology`, `Urology`, `ER`, `Endocrinologist`, `Gastroenterologist`, `Dentist`, `Maxillofacial surgery`, `Obesity and laparoscopic surgery`, `Pain management`, `Vascular surgeon`, `Immunologist`, `Intensivists`, `Neurosurgeon`, `Neuropsychiatrist`, `Cardiothoracic`, `Surgical oncologist`, `Beauty specialist`, `N/A`.
3. **`نوع الاكونت*` (Account Type)**:
   - Type: Dropdown Select. Required.
   - Options (25 Facility Types):
     `Clinic`, `Hospital`, `Health Unit`, `Dispensary`, `Pharmacy`, `Drug Store`, `Polyclinic`, `Center`, `Distributor`, `Contract`, `Bank`, `Organization`, `Physician`, `Pharmacist`, `Medical Center`, `X-ray Lab`, `Medical instrument`, `Optics Center`, `Home care company`, `Nursing company`, `Ambulance service company`, `Analysis lab`, `Gym`, `Warehouse`, `Others`.

### Field 1.3: `الاسم*` (Contact Name)
- **Position**: Row 2 (Full Width, `100%`).
- **Field Type**: Text Input (`input[type="text"]`).
- **Required**: Yes (`*`).
- **Validation**: Cannot be empty. Displays `هذا الحقل مطلوب` if empty.

### Field 1.4: `الموبايل` (Mobile Number)
- **Position**: Row 3, Column 1.
- **Field Type**: Split input compound component:
  - Country flag & Dial code select (Default: `🇪🇬 +20` Egypt).
  - Tel input: Placeholder `أدخل رقم الهاتف`.

### Field 1.5: `التليفون` (Landline / Telephone)
- **Position**: Row 3, Column 2.
- **Field Type**: Split input compound component:
  - Country code select (Default: `🇪🇬 +20` Egypt).
  - Tel input: Placeholder `أدخل رقم الهاتف`.

---

## 3. Section 2: العناوين (Addresses)

Section Heading: `العناوين` in `#27bebe` (Teal), font-size `16px`, font-weight `600`.

### Address Card Container (`mat-card`)
A distinct white card with thin border (`#e2e8f0`), rounded corners (`12px`), and padding (`20px`).
- **Delete / Clear Button**: Icon button `close` (`X`) at top-left.

#### Field 2.1: `اسم العنوان` (Address Title / Label)
- Type: Text input. Optional.
- Examples: `المقر الرئيسي`, `مستودع 1`, `الفرع الرئيسي`.

#### Field 2.2: `المنطقة*` (Area / Governorate)
- Position: Grid 2 cols, Right.
- Type: Dropdown Select. Required (`*`).
- Options: 34 governorates/regions (`محافظة القاهرة`, `محافظة الجيزة`, `محافظة الاسكندرية`, etc.).

#### Field 2.3: `المنطقة الفرعية*` (Sub-Area / City / District)
- Position: Grid 2 cols, Left.
- Type: Dropdown Select. Required (`*`).
- Behavior: Disabled until `المنطقة` is selected. Automatically loads relevant districts (e.g. for Cairo: `مدينة نصر`, `المعادي`, `مصر الجديدة`, etc.).

#### Field 2.4: `العنوان` (Detailed Street Address)
- Position: Full Width.
- Type: Text input. Optional.

#### Field 2.5: `الموقع` (GPS Location Coordinates)
- Status: Text `غير مسجل` (Unregistered) in red `#ef4444`.
- Action Button: `حدد الموقع` (Set Location) button with map pin icon.
- Required banner: `هذا الحقل مطلوب` in light red banner `#fee2e2`.

#### Field 2.6: `تعيين كعنوان رئيسى` (Set as Main Address)
- Type: Checkbox (`mat-checkbox`).
- Default: Checked (`true`).

### Button: `أضف عنوان` (Add Another Address)
- Full width outlined button with icon `add`. Allows appending additional address cards.

---

## 4. Section 3: معلومات أخرى (Other Information) — Collapsible Accordion

Section Header: `معلومات أخرى` with expandable chevron arrow `keyboard_arrow_down`.

### Fields inside `معلومات أخرى`:
1. **`البريد الإلكتروني` (Email)**: Email input.
2. **`الموقع الإلكتروني` (Website)**: URL/text input.
3. **Buttons Row**:
   - `اضف طرق الاتصال` (Add Communication Methods: WhatsApp, Facebook, etc.).
   - `اضف جهات الاتصال المرتبطة` (Add Related Contacts / Key Persons).
4. **`المعرف الضريبي` (Tax ID)**: Text input.
5. **`الكود` (ERP / External Code)**: Text input.
6. **`ملاحظة` (Notes / Remarks)**: Text input / textarea.
7. **`اسم المسؤول` (Contact Person / Manager Name)**: Text input.
8. **`AM/PM` (Preferred Visit Timing)**: Dropdown select with options `AM`, `PM`.
9. **`المسمي الوظيفي` (Job Title)**: Text input.
10. **`KOL` (Key Opinion Leader)**: Dropdown select with options `نعم` (Yes), `لا` (No).

---

## 5. Form Footer & Actions

Located at bottom of page:
- **`حفظ` (Save Button)**:
  - Background: `#27bebe` Primary Teal (hover `#1fa8a8`), White text, rounded corners.
  - Behavior: Validates required fields (`النوع`, `علاقة العمل`, `الاسم`, `المنطقة`, `المنطقة الفرعية`, and customer fields if customer selected).
- **`الغاء` (Cancel Button)**:
  - Secondary background `#f1f5f9`, dark text, returns to `/contacts/`.

---

## 6. Visual Design Tokens & Specs

| Property | Value | Notes |
|---|---|---|
| **Font Family** | `Cairo, sans-serif` | Identical to reference ERP |
| **Primary Brand Color** | `#27bebe` (Teal) | Used for titles, primary buttons, focus rings |
| **Border Color** | `#e2e8f0` (Slate-200) | Outlined inputs |
| **Focus Ring** | `2px solid #27bebe` | Outline input focus |
| **Error Color** | `#dc2626` / `#ef4444` | Red borders & error banners |
| **Input Height** | `48px` - `52px` | Standard Material Outlined density |
| **Border Radius** | `8px` for inputs, `12px` for cards | Soft rounded aesthetics |
| **Direction** | `RTL` (Right-to-Left) | Full Arabic enterprise layout |
