import csv
from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q
from django.http import JsonResponse, HttpResponse
from django.core.paginator import Paginator
from .models import Contact, ContactAddress, ContactComment, ContactAttachment, ContactTodo, ContactActivity
from master_data.models import Area
from treasury.models import VendorAccount
from sales.models import CustomerAccount
from accounts.models import User
from .constants import CUSTOMER_CATEGORIES, SPECIALTIES, ACCOUNT_TYPES, COUNTRY_CODES


@login_required
def contacts_list(request):
    relation = request.GET.get('relation', 'all').strip()
    status = request.GET.get('status', 'all').strip()
    search = request.GET.get('search', '').strip() or request.GET.get('q', '').strip()
    area_id = request.GET.get('area_id', '').strip()
    sub_area = request.GET.get('sub_area', '').strip()
    contact_type = request.GET.get('contact_type', 'all').strip()
    category = request.GET.get('category', 'all').strip()
    specialty = request.GET.get('specialty', 'all').strip()
    account_type = request.GET.get('account_type', 'all').strip()
    view_mode = request.GET.get('view', 'table').strip()
    show_inactive = request.GET.get('inactive', 'no').strip()

    qs = Contact.objects.select_related('area', 'created_by').prefetch_related('addresses').all()

    # Active filters counter
    active_filters_count = 0

    if show_inactive == 'no':
        qs = qs.exclude(status='inactive')
        active_filters_count += 1
    elif show_inactive == 'yes':
        active_filters_count += 1

    if relation == 'vendor':
        qs = qs.filter(is_supplier=True)
        active_filters_count += 1
    elif relation == 'customer':
        qs = qs.filter(is_customer=True)
        active_filters_count += 1
    elif relation == 'other':
        qs = qs.filter(is_other=True)
        active_filters_count += 1

    if status and status != 'all':
        qs = qs.filter(status=status)
        active_filters_count += 1

    if area_id:
        qs = qs.filter(Q(area_id=area_id) | Q(addresses__area_id=area_id)).distinct()
        active_filters_count += 1

    if sub_area:
        qs = qs.filter(addresses__sub_area__icontains=sub_area).distinct()
        active_filters_count += 1

    if contact_type and contact_type != 'all':
        qs = qs.filter(contact_type=contact_type)
        active_filters_count += 1

    if category and category != 'all':
        qs = qs.filter(customer_category=category)
        active_filters_count += 1

    if specialty and specialty != 'all':
        qs = qs.filter(specialty=specialty)
        active_filters_count += 1

    if account_type and account_type != 'all':
        qs = qs.filter(account_type=account_type)
        active_filters_count += 1

    if search:
        qs = qs.filter(
            Q(name__icontains=search) |
            Q(serial_num__icontains=search) |
            Q(mobile__icontains=search) |
            Q(phone__icontains=search) |
            Q(tax_card__icontains=search) |
            Q(tax_id__icontains=search) |
            Q(code__icontains=search) |
            Q(contact_person__icontains=search)
        ).distinct()

    # Pagination: 40 items per page (matching reference ERP)
    paginator = Paginator(qs, 40)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    governorates = Area.objects.filter(area_type='governorate').order_by('name')
    if not governorates.exists():
        governorates = Area.objects.all().order_by('name')

    context = {
        'contacts': page_obj,
        'page_obj': page_obj,
        'total_count': qs.count(),
        'active_filters_count': active_filters_count,
        'current_relation': relation,
        'current_status': status,
        'search_query': search,
        'current_area_id': area_id,
        'current_sub_area': sub_area,
        'current_contact_type': contact_type,
        'current_category': category,
        'current_specialty': specialty,
        'current_account_type': account_type,
        'current_show_inactive': show_inactive,
        'view_mode': view_mode,
        'governorates': governorates,
        'customer_categories': CUSTOMER_CATEGORIES,
        'specialties': SPECIALTIES,
        'account_types': ACCOUNT_TYPES,
        'users_list': User.objects.filter(is_active=True).order_by('name')[:30],
    }
    return render(request, 'contacts/contacts_list.html', context)


@login_required
def contact_detail(request, pk):
    contact = get_object_or_404(
        Contact.objects.select_related('area', 'created_by', 'parent_org')
        .prefetch_related('addresses__area', 'assigned_team', 'branches'),
        pk=pk
    )

    active_tab = request.GET.get('tab', 'overview').strip()

    addresses = contact.addresses.all()
    comments = contact.comments.select_related('author').order_by('-created_at')
    attachments = contact.attachments.select_related('uploaded_by').order_by('-created_at')
    todos = contact.todos.select_related('created_by').order_by('is_completed', '-created_at')
    activities = contact.activities.select_related('performed_by').order_by('-created_at')

    # Transactions & accounting relationships
    sales_orders = []
    collections = []
    purchase_orders = []
    customer_account = getattr(contact, 'customer_account', None)
    vendor_account = getattr(contact, 'vendor_account', None)

    if contact.is_customer:
        sales_orders = contact.sales_orders.select_related('created_by').order_by('-created_at')[:20]
        collections = contact.collections.select_related('created_by').order_by('-created_at')[:20]

    if contact.is_supplier:
        purchase_orders = contact.purchase_orders.select_related('created_by').order_by('-created_at')[:20]

    governorates = Area.objects.filter(area_type='governorate').order_by('name')
    if not governorates.exists():
        governorates = Area.objects.all().order_by('name')

    context = {
        'contact': contact,
        'active_tab': active_tab,
        'addresses': addresses,
        'comments': comments,
        'attachments': attachments,
        'todos': todos,
        'activities': activities,
        'sales_orders': sales_orders,
        'collections': collections,
        'purchase_orders': purchase_orders,
        'customer_account': customer_account,
        'vendor_account': vendor_account,
        'assigned_team': contact.assigned_team.all(),
        'branches': contact.branches.all(),
        'governorates': governorates,
    }
    return render(request, 'contacts/contact_detail.html', context)


@login_required
def contact_create(request):
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        contact_type = request.POST.get('contact_type', 'organization')
        
        # Business Relations (multi-select / multiple checkboxes)
        relations = request.POST.getlist('relations')
        is_customer = 'عميل' in relations or request.POST.get('is_customer') == 'on'
        is_supplier = 'مورد' in relations or request.POST.get('is_supplier') == 'on'
        is_other = 'أخرى' in relations or request.POST.get('is_other') == 'on'

        if not name:
            messages.error(request, "اسم جهة الاتصال مطلوب.")
            return render_create_form(request, errors={'name': 'هذا الحقل مطلوب'})

        # Conditional customer fields
        customer_category = request.POST.get('customer_category', '').strip() if is_customer else ''
        specialty = request.POST.get('specialty', '').strip() if is_customer else ''
        account_type = request.POST.get('account_type', '').strip() if is_customer else ''

        # Phone numbers
        mobile_code = request.POST.get('mobile_country_code', '+20').strip()
        mobile_num = request.POST.get('mobile_number', '').strip()
        mobile = f"{mobile_code} {mobile_num}".strip() if mobile_num else ''

        phone_code = request.POST.get('phone_country_code', '+20').strip()
        phone_num = request.POST.get('phone_number', '').strip()
        phone = f"{phone_code} {phone_num}".strip() if phone_num else ''

        # Other Info fields
        email = request.POST.get('email', '').strip()
        website = request.POST.get('website', '').strip()
        tax_id = request.POST.get('tax_id', '').strip()
        code = request.POST.get('code', '').strip()
        notes = request.POST.get('notes', '').strip()
        contact_person = request.POST.get('contact_person', '').strip()
        visit_timing = request.POST.get('visit_timing', '').strip()
        job_title = request.POST.get('job_title', '').strip()
        is_kol = request.POST.get('is_kol') in ['نعم', 'true', 'on']

        credit_limit = request.POST.get('credit_limit', 0)
        try:
            credit_limit = float(credit_limit) if credit_limit else 0.00
        except ValueError:
            credit_limit = 0.00

        # Area / Address info
        area_id = request.POST.get('area_id') or request.POST.get('area')
        area = Area.objects.filter(id=area_id).first() if area_id else None

        contact = Contact.objects.create(
            name=name,
            contact_type=contact_type,
            is_customer=is_customer,
            is_supplier=is_supplier,
            is_other=is_other,
            customer_category=customer_category,
            specialty=specialty,
            account_type=account_type,
            mobile=mobile,
            phone=phone,
            email=email,
            website=website,
            area=area,
            tax_id=tax_id,
            code=code,
            contact_person=contact_person,
            visit_timing=visit_timing,
            job_title=job_title,
            is_kol=is_kol,
            credit_limit=credit_limit,
            status='customer' if is_customer else 'active',
            notes=notes,
            created_by=request.user
        )

        # Handle addresses
        address_titles = request.POST.getlist('address_title[]')
        address_areas = request.POST.getlist('address_area[]')
        address_sub_areas = request.POST.getlist('address_sub_area[]')
        address_streets = request.POST.getlist('address_street[]')
        address_is_mains = request.POST.getlist('address_is_main[]')

        if address_areas:
            for idx, a_id in enumerate(address_areas):
                card_area = Area.objects.filter(id=a_id).first() if a_id else area
                sub_name = address_sub_areas[idx] if idx < len(address_sub_areas) else ''
                street = address_streets[idx] if idx < len(address_streets) else ''
                title = address_titles[idx] if idx < len(address_titles) else ''
                is_main = (idx == 0) or (idx < len(address_is_mains) and address_is_mains[idx] in ['on', 'true', '1'])

                if card_area or street or title:
                    ContactAddress.objects.create(
                        contact=contact,
                        title=title,
                        area=card_area,
                        sub_area=sub_name,
                        street_address=street,
                        is_main=is_main
                    )
        elif area:
            sub_name = request.POST.get('sub_area', '')
            street = request.POST.get('street_address', '')
            ContactAddress.objects.create(
                contact=contact,
                title=request.POST.get('address_title', ''),
                area=area,
                sub_area=sub_name,
                street_address=street,
                is_main=True
            )

        if is_supplier:
            VendorAccount.get_or_create_for_supplier(contact)

        messages.success(request, f"تم إنشاء جهة الاتصال '{contact.name}' بنجاح (#{contact.serial_num}).")
        return redirect('contact_detail', pk=contact.id)

    return render_create_form(request)


def render_create_form(request, errors=None):
    governorates = Area.objects.filter(area_type='governorate').order_by('name')
    if not governorates.exists():
        governorates = Area.objects.all().order_by('name')

    context = {
        'governorates': governorates,
        'customer_categories': CUSTOMER_CATEGORIES,
        'specialties': SPECIALTIES,
        'account_types': ACCOUNT_TYPES,
        'country_codes': COUNTRY_CODES,
        'errors': errors or {}
    }
    return render(request, 'contacts/contact_create.html', context)


@login_required
def contact_edit(request, pk):
    contact = get_object_or_404(Contact, pk=pk)
    
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        contact_type = request.POST.get('contact_type', 'organization')
        
        relations = request.POST.getlist('relations')
        is_customer = 'عميل' in relations or request.POST.get('is_customer') == 'on'
        is_supplier = 'مورد' in relations or request.POST.get('is_supplier') == 'on'
        is_other = 'أخرى' in relations or request.POST.get('is_other') == 'on'

        if not name:
            messages.error(request, "اسم جهة الاتصال مطلوب.")
            return render_edit_form(request, contact, errors={'name': 'هذا الحقل مطلوب'})

        contact.name = name
        contact.contact_type = contact_type
        contact.is_customer = is_customer
        contact.is_supplier = is_supplier
        contact.is_other = is_other

        contact.customer_category = request.POST.get('customer_category', '').strip() if is_customer else ''
        contact.specialty = request.POST.get('specialty', '').strip() if is_customer else ''
        contact.account_type = request.POST.get('account_type', '').strip() if is_customer else ''

        mobile_code = request.POST.get('mobile_country_code', '+20').strip()
        mobile_num = request.POST.get('mobile_number', '').strip()
        if mobile_num:
            contact.mobile = f"{mobile_code} {mobile_num}".strip()
        elif 'mobile_number' in request.POST:
            contact.mobile = ''

        phone_code = request.POST.get('phone_country_code', '+20').strip()
        phone_num = request.POST.get('phone_number', '').strip()
        if phone_num:
            contact.phone = f"{phone_code} {phone_num}".strip()
        elif 'phone_number' in request.POST:
            contact.phone = ''

        contact.email = request.POST.get('email', '').strip()
        contact.website = request.POST.get('website', '').strip()
        contact.tax_id = request.POST.get('tax_id', '').strip()
        contact.code = request.POST.get('code', '').strip()
        contact.notes = request.POST.get('notes', '').strip()
        contact.contact_person = request.POST.get('contact_person', '').strip()
        contact.visit_timing = request.POST.get('visit_timing', '').strip()
        contact.job_title = request.POST.get('job_title', '').strip()
        contact.is_kol = request.POST.get('is_kol') in ['نعم', 'true', 'on']

        credit_limit = request.POST.get('credit_limit')
        if credit_limit is not None and credit_limit != '':
            try:
                contact.credit_limit = float(credit_limit)
            except ValueError:
                pass

        area_id = request.POST.get('area_id') or request.POST.get('area')
        if area_id:
            contact.area = Area.objects.filter(id=area_id).first()

        contact.save()

        # Update addresses: delete removed and re-create / update
        address_titles = request.POST.getlist('address_title[]')
        address_areas = request.POST.getlist('address_area[]')
        address_sub_areas = request.POST.getlist('address_sub_area[]')
        address_streets = request.POST.getlist('address_street[]')
        address_is_mains = request.POST.getlist('address_is_main[]')

        if address_areas:
            contact.addresses.all().delete()
            for idx, a_id in enumerate(address_areas):
                card_area = Area.objects.filter(id=a_id).first() if a_id else contact.area
                sub_name = address_sub_areas[idx] if idx < len(address_sub_areas) else ''
                street = address_streets[idx] if idx < len(address_streets) else ''
                title = address_titles[idx] if idx < len(address_titles) else ''
                is_main = (idx == 0) or (idx < len(address_is_mains) and address_is_mains[idx] in ['on', 'true', '1'])

                if card_area or street or title:
                    ContactAddress.objects.create(
                        contact=contact,
                        title=title,
                        area=card_area,
                        sub_area=sub_name,
                        street_address=street,
                        is_main=is_main
                    )

        if is_supplier:
            VendorAccount.get_or_create_for_supplier(contact)

        messages.success(request, f"تم تحديث بيانات جهة الاتصال '{contact.name}' بنجاح.")
        return redirect('contact_detail', pk=contact.id)

    return render_edit_form(request, contact)


def render_edit_form(request, contact, errors=None):
    governorates = Area.objects.filter(area_type='governorate').order_by('name')
    if not governorates.exists():
        governorates = Area.objects.all().order_by('name')

    # Split mobile into country code & number
    mobile_parts = contact.mobile.split(' ', 1) if contact.mobile else ['', '']
    mobile_code = mobile_parts[0] if len(mobile_parts) > 1 and mobile_parts[0].startswith('+') else '+20'
    mobile_num = mobile_parts[1] if len(mobile_parts) > 1 and mobile_parts[0].startswith('+') else contact.mobile

    phone_parts = contact.phone.split(' ', 1) if contact.phone else ['', '']
    phone_code = phone_parts[0] if len(phone_parts) > 1 and phone_parts[0].startswith('+') else '+20'
    phone_num = phone_parts[1] if len(phone_parts) > 1 and phone_parts[0].startswith('+') else contact.phone

    context = {
        'contact': contact,
        'addresses': contact.addresses.all(),
        'governorates': governorates,
        'customer_categories': CUSTOMER_CATEGORIES,
        'specialties': SPECIALTIES,
        'account_types': ACCOUNT_TYPES,
        'country_codes': COUNTRY_CODES,
        'mobile_code': mobile_code,
        'mobile_num': mobile_num,
        'phone_code': phone_code,
        'phone_num': phone_num,
        'errors': errors or {}
    }
    return render(request, 'contacts/contact_edit.html', context)


@login_required
def contact_delete(request, pk):
    contact = get_object_or_404(Contact, pk=pk)
    if request.method == 'POST':
        name = contact.name
        serial = contact.serial_num
        contact.delete()
        messages.success(request, f"تم مسح جهة الاتصال '{name}' (#{serial}) بنجاح.")
        return redirect('contacts_list')
    return redirect('contact_detail', pk=pk)


@login_required
def contact_update_status(request, pk):
    contact = get_object_or_404(Contact, pk=pk)
    if request.method == 'POST':
        new_status = request.POST.get('status', '').strip().lower()
        if new_status in ['lead', 'customer', 'inactive', 'active']:
            contact.status = new_status
            contact.save()
            messages.success(request, f"تم تغيير حالة جهة الاتصال إلى {contact.status_label}.")
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({'status': 'ok', 'new_status': contact.status_label})
    return redirect('contact_detail', pk=pk)


@login_required
def contact_add_comment(request, pk):
    contact = get_object_or_404(Contact, pk=pk)
    if request.method == 'POST':
        text = request.POST.get('comment', '').strip()
        if text:
            ContactComment.objects.create(
                contact=contact,
                author=request.user,
                text=text
            )
            messages.success(request, "تمت إضافة التعليق بنجاح.")
        else:
            messages.warning(request, "لا يمكن إضافة تعليق فارغ.")
    return redirect(f"{redirect('contact_detail', pk=pk).url}?tab=overview")


@login_required
def contact_create_todo(request, pk):
    contact = get_object_or_404(Contact, pk=pk)
    if request.method == 'POST':
        title = request.POST.get('title', '').strip()
        if title:
            ContactTodo.objects.create(
                contact=contact,
                title=title,
                created_by=request.user
            )
            messages.success(request, "تمت إضافة المهمة بنجاح.")
    return redirect(f"{redirect('contact_detail', pk=pk).url}?tab=Todos")


@login_required
def contact_toggle_todo(request, pk, todo_id):
    contact = get_object_or_404(Contact, pk=pk)
    todo = get_object_or_404(ContactTodo, pk=todo_id, contact=contact)
    todo.is_completed = not todo.is_completed
    todo.save()
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({'status': 'ok', 'is_completed': todo.is_completed})
    return redirect(f"{redirect('contact_detail', pk=pk).url}?tab=Todos")


@login_required
def contact_upload_attachment(request, pk):
    contact = get_object_or_404(Contact, pk=pk)
    if request.method == 'POST' and request.FILES.get('file'):
        uploaded_file = request.FILES['file']
        ContactAttachment.objects.create(
            contact=contact,
            file=uploaded_file,
            filename=uploaded_file.name,
            uploaded_by=request.user
        )
        messages.success(request, f"تم رفع الملف '{uploaded_file.name}' بنجاح.")
    return redirect(f"{redirect('contact_detail', pk=pk).url}?tab=المرفقات")


@login_required
def contact_add_address(request, pk):
    contact = get_object_or_404(Contact, pk=pk)
    if request.method == 'POST':
        title = request.POST.get('title', '').strip()
        area_id = request.POST.get('area_id')
        sub_area = request.POST.get('sub_area', '').strip()
        street = request.POST.get('street_address', '').strip()
        is_main = request.POST.get('is_main') == 'on'

        area = Area.objects.filter(id=area_id).first() if area_id else None
        if area or street or title:
            if is_main:
                contact.addresses.update(is_main=False)
            ContactAddress.objects.create(
                contact=contact,
                title=title,
                area=area,
                sub_area=sub_area,
                street_address=street,
                is_main=is_main
            )
            messages.success(request, "تمت إضافة العنوان بنجاح.")
    return redirect(f"{redirect('contact_detail', pk=pk).url}?tab=overview")


@login_required
def contact_delete_address(request, pk, address_id):
    contact = get_object_or_404(Contact, pk=pk)
    address = get_object_or_404(ContactAddress, pk=address_id, contact=contact)
    if request.method == 'POST':
        address.delete()
        messages.success(request, "تم حذف العنوان بنجاح.")
    return redirect(f"{redirect('contact_detail', pk=pk).url}?tab=overview")


@login_required
def contacts_export(request):
    relation = request.GET.get('relation', 'all')
    search = request.GET.get('search', '').strip()

    qs = Contact.objects.select_related('area').all()
    if relation == 'vendor':
        qs = qs.filter(is_supplier=True)
    elif relation == 'customer':
        qs = qs.filter(is_customer=True)

    if search:
        qs = qs.filter(
            Q(name__icontains=search) |
            Q(serial_num__icontains=search) |
            Q(mobile__icontains=search) |
            Q(tax_id__icontains=search) |
            Q(code__icontains=search)
        )

from master_data.excel_utils import (
    export_to_excel_response,
    generate_excel_template_response,
    ExcelImportParser,
    parse_decimal_safe,
    parse_boolean_safe,
)
from sales.models import CustomerAccount
from django.db import transaction


@login_required
def contacts_export(request):
    relation = request.GET.get('relation', 'all').strip()
    status = request.GET.get('status', 'all').strip()
    search = request.GET.get('search', '').strip() or request.GET.get('q', '').strip()

    qs = Contact.objects.select_related('area').prefetch_related('addresses__area').all()

    if status != 'all' and status:
        qs = qs.filter(status=status)
    if relation == 'vendor':
        qs = qs.filter(is_supplier=True)
    elif relation == 'customer':
        qs = qs.filter(is_customer=True)

    if search:
        qs = qs.filter(
            Q(name__icontains=search) |
            Q(serial_num__icontains=search) |
            Q(mobile__icontains=search) |
            Q(tax_id__icontains=search) |
            Q(code__icontains=search)
        )

    columns = [
        {'header': 'رقم المسلسل', 'key': lambda c: f"#{c.serial_num}", 'width': 14, 'align': 'center'},
        {'header': 'الاسم', 'key': 'name', 'width': 35, 'align': 'right'},
        {'header': 'نوع الحساب', 'key': lambda c: c.get_contact_type_display(), 'width': 16, 'align': 'center'},
        {'header': 'علاقة العمل', 'key': lambda c: c.relation_display, 'width': 16, 'align': 'center'},
        {'header': 'حالة العميل', 'key': lambda c: c.status_label, 'width': 14, 'align': 'center'},
        {'header': 'المنطقة', 'key': lambda c: c.area.name if c.area else '', 'width': 22, 'align': 'right'},
        {'header': 'العنوان الرئيسي', 'key': lambda c: c.addresses.filter(is_main=True).first().street_address if c.addresses.filter(is_main=True).exists() else '', 'width': 35, 'align': 'right'},
        {'header': 'الموبايل', 'key': lambda c: c.mobile or '', 'width': 18, 'align': 'center'},
        {'header': 'الهاتف', 'key': lambda c: c.phone or '', 'width': 18, 'align': 'center'},
        {'header': 'تصنيف العميل', 'key': lambda c: c.customer_category or '', 'width': 18, 'align': 'center'},
        {'header': 'التخصص', 'key': lambda c: c.specialty or '', 'width': 18, 'align': 'center'},
        {'header': 'نوع الاكونت', 'key': lambda c: c.account_type or '', 'width': 18, 'align': 'center'},
        {'header': 'الكود', 'key': lambda c: c.code or '', 'width': 16, 'align': 'center'},
        {'header': 'حد الائتمان', 'key': lambda c: float(c.credit_limit) if c.credit_limit is not None else 0.0, 'format': '#,##0.00', 'width': 18, 'align': 'right'},
    ]

    return export_to_excel_response(qs, columns, filename="contacts_export", sheet_title="جهات الاتصال")


@login_required
def contacts_import_template(request):
    columns = [
        {'header': 'المسلسل', 'width': 14},
        {'header': 'الاسم', 'width': 35},
        {'header': 'علاقة العمل (عميل / مورد / كلاهما)', 'width': 24},
        {'header': 'الموبايل', 'width': 18},
        {'header': 'الهاتف', 'width': 18},
        {'header': 'المنطقة', 'width': 20},
        {'header': 'العنوان التفصيلي', 'width': 35},
        {'header': 'حد الائتمان', 'width': 16},
        {'header': 'تصنيف العميل', 'width': 18},
        {'header': 'التخصص', 'width': 18},
        {'header': 'الرقم الضريبي', 'width': 18},
        {'header': 'الكود', 'width': 16},
    ]
    sample_rows = [
        [1001, 'صيدلية النور والشفاء', 'عميل', '01012345678', '0223456789', 'مدينة نصر', '15 شارع الطيران، بجوار مسجد رابعة', 50000.00, 'A', 'صيدلية مجتمعية', '123-456-789', 'CLI-1001'],
        [1002, 'شركة النيل للتوزيع الدوائي', 'مورد', '01198765432', '0233445566', 'الدقي', '40 شارع مصدق، الجيزة', 0.00, '', '', '987-654-321', 'SUP-1002'],
    ]
    return generate_excel_template_response(columns, sample_rows=sample_rows, filename="contacts_import_template", sheet_title="نموذج جهات الاتصال")


@login_required
def contacts_import(request):
    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'preview':
            excel_file = request.FILES.get('excel_file')
            if not excel_file:
                messages.error(request, "يرجى اختيار ملف Excel للرفع.")
                return render(request, 'contacts/contacts_import.html', {'preview_mode': False})

            column_mapping = {
                'serial_num': ['رقم المسلسل', 'المسلسل', 'serial_num', 'serial'],
                'name': ['اسم العميل', 'اسم المورد', 'الاسم', 'name', 'contact_name'],
                'relation': ['علاقة العمل (عميل / مورد / كلاهما)', 'علاقة العمل', 'نوع العلاقة', 'relation', 'type'],
                'mobile': ['الموبايل', 'رقم الموبايل', 'mobile', 'phone_number'],
                'phone': ['الهاتف', 'التليفون', 'phone'],
                'area': ['المنطقة', 'المحافظة', 'area', 'governorate'],
                'street_address': ['العنوان التفصيلي', 'العنوان', 'العنوان الرئيسي', 'address', 'street'],
                'credit_limit': ['حد الائتمان', 'الحد الائتماني', 'credit_limit'],
                'customer_category': ['تصنيف العميل', 'التصنيف', 'category'],
                'specialty': ['التخصص', 'specialty'],
                'tax_id': ['الرقم الضريبي', 'البطاقة الضريبية', 'tax_id'],
                'code': ['الكود', 'كود العميل', 'كود المورد', 'code'],
            }

            parser = ExcelImportParser(excel_file, column_mapping)
            if not parser.parse():
                for err in parser.errors:
                    messages.error(request, err)
                return render(request, 'contacts/contacts_import.html', {'preview_mode': False})

            existing_serials = set(Contact.objects.filter(serial_num__isnull=False).values_list('serial_num', flat=True))
            existing_mobiles = set(Contact.objects.exclude(mobile='').values_list('mobile', flat=True))
            existing_codes = set(Contact.objects.exclude(code='').values_list('code', flat=True))

            preview_rows = []
            seen_serials = set()
            new_count = 0
            update_count = 0
            invalid_count = 0

            for r in parser.rows_data:
                row_errors = []
                name = str(r.get('name') or '').strip()
                serial = r.get('serial_num')
                serial_clean = None
                if serial not in [None, '']:
                    try:
                        serial_clean = int(float(str(serial)))
                    except Exception:
                        row_errors.append("رقم المسلسل يجب أن يكون عدداً صحيحاً")

                if not name:
                    row_errors.append("اسم جهة الاتصال مطلوب")

                if serial_clean:
                    if serial_clean in seen_serials:
                        row_errors.append("رقم مسلسل مكرر داخل نفس الملف")
                    else:
                        seen_serials.add(serial_clean)

                mobile = str(r.get('mobile') or '').strip()
                code = str(r.get('code') or '').strip()

                is_existing = False
                if serial_clean and serial_clean in existing_serials:
                    is_existing = True
                elif code and code in existing_codes:
                    is_existing = True
                elif mobile and mobile in existing_mobiles:
                    is_existing = True

                is_valid = len(row_errors) == 0

                if not is_valid:
                    invalid_count += 1
                elif is_existing:
                    update_count += 1
                else:
                    new_count += 1

                preview_rows.append({
                    'row_num': r.get('__row_num__'),
                    'serial_num': serial_clean,
                    'name': name,
                    'relation': r.get('relation') or 'عميل',
                    'mobile': mobile,
                    'phone': str(r.get('phone') or '').strip(),
                    'area': str(r.get('area') or '').strip(),
                    'street_address': str(r.get('street_address') or '').strip(),
                    'credit_limit': str(r.get('credit_limit') or '0.00'),
                    'customer_category': str(r.get('customer_category') or ''),
                    'specialty': str(r.get('specialty') or ''),
                    'tax_id': str(r.get('tax_id') or '').strip(),
                    'code': code,
                    'is_valid': is_valid,
                    'is_existing': is_existing,
                    'errors': row_errors,
                })

            valid_count = len(preview_rows) - invalid_count
            request.session['contacts_import_data'] = preview_rows

            context = {
                'preview_mode': True,
                'total_rows': len(preview_rows),
                'valid_count': valid_count,
                'invalid_count': invalid_count,
                'new_count': new_count,
                'update_count': update_count,
                'preview_rows': preview_rows[:100],
                'total_preview_count': min(len(preview_rows), 100),
            }
            return render(request, 'contacts/contacts_import.html', context)

        elif action == 'execute':
            import_mode = request.POST.get('import_mode', 'create_and_update')
            rows_data = request.session.get('contacts_import_data', [])

            if not rows_data:
                messages.error(request, "انتهت صلاحية جلسة الاستيراد أو لا توجد بيانات. يرجى إعادة رفع الملف.")
                return redirect('contacts_import')

            created_count = 0
            updated_count = 0
            skipped_count = 0

            areas_map = {a.name.strip().lower(): a for a in Area.objects.all()}

            try:
                with transaction.atomic():
                    for r in rows_data:
                        if not r.get('is_valid'):
                            skipped_count += 1
                            continue

                        name = r['name']
                        serial_clean = r.get('serial_num')
                        mobile = r.get('mobile', '')
                        code = r.get('code', '')
                        rel_str = str(r.get('relation') or '').lower()

                        is_customer = True
                        is_supplier = False
                        if 'مورد' in rel_str or 'supplier' in rel_str or 'vendor' in rel_str:
                            is_supplier = True
                            if 'عميل' not in rel_str and 'customer' not in rel_str:
                                is_customer = False
                        if 'كلاهما' in rel_str or ('عميل' in rel_str and 'مورد' in rel_str):
                            is_customer = True
                            is_supplier = True

                        area_name = r.get('area', '').strip()
                        area_obj = None
                        if area_name:
                            area_key = area_name.lower()
                            if area_key in areas_map:
                                area_obj = areas_map[area_key]
                            else:
                                area_obj = Area.objects.create(name=area_name, area_type='area')
                                areas_map[area_key] = area_obj

                        credit_limit = parse_decimal_safe(r.get('credit_limit'), Decimal('0.00'))

                        # Find matching contact
                        contact = None
                        if serial_clean:
                            contact = Contact.objects.filter(serial_num=serial_clean).first()
                        if not contact and code:
                            contact = Contact.objects.filter(code=code).first()
                        if not contact and mobile:
                            contact = Contact.objects.filter(mobile=mobile).first()

                        if contact:
                            if import_mode in ['create_and_update', 'update_only']:
                                contact.name = name
                                contact.is_customer = is_customer
                                contact.is_supplier = is_supplier
                                if mobile:
                                    contact.mobile = mobile
                                if r.get('phone'):
                                    contact.phone = r['phone']
                                if area_obj:
                                    contact.area = area_obj
                                if credit_limit > 0:
                                    contact.credit_limit = credit_limit
                                if r.get('customer_category'):
                                    contact.customer_category = r['customer_category']
                                if r.get('specialty'):
                                    contact.specialty = r['specialty']
                                if r.get('tax_id'):
                                    contact.tax_id = r['tax_id']
                                if code:
                                    contact.code = code
                                contact.save()

                                if r.get('street_address'):
                                    main_addr = contact.addresses.filter(is_main=True).first()
                                    if main_addr:
                                        main_addr.street_address = r['street_address']
                                        if area_obj:
                                            main_addr.area = area_obj
                                        main_addr.save()
                                    else:
                                        ContactAddress.objects.create(
                                            contact=contact,
                                            street_address=r['street_address'],
                                            area=area_obj,
                                            is_main=True
                                        )

                                if is_customer:
                                    CustomerAccount.get_or_create_for_customer(contact)
                                if is_supplier:
                                    VendorAccount.get_or_create_for_supplier(contact)

                                updated_count += 1
                            else:
                                skipped_count += 1
                        else:
                            if import_mode in ['create_and_update', 'create_only']:
                                new_contact = Contact(
                                    name=name,
                                    serial_num=serial_clean,
                                    is_customer=is_customer,
                                    is_supplier=is_supplier,
                                    mobile=mobile,
                                    phone=r.get('phone', ''),
                                    area=area_obj,
                                    credit_limit=credit_limit,
                                    customer_category=r.get('customer_category', ''),
                                    specialty=r.get('specialty', ''),
                                    tax_id=r.get('tax_id', ''),
                                    code=code,
                                    status='customer' if is_customer else 'active',
                                    created_by=request.user
                                )
                                new_contact.save()

                                if r.get('street_address') or area_obj:
                                    ContactAddress.objects.create(
                                        contact=new_contact,
                                        street_address=r.get('street_address', ''),
                                        area=area_obj,
                                        is_main=True
                                    )

                                if is_customer:
                                    CustomerAccount.get_or_create_for_customer(new_contact)
                                if is_supplier:
                                    VendorAccount.get_or_create_for_supplier(new_contact)

                                created_count += 1
                            else:
                                skipped_count += 1

                request.session.pop('contacts_import_data', None)
                messages.success(
                    request,
                    f"اكتمل استيراد جهات الاتصال بنجاح! تم إنشاء {created_count} جهة اتصال جديدة، "
                    f"وتحديث {updated_count} جهة، وتخطي {skipped_count} سجل."
                )
                return redirect('contacts_list')

            except Exception as e:
                messages.error(request, f"حدث خطأ أثناء حفظ جهات الاتصال وتم التراجع عن كافة العمليات: {str(e)}")
                return redirect('contacts_import')

    return render(request, 'contacts/contacts_import.html', {'preview_mode': False})


@login_required
def get_subareas(request):
    area_id = request.GET.get('area_id')
    if not area_id:
        return JsonResponse({'subareas': []})
    subareas = list(Area.objects.filter(parent_id=area_id).values('id', 'name'))
    return JsonResponse({'subareas': subareas})
