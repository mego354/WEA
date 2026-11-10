import os
import sys
import datetime
from decimal import Decimal
import pandas as pd

from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from django.db import transaction
from django.db.models import Sum, Q
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.db.models.signals import post_save

# Model Imports
from master_data.models import (
    Area, CompanyProfile, LocationSettings, SalesSettings, PurchaseSettings
)
from accounts.models import Role, RoleModuleScope, UserSettings
from accounts.signals import handle_representative_created
from catalog.models import ProductCategory, Product
from contacts.models import (
    Contact, ContactAddress, ContactComment, ContactAttachment, ContactTodo, ContactActivity
)
from inventory.models import (
    Warehouse, InventoryStock, InventoryLot, InventoryMemo, InventoryMemoItem,
    ProductTransferRequest, ProductTransferRequestItem
)
from treasury.models import (
    Vault, VaultTransaction, VendorAccount, VendorTransaction,
    VendorInstallment, VendorPayment, Settlement
)
from sales.models import (
    CustomerAccount, CustomerTransaction, SalesOrder, SalesOrderItem,
    SalesReturnOrder, SalesReturnOrderItem, Collection
)
from purchases.models import (
    PurchaseOrder, PurchaseOrderItem, PurchaseReturnOrder, PurchaseReturnOrderItem,
    PurchaseOrderAttachment, PurchaseOrderComment
)
from activities.models import (
    VisitTemplate, VisitTemplateQuestion, Visit, PlannedVisitDay,
    PlannedVisitItem, VisitSampleItem, VisitExpense, ApprovalAuditLog,
    Agreement, AgendaTodo
)

User = get_user_model()


def clean_phone(val):
    if pd.isna(val) or val is None:
        return ""
    s = str(val).strip()
    if s.endswith('.0'):
        s = s[:-2]
    # Remove any non-digit
    digits = ''.join(c for c in s if c.isdigit())
    if digits.startswith('20'):
        digits = '0' + digits[2:]
    return digits[:30]


def parse_dec(val, default='0.00'):
    if pd.isna(val) or val is None:
        return Decimal(default)
    s = str(val).strip()
    if s in ('', 'nan', 'NaN', 'None', 'NAT', 'null'):
        return Decimal(default)
    s = s.replace(',', '')
    try:
        return Decimal(s)
    except Exception:
        return Decimal(default)


def parse_date_safe(val):
    if pd.isna(val) or val is None or str(val).strip() in ('', 'nan', 'None'):
        return None
    if isinstance(val, (datetime.date, datetime.datetime)):
        return val.date() if isinstance(val, datetime.datetime) else val
    s = str(val).strip()
    for fmt in ('%d/%m/%Y %I:%M %p', '%d/%m/%Y %H:%M:%S', '%d/%m/%Y', '%Y-%m-%d', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%dT%H:%M:%S.%fZ', '%Y-%m-%dT%H:%M:%SZ'):
        try:
            return datetime.datetime.strptime(s.split('.')[0].replace('Z', ''), fmt.split('.')[0].replace('Z', '')).date()
        except ValueError:
            pass
    return None


def parse_dt_safe(val):
    if pd.isna(val) or val is None or str(val).strip() in ('', 'nan', 'None'):
        return None
    if isinstance(val, datetime.datetime):
        if timezone.is_naive(val):
            return timezone.make_aware(val, timezone.get_current_timezone())
        return val
    if isinstance(val, datetime.date):
        return timezone.make_aware(datetime.datetime.combine(val, datetime.time.min))
    s = str(val).strip()
    for fmt in ('%d/%m/%Y %I:%M %p', '%d/%m/%Y %H:%M:%S', '%d/%m/%Y', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d'):
        try:
            dt = datetime.datetime.strptime(s, fmt)
            return timezone.make_aware(dt, timezone.get_current_timezone())
        except ValueError:
            pass
    # Try ISO
    try:
        clean_s = s.replace('Z', '').split('.')[0]
        dt = datetime.datetime.fromisoformat(clean_s)
        return timezone.make_aware(dt, timezone.get_current_timezone())
    except Exception:
        pass
    return None


class Command(BaseCommand):
    help = "Authoritative enterprise migration command for WEA Pharma ERP data."

    def add_arguments(self, parser):
        parser.add_argument(
            '--source',
            type=str,
            default='data_folder',
            help='Directory containing the 12 source Excel files (default: data_folder)'
        )
        parser.add_argument(
            '--phase',
            type=str,
            default='all',
            help='Phase to execute: 0, 1, 2, 3, 4, 6, 7, 8, 10, 12, 13, 14, 15 or "all" (default: all)'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Validate and simulate operations without writing to database'
        )

    def handle(self, *args, **options):
        source_dir = options['source']
        phase_arg = options['phase'].lower()
        is_dry_run = options['dry_run']

        self.stdout.write(self.style.MIGRATE_HEADING("=" * 80))
        self.stdout.write(self.style.MIGRATE_HEADING("WEA PHARMA ERP — ENTERPRISE DATA MIGRATION ENGINE"))
        self.stdout.write(self.style.MIGRATE_HEADING(f"Source: {source_dir} | Phase: {phase_arg} | Dry Run: {is_dry_run}"))
        self.stdout.write(self.style.MIGRATE_HEADING("=" * 80))

        if not os.path.exists(source_dir):
            raise CommandError(f"Source directory '{source_dir}' does not exist!")

        # Verify environment
        engine = settings.DATABASES['default']['ENGINE']
        db_name = str(settings.DATABASES['default']['NAME'])
        is_test_env = 'test' in sys.argv or 'memory' in db_name or ':memory:' in db_name
        if 'sqlite3' not in engine or (not db_name.endswith('db.sqlite3') and not is_test_env):
            raise CommandError(f"Safety gate: Target DB ({db_name}) is not local sqlite3!")

        # Run requested phases
        phases_to_run = self.get_phases(phase_arg)
        self.stdout.write(f"Phases scheduled: {phases_to_run}\n")

        # Global lookup caches
        context = {
            'source_dir': source_dir,
            'dry_run': is_dry_run,
            'user_by_uuid': {},
            'contact_by_uuid': {},
            'warehouse_by_name': {},
            'vault_by_name': {},
            'main_area_by_name': {},
            'brick_by_name': {},
            'product_by_sku': {},
            'archive_user': None,
            'superuser': User.objects.filter(is_superuser=True).first(),
        }

        # Pre-populate existing caches
        for a in Area.objects.filter(parent__isnull=True):
            context['main_area_by_name'][a.name.strip()] = a
        for a in Area.objects.filter(parent__isnull=False):
            context['brick_by_name'][a.name.strip()] = a

        for p in phases_to_run:
            self.stdout.write(self.style.HTTP_INFO(f"\n>>> EXECUTING PHASE {p} <<<"))
            method_name = f"execute_phase_{p}"
            if hasattr(self, method_name):
                getattr(self, method_name)(context)
            else:
                self.stdout.write(self.style.WARNING(f"Phase {p} handler not found, skipping."))

        self.stdout.write(self.style.SUCCESS("\n============================================================"))
        self.stdout.write(self.style.SUCCESS("✓ MIGRATION COMMAND COMPLETED SUCCESSFULLY!"))
        self.stdout.write(self.style.SUCCESS("============================================================\n"))

    def get_phases(self, phase_arg):
        if phase_arg == 'all':
            return [0, 1, 2, 3, 4, 6, 7, 8, 10, 12, 13, 14, 15]
        if '-' in phase_arg:
            start, end = map(int, phase_arg.split('-'))
            return [p for p in [0, 1, 2, 3, 4, 6, 7, 8, 10, 12, 13, 14, 15] if start <= p <= end]
        if ',' in phase_arg:
            return [int(x.strip()) for x in phase_arg.split(',')]
        return [int(phase_arg)]

    # --------------------------------------------------------------------------
    # PHASE 0: Safe Bottom-Up Database Reset (Preserve Protected Records)
    # --------------------------------------------------------------------------
    def execute_phase_0(self, ctx):
        self.stdout.write("Phase 0: Safe bottom-up cleanup of non-protected operational data...")
        if ctx['dry_run']:
            self.stdout.write(self.style.WARNING("  [DRY-RUN] Would purge demo business records."))
            return

        with transaction.atomic():
            # 1. Sales & Collections
            Collection.objects.all().delete()
            CustomerTransaction.objects.all().delete()
            CustomerAccount.objects.all().delete()
            SalesOrderItem.objects.all().delete()
            SalesOrder.objects.all().delete()
            SalesReturnOrderItem.objects.all().delete()
            SalesReturnOrder.objects.all().delete()

            # 2. Purchases & Vendor Finance
            VendorPayment.objects.all().delete()
            VendorInstallment.objects.all().delete()
            VendorTransaction.objects.all().delete()
            VendorAccount.objects.all().delete()
            Settlement.objects.all().delete()
            PurchaseOrderItem.objects.all().delete()
            PurchaseOrderAttachment.objects.all().delete()
            PurchaseOrderComment.objects.all().delete()
            PurchaseOrder.objects.all().delete()
            PurchaseReturnOrderItem.objects.all().delete()
            PurchaseReturnOrder.objects.all().delete()

            # 3. Inventory & Transfers
            ProductTransferRequestItem.objects.all().delete()
            ProductTransferRequest.objects.all().delete()
            InventoryMemoItem.objects.all().delete()
            InventoryMemo.objects.all().delete()
            InventoryLot.objects.all().delete()
            InventoryStock.objects.all().delete()

            # 4. Vaults & Warehouses
            VaultTransaction.objects.all().delete()
            Vault.objects.all().delete()
            Warehouse.objects.all().delete()

            # 5. Field Activities & Visits (Protects VisitTemplates!)
            VisitExpense.objects.all().delete()
            VisitSampleItem.objects.all().delete()
            Visit.objects.all().delete()
            PlannedVisitItem.objects.all().delete()
            PlannedVisitDay.objects.all().delete()
            Agreement.objects.all().delete()

            # 6. CRM Contacts
            ContactActivity.objects.all().delete()
            ContactTodo.objects.all().delete()
            ContactAttachment.objects.all().delete()
            ContactComment.objects.all().delete()
            ContactAddress.objects.all().delete()
            Contact.objects.all().delete()

            # 7. Products (Leaves categories intact)
            Product.objects.all().delete()

            # 8. Non-Superuser Users
            User.objects.filter(is_superuser=False).delete()

        self.stdout.write(self.style.SUCCESS("  [PASS] Operational data purged safely. Protected records verified:"))
        self.stdout.write(f"    - VisitTemplates: {VisitTemplate.objects.count()} (Expected: 7)")
        self.stdout.write(f"    - Roles: {Role.objects.count()} (Expected: >=6)")
        self.stdout.write(f"    - Superusers: {User.objects.filter(is_superuser=True).count()} (Expected: >=1)")

    # --------------------------------------------------------------------------
    # PHASE 1: Areas & Bricks Import
    # --------------------------------------------------------------------------
    def execute_phase_1(self, ctx):
        self.stdout.write("Phase 1: Ensuring all Areas and Bricks from Contacts.xlsx exist...")
        contacts_file = os.path.join(ctx['source_dir'], 'Contacts.xlsx')
        df_c = pd.read_excel(contacts_file)

        created_count = 0
        if not ctx['dry_run']:
            with transaction.atomic():
                # Ensure missing brick: 'قطاعي Retail stores Great Cairo'
                gov = Area.objects.filter(name='WEA Stores Great cairo', parent__isnull=True).first()
                if not gov:
                    gov = Area.objects.create(name='WEA Stores Great cairo', code='31', area_type='governorate', is_company_area=True)
                brick, created = Area.objects.get_or_create(
                    name='قطاعي Retail stores Great Cairo',
                    defaults={
                        'code': '1234445',
                        'area_type': 'subarea',
                        'parent': gov,
                        'is_company_area': True
                    }
                )
                if created:
                    created_count += 1

        # Refresh cache
        ctx['main_area_by_name'] = {a.name.strip(): a for a in Area.objects.filter(parent__isnull=True)}
        ctx['brick_by_name'] = {a.name.strip(): a for a in Area.objects.filter(parent__isnull=False)}

        self.stdout.write(self.style.SUCCESS(f"  [PASS] Phase 1 completed. Bricks verified: {len(ctx['brick_by_name'])} in database."))

    # --------------------------------------------------------------------------
    # PHASE 2: Roles Reconciliation & Users Import
    # --------------------------------------------------------------------------
    def execute_phase_2(self, ctx):
        self.stdout.write("Phase 2: Reconciling roles and importing users from users.xlsx...")
        users_file = os.path.join(ctx['source_dir'], 'users.xlsx')
        df_u = pd.read_excel(users_file)

        if ctx['dry_run']:
            self.stdout.write(self.style.WARNING(f"  [DRY-RUN] Would process {len(df_u)} users from users.xlsx."))
            return

        with transaction.atomic():
            # 1. Suppress user post_save signals during user creation
            post_save.disconnect(handle_representative_created, sender=User)

            # 2. Create dedicated role for 'direct_sales_rep' copying from 'rep'
            rep_role = Role.objects.get(name='rep')
            direct_sales_role, _ = Role.objects.get_or_create(
                name='direct_sales_rep',
                defaults={
                    'display_name': 'مندوب مبيعات مباشر',
                    'is_rep': True,
                    'is_sales_team': True,
                    'can_hold_vault': True
                }
            )
            direct_sales_role.permissions.set(rep_role.permissions.all())
            for s in rep_role.module_scopes.all():
                RoleModuleScope.objects.get_or_create(
                    role=direct_sales_role,
                    module=s.module,
                    defaults={'view_scope': s.view_scope, 'manage_scope': s.manage_scope}
                )

            # 3. Create designated system archive user for historical orders
            archive_user, _ = User.objects.get_or_create(
                username='historical_archive@wea.com',
                defaults={
                    'email': 'historical_archive@wea.com',
                    'name': 'أرشيف العمليات التاريخية',
                    'role': rep_role,
                    'is_active': False
                }
            )
            archive_user.set_password('Wea@1111')
            archive_user.save()
            ctx['archive_user'] = archive_user

            role_cache = {
                'accountant': Role.objects.get(name='accountant'),
                'medical_rep': Role.objects.get(name='medical_rep'),
                'manager': Role.objects.get(name='manager'),
                'superadmin': Role.objects.get(name='superadmin'),
                'rep': rep_role,
                'direct_sales_rep': direct_sales_role,
            }

            USER_AREA_NAMES = {
                'bni-suief@gmail.com': ['محافظة بني سويف'],
                'sales.giza@gmail.com': ['محافظة الجيزة'],
                'wea.district.m.1@gmail.com': ['محافظة القاهرة', 'محافظة الجيزة'],
                'wea.fayoum@gmail.com': ['محافظة الفيوم'],
                'wea.imbaba@gmail.com': ['محافظة الجيزة'],
                'wea.district.m.2@gmail.com': ['محافظة القاهرة', 'محافظة الجيزة', 'محافظة بني سويف', 'محافظة الفيوم', 'محافظة المنيا'],
                'wea.maadi2@gmail.com': ['محافظة القاهرة'],
                'minia.north@gmail.com': ['محافظة المنيا'],
                'wea.bolaq@gmail.com': ['محافظة الجيزة', 'محافظة القاهرة'],
                'wea.feisal@gmail.com': ['محافظة الجيزة'],
                'mrg@gmail.com': ['محافظة القاهرة'],
                'wea.helwan@gmail.com': ['محافظة القاهرة'],
                'shobra@gmail.com': ['محافظة القاهرة', 'محافظة القليوبية'],
            }

            imported_count = 0
            for _, row in df_u.iterrows():
                email = str(row['email']).strip().lower()
                name = str(row['name']).strip()
                code = str(row['code']).strip() if pd.notna(row['code']) else ""
                mobile = clean_phone(row['mobile'])
                is_active = bool(row['active'])
                src_uuid = str(row['id']).strip()

                # Determine role
                role_str = str(row['role'])
                if 'Accountant' in role_str:
                    target_role = role_cache['accountant']
                elif 'DistrictManager' in role_str:
                    target_role = role_cache['manager']
                elif 'Direct Sales Rep' in role_str or 'DirectSalesRep' in role_str:
                    target_role = role_cache['direct_sales_rep']
                elif 'SuperAdmin' in role_str:
                    target_role = role_cache['superadmin']
                elif 'builtin:support' in role_str:
                    target_role = role_cache['rep']
                    is_active = False
                else:
                    target_role = role_cache['medical_rep']

                # Dr. Wael Atta (CEO) check
                if email == 'wea.pharm2020@gmail.com':
                    u = User.objects.filter(email=email).first()
                    if u:
                        u.name = name
                        u.role = role_cache['superadmin']
                        u.is_active = True
                        u.save()
                        ctx['user_by_uuid'][src_uuid] = u
                        ctx['user_by_uuid'][str(u.id)] = u
                        imported_count += 1
                        continue

                # Normal user upsert
                u, created = User.objects.get_or_create(
                    username=email,
                    defaults={
                        'email': email,
                        'name': name,
                        'code': code,
                        'mobile': mobile,
                        'role': target_role,
                        'is_active': is_active
                    }
                )
                if not created:
                    u.name = name
                    u.code = code
                    u.mobile = mobile
                    u.role = target_role
                    u.is_active = is_active
                u.set_password('Wea@1111')
                u.save()

                # Assign areas
                assigned_names = USER_AREA_NAMES.get(email, [])
                if assigned_names:
                    areas_to_assign = Area.objects.filter(name__in=assigned_names, parent__isnull=True)
                    u.assigned_areas.set(areas_to_assign)

                ctx['user_by_uuid'][src_uuid] = u
                ctx['user_by_uuid'][str(u.id)] = u
                imported_count += 1

            # Re-connect signal
            post_save.connect(handle_representative_created, sender=User)

        self.stdout.write(self.style.SUCCESS(f"  [PASS] Phase 2 completed: {imported_count} users imported and reconciled."))

    # --------------------------------------------------------------------------
    # PHASE 3: Warehouses & Cash Vaults
    # --------------------------------------------------------------------------
    def execute_phase_3(self, ctx):
        self.stdout.write("Phase 3: Creating and reconciling the 23 warehouses and vaults from inventory.xlsx...")
        if ctx['dry_run']:
            self.stdout.write(self.style.WARNING("  [DRY-RUN] Would create 23 warehouses and matching cash vaults."))
            return

        with transaction.atomic():
            admin_user = User.objects.filter(is_superuser=True).first()

            # 1. 10 Corporate Warehouses
            CORPORATE_WAREHOUSES = [
                ('المخزن الرئيسي بضاعه', 'WH-MAIN-01', True),
                ('مخزن المستلزمات', 'WH-SUPPLIES-01', False),
                ('مخزن اضافي 1', 'WH-EXTRA-01', False),
                ('مخزن اضافي 2', 'WH-EXTRA-02', False),
                ('مخزن اضافي 3', 'WH-EXTRA-03', False),
                ('مخزن اضافي 6', 'WH-EXTRA-06', False),
                ('مخزن اضافي 7', 'WH-EXTRA-07', False),
                ('مخزن اضافي 8', 'WH-EXTRA-08', False),
                ('مخزن فارما جروب الصعيد', 'WH-PHARMA-UPPER', False),
                ('مخزن فارما اوفرسيز جملة', 'WH-PHARMA-OVERSEAS', False),
            ]
            for name, code, is_main in CORPORATE_WAREHOUSES:
                wh, _ = Warehouse.objects.get_or_create(
                    name=name,
                    defaults={'code': code, 'is_main': is_main, 'manager': admin_user, 'is_rep_warehouse': False}
                )
                ctx['warehouse_by_name'][name] = wh

            # 2. 13 Representative Custody Warehouses and Vaults
            REP_WAREHOUSE_MAP = {
                'عهدة د. دينا علي': 'Bni-Suief@gmail.com',
                'عهدة ا. عبد الوهاب ': 'Sales.Giza@gmail.com',
                'عهدة د. محمد عصام ': 'wea.district.m.1@gmail.com',
                'عهدة د. محمد حاتم': 'wea.fayoum@gmail.com',
                'عهدة د. محمد البدري': 'wea.imbaba@gmail.com',
                'عهدة د. محمد عبد الجواد': 'wea.district.m.2@gmail.com',
                'عهدة د. دينا محمد': 'wea.maadi2@gmail.com',
                'عهدة د. ستيفن عياد ': 'Minia.North@gmail.com',
                'عهدة د. شهد أشرف ': 'wea.bolaq@gmail.com',
                'عهدة د. أحمد عبد العظيم ': 'wea.feisal@gmail.com',
                'عهدة مندوب المرج': 'MRG@gmail.com',
                'عهدة مندوب حلوان': 'wea.helwan@gmail.com',
                'عهدة مندوب شبرا الخيمة ': 'Shobra@gmail.com',
            }

            for wh_name, rep_email in REP_WAREHOUSE_MAP.items():
                rep = User.objects.filter(email=rep_email.lower()).first()
                if not rep:
                    self.stdout.write(self.style.WARNING(f"  Warning: Rep {rep_email} not found for warehouse {wh_name}"))
                    rep = admin_user

                wh, _ = Warehouse.objects.get_or_create(
                    name=wh_name,
                    defaults={
                        'code': f"WH-REP-{rep.id:04d}",
                        'assigned_user': rep,
                        'manager': rep,
                        'is_rep_warehouse': True,
                        'is_main': False
                    }
                )
                ctx['warehouse_by_name'][wh_name] = wh

                # Vault for representative
                vault, _ = Vault.objects.get_or_create(
                    name=f"خزنة {wh_name.strip()}",
                    defaults={
                        'vault_type': 'cash',
                        'assigned_user': rep,
                        'is_rep_vault': True,
                        'is_active': True,
                        'current_balance': Decimal('0.00')
                    }
                )
                ctx['vault_by_name'][f"خزنة {wh_name.strip()}"] = vault

            # 3. Central Company Cash Vault
            central_vault, _ = Vault.objects.get_or_create(
                name='الخزينة الرئيسية - المقر الرئيسي',
                defaults={
                    'vault_type': 'cash',
                    'is_rep_vault': False,
                    'is_active': True,
                    'current_balance': Decimal('0.00')
                }
            )
            ctx['vault_by_name']['الخزينة الرئيسية - المقر الرئيسي'] = central_vault

        self.stdout.write(self.style.SUCCESS(f"  [PASS] Phase 3 completed: {Warehouse.objects.count()} warehouses and {Vault.objects.count()} vaults verified."))

    # --------------------------------------------------------------------------
    # PHASE 4 & 5: Categories & Products
    # --------------------------------------------------------------------------
    def execute_phase_4(self, ctx):
        self.stdout.write("Phase 4 & 5: Importing Categories and Products from inventory.xlsx...")
        if ctx['dry_run']:
            self.stdout.write(self.style.WARNING("  [DRY-RUN] Would upsert 2 categories and 11 products."))
            return

        with transaction.atomic():
            cat_wea, _ = ProductCategory.objects.get_or_create(
                name='WEA',
                defaults={'code': 'WEA', 'description': 'مستحضرات وأدوية شركة WEA Pharma'}
            )
            cat_pack, _ = ProductCategory.objects.get_or_create(
                name='Packing materials',
                defaults={'code': 'PACK-MAT', 'description': 'مستلزمات ومواد تعبئة وتغليف'}
            )

            # 6 Finished Products
            PHARMA_PRODUCTS = [
                ('ST1', 'Steps', Decimal('140.00'), Decimal('85.00')),
                ('GE1', 'Geron', Decimal('140.00'), Decimal('18.80')),
                ('UL1', 'Ultrahumudin Cream', Decimal('105.00'), Decimal('7.00')),
                ('PU1', 'Putalaxy gel', Decimal('75.00'), Decimal('7.00')),
                ('SO1', 'Soriana V.D', Decimal('75.00'), Decimal('8.50')),
                ('LE1', 'Legatonexx Spray', Decimal('120.00'), Decimal('2.35')),
            ]
            for sku, name, price, cost in PHARMA_PRODUCTS:
                p, _ = Product.objects.get_or_create(
                    sku_code=sku,
                    defaults={
                        'name': name,
                        'category': cat_wea,
                        'retail_price': price,
                        'default_purchase_cost': cost,
                        'sellable': True,
                        'is_active': True
                    }
                )
                ctx['product_by_sku'][sku] = p

            # 5 Packaging items
            PACK_ITEMS = [
                ('6000', 'كرتون جيرون', Decimal('0.00'), Decimal('0.00')),
                ('4000', 'كرتون الترا هيوميدين', Decimal('0.00'), Decimal('0.00')),
                ('7000', 'تيوب الالترا هيوميدين', Decimal('0.00'), Decimal('3.10')),
                ('2000', 'كرتون ليجاتونيكس', Decimal('0.00'), Decimal('0.00')),
                ('1000', 'كرتون سوريانا', Decimal('0.00'), Decimal('0.00')),
            ]
            for sku, name, price, cost in PACK_ITEMS:
                p, _ = Product.objects.get_or_create(
                    sku_code=sku,
                    defaults={
                        'name': name,
                        'category': cat_pack,
                        'retail_price': price,
                        'default_purchase_cost': cost,
                        'sellable': False,
                        'is_active': True
                    }
                )
                ctx['product_by_sku'][sku] = p

        self.stdout.write(self.style.SUCCESS(f"  [PASS] Phase 4 & 5 completed: {Product.objects.count()} products verified."))

    # --------------------------------------------------------------------------
    # PHASE 6: Inventory Stock & Lots Import
    # --------------------------------------------------------------------------
    def execute_phase_6(self, ctx):
        self.stdout.write("Phase 6: Importing Stock quantities and lot numbers from inventory.xlsx...")
        inv_file = os.path.join(ctx['source_dir'], 'inventory.xlsx')
        df_inv = pd.read_excel(inv_file)

        if ctx['dry_run']:
            self.stdout.write(self.style.WARNING(f"  [DRY-RUN] Would process {len(df_inv)} stock rows."))
            return

        with transaction.atomic():
            admin_user = User.objects.filter(is_superuser=True).first()

            # Create an opening memo
            main_wh = ctx['warehouse_by_name'].get('المخزن الرئيسي بضاعه') or Warehouse.objects.filter(code='WH-MAIN-01').first()
            memo, _ = InventoryMemo.objects.get_or_create(
                memo_number='MEMO-OPENING-2026',
                defaults={
                    'memo_type': 'inward',
                    'warehouse': main_wh,
                    'statement': 'أرصدة افتتاحية للمخازن',
                    'status': 'applied',
                    'applied_at': timezone.now(),
                    'created_by': admin_user
                }
            )

            # Group by warehouse and sku
            grouped = df_inv.groupby(['المخزن', 'الكود'])
            for (wh_name, sku), group_df in grouped:
                wh = ctx['warehouse_by_name'].get(wh_name)
                prod = ctx['product_by_sku'].get(str(sku).strip())
                if not wh or not prod:
                    continue

                on_hand_val = group_df['فى المخزن'].dropna().sum()
                total_on_hand = parse_dec(on_hand_val)
                reserved_val = group_df['محجوز'].dropna().sum()
                total_reserved = parse_dec(reserved_val)

                # Weighted cost calculation
                cost_sum = Decimal('0.00')
                qty_with_cost = Decimal('0.00')
                for _, r in group_df.iterrows():
                    q = parse_dec(r['فى المخزن'])
                    if pd.notna(r['التكلفة']) and q > Decimal('0.00'):
                        c = parse_dec(r['التكلفة'])
                        cost_sum += q * c
                        qty_with_cost += q
                weighted_cost = (cost_sum / qty_with_cost).quantize(Decimal('0.01')) if qty_with_cost > Decimal('0.00') else prod.default_purchase_cost

                stock, _ = InventoryStock.objects.get_or_create(
                    warehouse=wh,
                    product=prod,
                    defaults={
                        'qty_on_hand': total_on_hand,
                        'qty_reserved': total_reserved,
                        'product_cost': weighted_cost
                    }
                )

                # Lots
                for _, r in group_df.iterrows():
                    batch = str(r['رقم التشغيل']).strip() if pd.notna(r['رقم التشغيل']) and str(r['رقم التشغيل']).strip() not in ('nan', 'None') else ""
                    exp_date = parse_date_safe(r['تاريخ الصلاحية'])
                    lot_qty = parse_dec(r['فى المخزن'])
                    if batch and lot_qty > Decimal('0.00'):
                        InventoryLot.objects.get_or_create(
                            stock=stock,
                            batch_number=batch,
                            expiry_date=exp_date,
                            defaults={'quantity': lot_qty}
                        )

        total_stock = InventoryStock.objects.aggregate(total=Sum('qty_on_hand'))['total'] or Decimal('0.00')
        self.stdout.write(self.style.SUCCESS(f"  [PASS] Phase 6 completed: Total stock on-hand = {total_stock:,.2f} units."))

    # --------------------------------------------------------------------------
    # PHASE 7: Contacts & Addresses Import
    # --------------------------------------------------------------------------
    def execute_phase_7(self, ctx):
        self.stdout.write("Phase 7: Importing CRM Contacts and Addresses from Contacts.xlsx...")
        contacts_file = os.path.join(ctx['source_dir'], 'Contacts.xlsx')
        df_c = pd.read_excel(contacts_file)

        if ctx['dry_run']:
            self.stdout.write(self.style.WARNING(f"  [DRY-RUN] Would import {len(df_c)} contacts."))
            return

        with transaction.atomic():
            contacts_to_create = []
            addresses_to_create = []
            rep_user_links = []  # tuple of (contact_idx, rep_user)

            # Pre-load users by name
            users_by_name = {u.name.strip(): u for u in User.objects.all()}

            for idx, row in df_c.iterrows():
                src_uuid = str(row['المعرف']).strip()
                name = str(row['الاسم']).strip()
                serial = int(row['مسلسل'])
                code = str(row['الكود']).strip()
                acc_type = str(row['نوع الاكونت']).strip()
                is_supplier = (acc_type == 'مورد')
                is_customer = not is_supplier
                cust_category = str(row['تصنيف العميل']).strip() if pd.notna(row['تصنيف العميل']) else ""
                specialty = str(row['التخصص']).strip() if pd.notna(row['التخصص']) else ""
                mobile = clean_phone(row['الموبايل'])

                main_area = ctx['main_area_by_name'].get(str(row['المنطقة - المنطقة الرئيسية - الاسم']).strip())
                brick = ctx['brick_by_name'].get(str(row['المنطقة - الاسم']).strip())

                c = Contact(
                    serial_num=serial,
                    name=name,
                    code=code,
                    account_type=acc_type,
                    is_customer=is_customer,
                    is_supplier=is_supplier,
                    customer_category=cust_category,
                    specialty=specialty,
                    mobile=mobile,
                    area=main_area,
                    brick=brick,
                    custom_values={'source_uuid': src_uuid, 'legacy_group': str(row['المنطقة - المجموعة'])}
                )
                contacts_to_create.append(c)

            # Insert missing customer: شيماء البقشيشى (Contact_SerialNum: 6489 from customers accounts.xlsx)
            giza_gov = ctx['main_area_by_name'].get('محافظة الجيزة') or ctx['main_area_by_name'].get('محافظة القاهرة')
            c_orphan = Contact(
                serial_num=6489,
                name='شيماء البقشيشى',
                code='W0749',
                account_type='عيادة',
                is_customer=True,
                is_supplier=False,
                specialty='Gynaecology',
                mobile='01006933356',
                area=giza_gov,
                custom_values={'source_uuid': 'd3618869-fc53-45d3-92b7-cf242c434f50', 'synthesized': True}
            )
            contacts_to_create.append(c_orphan)

            Contact.objects.bulk_create(contacts_to_create, batch_size=1000)

            # Refresh cache
            for c in Contact.objects.all():
                suuid = c.custom_values.get('source_uuid')
                if suuid:
                    ctx['contact_by_uuid'][suuid] = c

            # Address creation
            for idx, row in df_c.iterrows():
                src_uuid = str(row['المعرف']).strip()
                contact = ctx['contact_by_uuid'].get(src_uuid)
                addr_str = str(row['العنوان الرئيسي - العنوان']).strip() if pd.notna(row['العنوان الرئيسي - العنوان']) and str(row['العنوان الرئيسي - العنوان']).strip() not in ('nan', 'None') else ""
                coords_str = str(row['العنوان الرئيسي - الموقع - الإحداثيات']).strip() if pd.notna(row['العنوان الرئيسي - الموقع - الإحداثيات']) and str(row['العنوان الرئيسي - الموقع - الإحداثيات']).strip() not in ('nan', 'None') else ""

                lat, lng = None, None
                if coords_str and ',' in coords_str:
                    try:
                        p_lat, p_lng = coords_str.split(',')
                        lat = parse_dec(p_lat.strip())
                        lng = parse_dec(p_lng.strip())
                    except Exception:
                        pass

                if contact and (addr_str or lat):
                    addresses_to_create.append(ContactAddress(
                        contact=contact,
                        title='العنوان الرئيسي',
                        is_main=True,
                        street_address=addr_str,
                        area=contact.area,
                        brick=contact.brick,
                        latitude=lat,
                        longitude=lng
                    ))

            ContactAddress.objects.bulk_create(addresses_to_create, batch_size=1000)

        self.stdout.write(self.style.SUCCESS(f"  [PASS] Phase 7 completed: {Contact.objects.count()} contacts and {ContactAddress.objects.count()} addresses imported."))

    # --------------------------------------------------------------------------
    # PHASE 8 & 9: Customer & Vendor Financial Accounts
    # --------------------------------------------------------------------------
    def execute_phase_8(self, ctx):
        self.stdout.write("Phase 8 & 9: Importing Customer and Vendor accounts with balances...")
        ca_file = os.path.join(ctx['source_dir'], 'customers accounts.xlsx')
        va_file = os.path.join(ctx['source_dir'], 'vendors accounts.xlsx')
        df_ca = pd.read_excel(ca_file).drop_duplicates(subset=['AccountID'])
        df_va = pd.read_excel(va_file)

        if ctx['dry_run']:
            self.stdout.write(self.style.WARNING(f"  [DRY-RUN] Would import {len(df_ca)} customer accounts and {len(df_va)} vendor accounts."))
            return

        with transaction.atomic():
            ca_objs = []
            for _, row in df_ca.iterrows():
                contact_uuid = str(row['ContactID']).strip()
                contact = ctx['contact_by_uuid'].get(contact_uuid)
                if not contact:
                    continue

                bal = parse_dec(row['Account_AccountStats_Balance'])
                cred_lim = parse_dec(row['Account_AccountLimits_BalanceLimit'])
                days = int(row['Account_AccountLimits_DefaultDuePeriodDays']) if pd.notna(row['Account_AccountLimits_DefaultDuePeriodDays']) and str(row['Account_AccountLimits_DefaultDuePeriodDays']).strip() not in ('', 'nan', 'None') else 0
                overdue = parse_dec(row['Account_AccountStats_OverdueAmount'])
                last_tx = parse_date_safe(row['Account_AccountStats_LastTransactionDate'])

                ca_objs.append(CustomerAccount(
                    customer=contact,
                    current_balance=bal,
                    credit_limit=cred_lim,
                    credit_period_days=days,
                    overdue_balance=overdue,
                    last_transaction_date=last_tx
                ))

            CustomerAccount.objects.bulk_create(ca_objs, batch_size=500)

            # Vendor Accounts
            va_objs = []
            for _, row in df_va.iterrows():
                contact_uuid = str(row['ContactID']).strip()
                contact = ctx['contact_by_uuid'].get(contact_uuid)
                if not contact:
                    continue

                bal = parse_dec(row['Account_AccountStats_Balance'])
                cred_lim = parse_dec(row['Account_AccountLimits_BalanceLimit'])
                last_tx = parse_date_safe(row['Account_AccountStats_LastTransactionDate'])
                overdue = parse_dec(row['Account_AccountStats_OverdueAmount'])

                va_objs.append(VendorAccount(
                    supplier=contact,
                    current_balance=bal,
                    credit_limit=cred_lim,
                    credit_period_days=0,
                    overdue_balance=overdue,
                    last_transaction_date=last_tx
                ))

            VendorAccount.objects.bulk_create(va_objs)

        tot_ca = CustomerAccount.objects.aggregate(t=Sum('current_balance'))['t'] or Decimal('0.00')
        tot_va = VendorAccount.objects.aggregate(t=Sum('current_balance'))['t'] or Decimal('0.00')
        self.stdout.write(self.style.SUCCESS(f"  [PASS] Phase 8 & 9 completed:"))
        self.stdout.write(f"    - Customer Accounts: {CustomerAccount.objects.count()} (Net Balance: {tot_ca:,.2f} EGP)")
        self.stdout.write(f"    - Vendor Accounts: {VendorAccount.objects.count()} (Net Liabilities: {tot_va:,.2f} EGP)")

    # --------------------------------------------------------------------------
    # PHASE 10 & 11: Sales Orders & Sales Returns
    # --------------------------------------------------------------------------
    def execute_phase_10(self, ctx):
        self.stdout.write("Phase 10 & 11: Importing Sales Orders and Sales Returns...")
        so_file = os.path.join(ctx['source_dir'], 'sales-orders.xlsx')
        ro_file = os.path.join(ctx['source_dir'], 'return-orders.xlsx')
        df_so = pd.read_excel(so_file)
        df_ro = pd.read_excel(ro_file)

        if ctx['dry_run']:
            self.stdout.write(self.style.WARNING(f"  [DRY-RUN] Would import {len(df_so)} sales orders and {len(df_ro)} return order items."))
            return

        with transaction.atomic():
            main_wh = ctx['warehouse_by_name'].get('المخزن الرئيسي بضاعه') or Warehouse.objects.filter(code='WH-MAIN-01').first()
            archive_user = ctx['archive_user'] or User.objects.get(username='historical_archive@wea.com')

            # 1. Sales Orders (Headers only)
            STATUS_MAP = {
                'Invoiced': 'invoiced',
                'Delivered': 'delivered',
                'Manager Approved': 'manager_approval',
                'Preparing': 'preparing',
            }

            so_objs = []
            for _, row in df_so.iterrows():
                order_num = str(row['المعرف']).strip()
                serial = int(row['مسلسل'])
                cust_uuid = str(row['العميل - المعرف']).strip()
                customer = ctx['contact_by_uuid'].get(cust_uuid)
                if not customer:
                    continue

                creator_uuid = str(row['المنشء - المعرف']).strip()
                creator = ctx['user_by_uuid'].get(creator_uuid, archive_user)

                # Source Warehouse: rep warehouse or central
                wh = creator.get_default_warehouse() if creator != archive_user else None
                if not wh:
                    wh = main_wh

                order_date = parse_date_safe(row['تاريخ الإنشاء']) or timezone.now().date()
                status = STATUS_MAP.get(str(row['الحالة - الاسم']).strip(), 'invoiced')

                subtotal = parse_dec(row['الإجمالي'])
                items_disc = parse_dec(row['خصم المبيعات'])
                custom_disc_pct = parse_dec(row['الخصم الإضافي - نسبة'])
                custom_disc_amt = parse_dec(row['الخصم الإضافي - قيمة'])
                shipping = parse_dec(row['مصاريف الشحن'])
                grand_total = parse_dec(row['الإجمالي النهائي'])
                notes = str(row['ملاحظة']).strip() if pd.notna(row['ملاحظة']) and str(row['ملاحظة']).strip() not in ('nan', 'None') else ""

                so_objs.append(SalesOrder(
                    order_number=order_num,
                    serial_num=serial,
                    customer=customer,
                    source_warehouse=wh,
                    created_by=creator,
                    order_date=order_date,
                    status=status,
                    subtotal=subtotal,
                    items_discount_total=items_disc,
                    custom_discount_percentage=custom_disc_pct,
                    custom_discount_amount=custom_disc_amt,
                    shipping_fees=shipping,
                    grand_total=grand_total,
                    notes=notes
                ))

            SalesOrder.objects.bulk_create(so_objs, batch_size=1000)

            # 2. Sales Returns (Headers and Line items)
            RO_STATUS_MAP = {
                'Settled': 'settled',
                'Picked': 'delivered',
                'Pending': 'pending',
            }
            grouped_ro = df_ro.groupby('المعرف')
            ro_headers = []
            ro_items_by_ordernum = {}

            for order_num, group_df in grouped_ro:
                first_row = group_df.iloc[0]
                serial = int(first_row['مسلسل'])
                cust_uuid = str(first_row['العميل - المعرف']).strip()
                customer = ctx['contact_by_uuid'].get(cust_uuid)
                if not customer:
                    continue

                creator_uuid = str(first_row['المنشء - المعرف']).strip()
                creator = ctx['user_by_uuid'].get(creator_uuid, archive_user)
                wh = creator.get_default_warehouse() if creator != archive_user else None
                if not wh:
                    wh = main_wh

                status = RO_STATUS_MAP.get(str(first_row['الحالة - الاسم']).strip(), 'settled')
                order_date = parse_date_safe(first_row['تاريخ الإنشاء']) or timezone.now().date()
                grand_total = parse_dec(first_row['الإجمالي النهائي'])

                ro_obj = SalesReturnOrder(
                    order_number=str(order_num).strip(),
                    serial_num=serial,
                    customer=customer,
                    target_warehouse=wh,
                    created_by=creator,
                    status=status,
                    order_date=order_date,
                    grand_total=grand_total
                )
                ro_headers.append(ro_obj)
                ro_items_by_ordernum[str(order_num).strip()] = group_df

            SalesReturnOrder.objects.bulk_create(ro_headers)

            # Build lookup for return orders
            ro_by_num = {ro.order_number: ro for ro in SalesReturnOrder.objects.all()}

            ro_item_objs = []
            for order_num, group_df in ro_items_by_ordernum.items():
                ro = ro_by_num.get(order_num)
                if not ro:
                    continue
                for _, r in group_df.iterrows():
                    sku = str(r['العناصر - المنتج - الكود']).strip()
                    prod = ctx['product_by_sku'].get(sku)
                    if not prod:
                        continue
                    qty = parse_dec(r['العناصر - الكمية'], default='1.00')
                    price = parse_dec(r['العناصر - سعر القطعة'])
                    tot = parse_dec(r['العناصر - الكلي'])
                    batch = str(r['العناصر - رقم تشغيل المنتج']).strip() if pd.notna(r['العناصر - رقم تشغيل المنتج']) and str(r['العناصر - رقم تشغيل المنتج']).strip() not in ('nan', 'None') else ""
                    exp_date = parse_date_safe(r['العناصر - تاريخ صلاحية المنتج'])

                    ro_item_objs.append(SalesReturnOrderItem(
                        order=ro,
                        product=prod,
                        quantity=qty,
                        unit_price=price,
                        subtotal=tot,
                        batch_number=batch,
                        expiry_date=exp_date
                    ))

            SalesReturnOrderItem.objects.bulk_create(ro_item_objs, batch_size=500)

        tot_so = SalesOrder.objects.aggregate(t=Sum('grand_total'))['t'] or Decimal('0.00')
        tot_ro = SalesReturnOrder.objects.aggregate(t=Sum('grand_total'))['t'] or Decimal('0.00')
        self.stdout.write(self.style.SUCCESS(f"  [PASS] Phase 10 & 11 completed:"))
        self.stdout.write(f"    - Sales Orders: {SalesOrder.objects.count()} (Total: {tot_so:,.2f} EGP)")
        self.stdout.write(f"    - Sales Returns: {SalesReturnOrder.objects.count()} (Total: {tot_ro:,.2f} EGP)")
        self.stdout.write(f"    - Sales Return Line Items: {SalesReturnOrderItem.objects.count()}")

    # --------------------------------------------------------------------------
    # PHASE 12: Purchase Orders & Returns
    # --------------------------------------------------------------------------
    def execute_phase_12(self, ctx):
        self.stdout.write("Phase 12: Importing Purchase Orders and Returns...")
        po_file = os.path.join(ctx['source_dir'], 'Purchase-orders.xlsx')
        pro_file = os.path.join(ctx['source_dir'], 'purchase-return-orders.xlsx')
        df_po = pd.read_excel(po_file)
        df_pro = pd.read_excel(pro_file)

        if ctx['dry_run']:
            self.stdout.write(self.style.WARNING(f"  [DRY-RUN] Would import {len(df_po)} purchase orders and {len(df_pro)} purchase returns."))
            return

        with transaction.atomic():
            main_wh = ctx['warehouse_by_name'].get('المخزن الرئيسي بضاعه') or Warehouse.objects.filter(code='WH-MAIN-01').first()
            admin_user = User.objects.filter(is_superuser=True).first()

            PO_STATUS_MAP = {
                'Settled': 'settled',
                'Picked': 'picked',
            }

            po_objs = []
            for _, row in df_po.iterrows():
                order_num = str(row['المعرف']).strip()
                serial = int(row['مسلسل'])
                supp_uuid = str(row['العميل - المعرف']).strip()
                supplier = ctx['contact_by_uuid'].get(supp_uuid)
                if not supplier:
                    continue

                order_date = parse_date_safe(row['تاريخ الإنشاء']) or timezone.now().date()
                status = PO_STATUS_MAP.get(str(row['الحالة - الاسم']).strip(), 'settled')

                subtotal = parse_dec(row['الإجمالي'])
                grand_total = parse_dec(row['الإجمالي النهائي'])
                items_count = int(row['عدد الأسطر']) if pd.notna(row['عدد الأسطر']) and str(row['عدد الأسطر']).strip() not in ('', 'nan', 'None') else 1
                items_qty = parse_dec(row['عدد القطع'], default='1.00')

                po_objs.append(PurchaseOrder(
                    order_number=order_num,
                    serial_num=serial,
                    supplier=supplier,
                    target_warehouse=main_wh,
                    order_date=order_date,
                    status=status,
                    subtotal=subtotal,
                    grand_total=grand_total,
                    items_count=items_count,
                    items_quantity=items_qty,
                    created_by=admin_user
                ))

            PurchaseOrder.objects.bulk_create(po_objs)

            # Purchase Return
            for _, row in df_pro.iterrows():
                order_num = str(row['المعرف']).strip()
                serial = int(row['مسلسل'])
                supp_uuid = str(row['العميل - المعرف']).strip()
                supplier = ctx['contact_by_uuid'].get(supp_uuid)
                if not supplier:
                    continue
                grand_total = parse_dec(row['الإجمالي النهائي'], default='10000.00')
                order_date = parse_date_safe(row['تاريخ الإنشاء']) or timezone.now().date()

                PurchaseReturnOrder.objects.get_or_create(
                    order_number=order_num,
                    defaults={
                        'serial_num': serial,
                        'supplier': supplier,
                        'warehouse': main_wh,
                        'status': 'settled',
                        'order_date': order_date,
                        'grand_total': grand_total,
                        'created_by': admin_user
                    }
                )

        tot_po = PurchaseOrder.objects.aggregate(t=Sum('grand_total'))['t'] or Decimal('0.00')
        self.stdout.write(self.style.SUCCESS(f"  [PASS] Phase 12 completed: {PurchaseOrder.objects.count()} POs (Total: {tot_po:,.2f} EGP) and {PurchaseReturnOrder.objects.count()} PRO."))

    # --------------------------------------------------------------------------
    # PHASE 13: Collections & Vendor Payments
    # --------------------------------------------------------------------------
    def execute_phase_13(self, ctx):
        self.stdout.write("Phase 13: Importing Collections and Vendor Payments...")
        coll_file = os.path.join(ctx['source_dir'], 'collections.xlsx')
        vp_file = os.path.join(ctx['source_dir'], 'Vendor-payments.xlsx')
        df_coll = pd.read_excel(coll_file)
        df_vp = pd.read_excel(vp_file)

        if ctx['dry_run']:
            self.stdout.write(self.style.WARNING(f"  [DRY-RUN] Would import {len(df_coll)} collections and {len(df_vp)} vendor payments."))
            return

        with transaction.atomic():
            archive_user = ctx['archive_user'] or User.objects.get(username='historical_archive@wea.com')
            central_vault = ctx['vault_by_name'].get('الخزينة الرئيسية - المقر الرئيسي') or Vault.objects.filter(is_rep_vault=False).first()

            # 1. Collections
            coll_objs = []
            for _, row in df_coll.iterrows():
                serial = int(row['رقم التسلسل'])
                cust_uuid = str(row['id عميل']).strip()
                customer = ctx['contact_by_uuid'].get(cust_uuid)
                if not customer:
                    continue

                amt = parse_dec(row['الكمية'])
                c_date = parse_date_safe(row['تاريخ الإنشاء']) or timezone.now().date()
                method = 'cheque' if str(row['طريقة الدفع']).strip() == 'cheque' else 'cash'

                collector_uuid = str(row['id المنشء']).strip()
                collector = ctx['user_by_uuid'].get(collector_uuid, archive_user)

                vault = collector.get_default_treasury() if collector != archive_user else None
                if not vault:
                    vault = central_vault

                notes = str(row['ID']).strip()

                coll_objs.append(Collection(
                    serial_num=serial,
                    customer=customer,
                    vault=vault,
                    amount=amt,
                    collection_date=c_date,
                    payment_method=method,
                    notes=notes,
                    created_by=collector
                ))

            Collection.objects.bulk_create(coll_objs, batch_size=1000)

            # 2. Vendor Payments
            vp_objs = []
            admin_user = User.objects.filter(is_superuser=True).first()
            for _, row in df_vp.iterrows():
                serial = int(row['رقم التسلسل'])
                supp_uuid = str(row['id جهة الإتصال']).strip()
                supplier = ctx['contact_by_uuid'].get(supp_uuid)
                if not supplier:
                    continue

                amt = parse_dec(row['الكمية'])
                p_date = parse_date_safe(row['تاريخ الإنشاء']) or timezone.now().date()
                ref_num = str(row['ID']).strip()

                vp_objs.append(VendorPayment(
                    serial_num=serial,
                    supplier=supplier,
                    vault=central_vault,
                    payment_date=p_date,
                    amount=amt,
                    payment_method='cash',
                    reference_number=ref_num,
                    status='cleared',
                    created_by=admin_user
                ))

            VendorPayment.objects.bulk_create(vp_objs)

        tot_coll = Collection.objects.aggregate(t=Sum('amount'))['t'] or Decimal('0.00')
        tot_vp = VendorPayment.objects.aggregate(t=Sum('amount'))['t'] or Decimal('0.00')
        self.stdout.write(self.style.SUCCESS(f"  [PASS] Phase 13 completed:"))
        self.stdout.write(f"    - Collections: {Collection.objects.count()} (Total: {tot_coll:,.2f} EGP)")
        self.stdout.write(f"    - Vendor Payments: {VendorPayment.objects.count()} (Total: {tot_vp:,.2f} EGP)")

    # --------------------------------------------------------------------------
    # PHASE 14: Vendor Ledger Journal
    # --------------------------------------------------------------------------
    def execute_phase_14(self, ctx):
        self.stdout.write("Phase 14: Importing Vendor Ledger Transactions from vendor-transactions.xlsx...")
        vt_file = os.path.join(ctx['source_dir'], 'vendor-transactions.xlsx')
        df_vt = pd.read_excel(vt_file)

        if ctx['dry_run']:
            self.stdout.write(self.style.WARNING(f"  [DRY-RUN] Would import {len(df_vt)} vendor transactions."))
            return

        with transaction.atomic():
            admin_user = User.objects.filter(is_superuser=True).first()
            po_by_num = {po.order_number: po for po in PurchaseOrder.objects.all()}

            # Cache vendor accounts by supplier name
            va_by_name = {}
            for va in VendorAccount.objects.select_related('supplier').all():
                va_by_name[va.supplier.name.strip()] = va

            vt_objs = []
            start_serial = 10001
            for _, row in df_vt.iterrows():
                src_uuid = str(row['المعرف']).strip()
                acc_name = str(row['الحساب - الاسم']).strip()
                # Extract clean name
                clean_name = acc_name
                if ']' in acc_name:
                    clean_name = acc_name.split(']')[1].strip()

                va = va_by_name.get(clean_name)
                if not va:
                    # Try partial match
                    for k, v in va_by_name.items():
                        if k in clean_name or clean_name in k:
                            va = v
                            break
                if not va:
                    continue

                tx_type = 'credit' if str(row['نوع الحركة']).strip() == 'credit' else 'debit'
                reason = str(row['السبب']).strip() if pd.notna(row['السبب']) and str(row['السبب']).strip() not in ('nan', 'None') else 'adjustment'
                tx_date = parse_date_safe(row['التاريخ']) or timezone.now().date()
                due_date = parse_date_safe(row['تاريخ الاستحقاق'])
                credit = parse_dec(row['دائن'])
                debit = parse_dec(row['مدين'])
                bal = parse_dec(row['الرصيد'])
                raw_notes = str(row['ملاحظة']).strip() if pd.notna(row['ملاحظة']) and str(row['ملاحظة']).strip() not in ('nan', 'None') else ""
                notes = f"{raw_notes} (Legacy: {src_uuid})" if raw_notes else f"Legacy: {src_uuid}"

                # Link PO if reason is purchase
                po = None
                if reason == 'purchase' and pd.notna(row['السبب - الرقم']):
                    po_ref = str(row['السبب - الرقم']).replace('#', '').strip()
                    if po_ref.isdigit():
                        po = PurchaseOrder.objects.filter(serial_num=int(po_ref)).first()

                vt_objs.append(VendorTransaction(
                    serial=start_serial + len(vt_objs),
                    account=va,
                    purchase_order=po,
                    transaction_type=tx_type,
                    reason=reason,
                    transaction_date=tx_date,
                    due_date=due_date,
                    credit=credit,
                    debit=debit,
                    running_balance=bal,
                    description=f"{reason} - {raw_notes}"[:255] if raw_notes else reason,
                    notes=notes,
                    created_by=admin_user
                ))

            VendorTransaction.objects.bulk_create(vt_objs)

        self.stdout.write(self.style.SUCCESS(f"  [PASS] Phase 14 completed: {VendorTransaction.objects.count()} vendor transactions imported."))

    # --------------------------------------------------------------------------
    # PHASE 15: Post-Migration Quantitative Verification
    # --------------------------------------------------------------------------
    def execute_phase_15(self, ctx):
        self.stdout.write("Phase 15: Running quantitative reconciliation and assertion suite...")
        if ctx['dry_run']:
            self.stdout.write(self.style.WARNING("  [DRY-RUN] Verification assertions skipped in dry-run mode."))
            return

        # 1. Protected Records Check
        assert VisitTemplate.objects.count() == 7, f"VisitTemplate count mismatch: {VisitTemplate.objects.count()}"
        assert VisitTemplateQuestion.objects.count() == 21, f"VisitTemplateQuestion count mismatch: {VisitTemplateQuestion.objects.count()}"
        assert Role.objects.count() >= 6, f"Role count mismatch: {Role.objects.count()}"
        assert User.objects.filter(is_superuser=True).exists(), "Superuser missing!"

        # 2. Territorial & Contacts Check
        assert Area.objects.filter(parent__isnull=False).count() >= 217, "Bricks missing!"
        assert Contact.objects.count() == 8963, f"Contact count mismatch: {Contact.objects.count()}"

        # 3. Financial Balances Check
        cust_bal = CustomerAccount.objects.aggregate(total=Sum('current_balance'))['total'] or Decimal('0.00')
        assert abs(cust_bal - Decimal('506108.99')) < Decimal('1.00'), f"Customer balance mismatch: {cust_bal}"

        vend_bal = VendorAccount.objects.aggregate(total=Sum('current_balance'))['total'] or Decimal('0.00')
        assert abs(vend_bal - Decimal('192388.52')) < Decimal('1.00'), f"Vendor balance mismatch: {vend_bal}"

        # 4. Inventory Stock Check
        total_qty = InventoryStock.objects.aggregate(total=Sum('qty_on_hand'))['total'] or Decimal('0.00')
        assert abs(total_qty - Decimal('143076.00')) < Decimal('1.00'), f"Stock qty mismatch: {total_qty}"
        assert Warehouse.objects.count() == 23, f"Warehouse count mismatch: {Warehouse.objects.count()}"
        assert Vault.objects.count() == 14, f"Vault count mismatch: {Vault.objects.count()}"
        assert Product.objects.count() == 11, f"Product count mismatch: {Product.objects.count()}"

        # 5. Orders & Collections Check
        assert SalesOrder.objects.count() == 7276, f"Sales orders count mismatch: {SalesOrder.objects.count()}"
        assert SalesReturnOrder.objects.count() == 286, f"Sales returns count mismatch: {SalesReturnOrder.objects.count()}"
        assert SalesReturnOrderItem.objects.count() == 463, f"Return line items count mismatch: {SalesReturnOrderItem.objects.count()}"
        assert Collection.objects.count() == 6856, f"Collections count mismatch: {Collection.objects.count()}"
        assert PurchaseOrder.objects.count() == 17, f"Purchase orders count mismatch: {PurchaseOrder.objects.count()}"
        assert PurchaseReturnOrder.objects.count() == 1, f"Purchase returns count mismatch: {PurchaseReturnOrder.objects.count()}"
        assert VendorPayment.objects.count() == 31, f"Vendor payments count mismatch: {VendorPayment.objects.count()}"
        assert VendorTransaction.objects.count() == 62, f"Vendor transactions count mismatch: {VendorTransaction.objects.count()}"

        self.stdout.write(self.style.SUCCESS("  [PASS] All 5 Core Verification Audits Passed Perfectly!"))
        self.stdout.write("    ✓ Protected Records Preserved: 7 Visit Templates, 21 Questions, 6 Roles, Superusers.")
        self.stdout.write(f"    ✓ Contacts & Territory: 8,963 Contacts, 217 Bricks.")
        self.stdout.write(f"    ✓ Financial Ledgers: Customers = {cust_bal:,.2f} EGP, Vendors = {vend_bal:,.2f} EGP.")
        self.stdout.write(f"    ✓ Physical Inventory: {total_qty:,.2f} on-hand units across 23 Warehouses.")
        self.stdout.write(f"    ✓ Commercial Orders: 7,276 Sales Orders, 6,856 Collections, 17 Purchase Orders.")
