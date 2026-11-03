import os
import sys
import django
from decimal import Decimal
import datetime

if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.utils import timezone
from django.contrib.auth import get_user_model
from accounts.models import Role, Permission, UserSettings
from master_data.models import Area, CompanyProfile, SalesSettings, PurchaseSettings, LocationSettings
from contacts.models import Contact, ContactAddress
from catalog.models import Product, ProductCategory
from inventory.models import Warehouse, InventoryStock, InventoryMemo, InventoryMemoItem
from purchases.models import PurchaseOrder, PurchaseOrderItem, PurchaseReturnOrder, PurchaseReturnOrderItem
from purchases.services import PurchaseOrderService
from treasury.models import Vault, VendorAccount, VendorTransaction, VendorPayment, VendorInstallment, VaultTransaction
from sales.models import SalesOrder, SalesOrderItem, CustomerAccount, CustomerTransaction, Collection
from accounts.services import ensure_representative_resources

User = get_user_model()

def seed_data():
    print("=" * 60)
    print("SEEDING COMPREHENSIVE ERP DATA FOR ALL 9 WORKFLOW POINTS")
    print("=" * 60)

    # 1. Company Profile & Settings
    print("\n[1] Configuring Company Profile & Settings...")
    profile, _ = CompanyProfile.objects.get_or_create(id=1, defaults={'name': 'شركة وي فارما للأدوية والمستلزمات الطبية (WEA Pharma)'})
    sales_settings, _ = SalesSettings.objects.get_or_create(id=1, defaults={'require_manager_approval': True, 'allow_all_users_to_create': False})
    sales_settings.require_manager_approval = True
    sales_settings.save()

    purchase_settings, _ = PurchaseSettings.objects.get_or_create(id=1, defaults={'require_manager_approval': True, 'allow_all_users_to_create': False})
    purchase_settings.require_manager_approval = True
    purchase_settings.save()

    user_settings, _ = UserSettings.objects.get_or_create(id=1, defaults={'auto_create_rep_warehouse_vault': True})
    user_settings.auto_create_rep_warehouse_vault = True
    user_settings.save()

    # 2. Canonical Roles
    print("\n[2] Verifying Canonical Roles...")
    role_super, _ = Role.objects.get_or_create(name='superadmin', defaults={'is_super': True, 'description': 'مدير النظام العام'})
    role_accountant, _ = Role.objects.get_or_create(name='accountant', defaults={'description': 'المحاسب المالي'})
    role_manager, _ = Role.objects.get_or_create(name='manager', defaults={'is_area_manager': True, 'description': 'مدير المنطقة والمشرف'})
    role_rep, _ = Role.objects.get_or_create(name='rep', defaults={'is_rep': True, 'is_sales_team': True, 'description': 'مندوب المبيعات'})
    role_med_rep, _ = Role.objects.get_or_create(name='medical_rep', defaults={'is_rep': True, 'is_medical_rep': True, 'description': 'مندوب دعاية طبية'})

    # Configure warehouse operation roles in settings
    profile.roles_can_stock_in.add(role_manager)
    profile.roles_can_stock_out.add(role_manager)
    profile.roles_can_transfer.add(role_manager)
    profile.save()

    memo_perm = Permission.objects.filter(codename='inventory:memos/manage').first()
    if memo_perm:
        role_accountant.permissions.add(memo_perm)

    # 3. Areas Hierarchy
    print("\n[3] Setting up Geographic Areas...")
    cairo, _ = Area.objects.get_or_create(code='CAI', defaults={'name': 'محافظة القاهرة', 'area_type': 'governorate', 'parent': None})
    nasr_city, _ = Area.objects.get_or_create(code='CAI-NC', defaults={'name': 'مدينة نصر', 'area_type': 'subarea', 'parent': cairo})
    maadi, _ = Area.objects.get_or_create(code='CAI-MD', defaults={'name': 'المعادي', 'area_type': 'subarea', 'parent': cairo})

    giza, _ = Area.objects.get_or_create(code='GIZ', defaults={'name': 'محافظة الجيزة', 'area_type': 'governorate', 'parent': None})
    dokki, _ = Area.objects.get_or_create(code='GIZ-DK', defaults={'name': 'الدقي', 'area_type': 'subarea', 'parent': giza})
    mohandessin, _ = Area.objects.get_or_create(code='GIZ-MH', defaults={'name': 'المهندسين', 'area_type': 'subarea', 'parent': giza})

    alex, _ = Area.objects.get_or_create(code='ALX', defaults={'name': 'محافظة الإسكندرية', 'area_type': 'governorate', 'parent': None})
    smouha, _ = Area.objects.get_or_create(code='ALX-SM', defaults={'name': 'سموحة', 'area_type': 'subarea', 'parent': alex})

    # 4. Users
    print("\n[4] Creating Users for Different Roles...")
    # Superadmin
    superadmin, _ = User.objects.get_or_create(
        email='wea.pharm2020@gmail.com',
        defaults={'username': 'wea.pharm2020@gmail.com', 'name': 'المسؤول العام (SuperAdmin)', 'role': role_super, 'is_superuser': True, 'is_staff': True}
    )
    superadmin.set_password('Wea@4444')
    superadmin.role = role_super
    superadmin.is_superuser = True
    superadmin.is_staff = True
    superadmin.save()

    # Accountant
    accountant, _ = User.objects.get_or_create(
        username='accountant@wea.com',
        defaults={'email': 'accountant@wea.com', 'name': 'أحمد كمال (محاسب مالي)', 'role': role_accountant, 'is_staff': False}
    )
    accountant.set_password('Pass@1234')
    accountant.role = role_accountant
    accountant.name = 'أحمد كمال (محاسب مالي)'
    accountant.save()

    # Cairo Manager
    mgr_cairo, _ = User.objects.get_or_create(
        username='mgr_cairo@wea.com',
        defaults={'email': 'mgr_cairo@wea.com', 'name': 'سامح إبراهيم (مدير القاهرة)', 'role': role_manager}
    )
    mgr_cairo.set_password('Pass@1234')
    mgr_cairo.role = role_manager
    mgr_cairo.name = 'سامح إبراهيم (مدير القاهرة)'
    mgr_cairo.save()
    mgr_cairo.assigned_areas.clear()
    mgr_cairo.assigned_areas.add(cairo)

    # Giza Manager
    mgr_giza, _ = User.objects.get_or_create(
        username='mgr_giza@wea.com',
        defaults={'email': 'mgr_giza@wea.com', 'name': 'عمر خالد (مدير الجيزة)', 'role': role_manager}
    )
    mgr_giza.set_password('Pass@1234')
    mgr_giza.role = role_manager
    mgr_giza.name = 'عمر خالد (مدير الجيزة)'
    mgr_giza.save()
    mgr_giza.assigned_areas.clear()
    mgr_giza.assigned_areas.add(giza)

    # Cairo Rep
    rep_cairo, _ = User.objects.get_or_create(
        username='rep_cairo@wea.com',
        defaults={'email': 'rep_cairo@wea.com', 'name': 'محمود حسن (مندوب القاهرة)', 'role': role_rep}
    )
    rep_cairo.set_password('Pass@1234')
    rep_cairo.role = role_rep
    rep_cairo.name = 'محمود حسن (مندوب القاهرة)'
    rep_cairo.save()
    rep_cairo.assigned_areas.clear()
    rep_cairo.assigned_areas.add(nasr_city)

    # Giza Rep
    rep_giza, _ = User.objects.get_or_create(
        username='rep_giza@wea.com',
        defaults={'email': 'rep_giza@wea.com', 'name': 'ياسر مصطفى (مندوب الجيزة)', 'role': role_rep}
    )
    rep_giza.set_password('Pass@1234')
    rep_giza.role = role_rep
    rep_giza.name = 'ياسر مصطفى (مندوب الجيزة)'
    rep_giza.save()
    rep_giza.assigned_areas.clear()
    rep_giza.assigned_areas.add(dokki)

    # Auto-provision representative warehouses and vaults
    ensure_representative_resources(rep_cairo, create_warehouse=True, create_treasury=True)
    ensure_representative_resources(rep_giza, create_warehouse=True, create_treasury=True)

    rep_cairo_wh = rep_cairo.get_default_warehouse()
    rep_giza_wh = rep_giza.get_default_warehouse()
    rep_cairo_vault = rep_cairo.get_default_treasury()
    rep_giza_vault = rep_giza.get_default_treasury()

    # 5. Warehouses & Vaults
    print("\n[5] Setting up Main Warehouses & Main Vaults...")
    main_wh_cairo, _ = Warehouse.objects.get_or_create(
        code='WH-CAI-MAIN',
        defaults={'name': 'مخزن القاهرة الرئيسي المركزي', 'area': cairo, 'is_main': True, 'address': 'المنطقة الصناعية، مدينة نصر، القاهرة'}
    )
    main_wh_giza, _ = Warehouse.objects.get_or_create(
        code='WH-GIZ-MAIN',
        defaults={'name': 'مخزن الجيزة الرئيسي', 'area': giza, 'is_main': True, 'address': 'شارع السودان، المهندسين، الجيزة'}
    )

    main_vault, _ = Vault.objects.get_or_create(
        serial_num=1001,
        defaults={'name': 'الخزينة النقدية الرئيسية', 'current_balance': Decimal('750000.00'), 'vault_type': 'cash'}
    )
    if main_vault.current_balance < Decimal('100000.00'):
        main_vault.current_balance = Decimal('750000.00')
        main_vault.save()

    bank_cib, _ = Vault.objects.get_or_create(
        serial_num=1002,
        defaults={'name': 'حساب البنك التجاري الدولي (CIB)', 'current_balance': Decimal('1500000.00'), 'vault_type': 'bank'}
    )

    if rep_cairo_vault:
        rep_cairo_vault.current_balance = Decimal('15000.00')
        rep_cairo_vault.save()

    if rep_giza_vault:
        rep_giza_vault.current_balance = Decimal('10000.00')
        rep_giza_vault.save()

    # 6. Categories & Products
    print("\n[6] Setting up Products and Categories...")
    cat_anti, _ = ProductCategory.objects.get_or_create(code='CAT-ANTI', defaults={'name': 'أدوية ومضادات حيوية'})
    cat_pain, _ = ProductCategory.objects.get_or_create(code='CAT-PAIN', defaults={'name': 'مسكنات ومضادات التهاب'})
    cat_chron, _ = ProductCategory.objects.get_or_create(code='CAT-CHRON', defaults={'name': 'أدوية الأمراض المزمنة'})
    cat_vit, _ = ProductCategory.objects.get_or_create(code='CAT-VIT', defaults={'name': 'فيتامينات ومكملات غذائية'})

    p_aug, _ = Product.objects.get_or_create(
        sku_code='AUG-1G',
        defaults={'name': 'أوجمنتين 1 جم أقراص (Augmentin 1g)', 'category': cat_anti, 'retail_price': Decimal('120.00'), 'default_purchase_cost': Decimal('90.00')}
    )
    p_pan, _ = Product.objects.get_or_create(
        sku_code='PAN-EX',
        defaults={'name': 'بانادول إكسترا 500 ملجم (Panadol Extra)', 'category': cat_pain, 'retail_price': Decimal('60.00'), 'default_purchase_cost': Decimal('45.00')}
    )
    p_con, _ = Product.objects.get_or_create(
        sku_code='CON-5M',
        defaults={'name': 'كونكور 5 ملجم أقراص (Concor 5mg)', 'category': cat_chron, 'retail_price': Decimal('85.00'), 'default_purchase_cost': Decimal('65.00')}
    )
    p_cret, _ = Product.objects.get_or_create(
        sku_code='CRET-500',
        defaults={'name': 'سي-ريتارد 500 ملجم كبسول (C-Retard 500mg)', 'category': cat_vit, 'retail_price': Decimal('40.00'), 'default_purchase_cost': Decimal('28.00')}
    )

    # Stocks
    products = [p_aug, p_pan, p_con, p_cret]
    for p in products:
        # In main warehouse Cairo
        st, _ = InventoryStock.objects.get_or_create(
            warehouse=main_wh_cairo, product=p,
            defaults={'qty_on_hand': Decimal('1000.00'), 'qty_reserved': Decimal('0.00'), 'product_cost': p.default_purchase_cost}
        )
        if st.qty_on_hand < Decimal('500.00'):
            st.qty_on_hand = Decimal('1000.00')
            st.save()

        # In main warehouse Giza
        st_g, _ = InventoryStock.objects.get_or_create(
            warehouse=main_wh_giza, product=p,
            defaults={'qty_on_hand': Decimal('500.00'), 'qty_reserved': Decimal('0.00'), 'product_cost': p.default_purchase_cost}
        )
        if st_g.qty_on_hand < Decimal('200.00'):
            st_g.qty_on_hand = Decimal('500.00')
            st_g.save()

        # In rep cairo warehouse
        if rep_cairo_wh:
            st_rc, _ = InventoryStock.objects.get_or_create(
                warehouse=rep_cairo_wh, product=p,
                defaults={'qty_on_hand': Decimal('150.00'), 'qty_reserved': Decimal('0.00'), 'product_cost': p.default_purchase_cost}
            )
            if st_rc.qty_on_hand < Decimal('50.00'):
                st_rc.qty_on_hand = Decimal('150.00')
                st_rc.save()

        # In rep giza warehouse
        if rep_giza_wh:
            st_rg, _ = InventoryStock.objects.get_or_create(
                warehouse=rep_giza_wh, product=p,
                defaults={'qty_on_hand': Decimal('100.00'), 'qty_reserved': Decimal('0.00'), 'product_cost': p.default_purchase_cost}
            )
            if st_rg.qty_on_hand < Decimal('40.00'):
                st_rg.qty_on_hand = Decimal('100.00')
                st_rg.save()

    # 7. Suppliers & Customers
    print("\n[7] Setting up Suppliers and Customers...")
    supp_egy, _ = Contact.objects.get_or_create(
        code='SUPP-EG-01',
        defaults={'name': 'الشركة المصرية لتجارة الأدوية', 'is_supplier': True, 'area': cairo, 'status': 'supplier', 'created_by': superadmin}
    )
    VendorAccount.get_or_create_for_supplier(supp_egy)

    supp_pharma, _ = Contact.objects.get_or_create(
        code='SUPP-PH-02',
        defaults={'name': 'شركة فارما أوفرسيز لتوزيع الدواء', 'is_supplier': True, 'area': cairo, 'status': 'supplier', 'created_by': superadmin}
    )
    VendorAccount.get_or_create_for_supplier(supp_pharma)

    supp_ibn, _ = Contact.objects.get_or_create(
        code='SUPP-IBN-03',
        defaults={'name': 'شركة ابن سينا فارما', 'is_supplier': True, 'area': giza, 'status': 'supplier', 'created_by': superadmin}
    )
    VendorAccount.get_or_create_for_supplier(supp_ibn)

    # Customers
    cust_ezaby, _ = Contact.objects.get_or_create(
        code='CUST-EZ-01',
        defaults={'name': 'صيدلية العزبي - فرع مكرم عبيد', 'is_customer': True, 'area': nasr_city, 'status': 'customer', 'credit_limit': Decimal('100000.00'), 'created_by': rep_cairo}
    )
    CustomerAccount.get_or_create_for_customer(cust_ezaby)

    cust_seif, _ = Contact.objects.get_or_create(
        code='CUST-SF-02',
        defaults={'name': 'صيدليات سيف - فرع المعادي', 'is_customer': True, 'area': maadi, 'status': 'customer', 'credit_limit': Decimal('80000.00'), 'created_by': rep_cairo}
    )
    CustomerAccount.get_or_create_for_customer(cust_seif)

    cust_19011, _ = Contact.objects.get_or_create(
        code='CUST-19-03',
        defaults={'name': 'صيدلية 19011 - فرع مصدق الدقي', 'is_customer': True, 'area': dokki, 'status': 'customer', 'credit_limit': Decimal('50000.00'), 'created_by': rep_giza}
    )
    CustomerAccount.get_or_create_for_customer(cust_19011)

    # 8. Point 1: Purchase Orders & Purchase Return Orders
    print("\n[8] Creating Purchase Orders and Returns (Point 1)...")
    po_settled, _ = PurchaseOrder.objects.get_or_create(
        serial_num=61001,
        defaults={
            'order_number': 'PO-2026-0001',
            'supplier': supp_egy,
            'target_warehouse': main_wh_cairo,
            'order_date': timezone.now().date() - datetime.timedelta(days=10),
            'status': 'settled',
            'created_by': accountant,
            'approved_by': superadmin,
            'approved_at': timezone.now() - datetime.timedelta(days=9),
            'grand_total': Decimal('13500.00'),
            'subtotal': Decimal('13500.00')
        }
    )
    if not po_settled.items.exists():
        PurchaseOrderItem.objects.create(order=po_settled, product=p_aug, quantity=Decimal('100.00'), unit_price=Decimal('90.00'), subtotal=Decimal('9000.00'), item_order=1)
        PurchaseOrderItem.objects.create(order=po_settled, product=p_pan, quantity=Decimal('100.00'), unit_price=Decimal('45.00'), subtotal=Decimal('4500.00'), item_order=2)

    po_approved, _ = PurchaseOrder.objects.get_or_create(
        serial_num=61002,
        defaults={
            'order_number': 'PO-2026-0002',
            'supplier': supp_pharma,
            'target_warehouse': main_wh_cairo,
            'order_date': timezone.now().date() - datetime.timedelta(days=3),
            'status': 'approved',
            'created_by': accountant,
            'approved_by': superadmin,
            'approved_at': timezone.now() - datetime.timedelta(days=2),
            'grand_total': Decimal('6500.00'),
            'subtotal': Decimal('6500.00')
        }
    )
    if not po_approved.items.exists():
        PurchaseOrderItem.objects.create(order=po_approved, product=p_con, quantity=Decimal('100.00'), unit_price=Decimal('65.00'), subtotal=Decimal('6500.00'), item_order=1)

    # Purchase Return Order (PR-001)
    ret_order_delivered, _ = PurchaseReturnOrder.objects.get_or_create(
        serial_num=62001,
        defaults={
            'order_number': 'PR-2026-0001',
            'purchase_order': po_settled,
            'supplier': supp_egy,
            'warehouse': main_wh_cairo,
            'order_date': timezone.now().date() - datetime.timedelta(days=5),
            'status': 'delivered',
            'created_by': accountant,
            'notes': 'عبوات تالفة أثناء النقل والشحن',
            'grand_total': Decimal('900.00'),
            'subtotal': Decimal('900.00'),
            'items_quantity': Decimal('10.00'),
            'items_count': 1
        }
    )
    if not ret_order_delivered.items.exists():
        PurchaseReturnOrderItem.objects.create(return_order=ret_order_delivered, product=p_aug, quantity=Decimal('10.00'), unit_price=Decimal('90.00'), item_order=1)

    ret_order_pending, _ = PurchaseReturnOrder.objects.get_or_create(
        serial_num=62002,
        defaults={
            'order_number': 'PR-2026-0002',
            'purchase_order': po_settled,
            'supplier': supp_egy,
            'warehouse': main_wh_cairo,
            'order_date': timezone.now().date() - datetime.timedelta(days=1),
            'status': 'pending',
            'created_by': accountant,
            'notes': 'فائض في المخزون مطلوب رده للمورد',
            'grand_total': Decimal('450.00'),
            'subtotal': Decimal('450.00'),
            'items_quantity': Decimal('10.00'),
            'items_count': 1
        }
    )
    if not ret_order_pending.items.exists():
        PurchaseReturnOrderItem.objects.create(return_order=ret_order_pending, product=p_pan, quantity=Decimal('10.00'), unit_price=Decimal('45.00'), item_order=1)

    # 9. Point 2 & 3: Treasury Payments & Payment Requests
    print("\n[9] Creating Vendor Payments & Payment Requests (Point 2 & 3)...")
    pay_1, _ = VendorPayment.objects.get_or_create(
        serial_num=91001,
        defaults={
            'supplier': supp_egy,
            'vault': main_vault,
            'purchase_order': po_settled,
            'amount': Decimal('25000.00'),
            'payment_date': timezone.now().date() - datetime.timedelta(days=3),
            'payment_method': 'cash',
            'reference_number': 'REC-VEND-101',
            'created_by': accountant,
            'status': 'cleared',
            'notes': 'سداد دفعة نقدية بموجب أمر الشراء والتسوية'
        }
    )

    pay_2, _ = VendorPayment.objects.get_or_create(
        serial_num=91002,
        defaults={
            'supplier': supp_pharma,
            'vault': main_vault,
            'purchase_order': po_approved,
            'amount': Decimal('6500.00'),
            'payment_date': timezone.now().date() - datetime.timedelta(days=1),
            'payment_method': 'bank_transfer',
            'reference_number': 'TRF-BNK-9902',
            'created_by': accountant,
            'status': 'pending',
            'notes': 'طلب دفعة مقدمة قيد التنفيذ البنكي'
        }
    )

    # 10. Point 4: Inventory Memos (Stock In & Stock Out)
    print("\n[10] Creating Inventory Memos (Point 4)...")
    memo_in, _ = InventoryMemo.objects.get_or_create(
        memo_number='MEM-IN-2026-0001',
        defaults={
            'warehouse': main_wh_cairo,
            'memo_type': 'inward',
            'statement': 'إذن إضافة بضاعة واردة من التشغيلة الإنتاجية الجديدة',
            'notes': 'إذن إضافة بضاعة واردة DOC-IN-5501',
            'status': 'applied',
            'created_by': accountant
        }
    )
    if not memo_in.items.exists():
        InventoryMemoItem.objects.create(
            memo=memo_in,
            product=p_cret,
            quantity=Decimal('50.00'),
            unit_cost=Decimal('28.00'),
            batch_number='LOT-CR-2026A',
            expiry_date=datetime.date(2028, 12, 31)
        )

    memo_out, _ = InventoryMemo.objects.get_or_create(
        memo_number='MEM-OUT-2026-0001',
        defaults={
            'warehouse': main_wh_cairo,
            'memo_type': 'outward',
            'statement': 'صرف عينات ترويجية للمؤتمر العلمي للأطباء',
            'notes': 'صرف ترويجي DOC-OUT-7702',
            'status': 'applied',
            'created_by': accountant
        }
    )
    if not memo_out.items.exists():
        InventoryMemoItem.objects.create(
            memo=memo_out,
            product=p_pan,
            quantity=Decimal('10.00'),
            unit_cost=Decimal('45.00'),
            batch_number='LOT-PAN-2026',
            expiry_date=datetime.date(2027, 6, 30)
        )

    # 11. Point 5 & 6: Vaults & Vault Transactions
    print("\n[11] Creating Vault Transactions (Point 5 & 6)...")
    tx_dep, _ = VaultTransaction.objects.get_or_create(
        vault=main_vault,
        transaction_type='inflow',
        amount=Decimal('50000.00'),
        reference_type='deposit',
        defaults={
            'running_balance': main_vault.current_balance,
            'description': 'إيداع متحصلات نقدية من المركز المالي',
            'created_by': accountant
        }
    )

    tx_with, _ = VaultTransaction.objects.get_or_create(
        vault=main_vault,
        transaction_type='outflow',
        amount=Decimal('5000.00'),
        reference_type='withdrawal',
        defaults={
            'running_balance': main_vault.current_balance - Decimal('5000.00'),
            'description': 'صرف مصروفات صيانة وتوزيع',
            'created_by': accountant
        }
    )

    if rep_cairo_vault:
        tx_rep, _ = VaultTransaction.objects.get_or_create(
            vault=rep_cairo_vault,
            transaction_type='inflow',
            amount=Decimal('10000.00'),
            reference_type='transfer',
            defaults={
                'running_balance': rep_cairo_vault.current_balance,
                'description': 'تغذية عهدة نقدية للمندوب محمود حسن',
                'created_by': accountant
            }
        )

    # 12. Point 7: Sales Orders
    print("\n[12] Creating Sales Orders (Point 7)...")
    # SO 1: Pending order created by rep_cairo
    so_pending, _ = SalesOrder.objects.get_or_create(
        serial_num=501,
        defaults={
            'order_number': 'SO-2026-0001',
            'customer': cust_ezaby,
            'source_warehouse': rep_cairo_wh or main_wh_cairo,
            'order_date': timezone.now().date() - datetime.timedelta(days=1),
            'status': 'pending',
            'created_by': rep_cairo,
            'subtotal': Decimal('1200.00'),
            'items_discount_total': Decimal('60.00'),
            'custom_discount_percentage': Decimal('5.00'),
            'custom_discount_amount': Decimal('57.00'),
            'shipping_fees': Decimal('30.00'),
            'grand_total': Decimal('1113.00'),
            'notes': 'طلب توريد دوري لصيدلية العزبي'
        }
    )
    if not so_pending.items.exists():
        SalesOrderItem.objects.create(order=so_pending, product=p_pan, quantity=Decimal('10.00'), unit_price=Decimal('60.00'), discount_percentage=Decimal('10.00'), discount_amount=Decimal('60.00'), subtotal=Decimal('540.00'))
        SalesOrderItem.objects.create(order=so_pending, product=p_aug, quantity=Decimal('5.00'), unit_price=Decimal('120.00'), discount_percentage=Decimal('0.00'), discount_amount=Decimal('0.00'), subtotal=Decimal('600.00'))

    # SO 2: Manager-approved order for Cairo
    so_approved, _ = SalesOrder.objects.get_or_create(
        serial_num=502,
        defaults={
            'order_number': 'SO-2026-0002',
            'customer': cust_seif,
            'source_warehouse': rep_cairo_wh or main_wh_cairo,
            'order_date': timezone.now().date() - datetime.timedelta(days=2),
            'status': 'manager_approval',
            'created_by': rep_cairo,
            'approved_by': mgr_cairo,
            'approved_at': timezone.now() - datetime.timedelta(days=1),
            'subtotal': Decimal('1700.00'),
            'items_discount_total': Decimal('0.00'),
            'custom_discount_percentage': Decimal('0.00'),
            'shipping_fees': Decimal('50.00'),
            'grand_total': Decimal('1750.00'),
            'notes': 'معتمد من مدير القاهرة'
        }
    )
    if not so_approved.items.exists():
        SalesOrderItem.objects.create(order=so_approved, product=p_con, quantity=Decimal('20.00'), unit_price=Decimal('85.00'), subtotal=Decimal('1700.00'))

    # SO 3: Delivered and Invoiced order
    so_invoiced, _ = SalesOrder.objects.get_or_create(
        serial_num=503,
        defaults={
            'order_number': 'SO-2026-0003',
            'customer': cust_ezaby,
            'source_warehouse': rep_cairo_wh or main_wh_cairo,
            'order_date': timezone.now().date() - datetime.timedelta(days=4),
            'status': 'invoiced',
            'created_by': rep_cairo,
            'approved_by': mgr_cairo,
            'approved_at': timezone.now() - datetime.timedelta(days=3),
            'subtotal': Decimal('2500.00'),
            'grand_total': Decimal('2500.00'),
            'due_date': timezone.now().date() + datetime.timedelta(days=15),
            'notes': 'فاتورة مبيعات مسلمة ومرحلة للحسابات'
        }
    )
    if not so_invoiced.items.exists():
        SalesOrderItem.objects.create(order=so_invoiced, product=p_pan, quantity=Decimal('25.00'), unit_price=Decimal('60.00'), subtotal=Decimal('1500.00'))
        SalesOrderItem.objects.create(order=so_invoiced, product=p_con, quantity=Decimal('10.00'), unit_price=Decimal('85.00'), subtotal=Decimal('850.00'))
        SalesOrderItem.objects.create(order=so_invoiced, product=p_cret, quantity=Decimal('5.00'), unit_price=Decimal('30.00'), subtotal=Decimal('150.00'))

    # SO 4: Giza Order created by rep_giza (for ABAC data isolation testing)
    so_giza, _ = SalesOrder.objects.get_or_create(
        serial_num=504,
        defaults={
            'order_number': 'SO-GIZ-0001',
            'customer': cust_19011,
            'source_warehouse': rep_giza_wh or main_wh_giza,
            'order_date': timezone.now().date() - datetime.timedelta(days=1),
            'status': 'pending',
            'created_by': rep_giza,
            'subtotal': Decimal('1200.00'),
            'grand_total': Decimal('1200.00'),
            'notes': 'أمر بيع لمنطقة الجيزة - الدقي'
        }
    )
    if not so_giza.items.exists():
        SalesOrderItem.objects.create(order=so_giza, product=p_pan, quantity=Decimal('20.00'), unit_price=Decimal('60.00'), subtotal=Decimal('1200.00'))
    if not so_giza.items.exists():
        SalesOrderItem.objects.create(order=so_giza, product=p_pan, quantity=Decimal('20.00'), unit_price=Decimal('60.00'), subtotal=Decimal('1200.00'))

    # 13. Point 8: Collections
    print("\n[13] Creating Collections (Point 8)...")
    col_1, _ = Collection.objects.get_or_create(
        serial_num=71001,
        defaults={
            'customer': cust_ezaby,
            'sales_order': so_invoiced,
            'vault': rep_cairo_vault or main_vault,
            'amount': Decimal('1500.00'),
            'collection_date': timezone.now().date() - datetime.timedelta(days=2),
            'payment_method': 'cash',
            'created_by': rep_cairo,
            'notes': 'تحصيل دفعة نقدية من صيدلية العزبي'
        }
    )

    col_2, _ = Collection.objects.get_or_create(
        serial_num=71002,
        defaults={
            'customer': cust_seif,
            'sales_order': so_approved,
            'vault': rep_cairo_vault or main_vault,
            'amount': Decimal('1000.00'),
            'collection_date': timezone.now().date() - datetime.timedelta(days=1),
            'payment_method': 'cash',
            'created_by': rep_cairo,
            'notes': 'دفعة مقدمة تحت الحساب'
        }
    )

    print("\n" + "=" * 60)
    print("SUCCESS: ALL TEST DATA SEEDED CLEANLY!")
    print("=" * 60)

if __name__ == '__main__':
    seed_data()
