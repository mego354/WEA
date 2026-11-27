import datetime
from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from django.core.management import call_command
from django.utils import timezone

from accounts.models import User, Role
from master_data.models import Area
from contacts.models import Contact
from catalog.models import Product, ProductCategory
from inventory.models import Warehouse, InventoryStock
from treasury.models import Vault
from activities.models import Visit, Agreement, AgreementType, VisitSampleItem
from sales.models import SalesOrder, SalesOrderItem, Collection, CustomerAccount, CustomerTransaction
from purchases.models import PurchaseOrder, PurchaseOrderItem
from reports.models import SalesTarget, CustomerCall


class ReportsHubAndSpecializedReportsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('setup_permissions')

        cls.superadmin_role = Role.objects.get(name=Role.ROLE_SUPERADMIN)
        cls.rep_role = Role.objects.get(name=Role.ROLE_REP)

        # Geographic Structure
        cls.cairo = Area.objects.create(name='القاهرة', code='CAI-REP', area_type='governorate')
        cls.nasr_city = Area.objects.create(name='مدينة نصر', code='NAS-REP', parent=cls.cairo, area_type='subarea')

        # Admin User
        cls.admin_user = User.objects.create_user(
            username='admin_reports@example.com',
            email='admin_reports@example.com',
            password='Password123!',
            role=cls.superadmin_role,
            is_superuser=True,
            is_staff=True
        )

        # Rep User
        cls.rep_user = User.objects.create_user(
            username='rep_reports@example.com',
            email='rep_reports@example.com',
            password='Password123!',
            role=cls.rep_role,
            name='خالد مندوب'
        )
        cls.rep_user.assigned_areas.add(cls.nasr_city)

        # Customer & Account
        cls.customer = Contact.objects.create(
            name='مستشفى الشفاء',
            status='customer',
            account_type='hospital',
            area=cls.cairo,
            brick=cls.nasr_city,
            created_by=cls.admin_user
        )
        cls.customer.assigned_team.add(cls.rep_user)

        cls.account, _ = CustomerAccount.objects.get_or_create(
            customer=cls.customer,
            defaults={'credit_limit': Decimal('50000.00'), 'credit_period_days': 30}
        )

        # Warehouse & Vault
        cls.warehouse = Warehouse.objects.create(name='مخزن مدينة نصر', code='WH-NAS-REP')
        cls.vault = Vault.objects.create(name='خزينة الشفاء', vault_type='cash')

        # Product & Stock
        cls.cat = ProductCategory.objects.create(name='مستحضرات طبية')
        cls.product = Product.objects.create(
            name='أوجمنتين 1 جم',
            sku_code='AUG-1G-REP',
            category=cls.cat,
            retail_price=Decimal('90.00'),
            is_active=True
        )
        cls.stock = InventoryStock.objects.create(
            warehouse=cls.warehouse,
            product=cls.product,
            qty_on_hand=Decimal('100.00'),
            qty_reserved=Decimal('10.00'),
            product_cost=Decimal('50.00')
        )

        cls.today = timezone.now().date()

        # Customer Transaction (Debit Invoice)
        CustomerTransaction.objects.create(
            serial=9901,
            account=cls.account,
            transaction_type='debit',
            reason='sales',
            transaction_date=cls.today - datetime.timedelta(days=45),
            due_date=cls.today - datetime.timedelta(days=15),
            debit=Decimal('1800.00'),
            credit=Decimal('0.00'),
            running_balance=Decimal('1800.00'),
            description='فاتورة مبيعات مستحقة',
            created_by=cls.admin_user
        )
        cls.account.current_balance = Decimal('1800.00')
        cls.account.overdue_balance = Decimal('1800.00')
        cls.account.save()

        # Visit & Sample
        cls.visit = Visit.objects.create(
            owner=cls.rep_user,
            contact=cls.customer,
            date=cls.today,
            status='finished',
            location_verified=True,
            created_by=cls.rep_user
        )
        VisitSampleItem.objects.create(
            visit=cls.visit,
            product=cls.product,
            quantity=5
        )

        # Agreement
        cls.agr_type = AgreementType.objects.create(name='علمي', display_name_ar='اتفاقية علمية')
        cls.agreement = Agreement.objects.create(
            title='اتفاقية توريد شهرية',
            customer=cls.customer,
            type=cls.agr_type,
            amount=Decimal('5000.00'),
            date=cls.today,
            created_by=cls.rep_user
        )

        # Sales Order
        cls.order = SalesOrder.objects.create(
            customer=cls.customer,
            source_warehouse=cls.warehouse,
            order_date=cls.today,
            status='delivered',
            subtotal=Decimal('1800.00'),
            custom_discount_percentage=Decimal('10.00'),
            custom_discount_amount=Decimal('180.00'),
            grand_total=Decimal('1620.00'),
            created_by=cls.rep_user
        )
        SalesOrderItem.objects.create(
            order=cls.order,
            product=cls.product,
            quantity=20,
            unit_price=Decimal('90.00')
        )

        # Collection
        cls.col = Collection.objects.create(
            customer=cls.customer,
            vault=cls.vault,
            collection_date=cls.today,
            amount=Decimal('1000.00'),
            payment_method='cash',
            created_by=cls.rep_user
        )

        # Customer Call
        cls.call = CustomerCall.objects.create(
            contact=cls.customer,
            performed_by=cls.rep_user,
            call_date=cls.today,
            duration_minutes=12,
            purpose='sales_pitch',
            outcome='completed',
            notes='تم الاتفاق على توريد الدفعة القادمة'
        )

        # Sales Target
        cls.target = SalesTarget.objects.create(
            user=cls.rep_user,
            year=cls.today.year,
            month=cls.today.month,
            target_sales_amount=Decimal('15000.00'),
            target_collections_amount=Decimal('12000.00'),
            target_visits_count=60
        )

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.admin_user)

    def test_reports_hub(self):
        url = reverse('reports_hub')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'reports/reports_hub.html')
        self.assertIn('reports', response.context)
        self.assertEqual(len(response.context['reports']), 8)

    def test_report_ar_aging(self):
        url = reverse('report_ar_aging')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'reports/report_ar_aging.html')
        self.assertIn('rows', response.context)
        self.assertIn('summary', response.context)

        # Print View
        url_print = reverse('report_ar_aging_print')
        res_print = self.client.get(url_print)
        self.assertEqual(res_print.status_code, 200)

        # Export View
        url_export = reverse('report_ar_aging_export')
        res_export = self.client.get(url_export)
        self.assertEqual(res_export.status_code, 200)
        self.assertEqual(res_export['Content-Type'], 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

    def test_report_trial_balance(self):
        url = reverse('report_trial_balance')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'reports/report_trial_balance.html')

        # Print View
        res_print = self.client.get(reverse('report_trial_balance_print'))
        self.assertEqual(res_print.status_code, 200)

        # Export View
        res_export = self.client.get(reverse('report_trial_balance_export'))
        self.assertEqual(res_export.status_code, 200)
        self.assertEqual(res_export['Content-Type'], 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

    def test_report_agreements_roi(self):
        url = reverse('report_agreements_roi')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'reports/report_agreements_roi.html')

        res_export = self.client.get(reverse('report_agreements_roi_export'))
        self.assertEqual(res_export.status_code, 200)
        self.assertEqual(res_export['Content-Type'], 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

    def test_report_customer_360(self):
        url = reverse('report_customer_360')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'reports/report_customer_360.html')

        res_export = self.client.get(reverse('report_customer_360_export'))
        self.assertEqual(res_export.status_code, 200)
        self.assertEqual(res_export['Content-Type'], 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

    def test_report_delivery_stock(self):
        url = reverse('report_delivery_stock')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'reports/report_delivery_stock.html')

        res_export = self.client.get(reverse('report_delivery_stock_export'))
        self.assertEqual(res_export.status_code, 200)
        self.assertEqual(res_export['Content-Type'], 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

    def test_report_net_sales(self):
        url = reverse('report_net_sales')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'reports/report_net_sales.html')

        res_export = self.client.get(reverse('report_net_sales_export'))
        self.assertEqual(res_export.status_code, 200)
        self.assertEqual(res_export['Content-Type'], 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

    def test_report_item_purchases(self):
        url = reverse('report_item_purchases')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'reports/report_item_purchases.html')

        res_export = self.client.get(reverse('report_item_purchases_export'))
        self.assertEqual(res_export.status_code, 200)
        self.assertEqual(res_export['Content-Type'], 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

    def test_report_item_sales_by_customer(self):
        url = reverse('report_item_sales_by_customer')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'reports/report_item_sales_by_customer.html')

        res_export = self.client.get(reverse('report_item_sales_by_customer_export'))
        self.assertEqual(res_export.status_code, 200)
        self.assertEqual(res_export['Content-Type'], 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

    def test_report_delivery_stock_warehouse_filter_does_not_crash(self):
        """AUD-017: Filtering delivery stock report by warehouse_id uses source_warehouse_id (no FieldError)."""
        from inventory.models import Warehouse
        wh = Warehouse.objects.first()
        wh_id = wh.id if wh else 1
        url = f"{reverse('report_delivery_stock')}?warehouse_id={wh_id}"
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)

        exp = self.client.get(f"{reverse('report_delivery_stock_export')}?warehouse_id={wh_id}")
        self.assertEqual(exp.status_code, 200)
