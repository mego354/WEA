import os, sys, django

sys.path.insert(0, os.path.abspath('.'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from accounts.models import Role, RoleTag, User
from master_data.models import (
    CompanyProfile, LocationSettings, SalesSettings, PurchaseSettings,
    ExpenseType, TicketType, ApprovalRequestType, AgreementType,
    ContactFieldSetting, DataSyncConfig, Area
)

print("Starting settings & master data seeding...")

# 1. Seed Role Tags
tags_data = [
    ('customers:customers/bypassLocation', 'تجاوز التحقق من موقع العميل'),
    ('accounting:vaults/assignable', 'مخوّل بعهدة نقدية / خزنة'),
    ('expenses:expenses/assignable', 'مخوّل بتقديم مصروفات'),
    ('locationTracking:users/trackable', 'تفعيل متابعة الموقع الجغرافي'),
    ('sales:receiptBooks/assignable', 'مخوّل بدفاتر إيصالات التحصيل'),
    ('tickets:todos/restrictOwner', 'حصر المهام بالمسؤول فقط'),
]

for tag_key, tag_disp in tags_data:
    RoleTag.objects.get_or_create(tag=tag_key, defaults={'display_name': tag_disp})

# 2. Seed System Roles
roles_data = [
    ('SuperAdmin', 'مدير النظام الأعلى', {'is_system': True, 'is_super': True, 'is_active': True}),
    ('Admin', 'مدير النظام', {'is_system': True, 'is_super': True, 'is_active': True}),
    ('CEO', 'المدير العام', {'is_system': True, 'is_active': True}),
    ('Accountant', 'محاسب', {'is_system': True, 'can_hold_vault': True, 'is_active': True}),
    ('Bookkeeper', 'كاتب حسابات', {'is_system': True, 'is_active': True}),
    ('AreaManager', 'مدير منطقة', {'is_system': True, 'is_area_manager': True, 'is_sales_team': True, 'is_active': True}),
    ('DistrictManager', 'مدير قطاع', {'is_system': True, 'is_sub_area_manager': True, 'is_sales_team': True, 'is_active': True}),
    ('DirectSalesRep', 'مندوب مبيعات مباشر', {'is_system': True, 'is_rep': True, 'is_sales_team': True, 'has_sales_targets': True, 'is_active': True}),
    ('DirectSuperSalesRep', 'مندوب مبيعات متميز', {'is_system': True, 'is_rep': True, 'is_sales_team': True, 'has_sales_targets': True, 'is_active': True}),
    ('MedicalRep', 'مندوب دعاية طبية', {'is_system': True, 'is_rep': True, 'is_sales_team': True, 'has_sales_targets': True, 'is_active': True}),
    ('KeyAccountSupervisor', 'مشرف حسابات رئيسية', {'is_system': True, 'is_sales_team': True, 'is_active': True}),
    ('KeyAccountRep', 'مندوب حسابات رئيسية', {'is_system': True, 'is_rep': True, 'is_sales_team': True, 'is_active': True}),
    ('HRManager', 'مدير الموارد البشرية', {'is_system': True, 'is_active': True}),
    ('CarDriver', 'سائق توزيع', {'is_system': True, 'is_active': True}),
    ('LineAdmin', 'مدير خط', {'is_system': True, 'is_active': True}),
    ('LineSalesManager', 'مدير مبيعات خط', {'is_system': True, 'is_sales_team': True, 'is_active': True}),
]

bypass_tag = RoleTag.objects.filter(tag='customers:customers/bypassLocation').first()
vault_tag = RoleTag.objects.filter(tag='accounting:vaults/assignable').first()
exp_tag = RoleTag.objects.filter(tag='expenses:expenses/assignable').first()

for code, disp, attrs in roles_data:
    role, created = Role.objects.get_or_create(name=code, defaults={'display_name': disp, **attrs})
    if not created:
        for k, v in attrs.items():
            setattr(role, k, v)
        role.display_name = disp
        role.save()
    if code in ['SuperAdmin', 'Admin', 'Accountant'] and bypass_tag:
        role.tags.add(bypass_tag)
    if code in ['Accountant', 'DirectSalesRep', 'DirectSuperSalesRep'] and vault_tag:
        role.tags.add(vault_tag)
    if exp_tag:
        role.tags.add(exp_tag)

# Ensure superuser user has SuperAdmin role
super_user = User.objects.filter(is_superuser=True).first()
if super_user:
    super_role = Role.objects.filter(name='SuperAdmin').first()
    if super_role:
        super_user.role = super_role
        super_user.bypass_location_verification = True
        super_user.save()

# 3. Seed Expense Types
expenses_data = [
    ('مرتبات حوافز', 'Salaries & Incentives', 'general', 'الوحدة'),
    ('مصروفات الدعاية', 'Promotional Expenses', 'general', 'الوحدة'),
    ('مصروفات الحسابات والضرائب', 'Taxes & Accountant Expense', 'general', 'الوحدة'),
    ('مصروفات نقل وتوزيع', 'Transportation & Distribution Expenses', 'general', 'الوحدة'),
    ('تكاليف تصنيع', 'Manufacturing Costs', 'general', 'الوحدة'),
    ('مصروفات التسويق', 'Marketing Expenses', 'general', 'الوحدة'),
    ('رسوم تسجيل وترخيص', 'Regulatory Fees', 'general', 'الوحدة'),
    ('بدل انتقال وزيارات', 'Travel & Visit Allowance', 'visit', 'زيارة'),
    ('ضيافة وهدايا عينات', 'Hospitality & Samples', 'visit', 'عينة'),
]

for name, name_en, cat, unit in expenses_data:
    ExpenseType.objects.get_or_create(name=name, category=cat, defaults={'name_en': name_en, 'unit': unit})

# 4. Seed Ticket Types
TicketType.objects.get_or_create(name='Task', defaults={'is_default': True})

# 5. Seed Approval Request Types
approvals_data = [
    ('Absent day', True),
    ('Off day', True),
    ('Admin work', False),
    ('Admin work [AM]', False),
    ('Admin work [PM]', False),
    ('Area manager plan', False),
    ('Coaching Report', False),
    ('District manager plan', False),
]

for name, is_def in approvals_data:
    ApprovalRequestType.objects.get_or_create(name=name, defaults={'is_default': is_def})

# 6. Seed Agreement Types
agreements_data = [
    'Conference', 'Cash money', 'Devices', 'Gifts', 'RTD', 'Rx', 'Others'
]
for name in agreements_data:
    AgreementType.objects.get_or_create(name=name)

# 7. Seed Contact Custom Fields
udf_fields = [
    ('name', 'الاسم', 'header', True, True, True, False, False, 1),
    ('title', 'اللقب', 'header', False, False, True, False, False, 2),
    ('organization', 'المؤسسة', 'header', True, False, True, False, True, 3),
    ('type', 'النوع', 'subheader', True, True, True, True, True, 4),
    ('relation', 'علاقة العمل', 'subheader', True, True, True, True, True, 5),
    ('classification', 'تصنيف العميل', 'subheader', False, True, False, True, True, 6),
    ('specialty', 'التخصص', 'subheader', False, True, False, True, True, 7),
    ('account_type', 'نوع الاكونت', 'subheader', False, True, False, True, True, 8),
    ('code', 'الكود', 'basic', True, False, True, False, False, 9),
    ('phone', 'التليفون', 'basic', False, False, True, False, False, 10),
]

for key, disp, sec, locked, req, builtin, core, filterable, ord_num in udf_fields:
    ContactFieldSetting.objects.get_or_create(
        field_key=key,
        defaults={
            'display_name': disp,
            'section': sec,
            'is_locked': locked,
            'is_required': req,
            'is_builtin': builtin,
            'is_core': core,
            'is_filterable': filterable,
            'order': ord_num
        }
    )

# 8. Seed Data Sync Configs
DataSyncConfig.objects.get_or_create(
    sync_type='contacts',
    defaults={
        'title': 'إستيراد جهات الاتصال',
        'google_sheet_url': 'https://docs.google.com/spreadsheets/d/1CdSnVWLD3LOPKIQ1eenMcMqawnC'
    }
)
DataSyncConfig.objects.get_or_create(
    sync_type='products',
    defaults={
        'title': 'إستيراد المنتجات',
        'google_sheet_url': ''
    }
)
DataSyncConfig.objects.get_or_create(
    sync_type='areas',
    defaults={
        'title': 'مزامنة المناطق',
        'google_sheet_url': 'https://docs.google.com/spreadsheets/d/1-8GV2xRAhge--V0YFB-qvQ6si1Wv'
    }
)

# 9. Verify singleton settings
CompanyProfile.get_settings()
LocationSettings.get_settings()
SalesSettings.get_settings()
PurchaseSettings.get_settings()

print("Settings & Master Data seeding completed successfully!")
