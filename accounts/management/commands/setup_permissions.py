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

    def add_arguments(self, parser):
        parser.add_argument('--no-audit', action='store_true', help='Skip recording security audit log.')

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
        if not options.get('no_audit'):
            try:
                from accounts.services import AuditLogService
                AuditLogService.log(
                    action='create',
                    module='roles',
                    record_name='تهيئة الصلاحيات والأدوار',
                    status='success',
                    reason=f"Permissions seeded: {len(registered)} registered permissions synchronized across standard roles."
                )
                self.stdout.write(self.style.SUCCESS("Recorded security audit log entry."))
            except Exception:
                pass

    def setup_standard_roles(self, perm_map):
        """
        Configures exactly the five canonical supported enterprise roles:
        1. superadmin
        2. manager
        3. accountant
        4. rep
        5. medical_rep
        """
        # 1. superadmin (System Superuser - All registered permissions)
        super_admin, _ = Role.objects.get_or_create(
            name=Role.ROLE_SUPERADMIN,
            defaults={
                'display_name': 'مدير النظام الأعلى',
                'description': 'إدارة شاملة للنظام، كافة الصلاحيات والإعدادات والحسابات.',
                'is_system': True,
                'is_active': True,
                'is_super': True,
                'can_hold_vault': True,
            }
        )
        super_admin.display_name = 'مدير النظام الأعلى'
        super_admin.is_super = True
        super_admin.is_system = True
        super_admin.is_active = True
        super_admin.can_hold_vault = True
        super_admin.save()
        super_admin.permissions.set(list(perm_map.values()))

        # Also sync legacy 'SuperAdmin' role if present in DB
        legacy_super = Role.objects.filter(name='SuperAdmin').first()
        if legacy_super and legacy_super.pk != super_admin.pk:
            legacy_super.is_super = True
            legacy_super.is_system = True
            legacy_super.is_active = False
            legacy_super.save()
            legacy_super.permissions.set(list(perm_map.values()))

        # 2. manager (Executive & Operational Manager)
        manager_role, _ = Role.objects.get_or_create(
            name=Role.ROLE_MANAGER,
            defaults={
                'display_name': 'مدير',
                'description': 'إشراف على مناديب المنطقة، اعتماد خطط الزيارات وأوامر البيع وعمليات الشراء والاتفاقيات.',
                'is_system': True,
                'is_active': True,
                'is_sales_team': True,
                'is_area_manager': True,
                'is_main_area_bound': True,
                'has_sales_targets': True,
            }
        )
        manager_role.display_name = 'مدير'
        manager_role.is_system = True
        manager_role.is_active = True
        manager_role.is_sales_team = True
        manager_role.is_area_manager = True
        manager_role.is_main_area_bound = True
        manager_role.has_sales_targets = True
        manager_role.save()

        manager_codenames = [
            'module:activities', 'activities:visits/list', 'activities:visits/view',
            'activities:visits/approve', 'activities:visits/export',
            'activities:planned/list', 'activities:planned/manage', 'activities:planned/export',
            'activities:agreements/list', 'activities:agreements/view', 'activities:agreements/approve',
            'activities:agreements/export',
            'module:sales', 'sales:orders/list', 'sales:orders/view', 'sales:orders/approve', 'sales:orders/export',
            'sales:collections/list',
            'module:contacts', 'contacts:contacts/list', 'contacts:contacts/view', 'contacts:contacts/create',
            'contacts:contacts/edit', 'contacts:contacts/export',
            'module:catalog', 'catalog:products/list', 'catalog:products/view',
            'module:inventory', 'inventory:stocks/view',
            'module:purchases', 'purchases:orders/list', 'purchases:orders/view', 'purchases:orders/approve',
            'purchases:orders/export',
        ]
        manager_role.permissions.set([perm_map[c] for c in manager_codenames if c in perm_map])

        # 3. accountant (Finance & Treasury)
        accountant, _ = Role.objects.get_or_create(
            name=Role.ROLE_ACCOUNTANT,
            defaults={
                'display_name': 'محاسب',
                'description': 'إدارة الحسابات، الخزن النقدية، ترحيل الفواتير، مدفوعات الموردين.',
                'is_system': True,
                'is_active': True,
                'can_hold_vault': True,
            }
        )
        accountant.display_name = 'محاسب'
        accountant.is_system = True
        accountant.is_active = True
        accountant.can_hold_vault = True
        accountant.save()

        acc_codenames = [
            'module:treasury', 'treasury:treasury/view', 'treasury:reports/view',
            'treasury:vaults/view', 'treasury:vaults/transfer',
            'treasury:transactions/list', 'treasury:transactions/create', 'treasury:transactions/edit',
            'treasury:transactions/approve', 'treasury:transactions/reverse',
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

        # 4. rep (Commercial Sales Representative)
        rep_role, _ = Role.objects.get_or_create(
            name=Role.ROLE_REP,
            defaults={
                'display_name': 'مندوب مبيعات',
                'description': 'المبيعات التجارية، الفواتير، أوامر البيع، والتحصيلات الميدانية.',
                'is_system': True,
                'is_active': True,
                'is_sales_team': True,
                'is_rep': True,
                'is_sub_area_bound': True,
                'can_hold_vault': True,
                'has_sales_targets': True,
            }
        )
        rep_role.display_name = 'مندوب مبيعات'
        rep_role.is_system = True
        rep_role.is_active = True
        rep_role.is_sales_team = True
        rep_role.is_rep = True
        rep_role.is_sub_area_bound = True
        rep_role.can_hold_vault = True
        rep_role.has_sales_targets = True
        rep_role.save()

        rep_codenames = [
            'module:activities', 'activities:visits/list', 'activities:visits/view',
            'activities:visits/create', 'activities:visits/edit', 'activities:visits/evidence',
            'activities:planned/list',
            'activities:agreements/list', 'activities:agreements/view', 'activities:agreements/create',
            'module:contacts', 'contacts:contacts/list', 'contacts:contacts/view', 'contacts:contacts/create',
            'module:sales', 'sales:orders/list', 'sales:orders/view', 'sales:orders/create',
            'sales:collections/list', 'sales:collections/create',
            'module:catalog', 'catalog:products/list', 'catalog:products/view',
        ]
        rep_role.permissions.set([perm_map[c] for c in rep_codenames if c in perm_map])

        # 5. medical_rep (Medical / Scientific Representative)
        medical_rep_role, _ = Role.objects.get_or_create(
            name=Role.ROLE_MEDICAL_REP,
            defaults={
                'display_name': 'مندوب دعاية طبية',
                'description': 'الدعاية الطبية، الزيارات الميدانية للأطباء والمراكز الطبية والصيدليات، عينات الأدوية، والاتفاقيات.',
                'is_system': True,
                'is_active': True,
                'is_sales_team': True,
                'is_rep': True,
                'is_sub_area_bound': True,
                'can_hold_vault': True,
                'has_sales_targets': True,
            }
        )
        medical_rep_role.display_name = 'مندوب دعاية طبية'
        medical_rep_role.is_system = True
        medical_rep_role.is_active = True
        medical_rep_role.is_sales_team = True
        medical_rep_role.is_rep = True
        medical_rep_role.is_sub_area_bound = True
        medical_rep_role.can_hold_vault = True
        medical_rep_role.has_sales_targets = True
        medical_rep_role.save()
        medical_rep_role.permissions.set([perm_map[c] for c in rep_codenames if c in perm_map])

        # Deactivate any non-canonical roles so only the 5 canonical roles are active
        Role.objects.exclude(name__in=Role.CANONICAL_ROLE_KEYS).update(is_active=False)

        self.stdout.write(self.style.SUCCESS("Canonical 5 enterprise roles configured and synchronized successfully."))
