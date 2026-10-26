import os
import django
from decimal import Decimal

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.utils import timezone
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from accounts.models import Role, RoleTag, User
from accounts.permission_registry import get_all_registered_permissions
from master_data.models import Area, CompanyProfile
from contacts.models import Contact, ContactAddress
from catalog.models import ProductCategory, Product
from inventory.models import Warehouse, InventoryStock
from treasury.models import Vault, VendorAccount
from purchases.models import PurchaseOrder, PurchaseOrderItem
from sales.models import SalesOrder, SalesOrderItem, CustomerAccount
from activities.models import (
    Visit, VisitTemplate, PlannedVisitDay, PlannedVisitItem, AgendaTodo
)

DEFAULT_PASSWORD = "Wea@1234"

def seed_users_and_flows():
    print("=" * 60)
    print("SEEDING COMPREHENSIVE ERP TEST USERS & WORKFLOW ARTIFACTS")
    print("=" * 60)

    # 1. Sync all permissions map
    perm_map = {p.codename: p for p in Permission.objects.all()}

    # 2. Configure / Enhance Roles
    print("\n--- 1. Setting Up Enterprise Roles ---")

    # SuperAdmin
    super_role, _ = Role.objects.get_or_create(
        name="SuperAdmin",
        defaults={
            "display_name": "مدير النظام الأعلى (SuperAdmin)",
            "description": "صلاحيات غير مقيدة على كافة أقسام النظام والإعدادات",
            "is_system": True,
            "is_super": True,
            "can_hold_vault": True
        }
    )
    super_role.is_super = True
    super_role.is_system = True
    super_role.permissions.set(list(perm_map.values()))
    super_role.save()

    # Admin (Operations)
    admin_role, _ = Role.objects.get_or_create(
        name="Admin",
        defaults={
            "display_name": "مدير النظام والعمليات (Admin)",
            "description": "إدارة الإعدادات، المنتجات، جهات الاتصال، والمخازن",
            "is_system": True,
        }
    )
    admin_perms = [p for c, p in perm_map.items() if not c.startswith('system:rbac')]
    admin_role.permissions.set(admin_perms)
    admin_role.save()

    # CEO
    ceo_role, _ = Role.objects.get_or_create(
        name="CEO",
        defaults={
            "display_name": "المدير العام والتنفيذي (CEO)",
            "description": "رؤية شاملة للشركة، التقارير التنفيذية، والاعتمادات",
            "is_system": True,
        }
    )
    ceo_perms = [p for c, p in perm_map.items() if c.startswith('module:') or '/list' in c or '/view' in c or '/approve' in c or '/export' in c]
    ceo_role.permissions.set(ceo_perms)
    ceo_role.save()

    # AreaManager
    area_mgr_role, _ = Role.objects.get_or_create(
        name="AreaManager",
        defaults={
            "display_name": "مدير منطقة إقليمي (Area Manager)",
            "description": "إشراف على مناديب المنطقة، واعتماد الزيارات من الأجندة وقائمة الزيارات",
            "is_system": True,
            "is_sales_team": True,
            "is_area_manager": True,
            "is_main_area_bound": True,
            "has_sales_targets": True,
        }
    )
    area_mgr_role.is_area_manager = True
    area_mgr_role.is_main_area_bound = True
    area_mgr_role.is_sales_team = True
    area_perms = [
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
    ]
    area_mgr_role.permissions.set([perm_map[c] for c in area_perms if c in perm_map])
    area_mgr_role.save()

    # MedicalRep
    rep_role, _ = Role.objects.get_or_create(
        name="MedicalRep",
        defaults={
            "display_name": "مندوب دعاية ومبيعات (Medical Rep)",
            "description": "تسجيل الزيارات، تنفيذ خطة الأجندة، أوامر البيع والتحصيلات",
            "is_system": True,
            "is_sales_team": True,
            "is_rep": True,
            "is_sub_area_bound": True,
            "can_hold_vault": True,
            "has_sales_targets": True,
        }
    )
    rep_role.is_rep = True
    rep_role.is_sub_area_bound = True
    rep_role.is_sales_team = True
    rep_role.can_hold_vault = True
    rep_perms = [
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
    rep_role.permissions.set([perm_map[c] for c in rep_perms if c in perm_map])
    rep_role.save()

    # PurchasingOfficer
    purchasing_officer_role, _ = Role.objects.get_or_create(
        name="PurchasingOfficer",
        defaults={
            "display_name": "مسؤول المشتريات والتوريدات (Purchasing Officer)",
            "description": "إنشاء وتعديل أوامر المشتريات وإدارتها مع الموردين",
            "is_system": False,
        }
    )
    po_perms = [
        'module:purchases', 'purchases:orders/list', 'purchases:orders/view',
        'purchases:orders/create', 'purchases:orders/edit', 'purchases:orders/export',
        'purchases:returns/list', 'purchases:returns/view', 'purchases:returns/create',
        'module:contacts', 'contacts:contacts/list', 'contacts:contacts/view',
        'module:catalog', 'catalog:products/list', 'catalog:products/view',
        'module:inventory', 'inventory:stocks/view',
    ]
    purchasing_officer_role.permissions.set([perm_map[c] for c in po_perms if c in perm_map])
    purchasing_officer_role.save()

    # PurchasingManager
    purchasing_mgr_role, _ = Role.objects.get_or_create(
        name="PurchasingManager",
        defaults={
            "display_name": "مدير المشتريات والاعتمادات (Purchasing Manager)",
            "description": "اعتماد أو رفض أوامر المشتريات وإلغائها وإدارة المرتجعات",
            "is_system": False,
        }
    )
    pm_perms = [
        'module:purchases', 'purchases:orders/list', 'purchases:orders/view',
        'purchases:orders/create', 'purchases:orders/edit', 'purchases:orders/approve',
        'purchases:orders/cancel', 'purchases:orders/export',
        'purchases:returns/list', 'purchases:returns/view', 'purchases:returns/manage', 'purchases:returns/export',
        'module:contacts', 'contacts:contacts/list', 'contacts:contacts/view', 'contacts:contacts/create', 'contacts:contacts/edit',
        'module:catalog', 'catalog:products/list', 'catalog:products/view',
        'module:inventory', 'inventory:stocks/view', 'inventory:warehouses/manage',
    ]
    purchasing_mgr_role.permissions.set([perm_map[c] for c in pm_perms if c in perm_map])
    purchasing_mgr_role.save()

    # WarehouseKeeper
    wh_keeper_role, _ = Role.objects.get_or_create(
        name="WarehouseKeeper",
        defaults={
            "display_name": "أمين المخزن (Warehouse Keeper)",
            "description": "استلام بضاعة المشتريات في المخزن وصرف طلبيات البيع",
            "is_system": False,
        }
    )
    wh_perms = [
        'module:inventory', 'inventory:stocks/view', 'inventory:warehouses/manage', 'inventory:memos/manage',
        'module:purchases', 'purchases:orders/list', 'purchases:orders/view', 'purchases:orders/stock',
        'module:sales', 'sales:orders/list', 'sales:orders/view', 'sales:orders/unstock',
        'module:catalog', 'catalog:products/list', 'catalog:products/view',
    ]
    wh_keeper_role.permissions.set([perm_map[c] for c in wh_perms if c in perm_map])
    wh_keeper_role.save()

    # Accountant
    accountant_role, _ = Role.objects.get_or_create(
        name="Accountant",
        defaults={
            "display_name": "محاسب مالي عام (Chief Accountant)",
            "description": "ترحيل فواتير الشراء والبيع، مدفوعات الموردين، وإدارة الخزينة",
            "is_system": True,
            "can_hold_vault": True,
        }
    )
    accountant_role.can_hold_vault = True
    acc_perms = [
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
    accountant_role.permissions.set([perm_map[c] for c in acc_perms if c in perm_map])
    accountant_role.save()

    print("Roles configured successfully.")

    # 3. Setup Geographic Areas
    print("\n--- 2. Setting Up Geographic Areas ---")
    cairo_gov, _ = Area.objects.get_or_create(code="01", defaults={"name": "محافظة القاهرة", "area_type": "governorate"})
    giza_gov, _ = Area.objects.get_or_create(code="03", defaults={"name": "محافظة الجيزة", "area_type": "governorate"})
    alex_gov = Area.objects.filter(code="GOV-008").first() or Area.objects.filter(name__icontains="الاسكندرية").first()
    if not alex_gov:
        alex_gov = Area.objects.create(code="GOV-008", name="محافظة الاسكندرية", area_type="governorate")

    # Cairo subareas
    nasr_city = Area.objects.filter(parent=cairo_gov, name__icontains="مدينة نصر").first() or Area.objects.filter(name__icontains="مدينة نصر").first()
    if not nasr_city:
        nasr_city, _ = Area.objects.get_or_create(code="01-SUB-01", defaults={"name": "مدينة نصر", "area_type": "subarea", "parent": cairo_gov})
    heliopolis = Area.objects.filter(parent=cairo_gov, name__icontains="مصر الجديدة").first() or Area.objects.filter(name__icontains="مصر الجديدة").first()
    if not heliopolis:
        heliopolis, _ = Area.objects.get_or_create(code="01-SUB-02", defaults={"name": "مصر الجديدة", "area_type": "subarea", "parent": cairo_gov})

    # Giza subareas
    ahram = Area.objects.filter(parent=giza_gov, name__icontains="الأهرام").first() or Area.objects.filter(name__icontains="الأهرام").first()
    if not ahram:
        ahram, _ = Area.objects.get_or_create(code="0312", defaults={"name": "حدائق الأهرام", "area_type": "subarea", "parent": giza_gov})
    mohandessin = Area.objects.filter(parent=giza_gov, name__icontains="المهندسين").first() or Area.objects.filter(name__icontains="المهندسين").first()
    if not mohandessin:
        mohandessin, _ = Area.objects.get_or_create(code="0364", defaults={"name": "المهندسين", "area_type": "subarea", "parent": giza_gov})

    # Alex subareas
    smouha = Area.objects.filter(parent=alex_gov, name__icontains="سموحة").first() or Area.objects.filter(name__icontains="سموحة").first()
    if not smouha:
        smouha, _ = Area.objects.get_or_create(code="GOV-008-SUB-01", defaults={"name": "سموحة", "area_type": "subarea", "parent": alex_gov})
    miami = Area.objects.filter(parent=alex_gov, name__icontains="ميامي").first() or Area.objects.filter(name__icontains="ميامي").first()
    if not miami:
        miami, _ = Area.objects.get_or_create(code="GOV-008-SUB-03", defaults={"name": "ميامي", "area_type": "subarea", "parent": alex_gov})

    # 4. Warehouses & Vaults
    print("\n--- 3. Setting Up Warehouses & Vaults ---")
    main_wh, _ = Warehouse.objects.get_or_create(
        code="WH-MAIN",
        defaults={
            "name": "المخزن الرئيسي بضاعه",
            "is_main": True,
            "address": "حدائق الأهرام - الجيزة"
        }
    )

    main_vault, _ = Vault.objects.get_or_create(
        name="الخزنة الرئيسية",
        defaults={
            "serial_num": 1001,
            "vault_type": "cash",
            "current_balance": Decimal("250000.00")
        }
    )

    vault_cairo, _ = Vault.objects.get_or_create(
        name="خزنة عهدة مندوب القاهرة",
        defaults={
            "serial_num": 1011,
            "vault_type": "cash",
            "current_balance": Decimal("5000.00")
        }
    )

    vault_giza, _ = Vault.objects.get_or_create(
        name="خزنة عهدة مندوب الجيزة",
        defaults={
            "serial_num": 1012,
            "vault_type": "cash",
            "current_balance": Decimal("3500.00")
        }
    )

    vault_alex, _ = Vault.objects.get_or_create(
        name="خزنة عهدة مندوب الإسكندرية",
        defaults={
            "serial_num": 1013,
            "vault_type": "cash",
            "current_balance": Decimal("4200.00")
        }
    )

    # 5. Create Test Users
    print("\n--- 4. Creating Standard Test Users ---")
    users_data = [
        {
            "username": "superadmin",
            "email": "superadmin@wea.com",
            "name": "د. وائل عطا (مدير النظام الأعلى)",
            "role": super_role,
            "is_superuser": True,
            "is_staff": True,
            "mobile": "01111787179",
            "areas": [cairo_gov, giza_gov, alex_gov],
        },
        {
            "username": "wea.pharm2020@gmail.com",
            "email": "wea.pharm2020@gmail.com",
            "name": "د. وائل عطا (حساب المرجع)",
            "role": super_role,
            "is_superuser": True,
            "is_staff": True,
            "mobile": "01111787179",
            "areas": [cairo_gov, giza_gov, alex_gov],
        },
        {
            "username": "admin",
            "email": "admin@wea.com",
            "name": "أحمد إبراهيم (مدير العمليات والنظام)",
            "role": admin_role,
            "is_superuser": False,
            "is_staff": True,
            "mobile": "01001122334",
            "areas": [cairo_gov, giza_gov, alex_gov],
        },
        {
            "username": "ceo",
            "email": "ceo@wea.com",
            "name": "د. سارة عادل (المدير التنفيذي CEO)",
            "role": ceo_role,
            "is_superuser": False,
            "is_staff": False,
            "mobile": "01002233445",
            "areas": [cairo_gov, giza_gov, alex_gov],
        },
        {
            "username": "manager_cairo",
            "email": "manager_cairo@wea.com",
            "name": "محمود حسان (مدير منطقة القاهرة)",
            "role": area_mgr_role,
            "is_superuser": False,
            "is_staff": False,
            "mobile": "01003344556",
            "areas": [cairo_gov, nasr_city, heliopolis],
        },
        {
            "username": "rep_cairo",
            "email": "rep_cairo@wea.com",
            "name": "محمد خليل (مندوب القاهرة - مدينة نصر)",
            "role": rep_role,
            "is_superuser": False,
            "is_staff": False,
            "mobile": "01004455667",
            "areas": [nasr_city, heliopolis],
            "vault": vault_cairo,
        },
        {
            "username": "manager_giza",
            "email": "manager_giza@wea.com",
            "name": "طارق سليم (مدير منطقة الجيزة)",
            "role": area_mgr_role,
            "is_superuser": False,
            "is_staff": False,
            "mobile": "01005566778",
            "areas": [giza_gov, ahram, mohandessin],
        },
        {
            "username": "rep_giza",
            "email": "rep_giza@wea.com",
            "name": "كريم ممدوح (مندوب الجيزة - حدائق الأهرام)",
            "role": rep_role,
            "is_superuser": False,
            "is_staff": False,
            "mobile": "01006677889",
            "areas": [ahram, mohandessin],
            "vault": vault_giza,
        },
        {
            "username": "manager_alex",
            "email": "manager_alex@wea.com",
            "name": "يوسف ناصر (مدير منطقة الإسكندرية)",
            "role": area_mgr_role,
            "is_superuser": False,
            "is_staff": False,
            "mobile": "01007788990",
            "areas": [alex_gov, smouha, miami],
        },
        {
            "username": "rep_alex",
            "email": "rep_alex@wea.com",
            "name": "علي الشاذلي (مندوب الإسكندرية - سموحة)",
            "role": rep_role,
            "is_superuser": False,
            "is_staff": False,
            "mobile": "01008899001",
            "areas": [smouha, miami],
            "vault": vault_alex,
        },
        {
            "username": "buyer",
            "email": "buyer@wea.com",
            "name": "هاني جرجس (مسؤول المشتريات والتوريدات)",
            "role": purchasing_officer_role,
            "is_superuser": False,
            "is_staff": False,
            "mobile": "01009900112",
            "areas": [cairo_gov, giza_gov],
        },
        {
            "username": "manager_purchases",
            "email": "manager_purchases@wea.com",
            "name": "سامح فؤاد (مدير المشتريات والاعتمادات)",
            "role": purchasing_mgr_role,
            "is_superuser": False,
            "is_staff": False,
            "mobile": "01011122233",
            "areas": [cairo_gov, giza_gov],
        },
        {
            "username": "warehouse_keeper",
            "email": "warehouse_keeper@wea.com",
            "name": "عماد مصطفى (أمين المخزن الرئيسي)",
            "role": wh_keeper_role,
            "is_superuser": False,
            "is_staff": False,
            "mobile": "01022233344",
            "areas": [giza_gov],
        },
        {
            "username": "accountant",
            "email": "accountant@wea.com",
            "name": "حازم عبد الرحمن (رئيس الحسابات والمالية)",
            "role": accountant_role,
            "is_superuser": False,
            "is_staff": False,
            "mobile": "01033344455",
            "areas": [cairo_gov, giza_gov],
            "vault": main_vault,
        },
    ]

    created_users = {}
    for u_spec in users_data:
        uname = u_spec["username"]
        u = User.objects.filter(username=uname).first()
        if not u:
            u = User.objects.create_user(
                username=uname,
                email=u_spec["email"],
                password=DEFAULT_PASSWORD,
                name=u_spec["name"],
                role=u_spec["role"],
                is_superuser=u_spec.get("is_superuser", False),
                is_staff=u_spec.get("is_staff", False),
                mobile=u_spec.get("mobile", ""),
                bypass_location_verification=True
            )
            print(f"Created user: {uname} ({u_spec['role'].name})")
        else:
            u.email = u_spec["email"]
            u.name = u_spec["name"]
            u.role = u_spec["role"]
            u.is_superuser = u_spec.get("is_superuser", False)
            u.is_staff = u_spec.get("is_staff", False)
            u.mobile = u_spec.get("mobile", "")
            u.bypass_location_verification = True
            u.set_password(DEFAULT_PASSWORD)
            u.save()
            print(f"Updated user: {uname} ({u_spec['role'].name})")

        # Assign areas
        if "areas" in u_spec:
            u.assigned_areas.set(u_spec["areas"])

        # Assign vault
        if "vault" in u_spec:
            u_spec["vault"].assigned_user = u
            u_spec["vault"].save()

        created_users[uname] = u

    # Link warehouse manager
    main_wh.manager = created_users["warehouse_keeper"]
    main_wh.save()

    # 6. Sample Contacts in Cairo, Giza, and Alex
    print("\n--- 5. Ensuring Sample Contacts for Each Area ---")
    contact_cairo = Contact.objects.filter(area=nasr_city).first()
    if not contact_cairo:
        contact_cairo = Contact.objects.create(
            name="د. تامر فهمي (عيادة مدينة نصر)",
            contact_type="person",
            account_type="Clinic",
            specialty="Orthopedic / عظام",
            area=nasr_city,
            mobile="01012345678",
            created_by=created_users["rep_cairo"]
        )
    CustomerAccount.get_or_create_for_customer(contact_cairo)

    pharmacy_cairo = Contact.objects.filter(area=nasr_city, account_type="Pharmacy").first()
    if not pharmacy_cairo:
        pharmacy_cairo = Contact.objects.create(
            name="صيدلية الأمل الكبرى (مدينة نصر)",
            contact_type="company",
            account_type="Pharmacy",
            area=nasr_city,
            mobile="01087654321",
            created_by=created_users["rep_cairo"]
        )
    CustomerAccount.get_or_create_for_customer(pharmacy_cairo)

    contact_giza = Contact.objects.filter(area=ahram).first()
    if not contact_giza:
        contact_giza = Contact.objects.create(
            name="د. شريف رمزي (مركز الأهرام الطبي)",
            contact_type="person",
            account_type="Center",
            specialty="Cardiology / قلب وأوعية دموية",
            area=ahram,
            mobile="01123456789",
            created_by=created_users["rep_giza"]
        )
    CustomerAccount.get_or_create_for_customer(contact_giza)

    contact_alex = Contact.objects.filter(area=smouha).first()
    if not contact_alex:
        contact_alex = Contact.objects.create(
            name="د. إبراهيم فودة (مستشفى سموحة التخصصي)",
            contact_type="person",
            account_type="Hospital",
            specialty="Pediatrics / أطفال",
            area=smouha,
            mobile="01234567890",
            created_by=created_users["rep_alex"]
        )
    CustomerAccount.get_or_create_for_customer(contact_alex)

    supplier = Contact.objects.filter(is_supplier=True).first()
    if not supplier:
        supplier = Contact.objects.create(
            name="مصنع اورجانيك للمكملات الغذائية بنها",
            contact_type="company",
            is_supplier=True,
            is_customer=False,
            area=giza_gov,
            mobile="01009876543",
            credit_limit=Decimal("500000.00"),
            credit_period_days=45,
            created_by=created_users["superadmin"]
        )
    VendorAccount.get_or_create_for_supplier(supplier)

    # 7. Products Check
    print("\n--- 6. Checking Products & Stock ---")
    p1 = Product.objects.filter(sku_code="GE1").first()
    if not p1:
        cat_wea, _ = ProductCategory.objects.get_or_create(code="WEA", defaults={"name": "منتجات WEA Pharma"})
        p1 = Product.objects.create(
            sku_code="GE1",
            category=cat_wea,
            name="Geron Capsules 30s",
            retail_price=Decimal("140.00"),
            default_purchase_cost=Decimal("18.80"),
            unit="عبوة",
            is_active=True,
            created_by=created_users["superadmin"]
        )

    p2 = Product.objects.filter(sku_code="WEA-C1000").first()
    if not p2:
        cat_wea, _ = ProductCategory.objects.get_or_create(code="WEA", defaults={"name": "منتجات WEA Pharma"})
        p2 = Product.objects.create(
            sku_code="WEA-C1000",
            category=cat_wea,
            name="WEA Vitamin C 1000mg",
            retail_price=Decimal("95.00"),
            default_purchase_cost=Decimal("24.50"),
            unit="عبوة",
            is_active=True,
            created_by=created_users["superadmin"]
        )

    from inventory.models import InventoryLot
    # Initial stock in main warehouse
    stock1, _ = InventoryStock.objects.get_or_create(
        product=p1,
        warehouse=main_wh,
        defaults={"qty_on_hand": Decimal("1500"), "product_cost": p1.default_purchase_cost}
    )
    InventoryLot.objects.get_or_create(
        stock=stock1,
        batch_number="B-2026-01",
        defaults={"quantity": Decimal("1500"), "expiry_date": timezone.now().date().replace(year=timezone.now().year + 2)}
    )

    stock2, _ = InventoryStock.objects.get_or_create(
        product=p2,
        warehouse=main_wh,
        defaults={"qty_on_hand": Decimal("2000"), "product_cost": p2.default_purchase_cost}
    )
    InventoryLot.objects.get_or_create(
        stock=stock2,
        batch_number="B-2026-02",
        defaults={"quantity": Decimal("2000"), "expiry_date": timezone.now().date().replace(year=timezone.now().year + 2)}
    )

    # 8. Templates
    template_dr = VisitTemplate.objects.filter(active=True).first()
    today = timezone.now().date()

    # 9. Live Agenda & Visits for Cairo Rep
    print("\n--- 7. Seeding Live Agenda & Visits for Testing ---")
    rep_c = created_users["rep_cairo"]
    plan_day_today, _ = PlannedVisitDay.objects.get_or_create(
        assignee=rep_c,
        date=today,
        defaults={"created_by": created_users["manager_cairo"], "status": "new"}
    )

    # Item 1: Unexecuted planned visit (Ready to click "بدء الزيارة" from Agenda)
    item_unexecuted, _ = PlannedVisitItem.objects.get_or_create(
        plan_day=plan_day_today,
        order=1,
        defaults={
            "contact": contact_cairo,
            "template": template_dr,
            "is_executed": False,
            "notes": "زيارة صباحية دورية لمناقشة دواء Geron مع الطبيب"
        }
    )

    # Item 2: Executed finished visit pending approval (Ready for manager_cairo to approve or decline on Agenda / Visits)
    visit_pending = Visit.objects.filter(owner=rep_c, date=today, status="finished", approval_status="pending").first()
    if not visit_pending:
        max_sn = Visit.objects.aggregate(django.db.models.Max('serial_num'))['serial_num__max'] or 7000
        visit_pending = Visit.objects.create(
            serial_num=max_sn + 1,
            owner=rep_c,
            contact=pharmacy_cairo,
            template=template_dr,
            date=today,
            status="finished",
            approval_status="pending",
            feedback="تمت الزيارة ومراجعة العينات المتوفرة بصيدلية الأمل، ومناقشة الخصم التجاري.",
            is_successful=True,
            is_planned=True,
            created_by=rep_c
        )
    
    item_executed, _ = PlannedVisitItem.objects.get_or_create(
        plan_day=plan_day_today,
        order=2,
        defaults={
            "contact": pharmacy_cairo,
            "template": template_dr,
            "is_executed": True,
            "visit": visit_pending,
            "notes": "متابعة صيدلية الأمل"
        }
    )
    if not item_executed.visit:
        item_executed.visit = visit_pending
        item_executed.is_executed = True
        item_executed.save()

    # Personal Todos for rep_cairo on Agenda
    AgendaTodo.objects.get_or_create(
        user=rep_c,
        date=today,
        title="متابعة تحصيل شيك صيدلية الأمل المؤجل",
        defaults={"is_completed": False}
    )
    AgendaTodo.objects.get_or_create(
        user=rep_c,
        date=today,
        title="تجهيز عينات Geron لعيادة د. تامر فهمي",
        defaults={"is_completed": True}
    )

    # 10. Live Purchases Flow Data
    print("\n--- 8. Seeding Live Purchases Flow Artifacts ---")
    buyer_u = created_users["buyer"]
    po_mgr = created_users["manager_purchases"]

    # PO 1: Pending (Ready for manager_purchases to Approve or Reject with reason modal)
    po_pending = PurchaseOrder.objects.filter(order_number="PO-TEST-PENDING").first()
    if not po_pending:
        max_po = PurchaseOrder.objects.aggregate(django.db.models.Max('serial_num'))['serial_num__max'] or 2000
        po_pending = PurchaseOrder.objects.create(
            serial_num=max_po + 1,
            order_number="PO-TEST-PENDING",
            supplier=supplier,
            target_warehouse=main_wh,
            order_date=today,
            status="pending",
            items_count=2,
            items_quantity=Decimal("500"),
            subtotal=Decimal("9400.00"),
            grand_total=Decimal("9400.00"),
            notes="أمر توريد مواد خام ومكملات غذائية للربع الرابع",
            created_by=buyer_u
        )
        PurchaseOrderItem.objects.create(
            order=po_pending,
            product=p1,
            quantity=Decimal("500"),
            unit_price=Decimal("18.80"),
            total_price=Decimal("9400.00")
        )

    # PO 2: Approved (Ready for warehouse_keeper to click "إدخال المخزن / Stock Order")
    po_approved = PurchaseOrder.objects.filter(order_number="PO-TEST-APPROVED").first()
    if not po_approved:
        max_po = PurchaseOrder.objects.aggregate(django.db.models.Max('serial_num'))['serial_num__max'] or 2000
        po_approved = PurchaseOrder.objects.create(
            serial_num=max_po + 1,
            order_number="PO-TEST-APPROVED",
            supplier=supplier,
            target_warehouse=main_wh,
            order_date=today,
            status="approved",
            approved_by=po_mgr,
            approved_at=timezone.now(),
            items_count=1,
            items_quantity=Decimal("200"),
            subtotal=Decimal("4900.00"),
            grand_total=Decimal("4900.00"),
            notes="أمر شراء معتمد من الإدارة جاهز للاستلام المخزني",
            created_by=buyer_u
        )
        PurchaseOrderItem.objects.create(
            order=po_approved,
            product=p2,
            quantity=Decimal("200"),
            unit_price=Decimal("24.50"),
            total_price=Decimal("4900.00")
        )

    # PO 3: Picked / Stocked (Ready for accountant to click "ترحيل للحسابات / Invoice Order")
    po_picked = PurchaseOrder.objects.filter(order_number="PO-TEST-PICKED").first()
    if not po_picked:
        max_po = PurchaseOrder.objects.aggregate(django.db.models.Max('serial_num'))['serial_num__max'] or 2000
        po_picked = PurchaseOrder.objects.create(
            serial_num=max_po + 1,
            order_number="PO-TEST-PICKED",
            supplier=supplier,
            target_warehouse=main_wh,
            order_date=today,
            status="picked",
            approved_by=po_mgr,
            approved_at=timezone.now(),
            stocked_at=timezone.now(),
            items_count=1,
            items_quantity=Decimal("100"),
            subtotal=Decimal("1880.00"),
            grand_total=Decimal("1880.00"),
            notes="تم استلام البضاعة بالمخزن الرئيسي وجاهز للترحيل المالي",
            created_by=buyer_u
        )
        PurchaseOrderItem.objects.create(
            order=po_picked,
            product=p1,
            quantity=Decimal("100"),
            unit_price=Decimal("18.80"),
            total_price=Decimal("1880.00")
        )

    # 11. Live Sales Flow Data
    print("\n--- 9. Seeding Live Sales Flow Artifacts ---")
    so_pending = SalesOrder.objects.filter(order_number="SO-TEST-PENDING").first()
    if not so_pending:
        max_so = SalesOrder.objects.aggregate(django.db.models.Max('serial_num'))['serial_num__max'] or 600
        so_pending = SalesOrder.objects.create(
            serial_num=max_so + 1,
            order_number="SO-TEST-PENDING",
            customer=pharmacy_cairo,
            source_warehouse=main_wh,
            order_date=today,
            status="pending",
            grand_total=Decimal("7000.00"),
            notes="طلب بيع عاجل لصيدلية الأمل",
            created_by=rep_c
        )
        SalesOrderItem.objects.create(
            order=so_pending,
            product=p1,
            quantity=Decimal("50"),
            unit_price=Decimal("140.00"),
            subtotal=Decimal("7000.00")
        )

    so_approved = SalesOrder.objects.filter(order_number="SO-TEST-APPROVED").first()
    if not so_approved:
        max_so = SalesOrder.objects.aggregate(django.db.models.Max('serial_num'))['serial_num__max'] or 600
        so_approved = SalesOrder.objects.create(
            serial_num=max_so + 1,
            order_number="SO-TEST-APPROVED",
            customer=contact_cairo,
            source_warehouse=main_wh,
            order_date=today,
            status="manager_approval",
            approved_by=created_users["manager_cairo"],
            approved_at=timezone.now(),
            grand_total=Decimal("4750.00"),
            notes="طلب بيع معتمد لعيادة د. تامر فهمي جاهز للفوترة والصرف",
            created_by=rep_c
        )
        SalesOrderItem.objects.create(
            order=so_approved,
            product=p2,
            quantity=Decimal("50"),
            unit_price=Decimal("95.00"),
            subtotal=Decimal("4750.00")
        )

    print("\n" + "=" * 60)
    print("SUCCESS: ALL USER ROLES AND FLOW ARTIFACTS CREATED!")
    print(f"Universal Login Password for all test users: {DEFAULT_PASSWORD}")
    print("=" * 60)

if __name__ == "__main__":
    seed_users_and_flows()
