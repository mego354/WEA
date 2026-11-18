from datetime import date, timedelta

from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_date
from django.utils import timezone

from accounts.permissions import can_user_access_object, require_permission
from accounts.services import AuditLogService
from contacts.models import Contact
from master_data.pdf_service import generate_account_statement_pdf, generate_order_pdf
from purchases.models import PurchaseOrder, PurchaseReturnOrder
from sales.models import SalesOrder, SalesReturnOrder


def _parse_bool(val, default=True):
    if val is None:
        return default
    return str(val).strip().lower() in ("1", "true", "on", "yes")


def _extract_order_pdf_options(request):
    return {
        "include_company_info": _parse_bool(request.GET.get("include_company_info"), True),
        "include_party_info": _parse_bool(request.GET.get("include_party_info"), True),
        "include_items": _parse_bool(request.GET.get("include_items"), True),
        "include_totals": _parse_bool(request.GET.get("include_totals"), True),
        "include_payments": _parse_bool(request.GET.get("include_payments"), True),
        "include_returns": _parse_bool(request.GET.get("include_returns"), True),
        "include_notes": _parse_bool(request.GET.get("include_notes"), True),
        "include_signatures": _parse_bool(request.GET.get("include_signatures"), False),
    }


def _pdf_response(request, pdf_bytes, filename):
    disposition = "attachment" if _parse_bool(request.GET.get("download"), False) else "inline"
    resp = HttpResponse(pdf_bytes, content_type="application/pdf")
    resp["Content-Disposition"] = f'{disposition}; filename="{filename}"'
    resp["X-Content-Type-Options"] = "nosniff"
    return resp


@require_permission("sales:orders/pdf")
def sales_order_pdf(request, pk):
    order = get_object_or_404(
        SalesOrder.objects.select_related("customer", "customer__area", "source_warehouse"),
        pk=pk,
    )
    if not can_user_access_object(request.user, order):
        raise PermissionDenied("ليس لديك صلاحية للوصول إلى هذا الطلب.")
    opts = _extract_order_pdf_options(request)
    pdf_bytes, filename = generate_order_pdf("salesorder", order, options=opts, user=request.user)
    AuditLogService.log(
        actor=request.user,
        action_type="PDF_GENERATED",
        module="sales",
        record_id=str(order.pk),
        record_name=order.order_number,
        description=f"تصدير PDF لأمر البيع {order.order_number}",
        request=request,
    )
    return _pdf_response(request, pdf_bytes, filename)


@require_permission("sales:returns/pdf")
def sales_return_order_pdf(request, pk):
    order = get_object_or_404(
        SalesReturnOrder.objects.select_related("customer", "customer__area", "target_warehouse"),
        pk=pk,
    )
    if not can_user_access_object(request.user, order):
        raise PermissionDenied("ليس لديك صلاحية للوصول إلى هذا المرتجع.")
    opts = _extract_order_pdf_options(request)
    pdf_bytes, filename = generate_order_pdf("salesreturnorder", order, options=opts, user=request.user)
    AuditLogService.log(
        actor=request.user,
        action_type="PDF_GENERATED",
        module="sales",
        record_id=str(order.pk),
        record_name=order.order_number,
        description=f"تصدير PDF لمرتجع المبيعات {order.order_number}",
        request=request,
    )
    return _pdf_response(request, pdf_bytes, filename)


@require_permission("purchases:orders/pdf")
def purchase_order_pdf(request, pk):
    order = get_object_or_404(
        PurchaseOrder.objects.select_related("supplier", "supplier__area", "target_warehouse"),
        pk=pk,
    )
    if not can_user_access_object(request.user, order):
        raise PermissionDenied("ليس لديك صلاحية للوصول إلى أمر الشراء.")
    opts = _extract_order_pdf_options(request)
    pdf_bytes, filename = generate_order_pdf("purchaseorder", order, options=opts, user=request.user)
    AuditLogService.log(
        actor=request.user,
        action_type="PDF_GENERATED",
        module="purchases",
        record_id=str(order.pk),
        record_name=order.order_number,
        description=f"تصدير PDF لأمر الشراء {order.order_number}",
        request=request,
    )
    return _pdf_response(request, pdf_bytes, filename)


@require_permission("purchases:returns/pdf")
def purchase_return_order_pdf(request, pk):
    order = get_object_or_404(
        PurchaseReturnOrder.objects.select_related("supplier", "supplier__area", "warehouse"),
        pk=pk,
    )
    if not can_user_access_object(request.user, order):
        raise PermissionDenied("ليس لديك صلاحية للوصول إلى مرتجع المشتريات.")
    opts = _extract_order_pdf_options(request)
    pdf_bytes, filename = generate_order_pdf("purchasereturnorder", order, options=opts, user=request.user)
    AuditLogService.log(
        actor=request.user,
        action_type="PDF_GENERATED",
        module="purchases",
        record_id=str(order.pk),
        record_name=order.order_number,
        description=f"تصدير PDF لمرتجع المشتريات {order.order_number}",
        request=request,
    )
    return _pdf_response(request, pdf_bytes, filename)


def _resolve_statement_dates(request):
    today = timezone.localdate()
    default_start = today.replace(day=1)
    start_date = parse_date(request.GET.get("start_date") or "") or default_start
    end_date = parse_date(request.GET.get("end_date") or "") or today
    if start_date > end_date:
        start_date, end_date = end_date, start_date
    return start_date, end_date


@require_permission("sales:statements/pdf")
def customer_statement_pdf(request, pk):
    contact = get_object_or_404(Contact.objects.select_related("area"), pk=pk)
    if not can_user_access_object(request.user, contact):
        raise PermissionDenied("ليس لديك صلاحية للوصول إلى كشف حساب هذا العميل.")
    start_date, end_date = _resolve_statement_dates(request)
    category = (request.GET.get("category") or "all").strip()
    include_line_details = _parse_bool(request.GET.get("include_line_details"), False)

    pdf_bytes, filename = generate_account_statement_pdf(
        party_type="customer",
        contact=contact,
        start_date=start_date,
        end_date=end_date,
        category=category,
        include_line_details=include_line_details,
        user=request.user,
    )
    AuditLogService.log(
        actor=request.user,
        action_type="PDF_GENERATED",
        module="sales",
        record_id=str(contact.pk),
        record_name=contact.name,
        description=f"تصدير كشف حساب عميل PDF ({contact.name}) من {start_date} إلى {end_date}",
        request=request,
    )
    return _pdf_response(request, pdf_bytes, filename)


@require_permission("purchases:statements/pdf")
def vendor_statement_pdf(request, pk):
    contact = get_object_or_404(Contact.objects.select_related("area"), pk=pk)
    if not can_user_access_object(request.user, contact):
        raise PermissionDenied("ليس لديك صلاحية للوصول إلى كشف حساب هذا المورد.")
    start_date, end_date = _resolve_statement_dates(request)
    category = (request.GET.get("category") or "all").strip()
    include_line_details = _parse_bool(request.GET.get("include_line_details"), False)

    pdf_bytes, filename = generate_account_statement_pdf(
        party_type="vendor",
        contact=contact,
        start_date=start_date,
        end_date=end_date,
        category=category,
        include_line_details=include_line_details,
        user=request.user,
    )
    AuditLogService.log(
        actor=request.user,
        action_type="PDF_GENERATED",
        module="purchases",
        record_id=str(contact.pk),
        record_name=contact.name,
        description=f"تصدير كشف حساب مورد PDF ({contact.name}) من {start_date} إلى {end_date}",
        request=request,
    )
    return _pdf_response(request, pdf_bytes, filename)
