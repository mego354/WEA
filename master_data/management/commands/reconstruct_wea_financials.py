"""
Safe, Idempotent WEA Financial & Inventory Reconstruction Command.

Usage:
    python manage.py reconstruct_wea_financials --dry-run
    python manage.py reconstruct_wea_financials --backup-only
    python manage.py reconstruct_wea_financials --apply --confirm-reset

Defaults to --dry-run (zero database mutations).
NEVER modifies live db.sqlite3 unless BOTH --apply and --confirm-reset are supplied.
"""
import datetime
import hashlib
import json
import os
import shutil
import sqlite3
from collections import Counter, defaultdict
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.services import AuditLogService
from activities.models import ApprovalAuditLog
from catalog.models import Product
from contacts.models import Contact
from inventory.models import InventoryLot, InventoryMemo, InventoryMemoItem, InventoryStock, Warehouse
from master_data.wea_integration_service import (
    APPROVED_CUSTOMER_BALANCE_OVERRIDES,
    VAULT_NAME_MAP,
    clean_str,
    load_xlsx_rows,
    parse_date,
    parse_dec,
    parse_dt,
    parse_ref_int,
)
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
    Settlement,
    Vault,
    VaultTransaction,
    VendorAccount,
    VendorInstallment,
    VendorPayment,
    VendorPaymentRequest,
    VendorTransaction,
)

User = get_user_model()

SALES_STATUS_MAP = {
    'invoiced': 'invoiced',
    'delivered': 'delivered',
    'manager_approval': 'manager_approval',
    'preparing': 'preparing',
    'pending': 'pending',
    'rejected': 'rejected',
    'cancelled': 'cancelled',
    'canceled': 'cancelled',
}

RETURN_STATUS_MAP = {
    'settled': 'settled',
    'picked': 'delivered',
    'delivered': 'delivered',
    'approved': 'approved',
    'pending': 'pending',
    'rejected': 'rejected',
    'cancelled': 'cancelled',
    'canceled': 'cancelled',
}

PO_STATUS_MAP = {
    'settled': 'settled',
    'picked': 'picked',
    'approved': 'approved',
    'pending': 'pending',
    'rejected': 'rejected',
    'split': 'split',
    'cancelled': 'cancelled',
    'canceled': 'cancelled',
}

CUST_TX_REASON_MAP = {
    'sales': 'sales',
    'payments': 'collection',
    'payment': 'collection',
    'collection': 'collection',
    'returns': 'sales_return',
    'return': 'sales_return',
    'sales_return': 'sales_return',
    'adjustment': 'settlement',
    'settlement': 'settlement',
    'opening': 'opening',
    'opening_balance': 'opening',
}

VENDOR_TX_REASON_MAP = {
    'purchases': 'purchase',
    'purchase': 'purchase',
    'purchase_payments': 'purchase_payments',
    'payments': 'purchase_payments',
    'payment': 'purchase_payments',
    'purchase_returns': 'purchase_returns',
    'returns': 'purchase_returns',
    'return': 'purchase_returns',
    'adjustment': 'settlement',
    'settlement': 'settlement',
    'opening': 'opening',
}


def _norm(val) -> str:
    return ' '.join(clean_str(val).lower().split())


def _extract_status_code(val, mapping, default):
    raw = clean_str(val)
    if ':' in raw:
        raw = raw.split(':')[-1]
    return mapping.get(raw.lower().strip(), default)


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


class Command(BaseCommand):
    help = 'Safe, idempotent WEA financial & inventory reconstruction from verified wea data/*.xlsx files.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--data-dir',
            default=os.path.join(settings.BASE_DIR, 'wea data'),
            help='Directory containing the verified WEA Excel files (default: wea data/).',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            default=False,
            help='Run full parse and reconciliation report without modifying the database (default mode).',
        )
        parser.add_argument(
            '--backup-only',
            action='store_true',
            default=False,
            help='Only create and verify a timestamped SQLite backup + SalesReturnOrderItem JSON snapshot.',
        )
        parser.add_argument(
            '--apply',
            action='store_true',
            default=False,
            help='Execute financial reset and reconstruction (requires --confirm-reset).',
        )
        parser.add_argument(
            '--confirm-reset',
            action='store_true',
            default=False,
            help='Explicit safety confirmation required alongside --apply.',
        )

    def _create_verified_backup(self):
        backup_dir = os.path.join(settings.BASE_DIR, 'backups')
        os.makedirs(backup_dir, exist_ok=True)
        ts = timezone.localtime().strftime('%Y%m%d_%H%M%S')
        db_path = str(settings.DATABASES['default']['NAME'])
        if not os.path.exists(db_path):
            raise CommandError(f'SQLite database not found at: {db_path}')

        backup_path = os.path.join(backup_dir, f'db_pre_financial_reset_{ts}.sqlite3')
        src_conn = sqlite3.connect(db_path)
        dst_conn = sqlite3.connect(backup_path)
        try:
            src_conn.backup(dst_conn)
            res = dst_conn.execute('PRAGMA integrity_check;').fetchall()
            if res != [('ok',)]:
                # Repair stale index B-trees inside the backup copy only (never touches live db)
                dst_conn.execute('REINDEX;')
                dst_conn.commit()
                res_after = dst_conn.execute('PRAGMA integrity_check;').fetchall()
                if res_after != [('ok',)]:
                    raise CommandError(f'Backup SQLite integrity check failed even after REINDEX: {res_after}')
        finally:
            dst_conn.close()
            src_conn.close()

        sha = _sha256_file(backup_path)
        size_mb = os.path.getsize(backup_path) / (1024 * 1024)

        # Snapshot existing SalesReturnOrderItem rows keyed by SalesReturnOrder.serial_num
        snap_path = os.path.join(backup_dir, f'sales_return_items_snapshot_{ts}.json')
        items_by_serial = defaultdict(list)
        total_items = 0
        for it in SalesReturnOrderItem.objects.select_related('order', 'product').order_by('id'):
            items_by_serial[str(it.order.serial_num)].append({
                'product_id': it.product_id,
                'product_sku': it.product.sku_code,
                'condition': it.condition,
                'quantity': str(it.quantity),
                'unit_price': str(it.unit_price),
                'discount_percentage': str(it.discount_percentage),
                'discount_amount': str(it.discount_amount),
                'tax_percentage': str(it.tax_percentage),
                'tax_amount': str(it.tax_amount),
                'subtotal': str(it.subtotal),
                'total': str(it.total),
                'batch_number': it.batch_number,
                'expiry_date': it.expiry_date.isoformat() if it.expiry_date else None,
            })
            total_items += 1
        with open(snap_path, 'w', encoding='utf-8') as f:
            json.dump(items_by_serial, f, ensure_ascii=False, indent=2)

        return {
            'backup_path': backup_path,
            'backup_sha256': sha,
            'backup_size_mb': round(size_mb, 2),
            'snapshot_path': snap_path,
            'snapshot_return_count': len(items_by_serial),
            'snapshot_item_count': total_items,
            'items_by_serial': items_by_serial,
        }

    def _build_lookups(self):
        contacts_by_serial = {}
        contacts_by_code = {}
        contacts_by_name = {}
        for c in Contact.objects.all().only('id', 'serial_num', 'code', 'name', 'is_customer', 'is_supplier'):
            if c.serial_num:
                contacts_by_serial[int(c.serial_num)] = c
            if c.code:
                contacts_by_code[clean_str(c.code).upper()] = c
            if c.name:
                contacts_by_name[_norm(c.name)] = c

        products_by_sku = {}
        products_by_name = {}
        for p in Product.objects.all().only('id', 'sku_code', 'name', 'default_purchase_cost'):
            if p.sku_code:
                products_by_sku[clean_str(p.sku_code).upper()] = p
            if p.name:
                products_by_name[_norm(p.name)] = p

        warehouses_by_name = {}
        for w in Warehouse.objects.all().only('id', 'name', 'code', 'is_active'):
            warehouses_by_name[_norm(w.name)] = w

        vaults_by_name = {}
        for v in Vault.objects.all().only('id', 'name', 'serial_num', 'is_active'):
            vaults_by_name[_norm(v.name)] = v

        users_by_name = {}
        for u in User.objects.all().only('id', 'username', 'first_name', 'last_name'):
            users_by_name[_norm(u.username)] = u
            fn = u.get_full_name().strip()
            if fn:
                users_by_name[_norm(fn)] = u

        return {
            'contacts_by_serial': contacts_by_serial,
            'contacts_by_code': contacts_by_code,
            'contacts_by_name': contacts_by_name,
            'products_by_sku': products_by_sku,
            'products_by_name': products_by_name,
            'warehouses_by_name': warehouses_by_name,
            'vaults_by_name': vaults_by_name,
            'users_by_name': users_by_name,
            'default_warehouse': Warehouse.objects.filter(is_active=True).order_by('id').first() or Warehouse.objects.order_by('id').first(),
        }

    def _match_contact(self, lookups, serial=None, code=None, name=None):
        s_int = parse_ref_int(serial)
        if s_int and s_int in lookups['contacts_by_serial']:
            return lookups['contacts_by_serial'][s_int]
        c_key = clean_str(code).upper()
        if c_key and c_key in lookups['contacts_by_code']:
            return lookups['contacts_by_code'][c_key]
        # Sometimes serial column holds a code like W0047
        s_code = clean_str(serial).lstrip('#').upper()
        if s_code and s_code in lookups['contacts_by_code']:
            return lookups['contacts_by_code'][s_code]
        n_key = _norm(name)
        if n_key and n_key in lookups['contacts_by_name']:
            return lookups['contacts_by_name'][n_key]
        return None

    def _match_vault(self, lookups, raw_name):
        name = clean_str(raw_name)
        mapped = VAULT_NAME_MAP.get(name, name)
        return lookups['vaults_by_name'].get(_norm(mapped)) or lookups['vaults_by_name'].get(_norm(name))

    def _match_warehouse(self, lookups, raw_name):
        return lookups['warehouses_by_name'].get(_norm(raw_name))

    def _match_product(self, lookups, sku=None, name=None):
        s_key = clean_str(sku).upper()
        if s_key and s_key in lookups['products_by_sku']:
            return lookups['products_by_sku'][s_key]
        n_key = _norm(name)
        if n_key and n_key in lookups['products_by_name']:
            return lookups['products_by_name'][n_key]
        return None

    def _match_user(self, lookups, raw_name):
        n = _norm(raw_name)
        if not n or n == 'system user':
            return None
        if n in lookups['users_by_name']:
            return lookups['users_by_name'][n]
        base = n.split('(')[0].strip()
        if base in lookups['users_by_name']:
            return lookups['users_by_name'][base]
        return None

    def _match_contact_from_account_label(self, lookups, label):
        """Parses '[W0036] name' or '[#14435] name' and matches Contact."""
        s = clean_str(label)
        if not s:
            return None
        code_or_ser = None
        name_part = s
        if s.startswith('[') and ']' in s:
            bracket, rest = s[1:].split(']', 1)
            code_or_ser = bracket.strip()
            name_part = rest.strip()
        return self._match_contact(lookups, serial=code_or_ser, code=code_or_ser, name=name_part)

    def _parse_all_sources(self, data_dir: str, lookups: dict):
        """Reads and reconciles all verified Excel files into memory (zero DB writes)."""
        def _path(fname):
            return os.path.join(data_dir, fname)

        required_files = [
            'sales orders.xlsx',
            'sales return orders.xlsx',
            'collections.xlsx',
            'customer transactions 1.xlsx',
            'customer transactions 2.xlsx',
            'customers accounts.xlsx',
            'vaults transactions.xlsx',
            'inventory stock.xlsx',
            'memos.xlsx',
            'purchases orders.xlsx',
            'purchses return.xlsx',
            'vendor transactions.xlsx',
            'vendor-payments.xlsx',
            'vendors accounts.xlsx',
        ]
        missing = [f for f in required_files if not os.path.exists(_path(f))]
        if missing:
            raise CommandError(f'Missing required Excel files in {data_dir}: {missing}')

        report = {
            'unmatched': defaultdict(int),
            'warnings': [],
        }

        # 1. Memos
        _, memo_rows = load_xlsx_rows(_path('memos.xlsx'))
        memos_by_source_id = {}
        parsed_memos = []
        for r in memo_rows:
            ser = parse_ref_int(r.get('Serial Number'))
            if not ser:
                continue
            wh = self._match_warehouse(lookups, r.get('Warehouse Name'))
            if not wh:
                report['unmatched']['memo_warehouse'] += 1
                wh = lookups['default_warehouse']
            m_type_raw = clean_str(r.get('Type')).lower()
            m_type = 'addition' if m_type_raw in ('stock', 'in', 'addition') else 'dispatch'
            st_raw = clean_str(r.get('Status Progress State') or r.get('Status Name')).lower()
            st = 'done' if st_raw == 'done' else ('cancelled' if 'cancel' in st_raw else 'pending')
            rec = {
                'serial_num': ser,
                'memo_type': m_type,
                'status': st,
                'warehouse': wh,
                'source_id': clean_str(r.get('Source ID')),
                'source_type': clean_str(r.get('Source Type')),
                'source_number': clean_str(r.get('Source Number')),
                'notes': clean_str(r.get('Note')),
                'created_by': self._match_user(lookups, r.get('Creator Name')),
                'done_at': parse_dt(r.get('Done At')),
            }
            parsed_memos.append(rec)
            if rec['source_id']:
                memos_by_source_id[rec['source_id']] = ser

        # 2. Inventory Stock
        _, stock_rows = load_xlsx_rows(_path('inventory stock.xlsx'))
        parsed_stocks = []
        stock_totals = {'on_hand': Decimal('0.00'), 'reserved': Decimal('0.00'), 'cost_value': Decimal('0.00'), 'lots': 0}
        for r in stock_rows:
            wh = self._match_warehouse(lookups, r.get('المخزن') or r.get('المخزن - الاسم') or r.get('Warehouse'))
            prod = self._match_product(
                lookups,
                sku=r.get('الكود') or r.get('المنتج - الكود') or r.get('Product Code') or r.get('SKU'),
                name=r.get('المنتج') or r.get('المنتج - الاسم') or r.get('Product Name'),
            )
            if not wh:
                report['unmatched']['stock_warehouse'] += 1
                continue
            if not prod:
                report['unmatched']['stock_product'] += 1
                continue
            on_hand = parse_dec(r.get('فى المخزن') if r.get('فى المخزن') is not None else (r.get('الكمية بالمخزن') or r.get('Quantity')))
            reserved = parse_dec(r.get('محجوز') if r.get('محجوز') is not None else r.get('الكمية المحجوزة'))
            unit_cost = parse_dec(r.get('التكلفة') if r.get('التكلفة') is not None else r.get('سعر التكلفة'))
            row_cost_total = parse_dec(r.get('إجمالي التكلفة'))
            if row_cost_total == Decimal('0.00') and on_hand > Decimal('0.00') and unit_cost > Decimal('0.00'):
                row_cost_total = (on_hand * unit_cost).quantize(Decimal('0.01'))
            batch = clean_str(r.get('رقم التشغيل') or r.get('رقم التشغيلة') or r.get('Batch'))
            expiry = parse_date(r.get('تاريخ الصلاحية') or r.get('Expiry Date'))
            parsed_stocks.append({
                'warehouse': wh,
                'product': prod,
                'qty_on_hand': on_hand,
                'qty_reserved': reserved,
                'product_cost': unit_cost,
                'batch_number': batch,
                'expiry_date': expiry,
            })
            stock_totals['on_hand'] += on_hand
            stock_totals['reserved'] += reserved
            stock_totals['cost_value'] += row_cost_total
            if batch or expiry:
                stock_totals['lots'] += 1

        # 3. Sales Orders (grouped by serial)
        _, so_rows = load_xlsx_rows(_path('sales orders.xlsx'))
        so_groups = defaultdict(list)
        for r in so_rows:
            ser = parse_ref_int(r.get('مسلسل') or r.get('الرقم'))
            if ser:
                so_groups[ser].append(r)

        parsed_sales_orders = []
        so_status_counts = Counter()
        so_status_totals = defaultdict(Decimal)
        for ser, grp in sorted(so_groups.items()):
            head = grp[0]
            cust = self._match_contact(
                lookups,
                serial=head.get('العميل - مسلسل') or head.get('العميل - الرقم'),
                code=head.get('العميل - الكود'),
                name=head.get('العميل - الاسم'),
            )
            if not cust:
                report['unmatched']['sales_order_customer'] += 1
                continue
            wh = self._match_warehouse(lookups, head.get('المخزن - الاسم')) or lookups['default_warehouse']
            status = _extract_status_code(head.get('الحالة - الكود') or head.get('الحالة - الاسم'), SALES_STATUS_MAP, 'invoiced')
            order_date = parse_date(head.get('تاريخ الإنشاء')) or timezone.localdate()
            delivery_date = parse_date(head.get('تاريخ الحسابات') or head.get('تاريخ التسليم') or head.get('تاريخ إصدار الفاتورة'))
            due_date = parse_date(head.get('تاريخ الاستحقاق'))
            grand_total = parse_dec(head.get('الإجمالي النهائي') or head.get('الإجمالي'))
            subtotal = parse_dec(head.get('الإجمالي قبل الخصم') or head.get('الإجمالي') or grand_total)
            items = []
            for r in grp:
                prod = self._match_product(lookups, sku=r.get('المنتج - الكود'), name=r.get('المنتج - الاسم'))
                if not prod:
                    continue
                qty = parse_dec(r.get('الكمية'), '1.00')
                price = parse_dec(r.get('سعر الوحدة') or r.get('السعر'))
                disc_pct = parse_dec(r.get('نسبة الخصم'))
                disc_amt = parse_dec(r.get('قيمة الخصم'))
                items.append({
                    'product': prod,
                    'quantity': qty,
                    'unit_price': price,
                    'discount_percentage': disc_pct,
                    'discount_amount': disc_amt,
                })
            parsed_sales_orders.append({
                'serial_num': ser,
                'order_number': clean_str(head.get('الرقم')) or f'#{ser}',
                'source_id': clean_str(head.get('المعرف')),
                'customer': cust,
                'source_warehouse': wh,
                'order_date': order_date,
                'delivery_date': delivery_date,
                'due_date': due_date,
                'status': status,
                'subtotal': subtotal,
                'grand_total': grand_total,
                'notes': clean_str(head.get('ملاحظات')),
                'created_by': self._match_user(lookups, head.get('المنشء - الاسم')),
                'items': items,
            })
            so_status_counts[status] += 1
            so_status_totals[status] += grand_total

        # 4. Sales Return Orders
        _, ro_rows = load_xlsx_rows(_path('sales return orders.xlsx'))
        existing_db_return_serials = set(SalesReturnOrder.objects.values_list('serial_num', flat=True))
        parsed_returns = []
        returns_missing_items = []
        for r in ro_rows:
            ser = parse_ref_int(r.get('مسلسل') or r.get('الرقم'))
            if not ser:
                continue
            cust = self._match_contact(
                lookups,
                serial=r.get('العميل - مسلسل') or r.get('العميل - الرقم'),
                code=r.get('العميل - الكود'),
                name=r.get('العميل - الاسم'),
            )
            if not cust:
                report['unmatched']['sales_return_customer'] += 1
                continue
            status = _extract_status_code(r.get('الحالة - الكود') or r.get('الحالة - الاسم'), RETURN_STATUS_MAP, 'settled')
            order_date = parse_date(r.get('تاريخ الإنشاء')) or timezone.localdate()
            settled_at = parse_dt(r.get('تاريخ إصدار الفاتورة') or r.get('تاريخ الحسابات'))
            stocked_at = parse_dt(r.get('تاريخ التخزين'))
            grand_total = parse_dec(r.get('الإجمالي النهائي') or r.get('الإجمالي'))
            items_count = parse_ref_int(r.get('عدد الأسطر')) or 0
            items_qty = parse_dec(r.get('عدد القطع'))
            src_id = clean_str(r.get('المعرف'))
            rec = {
                'serial_num': ser,
                'order_number': clean_str(r.get('الرقم')) or f'#{ser}',
                'source_id': src_id,
                'customer': cust,
                'order_date': order_date,
                'status': status,
                'settled_at': settled_at,
                'stocked_at': stocked_at,
                'items_count': items_count,
                'items_quantity': items_qty,
                'subtotal': parse_dec(r.get('الإجمالي') or grand_total),
                'grand_total': grand_total,
                'created_by': self._match_user(lookups, r.get('المنشء - الاسم')),
            }
            parsed_returns.append(rec)
            if ser not in existing_db_return_serials:
                returns_missing_items.append({
                    'serial_num': ser,
                    'customer': cust.name,
                    'date': str(order_date),
                    'items_count': items_count,
                    'items_quantity': str(items_qty),
                    'grand_total': str(grand_total),
                })

        # 5. Collections
        _, col_rows = load_xlsx_rows(_path('collections.xlsx'))
        default_vault = Vault.objects.filter(name='الخزينة الرئيسية - المقر الرئيسي').first() or Vault.objects.filter(is_active=True).order_by('id').first()
        parsed_collections = []
        for r in col_rows:
            ser = parse_ref_int(r.get('رقم التسلسل') or r.get('مسلسل') or r.get('الرقم'))
            if not ser:
                continue
            cust = self._match_contact(
                lookups,
                serial=r.get('رقم تسلسل العميل') or r.get('العميل - مسلسل') or r.get('العميل - الرقم'),
                code=r.get('كود العميل') or r.get('العميل - الكود'),
                name=r.get('اسم العميل') or r.get('العميل - الاسم'),
            )
            if not cust:
                report['unmatched']['collection_customer'] += 1
                continue
            vault = self._match_vault(lookups, r.get('الخزنة - الاسم') or r.get('الخزنة')) or default_vault
            pm_raw = clean_str(r.get('طريقة الدفع') or r.get('نوع الدفع')).lower()
            pm = 'cheque' if ('شيك' in pm_raw or 'cheque' in pm_raw or 'check' in pm_raw) else (
                'bank_transfer' if ('بنك' in pm_raw or 'bank' in pm_raw or 'تحويل' in pm_raw) else 'cash'
            )
            parsed_collections.append({
                'serial_num': ser,
                'customer': cust,
                'vault': vault,
                'amount': parse_dec(r.get('الكمية') or r.get('المبلغ') or r.get('القيمة')),
                'collection_date': parse_date(r.get('تاريخ الإنشاء') or r.get('تاريخ التحصيل')) or timezone.localdate(),
                'payment_method': pm,
                'notes': clean_str(r.get('ملاحظة التلف') or r.get('ملاحظات')),
                'created_by': self._match_user(lookups, r.get('اسم المنشء') or r.get('المنشء - الاسم')),
            })

        # 6. Customer Transactions (1 & 2 deduplicated by UUID 'المعرف')
        _, ct_rows_1 = load_xlsx_rows(_path('customer transactions 1.xlsx'))
        _, ct_rows_2 = load_xlsx_rows(_path('customer transactions 2.xlsx'))
        ct_by_id = {}
        ct_ordered = []
        for r in ct_rows_1 + ct_rows_2:
            uid = clean_str(r.get('المعرف'))
            if uid and uid in ct_by_id:
                continue
            if uid:
                ct_by_id[uid] = True
            ct_ordered.append(r)

        parsed_cust_txs = []
        cust_net_balances = defaultdict(Decimal)
        cust_last_date = {}
        cust_settlement_stats = {'count': 0, 'credit_count': 0, 'credit_sum': Decimal('0.00'), 'debit_count': 0, 'debit_sum': Decimal('0.00')}
        for idx, r in enumerate(ct_ordered, 1):
            cust = self._match_contact_from_account_label(lookups, r.get('الحساب - الاسم'))
            if not cust:
                report['unmatched']['cust_tx_customer'] += 1
                continue
            reason_raw = clean_str(r.get('السبب')).lower()
            if ':' in reason_raw:
                reason_raw = reason_raw.split(':')[-1]
            reason = CUST_TX_REASON_MAP.get(reason_raw, 'sales')
            debit = parse_dec(r.get('مدين'))
            credit = parse_dec(r.get('دائن'))
            tx_type = clean_str(r.get('نوع الحركة')).lower()
            if tx_type not in ('debit', 'credit'):
                tx_type = 'credit' if credit > debit else 'debit'
            tx_date = parse_date(r.get('التاريخ') or r.get('نفذ فى')) or timezone.localdate()
            cust_net_balances[cust.id] += (debit - credit)
            if cust.id not in cust_last_date or tx_date > cust_last_date[cust.id]:
                cust_last_date[cust.id] = tx_date
            if reason == 'settlement':
                cust_settlement_stats['count'] += 1
                if credit > Decimal('0.00'):
                    cust_settlement_stats['credit_count'] += 1
                    cust_settlement_stats['credit_sum'] += credit
                if debit > Decimal('0.00'):
                    cust_settlement_stats['debit_count'] += 1
                    cust_settlement_stats['debit_sum'] += debit
            ref_num = clean_str(r.get('السبب - الرقم'))
            note = clean_str(r.get('ملاحظة'))
            desc_parts = [p for p in (reason_raw, ref_num, note) if p]
            parsed_cust_txs.append({
                'serial': 20000 + idx,
                'customer': cust,
                'transaction_type': tx_type,
                'reason': reason,
                'transaction_date': tx_date,
                'due_date': parse_date(r.get('تاريخ الاستحقاق')),
                'debit': debit,
                'credit': credit,
                'running_balance': cust_net_balances[cust.id],
                'description': ' - '.join(desc_parts)[:255] if desc_parts else f'{reason} #{20000 + idx}',
                'created_by': self._match_user(lookups, r.get('نفذ بواسطة - الاسم')),
            })

        # Enrich overdue & due_this_month from customers accounts.xlsx (deduped by contact)
        _, ca_rows = load_xlsx_rows(_path('customers accounts.xlsx'))
        cust_overdue_map = {}
        cust_due_month_map = {}
        seen_ca = set()
        for r in ca_rows:
            cust = self._match_contact(
                lookups,
                serial=r.get('Contact_SerialNum') or r.get('Contact_Number'),
                code=r.get('Contact_Code'),
                name=r.get('Contact_Name'),
            ) or self._match_contact_from_account_label(lookups, r.get('Account_Name'))
            if not cust or cust.id in seen_ca:
                continue
            seen_ca.add(cust.id)
            cust_overdue_map[cust.id] = parse_dec(r.get('Account_AccountStats_OverdueAmount'))
            cust_due_month_map[cust.id] = parse_dec(r.get('Account_AccountStats_FutureOverdueAmountThisMonth'))

        # Apply approved balance override ([W0047])
        for code_key, override_val in APPROVED_CUSTOMER_BALANCE_OVERRIDES.items():
            c = lookups['contacts_by_code'].get(code_key.upper())
            if c:
                cust_net_balances[c.id] = override_val

        # 7. Vault Transactions (Asset account: مدين = inflow, دائن = outflow)
        _, vt_rows = load_xlsx_rows(_path('vaults transactions.xlsx'))
        parsed_vault_txs = []
        vault_running = defaultdict(Decimal)
        for r in vt_rows:
            vault = self._match_vault(lookups, r.get('الحساب - الاسم') or r.get('الخزنة - الاسم') or r.get('الخزنة'))
            if not vault:
                report['unmatched']['vault_tx_vault'] += 1
                continue
            debit = parse_dec(r.get('مدين'))
            credit = parse_dec(r.get('دائن'))
            if credit > Decimal('0.00') and debit == Decimal('0.00'):
                tx_type = 'outflow'
                amt = credit
                vault_running[vault.id] -= amt
            else:
                tx_type = 'inflow'
                amt = debit
                vault_running[vault.id] += amt
            reason_raw = clean_str(r.get('السبب')) or 'excel_import'
            note = clean_str(r.get('ملاحظة'))
            ref_num = clean_str(r.get('السبب - الرقم'))
            desc = ' - '.join([p for p in (reason_raw, ref_num, note) if p]) or 'حركة خزينة'
            parsed_vault_txs.append({
                'vault': vault,
                'transaction_type': tx_type,
                'amount': amt,
                'running_balance': vault_running[vault.id],
                'reference_type': reason_raw[:50],
                'description': desc[:255],
                'created_by': self._match_user(lookups, r.get('نفذ بواسطة - الاسم')),
                'created_at': parse_dt(r.get('نفذ فى') or r.get('التاريخ')) or timezone.now(),
            })

        # 8. Purchases & Purchase Returns
        _, po_rows = load_xlsx_rows(_path('purchases orders.xlsx'))
        po_groups = defaultdict(list)
        for r in po_rows:
            ser = parse_ref_int(r.get('مسلسل') or r.get('الرقم'))
            if ser:
                po_groups[ser].append(r)

        parsed_pos = []
        for ser, grp in sorted(po_groups.items()):
            head = grp[0]
            sup = self._match_contact(
                lookups,
                serial=head.get('العميل - مسلسل') or head.get('العميل - الرقم') or head.get('المورد - مسلسل'),
                code=head.get('العميل - الكود') or head.get('المورد - الكود'),
                name=head.get('العميل - الاسم') or head.get('المورد - الاسم'),
            )
            if not sup:
                report['unmatched']['po_supplier'] += 1
                continue
            wh = self._match_warehouse(lookups, head.get('المخزن - الاسم')) or lookups['default_warehouse']
            items = []
            for r in grp:
                prod = self._match_product(
                    lookups,
                    sku=r.get('العناصر - المنتج - الكود') or r.get('المنتج - الكود'),
                    name=r.get('العناصر - المنتج - الاسم') or r.get('المنتج - الاسم'),
                )
                if not prod:
                    continue
                items.append({
                    'product': prod,
                    'quantity': parse_dec(r.get('العناصر - الكمية') or r.get('الكمية'), '1.00'),
                    'unit_price': parse_dec(r.get('العناصر - سعر القطعة') or r.get('سعر الوحدة')),
                })
            parsed_pos.append({
                'serial_num': ser,
                'order_number': clean_str(head.get('الرقم')) or f'#{ser}',
                'supplier': sup,
                'target_warehouse': wh,
                'order_date': parse_date(head.get('تاريخ الإنشاء')) or timezone.localdate(),
                'status': _extract_status_code(head.get('الحالة - الكود') or head.get('الحالة - الاسم'), PO_STATUS_MAP, 'settled'),
                'grand_total': parse_dec(head.get('الإجمالي النهائي') or head.get('الإجمالي')),
                'subtotal': parse_dec(head.get('الإجمالي') or head.get('الإجمالي النهائي')),
                'created_by': self._match_user(lookups, head.get('المنشء - الاسم')),
                'items': items,
            })

        _, pr_rows = load_xlsx_rows(_path('purchses return.xlsx'))
        parsed_prs = []
        for r in pr_rows:
            ser = parse_ref_int(r.get('مسلسل') or r.get('الرقم'))
            if not ser:
                continue
            sup = self._match_contact(
                lookups,
                serial=r.get('العميل - مسلسل') or r.get('العميل - الرقم') or r.get('المورد - مسلسل'),
                code=r.get('العميل - الكود') or r.get('المورد - الكود'),
                name=r.get('العميل - الاسم') or r.get('المورد - الاسم'),
            )
            if not sup:
                report['unmatched']['pr_supplier'] += 1
                continue
            parsed_prs.append({
                'serial_num': ser,
                'order_number': clean_str(r.get('الرقم')) or f'#{ser}',
                'supplier': sup,
                'warehouse': self._match_warehouse(lookups, r.get('المخزن - الاسم')) or lookups['default_warehouse'],
                'order_date': parse_date(r.get('تاريخ الإنشاء')) or timezone.localdate(),
                'grand_total': parse_dec(r.get('الإجمالي النهائي') or r.get('الإجمالي')),
                'created_by': self._match_user(lookups, r.get('المنشء - الاسم')),
            })

        # 9. Vendor Transactions & Vendor Payments
        _, vt_v_rows = load_xlsx_rows(_path('vendor transactions.xlsx'))
        parsed_vendor_txs = []
        vendor_balances = defaultdict(Decimal)
        vendor_last_date = {}
        vendor_settlement_stats = {'count': 0, 'credit_count': 0, 'credit_sum': Decimal('0.00'), 'debit_count': 0, 'debit_sum': Decimal('0.00')}
        for idx, r in enumerate(vt_v_rows, 1):
            sup = self._match_contact_from_account_label(lookups, r.get('الحساب - الاسم'))
            if not sup:
                report['unmatched']['vendor_tx_supplier'] += 1
                continue
            ser = 50000 + idx
            reason_raw = clean_str(r.get('السبب')).lower()
            if ':' in reason_raw:
                reason_raw = reason_raw.split(':')[-1]
            reason = VENDOR_TX_REASON_MAP.get(reason_raw, 'purchase')
            credit = parse_dec(r.get('دائن'))
            debit = parse_dec(r.get('مدين'))
            tx_type = clean_str(r.get('نوع الحركة')).lower()
            if tx_type not in ('debit', 'credit'):
                tx_type = 'debit' if debit > credit else 'credit'
            tx_date = parse_date(r.get('التاريخ') or r.get('نفذ فى')) or timezone.localdate()
            vendor_balances[sup.id] += (credit - debit)
            if sup.id not in vendor_last_date or tx_date > vendor_last_date[sup.id]:
                vendor_last_date[sup.id] = tx_date
            if reason == 'settlement':
                vendor_settlement_stats['count'] += 1
                if credit > Decimal('0.00'):
                    vendor_settlement_stats['credit_count'] += 1
                    vendor_settlement_stats['credit_sum'] += credit
                if debit > Decimal('0.00'):
                    vendor_settlement_stats['debit_count'] += 1
                    vendor_settlement_stats['debit_sum'] += debit
            ref_num = clean_str(r.get('السبب - الرقم'))
            note = clean_str(r.get('ملاحظة'))
            desc_parts = [p for p in (reason_raw, ref_num, note) if p]
            parsed_vendor_txs.append({
                'serial': ser,
                'supplier': sup,
                'transaction_type': tx_type,
                'reason': reason,
                'transaction_date': tx_date,
                'credit': credit,
                'debit': debit,
                'running_balance': vendor_balances[sup.id],
                'description': ' - '.join(desc_parts)[:255] if desc_parts else f'{reason} #{ser}',
                'created_by': self._match_user(lookups, r.get('نفذ بواسطة - الاسم')),
            })

        _, vp_rows = load_xlsx_rows(_path('vendor-payments.xlsx'))
        parsed_vendor_payments = []
        for idx, r in enumerate(vp_rows, 1):
            sup = self._match_contact(
                lookups,
                serial=r.get('رقم تسلسل جهة الإتصال') or r.get('المورد - مسلسل'),
                code=r.get('كود جهة الإتصال') or r.get('المورد - الكود'),
                name=r.get('اسم جهة الإتصال') or r.get('المورد - الاسم'),
            )
            if not sup:
                report['unmatched']['vendor_payment_supplier'] += 1
                continue
            vault = self._match_vault(lookups, r.get('الخزنة - الاسم') or r.get('الخزنة')) or default_vault
            ser = parse_ref_int(r.get('رقم التسلسل') or r.get('مسلسل') or r.get('الرقم')) or (10000 + idx)
            parsed_vendor_payments.append({
                'serial_num': ser,
                'supplier': sup,
                'vault': vault,
                'payment_date': parse_date(r.get('تاريخ الإنشاء') or r.get('تاريخ الصرف')) or timezone.localdate(),
                'amount': parse_dec(r.get('الكمية') or r.get('المبلغ') or r.get('القيمة')),
                'notes': clean_str(r.get('ملاحظة التلف') or r.get('ملاحظات')),
                'created_by': self._match_user(lookups, r.get('اسم المنشء') or r.get('المنشء - الاسم')),
            })

        # Compute Nov 2026 dashboard projection
        nov_start = datetime.date(2026, 11, 1)
        nov_end = datetime.date(2026, 11, 30)
        nov_so_created = [o for o in parsed_sales_orders if nov_start <= o['order_date'] <= nov_end and o['status'] not in ('cancelled', 'rejected')]
        nov_so_deliv = [
            o for o in parsed_sales_orders
            if o['status'] in ('delivered', 'invoiced')
            and nov_start <= (o['delivery_date'] or o['order_date']) <= nov_end
        ]
        all_so_pipeline = [o for o in parsed_sales_orders if o['status'] in ('pending', 'manager_approval', 'preparing')]
        nov_ro_created = [r for r in parsed_returns if nov_start <= r['order_date'] <= nov_end and r['status'] not in ('cancelled', 'rejected')]
        nov_ro_acc = [
            r for r in parsed_returns
            if r['status'] in ('settled', 'delivered', 'approved')
            and nov_start <= (r['settled_at'].date() if r['settled_at'] else r['order_date']) <= nov_end
        ]
        nov_colls = [c for c in parsed_collections if nov_start <= c['collection_date'] <= nov_end]

        return {
            'memos': parsed_memos,
            'memos_by_source_id': memos_by_source_id,
            'stocks': parsed_stocks,
            'stock_totals': stock_totals,
            'sales_orders': parsed_sales_orders,
            'so_status_counts': dict(so_status_counts),
            'so_status_totals': {k: str(v) for k, v in so_status_totals.items()},
            'sales_returns': parsed_returns,
            'returns_missing_items': returns_missing_items,
            'collections': parsed_collections,
            'cust_txs': parsed_cust_txs,
            'cust_net_balances': cust_net_balances,
            'cust_last_date': cust_last_date,
            'cust_overdue_map': cust_overdue_map,
            'cust_due_month_map': cust_due_month_map,
            'cust_settlement_stats': cust_settlement_stats,
            'vault_txs': parsed_vault_txs,
            'vault_running': vault_running,
            'purchase_orders': parsed_pos,
            'purchase_returns': parsed_prs,
            'vendor_txs': parsed_vendor_txs,
            'vendor_balances': vendor_balances,
            'vendor_last_date': vendor_last_date,
            'vendor_settlement_stats': vendor_settlement_stats,
            'vendor_payments': parsed_vendor_payments,
            'nov_projection': {
                'so_created_count': len(nov_so_created),
                'so_created_total': sum((o['grand_total'] for o in nov_so_created), Decimal('0.00')),
                'so_deliv_count': len(nov_so_deliv),
                'so_deliv_total': sum((o['grand_total'] for o in nov_so_deliv), Decimal('0.00')),
                'so_pipeline_count': len(all_so_pipeline),
                'so_pipeline_total': sum((o['grand_total'] for o in all_so_pipeline), Decimal('0.00')),
                'ro_created_count': len(nov_ro_created),
                'ro_created_total': sum((r['grand_total'] for r in nov_ro_created), Decimal('0.00')),
                'ro_acc_count': len(nov_ro_acc),
                'ro_acc_total': sum((r['grand_total'] for r in nov_ro_acc), Decimal('0.00')),
                'collections_count': len(nov_colls),
                'collections_total': sum((c['amount'] for c in nov_colls), Decimal('0.00')),
            },
            'report': report,
        }

    def _print_reconciliation_report(self, parsed: dict, mode_label: str):
        self.stdout.write(self.style.MIGRATE_HEADING(f'\n=== WEA FINANCIAL RECONSTRUCTION REPORT ({mode_label}) ==='))
        self.stdout.write(f"Inventory Memos:        {len(parsed['memos']):,}")
        st = parsed['stock_totals']
        self.stdout.write(
            f"Inventory Stock:        {len(parsed['stocks']):,} rows | "
            f"On-Hand={st['on_hand']:,.2f} | Reserved={st['reserved']:,.2f} | "
            f"Cost={st['cost_value']:,.2f} EGP | Batch/Expiry Lots={st['lots']}"
        )
        self.stdout.write(f"Sales Orders:           {len(parsed['sales_orders']):,} | By status: {parsed['so_status_counts']}")
        self.stdout.write(f"Sales Return Orders:    {len(parsed['sales_returns']):,} | Missing line items in Excel: {len(parsed['returns_missing_items'])}")
        for rm in parsed['returns_missing_items']:
            self.stdout.write(self.style.WARNING(f"  [!] Missing SKU detail for Return #{rm['serial_num']} ({rm['customer']}, {rm['date']}, {rm['items_quantity']} pcs, {rm['grand_total']} EGP) — will NOT invent SKU"))
        self.stdout.write(f"Collections:            {len(parsed['collections']):,}")
        cs = parsed['cust_settlement_stats']
        cust_total_bal = sum(parsed['cust_net_balances'].values(), Decimal('0.00'))
        cust_nonzero = sum(1 for v in parsed['cust_net_balances'].values() if v != Decimal('0.00'))
        cust_due_m = sum(parsed['cust_due_month_map'].values(), Decimal('0.00'))
        self.stdout.write(
            f"Customer Accounts:      {len(parsed['cust_net_balances']):,} total ({cust_nonzero} non-zero) | "
            f"Net Balance={cust_total_bal:,.2f} EGP | Due This Month={cust_due_m:,.2f} EGP"
        )
        self.stdout.write(
            f"Customer Transactions:  {len(parsed['cust_txs']):,} | "
            f"Settlements={cs['count']} (Credit={cs['credit_count']}/{cs['credit_sum']:,.2f}, Debit={cs['debit_count']}/{cs['debit_sum']:,.2f}, Vault Impact=0.00)"
        )
        vault_total = sum(parsed['vault_running'].values(), Decimal('0.00'))
        self.stdout.write(f"Vault Transactions:     {len(parsed['vault_txs']):,} | Total Vault Balances={vault_total:,.2f} EGP")
        for v in Vault.objects.order_by('id'):
            bal = parsed['vault_running'].get(v.id, Decimal('0.00'))
            if bal != Decimal('0.00'):
                self.stdout.write(f"  Vault [{v.id}] {v.name}: {bal:,.2f} EGP")
        vs = parsed['vendor_settlement_stats']
        vendor_total = sum(parsed['vendor_balances'].values(), Decimal('0.00'))
        self.stdout.write(
            f"Purchases:              {len(parsed['purchase_orders']):,} POs | {len(parsed['purchase_returns']):,} PRs | "
            f"{len(parsed['vendor_payments']):,} Vendor Payments"
        )
        self.stdout.write(
            f"Vendor Accounts:        {len(parsed['vendor_balances']):,} | Total Payable={vendor_total:,.2f} EGP | "
            f"Settlements={vs['count']} (Credit={vs['credit_count']}/{vs['credit_sum']:,.2f}, Debit={vs['debit_count']}/{vs['debit_sum']:,.2f}, Vault Impact=0.00)"
        )
        nov = parsed['nov_projection']
        net_sales = max(Decimal('0.00'), nov['so_deliv_total'] - nov['ro_acc_total'])
        self.stdout.write('\n--- Projected Nov 2026 Dashboard KPIs ---')
        self.stdout.write(f"  الطلبات المنشأة:      {nov['so_created_total']:,.2f} EGP ({nov['so_created_count']} طلب)")
        self.stdout.write(f"  الطلبات المسلمة:      {nov['so_deliv_total']:,.2f} EGP ({nov['so_deliv_count']} طلب)")
        self.stdout.write(f"  الطلبات تحت التشغيل:  {nov['so_pipeline_total']:,.2f} EGP ({nov['so_pipeline_count']} طلب)")
        self.stdout.write(f"  المرتجعات المنشأة:    {nov['ro_created_total']:,.2f} EGP ({nov['ro_created_count']} مرتجع)")
        self.stdout.write(f"  المرتجعات المقبولة:   {nov['ro_acc_total']:,.2f} EGP ({nov['ro_acc_count']} مرتجع)")
        self.stdout.write(f"  صافي المبيعات:        {net_sales:,.2f} EGP")
        self.stdout.write(f"  التحصيلات:            {nov['collections_total']:,.2f} EGP ({nov['collections_count']} تحصيل)")
        unmatched = dict(parsed['report']['unmatched'])
        if unmatched:
            self.stdout.write(self.style.WARNING(f"\nUnmatched rows summary: {unmatched}"))
        else:
            self.stdout.write(self.style.SUCCESS('\nUnmatched rows summary: 0 unmatched across all tables!'))

    @transaction.atomic
    def _apply_reconstruction(self, parsed: dict, snapshot_items: dict):
        # 1. FK-safe deletion of ONLY financial & inventory transactional tables
        ApprovalAuditLog.objects.filter(
            record_type__in=['sales_order', 'sales_return', 'purchase_order', 'purchase_return', 'payment_request']
        ).delete()
        Settlement.objects.all().delete()
        VendorInstallment.objects.all().delete()
        VendorPaymentRequest.objects.all().delete()
        VendorPayment.objects.all().delete()
        VendorTransaction.objects.all().delete()
        VendorAccount.objects.all().delete()
        VaultTransaction.objects.all().delete()
        Collection.objects.all().delete()
        CustomerTransaction.objects.all().delete()
        CustomerAccount.objects.all().delete()
        SalesReturnOrderItem.objects.all().delete()
        SalesReturnOrder.objects.all().delete()
        SalesOrderItem.objects.all().delete()
        SalesOrder.objects.all().delete()
        PurchaseReturnOrderItem.objects.all().delete()
        PurchaseReturnOrder.objects.all().delete()
        PurchaseOrderItem.objects.all().delete()
        PurchaseOrder.objects.all().delete()
        InventoryMemoItem.objects.all().delete()
        InventoryMemo.objects.all().delete()
        InventoryLot.objects.all().delete()
        InventoryStock.objects.all().delete()

        # 2. Memos
        memo_objs = [
            InventoryMemo(
                serial_num=m['serial_num'],
                memo_number=f"MEMO-{m['serial_num']}",
                memo_type=m['memo_type'],
                warehouse=m['warehouse'],
                status=m['status'],
                notes=m['notes'],
                created_by=m['created_by'],
            )
            for m in parsed['memos']
        ]
        InventoryMemo.objects.bulk_create(memo_objs, batch_size=500)
        memo_by_serial = {m.serial_num: m for m in InventoryMemo.objects.all()}

        # 3. InventoryStock & InventoryLot
        stock_agg = {}
        for s in parsed['stocks']:
            key = (s['warehouse'].id, s['product'].id)
            if key not in stock_agg:
                stock_agg[key] = {
                    'warehouse': s['warehouse'],
                    'product': s['product'],
                    'qty_on_hand': Decimal('0.00'),
                    'qty_reserved': Decimal('0.00'),
                    'product_cost': s['product_cost'],
                }
            stock_agg[key]['qty_on_hand'] += s['qty_on_hand']
            stock_agg[key]['qty_reserved'] += s['qty_reserved']

        InventoryStock.objects.bulk_create([
            InventoryStock(
                warehouse=v['warehouse'],
                product=v['product'],
                qty_on_hand=v['qty_on_hand'],
                qty_reserved=v['qty_reserved'],
                product_cost=v['product_cost'],
            )
            for v in stock_agg.values()
        ], batch_size=500)
        stock_map = {(st.warehouse_id, st.product_id): st for st in InventoryStock.objects.all()}

        lot_objs = []
        for s in parsed['stocks']:
            if s['batch_number'] or s['expiry_date']:
                st_obj = stock_map.get((s['warehouse'].id, s['product'].id))
                if st_obj:
                    lot_objs.append(InventoryLot(
                        stock=st_obj,
                        batch_number=s['batch_number'] or 'DEFAULT',
                        expiry_date=s['expiry_date'],
                        quantity=s['qty_on_hand'],
                    ))
        if lot_objs:
            InventoryLot.objects.bulk_create(lot_objs, batch_size=500)

        # 4. Sales Orders & Items
        so_objs = []
        used_memo_ids = set()
        for o in parsed['sales_orders']:
            m_ser = parsed['memos_by_source_id'].get(o['source_id'])
            memo_obj = memo_by_serial.get(m_ser) if m_ser else None
            if memo_obj and memo_obj.id in used_memo_ids:
                memo_obj = None
            elif memo_obj:
                used_memo_ids.add(memo_obj.id)
            so_objs.append(SalesOrder(
                serial_num=o['serial_num'],
                order_number=o['order_number'],
                customer=o['customer'],
                source_warehouse=o['source_warehouse'],
                order_date=o['order_date'],
                delivery_date=o['delivery_date'],
                due_date=o['due_date'],
                status=o['status'],
                memo=memo_obj,
                subtotal=o['subtotal'],
                grand_total=o['grand_total'],
                notes=o['notes'],
                created_by=o['created_by'],
            ))
        SalesOrder.objects.bulk_create(so_objs, batch_size=500)
        so_by_serial = {o.serial_num: o for o in SalesOrder.objects.all()}

        so_item_objs = []
        for o in parsed['sales_orders']:
            so_obj = so_by_serial.get(o['serial_num'])
            if not so_obj:
                continue
            for it in o['items']:
                sub = (it['quantity'] * it['unit_price']).quantize(Decimal('0.01'))
                so_item_objs.append(SalesOrderItem(
                    order=so_obj,
                    product=it['product'],
                    quantity=it['quantity'],
                    unit_price=it['unit_price'],
                    discount_percentage=it['discount_percentage'],
                    discount_amount=it['discount_amount'],
                    subtotal=sub,
                ))
        if so_item_objs:
            SalesOrderItem.objects.bulk_create(so_item_objs, batch_size=1000)

        # 5. Sales Return Orders & snapshotted SalesReturnOrderItems
        ro_objs = []
        for r in parsed['sales_returns']:
            m_ser = parsed['memos_by_source_id'].get(r['source_id'])
            memo_obj = memo_by_serial.get(m_ser) if m_ser else None
            if memo_obj and memo_obj.id in used_memo_ids:
                memo_obj = None
            elif memo_obj:
                used_memo_ids.add(memo_obj.id)
            ro_objs.append(SalesReturnOrder(
                serial_num=r['serial_num'],
                order_number=r['order_number'],
                customer=r['customer'],
                target_warehouse=memo_obj.warehouse if memo_obj else None,
                order_date=r['order_date'],
                status=r['status'],
                memo=memo_obj,
                settled_at=r['settled_at'],
                stocked_at=r['stocked_at'],
                items_count=r['items_count'],
                items_quantity=r['items_quantity'],
                subtotal=r['subtotal'],
                grand_total=r['grand_total'],
                created_by=r['created_by'],
            ))
        SalesReturnOrder.objects.bulk_create(ro_objs, batch_size=500)
        ro_by_serial = {r.serial_num: r for r in SalesReturnOrder.objects.all()}

        ro_item_objs = []
        for ser_str, items_list in snapshot_items.items():
            ro_obj = ro_by_serial.get(int(ser_str))
            if not ro_obj:
                continue
            for it in items_list:
                ro_item_objs.append(SalesReturnOrderItem(
                    order=ro_obj,
                    product_id=it['product_id'],
                    condition=it['condition'],
                    quantity=Decimal(it['quantity']),
                    unit_price=Decimal(it['unit_price']),
                    discount_percentage=Decimal(it['discount_percentage']),
                    discount_amount=Decimal(it['discount_amount']),
                    tax_percentage=Decimal(it['tax_percentage']),
                    tax_amount=Decimal(it['tax_amount']),
                    subtotal=Decimal(it['subtotal']),
                    total=Decimal(it['total']),
                    batch_number=it['batch_number'],
                    expiry_date=datetime.date.fromisoformat(it['expiry_date']) if it['expiry_date'] else None,
                ))
        if ro_item_objs:
            SalesReturnOrderItem.objects.bulk_create(ro_item_objs, batch_size=500)

        # 6. Collections
        Collection.objects.bulk_create([
            Collection(
                serial_num=c['serial_num'],
                customer=c['customer'],
                vault=c['vault'],
                amount=c['amount'],
                collection_date=c['collection_date'],
                payment_method=c['payment_method'],
                notes=c['notes'],
                created_by=c['created_by'],
            )
            for c in parsed['collections']
        ], batch_size=500)

        # 7. Customer Accounts & Transactions
        cust_acc_objs = []
        all_cust_ids = set(parsed['cust_net_balances'].keys()) | set(parsed['cust_overdue_map'].keys())
        for cid in all_cust_ids:
            cust_acc_objs.append(CustomerAccount(
                customer_id=cid,
                current_balance=parsed['cust_net_balances'].get(cid, Decimal('0.00')),
                overdue_balance=parsed['cust_overdue_map'].get(cid, Decimal('0.00')),
                due_this_month_balance=parsed['cust_due_month_map'].get(cid, Decimal('0.00')),
                last_transaction_date=parsed['cust_last_date'].get(cid),
            ))
        CustomerAccount.objects.bulk_create(cust_acc_objs, batch_size=500)
        ca_by_cust = {ca.customer_id: ca for ca in CustomerAccount.objects.all()}

        CustomerTransaction.objects.bulk_create([
            CustomerTransaction(
                serial=t['serial'],
                account=ca_by_cust[t['customer'].id],
                transaction_type=t['transaction_type'],
                reason=t['reason'],
                transaction_date=t['transaction_date'],
                due_date=t['due_date'],
                debit=t['debit'],
                credit=t['credit'],
                running_balance=t['running_balance'],
                description=t['description'],
                created_by=t['created_by'],
            )
            for t in parsed['cust_txs']
            if t['customer'].id in ca_by_cust
        ], batch_size=1000)

        # 8. Vault Transactions & Vault Balances
        VaultTransaction.objects.bulk_create([
            VaultTransaction(
                vault=vt['vault'],
                transaction_type=vt['transaction_type'],
                amount=vt['amount'],
                running_balance=vt['running_balance'],
                reference_type=vt['reference_type'],
                description=vt['description'],
                created_by=vt['created_by'],
            )
            for vt in parsed['vault_txs']
        ], batch_size=500)
        for v in Vault.objects.all():
            v.current_balance = parsed['vault_running'].get(v.id, Decimal('0.00'))
            v.save(update_fields=['current_balance'])

        # 9. Purchases, Vendor Accounts, Vendor Transactions, Vendor Payments
        po_objs = [
            PurchaseOrder(
                serial_num=p['serial_num'],
                order_number=p['order_number'],
                supplier=p['supplier'],
                target_warehouse=p['target_warehouse'],
                order_date=p['order_date'],
                status=p['status'],
                subtotal=p['subtotal'],
                grand_total=p['grand_total'],
                created_by=p['created_by'],
            )
            for p in parsed['purchase_orders']
        ]
        PurchaseOrder.objects.bulk_create(po_objs, batch_size=200)
        po_by_serial = {p.serial_num: p for p in PurchaseOrder.objects.all()}

        po_items = []
        for p in parsed['purchase_orders']:
            po_obj = po_by_serial.get(p['serial_num'])
            if not po_obj:
                continue
            for idx, it in enumerate(p['items'], 1):
                sub = (it['quantity'] * it['unit_price']).quantize(Decimal('0.01'))
                po_items.append(PurchaseOrderItem(
                    order=po_obj,
                    item_order=idx,
                    product=it['product'],
                    quantity=it['quantity'],
                    unit_price=it['unit_price'],
                    subtotal=sub,
                    total_price=sub,
                ))
        if po_items:
            PurchaseOrderItem.objects.bulk_create(po_items, batch_size=200)

        PurchaseReturnOrder.objects.bulk_create([
            PurchaseReturnOrder(
                serial_num=pr['serial_num'],
                order_number=pr['order_number'],
                supplier=pr['supplier'],
                warehouse=pr['warehouse'],
                order_date=pr['order_date'],
                grand_total=pr['grand_total'],
                created_by=pr['created_by'],
            )
            for pr in parsed['purchase_returns']
        ], batch_size=100)

        VendorAccount.objects.bulk_create([
            VendorAccount(
                supplier_id=sid,
                current_balance=bal,
                last_transaction_date=parsed['vendor_last_date'].get(sid),
            )
            for sid, bal in parsed['vendor_balances'].items()
        ], batch_size=100)
        va_by_sup = {va.supplier_id: va for va in VendorAccount.objects.all()}

        VendorTransaction.objects.bulk_create([
            VendorTransaction(
                serial=vt['serial'],
                account=va_by_sup[vt['supplier'].id],
                transaction_type=vt['transaction_type'],
                reason=vt['reason'],
                transaction_date=vt['transaction_date'],
                credit=vt['credit'],
                debit=vt['debit'],
                running_balance=vt['running_balance'],
                description=vt['description'],
                created_by=vt['created_by'],
            )
            for vt in parsed['vendor_txs']
            if vt['supplier'].id in va_by_sup
        ], batch_size=200)

        VendorPayment.objects.bulk_create([
            VendorPayment(
                serial_num=vp['serial_num'],
                supplier=vp['supplier'],
                vault=vp['vault'],
                payment_date=vp['payment_date'],
                amount=vp['amount'],
                notes=vp['notes'],
                created_by=vp['created_by'],
            )
            for vp in parsed['vendor_payments']
        ], batch_size=200)

        AuditLogService.log(
            action='update',
            action_type='WEA_FINANCIAL_RECONSTRUCTION_APPLIED',
            module='master_data',
            actor=None,
            record_name='WEA Financial Reconstruction',
            description=(
                f"Applied full WEA financial & inventory reconstruction: "
                f"{len(parsed['sales_orders'])} SOs, {len(parsed['sales_returns'])} SRs, "
                f"{len(parsed['collections'])} Collections, {len(parsed['cust_txs'])} CustTxs, "
                f"{len(parsed['vault_txs'])} VaultTxs, {len(parsed['stocks'])} Stock rows."
            ),
        )

    def handle(self, *args, **options):
        data_dir = options['data_dir']
        backup_only = options['backup_only']
        do_apply = options['apply']
        confirm_reset = options['confirm_reset']

        if do_apply and not confirm_reset:
            raise CommandError(
                'SAFETY GATE: --apply requires --confirm-reset to execute destructive financial reset. '
                'Run with --dry-run first to verify reconciliation figures.'
            )

        if backup_only:
            binfo = self._create_verified_backup()
            self.stdout.write(self.style.SUCCESS(
                f"Verified backup created: {binfo['backup_path']} ({binfo['backup_size_mb']} MB, SHA-256={binfo['backup_sha256'][:16]}...)\n"
                f"SalesReturnOrderItem snapshot: {binfo['snapshot_path']} ({binfo['snapshot_item_count']} items across {binfo['snapshot_return_count']} returns)"
            ))
            return

        lookups = self._build_lookups()
        parsed = self._parse_all_sources(data_dir, lookups)

        if not do_apply:
            self._print_reconciliation_report(parsed, mode_label='DRY-RUN — ZERO DB MUTATIONS')
            return

        # Apply mode: always create verified backup + return-item snapshot first
        binfo = self._create_verified_backup()
        self.stdout.write(self.style.SUCCESS(
            f"Pre-reset backup verified: {binfo['backup_path']} ({binfo['backup_size_mb']} MB, SHA-256={binfo['backup_sha256'][:16]}...)"
        ))
        self._apply_reconstruction(parsed, binfo['items_by_serial'])
        self._print_reconciliation_report(parsed, mode_label='APPLIED TO DATABASE')
