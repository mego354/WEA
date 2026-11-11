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
        lat1 = float(lat1)
        lon1 = float(lon1)
        lat2 = float(lat2)
        lon2 = float(lon2)
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


def validate_and_save_photo_evidence(visit, photo_file, max_size_mb=10):
    """
    Business Rule (Requirement 7):
    Validates uploaded location photo evidence:
    - Allowed extensions: .jpg, .jpeg, .png, .webp
    - File size <= 10MB
    - Image format / integrity check via Pillow
    - Generates a safe, non-guessable filename with UUID
    - Stores file in visit.location_photo
    """
    if not photo_file:
        return None

    ext = os.path.splitext(photo_file.name)[1].lower()
    allowed_exts = ['.jpg', '.jpeg', '.png', '.webp']
    if ext not in allowed_exts:
        raise ValidationError(f"نوع الملف غير مدعوم ({ext}). يُسمح فقط بالصور: JPG, JPEG, PNG, WEBP.")

    max_bytes = max_size_mb * 1024 * 1024
    if photo_file.size > max_bytes:
        raise ValidationError(f"حجم ملف الصورة يتجاوز الحد المسموح به ({max_size_mb} ميجابايت).")

    # Image integrity check
    try:
        img = Image.open(photo_file)
        img.verify()
        photo_file.seek(0)
    except Exception:
        raise ValidationError("ملف الصورة تالف أو لا يمثل صورة صالحة.")

    # Generate safe filename
    safe_name = f"{uuid.uuid4().hex}{ext}"
    photo_file.name = safe_name
    visit.location_photo = photo_file
    visit.photo_captured_at = timezone.now()
    return photo_file


def verify_visit_location(visit, user, contact, visit_lat=None, visit_lng=None, device_accuracy=None,
                          photo_file=None, force_bypass=False, bypass_reason='',
                          stage='create', request_distance_exception=False, strict_distance=False):
    """
    Applies the ERP location and distance verification policy across visit creation and completion:
    1. Dynamically determines allowed distance threshold:
       - Uses template's special_tolerance if allow_template_distance_override is enabled and configured on template.
       - Otherwise uses default LocationSettings.tolerance.
    2. Compares user's current GPS coordinates against client's registered coordinates.
    3. Records actual distance, allowed threshold, and distance discrepancy on the visit.
    4. Handles authorized bypass (Manager / Superadmin / configured roles) without requiring extra approval.
    5. Handles unauthorized user (Representative) exception requests with mandatory reason and submits for manager approval.
    """
    settings = LocationSettings.get_settings()
    template = getattr(visit, 'template', None)
    tolerance = settings.get_effective_tolerance(template)
    visit.allowed_distance = Decimal(str(round(float(tolerance), 2)))

    # Convert coordinates if passed
    if visit_lat is not None and visit_lng is not None and str(visit_lat).strip() != '' and str(visit_lng).strip() != '':
        try:
            visit.latitude = Decimal(str(visit_lat))
            visit.longitude = Decimal(str(visit_lng))
        except Exception:
            pass

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

    can_bypass_directly = settings.can_user_bypass_without_approval(user, stage=stage)
    is_super = bool(getattr(user, 'is_superuser', False) or getattr(user, 'is_super_admin', False))
    bypass_reason_clean = (bypass_reason or '').strip()

    # Handle Photo Evidence if uploaded
    if photo_file:
        validate_and_save_photo_evidence(visit, photo_file)

    # Check if verification is active for this stage
    stage_verify_enabled = settings.verify_visits
    if stage == 'create':
        if getattr(visit, 'is_planned', False):
            # Requirement 3.B: Planned visits do NOT require distance validation during creation
            stage_verify_enabled = False
        elif not settings.verify_unplanned_visit_distance:
            stage_verify_enabled = False
    elif stage == 'end':
        if not settings.verify_end_visit_distance:
            stage_verify_enabled = False

    # Handle explicit bypass / exception request
    if force_bypass or request_distance_exception:
        if can_bypass_directly:
            if settings.bypass_reason_mandatory and not bypass_reason_clean:
                raise ValidationError("يرجى إدخال سبب تجاوز المسافة المسموح بها (ذكر السبب إلزامي حسب إعدادات النظام).")
            visit.location_verified = True
            visit.verification_status = 'force_bypassed'
            if dist is not None and dist > tolerance:
                visit.location_status = 'بعيد جدا عن الموقع المحدد (تم التجاوز بصلاحية إدارية)'
            else:
                visit.location_status = 'تم تجاهل التحقق بالقوة بواسطة المشرف'
            visit.bypassed_by = user
            visit.bypassed_at = timezone.now()
            visit.bypass_reason = bypass_reason_clean or 'تجاوز مصرح به من الإدارة / المشرف'
            return visit
        else:
            # Representative / unauthorized user requesting an exception -> requires reason & manager approval
            if not bypass_reason_clean:
                raise ValidationError("يرجى توضيح سبب التواجد خارج المسافة المسموح بها لتقديم طلب استثناء لاعتماد المدير.")
            visit.location_verified = False
            visit.verification_status = 'unverified'
            visit.location_status = (
                f"خارج النطاق المسموح ({visit.distance}م / المسموح {tolerance}م) - بانتظار اعتماد الاستثناء"
                if visit.distance is not None else
                "طلب استثناء موقع جغرافي - بانتظار اعتماد المدير"
            )
            visit.bypassed_by = user
            visit.bypassed_at = timezone.now()
            visit.bypass_reason = bypass_reason_clean
            if settings.distance_bypass_requires_approval:
                visit.requires_approval_due_to_distance = True
                visit.approval_status = 'pending'
            return visit

    # If verification is disabled for this stage or globally
    if not stage_verify_enabled:
        if dist is not None:
            if dist <= tolerance:
                visit.location_verified = True
                visit.verification_status = 'verified'
                visit.location_status = 'ضمن النطاق المحدد'
            else:
                visit.location_verified = False
                visit.verification_status = 'unverified'
                visit.location_status = 'تخطيط مسبق (يتم التحقق من المسافة عند إنهاء الزيارة)' if getattr(visit, 'is_planned', False) else 'التحقق معطل في الإعدادات العامة'
        else:
            visit.location_verified = True
            visit.verification_status = 'verified'
            visit.location_status = 'زيارة مخططة (لا يتطلب التحقق من المسافة عند الإنشاء)' if getattr(visit, 'is_planned', False) else 'التحقق معطل في الإعدادات العامة'
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
        else:
            visit.location_verified = False
            visit.verification_status = 'unverified'
            visit.location_status = 'تعذر تحديد موقع الجهاز'
            if strict_distance:
                raise ValidationError("تحديد الموقع الجغرافي (GPS) إلزامي للتحقق من المسافة. يرجى تفعيل الموقع أو طلب استثناء مع ذكر السبب.")
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
                if can_bypass_directly:
                    if settings.bypass_reason_mandatory and not is_super and not bypass_reason_clean:
                        raise ValidationError(
                            f"المسافة الحالية ({visit.distance} متر) تتجاوز المسافة المسموح بها ({tolerance} متر). يرجى إدخال سبب التجاوز للمتابعة."
                        )
                    visit.location_verified = True
                    visit.verification_status = 'force_bypassed'
                    visit.location_status = 'بعيد جدا عن الموقع المحدد'
                    visit.bypassed_by = user
                    visit.bypassed_at = timezone.now()
                    visit.bypass_reason = bypass_reason_clean or 'الموقع خارج النطاق المحدد'
                else:
                    visit.location_verified = False
                    visit.verification_status = 'unverified'
                    visit.location_status = 'بعيد جدا عن الموقع المحدد'
                    if strict_distance:
                        raise ValidationError(
                            f"أنت خارج النطاق الجغرافي المسموح به للعميل (المسافة الحالية: {visit.distance} متر، المسافة المسموح بها: {tolerance} متر). "
                            "للمتابعة، يرجى طلب استثناء تجاوز المسافة مع كتابة سبب واضح لاعتماد المدير."
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
        if can_bypass_directly:
            visit.location_verified = True
            visit.verification_status = 'force_bypassed'
            visit.location_status = 'لا يوجد موقع مسجل للعميل (تم التجاوز)'
            visit.bypassed_by = user
            visit.bypassed_at = timezone.now()
            visit.bypass_reason = bypass_reason_clean or 'لا يوجد موقع مسجل للعميل'
        else:
            visit.location_verified = False
            visit.verification_status = 'unverified'
            visit.location_status = 'لا يوجد موقع مسجل للعميل'
        return visit


# =============================================================================
# STANDARDIZED VISIT LIFECYCLE SERVICE FUNCTIONS (STATE MACHINE)
# =============================================================================

def can_start_visit(visit, user):
    """
    Validates whether a user is authorized to start the visit (Check-in).
    Preconditions:
    1. Visit status must be 'planned'.
    2. Visit approval_status must be 'approved'.
    3. User must be the assigned owner or creator (or superuser / authorized supervisor).
    4. User's role must be eligible for the visit's template.
    """
    if not user or not user.is_authenticated:
        return False, "يجب تسجيل الدخول لبدء الزيارة."

    is_owner = (visit.owner_id == user.id or visit.created_by_id == user.id)
    from accounts.permissions import has_perm_or_admin
    from accounts.scope_service import ScopeResolutionService
    can_manage = (
        user.is_superuser or
        getattr(user, 'is_super_admin', False) or
        has_perm_or_admin(user, 'activities:visits/manage') or
        ScopeResolutionService.get_user_scope(user, 'activities', 'manage') in ['area', 'all']
    )
    if not (is_owner or can_manage):
        return False, "غير مصرح لك ببدء هذه الزيارة (فقط المندوب المسؤول أو المشرف المصرح له)."

    if visit.template and not visit.template.is_user_eligible(user):
        return False, f"دورك الوظيفي ({getattr(user, 'role_name', 'مستخدم')}) غير مصرح له باستخدام قالب الزيارة '{visit.template.display_name_ar}'."

    if visit.status != 'planned':
        return False, f"لا يمكن بدء الزيارة لأن حالتها الحالية '{visit.status_display_ar}' وليست 'مخططة'."

    if visit.approval_status != 'approved':
        return False, "لا يمكن بدء الزيارة قبل اعتمادها رسمياً من المدير المسؤول."

    return True, ""


def start_visit(visit, user, request=None, lat=None, lng=None, accuracy=None, photo_file=None, force_bypass=False, bypass_reason='', checkin_answers=None):
    """
    Executes explicit Start Visit / Check-in transition:
    planned (approved) -> started
    Captures server-side started_at timestamp, applies GPS check-in verification if provided/required,
    validates and saves check-in questionnaire answers (stage='start_only'),
    and records an audit log entry.
    """
    from django.db import transaction
    from activities.models import Visit, ApprovalAuditLog

    with transaction.atomic():
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

        # Process GPS check-in if coordinates provided
        if lat is not None or lng is not None or photo_file or force_bypass:
            verify_visit_location(
                visit, user, visit.contact,
                visit_lat=lat, visit_lng=lng, device_accuracy=accuracy,
                photo_file=photo_file, force_bypass=force_bypass, bypass_reason=bypass_reason,
                stage='create'
            )

        status_before = visit.status
        visit.status = 'started'
        visit.started_at = timezone.now()
        visit.questionnaire_answers = saved_answers
        visit.save()

        ip = request.META.get('REMOTE_ADDR') if request else None
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


def save_visit_answers(visit, user, answers, feedback='', detailed_product_ids=None):
    """
    Saves draft answers and detailing during an active visit without completing/ending it.
    Visit status strictly remains 'started'.
    """
    from django.db import transaction
    from catalog.models import Product

    can_submit, err = can_submit_answers(visit, user)
    if not can_submit:
        raise ValidationError(err)

    with transaction.atomic():
        visit.questionnaire_answers = answers or {}
        if feedback:
            visit.feedback = feedback

        if visit.template and visit.template.is_product_detailing_supported():
            if detailed_product_ids is not None:
                eligible_ids = set(Product.get_eligible_for_visits().values_list('id', flat=True))
                historical_ids = set(visit.detailed_products.values_list('id', flat=True))
                allowed_ids = eligible_ids | historical_ids
                valid_ids = [int(pid) for pid in detailed_product_ids if str(pid).isdigit() and int(pid) in allowed_ids]
                visit.detailed_products.set(valid_ids)
        else:
            visit.detailed_products.clear()

        visit.save()
        return visit


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


def end_visit(visit, user, request=None, answers=None, feedback='', detailed_product_ids=None,
              lat=None, lng=None, accuracy=None, photo_file=None, force_bypass=False, bypass_reason='',
              visit_outcome='', request_distance_exception=False):
    """
    Executes explicit End Visit / Check-out transition:
    started -> finished
    Captures server-side ended_at timestamp, calculates duration on the server,
    verifies GPS and photo evidence, updates planned items if applicable, and logs audit.
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
            visit.questionnaire_answers = answers

        if feedback:
            visit.feedback = feedback

        if visit_outcome:
            visit.visit_outcome = visit_outcome
            visit.is_successful = (visit_outcome == 'successful')

        # Product detailing
        if visit.template and visit.template.is_product_detailing_supported():
            if detailed_product_ids is not None:
                eligible_ids = set(Product.get_eligible_for_visits().values_list('id', flat=True))
                historical_ids = set(visit.detailed_products.values_list('id', flat=True))
                allowed_ids = eligible_ids | historical_ids
                valid_ids = [int(pid) for pid in detailed_product_ids if str(pid).isdigit() and int(pid) in allowed_ids]
                visit.detailed_products.set(valid_ids)
        else:
            visit.detailed_products.clear()

        approval_before = visit.approval_status
        # Location & photo verification for completion stage
        verify_visit_location(
            visit, user, visit.contact,
            visit_lat=lat if lat is not None else visit.latitude,
            visit_lng=lng if lng is not None else visit.longitude,
            device_accuracy=accuracy if accuracy is not None else visit.device_accuracy,
            photo_file=photo_file, force_bypass=force_bypass, bypass_reason=bypass_reason,
            stage='end', request_distance_exception=request_distance_exception, strict_distance=True
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

        if visit.requires_approval_due_to_distance:
            ApprovalAuditLog.objects.create(
                record_type='visit',
                visit=visit,
                action='distance_exception_requested',
                actor=user,
                status_before=approval_before,
                status_after='pending',
                reason=(
                    f"طلب استثناء مسافة عند إنهاء الزيارة (المسافة الفعلية: {visit.distance}م، المسموح: {visit.allowed_distance}م). "
                    f"السبب: {visit.bypass_reason}"
                ),
                ip_address=ip
            )
            AuditLogService.log(
                action_type='VISIT_DISTANCE_EXCEPTION_REQUESTED',
                module='visits',
                actor=user,
                request=request,
                record_id=visit.pk,
                record_name=str(visit.serial_num),
                description=f"طلب استثناء تجاوز المسافة للزيارة #{visit.serial_num} وتحويلها لاعتماد المدير",
                previous_values={'approval_status': approval_before},
                new_values={
                    'approval_status': visit.approval_status,
                    'distance': str(visit.distance or ''),
                    'allowed_distance': str(visit.allowed_distance or ''),
                    'bypass_reason': visit.bypass_reason,
                },
                status='SUCCESS',
            )
        elif visit.verification_status == 'force_bypassed':
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
            title = 'تعديل بعد الاعتماد — تتطلب إعادة اعتماد المدير'
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

        events.append({
            'timestamp': log.created_at,
            'title': title,
            'actor': actor_str,
            'icon': icon,
            'color': color,
            'details': log.reason or f"تغيير الحالة من ({log.status_before or '-'}) إلى ({log.status_after or '-'}).",
            'previous_values': {'الحالة السابقة': log.status_before} if log.status_before else None,
            'new_values': {'الحالة الجديدة': log.status_after} if log.status_after else None,
        })

    # 3. SecurityAuditLog entries for edits, distance validations, and answers
    sec_logs = SecurityAuditLog.objects.filter(
        module__in=['visits', 'activities'],
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
        elif 'UPDATE' in (slog.action_type or '') or slog.action_type == 'update':
            icon = 'edit'
            color = 'sky'
            title = 'تحديث بيانات وإجابات الزيارة'
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
    return events

