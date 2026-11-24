from django import forms
from django.utils import timezone
from .models import Agreement, Visit, PlannedVisitItem, VisitSampleItem, VisitTemplate, VisitTemplateQuestion
from contacts.models import Contact


class AgreementForm(forms.ModelForm):
    class Meta:
        model = Agreement
        fields = ['customer', 'title', 'type', 'amount', 'date', 'description']
        widgets = {
            'customer': forms.Select(attrs={
                'class': 'w-full rounded-xl border border-slate-200 px-3 py-2 text-sm focus:border-brand-500 focus:ring-1 focus:ring-brand-500',
                'data-smart-select': 'true',
                'data-search-url': '/contacts/api/search/',
                'data-search-placeholder': 'ابحث باسم العميل أو الكود أو المنطقة...',
            }),
            'title': forms.TextInput(attrs={'class': 'w-full rounded-xl border border-slate-200 px-3 py-2 text-sm focus:border-brand-500 focus:ring-1 focus:ring-brand-500', 'placeholder': 'عنوان الاتفاقية'}),
            'type': forms.Select(attrs={'class': 'w-full rounded-xl border border-slate-200 px-3 py-2 text-sm focus:border-brand-500 focus:ring-1 focus:ring-brand-500'}),
            'amount': forms.NumberInput(attrs={'class': 'w-full rounded-xl border border-slate-200 px-3 py-2 text-sm focus:border-brand-500 focus:ring-1 focus:ring-brand-500', 'step': '0.01'}),
            'date': forms.DateInput(attrs={'class': 'w-full rounded-xl border border-slate-200 px-3 py-2 text-sm focus:border-brand-500 focus:ring-1 focus:ring-brand-500', 'type': 'date'}),
            'description': forms.Textarea(attrs={'class': 'w-full rounded-xl border border-slate-200 px-3 py-2 text-sm focus:border-brand-500 focus:ring-1 focus:ring-brand-500', 'rows': 4, 'placeholder': 'تفاصيل وشروط الاتفاقية...'}),
        }

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        if user:
            from accounts.permissions import get_scoped_queryset
            base_qs = Contact.objects.filter(is_customer=True).exclude(status='inactive')
            scoped_qs = get_scoped_queryset(base_qs, user, 'contact')
            selected_cust_id = (
                (self.data.get('customer') if self.data else None)
                or self.initial.get('customer')
                or (self.instance.customer_id if (self.instance and self.instance.pk) else None)
            )
            bounded_pks = list(scoped_qs.values_list('pk', flat=True)[:100])
            if selected_cust_id:
                try:
                    target_pk = int(selected_cust_id)
                except (ValueError, TypeError):
                    target_pk = None
                if target_pk and target_pk not in bounded_pks:
                    if scoped_qs.filter(pk=target_pk).exists():
                        bounded_pks.append(target_pk)
            self.fields['customer'].queryset = Contact.objects.filter(pk__in=bounded_pks).select_related('area', 'brick').order_by('name')
        else:
            self.fields['customer'].queryset = Contact.objects.none()


class PlannedVisitItemForm(forms.ModelForm):
    class Meta:
        model = PlannedVisitItem
        fields = ['contact', 'template', 'order', 'notes']
        widgets = {
            'contact': forms.Select(attrs={'class': 'w-full rounded-xl border border-slate-200 px-3 py-2 text-sm focus:border-brand-500 focus:ring-1 focus:ring-brand-500'}),
            'template': forms.Select(attrs={'class': 'w-full rounded-xl border border-slate-200 px-3 py-2 text-sm focus:border-brand-500 focus:ring-1 focus:ring-brand-500'}),
            'order': forms.NumberInput(attrs={'class': 'w-full rounded-xl border border-slate-200 px-3 py-2 text-sm focus:border-brand-500 focus:ring-1 focus:ring-brand-500', 'min': 1}),
            'notes': forms.TextInput(attrs={'class': 'w-full rounded-xl border border-slate-200 px-3 py-2 text-sm focus:border-brand-500 focus:ring-1 focus:ring-brand-500', 'placeholder': 'ملاحظات التخطيط'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['template'].required = True
        self.fields['template'].empty_label = "-- اختر قالب الزيارة (إلزامي) --"

    def clean(self):
        cleaned_data = super().clean()
        contact = cleaned_data.get('contact')
        template = cleaned_data.get('template')
        if not template:
            raise forms.ValidationError("اختيار قالب الزيارة إلزامي لإتمام التخطيط.")
        if contact and template:
            if not template.is_contact_eligible(contact):
                allowed_str = ", ".join(template.restrict_account_types) if template.restrict_account_types else "الكل"
                raise forms.ValidationError(
                    f"قالب الزيارة '{template.display_name_ar}' غير مخصص لنوع حساب العميل ({contact.account_type or 'غير محدد'}). الأنواع المصرح بها: {allowed_str}."
                )
        return cleaned_data


from django.db.models import Q


class CustomerSelectWidget(forms.Select):
    """Custom select widget that enriches customer options with subtext and search metadata."""
    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        opt = super().create_option(name, value, label, selected, index, subindex=subindex, attrs=attrs)
        if value and hasattr(value, 'instance'):
            c = value.instance
            area_name = c.area.name if getattr(c, 'area', None) else ''
            brick_name = c.brick.name if getattr(c, 'brick', None) else ''
            geo = f"{area_name} - {brick_name}" if (area_name and brick_name and area_name != brick_name) else (brick_name or area_name)
            parts = [f"#{c.serial_num}"] if getattr(c, 'serial_num', None) else []
            if geo:
                parts.append(geo)
            acc = getattr(c, 'account_type', None) or getattr(c, 'customer_category', None)
            if acc:
                parts.append(str(acc))
            opt['attrs']['data-subtext'] = " | ".join(parts)
            opt['attrs']['data-search'] = f"{c.serial_num or ''} {c.code or ''} {c.mobile or ''} {geo} {c.specialty or ''}".strip()
        return opt


class CustomerModelChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return obj.name


class VisitForm(forms.ModelForm):
    contact = CustomerModelChoiceField(
        queryset=Contact.objects.none(),
        widget=CustomerSelectWidget(attrs={
            'id': 'visit-contact-select',
            'class': 'w-full rounded-xl border border-slate-200 px-3 py-2 text-xs font-bold text-slate-800 focus:border-[#27bebe] focus:ring-1 focus:ring-[#27bebe]',
            'data-smart-select': 'true',
            'data-search-url': '/contacts/api/search/',
            'data-search-placeholder': 'ابحث باسم العميل أو الكود أو الهاتف أو التخصص...',
            'onchange': 'onCustomerSelected(this.value)'
        }),
        label="جهة الاتصال (العميل) *"
    )
    latitude = forms.DecimalField(required=False, widget=forms.HiddenInput(attrs={'id': 'id_latitude'}))
    longitude = forms.DecimalField(required=False, widget=forms.HiddenInput(attrs={'id': 'id_longitude'}))
    device_accuracy = forms.DecimalField(required=False, widget=forms.HiddenInput(attrs={'id': 'id_device_accuracy'}))
    planned_item_id = forms.IntegerField(required=False, widget=forms.HiddenInput(attrs={'id': 'id_planned_item_id'}))

    class Meta:
        model = Visit
        fields = ['contact', 'template', 'owner', 'date', 'is_successful', 'doubled', 'latitude', 'longitude', 'device_accuracy']
        widgets = {
            'template': forms.Select(attrs={'id': 'visit-template-select', 'class': 'w-full rounded-xl border border-slate-200 px-3 py-2 text-xs font-bold text-slate-800 focus:border-[#27bebe] focus:ring-1 focus:ring-[#27bebe]', 'onchange': 'onTemplateSelected(this.value)'}),
            'owner': forms.Select(attrs={'id': 'visit-owner-select', 'class': 'w-full rounded-xl border border-slate-200 px-3 py-2 text-xs font-bold text-slate-800 focus:border-[#27bebe] focus:ring-1 focus:ring-[#27bebe]'}),
            'date': forms.DateInput(attrs={'class': 'w-full rounded-xl border border-slate-200 px-3 py-2 text-xs font-bold text-slate-800 focus:border-[#27bebe] focus:ring-1 focus:ring-[#27bebe]', 'type': 'date'}),
            'is_successful': forms.CheckboxInput(attrs={'class': 'w-4 h-4 rounded border-slate-300 text-[#27bebe] focus:ring-[#27bebe]'}),
            'doubled': forms.CheckboxInput(attrs={'class': 'w-4 h-4 rounded border-slate-300 text-[#27bebe] focus:ring-[#27bebe]'}),
        }

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        base_qs = Contact.objects.exclude(status='inactive')

        from django.contrib.auth import get_user_model
        UserModel = get_user_model()

        # Determine currently targeted contact (from POST submission, initial data, or instance on edit)
        selected_contact_id = (
            (self.data.get('contact') if self.data else None)
            or self.initial.get('contact')
            or (self.instance.contact_id if (self.instance and self.instance.pk) else None)
        )

        if user:
            from accounts.permissions import (
                is_manager_or_higher,
                get_visit_eligible_contacts_queryset,
                get_user_managed_representatives,
            )
            is_manager = is_manager_or_higher(user)
            self.is_manager = is_manager

            # Strictly scope available contacts to user's permitted geographical scope (Superadmin -> all, Manager -> Main Area, Rep -> Brick)
            scoped_qs = get_visit_eligible_contacts_queryset(base_qs, user)

            self.fields['owner'].required = False
            if not is_manager:
                # Lock representative assignment on create; preserve existing owner on edit
                locked_owner = self.instance.owner if (self.instance and self.instance.pk and self.instance.owner_id) else user
                self.fields['owner'].queryset = UserModel.objects.filter(pk=locked_owner.pk)
                self.fields['owner'].initial = locked_owner
                self.fields['owner'].disabled = True
            else:
                managed_reps = get_user_managed_representatives(user, module='activities')
                managed_rep_ids = list(managed_reps.values_list('pk', flat=True))
                allowed_owner_ids = set(managed_rep_ids) | {user.pk}
                if self.instance and self.instance.pk and self.instance.owner_id:
                    allowed_owner_ids.add(self.instance.owner_id)
                self.fields['owner'].queryset = UserModel.objects.filter(pk__in=allowed_owner_ids).order_by('first_name', 'username')
                self.fields['owner'].initial = self.instance.owner if (self.instance and self.instance.pk and self.instance.owner_id) else user
        else:
            self.is_manager = False
            scoped_qs = base_qs
            self.fields['owner'].required = False

        # Paginate/bound contact options to top 100 + selected contact to eliminate route lag (matching sales/create/)
        bounded_pks = list(scoped_qs.values_list('pk', flat=True)[:100])
        if selected_contact_id:
            try:
                target_pk = int(selected_contact_id)
            except (ValueError, TypeError):
                target_pk = None
            if target_pk and target_pk not in bounded_pks:
                # Strictly verify target_pk is within user's permitted scope
                if scoped_qs.filter(pk=target_pk).exists():
                    bounded_pks.append(target_pk)

        self.fields['contact'].queryset = (
            Contact.objects.filter(pk__in=bounded_pks)
            .select_related('area', 'brick')
            .order_by('name')
        )

        # Scope templates to active templates eligible for user's role
        templates_qs = VisitTemplate.objects.filter(active=True).prefetch_related('restricted_roles')
        eligible_template_ids = [t.id for t in templates_qs if t.is_user_eligible(user)]
        if self.instance and self.instance.pk and self.instance.template_id:
            eligible_template_ids.append(self.instance.template_id)
        self.fields['template'].queryset = VisitTemplate.objects.filter(id__in=eligible_template_ids).order_by('name')
        self.fields['template'].required = True
        self.fields['template'].empty_label = "-- اختر قالب الزيارة (إلزامي) --"

        is_editing = bool(self.instance and self.instance.pk)
        planned_item_id = (self.data.get('planned_item_id') if self.data else None) or self.initial.get('planned_item_id')
        if not is_editing and not planned_item_id:
            self.fields['date'].required = False

    def clean(self):
        cleaned_data = super().clean()
        user = self.user
        is_editing = bool(self.instance and self.instance.pk)

        # Business Rule (Requirement 4.B & 6): Non-managers cannot reassign owner
        is_manager = getattr(self, 'is_manager', False)
        if not is_manager:
            if is_editing and self.instance.owner_id:
                cleaned_data['owner'] = self.instance.owner
            elif user and user.is_authenticated:
                cleaned_data['owner'] = user
        elif not cleaned_data.get('owner') and user and user.is_authenticated:
            cleaned_data['owner'] = self.instance.owner if (is_editing and self.instance.owner_id) else user

        # Determine Visit Type: Planned vs Unplanned
        # Planned visits must ONLY be created via bulk planned-visits workflow and executed via planned_item_id.
        # Direct visit creation via /visits/create/ is strictly Unplanned.
        planned_item_id = self.data.get('planned_item_id') or cleaned_data.get('planned_item_id')
        if is_editing:
            is_planned_visit = self.instance.is_planned
        else:
            is_planned_visit = bool(planned_item_id)
        cleaned_data['is_planned'] = is_planned_visit

        # Geographical Scope Validation (Requirement 7)
        contact = cleaned_data.get('contact')
        if contact and user and user.is_authenticated and not is_editing:
            from accounts.permissions import can_user_access_contact_for_visit
            if not can_user_access_contact_for_visit(user, contact):
                raise forms.ValidationError(
                    "غير مصرح لك بإنشاء أو الوصول إلى زيارة لهذا العميل لأنه يقع خارج نطاق منطقتك الجغرافية المخصصة."
                )

        # Mandatory template validation & eligibility (Requirement 1)
        template = cleaned_data.get('template')
        if not template:
            raise forms.ValidationError("اختيار قالب الزيارة إلزامي لإتمام العملية.")
        if user and not template.is_user_eligible(user):
            raise forms.ValidationError(
                f"دورك الوظيفي غير مصرح له باستخدام قالب الزيارة '{template.display_name_ar}'."
            )
        if contact and not template.is_contact_eligible(contact, user=user):
            allowed_str = ", ".join(template.restrict_account_types) if template.restrict_account_types else "الكل"
            raise forms.ValidationError(
                f"قالب الزيارة '{template.display_name_ar}' غير مخصص لنوع حساب العميل ({contact.account_type or 'غير محدد'}). الأنواع المصرح بها: {allowed_str}."
            )

        # Date Validation:
        # - Unplanned immediate-start creation always forces today's local date.
        # - Planned / edited visits must be today or future when changed.
        if not is_editing and not is_planned_visit:
            cleaned_data['date'] = timezone.localdate()
        else:
            visit_date = cleaned_data.get('date')
            if visit_date:
                today = timezone.localdate()
                is_date_changed = is_editing and (self.instance.date != visit_date)
                if (not is_editing or is_date_changed) and visit_date < today:
                    raise forms.ValidationError("لا يمكن اختيار تاريخ في الماضي. يرجى اختيار تاريخ اليوم أو تاريخ مستقبلي.")

        # Planned Visit Item Backend Validation (Requirement 3)
        if planned_item_id:
            try:
                item = PlannedVisitItem.objects.select_related('plan_day', 'contact').get(pk=planned_item_id)
                if contact and contact.id != item.contact_id:
                    raise forms.ValidationError("جهة الاتصال المختارة لا تطابق العميل في جدول الخطة المحددة.")
                is_rep_owner = (item.plan_day.assignee == user)
                can_admin = bool(is_manager or (user and (user.is_superuser or getattr(user, 'is_super_admin', False))))
                if not (is_rep_owner or can_admin):
                    raise forms.ValidationError("غير مصرح لك بتسجيل زيارة لعنصر خطة خاص بمندوب آخر.")
                cleaned_data['planned_item'] = item
            except PlannedVisitItem.DoesNotExist:
                raise forms.ValidationError("عنصر الخطة المحدد غير موجود أو غير صالح.")

        # Distance & Location Validation during Visit Creation (Requirement 3.B):
        # - Planned visits: Distance validation is NOT required during creation.
        # - Unplanned visits: Distance validation IS mandatory during creation.
        from master_data.models import LocationSettings
        from activities.services import calculate_haversine_distance
        settings = LocationSettings.get_settings()

        lat = cleaned_data.get('latitude') if cleaned_data.get('latitude') is not None else self.data.get('latitude')
        lng = cleaned_data.get('longitude') if cleaned_data.get('longitude') is not None else self.data.get('longitude')
        has_coords = not (lat is None or lng is None or str(lat).strip() == '' or str(lng).strip() == '')

        lat_float = None
        lng_float = None
        if has_coords:
            try:
                lat_float = float(lat)
                lng_float = float(lng)
                if not (-90.0 <= lat_float <= 90.0 and -180.0 <= lng_float <= 180.0):
                    raise forms.ValidationError("إحداثيات الموقع الجغرافي غير صالحة.")
                if lat_float == 0.0 and lng_float == 0.0:
                    raise forms.ValidationError("إحداثيات الموقع الجغرافي غير صالحة (0, 0).")
            except (ValueError, TypeError):
                raise forms.ValidationError("صيغة إحداثيات الموقع غير صالحة.")

        return cleaned_data


ACCOUNT_TYPE_CHOICES = [
    ("Pharmacy", "صيدلية (Pharmacy)"),
    ("Clinic", "عيادة (Clinic)"),
    ("Hospital", "مستشفى (Hospital)"),
    ("Polyclinic", "مجمع عيادات (Polyclinic)"),
    ("Center", "مركز طبي (Medical Center)"),
    ("Health Unit", "وحدة صحية (Health Unit)"),
    ("Dispensary", "مستوصف (Dispensary)"),
    ("Distributor", "موزع (Distributor)"),
    ("Store", "مخزن أدوية (Drug Store / Store)"),
    ("Physician", "طبيب (Physician)"),
    ("Pharmacist", "صيدلي (Pharmacist)"),
    ("Organization", "مؤسسة (Organization)"),
    ("Others", "أخرى (Others)"),
    # Lowercase aliases for backward compatibility with legacy tests and APIs
    ("pharmacy", "صيدلية (pharmacy)"),
    ("clinic", "عيادة (clinic)"),
    ("hospital", "مستشفى (hospital)"),
    ("polyclinic", "مجمع عيادات (polyclinic)"),
    ("distributor", "موزع (distributor)"),
    ("store", "مخزن (store)"),
    ("center", "مركز طبي (center)"),
    ("lab", "معمل تحاليل (lab)"),
]


class VisitTemplateForm(forms.ModelForm):
    restrict_account_types = forms.MultipleChoiceField(
        choices=ACCOUNT_TYPE_CHOICES,
        required=False,
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'rounded border-slate-300 text-teal-600 focus:ring-teal-500'}),
        label="نوع الحساب المستهدف"
    )

    class Meta:
        model = VisitTemplate
        fields = [
            'display_name_ar', 'display_name_en', 'name', 'active',
            'allow_unplanned',
            'enable_product_detailing', 'enable_double_visit_assessment_only',
            'has_special_location_settings', 'special_tolerance',
            'restrict_account_types', 'restricted_roles', 'suggested_products'
        ]
        widgets = {
            'display_name_ar': forms.TextInput(attrs={'class': 'w-full rounded-xl border border-slate-200 px-3 py-2 text-sm focus:border-brand-500 focus:ring-1 focus:ring-brand-500', 'placeholder': 'اسم القالب بالعربية...'}),
            'display_name_en': forms.TextInput(attrs={'class': 'w-full rounded-xl border border-slate-200 px-3 py-2 text-sm focus:border-brand-500 focus:ring-1 focus:ring-brand-500', 'placeholder': 'اسم القالب بالإنجليزية...'}),
            'name': forms.TextInput(attrs={'class': 'w-full rounded-xl border border-slate-200 px-3 py-2 text-sm focus:border-brand-500 focus:ring-1 focus:ring-brand-500', 'placeholder': 'المعرف الفريد (e.g. single_visit_dr)'}),
            'special_tolerance': forms.NumberInput(attrs={'class': 'w-full rounded-xl border border-slate-200 px-3 py-2 text-sm focus:border-brand-500 focus:ring-1 focus:ring-brand-500', 'min': 10}),
            'restricted_roles': forms.CheckboxSelectMultiple(attrs={'class': 'rounded border-slate-300 text-teal-600 focus:ring-teal-500'}),
            'suggested_products': forms.CheckboxSelectMultiple(attrs={'class': 'rounded border-slate-300 text-teal-600 focus:ring-teal-500'}),
            'active': forms.CheckboxInput(attrs={'class': 'w-4 h-4 rounded border-slate-300 text-teal-600 focus:ring-teal-500'}),
            'allow_unplanned': forms.CheckboxInput(attrs={'class': 'w-4 h-4 rounded border-slate-300 text-teal-600 focus:ring-teal-500'}),
            'enable_product_detailing': forms.CheckboxInput(attrs={'class': 'w-4 h-4 rounded border-slate-300 text-teal-600 focus:ring-teal-500'}),
            'enable_double_visit_assessment_only': forms.CheckboxInput(attrs={'class': 'w-4 h-4 rounded border-slate-300 text-teal-600 focus:ring-teal-500'}),
            'has_special_location_settings': forms.CheckboxInput(attrs={'class': 'w-4 h-4 rounded border-slate-300 text-teal-600 focus:ring-teal-500'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from catalog.models import Product
        from accounts.models import Role
        self.fields['suggested_products'].queryset = Product.get_eligible_for_visits()
        self.fields['suggested_products'].label = "المنتجات المقترحة لهذا القالب (صالحة للبيع فقط)"
        self.fields['restricted_roles'].queryset = Role.objects.filter(is_active=True).order_by('display_name', 'name')
        self.fields['restricted_roles'].required = False
        self.fields['restricted_roles'].label = "تقييد على أدوار المستخدمين"
        if self.instance and self.instance.pk:
            raw = self.instance.restrict_account_types
            if isinstance(raw, list):
                canonical_map = {k.lower(): k for k, _ in ACCOUNT_TYPE_CHOICES}
                canonical_initial = []
                for val in raw:
                    norm = str(val).strip().lower()
                    canonical_initial.append(canonical_map.get(norm, val))
                self.fields['restrict_account_types'].initial = canonical_initial

    def clean_restrict_account_types(self):
        val = self.cleaned_data.get('restrict_account_types')
        if isinstance(val, (list, tuple)):
            return list(val)
        return []

    def clean_name(self):
        name = self.cleaned_data.get('name', '').strip()
        if not name:
            name_en = self.cleaned_data.get('display_name_en', '').strip()
            name_ar = self.cleaned_data.get('display_name_ar', '').strip()
            name = (name_en or name_ar).lower().replace(' ', '_').replace('(', '').replace(')', '')
        return name


class VisitTemplateQuestionForm(forms.ModelForm):
    class Meta:
        model = VisitTemplateQuestion
        fields = [
            'text_ar', 'text_en', 'question_type', 'stage',
            'is_required', 'is_conditional', 'conditional_parent',
            'conditional_trigger_value', 'order', 'is_active'
        ]
        widgets = {
            'text_ar': forms.TextInput(attrs={'class': 'w-full rounded-xl border border-slate-200 px-3 py-2 text-sm focus:border-brand-500 focus:ring-1 focus:ring-brand-500', 'placeholder': 'نص السؤال بالعربية...'}),
            'text_en': forms.TextInput(attrs={'class': 'w-full rounded-xl border border-slate-200 px-3 py-2 text-sm focus:border-brand-500 focus:ring-1 focus:ring-brand-500', 'placeholder': 'نص السؤال بالإنجليزية (اختياري)...'}),
            'question_type': forms.Select(attrs={'class': 'w-full rounded-xl border border-slate-200 px-3 py-2 text-sm focus:border-brand-500 focus:ring-1 focus:ring-brand-500'}),
            'stage': forms.Select(attrs={'class': 'w-full rounded-xl border border-slate-200 px-3 py-2 text-sm focus:border-brand-500 focus:ring-1 focus:ring-brand-500'}),
            'conditional_parent': forms.Select(attrs={'class': 'w-full rounded-xl border border-slate-200 px-3 py-2 text-sm focus:border-brand-500 focus:ring-1 focus:ring-brand-500'}),
            'conditional_trigger_value': forms.TextInput(attrs={'class': 'w-full rounded-xl border border-slate-200 px-3 py-2 text-sm focus:border-brand-500 focus:ring-1 focus:ring-brand-500', 'placeholder': 'مثال: Yes أو نعم'}),
            'order': forms.NumberInput(attrs={'class': 'w-full rounded-xl border border-slate-200 px-3 py-2 text-sm focus:border-brand-500 focus:ring-1 focus:ring-brand-500', 'min': 1}),
            'is_required': forms.CheckboxInput(attrs={'class': 'w-4 h-4 rounded border-slate-300 text-teal-600 focus:ring-teal-500'}),
            'is_conditional': forms.CheckboxInput(attrs={'class': 'w-4 h-4 rounded border-slate-300 text-teal-600 focus:ring-teal-500'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'w-4 h-4 rounded border-slate-300 text-teal-600 focus:ring-teal-500'}),
        }

    def __init__(self, *args, template=None, **kwargs):
        super().__init__(*args, **kwargs)
        if template:
            # Filter parent question to single_choice or multiple_choice questions in same template
            qs = VisitTemplateQuestion.objects.filter(
                template=template,
                question_type__in=['single_choice', 'multiple_choice']
            )
            if self.instance and self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            self.fields['conditional_parent'].queryset = qs



