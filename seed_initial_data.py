import os
import django
from decimal import Decimal

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.core.management import call_command
from accounts.models import Role, User
from master_data.models import CompanyProfile


def seed():
    print("=" * 70)
    print("WEA PHARMA ERP - SEEDING INITIAL MASTER & BUSINESS DATA")
    print("=" * 70)

    # 1. Company Profile
    print("\n[1/4] Configuring Company Profile...")
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
    print("  [OK] Company Profile configured: WEA Pharma")

    # 2. Roles
    print("\n[2/4] Ensuring System Roles...")
    super_role, _ = Role.objects.get_or_create(
        name="SuperAdmin",
        defaults={
            "display_name": "مدير النظام (SuperAdmin)",
            "description": "صلاحيات كاملة غير مقيدة على كافة أقسام النظام",
            "is_system": True,
            "is_super": True,
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
    print("  [OK] System roles verified.")

    # 3. SuperAdmin User
    print("\n[3/4] Ensuring SuperAdmin Account...")
    admin_user = User.objects.filter(email="wea.pharm2020@gmail.com").first()
    if not admin_user:
        admin_user = User.objects.create_superuser(
            username="wea.pharm2020@gmail.com",
            email="wea.pharm2020@gmail.com",
            password="Wea@4444",
            name="Dr. Wael Atta (CEO)",
            mobile="+201111787179",
            role=super_role
        )
        print("  [OK] Created SuperAdmin user (wea.pharm2020@gmail.com / Wea@4444).")
    else:
        admin_user.role = super_role
        admin_user.name = "Dr. Wael Atta (CEO)"
        admin_user.set_password("Wea@4444")
        admin_user.save()
        print("  [OK] Updated SuperAdmin user (wea.pharm2020@gmail.com / Wea@4444).")

    # 4. Import Full Business Data from data_folder
    print("\n[4/4] Importing business data from data_folder/...")
    call_command('import_excel_data', confirm=True, source='data_folder')

    print("\n" + "=" * 70)
    print("=== Initial Seeding Finished Successfully! ===")
    print("=" * 70)


if __name__ == "__main__":
    seed()
