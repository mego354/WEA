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
                    ('users:users/view', 'فحص الصلاحيات الفعلية للمستخدم', 'read'),
                ]
            },
            'roles': {
                'name_ar': 'إدارة الأدوار ومصفوفة الصلاحيات',
                'actions': [
                    ('system:rbac/manage', 'إنشاء وتعديل وتكرار وحذف أدوار الصلاحيات', 'admin'),
                ]
            },
            'audit': {
                'name_ar': 'سجل التدقيق الأمني للعمليات الحساسة',
                'actions': [
                    ('settings:auditLogs/view', 'عرض وتصفح سجل التدقيق الأمني', 'admin'),
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
                    ('purchases:orders/approve', 'اعتماد أمر المشتريات (Approve)', 'workflow'),
                    ('purchases:orders/stock', 'إدخال أمر المشتريات للمخزن (Stock / Picked)', 'workflow'),
                    ('purchases:orders/invoice', 'ترحيل فاتورة الشراء لحساب المورد (Invoice / Settle)', 'financial'),
                    ('purchases:orders/undoInvoice', 'إلغاء ترحيل فاتورة المشتريات من الحسابات', 'financial'),
                    ('purchases:orders/cancel', 'إلغاء أمر المشتريات', 'workflow'),
                    ('purchases:orders/export', 'تصدير أوامر المشتريات إلى Excel', 'export'),
                ]
            },
            'returns': {
                'name_ar': 'مرتجعات المشتريات',
                'actions': [
                    ('purchases:returns/list', 'عرض قائمة مرتجعات المشتريات', 'read'),
                    ('purchases:returns/view', 'عرض تفاصيل إذن مرتجع المشتريات', 'read'),
                    ('purchases:returns/create', 'إنشاء إذن مرتجع مشتريات جديد', 'write'),
                    ('purchases:returns/manage', 'تنفيذ واعتماد حركات مرتجع المشتريات', 'workflow'),
                    ('purchases:returns/export', 'تصدير مرتجعات المشتريات إلى Excel', 'export'),
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
                    ('sales:orders/approve', 'اعتماد أمر البيع من مدير المبيعات', 'workflow'),
                    ('sales:orders/unstock', 'صرف بضاعة أمر البيع من المخزن (Delivered)', 'workflow'),
                    ('sales:orders/invoice', 'ترحيل فاتورة البيع لحساب العميل المدين', 'financial'),
                    ('sales:orders/cancel', 'إلغاء أمر البيع', 'workflow'),
                    ('sales:orders/export', 'تصدير أوامر البيع إلى Excel', 'export'),
                ]
            },
            'collections': {
                'name_ar': 'التحصيلات النقدية والشيكات',
                'actions': [
                    ('sales:collections/list', 'عرض قائمة تحصيلات العملاء', 'read'),
                    ('sales:collections/create', 'تسجيل تحصيل نقدي جديد من عميل', 'financial'),
                    ('sales:collections/export', 'تصدير سجل التحصيلات إلى Excel', 'export'),
                ]
            },
            'customer_accounting': {
                'name_ar': 'حسابات ومعاملات العملاء',
                'actions': [
                    ('sales:customers/accounting', 'عرض كشف حسابات أرصدة العملاء', 'read'),
                    ('sales:customers/transactions', 'عرض كشف المعاملات المدينة والدائنة للعملاء', 'read'),
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
                ]
            },
            'warehouses': {
                'name_ar': 'دليل المخازن ومراكز التوزيع',
                'actions': [
                    ('inventory:warehouses/manage', 'إدارة وإضافة وتعديل بيانات المخازن', 'write'),
                ]
            },
            'memos': {
                'name_ar': 'أذونات المخزن (إضافة وصرف وتحويل)',
                'actions': [
                    ('inventory:memos/manage', 'إنشاء واعتماد أذونات الإضافة والصرف المخزني', 'workflow'),
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
            'vaults': {
                'name_ar': 'الخزن النقدية وحسابات العهد',
                'actions': [
                    ('treasury:vaults/view', 'عرض الخزن النقدية وأرصدتها الحالية', 'read'),
                    ('treasury:vaults/transactions', 'عرض وتسجيل حركات النقدية وسندات الصرف والقبض', 'financial'),
                ]
            },
            'vendor_payments': {
                'name_ar': 'مدفوعات الموردين',
                'actions': [
                    ('treasury:payments/list', 'عرض قائمة مدفوعات الموردين', 'read'),
                    ('treasury:payments/create', 'تسجيل مدفوعة نقدية/بنكية لمورد', 'financial'),
                    ('treasury:payments/requests', 'عرض واعتماد طلبات الدفع للموردين', 'financial'),
                    ('treasury:payments/export', 'تصدير مدفوعات الموردين إلى Excel', 'export'),
                ]
            },
            'vendor_accounting': {
                'name_ar': 'حسابات وعمليات الموردين',
                'actions': [
                    ('treasury:vendors/accounting', 'عرض أرصدة وكشوفات حسابات الموردين', 'read'),
                    ('treasury:vendors/transactions', 'عرض دفتر قيود وعمليات الموردين التفصيلية', 'read'),
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
                    ('activities:visits/view', 'عرض تفاصيل الزيارة والصور والاستبيان وموقع GPS', 'read'),
                    ('activities:visits/create', 'تسجيل وبدء زيارة ميدانية (مخططة أو حرة)', 'write'),
                    ('activities:visits/edit', 'تعديل بيانات وإجابات الزيارة المفتوحة', 'write'),
                    ('activities:visits/approve', 'اعتماد أو رفض الزيارة الميدانية من المشرف', 'workflow'),
                    ('activities:visits/evidence', 'رفع وتوثيق صورة الإثبات والموقع الجغرافي', 'write'),
                    ('activities:visits/export', 'تصدير تقارير الزيارات الميدانية إلى Excel', 'export'),
                ]
            },
            'plans': {
                'name_ar': 'خطط وجداول الزيارات',
                'actions': [
                    ('activities:planned/list', 'عرض خطط الزيارات المجدولة للمناديب', 'read'),
                    ('activities:planned/manage', 'إنشاء وإضافة وحذف مواعيد خطة الزيارات', 'write'),
                    ('activities:planned/export', 'تصدير خطة الزيارات إلى Excel', 'export'),
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
            'sync_data': {
                'name_ar': 'مزامنة البيانات الخارجية (Google Sheets)',
                'actions': [
                    ('settings:syncData/manage', 'إدارة وتشغيل مزامنة البيانات عبر Google Sheets', 'admin'),
                ]
            },
            'visits_templates': {
                'name_ar': 'قوالب واستبيانات الزيارات الميدانية',
                'actions': [
                    ('settings:visitsTemplates/manage', 'تصميم وإدارة قوالب الزيارات وأسئلة الاستبيانات', 'admin'),
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
