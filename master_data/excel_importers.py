"""
First-Wave 10 Approved Excel Importers for WEA Pharma ERP.
Entities strictly matching approved scope (Users STRICTLY EXCLUDED):
  1. contacts
  2. products
  3. categories
  4. areas
  5. warehouses
  6. planned_visits
  7. stock_adjustments
  8. collections
  9. vendor_payments
 10. inventory_stock
"""

from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from django.contrib.auth import get_user_model
from django.utils import timezone

from accounts.permissions import (
    can_user_access_object,
    can_user_perform_stock_in,
    can_user_perform_stock_out,
    get_scoped_queryset,
    get_visit_eligible_contacts_queryset,
)
from accounts.scope_service import ScopeResolutionService
from activities.models import PlannedVisitDay, PlannedVisitItem, VisitTemplate
from catalog.models import Product, ProductCategory
from contacts.models import Contact
from inventory.models import InventoryStock, Warehouse
from inventory.services import InventoryMemoService
from master_data.models import Area
from purchases.models import PurchaseOrder
from sales.models import SalesOrder
from sales.services import CollectionService
from treasury.models import Vault
from treasury.services import TreasuryService

from .excel_import_engine import (
    BaseExcelImporter,
    ColumnSpec,
    parse_bool_val,
    parse_date_val,
    parse_decimal_val,
    parse_int_val,
)

User = get_user_model()


def _clean_str(val: Any) -> str:
    return '' if val is None else str(val).strip()


# ---------------------------------------------------------------------------
# 1. CONTACTS (Customers / Suppliers — Strict DataScope, No Unauthorized Area Creation)
# ---------------------------------------------------------------------------
class ContactsExcelImporter(BaseExcelImporter):
    entity_key = 'contacts'
    title_ar = 'جهات الاتصال (العملاء والموردين)'
    description_ar = 'استيراد أو تحديث العملاء والموردين مع الالتزام التام بنطاق المناطق (DataScope).'
    permission_codename = 'contacts:contacts/import'
    back_url_name = 'contacts_list'
    columns = [
        ColumnSpec('name', 'الاسم', required=True, aliases=['اسم العميل', 'اسم المورد', 'contact_name'], sample='صيدلية الشفاء', rules_ar='الاسم الكامل للعميل أو المورد (إلزامي).', width=28),
        ColumnSpec('contact_type', 'النوع', required=False, aliases=['نوع الجهة', 'type'], sample='عميل', rules_ar='عميل / مورد / كلاهما / أخرى (الافتراضي: عميل).', width=16),
        ColumnSpec('code', 'الكود', required=False, aliases=['كود العميل', 'كود المورد'], sample='C-1001', rules_ar='اختياري؛ يُستخدم لمطابقة وتحديث السجلات القائمة.', width=16),
        ColumnSpec('area', 'المنطقة الرئيسية', required=False, aliases=['المحافظة', 'governorate', 'main_area'], sample='القاهرة', rules_ar='يجب أن تكون منطقة موجودة ومصرح بها ضمن نطاقك.', width=20),
        ColumnSpec('brick', 'المنطقة الفرعية (البريك)', required=False, aliases=['البريك', 'subarea'], sample='مدينة نصر', rules_ar='يجب أن يكون بريك موجود ضمن نطاقك.', width=22),
        ColumnSpec('mobile', 'الموبايل', required=False, aliases=['الهاتف المحمول', 'phone'], sample='01012345678', rules_ar='رقم الجوال للتواصل.', width=18),
        ColumnSpec('credit_limit', 'الحد الائتماني', required=False, aliases=['الائتمان'], sample='25000', rules_ar='رقم غير سالب (ج.م).', width=16),
        ColumnSpec('credit_period_days', 'فترة السماح (أيام)', required=False, aliases=['أيام الائتمان'], sample='30', rules_ar='عدد صحيح >= 0.', width=16),
        ColumnSpec('notes', 'ملاحظات', required=False, sample='', rules_ar='ملاحظات إضافية.', width=28),
    ]

    def prepare_context(self) -> None:
        self._is_super = bool(self.user.is_superuser or getattr(self.user, 'is_super_admin', False))
        self._areas_by_name = {a.name.strip().lower(): a for a in Area.objects.select_related('parent').all()}
        self._allowed_main_ids = set(ScopeResolutionService.get_user_main_areas(self.user).values_list('id', flat=True))
        self._allowed_brick_ids = set(ScopeResolutionService.get_user_bricks(self.user).values_list('id', flat=True))
        self._existing_by_code = {}
        self._existing_by_name = {}
        scoped_contacts = get_scoped_queryset(Contact.objects.all(), self.user, 'contact')
        for c in scoped_contacts:
            if c.code:
                self._existing_by_code[c.code.strip().lower()] = c.id
            self._existing_by_name[c.name.strip().lower()] = c.id

    def validate_row(self, row_num, raw, seen):
        errors = []
        name = _clean_str(raw.get('name'))
        if not name:
            errors.append("الاسم مطلوب.")

        code = _clean_str(raw.get('code'))
        seen_names = seen.setdefault('names', set())
        if name and name.lower() in seen_names:
            errors.append(f"اسم مكرر داخل الملف: '{name}'.")
        elif name:
            seen_names.add(name.lower())

        raw_type = _clean_str(raw.get('contact_type')).lower()
        is_customer, is_supplier, is_other = True, False, False
        if raw_type in ('مورد', 'supplier', 'vendor'):
            is_customer, is_supplier = False, True
        elif raw_type in ('كلاهما', 'عميل ومورد', 'both'):
            is_customer, is_supplier = True, True
        elif raw_type in ('أخرى', 'اخرى', 'other'):
            is_customer, is_other = False, True

        area_name = _clean_str(raw.get('area'))
        brick_name = _clean_str(raw.get('brick'))
        area_obj = None
        brick_obj = None

        if area_name:
            area_obj = self._areas_by_name.get(area_name.lower())
            if not area_obj:
                errors.append(f"المنطقة الرئيسية '{area_name}' غير موجودة في دليل المناطق (لا يُسمح بإنشاء مناطق تلقائياً).")
            elif area_obj.parent_id is not None:
                # User passed a brick in area column
                brick_obj = area_obj
                area_obj = area_obj.parent

        if brick_name:
            b = self._areas_by_name.get(brick_name.lower())
            if not b:
                errors.append(f"البريك '{brick_name}' غير موجود في دليل المناطق.")
            else:
                brick_obj = b
                if b.parent_id and area_obj is None:
                    area_obj = b.parent

        # Strict DataScope validation for non-SuperAdmin
        if not self._is_super and not errors:
            if brick_obj:
                if self._allowed_brick_ids and brick_obj.id not in self._allowed_brick_ids:
                    root = ScopeResolutionService.get_main_area(brick_obj)
                    if not (root and root.id in self._allowed_main_ids and getattr(self.user.role, 'is_area_manager', False)):
                        errors.append(f"البريك '{brick_obj.name}' خارج نطاقك الجغرافي المصرح به.")
            elif area_obj:
                root = ScopeResolutionService.get_main_area(area_obj)
                if not root or root.id not in self._allowed_main_ids:
                    errors.append(f"المنطقة '{area_obj.name}' خارج نطاقك الجغرافي المصرح به.")
            else:
                # Default to user's first allowed brick/main area if available
                if self._allowed_brick_ids:
                    first_b = Area.objects.filter(id__in=self._allowed_brick_ids).select_related('parent').first()
                    if first_b:
                        brick_obj = first_b
                        area_obj = first_b.parent or first_b
                elif self._allowed_main_ids:
                    area_obj = Area.objects.filter(id__in=self._allowed_main_ids).first()
                else:
                    errors.append("يجب تحديد منطقة/بريك ضمن نطاقك الجغرافي.")

        credit_limit, err = parse_decimal_val(raw.get('credit_limit'), 'الحد الائتماني', default=Decimal('0.00'))
        if err:
            errors.append(err)
        credit_days, err = parse_int_val(raw.get('credit_period_days'), 'فترة السماح', min_val=0, default=0)
        if err:
            errors.append(err)

        existing_id = None
        if code and code.lower() in self._existing_by_code:
            existing_id = self._existing_by_code[code.lower()]
        elif name and name.lower() in self._existing_by_name:
            existing_id = self._existing_by_name[name.lower()]

        if errors:
            return None, 'error', errors

        cleaned = {
            'existing_id': existing_id,
            'name': name,
            'code': code,
            'is_customer': is_customer,
            'is_supplier': is_supplier,
            'is_other': is_other,
            'area_id': area_obj.id if area_obj else None,
            'brick_id': brick_obj.id if brick_obj else None,
            'mobile': _clean_str(raw.get('mobile')),
            'credit_limit': str(credit_limit or Decimal('0.00')),
            'credit_period_days': int(credit_days or 0),
            'notes': _clean_str(raw.get('notes')),
        }
        return cleaned, ('update' if existing_id else 'create'), []

    def commit_rows(self, valid_rows):
        created, updated = 0, 0
        for item in valid_rows:
            d = item['cleaned']
            if d['existing_id']:
                c = Contact.objects.get(pk=d['existing_id'])
                c.name = d['name']
                if d['code']:
                    c.code = d['code']
                c.is_customer = d['is_customer']
                c.is_supplier = d['is_supplier']
                c.is_other = d['is_other']
                if d['area_id']:
                    c.area_id = d['area_id']
                if d['brick_id']:
                    c.brick_id = d['brick_id']
                if d['mobile']:
                    c.mobile = d['mobile']
                c.credit_limit = Decimal(d['credit_limit'])
                c.credit_period_days = d['credit_period_days']
                if d['notes']:
                    c.notes = d['notes']
                c.save()
                updated += 1
            else:
                Contact.objects.create(
                    name=d['name'],
                    code=d['code'] or '',
                    is_customer=d['is_customer'],
                    is_supplier=d['is_supplier'],
                    is_other=d['is_other'],
                    area_id=d['area_id'],
                    brick_id=d['brick_id'],
                    mobile=d['mobile'],
                    credit_limit=Decimal(d['credit_limit']),
                    credit_period_days=d['credit_period_days'],
                    notes=d['notes'],
                    created_by=self.user,
                )
                created += 1
        return created, updated


# ---------------------------------------------------------------------------
# 2. PRODUCTS
# ---------------------------------------------------------------------------
class ProductsExcelImporter(BaseExcelImporter):
    entity_key = 'products'
    title_ar = 'دليل المنتجات'
    description_ar = 'استيراد وتحديث المنتجات والأسعار والتصنيفات.'
    permission_codename = 'catalog:products/import'
    back_url_name = 'products_list'
    columns = [
        ColumnSpec('name', 'اسم المنتج', required=True, aliases=['الاسم', 'product_name'], sample='أموكسيسيلين 500 مجم', rules_ar='اسم المنتج التجاري (إلزامي).', width=30),
        ColumnSpec('sku_code', 'كود الصنف (SKU)', required=False, aliases=['الكود', 'sku'], sample='SKU-101', rules_ar='اختياري؛ يُستخدم للتحديث إن كان موجوداً.', width=18),
        ColumnSpec('category', 'التصنيف', required=False, aliases=['الفئة', 'category_name'], sample='مضادات حيوية', rules_ar='اسم تصنيف موجود في دليل التصنيفات.', width=22),
        ColumnSpec('retail_price', 'سعر البيع', required=True, aliases=['السعر', 'price'], sample='120.00', rules_ar='رقم >= 0 (إلزامي).', width=16),
        ColumnSpec('default_purchase_cost', 'سعر التكلفة', required=False, aliases=['التكلفة', 'cost'], sample='85.00', rules_ar='رقم >= 0.', width=16),
        ColumnSpec('tax_percentage', 'الضريبة %', required=False, aliases=['الضريبة', 'tax'], sample='0', rules_ar='نسبة بين 0 و 100.', width=14),
        ColumnSpec('unit', 'الوحدة', required=False, sample='علبة', rules_ar='مثال: علبة / شريط / كرتونة.', width=14),
        ColumnSpec('sellable', 'قابل للبيع', required=False, sample='نعم', rules_ar='نعم / لا (الافتراضي: نعم).', width=14),
    ]

    def prepare_context(self) -> None:
        self._cats_by_name = {c.name.strip().lower(): c.id for c in ProductCategory.objects.all()}
        self._prod_by_sku = {p.sku_code.strip().lower(): p.id for p in Product.objects.exclude(sku_code='').exclude(sku_code__isnull=True)}
        self._prod_by_name = {p.name.strip().lower(): p.id for p in Product.objects.all()}

    def validate_row(self, row_num, raw, seen):
        errors = []
        name = _clean_str(raw.get('name'))
        if not name:
            errors.append("اسم المنتج مطلوب.")
        sku = _clean_str(raw.get('sku_code'))
        if sku:
            seen_skus = seen.setdefault('skus', set())
            if sku.lower() in seen_skus:
                errors.append(f"كود SKU مكرر داخل الملف: '{sku}'.")
            else:
                seen_skus.add(sku.lower())

        price, err = parse_decimal_val(raw.get('retail_price'), 'سعر البيع')
        if err:
            errors.append(err)
        elif price is None:
            errors.append("سعر البيع مطلوب.")

        cost, err = parse_decimal_val(raw.get('default_purchase_cost'), 'سعر التكلفة', default=Decimal('0.00'))
        if err:
            errors.append(err)

        tax, err = parse_decimal_val(raw.get('tax_percentage'), 'الضريبة %', default=Decimal('0.00'))
        if err:
            errors.append(err)
        elif tax is not None and tax > Decimal('100'):
            errors.append("نسبة الضريبة يجب أن تكون <= 100.")

        cat_name = _clean_str(raw.get('category'))
        cat_id = None
        if cat_name:
            cat_id = self._cats_by_name.get(cat_name.lower())
            if not cat_id:
                errors.append(f"التصنيف '{cat_name}' غير موجود في دليل التصنيفات.")

        existing_id = self._prod_by_sku.get(sku.lower()) if sku else None
        if not existing_id and name:
            existing_id = self._prod_by_name.get(name.lower())

        if errors:
            return None, 'error', errors

        cleaned = {
            'existing_id': existing_id,
            'name': name,
            'sku_code': sku,
            'category_id': cat_id,
            'retail_price': str(price),
            'default_purchase_cost': str(cost or Decimal('0.00')),
            'tax_percentage': str(tax or Decimal('0.00')),
            'unit': _clean_str(raw.get('unit')) or 'وحدة',
            'sellable': parse_bool_val(raw.get('sellable'), default=True),
        }
        return cleaned, ('update' if existing_id else 'create'), []

    def commit_rows(self, valid_rows):
        created, updated = 0, 0
        for item in valid_rows:
            d = item['cleaned']
            if d['existing_id']:
                p = Product.objects.get(pk=d['existing_id'])
                p.name = d['name']
                if d['sku_code']:
                    p.sku_code = d['sku_code']
                if d['category_id']:
                    p.category_id = d['category_id']
                p.retail_price = Decimal(d['retail_price'])
                p.default_purchase_cost = Decimal(d['default_purchase_cost'])
                p.tax_percentage = Decimal(d['tax_percentage'])
                p.unit = d['unit']
                p.sellable = d['sellable']
                p.save()
                updated += 1
            else:
                Product.objects.create(
                    name=d['name'],
                    sku_code=d['sku_code'] or '',
                    category_id=d['category_id'],
                    retail_price=Decimal(d['retail_price']),
                    default_purchase_cost=Decimal(d['default_purchase_cost']),
                    tax_percentage=Decimal(d['tax_percentage']),
                    unit=d['unit'],
                    sellable=d['sellable'],
                    is_active=True,
                    created_by=self.user,
                )
                created += 1
        return created, updated


# ---------------------------------------------------------------------------
# 3. PRODUCT CATEGORIES
# ---------------------------------------------------------------------------
class CategoriesExcelImporter(BaseExcelImporter):
    entity_key = 'categories'
    title_ar = 'تصنيفات المنتجات'
    description_ar = 'استيراد أو تحديث تصنيفات دليل المنتجات.'
    permission_codename = 'catalog:categories/import'
    back_url_name = 'categories_list'
    columns = [
        ColumnSpec('name', 'اسم التصنيف', required=True, aliases=['التصنيف', 'الاسم'], sample='مكملات غذائية', rules_ar='اسم التصنيف (إلزامي وفريد).', width=28),
        ColumnSpec('code', 'الكود', required=False, aliases=['كود التصنيف'], sample='CAT-01', rules_ar='كود مختصر اختياري.', width=16),
        ColumnSpec('description', 'الوصف', required=False, sample='فيتامينات ومعادن', rules_ar='وصف اختياري للتصنيف.', width=34),
    ]

    def prepare_context(self) -> None:
        self._by_name = {c.name.strip().lower(): c.id for c in ProductCategory.objects.all()}

    def validate_row(self, row_num, raw, seen):
        errors = []
        name = _clean_str(raw.get('name'))
        if not name:
            errors.append("اسم التصنيف مطلوب.")
        seen_names = seen.setdefault('names', set())
        if name and name.lower() in seen_names:
            errors.append(f"اسم التصنيف مكرر داخل الملف: '{name}'.")
        elif name:
            seen_names.add(name.lower())

        if errors:
            return None, 'error', errors
        existing_id = self._by_name.get(name.lower())
        return {
            'existing_id': existing_id,
            'name': name,
            'code': _clean_str(raw.get('code')),
            'description': _clean_str(raw.get('description')),
        }, ('update' if existing_id else 'create'), []

    def commit_rows(self, valid_rows):
        created, updated = 0, 0
        for item in valid_rows:
            d = item['cleaned']
            if d['existing_id']:
                c = ProductCategory.objects.get(pk=d['existing_id'])
                c.name = d['name']
                if d['code']:
                    c.code = d['code']
                if d['description']:
                    c.description = d['description']
                c.save()
                updated += 1
            else:
                ProductCategory.objects.create(
                    name=d['name'],
                    code=d['code'] or '',
                    description=d['description'] or '',
                )
                created += 1
        return created, updated


# ---------------------------------------------------------------------------
# 4. AREAS & BRICKS
# ---------------------------------------------------------------------------
class AreasExcelImporter(BaseExcelImporter):
    entity_key = 'areas'
    title_ar = 'المناطق والبريكات'
    description_ar = 'استيراد المحافظات (المناطق الرئيسية) والمناطق الفرعية (البريكات).'
    permission_codename = 'settings:areas/import'
    back_url_name = 'areas_settings'
    columns = [
        ColumnSpec('name', 'اسم المنطقة / البريك', required=True, aliases=['الاسم', 'المنطقة'], sample='مدينة نصر', rules_ar='اسم المحافظة أو البريك (إلزامي).', width=28),
        ColumnSpec('parent', 'المنطقة الرئيسية (المحافظة)', required=False, aliases=['المحافظة', 'parent_name'], sample='القاهرة', rules_ar='اتركه فارغاً إذا كان الصف يمثل محافظة رئيسية، أو اكتب اسم المحافظة الأم للبريك.', width=28),
    ]

    def prepare_context(self) -> None:
        self._main_by_name = {a.name.strip().lower(): a.id for a in Area.objects.filter(parent__isnull=True)}
        self._all_pairs = {(a.name.strip().lower(), a.parent_id): a.id for a in Area.objects.all()}

    def validate_row(self, row_num, raw, seen):
        errors = []
        name = _clean_str(raw.get('name'))
        parent_name = _clean_str(raw.get('parent'))
        if not name:
            errors.append("اسم المنطقة / البريك مطلوب.")
        if parent_name and parent_name.lower() == name.lower():
            errors.append("لا يمكن أن تكون المنطقة أباً لنفسها.")

        seen_main = seen.setdefault('main', set())
        seen_pairs = seen.setdefault('pairs', set())
        pair_key = (name.lower(), parent_name.lower())
        if pair_key in seen_pairs:
            errors.append(f"منطقة مكررة داخل الملف: '{name}'.")
        elif name:
            seen_pairs.add(pair_key)

        if not parent_name and name:
            seen_main.add(name.lower())

        parent_id = None
        if parent_name:
            parent_id = self._main_by_name.get(parent_name.lower())
            if not parent_id and parent_name.lower() not in seen_main:
                errors.append(f"المنطقة الرئيسية '{parent_name}' غير موجودة (أضفها أولاً أو في صف سابق بالملف).")

        if errors:
            return None, 'error', errors

        existing_id = self._all_pairs.get((name.lower(), parent_id))
        return {
            'existing_id': existing_id,
            'name': name,
            'parent_name': parent_name,
        }, ('update' if existing_id else 'create'), []

    def commit_rows(self, valid_rows):
        created, updated = 0, 0
        main_map = {a.name.strip().lower(): a for a in Area.objects.filter(parent__isnull=True)}
        # First pass: main areas
        for item in valid_rows:
            d = item['cleaned']
            if d['parent_name']:
                continue
            obj, was_created = Area.objects.get_or_create(name=d['name'], parent=None)
            main_map[d['name'].lower()] = obj
            if was_created:
                created += 1
            else:
                updated += 1
        # Second pass: child bricks
        for item in valid_rows:
            d = item['cleaned']
            if not d['parent_name']:
                continue
            parent = main_map.get(d['parent_name'].lower())
            obj, was_created = Area.objects.get_or_create(name=d['name'], parent=parent)
            if was_created:
                created += 1
            else:
                updated += 1
        return created, updated


# ---------------------------------------------------------------------------
# 5. WAREHOUSES
# ---------------------------------------------------------------------------
class WarehousesExcelImporter(BaseExcelImporter):
    entity_key = 'warehouses'
    title_ar = 'المخازن'
    description_ar = 'استيراد أو تحديث المخازن وربطها بالمناطق والمناديب.'
    permission_codename = 'inventory:warehouses/import'
    back_url_name = 'warehouses_list'
    columns = [
        ColumnSpec('name', 'اسم المخزن', required=True, aliases=['المخزن'], sample='مخزن شرق القاهرة', rules_ar='اسم المخزن (إلزامي).', width=28),
        ColumnSpec('code', 'كود المخزن', required=False, aliases=['الكود'], sample='WH-CAI-02', rules_ar='كود فريد اختياري.', width=16),
        ColumnSpec('area', 'المنطقة', required=False, aliases=['المحافظة'], sample='القاهرة', rules_ar='منطقة موجودة ضمن نطاقك.', width=20),
        ColumnSpec('assigned_user', 'المندوب / المسؤول (البريد أو الكود)', required=False, aliases=['المندوب', 'المستخدم'], sample='rep@wea.com', rules_ar='اختياري؛ البريد الإلكتروني أو كود المستخدم.', width=26),
        ColumnSpec('is_main', 'مخزن رئيسي؟', required=False, sample='لا', rules_ar='نعم / لا.', width=14),
        ColumnSpec('address', 'العنوان', required=False, sample='مدينة نصر', rules_ar='عنوان المخزن الاختياري.', width=28),
    ]

    def prepare_context(self) -> None:
        self._is_super = bool(self.user.is_superuser or getattr(self.user, 'is_super_admin', False))
        self._areas = {a.name.strip().lower(): a for a in Area.objects.select_related('parent').all()}
        self._allowed_main_ids = set(ScopeResolutionService.get_user_main_areas(self.user).values_list('id', flat=True))
        self._users = {}
        for u in User.objects.filter(is_active=True):
            if u.email:
                self._users[u.email.strip().lower()] = u.id
            if u.username:
                self._users[u.username.strip().lower()] = u.id
            if u.code:
                self._users[u.code.strip().lower()] = u.id
        self._existing = {w.name.strip().lower(): w.id for w in get_scoped_queryset(Warehouse.objects.all(), self.user, 'warehouse')}

    def validate_row(self, row_num, raw, seen):
        errors = []
        name = _clean_str(raw.get('name'))
        if not name:
            errors.append("اسم المخزن مطلوب.")
        seen_names = seen.setdefault('names', set())
        if name and name.lower() in seen_names:
            errors.append(f"اسم مخزن مكرر داخل الملف: '{name}'.")
        elif name:
            seen_names.add(name.lower())

        area_obj = None
        area_name = _clean_str(raw.get('area'))
        if area_name:
            area_obj = self._areas.get(area_name.lower())
            if not area_obj:
                errors.append(f"المنطقة '{area_name}' غير موجودة.")
            elif not self._is_super:
                root = ScopeResolutionService.get_main_area(area_obj)
                if not root or root.id not in self._allowed_main_ids:
                    errors.append(f"المنطقة '{area_name}' خارج نطاقك الجغرافي.")

        assigned_uid = None
        user_ref = _clean_str(raw.get('assigned_user'))
        if user_ref:
            assigned_uid = self._users.get(user_ref.lower())
            if not assigned_uid:
                errors.append(f"المستخدم '{user_ref}' غير موجود أو معطل.")

        if errors:
            return None, 'error', errors

        existing_id = self._existing.get(name.lower())
        is_main = parse_bool_val(raw.get('is_main'), default=False)
        return {
            'existing_id': existing_id,
            'name': name,
            'code': _clean_str(raw.get('code')),
            'area_id': area_obj.id if area_obj else None,
            'assigned_user_id': assigned_uid,
            'is_main': is_main,
            'is_rep_warehouse': bool(assigned_uid and not is_main),
            'address': _clean_str(raw.get('address')),
        }, ('update' if existing_id else 'create'), []

    def commit_rows(self, valid_rows):
        created, updated = 0, 0
        for item in valid_rows:
            d = item['cleaned']
            if d['existing_id']:
                w = Warehouse.objects.get(pk=d['existing_id'])
                w.name = d['name']
                if d['code']:
                    w.code = d['code']
                if d['area_id']:
                    w.area_id = d['area_id']
                if d['assigned_user_id']:
                    w.assigned_user_id = d['assigned_user_id']
                w.is_main = d['is_main']
                w.is_rep_warehouse = d['is_rep_warehouse']
                if d['address']:
                    w.address = d['address']
                w.save()
                updated += 1
            else:
                Warehouse.objects.create(
                    name=d['name'],
                    code=d['code'] or '',
                    area_id=d['area_id'],
                    assigned_user_id=d['assigned_user_id'],
                    is_main=d['is_main'],
                    is_rep_warehouse=d['is_rep_warehouse'],
                    address=d['address'],
                    is_active=True,
                )
                created += 1
        return created, updated


# ---------------------------------------------------------------------------
# 6. PLANNED VISITS
# ---------------------------------------------------------------------------
class PlannedVisitsExcelImporter(BaseExcelImporter):
    entity_key = 'planned_visits'
    title_ar = 'الزيارات المخططة'
    description_ar = 'استيراد جدول الزيارات المخططة اليومية للمناديب مع التحقق من نطاق العملاء.'
    permission_codename = 'activities:planned/import'
    back_url_name = 'planned_visits_list'
    columns = [
        ColumnSpec('date', 'تاريخ الزيارة', required=True, aliases=['التاريخ'], sample=date.today().isoformat(), rules_ar='صيغة YYYY-MM-DD (إلزامي).', width=18),
        ColumnSpec('customer', 'العميل (الاسم أو الكود)', required=True, aliases=['اسم العميل', 'جهة الاتصال'], sample='صيدلية الشفاء', rules_ar='يجب أن يكون عميلاً نشطاً ومصرحاً بزيارته ضمن نطاقك.', width=30),
        ColumnSpec('assignee', 'المندوب (البريد أو الكود)', required=False, aliases=['المستخدم', 'rep'], sample='', rules_ar='اتركه فارغاً لتعيينك أنت، أو أدخل بريد/كود مندوب ضمن نطاقك.', width=26),
        ColumnSpec('template', 'قالب الزيارة', required=False, aliases=['النموذج'], sample='', rules_ar='اختياري؛ اسم قالب زيارة مفعل.', width=22),
        ColumnSpec('notes', 'ملاحظات', required=False, sample='زيارة متابعة شهرية', rules_ar='ملاحظات اختيارية.', width=28),
    ]

    def prepare_context(self) -> None:
        self._eligible_contacts = {}
        for c in get_visit_eligible_contacts_queryset(self.user):
            self._eligible_contacts[c.name.strip().lower()] = c.id
            if c.code:
                self._eligible_contacts[c.code.strip().lower()] = c.id
        self._scoped_users = {}
        for u in get_scoped_queryset(User.objects.filter(is_active=True), self.user, 'user'):
            if u.email:
                self._scoped_users[u.email.strip().lower()] = u.id
            if u.username:
                self._scoped_users[u.username.strip().lower()] = u.id
            if u.code:
                self._scoped_users[u.code.strip().lower()] = u.id
        self._templates = {t.name.strip().lower(): t.id for t in VisitTemplate.objects.filter(active=True)}
        for t in VisitTemplate.objects.filter(active=True):
            if t.display_name_ar:
                self._templates[t.display_name_ar.strip().lower()] = t.id

    def validate_row(self, row_num, raw, seen):
        errors = []
        vdate, err = parse_date_val(raw.get('date'), 'تاريخ الزيارة')
        if err:
            errors.append(err)
        elif not vdate:
            errors.append("تاريخ الزيارة مطلوب.")

        cust_ref = _clean_str(raw.get('customer'))
        contact_id = self._eligible_contacts.get(cust_ref.lower()) if cust_ref else None
        if not cust_ref:
            errors.append("اسم أو كود العميل مطلوب.")
        elif not contact_id:
            errors.append(f"العميل '{cust_ref}' غير موجود أو خارج نطاق الزيارات المصرح به.")

        assignee_ref = _clean_str(raw.get('assignee'))
        if assignee_ref:
            assignee_id = self._scoped_users.get(assignee_ref.lower())
            if not assignee_id:
                errors.append(f"المندوب '{assignee_ref}' غير موجود أو خارج نطاق إشرافك.")
        else:
            assignee_id = self.user.id

        tpl_ref = _clean_str(raw.get('template'))
        tpl_id = None
        if tpl_ref:
            tpl_id = self._templates.get(tpl_ref.lower())
            if not tpl_id:
                errors.append(f"قالب الزيارة '{tpl_ref}' غير موجود أو معطل.")

        if vdate and contact_id and assignee_id:
            dup_key = (assignee_id, vdate.isoformat(), contact_id)
            seen_p = seen.setdefault('planned', set())
            if dup_key in seen_p:
                errors.append("زيارة مخططة مكررة لنفس العميل والمندوب والتاريخ داخل الملف.")
            else:
                seen_p.add(dup_key)

        if errors:
            return None, 'error', errors

        return {
            'date': vdate.isoformat(),
            'contact_id': contact_id,
            'assignee_id': assignee_id,
            'template_id': tpl_id,
            'notes': _clean_str(raw.get('notes')),
        }, 'create', []

    def commit_rows(self, valid_rows):
        created, updated = 0, 0
        for item in valid_rows:
            d = item['cleaned']
            vdate = date.fromisoformat(d['date'])
            day, _ = PlannedVisitDay.objects.get_or_create(
                assignee_id=d['assignee_id'],
                date=vdate,
                defaults={'created_by': self.user, 'status': 'draft'},
            )
            exists = PlannedVisitItem.objects.filter(plan_day=day, contact_id=d['contact_id']).first()
            if exists:
                if d['notes']:
                    exists.notes = d['notes']
                    exists.save(update_fields=['notes'])
                updated += 1
            else:
                next_order = day.items.count() + 1
                PlannedVisitItem.objects.create(
                    plan_day=day,
                    contact_id=d['contact_id'],
                    template_id=d['template_id'],
                    order=next_order,
                    notes=d['notes'],
                )
                created += 1
        return created, updated


# ---------------------------------------------------------------------------
# 7. INVENTORY STOCK ADJUSTMENTS (via official InventoryMemoService)
# ---------------------------------------------------------------------------
class StockAdjustmentsExcelImporter(BaseExcelImporter):
    entity_key = 'stock_adjustments'
    title_ar = 'تسويات وأذون المخزون (إضافة / صرف)'
    description_ar = 'إنشاء أذون إضافة وصرف مخزنية رسمية عبر محرك المخزون مع التحقق من الصلاحيات والأرصدة.'
    permission_codename = 'inventory:memos/import'
    back_url_name = 'inventory_memos_list'
    columns = [
        ColumnSpec('warehouse', 'المخزن', required=True, aliases=['اسم المخزن'], sample='المخزن الرئيسي بضاعه', rules_ar='اسم أو كود مخزن مفعل ضمن نطاقك.', width=26),
        ColumnSpec('product', 'المنتج (الاسم أو SKU)', required=True, aliases=['اسم المنتج', 'sku'], sample='أموكسيسيلين 500 مجم', rules_ar='اسم أو كود منتج موجود.', width=28),
        ColumnSpec('memo_type', 'نوع الحركة', required=True, aliases=['النوع', 'type'], sample='إضافة', rules_ar='إضافة (inward) أو صرف (outward).', width=16),
        ColumnSpec('quantity', 'الكمية', required=True, sample='50', rules_ar='عدد صحيح موجب (> 0).', width=14),
        ColumnSpec('unit_cost', 'سعر التكلفة', required=False, aliases=['التكلفة'], sample='85.00', rules_ar='اختياري؛ رقم >= 0 لحركات الإضافة.', width=16),
        ColumnSpec('batch_number', 'رقم التشغيلة', required=False, sample='B-2026-01', rules_ar='اختياري.', width=18),
        ColumnSpec('statement', 'البيان', required=False, aliases=['ملاحظات', 'السبب'], sample='تسوية جردية عبر Excel', rules_ar='وصف حركة الإذن المخزني.', width=28),
    ]

    def prepare_context(self) -> None:
        self._warehouses = {}
        for w in get_scoped_queryset(Warehouse.objects.filter(is_active=True), self.user, 'warehouse'):
            self._warehouses[w.name.strip().lower()] = w
            if w.code:
                self._warehouses[w.code.strip().lower()] = w
        self._products = {}
        for p in Product.objects.all():
            self._products[p.name.strip().lower()] = p
            if p.sku_code:
                self._products[p.sku_code.strip().lower()] = p

    def validate_row(self, row_num, raw, seen):
        errors = []
        wh_ref = _clean_str(raw.get('warehouse'))
        wh = self._warehouses.get(wh_ref.lower()) if wh_ref else None
        if not wh_ref:
            errors.append("اسم المخزن مطلوب.")
        elif not wh:
            errors.append(f"المخزن '{wh_ref}' غير موجود أو خارج نطاقك.")

        prod_ref = _clean_str(raw.get('product'))
        prod = self._products.get(prod_ref.lower()) if prod_ref else None
        if not prod_ref:
            errors.append("اسم أو كود المنتج مطلوب.")
        elif not prod:
            errors.append(f"المنتج '{prod_ref}' غير موجود.")

        mt_raw = _clean_str(raw.get('memo_type')).lower()
        memo_type = None
        if mt_raw in ('إضافة', 'اضافة', 'inward', 'in', 'add'):
            memo_type = 'inward'
        elif mt_raw in ('صرف', 'خصم', 'outward', 'out', 'deduct'):
            memo_type = 'outward'
        else:
            errors.append("نوع الحركة يجب أن يكون 'إضافة' أو 'صرف'.")

        qty, err = parse_int_val(raw.get('quantity'), 'الكمية', min_val=1)
        if err:
            errors.append(err)
        elif not qty:
            errors.append("الكمية مطلوبة ويجب أن تكون أكبر من صفر.")

        cost, err = parse_decimal_val(raw.get('unit_cost'), 'سعر التكلفة', default=None)
        if err:
            errors.append(err)

        if wh and memo_type == 'inward' and not can_user_perform_stock_in(self.user, wh):
            errors.append(f"غير مصرح لك بإنشاء إذن إضافة للمخزن '{wh.name}'.")
        if wh and memo_type == 'outward' and not can_user_perform_stock_out(self.user, wh):
            errors.append(f"غير مصرح لك بإنشاء إذن صرف من المخزن '{wh.name}'.")

        if wh and prod and memo_type == 'outward' and qty:
            st = InventoryStock.objects.filter(warehouse=wh, product=prod).first()
            avail = st.qty_available if st else Decimal('0')
            if avail < Decimal(qty):
                errors.append(f"الرصيد المتاح ({avail:,.0f}) أقل من كمية الصرف المطلوبة ({qty}).")

        if errors:
            return None, 'error', errors

        return {
            'warehouse_id': wh.id,
            'product_id': prod.id,
            'memo_type': memo_type,
            'quantity': qty,
            'unit_cost': str(cost if cost is not None else (prod.default_purchase_cost or Decimal('0.00'))),
            'batch_number': _clean_str(raw.get('batch_number')),
            'statement': _clean_str(raw.get('statement')) or 'تسوية مخزنية عبر Excel',
        }, 'create', []

    def commit_rows(self, valid_rows):
        grouped: Dict[Tuple[int, str], List[Dict[str, Any]]] = {}
        for item in valid_rows:
            d = item['cleaned']
            grouped.setdefault((d['warehouse_id'], d['memo_type']), []).append(d)

        created = 0
        for (wh_id, mtype), entries in grouped.items():
            wh = Warehouse.objects.get(pk=wh_id)
            items_data = [
                {
                    'product': e['product_id'],
                    'quantity': e['quantity'],
                    'unit_cost': Decimal(e['unit_cost']),
                    'batch_number': e['batch_number'],
                }
                for e in entries
            ]
            InventoryMemoService.create_memo(
                warehouse=wh,
                memo_type=mtype,
                statement=entries[0]['statement'],
                items_data=items_data,
                user=self.user,
                notes='مستورد من Excel',
            )
            created += len(entries)
        return created, 0


# ---------------------------------------------------------------------------
# 8. COLLECTIONS (via official CollectionService.record_collection)
# ---------------------------------------------------------------------------
class CollectionsExcelImporter(BaseExcelImporter):
    entity_key = 'collections'
    title_ar = 'التحصيلات النقدية من العملاء'
    description_ar = 'استيراد تحصيلات العملاء وتسجيلها رسمياً في الخزن وكشف حساب العميل عبر محرك التحصيلات.'
    permission_codename = 'sales:collections/import'
    back_url_name = 'collections_list'
    columns = [
        ColumnSpec('customer', 'العميل (الاسم أو الكود)', required=True, aliases=['اسم العميل'], sample='صيدلية الشفاء', rules_ar='عميل موجود ضمن نطاقك.', width=28),
        ColumnSpec('vault', 'الخزنة', required=True, aliases=['اسم الخزنة'], sample='الخزنة الرئيسية', rules_ar='خزنة مفعلة ضمن نطاقك.', width=24),
        ColumnSpec('amount', 'المبلغ المحصل', required=True, aliases=['المبلغ'], sample='1500.00', rules_ar='رقم موجب (> 0).', width=16),
        ColumnSpec('collection_date', 'تاريخ التحصيل', required=False, aliases=['التاريخ'], sample=date.today().isoformat(), rules_ar='YYYY-MM-DD (الافتراضي: اليوم).', width=18),
        ColumnSpec('sales_order', 'رقم أمر البيع (اختياري)', required=False, aliases=['أمر البيع'], sample='', rules_ar='رقم أمر بيع مرتبط بنفس العميل (اختياري).', width=20),
        ColumnSpec('payment_method', 'طريقة الدفع', required=False, sample='cash', rules_ar='cash / bank_transfer / check (الافتراضي: cash).', width=16),
        ColumnSpec('notes', 'ملاحظات', required=False, sample='تحصيل عبر Excel', rules_ar='ملاحظات اختيارية.', width=28),
    ]

    def prepare_context(self) -> None:
        self._customers = {}
        for c in get_scoped_queryset(Contact.objects.filter(is_customer=True), self.user, 'contact'):
            self._customers[c.name.strip().lower()] = c
            if c.code:
                self._customers[c.code.strip().lower()] = c
        self._vaults = {}
        for v in get_scoped_queryset(Vault.objects.filter(is_active=True), self.user, 'vault'):
            self._vaults[v.name.strip().lower()] = v
        self._orders = {o.order_number.strip().lower(): o for o in get_scoped_queryset(SalesOrder.objects.all(), self.user, 'salesorder')}

    def validate_row(self, row_num, raw, seen):
        errors = []
        cust_ref = _clean_str(raw.get('customer'))
        cust = self._customers.get(cust_ref.lower()) if cust_ref else None
        if not cust_ref:
            errors.append("العميل مطلوب.")
        elif not cust:
            errors.append(f"العميل '{cust_ref}' غير موجود أو خارج نطاقك.")

        vault_ref = _clean_str(raw.get('vault'))
        vault = self._vaults.get(vault_ref.lower()) if vault_ref else None
        if not vault_ref:
            errors.append("الخزنة مطلوبة.")
        elif not vault:
            errors.append(f"الخزنة '{vault_ref}' غير موجودة أو خارج نطاقك.")

        amount, err = parse_decimal_val(raw.get('amount'), 'المبلغ المحصل')
        if err:
            errors.append(err)
        elif not amount or amount <= 0:
            errors.append("المبلغ المحصل يجب أن يكون أكبر من صفر.")

        cdate, err = parse_date_val(raw.get('collection_date'), 'تاريخ التحصيل', default=timezone.localdate())
        if err:
            errors.append(err)

        so_id = None
        so_ref = _clean_str(raw.get('sales_order'))
        if so_ref:
            so = self._orders.get(so_ref.lower())
            if not so:
                errors.append(f"أمر البيع '{so_ref}' غير موجود أو خارج نطاقك.")
            elif cust and so.customer_id != cust.id:
                errors.append(f"أمر البيع '{so_ref}' لا يتبع العميل '{cust.name}'.")
            else:
                so_id = so.id

        pm = _clean_str(raw.get('payment_method')).lower() or 'cash'
        if pm in ('نقدي', 'كاش'):
            pm = 'cash'
        elif pm in ('تحويل بنكي', 'بنكي', 'تحويل'):
            pm = 'bank_transfer'
        elif pm in ('شيك',):
            pm = 'check'
        if pm not in ('cash', 'bank_transfer', 'check', 'card', 'wallet'):
            pm = 'cash'

        if errors:
            return None, 'error', errors

        return {
            'customer_id': cust.id,
            'vault_id': vault.id,
            'amount': str(amount),
            'collection_date': cdate.isoformat(),
            'sales_order_id': so_id,
            'payment_method': pm,
            'notes': _clean_str(raw.get('notes')) or 'تحصيل مستورد عبر Excel',
        }, 'create', []

    def commit_rows(self, valid_rows):
        created = 0
        for item in valid_rows:
            d = item['cleaned']
            cust = Contact.objects.get(pk=d['customer_id'])
            vault = Vault.objects.get(pk=d['vault_id'])
            so = SalesOrder.objects.get(pk=d['sales_order_id']) if d['sales_order_id'] else None
            CollectionService.record_collection(
                customer=cust,
                vault=vault,
                amount=Decimal(d['amount']),
                user=self.user,
                payment_method=d['payment_method'],
                notes=d['notes'],
                sales_order=so,
                collection_date=date.fromisoformat(d['collection_date']),
            )
            created += 1
        return created, 0


# ---------------------------------------------------------------------------
# 9. VENDOR PAYMENTS (via official TreasuryService.record_vendor_payment)
# ---------------------------------------------------------------------------
class VendorPaymentsExcelImporter(BaseExcelImporter):
    entity_key = 'vendor_payments'
    title_ar = 'سدادات الموردين والخزينة'
    description_ar = 'استيراد دفعات سداد الموردين وخصمها رسمياً من الخزنة وحساب المورد.'
    permission_codename = 'treasury:payments/import'
    back_url_name = 'vendor_payments_list'
    columns = [
        ColumnSpec('supplier', 'المورد (الاسم أو الكود)', required=True, aliases=['اسم المورد'], sample='شركة الدواء المتحدة', rules_ar='مورد موجود ضمن نطاقك.', width=28),
        ColumnSpec('vault', 'الخزنة', required=True, aliases=['اسم الخزنة'], sample='الخزنة الرئيسية', rules_ar='خزنة مفعلة وبها رصيد كافٍ.', width=24),
        ColumnSpec('amount', 'المبلغ المدفوع', required=True, aliases=['المبلغ'], sample='5000.00', rules_ar='رقم موجب (> 0).', width=16),
        ColumnSpec('payment_date', 'تاريخ السداد', required=False, aliases=['التاريخ'], sample=date.today().isoformat(), rules_ar='YYYY-MM-DD (الافتراضي: اليوم).', width=18),
        ColumnSpec('purchase_order', 'رقم أمر الشراء (اختياري)', required=False, aliases=['أمر الشراء'], sample='', rules_ar='رقم أمر شراء مرتبط بنفس المورد (اختياري).', width=20),
        ColumnSpec('reference_number', 'رقم المرجع', required=False, sample='', rules_ar='رقم إيصال أو شيك اختياري.', width=18),
        ColumnSpec('notes', 'ملاحظات', required=False, sample='سداد مورد عبر Excel', rules_ar='ملاحظات اختيارية.', width=28),
    ]

    def prepare_context(self) -> None:
        self._suppliers = {}
        for s in get_scoped_queryset(Contact.objects.filter(is_supplier=True), self.user, 'contact'):
            self._suppliers[s.name.strip().lower()] = s
            if s.code:
                self._suppliers[s.code.strip().lower()] = s
        self._vaults = {}
        for v in get_scoped_queryset(Vault.objects.filter(is_active=True), self.user, 'vault'):
            self._vaults[v.name.strip().lower()] = v
        self._pos = {p.order_number.strip().lower(): p for p in get_scoped_queryset(PurchaseOrder.objects.all(), self.user, 'purchaseorder')}
        self._vault_running_spend: Dict[int, Decimal] = {}

    def validate_row(self, row_num, raw, seen):
        errors = []
        sup_ref = _clean_str(raw.get('supplier'))
        sup = self._suppliers.get(sup_ref.lower()) if sup_ref else None
        if not sup_ref:
            errors.append("المورد مطلوب.")
        elif not sup:
            errors.append(f"المورد '{sup_ref}' غير موجود أو خارج نطاقك.")

        vault_ref = _clean_str(raw.get('vault'))
        vault = self._vaults.get(vault_ref.lower()) if vault_ref else None
        if not vault_ref:
            errors.append("الخزنة مطلوبة.")
        elif not vault:
            errors.append(f"الخزنة '{vault_ref}' غير موجودة أو خارج نطاقك.")

        amount, err = parse_decimal_val(raw.get('amount'), 'المبلغ المدفوع')
        if err:
            errors.append(err)
        elif not amount or amount <= 0:
            errors.append("المبلغ المدفوع يجب أن يكون أكبر من صفر.")

        if vault and amount and amount > 0:
            projected = self._vault_running_spend.get(vault.id, Decimal('0.00')) + amount
            if vault.current_balance < projected:
                errors.append(f"رصيد الخزنة '{vault.name}' ({vault.current_balance:,.2f}) غير كافٍ لسداد إجمالي {projected:,.2f} ج.م.")

        pdate, err = parse_date_val(raw.get('payment_date'), 'تاريخ السداد', default=timezone.localdate())
        if err:
            errors.append(err)

        po_id = None
        po_ref = _clean_str(raw.get('purchase_order'))
        if po_ref:
            po = self._pos.get(po_ref.lower())
            if not po:
                errors.append(f"أمر الشراء '{po_ref}' غير موجود أو خارج نطاقك.")
            elif sup and po.supplier_id != sup.id:
                errors.append(f"أمر الشراء '{po_ref}' لا يتبع المورد '{sup.name}'.")
            else:
                po_id = po.id

        if errors:
            return None, 'error', errors

        self._vault_running_spend[vault.id] = self._vault_running_spend.get(vault.id, Decimal('0.00')) + amount
        return {
            'supplier_id': sup.id,
            'vault_id': vault.id,
            'amount': str(amount),
            'payment_date': pdate.isoformat(),
            'purchase_order_id': po_id,
            'reference_number': _clean_str(raw.get('reference_number')),
            'notes': _clean_str(raw.get('notes')) or 'سداد مورد مستورد عبر Excel',
        }, 'create', []

    def commit_rows(self, valid_rows):
        created = 0
        for item in valid_rows:
            d = item['cleaned']
            sup = Contact.objects.get(pk=d['supplier_id'])
            vault = Vault.objects.get(pk=d['vault_id'])
            po = PurchaseOrder.objects.get(pk=d['purchase_order_id']) if d['purchase_order_id'] else None
            TreasuryService.record_vendor_payment(
                supplier=sup,
                vault=vault,
                amount=Decimal(d['amount']),
                user=self.user,
                purchase_order=po,
                payment_date=date.fromisoformat(d['payment_date']),
                reference_number=d['reference_number'],
                notes=d['notes'],
            )
            created += 1
        return created, 0


# ---------------------------------------------------------------------------
# 10. INVENTORY / STOCK (Initial / Target Stock via official InventoryMemoService)
# ---------------------------------------------------------------------------
class InventoryStockExcelImporter(BaseExcelImporter):
    entity_key = 'inventory_stock'
    title_ar = 'أرصدة المخزون (تحميل / مطابقة)'
    description_ar = 'تحميل الأرصدة الافتتاحية أو مطابقة أرصدة الأصناف في المخازن عبر أذون مخزنية رسمية.'
    permission_codename = 'inventory:stocks/import'
    back_url_name = 'inventory_stock_list'
    columns = [
        ColumnSpec('warehouse', 'المخزن', required=True, aliases=['اسم المخزن'], sample='المخزن الرئيسي بضاعه', rules_ar='مخزن مفعل ضمن نطاقك.', width=26),
        ColumnSpec('product', 'المنتج (الاسم أو SKU)', required=True, aliases=['اسم المنتج', 'sku'], sample='أموكسيسيلين 500 مجم', rules_ar='اسم أو كود المنتج.', width=28),
        ColumnSpec('target_qty', 'الكمية المستهدفة', required=True, aliases=['الكمية', 'الرصيد', 'quantity'], sample='100', rules_ar='الرصيد النهائي المطلوب (>= 0)؛ يُحسب الفرق تلقائياً كإذن إضافة أو صرف.', width=18),
        ColumnSpec('unit_cost', 'سعر التكلفة', required=False, aliases=['التكلفة'], sample='85.00', rules_ar='اختياري؛ يُطبق عند وجود إضافة مخزنية.', width=16),
        ColumnSpec('batch_number', 'رقم التشغيلة', required=False, sample='INIT-2026', rules_ar='اختياري.', width=18),
        ColumnSpec('expiry_date', 'تاريخ الصلاحية', required=False, sample='2028-12-31', rules_ar='YYYY-MM-DD (اختياري).', width=18),
    ]

    def prepare_context(self) -> None:
        self._warehouses = {}
        for w in get_scoped_queryset(Warehouse.objects.filter(is_active=True), self.user, 'warehouse'):
            self._warehouses[w.name.strip().lower()] = w
            if w.code:
                self._warehouses[w.code.strip().lower()] = w
        self._products = {}
        for p in Product.objects.all():
            self._products[p.name.strip().lower()] = p
            if p.sku_code:
                self._products[p.sku_code.strip().lower()] = p

    def validate_row(self, row_num, raw, seen):
        errors = []
        wh_ref = _clean_str(raw.get('warehouse'))
        wh = self._warehouses.get(wh_ref.lower()) if wh_ref else None
        if not wh_ref:
            errors.append("المخزن مطلوب.")
        elif not wh:
            errors.append(f"المخزن '{wh_ref}' غير موجود أو خارج نطاقك.")

        prod_ref = _clean_str(raw.get('product'))
        prod = self._products.get(prod_ref.lower()) if prod_ref else None
        if not prod_ref:
            errors.append("المنتج مطلوب.")
        elif not prod:
            errors.append(f"المنتج '{prod_ref}' غير موجود.")

        target_qty, err = parse_int_val(raw.get('target_qty'), 'الكمية المستهدفة', min_val=0)
        if err:
            errors.append(err)
        elif target_qty is None:
            errors.append("الكمية المستهدفة مطلوبة.")

        cost, err = parse_decimal_val(raw.get('unit_cost'), 'سعر التكلفة', default=None)
        if err:
            errors.append(err)

        exp_date, err = parse_date_val(raw.get('expiry_date'), 'تاريخ الصلاحية', default=None)
        if err:
            errors.append(err)

        if wh and prod:
            pair = (wh.id, prod.id)
            seen_pairs = seen.setdefault('stock_pairs', set())
            if pair in seen_pairs:
                errors.append("تكرار نفس الصنف ونفس المخزن داخل الملف.")
            else:
                seen_pairs.add(pair)

            st = InventoryStock.objects.filter(warehouse=wh, product=prod).first()
            curr_qty = int(st.qty_on_hand) if st else 0
            reserved_qty = int(st.qty_reserved) if st else 0
            if target_qty is not None:
                if target_qty < reserved_qty:
                    errors.append(f"الكمية المستهدفة ({target_qty}) أقل من الكمية المحجوزة حالياً ({reserved_qty}).")
                delta = target_qty - curr_qty
                if delta > 0 and not can_user_perform_stock_in(self.user, wh):
                    errors.append(f"غير مصرح لك بالإضافة على المخزن '{wh.name}'.")
                elif delta < 0 and not can_user_perform_stock_out(self.user, wh):
                    errors.append(f"غير مصرح لك بالصرف من المخزن '{wh.name}'.")

        if errors:
            return None, 'error', errors

        st = InventoryStock.objects.filter(warehouse=wh, product=prod).first()
        curr_qty = int(st.qty_on_hand) if st else 0
        delta = target_qty - curr_qty
        return {
            'warehouse_id': wh.id,
            'product_id': prod.id,
            'target_qty': target_qty,
            'delta': delta,
            'unit_cost': str(cost if cost is not None else (prod.default_purchase_cost or Decimal('0.00'))),
            'batch_number': _clean_str(raw.get('batch_number')),
            'expiry_date': exp_date.isoformat() if exp_date else '',
        }, ('update' if st else 'create'), []

    def commit_rows(self, valid_rows):
        inward_by_wh: Dict[int, List[Dict[str, Any]]] = {}
        outward_by_wh: Dict[int, List[Dict[str, Any]]] = {}
        created, updated = 0, 0
        for item in valid_rows:
            d = item['cleaned']
            delta = int(d['delta'])
            if delta > 0:
                inward_by_wh.setdefault(d['warehouse_id'], []).append(d)
                if item['action'] == 'create':
                    created += 1
                else:
                    updated += 1
            elif delta < 0:
                outward_by_wh.setdefault(d['warehouse_id'], []).append(d)
                updated += 1
            else:
                # Zero delta — ensure InventoryStock record exists
                _, was_created = InventoryStock.objects.get_or_create(
                    warehouse_id=d['warehouse_id'],
                    product_id=d['product_id'],
                    defaults={'qty_on_hand': Decimal('0.00'), 'qty_reserved': Decimal('0.00'), 'product_cost': Decimal(d['unit_cost'])},
                )
                if was_created:
                    created += 1
                else:
                    updated += 1

        for wh_id, entries in inward_by_wh.items():
            wh = Warehouse.objects.get(pk=wh_id)
            InventoryMemoService.create_memo(
                warehouse=wh,
                memo_type='inward',
                statement='مطابقة/تحميل أرصدة المخزون عبر Excel',
                items_data=[
                    {
                        'product': e['product_id'],
                        'quantity': int(e['delta']),
                        'unit_cost': Decimal(e['unit_cost']),
                        'batch_number': e['batch_number'],
                        'expiry_date': date.fromisoformat(e['expiry_date']) if e['expiry_date'] else None,
                    }
                    for e in entries
                ],
                user=self.user,
                notes='مستورد من Excel',
            )

        for wh_id, entries in outward_by_wh.items():
            wh = Warehouse.objects.get(pk=wh_id)
            InventoryMemoService.create_memo(
                warehouse=wh,
                memo_type='outward',
                statement='تسوية خصم أرصدة المخزون عبر Excel',
                items_data=[
                    {
                        'product': e['product_id'],
                        'quantity': abs(int(e['delta'])),
                        'batch_number': e['batch_number'],
                    }
                    for e in entries
                ],
                user=self.user,
                notes='مستورد من Excel',
            )

        return created, updated


# Canonical Registry of ALL 10 Approved First-Wave Importers (Users STRICTLY EXCLUDED)
IMPORTER_REGISTRY = {
    'contacts': ContactsExcelImporter,
    'products': ProductsExcelImporter,
    'categories': CategoriesExcelImporter,
    'areas': AreasExcelImporter,
    'warehouses': WarehousesExcelImporter,
    'planned_visits': PlannedVisitsExcelImporter,
    'stock_adjustments': StockAdjustmentsExcelImporter,
    'collections': CollectionsExcelImporter,
    'vendor_payments': VendorPaymentsExcelImporter,
    'inventory_stock': InventoryStockExcelImporter,
}


def get_importer_class(entity_key: str):
    key = (entity_key or '').strip().lower()
    if key in ('users', 'user', 'accounts'):
        # Explicitly forbidden per approved policy
        return None
    return IMPORTER_REGISTRY.get(key)
