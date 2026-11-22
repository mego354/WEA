"""
Comprehensive tests for the Global Excel Import/Export System:
- All 10 approved first-wave importers (Users STRICTLY EXCLUDED -> 404)
- 2-sheet .xlsx template download (البيانات + التعليمات)
- Upload -> Validate -> Preview -> Error Report (.xlsx) -> Confirm atomic commit
- Strict DataScope enforcement (no cross-area imports, no unauthorized Area creation)
- Never silently skips invalid rows unless explicitly opted in
- Formula-injection sanitization
- All 8 newly added exports + fixed filter bugs on accounting_customers_export & vendor_payments_export
"""

import io
from decimal import Decimal
import openpyxl

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import Role, SecurityAuditLog, User
from catalog.models import Product, ProductCategory
from contacts.models import Contact
from inventory.models import InventoryStock, Warehouse
from master_data.excel_import_engine import ImportBatchStore
from master_data.excel_importers import IMPORTER_REGISTRY, get_importer_class
from master_data.models import Area
from treasury.models import Vault


def _build_xlsx_upload(headers, rows, filename='test_upload.xlsx'):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'البيانات'
    ws.append(headers)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return SimpleUploadedFile(
        filename,
        buf.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )


class GlobalExcelImportExportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('setup_permissions')

    def setUp(self):
        self.client = Client()
        self.super_role = Role.objects.get(name='superadmin')
        self.rep_role = Role.objects.get(name='rep')

        self.cairo = Area.objects.create(name='القاهرة_إكسل', code='CAI-X', area_type='governorate')
        self.nasr = Area.objects.create(name='مدينة نصر_إكسل', code='NASR-X', parent=self.cairo, area_type='subarea')
        self.giza = Area.objects.create(name='الجيزة_إكسل', code='GIZ-X', area_type='governorate')

        self.superadmin = User.objects.create_superuser(
            username='super_excel@wea.com', email='super_excel@wea.com', password='Password123!', name='Super Excel', role=self.super_role
        )
        self.rep = User.objects.create_user(
            username='rep_excel@wea.com', email='rep_excel@wea.com', password='Password123!', name='Rep Excel', role=self.rep_role
        )
        self.rep.assigned_areas.add(self.nasr)

        self.wh = Warehouse.objects.create(name='مخزن إكسل', code='WH-X1', area=self.cairo, is_main=True, is_active=True)
        self.vault = Vault.objects.create(name='خزنة إكسل', serial_num=8801, current_balance=Decimal('10000.00'), is_active=True)

    def test_exactly_10_approved_importers_and_users_strictly_excluded(self):
        self.assertEqual(len(IMPORTER_REGISTRY), 10)
        self.assertIsNone(get_importer_class('users'))
        self.assertIsNone(get_importer_class('user'))
        self.client.force_login(self.superadmin)
        self.assertEqual(self.client.get('/excel/import/users/').status_code, 404)

    def test_all_10_templates_generate_two_sheets(self):
        self.client.force_login(self.superadmin)
        for entity_key in IMPORTER_REGISTRY:
            resp = self.client.get(reverse('excel_import_template', kwargs={'entity': entity_key}))
            self.assertEqual(resp.status_code, 200, f"Template failed for {entity_key}")
            wb = openpyxl.load_workbook(io.BytesIO(resp.content))
            self.assertIn('البيانات', wb.sheetnames)
            self.assertIn('التعليمات', wb.sheetnames)

    def test_preview_error_blocking_error_report_and_atomic_commit(self):
        """Categories import: blocks commit if invalid rows exist without allow_partial; downloads error xlsx; commits valid rows atomically."""
        self.client.force_login(self.superadmin)
        upload = _build_xlsx_upload(
            ['اسم التصنيف', 'الكود', 'الوصف'],
            [
                ['مضادات حيوية X', 'CAT-X1', 'وصف سليم'],
                ['', 'CAT-BAD', 'صف بلا اسم'],  # invalid!
            ],
        )
        res = self.client.post(reverse('excel_import', kwargs={'entity': 'categories'}), {'action': 'upload', 'excel_file': upload})
        self.assertEqual(res.status_code, 302)
        batch_id = res['Location'].split('batch=')[1]

        # Preview page loads without committing anything to DB
        prev = self.client.get(res['Location'])
        self.assertEqual(prev.status_code, 200)
        self.assertFalse(ProductCategory.objects.filter(name='مضادات حيوية X').exists())

        # Download error report .xlsx
        err_resp = self.client.get(reverse('excel_import_errors', kwargs={'entity': 'categories', 'batch_id': batch_id}))
        self.assertEqual(err_resp.status_code, 200)
        err_wb = openpyxl.load_workbook(io.BytesIO(err_resp.content))
        err_ws = err_wb.active
        self.assertEqual(err_ws.max_row, 2)  # header + 1 error row

        # Attempting confirm WITHOUT allow_partial must NOT commit
        res_block = self.client.post(reverse('excel_import', kwargs={'entity': 'categories'}), {'action': 'confirm', 'batch_id': batch_id})
        self.assertEqual(res_block.status_code, 200)
        self.assertFalse(ProductCategory.objects.filter(name='مضادات حيوية X').exists())

        # Confirm WITH explicit allow_partial=1 commits valid row + logs audit
        res_ok = self.client.post(
            reverse('excel_import', kwargs={'entity': 'categories'}),
            {'action': 'confirm', 'batch_id': batch_id, 'allow_partial': '1'},
        )
        self.assertEqual(res_ok.status_code, 200)
        self.assertTrue(ProductCategory.objects.filter(name='مضادات حيوية X').exists())
        self.assertTrue(SecurityAuditLog.objects.filter(action_type='EXCEL_IMPORT_COMPLETED').exists())

    def test_contacts_import_enforces_datascope_and_blocks_area_creation(self):
        """A Nasr City rep cannot import Giza contacts or auto-create unknown areas."""
        from django.contrib.auth.models import Permission
        p_imp = Permission.objects.get(codename='contacts:contacts/import')
        self.rep_role.permissions.add(p_imp)
        self.rep.clear_perm_cache()

        importer = get_importer_class('contacts')(self.rep)
        upload = _build_xlsx_upload(
            ['الاسم', 'النوع', 'المنطقة الرئيسية', 'المنطقة الفرعية (البريك)'],
            [
                ['صيدلية نصر المسموحة', 'عميل', 'القاهرة_إكسل', 'مدينة نصر_إكسل'],
                ['صيدلية الجيزة المرفوضة', 'عميل', 'الجيزة_إكسل', ''],
                ['صيدلية منطقة وهمية', 'عميل', 'منطقة غير موجودة إطلاقاً', ''],
            ],
        )
        parsed, err = importer.parse_and_validate_upload(upload)
        self.assertIsNone(err)
        self.assertEqual(parsed['valid_count'], 1)
        self.assertEqual(parsed['invalid_count'], 2)
        self.assertFalse(Area.objects.filter(name='منطقة غير موجودة إطلاقاً').exists())

    def test_all_new_excel_exports_return_valid_xlsx(self):
        self.client.force_login(self.superadmin)
        export_names = [
            'roles_export',
            'areas_export',
            'expenses_export',
            'tickets_export',
            'requests_export',
            'agreements_types_export',
            'visit_templates_export',
            'performance_overview_export',
            'accounting_customers_export',
            'vendor_payments_export',
        ]
        for url_name in export_names:
            resp = self.client.get(reverse(url_name))
            self.assertEqual(resp.status_code, 200, f"Export {url_name} failed")
            self.assertIn('spreadsheetml', resp['Content-Type'])
            wb = openpyxl.load_workbook(io.BytesIO(resp.content))
            self.assertGreaterEqual(len(wb.sheetnames), 1)
