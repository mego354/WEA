# Egypt Governorates & Geographic Areas Architecture

## 1. Executive Summary

The Areas Management subsystem (`/settings/areas/`) has been standardized to reflect the official **27 Egyptian Governorates** and their nested administrative sub-areas, while completely separating and preserving internal WEA company facilities and warehouses.

---

## 2. Problem Statement & Historical Context

Prior to this enhancement:
1. The areas settings page displayed internal WEA company branches and warehouse hubs (such as "WEA Main Branch", "فرع دمياط", "فرع القليوبية", "شركة WEA فارما") mixed with geographic governorates.
2. The list omitted several official Egyptian governorates.
3. Sub-area counts were calculated via unoptimized N+1 queries or were absent.
4. Hard-deleting the internal company branch records would have broken foreign-key relationships across existing contacts, warehouses, vaults, and sales orders.

---

## 3. Data Model Enhancements

In `master_data/models.py`, `Area` was extended:
- **`is_company_area`** (`BooleanField(default=False)`): Differentiates between physical administrative regions of Egypt and internal enterprise facilities.
- **`name_en`** (`CharField(max_length=150, blank=True)`): English romanized name for bilingual exports and API integrations.

Migration applied: `master_data.0007_area_is_company_area_area_name_en_and_more`.

---

## 4. Preservation of Company Facilities

Fourteen pre-existing records representing WEA corporate buildings, operational hubs, and branch warehouses (Area codes `29`, `30`, `31`, `99999999` and their children) were safely updated with `is_company_area=True`:
- **Referential Integrity:** Preserved 100% of links to `contacts_contact.area_id`, `inventory_warehouse.area_id`, and `treasury_vault.area_id`.
- **Visibility:** Excluded from the public geographic hierarchy on `/settings/areas/`.

---

## 5. The 27 Canonical Egyptian Governorates

The management command `setup_egypt_areas` (`master_data/management/commands/setup_egypt_areas.py`) populates and verifies the 27 official governorates:

| Code | Governorate Name (Arabic) | Governorate Name (English) |
|---|---|---|
| `01` | محافظة القاهرة | Cairo |
| `02` | محافظة الإسكندرية | Alexandria |
| `03` | محافظة الجيزة | Giza |
| `04` | محافظة بورسعيد | Port Said |
| `05` | محافظة السويس | Suez |
| `06` | محافظة الإسماعيلية | Ismailia |
| `07` | محافظة القليوبية | Qalyubia |
| `08` | محافظة الشرقية | Sharkia |
| `09` | محافظة الغربية | Gharbia |
| `10` | محافظة المنوفية | Monufia |
| `11` | محافظة الدقهلية | Dakahlia |
| `12` | محافظة كفر الشيخ | Kafr El Sheikh |
| `13` | محافظة دمياط | Damietta |
| `14` | محافظة البحيرة | Beheira |
| `15` | محافظة الفيوم | Faiyum |
| `16` | محافظة بني سويف | Beni Suef |
| `17` | محافظة المنيا | Minya |
| `18` | محافظة أسيوط | Asyut |
| `19` | محافظة سوهاج | Sohag |
| `20` | محافظة قنا | Qena |
| `21` | محافظة الأقصر | Luxor |
| `22` | محافظة البحر الأحمر | Red Sea |
| `23` | محافظة اسوان | Aswan |
| `24` | محافظة الوادي الجديد | New Valley |
| `25` | محافظة مطروح | Matrouh |
| `26` | محافظة شمال سيناء | North Sinai |
| `27` | محافظة جنوب سيناء | South Sinai |

---

## 6. Query Optimization & View Implementation

In `master_data/views.py` (`areas_settings_view`):
```python
governorates = (
    Area.objects.filter(parent__isnull=True, is_company_area=False)
    .annotate(subareas_count=Count('subareas'))
    .prefetch_related('subareas')
    .order_by('code', 'name')
)
```
- Excludes company internal areas (`is_company_area=False`).
- Annotates `subareas_count` in a single SQL query (`Count('subareas')`).
- Prefetches subareas for fast rendering of child administrative zones.

---

## 7. UI & UX Highlights (`templates/settings/areas_settings.html`)

- **Interactive Governorate Grid:** Responsive cards displaying governorate code, Arabic & English names, and a badge pill showing `N مناطق فرعية`.
- **Sub-area Modal:** Fast creation and management of sub-areas linked directly to parent governorates.
- **Audit Logging:** Every area creation, update, and deletion is audited via `AuditLogService.log(module='areas', ...)`.
- **Automated Verification:** Verified by unit tests in `master_data/tests_egypt_areas.py`.
