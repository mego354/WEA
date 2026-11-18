import io
import os
import re
from decimal import Decimal

import arabic_reshaper
from bidi.algorithm import get_display
from django.core.files.storage import default_storage
from django.db.models import Sum
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


TEAL_BRAND = colors.HexColor("#27bebe")
TEAL_DARK = colors.HexColor("#178c8c")
SLATE_900 = colors.HexColor("#0f172a")
SLATE_700 = colors.HexColor("#334155")
SLATE_500 = colors.HexColor("#64748b")
SLATE_200 = colors.HexColor("#e2e8f0")
SLATE_50 = colors.HexColor("#f8fafc")
EMERALD_700 = colors.HexColor("#047857")
ROSE_700 = colors.HexColor("#be123c")

_FONTS_REGISTERED = False
FONT_REGULAR = "Helvetica"
FONT_BOLD = "Helvetica-Bold"


def _ensure_arabic_fonts():
    global _FONTS_REGISTERED, FONT_REGULAR, FONT_BOLD
    if _FONTS_REGISTERED:
        return FONT_REGULAR, FONT_BOLD

    candidates = [
        (r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\arialbd.ttf"),
        (r"C:\Windows\Fonts\tahoma.ttf", r"C:\Windows\Fonts\tahomabd.ttf"),
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        ("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
        ("/usr/share/fonts/truetype/freefont/FreeSans.ttf", "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf"),
    ]
    for reg_path, bold_path in candidates:
        if os.path.exists(reg_path):
            try:
                pdfmetrics.registerFont(TTFont("ERPArabic", reg_path))
                FONT_REGULAR = "ERPArabic"
                if os.path.exists(bold_path):
                    pdfmetrics.registerFont(TTFont("ERPArabic-Bold", bold_path))
                    FONT_BOLD = "ERPArabic-Bold"
                else:
                    FONT_BOLD = "ERPArabic"
                break
            except Exception:
                continue

    _FONTS_REGISTERED = True
    return FONT_REGULAR, FONT_BOLD


def ar(text):
    """Reshape and apply BiDi algorithm for Arabic RTL rendering in ReportLab."""
    if text is None:
        return ""
    s = str(text)
    if not s.strip():
        return s
    # Only reshape if text contains Arabic characters
    if not any("\u0600" <= ch <= "\u06FF" or "\u0750" <= ch <= "\u077F" or "\uFB50" <= ch <= "\uFDFF" or "\uFE70" <= ch <= "\uFEFF" for ch in s):
        return s
    reshaped = arabic_reshaper.reshape(s)
    return get_display(reshaped)


def fmt_money(val):
    try:
        d = Decimal(str(val or "0.00"))
    except Exception:
        d = Decimal("0.00")
    return f"{d:,.2f}"


def fmt_qty(val):
    try:
        d = Decimal(str(val or "0"))
        if d == d.to_integral_value():
            return f"{int(d):,}"
        return f"{d:,.2f}"
    except Exception:
        return str(val or "0")


class NumberedCanvas(canvas.Canvas):
    """Canvas adding consistent RTL footer with page numbers (صفحة X من Y) and print timestamp."""

    def __init__(self, *args, footer_user="", **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []
        self._footer_user = footer_user

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self._draw_footer(num_pages)
            super().showPage()
        super().save()

    def _draw_footer(self, page_count):
        reg_font, _ = _ensure_arabic_fonts()
        self.saveState()
        self.setStrokeColor(SLATE_200)
        self.setLineWidth(0.5)
        self.line(14 * mm, 13 * mm, A4[0] - 14 * mm, 13 * mm)

        self.setFont(reg_font, 8)
        self.setFillColor(SLATE_500)
        page_label = ar(f"صفحة {self._pageNumber} من {page_count}")
        self.drawRightString(A4[0] - 14 * mm, 8.5 * mm, page_label)

        now_str = timezone.localtime(timezone.now()).strftime("%Y-%m-%d %H:%M")
        meta = f"{now_str}"
        if self._footer_user:
            meta = f"{ar('بواسطة: ' + self._footer_user)}  |  {now_str}"
        self.drawString(14 * mm, 8.5 * mm, meta)
        self.restoreState()


def _get_styles():
    reg, bold = _ensure_arabic_fonts()
    return {
        "title": ParagraphStyle("ERPTitle", fontName=bold, fontSize=14, leading=19, alignment=TA_RIGHT, textColor=SLATE_900),
        "subtitle": ParagraphStyle("ERPSub", fontName=reg, fontSize=9, leading=13, alignment=TA_RIGHT, textColor=SLATE_500),
        "h2": ParagraphStyle("ERPH2", fontName=bold, fontSize=10.5, leading=15, alignment=TA_RIGHT, textColor=SLATE_900),
        "body": ParagraphStyle("ERPBody", fontName=reg, fontSize=8.5, leading=13, alignment=TA_RIGHT, textColor=SLATE_700),
        "body_bold": ParagraphStyle("ERPBodyBold", fontName=bold, fontSize=8.5, leading=13, alignment=TA_RIGHT, textColor=SLATE_900),
        "th": ParagraphStyle("ERPTH", fontName=bold, fontSize=8.5, leading=12, alignment=TA_CENTER, textColor=colors.white),
        "td_r": ParagraphStyle("ERPTDR", fontName=reg, fontSize=8, leading=11, alignment=TA_RIGHT, textColor=SLATE_700),
        "td_c": ParagraphStyle("ERPTDC", fontName=reg, fontSize=8, leading=11, alignment=TA_CENTER, textColor=SLATE_700),
        "td_l": ParagraphStyle("ERPTDL", fontName=reg, fontSize=8, leading=11, alignment=TA_LEFT, textColor=SLATE_700),
        "td_bold_c": ParagraphStyle("ERPTDBC", fontName=bold, fontSize=8, leading=11, alignment=TA_CENTER, textColor=SLATE_900),
        "small_muted": ParagraphStyle("ERPMuted", fontName=reg, fontSize=7.5, leading=11, alignment=TA_RIGHT, textColor=SLATE_500),
    }


def _load_logo_flowable(company):
    if not company or not company.logo:
        return None
    try:
        with default_storage.open(company.logo.name, "rb") as f:
            img_bytes = io.BytesIO(f.read())
        img = Image(img_bytes, width=22 * mm, height=22 * mm, kind="proportional")
        return img
    except Exception:
        return None


def _build_header(story, styles, doc_title, doc_number, doc_date_str, include_company_info=True, extra_meta=None):
    from master_data.models import CompanyProfile

    company = CompanyProfile.get_settings()
    logo_img = _load_logo_flowable(company) if include_company_info else None

    left_lines = [
        Paragraph(ar(doc_title), styles["title"]),
        Paragraph(f"<b>{ar('الرقم:')}</b> {doc_number}", styles["body"]),
        Paragraph(f"<b>{ar('التاريخ:')}</b> {doc_date_str}", styles["body"]),
    ]
    for k, v in (extra_meta or []):
        left_lines.append(Paragraph(f"<b>{ar(k)}:</b> {ar(v)}", styles["body"]))

    if include_company_info and company:
        comp_lines = [
            Paragraph(ar(company.company_name), styles["h2"]),
        ]
        if company.address:
            comp_lines.append(Paragraph(ar(company.address), styles["small_muted"]))
        contact_parts = [p for p in [company.phone, company.email] if p]
        if contact_parts:
            comp_lines.append(Paragraph(ar(" | ".join(contact_parts)), styles["small_muted"]))
        reg_parts = [p for p in [company.commercial_registry, company.tax_id] if p]
        if reg_parts:
            comp_lines.append(Paragraph(ar(" | ".join(reg_parts)), styles["small_muted"]))

        if logo_img:
            right_cell = Table([[comp_lines, logo_img]], colWidths=[68 * mm, 24 * mm])
            right_cell.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]))
        else:
            right_cell = comp_lines
    else:
        right_cell = [Paragraph("", styles["body"])]

    header_table = Table([[left_lines, right_cell]], colWidths=[88 * mm, 94 * mm])
    header_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (-1, -1), SLATE_50),
        ("BOX", (0, 0), (-1, -1), 0.75, SLATE_200),
        ("LINEABOVE", (0, 0), (-1, 0), 3, TEAL_BRAND),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 5 * mm))


def _rtl_table(headers, rows, col_widths, styles, repeat_rows=1):
    """Build an RTL-ordered table by reversing columns so column 0 appears on the right."""
    rtl_headers = [Paragraph(ar(h), styles["th"]) for h in reversed(headers)]
    data = [rtl_headers]
    for row in rows:
        data.append(list(reversed(row)))

    tbl = Table(data, colWidths=list(reversed(col_widths)), repeatRows=repeat_rows)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), SLATE_900),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, SLATE_50]),
        ("GRID", (0, 0), (-1, -1), 0.4, SLATE_200),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]))
    return tbl


def _build_section_title(story, styles, title):
    story.append(Paragraph(ar(title), styles["h2"]))
    story.append(Spacer(1, 2 * mm))


def generate_order_pdf(doc_type, order, options=None, user=None):
    """
    Generate an A4 RTL PDF for SalesOrder, PurchaseOrder, SalesReturnOrder, or PurchaseReturnOrder.
    Returns (bytes, filename).
    """
    opts = {
        "include_company_info": True,
        "include_party_info": True,
        "include_items": True,
        "include_totals": True,
        "include_payments": True,
        "include_returns": True,
        "include_notes": True,
        "include_signatures": False,
    }
    if options:
        opts.update(options)

    styles = _get_styles()
    buf = io.BytesIO()
    footer_user = (user.get_full_name() or user.username) if user else ""

    if doc_type == "salesorder":
        doc_title = "فاتورة مبيعات / أمر بيع"
        doc_num = order.order_number
        party = order.customer
        party_label = "بيانات العميل"
        wh_name = order.source_warehouse.name if order.source_warehouse else "—"
        status_label = order.get_status_display()
        date_str = order.order_date.strftime("%Y-%m-%d") if order.order_date else "—"
        items = list(order.items.select_related("product").all())
        payments = list(order.collections.select_related("vault").all()) if opts["include_payments"] else []
        returns = list(order.return_orders.all()) if opts["include_returns"] else []
        paid_total = order.total_paid
        balance_due = order.outstanding_balance
        items_disc = getattr(order, "items_discount_total", Decimal("0.00"))
        custom_disc = getattr(order, "custom_discount_amount", Decimal("0.00"))
        shipping = getattr(order, "shipping_fees", Decimal("0.00"))
    elif doc_type == "purchaseorder":
        doc_title = "فاتورة مشتريات / أمر شراء"
        doc_num = order.order_number
        party = order.supplier
        party_label = "بيانات المورد"
        wh_name = order.target_warehouse.name if order.target_warehouse else "—"
        status_label = order.get_status_display()
        date_str = order.order_date.strftime("%Y-%m-%d") if order.order_date else "—"
        items = list(order.items.select_related("product").all())
        payments = list(order.vendor_payments.select_related("vault").all()) if opts["include_payments"] else []
        returns = list(order.return_orders.all()) if opts["include_returns"] else []
        paid_total = order.total_paid
        balance_due = order.outstanding_balance
        items_disc = getattr(order, "items_discount_total", Decimal("0.00"))
        custom_disc = getattr(order, "custom_discount_amount", Decimal("0.00"))
        shipping = getattr(order, "shipping_fees", Decimal("0.00"))
    elif doc_type == "salesreturnorder":
        doc_title = "إشعار دائن / مرتجع مبيعات"
        doc_num = order.order_number
        party = order.customer
        party_label = "بيانات العميل"
        wh_name = order.target_warehouse.name if order.target_warehouse else "—"
        status_label = order.get_status_display()
        date_str = order.order_date.strftime("%Y-%m-%d") if order.order_date else "—"
        items = list(order.items.select_related("product").all())
        payments = []
        returns = []
        paid_total = None
        balance_due = None
        items_disc = getattr(order, "discount_total", Decimal("0.00"))
        custom_disc = Decimal("0.00")
        shipping = Decimal("0.00")
    elif doc_type == "purchasereturnorder":
        doc_title = "إشعار مدين / مرتجع مشتريات"
        doc_num = order.order_number
        party = order.supplier
        party_label = "بيانات المورد"
        wh_name = order.warehouse.name if order.warehouse else "—"
        status_label = order.get_status_display()
        date_str = order.order_date.strftime("%Y-%m-%d") if order.order_date else "—"
        items = list(order.items.select_related("product").all())
        payments = []
        returns = []
        paid_total = None
        balance_due = None
        items_disc = Decimal("0.00")
        custom_disc = Decimal("0.00")
        shipping = Decimal("0.00")
    else:
        raise ValueError(f"Unsupported PDF document type: {doc_type}")

    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        rightMargin=14 * mm,
        leftMargin=14 * mm,
        topMargin=12 * mm,
        bottomMargin=18 * mm,
        title=f"{doc_title} - {doc_num}",
    )

    story = []
    extra_meta = [("الحالة", status_label), ("المخزن", wh_name)]
    _build_header(
        story,
        styles,
        doc_title=doc_title,
        doc_number=doc_num,
        doc_date_str=date_str,
        include_company_info=opts["include_company_info"],
        extra_meta=extra_meta,
    )

    # Party info card
    if opts["include_party_info"] and party:
        party_phone = getattr(party, "mobile", None) or getattr(party, "phone", None) or "—"
        party_area = party.area.name if getattr(party, "area", None) else "—"
        party_addr = getattr(party, "address", None) or "—"
        party_rows = [
            [
                Paragraph(f"<b>{ar('المنطقة:')}</b> {ar(party_area)}", styles["body"]),
                Paragraph(f"<b>{ar('الاسم:')}</b> {ar(party.name)}", styles["body_bold"]),
            ],
            [
                Paragraph(f"<b>{ar('الهاتف:')}</b> {party_phone}", styles["body"]),
                Paragraph(f"<b>{ar('العنوان:')}</b> {ar(party_addr)}", styles["body"]),
            ],
        ]
        ptbl = Table(party_rows, colWidths=[85 * mm, 97 * mm])
        ptbl.setStyle(TableStyle([
            ("BOX", (0, 0), (-1, -1), 0.5, SLATE_200),
            ("BACKGROUND", (0, 0), (-1, -1), colors.white),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 7),
            ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ]))
        _build_section_title(story, styles, party_label)
        story.append(ptbl)
        story.append(Spacer(1, 5 * mm))

    # Items Table
    if opts["include_items"]:
        _build_section_title(story, styles, "بنود الأصناف")
        headers = ["#", "الصنف", "الكمية", "سعر الوحدة", "الخصم", "الضريبة", "الإجمالي"]
        widths = [10 * mm, 64 * mm, 18 * mm, 24 * mm, 20 * mm, 20 * mm, 26 * mm]
        t_rows = []
        for idx, item in enumerate(items, 1):
            line_disc = getattr(item, "discount_amount", Decimal("0.00")) or Decimal("0.00")
            line_tax = getattr(item, "tax_amount", Decimal("0.00")) or Decimal("0.00")
            line_total = getattr(item, "total_price", None)
            if line_total is None:
                line_total = getattr(item, "total", None)
            if line_total is None:
                line_total = max(Decimal("0.00"), (getattr(item, "subtotal", Decimal("0.00")) or Decimal("0.00")) - line_disc) + line_tax
            prod_label = f"[{item.product.sku_code}] {item.product.name}" if getattr(item.product, "sku_code", None) else item.product.name
            t_rows.append([
                Paragraph(str(idx), styles["td_c"]),
                Paragraph(ar(prod_label), styles["td_r"]),
                Paragraph(fmt_qty(item.quantity), styles["td_c"]),
                Paragraph(fmt_money(item.unit_price), styles["td_c"]),
                Paragraph(fmt_money(line_disc), styles["td_c"]),
                Paragraph(fmt_money(line_tax), styles["td_c"]),
                Paragraph(fmt_money(line_total), styles["td_bold_c"]),
            ])
        if not t_rows:
            t_rows.append([Paragraph(ar("لا توجد بنود"), styles["td_c"])] + [Paragraph("", styles["td_c"])] * 6)
        story.append(_rtl_table(headers, t_rows, widths, styles))
        story.append(Spacer(1, 5 * mm))

    # Totals summary
    if opts["include_totals"]:
        total_lines = [
            ("الإجمالي قبل الخصم", f"{fmt_money(order.subtotal)} {ar('ج.م')}"),
        ]
        if items_disc:
            total_lines.append(("خصم الأصناف", f"{fmt_money(items_disc)} {ar('ج.م')}"))
        if custom_disc:
            total_lines.append(("خصم إضافي", f"{fmt_money(custom_disc)} {ar('ج.م')}"))
        if order.tax_amount:
            total_lines.append(("إجمالي الضريبة", f"{fmt_money(order.tax_amount)} {ar('ج.م')}"))
        if shipping:
            total_lines.append(("مصاريف الشحن", f"{fmt_money(shipping)} {ar('ج.م')}"))
        total_lines.append(("الإجمالي النهائي", f"{fmt_money(order.grand_total)} {ar('ج.م')}"))
        if paid_total is not None:
            total_lines.append(("إجمالي المسدد / المحصل", f"{fmt_money(paid_total)} {ar('ج.م')}"))
            total_lines.append(("المتبقي المستحق", f"{fmt_money(balance_due)} {ar('ج.م')}"))

        sum_rows = []
        for label, val in total_lines:
            is_grand = label == "الإجمالي النهائي"
            style_k = styles["body_bold"] if is_grand else styles["body"]
            style_v = styles["td_bold_c"] if is_grand else styles["td_c"]
            sum_rows.append([Paragraph(val, style_v), Paragraph(ar(label), style_k)])

        sum_tbl = Table(sum_rows, colWidths=[45 * mm, 50 * mm], hAlign="LEFT")
        sum_tbl.setStyle(TableStyle([
            ("BOX", (0, 0), (-1, -1), 0.6, SLATE_200),
            ("GRID", (0, 0), (-1, -1), 0.3, SLATE_200),
            ("BACKGROUND", (0, 0), (-1, -1), SLATE_50),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(sum_tbl)
        story.append(Spacer(1, 5 * mm))

    # Linked Payments
    if opts["include_payments"] and payments:
        _build_section_title(story, styles, "الدفعات / التحصيلات المرتبطة")
        p_headers = ["#", "التاريخ", "الخزنة", "الطريقة", "المبلغ"]
        p_widths = [18 * mm, 32 * mm, 52 * mm, 40 * mm, 40 * mm]
        p_rows = []
        for p in payments:
            p_date = getattr(p, "collection_date", None) or getattr(p, "payment_date", None) or p.created_at
            p_date_str = p_date.strftime("%Y-%m-%d") if p_date else "—"
            p_method = p.get_payment_method_display() if hasattr(p, "get_payment_method_display") else "—"
            p_rows.append([
                Paragraph(f"#{getattr(p, 'serial_num', p.pk)}", styles["td_c"]),
                Paragraph(p_date_str, styles["td_c"]),
                Paragraph(ar(p.vault.name if p.vault else "—"), styles["td_r"]),
                Paragraph(ar(p_method), styles["td_c"]),
                Paragraph(f"{fmt_money(p.amount)} {ar('ج.م')}", styles["td_bold_c"]),
            ])
        story.append(_rtl_table(p_headers, p_rows, p_widths, styles))
        story.append(Spacer(1, 5 * mm))

    # Linked Returns
    if opts["include_returns"] and returns:
        _build_section_title(story, styles, "المرتجعات المرتبطة")
        r_headers = ["رقم المرتجع", "التاريخ", "الحالة", "الإجمالي"]
        r_widths = [45 * mm, 35 * mm, 62 * mm, 40 * mm]
        r_rows = []
        for r in returns:
            r_rows.append([
                Paragraph(r.order_number, styles["td_c"]),
                Paragraph(r.order_date.strftime("%Y-%m-%d") if r.order_date else "—", styles["td_c"]),
                Paragraph(ar(r.get_status_display()), styles["td_c"]),
                Paragraph(f"{fmt_money(r.grand_total)} {ar('ج.م')}", styles["td_bold_c"]),
            ])
        story.append(_rtl_table(r_headers, r_rows, r_widths, styles))
        story.append(Spacer(1, 5 * mm))

    # Notes
    if opts["include_notes"] and getattr(order, "notes", None):
        _build_section_title(story, styles, "ملاحظات")
        story.append(Paragraph(ar(order.notes), styles["body"]))
        story.append(Spacer(1, 5 * mm))

    # Signatures
    if opts["include_signatures"]:
        sig_tbl = Table(
            [[
                Paragraph(ar("توقيع المستلم / العميل\n\n........................"), styles["td_c"]),
                Paragraph(ar("اعتماد الحسابات\n\n........................"), styles["td_c"]),
                Paragraph(ar("توقيع المسئول\n\n........................"), styles["td_c"]),
            ]],
            colWidths=[60 * mm, 60 * mm, 62 * mm],
        )
        sig_tbl.setStyle(TableStyle([
            ("BOX", (0, 0), (-1, -1), 0.4, SLATE_200),
            ("INNERGRID", (0, 0), (-1, -1), 0.4, SLATE_200),
            ("TOPPADDING", (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ]))
        story.append(sig_tbl)

    doc.build(story, canvasmaker=lambda *a, **kw: NumberedCanvas(*a, footer_user=footer_user, **kw))
    pdf_bytes = buf.getvalue()
    buf.close()
    safe_num = re.sub(r"[^A-Za-z0-9_-]", "_", str(doc_num))
    return pdf_bytes, f"{doc_type}_{safe_num}.pdf"


def generate_account_statement_pdf(
    party_type,
    contact,
    start_date,
    end_date,
    category="all",
    include_line_details=False,
    user=None,
):
    """
    Generate Customer or Supplier Account Statement PDF with:
    - True Opening Balance before start_date
    - Chronological running balance across all transactions in [start_date, end_date]
    - True Closing Balance (invariant to display category filter)
    - Optional category filter ('all', 'orders', 'returns', 'payments', 'adjustments')
    - Optional line-item breakdown (batched prefetch, zero N+1)
    """
    styles = _get_styles()
    buf = io.BytesIO()
    footer_user = (user.get_full_name() or user.username) if user else ""

    if party_type == "customer":
        from sales.models import CustomerTransaction, SalesOrder, SalesReturnOrder

        doc_title = "كشف حساب عميل"
        base_qs = CustomerTransaction.objects.filter(account__customer=contact)
        before_agg = base_qs.filter(transaction_date__lt=start_date).aggregate(
            d=Sum("debit"), c=Sum("credit")
        )
        opening_balance = (before_agg["d"] or Decimal("0.00")) - (before_agg["c"] or Decimal("0.00"))

        period_txs = list(
            base_qs.filter(transaction_date__gte=start_date, transaction_date__lte=end_date)
            .order_by("transaction_date", "id")
        )

        # Compute true running balance chronologically before applying display filter
        running = opening_balance
        total_debit = Decimal("0.00")
        total_credit = Decimal("0.00")
        enriched = []
        cat_map = {
            "orders": "sales",
            "returns": "sales_return",
            "payments": "collection",
        }
        target_reason = cat_map.get(category)

        for tx in period_txs:
            running = running + (tx.debit or Decimal("0.00")) - (tx.credit or Decimal("0.00"))
            total_debit += tx.debit or Decimal("0.00")
            total_credit += tx.credit or Decimal("0.00")
            if target_reason is None or tx.reason == target_reason:
                enriched.append((tx, running))
        closing_balance = running

        # Batch prefetch linked SalesOrder / SalesReturnOrder line items if requested
        items_by_ref = {}
        if include_line_details and enriched:
            order_nums = set()
            ret_nums = set()
            for tx, _ in enriched:
                for m in re.findall(r"SO-[A-Za-z0-9-]+", tx.description or ""):
                    order_nums.add(m)
                for m in re.findall(r"SRO-[A-Za-z0-9-]+", tx.description or ""):
                    ret_nums.add(m)
            if order_nums:
                for o in SalesOrder.objects.filter(order_number__in=order_nums).prefetch_related("items__product"):
                    items_by_ref[o.order_number] = list(o.items.all())
            if ret_nums:
                for r in SalesReturnOrder.objects.filter(order_number__in=ret_nums).prefetch_related("items__product"):
                    items_by_ref[r.order_number] = list(r.items.all())

    elif party_type == "vendor":
        from purchases.models import PurchaseOrder
        from treasury.models import VendorTransaction

        doc_title = "كشف حساب مورد"
        base_qs = VendorTransaction.objects.filter(account__supplier=contact)
        before_agg = base_qs.filter(transaction_date__lt=start_date).aggregate(
            d=Sum("debit"), c=Sum("credit")
        )
        # Vendor payable balance = credits (invoices) - debits (payments/returns)
        opening_balance = (before_agg["c"] or Decimal("0.00")) - (before_agg["d"] or Decimal("0.00"))

        period_txs = list(
            base_qs.filter(transaction_date__gte=start_date, transaction_date__lte=end_date)
            .select_related("purchase_order")
            .order_by("transaction_date", "id")
        )

        running = opening_balance
        total_debit = Decimal("0.00")
        total_credit = Decimal("0.00")
        enriched = []
        cat_map = {
            "orders": "purchase",
            "returns": "purchase_returns",
            "payments": "purchase_payments",
            "adjustments": "adjustment",
        }
        target_reason = cat_map.get(category)

        for tx in period_txs:
            running = running + (tx.credit or Decimal("0.00")) - (tx.debit or Decimal("0.00"))
            total_debit += tx.debit or Decimal("0.00")
            total_credit += tx.credit or Decimal("0.00")
            if target_reason is None or tx.reason == target_reason:
                enriched.append((tx, running))
        closing_balance = running

        items_by_ref = {}
        if include_line_details and enriched:
            po_ids = [tx.purchase_order_id for tx, _ in enriched if tx.purchase_order_id]
            if po_ids:
                for po in PurchaseOrder.objects.filter(id__in=po_ids).prefetch_related("items__product"):
                    items_by_ref[po.id] = list(po.items.all())
    else:
        raise ValueError(f"Unsupported statement party type: {party_type}")

    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        rightMargin=14 * mm,
        leftMargin=14 * mm,
        topMargin=12 * mm,
        bottomMargin=18 * mm,
        title=f"{doc_title} - {contact.name}",
    )

    story = []
    period_str = f"{start_date.strftime('%Y-%m-%d')}  ->  {end_date.strftime('%Y-%m-%d')}"
    cat_labels = {
        "all": "جميع الحركات",
        "orders": "الفواتير فقط",
        "returns": "المرتجعات فقط",
        "payments": "المدفوعات / التحصيلات فقط",
        "adjustments": "التسويات فقط",
    }
    _build_header(
        story,
        styles,
        doc_title=doc_title,
        doc_number=f"STMT-{contact.pk}",
        doc_date_str=period_str,
        include_company_info=True,
        extra_meta=[
            ("الطرف", contact.name),
            ("نطاق العرض", cat_labels.get(category, "جميع الحركات")),
        ],
    )

    # Financial Summary Box
    sum_rows = [
        [
            Paragraph(f"{fmt_money(closing_balance)} {ar('ج.م')}", styles["td_bold_c"]),
            Paragraph(f"{fmt_money(total_credit)} {ar('ج.م')}", styles["td_c"]),
            Paragraph(f"{fmt_money(total_debit)} {ar('ج.م')}", styles["td_c"]),
            Paragraph(f"{fmt_money(opening_balance)} {ar('ج.م')}", styles["td_bold_c"]),
        ],
        [
            Paragraph(ar("الرصيد الختامي"), styles["th"]),
            Paragraph(ar("إجمالي الدائن"), styles["th"]),
            Paragraph(ar("إجمالي المدين"), styles["th"]),
            Paragraph(ar("الرصيد الافتتاحي"), styles["th"]),
        ],
    ]
    # Header row on top, values below
    sum_tbl = Table([sum_rows[1], sum_rows[0]], colWidths=[45 * mm, 45 * mm, 45 * mm, 47 * mm])
    sum_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), SLATE_900),
        ("BACKGROUND", (0, 1), (-1, 1), SLATE_50),
        ("GRID", (0, 0), (-1, -1), 0.5, SLATE_200),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(sum_tbl)
    story.append(Spacer(1, 5 * mm))

    # Ledger Table
    headers = ["#", "التاريخ", "النوع / البيان", "التوصيف", "مدين", "دائن", "الرصيد"]
    widths = [15 * mm, 22 * mm, 26 * mm, 53 * mm, 22 * mm, 22 * mm, 22 * mm]
    t_rows = []
    for tx, run_bal in enriched:
        reason_label = tx.get_reason_display() if hasattr(tx, "get_reason_display") else tx.reason
        desc_text = tx.description or "—"
        if include_line_details:
            matched_items = []
            if party_type == "vendor" and getattr(tx, "purchase_order_id", None):
                matched_items = items_by_ref.get(tx.purchase_order_id, [])
            elif party_type == "customer":
                for ref_key, ref_items in items_by_ref.items():
                    if ref_key in (tx.description or ""):
                        matched_items = ref_items
                        break
            if matched_items:
                sub_lines = [
                    f"• {it.product.name} ({fmt_qty(it.quantity)} × {fmt_money(it.unit_price)})"
                    for it in matched_items[:12]
                ]
                if len(matched_items) > 12:
                    sub_lines.append(f"... +{len(matched_items) - 12}")
                desc_text = desc_text + "\n" + "\n".join(sub_lines)

        t_rows.append([
            Paragraph(f"#{tx.serial}", styles["td_c"]),
            Paragraph(tx.transaction_date.strftime("%Y-%m-%d"), styles["td_c"]),
            Paragraph(ar(reason_label), styles["td_c"]),
            Paragraph(ar(desc_text), styles["td_r"]),
            Paragraph(fmt_money(tx.debit), styles["td_c"]),
            Paragraph(fmt_money(tx.credit), styles["td_c"]),
            Paragraph(fmt_money(run_bal), styles["td_bold_c"]),
        ])

    if not t_rows:
        t_rows.append([Paragraph(ar("لا توجد حركات مطابقة في هذه الفترة"), styles["td_c"])] + [Paragraph("", styles["td_c"])] * 6)

    story.append(_rtl_table(headers, t_rows, widths, styles))

    doc.build(story, canvasmaker=lambda *a, **kw: NumberedCanvas(*a, footer_user=footer_user, **kw))
    pdf_bytes = buf.getvalue()
    buf.close()
    return pdf_bytes, f"statement_{party_type}_{contact.pk}_{start_date:%Y%m%d}_{end_date:%Y%m%d}.pdf"
