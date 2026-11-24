"""
WEA Pharma ERP — Idempotent Excel Data Integration & Reconciliation Engine.

Integrates all 14 WEA Excel workbooks (`wea data/*.xlsx` + `data_folder/users.xlsx`)
into the existing Django ERP schema with ZERO schema migrations, strict idempotency,
atomic transaction safety, and full financial & inventory reconciliation.
"""
import datetime
import logging
import os
import re
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation

import openpyxl
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from accounts.models import Role
from accounts.services import AuditLogService
from catalog.models import Product, ProductCategory
from contacts.models import Contact
from inventory.models import InventoryLot, InventoryMemo, InventoryMemoItem, InventoryStock, Warehouse
from master_data.models import Area
from purchases.models import (
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseReturnOrder,
    PurchaseReturnOrderItem,
)
from sales.models import (
    Collection,
    CustomerAccount,
    CustomerTransaction,
    SalesOrder,
    SalesOrderItem,
    SalesReturnOrder,
    SalesReturnOrderItem,
)
from treasury.models import (
    Vault,
    VaultTransaction,
    VendorAccount,
    VendorInstallment,
    VendorPayment,
    VendorTransaction,
)

logger = logging.getLogger(__name__)
User = get_user_model()


# Canonical cleanup targets (Approved Decision #4)
TEST_WAREHOUSE_CODES = [
    'WH-REP-0107', 'WH-REP-0109', 'WH-REP-0111',
    'WH-SRC-01', 'WH-T1', 'WH-REP-0089',
]
TEST_VAULT_NAMES = [
    'خزنة عهدة - rep_u3', 'خزنة عهدة - rep_t_u', 'خزنة عهدة - rep_t2_u',
    'v_del_test', 'خزنة عهدة - test', 'خزنة عهدة - test (1)',
]
TEST_USERNAMES = ['superadmin_test', 'mgr2', 'test_debug_u']

# Canonical Excel -> DB Vault name mapping
VAULT_NAME_MAP = {
    'خزنة WEA': 'الخزينة الرئيسية - المقر الرئيسي',
    'خزنة ا. عبد الوهاب': 'خزنة عهدة ا. عبد الوهاب',
    'خزنة د. محمد عصام': 'خزنة عهدة د. محمد عصام',
    'خزنة د. محمد البدري': 'خزنة عهدة د. محمد البدري',
    'خزنة د. شهد أشرف': 'خزنة عهدة د. شهد أشرف',
    'خزنة مندوب حلوان': 'خزنة عهدة مندوب حلوان',
    'خزنة د. محمد حاتم': 'خزنة عهدة د. محمد حاتم',
    'خزنة د.أحمد عبدالعظي': 'خزنة عهدة د. أحمد عبد العظيم',
    'خزنة الحسابات': 'خزنة الحسابات',
    'خزنة د. دينا علي': 'خزنة عهدة د. دينا علي',
    'خزنة د. محمد جواد': 'خزنة عهدة د. محمد عبد الجواد',
    'خزنة مندوب المرج': 'خزنة عهدة مندوب المرج',
    'خزنة د. دينا محمد': 'خزنة عهدة د. دينا محمد',
    'خزنة د. ستيفن عياد': 'خزنة عهدة د. ستيفن عياد',
    'خزنة مندوب شبرا خيمة': 'خزنة عهدة مندوب شبرا الخيمة',
}

# Approved Decision #6: authoritative balance override for [W0047]
APPROVED_CUSTOMER_BALANCE_OVERRIDES = {
    'W0047': Decimal('1988.20'),
}


def clean_str(val) -> str:
    if val is None:
        return ''
    s = str(val).strip()
    return '' if s.lower() in ('none', 'nan') else s


def parse_dec(val, default='0.00') -> Decimal:
    if val is None:
        return Decimal(default)
    s = str(val).strip().replace(',', '')
    if not s or s.lower() in ('none', 'nan'):
        return Decimal(default)
    try:
        return Decimal(s).quantize(Decimal('0.01'))
    except (InvalidOperation, ValueError):
        return Decimal(default)


def parse_dt(val):
    if val is None:
        return None
    if isinstance(val, datetime.datetime):
        return timezone.make_aware(val) if timezone.is_naive(val) else val
    if isinstance(val, datetime.date):
        return timezone.make_aware(datetime.datetime.combine(val, datetime.time.min))
    s = str(val).strip()
    if not s or s.lower() in ('none', 'nan'):
        return None
    for fmt in (
        '%d/%m/%Y %I:%M %p',
        '%d/%m/%Y %H:%M:%S',
        '%d/%m/%Y %H:%M',
        '%d/%m/%Y',
        '%Y-%m-%dT%H:%M:%S.%fZ',
        '%Y-%m-%dT%H:%M:%SZ',
        '%Y-%m-%d %H:%M:%S',
        '%Y-%m-%d',
    ):
        try:
            dt = datetime.datetime.strptime(s, fmt)
            return timezone.make_aware(dt) if timezone.is_naive(dt) else dt
        except ValueError:
            continue
    return None


def parse_date(val):
    dt = parse_dt(val)
    return dt.date() if dt else None


def load_xlsx_rows(filepath: str):
    """Loads active worksheet safely, resetting malformed dimension tags."""
    if not os.path.exists(filepath):
        return [], []
    wb = openpyxl.load_workbook(filepath, read_only=True, data_only=True)
    ws = wb.active
    ws.reset_dimensions()
    rows = list(ws.iter_rows(values_only=True))
    wb.close()
    if not rows:
        return [], []
    headers = [str(h).strip() if h is not None else '' for h in rows[0]]
    while headers and headers[-1] == '':
        headers.pop()
    ncols = len(headers)
    data = []
    for r in rows[1:]:
        vals = list(r[:ncols])
        if any(v is not None and str(v).strip() != '' for v in vals):
            data.append(dict(zip(headers, vals)))
    return headers, data


def parse_ref_int(val):
    """Extracts integer serial from '#16846' or '16846'."""
    s = clean_str(val).lstrip('#')
    return int(s) if s.isdigit() else None


def _has_fk_references(obj) -> list:
    refs = []
    for rel in obj._meta.related_objects:
        accessor = rel.get_accessor_name()
        try:
            mgr = getattr(obj, accessor)
            cnt = mgr.count() if hasattr(mgr, 'count') else (1 if mgr else 0)
            if cnt > 0:
                refs.append(f'{rel.related_model._meta.label}:{cnt}')
        except Exception:
            continue
    return refs


class WeaDataIntegrationService:
    """
    Orchestrates full idempotent integration of WEA Pharma Excel datasets
    into the existing Django ERP database without altering the schema.
    """

    def __init__(self, wea_dir='wea data', data_dir='data_folder'):
        self.wea_dir = wea_dir
        self.data_dir = data_dir
        self.stats = defaultdict(int)
        self.warnings = []
        self.discrepancies = []

        # In-memory lookup maps populated during execution
        self.user_by_uuid = {}
        self.user_by_name = {}
        self.default_admin = None
        self.wh_by_name = {}
        self.wh_by_user_id = {}
        self.main_wh = None
        self.supplies_wh = None
        self.vault_by_excel_name = {}
        self.vault_by_user_id = {}
        self.main_vault = None
        self.prod_by_sku = {}
        self.contact_by_serial = {}
        self.contact_by_code = {}
        self.memo_by_source = {}  # (source_type, source_uuid) -> InventoryMemo

    def _load_all_sources(self):
        def _p(fname):
            return os.path.join(self.wea_dir, fname)

        self.users_xlsx = load_xlsx_rows(os.path.join(self.data_dir, 'users.xlsx'))[1]
        self.inv_rows = load_xlsx_rows(_p('inventory stock.xlsx'))[1]
        self.memo_rows = load_xlsx_rows(_p('memos.xlsx'))[1]
        self.po_rows = load_xlsx_rows(_p('purchases orders.xlsx'))[1]
        self.pro_rows = load_xlsx_rows(_p('purchses return.xlsx'))[1]
        self.vp_rows = load_xlsx_rows(_p('vendor-payments.xlsx'))[1]
        self.va_rows = load_xlsx_rows(_p('vendors accounts.xlsx'))[1]
        self.vt_rows = load_xlsx_rows(_p('vendor transactions.xlsx'))[1]
        self.so_rows = load_xlsx_rows(_p('sales orders.xlsx'))[1]
        self.sro_rows = load_xlsx_rows(_p('sales return orders.xlsx'))[1]
        self.col_rows = load_xlsx_rows(_p('collections.xlsx'))[1]
        self.ca_rows = load_xlsx_rows(_p('customers accounts.xlsx'))[1]
        self.ct1_rows = load_xlsx_rows(_p('customer transactions 1.xlsx'))[1]
        self.ct2_rows = load_xlsx_rows(_p('customer transactions 2.xlsx'))[1]
        self.vtx_rows = load_xlsx_rows(_p('vaults transactions.xlsx'))[1]

    @transaction.atomic
    def run(self, dry_run=False):
        self._load_all_sources()

        self.default_admin = (
            User.objects.filter(username__iexact='wea.pharm2020@gmail.com').first()
            or User.objects.filter(is_superuser=True).first()
        )

        # 1. Safe Database Cleanup (Approved Decisions #4 & #7)
        self._cleanup_existing_db()

        # 2. Users & Inactive Historical Archive Users (Approved Decision #3)
        self._sync_users_and_historical_archives()

        # 3. Product Categories & Products
        self._sync_products()

        # 4. Warehouses & Vaults
        self._sync_warehouses_and_vaults()

        # 5. Missing Suppliers & Customers
        self._sync_contacts()

        # 6. Authoritative Inventory Stock & Lots (from inventory stock.xlsx)
        self._import_inventory_stock()

        # 7. Inventory Memos (from memos.xlsx — provides exact historical warehouses!)
        self._import_memos()

        # 8. Purchases, Purchase Returns, Vendor Accounts, Transactions, Installments & Payments
        self._import_purchases_chain()

        # 9. Sales Orders, Sales Returns, Collections, Customer Accounts & Transactions
        self._import_sales_chain()

        # 10. Vault Transactions & Reconciled Vault Closing Balances
        self._import_vault_transactions()

        # 11. Audit Log Summary
        if not dry_run and self.default_admin:
            AuditLogService.log(
                action_type='WEA_DATA_INTEGRATION_COMPLETED',
                module='master_data',
                actor=self.default_admin,
                record_id=0,
                record_name='WEA ERP Data Integration',
                description=(
                    f"اكتمل دمج بيانات WEA ERP: "
                    f"أوامر شراء={self.stats['po_total']}, أوامر بيع={self.stats['so_total']}, "
                    f"تحصيلات={self.stats['collections_total']}, حركات خزن={self.stats['vault_tx_total']}"
                ),
                new_values=dict(self.stats),
            )

        reconciliation = self.verify_reconciliation()

        if dry_run:
            transaction.set_rollback(True)

        return {
            'stats': dict(self.stats),
            'warnings': self.warnings,
            'discrepancies': self.discrepancies,
            'reconciliation': reconciliation,
        }

    # ------------------------------------------------------------------
    # STEP 1: SAFE DATABASE CLEANUP
    # ------------------------------------------------------------------
    def _cleanup_existing_db(self):
        # 1a. Delete 6 test warehouses only if zero FK references
        for w in Warehouse.objects.filter(code__in=TEST_WAREHOUSE_CODES):
            refs = _has_fk_references(w)
            if not refs:
                w.delete()
                self.stats['cleanup_test_warehouses_deleted'] += 1
            else:
                w.is_active = False
                w.save(update_fields=['is_active'])
                self.stats['cleanup_test_warehouses_deactivated'] += 1
                self.warnings.append(f"Warehouse {w.code} had refs {refs}; deactivated instead of deleted.")

        # 1b. Delete 6 test vaults by exact test name only if zero FK references
        for v in Vault.objects.filter(name__in=TEST_VAULT_NAMES):
            refs = _has_fk_references(v)
            if not refs:
                v.delete()
                self.stats['cleanup_test_vaults_deleted'] += 1
            else:
                v.is_active = False
                v.save(update_fields=['is_active'])
                self.stats['cleanup_test_vaults_deactivated'] += 1
                self.warnings.append(f"Vault {v.name!r} had refs {refs}; deactivated instead of deleted.")

        # 1c. Reassign Warehouse.manager from superadmin_test before deleting test users
        sa_test = User.objects.filter(username='superadmin_test').first()
        if sa_test and self.default_admin:
            reassigned = Warehouse.objects.filter(manager=sa_test).update(manager=self.default_admin)
            self.stats['cleanup_warehouse_managers_reassigned'] += reassigned

        for u in User.objects.filter(username__in=TEST_USERNAMES):
            refs = _has_fk_references(u)
            if not refs:
                u.delete()
                self.stats['cleanup_test_users_deleted'] += 1
            else:
                u.is_active = False
                u.save(update_fields=['is_active'])
                self.stats['cleanup_test_users_deactivated'] += 1
                self.warnings.append(f"User {u.username} had refs {refs}; deactivated instead of deleted.")

        # 1d. Clean literal 'nan' codes on Contacts
        cleaned_nan = Contact.objects.filter(code='nan').update(code='')
        self.stats['cleanup_nan_codes_fixed'] += cleaned_nan

        # 1e. Set is_customer=False on pure suppliers (not present in customer files)
        cust_serials = set()
        for r in self.ca_rows:
            if r.get('Contact_SerialNum'):
                cust_serials.add(int(r['Contact_SerialNum']))
        for r in self.so_rows:
            if r.get('العميل - مسلسل'):
                cust_serials.add(int(r['العميل - مسلسل']))
        for r in self.sro_rows:
            if r.get('العميل - مسلسل'):
                cust_serials.add(int(r['العميل - مسلسل']))
        for r in self.col_rows:
            if r.get('رقم تسلسل العميل'):
                cust_serials.add(int(r['رقم تسلسل العميل']))

        pure_supp_qs = Contact.objects.filter(is_supplier=True, is_customer=True).exclude(serial_num__in=cust_serials)
        self.stats['cleanup_pure_suppliers_fixed'] += pure_supp_qs.update(is_customer=False)

        # 1f. Rename WH-REP-0095 -> 'عهدة د. أحمد عبد العظيم'
        wh_feisal = Warehouse.objects.filter(code='WH-REP-0095').first()
        if wh_feisal and wh_feisal.name != 'عهدة د. أحمد عبد العظيم':
            wh_feisal.name = 'عهدة د. أحمد عبد العظيم'
            wh_feisal.save(update_fields=['name'])
            self.stats['cleanup_wh_0095_renamed'] += 1

        # 1g. Approved Decision #7: Rename supplier #16031
        supp_16031 = Contact.objects.filter(serial_num=16031).first()
        if supp_16031 and supp_16031.name != 'مصنع بايوفيردا لمستحضرات التجميل':
            old_name = supp_16031.name
            supp_16031.name = 'مصنع بايوفيردا لمستحضرات التجميل'
            if old_name and old_name not in (supp_16031.notes or ''):
                supp_16031.notes = ((supp_16031.notes or '') + f"\nالاسم السابق: {old_name}").strip()
            supp_16031.save(update_fields=['name', 'notes'])
            self.stats['cleanup_supplier_16031_renamed'] += 1

    # ------------------------------------------------------------------
    # STEP 2: USERS & INACTIVE ARCHIVE USERS
    # ------------------------------------------------------------------
    def _sync_users_and_historical_archives(self):
        db_by_email = {u.username.lower(): u for u in User.objects.all()}
        for u in User.objects.all():
            if u.email:
                db_by_email.setdefault(u.email.lower(), u)

        # Map users.xlsx (18 users)
        for r in self.users_xlsx:
            uid = clean_str(r.get('id'))
            email = clean_str(r.get('email')).lower()
            name = clean_str(r.get('name'))
            user = db_by_email.get(email)
            if user:
                if name and not user.first_name:
                    User.objects.filter(pk=user.pk).update(first_name=name[:150])
                    user.first_name = name[:150]
                self.user_by_uuid[uid] = user
                if name:
                    self.user_by_name[name] = user
                    self.user_by_name[name.strip()] = user

        # Also map known alias names found in memos/transactions
        alias_to_email = {
            'Dina Mohamed (Maadi&Helwan)': 'wea.maadi2@gmail.com',
            'Mohamed Albadry ( Imbaba )': 'wea.imbaba@gmail.com',
        }
        for alias, em in alias_to_email.items():
            if em in db_by_email:
                self.user_by_name[alias] = db_by_email[em]

        # Collect all historical user UUIDs & names across all files
        historical_uuid_names = {}
        for rows, id_col, name_col in [
            (self.po_rows, 'المنشء - المعرف', 'المنشء - الاسم'),
            (self.pro_rows, 'المنشء - المعرف', 'المنشء - الاسم'),
            (self.vp_rows, 'id المنشء', 'اسم المنشء'),
            (self.vt_rows, 'نفذ بواسطة - المعرف', 'نفذ بواسطة - الاسم'),
            (self.so_rows, 'المنشء - المعرف', 'المنشء - الاسم'),
            (self.sro_rows, 'المنشء - المعرف', 'المنشء - الاسم'),
            (self.col_rows, 'id المنشء', 'اسم المنشء'),
            (self.ct1_rows, 'نفذ بواسطة - المعرف', 'نفذ بواسطة - الاسم'),
            (self.ct2_rows, 'نفذ بواسطة - المعرف', 'نفذ بواسطة - الاسم'),
            (self.vtx_rows, 'نفذ بواسطة - المعرف', 'نفذ بواسطة - الاسم'),
        ]:
            for r in rows:
                uid = clean_str(r.get(id_col))
                uname = clean_str(r.get(name_col))
                if uid and uid not in self.user_by_uuid and uid not in historical_uuid_names:
                    historical_uuid_names[uid] = uname or f'Historical User {uid[:8]}'

        # Create inactive archive accounts (role=None, is_active=False -> no rep provisioning!)
        for uid, uname in sorted(historical_uuid_names.items()):
            short_id = uid.replace('-', '')[:12]
            archive_username = f"archive_{short_id}@wea.local"
            user, created = User.objects.get_or_create(
                username=archive_username,
                defaults={
                    'email': archive_username,
                    'first_name': uname[:150],
                    'is_active': False,
                    'is_staff': False,
                    'is_superuser': False,
                    'role': None,
                },
            )
            if created:
                user.set_unusable_password()
                user.save(update_fields=['password'])
                self.stats['historical_users_created'] += 1
            else:
                if user.is_active:
                    user.is_active = False
                    user.save(update_fields=['is_active'])
            self.user_by_uuid[uid] = user
            if uname and uname not in self.user_by_name:
                self.user_by_name[uname] = user

        # Check any creator names in memos.xlsx not yet mapped (e.g. 'Islam Maher')
        for r in self.memo_rows:
            cname = clean_str(r.get('Creator Name'))
            if cname and cname not in self.user_by_name:
                slug = re.sub(r'[^a-zA-Z0-9]+', '_', cname.lower()).strip('_') or 'memo_user'
                archive_username = f"archive_{slug}@wea.local"
                user, created = User.objects.get_or_create(
                    username=archive_username,
                    defaults={
                        'email': archive_username,
                        'first_name': cname[:150],
                        'is_active': False,
                        'is_staff': False,
                        'is_superuser': False,
                        'role': None,
                    },
                )
                if created:
                    user.set_unusable_password()
                    user.save(update_fields=['password'])
                    self.stats['historical_users_created'] += 1
                self.user_by_name[cname] = user

    def _resolve_user(self, uid='', name=''):
        u = self.user_by_uuid.get(clean_str(uid))
        if u:
            return u
        u = self.user_by_name.get(clean_str(name))
        return u or self.default_admin

    # ------------------------------------------------------------------
    # STEP 3: PRODUCT CATEGORIES & PRODUCTS
    # ------------------------------------------------------------------
    def _sync_products(self):
        cat_wea, _ = ProductCategory.objects.get_or_create(
            code='WEA', defaults={'name': 'WEA', 'description': 'منتجات شركة WEA فارما'}
        )
        cat_pack, _ = ProductCategory.objects.get_or_create(
            code='PACK-MAT', defaults={'name': 'Packing materials', 'description': 'مستلزمات ومواد التعبئة والتغليف'}
        )
        cat_map = {'WEA': cat_wea, 'Packing materials': cat_pack}

        # Discover all products across inv_stock, PO, PRO, SO, SRO
        discovered = {}
        for r in self.inv_rows:
            sku = clean_str(r.get('الكود'))
            if sku and sku not in discovered:
                price_val = next((v for k, v in r.items() if 'سعر' in k), None)
                discovered[sku] = {
                    'name': clean_str(r.get('المنتج')),
                    'cat': clean_str(r.get('التصنيف')) or 'WEA',
                    'retail_price': parse_dec(price_val),
                    'cost': parse_dec(r.get('التكلفة')),
                }
        for rows in (self.po_rows, self.pro_rows, self.so_rows, self.sro_rows):
            for r in rows:
                sku = clean_str(r.get('العناصر - المنتج - الكود'))
                if sku and sku not in discovered:
                    discovered[sku] = {
                        'name': clean_str(r.get('العناصر - المنتج - الاسم')),
                        'cat': clean_str(r.get('العناصر - المنتج - التصنيف')) or 'WEA',
                        'retail_price': parse_dec(r.get('العناصر - المنتج - سعر القطعة')),
                        'cost': parse_dec(r.get('العناصر - سعر القطعة')),
                    }

        for sku, info in discovered.items():
            existing = Product.objects.filter(sku_code=sku).first()
            if existing:
                self.prod_by_sku[sku] = existing
            else:
                cat = cat_map.get(info['cat'], cat_wea)
                is_sellable = (cat == cat_wea)
                prod = Product.objects.create(
                    sku_code=sku,
                    name=info['name'] or sku,
                    category=cat,
                    retail_price=info['retail_price'] if is_sellable else Decimal('0.00'),
                    default_purchase_cost=info['cost'],
                    unit='عبوة (Pack)',
                    sellable=is_sellable,
                    is_active=True,
                    created_by=self.default_admin,
                )
                self.prod_by_sku[sku] = prod
                self.stats['products_created'] += 1

        # Refresh map with all existing DB products
        for p in Product.objects.select_related('category').all():
            self.prod_by_sku[p.sku_code.strip()] = p

    # ------------------------------------------------------------------
    # STEP 4: WAREHOUSES & VAULTS
    # ------------------------------------------------------------------
    def _sync_warehouses_and_vaults(self):
        for w in Warehouse.objects.select_related('assigned_user').all():
            self.wh_by_name[w.name.strip()] = w
            if w.assigned_user_id:
                self.wh_by_user_id[w.assigned_user_id] = w

        self.main_wh = (
            Warehouse.objects.filter(code='WH-MAIN-01').first()
            or Warehouse.objects.filter(is_main=True).first()
        )
        self.supplies_wh = (
            Warehouse.objects.filter(code='WH-SUPPLIES-01').first()
            or self.main_wh
        )

        # Ensure 'خزنة الحسابات' exists
        acc_vault, created = Vault.objects.get_or_create(
            name='خزنة الحسابات',
            defaults={
                'vault_type': 'cash',
                'is_rep_vault': False,
                'is_active': True,
                'current_balance': Decimal('0.00'),
            },
        )
        if created:
            self.stats['vaults_created'] += 1

        db_vaults_by_name = {v.name.strip(): v for v in Vault.objects.select_related('assigned_user').all()}
        for v in db_vaults_by_name.values():
            if v.assigned_user_id:
                self.vault_by_user_id[v.assigned_user_id] = v

        for excel_name, db_name in VAULT_NAME_MAP.items():
            v = db_vaults_by_name.get(db_name)
            if v:
                self.vault_by_excel_name[excel_name] = v
                self.vault_by_excel_name[db_name] = v

        self.main_vault = (
            db_vaults_by_name.get('الخزينة الرئيسية - المقر الرئيسي')
            or Vault.objects.filter(is_rep_vault=False, is_active=True).first()
        )

    # ------------------------------------------------------------------
    # STEP 5: CONTACTS (SUPPLIERS & CUSTOMERS)
    # ------------------------------------------------------------------
    def _sync_contacts(self):
        for c in Contact.objects.all():
            self.contact_by_serial[c.serial_num] = c
            if c.code and c.code.strip():
                self.contact_by_code[c.code.strip()] = c

        area_by_code = {a.code.strip(): a for a in Area.objects.all() if a.code}

        # 5a. Ensure all vendors from VA / PO / VP exist
        vendor_records = {}
        for r in self.va_rows:
            ser = int(r['Contact_SerialNum'])
            vendor_records[ser] = {
                'name': clean_str(r.get('Contact_Name')),
                'mobile': clean_str(r.get('Contact_Mobile')),
                'phone': clean_str(r.get('Contact_Phone')),
                'notes': clean_str(r.get('Contact_Note')),
                'area_code': clean_str(r.get('Contact_AreaID')),
            }
        for r in self.po_rows:
            ser = int(r['العميل - مسلسل'])
            if ser not in vendor_records:
                vendor_records[ser] = {
                    'name': clean_str(r.get('العميل - الاسم')),
                    'mobile': '', 'phone': '', 'notes': '',
                    'area_code': clean_str(r.get('العميل - المنطقة - الكود')),
                }

        for ser, info in vendor_records.items():
            c = self.contact_by_serial.get(ser)
            if not c:
                area_obj = area_by_code.get(info['area_code'])
                gov = area_obj.parent if (area_obj and area_obj.parent) else area_obj
                brick = area_obj if (area_obj and area_obj.parent) else None
                c = Contact.objects.create(
                    serial_num=ser,
                    name=info['name'] or f"مورد #{ser}",
                    contact_type='organization',
                    is_supplier=True,
                    is_customer=False,
                    mobile=info['mobile'][:30],
                    phone=info['phone'][:30],
                    notes=info['notes'],
                    area=gov,
                    brick=brick,
                    status='customer',
                    created_by=self.default_admin,
                )
                self.contact_by_serial[ser] = c
                self.stats['suppliers_created'] += 1
            elif not c.is_supplier:
                c.is_supplier = True
                c.save(update_fields=['is_supplier'])

        # 5b. Ensure all missing customers from CA / SO / SRO / COL exist
        missing_cust_info = {}
        for r in self.ca_rows:
            ser = int(r['Contact_SerialNum'])
            if ser not in self.contact_by_serial and ser not in missing_cust_info:
                missing_cust_info[ser] = {
                    'name': clean_str(r.get('Contact_Name')),
                    'code': clean_str(r.get('Contact_Code')),
                    'mobile': clean_str(r.get('Contact_Mobile')),
                    'phone': clean_str(r.get('Contact_Phone')),
                    'account_type': clean_str(r.get('Contact_Extra_account_type')),
                    'customer_category': clean_str(r.get('Contact_Extra_class')),
                    'specialty': clean_str(r.get('Contact_Extra_specialty')),
                    'area_code': clean_str(r.get('Contact_AreaID')),
                    'gov_code': '',
                }
        for rows in (self.so_rows, self.sro_rows):
            for r in rows:
                ser = int(r['العميل - مسلسل'])
                if ser not in self.contact_by_serial and ser not in missing_cust_info:
                    missing_cust_info[ser] = {
                        'name': clean_str(r.get('العميل - الاسم')),
                        'code': clean_str(r.get('العميل - الكود')),
                        'mobile': '', 'phone': '',
                        'account_type': '', 'customer_category': '', 'specialty': '',
                        'area_code': clean_str(r.get('العميل - المنطقة - الكود')),
                        'gov_code': clean_str(r.get('العميل - المنطقة - المنطقة الرئيسية - الكود')),
                    }
        for r in self.col_rows:
            ser = int(r['رقم تسلسل العميل'])
            if ser not in self.contact_by_serial and ser not in missing_cust_info:
                missing_cust_info[ser] = {
                    'name': clean_str(r.get('اسم العميل')),
                    'code': clean_str(r.get('كود العميل')),
                    'mobile': clean_str(r.get('رقم محمول العميل')),
                    'phone': '', 'account_type': '', 'customer_category': '', 'specialty': '',
                    'area_code': clean_str(r.get('كود المنطقة')),
                    'gov_code': clean_str(r.get('كود المنطقة الرئيسية')),
                }

        for ser, info in missing_cust_info.items():
            sub_area = area_by_code.get(info['area_code'])
            gov_area = area_by_code.get(info['gov_code']) or (sub_area.parent if sub_area and sub_area.parent else sub_area)
            brick_area = sub_area if (sub_area and sub_area.parent) else None
            c = Contact.objects.create(
                serial_num=ser,
                name=info['name'] or f"عميل #{ser}",
                code=info['code'],
                contact_type='organization',
                is_customer=True,
                is_supplier=False,
                mobile=info['mobile'][:30],
                phone=info['phone'][:30],
                account_type=info['account_type'][:100],
                customer_category=info['customer_category'][:10],
                specialty=info['specialty'][:150],
                area=gov_area,
                brick=brick_area,
                status='customer',
                created_by=self.default_admin,
            )
            self.contact_by_serial[ser] = c
            if c.code:
                self.contact_by_code[c.code] = c
            self.stats['customers_created'] += 1

    # ------------------------------------------------------------------
    # STEP 6: AUTHORITATIVE INVENTORY STOCK & LOTS
    # ------------------------------------------------------------------
    def _import_inventory_stock(self):
        grouped = defaultdict(list)
        for r in self.inv_rows:
            wh_name = clean_str(r.get('المخزن'))
            sku = clean_str(r.get('الكود'))
            wh = self.wh_by_name.get(wh_name)
            prod = self.prod_by_sku.get(sku)
            if not wh or not prod:
                self.warnings.append(f"Skipped inventory stock row: wh={wh_name!r}, sku={sku!r}")
                continue
            grouped[(wh, prod)].append(r)

        for (wh, prod), rows in grouped.items():
            total_on_hand = Decimal('0.00')
            total_reserved = Decimal('0.00')
            weighted_cost_num = Decimal('0.00')
            weighted_cost_den = Decimal('0.00')
            fallback_cost = None

            lot_agg = defaultdict(Decimal)
            for r in rows:
                qty = parse_dec(r.get('فى المخزن'))
                res = parse_dec(r.get('محجوز'))
                cost_raw = r.get('التكلفة')
                cost = parse_dec(cost_raw) if cost_raw is not None and str(cost_raw).strip() != '' else None

                total_on_hand += qty
                total_reserved += res
                if cost is not None:
                    if fallback_cost is None:
                        fallback_cost = cost
                    if qty > 0:
                        weighted_cost_num += qty * cost
                        weighted_cost_den += qty

                batch = clean_str(r.get('رقم التشغيل'))
                expiry = parse_date(r.get('تاريخ الصلاحية'))
                if (batch or expiry) and qty > 0:
                    lot_agg[(batch or 'DEFAULT', expiry)] += qty

            if weighted_cost_den > 0:
                avg_cost = (weighted_cost_num / weighted_cost_den).quantize(Decimal('0.01'))
            elif fallback_cost is not None:
                avg_cost = fallback_cost
            else:
                avg_cost = prod.default_purchase_cost or Decimal('0.00')

            stock, created = InventoryStock.objects.update_or_create(
                warehouse=wh,
                product=prod,
                defaults={
                    'qty_on_hand': total_on_hand,
                    'qty_reserved': total_reserved,
                    'product_cost': avg_cost,
                },
            )
            self.stats['inventory_stock_created' if created else 'inventory_stock_updated'] += 1

            for (batch, expiry), lqty in lot_agg.items():
                _, lcreated = InventoryLot.objects.update_or_create(
                    stock=stock,
                    batch_number=batch,
                    expiry_date=expiry,
                    defaults={'quantity': lqty},
                )
                self.stats['inventory_lots_created' if lcreated else 'inventory_lots_updated'] += 1

    # ------------------------------------------------------------------
    # STEP 7: INVENTORY MEMOS (from memos.xlsx)
    # ------------------------------------------------------------------
    def _import_memos(self):
        existing_memos = {m.memo_number: m for m in InventoryMemo.objects.all()}
        to_create = []
        created_meta = []  # (memo_number, creation_dt)

        type_label_ar = {
            'unstock': 'صرف مخزني',
            'stock': 'إضافة مخزنية',
            'transfer_out': 'تحويل مخزني صادر',
            'transfer_in': 'تحويل مخزني وارد',
            'adjustment': 'تسوية / رصيد مخزني',
        }

        for r in self.memo_rows:
            ser = r.get('Serial Number')
            if ser is None:
                continue
            memo_number = f"MEMO-{int(ser)}"
            wh_name = clean_str(r.get('Warehouse Name'))
            wh = self.wh_by_name.get(wh_name) or self.main_wh
            raw_type = clean_str(r.get('Type')).lower()
            memo_type = 'outward' if raw_type in ('unstock', 'transfer_out') else 'inward'
            raw_status = clean_str(r.get('Status Name')).lower()
            status = 'draft' if raw_status == 'staged' else 'applied'

            src_type = clean_str(r.get('Source Type'))
            src_id = clean_str(r.get('Source ID'))
            src_num = clean_str(r.get('Source Number'))
            tr_num = clean_str(r.get('Transfer Serial Number'))
            note = clean_str(r.get('Note'))
            contact_name = clean_str(r.get('Source Contact Name'))

            stmt_parts = [type_label_ar.get(raw_type, raw_type)]
            if src_num:
                stmt_parts.append(src_num)
            elif tr_num:
                stmt_parts.append(f"تحويل #{tr_num}")
            if contact_name:
                stmt_parts.append(f"- {contact_name}")
            statement = ' '.join(stmt_parts)[:255]

            done_dt = parse_dt(r.get('Done At'))
            create_dt = parse_dt(r.get('Creation Time')) or done_dt or timezone.now()
            creator = self._resolve_user(name=r.get('Creator Name'))

            if memo_number in existing_memos:
                memo_obj = existing_memos[memo_number]
            else:
                memo_obj = InventoryMemo(
                    memo_number=memo_number,
                    memo_type=memo_type,
                    warehouse=wh,
                    statement=statement,
                    status=status,
                    applied_at=done_dt,
                    notes=note,
                    created_by=creator,
                )
                to_create.append(memo_obj)
                created_meta.append((memo_number, create_dt))

        if to_create:
            InventoryMemo.objects.bulk_create(to_create, batch_size=1000)
            self.stats['memos_created'] += len(to_create)
            # Re-fetch & preserve historical created_at timestamps
            all_memos = {m.memo_number: m for m in InventoryMemo.objects.select_related('warehouse').all()}
            to_update_ts = []
            for mnum, cdt in created_meta:
                m = all_memos.get(mnum)
                if m and cdt:
                    m.created_at = cdt
                    to_update_ts.append(m)
            if to_update_ts:
                InventoryMemo.objects.bulk_update(to_update_ts, ['created_at'], batch_size=1000)
        else:
            all_memos = {m.memo_number: m for m in InventoryMemo.objects.select_related('warehouse').all()}

        self.stats['memos_total'] = len(all_memos)

        # Build lookup: (source_type, source_uuid) -> latest InventoryMemo
        for r in self.memo_rows:
            ser = r.get('Serial Number')
            src_type = clean_str(r.get('Source Type'))
            src_id = clean_str(r.get('Source ID'))
            if ser is not None and src_type and src_id:
                m = all_memos.get(f"MEMO-{int(ser)}")
                if m:
                    self.memo_by_source[(src_type, src_id)] = m

    # ------------------------------------------------------------------
    # STEP 8: PURCHASES, RETURNS, VENDOR ACCOUNTS, TRANSACTIONS & PAYMENTS
    # ------------------------------------------------------------------
    def _import_purchases_chain(self):
        # 8a. Group Purchase Orders by UUID
        po_groups = defaultdict(list)
        for r in self.po_rows:
            uid = clean_str(r.get('المعرف'))
            if uid:
                po_groups[uid].append(r)

        po_by_uuid = {}
        used_memo_ids = set(PurchaseOrder.objects.exclude(memo__isnull=True).values_list('memo_id', flat=True))

        for uid, rows in po_groups.items():
            r0 = rows[0]
            serial_num = int(r0['مسلسل'])
            order_number = clean_str(r0.get('الرقم')) or f"#{serial_num}"
            supplier = self.contact_by_serial[int(r0['العميل - مسلسل'])]
            creator = self._resolve_user(r0.get('المنشء - المعرف'), r0.get('المنشء - الاسم'))

            # Exact warehouse from memos.xlsx first, then fallback by product category
            linked_memo = self.memo_by_source.get(('purchase_order', uid))
            if linked_memo:
                target_wh = linked_memo.warehouse
                self.stats['po_wh_from_memo'] += 1
            else:
                cats = {clean_str(x.get('العناصر - المنتج - التصنيف')) for x in rows}
                target_wh = self.supplies_wh if cats == {'Packing materials'} else self.main_wh
                self.stats['po_wh_from_fallback'] += 1

            raw_status = clean_str(r0.get('الحالة - الاسم')).lower()
            status = 'picked' if raw_status == 'picked' else 'settled'

            before_disc = parse_dec(r0.get('السعر قبل كل الخصومات'))
            after_disc = parse_dec(r0.get('السعر بعد كل الخصومات'))
            extra_disc_pct = parse_dec(r0.get('الخصم الإضافي - نسبة'))
            extra_disc_amt = parse_dec(r0.get('الخصم الإضافي - قيمة'))
            grand_total = parse_dec(r0.get('الإجمالي النهائي'))
            shipping_fees = max(Decimal('0.00'), grand_total - after_disc)

            memo_to_link = linked_memo if (linked_memo and linked_memo.id not in used_memo_ids) else None
            if memo_to_link:
                used_memo_ids.add(memo_to_link.id)

            po, created = PurchaseOrder.objects.update_or_create(
                serial_num=serial_num,
                defaults={
                    'order_number': order_number,
                    'supplier': supplier,
                    'target_warehouse': target_wh,
                    'order_date': parse_date(r0.get('تاريخ الإنشاء')) or timezone.now().date(),
                    'due_date': parse_date(r0.get('تاريخ الاستحقاق')),
                    'stocked_at': parse_dt(r0.get('تاريخ التخزين')),
                    'invoiced_at': parse_dt(r0.get('تاريخ إصدار الفاتورة')),
                    'status': status,
                    'payment_status': 'credit',
                    'memo': memo_to_link,
                    'items_count': len(rows),
                    'items_quantity': sum((parse_dec(x.get('العناصر - الكمية')) for x in rows), Decimal('0.00')),
                    'subtotal': before_disc,
                    'items_discount_total': max(Decimal('0.00'), before_disc - after_disc - extra_disc_amt),
                    'custom_discount_percentage': extra_disc_pct,
                    'custom_discount_amount': extra_disc_amt,
                    'tax_amount': Decimal('0.00'),
                    'shipping_fees': shipping_fees,
                    'grand_total': grand_total,
                    'notes': clean_str(r0.get('ملاحظة')),
                    'created_by': creator,
                    'updated_by': creator,
                    'approved_by': creator,
                    'approved_at': parse_dt(r0.get('تاريخ الإنشاء')),
                },
            )
            po_by_uuid[uid] = po
            self.stats['po_created' if created else 'po_updated'] += 1

            if created or not po.items.exists():
                po.items.all().delete()
                for idx, itm in enumerate(rows, start=1):
                    prod = self.prod_by_sku[clean_str(itm.get('العناصر - المنتج - الكود'))]
                    qty = parse_dec(itm.get('العناصر - الكمية'))
                    price = parse_dec(itm.get('العناصر - سعر القطعة'))
                    line_sub = (qty * price).quantize(Decimal('0.01'))
                    line_tot = parse_dec(itm.get('العناصر - الكلي'))
                    disc_pct = parse_dec(itm.get('العناصر - خصم القطعة %'))
                    disc_amt = max(Decimal('0.00'), line_sub - line_tot)
                    PurchaseOrderItem.objects.bulk_create([
                        PurchaseOrderItem(
                            order=po,
                            item_order=idx,
                            product=prod,
                            quantity=qty,
                            unit_price=price,
                            product_batch_number=clean_str(itm.get('العناصر - رقم تشغيل المنتج')),
                            product_expiry_date=parse_date(itm.get('العناصر - تاريخ صلاحية المنتج')),
                            discount_percentage=disc_pct,
                            discount_amount=disc_amt,
                            tax_percentage=Decimal('0.00'),
                            tax_amount=Decimal('0.00'),
                            subtotal=line_sub,
                            total_price=line_tot,
                        )
                    ])
                    if memo_to_link and not memo_to_link.items.filter(product=prod, quantity=qty).exists():
                        InventoryMemoItem.objects.create(
                            memo=memo_to_link,
                            product=prod,
                            quantity=qty,
                            unit_cost=price,
                            batch_number=clean_str(itm.get('العناصر - رقم تشغيل المنتج')),
                            expiry_date=parse_date(itm.get('العناصر - تاريخ صلاحية المنتج')),
                        )

        self.stats['po_total'] = len(po_by_uuid)

        # 8b. Purchase Returns (1 row: #3)
        for r in self.pro_rows:
            serial_num = int(r['مسلسل'])
            order_number = clean_str(r.get('الرقم')) or f"#RO-{serial_num}"
            supplier = self.contact_by_serial[int(r['العميل - مسلسل'])]
            creator = self._resolve_user(r.get('المنشء - المعرف'), r.get('المنشء - الاسم'))
            prod = self.prod_by_sku[clean_str(r.get('العناصر - المنتج - الكود'))]
            qty = parse_dec(r.get('العناصر - الكمية'))
            price = parse_dec(r.get('العناصر - سعر القطعة'))
            tot = parse_dec(r.get('الإجمالي النهائي'))

            pro, created = PurchaseReturnOrder.objects.update_or_create(
                serial_num=serial_num,
                defaults={
                    'order_number': order_number,
                    'supplier': supplier,
                    'warehouse': self.main_wh,
                    'order_date': parse_date(r.get('تاريخ الإنشاء')) or timezone.now().date(),
                    'status': 'settled',
                    'settled_at': parse_dt(r.get('تاريخ إصدار الفاتورة')),
                    'items_count': 1,
                    'items_quantity': qty,
                    'subtotal': tot,
                    'tax_amount': Decimal('0.00'),
                    'grand_total': tot,
                    'notes': clean_str(r.get('ملاحظة')),
                    'created_by': creator,
                    'updated_by': creator,
                },
            )
            self.stats['pro_created' if created else 'pro_updated'] += 1
            if created or not pro.items.exists():
                pro.items.all().delete()
                PurchaseReturnOrderItem.objects.create(
                    return_order=pro,
                    item_order=1,
                    product=prod,
                    quantity=qty,
                    unit_price=price,
                )

        # 8c. Vendor Accounts (9 from VA + ensure #16030 and all suppliers have VendorAccount)
        va_by_serial = {}
        for r in self.va_rows:
            ser = int(r['Contact_SerialNum'])
            supp = self.contact_by_serial[ser]
            acc, created = VendorAccount.objects.update_or_create(
                supplier=supp,
                defaults={
                    'current_balance': parse_dec(r.get('Account_AccountStats_Balance')),
                    'overdue_balance': parse_dec(r.get('Account_AccountStats_OverdueAmount')),
                    'last_transaction_date': parse_date(r.get('Account_AccountStats_LastTransactionDate')),
                },
            )
            va_by_serial[ser] = acc
            self.stats['vendor_accounts_created' if created else 'vendor_accounts_updated'] += 1

        for supp in Contact.objects.filter(is_supplier=True):
            if supp.serial_num not in va_by_serial:
                acc, created = VendorAccount.objects.get_or_create(
                    supplier=supp,
                    defaults={'current_balance': Decimal('0.00')},
                )
                va_by_serial[supp.serial_num] = acc
                if created:
                    self.stats['vendor_accounts_created'] += 1

        # 8d. Vendor Transactions (70 rows)
        vt_by_ref_uuid = {}
        vt_sorted = sorted(
            self.vt_rows,
            key=lambda x: (
                parse_date(x.get('التاريخ')) or datetime.date(2000, 1, 1),
                parse_dt(x.get('نفذ فى')) or timezone.now(),
                clean_str(x.get('المعرف')),
            ),
        )
        for idx, r in enumerate(vt_sorted, start=1):
            serial = 500000 + idx
            acc_name = clean_str(r.get('الحساب - الاسم'))
            m = re.match(r'^\[#(\d+)\]', acc_name)
            if not m or int(m.group(1)) not in va_by_serial:
                self.warnings.append(f"Unmatched vendor transaction account: {acc_name!r}")
                continue
            acc = va_by_serial[int(m.group(1))]
            ref_uuid = clean_str(r.get('السبب - المعرف'))
            ref_num = clean_str(r.get('السبب - الرقم'))
            raw_reason = clean_str(r.get('السبب'))
            tx_type = 'credit' if clean_str(r.get('نوع الحركة')).lower() == 'credit' else 'debit'
            credit = parse_dec(r.get('دائن'))
            debit = parse_dec(r.get('مدين'))
            running_bal = parse_dec(r.get('الرصيد'))
            open_amt = parse_dec(r.get('المديونية'))
            note = clean_str(r.get('ملاحظة'))
            tx_date = parse_date(r.get('التاريخ')) or timezone.now().date()
            due_date = parse_date(r.get('تاريخ الاستحقاق')) or tx_date
            creator = self._resolve_user(r.get('نفذ بواسطة - المعرف'), r.get('نفذ بواسطة - الاسم'))
            po_obj = po_by_uuid.get(ref_uuid) if raw_reason == 'purchase' else None

            desc_parts = [raw_reason]
            if ref_num:
                desc_parts.append(ref_num)
            if note:
                desc_parts.append(f"- {note}")
            description = ' '.join(desc_parts)[:255]

            vt, created = VendorTransaction.objects.update_or_create(
                serial=serial,
                defaults={
                    'account': acc,
                    'purchase_order': po_obj,
                    'transaction_type': tx_type,
                    'reason': raw_reason,
                    'transaction_date': tx_date,
                    'due_date': due_date,
                    'credit': credit,
                    'debit': debit,
                    'running_balance': running_bal,
                    'description': description,
                    'notes': note,
                    'created_by': creator,
                },
            )
            if ref_uuid:
                vt_by_ref_uuid[ref_uuid] = vt
            self.stats['vendor_tx_created' if created else 'vendor_tx_updated'] += 1

            # Create VendorInstallment for purchase credit transactions
            if tx_type == 'credit' and credit > 0 and raw_reason == 'purchase':
                closed_amt = max(Decimal('0.00'), credit - open_amt)
                VendorInstallment.objects.update_or_create(
                    transaction=vt,
                    defaults={
                        'total_amount': credit,
                        'closed_amount': closed_amt,
                        'open_amount': open_amt,
                        'due_date': due_date,
                        'is_settled': (open_amt <= Decimal('0.00')),
                    },
                )

        # 8e. Map Vault per VendorPayment UUID from vaults transactions.xlsx (35/35 exact!)
        vtx_vault_by_ref = {}
        for r in self.vtx_rows:
            ru = clean_str(r.get('السبب - المعرف'))
            vname = clean_str(r.get('الحساب - الاسم'))
            if ru and vname in self.vault_by_excel_name:
                vtx_vault_by_ref[ru] = self.vault_by_excel_name[vname]

        for r in self.vp_rows:
            vp_uuid = clean_str(r.get('ID'))
            serial_num = int(r['رقم التسلسل'])
            supp = self.contact_by_serial[int(r['رقم تسلسل جهة الإتصال'])]
            vault = vtx_vault_by_ref.get(vp_uuid) or self.main_vault
            amt = parse_dec(r.get('الكمية'))
            pay_date = parse_date(r.get('تاريخ الإنشاء')) or timezone.now().date()
            raw_method = clean_str(r.get('طريقة الدفع')).lower()
            method = 'cheque' if raw_method == 'cheque' else ('bank_transfer' if 'bank' in raw_method else 'cash')
            creator = self._resolve_user(r.get('id المنشء'), r.get('اسم المنشء'))
            debit_tx = vt_by_ref_uuid.get(vp_uuid)

            if debit_tx is None:
                self.discrepancies.append(
                    f"VendorPayment #{serial_num} ({supp.name}, {amt} EGP) is in vendor-payments.xlsx & vaults transactions.xlsx "
                    f"but has no row in vendor transactions.xlsx; imported with status='cleared' and debit_transaction=None."
                )

            # Approved Decision #5: status='cleared'
            _, created = VendorPayment.objects.update_or_create(
                serial_num=serial_num,
                defaults={
                    'supplier': supp,
                    'vault': vault,
                    'payment_date': pay_date,
                    'amount': amt,
                    'payment_method': method,
                    'status': 'cleared',
                    'debit_transaction': debit_tx,
                    'notes': clean_str(r.get('ملاحظة جهة الإتصال')),
                    'created_by': creator,
                },
            )
            self.stats['vendor_payments_created' if created else 'vendor_payments_updated'] += 1

    # ------------------------------------------------------------------
    # STEP 9: SALES ORDERS, RETURNS, COLLECTIONS, CUSTOMER ACCOUNTS & LEDGER
    # ------------------------------------------------------------------
    def _import_sales_chain(self):
        # 9a. Sales Orders (7,334 SOs + 12,942 items)
        so_groups = defaultdict(list)
        for r in self.so_rows:
            uid = clean_str(r.get('المعرف'))
            if uid:
                so_groups[uid].append(r)

        so_status_map = {
            'invoiced': 'invoiced',
            'delivered': 'delivered',
            'manager approved': 'manager_approval',
            'preparing': 'preparing',
            'pending': 'pending',
            'cancelled': 'cancelled',
        }

        existing_so_serials = set(SalesOrder.objects.values_list('serial_num', flat=True))
        used_so_memo_ids = set(SalesOrder.objects.exclude(memo__isnull=True).values_list('memo_id', flat=True))
        so_to_create = []
        so_items_meta = []  # (serial_num, rows, linked_memo)

        for uid, rows in so_groups.items():
            r0 = rows[0]
            serial_num = int(r0['مسلسل'])
            if serial_num in existing_so_serials:
                self.stats['so_skipped_existing'] += 1
                continue

            order_number = clean_str(r0.get('الرقم')) or f"#{serial_num}"
            customer = self.contact_by_serial[int(r0['العميل - مسلسل'])]
            creator = self._resolve_user(r0.get('المنشء - المعرف'), r0.get('المنشء - الاسم'))

            # Exact historical warehouse from memos.xlsx -> fallback rep custody -> main warehouse
            linked_memo = self.memo_by_source.get(('sales_order', uid))
            if linked_memo:
                src_wh = linked_memo.warehouse
                self.stats['so_wh_from_memo'] += 1
            elif creator and creator.id in self.wh_by_user_id:
                src_wh = self.wh_by_user_id[creator.id]
                self.stats['so_wh_from_rep_fallback'] += 1
            else:
                src_wh = self.main_wh
                self.stats['so_wh_from_main_fallback'] += 1

            memo_to_link = linked_memo if (linked_memo and linked_memo.id not in used_so_memo_ids) else None
            if memo_to_link:
                used_so_memo_ids.add(memo_to_link.id)

            raw_status = clean_str(r0.get('الحالة - الاسم')).lower()
            status = so_status_map.get(raw_status, 'invoiced')
            is_cash = (clean_str(r0.get('الدفع كاش')) == 'نعم')
            payment_status = 'paid' if is_cash else 'credit'

            raw_sub = sum((parse_dec(x.get('العناصر - الكمية')) * parse_dec(x.get('العناصر - سعر القطعة')) for x in rows), Decimal('0.00')).quantize(Decimal('0.01'))
            before_extra = parse_dec(r0.get('السعر قبل كل الخصومات'))
            extra_disc_pct = parse_dec(r0.get('الخصم الإضافي - نسبة'))
            extra_disc_amt = parse_dec(r0.get('الخصم الإضافي - قيمة'))
            ship_val = next((v for k, v in r0.items() if 'الشحن' in k), 0)
            shipping = max(Decimal('0.00'), parse_dec(ship_val))
            grand_total = parse_dec(r0.get('الإجمالي النهائي'))
            items_disc_total = max(Decimal('0.00'), raw_sub - before_extra)

            so_to_create.append(
                SalesOrder(
                    serial_num=serial_num,
                    order_number=order_number,
                    customer=customer,
                    source_warehouse=src_wh,
                    order_date=parse_date(r0.get('تاريخ الإنشاء')) or timezone.now().date(),
                    delivery_date=parse_date(r0.get('تاريخ الخصم من المخزن')),
                    due_date=parse_date(r0.get('تاريخ الاستحقاق')),
                    status=status,
                    payment_status=payment_status,
                    memo=memo_to_link,
                    subtotal=raw_sub,
                    items_discount_total=items_disc_total,
                    custom_discount_percentage=extra_disc_pct,
                    custom_discount_amount=extra_disc_amt,
                    tax_amount=Decimal('0.00'),
                    shipping_fees=shipping,
                    grand_total=grand_total,
                    notes=clean_str(r0.get('ملاحظة')),
                    approved_by=creator,
                    approved_at=parse_dt(r0.get('تاريخ الإنشاء')),
                    created_by=creator,
                )
            )
            so_items_meta.append((serial_num, rows, memo_to_link))

        if so_to_create:
            SalesOrder.objects.bulk_create(so_to_create, batch_size=1000)
            self.stats['so_created'] += len(so_to_create)

            so_map = {so.serial_num: so for so in SalesOrder.objects.all()}
            items_to_create = []
            memo_items_to_create = []
            for snum, rows, memo_obj in so_items_meta:
                so_obj = so_map[snum]
                for itm in rows:
                    prod = self.prod_by_sku[clean_str(itm.get('العناصر - المنتج - الكود'))]
                    qty = parse_dec(itm.get('العناصر - الكمية'))
                    price = parse_dec(itm.get('العناصر - سعر القطعة'))
                    line_sub = (qty * price).quantize(Decimal('0.01'))
                    disc_pct = parse_dec(itm.get('العناصر - خصم القطعة %'))
                    line_after_disc = parse_dec(itm.get('العناصر - السعر بعد كل الخصومات'))
                    disc_amt = max(Decimal('0.00'), line_sub - line_after_disc)
                    items_to_create.append(
                        SalesOrderItem(
                            order=so_obj,
                            product=prod,
                            quantity=qty,
                            unit_price=price,
                            discount_percentage=disc_pct,
                            discount_amount=disc_amt,
                            tax_percentage=Decimal('0.00'),
                            tax_amount=Decimal('0.00'),
                            subtotal=line_sub,
                        )
                    )
                    if memo_obj:
                        memo_items_to_create.append(
                            InventoryMemoItem(
                                memo=memo_obj,
                                product=prod,
                                quantity=qty,
                                unit_cost=prod.default_purchase_cost or Decimal('0.00'),
                            )
                        )
            SalesOrderItem.objects.bulk_create(items_to_create, batch_size=2000)
            self.stats['so_items_created'] += len(items_to_create)
            if memo_items_to_create:
                InventoryMemoItem.objects.bulk_create(memo_items_to_create, batch_size=2000)
                self.stats['memo_items_created'] += len(memo_items_to_create)

        self.stats['so_total'] = SalesOrder.objects.count()

        # 9b. Sales Return Orders (290 SROs + 467 items)
        sro_groups = defaultdict(list)
        for r in self.sro_rows:
            uid = clean_str(r.get('المعرف'))
            if uid:
                sro_groups[uid].append(r)

        sro_status_map = {'settled': 'settled', 'picked': 'delivered', 'pending': 'pending'}
        existing_sro_serials = set(SalesReturnOrder.objects.values_list('serial_num', flat=True))
        used_sro_memo_ids = set(SalesReturnOrder.objects.exclude(memo__isnull=True).values_list('memo_id', flat=True))
        sro_to_create = []
        sro_items_meta = []

        for uid, rows in sro_groups.items():
            r0 = rows[0]
            serial_num = int(r0['مسلسل'])
            if serial_num in existing_sro_serials:
                self.stats['sro_skipped_existing'] += 1
                continue

            order_number = clean_str(r0.get('الرقم')) or f"#{serial_num}"
            customer = self.contact_by_serial[int(r0['العميل - مسلسل'])]
            creator = self._resolve_user(r0.get('المنشء - المعرف'), r0.get('المنشء - الاسم'))

            linked_memo = self.memo_by_source.get(('return_order', uid))
            if linked_memo:
                tgt_wh = linked_memo.warehouse
                self.stats['sro_wh_from_memo'] += 1
            elif creator and creator.id in self.wh_by_user_id:
                tgt_wh = self.wh_by_user_id[creator.id]
                self.stats['sro_wh_from_rep_fallback'] += 1
            else:
                tgt_wh = self.main_wh
                self.stats['sro_wh_from_main_fallback'] += 1

            memo_to_link = linked_memo if (linked_memo and linked_memo.id not in used_sro_memo_ids) else None
            if memo_to_link:
                used_sro_memo_ids.add(memo_to_link.id)

            raw_status = clean_str(r0.get('الحالة - الاسم')).lower()
            status = sro_status_map.get(raw_status, 'settled')
            grand_total = parse_dec(r0.get('الإجمالي النهائي'))

            sro_to_create.append(
                SalesReturnOrder(
                    serial_num=serial_num,
                    order_number=order_number,
                    sales_order=None,
                    customer=customer,
                    target_warehouse=tgt_wh,
                    order_date=parse_date(r0.get('تاريخ الإنشاء')) or timezone.now().date(),
                    status=status,
                    memo=memo_to_link,
                    stocked_at=parse_dt(r0.get('تاريخ التخزين')),
                    settled_at=parse_dt(r0.get('تاريخ إصدار الفاتورة')),
                    items_count=len(rows),
                    items_quantity=sum((parse_dec(x.get('العناصر - الكمية')) for x in rows), Decimal('0.00')),
                    subtotal=grand_total,
                    discount_total=Decimal('0.00'),
                    tax_amount=Decimal('0.00'),
                    grand_total=grand_total,
                    notes=clean_str(r0.get('ملاحظة')),
                    created_by=creator,
                    updated_by=creator,
                )
            )
            sro_items_meta.append((serial_num, rows, memo_to_link))

        if sro_to_create:
            SalesReturnOrder.objects.bulk_create(sro_to_create, batch_size=500)
            self.stats['sro_created'] += len(sro_to_create)

            sro_map = {ro.serial_num: ro for ro in SalesReturnOrder.objects.all()}
            sro_items = []
            sro_memo_items = []
            for snum, rows, memo_obj in sro_items_meta:
                ro_obj = sro_map[snum]
                for itm in rows:
                    prod = self.prod_by_sku[clean_str(itm.get('العناصر - المنتج - الكود'))]
                    qty = parse_dec(itm.get('العناصر - الكمية'))
                    price = parse_dec(itm.get('العناصر - سعر القطعة'))
                    line_tot = parse_dec(itm.get('العناصر - الكلي'))
                    sro_items.append(
                        SalesReturnOrderItem(
                            order=ro_obj,
                            product=prod,
                            condition='resalable',
                            quantity=qty,
                            unit_price=price,
                            subtotal=line_tot,
                            total=line_tot,
                            batch_number=clean_str(itm.get('العناصر - رقم تشغيل المنتج')),
                            expiry_date=parse_date(itm.get('العناصر - تاريخ صلاحية المنتج')),
                        )
                    )
                    if memo_obj:
                        sro_memo_items.append(
                            InventoryMemoItem(
                                memo=memo_obj,
                                product=prod,
                                quantity=qty,
                                unit_cost=prod.default_purchase_cost or Decimal('0.00'),
                                batch_number=clean_str(itm.get('العناصر - رقم تشغيل المنتج')),
                                expiry_date=parse_date(itm.get('العناصر - تاريخ صلاحية المنتج')),
                            )
                        )
            SalesReturnOrderItem.objects.bulk_create(sro_items, batch_size=1000)
            self.stats['sro_items_created'] += len(sro_items)
            if sro_memo_items:
                InventoryMemoItem.objects.bulk_create(sro_memo_items, batch_size=1000)
                self.stats['memo_items_created'] += len(sro_memo_items)

        self.stats['sro_total'] = SalesReturnOrder.objects.count()

        # 9c. Collections (6,912 rows) — Approved Decision #2 (no archive vault!)
        vtx_vault_by_ref = {}
        for r in self.vtx_rows:
            ru = clean_str(r.get('السبب - المعرف'))
            vname = clean_str(r.get('الحساب - الاسم'))
            if ru and vname in self.vault_by_excel_name:
                vtx_vault_by_ref[ru] = self.vault_by_excel_name[vname]

        existing_col_serials = set(Collection.objects.values_list('serial_num', flat=True))
        cols_to_create = []

        for r in self.col_rows:
            serial_num = int(r['رقم التسلسل'])
            if serial_num in existing_col_serials:
                self.stats['collections_skipped_existing'] += 1
                continue

            col_uuid = clean_str(r.get('ID'))
            customer = self.contact_by_serial[int(r['رقم تسلسل العميل'])]
            creator = self._resolve_user(r.get('id المنشء'), r.get('اسم المنشء'))

            if col_uuid in vtx_vault_by_ref:
                vault = vtx_vault_by_ref[col_uuid]
                self.stats['col_vault_exact_vtx'] += 1
            elif creator and creator.id in self.vault_by_user_id:
                vault = self.vault_by_user_id[creator.id]
                self.stats['col_vault_rep_fallback'] += 1
            else:
                vault = self.main_vault
                self.stats['col_vault_main_fallback'] += 1

            raw_method = clean_str(r.get('طريقة الدفع')).lower()
            method = 'cheque' if raw_method == 'cheque' else 'cash'
            cheque_no = clean_str(r.get('رقم الشيك'))
            col_status = clean_str(r.get('اسم حالة التحصيل'))
            note_parts = []
            if col_status:
                note_parts.append(f"[{col_status}]")
            if cheque_no:
                note_parts.append(f"شيك #{cheque_no}")
            if clean_str(r.get('ملاحظة العميل')):
                note_parts.append(clean_str(r.get('ملاحظة العميل')))

            cols_to_create.append(
                Collection(
                    serial_num=serial_num,
                    sales_order=None,
                    customer=customer,
                    vault=vault,
                    amount=parse_dec(r.get('الكمية')),
                    collection_date=parse_date(r.get('تاريخ الإنشاء')) or timezone.now().date(),
                    due_date=parse_date(r.get('تاريخ استحقاق الشيك')),
                    payment_method=method,
                    notes=' | '.join(note_parts),
                    created_by=creator,
                )
            )

        if cols_to_create:
            Collection.objects.bulk_create(cols_to_create, batch_size=1000)
            self.stats['collections_created'] += len(cols_to_create)
        self.stats['collections_total'] = Collection.objects.count()

        # 9d. Customer Accounts (deduplicate 1,399 -> 1,100 + recover 299 from CT1/CT2)
        seen_ca_ids = set()
        ca_by_acc_name = {}
        for r in self.ca_rows:
            aid = clean_str(r.get('AccountID'))
            if aid in seen_ca_ids:
                self.stats['ca_duplicates_skipped'] += 1
                continue
            seen_ca_ids.add(aid)
            ser = int(r['Contact_SerialNum'])
            cust = self.contact_by_serial[ser]
            bal = parse_dec(r.get('Account_AccountStats_Balance'))
            overdue = parse_dec(r.get('Account_AccountStats_OverdueAmount'))
            last_dt = parse_date(r.get('Account_AccountStats_LastTransactionDate'))
            due_days = int(r['Account_AccountLimits_DefaultDuePeriodDays']) if r.get('Account_AccountLimits_DefaultDuePeriodDays') else cust.credit_period_days

            acc, created = CustomerAccount.objects.update_or_create(
                customer=cust,
                defaults={
                    'credit_limit': cust.credit_limit,
                    'credit_period_days': due_days,
                    'current_balance': bal,
                    'overdue_balance': overdue,
                    'last_transaction_date': last_dt,
                },
            )
            ca_by_acc_name[clean_str(r.get('Account_Name'))] = acc
            self.stats['customer_accounts_from_ca'] += 1

        # Group all CT1 + CT2 by account name to recover the 299 dropped accounts
        all_ct = self.ct1_rows + self.ct2_rows
        ct_by_acc_name = defaultdict(list)
        for r in all_ct:
            ct_by_acc_name[clean_str(r.get('الحساب - الاسم'))].append(r)

        for acc_name, txs in ct_by_acc_name.items():
            if acc_name in ca_by_acc_name:
                continue
            cust = self._resolve_customer_from_account_name(acc_name)
            if not cust:
                self.warnings.append(f"Unmatched CT account name: {acc_name!r}")
                continue
            net_bal = sum((parse_dec(t.get('مدين')) - parse_dec(t.get('دائن')) for t in txs), Decimal('0.00'))
            tx_dates = [parse_date(t.get('التاريخ')) for t in txs if parse_date(t.get('التاريخ'))]
            last_dt = max(tx_dates) if tx_dates else None
            acc, _ = CustomerAccount.objects.update_or_create(
                customer=cust,
                defaults={
                    'credit_limit': cust.credit_limit,
                    'credit_period_days': cust.credit_period_days,
                    'current_balance': net_bal,
                    'last_transaction_date': last_dt,
                },
            )
            ca_by_acc_name[acc_name] = acc
            self.stats['customer_accounts_recovered_from_ct'] += 1

        # Apply Approved Decision #6 override explicitly for [W0047]
        for code, approved_bal in APPROVED_CUSTOMER_BALANCE_OVERRIDES.items():
            cust = self.contact_by_code.get(code)
            if cust:
                CustomerAccount.objects.filter(customer=cust).update(current_balance=approved_bal)
                self.discrepancies.append(
                    f"Approved Exception (Decision #6): [{code}] {cust.name} balance set to {approved_bal} EGP "
                    f"(customers accounts.xlsx) vs CT ledger net -846.80 EGP (diff = 2,835.00 EGP); all 69 source transactions preserved."
                )

        # Ensure remaining is_customer=True contacts have zero-balance CustomerAccount
        existing_ca_cust_ids = set(CustomerAccount.objects.values_list('customer_id', flat=True))
        zero_cas = [
            CustomerAccount(
                customer=c,
                credit_limit=c.credit_limit,
                credit_period_days=c.credit_period_days,
                current_balance=Decimal('0.00'),
            )
            for c in Contact.objects.filter(is_customer=True).exclude(id__in=existing_ca_cust_ids)
        ]
        if zero_cas:
            CustomerAccount.objects.bulk_create(zero_cas, batch_size=1000)
            self.stats['customer_accounts_zero_initialized'] += len(zero_cas)

        # 9e. Customer Transactions (16,398 rows from CT1 + CT2)
        reason_map = {
            'sales': 'sales',
            'payments': 'collection',
            'returns': 'sales_return',
            'opening': 'opening',
            'adjustment': 'adjustment',
        }
        ct_sorted = sorted(
            all_ct,
            key=lambda x: (
                parse_date(x.get('التاريخ')) or datetime.date(2000, 1, 1),
                parse_dt(x.get('نفذ فى')) or timezone.now(),
                clean_str(x.get('المعرف')),
            ),
        )
        existing_ct_serials = set(CustomerTransaction.objects.values_list('serial', flat=True))
        ct_to_create = []
        for idx, r in enumerate(ct_sorted, start=1):
            serial = 100000 + idx
            if serial in existing_ct_serials:
                self.stats['customer_tx_skipped_existing'] += 1
                continue
            acc_name = clean_str(r.get('الحساب - الاسم'))
            acc = ca_by_acc_name.get(acc_name)
            if not acc:
                continue
            raw_reason = clean_str(r.get('السبب'))
            reason = reason_map.get(raw_reason, raw_reason or 'sales')
            tx_type = 'debit' if clean_str(r.get('نوع الحركة')).lower() == 'debit' else 'credit'
            ref_num = clean_str(r.get('السبب - الرقم'))
            note = clean_str(r.get('ملاحظة'))
            desc_parts = [raw_reason]
            if ref_num:
                desc_parts.append(ref_num)
            if note:
                desc_parts.append(f"- {note}")
            creator = self._resolve_user(r.get('نفذ بواسطة - المعرف'), r.get('نفذ بواسطة - الاسم'))

            ct_to_create.append(
                CustomerTransaction(
                    serial=serial,
                    account=acc,
                    transaction_type=tx_type,
                    reason=reason,
                    transaction_date=parse_date(r.get('التاريخ')) or timezone.now().date(),
                    due_date=parse_date(r.get('تاريخ الاستحقاق')),
                    debit=parse_dec(r.get('مدين')),
                    credit=parse_dec(r.get('دائن')),
                    running_balance=parse_dec(r.get('الرصيد')),
                    description=' '.join(desc_parts)[:255],
                    created_by=creator,
                )
            )
        if ct_to_create:
            CustomerTransaction.objects.bulk_create(ct_to_create, batch_size=2000)
            self.stats['customer_tx_created'] += len(ct_to_create)
        self.stats['customer_tx_total'] = CustomerTransaction.objects.count()

    def _resolve_customer_from_account_name(self, acc_name: str):
        m = re.match(r'^\[([^\]]+)\]', acc_name)
        if not m:
            return None
        tok = m.group(1).strip()
        if tok.startswith('#') and tok[1:].isdigit():
            return self.contact_by_serial.get(int(tok[1:]))
        return self.contact_by_code.get(tok)

    # ------------------------------------------------------------------
    # STEP 10: VAULT TRANSACTIONS & RECONCILED VAULT CLOSING BALANCES
    # ------------------------------------------------------------------
    def _import_vault_transactions(self):
        # Build existing key set for idempotency without schema changes
        existing_keys = set(
            VaultTransaction.objects.values_list(
                'vault_id', 'transaction_type', 'amount', 'running_balance', 'reference_type', 'reference_id', 'description'
            )
        )

        vtx_to_create = []
        vtx_timestamps = []
        vault_closing_bal = {}

        for r in self.vtx_rows:
            vname = clean_str(r.get('الحساب - الاسم'))
            vault = self.vault_by_excel_name.get(vname)
            if not vault:
                self.warnings.append(f"Unmatched vault in vaults transactions.xlsx: {vname!r}")
                continue

            dr = parse_dec(r.get('مدين'))
            cr = parse_dec(r.get('دائن'))
            running_bal = parse_dec(r.get('الرصيد'))
            # In Bricks-Rep vault asset accounts: debit (مدين) = inflow (+), credit (دائن) = outflow (-)
            if cr > Decimal('0.00') and dr == Decimal('0.00'):
                tx_type = 'outflow'
                amt = cr
            else:
                tx_type = 'inflow'
                amt = dr

            raw_reason = clean_str(r.get('السبب')) or 'adjustment'
            ref_num_str = clean_str(r.get('السبب - الرقم'))
            ref_id = parse_ref_int(ref_num_str)
            note = clean_str(r.get('ملاحظة'))
            tx_date_str = clean_str(r.get('التاريخ'))
            exec_dt = parse_dt(r.get('نفذ فى')) or parse_dt(r.get('التاريخ')) or timezone.now()
            creator = self._resolve_user(r.get('نفذ بواسطة - المعرف'), r.get('نفذ بواسطة - الاسم'))

            desc_parts = [f"[{tx_date_str}]", raw_reason]
            if ref_num_str:
                desc_parts.append(ref_num_str)
            if note:
                desc_parts.append(f"- {note}")
            description = ' '.join(desc_parts)[:255]

            # Track last balance per vault (file is ordered chronologically per vault)
            vault_closing_bal[vault.id] = running_bal

            key = (vault.id, tx_type, amt, running_bal, raw_reason, ref_id, description)
            if key in existing_keys:
                self.stats['vault_tx_skipped_existing'] += 1
                continue
            existing_keys.add(key)

            vtx_to_create.append(
                VaultTransaction(
                    vault=vault,
                    transaction_type=tx_type,
                    amount=amt,
                    running_balance=running_bal,
                    reference_type=raw_reason,
                    reference_id=ref_id,
                    description=description,
                    created_by=creator,
                )
            )
            vtx_timestamps.append(exec_dt)

        if vtx_to_create:
            created_objs = VaultTransaction.objects.bulk_create(vtx_to_create, batch_size=1000)
            self.stats['vault_tx_created'] += len(created_objs)
            # Preserve exact historical timestamps on created_at
            for obj, ts in zip(created_objs, vtx_timestamps):
                obj.created_at = ts
            VaultTransaction.objects.bulk_update(created_objs, ['created_at'], batch_size=1000)

        self.stats['vault_tx_total'] = VaultTransaction.objects.count()

        # Authoritatively reconcile Vault.current_balance from vaults transactions.xlsx
        for vid, closing_bal in vault_closing_bal.items():
            Vault.objects.filter(id=vid).update(current_balance=closing_bal)
            self.stats['vaults_reconciled'] += 1

    # ------------------------------------------------------------------
    # PHASE 5: FINANCIAL & INVENTORY RECONCILIATION VERIFICATION
    # ------------------------------------------------------------------
    def verify_reconciliation(self) -> dict:
        from django.db.models import Sum

        # 1. Inventory Stock reconciliation
        excel_qty_on_hand = sum((parse_dec(r.get('فى المخزن')) for r in self.inv_rows), Decimal('0.00'))
        excel_qty_reserved = sum((parse_dec(r.get('محجوز')) for r in self.inv_rows), Decimal('0.00'))
        db_stock_agg = InventoryStock.objects.aggregate(
            on_hand=Sum('qty_on_hand'), reserved=Sum('qty_reserved')
        )
        db_on_hand = db_stock_agg['on_hand'] or Decimal('0.00')
        db_reserved = db_stock_agg['reserved'] or Decimal('0.00')

        # 2. Vendor Accounts reconciliation
        excel_va_total = sum((parse_dec(r.get('Account_AccountStats_Balance')) for r in self.va_rows), Decimal('0.00'))
        db_va_total = VendorAccount.objects.aggregate(s=Sum('current_balance'))['s'] or Decimal('0.00')

        # 3. Vault Balances reconciliation
        excel_vault_net = defaultdict(Decimal)
        for r in self.vtx_rows:
            vname = clean_str(r.get('الحساب - الاسم'))
            excel_vault_net[vname] += parse_dec(r.get('مدين')) - parse_dec(r.get('دائن'))
        excel_vault_total = sum(excel_vault_net.values(), Decimal('0.00'))
        db_vault_total = Vault.objects.aggregate(s=Sum('current_balance'))['s'] or Decimal('0.00')

        # 4. Customer Accounts reconciliation (1,100 unique CA + 299 CT-recovered)
        seen_ca = set()
        excel_ca_total = Decimal('0.00')
        ca_names = set()
        for r in self.ca_rows:
            aid = clean_str(r.get('AccountID'))
            if aid in seen_ca:
                continue
            seen_ca.add(aid)
            ca_names.add(clean_str(r.get('Account_Name')))
            excel_ca_total += parse_dec(r.get('Account_AccountStats_Balance'))

        ct_only_total = Decimal('0.00')
        for r in (self.ct1_rows + self.ct2_rows):
            aname = clean_str(r.get('الحساب - الاسم'))
            if aname not in ca_names:
                ct_only_total += parse_dec(r.get('مدين')) - parse_dec(r.get('دائن'))

        expected_cust_total = excel_ca_total + ct_only_total
        db_cust_total = CustomerAccount.objects.aggregate(s=Sum('current_balance'))['s'] or Decimal('0.00')

        # 5. Purchase & Sales Totals reconciliation
        po_seen = {}
        for r in self.po_rows:
            po_seen[clean_str(r.get('المعرف'))] = parse_dec(r.get('الإجمالي النهائي'))
        excel_po_total = sum(po_seen.values(), Decimal('0.00'))
        db_po_total = PurchaseOrder.objects.aggregate(s=Sum('grand_total'))['s'] or Decimal('0.00')

        so_seen = {}
        for r in self.so_rows:
            so_seen[clean_str(r.get('المعرف'))] = parse_dec(r.get('الإجمالي النهائي'))
        excel_so_total = sum(so_seen.values(), Decimal('0.00'))
        db_so_total = SalesOrder.objects.aggregate(s=Sum('grand_total'))['s'] or Decimal('0.00')

        excel_col_total = sum((parse_dec(r.get('الكمية')) for r in self.col_rows), Decimal('0.00'))
        db_col_total = Collection.objects.aggregate(s=Sum('amount'))['s'] or Decimal('0.00')

        excel_vp_total = sum((parse_dec(r.get('الكمية')) for r in self.vp_rows), Decimal('0.00'))
        db_vp_total = VendorPayment.objects.aggregate(s=Sum('amount'))['s'] or Decimal('0.00')

        return {
            'inventory_on_hand': {'excel': str(excel_qty_on_hand), 'db': str(db_on_hand), 'match': excel_qty_on_hand == db_on_hand},
            'inventory_reserved': {'excel': str(excel_qty_reserved), 'db': str(db_reserved), 'match': excel_qty_reserved == db_reserved},
            'vendor_balances': {'excel': str(excel_va_total), 'db': str(db_va_total), 'match': excel_va_total == db_va_total},
            'vault_balances': {'excel': str(excel_vault_total), 'db': str(db_vault_total), 'match': excel_vault_total == db_vault_total},
            'customer_balances': {'excel_plus_ct299': str(expected_cust_total), 'db': str(db_cust_total), 'match': expected_cust_total == db_cust_total},
            'purchase_orders_total': {'excel': str(excel_po_total), 'db': str(db_po_total), 'match': excel_po_total == db_po_total},
            'sales_orders_total': {'excel': str(excel_so_total), 'db': str(db_so_total), 'match': excel_so_total == db_so_total},
            'collections_total': {'excel': str(excel_col_total), 'db': str(db_col_total), 'match': excel_col_total == db_col_total},
            'vendor_payments_total': {'excel': str(excel_vp_total), 'db': str(db_vp_total), 'match': excel_vp_total == db_vp_total},
        }
