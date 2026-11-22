"""
Reusable File-Backed Global Excel Import Engine for WEA Pharma ERP.
- Zero session bloat & zero DB schema changes: stages parsed batches as JSON under MEDIA_ROOT/tmp_imports/ (24h TTL).
- Generates styled RTL 2-sheet .xlsx templates (Sheet 1: البيانات, Sheet 2: التعليمات).
- Validates file format, size, headers, field types, duplicates, FKs, and ScopeResolutionService DataScope.
- Provides filterable paginated preview before confirmation (never commits without confirmation; never silently skips invalid rows).
- Generates downloadable .xlsx error reports with formula-injection protection.
- Commits atomically via @transaction.atomic + writes SecurityAuditLog + emits catalog.excel_import_completed notification.
"""

import io
import json
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from django.conf import settings
from django.db import transaction
from django.http import HttpResponse
from django.utils import timezone

from accounts.services import AuditLogService
from master_data.excel_utils import sanitize_excel_cell

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB
MAX_IMPORT_ROWS = 5000
STAGING_TTL_SECONDS = 24 * 3600


@dataclass
class ColumnSpec:
    key: str
    header_ar: str
    required: bool = False
    aliases: List[str] = field(default_factory=list)
    sample: str = ''
    rules_ar: str = ''
    width: int = 22


def _normalize_header(text: Any) -> str:
    if text is None:
        return ''
    s = str(text).strip().replace('*', '').replace('ـ', '')
    s = re.sub(r'\s+', ' ', s).strip().lower()
    return s


def parse_decimal_val(raw: Any, field_label: str, allow_negative: bool = False, default=None) -> Tuple[Optional[Decimal], Optional[str]]:
    if raw is None or str(raw).strip() == '':
        return default, None
    try:
        cleaned = str(raw).strip().replace(',', '').replace('ج.م', '').replace('EGP', '').strip()
        val = Decimal(cleaned)
        if not val.is_finite():
            return None, f"القيمة في '{field_label}' غير صالحة."
        if not allow_negative and val < 0:
            return None, f"القيمة في '{field_label}' لا يمكن أن تكون سالبة."
        return val, None
    except (InvalidOperation, ValueError):
        return None, f"القيمة '{raw}' في '{field_label}' ليست رقماً صالحاً."


def parse_int_val(raw: Any, field_label: str, min_val: int = 0, default=None) -> Tuple[Optional[int], Optional[str]]:
    if raw is None or str(raw).strip() == '':
        return default, None
    try:
        d = Decimal(str(raw).strip().replace(',', ''))
        if d != int(d):
            return None, f"القيمة '{raw}' في '{field_label}' يجب أن تكون عدداً صحيحاً."
        iv = int(d)
        if iv < min_val:
            return None, f"القيمة في '{field_label}' يجب أن تكون >= {min_val}."
        return iv, None
    except (InvalidOperation, ValueError):
        return None, f"القيمة '{raw}' في '{field_label}' ليست عدداً صحيحاً."


def parse_date_val(raw: Any, field_label: str, default=None) -> Tuple[Optional[date], Optional[str]]:
    if raw is None or str(raw).strip() == '':
        return default, None
    if isinstance(raw, datetime):
        return raw.date(), None
    if isinstance(raw, date):
        return raw, None
    s = str(raw).strip()
    for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y', '%Y/%m/%d'):
        try:
            return datetime.strptime(s, fmt).date(), None
        except ValueError:
            continue
    return None, f"التاريخ '{raw}' في '{field_label}' غير صالح (استخدم الصيغة YYYY-MM-DD)."


def parse_bool_val(raw: Any, default: bool = True) -> bool:
    if raw is None or str(raw).strip() == '':
        return default
    if isinstance(raw, bool):
        return raw
    s = str(raw).strip().lower()
    if s in ('1', 'true', 'yes', 'y', 'نعم', 'مفعل', 'فعال', 'صح'):
        return True
    if s in ('0', 'false', 'no', 'n', 'لا', 'معطل', 'غير مفعل', 'خطأ'):
        return False
    return default


class ImportBatchStore:
    """File-backed temporary JSON staging under MEDIA_ROOT/tmp_imports/ (zero session bloat)."""

    @classmethod
    def _dir(cls) -> Path:
        base = Path(getattr(settings, 'MEDIA_ROOT', Path(settings.BASE_DIR) / 'media'))
        target = base / 'tmp_imports'
        target.mkdir(parents=True, exist_ok=True)
        return target

    @classmethod
    def cleanup_expired(cls) -> None:
        try:
            now = time.time()
            for p in cls._dir().glob('*.json'):
                if now - p.stat().st_mtime > STAGING_TTL_SECONDS:
                    p.unlink(missing_ok=True)
        except Exception:
            pass

    @classmethod
    def save_batch(cls, user_id: int, entity: str, payload: Dict[str, Any]) -> str:
        cls.cleanup_expired()
        batch_id = uuid.uuid4().hex
        data = {
            'batch_id': batch_id,
            'user_id': int(user_id),
            'entity': entity,
            'created_at': timezone.now().isoformat(),
            **payload,
        }
        path = cls._dir() / f"{batch_id}.json"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        return batch_id

    @classmethod
    def load_batch(cls, batch_id: str, user_id: int, entity: str) -> Optional[Dict[str, Any]]:
        if not batch_id or not re.fullmatch(r'[0-9a-f]{32}', batch_id):
            return None
        path = cls._dir() / f"{batch_id}.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            if int(data.get('user_id', -1)) != int(user_id) or data.get('entity') != entity:
                return None
            return data
        except Exception:
            return None

    @classmethod
    def delete_batch(cls, batch_id: str) -> None:
        if not batch_id or not re.fullmatch(r'[0-9a-f]{32}', batch_id):
            return
        path = cls._dir() / f"{batch_id}.json"
        path.unlink(missing_ok=True)


class BaseExcelImporter:
    entity_key: str = ''
    title_ar: str = ''
    description_ar: str = ''
    permission_codename: str = ''
    back_url_name: str = 'home'
    columns: List[ColumnSpec] = []

    def __init__(self, user):
        self.user = user
        self._ctx: Dict[str, Any] = {}

    def prepare_context(self) -> None:
        """Override to preload scoped lookup maps for fast O(1) validation."""
        pass

    def validate_row(self, row_num: int, raw: Dict[str, Any], seen: Dict[str, set]) -> Tuple[Optional[Dict[str, Any]], str, List[str]]:
        """
        Validate a single parsed row.
        Returns (cleaned_payload_json_safe | None, action ('create'|'update'|'error'), errors_list).
        """
        raise NotImplementedError

    def commit_rows(self, valid_rows: List[Dict[str, Any]]) -> Tuple[int, int]:
        """
        Atomically persist validated rows inside @transaction.atomic.
        Returns (created_count, updated_count).
        """
        raise NotImplementedError

    def generate_template_response(self) -> HttpResponse:
        wb = openpyxl.Workbook()

        # --- Sheet 1: Data ---
        ws = wb.active
        ws.title = 'البيانات'
        ws.sheet_view.rightToLeft = True

        header_fill = PatternFill(start_color='FF27BEBE', end_color='FF27BEBE', fill_type='solid')
        req_fill = PatternFill(start_color='FF0F766E', end_color='FF0F766E', fill_type='solid')
        header_font = Font(name='Cairo', size=11, bold=True, color='FFFFFFFF')
        sample_font = Font(name='Cairo', size=10, color='FF334155')
        sample_fill = PatternFill(start_color='FFF8FAFC', end_color='FFF8FAFC', fill_type='solid')
        thin = Side(border_style='thin', color='FFE2E8F0')
        border = Border(left=thin, right=thin, top=thin, bottom=thin)

        for idx, col in enumerate(self.columns, start=1):
            label = f"{col.header_ar} *" if col.required else col.header_ar
            c = ws.cell(row=1, column=idx, value=label)
            c.fill = req_fill if col.required else header_fill
            c.font = header_font
            c.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
            c.border = border

            sc = ws.cell(row=2, column=idx, value=sanitize_excel_cell(col.sample))
            sc.font = sample_font
            sc.fill = sample_fill
            sc.alignment = Alignment(horizontal='right', vertical='center')
            sc.border = border
            ws.column_dimensions[get_column_letter(idx)].width = col.width

        ws.row_dimensions[1].height = 28
        ws.row_dimensions[2].height = 22
        ws.freeze_panes = 'A2'

        # --- Sheet 2: Instructions ---
        ws2 = wb.create_sheet(title='التعليمات')
        ws2.sheet_view.rightToLeft = True
        inst_headers = ['العمود', 'المعرف البرمجي', 'إلزامي؟', 'مثال', 'القواعد والتعليمات']
        inst_widths = [26, 20, 12, 26, 52]
        for idx, (h, w) in enumerate(zip(inst_headers, inst_widths), start=1):
            c = ws2.cell(row=1, column=idx, value=h)
            c.fill = header_fill
            c.font = header_font
            c.alignment = Alignment(horizontal='center', vertical='center')
            c.border = border
            ws2.column_dimensions[get_column_letter(idx)].width = w
        ws2.row_dimensions[1].height = 26

        for r_idx, col in enumerate(self.columns, start=2):
            vals = [
                col.header_ar,
                col.key,
                'إلزامي' if col.required else 'اختياري',
                col.sample,
                col.rules_ar or ('حقل مطلوب' if col.required else 'اختياري'),
            ]
            for c_idx, val in enumerate(vals, start=1):
                cell = ws2.cell(row=r_idx, column=c_idx, value=sanitize_excel_cell(val))
                cell.font = sample_font
                cell.alignment = Alignment(horizontal='right' if c_idx != 3 else 'center', vertical='center', wrap_text=True)
                cell.border = border
            ws2.row_dimensions[r_idx].height = 22

        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        resp = HttpResponse(
            buf.getvalue(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        resp['Content-Disposition'] = f'attachment; filename="{self.entity_key}_import_template.xlsx"'
        return resp

    def _map_headers(self, header_cells: List[Any]) -> Tuple[Dict[int, str], List[str]]:
        lookup: Dict[str, str] = {}
        for col in self.columns:
            lookup[_normalize_header(col.header_ar)] = col.key
            lookup[_normalize_header(col.key)] = col.key
            for alias in col.aliases:
                lookup[_normalize_header(alias)] = col.key

        col_idx_to_key: Dict[int, str] = {}
        matched_keys = set()
        for idx, h in enumerate(header_cells):
            norm = _normalize_header(h)
            if norm in lookup:
                key = lookup[norm]
                col_idx_to_key[idx] = key
                matched_keys.add(key)

        missing_required = [
            col.header_ar for col in self.columns
            if col.required and col.key not in matched_keys
        ]
        return col_idx_to_key, missing_required

    def parse_and_validate_upload(self, uploaded_file) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        fname = getattr(uploaded_file, 'name', '') or ''
        if not fname.lower().endswith('.xlsx'):
            return None, "يرجى رفع ملف Excel بصيغة .xlsx فقط."
        if getattr(uploaded_file, 'size', 0) > MAX_UPLOAD_BYTES:
            return None, "حجم الملف يتجاوز الحد الأقصى المسموح (10 ميجابايت)."

        try:
            wb = openpyxl.load_workbook(uploaded_file, data_only=True, read_only=True)
        except Exception:
            return None, "تعذر قراءة ملف Excel. تأكد من سلامة الملف وأنه بصيغة .xlsx صالحة."

        ws = wb['البيانات'] if 'البيانات' in wb.sheetnames else wb.active
        rows_iter = ws.iter_rows(values_only=True)
        try:
            header_row = list(next(rows_iter))
        except StopIteration:
            wb.close()
            return None, "الملف فارغ ولا يحتوي على صف عناوين."

        col_map, missing_req = self._map_headers(header_row)
        if missing_req:
            wb.close()
            return None, f"الأعمدة الإلزامية التالية غير موجودة في الملف: {', '.join(missing_req)}"

        self.prepare_context()
        seen: Dict[str, set] = {}
        staged_rows: List[Dict[str, Any]] = []
        valid_count = 0
        invalid_count = 0
        create_count = 0
        update_count = 0

        for row_num, raw_tuple in enumerate(rows_iter, start=2):
            if len(staged_rows) >= MAX_IMPORT_ROWS:
                wb.close()
                return None, f"تجاوز الملف الحد الأقصى المسموح ({MAX_IMPORT_ROWS} صف في الدفعة الواحدة)."

            if not raw_tuple or all(v is None or str(v).strip() == '' for v in raw_tuple):
                continue

            raw_dict: Dict[str, Any] = {}
            display_dict: Dict[str, str] = {}
            for idx, key in col_map.items():
                val = raw_tuple[idx] if idx < len(raw_tuple) else None
                raw_dict[key] = val
                if isinstance(val, datetime):
                    display_dict[key] = val.strftime('%Y-%m-%d')
                elif isinstance(val, date):
                    display_dict[key] = val.isoformat()
                elif val is None:
                    display_dict[key] = ''
                else:
                    display_dict[key] = str(val).strip()

            cleaned, action, errors = self.validate_row(row_num, raw_dict, seen)
            is_valid = len(errors) == 0 and cleaned is not None
            if is_valid:
                valid_count += 1
                if action == 'update':
                    update_count += 1
                else:
                    create_count += 1
            else:
                invalid_count += 1
                action = 'error'

            staged_rows.append({
                'row_num': row_num,
                'is_valid': is_valid,
                'action': action,
                'display': display_dict,
                'cleaned': cleaned if is_valid else None,
                'errors': errors,
            })

        wb.close()
        if not staged_rows:
            return None, "لا توجد صفوف بيانات صالحة للمعالجة في الملف."

        payload = {
            'filename': fname,
            'total_rows': len(staged_rows),
            'valid_count': valid_count,
            'invalid_count': invalid_count,
            'create_count': create_count,
            'update_count': update_count,
            'rows': staged_rows,
        }
        return payload, None

    def generate_error_report_response(self, batch_data: Dict[str, Any]) -> HttpResponse:
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = 'تقرير الأخطاء'
        ws.sheet_view.rightToLeft = True

        header_fill = PatternFill(start_color='FFDC2626', end_color='FFDC2626', fill_type='solid')
        header_font = Font(name='Cairo', size=11, bold=True, color='FFFFFFFF')
        err_fill = PatternFill(start_color='FFFEF2F2', end_color='FFFEF2F2', fill_type='solid')
        err_font = Font(name='Cairo', size=10, bold=True, color='FFB91C1C')
        reg_font = Font(name='Cairo', size=10, color='FF0F172A')
        thin = Side(border_style='thin', color='FFE2E8F0')
        border = Border(left=thin, right=thin, top=thin, bottom=thin)

        headers = ['رقم الصف'] + [c.header_ar for c in self.columns] + ['سبب الخطأ']
        for idx, h in enumerate(headers, start=1):
            c = ws.cell(row=1, column=idx, value=h)
            c.fill = header_fill
            c.font = header_font
            c.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
            c.border = border
        ws.row_dimensions[1].height = 28

        r_idx = 2
        for row in batch_data.get('rows', []):
            if row.get('is_valid'):
                continue
            disp = row.get('display', {})
            vals = [row.get('row_num', '')] + [disp.get(c.key, '') for c in self.columns] + [' | '.join(row.get('errors', []))]
            for c_idx, v in enumerate(vals, start=1):
                cell = ws.cell(row=r_idx, column=c_idx, value=sanitize_excel_cell(v))
                cell.border = border
                if c_idx == len(vals):
                    cell.fill = err_fill
                    cell.font = err_font
                    cell.alignment = Alignment(horizontal='right', vertical='center', wrap_text=True)
                else:
                    cell.font = reg_font
                    cell.alignment = Alignment(horizontal='center' if c_idx == 1 else 'right', vertical='center')
            ws.row_dimensions[r_idx].height = 24
            r_idx += 1

        ws.column_dimensions['A'].width = 12
        for idx, c in enumerate(self.columns, start=2):
            ws.column_dimensions[get_column_letter(idx)].width = c.width
        ws.column_dimensions[get_column_letter(len(headers))].width = 48

        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        resp = HttpResponse(
            buf.getvalue(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        resp['Content-Disposition'] = f'attachment; filename="{self.entity_key}_import_errors.xlsx"'
        return resp

    @transaction.atomic
    def execute_commit(self, batch_data: Dict[str, Any], allow_partial: bool = False, request=None) -> Dict[str, int]:
        rows = batch_data.get('rows', [])
        invalid_rows = [r for r in rows if not r.get('is_valid')]
        valid_rows = [r for r in rows if r.get('is_valid') and r.get('cleaned') is not None]

        if invalid_rows and not allow_partial:
            raise ValueError("يوجد صفوف بها أخطاء. يرجى تصحيح الملف أو تحديد خيار استيراد الصفوف السليمة فقط صراحةً.")
        if not valid_rows:
            raise ValueError("لا توجد صفوف سليمة قابلة للاستيراد.")

        created_count, updated_count = self.commit_rows(valid_rows)
        skipped_count = len(invalid_rows)

        AuditLogService.log(
            actor=self.user,
            request=request,
            module=self.entity_key,
            action_type='EXCEL_IMPORT_COMPLETED',
            record_name=f"{self.title_ar} ({batch_data.get('filename', '')})",
            description=(
                f"استيراد Excel لـ {self.title_ar}: تم إنشاء {created_count} وتحديث {updated_count}"
                + (f" وتجاهل {skipped_count} صف خطأ بموافقة المستخدم" if skipped_count else "")
            ),
            new_values={
                'entity': self.entity_key,
                'filename': batch_data.get('filename', ''),
                'created': created_count,
                'updated': updated_count,
                'skipped': skipped_count,
            },
        )

        try:
            from notifications.services import NotificationService
            from django.urls import reverse
            back_url = ''
            try:
                back_url = reverse(self.back_url_name)
            except Exception:
                pass
            NotificationService.emit(
                event_code='catalog.excel_import_completed',
                actor=self.user,
                title=f"اكتمال استيراد Excel: {self.title_ar}",
                body=f"تم إنشاء {created_count} سجل وتحديث {updated_count} سجل من الملف '{batch_data.get('filename', '')}'.",
                action_url=back_url,
                dedupe_key=f"excel_import:{self.entity_key}:{batch_data.get('batch_id', '')}",
            )
        except Exception:
            pass

        return {
            'created': created_count,
            'updated': updated_count,
            'skipped': skipped_count,
        }
