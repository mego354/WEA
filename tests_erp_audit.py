import datetime
from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone

from accounts.models import Role, SecurityAuditLog
from accounts.services import ensure_representative_resources
from master_data.models import Area
from contacts.models import Contact, ContactAddress
from purchases.models import PurchaseOrder, PurchaseOrderItem
from sales.models import SalesOrder, SalesOrderItem, Collection, CustomerAccount
from treasury.models import Vault, VendorAccount, VendorPayment
from catalog.models import Product, ProductCategory
from inventory.models import Warehouse, InventoryStock, InventoryMemo
from purchases.services import PurchaseOrderService
from sales.services import SalesOrderService, CollectionService
from treasury.services import TreasuryService

User = get_user_model()


class ERPAuditTestSuite(TestCase):
    def setUp(self):
        # Create or fetch canonical roles
        self.superadmin_role, _ = Role.objects.get_or_create(
            name=Role.ROLE_SUPERADMIN, defaults={'display_name': "مدير النظام الأعلى", 'is_super': True}
        )
        self.accountant_role, _ = Role.objects.get_or_create(
            name=Role.ROLE_ACCOUNTANT, defaults={'display_name': "محاسب"}
        )
        self.manager_role, _ = Role.objects.get_or_create(
            name=Role.ROLE_MANAGER, defaults={'display_name': "مدير منطقة", 'is_area_manager': True}
        )
        self.rep_role, _ = Role.objects.get_or_create(
            name=Role.ROLE_REP, defaults={'display_name': "مندوب مبيعات", 'is_sales_team': True, 'is_rep': True}
        )

        # Create Geographic Areas
        self.area_cairo, _ = Area.objects.get_or_create(code="CAIRO-TEST", defaults={'name': "القاهرة - اختبار", 'area_type': "governorate"})
        self.area_alex, _ = Area.objects.get_or_create(code="ALEX-TEST", defaults={'name': "الإسكندرية - اختبار", 'area_type': "governorate"})

        # Create Users
        self.superadmin_user, _ = User.objects.get_or_create(
            username="test_superadmin", defaults={
                'email': "super@erp.com", 'is_superuser': True, 'is_staff': True,
                'name': "Super Admin", 'role': self.superadmin_role
            }
        )
        self.superadmin_user.set_password("password123")
        self.superadmin_user.save()

        self.accountant_user, _ = User.objects.get_or_create(
            username="test_accountant", defaults={
                'email': "acct@erp.com", 'name': "Accountant User", 'role': self.accountant_role
            }
        )
        self.accountant_user.set_password("password123")
        self.accountant_user.save()

        self.manager_cairo, _ = User.objects.get_or_create(
            username="test_mgr_cairo", defaults={
                'email': "mgr@erp.com", 'name': "Cairo Manager", 'role': self.manager_role
            }
        )
        self.manager_cairo.set_password("password123")
        self.manager_cairo.save()
        self.manager_cairo.assigned_areas.add(self.area_cairo)

        self.rep_cairo, _ = User.objects.get_or_create(
            username="test_rep_cairo", defaults={
                'email': "repcairo@erp.com", 'name': "Cairo Rep", 'role': self.rep_role
            }
        )
        self.rep_cairo.set_password("password123")
        self.rep_cairo.save()
        self.rep_cairo.assigned_areas.add(self.area_cairo)

        self.rep_alex, _ = User.objects.get_or_create(
            username="test_rep_alex", defaults={
                'email': "repalex@erp.com", 'name': "Alex Rep", 'role': self.rep_role
            }
        )
        self.rep_alex.set_password("password123")
        self.rep_alex.save()
        self.rep_alex.assigned_areas.add(self.area_alex)

        # Ensure representatives have their designated default warehouses and treasuries
        ensure_representative_resources(self.rep_cairo, create_warehouse=True, create_treasury=True)
        ensure_representative_resources(self.rep_alex, create_warehouse=True, create_treasury=True)
        self.rep_cairo_warehouse = self.rep_cairo.get_default_warehouse()
        self.rep_alex_warehouse = self.rep_alex.get_default_warehouse()

        # Setup Product & Category
        self.category, _ = ProductCategory.objects.get_or_create(
            code="GEN-CAT-TEST", defaults={'name': "أدوية عامة اختبار"}
        )
        self.product, _ = Product.objects.get_or_create(
            sku_code="PAN-TEST-001", defaults={
                'name': "Panadol Extra Test", 'category': self.category,
                'default_purchase_cost': Decimal("40.00"), 'retail_price': Decimal("50.00")
            }
        )

        # Setup Warehouses & Vaults
        self.main_warehouse, _ = Warehouse.objects.get_or_create(
            name="مخزن القاهرة للاختبار", defaults={'area': self.area_cairo, 'is_main': True}
        )
        self.main_vault, _ = Vault.objects.get_or_create(
            name="خزينة المركز الرئيسي للاختبار", defaults={'current_balance': Decimal("100000.00")}
        )

        # Setup Contacts
        self.supplier, _ = Contact.objects.get_or_create(
            serial_num=991001, defaults={
                'name': "شركة الأدوية المتحدة للاختبار", 'contact_type': "organization",
                'is_supplier': True, 'area': self.area_cairo, 'status': "active"
            }
        )
        self.vendor_account = VendorAccount.get_or_create_for_supplier(self.supplier)

        self.customer, _ = Contact.objects.get_or_create(
            serial_num=992001, defaults={
                'name': "صيدلية النور للاختبار", 'contact_type': "organization",
                'is_customer': True, 'area': self.area_cairo, 'status': "customer",
                'credit_limit': Decimal("50000.00"), 'credit_period_days': 30
            }
        )
        self.customer_account = CustomerAccount.get_or_create_for_customer(self.customer)

        self.client = Client()

    # =========================================================================
    # 1. CONTACTS: Default Lead, Coordinates & Credit Limit Persistence
    # =========================================================================

    def test_default_contact_classification_is_lead(self):
        """Newly created contacts must default to Lead, not Customer."""
        self.client.force_login(self.superadmin_user)
        post_data = {
            'name': 'صيدلية المستقبل الجديدة',
            'contact_type': 'organization',
            'relations': ['عميل'],
            'area_id': self.area_cairo.id,
            'address_area[]': [self.area_cairo.id],
            'address_sub_area[]': ['المعادي'],
            'address_street[]': ['شارع 9'],
            'address_is_main[]': ['true'],
        }
        response = self.client.post(reverse('contact_create'), post_data)
        self.assertEqual(response.status_code, 302)

        new_contact = Contact.objects.filter(name='صيدلية المستقبل الجديدة').first()
        self.assertIsNotNone(new_contact)
        self.assertEqual(new_contact.status, 'lead')
        self.assertTrue(new_contact.is_customer)

    def test_contact_coordinates_saved_and_persisted_on_edit(self):
        """Map-based location selection must accurately save and survive subsequent edits without loss."""
        self.client.force_login(self.superadmin_user)
        lat = Decimal("30.0444220")
        lng = Decimal("31.2357110")

        post_data = {
            'name': 'مجمع عيادات الشفاء',
            'contact_type': 'organization',
            'relations': ['عميل'],
            'latitude': str(lat),
            'longitude': str(lng),
            'credit_limit': '25000.00',
            'credit_period_days': '45',
            'area_id': self.area_cairo.id,
            'address_area[]': [self.area_cairo.id],
            'address_sub_area[]': ['مدينة نصر'],
            'address_street[]': ['شارع عباس العقاد'],
            'address_is_main[]': ['true'],
        }
        self.client.post(reverse('contact_create'), post_data)
        contact = Contact.objects.filter(name='مجمع عيادات الشفاء').first()
        self.assertIsNotNone(contact)
        self.assertTrue(contact.has_saved_location)
        self.assertAlmostEqual(contact.latitude, lat, places=4)
        self.assertAlmostEqual(contact.longitude, lng, places=4)
        self.assertEqual(contact.credit_limit, Decimal("25000.00"))
        self.assertEqual(contact.credit_period_days, 45)

        # Edit contact without passing coordinates (e.g. updating phone or note)
        edit_data = {
            'name': 'مجمع عيادات الشفاء - فرع أول',
            'contact_type': 'organization',
            'relations': ['عميل'],
            'notes': 'تم تجديد العقد السنوي',
            'credit_limit': '30000.00',
            'credit_period_days': '60',
            'area_id': self.area_cairo.id,
            'address_area[]': [self.area_cairo.id],
            'address_sub_area[]': ['مدينة نصر'],
            'address_street[]': ['شارع عباس العقاد المطور'],
            'address_is_main[]': ['true'],
        }
        edit_resp = self.client.post(reverse('contact_edit', args=[contact.id]), edit_data)
        self.assertEqual(edit_resp.status_code, 302)

        contact.refresh_from_db()
        self.assertEqual(contact.name, 'مجمع عيادات الشفاء - فرع أول')
        self.assertEqual(contact.credit_limit, Decimal("30000.00"))
        self.assertEqual(contact.credit_period_days, 60)
        # Verify coordinates were preserved without loss!
        self.assertTrue(contact.has_saved_location)
        self.assertAlmostEqual(contact.latitude, lat, places=4)
        self.assertAlmostEqual(contact.longitude, lng, places=4)

    # =========================================================================
    # 2. PURCHASES: Due Dates, Lifecycle & Comprehensive Audit Logging
    # =========================================================================

    def test_purchase_order_lifecycle_and_audit_logging(self):
        """Purchase order lifecycle generates audit log events with correct previous and new states."""
        due_date = datetime.date(2026, 11, 15)
        order = PurchaseOrderService.create_order(
            supplier=self.supplier,
            target_warehouse=self.main_warehouse,
            order_date=timezone.now().date(),
            items_data=[{
                'product': self.product,
                'quantity': 100,
                'unit_price': Decimal("40.00"),
                'discount_percentage': Decimal("0.00"),
                'tax_percentage': Decimal("0.00"),
            }],
            user=self.accountant_user,
            due_date=due_date,
            notes="شحنة أدوية طارئة"
        )
        self.assertEqual(order.grand_total, Decimal("4000.00"))
        self.assertEqual(order.due_date, due_date)
        self.assertEqual(order.outstanding_balance, Decimal("4000.00"))
        self.assertFalse(order.is_paid)

        # Verify creation audit log
        create_audit = SecurityAuditLog.objects.filter(
            module="purchases", action_type="PURCHASE_ORDER_CREATED", record_id=order.id
        ).first()
        self.assertIsNotNone(create_audit)
        self.assertEqual(create_audit.actor, self.accountant_user)

        # Approve Order
        PurchaseOrderService.approve_order(order, self.superadmin_user)
        order.refresh_from_db()
        self.assertEqual(order.status, 'approved')

        approve_audit = SecurityAuditLog.objects.filter(
            module="purchases", action_type="PURCHASE_ORDER_APPROVED", record_id=order.id
        ).first()
        self.assertIsNotNone(approve_audit)
        self.assertEqual(approve_audit.actor, self.superadmin_user)

        # Stock Order in warehouse
        PurchaseOrderService.stock_order(order, self.superadmin_user)
        order.refresh_from_db()
        self.assertEqual(order.status, 'picked')

        # Invoice / Settle Order
        PurchaseOrderService.invoice_order(order, self.accountant_user)
        order.refresh_from_db()
        self.assertEqual(order.status, 'settled')

        settle_audit = SecurityAuditLog.objects.filter(
            module="purchases", action_type="PURCHASE_ORDER_SETTLED", record_id=order.id
        ).first()
        self.assertIsNotNone(settle_audit)

    # =========================================================================
    # 3. ORDER-LINKED PAYMENTS & OVERPAYMENT PREVENTION
    # =========================================================================

    def test_vendor_payment_linked_to_purchase_order(self):
        """Vendor payment linked to a specific purchase order reduces its outstanding balance."""
        po = PurchaseOrderService.create_order(
            supplier=self.supplier,
            target_warehouse=self.main_warehouse,
            order_date=timezone.now().date(),
            items_data=[{'product': self.product, 'quantity': 50, 'unit_price': Decimal("40.00")}],
            user=self.accountant_user,
            due_date=datetime.date(2026, 11, 20)
        )
        # Approve, stock, and settle
        PurchaseOrderService.approve_order(po, self.superadmin_user)
        PurchaseOrderService.stock_order(po, self.superadmin_user)
        PurchaseOrderService.invoice_order(po, self.accountant_user)
        po.refresh_from_db()
        self.assertEqual(po.outstanding_balance, Decimal("2000.00"))

        # Partial payment: 800 LE
        payment1 = TreasuryService.record_vendor_payment(
            supplier=self.supplier,
            vault=self.main_vault,
            amount=Decimal("800.00"),
            payment_method="cash",
            user=self.accountant_user,
            purchase_order=po,
            notes="دفعة أولى"
        )
        po.refresh_from_db()
        self.assertEqual(po.total_paid, Decimal("800.00"))
        self.assertEqual(po.outstanding_balance, Decimal("1200.00"))
        self.assertFalse(po.is_paid)

        # Full settlement remaining: 1200 LE
        payment2 = TreasuryService.record_vendor_payment(
            supplier=self.supplier,
            vault=self.main_vault,
            amount=Decimal("1200.00"),
            payment_method="cash",
            user=self.accountant_user,
            purchase_order=po,
            notes="تسوية كاملة"
        )
        po.refresh_from_db()
        self.assertEqual(po.total_paid, Decimal("2000.00"))
        self.assertEqual(po.outstanding_balance, Decimal("0.00"))
        self.assertTrue(po.is_paid)

    def test_vendor_payment_overpayment_rejected(self):
        """Attempting to pay more than the purchase order's outstanding balance must raise ValidationError."""
        po = PurchaseOrderService.create_order(
            supplier=self.supplier,
            target_warehouse=self.main_warehouse,
            order_date=timezone.now().date(),
            items_data=[{'product': self.product, 'quantity': 10, 'unit_price': Decimal("40.00")}],
            user=self.accountant_user
        )
        self.assertEqual(po.outstanding_balance, Decimal("400.00"))

        with self.assertRaises(ValidationError) as ctx:
            TreasuryService.record_vendor_payment(
                supplier=self.supplier,
                vault=self.main_vault,
                amount=Decimal("500.00"),  # Exceeds 400.00!
                payment_method="cash",
                user=self.accountant_user,
                purchase_order=po
            )
        self.assertIn("يتجاوز الرصيد المستحق", str(ctx.exception))

    def test_sales_collection_linked_to_sales_order(self):
        """Collections linked to a sales order correctly reduce outstanding balance and prevent overpayment."""
        due_date = datetime.date(2026, 11, 10)
        so = SalesOrderService.create_order(
            customer=self.customer,
            source_warehouse=self.rep_cairo_warehouse,
            order_date=timezone.now().date(),
            items_data=[{'product': self.product, 'quantity': 20, 'unit_price': Decimal("50.00")}],
            user=self.rep_cairo,
            due_date=due_date
        )
        self.assertEqual(so.grand_total, Decimal("1000.00"))
        self.assertEqual(so.outstanding_balance, Decimal("1000.00"))
        self.assertEqual(so.due_date, due_date)

        # Partial collection: 400 LE
        col = CollectionService.record_collection(
            customer=self.customer,
            vault=self.main_vault,
            amount=Decimal("400.00"),
            user=self.rep_cairo,
            sales_order=so,
            due_date=due_date,
            notes="دفعة نقدية"
        )
        so.refresh_from_db()
        self.assertEqual(so.total_paid, Decimal("400.00"))
        self.assertEqual(so.outstanding_balance, Decimal("600.00"))
        self.assertFalse(so.is_paid)

        # Attempting overpayment (> 600 LE) must be rejected
        with self.assertRaises(ValidationError):
            CollectionService.record_collection(
                customer=self.customer,
                vault=self.main_vault,
                amount=Decimal("700.00"),
                user=self.rep_cairo,
                sales_order=so
            )

    # =========================================================================
    # 4. SERVER-SIDE ROLE-BASED ACCESS CONTROL (RBAC) & IDOR PREVENTION
    # =========================================================================

    def test_representative_cannot_access_other_representative_order(self):
        """Representatives must strictly be restricted to their own records; IDOR is blocked."""
        # Cairo rep creates an order
        cairo_order = SalesOrderService.create_order(
            customer=self.customer,
            source_warehouse=self.rep_cairo_warehouse,
            order_date=timezone.now().date(),
            items_data=[{'product': self.product, 'quantity': 5, 'unit_price': Decimal("50.00")}],
            user=self.rep_cairo
        )

        # Alex rep logs in and attempts to access Cairo rep's order directly by ID
        self.client.force_login(self.rep_alex)
        detail_url = reverse('sales_order_detail', args=[cairo_order.pk])
        resp = self.client.get(detail_url)
        # Must be rejected (403 Forbidden)
        self.assertEqual(resp.status_code, 403)

    def test_manager_scoped_to_own_area_and_representatives(self):
        """Managers can access records in their authorized area hierarchy, but not outside areas."""
        cairo_order = SalesOrderService.create_order(
            customer=self.customer,
            source_warehouse=self.rep_cairo_warehouse,
            order_date=timezone.now().date(),
            items_data=[{'product': self.product, 'quantity': 5, 'unit_price': Decimal("50.00")}],
            user=self.rep_cairo
        )

        # Cairo manager logs in -> Can view Cairo rep's order
        self.client.force_login(self.manager_cairo)
        resp = self.client.get(reverse('sales_order_detail', args=[cairo_order.pk]))
        self.assertEqual(resp.status_code, 200)

        # Customer & Order in Alexandria
        alex_customer = Contact.objects.create(
            serial_num=3001, name="صيدلية الإسكندرية", contact_type="organization",
            is_customer=True, area=self.area_alex, status="customer"
        )
        alex_order = SalesOrderService.create_order(
            customer=alex_customer,
            source_warehouse=self.rep_alex_warehouse,
            order_date=timezone.now().date(),
            items_data=[{'product': self.product, 'quantity': 5, 'unit_price': Decimal("50.00")}],
            user=self.rep_alex
        )

        # Cairo manager attempts to access Alex order -> Must be rejected (403 Forbidden)
        resp_alex = self.client.get(reverse('sales_order_detail', args=[alex_order.pk]))
        self.assertEqual(resp_alex.status_code, 403)

    # =========================================================================
    # 5. DASHBOARD STATISTICS INTEGRATION
    # =========================================================================

    def test_dashboard_purchase_statistics_calculation(self):
        """Dashboard home_view computes accurate purchase and financial metrics matching DB state."""
        # Create an approved purchase order
        po = PurchaseOrderService.create_order(
            supplier=self.supplier,
            target_warehouse=self.main_warehouse,
            order_date=timezone.now().date(),
            items_data=[{'product': self.product, 'quantity': 25, 'unit_price': Decimal("40.00")}],
            user=self.accountant_user,
            due_date=datetime.date(2026, 10, 25)
        )
        PurchaseOrderService.approve_order(po, self.superadmin_user)

        self.client.force_login(self.superadmin_user)
        resp = self.client.get(reverse('home'), {'period': 'all'})
        self.assertEqual(resp.status_code, 200)

        # Verify purchase card exists in rendered dashboard
        content = resp.content.decode('utf-8')
        self.assertIn("أوامر الشراء", content)
        self.assertIn("المدفوع للموردين", content)
        self.assertIn("أحدث أوامر الشراء", content)
        self.assertIn(f"{po.order_number}", content)
