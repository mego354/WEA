import datetime
from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission

from accounts.models import Role
from master_data.models import Area, LocationSettings, SalesSettings, PurchaseSettings
from contacts.models import Contact
from catalog.models import Product, ProductCategory
from inventory.models import Warehouse
from activities.models import VisitTemplate, PlannedVisitDay, PlannedVisitItem, Visit, Agreement, AgreementType
from sales.models import SalesOrder, SalesOrderItem
from sales.services import SalesOrderService
from purchases.models import PurchaseOrder, PurchaseOrderItem
from purchases.services import PurchaseOrderService

User = get_user_model()


class ComprehensiveUserWorkflowsTestCase(TestCase):
    """
    Full end-to-end test suite for user workflows:
    - Different kinds of users: Medical Rep, Area Manager, Accountant.
    - Planned and unplanned visits.
    - Single and double visits (doubled=True/False).
    - Creation, Manager Approval, Rep Completion flow.
    - Settings-controlled permissions and require_manager_approval for visits, sales, purchases, and agreements.
    """

    def setUp(self):
        self.client = Client()

        # 1. Settings Setup
        self.loc_settings = LocationSettings.get_settings()
        self.loc_settings.allow_all_users_to_create_visits = True
        self.loc_settings.require_manager_approval_for_visits = True
        self.loc_settings.allow_all_users_to_create_agreements = True
        self.loc_settings.require_manager_approval_for_agreements = True
        self.loc_settings.verify_visits = False
        self.loc_settings.save()

        self.sales_settings = SalesSettings.get_settings()
        self.sales_settings.allow_all_users_to_create = True
        self.sales_settings.require_manager_approval = True
        self.sales_settings.save()

        self.purchase_settings = PurchaseSettings.get_settings()
        self.purchase_settings.allow_all_users_to_create = True
        self.purchase_settings.require_manager_approval = True
        self.purchase_settings.save()

        # 2. Roles Setup
        self.manager_role = Role.objects.create(
            name='area_manager',
            display_name='مدير منطقة',
            is_area_manager=True
        )
        self.rep_role = Role.objects.create(
            name='sales_rep',
            display_name='مندوب مبيعات',
            is_rep=True
        )
        self.accountant_role = Role.objects.create(
            name='accountant',
            display_name='محاسب',
            is_rep=False,
            is_area_manager=False
        )

        all_perms = Permission.objects.filter(
            codename__in=[
                'activities:visits/list', 'activities:visits/view', 'activities:visits/create', 'activities:visits/edit',
                'activities:visits/approve', 'activities:planned/list', 'activities:planned/manage',
                'activities:agreements/list', 'activities:agreements/view', 'activities:agreements/create', 'activities:agreements/approve',
                'sales:orders/list', 'sales:orders/view', 'sales:orders/create', 'sales:orders/approve',
                'purchases:orders/list', 'purchases:orders/view', 'purchases:orders/create', 'purchases:orders/approve',
                'module:activities', 'module:sales', 'module:contacts', 'module:purchases', 'module:treasury'
            ]
        )
        self.manager_role.permissions.set(all_perms)
        self.rep_role.permissions.set(
            all_perms.exclude(codename__in=['activities:visits/approve', 'sales:orders/approve', 'purchases:orders/approve', 'activities:agreements/approve'])
        )
        # Accountant role has accounting/treasury perms only, no visit/sales creation perms
        self.accountant_role.permissions.set(
            Permission.objects.filter(codename__in=['module:treasury', 'module:contacts'])
        )

        # 3. Areas Hierarchy
        self.region_cairo = Area.objects.create(code='CAI', name='القاهرة', area_type='governorate')
        self.sub_nasr_city = Area.objects.create(code='CAI-NASR', name='مدينة نصر', area_type='subarea', parent=self.region_cairo)
        self.sub_maadi = Area.objects.create(code='CAI-MAADI', name='المعادي', area_type='subarea', parent=self.region_cairo)

        self.region_alex = Area.objects.create(code='ALX', name='الإسكندرية', area_type='governorate')
        self.sub_smouha = Area.objects.create(code='ALX-SMO', name='سموحة', area_type='subarea', parent=self.region_alex)

        # 4. Users
        self.manager_cairo = User.objects.create_user(
            username='mgr_cairo', email='mgr_cairo@example.com', password='Password123!',
            first_name='مدير', last_name='القاهرة', role=self.manager_role
        )
        self.manager_cairo.assigned_areas.add(self.region_cairo)

        self.manager_alex = User.objects.create_user(
            username='mgr_alex', email='mgr_alex@example.com', password='Password123!',
            first_name='مدير', last_name='الإسكندرية', role=self.manager_role
        )
        self.manager_alex.assigned_areas.add(self.region_alex)

        self.rep_cairo = User.objects.create_user(
            username='rep_cairo', email='rep_cairo@example.com', password='Password123!',
            first_name='مندوب', last_name='القاهرة', role=self.rep_role
        )
        self.rep_cairo.assigned_areas.add(self.sub_nasr_city)

        self.accountant_user = User.objects.create_user(
            username='acc_user', email='acc@example.com', password='Password123!',
            first_name='محمود', last_name='محاسب', role=self.accountant_role
        )
        self.accountant_user.assigned_areas.add(self.sub_nasr_city)

        # 5. Contacts (Customers & Suppliers)
        self.customer_cairo = Contact.objects.create(
            name='صيدلية الشفاء مدينة نصر', code='CUST-001', account_type='Pharmacy',
            area=self.sub_nasr_city, is_customer=True, status='customer'
        )
        self.customer_maadi = Contact.objects.create(
            name='مستشفى المعادي الدولي', code='CUST-002', account_type='Hospital',
            area=self.sub_maadi, is_customer=True, status='customer'
        )
        self.customer_alex = Contact.objects.create(
            name='صيدلية سموحة الإسكندرية', code='CUST-003', account_type='Pharmacy',
            area=self.sub_smouha, is_customer=True, status='customer'
        )
        self.supplier_cairo = Contact.objects.create(
            name='شركة الأدوية المتحدة', code='SUPP-001', is_supplier=True, status='supplier',
            area=self.sub_nasr_city
        )

        # 6. Inventory & Catalog
        self.cat = ProductCategory.objects.create(name='أدوية عامة', code='GEN-CAT')
        self.product = Product.objects.create(
            name='بانادول إكسترا 500 ملجم', sku_code='PAN-01', retail_price=50.00, default_purchase_cost=35.00, category=self.cat
        )
        self.warehouse = Warehouse.objects.create(name='المخزن الرئيسي بالقاهرة', code='WH-CAI')

        # 7. Visit Templates & Agreement Type
        self.general_template = VisitTemplate.objects.create(
            name='general_field_visit',
            display_name_ar='زيارة ميدانية عامة',
            active=True
        )
        self.agreement_type = AgreementType.objects.create(
            name='اتفاقية توريد سنوية'
        )

    # =========================================================================
    # Test 1: Rep creates Unplanned Single Visit -> Manager Approves -> Rep Completes
    # =========================================================================
    def test_rep_unplanned_single_visit_full_flow(self):
        """
        Flow:
        1. Rep creates unplanned single visit (doubled=False) in their area.
        2. Visit starts in approval_status='pending' because rep is not a manager.
        3. Area manager reviews and approves visit in visit detail page.
        4. Rep completes visit (status='finished').
        5. Prior manager approval is preserved (approval_status remains 'approved').
        6. Visit can now be sent to agenda.
        """
        # Step 1: Rep logs in and creates unplanned single visit
        self.client.login(username='rep_cairo', password='Password123!')
        res_create = self.client.post(reverse('visit_create'), {
            'contact': self.customer_cairo.id,
            'template': self.general_template.id,
            'date': timezone.now().strftime('%Y-%m-%d'),
            'doubled': '',  # Single visit (unchecked)
            'is_successful': 'on',
            'feedback': 'مناقشة طلبيات الشهر الجديد مع صيدلية الشفاء',
        })
        self.assertEqual(res_create.status_code, 302)
        visit = Visit.objects.filter(contact=self.customer_cairo, owner=self.rep_cairo).first()
        self.assertIsNotNone(visit)
        self.assertFalse(visit.is_planned)
        self.assertFalse(visit.doubled, "Must be recorded as a single visit")
        self.assertEqual(visit.status, 'started')
        self.assertEqual(visit.approval_status, 'pending', "Must require manager approval for non-manager rep")

        # Step 2: Rep tries to send unapproved visit to agenda -> MUST FAIL
        res_agenda_unapproved = self.client.post(reverse('visit_action', args=[visit.pk, 'send_to_agenda']))
        self.assertEqual(visit.approval_status, 'pending')
        # Agenda should not have this item
        self.assertFalse(PlannedVisitItem.objects.filter(visit=visit).exists())

        # Step 3: Area Manager logs in and approves the visit
        self.client.logout()
        self.client.login(username='mgr_cairo', password='Password123!')
        res_approve = self.client.post(reverse('visit_action', args=[visit.pk, 'manage_status']), {
            'approval_status': 'approved',
            'approval_notes': 'معتمد من مدير منطقة القاهرة'
        })
        self.assertEqual(res_approve.status_code, 302)
        visit.refresh_from_db()
        self.assertEqual(visit.approval_status, 'approved', "Manager of the area successfully approved the visit")
        self.assertEqual(visit.approved_by, self.manager_cairo)
        self.assertIsNotNone(visit.approved_at)

        # Step 4: Rep logs in and completes the visit
        self.client.logout()
        self.client.login(username='rep_cairo', password='Password123!')
        res_complete = self.client.post(reverse('visit_detail', args=[visit.pk]), {
            'action': 'complete',
            'visit_outcome': 'successful',
            'feedback': 'تم إنهاء الزيارة بنجاح والاتفاق على التوريد',
        })
        self.assertEqual(res_complete.status_code, 302)
        visit.refresh_from_db()
        self.assertEqual(visit.status, 'finished', "Visit status transitioned to finished")
        self.assertEqual(visit.approval_status, 'approved', "Approval status must remain approved after completion")
        self.assertFalse(visit.doubled)

        # Step 5: Send approved visit to agenda -> MUST SUCCEED
        res_agenda = self.client.post(reverse('visit_action', args=[visit.pk, 'send_to_agenda']))
        self.assertEqual(res_agenda.status_code, 302)
        item = PlannedVisitItem.objects.filter(visit=visit).first()
        self.assertIsNotNone(item, "Visit was successfully dispatched to agenda after approval")
        self.assertTrue(item.is_executed)

    # =========================================================================
    # Test 2: Rep creates Unplanned Double Visit -> Manager Approves -> Rep Completes
    # =========================================================================
    def test_rep_unplanned_double_visit_full_flow(self):
        """
        Flow:
        1. Rep creates double visit (doubled=True) for coaching/joint visit.
        2. Visit starts in approval_status='pending', doubled=True.
        3. Manager approves the double visit.
        4. Rep completes the double visit.
        5. Double flag and approved status are preserved.
        """
        self.client.login(username='rep_cairo', password='Password123!')
        res = self.client.post(reverse('visit_create'), {
            'contact': self.customer_cairo.id,
            'template': self.general_template.id,
            'date': timezone.now().strftime('%Y-%m-%d'),
            'doubled': 'on',  # Double visit checked
            'is_successful': 'on',
            'feedback': 'زيارة مشتركة ومرافقة ميدانية مع الإدارة',
        })
        self.assertEqual(res.status_code, 302)
        visit = Visit.objects.filter(contact=self.customer_cairo, owner=self.rep_cairo, doubled=True).first()
        self.assertIsNotNone(visit)
        self.assertTrue(visit.doubled, "Must be recorded as a double visit")
        self.assertEqual(visit.approval_status, 'pending')

        # Manager approves
        self.client.logout()
        self.client.login(username='mgr_cairo', password='Password123!')
        self.client.post(reverse('visit_action', args=[visit.pk, 'manage_status']), {
            'approval_status': 'approved',
            'approval_notes': 'اعتماد الزيارة المزدوجة'
        })
        visit.refresh_from_db()
        self.assertEqual(visit.approval_status, 'approved')

        # Rep completes
        self.client.logout()
        self.client.login(username='rep_cairo', password='Password123!')
        self.client.post(reverse('visit_detail', args=[visit.pk]), {
            'action': 'complete',
            'visit_outcome': 'successful',
        })
        visit.refresh_from_db()
        self.assertEqual(visit.status, 'finished')
        self.assertEqual(visit.approval_status, 'approved')
        self.assertTrue(visit.doubled, "Double visit flag must remain True upon completion")

    # =========================================================================
    # Test 3: Rep Planned Visit Flow (Plan Item -> Execute -> Manager Approves -> Complete)
    # =========================================================================
    def test_rep_planned_visit_flow(self):
        """
        Flow:
        1. Rep plans a visit via planned_visit_add_item for their area.
        2. Rep executes the planned visit via planned_visit_item_execute.
        3. Visit is created with is_planned=True and approval_status='pending'.
        4. Manager of the same area approves the visit.
        5. Rep completes the planned visit -> finished and approved.
        """
        self.client.login(username='rep_cairo', password='Password123!')
        today_str = timezone.now().strftime('%Y-%m-%d')

        # 1. Add item to plan
        res_plan = self.client.post(reverse('planned_visit_add_item'), {
            'assignee_id': self.rep_cairo.id,
            'date': today_str,
            'contact_id': self.customer_cairo.id,
            'template_id': self.general_template.id,
            'notes': 'زيارة مجدولة ضمن الخطة الأسبوعية'
        })
        self.assertEqual(res_plan.status_code, 302)
        plan_item = PlannedVisitItem.objects.filter(contact=self.customer_cairo, plan_day__assignee=self.rep_cairo).first()
        self.assertIsNotNone(plan_item)

        # 2. Execute planned item
        res_exec = self.client.post(reverse('visit_create'), {
            'planned_item_id': plan_item.pk,
            'contact': self.customer_cairo.id,
            'template': self.general_template.id,
            'date': today_str,
            'is_successful': 'on',
        })
        self.assertEqual(res_exec.status_code, 302)
        plan_item.refresh_from_db()
        self.assertTrue(plan_item.is_executed)
        visit = plan_item.visit
        self.assertIsNotNone(visit)
        self.assertTrue(visit.is_planned)
        self.assertEqual(visit.approval_status, 'pending')

        # 3. Manager approves
        self.client.logout()
        self.client.login(username='mgr_cairo', password='Password123!')
        self.client.post(reverse('visit_action', args=[visit.pk, 'manage_status']), {
            'approval_status': 'approved',
            'approval_notes': 'معتمد'
        })
        visit.refresh_from_db()
        self.assertEqual(visit.approval_status, 'approved')

        # 4. Rep completes
        self.client.logout()
        self.client.login(username='rep_cairo', password='Password123!')
        self.client.post(reverse('visit_detail', args=[visit.pk]), {
            'action': 'complete',
            'visit_outcome': 'successful',
        })
        visit.refresh_from_db()
        self.assertEqual(visit.status, 'finished')
        self.assertEqual(visit.approval_status, 'approved')
        self.assertTrue(visit.is_planned)

    # =========================================================================
    # Test 4: Manager Created Visit Auto-Approved (No Manager Approval Required)
    # =========================================================================
    def test_manager_created_visit_auto_approved(self):
        """When an Area Manager or executive creates a visit, approval is auto-granted."""
        self.client.login(username='mgr_cairo', password='Password123!')
        res = self.client.post(reverse('visit_create'), {
            'contact': self.customer_cairo.id,
            'template': self.general_template.id,
            'date': timezone.now().strftime('%Y-%m-%d'),
            'is_successful': 'on',
            'feedback': 'زيارة تفقدية من مدير المنطقة',
        })
        self.assertEqual(res.status_code, 302)
        visit = Visit.objects.filter(contact=self.customer_cairo, owner=self.manager_cairo).first()
        self.assertIsNotNone(visit)
        self.assertEqual(visit.approval_status, 'approved', "Manager creation must auto-approve")
        self.assertEqual(visit.approved_by, self.manager_cairo)

    # =========================================================================
    # Test 5: Accountant Can Create Visits When Setting Enabled
    # =========================================================================
    def test_accountant_user_can_create_and_complete_visit(self):
        """
        'all kind of users can make a visit either planned or not'
        Accountant user (without rep permissions) can create visit because
        allow_all_users_to_create_visits is True in settings.
        """
        self.client.login(username='acc_user', password='Password123!')
        res = self.client.post(reverse('visit_create'), {
            'contact': self.customer_cairo.id,
            'template': self.general_template.id,
            'date': timezone.now().strftime('%Y-%m-%d'),
            'is_successful': 'on',
            'feedback': 'زيارة ميدانية لمطابقة أرصدة العميل',
        })
        self.assertEqual(res.status_code, 302)
        visit = Visit.objects.filter(contact=self.customer_cairo, owner=self.accountant_user).first()
        self.assertIsNotNone(visit)
        self.assertEqual(visit.approval_status, 'pending', "Accountant is non-manager so approval is required")

        # Manager approves
        self.client.logout()
        self.client.login(username='mgr_cairo', password='Password123!')
        self.client.post(reverse('visit_action', args=[visit.pk, 'manage_status']), {
            'approval_status': 'approved',
            'approval_notes': 'موافق على زيارة المحاسب'
        })
        visit.refresh_from_db()
        self.assertEqual(visit.approval_status, 'approved')

        # Accountant completes
        self.client.logout()
        self.client.login(username='acc_user', password='Password123!')
        self.client.post(reverse('visit_detail', args=[visit.pk]), {
            'action': 'complete',
            'visit_outcome': 'successful',
        })
        visit.refresh_from_db()
        self.assertEqual(visit.status, 'finished')
        self.assertEqual(visit.approval_status, 'approved')

    # =========================================================================
    # Test 6: Settings Toggle - require_manager_approval_for_visits=False Auto-Approves
    # =========================================================================
    def test_require_manager_approval_disabled_auto_approves_for_all(self):
        """When require_manager_approval_for_visits is turned OFF in settings, all users auto-approve."""
        self.loc_settings.require_manager_approval_for_visits = False
        self.loc_settings.save()

        self.client.login(username='rep_cairo', password='Password123!')
        res = self.client.post(reverse('visit_create'), {
            'contact': self.customer_cairo.id,
            'template': self.general_template.id,
            'date': timezone.now().strftime('%Y-%m-%d'),
            'is_successful': 'on',
        })
        self.assertEqual(res.status_code, 302)
        visit = Visit.objects.filter(contact=self.customer_cairo, owner=self.rep_cairo).order_by('-id').first()
        self.assertEqual(visit.approval_status, 'approved', "Must auto-approve when require_manager_approval is False")

    # =========================================================================
    # Test 7: Universal Purchases, Sales, and Agreements Approval Workflows
    # =========================================================================
    def test_sales_purchases_agreements_approval_by_role(self):
        """
        Verify settings-controlled creation and require_manager_approval for:
        - Sales Orders
        - Purchase Orders
        - Agreements
        """
        # A. Sales Orders
        # 1. Rep creates Sales Order -> Pending
        self.client.login(username='rep_cairo', password='Password123!')
        res_so_rep = self.client.post(reverse('sales_order_create'), {
            'customer': self.customer_cairo.id,
            'warehouse': self.warehouse.id,
            'order_date': timezone.now().strftime('%Y-%m-%d'),
            'product_id[]': [self.product.id],
            'quantity[]': ['10'],
            'unit_price[]': ['50.00'],
        })
        self.assertEqual(res_so_rep.status_code, 302)
        so_rep = SalesOrder.objects.filter(customer=self.customer_cairo, created_by=self.rep_cairo).first()
        self.assertIsNotNone(so_rep)
        self.assertEqual(so_rep.status, 'pending', "Rep sales order must be pending manager approval")

        # 2. Manager creates Sales Order -> Auto-approved to manager_approval
        self.client.logout()
        self.client.login(username='mgr_cairo', password='Password123!')
        res_so_mgr = self.client.post(reverse('sales_order_create'), {
            'customer': self.customer_cairo.id,
            'warehouse': self.warehouse.id,
            'order_date': timezone.now().strftime('%Y-%m-%d'),
            'product_id[]': [self.product.id],
            'quantity[]': ['5'],
            'unit_price[]': ['50.00'],
        })
        self.assertEqual(res_so_mgr.status_code, 302)
        so_mgr = SalesOrder.objects.filter(customer=self.customer_cairo, created_by=self.manager_cairo).first()
        self.assertIsNotNone(so_mgr)
        self.assertEqual(so_mgr.status, 'manager_approval', "Manager sales order must be auto-approved")
        self.assertEqual(so_mgr.approved_by, self.manager_cairo)

        # B. Purchase Orders
        # 1. Accountant creates Purchase Order -> Pending
        self.client.logout()
        self.client.login(username='acc_user', password='Password123!')
        res_po_acc = self.client.post(reverse('purchase_order_create'), {
            'supplier': self.supplier_cairo.id,
            'warehouse': self.warehouse.id,
            'order_date': timezone.now().strftime('%Y-%m-%d'),
            'product_id[]': [self.product.id],
            'quantity[]': ['20'],
            'unit_price[]': ['35.00'],
        })
        self.assertEqual(res_po_acc.status_code, 302)
        po_acc = PurchaseOrder.objects.filter(supplier=self.supplier_cairo, created_by=self.accountant_user).first()
        self.assertIsNotNone(po_acc)
        self.assertEqual(po_acc.status, 'pending', "Accountant purchase order must require manager approval")

        # 2. Manager creates Purchase Order -> Auto-approved
        self.client.logout()
        self.client.login(username='mgr_cairo', password='Password123!')
        res_po_mgr = self.client.post(reverse('purchase_order_create'), {
            'supplier': self.supplier_cairo.id,
            'warehouse': self.warehouse.id,
            'order_date': timezone.now().strftime('%Y-%m-%d'),
            'product_id[]': [self.product.id],
            'quantity[]': ['10'],
            'unit_price[]': ['35.00'],
        })
        self.assertEqual(res_po_mgr.status_code, 302)
        po_mgr = PurchaseOrder.objects.filter(supplier=self.supplier_cairo, created_by=self.manager_cairo).first()
        self.assertIsNotNone(po_mgr)
        self.assertEqual(po_mgr.status, 'approved', "Manager purchase order must auto-approve")
        self.assertEqual(po_mgr.approved_by, self.manager_cairo)

        # C. Agreements
        # 1. Rep creates agreement -> status='new' (awaiting approval)
        self.client.logout()
        self.client.login(username='rep_cairo', password='Password123!')
        res_ag_rep = self.client.post(reverse('agreement_create'), {
            'customer': self.customer_cairo.id,
            'title': 'اتفاقية توريد صيدلية الشفاء',
            'type': self.agreement_type.id,
            'amount': '15000.00',
            'date': timezone.now().strftime('%Y-%m-%d'),
            'description': 'شروط التوريد'
        })
        self.assertEqual(res_ag_rep.status_code, 302)
        ag_rep = Agreement.objects.filter(customer=self.customer_cairo, created_by=self.rep_cairo).first()
        self.assertIsNotNone(ag_rep)
        self.assertEqual(ag_rep.status, 'new', "Rep agreement must be in new/pending status")

        # 2. Manager creates agreement -> status='approved'
        self.client.logout()
        self.client.login(username='mgr_cairo', password='Password123!')
        res_ag_mgr = self.client.post(reverse('agreement_create'), {
            'customer': self.customer_cairo.id,
            'title': 'اتفاقية توريد معتمدة من الإدارة',
            'type': self.agreement_type.id,
            'amount': '50000.00',
            'date': timezone.now().strftime('%Y-%m-%d'),
            'description': 'معتمدة مباشرة'
        })
        self.assertEqual(res_ag_mgr.status_code, 302)
        ag_mgr = Agreement.objects.filter(customer=self.customer_cairo, created_by=self.manager_cairo).first()
        self.assertIsNotNone(ag_mgr)
        self.assertEqual(ag_mgr.status, 'approved', "Manager agreement must be auto-approved")

    # =========================================================================
    # Test 8: Cross-Regional Security & Isolation
    # =========================================================================
    def test_cross_region_isolation(self):
        """Manager B (Alex) cannot approve visits created in Region A (Cairo)."""
        # Rep Cairo creates visit
        self.client.login(username='rep_cairo', password='Password123!')
        self.client.post(reverse('visit_create'), {
            'contact': self.customer_cairo.id,
            'template': self.general_template.id,
            'date': timezone.now().strftime('%Y-%m-%d'),
            'is_successful': 'on',
        })
        visit = Visit.objects.filter(contact=self.customer_cairo, owner=self.rep_cairo).first()

        # Manager Alex tries to approve Cairo visit -> MUST BE 403 FORBIDDEN
        self.client.logout()
        self.client.login(username='mgr_alex', password='Password123!')
        res_cross = self.client.post(reverse('visit_action', args=[visit.pk, 'manage_status']), {
            'approval_status': 'approved',
        })
        self.assertEqual(res_cross.status_code, 403, "Cross-region manager status change must be rejected with 403")
        visit.refresh_from_db()
        self.assertEqual(visit.approval_status, 'pending', "Approval status must remain unchanged")

    # =========================================================================
    # Test 9: Product Eligibility in Visits (Sellable Only)
    # =========================================================================
    def test_product_eligibility_in_visits(self):
        """
        Products not intended for sale (sellable=False or is_active=False)
        must not be selectable for new visit-related operations.
        """
        pharmacy_tmpl = VisitTemplate.objects.create(
            name='single_visit_pharmacy',
            display_name_ar='زيارة فردية صيدلية',
            active=True,
            enable_product_detailing=True
        )

        p_sellable = Product.objects.create(
            name='دواء معتمد للبيع', sku_code='SELL-01', retail_price=100.00,
            category=self.cat, sellable=True, is_active=True
        )
        p_nonsellable = Product.objects.create(
            name='عينات مجانية غير معروضة للبيع', sku_code='FREE-01', retail_price=0.00,
            category=self.cat, sellable=False, is_active=True
        )
        p_inactive = Product.objects.create(
            name='دواء مسحوب من السوق', sku_code='INACT-01', retail_price=50.00,
            category=self.cat, sellable=True, is_active=False
        )

        eligible_qs = Product.get_eligible_for_visits()
        self.assertIn(p_sellable, eligible_qs)
        self.assertNotIn(p_nonsellable, eligible_qs)
        self.assertNotIn(p_inactive, eligible_qs)

        self.client.login(username='rep_cairo', password='Password123!')
        res = self.client.post(reverse('visit_create'), {
            'contact': self.customer_cairo.id,
            'template': pharmacy_tmpl.id,
            'date': timezone.now().strftime('%Y-%m-%d'),
            'detailed_products': [str(p_sellable.id), str(p_nonsellable.id), str(p_inactive.id)],
            'is_successful': 'on',
        })
        self.assertEqual(res.status_code, 302)
        visit = Visit.objects.filter(contact=self.customer_cairo, owner=self.rep_cairo).order_by('-id').first()
        detailed_ids = set(visit.detailed_products.values_list('id', flat=True))
        self.assertIn(p_sellable.id, detailed_ids, "Sellable product must be linked")
        self.assertNotIn(p_nonsellable.id, detailed_ids, "Non-sellable product must be filtered out")
        self.assertNotIn(p_inactive.id, detailed_ids, "Inactive product must be filtered out")

        # Rep attempts to add non-sellable product during visit completion
        res_complete = self.client.post(reverse('visit_detail', args=[visit.pk]), {
            'action': 'save_details',
            'detailed_products': [str(p_nonsellable.id)],
            'detailed_products_submitted': '1',
        })
        self.assertEqual(res_complete.status_code, 302)
        visit.refresh_from_db()
        self.assertNotIn(p_nonsellable.id, visit.detailed_products.values_list('id', flat=True))

    # =========================================================================
    # Test 10: Configurable Product Suggestions in Settings and Visit Detail
    # =========================================================================
    def test_configurable_product_suggestions(self):
        """
        Product suggestions must be configurable through the existing settings UI
        and restricted to eligible products.
        """
        pharmacy_tmpl = VisitTemplate.objects.create(
            name='single_visit_pharmacy',
            display_name_ar='زيارة فردية صيدلية',
            active=True,
            enable_product_detailing=True
        )

        p_sugg1 = Product.objects.create(
            name='بانادول مقترح 1', sku_code='PAN-SUGG1', retail_price=60.00,
            category=self.cat, sellable=True, is_active=True
        )
        p_sugg2 = Product.objects.create(
            name='بانادول مقترح 2', sku_code='PAN-SUGG2', retail_price=70.00,
            category=self.cat, sellable=True, is_active=True
        )
        p_nonsellable = Product.objects.create(
            name='عينات غير معروضة للبيع', sku_code='SAMPLE-X', retail_price=0.00,
            category=self.cat, sellable=False, is_active=True
        )

        # 1. Global Location Settings configure suggestions
        self.loc_settings.enable_product_suggestions = True
        self.loc_settings.suggested_products.set([p_sugg1, p_nonsellable])
        self.loc_settings.save()

        eligible_global_sugg = list(self.loc_settings.get_eligible_suggested_products())
        self.assertIn(p_sugg1, eligible_global_sugg)
        self.assertNotIn(p_nonsellable, eligible_global_sugg)

        # 2. Template-level configurable suggestions
        pharmacy_tmpl.suggested_products.set([p_sugg2, p_nonsellable])
        eligible_tmpl_sugg = list(pharmacy_tmpl.get_eligible_suggested_products())
        self.assertIn(p_sugg2, eligible_tmpl_sugg)
        self.assertNotIn(p_nonsellable, eligible_tmpl_sugg)

        # 3. Create visit and view visit detail
        visit = Visit.objects.create(
            contact=self.customer_cairo,
            template=pharmacy_tmpl,
            owner=self.rep_cairo,
            created_by=self.rep_cairo,
            date=timezone.now().date(),
            status='started',
            approval_status='approved'
        )

        self.client.login(username='rep_cairo', password='Password123!')
        res_view = self.client.get(reverse('visit_detail', args=[visit.pk]))
        self.assertEqual(res_view.status_code, 200)

        suggested_ids = res_view.context['suggested_product_ids']
        self.assertIn(p_sugg1.id, suggested_ids)
        self.assertIn(p_sugg2.id, suggested_ids)
        self.assertNotIn(p_nonsellable.id, suggested_ids)

    # =========================================================================
    # Test 11: Historical Non-Sellable Products Preserved
    # =========================================================================
    def test_historical_non_sellable_products_preserved(self):
        """
        Historical data preservation: if a product was previously detailed and is
        later marked non-sellable (sellable=False), it must remain linked to the visit.
        """
        pharmacy_tmpl = VisitTemplate.objects.create(
            name='single_visit_pharmacy',
            display_name_ar='زيارة فردية صيدلية',
            active=True,
            enable_product_detailing=True
        )

        p_historical = Product.objects.create(
            name='دواء تم إيقاف بيعه لاحقاً', sku_code='HIST-01', retail_price=80.00,
            category=self.cat, sellable=True, is_active=True
        )

        visit = Visit.objects.create(
            contact=self.customer_cairo,
            template=pharmacy_tmpl,
            owner=self.rep_cairo,
            created_by=self.rep_cairo,
            date=timezone.now().date(),
            status='started',
            approval_status='approved'
        )
        visit.detailed_products.set([p_historical])

        # Product is now retired/marked non-sellable
        p_historical.sellable = False
        p_historical.save()

        # Rep opens visit_detail: historical product should still be included in context products
        self.client.login(username='rep_cairo', password='Password123!')
        res_view = self.client.get(reverse('visit_detail', args=[visit.pk]))
        self.assertEqual(res_view.status_code, 200)
        context_product_ids = set(p.id for p in res_view.context['products'])
        self.assertIn(p_historical.id, context_product_ids, "Historical product must be preserved in context")

        # Rep completes visit without removing detailed products
        res_complete = self.client.post(reverse('visit_detail', args=[visit.pk]), {
            'action': 'complete',
            'detailed_products': [str(p_historical.id)],
            'visit_outcome': 'successful',
        })
        self.assertEqual(res_complete.status_code, 302)
        visit.refresh_from_db()
        self.assertIn(p_historical.id, visit.detailed_products.values_list('id', flat=True),
                      "Historical product must remain attached to the completed visit")
