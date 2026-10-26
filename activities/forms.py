from django import forms
from .models import Agreement, Visit, PlannedVisitItem, VisitSampleItem, VisitTemplate, VisitTemplateQuestion
from contacts.models import Contact


class AgreementForm(forms.ModelForm):
    class Meta:
        model = Agreement
        fields = ['customer', 'title', 'type', 'amount', 'date', 'description']
        widgets = {
            'customer': forms.Select(attrs={'class': 'w-full rounded-xl border border-slate-200 px-3 py-2 text-sm focus:border-brand-500 focus:ring-1 focus:ring-brand-500'}),
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
            self.fields['customer'].queryset = scoped_qs.order_by('name') if scoped_qs.exists() else base_qs.order_by('name')


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

    def clean(self):
        cleaned_data = super().clean()
        contact = cleaned_data.get('contact')
        template = cleaned_data.get('template')
        if contact and template:
            if not template.is_contact_eligible(contact):
                allowed_str = ", ".join(template.restrict_account_types) if template.restrict_account_types else "الكل"
                raise forms.ValidationError(
                    f"قالب الزيارة '{template.display_name_ar}' غير مخصص لنوع حساب العميل ({contact.account_type or 'غير محدد'}). الأنواع المصرح بها: {allowed_str}."
                )
        return cleaned_data


from django.db.models import Q


class CustomerModelChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return obj.name


class VisitForm(forms.ModelForm):
    contact = CustomerModelChoiceField(
        queryset=Contact.objects.none(),
        widget=forms.Select(attrs={
            'id': 'visit-contact-select',
            'class': 'w-full rounded-xl border border-slate-200 px-3 py-2 text-xs font-bold text-slate-800 focus:border-[#27bebe] focus:ring-1 focus:ring-[#27bebe]',
            'onchange': 'onCustomerSelected(this.value)'
        }),
        label="جهة الاتصال (العميل) *"
    )
    latitude = forms.DecimalField(required=False, widget=forms.HiddenInput(attrs={'id': 'id_latitude'}))
    longitude = forms.DecimalField(required=False, widget=forms.HiddenInput(attrs={'id': 'id_longitude'}))
    device_accuracy = forms.DecimalField(required=False, widget=forms.HiddenInput(attrs={'id': 'id_device_accuracy'}))
    planned_item_id = forms.IntegerField(required=False, widget=forms.HiddenInput(attrs={'id': 'id_planned_item_id'}))
    location_photo = forms.ImageField(
        required=False,
        widget=forms.FileInput(attrs={
            'accept': 'image/*',
            'capture': 'environment',
            'id': 'id_location_photo',
            'class': 'hidden',
            'onchange': 'handleLocationPhotoSelected(event)'
        }),
        label="صورة إثبات الموقع"
    )

    class Meta:
        model = Visit
        fields = ['contact', 'template', 'owner', 'date', 'is_successful', 'doubled', 'feedback', 'latitude', 'longitude', 'device_accuracy', 'location_photo']
        widgets = {
            'template': forms.Select(attrs={'id': 'visit-template-select', 'class': 'w-full rounded-xl border border-slate-200 px-3 py-2 text-xs font-bold text-slate-800 focus:border-[#27bebe] focus:ring-1 focus:ring-[#27bebe]', 'onchange': 'onTemplateSelected(this.value)'}),
            'owner': forms.Select(attrs={'id': 'visit-owner-select', 'class': 'w-full rounded-xl border border-slate-200 px-3 py-2 text-xs font-bold text-slate-800 focus:border-[#27bebe] focus:ring-1 focus:ring-[#27bebe]'}),
            'date': forms.DateInput(attrs={'class': 'w-full rounded-xl border border-slate-200 px-3 py-2 text-xs font-bold text-slate-800 focus:border-[#27bebe] focus:ring-1 focus:ring-[#27bebe]', 'type': 'date'}),
            'is_successful': forms.CheckboxInput(attrs={'class': 'w-4 h-4 rounded border-slate-300 text-[#27bebe] focus:ring-[#27bebe]'}),
            'doubled': forms.CheckboxInput(attrs={'class': 'w-4 h-4 rounded border-slate-300 text-[#27bebe] focus:ring-[#27bebe]'}),
            'feedback': forms.Textarea(attrs={'class': 'w-full rounded-xl border border-slate-200 px-3 py-2 text-xs text-slate-800 focus:border-[#27bebe] focus:ring-1 focus:ring-[#27bebe]', 'rows': 4, 'placeholder': 'ملاحظات ونتائج الزيارة...'}),
        }

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        base_qs = Contact.objects.filter(
            Q(is_customer=True) | Q(status='customer') | Q(account_type__gt='')
        ).exclude(status='inactive')

        from django.contrib.auth import get_user_model
        UserModel = get_user_model()

        if user:
            from accounts.permissions import is_manager_or_higher, get_scoped_queryset
            is_manager = is_manager_or_higher(user)
            self.is_manager = is_manager

            # Territorial and regional scoping matching user's assigned area
            scoped_qs = get_scoped_queryset(base_qs, user, 'contact')
            self.fields['contact'].queryset = scoped_qs.order_by('name') if scoped_qs.exists() else base_qs.order_by('name')

            if not is_manager:
                # Lock representative assignment to current user
                self.fields['owner'].queryset = UserModel.objects.filter(pk=user.pk)
                self.fields['owner'].initial = user
                self.fields['owner'].disabled = True
            else:
                self.fields['owner'].queryset = UserModel.objects.filter(is_active=True).order_by('first_name', 'username')
                self.fields['owner'].initial = user
                self.fields['owner'].required = False
        else:
            self.is_manager = False
            self.fields['contact'].queryset = base_qs.order_by('name')

    def clean(self):
        cleaned_data = super().clean()
        user = self.user

        # Business Rule (Requirement 6): Non-superusers cannot change assigned representative
        is_manager = getattr(self, 'is_manager', False)
        if not is_manager and user and user.is_authenticated:
            cleaned_data['owner'] = user
        elif not cleaned_data.get('owner') and user and user.is_authenticated:
            cleaned_data['owner'] = user

        # Business Rule (Requirement 1 & 2): Centralized Account-Type & Role Eligibility Validation
        contact = cleaned_data.get('contact')
        template = cleaned_data.get('template')
        if template:
            if user and not template.is_user_eligible(user):
                raise forms.ValidationError(
                    f"دورك الوظيفي غير مصرح له باستخدام قالب الزيارة '{template.display_name_ar}'."
                )
            if contact and not template.is_contact_eligible(contact, user=user):
                allowed_str = ", ".join(template.restrict_account_types) if template.restrict_account_types else "الكل"
                raise forms.ValidationError(
                    f"قالب الزيارة '{template.display_name_ar}' غير مخصص لنوع حساب العميل ({contact.account_type or 'غير محدد'}). الأنواع المصرح بها: {allowed_str}."
                )

        # Planned Visit Item Backend Validation (Requirement 3)
        planned_item_id = self.data.get('planned_item_id') or cleaned_data.get('planned_item_id')
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

        # Enforce server-side GPS requirement for representative users when verify_visits is active
        from master_data.models import LocationSettings
        settings = LocationSettings.get_settings()
        can_bypass = False
        if user and user.is_authenticated:
            can_bypass = bool(
                user.is_superuser or
                getattr(user, 'is_super_admin', False) or
                getattr(user, 'can_bypass_location', False)
            )

        if settings.verify_visits and not can_bypass:
            lat = cleaned_data.get('latitude') or self.data.get('latitude')
            lng = cleaned_data.get('longitude') or self.data.get('longitude')
            if lat is None or lng is None or str(lat).strip() == '' or str(lng).strip() == '':
                raise forms.ValidationError(
                    "تحديد الموقع الجغرافي (GPS) إلزامي للمندوب لتسجيل الزيارة. يرجى تفعيل إذن الموقع في المتصفح والمحاولة مجدداً."
                )
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
            'mode', 'allow_unplanned', 'auto_approve_unplanned',
            'enable_product_detailing', 'enable_double_visit_assessment_only',
            'visit_outcome_mode', 'auto_end_visit',
            'has_special_location_settings', 'special_tolerance',
            'restrict_account_types', 'restricted_roles', 'suggested_products'
        ]
        widgets = {
            'display_name_ar': forms.TextInput(attrs={'class': 'w-full rounded-xl border border-slate-200 px-3 py-2 text-sm focus:border-brand-500 focus:ring-1 focus:ring-brand-500', 'placeholder': 'اسم القالب بالعربية...'}),
            'display_name_en': forms.TextInput(attrs={'class': 'w-full rounded-xl border border-slate-200 px-3 py-2 text-sm focus:border-brand-500 focus:ring-1 focus:ring-brand-500', 'placeholder': 'اسم القالب بالإنجليزية...'}),
            'name': forms.TextInput(attrs={'class': 'w-full rounded-xl border border-slate-200 px-3 py-2 text-sm focus:border-brand-500 focus:ring-1 focus:ring-brand-500', 'placeholder': 'المعرف الفريد (e.g. single_visit_dr)'}),
            'mode': forms.Select(attrs={'class': 'w-full rounded-xl border border-slate-200 px-3 py-2 text-sm focus:border-brand-500 focus:ring-1 focus:ring-brand-500'}),
            'visit_outcome_mode': forms.Select(attrs={'class': 'w-full rounded-xl border border-slate-200 px-3 py-2 text-sm focus:border-brand-500 focus:ring-1 focus:ring-brand-500'}),
            'special_tolerance': forms.NumberInput(attrs={'class': 'w-full rounded-xl border border-slate-200 px-3 py-2 text-sm focus:border-brand-500 focus:ring-1 focus:ring-brand-500', 'min': 10}),
            'restricted_roles': forms.SelectMultiple(attrs={'class': 'w-full rounded-xl border border-slate-200 px-3 py-2 text-sm focus:border-brand-500 focus:ring-1 focus:ring-brand-500'}),
            'suggested_products': forms.CheckboxSelectMultiple(attrs={'class': 'rounded border-slate-300 text-teal-600 focus:ring-teal-500'}),
            'active': forms.CheckboxInput(attrs={'class': 'w-4 h-4 rounded border-slate-300 text-teal-600 focus:ring-teal-500'}),
            'allow_unplanned': forms.CheckboxInput(attrs={'class': 'w-4 h-4 rounded border-slate-300 text-teal-600 focus:ring-teal-500'}),
            'auto_approve_unplanned': forms.CheckboxInput(attrs={'class': 'w-4 h-4 rounded border-slate-300 text-teal-600 focus:ring-teal-500'}),
            'enable_product_detailing': forms.CheckboxInput(attrs={'class': 'w-4 h-4 rounded border-slate-300 text-teal-600 focus:ring-teal-500'}),
            'enable_double_visit_assessment_only': forms.CheckboxInput(attrs={'class': 'w-4 h-4 rounded border-slate-300 text-teal-600 focus:ring-teal-500'}),
            'auto_end_visit': forms.CheckboxInput(attrs={'class': 'w-4 h-4 rounded border-slate-300 text-teal-600 focus:ring-teal-500'}),
            'has_special_location_settings': forms.CheckboxInput(attrs={'class': 'w-4 h-4 rounded border-slate-300 text-teal-600 focus:ring-teal-500'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from catalog.models import Product
        self.fields['suggested_products'].queryset = Product.get_eligible_for_visits()
        self.fields['suggested_products'].label = "المنتجات المقترحة لهذا القالب (صالحة للبيع فقط)"
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



