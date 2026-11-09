from django.db import migrations


def seed_default_scopes(apps, schema_editor):
    Role = apps.get_model('accounts', 'Role')
    RoleModuleScope = apps.get_model('accounts', 'RoleModuleScope')
    Vault = apps.get_model('treasury', 'Vault')

    default_scopes_by_role = {
        'superadmin': {
            'contacts': ('all', 'all'),
            'activities': ('all', 'all'),
            'sales': ('all', 'all'),
            'purchases': ('all', 'all'),
            'inventory': ('all', 'all'),
            'treasury': ('all', 'all'),
            'catalog': ('all', 'all'),
            'accounts': ('all', 'all'),
        },
        'manager': {
            'contacts': ('area', 'area'),
            'activities': ('area', 'area'),
            'sales': ('area', 'area'),
            'purchases': ('area', 'area'),
            'inventory': ('area', 'area'),
            'treasury': ('area', 'area'),
            'catalog': ('all', 'own'),
            'accounts': ('area', 'area'),
        },
        'accountant': {
            'contacts': ('all', 'own'),
            'activities': ('own', 'own'),
            'sales': ('all', 'all'),
            'purchases': ('all', 'all'),
            'inventory': ('all', 'all'),
            'treasury': ('all', 'all'),
            'catalog': ('all', 'own'),
            'accounts': ('own', 'own'),
        },
        'rep': {
            'contacts': ('brick', 'brick'),
            'activities': ('own', 'own'),
            'sales': ('own', 'own'),
            'purchases': ('own', 'own'),
            'inventory': ('own', 'own'),
            'treasury': ('own', 'own'),
            'catalog': ('all', 'own'),
            'accounts': ('own', 'own'),
        },
        'medical_rep': {
            'contacts': ('brick', 'brick'),
            'activities': ('own', 'own'),
            'sales': ('own', 'own'),
            'purchases': ('own', 'own'),
            'inventory': ('own', 'own'),
            'treasury': ('own', 'own'),
            'catalog': ('all', 'own'),
            'accounts': ('own', 'own'),
        },
    }

    modules = ['contacts', 'activities', 'sales', 'purchases', 'inventory', 'treasury', 'catalog', 'accounts']

    for role in Role.objects.all():
        role_key = (role.name or '').lower()
        mapping = default_scopes_by_role.get(role_key)
        if not mapping:
            # Fallback for custom or legacy roles based on flags
            if getattr(role, 'is_super', False):
                mapping = default_scopes_by_role['superadmin']
            elif getattr(role, 'is_area_manager', False) or getattr(role, 'is_sub_area_manager', False):
                mapping = default_scopes_by_role['manager']
            elif 'accountant' in role_key:
                mapping = default_scopes_by_role['accountant']
            else:
                mapping = default_scopes_by_role['rep']

        for mod in modules:
            v_scope, m_scope = mapping.get(mod, ('own', 'own'))
            RoleModuleScope.objects.update_or_create(
                role=role,
                module=mod,
                defaults={
                    'view_scope': v_scope,
                    'manage_scope': m_scope,
                }
            )

    # Backfill Vault.area if null
    for v in Vault.objects.filter(area__isnull=True):
        if v.assigned_user:
            first_area = v.assigned_user.assigned_areas.first()
            if first_area:
                v.area = first_area
                v.save(update_fields=['area'])


def reverse_seed(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0009_usermodulescope_rolemodulescope'),
        ('treasury', '0005_vault_area'),
    ]

    operations = [
        migrations.RunPython(seed_default_scopes, reverse_seed),
    ]
