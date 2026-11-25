"""
Management command to synchronize Contact statuses ('customer', 'lead', 'inactive')
from Contacts.xlsx and optionally import missing Excel contacts (--add-missing).
"""

from collections import Counter
from decimal import Decimal, InvalidOperation
import os

import openpyxl
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.services import AuditLogService
from contacts.models import Contact, ContactAddress, ContactCommunicationMethod
from master_data.models import Area
from master_data.search_utils import normalize_arabic_text


EXCEL_STATUS_MAP = {
    'lead': 'lead',
    'customers:status:lead': 'lead',
    'عميل محتمل': 'lead',
    'inactive': 'inactive',
    'customers:status:inactive': 'inactive',
    'غير نشط': 'inactive',
    'معطل': 'inactive',
    '<not set>': 'inactive',
    'builtin:not_set_state': 'inactive',
    'customer': 'customer',
    'customers:status:customer': 'customer',
    'active': 'customer',
    'عميل': 'customer',
    'نشط': 'customer',
}


def clean_excel_str(val) -> str:
    if val is None:
        return ''
    s = str(val).strip()
    return '' if s.lower() in ('none', 'nan') else s


def clean_excel_phone(val) -> str:
    s = clean_excel_str(val)
    if not s:
        return ''
    if s.endswith('.0'):
        s = s[:-2]
    digits = ''.join(ch for ch in s if ch.isdigit())
    if digits.startswith('20') and len(digits) >= 11:
        digits = '0' + digits[2:]
    return digits[:30]


def parse_coords_pair(raw_coords):
    s = clean_excel_str(raw_coords)
    if not s or ',' not in s:
        return None, None
    parts = [p.strip() for p in s.split(',', 1)]
    if len(parts) != 2:
        return None, None
    try:
        lat = Decimal(parts[0]).quantize(Decimal('0.0000001'))
        lng = Decimal(parts[1]).quantize(Decimal('0.0000001'))
        if Decimal('-90') <= lat <= Decimal('90') and Decimal('-180') <= lng <= Decimal('180'):
            return lat, lng
    except (InvalidOperation, ValueError):
        pass
    return None, None


def resolve_excel_contact_status(status_name, status_code):
    """
    Maps Excel status columns to canonical lowercase status:
    - Customer -> 'customer'
    - Lead -> 'lead'
    - Inactive / blank / <not set> -> 'inactive'
    """
    for raw in (status_name, status_code):
        token = clean_excel_str(raw).lower()
        if not token:
            continue
        if token in EXCEL_STATUS_MAP:
            return EXCEL_STATUS_MAP[token]
    return 'inactive'


class Command(BaseCommand):
    help = "Update Contact statuses ('customer' / 'lead' / 'inactive') from Contacts.xlsx and optionally add missing rows (--add-missing)."

    def add_arguments(self, parser):
        parser.add_argument(
            '--file',
            type=str,
            default='wea data/Contacts.xlsx',
            help='Path to the Contacts.xlsx workbook (default: wea data/Contacts.xlsx)',
        )
        parser.add_argument(
            '--add-missing',
            action='store_true',
            help='Also import Excel rows whose UUID/serial does not exist in DB (skipping serial collisions).',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Simulate and report changes without writing to the database.',
        )

    def handle(self, *args, **options):
        filepath = options['file']
        add_missing = bool(options['add_missing'])
        dry_run = bool(options['dry_run'])

        if not filepath or not os.path.isfile(filepath):
            raise CommandError(f"Excel file not found: '{filepath}'")

        wb = openpyxl.load_workbook(filepath, read_only=True, data_only=True)
        try:
            ws = wb.active
            ws.reset_dimensions()
            rows = list(ws.iter_rows(values_only=True))
        finally:
            wb.close()

        if not rows:
            raise CommandError(f"Excel file '{filepath}' is empty.")

        headers = [str(h).strip() if h is not None else '' for h in rows[0]]
        required_cols = ('المعرف', 'الاسم', 'مسلسل', 'حالة العميل - الكود', 'حالة العميل - الاسم')
        missing = [c for c in required_cols if c not in headers]
        if missing:
            raise CommandError(f"Missing required column(s) in '{filepath}': {', '.join(missing)}")

        col_idx = {h: i for i, h in enumerate(headers) if h}

        def get_val(row, col_name):
            i = col_idx.get(col_name)
            if i is None or i >= len(row):
                return None
            return row[i]

        excel_rows = []
        excel_by_uuid = {}
        excel_by_serial = {}

        for r in rows[1:]:
            if not r or not any(v is not None and str(v).strip() != '' for v in r):
                continue
            uuid_val = clean_excel_str(get_val(r, 'المعرف'))
            name_val = clean_excel_str(get_val(r, 'الاسم'))
            raw_ser = get_val(r, 'مسلسل')
            ser_val = None
            if raw_ser is not None and str(raw_ser).strip() != '':
                try:
                    ser_val = int(str(raw_ser).strip())
                except (TypeError, ValueError):
                    ser_val = None
            st_code = get_val(r, 'حالة العميل - الكود')
            st_name = get_val(r, 'حالة العميل - الاسم')
            target_status = resolve_excel_contact_status(st_name, st_code)

            row_rec = {
                'uuid': uuid_val,
                'name': name_val,
                'serial_num': ser_val,
                'code': clean_excel_str(get_val(r, 'الكود'))[:100],
                'status': target_status,
                'account_type': clean_excel_str(get_val(r, 'نوع الاكونت'))[:100],
                'customer_category': clean_excel_str(get_val(r, 'تصنيف العميل'))[:10],
                'specialty': clean_excel_str(get_val(r, 'التخصص'))[:150],
                'mobile': clean_excel_phone(get_val(r, 'الموبايل')),
                'gov_code': clean_excel_str(get_val(r, 'المنطقة - المنطقة الرئيسية - الكود')),
                'gov_name': clean_excel_str(get_val(r, 'المنطقة - المنطقة الرئيسية - الاسم')),
                'brick_code': clean_excel_str(get_val(r, 'المنطقة - الكود')),
                'brick_name': clean_excel_str(get_val(r, 'المنطقة - الاسم')),
                'legacy_group': clean_excel_str(get_val(r, 'المنطقة - المجموعة')),
                'addr_title': clean_excel_str(get_val(r, 'العنوان الرئيسي - الاسم'))[:150] or 'العنوان الرئيسي',
                'addr_street': clean_excel_str(get_val(r, 'العنوان الرئيسي - العنوان')),
                'coords': get_val(r, 'العنوان الرئيسي - الموقع - الإحداثيات'),
            }
            excel_rows.append(row_rec)
            if uuid_val:
                excel_by_uuid[uuid_val] = row_rec
            if ser_val is not None:
                excel_by_serial[ser_val] = row_rec

        ids_by_target = {'customer': [], 'lead': [], 'inactive': []}
        transitions = Counter()
        matched_by_uuid = 0
        matched_by_serial_name = 0
        skipped_collision = 0
        unmatched = 0
        unchanged = 0
        matched_excel_uuids = set()
        matched_excel_serials = set()
        existing_db_serials = set()

        for contact in Contact.objects.only('id', 'serial_num', 'name', 'status', 'custom_values').iterator(chunk_size=1000):
            if contact.serial_num is not None:
                existing_db_serials.add(contact.serial_num)
            cv = contact.custom_values if isinstance(contact.custom_values, dict) else {}
            src_uuid = str(cv.get('source_uuid') or '').strip()

            matched_rec = None
            if src_uuid:
                if src_uuid in excel_by_uuid:
                    matched_rec = excel_by_uuid[src_uuid]
                    matched_by_uuid += 1
                else:
                    unmatched += 1
            elif contact.serial_num in excel_by_serial:
                cand = excel_by_serial[contact.serial_num]
                if normalize_arabic_text(contact.name) == normalize_arabic_text(cand['name']):
                    matched_rec = cand
                    matched_by_serial_name += 1
                else:
                    skipped_collision += 1
            else:
                unmatched += 1

            if not matched_rec:
                continue

            if matched_rec['uuid']:
                matched_excel_uuids.add(matched_rec['uuid'])
            if matched_rec['serial_num'] is not None:
                matched_excel_serials.add(matched_rec['serial_num'])

            target_status = matched_rec['status']
            if contact.status == target_status:
                unchanged += 1
                continue

            ids_by_target[target_status].append(contact.id)
            transitions[f"{contact.status}->{target_status}"] += 1

        extra_to_add = []
        skipped_extra_serial_collision = 0
        created_status_counts = Counter()
        bricks_needed = {}

        if add_missing:
            for rec in excel_rows:
                u = rec['uuid']
                s = rec['serial_num']
                if (u and u in matched_excel_uuids) or (s is not None and s in matched_excel_serials):
                    continue
                if s is None or s in existing_db_serials:
                    skipped_extra_serial_collision += 1
                    continue
                existing_db_serials.add(s)
                extra_to_add.append(rec)
                created_status_counts[rec['status']] += 1
                if rec['brick_name']:
                    bkey = (rec['gov_code'], rec['gov_name'], rec['brick_code'], rec['brick_name'])
                    bricks_needed[bkey] = rec

        total_updates = sum(len(v) for v in ids_by_target.values())
        total_created = len(extra_to_add)

        # Inspect/prepare area & brick caches when adding missing contacts
        gov_by_code = {}
        gov_by_name = {}
        brick_by_code = {}
        brick_by_name = {}
        missing_bricks_to_create = []
        if add_missing and extra_to_add:
            for a in Area.objects.filter(parent__isnull=True):
                if a.code:
                    gov_by_code[a.code.strip()] = a
                if a.name:
                    gov_by_name[a.name.strip()] = a
            for b in Area.objects.filter(parent__isnull=False):
                if b.code:
                    brick_by_code[(b.parent_id, b.code.strip())] = b
                    brick_by_code[('_any_', b.code.strip())] = b
                if b.name:
                    brick_by_name[(b.parent_id, b.name.strip())] = b
                    brick_by_name[('_any_', b.name.strip())] = b

            for bkey, rec in bricks_needed.items():
                gov = gov_by_code.get(rec['gov_code']) or gov_by_name.get(rec['gov_name'])
                gov_id = gov.id if gov else None
                b_obj = (
                    (gov_id and brick_by_code.get((gov_id, rec['brick_code'])))
                    or (gov_id and brick_by_name.get((gov_id, rec['brick_name'])))
                    or brick_by_code.get(('_any_', rec['brick_code']))
                    or brick_by_name.get(('_any_', rec['brick_name']))
                )
                if not b_obj and gov is not None:
                    missing_bricks_to_create.append((gov, rec['brick_code'], rec['brick_name']))

        summary = {
            'file': filepath,
            'add_missing': add_missing,
            'dry_run': dry_run,
            'excel_uuid_rows': len(excel_by_uuid),
            'matched_by_uuid': matched_by_uuid,
            'matched_by_serial_name': matched_by_serial_name,
            'skipped_collision': skipped_collision,
            'unmatched': unmatched,
            'unchanged': unchanged,
            'total_updates': total_updates,
            'transitions': dict(transitions),
            'total_created': total_created,
            'created_status_counts': dict(created_status_counts),
            'skipped_extra_serial_collision': skipped_extra_serial_collision,
            'bricks_created': len(missing_bricks_to_create),
        }

        if not dry_run and (total_updates > 0 or total_created > 0):
            with transaction.atomic():
                for target_status, id_list in ids_by_target.items():
                    if id_list:
                        for start in range(0, len(id_list), 900):
                            batch = id_list[start:start + 900]
                            Contact.objects.filter(id__in=batch).update(status=target_status)

                if add_missing and extra_to_add:
                    for gov, b_code, b_name in missing_bricks_to_create:
                        b_obj = None
                        if b_code:
                            b_obj = Area.objects.filter(parent=gov, code=b_code).first()
                        if not b_obj:
                            b_obj, _ = Area.objects.get_or_create(
                                name=b_name,
                                parent=gov,
                                defaults={'code': b_code or None, 'area_type': 'subarea'},
                            )
                        if b_obj.code:
                            brick_by_code[(gov.id, b_obj.code.strip())] = b_obj
                            brick_by_code[('_any_', b_obj.code.strip())] = b_obj
                        if b_obj.name:
                            brick_by_name[(gov.id, b_obj.name.strip())] = b_obj
                            brick_by_name[('_any_', b_obj.name.strip())] = b_obj

                    new_contacts = []
                    meta_by_serial = {}
                    for rec in extra_to_add:
                        gov = gov_by_code.get(rec['gov_code']) or gov_by_name.get(rec['gov_name'])
                        gov_id = gov.id if gov else None
                        brick = (
                            (gov_id and brick_by_code.get((gov_id, rec['brick_code'])))
                            or (gov_id and brick_by_name.get((gov_id, rec['brick_name'])))
                            or brick_by_code.get(('_any_', rec['brick_code']))
                            or brick_by_name.get(('_any_', rec['brick_name']))
                        )
                        is_supplier = (rec['account_type'] == 'مورد')
                        is_customer = not is_supplier
                        cv_payload = {}
                        if rec['uuid']:
                            cv_payload['source_uuid'] = rec['uuid']
                        if rec['legacy_group']:
                            cv_payload['legacy_group'] = rec['legacy_group']

                        new_contacts.append(Contact(
                            serial_num=rec['serial_num'],
                            name=rec['name'] or f"عميل #{rec['serial_num']}",
                            code=rec['code'],
                            contact_type='organization',
                            is_customer=is_customer,
                            is_supplier=is_supplier,
                            account_type=rec['account_type'],
                            customer_category=rec['customer_category'],
                            specialty=rec['specialty'],
                            mobile=rec['mobile'],
                            area=gov,
                            brick=brick,
                            status=rec['status'],
                            custom_values=cv_payload,
                        ))
                        meta_by_serial[rec['serial_num']] = (rec, gov, brick)

                    Contact.objects.bulk_create(new_contacts, batch_size=500)

                    created_contacts = list(
                        Contact.objects.filter(serial_num__in=list(meta_by_serial.keys()))
                    )
                    addresses_to_create = []
                    comms_to_create = []
                    customer_accounts_to_create = []
                    vendor_accounts_to_create = []

                    from sales.models import CustomerAccount
                    from treasury.models import VendorAccount

                    existing_ca_cids = set(
                        CustomerAccount.objects.filter(customer__in=created_contacts).values_list('customer_id', flat=True)
                    )
                    existing_va_cids = set(
                        VendorAccount.objects.filter(supplier__in=created_contacts).values_list('supplier_id', flat=True)
                    )

                    for c in created_contacts:
                        rec, gov, brick = meta_by_serial[c.serial_num]
                        lat, lng = parse_coords_pair(rec['coords'])
                        if rec['addr_street'] or lat is not None:
                            addresses_to_create.append(ContactAddress(
                                contact=c,
                                title=rec['addr_title'],
                                is_main=True,
                                street_address=rec['addr_street'],
                                area=gov,
                                brick=brick,
                                latitude=lat,
                                longitude=lng,
                            ))
                        if c.mobile:
                            comms_to_create.append(ContactCommunicationMethod(
                                contact=c,
                                method_type='mobile',
                                value=c.mobile,
                                label='الموبايل الرئيسي',
                                is_primary=True,
                            ))
                        if c.is_customer and c.id not in existing_ca_cids:
                            customer_accounts_to_create.append(CustomerAccount(
                                customer=c,
                                credit_limit=c.credit_limit or Decimal('0.00'),
                                credit_period_days=c.credit_period_days or 30,
                                current_balance=Decimal('0.00'),
                                overdue_balance=Decimal('0.00'),
                            ))
                        if c.is_supplier and c.id not in existing_va_cids:
                            vendor_accounts_to_create.append(VendorAccount(
                                supplier=c,
                                credit_limit=c.credit_limit or Decimal('0.00'),
                                credit_period_days=c.credit_period_days or 30,
                                current_balance=Decimal('0.00'),
                            ))

                    if addresses_to_create:
                        ContactAddress.objects.bulk_create(addresses_to_create, batch_size=500)
                    if comms_to_create:
                        ContactCommunicationMethod.objects.bulk_create(comms_to_create, batch_size=500)
                    if customer_accounts_to_create:
                        CustomerAccount.objects.bulk_create(customer_accounts_to_create, batch_size=500)
                    if vendor_accounts_to_create:
                        VendorAccount.objects.bulk_create(vendor_accounts_to_create, batch_size=500)

                AuditLogService.log(
                    actor=None,
                    action_type='BULK_IMPORT',
                    module='contacts',
                    record_name='Contacts.xlsx',
                    description=(
                        f"مزامنة جهات الاتصال من '{filepath}': "
                        f"تحديث {total_updates} حالة ({dict(transitions)})، وإضافة {total_created} جهة اتصال جديدة."
                    ),
                    new_values=summary,
                )

        mode_label = "[DRY-RUN] " if dry_run else ""
        self.stdout.write(
            f"{mode_label}Matched by UUID: {matched_by_uuid}, by serial+name: {matched_by_serial_name}, "
            f"skipped collisions: {skipped_collision}, unmatched: {unmatched}, unchanged: {unchanged}, "
            f"updated: {total_updates}, transitions: {dict(transitions)}, "
            f"created: {total_created}, created_statuses: {dict(created_status_counts)}, "
            f"skipped_extra_serial_collisions: {skipped_extra_serial_collision}, bricks_created: {len(missing_bricks_to_create)}"
        )
