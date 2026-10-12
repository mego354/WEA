# Products & Purchases Replication Checklist (TODO)

> **Status Reference**:
> - `NOT STARTED`
> - `IN PROGRESS`
> - `BLOCKED`
> - `COMPLETED`

---

## 1. Safe Read-Only Reference ERP Inspection
- [x] **[COMPLETED]** Login and save authenticated session safely (`scratch/auth_state.json`)
- [x] **[COMPLETED]** Capture sidebar menus and submenus hierarchy
- [x] **[COMPLETED]** Inspect Products List (`/products`) - columns, layout, 13 products, search, pagination
- [x] **[COMPLETED]** Inspect Product Categories (`/product-categories`) - columns, create modal
- [x] **[COMPLETED]** Inspect Product Creation Form (`/products/create`) - fields, discounts, packaging, photos
- [x] **[COMPLETED]** Inspect Purchase Orders List (`/purchase-orders`) - columns, status pills, default filters
- [x] **[COMPLETED]** Inspect Purchase Order Detail (`/purchase-orders/{id}`) - header, status dropdown, items table, price summary, accounting card, attachments, sidebar accordions
- [x] **[COMPLETED]** Inspect Purchase Order Creation (`/purchase-orders/create`) - supplier selection, items repeater
- [x] **[COMPLETED]** Inspect Vendor Payments (`/vendor-payments`)
- [x] **[COMPLETED]** Inspect Vendor Payment Requests (`/vendor-payment-requests`)
- [x] **[COMPLETED]** Inspect Vendor Accounts (`/accounting/vendors`)
- [x] **[COMPLETED]** Inspect Vendor Transactions (`/accounting/vendor-transactions`)
- [x] **[COMPLETED]** Compile `docs/PRODUCTS_REFERENCE.md`
- [x] **[COMPLETED]** Compile `docs/PURCHASES_REFERENCE.md`
- [x] **[COMPLETED]** Compile `docs/REFERENCE_UI_SPECIFICATION.md`

---

## 2. Navigation & Sidebar Parity
- [x] **[COMPLETED]** Update sidebar navigation in `templates/layouts/base.html` to match reference ERP exact order, Arabic names, icons, and collapsible submenus:
  - `store المنتجات` -> `store المنتجات` (`/products`), `category التصنيفات` (`/product-categories`)
  - `storefront المشتريات` -> `shopping_cart الطلبات` (`/purchase-orders`), `refresh المرتجعات` (`/purchase-return-orders`), `receipt المدفوعات` (`/vendor-payments`), `request_quote طلبات الدفع` (`/vendor-payment-requests`), `attach_money حسابات الموردين` (`/accounting/vendors`), `receipt_long عمليات الموردين` (`/accounting/vendor-transactions`)
- [x] **[COMPLETED]** Root URL aliases added to `config/urls.py` matching exact reference routes.

---

## 3. Products Module Implementation
- [x] **[COMPLETED]** Models & Schema verification (`catalog/models.py`):
  - Added `barcode`, `packing_boxes`, `packing_cartons`, `has_volume_discounts`, `price_display`.
  - Migration `0002_product_barcode_product_has_volume_discounts_and_more` applied.
- [x] **[COMPLETED]** Synced 13 observed reference products into DB while preserving existing records (Total 16 products in DB).
- [x] **[COMPLETED]** Products List View (`templates/catalog/products_list.html`):
  - Title in teal `#27bebe`, `انشئ منتج` button, `فلتر` button with active count badge, floating `+` button.
  - Table headers matching RTL order: `الاسم`, `الكود`, `التصنيف`, `السعر`, `قيمة الضريبة`, `متاح للبيع`, `باركود`, `إجراءات`.
  - Slide-out Filter Drawer matching reference ERP.
  - Pagination footer matching reference (`Items per page: 40`).
  - UTF-8 BOM CSV Export.
- [x] **[COMPLETED]** Product Create / Edit Form (`templates/catalog/product_form.html`):
  - Matching layout, inputs, volume discount toggle, packaging boxes/cartons, drag-drop image upload.
- [x] **[COMPLETED]** Product Categories View (`templates/catalog/categories_list.html`):
  - Table headers: `الاسم`, `الكود`, `التوصيف`, `انشئ فى`.
  - Create category modal.

---

## 4. Purchases Module Implementation
- [x] **[COMPLETED]** Models & Schema verification (`purchases/models.py`):
  - Status choices matching reference (`pending`, `approved`, `picked`, `settled`, `rejected`, `split`, `cancelled`).
  - Added `delivery_agent`, `delivery_time`, `is_canceled`, `is_split`, `PurchaseOrderComment`, `PurchaseOrderAttachment`.
  - Status properties: `status_label_en`, `status_label_ar`, `status_badge_class`.
  - Migration `0002_purchaseorder_delivery_agent_and_more` applied.
- [x] **[COMPLETED]** Purchase Orders List View (`templates/purchases/purchase_orders_list.html`):
  - Matching title, `أمر مشتريات جديد`, `تصدير البيانات`, `اطبع`, `فلتر 3` with active badge.
  - Table headers matching RTL: `رقم المسلسل`, `الاسم`, `المنطقة`, `انشئ فى`, `المنشئ`, `الحالة`, `اجمالى القيمة`, `مسئول التوصيل`, `وقت التوصيل`.
  - Slide-out filter drawer with default filter badges.
- [x] **[COMPLETED]** Purchase Order Detail View (`templates/purchases/purchase_order_detail.html`):
  - Header with serial, supplier initials badge, AJAX status dropdown, `الغاء الفاتورة` button, `print`.
  - Center line-items table (`#`, `الكود`, `التصنيف`, `الصنف`, `الكمية`, `سعر القطعة`, `خصم القطعة`, `إجمالي السعر`, `رقم التشغيل`, `تاريخ الصلاحية`, `ملاحظة`).
  - Price summary breakdown card (Subtotal, discounts, shipping fees, grand total).
  - Linked Accounting Card (Settlement payments, due dates, outstanding debt).
  - Attachments card & Comments timeline.
  - Left sidebar accordions (`تفاصيل أساسية`, `معلومات التوصيل`, `حساب المورد`, `جهة الاتصال`).
- [x] **[COMPLETED]** Purchase Order Create View (`templates/purchases/purchase_order_create.html`):
  - Dynamic supplier selection and full line items repeater with warehouse, batches, expiry dates, and discounts.
- [x] **[COMPLETED]** Purchase Returns, Vendor Payments, Vendor Accounts, and Transactions integration.

---

## 5. Testing & Verification
- [x] **[COMPLETED]** Unit and integration tests for catalog (`python manage.py test catalog`) -> 10 tests passed.
- [x] **[COMPLETED]** Unit and integration tests for purchases (`python manage.py test purchases`) -> 13 tests passed.
- [x] **[COMPLETED]** Full application Django test suite (`python manage.py test`) -> 33 tests passed (100% OK).
- [x] **[COMPLETED]** End-to-end regression tests (`python test_e2e_workflows.py`) -> 100% PASS across all P0/P1 modules.
- [x] **[COMPLETED]** Browser screenshot comparison (Reference vs Local captured in `scratch/screenshots/`).
- [x] **[COMPLETED]** Zero write operations performed on Reference ERP confirmed.
