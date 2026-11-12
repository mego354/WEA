from django import forms
from django.utils import timezone
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
            'contact': forms.Select(attrs={'id': 'visit-contact-select', 'class': 'w-full rounded-xl border border-slate-200 px-3 py-2 text-xs font-bold text-slate-800 focus:border-[#27bebe] focus:ring-1 focus:ring-[#27bebe]'}),
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
            from accounts.permissions import (
                is_manager_or_higher,
                get_visit_eligible_contacts_queryset,
                get_user_managed_representatives,
            )
            is_manager = is_manager_or_higher(user)
            self.is_manager = is_manager

            # Strictly scope available contacts to user's permitted geographical scope (Superadmin -> all, Manager -> Main Area, Rep -> Brick)
            scoped_qs = get_visit_eligible_contacts_queryset(base_qs, user)
            if self.instance and self.instance.pk and self.instance.contact_id:
                scoped_ids = list(scoped_qs.values_list('pk', flat=True))
                scoped_qs = Contact.objects.filter(pk__in=scoped_ids + [self.instance.contact_id])
            self.fields['contact'].queryset = scoped_qs.order_by('name')

            self.fields['owner'].required = False
            if not is_manager:
                # Lock representative assignment on create; preserve existing owner on edit
                locked_owner = self.instance.owner if (self.instance and self.instance.pk and self.instance.owner_id) else user
                self.fields['owner'].queryset = UserModel.objects.filter(pk=locked_owner.pk)
                self.fields['owner'].initial = locked_owner
                self.fields['owner'].disabled = True
            else:
                managed_reps = get_user_managed_representatives(user)
                managed_rep_ids = list(managed_reps.values_list('pk', flat=True))
                allowed_owner_ids = set(managed_rep_ids) | {user.pk}
                if self.instance and self.instance.pk and self.instance.owner_id:
                    allowed_owner_ids.add(self.instance.owner_id)
                self.fields['owner'].queryset = UserModel.objects.filter(pk__in=allowed_owner_ids).order_by('first_name', 'username')
                self.fields['owner'].initial = self.instance.owner if (self.instance and self.instance.pk and self.instance.owner_id) else user
        else:
            self.is_manager = False
            self.fields['contact'].queryset = base_qs.order_by('name')
            self.fields['owner'].required = False

        # Scope templates to active templates eligible for user's role
        templates_qs = VisitTemplate.objects.filter(active=True).prefetch_related('restricted_roles')
        eligible_template_ids = [t.id for t in templates_qs if t.is_user_eligible(user)]
        if self.instance and self.instance.pk and self.instance.template_id:
            eligible_template_ids.append(self.instance.template_id)
        self.fields['template'].queryset = VisitTemplate.objects.filter(id__in=eligible_template_ids).order_by('name')
        self.fields['template'].required = True
        self.fields['template'].empty_label = "-- اختر قالب الزيارة (إلزامي) --"

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

        # Date Validation (Requirement 4): All visit dates must be today or a future date
        visit_date = cleaned_data.get('date')
        if visit_date:
            today = timezone.now().date()
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

        if not is_editing and not is_planned_visit and settings.verify_visits and settings.verify_unplanned_visit_distance:
            can_bypass_directly = settings.can_user_bypass_without_approval(user, stage='create')
            force_bypass = str(self.data.get('force_bypass_location', '')).strip().lower() in ('1', 'true', 'on')
            request_exception = str(self.data.get('request_distance_exception', '')).strip().lower() in ('1', 'true', 'on')
            bypass_reason = (self.data.get('bypass_reason') or '').strip()

            if not has_coords:
                if not can_bypass_directly and not (force_bypass or request_exception):
                    raise forms.ValidationError(
                        "تحديد الموقع الجغرافي (GPS) إلزامي للمندوب لتسجيل الزيارة. يرجى تفعيل إذن الموقع في المتصفح والمحاولة مجدداً."
                    )
                if not can_bypass_directly and (force_bypass or request_exception) and not bypass_reason:
                    raise forms.ValidationError(
                        "يرجى توضيح سبب عدم توفر الموقع أو التواجد خارج المسافة المسموح بها لطلب استثناء واعتماد المدير."
                    )
                if can_bypass_directly and force_bypass and settings.bypass_reason_mandatory and not bypass_reason:
                    raise forms.ValidationError(
                        "يرجى إدخال سبب تجاوز التحقق من المسافة (ذكر السبب إلزامي حسب إعدادات النظام)."
                    )
            elif contact and contact.latitude is not None and contact.longitude is not None:
                allowed_dist = settings.get_effective_tolerance(template)
                dist = calculate_haversine_distance(lat_float, lng_float, float(contact.latitude), float(contact.longitude))
                if dist is not None and dist > allowed_dist:
                    if can_bypass_directly:
                        is_super = bool(user and (user.is_superuser or getattr(user, 'is_super_admin', False)))
                        if settings.bypass_reason_mandatory and (force_bypass or not is_super) and not bypass_reason:
                            raise forms.ValidationError(
                                f"المسافة الحالية ({dist:.0f} متر) تتجاوز المسافة المسموح بها ({allowed_dist} متر). يرجى إدخال سبب التجاوز للمتابعة."
                            )
                    else:
                        if not (force_bypass or request_exception):
                            raise forms.ValidationError(
                                f"أنت خارج النطاق الجغرافي المسموح به للعميل (المسافة الفعلية: {dist:.0f} متر، المسافة المسموح بها: {allowed_dist} متر). "
                                "يرجى التواجد ضمن النطاق المسموح أو طلب استثناء مع كتابة السبب لاعتماد المدير."
                            )
                        if not bypass_reason:
                            raise forms.ValidationError(
                                "يرجى كتابة سبب واضح للتواجد خارج المسافة المسموح بها لتقديم طلب استثناء لاعتماد المدير."
                            )

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



