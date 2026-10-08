from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q
from django.http import JsonResponse
from .models import Contact, ContactAddress
from master_data.models import Area
from treasury.models import VendorAccount
from .constants import CUSTOMER_CATEGORIES, SPECIALTIES, ACCOUNT_TYPES, COUNTRY_CODES


@login_required
def contacts_list(request):
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
            Q(tax_card__icontains=search) |
            Q(tax_id__icontains=search) |
            Q(code__icontains=search)
        )

    areas = Area.objects.all()

    context = {
        'contacts': qs,
        'current_relation': relation,
        'search_query': search,
        'areas': areas,
        'total_count': qs.count(),
    }
    return render(request, 'contacts/contacts_list.html', context)


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
            notes=notes,
            created_by=request.user
        )

        # Handle addresses (address cards)
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
            # Fallback for single address fields
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
        return redirect('contacts_list')

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
def get_subareas(request):
    area_id = request.GET.get('area_id')
    if not area_id:
        return JsonResponse({'subareas': []})
    subareas = list(Area.objects.filter(parent_id=area_id).values('id', 'name'))
    return JsonResponse({'subareas': subareas})
