import math
from decimal import Decimal
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


def verify_visit_location(visit, user, contact, visit_lat=None, visit_lng=None, device_accuracy=None):
    """
    Applies the reference ERP location verification policy:
    1. Checks LocationSettings tolerance (default 300m) and verification policy.
    2. Compares visit GPS coordinates against saved customer coordinates.
    3. Handles auto-setting customer location on first check-in.
    4. Handles superuser/role bypass policies ("تم تجاهل التحقق بالقوة").
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

    customer_lat = contact.latitude
    customer_lng = contact.longitude

    visit.customer_latitude_snapshot = customer_lat
    visit.customer_longitude_snapshot = customer_lng

    can_bypass = getattr(user, 'can_bypass_location', False) or user.is_superuser or getattr(user, 'is_super_admin', False)

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
            visit.location_status = 'تعذر تحديد موقع الجهاز (تم تجاهل التحقق بالقوة)'
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
        else:
            visit.location_verified = False
            visit.verification_status = 'unverified'
            visit.location_status = 'لا يوجد موقع مسجل للعميل'
        return visit
