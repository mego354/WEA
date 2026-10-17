import os
import django
import sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.test import Client
from django.utils import timezone
from django.urls import reverse
from decimal import Decimal
from accounts.models import User, Role
from contacts.models import Contact, ContactAddress
from activities.models import Visit, VisitTemplate, PlannedVisitDay, PlannedVisitItem
from master_data.models import LocationSettings


def run_e2e_tests():
    print("=" * 65)
    print("STRICT REFERENCE-PARITY E2E SUITE: VISIT REGISTRATION & LOCATION")
    print("=" * 65)

    client = Client()

    # 1. Setup Users
    superadmin, _ = User.objects.get_or_create(
        username="superadmin_test",
        defaults={
            "email": "superadmin_test@wea.com",
            "first_name": "Super",
            "last_name": "Admin",
            "is_staff": True,
            "is_superuser": True
        }
    )
    superadmin.set_password("AdminPass123!")
    superadmin.save()

    rep_role, _ = Role.objects.get_or_create(
        name="med_rep_test",
        defaults={"display_name": "مندوب دعاية", "is_rep": True, "is_area_manager": False}
    )
    rep_user, _ = User.objects.get_or_create(
        username="rep_test",
        defaults={
            "email": "rep_test@wea.com",
            "first_name": "Ahmed",
            "last_name": "Rep",
            "role": rep_role,
            "is_staff": False,
            "is_superuser": False,
            "bypass_location_verification": False
        }
    )
    rep_user.set_password("RepPass123!")
    rep_user.bypass_location_verification = False
    rep_user.save()

    # 2. Location Settings Setup
    loc_settings = LocationSettings.get_settings()
    loc_settings.tolerance = 300
    loc_settings.max_verified_accuracy = 50
    loc_settings.max_verified_warn_accuracy = 100
    loc_settings.verify_visits = True
    loc_settings.auto_set_customer_location_in_visit = True
    loc_settings.save()
    print("  ✓ [1/7] Location Settings configured (tolerance: 300m, auto_set_customer_location: True)")

    # 3. Setup Customers
    # Customer A: with known GPS (Alexandria Sporting: 31.2156, 29.9245)
    cust_with_gps, _ = Contact.objects.get_or_create(
        code="CUST-GPS-01",
        defaults={
            "name": "صيدلية سبورتنج الحديثة",
            "is_customer": True,
            "status": "customer",
            "account_type": "Pharmacy",
            "customer_category": "A",
            "specialty": "Community",
            "latitude": Decimal("31.2156000"),
            "longitude": Decimal("29.9245000")
        }
    )
    cust_with_gps.latitude = Decimal("31.2156000")
    cust_with_gps.longitude = Decimal("29.9245000")
    cust_with_gps.is_customer = True
    cust_with_gps.status = "customer"
    cust_with_gps.save()
    cust_with_gps.set_location(Decimal("31.2156000"), Decimal("29.9245000"))

    # Customer B: WITHOUT GPS
    cust_no_gps, _ = Contact.objects.get_or_create(
        code="CUST-NOGPS-02",
        defaults={
            "name": "عيادة د. حسام النجار",
            "is_customer": True,
            "status": "customer",
            "account_type": "Clinic",
            "customer_category": "B",
            "specialty": "Cardiology"
        }
    )
    # Clear addresses if any
    cust_no_gps.addresses.all().delete()
    cust_no_gps.is_customer = True
    cust_no_gps.status = "customer"
    cust_no_gps.save()

    template, _ = VisitTemplate.objects.get_or_create(
        name="Single visit (DR)",
        defaults={"display_name_ar": "زيارة فردية لطبيب", "active": True}
    )

    # 4. Test Customer Search API
    client.login(username="superadmin_test", password="AdminPass123!")
    search_res = client.get("/contacts/api/search/?q=سبورتنج")
    assert search_res.status_code == 200, f"Search API failed with {search_res.status_code}"
    search_data = search_res.json().get("results", [])
    assert len(search_data) >= 1, "Expected at least 1 customer matching 'سبورتنج'"
    c_found = search_data[0]
    assert c_found["id"] == cust_with_gps.id, "Customer ID mismatch in search API"
    assert c_found["has_saved_location"] is True, "has_saved_location should be True"
    assert abs(float(c_found["latitude"]) - 31.2156) < 0.001, "Latitude mismatch"
    print(f"  ✓ [2/7] Customer Search API verified (returns {len(search_data)} customer with [Code] Name and GPS)")

    # 5. Test Visit Registration UI & Pre-selection
    # Test GET canonical form
    form_res = client.get(f"/visits/create/?contact_id={cust_with_gps.id}")
    assert form_res.status_code == 200, f"Visit create GET failed: {form_res.status_code}"
    assert "صيدلية سبورتنج الحديثة" in form_res.content.decode("utf-8"), "Customer name missing in visit form"
    assert "id_latitude" in form_res.content.decode("utf-8"), "id_latitude hidden input missing"
    assert "التحقق من الموقع الجغرافي" in form_res.content.decode("utf-8"), "GPS verification card missing"
    print("  ✓ [3/7] Canonical Visit Registration Form verified with prefilled customer card & GPS UI")

    # 6. Test Within-Geofence Visit Check-In (<= 300m)
    today = timezone.now().date().strftime("%Y-%m-%d")
    # Rep located 25 meters away: (31.2158, 29.9246)
    v_near_res = client.post("/visits/create/", {
        "contact": cust_with_gps.id,
        "owner": superadmin.id,
        "template": template.id,
        "date": today,
        "latitude": "31.2158000",
        "longitude": "29.9246000",
        "device_accuracy": "12.0",
        "is_successful": "on",
        "feedback": "زيارة ناجحة داخل النطاق المحدد (25م)"
    })
    assert v_near_res.status_code == 302, f"Expected redirect after visit create, got {v_near_res.status_code}"
    v_near = Visit.objects.filter(contact=cust_with_gps, owner=superadmin).order_by("-id").first()
    assert v_near is not None, "Visit record not created"
    assert v_near.location_verified is True, "Expected location_verified=True"
    assert v_near.verification_status == "verified", f"Expected 'verified', got {v_near.verification_status}"
    assert float(v_near.distance) <= 300.0, f"Expected distance <= 300m, got {v_near.distance}"
    assert "ضمن النطاق" in v_near.location_status, f"Expected 'ضمن النطاق', got {v_near.location_status}"
    print(f"  ✓ [4/7] Within-Geofence Visit Check-In: {v_near.distance}m -> verified ('{v_near.location_status}')")

    # 7. Test Outside-Geofence Visit Check-In for Non-Bypassed Rep (> 300m)
    client.login(username="rep_test", password="RepPass123!")
    # Rep located in Cairo (180 km away)
    v_far_res = client.post("/visits/create/", {
        "contact": cust_with_gps.id,
        "owner": rep_user.id,
        "template": template.id,
        "date": today,
        "latitude": "30.0444000",
        "longitude": "31.2357000",
        "device_accuracy": "25.0",
        "is_successful": "on",
        "feedback": "زيارة خارج النطاق لمندوب بدون استثناء"
    })
    assert v_far_res.status_code == 302
    v_far = Visit.objects.filter(contact=cust_with_gps, owner=rep_user).order_by("-id").first()
    assert v_far is not None, "Far visit not created"
    assert v_far.location_verified is False, "Expected location_verified=False for non-bypassed rep"
    assert v_far.verification_status == "unverified", f"Expected 'unverified', got {v_far.verification_status}"
    assert float(v_far.distance) > 100000.0, "Expected distance > 100km"
    assert "بعيد جدا" in v_far.location_status, f"Expected 'بعيد جدا', got {v_far.location_status}"
    print(f"  ✓ [5/7] Outside-Geofence Visit Check-In (Rep without bypass): {v_far.distance}m -> unverified ('{v_far.location_status}')")

    # 8. Test Auto-Set Customer GPS on First Visit
    client.login(username="superadmin_test", password="AdminPass123!")
    assert cust_no_gps.has_saved_location is False, "Customer should start with no saved location"
    v_first_res = client.post("/visits/create/", {
        "contact": cust_no_gps.id,
        "owner": superadmin.id,
        "template": template.id,
        "date": today,
        "latitude": "31.2005000",
        "longitude": "29.9125000",
        "device_accuracy": "8.0",
        "is_successful": "on",
        "feedback": "أول زيارة للعميل لتثبيت الإحداثيات تلقائياً"
    })
    assert v_first_res.status_code == 302
    cust_no_gps.refresh_from_db()
    assert cust_no_gps.has_saved_location is True, "Customer should have saved location after first visit"
    assert abs(float(cust_no_gps.latitude) - 31.2005) < 0.001, "Customer latitude not auto-set correctly"
    print(f"  ✓ [6/7] Auto-Set Customer GPS on First Visit: Saved ({cust_no_gps.latitude}, {cust_no_gps.longitude})")

    # 9. Test Superuser-Only Location Settings & Bypass Toggle
    # A. Rep tries to access /settings/location/ -> denied
    client.login(username="rep_test", password="RepPass123!")
    rep_sett_res = client.get("/settings/location/")
    assert rep_sett_res.status_code == 302, "Non-superuser should be redirected from /settings/location/"
    
    # B. Superadmin accesses and updates settings
    client.login(username="superadmin_test", password="AdminPass123!")
    admin_sett_res = client.get("/settings/location/")
    assert admin_sett_res.status_code == 200, f"Superadmin GET /settings/location/ failed: {admin_sett_res.status_code}"
    assert "معايير ودقة الموقع" in admin_sett_res.content.decode("utf-8")
    
    # C. Superadmin updates settings POST
    post_sett_res = client.post("/settings/location/", {
        "tolerance": 350,
        "max_verified_accuracy": 60,
        "max_verified_warn_accuracy": 120,
        "auto_set_customer_location_in_visit": "on",
        "verify_visits": "on"
    })
    assert post_sett_res.status_code == 302
    loc_settings.refresh_from_db()
    assert loc_settings.tolerance == 350, f"Expected tolerance 350, got {loc_settings.tolerance}"
    # Restore to 300
    loc_settings.tolerance = 300
    loc_settings.save()

    # D. User bypass toggle restriction
    client.login(username="rep_test", password="RepPass123!")
    rep_toggle_res = client.get(f"/auth/users/{rep_user.id}/toggle-bypass-location/")
    assert rep_toggle_res.status_code == 302
    rep_user.refresh_from_db()
    assert rep_user.bypass_location_verification is False, "Rep should not be able to toggle own bypass"

    client.login(username="superadmin_test", password="AdminPass123!")
    admin_toggle_res = client.get(f"/auth/users/{rep_user.id}/toggle-bypass-location/")
    assert admin_toggle_res.status_code == 302
    rep_user.refresh_from_db()
    assert rep_user.bypass_location_verification is True, "SuperAdmin should toggle bypass successfully"
    # Toggle back to False
    client.get(f"/auth/users/{rep_user.id}/toggle-bypass-location/")
    rep_user.refresh_from_db()
    assert rep_user.bypass_location_verification is False
    print("  ✓ [7/7] Superuser-only permissions strictly enforced for Location Settings & User Bypass")

    # 10. Visit Detail Location Card Parity Verification
    v_detail_res = client.get(f"/visits/{v_near.pk}/")
    assert v_detail_res.status_code == 200
    detail_html = v_detail_res.content.decode("utf-8")
    assert "التحقق من الموقع" in detail_html, "Location verification section missing from visit detail"
    assert "المسافة:" in detail_html, "Distance label missing"
    assert "حالة الاستكمال:" in detail_html, "Completion status missing"
    assert "حالة الموقع:" in detail_html, "Location status missing"
    assert "gpp_good" in detail_html or "gpp_maybe" in detail_html, "Verification shield icon missing"
    assert "Google Maps" in detail_html, "Google Maps link missing"
    print(f"  ✓ Visit #{v_near.serial_num} detail page location verification card verified")

    # 11. Contact Dossier "تسجيل زيارة" Action Button Parity Verification
    contact_res = client.get(f"/contacts/{cust_with_gps.id}/")
    assert contact_res.status_code == 200
    contact_html = contact_res.content.decode("utf-8")
    assert f"/visits/create/?contact_id={cust_with_gps.id}" in contact_html, "Register visit link missing on customer dossier"
    assert "الموقع الجغرافي (GPS)" in contact_html, "GPS coordinates missing from contact overview"
    print(f"  ✓ Contact dossier #{cust_with_gps.id} 'تسجيل زيارة' button & GPS coordinates row verified")

    print("=" * 65)
    print("ALL 7 PARITY CATEGORIES VERIFIED WITH 100% SUCCESS!")
    print("=" * 65)


if __name__ == "__main__":
    run_e2e_tests()
