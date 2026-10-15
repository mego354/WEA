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
