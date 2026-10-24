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

