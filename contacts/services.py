"""
Domain services for the contacts app.
"""
import csv
import logging
from pathlib import Path
from typing import Iterable, Optional

from django.conf import settings
from django.db import transaction

from master_data.search_utils import normalize_arabic_text

logger = logging.getLogger(__name__)


def _resolve_supplier_source_files(source_path: str) -> list[Path]:
    """
    Resolve a supplier source directory or file path into concrete readable file paths.
    Supports directories containing .xlsx/.xls/.csv/.txt or direct files, including
    falling back to `<source_path>.xlsx` when `<source_path>` is referenced as a folder name.
    """
    raw = Path(source_path)
    if not raw.is_absolute():
        base_dir = Path(getattr(settings, 'BASE_DIR', '.'))
        candidate = base_dir / raw
    else:
        candidate = raw

    if candidate.is_dir():
        supported_exts = {'.xlsx', '.xls', '.csv', '.txt'}
        return sorted(
            p for p in candidate.iterdir()
            if p.is_file() and p.suffix.lower() in supported_exts and not p.name.startswith('~$')
        )

    if candidate.is_file():
        return [candidate]

    # Check common file extension siblings (e.g. data_folder/suppliers -> data_folder/suppliers.xlsx)
    for ext in ('.xlsx', '.xls', '.csv', '.txt'):
        alt = candidate.with_suffix(ext)
        if alt.is_file():
            return [alt]

    raise FileNotFoundError(f"Supplier source path not found: {source_path}")


def _read_supplier_entries_from_file(file_path: Path) -> list[dict]:
    """
    Read supplier entries from an Excel, CSV, or plain text file.
    Returns list of dicts with keys: 'name', 'serial_num' (optional), 'source_uuid' (optional), 'source'.
    """
    suffix = file_path.suffix.lower()
    entries = []

    if suffix in ('.xlsx', '.xls'):
        import pandas as pd
        df = pd.read_excel(file_path)
        cols = [str(c).strip() for c in df.columns]
        name_col = next(
            (c for c in cols if c in ('الاسم', 'اسم المورد', 'المورد', 'name', 'supplier_name', 'Name')),
            cols[0] if cols else None,
        )
        serial_col = next((c for c in cols if c in ('مسلسل', 'serial', 'serial_num')), None)
        uuid_col = next((c for c in cols if c in ('المعرف', 'uuid', 'source_uuid')), None)

        if not name_col:
            return entries

        for _, row in df.iterrows():
            raw_name = row.get(name_col)
            if pd.isna(raw_name):
                continue
            name_str = str(raw_name).strip()
            if not name_str:
                continue

            serial_val = None
            if serial_col and pd.notna(row.get(serial_col)):
                try:
                    serial_val = int(row.get(serial_col))
                except (TypeError, ValueError):
                    serial_val = None

            uuid_val = None
            if uuid_col and pd.notna(row.get(uuid_col)):
                uuid_val = str(row.get(uuid_col)).strip() or None

            entries.append({
                'name': name_str,
                'serial_num': serial_val,
                'source_uuid': uuid_val,
                'source': file_path.name,
            })

    elif suffix == '.csv':
        with file_path.open('r', encoding='utf-8-sig', newline='') as f:
            reader = csv.DictReader(f)
            if reader.fieldnames:
                name_col = next(
                    (c for c in reader.fieldnames if c.strip() in ('الاسم', 'اسم المورد', 'المورد', 'name', 'supplier_name')),
                    reader.fieldnames[0],
                )
                for row in reader:
                    val = (row.get(name_col) or '').strip()
                    if val:
                        entries.append({'name': val, 'serial_num': None, 'source_uuid': None, 'source': file_path.name})

    elif suffix == '.txt':
        with file_path.open('r', encoding='utf-8-sig') as f:
            for line in f:
                val = line.strip()
                if val:
                    entries.append({'name': val, 'serial_num': None, 'source_uuid': None, 'source': file_path.name})

    return entries


def extract_supplier_names_from_source(source_path: str = 'data_folder/suppliers') -> list[dict]:
    """
    Load supplier records from `source_path` without modifying the database.
    """
    files = _resolve_supplier_source_files(source_path)
    entries = []
    for file_path in files:
        entries.extend(_read_supplier_entries_from_file(file_path))
    return entries


@transaction.atomic
def activate_suppliers_from_source(
    source_path: Optional[str] = 'data_folder/suppliers',
    supplier_names: Optional[Iterable[str]] = None,
) -> dict:
    """
    Safely match existing Contact records against supplier names (from `supplier_names` or
    `source_path`) using Arabic text normalization, and set `is_supplier=True` without
    creating new contacts, creating duplicates, or modifying unrelated records.

    Returns a detailed summary dict:
        {
            'total_input': int,
            'matched': [...],
            'activated': [...],
            'already_active': [...],
            'unmatched': [...],
            'ambiguous': [...],
        }
    """
    from contacts.models import Contact
    from treasury.models import VendorAccount

    if supplier_names is not None:
        entries = [
            {'name': str(n).strip(), 'serial_num': None, 'source_uuid': None, 'source': 'direct_list'}
            for n in supplier_names
            if str(n).strip()
        ]
    else:
        entries = extract_supplier_names_from_source(source_path or 'data_folder/suppliers')

    # Build normalized name index over existing contacts without duplicating or creating contacts
    all_contacts = list(
        Contact.objects.all().only(
            'id', 'serial_num', 'name', 'is_supplier',
            'credit_limit', 'credit_period_days', 'custom_values',
        )
    )
    normalized_index = {}
    for contact in all_contacts:
        norm = normalize_arabic_text(contact.name)
        if not norm:
            continue
        normalized_index.setdefault(norm, []).append(contact)

    matched = []
    activated = []
    already_active = []
    unmatched = []
    ambiguous = []

    for entry in entries:
        raw_name = entry['name']
        norm_query = normalize_arabic_text(raw_name)
        if not norm_query:
            unmatched.append({'input_name': raw_name, 'reason': 'empty_after_normalization'})
            continue

        candidates = normalized_index.get(norm_query, [])

        if not candidates:
            unmatched.append({
                'input_name': raw_name,
                'normalized_name': norm_query,
                'serial_num': entry.get('serial_num'),
                'reason': 'no_matching_contact',
            })
            continue

        chosen = None
        if len(candidates) == 1:
            chosen = candidates[0]
            # If external source carries serial_num or source_uuid, verify no mismatch
            expected_serial = entry.get('serial_num')
            expected_uuid = entry.get('source_uuid')
            actual_uuid = (chosen.custom_values or {}).get('source_uuid')
            if expected_serial is not None and chosen.serial_num != expected_serial:
                unmatched.append({
                    'input_name': raw_name,
                    'reason': f'serial_mismatch (expected {expected_serial}, found {chosen.serial_num})',
                })
                continue
            if expected_uuid and actual_uuid and actual_uuid != expected_uuid:
                unmatched.append({
                    'input_name': raw_name,
                    'reason': 'source_uuid_mismatch',
                })
                continue
        else:
            # Disambiguate ONLY if exact serial_num + source_uuid narrow down to 1 candidate
            expected_serial = entry.get('serial_num')
            expected_uuid = entry.get('source_uuid')
            narrowed = candidates
            if expected_serial is not None:
                narrowed = [c for c in narrowed if c.serial_num == expected_serial]
            if expected_uuid and len(narrowed) > 1:
                narrowed = [c for c in narrowed if (c.custom_values or {}).get('source_uuid') == expected_uuid]

            if len(narrowed) == 1 and (expected_serial is not None or expected_uuid):
                chosen = narrowed[0]
            else:
                ambiguous.append({
                    'input_name': raw_name,
                    'normalized_name': norm_query,
                    'candidate_ids': [c.id for c in candidates],
                    'candidate_names': [c.name for c in candidates],
                })
                continue

        was_supplier = bool(chosen.is_supplier)
        if not chosen.is_supplier:
            chosen.is_supplier = True
            chosen.save(update_fields=['is_supplier'])
            activated.append(chosen.id)
        else:
            already_active.append(chosen.id)

        _, account_created = VendorAccount.objects.get_or_create(
            supplier=chosen,
            defaults={
                'credit_limit': chosen.credit_limit,
                'credit_period_days': chosen.credit_period_days,
            },
        )

        matched.append({
            'input_name': raw_name,
            'contact_id': chosen.id,
            'serial_num': chosen.serial_num,
            'contact_name': chosen.name,
            'was_already_supplier': was_supplier,
            'vendor_account_created': account_created,
            'source': entry.get('source'),
        })

    return {
        'total_input': len(entries),
        'matched': matched,
        'activated': activated,
        'already_active': already_active,
        'unmatched': unmatched,
        'ambiguous': ambiguous,
    }
