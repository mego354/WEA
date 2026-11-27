"""
Centralized Permission Registry for WEA Pharma ERP.
Defines all enterprise modules, pages, actions, and their hierarchical codenames.
"""

from typing import Dict, List, Any

# Hierarchy: Module -> Submodule/Page -> Actions
ERP_PERMISSIONS_CATALOG = {
    'accounts': {
        'code': 'accounts',
        'name_ar': 'المستخدمون والأدوار والصلاحيات',
        'name_en': 'Users, Roles & RBAC',
        'icon': 'shield_person',
        'root_perm': 'module:accounts',
        'pages': {
            'users': {
                'name_ar': 'دليل حسابات المستخدمين',
                'actions': [
                    ('users:users/list', 'عرض قائمة المستخدمين', 'read'),
                    ('users:users/create', 'إنشاء حساب مستخدم جديد', 'write'),
                    ('users:users/edit', 'تعديل بيانات المستخدم وكلمة المرور', 'write'),
                    ('users:users/delete', 'تعطيل أو حذف حساب المستخدم', 'delete'),
                    ('users:users/export', 'تصدير بيانات المستخدمين (Excel/CSV)', 'export'),
                    ('users:users/view', 'عرض ملف وتفاصيل المستخدم', 'read'),
                ]
            },
            'roles': {
                'name_ar': 'إدارة الأدوار ومصفوفة الصلاحيات',
                'actions': [
                    ('system:rbac/manage', 'إنشاء وتعديل وتكرار وحذف أدوار الصلاحيات', 'admin'),
                    ('settings:rbac/view', 'عرض واستعراض أدوار ومصفوفة الصلاحيات', 'read'),
                    ('settings:rbac/export', 'تصدير الأدوار والصلاحيات إلى Excel', 'export'),
                ]
            },
            'audit': {
                'name_ar': 'سجل التدقيق الأمني للعمليات الحساسة',
                'actions': [
                    ('settings:auditLogs/view', 'عرض وتصفح سجل التدقيق الأمني', 'admin'),
                    ('settings:auditLogs/export', 'تصدير سجل التدقيق الأمني إلى Excel', 'export'),
                ]
            }
        }
    },
    'catalog': {
        'code': 'catalog',
        'name_ar': 'دليل المنتجات والتصنيفات',
        'name_en': 'Product Catalog',
        'icon': 'store',
        'root_perm': 'module:catalog',
        'pages': {
            'products': {
                'name_ar': 'المنتجات والأصناف الطبية',
                'actions': [
                    ('catalog:products/list', 'عرض قائمة المنتجات', 'read'),
                    ('catalog:products/view', 'عرض تفاصيل المنتج والتسعير', 'read'),
                    ('catalog:products/create', 'إضافة صنف أو منتج جديد', 'write'),
                    ('catalog:products/edit', 'تعديل بيانات المنتج وسعر البيع', 'write'),
                    ('catalog:products/delete', 'حذف منتج من الدليل', 'delete'),
                    ('catalog:products/export', 'تصدير دليل المنتجات إلى Excel', 'export'),
                    ('catalog:products/import', 'استيراد المنتجات من ملف Excel', 'write'),
                ]
            },
            'categories': {
                'name_ar': 'تصنيفات المنتجات',
                'actions': [
                    ('catalog:categories/list', 'عرض تصنيفات المنتجات', 'read'),
                    ('catalog:categories/create', 'إضافة تصنيف منتجات جديد', 'write'),
                    ('catalog:categories/edit', 'تعديل بيانات التصنيف', 'write'),
                    ('catalog:categories/delete', 'حذف تصنيف منتجات', 'delete'),
                    ('catalog:categories/export', 'تصدير تصنيفات المنتجات إلى Excel', 'export'),
                    ('catalog:categories/import', 'استيراد تصنيفات المنتجات من Excel', 'write'),
                ]
            }
        }
    },
    'contacts': {
        'code': 'contacts',
        'name_ar': 'جهات الاتصال (العملاء والموردين)',
        'name_en': 'Contacts Master',
        'icon': 'contacts',
        'root_perm': 'module:contacts',
        'pages': {
            'contacts': {
                'name_ar': 'دليل جهات الاتصال',
                'actions': [
                    ('contacts:contacts/list', 'عرض قائمة جهات الاتصال والعملاء والموردين', 'read'),
                    ('contacts:contacts/view', 'عرض ملف العميل/المورد الشامل والمعاملات', 'read'),
                    ('contacts:contacts/create', 'إنشاء عميل أو مورد جديد', 'write'),
                    ('contacts:contacts/edit', 'تعديل بيانات العميل أو المورد والحد الائتماني', 'write'),
                    ('contacts:contacts/delete', 'حذف جهة اتصال', 'delete'),
                    ('contacts:contacts/export', 'تصدير جهات الاتصال إلى Excel', 'export'),
                    ('contacts:contacts/import', 'استيراد جهات الاتصال من Excel', 'write'),
                ]
            }
        }
    },
    'purchases': {
        'code': 'purchases',
        'name_ar': 'المشتريات والموردين',
        'name_en': 'Purchasing & Vendors',
        'icon': 'storefront',
        'root_perm': 'module:purchases',
        'pages': {
            'orders': {
                'name_ar': 'أوامر المشتريات',
                'actions': [
                    ('purchases:orders/list', 'عرض قائمة أوامر المشتريات', 'read'),
                    ('purchases:orders/view', 'عرض تفاصيل أمر المشتريات والبنود', 'read'),
                    ('purchases:orders/create', 'إنشاء أمر مشتريات جديد', 'write'),
                    ('purchases:orders/edit', 'تعديل أمر المشتريات والخصومات والكميات', 'write'),
                    ('purchases:orders/delete', 'حذف أمر مشتريات مع عكس القيود والمخزون', 'delete'),
                    ('purchases:orders/approve', 'اعتماد أمر المشتريات (Approve)', 'workflow'),
                    ('purchases:orders/stock', 'إدخال أمر المشتريات للمخزن (Stock / Picked)', 'workflow'),
                    ('purchases:orders/invoice', 'ترحيل فاتورة الشراء لحساب المورد (Invoice / Settle)', 'financial'),
                    ('purchases:orders/undoInvoice', 'إلغاء ترحيل فاتورة المشتريات من الحسابات', 'financial'),
                    ('purchases:orders/cancel', 'إلغاء أمر المشتريات', 'workflow'),
                    ('purchases:orders/manage_payment_status', 'تعديل وتحديد حالة سداد أمر الشراء التجارية', 'workflow'),
                    ('purchases:orders/export', 'تصدير أوامر المشتريات إلى Excel', 'export'),
                    ('purchases:orders/pdf', 'إصدار وطباعة فاتورة أمر الشراء PDF', 'export'),
                ]
            },
            'returns': {
                'name_ar': 'مرتجعات المشتريات',
                'actions': [
                    ('purchases:returns/list', 'عرض قائمة مرتجعات المشتريات', 'read'),
                    ('purchases:returns/view', 'عرض تفاصيل إذن مرتجع المشتريات', 'read'),
                    ('purchases:returns/create', 'إنشاء إذن مرتجع مشتريات جديد', 'write'),
                    ('purchases:returns/edit', 'تعديل أمر مرتجع المشتريات', 'write'),
                    ('purchases:returns/delete', 'حذف أمر مرتجع المشتريات وعكس القيود', 'delete'),
                    ('purchases:returns/approve', 'اعتماد أو رفض أمر مرتجع المشتريات', 'workflow'),
                    ('purchases:returns/manage', 'تنفيذ وتسوية حركات مرتجع المشتريات', 'workflow'),
                    ('purchases:returns/export', 'تصدير مرتجعات المشتريات إلى Excel', 'export'),
                    ('purchases:returns/pdf', 'إصدار إشعار مرتجع المشتريات PDF', 'export'),
                ]
            },
            'statements': {
                'name_ar': 'كشوف حسابات الموردين PDF',
                'actions': [
                    ('purchases:statements/pdf', 'إصدار كشف حساب مورد PDF', 'export'),
                ]
            }
        }
    },
    'sales': {
        'code': 'sales',
        'name_ar': 'المبيعات والعملاء',
        'name_en': 'Sales & Customers',
        'icon': 'point_of_sale',
        'root_perm': 'module:sales',
        'pages': {
            'orders': {
                'name_ar': 'أوامر المبيعات',
                'actions': [
                    ('sales:orders/list', 'عرض قائمة أوامر المبيعات', 'read'),
                    ('sales:orders/view', 'عرض تفاصيل أمر البيع والأسعار', 'read'),
                    ('sales:orders/create', 'إنشاء وتجهيز أمر بيع جديد', 'write'),
                    ('sales:orders/edit', 'تعديل بيانات أمر البيع والبنود قبل الاعتماد', 'write'),
                    ('sales:orders/delete', 'حذف أمر بيع مع عكس القيود والمخزون', 'delete'),
                    ('sales:orders/approve', 'اعتماد أمر البيع من مدير المبيعات', 'workflow'),
                    ('sales:orders/unstock', 'صرف بضاعة أمر البيع من المخزن (Delivered)', 'workflow'),
                    ('sales:orders/invoice', 'ترحيل فاتورة البيع لحساب العميل المدين', 'financial'),
                    ('sales:orders/cancel', 'إلغاء أمر البيع', 'workflow'),
                    ('sales:orders/manage_payment_status', 'تعديل وتحديد حالة سداد أمر البيع التجارية', 'workflow'),
                    ('sales:orders/export', 'تصدير أوامر البيع إلى Excel', 'export'),
                    ('sales:orders/pdf', 'إصدار وطباعة فاتورة البيع PDF', 'export'),
                ]
            },
            'returns': {
                'name_ar': 'مرتجعات المبيعات',
                'actions': [
                    ('sales:returns/list', 'عرض قائمة مرتجعات المبيعات', 'read'),
                    ('sales:returns/view', 'عرض تفاصيل وأمر مرتجع المبيعات', 'read'),
                    ('sales:returns/create', 'إنشاء أمر مرتجع مبيعات جديد', 'write'),
                    ('sales:returns/edit', 'تعديل أمر مرتجع المبيعات', 'write'),
                    ('sales:returns/delete', 'حذف أمر مرتجع المبيعات وعكس القيود', 'delete'),
                    ('sales:returns/approve', 'اعتماد أو رفض أمر مرتجع المبيعات', 'workflow'),
                    ('sales:returns/manage', 'استلام وتسوية مرتجع المبيعات', 'workflow'),
                    ('sales:returns/cancel', 'إلغاء أمر مرتجع المبيعات', 'workflow'),
                    ('sales:returns/export', 'تصدير مرتجعات المبيعات إلى Excel', 'export'),
                    ('sales:returns/pdf', 'إصدار إشعار مرتجع المبيعات PDF', 'export'),
                ]
            },
            'collections': {
                'name_ar': 'التحصيلات النقدية والشيكات',
                'actions': [
                    ('sales:collections/list', 'عرض قائمة تحصيلات العملاء', 'read'),
                    ('sales:collections/create', 'تسجيل تحصيل نقدي جديد من عميل', 'financial'),
                    ('sales:collections/export', 'تصدير سجل التحصيلات إلى Excel', 'export'),
                    ('sales:collections/import', 'استيراد التحصيلات من Excel', 'financial'),
                ]
            },
            'customer_accounts': {
                'name_ar': 'حسابات وأرصدة العملاء (sales/customers/accounts/)',
                'actions': [
                    ('sales:customers/accounting', 'عرض صفحة كشف حسابات وأرصدة العملاء', 'read'),
                    ('sales:customers/accounting_export', 'تصدير كشف حسابات وأرصدة العملاء إلى Excel', 'export'),
                    ('sales:customers/zero_balance', 'تصفير رصيد حساب عميل (تسوية غير نقدية)', 'financial'),
                    ('sales:statements/pdf', 'إصدار كشف حساب عميل PDF', 'export'),
                ]
            },
            'customer_transactions': {
                'name_ar': 'عمليات وحركات العملاء (sales/customer-transactions/)',
                'actions': [
                    ('sales:customers/transactions', 'عرض صفحة دفتر عمليات وحركات العملاء', 'read'),
                    ('sales:customers/transactions_export', 'تصدير سجل عمليات وحركات العملاء إلى Excel', 'export'),
                ]
            }
        }
    },
    'inventory': {
        'code': 'inventory',
        'name_ar': 'المخازن وإدارة المخزون',
        'name_en': 'Inventory & Warehousing',
        'icon': 'warehouse',
        'root_perm': 'module:inventory',
        'pages': {
            'stocks': {
                'name_ar': 'أرصدة المخزون والتشغيلات',
                'actions': [
                    ('inventory:stocks/view', 'عرض أرصدة المخزون والتشغيلات وتواريخ الصلاحية', 'read'),
                    ('inventory:stocks/export', 'تصدير كشف أرصدة المخزون إلى Excel', 'export'),
                    ('inventory:stocks/import', 'استيراد أرصدة وتسويات المخزون من Excel', 'workflow'),
                ]
            },
            'warehouses': {
                'name_ar': 'دليل المخازن ومراكز التوزيع',
                'actions': [
                    ('inventory:warehouses/manage', 'إدارة وإضافة وتعديل بيانات المخازن', 'write'),
                    ('inventory:warehouses/delete', 'حذف المخازن الخالية من الحركات والأرصدة', 'admin'),
                    ('inventory:warehouses/export', 'تصدير دليل المخازن إلى Excel', 'export'),
                    ('inventory:warehouses/import', 'استيراد دليل المخازن من Excel', 'write'),
                ]
            },
            'memos': {
                'name_ar': 'أذونات المخزن (إضافة وصرف وتحويل)',
                'actions': [
                    ('inventory:memos/manage', 'إنشاء واعتماد أذونات الإضافة والصرف المخزني', 'workflow'),
                    ('inventory:memos/export', 'تصدير أذونات المخزن إلى Excel', 'export'),
                    ('inventory:memos/import', 'استيراد تسويات المخزون من Excel', 'workflow'),
                ]
            },
            'transfers': {
                'name_ar': 'التحويلات المخزنية بين الفروع',
                'actions': [
                    ('inventory:transfers/list', 'عرض قائمة طلبات التحويل المخزني', 'read'),
                    ('inventory:transfers/view', 'عرض تفاصيل طلب التحويل المخزني والبنود', 'read'),
                    ('inventory:transfers/create', 'إنشاء وطلب تحويل مخزني جديد', 'write'),
                    ('inventory:transfers/approve', 'اعتماد أو رفض طلب التحويل المخزني', 'workflow'),
                    ('inventory:transfers/execute', 'تنفيذ التحويل المخزني ونقل البضاعة', 'workflow'),
                    ('inventory:transfers/cancel', 'إلغاء طلب التحويل المخزني', 'workflow'),
                    ('inventory:transfers/export', 'تصدير طلبات التحويل المخزني إلى Excel', 'export'),
                ]
            }
        }
    },
    'treasury': {
        'code': 'treasury',
        'name_ar': 'الخزينة والمالية والمدفوعات',
        'name_en': 'Treasury & Cash Management',
        'icon': 'account_balance_wallet',
        'root_perm': 'module:treasury',
        'pages': {
            'overview': {
                'name_ar': 'لوحة الخزينة والتقارير',
                'actions': [
                    ('treasury:treasury/view', 'عرض لوحة الخزينة والمعلومات المالية العامة', 'read'),
                    ('treasury:reports/view', 'عرض كشوفات وتقارير الخزينة والسيولة النقدية', 'read'),
                ]
            },
            'vaults': {
                'name_ar': 'الخزن النقدية وحسابات العهد',
                'actions': [
                    ('treasury:vaults/view', 'عرض الخزن النقدية وأرصدتها الحالية المصرح بها', 'read'),
                    ('treasury:vaults/manage', 'إدارة وإنشاء وتعديل وتفعيل الخزن النقدية', 'admin'),
                    ('treasury:vaults/delete', 'حذف الخزن النقدية الخالية من الحركات والأرصدة', 'admin'),
                    ('treasury:vaults/transfer', 'إجراء تحويلات نقدية بين الخزن والحسابات المصرح بها', 'financial'),
                    ('treasury:vaults/export', 'تصدير الخزن النقدية وأرصدتها إلى Excel', 'export'),
                ]
            },
            'transactions': {
                'name_ar': 'حركات وسندات الخزن',
                'actions': [
                    ('treasury:transactions/list', 'عرض سجل وتاريخ حركات الخزن النقدية', 'read'),
                    ('treasury:transactions/create', 'تسجيل حركة خزينة وسند قبض/صرف نقدي', 'financial'),
                    ('treasury:transactions/edit', 'تعديل بيانات وحركات الخزينة غير المقفلة', 'write'),
                    ('treasury:transactions/approve', 'اعتماد حركات الخزينة والتحويلات المالية', 'workflow'),
                    ('treasury:transactions/reverse', 'عكس وتسوية الحركات النقدية الخاطئة (Financial Reversal)', 'financial'),
                    ('treasury:transactions/export', 'تصدير حركات وسندات الخزن إلى Excel', 'export'),
                ]
            },
            'vendor_payments': {
                'name_ar': 'مدفوعات وطلبات سداد الموردين',
                'actions': [
                    ('treasury:payments/list', 'عرض قائمة مدفوعات وسندات صرف الموردين', 'read'),
                    ('treasury:payments/create', 'تسجيل مدفوعة نقدية/بنكية لمورد', 'financial'),
                    ('treasury:payments/requests', 'عرض قائمة وتفاصيل طلبات الدفع للموردين', 'read'),
                    ('treasury:payment_requests/create', 'إنشاء وتعديل طلب سداد للمورد', 'write'),
                    ('treasury:payment_requests/approve', 'اعتماد أو رفض طلبات سداد الموردين', 'workflow'),
                    ('treasury:payment_requests/execute', 'تنفيذ وصرف طلبات سداد الموردين المعتمدة', 'financial'),
                    ('treasury:payment_requests/export', 'تصدير طلبات سداد الموردين إلى Excel', 'export'),
                    ('treasury:payments/export', 'تصدير مدفوعات الموردين إلى Excel', 'export'),
                    ('treasury:payments/import', 'استيراد مدفوعات الموردين من Excel', 'financial'),
                ]
            },
            'vendor_accounting': {
                'name_ar': 'حسابات وعمليات الموردين',
                'actions': [
                    ('treasury:vendors/accounting', 'عرض أرصدة وكشوفات حسابات الموردين', 'read'),
                    ('treasury:vendors/accounting_export', 'تصدير أرصدة حسابات الموردين إلى Excel', 'export'),
                    ('treasury:vendors/zero_balance', 'تصفير رصيد حساب مورد (تسوية غير نقدية)', 'financial'),
                    ('treasury:vendors/transactions', 'عرض دفتر قيود وعمليات الموردين التفصيلية', 'read'),
                    ('treasury:vendors/transactions_export', 'تصدير دفتر قيود الموردين إلى Excel', 'export'),
                ]
            }
        }
    },
    'activities': {
        'code': 'activities',
        'name_ar': 'الأنشطة الميدانية والزيارات والاتفاقيات',
        'name_en': 'Field Activities & Visits',
        'icon': 'timeline',
        'root_perm': 'module:activities',
        'pages': {
            'visits': {
                'name_ar': 'الزيارات الميدانية',
                'actions': [
                    ('activities:visits/list', 'عرض قائمة وسجل الزيارات الميدانية', 'read'),
                    ('activities:visits/view', 'عرض تفاصيل الزيارة والاستبيان وموقع GPS', 'read'),
                    ('activities:visits/create', 'تسجيل وبدء زيارة ميدانية (مخططة أو حرة)', 'write'),
                    ('activities:visits/edit', 'تعديل بيانات الزيارة الميدانية', 'write'),
                    ('activities:visits/edit_answers', 'تعديل إجابات استبيان الزيارة بعد اكتمالها', 'write'),
                    ('activities:visits/delete', 'حذف الزيارات', 'delete'),
                    ('activities:visits/approve', 'اعتماد أو رفض الزيارة الميدانية من المشرف', 'workflow'),
                    ('activities:visits/export', 'تصدير تقارير الزيارات الميدانية إلى Excel', 'export'),
                    ('activities:visits/bypass_gps', 'تجاوز قيد المسافة (صلاحية مدير / مشرف)', 'workflow'),
                    ('activities:visits/gps_request_exception', 'طلب استثناء تجاوز المسافة الجغرافية (GBS)', 'workflow'),
                    ('activities:visits/view_gps_suspicion', 'عرض وفلترة تنبيهات الموقع المشبوه أو المزيف (GBS)', 'admin'),
                ]
            },
            'plans': {
                'name_ar': 'خطط وجداول الزيارات',
                'actions': [
                    ('activities:planned/list', 'عرض خطط الزيارات المجدولة للمناديب', 'read'),
                    ('activities:planned/manage', 'إنشاء وإضافة وحذف مواعيد خطة الزيارات', 'write'),
                    ('activities:planned/export', 'تصدير خطة الزيارات إلى Excel', 'export'),
                    ('activities:planned/import', 'استيراد خطط الزيارات من Excel', 'write'),
                ]
            },
            'agreements': {
                'name_ar': 'الاتفاقيات والعقود التجارية',
                'actions': [
                    ('activities:agreements/list', 'عرض قائمة الاتفاقيات التجارية', 'read'),
                    ('activities:agreements/view', 'عرض تفاصيل وبنود الاتفاقية', 'read'),
                    ('activities:agreements/create', 'إنشاء اتفاقية أو عقد جديد مع عميل', 'write'),
                    ('activities:agreements/edit', 'تعديل بنود وشروط الاتفاقية الجديدة', 'write'),
                    ('activities:agreements/delete', 'حذف مسودة اتفاقية', 'delete'),
                    ('activities:agreements/approve', 'اعتماد أو إنهاء الاتفاقية التجارية (Approve / Done)', 'workflow'),
                    ('activities:agreements/export', 'تصدير الاتفاقيات إلى Excel', 'export'),
                ]
            }
        }
    },
    'settings': {
        'code': 'settings',
        'name_ar': 'إعدادات النظام والتهيئة العامة',
        'name_en': 'System Settings',
        'icon': 'settings',
        'root_perm': 'module:settings',
        'pages': {
            'branding': {
                'name_ar': 'بيانات وهوية الشركة والفاتورة',
                'actions': [
                    ('settings:branding/edit', 'تعديل الاسم التجاري والشعار والرقم الضريبي', 'admin'),
                ]
            },
            'location': {
                'name_ar': 'إعدادات الموقع الجغرافي والتتبع',
                'actions': [
                    ('settings:location/manage', 'ضبط نصف قطر النطاق الجغرافي وسماحية الـ GPS', 'admin'),
                ]
            },
            'areas': {
                'name_ar': 'المناطق والمحافظات الجغرافية',
                'actions': [
                    ('settings:areas/manage', 'إضافة وتعديل وحذف المحافظات والمناطق التوزيعية', 'admin'),
                    ('settings:areas/export', 'تصدير المناطق والخطوط الجغرافية إلى Excel', 'export'),
                    ('settings:areas/import', 'استيراد المناطق والخطوط الجغرافية من Excel', 'admin'),
                ]
            },
            'expenses': {
                'name_ar': 'أنواع المصروفات وبنود الصرف',
                'actions': [
                    ('settings:expenses/manage', 'إدارة وتخصيص تصنيفات المصروفات الميدانية والإدارية', 'admin'),
                ]
            },
            'tickets': {
                'name_ar': 'أنواع وتصنيفات المهام',
                'actions': [
                    ('settings:tickets/manage', 'إدارة أنواع المهام والمتابعات', 'admin'),
                ]
            },
            'requests': {
                'name_ar': 'أنواع الطلبات والموافقات',
                'actions': [
                    ('settings:requests/manage', 'إدارة وتخصيص فئات طلبات الموافقات الإدارية', 'admin'),
                ]
            },
            'agreements_types': {
                'name_ar': 'أنواع وتصنيفات الاتفاقيات',
                'actions': [
                    ('settings:agreements/manage', 'إدارة أنواع الاتفاقيات والعقود المعتمدة', 'admin'),
                ]
            },
            'sales_settings': {
                'name_ar': 'إعدادات المبيعات والضرائب',
                'actions': [
                    ('settings:sales/manage', 'ضبط سياسات البيع والضريبة الافتراضية والحدود', 'admin'),
                ]
            },
            'purchase_settings': {
                'name_ar': 'إعدادات المشتريات والتوريد',
                'actions': [
                    ('settings:purchase/manage', 'ضبط سياسات الشراء وأرقام أوامر التوريد', 'admin'),
                ]
            },
            'inventory_settings': {
                'name_ar': 'إعدادات المخازن والصلاحية',
                'actions': [
                    ('settings:inventory/manage', 'إلزامية أرقام التشغيلات وتواريخ الصلاحية', 'admin'),
                ]
            },
            'contacts_udf': {
                'name_ar': 'تخصيص الحقول الإضافية لجهات الاتصال',
                'actions': [
                    ('settings:contactsUdf/manage', 'إدارة الحقول المخصصة لجهات الاتصال', 'admin'),
                ]
            },
            'visits_templates': {
                'name_ar': 'قوالب واستبيانات الزيارات الميدانية',
                'actions': [
                    ('settings:visitsTemplates/manage', 'تصميم وإدارة قوالب الزيارات وأسئلة الاستبيانات', 'admin'),
                ]
            },
            'storage': {
                'name_ar': 'التخزين السحابي وحاسبة تكلفة Cloudflare R2',
                'actions': [
                    ('settings:storage/manage', 'عرض وتعديل إعدادات وحاسبة تكلفة التخزين السحابي (R2)', 'admin'),
                ]
            },
            'report_groups': {
                'name_ar': 'مجموعات أنواع الحسابات بالتقارير',
                'actions': [
                    ('settings:reportGroups/manage', 'إدارة وتكوين مجموعات أنواع الحسابات في تقارير الأداء والزيارات', 'admin'),
                ]
            }
        }
    },
    'performance': {
        'code': 'performance',
        'name_ar': 'الأداء والتحليلات الميدانية',
        'name_en': 'Performance & Field Analytics',
        'icon': 'speed',
        'root_perm': 'module:performance',
        'pages': {
            'overview': {
                'name_ar': 'النظرة العامة والمؤشرات القيادية',
                'actions': [
                    ('performance:overview/view', 'عرض لوحة النظرة العامة ومؤشرات الأداء', 'read'),
                    ('performance:overview/export', 'تصدير نظرة عامة على الأداء وتقارير الزيارات إلى Excel', 'export'),
                ]
            },
            'analysis': {
                'name_ar': 'التحليلات المقارنة والرسوم البيانية',
                'actions': [
                    ('performance:analysis/view', 'عرض التحليلات المقارنة والرسوم البيانية', 'read'),
                    ('performance:analysis/export', 'تصدير تحليلات الأداء إلى Excel', 'export'),
                ]
            },
            'daily': {
                'name_ar': 'متابعة النشاط الميداني اليومي',
                'actions': [
                    ('performance:daily/view', 'متابعة النشاط اليومي للمناديب والتبويبات الفرعية', 'read'),
                    ('performance:daily/export', 'تصدير كشف النشاط اليومي إلى Excel', 'export'),
                ]
            },
            'detailed': {
                'name_ar': 'مصفوفة الأداء الكبرى وتقييمات الكوتشينج',
                'actions': [
                    ('performance:detailed/view', 'عرض مصفوفة الأداء الكبرى وجلسات الكوتشينج', 'read'),
                    ('performance:detailed/export', 'تصدير مصفوفة الأداء إلى Excel', 'export'),
                ]
            }
        }
    },
    'reports': {
        'code': 'reports',
        'name_ar': 'التقارير وسجلات الأعمال الشاملة',
        'name_en': 'Business & Financial Reports',
        'icon': 'bar_chart',
        'root_perm': 'module:reports',
        'pages': {
            'hub': {
                'name_ar': 'بوابة التقارير الرئيسية',
                'actions': [
                    ('reports:hub/view', 'عرض بوابة وقائمة التقارير المتاحة', 'read'),
                ]
            },
            'financial': {
                'name_ar': 'التقارير المالية والديون والمراجعة',
                'actions': [
                    ('reports:financial/view', 'عرض تقارير أعمار الديون وميزان المراجعة وتحقيق الأهداف', 'read'),
                    ('reports:financial/export', 'تصدير التقارير المالية إلى Excel والطباعة', 'export'),
                ]
            },
            'sales': {
                'name_ar': 'تقارير المبيعات والربحية والعملاء',
                'actions': [
                    ('reports:sales/view', 'عرض تقارير صافي المبيعات والربحية وملخص العملاء 360 وأداء العروض', 'read'),
                    ('reports:sales/export', 'تصدير تقارير المبيعات إلى Excel', 'export'),
                ]
            },
            'inventory': {
                'name_ar': 'تقارير التوريد واللوجستيات والمخزون',
                'actions': [
                    ('reports:inventory/view', 'عرض تقارير تسليمات الطلبات وتوفر المخزون ومشتريات الأصناف', 'read'),
                    ('reports:inventory/export', 'تصدير تقارير المخازن والتوريد إلى Excel', 'export'),
                ]
            },
            'activities': {
                'name_ar': 'تقارير الأنشطة والاتفاقيات والعينات',
                'actions': [
                    ('reports:activities/view', 'عرض تقارير تحقيق الاتفاقيات والمكالمات وتتبع العينات الطبية', 'read'),
                    ('reports:activities/export', 'تصدير تقارير الأنشطة والعينات إلى Excel', 'export'),
                ]
            }
        }
    },
    'notifications': {
        'code': 'notifications',
        'name_ar': 'الإشعارات والتنبيهات المركزية',
        'name_en': 'Notifications Center',
        'icon': 'notifications',
        'root_perm': 'module:notifications',
        'pages': {
            'inbox': {
                'name_ar': 'صندوق الإشعارات والتنبيهات',
                'actions': [
                    ('notifications:notifications/view', 'عرض وقراءة الإشعارات الواردة', 'read'),
                    ('notifications:rules/manage', 'إدارة وضبط قواعد الإشعارات في إعدادات الأدوار', 'admin'),
                ]
            }
        }
    }
}


def get_all_registered_permissions() -> List[Dict[str, Any]]:
    """
    Flattens the catalog into a list of all permission definitions,
    including root module permissions.
    """
    perms = []
    
    for mod_key, mod_info in ERP_PERMISSIONS_CATALOG.items():
        # Root module perm
        perms.append({
            'codename': mod_info['root_perm'],
            'name': f"الوصول إلى موديول {mod_info['name_ar']}",
            'module_key': mod_key,
            'page_key': '__root__',
            'action_type': 'module_root',
            'is_root': True,
        })
        
        for page_key, page_info in mod_info['pages'].items():
            for codename, name_ar, action_type in page_info['actions']:
                perms.append({
                    'codename': codename,
                    'name': name_ar,
                    'module_key': mod_key,
                    'page_key': page_key,
                    'action_type': action_type,
                    'is_root': False,
                })
                
    return perms


def get_module_for_permission(codename: str) -> str:
    """
    Returns the module key for any given permission codename.
    """
    if codename.startswith('module:'):
        return codename.split(':', 1)[1]
    
    for mod_key, mod_info in ERP_PERMISSIONS_CATALOG.items():
        if mod_info['root_perm'] == codename:
            return mod_key
        for page_key, page_info in mod_info['pages'].items():
            for c, _, _ in page_info['actions']:
                if c == codename:
                    return mod_key
                
    # Fallback by domain prefix
    if ':' in codename:
        prefix = codename.split(':', 1)[0]
        if prefix in ERP_PERMISSIONS_CATALOG:
            return prefix
    return None


def get_preset_codenames(preset: str) -> List[str]:
    """
    Returns lists of codenames for quick role configuration presets.
    Presets:
    - 'admin': all registered permissions.
    - 'readonly': all module roots + read actions.
    - 'default': module roots + read + write actions (no admin/super settings).
    """
    all_perms = get_all_registered_permissions()
    
    if preset == 'admin':
        return [p['codename'] for p in all_perms]
        
    elif preset == 'readonly':
        return [
            p['codename'] for p in all_perms 
            if p['is_root'] or p['action_type'] in ['read', 'export']
        ]
        
    elif preset == 'default':
        return [
            p['codename'] for p in all_perms
            if p['is_root'] or p['action_type'] in ['read', 'write', 'export', 'workflow']
        ]
        
    return []
