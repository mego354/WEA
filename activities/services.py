import os
import uuid
import math
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.utils import timezone
from PIL import Image
from master_data.models import LocationSettings


def calculate_haversine_distance(lat1, lon1, lat2, lon2):
    """
    Calculate Haversine distance in meters between two GPS coordinates (lat1, lon1) and (lat2, lon2).
    Returns float distance in meters.
    """
    if lat1 is None or lon1 is None or lat2 is None or lon2 is None:
        return None

    try:
        lat1 = float(str(lat1).replace(',', '.'))
        lon1 = float(str(lon1).replace(',', '.'))
        lat2 = float(str(lat2).replace(',', '.'))
        lon2 = float(str(lon2).replace(',', '.'))
    except (ValueError, TypeError):
        return None

    R = 6371000.0  # Earth radius in meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (math.sin(delta_phi / 2.0) ** 2 +
         math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2)
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return R * c


def verify_visit_location(visit, user, contact, visit_lat=None, visit_lng=None, device_accuracy=None,
                          photo_file=None, force_bypass=False, bypass_reason='',
                          stage='start', strict_distance=False, **kwargs):
    """
    Applies the ERP location and distance verification policy across visit execution (start & end):
    1. Dynamically determines allowed distance threshold:
       - Uses template's special_tolerance if allow_template_distance_override is enabled and configured on template.
       - Otherwise uses default LocationSettings.tolerance.
    2. Compares user's current GPS coordinates against client's registered coordinates.
    3. Records actual distance, allowed threshold, and distance discrepancy on the visit.
    4. Handles authorized bypass (users with activities:visits/bypass_gps / Superadmin):
       - Bypassing distance will NOT make the visit need an approval (approval_status is untouched).
    5. Unauthorized users outside distance threshold cannot start or end the visit.
    """
    settings = LocationSettings.get_settings()
    template = getattr(visit, 'template', None)
    tolerance = settings.get_effective_tolerance(template)
    visit.allowed_distance = Decimal(str(round(float(tolerance), 2)))

    can_bypass_directly = settings.can_user_bypass_without_approval(user, stage=stage)
    is_super = bool(getattr(user, 'is_superuser', False) or getattr(user, 'is_super_admin', False))
    bypass_reason_clean = (bypass_reason or '').strip()

    # Security check: unauthorized users must never force-bypass directly
    if force_bypass and not can_bypass_directly:
        raise ValidationError("عذراً، لا تملك صلاحية تجاوز التحقق الجغرافي (GPS).")

    # Convert and validate coordinates if passed
    if visit_lat is not None and visit_lng is not None and str(visit_lat).strip() != '' and str(visit_lng).strip() != '':
        try:
            lat_str = str(visit_lat).strip().replace(',', '.')
            lng_str = str(visit_lng).strip().replace(',', '.')
            lat_f = float(lat_str)
            lng_f = float(lng_str)
            if not (-90.0 <= lat_f <= 90.0 and -180.0 <= lng_f <= 180.0):
                raise ValidationError("إحداثيات الموقع الجغرافي غير صالحة.")
            if lat_f == 0.0 and lng_f == 0.0:
                raise ValidationError("إحداثيات الموقع الجغرافي غير صالحة (0, 0).")
            visit.latitude = Decimal(lat_str)
            visit.longitude = Decimal(lng_str)
        except ValidationError:
            raise
        except Exception:
            if strict_distance:
                raise ValidationError("صيغة إحداثيات الموقع غير صالحة.")

    if device_accuracy is not None and str(device_accuracy).strip() != '':
        try:
            visit.device_accuracy = Decimal(str(device_accuracy))
        except Exception:
            pass

    customer_lat = getattr(contact, 'latitude', None)
    customer_lng = getattr(contact, 'longitude', None)

    visit.customer_latitude_snapshot = customer_lat
    visit.customer_longitude_snapshot = customer_lng

    # Always compute actual distance and discrepancy whenever both sets of coordinates exist
    dist = None
    if visit.latitude is not None and visit.longitude is not None and customer_lat is not None and customer_lng is not None:
        dist = calculate_haversine_distance(visit.latitude, visit.longitude, customer_lat, customer_lng)
        if dist is not None:
            visit.distance = Decimal(str(round(dist, 2)))
            visit.distance_discrepancy = max(Decimal('0.00'), visit.distance - visit.allowed_distance)

    # Non-blocking server-side GPS integrity evaluation (never alters distance rules or blocks workflow)
    from activities.gps_integrity import evaluate_visit_gps_integrity
    evaluate_visit_gps_integrity(
        visit,
        user,
        contact,
        stage=stage,
        client_telemetry=kwargs.get('client_telemetry'),
    )

    # If user is strictly within effective distance tolerance, no bypass is needed or recorded
    if dist is not None and dist <= tolerance:
        visit.location_verified = True
        visit.verification_status = 'verified'
        visit.location_status = 'ضمن النطاق المحدد'
        visit.distance_discrepancy = Decimal('0.00')
        return visit

    # Handle explicit bypass:
    # All users who have activities:visits/bypass_gps (or superadmin) can ignore distance.
    # Bypassing distance will NOT make the visit need an approval.
    if force_bypass:
        if not can_bypass_directly:
            raise ValidationError("عذراً، لا تملك صلاحية تجاوز التحقق الجغرافي (GPS).")
        if settings.bypass_reason_mandatory and not is_super and not bypass_reason_clean:
            raise ValidationError("يرجى إدخال سبب تجاوز المسافة المسموح بها (ذكر السبب إلزامي حسب إعدادات النظام).")
        visit.location_verified = True
        visit.verification_status = 'force_bypassed'
        if dist is not None and dist > tolerance:
            visit.location_status = 'بعيد جدا عن الموقع المحدد (تم التجاوز بصلاحية إدارية)'
        else:
            visit.location_status = 'تم تجاهل التحقق بالقوة بواسطة المشرف'
        visit.bypassed_by = user
        visit.bypassed_at = timezone.now()
        visit.bypass_reason = bypass_reason_clean or 'تجاوز مصرح به (صلاحية تجاوز GPS)'
        if stage == 'start':
            visit.gps_forced_start = True
            visit.gps_forced_start_by = user
            visit.gps_forced_start_at = timezone.now()
        elif stage == 'end':
            visit.gps_forced_end = True
            visit.gps_forced_end_by = user
            visit.gps_forced_end_at = timezone.now()
        visit.requires_approval_due_to_distance = False
        return visit

    # Check if verification is active for this stage
    stage_verify_enabled = settings.verify_visits
    if stage == 'end' and not settings.verify_end_visit_distance:
        stage_verify_enabled = False

    if not stage_verify_enabled:
        if dist is not None:
            if dist <= tolerance:
                visit.location_verified = True
                visit.verification_status = 'verified'
                visit.location_status = 'ضمن النطاق المحدد'
            else:
                visit.location_verified = False
                visit.verification_status = 'unverified'
                visit.location_status = 'التحقق معطل في الإعدادات العامة'
        else:
            visit.location_verified = True
            visit.verification_status = 'verified'
            visit.location_status = 'التحقق معطل في الإعدادات العامة'
        return visit

    # Case 1: Device location unavailable
    if visit.latitude is None or visit.longitude is None:
        if can_bypass_directly:
            if settings.bypass_reason_mandatory and not is_super and not bypass_reason_clean:
                raise ValidationError("تعذر تحديد موقع الجهاز، يرجى إدخال سبب التجاوز للمتابعة.")
            visit.location_verified = True
            visit.verification_status = 'force_bypassed'
            visit.location_status = 'تم تجاهل التحقق بالقوة - تعذر تحديد موقع الجهاز'
            visit.bypassed_by = user
            visit.bypassed_at = timezone.now()
            visit.bypass_reason = bypass_reason_clean or 'تعذر تحديد موقع الجهاز'
            if stage == 'start':
                visit.gps_forced_start = True
                visit.gps_forced_start_by = user
                visit.gps_forced_start_at = timezone.now()
            elif stage == 'end':
                visit.gps_forced_end = True
                visit.gps_forced_end_by = user
                visit.gps_forced_end_at = timezone.now()
            visit.requires_approval_due_to_distance = False
            return visit
        else:
            visit.location_verified = False
            visit.verification_status = 'unverified'
            visit.location_status = 'تعذر تحديد موقع الجهاز'
            if strict_distance:
                raise ValidationError("تحديد الموقع الجغرافي (GPS) إلزامي للتحقق من المسافة.")
            return visit

    # Case 2: Customer has saved GPS coordinates
    if customer_lat is not None and customer_lng is not None:
        if dist is not None:
            if dist <= tolerance:
                visit.location_verified = True
                visit.verification_status = 'verified'
                visit.location_status = 'ضمن النطاق المحدد'
                visit.distance_discrepancy = Decimal('0.00')
            else:
                visit.location_verified = False
                visit.verification_status = 'unverified'
                visit.location_status = 'بعيد جدا عن الموقع المحدد'
                if strict_distance:
                    raise ValidationError(
                        f"أنت خارج النطاق الجغرافي المسموح به للعميل (المسافة الحالية: {visit.distance} متر، المسافة المسموح بها: {tolerance} متر)."
                    )
        return visit

    # Case 3: Customer has NO saved GPS coordinates
    if settings.auto_set_customer_location_in_visit and visit.latitude is not None and visit.longitude is not None:
        # Auto-set customer's location from this first visit
        contact.set_location(visit.latitude, visit.longitude)
        visit.customer_latitude_snapshot = visit.latitude
        visit.customer_longitude_snapshot = visit.longitude
        visit.distance = Decimal('0.00')
        visit.distance_discrepancy = Decimal('0.00')
        visit.location_verified = True
        visit.verification_status = 'verified'
        visit.location_status = 'تم حفظ موقع العميل بشكل تلقائي مع أول زيارة'
        return visit
    else:
        visit.location_verified = False
        visit.verification_status = 'unverified'
        visit.location_status = 'لا يوجد موقع مسجل للعميل'
        return visit


def get_question_product_choices(template, visit=None, question=None):
    """
    Returns (combined_products_qs, historical_ids_set, suggested_ids_set) for a
    `suggested_products` template question or legacy `detailed_products` picker.
    Always includes eligible active+sellable products plus any historically saved
    IDs on the visit so historical non-sellable/inactive products remain intact.
    """
    from django.db.models import Case, When, Value, IntegerField
    from catalog.models import Product

    eligible_qs = template.get_suggested_products_pool() if template else Product.get_eligible_for_visits()
    eligible_ids = set(eligible_qs.values_list('id', flat=True))

    suggested_ids = set()
    if template:
        suggested_ids.update(template.get_eligible_suggested_products().values_list('id', flat=True))
    loc_settings = LocationSettings.get_settings()
    if getattr(loc_settings, 'enable_product_suggestions', False):
        suggested_ids.update(loc_settings.get_eligible_suggested_products().values_list('id', flat=True))

    historical_ids = set()
    if visit and getattr(visit, 'pk', None):
        if question is not None:
            raw_ans = (visit.questionnaire_answers or {}).get(str(question.id))
            items = raw_ans if isinstance(raw_ans, (list, tuple)) else ([raw_ans] if raw_ans not in (None, '') else [])
            for item in items:
                s = str(item).strip()
                if s.isdigit():
                    historical_ids.add(int(s))
        else:
            historical_ids = set(visit.detailed_products.values_list('id', flat=True))

    allowed_ids = eligible_ids | historical_ids
    if not allowed_ids:
        return Product.objects.none(), historical_ids, suggested_ids

    combined_qs = Product.objects.filter(id__in=allowed_ids)
    if suggested_ids:
        combined_qs = combined_qs.annotate(
            _is_suggested=Case(
                When(id__in=suggested_ids, then=Value(0)),
                default=Value(1),
                output_field=IntegerField(),
            )
        ).order_by('_is_suggested', 'name')
    else:
        combined_qs = combined_qs.order_by('name')
    return combined_qs, historical_ids, suggested_ids


def parse_suggested_products_submission(post_data, field_name, allowed_ids, strict=True):
    """
    Parses and validates product IDs submitted for a `suggested_products` question
    or `detailed_products` field against `allowed_ids`.
    When strict=True, raises ValidationError on any invalid or unauthorized product ID.
    """
    if hasattr(post_data, 'getlist'):
        raw_vals = post_data.getlist(field_name)
    else:
        raw_v = post_data.get(field_name)
        if raw_v is None:
            raw_vals = []
        elif isinstance(raw_v, (list, tuple)):
            raw_vals = list(raw_v)
        else:
            raw_vals = [raw_v]

    tokens = []
    for v in raw_vals:
        if isinstance(v, (list, tuple)):
            tokens.extend(v)
        elif isinstance(v, str) and ',' in v:
            tokens.extend(part for part in v.split(','))
        else:
            tokens.append(v)

    selected_ids = []
    seen = set()
    for tok in tokens:
        s = str(tok).strip()
        if not s:
            continue
        if not s.isdigit() or int(s) <= 0:
            if strict:
                raise ValidationError("تم اختيار منتج غير صالح أو غير مصرح به لهذا القالب.")
            continue
        pid = int(s)
        if pid not in allowed_ids:
            if strict:
                raise ValidationError("تم اختيار منتج غير صالح أو غير مصرح به لهذا القالب.")
            continue
        if pid not in seen:
            seen.add(pid)
            selected_ids.append(pid)
    return selected_ids


def preload_visit_qa_product_map(visits):
    """
    Batch-loads all Product names referenced in `suggested_products` questionnaire
    answers across `visits` in a single ORM query and caches `_qa_product_map` &
    `qa_display_list` on each Visit instance (eliminating N+1 queries in lists/exports).
    """
    from catalog.models import Product

    visit_list = list(visits)
    needed_pids = set()
    for v in visit_list:
        answers = getattr(v, 'questionnaire_answers', None) or {}
        if not answers or not getattr(v, 'template_id', None):
            continue
        sp_qids = {str(q.id) for q in v.template.questions.all() if q.question_type == 'suggested_products'}
        for qid_str in sp_qids:
            val = answers.get(qid_str)
            if val in (None, '', []):
                continue
            items = val if isinstance(val, (list, tuple)) else [val]
            for item in items:
                s = str(item).strip()
                if s.isdigit():
                    needed_pids.add(int(s))

    prod_map = {}
    if needed_pids:
        prod_map = dict(Product.objects.filter(id__in=needed_pids).values_list('id', 'name'))

    for v in visit_list:
        v._qa_product_map = prod_map
        v.qa_display_list = v.get_qa_display_list(product_map=prod_map)
    return prod_map


def format_answer_for_display(question, raw_val, product_map=None):
    """
    Unified formatter converting raw answer values (scalar, multi-choice, or
    suggested_products IDs) into human-readable Arabic display text.
    Returns '' for empty values so callers can apply context-appropriate placeholders.
    """
    from activities.models import Visit

    if raw_val is None or raw_val == '' or raw_val == []:
        return ''

    q_type = getattr(question, 'question_type', '') if question else ''
    if q_type == 'suggested_products':
        items = raw_val if isinstance(raw_val, (list, tuple)) else [raw_val]
        pmap = dict(product_map) if product_map else {}
        missing = [int(str(x).strip()) for x in items if str(x).strip().isdigit() and int(str(x).strip()) not in pmap]
        if missing:
            from catalog.models import Product
            pmap.update(dict(Product.objects.filter(id__in=missing).values_list('id', 'name')))
        names = []
        for item in items:
            s = str(item).strip()
            if s.isdigit():
                pid = int(s)
                names.append(pmap.get(pid, f"منتج #{pid}"))
            elif item not in (None, ''):
                names.append(str(item))
        return '، '.join(names)

    q_lookup = {}
    opts = getattr(question, 'options', None) if question else None
    if isinstance(opts, list):
        for opt in opts:
            if isinstance(opt, dict):
                vk = str(opt.get('value', '')).strip()
                if vk:
                    q_lookup[vk.lower()] = opt.get('text_ar') or opt.get('text_en') or vk

    if isinstance(raw_val, (list, tuple)):
        cleaned = [Visit.translate_answer_value(x, q_lookup) for x in raw_val if x not in (None, '')]
        return '، '.join(cleaned)
    return Visit.translate_answer_value(raw_val, q_lookup)


def can_edit_agreement(user, agreement):
    """Checks permission, data scope, and editable business status ('new' or 'disapproved')."""
    from accounts.permissions import has_perm_or_admin, can_user_access_object

    if not user or not getattr(user, 'is_authenticated', False):
        return False, "يجب تسجيل الدخول لتعديل الاتفاقية."
    if not has_perm_or_admin(user, 'activities:agreements/edit'):
        return False, "عذراً، لا تملك صلاحية تعديل الاتفاقيات."
    if agreement.status not in ('new', 'disapproved'):
        return False, "لا يمكن تعديل الاتفاقية بعد إنجازها أو اعتمادها."
    if not can_user_access_object(user, agreement, 'edit'):
        return False, "غير مصرح لك بتعديل هذه الاتفاقية خارج نطاق صلاحياتك."
    return True, ""


def can_delete_agreement(user, agreement):
    """Checks permission, data scope, and deletable business status ('new' or 'disapproved')."""
    from accounts.permissions import has_perm_or_admin, can_user_access_object

    if not user or not getattr(user, 'is_authenticated', False):
        return False, "يجب تسجيل الدخول لحذف الاتفاقية."
    if not has_perm_or_admin(user, 'activities:agreements/delete'):
        return False, "عذراً، لا تملك صلاحية حذف الاتفاقيات."
    if agreement.status not in ('new', 'disapproved'):
        return False, "لا يمكن حذف الاتفاقية بعد إنجازها أو اعتمادها."
    if not can_user_access_object(user, agreement, 'delete'):
        return False, "غير مصرح لك بحذف هذه الاتفاقية خارج نطاق صلاحياتك."
    return True, ""


# =============================================================================
# STANDARDIZED VISIT LIFECYCLE SERVICE FUNCTIONS (STATE MACHINE)
# =============================================================================

def get_open_visit_for_owner(owner_or_id, exclude_visit_id=None):
    """
    Returns an active open visit (status='started', ended_at IS NULL) owned by `owner_or_id`,
    or None if no open visit exists. Applies strictly per `visit.owner`.
    """
    from activities.models import Visit
    owner_id = getattr(owner_or_id, 'pk', owner_or_id)
    if not owner_id:
        return None
    qs = Visit.objects.filter(
        owner_id=owner_id, status='started', ended_at__isnull=True
    ).select_related('contact')
    if exclude_visit_id:
        qs = qs.exclude(pk=exclude_visit_id)
    return qs.first()


def extract_checkin_answers_from_post(post_data, template):
    """
    Extracts check-in (`stage='start_only'`) questionnaire answers from POST data.
    Shared by both `visit_action('start')` and combined unplanned `visit_create`.
    """
    checkin_answers = {}
    if not template or post_data is None:
        return checkin_answers
    for q in template.get_active_questions().filter(stage='start_only'):
        field_name = f'question_{q.id}'
        if q.question_type == 'suggested_products':
            val = post_data.getlist(field_name) if hasattr(post_data, 'getlist') else post_data.get(field_name, [])
        elif q.question_type == 'multiple_choice':
            val = post_data.getlist(field_name) if hasattr(post_data, 'getlist') else post_data.get(field_name, [])
        else:
            val = post_data.get(field_name)
            if val is None and hasattr(post_data, 'getlist'):
                lst = post_data.getlist(field_name)
                val = lst[0] if len(lst) == 1 else (lst if lst else '')
        if val:
            checkin_answers[str(q.id)] = val
    return checkin_answers


def can_start_visit(visit, user):
    """
    Validates whether a user is authorized to start the visit (Check-in).
    Preconditions:
    1. Visit status must be 'planned'.
    2. Visit approval_status must be 'approved'.
    3. Visit date must be today (visit.date == timezone.localdate()).
    4. User must be the assigned owner or creator (or superuser / authorized supervisor).
    5. User's role must be eligible for the visit's template.
    6. Visit owner must NOT already have another open visit (`status='started'`, `ended_at IS NULL`) — zero role bypass.
    """
    if not user or not user.is_authenticated:
        return False, "يجب تسجيل الدخول لبدء الزيارة."

    today_dates = {timezone.localdate(), timezone.now().date()}
    if visit.date not in today_dates:
        return False, f"لا يمكن بدء الزيارة إلا في تاريخ اليوم ({timezone.localdate().strftime('%d/%m/%Y')})، وتاريخ الزيارة هو {visit.date.strftime('%d/%m/%Y')}."

    is_owner = (visit.owner_id == user.id or visit.created_by_id == user.id)
    can_override = user.is_superuser or getattr(user, 'is_super_admin', False)
    if not (is_owner or can_override):
        return False, "غير مصرح لك ببدء هذه الزيارة (فقط المندوب المسؤول أو منشئ الزيارة)."

    if visit.template and not visit.template.is_user_eligible(user):
        return False, f"دورك الوظيفي ({getattr(user, 'role_name', 'مستخدم')}) غير مصرح له باستخدام قالب الزيارة '{visit.template.display_name_ar}'."

    if visit.status != 'planned':
        return False, f"لا يمكن بدء الزيارة لأن حالتها الحالية '{visit.status_display_ar}' وليست 'مخططة'."

    if visit.approval_status != 'approved':
        return False, "لا يمكن بدء الزيارة قبل اعتمادها رسمياً من المدير المسؤول."

    open_conflict = get_open_visit_for_owner(visit.owner_id, exclude_visit_id=visit.pk)
    if open_conflict:
        return False, (
            f"لا يمكن بدء الزيارة لوجود زيارة مفتوحة حالياً للمسؤول "
            f"(#{open_conflict.serial_num} - {open_conflict.contact.name}). يرجى إنهاء الزيارة المفتوحة أولاً."
        )

    return True, ""


def start_visit(visit, user, request=None, lat=None, lng=None, accuracy=None, photo_file=None,
                force_bypass=False, bypass_reason='', checkin_answers=None, **kwargs):
    """
    Executes explicit Start Visit / Check-in transition:
    planned (approved) -> started
    Captures server-side started_at timestamp, applies GPS check-in verification,
    validates and saves check-in questionnaire answers (stage='start_only'),
    enforces one open visit per owner (via owner lock + DB constraint),
    and records an audit log entry.
    """
    from django.contrib.auth import get_user_model
    from django.db import IntegrityError, transaction
    from activities.models import Visit, ApprovalAuditLog

    UserModel = get_user_model()
    with transaction.atomic():
        if visit.owner_id:
            UserModel.objects.select_for_update().get(pk=visit.owner_id)
        visit = Visit.objects.select_for_update().get(pk=visit.pk)
        can_start, err = can_start_visit(visit, user)
        if not can_start:
            raise ValidationError(err)

        # Validate check-in questions (stage == 'start_only')
        saved_answers = dict(visit.questionnaire_answers or {})
        if checkin_answers:
            for k, v in checkin_answers.items():
                if v is not None and v != '':
                    saved_answers[str(k)] = v

        if visit.template:
            sp_start_qs = {
                q.id: q for q in visit.template.get_active_questions().filter(stage='start_only', question_type='suggested_products')
            }
            for qid, q_obj in sp_start_qs.items():
                if str(qid) in saved_answers:
                    eligible_qs, hist_ids, _ = get_question_product_choices(visit.template, visit=visit, question=q_obj)
                    allowed_ids = set(eligible_qs.values_list('id', flat=True)) | hist_ids
                    saved_answers[str(qid)] = parse_suggested_products_submission(
                        {str(qid): saved_answers[str(qid)]}, str(qid), allowed_ids, strict=True
                    )
                    if not saved_answers[str(qid)]:
                        saved_answers.pop(str(qid), None)

            start_questions = visit.template.get_active_questions().filter(stage='start_only')
            for q in start_questions:
                # Conditional check if applicable
                if q.is_conditional and q.conditional_parent_id:
                    parent_val = saved_answers.get(str(q.conditional_parent_id), '')
                    trigger_val = (q.conditional_trigger_value or '').strip().lower()
                    if str(parent_val).strip().lower() != trigger_val:
                        continue
                if q.is_required:
                    ans = saved_answers.get(str(q.id))
                    if ans is None or (isinstance(ans, str) and not ans.strip()) or (isinstance(ans, (list, tuple)) and len(ans) == 0):
                        raise ValidationError(f"سؤال بداية الزيارة '{q.text_ar}' إلزامي لبدء الزيارة.")

        # Enforce GPS check-in verification when enabled or when coordinates/bypass are provided
        loc_settings = LocationSettings.get_settings()
        should_verify_start = bool(
            loc_settings.verify_visits or
            lat is not None or lng is not None or force_bypass
        )
        if should_verify_start:
            verify_visit_location(
                visit, user, visit.contact,
                visit_lat=lat if lat is not None else visit.latitude,
                visit_lng=lng if lng is not None else visit.longitude,
                device_accuracy=accuracy if accuracy is not None else visit.device_accuracy,
                force_bypass=force_bypass, bypass_reason=bypass_reason,
                stage='start',
                strict_distance=bool(loc_settings.verify_visits)
            )

        status_before = visit.status
        visit.status = 'started'
        visit.started_at = timezone.now()
        visit.ended_at = None
        visit.questionnaire_answers = saved_answers
        try:
            visit.save()
        except IntegrityError:
            raise ValidationError(
                "لا يمكن بدء الزيارة لوجود زيارة أخرى مفتوحة حالياً لنفس المسؤول. يرجى إنهاء الزيارة الجارية أولاً."
            )

        ip = request.META.get('REMOTE_ADDR') if request else None
        if force_bypass or visit.gps_forced_start:
            ApprovalAuditLog.objects.create(
                record_type='visit',
                visit=visit,
                action='bypass',
                actor=user,
                status_before=status_before,
                status_after='started',
                reason=f"تجاوز GPS عند بدء الزيارة: {bypass_reason or 'تجاوز بصلاحية تجاوز GPS'}",
                ip_address=ip
            )
        ApprovalAuditLog.objects.create(
            record_type='visit',
            visit=visit,
            action='status_changed',
            actor=user,
            status_before=status_before,
            status_after='started',
            reason='بدأ المندوب الزيارة رسمياً (Check-in)',
            ip_address=ip
        )
        from accounts.services import AuditLogService
        AuditLogService.log(
            action_type='VISIT_STARTED',
            module='visits',
            actor=user,
            request=request,
            record_id=visit.pk,
            record_name=str(visit.serial_num),
            description=f"بدء الزيارة رقم {visit.serial_num}",
            previous_values={'status': status_before},
            new_values={'status': 'started'},
            status='SUCCESS',
        )
        return visit


def create_and_start_unplanned_visit(
    user,
    contact,
    template,
    *,
    owner=None,
    doubled=False,
    is_successful=True,
    post_data=None,
    lat=None,
    lng=None,
    accuracy=None,
    photo_file=None,
    force_bypass=False,
    bypass_reason='',
    checkin_answers=None,
    detailed_product_ids=None,
    request=None,
):
    """
    Atomically creates an unplanned Visit dated today (`timezone.localdate()`)
    and immediately starts it via `start_visit()`.
    If ANY validation, open-visit conflict, GPS rule, or start question fails,
    the entire `transaction.atomic()` block rolls back so zero unstarted or
    orphaned visits/logs remain in the database.
    """
    from django.contrib.auth import get_user_model
    from django.db import IntegrityError, transaction
    from activities.models import Visit, ApprovalAuditLog
    from catalog.models import Product
    from accounts.permissions import can_user_access_contact_for_visit
    from accounts.services import AuditLogService

    if not user or not getattr(user, 'is_authenticated', False):
        raise ValidationError("يجب تسجيل الدخول لتسجيل وبدء الزيارة.")

    target_owner = owner or user
    UserModel = get_user_model()
    loc_settings = LocationSettings.get_settings()

    with transaction.atomic():
        UserModel.objects.select_for_update().get(pk=target_owner.pk)

        if not contact:
            raise ValidationError("يرجى اختيار جهة الاتصال (العميل).")
        if not can_user_access_contact_for_visit(user, contact):
            raise ValidationError("غير مصرح لك بإنشاء زيارة لهذا العميل خارج نطاق منطقتك الجغرافية.")
        if not template:
            raise ValidationError("اختيار قالب الزيارة إلزامي لإتمام العملية.")
        if not template.is_user_eligible(user):
            raise ValidationError(f"دورك الوظيفي غير مصرح له باستخدام قالب الزيارة '{template.display_name_ar}'.")
        if not template.is_contact_eligible(contact, user=user):
            allowed_str = ", ".join(template.restrict_account_types) if template.restrict_account_types else "الكل"
            raise ValidationError(
                f"قالب الزيارة '{template.display_name_ar}' غير مصرح به لنوع حساب العميل ({contact.account_type or 'غير محدد'}). الأنواع المصرح بها: {allowed_str}."
            )

        open_conflict = get_open_visit_for_owner(target_owner.pk)
        if open_conflict:
            raise ValidationError(
                f"لا يمكن إنشاء وبدء زيارة جديدة لوجود زيارة مفتوحة حالياً للمسؤول "
                f"(#{open_conflict.serial_num} - {open_conflict.contact.name}). يرجى إنهاء الزيارة المفتوحة أولاً."
            )

        visit_date = timezone.localdate()
        now_ts = timezone.now()

        visit = Visit(
            contact=contact,
            template=template,
            owner=target_owner,
            created_by=user,
            is_planned=False,
            date=visit_date,
            status='planned',
            started_at=None,
            ended_at=None,
            is_successful=bool(is_successful),
            doubled=bool(doubled),
            allowed_distance=loc_settings.get_effective_tolerance(template),
            approval_status='approved',
            approved_by=user,
            approved_at=now_ts,
            location_verified=False,
            verification_status='unverified',
            location_status='بانتظار بدء الزيارة والتحقق من الموقع الجغرافي',
            requires_approval_due_to_distance=False,
        )
        visit.save()

        # Persist optional suggested_products / product detailing submitted at creation
        if template and post_data is not None:
            sp_answers = dict(visit.questionnaire_answers or {})
            sp_changed = False
            for q in template.get_active_questions().filter(question_type='suggested_products'):
                fname = f'question_{q.id}'
                if fname in post_data:
                    eligible_qs, _, _ = get_question_product_choices(template, question=q)
                    allowed_ids = set(eligible_qs.values_list('id', flat=True))
                    parsed_sp = parse_suggested_products_submission(post_data, fname, allowed_ids, strict=False)
                    if parsed_sp:
                        sp_answers[str(q.id)] = parsed_sp
                        sp_changed = True
            if sp_changed:
                visit.questionnaire_answers = sp_answers
                visit.save(update_fields=['questionnaire_answers'])

        if template and template.is_product_detailing_supported():
            raw_det_ids = detailed_product_ids
            if raw_det_ids is None and post_data is not None:
                raw_det_ids = post_data.getlist('detailed_products') if hasattr(post_data, 'getlist') else post_data.get('detailed_products', [])
            if raw_det_ids:
                eligible_ids = set(Product.get_eligible_for_visits().values_list('id', flat=True))
                valid_ids = [int(pid) for pid in raw_det_ids if str(pid).isdigit() and int(pid) in eligible_ids]
                visit.detailed_products.set(valid_ids)
            elif template.has_suggested_products_question() and visit.questionnaire_answers:
                sp_union = []
                for q in template.get_active_questions().filter(question_type='suggested_products'):
                    for pid in (visit.questionnaire_answers.get(str(q.id)) or []):
                        if str(pid).isdigit() and int(pid) not in sp_union:
                            sp_union.append(int(pid))
                if sp_union:
                    visit.detailed_products.set(sp_union)

        ip = request.META.get('REMOTE_ADDR') if request else None
        ApprovalAuditLog.objects.create(
            record_type='visit',
            visit=visit,
            action='created',
            actor=user,
            status_before='',
            status_after=visit.approval_status,
            reason=f"إنشاء زيارة خارج الخطة للعميل {contact.name}",
            ip_address=ip,
        )

        AuditLogService.log(
            action='create',
            action_type='VISIT_CREATED',
            module='visits',
            user=user,
            request=request,
            record_id=visit.pk,
            object_repr=f"Visit #{visit.serial_num}",
            new_values={
                'serial_num': visit.serial_num,
                'contact_id': contact.id,
                'contact_name': contact.name,
                'is_planned': False,
                'date': str(visit.date),
                'owner_id': target_owner.id,
                'template_id': template.id,
                'doubled': visit.doubled,
                'allowed_distance': float(visit.allowed_distance) if visit.allowed_distance is not None else None,
                'verification_status': visit.verification_status,
                'approval_status': visit.approval_status,
            },
        )

        resolved_checkin = checkin_answers
        if resolved_checkin is None and post_data is not None:
            resolved_checkin = extract_checkin_answers_from_post(post_data, template)

        try:
            visit = start_visit(
                visit,
                user,
                request=request,
                lat=lat,
                lng=lng,
                accuracy=accuracy,
                photo_file=photo_file,
                force_bypass=force_bypass,
                bypass_reason=bypass_reason,
                checkin_answers=resolved_checkin,
            )
        except IntegrityError:
            raise ValidationError(
                "لا يمكن بدء الزيارة لوجود زيارة أخرى مفتوحة حالياً لنفس المسؤول. يرجى إنهاء الزيارة الجارية أولاً."
            )
        return visit


def can_submit_answers(visit, user):
    """
    Validates whether user can submit/save answers for a visit.
    Preconditions:
    1. Visit must be 'started'. Cannot submit answers when 'planned' or 'finished'.
    2. User must be visit owner or superuser/supervisor.
    3. Role restriction: user role must be eligible for the template.
    """
    if not user or not user.is_authenticated:
        return False, "يجب تسجيل الدخول لتسجيل الإجابات."

    is_owner = (visit.owner_id == user.id or visit.created_by_id == user.id)
    can_override = user.is_superuser or getattr(user, 'is_super_admin', False)
    if not (is_owner or can_override):
        return False, "غير مصرح لك بتسجيل إجابات هذه الزيارة."

    if visit.template and not visit.template.is_user_eligible(user):
        return False, f"دورك الوظيفي غير مصرح له باستخدام قالب الزيارة '{visit.template.display_name_ar}'."

    if visit.status != 'started':
        return False, f"لا يمكن تسجيل الإجابات لأن الزيارة ليست جارية (حالتها: {visit.status_display_ar})."

    return True, ""


def can_end_visit(visit, user, answers=None):
    """
    Validates whether the visit satisfies all requirements to be explicitly ended:
    1. Visit must be 'started'.
    2. User must be visit owner or superuser.
    3. Required questions in template must have valid answers.
    """
    if not user or not user.is_authenticated:
        return False, "يجب تسجيل الدخول لإنهاء الزيارة."

    is_owner = (visit.owner_id == user.id or visit.created_by_id == user.id)
    can_override = user.is_superuser or getattr(user, 'is_super_admin', False)
    if not (is_owner or can_override):
        return False, "غير مصرح لك بإنهاء هذه الزيارة."

    if visit.template and not visit.template.is_user_eligible(user):
        return False, f"دورك الوظيفي غير مصرح له باستخدام قالب الزيارة '{visit.template.display_name_ar}'."

    if visit.status == 'planned':
        return False, "لا يمكن إنهاء الزيارة قبل بدئها."

    if visit.status == 'finished':
        return False, "الزيارة منتهية بالفعل (تم تسجيل الخروج مسبقاً)."

    if visit.status != 'started':
        return False, f"لا يمكن إنهاء الزيارة لأن حالتها الحالية هي '{visit.status_display_ar}'."

    # Validate required questions strictly (Requirement 5)
    effective_answers = answers if answers is not None else (visit.questionnaire_answers or {})
    if visit.template:
        questions = visit.template.get_active_questions()
        for q in questions:
            # Check conditional logic
            if q.is_conditional and q.conditional_parent_id:
                parent_val = effective_answers.get(str(q.conditional_parent_id))
                if parent_val is None:
                    parent_val = effective_answers.get(q.conditional_parent_id, '')
                trigger_val = (q.conditional_trigger_value or '').strip().lower()
                if str(parent_val).strip().lower() != trigger_val:
                    continue  # Question was not active

            if q.is_required:
                ans = effective_answers.get(str(q.id))
                if ans is None:
                    ans = effective_answers.get(q.id)
                is_empty = (
                    ans is None or
                    (isinstance(ans, str) and not ans.strip()) or
                    (isinstance(ans, (list, tuple)) and (len(ans) == 0 or all(not str(x).strip() for x in ans))) or
                    (isinstance(ans, dict) and len(ans) == 0)
                )
                if is_empty:
                    return False, f"السؤال '{q.text_ar}' إلزامي لإتمام الزيارة."

    return True, ""


def end_visit(visit, user, request=None, answers=None, detailed_product_ids=None,
              lat=None, lng=None, accuracy=None, force_bypass=False, bypass_reason='',
              request_distance_exception=False, **kwargs):
    """
    Executes explicit End Visit / Check-out transition:
    started -> finished
    Captures server-side ended_at timestamp, calculates duration on the server,
    verifies GPS, derives outcome from Question #1 in answers, updates planned items, and logs audit.
    """
    import datetime
    from django.db import transaction
    from activities.models import Visit, ApprovalAuditLog, PlannedVisitItem
    from catalog.models import Product

    with transaction.atomic():
        visit = Visit.objects.select_for_update().get(pk=visit.pk)
        can_end, err = can_end_visit(visit, user, answers=answers)
        if not can_end:
            raise ValidationError(err)

        if answers is not None:
            normalized_answers = dict(answers)
            if visit.template:
                for q in visit.template.get_active_questions():
                    if q.question_type == 'suggested_products' and str(q.id) in normalized_answers:
                        eligible_qs, hist_ids, _ = get_question_product_choices(visit.template, visit=visit, question=q)
                        allowed_ids = set(eligible_qs.values_list('id', flat=True)) | hist_ids
                        parsed = parse_suggested_products_submission(
                            {str(q.id): normalized_answers[str(q.id)]}, str(q.id), allowed_ids, strict=True
                        )
                        if parsed:
                            normalized_answers[str(q.id)] = parsed
                        else:
                            normalized_answers.pop(str(q.id), None)
            visit.questionnaire_answers = normalized_answers

        # Derive is_successful from Question #1 in questionnaire answers
        effective_answers = visit.questionnaire_answers or {}
        if visit.template:
            q1 = visit.template.questions.filter(order=1).first()
            if q1 and str(q1.id) in effective_answers:
                val = str(effective_answers[str(q1.id)]).strip().lower()
                visit.is_successful = (val == 'successful' or ('ناجحة' in val and 'غير' not in val))
            else:
                for q in visit.template.questions.all():
                    if 'نتيجة' in q.text_ar or 'outcome' in q.text_en.lower():
                        if str(q.id) in effective_answers:
                            val = str(effective_answers[str(q.id)]).strip().lower()
                            visit.is_successful = (val == 'successful' or ('ناجحة' in val and 'غير' not in val))
                            break

        # Product detailing
        if visit.template and visit.template.is_product_detailing_supported():
            if visit.template.has_suggested_products_question():
                sp_union_ids = []
                for q in visit.template.get_active_questions():
                    if q.question_type == 'suggested_products':
                        q_vals = (visit.questionnaire_answers or {}).get(str(q.id), [])
                        if isinstance(q_vals, (list, tuple)):
                            for pid in q_vals:
                                if str(pid).isdigit() and int(pid) not in sp_union_ids:
                                    sp_union_ids.append(int(pid))
                visit.detailed_products.set(sp_union_ids)
            elif detailed_product_ids is not None:
                eligible_ids = set(Product.get_eligible_for_visits().values_list('id', flat=True))
                historical_ids = set(visit.detailed_products.values_list('id', flat=True))
                allowed_ids = eligible_ids | historical_ids
                valid_ids = [int(pid) for pid in detailed_product_ids if str(pid).isdigit() and int(pid) in allowed_ids]
                visit.detailed_products.set(valid_ids)
        else:
            visit.detailed_products.clear()

        approval_before = visit.approval_status
        # Location verification for completion stage
        verify_visit_location(
            visit, user, visit.contact,
            visit_lat=lat if lat is not None else visit.latitude,
            visit_lng=lng if lng is not None else visit.longitude,
            device_accuracy=accuracy if accuracy is not None else visit.device_accuracy,
            force_bypass=force_bypass, bypass_reason=bypass_reason,
            stage='end', strict_distance=bool(LocationSettings.get_settings().verify_visits and LocationSettings.get_settings().verify_end_visit_distance)
        )

        status_before = visit.status
        visit.status = 'finished'
        visit.ended_at = timezone.now()

        # Strict server-side duration calculation
        if visit.started_at:
            visit.duration = max(1, int((visit.ended_at - visit.started_at).total_seconds()))
        else:
            visit.started_at = visit.ended_at - datetime.timedelta(minutes=15)
            visit.duration = 900

        visit.save()

        # Mark associated planned visit item as executed
        planned_item = PlannedVisitItem.objects.filter(visit=visit).first()
        if planned_item:
            planned_item.is_executed = True
            planned_item.save(update_fields=['is_executed'])

        ip = request.META.get('REMOTE_ADDR') if request else None
        from accounts.services import AuditLogService

        if force_bypass or visit.gps_forced_end or visit.verification_status == 'force_bypassed':
            ApprovalAuditLog.objects.create(
                record_type='visit',
                visit=visit,
                action='bypass',
                actor=user,
                status_before=status_before,
                status_after='finished',
                reason=f"تجاوز GPS عند إنهاء الزيارة: {bypass_reason or 'تجاوز بصلاحية تجاوز GPS'}",
                ip_address=ip
            )
            ApprovalAuditLog.objects.create(
                record_type='visit',
                visit=visit,
                action='distance_bypass',
                actor=user,
                status_before=approval_before,
                status_after=visit.approval_status,
                reason=(
                    f"تجاوز شرط المسافة عند إنهاء الزيارة (المسافة الفعلية: {visit.distance or 'غير محددة'}م، المسموح: {visit.allowed_distance}م). "
                    f"السبب: {visit.bypass_reason}"
                ),
                ip_address=ip
            )
            AuditLogService.log(
                action_type='VISIT_DISTANCE_BYPASSED',
                module='visits',
                actor=user,
                request=request,
                record_id=visit.pk,
                record_name=str(visit.serial_num),
                description=f"تجاوز شرط المسافة للزيارة #{visit.serial_num} بصلاحية إدارية",
                new_values={
                    'distance': str(visit.distance or ''),
                    'allowed_distance': str(visit.allowed_distance or ''),
                    'bypass_reason': visit.bypass_reason,
                    'approval_status': visit.approval_status,
                },
                status='SUCCESS',
            )

        ApprovalAuditLog.objects.create(
            record_type='visit',
            visit=visit,
            action='status_changed',
            actor=user,
            status_before=status_before,
            status_after='finished',
            reason='إنهاء الزيارة وتوثيق الإجراءات رسمياً (Check-out)',
            ip_address=ip
        )
        AuditLogService.log(
            action_type='VISIT_COMPLETED',
            module='visits',
            actor=user,
            request=request,
            record_id=visit.pk,
            record_name=str(visit.serial_num),
            description=f"إنهاء الزيارة رقم {visit.serial_num}",
            previous_values={'status': status_before},
            new_values={
                'status': 'finished',
                'distance': str(visit.distance or ''),
                'allowed_distance': str(visit.allowed_distance or ''),
                'verification_status': visit.verification_status,
                'approval_status': visit.approval_status,
            },
            status='SUCCESS',
        )
        return visit


def build_visit_timeline(visit):
    """
    Constructs a complete, chronological timeline of all lifecycle events for a visit (Requirement 6):
    - Visit creation, type (planned vs unplanned), and assignment to responsible user
    - Start visit (check-in)
    - Location and distance validation (actual vs allowed threshold)
    - Distance bypass attempts and exception reasons
    - Visit completion & answers
    - Approval requests, approvals, and rejections
    - Subsequent edits (with previous and new values)
    - Reapproval requests and decisions
    - Cancellation
    """
    from accounts.models import SecurityAuditLog

    events = []
    creator_name = (
        (visit.created_by.get_full_name() or visit.created_by.username)
        if visit.created_by else
        (visit.owner.get_full_name() or visit.owner.username if visit.owner else "النظام")
    )
    owner_name = (visit.owner.get_full_name() or visit.owner.username) if visit.owner else "غير محدد"

    # 1. Creation & Assignment Milestone
    events.append({
        'timestamp': visit.created_at,
        'title': f"إنشاء الزيارة ({visit.plan_type_display_ar})",
        'actor': creator_name,
        'icon': 'add_location_alt' if not visit.is_planned else 'event_available',
        'color': 'teal',
        'details': (
            f"تم تسجيل {visit.plan_type_display_ar} للعميل «{visit.contact.name}» "
            f"وتعيين المسؤول: «{owner_name}»"
            + (f" باستخدام قالب «{visit.template.display_name_ar}»." if visit.template else ".")
        ),
        'previous_values': None,
        'new_values': {
            'نوع الزيارة': visit.plan_type_display_ar,
            'العميل': visit.contact.name,
            'المسؤول': owner_name,
            'تاريخ الزيارة': visit.date.strftime('%Y-%m-%d') if visit.date else '-',
        },
    })

    # 2. ApprovalAuditLog entries
    approval_logs = list(visit.approval_history.select_related('actor').order_by('created_at', 'id'))
    for log in approval_logs:
        actor_str = (log.actor.get_full_name() or log.actor.username) if log.actor else "النظام"
        icon = 'history'
        color = 'slate'
        title = log.get_action_display()

        if log.action == 'approved':
            icon = 'check_circle'
            color = 'emerald'
            title = 'اعتماد الزيارة'
        elif log.action == 'rejected':
            icon = 'cancel'
            color = 'rose'
            title = 'رفض الزيارة'
        elif log.action == 'resubmitted':
            icon = 'replay'
            color = 'amber'
            title = 'إعادة تقديم الزيارة للاعتماد'
        elif log.action == 'edited_reapproval_required':
            icon = 'edit_notifications'
            color = 'amber'
            title = 'تعديل بعد الاعتماد (يتطلب اعتماد المدير)'
        elif log.action == 'edited_by_manager':
            icon = 'edit_note'
            color = 'sky'
            title = 'تعديل بيانات الزيارة'
        elif log.action == 'distance_bypass':
            icon = 'admin_panel_settings'
            color = 'amber'
            title = 'تجاوز شرط المسافة بصلاحية إدارية'
        elif log.action == 'distance_exception_requested':
            icon = 'warning'
            color = 'amber'
            title = 'طلب استثناء مسافة وتحويل لاعتماد المدير'
        elif log.action == 'status_changed':
            if log.status_after == 'started':
                icon = 'play_circle'
                color = 'teal'
                title = 'بدء الزيارة (Check-in)'
            elif log.status_after == 'finished':
                icon = 'task_alt'
                color = 'emerald'
                title = 'إنهاء وتوثيق الزيارة (Check-out)'
            elif log.status_after == 'cancelled':
                icon = 'cancel'
                color = 'rose'
                title = 'إلغاء الزيارة'
            else:
                icon = 'tune'
                color = 'purple'
                title = 'تغيير حالة الزيارة'
        elif log.action == 'sent_to_agenda':
            icon = 'view_agenda'
            color = 'teal'
            title = 'إرسال إلى جدول الأعمال'
        elif log.action == 'answers_updated':
            icon = 'quiz'
            color = 'teal'
            title = 'تعديل إجابات استبيان الزيارة'

        events.append({
            'timestamp': log.created_at,
            'title': title,
            'actor': actor_str,
            'icon': icon,
            'color': color,
            'details': log.reason or f"تغيير الحالة من ({log.status_before or '-'}) إلى ({log.status_after or '-'}).",
            'previous_values': {'الحالة السابقة': log.status_before} if log.status_before else None,
            'new_values': {'الحالة الجديدة': log.status_after} if log.status_after else None,
            'changes': log.changes if log.changes else None,
            'approval_required': log.approval_required,
        })

    # 3. SecurityAuditLog entries for edits, distance validations, and answers
    sec_logs = SecurityAuditLog.objects.filter(
        module='visits',
        record_id=str(visit.pk)
    ).select_related('actor').order_by('created_at', 'id')

    for slog in sec_logs:
        # Skip duplicate entries already represented cleanly unless they carry field diffs (edits/answers)
        if slog.action_type in ('VISIT_CREATED', 'VISIT_STARTED', 'VISIT_COMPLETED', 'VISIT_DISTANCE_BYPASSED', 'VISIT_DISTANCE_EXCEPTION_REQUESTED'):
            continue
        actor_str = (slog.actor.get_full_name() or slog.actor.username) if slog.actor else "النظام"
        icon = 'edit_note'
        color = 'sky'
        title = slog.description or slog.action_type

        if 'REAPPROVAL' in (slog.action_type or ''):
            icon = 'published_with_changes'
            color = 'amber'
            title = 'تعديل بيانات زيارة معتمدة (إعادة اعتماد مطلوبة)'
        elif slog.action_type == 'VISIT_ANSWERS_UPDATED':
            icon = 'quiz'
            color = 'teal'
            title = 'تعديل إجابات استبيان الزيارة'
        elif 'UPDATE' in (slog.action_type or '') or slog.action_type == 'update':
            icon = 'edit'
            color = 'sky'
            title = 'تحديث بيانات الزيارة'
        elif 'CANCEL' in (slog.action_type or ''):
            icon = 'cancel'
            color = 'rose'
            title = 'إلغاء الزيارة'

        events.append({
            'timestamp': slog.created_at,
            'title': title,
            'actor': actor_str,
            'icon': icon,
            'color': color,
            'details': slog.description or '',
            'previous_values': slog.previous_values if slog.previous_values else None,
            'new_values': slog.new_values if slog.new_values else None,
        })

    # 4. Location & Distance validation summary event if not already logged via ApprovalAuditLog
    has_distance_log = any(e['icon'] in ('admin_panel_settings', 'warning') for e in events)
    if visit.distance is not None or visit.verification_status == 'force_bypassed':
        dist_ts = visit.bypassed_at or visit.ended_at or visit.started_at or visit.created_at
        allowed_m = visit.effective_allowed_distance
        actual_m = float(visit.distance) if visit.distance is not None else None
        if not has_distance_log:
            events.append({
                'timestamp': dist_ts,
                'title': 'التحقق من الموقع والمسافة الجغرافية',
                'actor': (visit.bypassed_by.get_full_name() or visit.bypassed_by.username) if visit.bypassed_by else owner_name,
                'icon': 'my_location' if visit.location_verified else 'location_off',
                'color': 'emerald' if (visit.location_verified and visit.verification_status == 'verified') else 'amber',
                'details': (
                    f"حالة التحقق: {visit.verification_status_display_ar} — "
                    f"المسافة الفعلية: {f'{actual_m:.2f} متر' if actual_m is not None else 'غير متوفرة'} | "
                    f"المسافة المسموح بها: {allowed_m:.0f} متر"
                    + (f" | سبب التجاوز/الاستثناء: {visit.bypass_reason}" if visit.bypass_reason else "")
                ),
                'previous_values': None,
                'new_values': {
                    'المسافة الفعلية': f"{actual_m:.2f} م" if actual_m is not None else "غير محددة",
                    'المسافة المسموح بها': f"{allowed_m:.0f} م",
                    'حالة الموقع': visit.location_status or visit.verification_status_display_ar,
                },
            })

    events.sort(key=lambda x: x['timestamp'] or timezone.now())

    # Build structured before/after diffs (`changes`) for template rendering
    for ev in events:
        if ev.get('changes'):
            continue
        prev_dict = ev.get('previous_values')
        new_dict = ev.get('new_values')
        if isinstance(prev_dict, dict) and isinstance(new_dict, dict):
            changes = []
            # If questionnaire_answers changed, expand each modified question
            prev_ans = prev_dict.get('questionnaire_answers')
            new_ans = new_dict.get('questionnaire_answers')
            if isinstance(prev_ans, dict) and isinstance(new_ans, dict) and prev_ans != new_ans:
                q_obj_map = {}
                sp_pids = set()
                if visit.template:
                    for q in visit.template.questions.all():
                        q_obj_map[str(q.id)] = q
                all_q_keys = list(dict.fromkeys(list(prev_ans.keys()) + list(new_ans.keys())))
                for qk in all_q_keys:
                    q_obj = q_obj_map.get(str(qk))
                    if q_obj and q_obj.question_type == 'suggested_products':
                        for raw_side in (prev_ans.get(qk), new_ans.get(qk)):
                            if raw_side not in (None, '', []):
                                for item in (raw_side if isinstance(raw_side, (list, tuple)) else [raw_side]):
                                    if str(item).isdigit():
                                        sp_pids.add(int(item))
                tl_pmap = {}
                if sp_pids:
                    from catalog.models import Product
                    tl_pmap = dict(Product.objects.filter(id__in=sp_pids).values_list('id', 'name'))
                for qk in all_q_keys:
                    old_v = prev_ans.get(qk)
                    new_v = new_ans.get(qk)
                    if old_v != new_v:
                        q_obj = q_obj_map.get(str(qk))
                        q_label = q_obj.text_ar if q_obj else f"سؤال #{qk}"
                        old_str = (format_answer_for_display(q_obj, old_v, product_map=tl_pmap) or '-') if q_obj else (
                            "، ".join(str(x) for x in old_v) if isinstance(old_v, list) else (str(old_v) if old_v not in (None, '') else '-')
                        )
                        new_str = (format_answer_for_display(q_obj, new_v, product_map=tl_pmap) or '-') if q_obj else (
                            "، ".join(str(x) for x in new_v) if isinstance(new_v, list) else (str(new_v) if new_v not in (None, '') else '-')
                        )
                        changes.append({'field': q_label, 'old': old_str, 'new': new_str})

            # Also check answer_changes if explicitly stored
            ans_changes = new_dict.get('answer_changes')
            if isinstance(ans_changes, list):
                for ac in ans_changes:
                    if isinstance(ac, dict) and 'field' in ac:
                        changes.append({
                            'field': ac.get('field'),
                            'old': ac.get('old', '-'),
                            'new': ac.get('new', '-')
                        })

            field_labels = {
                'contact_id': 'العميل (ID)',
                'template_id': 'القالب (ID)',
                'date': 'التاريخ',
                'owner_id': 'المسؤول (ID)',
                'feedback': 'الملاحظات',
                'visit_outcome': 'نتيجة الزيارة',
                'is_successful': 'زيارة ناجحة',
                'doubled': 'زيارة مزدوجة',
                'approval_status': 'حالة الاعتماد',
                'status': 'حالة الزيارة',
                'time': 'وقت الزيارة',
                'الحالة السابقة': 'الحالة',
            }
            for k, old_val in prev_dict.items():
                if k in ('questionnaire_answers', 'answer_changes', 'detailed_products'):
                    continue
                if k == 'الحالة السابقة' and 'الحالة الجديدة' in new_dict:
                    if old_val != new_dict['الحالة الجديدة']:
                        changes.append({'field': 'الحالة', 'old': str(old_val), 'new': str(new_dict['الحالة الجديدة'])})
                    continue
                if k in new_dict and new_dict[k] != old_val:
                    changes.append({
                        'field': field_labels.get(k, k),
                        'old': str(old_val) if old_val not in (None, '') else '-',
                        'new': str(new_dict[k]) if new_dict[k] not in (None, '') else '-'
                    })
            if changes:
                ev['changes'] = changes

    return events


def can_delete_unended_visit(visit, user):
    """
    Validates whether a user is authorized to delete a visit:
    1. User must be authenticated and hold `activities:visits/delete` (or SuperAdmin).
    2. User must pass object-level DataScope (`can_user_access_object(user, visit, 'delete')`)
       BEFORE inspecting or exposing visit lifecycle status.
    3. Visit must NOT be ended (`visit.status != 'finished'` and `visit.ended_at is None`).
    Note: Decoupled from LocationSettings.allow_visit_deletion_before_end.
    """
    if not user or not getattr(user, 'is_authenticated', False):
        return False, "يجب تسجيل الدخول لحذف الزيارة."

    from accounts.permissions import has_perm_or_admin, can_user_access_object
    if not has_perm_or_admin(user, 'activities:visits/delete'):
        return False, "عذراً، لا تملك صلاحية حذف الزيارات."

    if not can_user_access_object(user, visit, 'delete'):
        return False, "غير مصرح لك بحذف هذه الزيارة خارج نطاق صلاحياتك أو منطقتك الجغرافية."

    return True, ""


def delete_unended_visit(visit, user, request=None):
    """
    Deletes an unended visit after verifying permissions and data scope.
    - Deletes associated PlannedVisitItem records (and empty parent VisitPlan if orphaned).
    - Cleans up linked ERPAttachment records and Visit.photo safely post-commit.
    - Preserves full audit snapshot (including ApprovalAuditLog history) in SecurityAuditLog.
    """
    from django.contrib.contenttypes.models import ContentType
    from django.db import transaction
    from activities.models import Visit, PlannedVisitItem, VisitPlan
    from accounts.services import AuditLogService
    from master_data.models import ERPAttachment
    from master_data.media_service import delete_attachment, schedule_storage_deletion

    with transaction.atomic():
        visit = Visit.objects.select_for_update().select_related('contact', 'owner', 'template', 'plan').get(pk=visit.pk)
        allowed, reason = can_delete_unended_visit(visit, user)
        if not allowed:
            raise ValidationError(reason)

        visit_pk = visit.pk
        serial_num = visit.serial_num
        linked_items = list(PlannedVisitItem.objects.filter(visit=visit).select_related('plan'))
        parent_plan_ids = {it.plan_id for it in linked_items if it.plan_id}
        if visit.plan_id:
            parent_plan_ids.add(visit.plan_id)

        approval_logs = [
            {
                'id': log.id,
                'action': log.action,
                'actor_id': log.actor_id,
                'actor_username': log.actor.username if log.actor else '',
                'status_before': log.status_before,
                'status_after': log.status_after,
                'reason': log.reason,
                'ip_address': log.ip_address,
                'created_at': log.created_at.isoformat() if log.created_at else None,
            }
            for log in visit.approval_history.select_related('actor').order_by('created_at', 'id')
        ]

        snapshot = {
            'id': visit_pk,
            'serial_num': serial_num,
            'contact_id': visit.contact_id,
            'contact_name': visit.contact.name if visit.contact else '',
            'owner_id': visit.owner_id,
            'owner_username': visit.owner.username if visit.owner else '',
            'created_by_id': visit.created_by_id,
            'template_id': visit.template_id,
            'plan_id': visit.plan_id,
            'deleted_planned_item_ids': [it.id for it in linked_items],
            'date': str(visit.date),
            'status': visit.status,
            'approval_status': visit.approval_status,
            'is_planned': visit.is_planned,
            'started_at': visit.started_at.isoformat() if visit.started_at else None,
            'latitude': str(visit.latitude) if visit.latitude is not None else None,
            'longitude': str(visit.longitude) if visit.longitude is not None else None,
            'distance': str(visit.distance) if visit.distance is not None else None,
            'verification_status': visit.verification_status,
            'questionnaire_answers': visit.questionnaire_answers or {},
            'approval_history': approval_logs,
        }

        # Clean up any linked ERPAttachment records and optional photo field safely
        ct_visit = ContentType.objects.get_for_model(Visit)
        for att in ERPAttachment.objects.filter(content_type=ct_visit, object_id=visit.pk):
            delete_attachment(att, user, request=request)

        photo_field = getattr(visit, 'photo', None)
        photo_key = photo_field.name if photo_field and getattr(photo_field, 'name', '') else ''

        # Delete associated PlannedVisitItem records (nothing related remains in planned items)
        PlannedVisitItem.objects.filter(visit=visit).delete()

        visit.delete()

        # Remove parent VisitPlan only if it now has zero items and zero visits left
        if parent_plan_ids:
            for plan_obj in VisitPlan.objects.filter(id__in=parent_plan_ids):
                if not plan_obj.planned_items.exists() and not plan_obj.visits.exists():
                    plan_obj.delete()

        if photo_key:
            schedule_storage_deletion(photo_key, size_bytes=0)

        AuditLogService.log(
            action='delete',
            action_type='VISIT_DELETED',
            module='visits',
            actor=user,
            request=request,
            record_id=visit_pk,
            record_name=f"Visit #{serial_num}",
            description=f"حذف الزيارة رقم #{serial_num} للعميل {snapshot['contact_name']}",
            previous_values=snapshot,
            new_values=None,
            status='SUCCESS',
        )
        return snapshot


def can_edit_visit_answers(visit, user):
    """
    Validates whether a user is allowed to edit the visit's questionnaire answers:
    - REQUIREMENT E: Must ONLY be available AFTER the visit has ended (`status == 'finished'` and `ended_at` is set).
    - REQUIREMENT I: Restricted to original creator / assigned owner of the visit (or superuser).
    - User must have `activities:visits/edit_answers` or `activities:visits/edit` permission.
    - Visit must have a template.
    """
    if not user or not getattr(user, 'is_authenticated', False):
        return False, "يجب تسجيل الدخول لتعديل إجابات الاستبيان."

    if visit.status != 'finished' or not visit.ended_at:
        return False, "عذراً، لا يمكن تعديل إجابات الاستبيان إلا بعد انتهاء الزيارة واكتمالها نهائياً."

    is_owner = (visit.owner_id == user.id or visit.created_by_id == user.id)
    is_super = getattr(user, 'is_superuser', False) or getattr(user, 'is_super_admin', False)
    if not (is_owner or is_super):
        return False, "عذراً، تعديل إجابات الاستبيان مقتصر على المندوب المسؤول صاحب الزيارة فقط."

    from accounts.permissions import has_perm_or_admin
    can_perm = has_perm_or_admin(user, 'activities:visits/edit_answers') or has_perm_or_admin(user, 'activities:visits/edit')
    if not can_perm:
        return False, "عذراً، لا تملك صلاحية تعديل إجابات استبيان هذه الزيارة."

    if not visit.template:
        return False, "لا يوجد قالب استبيان مرتبط بهذه الزيارة."

    return True, ""


def update_visit_questionnaire_answers(visit, user, post_data, request=None):
    """
    Independently updates only a visit's questionnaire answers (`visit.questionnaire_answers`
    and legacy `detailed_products` when no `suggested_products` question exists on the template):
    - Restricted to ended visits and authorized users.
    - Never modifies VisitTemplate or its questions, and never affects other visits.
    - Validates `suggested_products` & `detailed_products` selections against authorized product pools.
    - Triggers re-approval (`approval_status='pending'`, `waiting_for_reapproval=True`).
    - Records before/after answer diffs in `ApprovalAuditLog` (`answers_updated`) and `SecurityAuditLog`,
      and updates creator-edit tracking (`edited_by_creator`, `last_edited_by`, `last_edited_at`).
    """
    from django.db import transaction
    from activities.models import Visit, ApprovalAuditLog
    from accounts.services import AuditLogService
    from catalog.models import Product

    with transaction.atomic():
        visit = Visit.objects.select_for_update().select_related('template', 'contact', 'owner').get(pk=visit.pk)
        allowed, reason = can_edit_visit_answers(visit, user)
        if not allowed:
            raise ValidationError(reason)

        template = visit.template
        old_answers = dict(visit.questionnaire_answers or {})
        new_answers = dict(old_answers)

        questions = list(template.get_active_questions())
        parent_answers = {}

        # First pass: collect parent answers for conditional visibility
        for q in questions:
            field_name = f'question_{q.id}'
            if hasattr(post_data, 'getlist') and q.question_type in ('multiple_choice', 'suggested_products'):
                val = post_data.getlist(field_name)
            else:
                val = post_data.get(field_name)
            if val is not None and val != '' and val != []:
                parent_answers[q.id] = val

        for q in questions:
            is_visible = True
            if q.is_conditional and q.conditional_parent_id:
                parent_val = parent_answers.get(q.conditional_parent_id, '')
                trigger_val = (q.conditional_trigger_value or '').strip().lower()
                if str(parent_val).strip().lower() != trigger_val:
                    is_visible = False

            if not is_visible:
                new_answers.pop(str(q.id), None)
                continue

            field_name = f'question_{q.id}'
            present_marker = f'{field_name}_present'
            if field_name not in post_data and present_marker not in post_data:
                continue

            if q.question_type == 'suggested_products':
                eligible_qs, historical_ids, _ = get_question_product_choices(template, visit=visit, question=q)
                allowed_ids = set(eligible_qs.values_list('id', flat=True)) | historical_ids
                val = parse_suggested_products_submission(post_data, field_name, allowed_ids, strict=True)
            elif hasattr(post_data, 'getlist') and q.question_type == 'multiple_choice':
                val = [v for v in post_data.getlist(field_name) if str(v).strip()]
            else:
                val = post_data.get(field_name)
                if isinstance(val, str):
                    val = val.strip()

            # Enforce required questions when visit is already finished
            if visit.status == 'finished' and q.is_required:
                is_empty = (val is None or val == '' or val == [])
                if is_empty:
                    raise ValidationError(f"السؤال '{q.text_ar}' إلزامي ولا يمكن تركه فارغاً.")

            if val is not None and val != '' and val != []:
                new_answers[str(q.id)] = val
            else:
                new_answers.pop(str(q.id), None)

        # Preload product names for readable diff logging
        all_sp_pids = set()
        q_obj_map = {str(q.id): q for q in questions}
        for q in questions:
            if q.question_type == 'suggested_products':
                for ans_src in (old_answers, new_answers):
                    raw_v = ans_src.get(str(q.id))
                    if raw_v not in (None, '', []):
                        for item in (raw_v if isinstance(raw_v, (list, tuple)) else [raw_v]):
                            if str(item).isdigit():
                                all_sp_pids.add(int(item))

        has_sp_question = any(q.question_type == 'suggested_products' for q in questions)
        det_changed = False
        new_det_ids = None
        old_det_ids = list(visit.detailed_products.order_by('id').values_list('id', flat=True))
        all_sp_pids.update(old_det_ids)

        if template.is_product_detailing_supported() and not has_sp_question and (
            'detailed_products' in post_data or 'detailed_products_present' in post_data
        ):
            eligible_det_qs, hist_det_ids, _ = get_question_product_choices(template, visit=visit, question=None)
            allowed_det_ids = set(eligible_det_qs.values_list('id', flat=True)) | hist_det_ids
            new_det_ids = parse_suggested_products_submission(post_data, 'detailed_products', allowed_det_ids, strict=True)
            all_sp_pids.update(new_det_ids)
            if old_det_ids != new_det_ids:
                det_changed = True
        elif template.is_product_detailing_supported() and has_sp_question:
            synced_ids = []
            for q in questions:
                if q.question_type == 'suggested_products':
                    for pid in (new_answers.get(str(q.id)) or []):
                        if str(pid).isdigit() and int(pid) not in synced_ids:
                            synced_ids.append(int(pid))
            new_det_ids = synced_ids

        all_pmap = dict(Product.objects.filter(id__in=all_sp_pids).values_list('id', 'name')) if all_sp_pids else {}

        # Compute detailed per-question changes using human-readable labels & product names
        answer_changes = []
        all_keys = list(dict.fromkeys(list(old_answers.keys()) + list(new_answers.keys())))
        for qk in all_keys:
            old_v = old_answers.get(qk)
            new_v = new_answers.get(qk)
            if old_v != new_v:
                q_obj = q_obj_map.get(str(qk))
                old_str = (format_answer_for_display(q_obj, old_v, product_map=all_pmap) or '-') if q_obj else (
                    "، ".join(str(x) for x in old_v) if isinstance(old_v, list) else (str(old_v) if old_v not in (None, '') else '-')
                )
                new_str = (format_answer_for_display(q_obj, new_v, product_map=all_pmap) or '-') if q_obj else (
                    "، ".join(str(x) for x in new_v) if isinstance(new_v, list) else (str(new_v) if new_v not in (None, '') else '-')
                )
                answer_changes.append({
                    'question_id': str(qk),
                    'field': q_obj.text_ar if q_obj else f"سؤال #{qk}",
                    'old': old_str,
                    'new': new_str,
                })

        if det_changed and new_det_ids is not None:
            answer_changes.append({
                'question_id': 'detailed_products',
                'field': 'المنتجات المشروحة (Product Detailing)',
                'old': '، '.join(all_pmap.get(pid, f"منتج #{pid}") for pid in old_det_ids) or '-',
                'new': '، '.join(all_pmap.get(pid, f"منتج #{pid}") for pid in new_det_ids) or '-',
            })

        if not answer_changes:
            return visit, []

        if new_det_ids is not None:
            visit.detailed_products.set(new_det_ids)

        prev_approval_status = visit.approval_status
        # Sync visit.is_successful if Question 1 (outcome) changed
        first_q = questions[0] if questions else None
        if first_q and str(first_q.id) in new_answers:
            q1_val = str(new_answers[str(first_q.id)]).strip().lower()
            visit.is_successful = (q1_val == 'successful' or ('ناجح' in q1_val and 'غير' not in q1_val))

        now = timezone.now()
        # REQUIREMENT C & D: Editing questionnaire answers triggers re-approval
        visit.questionnaire_answers = new_answers
        visit.approval_status = 'pending'
        visit.waiting_for_reapproval = True
        visit.approved_by = None
        visit.approved_at = None
        visit.last_edited_by = user
        visit.last_edited_at = now
        if visit.created_by_id and user.id == visit.created_by_id:
            visit.edited_by_creator = True
        visit.save(update_fields=[
            'questionnaire_answers', 'is_successful', 'approval_status',
            'waiting_for_reapproval', 'approved_by', 'approved_at',
            'edited_by_creator', 'last_edited_by', 'last_edited_at', 'updated_at',
        ])

        changes_summary = " | ".join(
            f"{c['field']}: ({c['old']}) ➔ ({c['new']})" for c in answer_changes
        )
        ip = request.META.get('REMOTE_ADDR') if request else None
        ApprovalAuditLog.objects.create(
            record_type='visit',
            visit=visit,
            action='answers_updated',
            actor=user,
            status_before=prev_approval_status,
            status_after='pending',
            reason=f"تعديل إجابات الاستبيان بعد انتهاء الزيارة (يتطلب إعادة اعتماد المدير): {changes_summary}",
            changes=answer_changes,
            approval_required=True,
            context_data={'previous_approval_status': prev_approval_status},
            ip_address=ip,
        )

        AuditLogService.log(
            action='update',
            action_type='VISIT_ANSWERS_UPDATED',
            module='visits',
            actor=user,
            request=request,
            record_id=visit.pk,
            record_name=f"Visit #{visit.serial_num}",
            description=f"تعديل إجابات استبيان الزيارة #{visit.serial_num} وتحويلها للاعتماد ({len(answer_changes)} تعديل)",
            previous_values={'questionnaire_answers': old_answers, 'approval_status': prev_approval_status},
            new_values={'questionnaire_answers': new_answers, 'approval_status': 'pending', 'waiting_for_reapproval': True},
            status='SUCCESS',
        )

        return visit, answer_changes


def _agreement_snapshot(agreement):
    if not agreement:
        return {}
    return {
        'title': agreement.title,
        'customer_id': agreement.customer_id,
        'customer_name': agreement.customer.name if agreement.customer else '',
        'type_id': agreement.type_id,
        'type_name': agreement.type.name if agreement.type else '',
        'amount': str(agreement.amount),
        'date': agreement.date.strftime('%Y-%m-%d') if agreement.date else '',
        'description': agreement.description or '',
        'status': agreement.status,
    }


def _diff_agreement_fields(before_snap, after_snap):
    labels = {
        'title': 'العنوان',
        'customer_name': 'العميل',
        'type_name': 'النوع',
        'amount': 'المبلغ',
        'date': 'التاريخ',
        'description': 'الوصف والشروط',
        'status': 'الحالة',
    }
    status_map = {
        'new': 'بانتظار الاعتماد',
        'approved': 'معتمد',
        'disapproved': 'مرفوض',
        'done': 'منجز',
    }
    changes = []
    for k in ('title', 'customer_name', 'type_name', 'amount', 'date', 'description', 'status'):
        old_val = before_snap.get(k)
        new_val = after_snap.get(k)
        if old_val != new_val:
            old_str = status_map.get(old_val, str(old_val) if old_val not in (None, '') else '-')
            new_str = status_map.get(new_val, str(new_val) if new_val not in (None, '') else '-')
            changes.append({
                'field': labels.get(k, k),
                'old': old_str,
                'new': new_str,
            })
    return changes


def build_agreement_timeline(agreement):
    """
    Constructs a complete, chronological timeline of all lifecycle events for an agreement:
    - Creation
    - Updates & field diffs
    - Approval requests, approvals, rejections, reopening, and completion
    - Deletion / status changes
    """
    from accounts.models import SecurityAuditLog

    events = []
    creator_name = (
        (agreement.created_by.get_full_name() or agreement.created_by.username)
        if agreement.created_by else "النظام"
    )

    # 1. Creation milestone
    events.append({
        'timestamp': agreement.created_at,
        'title': f"إنشاء الاتفاقية #{agreement.serial_num}",
        'actor': creator_name,
        'icon': 'handshake',
        'color': 'teal',
        'details': (
            f"تم إنشاء الاتفاقية للعميل «{agreement.customer.name if agreement.customer else '-'}» "
            f"بقيمة {agreement.amount} ج.م ونوع «{agreement.type.name if agreement.type else '-'}»."
        ),
        'previous_values': None,
        'new_values': {
            'العميل': agreement.customer.name if agreement.customer else '-',
            'العنوان': agreement.title,
            'المبلغ': f"{agreement.amount} ج.م",
            'التاريخ': agreement.date.strftime('%Y-%m-%d') if agreement.date else '-',
            'الحالة': agreement.status_display_ar,
        },
        'changes': None,
        'approval_required': False,
    })

    # 2. ApprovalAuditLog entries
    approval_logs = list(agreement.approval_history.select_related('actor').order_by('created_at', 'id'))
    status_map = {
        'new': 'بانتظار الاعتماد',
        'approved': 'معتمد',
        'disapproved': 'مرفوض',
        'done': 'منجز',
    }
    for log in approval_logs:
        actor_str = (log.actor.get_full_name() or log.actor.username) if log.actor else "النظام"
        icon = 'history'
        color = 'slate'
        title = log.get_action_display()

        if log.action == 'approved':
            icon = 'check_circle'
            color = 'emerald'
            title = 'اعتماد الاتفاقية'
        elif log.action == 'rejected':
            icon = 'cancel'
            color = 'rose'
            title = 'رفض الاتفاقية'
        elif log.action == 'resubmitted':
            icon = 'replay'
            color = 'amber'
            title = 'إعادة تقديم الاتفاقية للاعتماد'
        elif log.action in ('edited_reapproval_required', 'edited_by_manager'):
            icon = 'edit_note'
            color = 'sky'
            title = 'تعديل بيانات الاتفاقية'
        elif log.action == 'status_changed':
            if log.status_after == 'done':
                icon = 'task_alt'
                color = 'purple'
                title = 'إنجاز الاتفاقية'
            elif log.status_after == 'new':
                icon = 'refresh'
                color = 'sky'
                title = 'إعادة فتح الاتفاقية'
            else:
                icon = 'tune'
                color = 'teal'
                title = 'تغيير حالة الاتفاقية'
        elif log.action in ('created', 'submitted'):
            continue

        events.append({
            'timestamp': log.created_at,
            'title': title,
            'actor': actor_str,
            'icon': icon,
            'color': color,
            'details': log.reason or f"تغيير الحالة من ({status_map.get(log.status_before, log.status_before or '-')}) إلى ({status_map.get(log.status_after, log.status_after or '-')}).",
            'previous_values': {'الحالة السابقة': status_map.get(log.status_before, log.status_before)} if log.status_before else None,
            'new_values': {'الحالة الجديدة': status_map.get(log.status_after, log.status_after)} if log.status_after else None,
            'changes': log.changes if log.changes else None,
            'approval_required': log.approval_required,
        })

    # 3. SecurityAuditLog entries for updates and transitions not captured in ApprovalAuditLog
    # Filter strictly by action_type__startswith='AGREEMENT_' to prevent collision with other entities (e.g. VisitPlan)
    sec_logs = SecurityAuditLog.objects.filter(
        module='activities',
        record_id=str(agreement.pk),
        action_type__startswith='AGREEMENT_'
    ).select_related('actor').order_by('created_at', 'id')

    for slog in sec_logs:
        if slog.action_type in ('AGREEMENT_CREATED', 'AGREEMENT_APPROVED', 'AGREEMENT_REJECTED'):
            continue
        actor_str = (slog.actor.get_full_name() or slog.actor.username) if slog.actor else "النظام"
        icon = 'edit_note'
        color = 'sky'
        title = slog.description or slog.action_type

        if 'UPDATE' in (slog.action_type or '') or slog.action == 'update':
            icon = 'edit'
            color = 'sky'
            title = 'تحديث بيانات الاتفاقية'
        elif 'STATUS' in (slog.action_type or ''):
            icon = 'tune'
            color = 'teal'
            title = 'تحديث حالة الاتفاقية'
        elif 'DELETE' in (slog.action_type or ''):
            icon = 'delete'
            color = 'rose'
            title = 'حذف الاتفاقية'

        events.append({
            'timestamp': slog.created_at,
            'title': title,
            'actor': actor_str,
            'icon': icon,
            'color': color,
            'details': slog.description or '',
            'previous_values': slog.previous_values if slog.previous_values else None,
            'new_values': slog.new_values if slog.new_values else None,
            'changes': None,
            'approval_required': False,
        })

    events.sort(key=lambda x: x['timestamp'] or timezone.now())
    return events


