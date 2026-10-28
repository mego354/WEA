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
                          photo_file=None, force_bypass=False, bypass_reason=''):
    """
    Applies the reference ERP location verification policy:
    1. Checks LocationSettings tolerance (default 300m) and verification policy.
    2. Compares visit GPS coordinates against saved customer coordinates.
    3. Handles auto-setting customer location on first check-in.
    4. Validates and saves location photo evidence.
    5. Handles superuser/role bypass policies with audit trail ("تم تجاهل التحقق بالقوة").
    """
    settings = LocationSettings.get_settings()
    tolerance = settings.tolerance

    # Convert coordinates if passed
    if visit_lat is not None and visit_lng is not None:
        try:
            visit.latitude = Decimal(str(visit_lat))
            visit.longitude = Decimal(str(visit_lng))
        except Exception:
            pass

    if device_accuracy is not None:
        try:
            visit.device_accuracy = Decimal(str(device_accuracy))
        except Exception:
            pass

    customer_lat = getattr(contact, 'latitude', None)
    customer_lng = getattr(contact, 'longitude', None)

    visit.customer_latitude_snapshot = customer_lat
    visit.customer_longitude_snapshot = customer_lng

    can_bypass = getattr(user, 'can_bypass_location', False) or user.is_superuser or getattr(user, 'is_super_admin', False)

    # Handle Photo Evidence if uploaded
    if photo_file:
        validate_and_save_photo_evidence(visit, photo_file)

    # Handle Superuser Force Bypass
    if force_bypass:
        if not can_bypass:
            raise ValidationError("غير مصرح لك بتجاوز التحقق من الموقع أو صورة الإثبات.")
        visit.location_verified = True
        visit.verification_status = 'force_bypassed'
        visit.location_status = 'تم تجاهل التحقق بالقوة بواسطة المشرف'
        visit.bypassed_by = user
        visit.bypassed_at = timezone.now()
        visit.bypass_reason = bypass_reason or 'تجاوز مصرح به من مدير النظام'
        return visit

    # If verification is disabled in global settings
    if not settings.verify_visits:
        visit.location_verified = True
        visit.verification_status = 'verified'
        visit.location_status = 'التحقق معطل في الإعدادات العامة'
        return visit

    # Case 1: Device location unavailable
    if visit.latitude is None or visit.longitude is None:
        if can_bypass:
            visit.location_verified = True
            visit.verification_status = 'force_bypassed'
            visit.location_status = 'تم تجاهل التحقق بالقوة - تعذر تحديد موقع الجهاز'
            visit.bypassed_by = user
            visit.bypassed_at = timezone.now()
            visit.bypass_reason = bypass_reason or 'تعذر تحديد موقع الجهاز'
        else:
            visit.location_verified = False
            visit.verification_status = 'unverified'
            visit.location_status = 'تعذر تحديد موقع الجهاز'
        return visit

    # Case 2: Customer has saved GPS coordinates
    if customer_lat is not None and customer_lng is not None:
        dist = calculate_haversine_distance(visit.latitude, visit.longitude, customer_lat, customer_lng)
        if dist is not None:
            visit.distance = Decimal(str(round(dist, 2)))

            if dist <= tolerance:
                visit.location_verified = True
                visit.verification_status = 'verified'
                visit.location_status = 'ضمن النطاق المحدد'
            else:
                if can_bypass:
                    visit.location_verified = True
                    visit.verification_status = 'force_bypassed'
                    visit.location_status = 'بعيد جدا عن الموقع المحدد'
                    visit.bypassed_by = user
                    visit.bypassed_at = timezone.now()
                    visit.bypass_reason = bypass_reason or 'الموقع خارج النطاق المحدد'
                else:
                    visit.location_verified = False
                    visit.verification_status = 'unverified'
                    visit.location_status = 'بعيد جدا عن الموقع المحدد'
        return visit

    # Case 3: Customer has NO saved GPS coordinates
    if settings.auto_set_customer_location_in_visit and visit.latitude is not None and visit.longitude is not None:
        # Auto-set customer's location from this first visit
        contact.set_location(visit.latitude, visit.longitude)
        visit.customer_latitude_snapshot = visit.latitude
        visit.customer_longitude_snapshot = visit.longitude
        visit.distance = Decimal('0.00')
        visit.location_verified = True
        visit.verification_status = 'verified'
        visit.location_status = 'تم حفظ موقع العميل بشكل تلقائي مع أول زيارة'
        return visit
    else:
        if can_bypass:
            visit.location_verified = True
            visit.verification_status = 'force_bypassed'
            visit.location_status = 'لا يوجد موقع مسجل للعميل (تم التجاوز)'
            visit.bypassed_by = user
            visit.bypassed_at = timezone.now()
            visit.bypass_reason = bypass_reason or 'لا يوجد موقع مسجل للعميل'
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
    can_manage = (
        user.is_superuser or
        getattr(user, 'is_super_admin', False) or
        bool(user.role and user.role.is_manager_role)
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


def start_visit(visit, user, request=None, lat=None, lng=None, accuracy=None, photo_file=None, force_bypass=False, bypass_reason=''):
    """
    Executes explicit Start Visit / Check-in transition:
    planned (approved) -> started
    Captures server-side started_at timestamp, applies GPS check-in verification if provided/required,
    and records an audit log entry.
    """
    from django.db import transaction
    from activities.models import Visit, ApprovalAuditLog

    with transaction.atomic():
        visit = Visit.objects.select_for_update().get(pk=visit.pk)
        can_start, err = can_start_visit(visit, user)
        if not can_start:
            raise ValidationError(err)

        # Process GPS check-in if coordinates provided
        if lat is not None or lng is not None:
            verify_visit_location(
                visit, user, visit.contact,
                visit_lat=lat, visit_lng=lng, device_accuracy=accuracy,
                photo_file=photo_file, force_bypass=force_bypass, bypass_reason=bypass_reason
            )

        status_before = visit.status
        visit.status = 'started'
        visit.started_at = timezone.now()
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

    # Validate required questions
    effective_answers = answers if answers is not None else (visit.questionnaire_answers or {})
    if visit.template:
        questions = visit.template.get_active_questions()
        for q in questions:
            # Check conditional logic
            if q.is_conditional and q.conditional_parent_id:
                parent_val = effective_answers.get(str(q.conditional_parent_id), '')
                trigger_val = (q.conditional_trigger_value or '').strip().lower()
                if str(parent_val).strip().lower() != trigger_val:
                    continue  # Question was not active

            if q.is_required:
                ans = effective_answers.get(str(q.id))
                if ans is None or ans == '' or ans == []:
                    return False, f"السؤال '{q.text_ar}' إلزامي لإتمام الزيارة."

    return True, ""


def end_visit(visit, user, request=None, answers=None, feedback='', detailed_product_ids=None,
              lat=None, lng=None, accuracy=None, photo_file=None, force_bypass=False, bypass_reason='',
              visit_outcome=''):
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

        # Location & photo verification
        verify_visit_location(
            visit, user, visit.contact,
            visit_lat=lat if lat is not None else visit.latitude,
            visit_lng=lng if lng is not None else visit.longitude,
            device_accuracy=accuracy if accuracy is not None else visit.device_accuracy,
            photo_file=photo_file, force_bypass=force_bypass, bypass_reason=bypass_reason
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
        return visit

