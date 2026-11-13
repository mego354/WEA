from django.db.models import Q
from django.contrib.auth import get_user_model


class ScopeResolutionService:
    """
    Centralized Scope Resolution Service for WEA Pharma ERP.
    Resolves organizational data access scopes (OWN, BRICK, AREA, ALL) dynamically
    based on role and user custom configuration rather than hardcoded role names.
    """

    MODEL_MODULE_MAP = {
        'contact': 'contacts',
        'contactaddress': 'contacts',
        'contactactivity': 'contacts',
        'visit': 'activities',
        'plannedvisitday': 'activities',
        'plannedvisititem': 'activities',
        'agreement': 'activities',
        'visittemplate': 'activities',
        'salesorder': 'sales',
        'salesreturnorder': 'sales',
        'collection': 'sales',
        'customeraccount': 'sales',
        'purchaseorder': 'purchases',
        'purchasereturnorder': 'purchases',
        'warehouse': 'inventory',
        'inventorystock': 'inventory',
        'inventorymemo': 'inventory',
        'producttransferrequest': 'inventory',
        'vault': 'treasury',
        'vaulttransaction': 'treasury',
        'vendorpayment': 'treasury',
        'vendortransaction': 'treasury',
        'vendoraccount': 'treasury',
        'stocklot': 'inventory',
        'productlot': 'inventory',
        'user': 'accounts',
    }

    @classmethod
    def get_user_scope(cls, user, module: str, scope_type: str = 'view') -> str:
        """
        Determines the effective scope ('own', 'brick', 'area', 'all') for a user and module.
        scope_type is either 'view' or 'manage'.
        """
        if not user or not user.is_authenticated or not user.is_active:
            return 'none'

        # SuperAdmin and Superuser global bypass
        if user.is_superuser or getattr(user, 'is_super_admin', False):
            return 'all'

        role = getattr(user, 'role', None)
        if role and getattr(role, 'is_super', False):
            return 'all'

        # Per-request cache on user instance
        cache_attr = '_module_scope_cache'
        if not hasattr(user, cache_attr):
            setattr(user, cache_attr, {})
        cache = getattr(user, cache_attr)
        cache_key = f"{module}:{scope_type}"
        if cache_key in cache:
            return cache[cache_key]

        scope = None

        # 1. Custom User-Level Overrides (100% authoritative when enabled)
        if getattr(user, 'has_custom_permissions', False):
            from accounts.models import UserModuleScope
            ums = UserModuleScope.objects.filter(user=user, module=module).first()
            if ums:
                scope = getattr(ums, f"{scope_type}_scope", None)

        # 2. Role-Level Configuration
        if not scope and role:
            from accounts.models import RoleModuleScope
            rms = RoleModuleScope.objects.filter(role=role, module=module).first()
            if rms:
                scope = getattr(rms, f"{scope_type}_scope", None)

        # 3. Fallbacks if unseeded/unconfigured
        if not scope:
            if role:
                if getattr(role, 'is_area_manager', False) or getattr(role, 'is_sub_area_manager', False) or getattr(role, 'is_manager_role', False):
                    scope = 'area'
                elif getattr(role, 'is_rep', False):
                    scope = 'brick' if module == 'contacts' else 'own'
                elif role.name in ['accountant', 'Accountant']:
                    scope = 'all' if module in ['sales', 'purchases', 'treasury', 'inventory', 'contacts'] else 'own'
                else:
                    scope = 'own'
            else:
                scope = 'own'

        cache[cache_key] = scope
        return scope

    @classmethod
    def get_main_area(cls, area):
        """
        Returns the canonical root main area (e.g. Governorate) for an Area.
        Traverses parent relationships up to the top-level parent (parent is None).
        """
        if not area:
            return None
        curr = area
        while getattr(curr, 'parent_id', None):
            curr = curr.parent
        return curr

    @classmethod
    def get_user_main_areas(cls, user):
        """
        Returns a distinct QuerySet of canonical root Area objects (Main Areas / Governorates)
        assigned to this user.
        """
        from master_data.models import Area
        if not user or not user.is_authenticated or not user.is_active:
            return Area.objects.none()

        if getattr(user, 'is_super_admin', False) or user.is_superuser:
            return Area.objects.filter(parent__isnull=True)

        assigned_areas = user.assigned_areas.all()
        if not assigned_areas.exists():
            return Area.objects.none()

        main_area_ids = set()
        for a in assigned_areas:
            root = cls.get_main_area(a)
            if root:
                main_area_ids.add(root.id)

        return Area.objects.filter(id__in=main_area_ids)

    @classmethod
    def get_user_bricks(cls, user):
        """
        Returns a QuerySet of all assigned Bricks (subareas, parent__isnull=False).
        If user is assigned directly to an area without parent, returns those assigned areas.
        """
        from master_data.models import Area
        if not user or not user.is_authenticated or not user.is_active:
            return Area.objects.none()

        if getattr(user, 'is_super_admin', False) or user.is_superuser:
            return Area.objects.filter(parent__isnull=False)

        assigned = user.assigned_areas.all()
        bricks = assigned.filter(parent__isnull=False)
        if bricks.exists():
            return bricks
        return assigned

    @classmethod
    def get_user_managed_areas(cls, user, scope: str = 'area'):
        """
        Returns a QuerySet of Area objects under the user's regional responsibility:
        - 'all': All Area objects.
        - 'area': All root main areas assigned to user, PLUS all their child subareas/bricks.
        - 'brick' / 'own': Strictly user's assigned areas/bricks.
        """
        from master_data.models import Area
        if not user or not user.is_authenticated or not user.is_active:
            return Area.objects.none()

        if getattr(user, 'is_super_admin', False) or user.is_superuser:
            return Area.objects.all()

        role = getattr(user, 'role', None)
        if role and getattr(role, 'is_super', False):
            return Area.objects.all()

        if scope == 'all':
            return Area.objects.all()

        if scope == 'area':
            main_areas = cls.get_user_main_areas(user)
            main_area_ids = list(main_areas.values_list('id', flat=True))
            if not main_area_ids:
                return Area.objects.none()
            return Area.objects.filter(
                Q(id__in=main_area_ids) |
                Q(parent_id__in=main_area_ids) |
                Q(parent__parent_id__in=main_area_ids)
            ).distinct()

        # 'brick' or 'own': assigned areas
        assigned_ids = list(user.assigned_areas.values_list('id', flat=True))
        
        if not assigned_ids:
            return Area.objects.none()
        return Area.objects.filter(
            Q(id__in=assigned_ids) |
            Q(parent_id__in=assigned_ids)
        ).distinct()

    @classmethod
    def get_user_managed_subordinates(cls, user, module: str = 'accounts'):
        """
        Returns a QuerySet of active User objects under the user's management scope:
        - SuperAdmin / Executive: all active users.
        - 'all': all active users.
        - 'area': users whose assigned areas intersect the user's root main areas, plus self.
        - 'brick': users whose assigned areas intersect the user's assigned bricks, plus self.
        - 'own': only the user themselves.
        """
        UserModel = get_user_model()
        if not user or not user.is_authenticated or not user.is_active:
            return UserModel.objects.none()

        if getattr(user, 'is_super_admin', False) or user.is_superuser:
            return UserModel.objects.filter(is_active=True)

        role = getattr(user, 'role', None)
        if role and getattr(role, 'is_super', False):
            return UserModel.objects.filter(is_active=True)

        scope = cls.get_user_scope(user, module, 'view')
        if scope == 'own' and module == 'accounts':
            act_scope = cls.get_user_scope(user, 'activities', 'view')
            if act_scope in ('area', 'all', 'brick'):
                scope = act_scope
        if scope == 'all':
            return UserModel.objects.filter(is_active=True)

        if scope == 'area':
            managed_areas = cls.get_user_managed_areas(user, 'area')
            if not managed_areas.exists():
                return UserModel.objects.filter(pk=user.pk)
            return UserModel.objects.filter(
                Q(assigned_areas__in=managed_areas) | Q(id=user.id)
            ).filter(is_active=True).distinct()

        if scope == 'brick':
            user_bricks = cls.get_user_bricks(user)
            if not user_bricks.exists():
                return UserModel.objects.filter(pk=user.pk)
            return UserModel.objects.filter(
                Q(assigned_areas__in=user_bricks) | Q(id=user.id)
            ).filter(is_active=True).distinct()

        # 'own'
        return UserModel.objects.filter(pk=user.pk)

    @classmethod
    def is_manager_eligible_for_user(cls, manager, target_user) -> bool:
        """
        Standardized organizational check:
        Can manager supervise target_user?
        - Anti-self-approval: manager cannot manage or approve their own operations.
        - SuperAdmin / Executive has system-wide eligibility.
        - Evaluates intersection of root main areas.
        """
        if not manager or not manager.is_authenticated or not manager.is_active:
            return False
        if not target_user or not target_user.is_authenticated:
            return False

        # Anti-self-approval
        if manager.id == target_user.id:
            return False

        if getattr(manager, 'is_super_admin', False) or manager.is_superuser:
            return True

        role = getattr(manager, 'role', None)
        if role and getattr(role, 'is_super', False):
            return True

        mgr_main_area_ids = set(cls.get_user_main_areas(manager).values_list('id', flat=True))
        if not mgr_main_area_ids:
            return False

        target_main_area_ids = set(cls.get_user_main_areas(target_user).values_list('id', flat=True))
        if not target_main_area_ids:
            return False

        return bool(mgr_main_area_ids & target_main_area_ids)

    @classmethod
    def is_manager_eligible_for_area(cls, manager, area) -> bool:
        """
        Checks if a manager is eligible for a given Area (governorate or subarea).
        Matches based on canonical root main area.
        """
        if not manager or not manager.is_authenticated or not manager.is_active:
            return False
        if not area:
            return False

        if getattr(manager, 'is_super_admin', False) or manager.is_superuser:
            return True

        role = getattr(manager, 'role', None)
        if role and getattr(role, 'is_super', False):
            return True

        root = cls.get_main_area(area)
        if not root:
            return False

        mgr_main_area_ids = set(cls.get_user_main_areas(manager).values_list('id', flat=True))
        return root.id in mgr_main_area_ids

    @classmethod
    def get_scoped_queryset(cls, queryset, user, model_name: str = None, scope_type: str = 'view'):
        """
        Centralized query filtering engine enforcing configurable module scopes:
        'own', 'brick', 'area', 'all'.
        Replaces hardcoded role-name checks with settings-driven data scopes.
        """
        if not user or not user.is_authenticated or not user.is_active:
            return queryset.none()

        if getattr(user, 'is_super_admin', False) or user.is_superuser:
            return queryset

        role = getattr(user, 'role', None)
        if role and getattr(role, 'is_super', False):
            return queryset

        model = queryset.model
        m_name = (model_name or model.__name__).lower()
        if m_name not in cls.MODEL_MODULE_MAP:
            # Unknown model fails closed for non-superusers
            return queryset.none()
        module = cls.MODEL_MODULE_MAP[m_name]

        scope = cls.get_user_scope(user, module, scope_type)

        if scope == 'all':
            return queryset

        managed_areas = cls.get_user_managed_areas(user, 'area')
        user_bricks = cls.get_user_bricks(user)
        managed_subordinates = cls.get_user_managed_subordinates(user, module)

        # 1. Activities: Visit
        if m_name == 'visit':
            if scope == 'own':
                qs = queryset.filter(Q(owner=user) | Q(created_by=user))
                if user_bricks.exists():
                    return qs.filter(
                        Q(contact__brick__in=user_bricks) |
                        Q(contact__area__in=user_bricks) |
                        (Q(contact__area__isnull=True) & Q(contact__brick__isnull=True))
                    ).distinct()
                return qs.filter(contact__area__isnull=True, contact__brick__isnull=True).distinct()

            elif scope == 'brick':
                if not user_bricks.exists():
                    return queryset.filter(
                        (Q(owner=user) | Q(created_by=user)) &
                        Q(contact__area__isnull=True, contact__brick__isnull=True)
                    ).distinct()
                return queryset.filter(
                    Q(owner__in=managed_subordinates) |
                    Q(created_by__in=managed_subordinates) |
                    Q(contact__brick__in=user_bricks) |
                    Q(contact__area__in=user_bricks)
                ).filter(
                    Q(contact__brick__in=user_bricks) |
                    Q(contact__area__in=user_bricks) |
                    (Q(contact__area__isnull=True) & Q(contact__brick__isnull=True))
                ).distinct()

            elif scope == 'area':
                if not managed_areas.exists():
                    return queryset.none()
                return queryset.filter(
                    Q(owner__in=managed_subordinates) |
                    Q(created_by__in=managed_subordinates) |
                    Q(contact__brick__in=managed_areas) |
                    Q(contact__area__in=managed_areas)
                ).filter(
                    Q(contact__brick__in=managed_areas) |
                    Q(contact__area__in=managed_areas) |
                    (Q(contact__area__isnull=True) & Q(contact__brick__isnull=True))
                ).distinct()

        # 2. Activities: PlannedVisitDay & PlannedVisitItem
        elif m_name == 'plannedvisitday':
            if scope == 'own':
                return queryset.filter(assignee=user)
            elif scope == 'brick':
                return queryset.filter(
                    Q(assignee=user) | Q(assignee__assigned_areas__in=user_bricks)
                ).distinct()
            elif scope == 'area':
                if not managed_areas.exists():
                    return queryset.filter(assignee=user)
                return queryset.filter(assignee__in=managed_subordinates).distinct()
            return queryset.filter(assignee__in=managed_subordinates).distinct()

        elif m_name == 'plannedvisititem':
            if scope == 'own':
                return queryset.filter(plan_day__assignee=user)
            elif scope == 'brick':
                return queryset.filter(
                    Q(plan_day__assignee=user) |
                    Q(plan_day__assignee__assigned_areas__in=user_bricks)
                ).filter(
                    Q(contact__brick__in=user_bricks) |
                    Q(contact__area__in=user_bricks) |
                    (Q(contact__area__isnull=True) & Q(contact__brick__isnull=True))
                ).distinct()
            elif scope == 'area':
                if not managed_areas.exists():
                    return queryset.filter(plan_day__assignee=user)
                return queryset.filter(
                    Q(plan_day__assignee__in=managed_subordinates)
                ).filter(
                    Q(contact__brick__in=managed_areas) |
                    Q(contact__area__in=managed_areas) |
                    (Q(contact__area__isnull=True) & Q(contact__brick__isnull=True))
                ).distinct()

        # 3. Activities: Agreement
        elif m_name == 'agreement':
            if scope == 'own':
                return queryset.filter(created_by=user)
            return queryset.filter(created_by__in=managed_subordinates).distinct()

        # 4. Contacts: Contact
        elif m_name == 'contact':
            if scope == 'own':
                return queryset.filter(
                    Q(created_by=user) | Q(assigned_team=user)
                ).distinct()

            elif scope == 'brick':
                if user_bricks.exists():
                    return queryset.filter(
                        Q(brick__in=user_bricks) |
                        Q(area__in=user_bricks) |
                        Q(addresses__brick__in=user_bricks) |
                        Q(addresses__area__in=user_bricks) |
                        (Q(area__isnull=True) & Q(brick__isnull=True))
                    ).exclude(
                        brick__isnull=False,
                        pk__in=queryset.exclude(brick__in=user_bricks).values('pk')
                    ).exclude(
                        brick__isnull=True,
                        area__isnull=False,
                        pk__in=queryset.exclude(area__in=user_bricks).values('pk')
                    ).distinct()
                # Representative with no assigned brick: can access area-less contacts (e.g. non-geographic unit tests)
                return queryset.filter(area__isnull=True, brick__isnull=True).distinct()

            elif scope == 'area':
                if not managed_areas.exists():
                    return queryset.none()
                return queryset.filter(
                    Q(brick__in=managed_areas) |
                    Q(area__in=managed_areas) |
                    Q(addresses__area__in=managed_areas) |
                    Q(addresses__brick__in=managed_areas) |
                    Q(created_by__in=managed_subordinates) |
                    Q(assigned_team__in=managed_subordinates) |
                    (Q(area__isnull=True, brick__isnull=True) & (Q(created_by__in=managed_subordinates) | Q(assigned_team__in=managed_subordinates) | Q(created_by__isnull=True)))
                ).distinct()

        # 5. Sales: SalesOrder & SalesReturnOrder
        elif m_name in ['salesorder', 'salesreturnorder']:
            if scope == 'own':
                return queryset.filter(created_by=user)
            elif scope == 'brick':
                return queryset.filter(
                    Q(created_by__in=managed_subordinates) |
                    Q(customer__brick__in=user_bricks) |
                    Q(customer__area__in=user_bricks)
                ).distinct()
            elif scope == 'area':
                return queryset.filter(
                    Q(created_by__in=managed_subordinates) |
                    Q(customer__brick__in=managed_areas) |
                    Q(customer__area__in=managed_areas)
                ).distinct()

        # 6. Sales: Collection
        elif m_name == 'collection':
            if scope == 'own':
                return queryset.filter(created_by=user)
            elif scope == 'brick':
                return queryset.filter(
                    Q(created_by__in=managed_subordinates) |
                    Q(customer__brick__in=user_bricks) |
                    Q(customer__area__in=user_bricks)
                ).distinct()
            elif scope == 'area':
                return queryset.filter(
                    Q(created_by__in=managed_subordinates) |
                    Q(customer__brick__in=managed_areas) |
                    Q(customer__area__in=managed_areas)
                ).distinct()

        # 7. Sales: CustomerAccount
        elif m_name == 'customeraccount':
            if scope == 'own':
                from contacts.models import Contact
                scoped_contacts = cls.get_scoped_queryset(Contact.objects.all(), user, 'contact', scope_type)
                return queryset.filter(customer__in=scoped_contacts).distinct()
            elif scope == 'brick':
                return queryset.filter(
                    Q(customer__brick__in=user_bricks) |
                    Q(customer__area__in=user_bricks) |
                    Q(customer__created_by=user) |
                    Q(customer__assigned_team=user)
                ).distinct()
            elif scope == 'area':
                return queryset.filter(
                    Q(customer__brick__in=managed_areas) |
                    Q(customer__area__in=managed_areas) |
                    Q(customer__created_by__in=managed_subordinates) |
                    Q(customer__assigned_team__in=managed_subordinates)
                ).distinct()

        # 8. Purchases: PurchaseOrder & PurchaseReturnOrder
        elif m_name in ['purchaseorder', 'purchasereturnorder']:
            wh_field = 'warehouse' if m_name == 'purchasereturnorder' else 'target_warehouse'
            if scope == 'own':
                return queryset.filter(created_by=user)
            elif scope == 'brick':
                return queryset.filter(
                    Q(created_by=user) |
                    Q(**{f"{wh_field}__assigned_user": user}) |
                    Q(**{f"{wh_field}__area__in": user_bricks}) |
                    Q(supplier__brick__in=user_bricks)
                ).distinct()
            elif scope == 'area':
                return queryset.filter(
                    Q(created_by__in=managed_subordinates) |
                    Q(**{f"{wh_field}__assigned_user__in": managed_subordinates}) |
                    Q(**{f"{wh_field}__area__in": managed_areas}) |
                    Q(supplier__area__in=managed_areas) |
                    Q(supplier__brick__in=managed_areas)
                ).distinct()

        # 9. Inventory: Warehouse
        elif m_name == 'warehouse':
            if scope == 'own':
                return queryset.filter(
                    Q(assigned_user=user) | Q(is_main=True) | (Q(area__isnull=True) & Q(assigned_user__isnull=True))
                ).distinct()
            elif scope == 'brick':
                return queryset.filter(
                    Q(assigned_user=user) |
                    Q(is_main=True) |
                    Q(area__in=user_bricks) |
                    (Q(area__isnull=True) & Q(assigned_user__isnull=True))
                ).distinct()
            elif scope == 'area':
                return queryset.filter(
                    Q(is_main=True) |
                    Q(assigned_user__in=managed_subordinates) |
                    Q(area__in=managed_areas) |
                    (Q(area__isnull=True) & Q(assigned_user__isnull=True))
                ).distinct()

        # 10. Inventory: InventoryStock
        elif m_name == 'inventorystock':
            from inventory.models import Warehouse
            scoped_warehouses = cls.get_scoped_queryset(Warehouse.objects.all(), user, 'warehouse', scope_type)
            return queryset.filter(warehouse__in=scoped_warehouses)

        # 11. Inventory: InventoryMemo
        elif m_name == 'inventorymemo':
            from inventory.models import Warehouse
            scoped_warehouses = cls.get_scoped_queryset(Warehouse.objects.all(), user, 'warehouse', scope_type)
            return queryset.filter(warehouse__in=scoped_warehouses)

        # 12. Inventory: ProductTransferRequest
        elif m_name == 'producttransferrequest':
            if scope == 'own':
                return queryset.filter(
                    Q(requesting_user=user) |
                    Q(source_warehouse__assigned_user=user) |
                    Q(destination_warehouse__assigned_user=user)
                ).distinct()
            elif scope == 'brick':
                return queryset.filter(
                    Q(requesting_user__in=managed_subordinates) |
                    Q(source_warehouse__assigned_user=user) |
                    Q(destination_warehouse__assigned_user=user) |
                    Q(source_warehouse__area__in=user_bricks) |
                    Q(destination_warehouse__area__in=user_bricks)
                ).distinct()
            elif scope == 'area':
                return queryset.filter(
                    Q(requesting_user__in=managed_subordinates) |
                    Q(source_warehouse__assigned_user__in=managed_subordinates) |
                    Q(destination_warehouse__assigned_user__in=managed_subordinates) |
                    Q(source_warehouse__area__in=managed_areas) |
                    Q(destination_warehouse__area__in=managed_areas)
                ).distinct()

        # 13. Treasury: Vault
        elif m_name == 'vault':
            if scope == 'own':
                return queryset.filter(assigned_user=user)
            elif scope == 'brick':
                return queryset.filter(
                    Q(assigned_user=user) |
                    Q(area__in=user_bricks)
                ).distinct()
            elif scope == 'area':
                return queryset.filter(
                    Q(assigned_user=user) |
                    Q(assigned_user__in=managed_subordinates) |
                    Q(area__in=managed_areas)
                ).distinct()

        # 14. Treasury: VaultTransaction
        elif m_name == 'vaulttransaction':
            from treasury.models import Vault
            scoped_vaults = cls.get_scoped_queryset(Vault.objects.all(), user, 'vault', scope_type)
            return queryset.filter(vault__in=scoped_vaults)

        # 15. Treasury: VendorPayment & VendorTransaction
        elif m_name in ['vendorpayment', 'vendortransaction']:
            if scope == 'own':
                return queryset.filter(created_by=user)
            return queryset.filter(created_by__in=managed_subordinates).distinct()

        # 16. Accounts: User
        elif m_name == 'user':
            if scope == 'own':
                return queryset.filter(pk=user.pk)
            elif scope == 'brick':
                return queryset.filter(
                    Q(pk=user.pk) | Q(assigned_areas__in=user_bricks)
                ).distinct()
            elif scope == 'area':
                return queryset.filter(
                    Q(pk=user.pk) | Q(assigned_areas__in=managed_areas)
                ).distinct()

        # 17. Treasury: VendorAccount
        elif m_name == 'vendoraccount':
            if scope == 'own':
                return queryset.filter(Q(vendor__created_by=user) | Q(vendor__assigned_team=user))
            elif scope == 'brick':
                return queryset.filter(
                    Q(vendor__brick__in=user_bricks) |
                    Q(vendor__area__in=user_bricks) |
                    Q(vendor__created_by=user) |
                    Q(vendor__assigned_team=user)
                ).distinct()
            elif scope == 'area':
                return queryset.filter(
                    Q(vendor__brick__in=managed_areas) |
                    Q(vendor__area__in=managed_areas) |
                    Q(vendor__created_by__in=managed_subordinates) |
                    Q(vendor__assigned_team__in=managed_subordinates)
                ).distinct()

        # 18. Activities: VisitTemplate
        elif m_name == 'visittemplate':
            qs = queryset.filter(active=True)
            user_role = getattr(user, 'role', None)
            if user_role:
                return qs.filter(Q(restricted_roles__isnull=True) | Q(restricted_roles=user_role)).distinct()
            return qs

        # Fail closed for any unhandled model
        return queryset.none()

    @classmethod
    def can_user_access_object(cls, user, obj, action: str = 'view') -> bool:
        """
        Object-level security checker protecting against IDOR, BOLA, and privilege escalation.
        Enforces:
        1. SuperAdmin / Superuser company-wide access.
        2. Anti-self-approval: Users cannot approve or reject their own submissions.
        3. Configurable scope resolution (View scope for 'view', Manage scope for mutations).
        """
        if not user or not user.is_authenticated or not user.is_active:
            return False

        if getattr(user, 'is_super_admin', False) or user.is_superuser:
            return True

        role = getattr(user, 'role', None)
        if role and getattr(role, 'is_super', False):
            return True

        # Anti-self-approval rule across all models
        if action in ['approve', 'reject', 'disapprove', 'execute']:
            owner_id = (
                getattr(obj, 'owner_id', None) or
                getattr(obj, 'created_by_id', None) or
                getattr(obj, 'requesting_user_id', None)
            )
            if owner_id == user.id:
                return False

        # Determine scope type: 'manage' for mutations/approvals, 'view' for reading
        scope_type = 'manage' if action in [
            'edit', 'delete', 'approve', 'reject', 'disapprove', 'execute', 'manage', 'operate'
        ] else 'view'

        model_class = obj.__class__
        m_name = model_class.__name__.lower()

        # Handle specific model rules:
        # 1. Warehouse: editing/deleting reserved for superadmin or inventory:warehouses/manage
        if m_name == 'warehouse':
            if action in ['edit', 'delete', 'manage']:
                from accounts.permissions import has_perm_or_admin
                if not has_perm_or_admin(user, 'inventory:warehouses/manage'):
                    return False
            elif action == 'operate':
                if obj.is_main or obj.assigned_user_id == user.id:
                    return True
                if obj.assigned_user_id is not None and obj.assigned_user_id != user.id:
                    return False

        # 2. Vault: transacting requires treasury permissions and ownership/manage scope
        elif m_name == 'vault':
            from accounts.permissions import has_perm_or_admin
            if action in ['edit', 'manage', 'delete']:
                if not has_perm_or_admin(user, 'treasury:vaults/manage'):
                    return False
            elif action in ['transfer', 'withdraw', 'deposit']:
                if not has_perm_or_admin(user, 'treasury:vaults/transfer'):
                    return False
                if obj.assigned_user_id == user.id:
                    return True

        # 3. ProductTransferRequest: rep cannot approve or execute transfer
        elif m_name == 'producttransferrequest':
            from accounts.permissions import has_perm_or_admin
            if action in ['approve', 'reject', 'execute']:
                if not has_perm_or_admin(user, 'inventory:transfers/approve'):
                    return False

        # 4. Agreement editing/deleting when status is approved/done
        elif m_name == 'agreement':
            if action in ['edit', 'delete'] and obj.status in ['approved', 'done']:
                return False

        # General check against scoped queryset
        scoped_qs = cls.get_scoped_queryset(
            model_class.objects.filter(pk=obj.pk),
            user,
            model_name=m_name,
            scope_type=scope_type
        )
        return scoped_qs.exists()

    @classmethod
    def get_scoped_choices(cls, user, target_choice_type: str, context_module: str = None):
        """
        Scoping helper for form dropdowns and autocomplete selectors:
        - 'governorates': Governorates/Main Areas authorized for user
        - 'bricks': Bricks authorized for user
        - 'customers': Scoped Contact list
        - 'suppliers': Scoped Supplier list
        - 'warehouses': Scoped Warehouse list
        - 'vaults': Scoped Vault list
        - 'subordinates': Subordinate Users list
        """
        from master_data.models import Area
        from contacts.models import Contact
        from inventory.models import Warehouse
        from treasury.models import Vault

        module = context_module or 'contacts'
        scope = cls.get_user_scope(user, module, 'view')

        if target_choice_type == 'governorates':
            if scope == 'all':
                govs = Area.objects.filter(parent__isnull=True, is_company_area=False).order_by('name')
                return govs if govs.exists() else Area.objects.filter(is_company_area=False).order_by('name')
            return cls.get_user_main_areas(user).order_by('name')

        elif target_choice_type == 'bricks':
            if scope == 'all':
                return Area.objects.filter(parent__isnull=False, is_company_area=False).select_related('parent').order_by('name')
            elif scope == 'area':
                main_areas = cls.get_user_main_areas(user)
                return Area.objects.filter(parent__in=main_areas, is_company_area=False).select_related('parent').order_by('name')
            else:
                return cls.get_user_bricks(user).filter(parent__isnull=False, is_company_area=False).select_related('parent').order_by('name')

        elif target_choice_type == 'customers':
            return cls.get_scoped_queryset(
                Contact.objects.filter(is_customer=True, status='active'),
                user,
                'contact',
                'view'
            ).order_by('name')

        elif target_choice_type == 'suppliers':
            return cls.get_scoped_queryset(
                Contact.objects.filter(is_supplier=True),
                user,
                'contact',
                'view'
            ).order_by('name')

        elif target_choice_type == 'warehouses':
            return cls.get_scoped_queryset(
                Warehouse.objects.filter(is_active=True),
                user,
                'warehouse',
                'view'
            ).order_by('name')

        elif target_choice_type == 'vaults':
            return cls.get_scoped_queryset(
                Vault.objects.filter(is_active=True),
                user,
                'vault',
                'view'
            ).order_by('name')

        elif target_choice_type == 'subordinates':
            return cls.get_user_managed_subordinates(user, module).order_by('name')

        return Area.objects.none()
