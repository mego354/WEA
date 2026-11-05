from decimal import Decimal
import io
import openpyxl
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from contacts.models import Contact
from treasury.models import Vault, VendorPayment

User = get_user_model()


class TreasuryExcelExportTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(
            email='treasuryadmin@weapharma.com',
            username='treasuryadmin@weapharma.com',
            password='Password123!',
            first_name='Treasury',
            last_name='Admin'
        )
        self.client = Client()
        self.client.login(username='treasuryadmin@weapharma.com', password='Password123!')

        self.vault = Vault.objects.create(
            name='الخزينة الرئيسية - المقر',
            vault_type='cash',
            current_balance=Decimal('500000.00'),
            is_active=True
        )
        self.supplier = Contact.objects.create(
            serial_num=7701,
            name='شركة فارما للتوزيع الدوائي',
            is_supplier=True,
            phone='01122334455'
        )
        self.payment = VendorPayment.objects.create(
            supplier=self.supplier,
            vault=self.vault,
            amount=Decimal('15000.00'),
            payment_method='cash',
            status='cleared',
            reference_number='REF-PAY-2026',
            created_by=self.user
        )

    def test_vendor_payments_export_excel(self):
        response = self.client.get(reverse('vendor_payments_export'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        self.assertIn('.xlsx', response['Content-Disposition'])

        wb = openpyxl.load_workbook(io.BytesIO(response.content))
        ws = wb.active
        self.assertTrue(ws.sheet_view.rightToLeft)
        found = any('شركة فارما للتوزيع' in str(cell.value) for row in ws.iter_rows() for cell in row)
        self.assertTrue(found)


class VaultDetailViewTestCase(TestCase):
    def setUp(self):
        self.super_user = User.objects.create_superuser(
            email='vaultsuper@weapharma.com',
            username='vaultsuper@weapharma.com',
            password='Password123!',
            first_name='Super',
            last_name='User'
        )
        self.regular_user = User.objects.create_user(
            email='regular@weapharma.com',
            username='regular@weapharma.com',
            password='Password123!',
            first_name='Regular',
            last_name='User'
        )
        self.client = Client()
        self.vault = Vault.objects.create(
            name='خزينة فرع القاهرة الرئيسية',
            vault_type='cash',
            current_balance=Decimal('1250000.00'),
            is_active=True
        )

    def test_vault_detail_view_success(self):
        self.client.login(username='vaultsuper@weapharma.com', password='Password123!')
        url = reverse('vault_detail', kwargs={'pk': self.vault.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'خزينة فرع القاهرة الرئيسية')
        self.assertContains(response, str(self.vault.serial_num))
        self.assertContains(response, '1,250,000')

    def test_vault_detail_permission_denied_for_unauthorized_user(self):
        self.client.login(username='regular@weapharma.com', password='Password123!')
        url = reverse('vault_detail', kwargs={'pk': self.vault.pk})
        response = self.client.get(url)
        # Should be forbidden 403 or redirect
        self.assertIn(response.status_code, [302, 403])

    def test_vaults_list_has_clickable_links_and_detail_button(self):
        self.client.login(username='vaultsuper@weapharma.com', password='Password123!')
        response = self.client.get(reverse('vaults_list'))
        self.assertEqual(response.status_code, 200)
        detail_url = reverse('vault_detail', kwargs={'pk': self.vault.pk})
        self.assertContains(response, detail_url)
        self.assertContains(response, 'تفاصيل')

