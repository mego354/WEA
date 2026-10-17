from django import forms
from .models import Agreement, Visit, PlannedVisitItem, VisitSampleItem
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
            'template': forms.Select(attrs={'id': 'visit-template-select', 'class': 'w-full rounded-xl border border-slate-200 px-3 py-2 text-xs font-bold text-slate-800 focus:border-[#27bebe] focus:ring-1 focus:ring-[#27bebe]'}),
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


