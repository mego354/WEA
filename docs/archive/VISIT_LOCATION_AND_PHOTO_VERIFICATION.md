# Visit Location and Photo Verification Specification

## 1. Executive Summary & Problem Statement
In field medical sales, verifying representative presence at customer clinics, pharmacies, and hospitals is essential for compliance and auditing. GPS coordinates alone can occasionally be faked via browser emulation or software spoofers.

To guarantee physical attendance:
1. **Dual Evidence Verification**: Representatives must satisfy **both** GPS geofencing (within the verified 300-meter tolerance) and capture a **live photograph** as evidence of the visit location.
2. **Strict Superuser Bypass**: Superusers and authorized administrators may bypass location and photo capture (e.g. when checking in from inside basement hospital wards where GPS/cell signal is unreachable), with mandatory audit logging (`bypassed_by`, `bypassed_at`, `bypass_reason`).
3. **Data Protection**: Uploaded evidence photos are stored securely, scanned for integrity, and protected behind authentication (`visit_evidence_photo` endpoint) to prevent unauthorized public exposure.

---

## 2. Geofence & Tolerance Rules
- **Standard Geofence Radius**: **300 meters** (configurable globally via `LocationSettings.tolerance`).
- **Haversine Distance**: Computed in meters using the standard spherical earth radius (6,371,000 meters).
- **Auto-Setting First Customer Location**: If a customer has no recorded GPS coordinates in the database, the coordinates of the first approved visit are automatically captured and saved to `Contact.latitude` and `Contact.longitude` with status `no_customer_location` / `تم حفظ موقع العميل بشكل تلقائي مع أول زيارة`.
- **Location Statuses**:
  - `verified`: Visit recorded within tolerance (<= 300m).
  - `unverified`: Visit recorded outside tolerance (> 300m) without bypass authorization.
  - `force_bypassed`: Superuser administrative override.
  - `no_customer_location`: First visit capturing customer location.

---

## 3. Photo Evidence Architecture

### 3.1 Model Fields (`Visit`)
In [activities/models.py](file:///c:/D/Cooding/GENERAL/new/ERP/activities/models.py):
```python
location_photo = models.ImageField(
    upload_to='activities/evidence/%Y/%m/',
    null=True, blank=True,
    help_text="صورة ملتقطة كإثبات لموقع الزيارة الحالية"
)
photo_captured_at = models.DateTimeField(null=True, blank=True)
bypassed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='bypassed_visits')
bypassed_at = models.DateTimeField(null=True, blank=True)
bypass_reason = models.CharField(max_length=255, blank=True)
```

### 3.2 File Validation Service (`validate_and_save_photo_evidence`)
In [activities/services.py](file:///c:/D/Cooding/GENERAL/new/ERP/activities/services.py):
1. **Extension Whitelist**: `.jpg`, `.jpeg`, `.png`, `.webp`.
2. **Size Constraint**: Maximum **10 MB**.
3. **MIME & Integrity Check**: Pillow `Image.open(photo_file).verify()` ensures the uploaded file is a valid image and not an executable or corrupted payload.
4. **UUID Filename Generation**: Files are saved with cryptographically secure UUID filenames (`evidence_<uuid>.<ext>`) to prevent path traversal and overwrite attacks.

### 3.3 Mobile Camera Capture UI
In [templates/activities/visit_detail.html](file:///c:/D/Cooding/GENERAL/new/ERP/templates/activities/visit_detail.html):
```html
<input type="file" name="location_photo" id="location-photo-file" accept="image/*" capture="environment" class="hidden" onchange="previewCapturedPhoto(event)">
```
- `capture="environment"` instructs mobile browsers (iOS Safari, Android Chrome) to open the rear camera directly.
- Instant JavaScript `FileReader` preview card with "إعادة التقاط الصورة" (Retake) button.

---

## 4. Protected Media Endpoint (`visit_evidence_photo`)
To protect representative privacy and prevent unauthorized downloads:
```python
path('visits/<int:pk>/evidence/photo/', views.visit_evidence_photo, name='visit_evidence_photo')
```
- **Authorized**:
  - Visit owner (conducted by)
  - Visit creator
  - Area manager / Supervisor
  - Superusers & staff
- **Unauthorized**:
  - Returns `403 Forbidden` (`عذراً، غير مصرح لك بالوصول إلى صورة الإثبات الخاصة بمستخدم آخر`).
- **File Serving**:
  - Streams the image via Django `FileResponse` with correct MIME headers.

---

## 5. Superuser Bypass & Audit Record
Superusers can check the bypass box on `/visits/<id>/` when completing:
- Backend verifies `request.user.is_superuser or is_super_admin or can_bypass_location`.
- Sets:
  - `verification_status = 'force_bypassed'`
  - `bypassed_by = request.user`
  - `bypassed_at = timezone.now()`
  - `bypass_reason = request.POST.get('bypass_reason')`
- Completed dossier displays a yellow audit badge:
  `تم التجاوز بموافقة إدارية بواسطة [اسم المشرف] في [التاريخ والوقت] - السبب: [السبب]`
