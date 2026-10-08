import os
import django
from decimal import Decimal

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from accounts.models import Role, User
from master_data.models import Area, CompanyProfile
from contacts.models import Contact, ContactAddress
from catalog.models import ProductCategory, Product
from inventory.models import Warehouse, InventoryStock
from treasury.models import Vault, VendorAccount
from purchases.models import PurchaseOrder, PurchaseOrderItem

def seed():
    print("--- Seeding Initial Master Data ---")

    # 1. Company Profile
    profile = CompanyProfile.get_settings()
    profile.company_name = "WEA Pharma"
    profile.commercial_registry = "سجل تجاري 184791"
    profile.tax_id = "بطاقة ضريبية 978 - 339 - 684"
    profile.phone = "01111787179 - 01024070412"
    profile.address = "173 ز - البوابة الأولى- حدائق الأهرام"
    profile.email = "wea.pharm2020@gmail.com"
    profile.currency = "EGP"
    profile.use_batch_number = True
    profile.use_expiry_date = True
    profile.save()
    print("Company Profile configured.")

    # 2. Roles
    super_role, _ = Role.objects.get_or_create(
        name="SuperAdmin",
        defaults={
            "display_name": "مدير النظام (SuperAdmin)",
            "description": "صلاحيات كاملة غير مقيدة على كافة أقسام النظام",
            "is_system": True,
            "can_hold_vault": True
        }
    )

    accountant_role, _ = Role.objects.get_or_create(
        name="Accountant",
        defaults={
            "display_name": "محاسب مالي",
            "description": "إدارة المشتريات والحسابات والمدفوعات والخزن",
            "is_system": False,
            "can_hold_vault": True
        }
    )

    rep_role, _ = Role.objects.get_or_create(
        name="MedicalRep",
        defaults={
            "display_name": "مندوب مبيعات / دعاية",
            "description": "إدارة أوامر البيع والتحصيلات الميدانية",
            "is_sales_team": True,
            "is_rep": True,
            "can_hold_vault": True
        }
    )
    print("Roles created.")

    # 3. SuperAdmin User
    admin_user = User.objects.filter(email="wea.pharm2020@gmail.com").first()
    if not admin_user:
        admin_user = User.objects.create_superuser(
            username="wea.pharm2020@gmail.com",
            email="wea.pharm2020@gmail.com",
            password="Wea@0000",
            name="Dr. Wael Atta (CEO)",
            mobile="+201111787179",
            role=super_role
        )
        print("Created SuperAdmin user (wea.pharm2020@gmail.com / Wea@0000).")
    else:
        admin_user.role = super_role
        admin_user.name = "Dr. Wael Atta (CEO)"
        admin_user.set_password("Wea@0000")
        admin_user.save()
        print("Updated SuperAdmin user.")

    # 4. Areas
    giza, _ = Area.objects.get_or_create(code="03", defaults={"name": "محافظة الجيزة", "area_type": "governorate"})
    cairo, _ = Area.objects.get_or_create(code="01", defaults={"name": "محافظة القاهرة", "area_type": "governorate"})
    manashy, _ = Area.objects.get_or_create(code="0354", defaults={"name": "المناشى", "area_type": "subarea", "parent": giza})
    ahram, _ = Area.objects.get_or_create(code="0312", defaults={"name": "حدائق الأهرام", "area_type": "subarea", "parent": giza})
    print("Areas created.")

    # 5. Warehouses
    main_wh, _ = Warehouse.objects.get_or_create(
        code="WH-MAIN",
        defaults={
            "name": "المخزن الرئيسي بضاعه",
            "is_main": True,
            "address": "حدائق الأهرام - الجيزة",
            "manager": admin_user
        }
    )
    extra_wh, _ = Warehouse.objects.get_or_create(
        code="WH-EXTRA",
        defaults={
            "name": "مخزن إضافي 2",
            "is_main": False,
            "address": "بني سويف"
        }
    )
    print("Warehouses created.")

    # 6. Vaults
    main_vault, _ = Vault.objects.get_or_create(
        name="الخزنة الرئيسية",
        defaults={
            "serial_num": 1001,
            "vault_type": "cash",
            "assigned_user": admin_user,
            "current_balance": Decimal("150000.00")
        }
    )
    rep_vault, _ = Vault.objects.get_or_create(
        name="خزنة مندوب بني سويف",
        defaults={
            "serial_num": 1032,
            "vault_type": "cash",
            "assigned_user": admin_user,
            "current_balance": Decimal("3637.60")
        }
    )
    print("Vaults created.")

    # 7. Product Category & Products
    cat_wea, _ = ProductCategory.objects.get_or_create(code="WEA", defaults={"name": "منتجات WEA Pharma"})
    cat_cosmetics, _ = ProductCategory.objects.get_or_create(code="COSM", defaults={"name": "مستحضرات تجميل ومكملات"})
    
    p1, _ = Product.objects.get_or_create(
        sku_code="GE1",
        defaults={
            "category": cat_wea,
            "name": "Geron",
            "retail_price": Decimal("140.00"),
            "default_purchase_cost": Decimal("18.80"),
            "tax_percentage": Decimal("0.00"),
            "unit": "عبوة",
            "created_by": admin_user
        }
    )
    p2, _ = Product.objects.get_or_create(
        sku_code="WEA-C1000",
        defaults={
            "category": cat_wea,
            "name": "WEA Vitamin C 1000mg",
            "retail_price": Decimal("95.00"),
            "default_purchase_cost": Decimal("24.50"),
            "tax_percentage": Decimal("0.00"),
            "unit": "عبوة",
            "created_by": admin_user
        }
    )
    p3, _ = Product.objects.get_or_create(
        sku_code="WEA-ZINC",
        defaults={
            "category": cat_wea,
            "name": "WEA Zinc Plus",
            "retail_price": Decimal("65.00"),
            "default_purchase_cost": Decimal("12.00"),
            "tax_percentage": Decimal("0.00"),
            "unit": "شريط",
            "created_by": admin_user
        }
    )
    print("Products created.")

    # 8. Contacts (Supplier & Customer)
    supplier, _ = Contact.objects.get_or_create(
        name="مصنع اورجانيك للمكملات الغذائية بنها",
        defaults={
            "serial_num": 10027,
            "contact_type": "company",
            "is_supplier": True,
            "is_customer": False,
            "mobile": "01009876543",
            "phone": "0133221100",
            "area": giza,
            "commercial_registry": "194820",
            "tax_card": "654-123-889",
            "credit_limit": Decimal("200000.00"),
            "credit_period_days": 45,
            "created_by": admin_user
        }
    )
    ContactAddress.objects.get_or_create(
        contact=supplier,
        is_main=True,
        defaults={"title": "المصنع الرئيسي", "street_address": "المنطقة الصناعية - بنها", "area": giza}
    )
    VendorAccount.get_or_create_for_supplier(supplier)

    customer, _ = Contact.objects.get_or_create(
        name="صيدلية سامي هلال",
        defaults={
            "serial_num": 16456,
            "contact_type": "company",
            "is_supplier": False,
            "is_customer": True,
            "mobile": "01223344556",
            "area": manashy,
            "credit_limit": Decimal("50000.00"),
            "credit_period_days": 30,
            "created_by": admin_user
        }
    )
    ContactAddress.objects.get_or_create(
        contact=customer,
        is_main=True,
        defaults={"title": "فرع المناشي", "street_address": "شارع الجمهورية - المناشي", "area": manashy}
    )
    print("Contacts created.")

    print("\n=== Initial Seeding Finished Successfully! ===")

if __name__ == "__main__":
    seed()
