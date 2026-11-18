"""
Reusable Excel Import & Export Utilities for WEA Pharma ERP.
Using openpyxl for production-grade, secure, styled XLSX generation, template creation, and parsing.
"""

import io
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from django.http import HttpResponse
from django.utils import timezone
from django.db import transaction
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

# Security: Characters that can trigger formula execution in spreadsheet software
FORMULA_PREFIXES = ('=', '+', '-', '@', '\t', '\r')


def sanitize_excel_cell(val):
    """
    Sanitize text to prevent Excel Formula Injection (CSV/Formula injection).
    Prefixes risky leading characters with a single apostrophe.
    Preserves numbers, booleans, and dates as native values.
    """
    if val is None:
        return ""
    if isinstance(val, bool):
        return "نعم" if val else "لا"
    if isinstance(val, (int, float, Decimal)):
        return val
    if isinstance(val, (date, datetime)):
        return val
    
    val_str = str(val)
    if val_str and val_str.startswith(FORMULA_PREFIXES):
        return "'" + val_str
    return val_str


def export_to_excel_response(
    data,
    columns,
    filename="export",
    sheet_title="البيانات",
    report_title=None,
    user=None,
):
    """
    Generate a styled, secure .xlsx Excel file response with CompanyProfile branding.
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = str(sheet_title)[:31]  # Excel limits sheet titles to 31 chars

    # Enable Right-to-Left for Arabic layout
    ws.sheet_view.rightToLeft = True

    # Load CompanyProfile dynamically (never hardcode company info)
    from master_data.models import CompanyProfile
    profile = CompanyProfile.get_settings()
    company_name = getattr(profile, 'company_name', '') or 'WEA Pharma'
    reg_info = " | ".join(
        part for part in [
            getattr(profile, 'commercial_registry', ''),
            getattr(profile, 'tax_id', ''),
            getattr(profile, 'phone', ''),
        ] if part
    )
    addr_info = getattr(profile, 'address', '') or ''
    title_text = report_title or sheet_title or 'تقرير البيانات'
    now_str = timezone.localtime(timezone.now()).strftime('%Y-%m-%d %H:%M')
    actor_name = ''
    if user and getattr(user, 'is_authenticated', False):
        actor_name = getattr(user, 'name', '') or getattr(user, 'username', '')

    num_cols = max(1, len(columns))
    last_col_letter = get_column_letter(num_cols)

    # Styling Palettes (WEA Brand Teal #27BEBE)
    brand_banner_fill = PatternFill(start_color="FFF0FDFD", end_color="FFF0FDFD", fill_type="solid")
    title_font = Font(name="Cairo", size=13, bold=True, color="FF0F766E")
    meta_font = Font(name="Cairo", size=9, color="FF475569")

    header_fill = PatternFill(start_color="FF27BEBE", end_color="FF27BEBE", fill_type="solid")
    header_font = Font(name="Cairo", size=11, bold=True, color="FFFFFFFF")
    header_alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    alt_row_fill = PatternFill(start_color="FFF8FAFC", end_color="FFF8FAFC", fill_type="solid")
    white_row_fill = PatternFill(start_color="FFFFFFFF", end_color="FFFFFFFF", fill_type="solid")

    thin_border_side = Side(border_style="thin", color="FFE2E8F0")
    cell_border = Border(left=thin_border_side, right=thin_border_side, top=thin_border_side, bottom=thin_border_side)

    regular_font = Font(name="Cairo", size=10, color="FF0F172A")

    # Company Branding & Report Title Header Rows (Rows 1..3)
    ws.cell(row=1, column=1, value=f"{company_name} — {title_text}")
    if num_cols > 1:
        ws.merge_cells(f"A1:{last_col_letter}1")
    c1 = ws.cell(row=1, column=1)
    c1.font = title_font
    c1.fill = brand_banner_fill
    c1.alignment = Alignment(horizontal="right", vertical="center")
    ws.row_dimensions[1].height = 26

    meta_parts = [p for p in [reg_info, addr_info] if p]
    ws.cell(row=2, column=1, value=" | ".join(meta_parts))
    if num_cols > 1:
        ws.merge_cells(f"A2:{last_col_letter}2")
    c2 = ws.cell(row=2, column=1)
    c2.font = meta_font
    c2.fill = brand_banner_fill
    c2.alignment = Alignment(horizontal="right", vertical="center")
    ws.row_dimensions[2].height = 18

    export_meta = f"تاريخ التصدير: {now_str}" + (f" | بواسطة: {actor_name}" if actor_name else "")
    ws.cell(row=3, column=1, value=export_meta)
    if num_cols > 1:
        ws.merge_cells(f"A3:{last_col_letter}3")
    c3 = ws.cell(row=3, column=1)
    c3.font = meta_font
    c3.alignment = Alignment(horizontal="right", vertical="center")
    ws.row_dimensions[3].height = 18

    # Write Table Header Row at Row 5
    header_row_idx = 5
    headers = [col.get('header', '') for col in columns]
    for col_idx, h_val in enumerate(headers, start=1):
        cell = ws.cell(row=header_row_idx, column=col_idx, value=h_val)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = header_alignment
        cell.border = cell_border
    ws.row_dimensions[header_row_idx].height = 28
    ws.freeze_panes = f"A{header_row_idx + 1}"

    # Write Data Rows
    row_idx = header_row_idx + 1
    for item in data:
        row_values = []
        for col in columns:
            key = col.get('key')
            val = None
            if callable(key):
                try:
                    val = key(item)
                except Exception:
                    val = ""
            elif isinstance(item, dict):
                val = item.get(key, "")
            elif isinstance(item, (list, tuple)) and isinstance(key, int):
                val = item[key] if key < len(item) else ""
            else:
                val = getattr(item, str(key), "")
            
            # Format types
            if isinstance(val, (datetime, timezone.datetime)):
                val = val.strftime('%Y-%m-%d %H:%M')
            elif isinstance(val, date):
                val = val.strftime('%Y-%m-%d')
            elif isinstance(val, Decimal):
                val = float(val)
            elif isinstance(val, bool):
                val = "نعم" if val else "لا"
            elif val is None:
                val = ""
            
            row_values.append(sanitize_excel_cell(val))

        for col_idx, val in enumerate(row_values, start=1):
            ws.cell(row=row_idx, column=col_idx, value=val)
        ws.row_dimensions[row_idx].height = 22
        
        # Style Data Cells
        is_even = (row_idx % 2 == 0)
        current_fill = white_row_fill if is_even else alt_row_fill

        for col_idx, col in enumerate(columns, start=1):
            cell = ws.cell(row=row_idx, column=col_idx)
            cell.font = regular_font
            cell.fill = current_fill
            cell.border = cell_border

            # Alignment based on data type or column preference
            align_pref = col.get('align')
            if align_pref:
                cell.alignment = Alignment(horizontal=align_pref, vertical="center")
            elif isinstance(cell.value, (int, float)):
                cell.alignment = Alignment(horizontal="right", vertical="center")
            else:
                cell.alignment = Alignment(horizontal="right", vertical="center")

            # Number Formatting
            num_format = col.get('format')
            if num_format:
                cell.number_format = num_format
            elif isinstance(cell.value, float):
                cell.number_format = '#,##0.00'

        row_idx += 1

    # Auto-adjust column widths
    for col_idx, col in enumerate(columns, start=1):
        col_letter = get_column_letter(col_idx)
        specified_width = col.get('width')
        if specified_width:
            ws.column_dimensions[col_letter].width = specified_width
        else:
            header_len = len(str(col.get('header', '')))
            max_len = header_len
            for r in range(header_row_idx, min(row_idx, header_row_idx + 100)):
                cell_val = str(ws.cell(row=r, column=col_idx).value or '')
                max_len = max(max_len, len(cell_val))
            ws.column_dimensions[col_letter].width = max(max_len + 4, 12)

    # Save to BytesIO buffer
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    # Construct Response
    if not filename.endswith('.xlsx'):
        clean_filename = f"{filename}.xlsx"
    else:
        clean_filename = filename

    response = HttpResponse(
        output.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="{clean_filename}"'
    return response


def generate_excel_template_response(columns, sample_rows=None, filename="template", sheet_title="نموذج الاستيراد"):
    """
    Generates a ready-to-fill Excel template with formatted headers and explanatory sample data.
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = str(sheet_title)[:31]
    ws.sheet_view.rightToLeft = True

    header_fill = PatternFill(start_color="FF27BEBE", end_color="FF27BEBE", fill_type="solid")
    header_font = Font(name="Cairo", size=11, bold=True, color="FFFFFFFF")
    header_alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    sample_fill = PatternFill(start_color="FFF0FDFD", end_color="FFF0FDFD", fill_type="solid")
    sample_font = Font(name="Cairo", size=10, italic=True, color="FF0F766E")

    thin_border_side = Side(border_style="thin", color="FFE2E8F0")
    cell_border = Border(left=thin_border_side, right=thin_border_side, top=thin_border_side, bottom=thin_border_side)

    headers = [col.get('header', '') for col in columns]
    ws.append(headers)
    ws.row_dimensions[1].height = 28

    for col_idx in range(1, len(columns) + 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = header_alignment
        cell.border = cell_border

    if sample_rows:
        for r_idx, s_row in enumerate(sample_rows, start=2):
            ws.append(s_row)
            ws.row_dimensions[r_idx].height = 22
            for col_idx in range(1, len(columns) + 1):
                cell = ws.cell(row=r_idx, column=col_idx)
                cell.fill = sample_fill
                cell.font = sample_font
                cell.border = cell_border
                cell.alignment = Alignment(horizontal="right", vertical="center")

    for col_idx, col in enumerate(columns, start=1):
        col_letter = get_column_letter(col_idx)
        width = col.get('width', 18)
        ws.column_dimensions[col_letter].width = width

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    clean_filename = f"{filename}.xlsx" if not filename.endswith('.xlsx') else filename
    response = HttpResponse(
        output.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="{clean_filename}"'
    return response


def export_error_report_response(errors_list, filename="import_errors"):
    """
    Generates a downloadable Excel file containing error details from an import operation.
    """
    columns = [
        {'header': 'رقم الصف', 'key': 'row_num', 'width': 12, 'align': 'center'},
        {'header': 'المعرف / الكود', 'key': 'identifier', 'width': 20, 'align': 'center'},
        {'header': 'الاسم / البيان', 'key': 'name', 'width': 30, 'align': 'right'},
        {'header': 'تفاصيل الخطأ', 'key': 'error', 'width': 50, 'align': 'right'},
    ]
    return export_to_excel_response(errors_list, columns, filename=filename, sheet_title="تقرير الأخطاء")


class ExcelImportParser:
    """
    Parser for handling uploaded Excel files safely, validating headers,
    performing row-by-row dry-run validation, and detecting duplicates.
    """
    def __init__(self, uploaded_file, column_mapping, max_size_mb=10):
        self.uploaded_file = uploaded_file
        self.column_mapping = column_mapping  # Dict of canonical_field: [accepted_header_names]
        self.max_size_mb = max_size_mb
        self.errors = []
        self.warnings = []
        self.rows_data = []
        self.matched_headers = {}

    def validate_file(self):
        """Validate file size and magic extension"""
        if not self.uploaded_file:
            self.errors.append("لم يتم رفع أي ملف.")
            return False
        
        # Check size
        if self.uploaded_file.size > self.max_size_mb * 1024 * 1024:
            self.errors.append(f"حجم الملف يتجاوز الحد المسموح به ({self.max_size_mb} ميجابايت).")
            return False

        # Check name
        if not self.uploaded_file.name.lower().endswith(('.xlsx', '.xlsm')):
            self.errors.append("صيغة الملف غير مدعومة. يرجى رفع ملف Excel بصيغة .xlsx فقط.")
            return False

        # Verify ZIP header (magic bytes: PK\x03\x04)
        try:
            self.uploaded_file.seek(0)
            magic = self.uploaded_file.read(4)
            self.uploaded_file.seek(0)
            if magic != b'PK\x03\x04':
                self.errors.append("الملف المرفوع ليس ملف Excel بصيغة OpenXML صالحة.")
                return False
        except Exception:
            pass

        return True

    def parse(self):
        """Parse rows and map to canonical dictionary keys"""
        if not self.validate_file():
            return False

        try:
            wb = openpyxl.load_workbook(self.uploaded_file, data_only=True)
            ws = wb.active
        except Exception as e:
            self.errors.append(f"فشل قراءة ملف Excel: {str(e)}")
            return False

        # Read first row (headers)
        header_cells = [cell.value for cell in ws[1] if cell.value is not None]
        if not header_cells:
            self.errors.append("الملف المرفوع فارغ أو لا يحتوي على صف عناوين.")
            return False

        # Match headers to column_mapping
        header_index_map = {}
        for col_idx, cell in enumerate(ws[1], start=1):
            val = str(cell.value or '').strip()
            if not val:
                continue
            for canonical_key, aliases in self.column_mapping.items():
                for alias in aliases:
                    if val.lower() == alias.lower():
                        header_index_map[canonical_key] = col_idx
                        self.matched_headers[canonical_key] = val
                        break

        # Read rows
        row_num = 2
        for row in ws.iter_rows(min_row=2, values_only=True):
            if not any(row):
                # Skip completely empty rows
                row_num += 1
                continue

            row_dict = {'__row_num__': row_num}
            for canonical_key, col_idx in header_index_map.items():
                val = row[col_idx - 1] if col_idx - 1 < len(row) else None
                if isinstance(val, str):
                    val = val.strip()
                row_dict[canonical_key] = val

            self.rows_data.append(row_dict)
            row_num += 1

        return len(self.errors) == 0


def parse_decimal_safe(val, default=Decimal('0.00')):
    """Safely parse decimal value from Excel cell (handles numbers, strings with currency/commas)."""
    if val is None or val == "":
        return default
    if isinstance(val, (int, float, Decimal)):
        try:
            return Decimal(str(val)).quantize(Decimal('0.01'))
        except (InvalidOperation, ValueError):
            return default
    try:
        s = str(val).strip()
        # Find numeric component like -123.45 or 1,234.56
        match = re.search(r'[-+]?\d+(?:,\d+)*(?:\.\d+)?', s)
        if match:
            clean_str = match.group(0).replace(',', '')
            return Decimal(clean_str).quantize(Decimal('0.01'))
        return default
    except (InvalidOperation, ValueError):
        return default


def parse_boolean_safe(val, default=True):
    """Safely parse boolean value from Arabic/English Excel cell values."""
    if val is None or val == "":
        return default
    if isinstance(val, bool):
        return val
    s = str(val).strip().lower()
    if s in ['نعم', 'true', '1', 'yes', 'صحيح', 'متاح', 'نشط']:
        return True
    if s in ['لا', 'false', '0', 'no', 'خطأ', 'غير متاح', 'معطل']:
        return False
    return default
