from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q
from .models import Contact, ContactAddress
from master_data.models import Area
from treasury.models import VendorAccount


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
            Q(tax_card__icontains=search)
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
        contact_type = request.POST.get('contact_type', 'company')
        is_supplier = request.POST.get('is_supplier') == 'on'
        is_customer = request.POST.get('is_customer') == 'on'
        mobile = request.POST.get('mobile', '').strip()
        phone = request.POST.get('phone', '').strip()
        email = request.POST.get('email', '').strip()
        area_id = request.POST.get('area')
        street_address = request.POST.get('street_address', '').strip()
        tax_card = request.POST.get('tax_card', '').strip()
        commercial_registry = request.POST.get('commercial_registry', '').strip()
        credit_limit = request.POST.get('credit_limit') or '0.00'
        credit_period_days = request.POST.get('credit_period_days') or '30'

        if not name:
            messages.error(request, "اسم جهة الاتصال مطلوب.")
            return redirect('contacts_list')

        area = Area.objects.filter(id=area_id).first() if area_id else None

        contact = Contact.objects.create(
            name=name,
            contact_type=contact_type,
            is_supplier=is_supplier,
            is_customer=is_customer,
            mobile=mobile,
            phone=phone,
            email=email,
            area=area,
            tax_card=tax_card,
            commercial_registry=commercial_registry,
            credit_limit=credit_limit,
            credit_period_days=credit_period_days,
            created_by=request.user
        )

        if street_address:
            ContactAddress.objects.create(
                contact=contact,
                title="العنوان الرئيسي",
                street_address=street_address,
                area=area,
                is_main=True
            )

        if is_supplier:
            VendorAccount.get_or_create_for_supplier(contact)

        messages.success(request, f"تم إنشاء جهة الاتصال '{contact.name}' بنجاح (#{contact.serial_num}).")
        return redirect('contacts_list')

    return redirect('contacts_list')
