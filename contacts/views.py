import csv
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q
from django.http import JsonResponse, HttpResponse
from django.core.paginator import Paginator
from .models import Contact, ContactAddress, ContactComment, ContactAttachment, ContactTodo, ContactActivity
from master_data.models import Area
from treasury.models import VendorAccount
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

    response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
    response['Content-Disposition'] = 'attachment; filename="contacts_export.csv"'
    writer = csv.writer(response)
    writer.writerow([
        'رقم المسلسل', 'الاسم', 'نوع الحساب', 'علاقة العمل',
        'حالة العميل', 'المنطقة', 'العنوان الرئيسي', 'الموبايل',
        'تصنيف العميل', 'التخصص', 'نوع الاكونت', 'الكود', 'حد الائتمان'
    ])

    for c in qs:
        main_addr = c.addresses.filter(is_main=True).first()
        addr_text = main_addr.street_address if main_addr else ''
        area_text = f"{main_addr.sub_area} | {main_addr.area.name}" if (main_addr and main_addr.area) else (c.area.name if c.area else '')
        writer.writerow([
            f"#{c.serial_num}",
            c.name,
            c.get_contact_type_display(),
            c.relation_display,
            c.status_label,
            area_text,
            addr_text,
            c.mobile or c.phone,
            c.customer_category,
            c.specialty,
            c.account_type,
            c.code,
            c.credit_limit
        ])

    return response


@login_required
def get_subareas(request):
    area_id = request.GET.get('area_id')
    if not area_id:
        return JsonResponse({'subareas': []})
    subareas = list(Area.objects.filter(parent_id=area_id).values('id', 'name'))
    return JsonResponse({'subareas': subareas})
