# تقرير اختبارات التحقق من الموقع الجغرافي (GPS) والصلاحيات المبنية على الأدوار
## GPS Role-Based Validation & Security Authorization Test Suite

### 1. نظرة عامة وقواعد التحقق المعتمدة
وفقاً لمتطلبات التطبيق المرجعي ([https://weapharma.bricks-rep.com](https://weapharma.bricks-rep.com)) وقواعد العمل الصارمة:
1. **مندوبو الدعاية والمبيعات (Medical / Sales Representatives)**:
   - تحديد الموقع الجغرافي (GPS) إلزامي تماماً عند تسجيل أي زيارة ميدانية طالما أن إعداد التحقق مفعل في [`LocationSettings.verify_visits`](file:///c:/D/Cooding/GENERAL/new/ERP/master_data/models.py).
   - يتم احتساب المسافة الحقيقية للزيارة باستخدام معادلة Haversine بين إحداثيات الجهاز الفعلية وموقع العميل المسجل.
   - إذا كانت المسافة $\le 300$ متر، تصبح الزيارة معتمدة جغرافياً (`verified`).
   - إذا كانت المسافة $> 300$ متر، تسجل كزيارة غير معتمدة جغرافياً (`unverified`).
   - في حال تعذر الحصول على الإحداثيات (رفض الإذن، انتهاء المهلة، أو عدم توفر الإشارة)، يُمنع المندوب تماماً من التسجيل، ويرفض الخادم حفظ الزيارة.
   - لا يمكن للمندوب تجاوز هذا التحقق عن طريق التلاعب بكود الجافاسكريبت، أو تعديل حقول النموذج، أو استدعاء نقطة النهاية (API) مباشرة.
2. **المشرف العام والمدراء (Superusers & SuperAdmins)**:
   - يتاح للمشرف العام تجاوز شرط الموقع الجغرافي استثنائياً (`force_bypassed` - "تم تجاهل التحقق بالقوة") مع توثيق الاستثناء في سجل تدقيق الزيارة.
   - يعتمد الاستثناء حصراً على التحقق من هوية المستخدم المسجلة في الجلسة على الخادم (`request.user.is_superuser` أو `request.user.can_bypass_location`).
   - يظل التحقق الإلزامي من الحقول الجوهرية الأخرى (مثل العميل والتاريخ) فعالاً ويرفض أي بيانات ناقصة أو غير صالحة.
   - يتم إحباط أي محاولة تزييف صلاحيات من قبل مستخدم غير مخول عبر معلمات الطلب (`request.POST`).

---

### 2. مصفوفة الاختبارات الإلزامية (Required GPS Test Matrix)

| # | المستخدم والسيناريو | السلوك المتوقع | النتيجة الفعلية | الحالة (Status) |
| :-: | :--- | :--- | :--- | :-: |
| **1** | **مندوب (Representative)، موقع صحيح داخل النطاق ($\le 300$م)** | التحقق بنجاح واعتماد الموقع `verified` مع احتساب المسافة الحقيقية. | تم التحقق، مسافة 15.2م، الحالة `verified` ("ضمن النطاق المحدد"). | **PASS — VERIFIED** |
| **2** | **مندوب، رفض إذن المتصفح (Permission Denied)** | إظهار رسالة خطأ صريحة، ومنع الحفظ من جانب الخادم والواجهة. | رفض الخادم الطلب برسالة إلزامية الـ GPS، ولم يتم إنشاء سجل الزيارة. | **PASS — VERIFIED** |
| **3** | **مندوب، تعذر تحديد الموقع أو انتهاء المهلة (Timeout / Unavailable)** | إظهار الخطأ الدقيق ومنع الحفظ من الخادم والواجهة. | تم رفض الطلب وأعيد عرض النموذج مع رسالة الخطأ الصريحة. | **PASS — VERIFIED** |
| **4** | **مندوب، إحداثيات مفقودة أو غير صالحة (Invalid / Out of bounds)** | رفض الطلب بواسطة `VisitForm.clean()` عند تقديم إحداثيات غير منطقية. | رفض الخادم إحداثيات خط العرض 999.0 برمز خطأ تحققي ولم تنشأ زيارة. | **PASS — VERIFIED** |
| **5** | **مندوب، طلب API / AJAX مباشر بدون إحداثيات صالحة** | إرجاع رمز خطأ HTTP 400 Bad Request مع تفاصيل الخطأ بصيغة JSON. | رد الخادم برمز `400` مع مصفوفة أخطاء JSON واضحة وموثقة. | **PASS — VERIFIED** |
| **6** | **مشرف عام (Superuser)، تعذر توفر الـ GPS** | السماح بالمتابعة وحفظ الزيارة مع توثيق التجاوز (`force_bypassed`). | تم الحفظ بنجاح، ووثقت الحالة: `تعذر تحديد موقع الجهاز (تم تجاهل التحقق بالقوة)`. | **PASS — VERIFIED** |
| **7** | **مشرف عام، رفض إذن الـ GPS** | السماح بالمتابعة وحفظ الزيارة تحت مظلة الصلاحية الاستثنائية. | تم إنشاء الزيارة بنجاح بحالة `force_bypassed`. | **PASS — VERIFIED** |
| **8** | **مشرف عام، حقول إلزامية أخرى مفقودة (مثل العميل)** | رفض الطلب وإظهار أخطاء التحقق القياسية للنموذج. | رفض الخادم الحفظ لأن حقل العميل مطلوب، ولم يتجاوز المشرف الحقول الأساسية. | **PASS — VERIFIED** |
| **9** | **مندوب عادي يحاول انتحال صفة مشرف عبر بيانات الطلب (Impersonation)** | رفض محاولة التجاوز فوراً وتطبيق قواعد المندوب الصارمة. | تجاهل الخادم معلمات `is_superuser` في الـ POST ورفض الزيارة لعدم وجود GPS. | **PASS — VERIFIED** |

---

### 3. تفاصيل بنية الحماية والأمان على الخادم (Server-Side Security Enforcement)

#### 1. التحقق في `VisitForm.clean()`:
```python
# activities/forms.py
def clean(self):
    cleaned_data = super().clean()
    lat = cleaned_data.get('latitude')
    lng = cleaned_data.get('longitude')
    settings = LocationSettings.get_settings()

    # يتم الفحص حصراً من كائن المستخدم الموثق في الجلسة
    user = self.user
    can_bypass = False
    if user and user.is_authenticated:
        can_bypass = bool(
            user.is_superuser or
            getattr(user, 'is_super_admin', False) or
            getattr(user, 'can_bypass_location', False)
        )

    # فرض التحقق من إحداثيات المندوبين
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
```

#### 2. محرك التوثيق والتدقيق الجغرافي في `verify_visit_location()`:
- يتم حفظ إحداثيات المندوب وإحداثيات العميل المسجلة لحظة الزيارة كلقطة مرجعية (`snapshot`).
- يتم تسجيل حالة التحقق الدقيقة في الحقلين:
  - `verification_status`: (`verified`, `unverified`, `force_bypassed`).
  - `location_status`: نص عربي وصفي معتمد يعرض في تفاصيل الزيارة وقوائمها.

---

### 4. سجل الاختبارات الآلية (Automated Test Execution Log)
تم تشغيل حزمة الاختبارات الآلية المخصصة لمصفوفة الـ GPS:
- الملف: [`activities/tests.py`](file:///c:/D/Cooding/GENERAL/new/ERP/activities/tests.py)
- عدد الاختبارات المنفذة: **24 اختباراً كاملاً**
- النتيجة: **OK — All 24 tests passed in 26.199s**
- الملف الإضافي: [`test_visit_location_e2e.py`](file:///c:/D/Cooding/GENERAL/new/ERP/test_visit_location_e2e.py)
- النتيجة: **100% SUCCESS — All 7 categories passed**
