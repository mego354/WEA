from django.core.management.base import BaseCommand
from django.db import transaction
from accounts.models import User, Role, SecurityAuditLog


class Command(BaseCommand):
    help = "Migrates all existing users and roles safely into the 5 canonical roles: superadmin, manager, accountant, rep, medical_rep."

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE("Starting User Role Consolidation migration..."))

        with transaction.atomic():
            # 1. Ensure the 5 canonical roles exist and are active
            superadmin, _ = Role.objects.get_or_create(
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
            superadmin.display_name = 'مدير النظام الأعلى'
            superadmin.is_super = True
            superadmin.is_system = True
            superadmin.is_active = True
            superadmin.can_hold_vault = True
            superadmin.save()

            manager, _ = Role.objects.get_or_create(
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
            manager.display_name = 'مدير'
            manager.is_system = True
            manager.is_active = True
            manager.is_sales_team = True
            manager.is_area_manager = True
            manager.is_main_area_bound = True
            manager.has_sales_targets = True
            manager.save()

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

            rep, _ = Role.objects.get_or_create(
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
            rep.display_name = 'مندوب مبيعات'
            rep.is_system = True
            rep.is_active = True
            rep.is_sales_team = True
            rep.is_rep = True
            rep.is_sub_area_bound = True
            rep.can_hold_vault = True
            rep.has_sales_targets = True
            rep.save()

            medical_rep, _ = Role.objects.get_or_create(
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
            medical_rep.display_name = 'مندوب دعاية طبية'
            medical_rep.is_system = True
            medical_rep.is_active = True
            medical_rep.is_sales_team = True
            medical_rep.is_rep = True
            medical_rep.is_sub_area_bound = True
            medical_rep.can_hold_vault = True
            medical_rep.has_sales_targets = True
            medical_rep.save()

            # Ensure permissions from legacy roles are copied over if canonical role lacks them
            legacy_super = Role.objects.filter(name='SuperAdmin').first()
            if legacy_super and legacy_super.permissions.exists():
                superadmin.permissions.add(*legacy_super.permissions.all())

            legacy_acc = Role.objects.filter(name='Accountant').first()
            if legacy_acc and legacy_acc.permissions.exists():
                accountant.permissions.add(*legacy_acc.permissions.all())

            legacy_med_rep = Role.objects.filter(name='MedicalRep').first()
            if legacy_med_rep and legacy_med_rep.permissions.exists():
                medical_rep.permissions.add(*legacy_med_rep.permissions.all())
                rep.permissions.add(*legacy_med_rep.permissions.all())

            legacy_area_mgr = Role.objects.filter(name='AreaManager').first()
            if legacy_area_mgr and legacy_area_mgr.permissions.exists():
                manager.permissions.add(*legacy_area_mgr.permissions.all())

            # 2. Iterate through all users and migrate to canonical roles
            migrated_count = 0
            for u in User.objects.all():
                old_role = u.role
                old_role_name = (old_role.name or '').lower() if old_role else ''
                new_role = None

                if u.is_superuser or old_role_name in ['superadmin']:
                    new_role = superadmin
                elif old_role_name in ['manager', 'admin', 'ceo', 'areamanager', 'area_manager', 'districtmanager', 'purchasingmanager']:
                    new_role = manager
                elif old_role_name in ['accountant', 'bookkeeper']:
                    new_role = accountant
                elif old_role_name in ['medicalrep', 'medical_rep', 'med_rep_test']:
                    new_role = medical_rep
                elif old_role_name in ['rep', 'representative', 'directsalesrep', 'directsupersalesrep', 'keyaccountrep']:
                    new_role = rep
                elif old_role_name in ['purchasingofficer']:
                    # User 14 ('buyer'): assign to manager and copy specific permissions to user.user_permissions
                    new_role = manager
                    if old_role and old_role.permissions.exists():
                        u.user_permissions.add(*old_role.permissions.all())
                elif old_role_name in ['warehousekeeper']:
                    # User 16 ('warehouse_keeper'): assign to manager and copy specific permissions to user.user_permissions
                    new_role = manager
                    if old_role and old_role.permissions.exists():
                        u.user_permissions.add(*old_role.permissions.all())
                elif not old_role:
                    if u.is_superuser:
                        new_role = superadmin
                    else:
                        new_role = rep

                if new_role and u.role_id != new_role.id:
                    u.role = new_role
                    u.save(update_fields=['role'])
                    u.clear_perm_cache()
                    migrated_count += 1

                    SecurityAuditLog.objects.create(
                        actor=None,
                        action_type='USER_ROLE_CHANGED',
                        target_user=u,
                        target_role=new_role,
                        description=f"Consolidated user '{u.name or u.username}' role from '{old_role.display_name if old_role else 'None'}' to canonical role '{new_role.display_name}' ({new_role.name})."
                    )

            # 3. Preserve audit log details before cleaning up obsolete roles
            non_canonical = Role.objects.exclude(name__in=Role.CANONICAL_ROLE_KEYS)
            for l in SecurityAuditLog.objects.filter(target_role__in=non_canonical):
                if l.target_role:
                    if not l.record_name:
                        l.record_name = f"دور: {l.target_role.display_name} ({l.target_role.name})"
                    l.target_role = None
                    l.save(update_fields=['record_name', 'target_role'])

            # 4. Remove obsolete role definitions so only the 5 canonical roles remain
            deleted_roles_count = non_canonical.count()
            non_canonical.delete()

        self.stdout.write(self.style.SUCCESS(
            f"Successfully consolidated roles and users: {migrated_count} users verified on canonical roles. {deleted_roles_count} obsolete roles removed from database."
        ))
