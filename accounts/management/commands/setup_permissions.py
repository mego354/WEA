from django.core.management.base import BaseCommand
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from accounts.models import Role, User, SecurityAuditLog
from accounts.permission_registry import (
    ERP_PERMISSIONS_CATALOG,
    get_all_registered_permissions,
    get_preset_codenames,
)


class Command(BaseCommand):
    help = "Seeds and updates all centralized permissions and standard roles for WEA Pharma ERP."

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE("Starting ERP permissions synchronization..."))

        # Map each module key to a primary ContentType
        def _get_ct(app_lbl, mdl):
            ct, _ = ContentType.objects.get_or_create(app_label=app_lbl, model=mdl)
            return ct

        app_ct_map = {
            'accounts': _get_ct('accounts', 'role'),
            'catalog': _get_ct('catalog', 'product'),
            'contacts': _get_ct('contacts', 'contact'),
            'purchases': _get_ct('purchases', 'purchaseorder'),
            'sales': _get_ct('sales', 'salesorder'),
            'inventory': _get_ct('inventory', 'inventorystock'),
            'treasury': _get_ct('treasury', 'vault'),
            'activities': _get_ct('activities', 'visit'),
            'settings': _get_ct('master_data', 'companyprofile'),
        }

        registered = get_all_registered_permissions()
        created_count = 0
        updated_count = 0

        created_perm_objs = {}

        for p_info in registered:
            codename = p_info['codename']
            name = p_info['name']
            mod_key = p_info['module_key']
            ct = app_ct_map.get(mod_key, app_ct_map['accounts'])

            perm_obj, created = Permission.objects.update_or_create(
                codename=codename,
                defaults={
                    'name': name,
                    'content_type': ct,
                }
            )
            created_perm_objs[codename] = perm_obj
            if created:
                created_count += 1
            else:
                updated_count += 1

        self.stdout.write(self.style.SUCCESS(
            f"Successfully processed {len(registered)} permissions (Created: {created_count}, Updated: {updated_count})."
        ))

        # Setup / Ensure Standard Enterprise Roles
        self.setup_standard_roles(created_perm_objs)

        # Record Security Audit Log
        SecurityAuditLog.objects.create(
            actor=None,
            action_type='PERMISSIONS_SEEDED',
            description=f"Permissions seeded: {len(registered)} registered permissions synchronized across standard roles.",
        )
        self.stdout.write(self.style.SUCCESS("Recorded security audit log entry."))

    def setup_standard_roles(self, perm_map):
        """
        Configures the standard enterprise roles and their default permission sets.
        """
        # 1. SuperAdmin (System Superuser - All permissions)
        super_admin, _ = Role.objects.get_or_create(
            name='SuperAdmin',
            defaults={
                'display_name': 'مدير النظام الأعلى',
                'description': 'إدارة شاملة للنظام، كافة الصلاحيات والإعدادات والحسابات.',
                'is_system': True,
                'is_active': True,
                'is_super': True,
            }
        )
        super_admin.is_super = True
        super_admin.is_system = True
        super_admin.save()
        super_admin.permissions.set(list(perm_map.values()))

        # 2. Admin (General System Admin)
        admin_role, _ = Role.objects.get_or_create(
            name='Admin',
            defaults={
                'display_name': 'مدير النظام',
                'description': 'إدارة العمليات اليومية، المستخدمين، المناطق، الإعدادات العامة.',
                'is_system': True,
                'is_active': True,
                'is_super': False,
            }
        )
        # Admins get all operational and settings permissions
        admin_perms = [
            p for c, p in perm_map.items()
            if not c.startswith('system:rbac') # Only superadmin edits roles
        ]
        admin_role.permissions.set(admin_perms)

        # 3. CEO (Executive Management)
        ceo_role, _ = Role.objects.get_or_create(
            name='CEO',
            defaults={
                'display_name': 'المدير العام',
                'description': 'رؤية شاملة للشركة، التقارير التنفيذية، الاعتمادات العليا.',
                'is_system': True,
                'is_active': True,
                'is_super': False,
            }
        )
        ceo_perms = [
            p for c, p in perm_map.items()
            if c.startswith('module:') or '/list' in c or '/view' in c or '/approve' in c or '/export' in c
        ]
        ceo_role.permissions.set(ceo_perms)

        # 4. Chief Accountant (رئيس الحسابات)
        accountant, _ = Role.objects.get_or_create(
            name='Accountant',
            defaults={
                'display_name': 'محاسب عام',
                'description': 'إدارة الحسابات، الخزن النقدية، ترحيل الفواتير، مدفوعات الموردين.',
                'is_system': True,
                'is_active': True,
                'can_hold_vault': True,
            }
        )
        acc_codenames = [
            'module:treasury', 'treasury:vaults/view', 'treasury:vaults/transactions',
            'treasury:payments/list', 'treasury:payments/create', 'treasury:payments/requests',
            'treasury:payments/export', 'treasury:vendors/accounting', 'treasury:vendors/transactions',
            'module:purchases', 'purchases:orders/list', 'purchases:orders/view',
            'purchases:orders/invoice', 'purchases:orders/undoInvoice', 'purchases:orders/export',
            'purchases:returns/list', 'purchases:returns/view', 'purchases:returns/export',
            'module:sales', 'sales:orders/list', 'sales:orders/view', 'sales:orders/invoice',
            'sales:collections/list', 'sales:collections/create', 'sales:collections/export',
            'sales:customers/accounting', 'sales:customers/transactions',
            'module:contacts', 'contacts:contacts/list', 'contacts:contacts/view', 'contacts:contacts/export',
            'module:inventory', 'inventory:stocks/view',
        ]
        accountant.permissions.set([perm_map[c] for c in acc_codenames if c in perm_map])

        # 5. Area Manager (مدير منطقة)
        area_mgr, _ = Role.objects.get_or_create(
            name='AreaManager',
            defaults={
                'display_name': 'مدير منطقة',
                'description': 'إشراف على مناديب المنطقة، اعتماد خطط الزيارات وأوامر البيع والاتفاقيات.',
                'is_system': True,
                'is_active': True,
                'is_sales_team': True,
                'is_area_manager': True,
                'is_main_area_bound': True,
                'has_sales_targets': True,
            }
        )
        area_codenames = [
            'module:activities', 'activities:visits/list', 'activities:visits/view',
            'activities:visits/approve', 'activities:visits/export',
            'activities:planned/list', 'activities:planned/manage', 'activities:planned/export',
            'activities:agreements/list', 'activities:agreements/view', 'activities:agreements/approve',
            'activities:agreements/export',
            'module:sales', 'sales:orders/list', 'sales:orders/view', 'sales:orders/approve', 'sales:orders/export',
            'module:contacts', 'contacts:contacts/list', 'contacts:contacts/view', 'contacts:contacts/create',
            'contacts:contacts/edit', 'contacts:contacts/export',
            'module:catalog', 'catalog:products/list', 'catalog:products/view',
        ]
        area_mgr.permissions.set([perm_map[c] for c in area_codenames if c in perm_map])

        # 6. Medical / Field Sales Representative (مندوب دعاية / مبيعات)
        rep_role, _ = Role.objects.get_or_create(
            name='MedicalRep',
            defaults={
                'display_name': 'مندوب دعاية ومبيعات',
                'description': 'تنفيذ الزيارات الميدانية، خطط الزيارات، طلبات البيع، إبرام الاتفاقيات.',
                'is_system': True,
                'is_active': True,
                'is_sales_team': True,
                'is_rep': True,
                'is_sub_area_bound': True,
                'can_hold_vault': True,
                'has_sales_targets': True,
            }
        )
        rep_codenames = [
            'module:activities', 'activities:visits/list', 'activities:visits/view',
            'activities:visits/create', 'activities:visits/edit', 'activities:visits/evidence',
            'activities:planned/list',
            'activities:agreements/list', 'activities:agreements/view', 'activities:agreements/create',
            'module:contacts', 'contacts:contacts/list', 'contacts:contacts/view', 'contacts:contacts/create',
            'module:sales', 'sales:orders/list', 'sales:orders/view', 'sales:orders/create',
            'sales:collections/list', 'sales:collections/create',
            'module:catalog', 'catalog:products/list', 'catalog:products/view',
            'module:treasury', 'treasury:vaults/view', 'treasury:vaults/transactions',
        ]
        rep_role.permissions.set([perm_map[c] for c in rep_codenames if c in perm_map])

        # Also sync existing lowercase or test roles in DB
        for role_name in ['medical_rep', 'med_rep_test']:
            r = Role.objects.filter(name=role_name).first()
            if r:
                r.permissions.set([perm_map[c] for c in rep_codenames if c in perm_map])

        self.stdout.write(self.style.SUCCESS("Standard enterprise roles updated successfully."))
