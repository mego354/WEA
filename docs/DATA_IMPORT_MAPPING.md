# وثيقة تخطيط ومطابقة استيراد البيانات
# Data Import & Schema Mapping Specification

> **البيئة المستهدفة**: قاعدة البيانات المحلية للتطوير فقط (`c:\D\Cooding\GENERAL\new\ERP\db.sqlite3`)  
> **حالة النظام المرجعي**: محمي بالكامل - قراءة فقط (100% Read-Only)، لن يتم إجراء أي تعديل أو اتصال به.  
> **تاريخ الإعداد**: 20 أكتوبر 2026  
> **حالة النسخ الاحتياطي**: جاهز ويتم التحقق منه قبل أي عملية استبدال (`PRAGMA integrity_check; -> ok`).

---

## 1. فهرس ملفات المصدر (`data_folder/`)

| اسم الملف | نوع الملف | عدد الصفوف الإجمالي | عدد صفوف البيانات | عدد الأعمدة | الكيانات المستهدفة في النظام |
|---|---|---|---|---|---|
| `لستة العملاء.xlsx` | Excel (.xlsx) | 8,877 | 8,876 | 42 | `contacts.Contact`, `contacts.ContactAddress`, `master_data.Area`, `sales.CustomerAccount` |
| `اوامر البيع.xlsx` | Excel (.xlsx) | 12,517 | 12,516 | 72 | `catalog.ProductCategory`, `catalog.Product`, `sales.SalesOrder`, `sales.SalesOrderItem` |
| `التحصيلات.xlsx` | Excel (.xlsx) | 6,677 | 6,676 | 24 | `sales.Collection`, `sales.CustomerTransaction` |
| `الاتفاقيات.xlsx` | Excel (.xlsx) | 212 | 211 | 13 | `contacts.ContactActivity` (`activity_type='agreement'`) |
| `المرتجعات.xlsx` | Excel (.xlsx) | 433 | 432 | 56 | `sales.SalesReturnOrder`, `sales.SalesReturnOrderItem`, `sales.CustomerTransaction` |

---

## 2. نطاق البيانات وتحديد الاستبدال (Scope & Classification)

### 2.1 بيانات الأعمال المراد استبدالها (Replacement Business Scope)
تمثل الملفات في `data_folder` دورة المبيعات والعملاء لشركة WEA فارما:
1. **العملاء والمناطق**: 8,876 عميل، عناوينهم وإحداثياتهم الجغرافية، والمناطق والمحافظات التابعة لهم.
2. **المنتجات والتصنيفات**: تصنيف ومنتجات شركة WEA الستة الرسمية المستخرجة من بنود الأوامر:
   - `ST1`: Steps (سعر البيع 140.00 ج.م)
   - `UL1`: Ultrahumudin Cream (سعر البيع 105.00 ج.م)
   - `SO1`: Soriana V.D (سعر البيع 75.00 ج.م)
   - `GE1`: Geron (سعر البيع 140.00 ج.م)
   - `LE1`: Legatonexx Spray (سعر البيع 120.00 ج.م)
   - `PU1`: Putalaxy gel (سعر البيع 75.00 ج.م)
3. **أوامر البيع**: 7,088 أمر بيع فريد بـ 12,516 بنداً تفصيلياً.
4. **التحصيلات**: 6,676 سند تحصيل نقدي وشيكات وحركات كشف حساب العملاء.
5. **الاتفاقيات**: 211 اتفاقية عملاء ومندوبين.
6. **المرتجعات**: 270 أمر إرجاع بـ 432 بند مرتجع.

### 2.2 بيانات النظام والبنية التحتية المحمية (Preserved Application Infrastructure)
تُستثنى السجلات التالية قطعياً من أي حذف أو تصفير لضمان استقرار التطبيق:
1. **حسابات المستخدمين والصلاحيات**:
   - حساب السوبر يوزر والمدير العام: `wea.pharm2020@gmail.com` (يبقى نشطاً ومحتفظاً بصلاحياته الفائقة).
   - مجموعات الصلاحيات (`Group`, `Permission`, `ContentType`).
   - سجلات الترحيلات (`django_migrations`).
2. **المخزن الرئيسي والخزينة الرئيسية**:
   - `inventory.Warehouse` (`code="WH-MAIN"`).
   - `treasury.Vault` (`serial_num=1001`).
3. **قوالب الزيارات والزيارات المخططة**:
   - قوالب الزيارات واستبياناتها الديناميكية (`VisitTemplate`, `VisitTemplateQuestion`).
4. **موردو وأوامر المشتريات الأساسية**:
   - ملفات Excel لا تحتوي على فواتير شراء موردين خام، ولذلك يتم الاحتفاظ بسجلات الموردين التجريبية وتعديل أرقامهم المسلسلة لتبدأ من `90000+` لمنع أي تعارض مسلسلات مع العملاء الحقيقيين.

---

## 3. مطابقة الحقول التفصيلية (Field-by-Field Mappings)

### 3.1 ملف `لستة العملاء.xlsx` -> `contacts.Contact` & `master_data.Area`

| عمود Excel المصدر | الحقل في النموذج | نوع البيانات | المعالجة وقواعد التحويل |
|---|---|---|---|
| `المعرف` | `Contact.code` | CharField(100) | حفظ UUID الأصلي للربط والتتبع |
| `مسلسل` | `Contact.serial_num` | IntegerField | رقم المسلسل الفريد للعميل |
| `الاسم` | `Contact.name` | CharField(255) | الاسم التجاري للعميل بعد تنظيف الفراغات |
| `حالة العميل - الاسم` | `Contact.status` | CharField(20) | Customer -> `'customer'`, Lead -> `'lead'`, Inactive -> `'inactive'` |
| `الموبايل` | `Contact.mobile` | CharField(30) | رقم الهاتف الأساسي |
| `تصنيف العميل` | `Contact.customer_category` | CharField(10) | فئة العميل (A, B, C, إلخ) |
| `التخصص` | `Contact.specialty` | CharField(100) | تخصص الطبيب أو الصيدلية |
| `نوع الاكونت` | `Contact.account_type` | CharField(100) | Pharmacy, Hospital, Polyclinic |
| `المنطقة - المنطقة الرئيسية - الكود` | `Area.code` (parent) | CharField(20) | كود المحافظة |
| `المنطقة - المنطقة الرئيسية - الاسم` | `Area.name` (parent) | CharField(150) | اسم المحافظة (`area_type='governorate'`) |
| `المنطقة - الكود` | `Area.code` (child) | CharField(20) | كود المنطقة/المركز |
| `المنطقة - الاسم` | `Area.name` (child) | CharField(150) | اسم المنطقة/المركز (`area_type='subarea'`) |
| `العنوان الرئيسي - العنوان` | `ContactAddress.street_address` | TextField | عنوان الشارع والمقر |
| `العنوان الرئيسي - الموقع - الإحداثيات` | `latitude`, `longitude` | DecimalField | استخراج خطوط الطول والعرض الجغرافية بدقة 7 أرقام عشرية |
| ثابت | `Contact.is_customer` | BooleanField | تعيين القيمة `True` |
| ثابت | `Contact.is_supplier` | BooleanField | تعيين القيمة `False` |

---

### 3.2 ملف `اوامر البيع.xlsx` -> `sales.SalesOrder` & `sales.SalesOrderItem`

| عمود Excel المصدر | الحقل في النموذج | نوع البيانات | المعالجة وقواعد التحويل |
|---|---|---|---|
| `المعرف` | `SalesOrder.order_number` | CharField(60) | كود/UUID أمر البيع الفريد |
| `مسلسل` | `SalesOrder.serial_num` | IntegerField | رقم مسلسل الأمر |
| `تاريخ الإنشاء` | `SalesOrder.order_date` | DateTimeField | وقت وتاريخ تحرير الطلب بتوقيت القاهرة |
| `العميل - المعرف` | `SalesOrder.customer` | ForeignKey(Contact) | الربط بالعميل عبر `Contact.code` |
| `الحالة - الاسم` | `SalesOrder.status` | CharField(20) | Delivered -> `'delivered'`, Invoiced -> `'invoiced'`, Pending -> `'pending'`, Cancelled -> `'cancelled'` |
| `الإجمالي النهائي` | `SalesOrder.grand_total` | DecimalField(12,2) | إجمالي قيمة الفاتورة |
| `ملاحظة` | `SalesOrder.notes` | TextField | ملاحظات التوصيل أو الاعتماد |
| `العناصر - المنتج - الكود` | `SalesOrderItem.product` | ForeignKey(Product) | ربط البند بكود الصنف (SKU) |
| `العناصر - الكمية` | `SalesOrderItem.quantity` | IntegerField | الكمية المطلوبة بالعبوة |
| `العناصر - سعر القطعة` | `SalesOrderItem.unit_price` | DecimalField(10,2) | سعر البيع للجمهور/الصيدلية |
| `العناصر - الكلي` | `SalesOrderItem.subtotal` | DecimalField(12,2) | إجمالي قيمة السطر |

---

### 3.3 ملف `التحصيلات.xlsx` -> `sales.Collection` & `sales.CustomerTransaction`

| عمود Excel المصدر | الحقل في النموذج | نوع البيانات | المعالجة وقواعد التحويل |
|---|---|---|---|
| `رقم التسلسل` | `Collection.serial_num` | IntegerField | رقم إيصال التحصيل |
| `تاريخ الإنشاء` | `Collection.collection_date` | DateField | تاريخ التحصيل الفعلي |
| `الكمية` | `Collection.amount` | DecimalField(12,2) | المبلغ المحصل |
| `طريقة الدفع` | `Collection.payment_method` | CharField(20) | cash -> `'cash'`, cheque -> `'cheque'` |
| `id عميل` / `رقم تسلسل العميل` | `Collection.customer` | ForeignKey(Contact) | ربط العميل صاحب السند |
| ثابت | `Collection.vault` | ForeignKey(Vault) | ربط بالخزينة الرئيسية الافتراضية |
| `حال التحصيل` | ترحيل كشف الحساب | CustomerTransaction | إنشاء حركة دائنة في دفتر أستاذ العميل |

---

### 3.4 ملف `الاتفاقيات.xlsx` -> `contacts.ContactActivity`

| عمود Excel المصدر | الحقل في النموذج | نوع البيانات | المعالجة وقواعد التحويل |
|---|---|---|---|
| `Customer id` | `ContactActivity.contact` | ForeignKey(Contact) | ربط العميل الطرف في الاتفاق |
| `العنوان` | `ContactActivity.title` | CharField(255) | نص أو موضوع الاتفاقية |
| `التاريخ` | `ContactActivity.start_time` | DateTimeField | تاريخ سريان الاتفاقية |
| `المبلغ` + `Type` + `Status` | `ContactActivity.notes` | TextField | تجميع تفاصيل المبلغ والنوع والحالة والمنشئ في الملاحظات |
| ثابت | `ContactActivity.activity_type` | CharField(20) | تعيين القيمة `'agreement'` |

---

### 3.5 ملف `المرتجعات.xlsx` -> `sales.SalesReturnOrder` & `sales.SalesReturnOrderItem`

| عمود Excel المصدر | الحقل في النموذج | نوع البيانات | المعالجة وقواعد التحويل |
|---|---|---|---|
| `مسلسل` | `SalesReturnOrder.serial_num` | IntegerField | رقم المسلسل الفريد لمرتجع المبيعات |
| `الرقم` | `SalesReturnOrder.order_number` | CharField(60) | رقم أو كود مستند الإرجاع |
| `تاريخ الإنشاء` | `SalesReturnOrder.order_date` | DateField | تاريخ استلام المرتجع |
| `العميل - المعرف` | `SalesReturnOrder.customer` | ForeignKey(Contact) | العميل المرتجع منه |
| `الإجمالي النهائي` | `SalesReturnOrder.grand_total` | DecimalField(12,2) | إجمالي قيمة المرتجع |
| `العناصر - المنتج - الكود` | `SalesReturnOrderItem.product` | ForeignKey(Product) | صنف المرتجع |
| `العناصر - الكمية` | `SalesReturnOrderItem.quantity` | IntegerField | الكمية المرتجعة |
| `العناصر - سعر القطعة` | `SalesReturnOrderItem.unit_price` | DecimalField(10,2) | سعر تسعير المرتجع |
| `العناصر - رقم تشغيل المنتج` | `SalesReturnOrderItem.batch_number`| CharField(50) | رقم التشغيلة/الباتش |

---

## 4. ترتيب التبعيات وتنفيذ الاستيراد الذري (Execution Order & Transactions)

لمنع حدوث أخطاء المفاتيح الأجنبية أو تجزئة البيانات عند حدوث خطأ، يتم تنفيذ الاستبدال ضمن معاملة ذرية واحدة (`transaction.atomic()`):

```
1. التحقق من البيئة المحلية وأخذ نسخة احتياطية (PRAGMA integrity_check).
2. حذف بيانات الأعمال القديمة ضمن النطاق المستهدف.
3. استيراد المحافظات والمراكز (master_data.Area).
4. استيراد منتجات شركة WEA الستة وتصنيفها (catalog.ProductCategory & Product).
5. استيراد العملاء وعناوينهم وفتح حساباتهم (contacts.Contact & ContactAddress & CustomerAccount).
6. استيراد أوامر البيع وبنودها (sales.SalesOrder & SalesOrderItem).
7. استيراد سندات التحصيل وحركات الحسابات (sales.Collection & CustomerTransaction).
8. استيراد اتفاقيات العملاء (contacts.ContactActivity).
9. استيراد مرتجعات المبيعات وبنودها (sales.SalesReturnOrder & SalesReturnOrderItem).
10. تأكيد سلامة كلمة مرور المدير العام (wea.pharm2020@gmail.com -> Wea@4444).
```

---

## 5. قواعد معالجة التكرار والقيم الخالية (Deduplication & Null Handling)

1. **العملاء**:
   - `code` (المعرف الفريد UUID) غير مكرر في الملف (8,876 قيمة فريدة بنسبة 100%).
   - `serial_num` مسلسل فريد رقمياً. في حال وجود صف ناقص يتم توليد رقم مسلسل فريد يبدأ من 20000+.
2. **أوامر البيع**:
   - يتكرر معرف الأمر `المعرف` لعدة صفوف لتمثيل بنود المنتجات المختلفة للطلب نفسه (12,516 سطراً لبنود الأوامر تنتمي إلى 7,088 أمراً فريداً).
   - يتم تجميع بنود الطلب الواحد تلقائياً تحت سجل `SalesOrder` واحد، وتوليد سجلات `SalesOrderItem` لكل بند.
3. **الأرقام العشرية والتواريخ**:
   - تحويل التواريخ النصية ذات التنسيقات المتعددة (`%d/%m/%Y %I:%M %p`, `%Y-%m-%d`) إلى تواريخ واعية بالتوقيت المحلي (`timezone.make_aware`).
   - تنظيف الفواصل وتطبيع الأرقام العشرية إلى منزلتين (`quantize(Decimal('0.01'))`).
