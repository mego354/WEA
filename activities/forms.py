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


from django.db.models import Q


class CustomerModelChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        if obj.code:
            return f"[{obj.code}] {obj.name}"
        return f"[#{obj.serial_num}] {obj.name}"


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

    class Meta:
        model = Visit
        fields = ['contact', 'template', 'owner', 'date', 'is_successful', 'doubled', 'feedback', 'latitude', 'longitude', 'device_accuracy']
        widgets = {
            'template': forms.Select(attrs={'id': 'visit-template-select', 'class': 'w-full rounded-xl border border-slate-200 px-3 py-2 text-xs font-bold text-slate-800 focus:border-[#27bebe] focus:ring-1 focus:ring-[#27bebe]', 'onchange': 'onTemplateSelected(this.value)'}),
            'owner': forms.Select(attrs={'class': 'w-full rounded-xl border border-slate-200 px-3 py-2 text-xs font-bold text-slate-800 focus:border-[#27bebe] focus:ring-1 focus:ring-[#27bebe]'}),
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

        if user:
            is_manager = (
                user.is_superuser or
                getattr(user, 'is_super_admin', False) or
                (user.role and (
                    user.role.is_area_manager or
                    any(t in (user.role.name or '').lower() for t in ['manager', 'admin', 'supervisor', 'director']) or
                    any(t in (user.role.display_name or '').lower() for t in ['مدير', 'مشرف'])
                ))
            )
            if not is_manager:
                scoped_qs = base_qs.filter(Q(assigned_team=user) | Q(created_by=user)).distinct()
                self.fields['contact'].queryset = scoped_qs if scoped_qs.exists() else base_qs.order_by('name')
            else:
                self.fields['contact'].queryset = base_qs.order_by('name')
        else:
            self.fields['contact'].queryset = base_qs.order_by('name')

    def clean(self):
        cleaned_data = super().clean()
        lat = cleaned_data.get('latitude')
        lng = cleaned_data.get('longitude')

        from master_data.models import LocationSettings
        settings = LocationSettings.get_settings()

        user = self.user
        can_bypass = False
        if user and user.is_authenticated:
            can_bypass = bool(
                user.is_superuser or
                getattr(user, 'is_super_admin', False) or
                getattr(user, 'can_bypass_location', False)
            )

        # Enforce server-side GPS requirement for representative users when verify_visits is active
        if settings.verify_visits and not can_bypass:
            if lat is None or lng is None:
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
    ('clinic', 'عيادة (Clinic)'),
    ('hospital', 'مستشفى (Hospital)'),
    ('pharmacy', 'صيدلية (Pharmacy)'),
    ('polyclinic', 'مجمع عيادات (Polyclinic)'),
    ('distributor', 'موزع (Distributor)'),
    ('store', 'مخزن (Store)'),
    ('center', 'مركز طبي (Medical Center)'),
    ('lab', 'معمل تحاليل (Lab)'),
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
            'restrict_account_types', 'restricted_roles'
        ]
        widgets = {
            'display_name_ar': forms.TextInput(attrs={'class': 'w-full rounded-xl border border-slate-200 px-3 py-2 text-sm focus:border-brand-500 focus:ring-1 focus:ring-brand-500', 'placeholder': 'اسم القالب بالعربية...'}),
            'display_name_en': forms.TextInput(attrs={'class': 'w-full rounded-xl border border-slate-200 px-3 py-2 text-sm focus:border-brand-500 focus:ring-1 focus:ring-brand-500', 'placeholder': 'اسم القالب بالإنجليزية...'}),
            'name': forms.TextInput(attrs={'class': 'w-full rounded-xl border border-slate-200 px-3 py-2 text-sm focus:border-brand-500 focus:ring-1 focus:ring-brand-500', 'placeholder': 'المعرف الفريد (e.g. single_visit_dr)'}),
            'mode': forms.Select(attrs={'class': 'w-full rounded-xl border border-slate-200 px-3 py-2 text-sm focus:border-brand-500 focus:ring-1 focus:ring-brand-500'}),
            'visit_outcome_mode': forms.Select(attrs={'class': 'w-full rounded-xl border border-slate-200 px-3 py-2 text-sm focus:border-brand-500 focus:ring-1 focus:ring-brand-500'}),
            'special_tolerance': forms.NumberInput(attrs={'class': 'w-full rounded-xl border border-slate-200 px-3 py-2 text-sm focus:border-brand-500 focus:ring-1 focus:ring-brand-500', 'min': 10}),
            'restricted_roles': forms.SelectMultiple(attrs={'class': 'w-full rounded-xl border border-slate-200 px-3 py-2 text-sm focus:border-brand-500 focus:ring-1 focus:ring-brand-500'}),
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
        if self.instance and self.instance.pk:
            if isinstance(self.instance.restrict_account_types, list):
                self.fields['restrict_account_types'].initial = self.instance.restrict_account_types

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



