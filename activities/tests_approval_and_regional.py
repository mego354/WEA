import datetime
from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission

from accounts.models import Role
from master_data.models import Area
from contacts.models import Contact
from catalog.models import Product, ProductCategory
from inventory.models import Warehouse
from activities.models import VisitTemplate, PlannedVisitDay, PlannedVisitItem, Visit, ApprovalAuditLog
from sales.models import SalesOrder, SalesOrderItem
from sales.services import SalesOrderService
from purchases.models import PurchaseOrder, PurchaseOrderItem
from purchases.services import PurchaseOrderService
from django.core.exceptions import ValidationError
from accounts.permissions import get_scoped_queryset, can_user_access_object, get_user_managed_areas, get_user_managed_representatives

User = get_user_model()


class RoleBasedTemplatesAndRegionalApprovalsTestCase(TestCase):
    def setUp(self):
        self.client = Client()

        # 1. Create Roles
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

        # 2. Assign standard permissions to manager and rep roles
        perms = Permission.objects.filter(
            codename__in=[
                'activities:visits/list', 'activities:visits/view', 'activities:visits/create', 'activities:visits/edit',
                'activities:visits/approve', 'activities:planned/list', 'activities:planned/manage',
                'sales:orders/list', 'sales:orders/view', 'sales:orders/create', 'sales:orders/approve',
                'purchases:orders/list', 'purchases:orders/view', 'purchases:orders/create', 'purchases:orders/approve',
                'module:activities', 'module:sales', 'module:contacts', 'module:purchases'
            ]
        )
        self.manager_role.permissions.set(perms)
        self.rep_role.permissions.set(
            perms.exclude(codename__in=['activities:visits/approve', 'sales:orders/approve', 'purchases:orders/approve'])
        )

        # 3. Create Regional Hierarchy
        # Region A: Riyadh (Governorate) with Subregions Olaya and Malaz
        self.region_a = Area.objects.create(code='REG-A', name='الرياض', area_type='governorate')
        self.subregion_a1 = Area.objects.create(code='SUB-A1', name='العليا', area_type='subarea', parent=self.region_a)
        self.subregion_a2 = Area.objects.create(code='SUB-A2', name='الملز', area_type='subarea', parent=self.region_a)

        # Region B: Jeddah (Governorate) with Subregion Rawdah
        self.region_b = Area.objects.create(code='REG-B', name='جدة', area_type='governorate')
        self.subregion_b1 = Area.objects.create(code='SUB-B1', name='الروضة', area_type='subarea', parent=self.region_b)

        # 4. Create Users
        # SuperAdmin
        self.superadmin = User.objects.create_superuser(
            username='superadmin', email='super@example.com', password='Password123!',
            first_name='Super', last_name='Admin'
        )

        # Manager A (Assigned to Region A)
        self.manager_a = User.objects.create_user(
            username='manager_a', email='manager_a@example.com', password='Password123!',
            first_name='أحمد', last_name='مدير الرياض', role=self.manager_role
        )
        self.manager_a.assigned_areas.add(self.region_a)

        # Manager B (Assigned to Region B)
        self.manager_b = User.objects.create_user(
            username='manager_b', email='manager_b@example.com', password='Password123!',
            first_name='سعيد', last_name='مدير جدة', role=self.manager_role
        )
        self.manager_b.assigned_areas.add(self.region_b)

        # Rep A1 (Assigned to Subregion A1 under Region A)
        self.rep_a1 = User.objects.create_user(
            username='rep_a1', email='rep_a1@example.com', password='Password123!',
            first_name='خالد', last_name='مندوب العليا', role=self.rep_role
        )
        self.rep_a1.assigned_areas.add(self.subregion_a1)

        # Rep B1 (Assigned to Subregion B1 under Region B)
        self.rep_b1 = User.objects.create_user(
            username='rep_b1', email='rep_b1@example.com', password='Password123!',
            first_name='طارق', last_name='مندوب الروضة', role=self.rep_role
        )
        self.rep_b1.assigned_areas.add(self.subregion_b1)

        # 5. Create Contacts
        self.contact_pharmacy_a = Contact.objects.create(
            name='صيدلية الأمل', code='PH001', account_type='Pharmacy',
            area=self.subregion_a1, is_customer=True, status='customer'
        )
        self.contact_clinic_a = Contact.objects.create(
            name='عيادة النور', code='CL001', account_type='Clinic',
            area=self.subregion_a2, is_customer=True, status='customer'
        )
        self.contact_pharmacy_b = Contact.objects.create(
            name='صيدلية الشفاء بجدة', code='PH002', account_type='Pharmacy',
            area=self.subregion_b1, is_customer=True, status='customer'
        )
        self.supplier = Contact.objects.create(
            name='شركة توريد الأدوية العالمية', code='SUP001', account_type='Store',
            area=self.subregion_a1, is_supplier=True, status='supplier'
        )

        # 6. Create Templates
        self.pharmacy_template = VisitTemplate.objects.create(
            name='Pharmacy Routine Visit',
            display_name_ar='زيارة دورية لصيدلية',
            restrict_account_types=['Pharmacy', 'Store'],
            active=True
        )
        self.clinic_template = VisitTemplate.objects.create(
            name='Physician Detailing',
            display_name_ar='زيارة شرح لطبيب بعيادة',
            restrict_account_types=['Clinic', 'Center'],
            active=True
        )
        self.general_template = VisitTemplate.objects.create(
            name='General Contact Visit',
            display_name_ar='زيارة عامة لأي عميل',
            restrict_account_types=[],
            active=True
        )

        # 7. Create Warehouse and Product for Sales Orders
        self.category = ProductCategory.objects.create(name='الأدوية', code='CAT-MED')
        self.product = Product.objects.create(
            name='بانادول 500 ملجم', sku_code='PAN500', category=self.category,
            retail_price=Decimal('15.00'), default_purchase_cost=Decimal('10.00'), is_active=True
        )
        self.warehouse = Warehouse.objects.create(name='مستودع الرياض المركزي', code='WH-RYD', is_active=True)

    # =========================================================================
    # REQUIREMENT 1 & 2: Role-Based Visit Templates & Contact Compatibility
    # =========================================================================
    def test_visit_template_contact_eligibility_model_level(self):
        """Model level tests for template/contact eligibility with aliases."""
        # Pharmacy template vs Pharmacy contact -> True
        self.assertTrue(self.pharmacy_template.is_contact_eligible(self.contact_pharmacy_a))
        # Pharmacy template vs Clinic contact -> False
        self.assertFalse(self.pharmacy_template.is_contact_eligible(self.contact_clinic_a))
        # Clinic template vs Clinic contact -> True
        self.assertTrue(self.clinic_template.is_contact_eligible(self.contact_clinic_a))
        # Clinic template vs Pharmacy contact -> False
        self.assertFalse(self.clinic_template.is_contact_eligible(self.contact_pharmacy_a))
        # General template (empty restrictions) -> True for all
        self.assertTrue(self.general_template.is_contact_eligible(self.contact_pharmacy_a))
        self.assertTrue(self.general_template.is_contact_eligible(self.contact_clinic_a))

    def test_planned_visit_add_item_enforces_template_compatibility(self):
        """Planned visit item creation must reject incompatible templates."""
        self.client.login(username='rep_a1', password='Password123!')
        
        # Incompatible: Assigning Pharmacy template to Clinic contact
        res_incompatible = self.client.post(reverse('planned_visit_add_item'), {
            'date': timezone.now().strftime('%Y-%m-%d'),
            'contact_id': self.contact_clinic_a.id,
            'template_id': self.pharmacy_template.id,
            'assignee_id': self.rep_a1.id,
        })
        self.assertFalse(PlannedVisitItem.objects.filter(contact=self.contact_clinic_a, template=self.pharmacy_template).exists())

        # Compatible: Assigning Clinic template to Clinic contact
        res_compatible = self.client.post(reverse('planned_visit_add_item'), {
            'date': timezone.now().strftime('%Y-%m-%d'),
            'contact_id': self.contact_clinic_a.id,
            'template_id': self.clinic_template.id,
            'assignee_id': self.rep_a1.id,
        })
        self.assertTrue(PlannedVisitItem.objects.filter(contact=self.contact_clinic_a, template=self.clinic_template).exists())

    def test_unplanned_visit_backend_rejects_incompatible_template(self):
        """Unplanned visit form submission must reject incompatible template independently on backend."""
        self.client.login(username='rep_a1', password='Password123!')
        
        # Try submitting visit for Clinic contact with Pharmacy template
        post_data = {
            'contact': self.contact_clinic_a.id,
            'template': self.pharmacy_template.id,
            'date': timezone.now().strftime('%Y-%m-%d'),
            'is_successful': 'on',
            'latitude': '24.7136',
            'longitude': '46.6753',
            'device_accuracy': '15.0',
        }
        res = self.client.post(reverse('visit_create'), post_data)
        # Form error should prevent creation
        self.assertFalse(Visit.objects.filter(contact=self.contact_clinic_a, template=self.pharmacy_template).exists())

        # Now submit compatible template
        post_data['template'] = self.clinic_template.id
        res_valid = self.client.post(reverse('visit_create'), post_data)
        self.assertTrue(Visit.objects.filter(contact=self.contact_clinic_a, template=self.clinic_template).exists())

    def test_visit_templates_api_filters_by_contact_and_user_role(self):
        """API /api/templates/ must return only templates eligible for the requested contact."""
        self.client.login(username='rep_a1', password='Password123!')
        
        # Query for Pharmacy contact
        res_ph = self.client.get(f"{reverse('visit_templates_api')}?contact_id={self.contact_pharmacy_a.id}")
        self.assertEqual(res_ph.status_code, 200)
        data_ph = res_ph.json()
        ids_ph = [t['id'] for t in data_ph['results']]
        self.assertIn(self.pharmacy_template.id, ids_ph)
        self.assertIn(self.general_template.id, ids_ph)
        self.assertNotIn(self.clinic_template.id, ids_ph)

        # Query for Clinic contact
        res_cl = self.client.get(f"{reverse('visit_templates_api')}?contact_id={self.contact_clinic_a.id}")
        self.assertEqual(res_cl.status_code, 200)
        data_cl = res_cl.json()
        ids_cl = [t['id'] for t in data_cl['results']]
        self.assertIn(self.clinic_template.id, ids_cl)
        self.assertIn(self.general_template.id, ids_cl)
        self.assertNotIn(self.pharmacy_template.id, ids_cl)

    # =========================================================================
    # REQUIREMENT 4: Regional Hierarchy & Horizontal/Vertical Data Isolation
    # =========================================================================
    def test_regional_hierarchy_scope_calculation(self):
        """Manager assigned to governorate automatically manages all child subareas and their reps."""
        managed_areas_a = get_user_managed_areas(self.manager_a)
        self.assertIn(self.region_a, managed_areas_a)
        self.assertIn(self.subregion_a1, managed_areas_a)
        self.assertIn(self.subregion_a2, managed_areas_a)
        self.assertNotIn(self.region_b, managed_areas_a)
        self.assertNotIn(self.subregion_b1, managed_areas_a)

        managed_reps_a = get_user_managed_representatives(self.manager_a)
        self.assertIn(self.rep_a1, managed_reps_a)
        self.assertNotIn(self.rep_b1, managed_reps_a)

        # SuperAdmin manages all
        all_reps = get_user_managed_representatives(self.superadmin)
        self.assertIn(self.rep_a1, all_reps)
        self.assertIn(self.rep_b1, all_reps)

    def test_horizontal_data_isolation_between_regions(self):
        """Manager A cannot access or view records of Region B."""
        # Create Visit and Order in Region A
        visit_a = Visit.objects.create(
            serial_num=8001, contact=self.contact_pharmacy_a,
            template=self.pharmacy_template, owner=self.rep_a1,
            approval_status='pending', status='finished'
        )
        order_a = SalesOrder.objects.create(
            serial_num=9001,
            order_number='SO-REG-A01', customer=self.contact_pharmacy_a,
            source_warehouse=self.warehouse, created_by=self.rep_a1,
            grand_total=Decimal('150.00'), status='pending'
        )

        # Create Visit and Order in Region B
        visit_b = Visit.objects.create(
            serial_num=8002, contact=self.contact_pharmacy_b,
            template=self.pharmacy_template, owner=self.rep_b1,
            approval_status='pending', status='finished'
        )
        order_b = SalesOrder.objects.create(
            serial_num=9002,
            order_number='SO-REG-B01', customer=self.contact_pharmacy_b,
            source_warehouse=self.warehouse, created_by=self.rep_b1,
            grand_total=Decimal('200.00'), status='pending'
        )

        # Manager A access checks:
        self.assertTrue(can_user_access_object(self.manager_a, visit_a, 'view'))
        self.assertTrue(can_user_access_object(self.manager_a, visit_a, 'approve'))
        self.assertTrue(can_user_access_object(self.manager_a, order_a, 'view'))
        self.assertTrue(can_user_access_object(self.manager_a, order_a, 'approve'))

        # Manager A cross-region access to Region B must be FALSE:
        self.assertFalse(can_user_access_object(self.manager_a, visit_b, 'view'))
        self.assertFalse(can_user_access_object(self.manager_a, visit_b, 'approve'))
        self.assertFalse(can_user_access_object(self.manager_a, order_b, 'view'))
        self.assertFalse(can_user_access_object(self.manager_a, order_b, 'approve'))

        # Direct HTTP attempt by Manager A on Region B records must be blocked:
        self.client.login(username='manager_a', password='Password123!')
        res_visit_b = self.client.get(reverse('visit_detail', args=[visit_b.pk]))
        self.assertEqual(res_visit_b.status_code, 403)

        res_order_b = self.client.get(reverse('sales_order_detail', args=[order_b.pk]))
        self.assertEqual(res_order_b.status_code, 403)

    # =========================================================================
    # REQUIREMENT 3 & 5: Approval Workflows, Self-Approval Block & Resubmission
    # =========================================================================
    def test_representative_cannot_self_approve_visit_or_order(self):
        """A representative must never be able to approve their own visit or sales order."""
        visit_a = Visit.objects.create(
            serial_num=8003, contact=self.contact_pharmacy_a,
            template=self.pharmacy_template, owner=self.rep_a1,
            approval_status='pending', status='finished'
        )
        order_a = SalesOrder.objects.create(
            serial_num=9003,
            order_number='SO-REG-A02', customer=self.contact_pharmacy_a,
            source_warehouse=self.warehouse, created_by=self.rep_a1,
            grand_total=Decimal('300.00'), status='pending'
        )

        self.assertFalse(can_user_access_object(self.rep_a1, visit_a, 'approve'))
        self.assertFalse(can_user_access_object(self.rep_a1, order_a, 'approve'))

        # Rep direct HTTP approval attempt must fail
        self.client.login(username='rep_a1', password='Password123!')
        res_approve_visit = self.client.post(reverse('visit_action', args=[visit_a.pk, 'approve']))
        visit_a.refresh_from_db()
        self.assertEqual(visit_a.approval_status, 'pending')

        res_approve_order = self.client.post(reverse('sales_order_action', args=[order_a.pk, 'approve']))
        order_a.refresh_from_db()
        self.assertEqual(order_a.status, 'pending')

    def test_visit_approval_rejection_and_resubmission_lifecycle(self):
        """Full lifecycle of visit approval, rejection with mandatory reason, and resubmission."""
        visit = Visit.objects.create(
            serial_num=8004, contact=self.contact_pharmacy_a,
            template=self.pharmacy_template, owner=self.rep_a1,
            approval_status='pending', status='finished'
        )

        # 1. Manager rejects without reason -> must be blocked
        self.client.login(username='manager_a', password='Password123!')
        res_reject_no_reason = self.client.post(reverse('visit_action', args=[visit.pk, 'disapprove']), {
            'approval_notes': ''
        })
        visit.refresh_from_db()
        self.assertEqual(visit.approval_status, 'pending')

        # 2. Manager rejects with reason -> succeeds and logs audit
        res_reject = self.client.post(reverse('visit_action', args=[visit.pk, 'disapprove']), {
            'approval_notes': 'يرجى مراجعة إجابات أسئلة المخزون وإعادة الإرسال.'
        })
        visit.refresh_from_db()
        self.assertEqual(visit.approval_status, 'disapproved')
        self.assertEqual(visit.approved_by, self.manager_a)
        self.assertIn('يرجى مراجعة', visit.approval_notes)
        self.assertTrue(ApprovalAuditLog.objects.filter(visit=visit, action='rejected').exists())

        # 3. Representative resubmits after correction
        self.client.login(username='rep_a1', password='Password123!')
        res_resubmit = self.client.post(reverse('visit_action', args=[visit.pk, 'resubmit']), {
            'notes': 'تم تعديل البيانات وفق الملاحظات.'
        })
        visit.refresh_from_db()
        self.assertEqual(visit.approval_status, 'pending')
        self.assertIsNone(visit.approved_by)
        self.assertTrue(ApprovalAuditLog.objects.filter(visit=visit, action='resubmitted').exists())

        # 4. Manager approves -> succeeds
        self.client.login(username='manager_a', password='Password123!')
        res_approve = self.client.post(reverse('visit_action', args=[visit.pk, 'approve']), {
            'approval_notes': 'معتمد ومقبول.'
        })
        visit.refresh_from_db()
        self.assertEqual(visit.approval_status, 'approved')
        self.assertEqual(visit.approved_by, self.manager_a)
        self.assertIsNotNone(visit.approved_at)
        self.assertTrue(ApprovalAuditLog.objects.filter(visit=visit, action='approved').exists())

    def test_sales_order_approval_rejection_resubmission_and_downstream_enforcement(self):
        """Full sales order approval lifecycle and strict prevention of downstream bypass."""
        from inventory.models import InventoryStock
        InventoryStock.objects.create(
            warehouse=self.warehouse, product=self.product,
            qty_on_hand=Decimal('100.00'), qty_reserved=Decimal('0.00'),
            product_cost=Decimal('10.00')
        )

        order = SalesOrder.objects.create(
            serial_num=9004,
            order_number='SO-REG-A03', customer=self.contact_pharmacy_a,
            source_warehouse=self.warehouse, created_by=self.rep_a1,
            grand_total=Decimal('450.00'), status='pending'
        )
        SalesOrderItem.objects.create(
            order=order, product=self.product, quantity=30,
            unit_price=Decimal('15.00'), subtotal=Decimal('450.00')
        )

        # 1. Downstream preparation while status is 'pending' MUST fail
        with self.assertRaises(ValidationError):
            SalesOrderService.prepare_order(order, self.manager_a)
        with self.assertRaises(ValidationError):
            SalesOrderService.deliver_order(order, self.manager_a)
        with self.assertRaises(ValidationError):
            SalesOrderService.invoice_order(order, self.manager_a)

        # 2. Manager rejects order with reason
        SalesOrderService.reject_order(order, self.manager_a, reason='تجاوز الحد الائتماني المسموح به')
        order.refresh_from_db()
        self.assertEqual(order.status, 'rejected')
        self.assertEqual(order.rejection_reason, 'تجاوز الحد الائتماني المسموح به')
        self.assertTrue(ApprovalAuditLog.objects.filter(sales_order=order, action='rejected').exists())

        # 3. Downstream operations while rejected MUST fail
        with self.assertRaises(ValidationError):
            SalesOrderService.prepare_order(order, self.manager_a)

        # 4. Rep resubmits order
        SalesOrderService.resubmit_order(order, self.rep_a1)
        order.refresh_from_db()
        self.assertEqual(order.status, 'pending')
        self.assertTrue(ApprovalAuditLog.objects.filter(sales_order=order, action='resubmitted').exists())

        # 5. Manager approves order
        SalesOrderService.approve_order(order, self.manager_a)
        order.refresh_from_db()
        self.assertEqual(order.status, 'manager_approval')
        self.assertEqual(order.approved_by, self.manager_a)
        self.assertIsNotNone(order.approved_at)
        self.assertTrue(ApprovalAuditLog.objects.filter(sales_order=order, action='approved').exists())

        # 6. Now downstream prepare_order is allowed!
        SalesOrderService.prepare_order(order, self.manager_a)
        order.refresh_from_db()
        self.assertEqual(order.status, 'preparing')

    # =========================================================================
    # REQUIREMENT 5 & 8: Approvals Removal & Canonical List/Detail Integration
    # =========================================================================
    def test_approvals_hub_and_regional_dashboard_endpoints(self):
        """Verify approvals hub redirects to canonical item list views and regional dashboard loads."""
        # Unauthenticated or rep login
        self.client.login(username='rep_a1', password='Password123!')
        res_rep_appr = self.client.get(reverse('approvals_hub'))
        # Canonical redirect to visits list pending
        self.assertEqual(res_rep_appr.status_code, 302)
        self.assertIn('/visits/', res_rep_appr.url)

        # Manager A accessing approvals_hub also cleanly redirects to canonical list
        self.client.login(username='manager_a', password='Password123!')
        res_mgr_appr = self.client.get(reverse('approvals_hub'))
        self.assertEqual(res_mgr_appr.status_code, 302)
        self.assertIn('/visits/', res_mgr_appr.url)

        # Orders tab redirects to sales list
        res_orders_tab = self.client.get(f"{reverse('approvals_hub')}?tab=orders")
        self.assertEqual(res_orders_tab.status_code, 302)
        self.assertIn('/sales/', res_orders_tab.url)

        # Manager A can view Agenda for subordinate reps
        res_mgr_agenda = self.client.get(reverse('agenda'), {'assignee': self.rep_a1.id})
        self.assertEqual(res_mgr_agenda.status_code, 200)
        self.assertContains(res_mgr_agenda, 'جدول الاعمال')

    def test_purchase_order_approval_lifecycle_and_downstream_enforcement(self):
        """Verify purchase order approval, rejection with reason, resubmit, self-approval prevention, and downstream blocks."""
        po = PurchaseOrder.objects.create(
            serial_num=999,
            order_number="#999",
            supplier=self.supplier,
            target_warehouse=self.warehouse,
            created_by=self.rep_a1,
            status='pending'
        )
        PurchaseOrderItem.objects.create(
            order=po,
            product=self.product,
            quantity=10,
            unit_price=100
        )
        po.recalculate_totals()

        # 1. Downstream block: Cannot stock unapproved purchase order
        with self.assertRaises(ValidationError):
            PurchaseOrderService.stock_order(po, self.manager_a)

        # 2. Self-approval prevention: Purchaser/creator cannot approve own order
        with self.assertRaises(ValidationError):
            PurchaseOrderService.approve_order(po, self.rep_a1)

        # 3. Rejection requires non-empty reason
        with self.assertRaises(ValidationError):
            PurchaseOrderService.reject_order(po, self.manager_a, reason="")

        # 4. Authorized rejection
        PurchaseOrderService.reject_order(po, self.manager_a, reason="سعر التكلفة غير مطابق للاتفاقية")
        po.refresh_from_db()
        self.assertEqual(po.status, 'rejected')
        self.assertEqual(po.rejection_reason, "سعر التكلفة غير مطابق للاتفاقية")
        self.assertTrue(ApprovalAuditLog.objects.filter(purchase_order=po, action='rejected').exists())

        # 5. Resubmission by creator resets status to pending
        PurchaseOrderService.resubmit_order(po, self.rep_a1)
        po.refresh_from_db()
        self.assertEqual(po.status, 'pending')
        self.assertEqual(po.rejection_reason, "")
        self.assertTrue(ApprovalAuditLog.objects.filter(purchase_order=po, action='resubmitted').exists())

        # 6. Authorized approval by manager
        PurchaseOrderService.approve_order(po, self.manager_a, notes="معتمد للشراء")
        po.refresh_from_db()
        self.assertEqual(po.status, 'approved')
        self.assertEqual(po.approved_by, self.manager_a)
        self.assertTrue(ApprovalAuditLog.objects.filter(purchase_order=po, action='approved').exists())

        # 7. Downstream stocking unlocked after approval
        PurchaseOrderService.stock_order(po, self.manager_a)
        po.refresh_from_db()
        self.assertEqual(po.status, 'picked')

    def test_item_detail_pages_approval_actions_and_list_filters(self):
        """Verify approval actions directly on Visit, SalesOrder, and PurchaseOrder detail pages, and list filters."""
        # --- Visit Detail & Approval ---
        visit = Visit.objects.create(
            serial_num=888,
            owner=self.rep_a1,
            contact=self.contact_pharmacy_a,
            template=self.pharmacy_template,
            status='finished',
            approval_status='pending',
            date=timezone.now().date(),
            created_by=self.rep_a1
        )
        self.client.login(username='manager_a', password='Password123!')
        res_v_detail = self.client.get(reverse('visit_detail', args=[visit.pk]))
        self.assertEqual(res_v_detail.status_code, 200)
        self.assertTrue(res_v_detail.context['can_approve'])

        # Approve visit via detail page action
        res_v_act = self.client.post(reverse('visit_action', args=[visit.pk, 'approve']))
        self.assertEqual(res_v_act.status_code, 302)
        visit.refresh_from_db()
        self.assertEqual(visit.approval_status, 'approved')

        # Visits list filter by approval_status
        res_v_list = self.client.get(reverse('visits_list') + '?approval_status=approved')
        self.assertEqual(res_v_list.status_code, 200)
        self.assertContains(res_v_list, str(visit.serial_num))

        # --- Sales Order Detail & Approval ---
        order = SalesOrder.objects.create(
            serial_num=888,
            order_number="#SO-888",
            customer=self.contact_pharmacy_a,
            source_warehouse=self.warehouse,
            created_by=self.rep_a1,
            status='pending',
            order_date=timezone.now().date()
        )
        res_so_detail = self.client.get(reverse('sales_order_detail', args=[order.pk]))
        self.assertEqual(res_so_detail.status_code, 200)
        self.assertTrue(res_so_detail.context['can_approve'])

        # Reject sales order with reason
        res_so_reject = self.client.post(reverse('sales_order_action', args=[order.pk, 'reject']), {
            'rejection_reason': 'الحد الائتماني غير كافي'
        })
        self.assertEqual(res_so_reject.status_code, 302)
        order.refresh_from_db()
        self.assertEqual(order.status, 'rejected')

        # Sales list filter by status=rejected
        res_so_list = self.client.get(reverse('sales_orders_list') + '?status=rejected')
        self.assertEqual(res_so_list.status_code, 200)
        self.assertContains(res_so_list, order.order_number)

        # --- Purchase Order Detail & Approval ---
        po = PurchaseOrder.objects.create(
            serial_num=888,
            order_number="#PO-888",
            supplier=self.supplier,
            target_warehouse=self.warehouse,
            created_by=self.rep_a1,
            status='pending',
            order_date=timezone.now().date()
        )
        res_po_detail = self.client.get(reverse('purchase_order_detail', args=[po.pk]))
        self.assertEqual(res_po_detail.status_code, 200)
        self.assertTrue(res_po_detail.context['can_approve'])

        # Approve purchase order via detail action
        res_po_act = self.client.post(reverse('purchase_order_action', args=[po.pk, 'approve']), {
            'approval_notes': 'معتمد من مدير المشتريات'
        })
        self.assertEqual(res_po_act.status_code, 302)
        po.refresh_from_db()
        self.assertEqual(po.status, 'approved')

        # Purchase orders list filter by status=approved
        res_po_list = self.client.get(reverse('purchase_orders_list') + '?status=approved')
        self.assertEqual(res_po_list.status_code, 200)
        self.assertContains(res_po_list, po.order_number)

    def test_manager_of_same_area_can_change_visit_status_and_approve(self):
        """Manager of the same regional area can approve and change visit status from detail page."""
        visit = Visit.objects.create(
            serial_num=9901,
            contact=self.contact_pharmacy_a,
            template=self.pharmacy_template,
            owner=self.rep_a1,
            created_by=self.rep_a1,
            date=timezone.now().date(),
            status='started',
            approval_status='pending'
        )

        # Manager A (same area) views detail page
        self.client.force_login(self.manager_a)
        res_detail = self.client.get(reverse('visit_detail', args=[visit.pk]))
        self.assertEqual(res_detail.status_code, 200)
        self.assertTrue(res_detail.context['can_approve'])
        self.assertFalse(res_detail.context['is_in_agenda'])

        # Manager A changes status to approved and finished
        res_change = self.client.post(
            reverse('visit_action', args=[visit.pk, 'change_status']),
            {
                'approval_status': 'approved',
                'visit_status': 'finished',
                'reason': 'اعتماد وتغيير الحالة من مدير المنطقة'
            }
        )
        self.assertEqual(res_change.status_code, 302)
        visit.refresh_from_db()
        self.assertEqual(visit.approval_status, 'approved')
        self.assertEqual(visit.status, 'finished')
        self.assertEqual(visit.approved_by, self.manager_a)
        self.assertIsNotNone(visit.approved_at)

        # Audit log verification
        audit = ApprovalAuditLog.objects.filter(visit=visit, action='status_changed').first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.actor, self.manager_a)

    def test_manager_of_different_area_cannot_change_visit_status(self):
        """Manager of a different region cannot approve or change visit status."""
        visit = Visit.objects.create(
            serial_num=9902,
            contact=self.contact_pharmacy_a,
            template=self.pharmacy_template,
            owner=self.rep_a1,
            created_by=self.rep_a1,
            date=timezone.now().date(),
            status='started',
            approval_status='pending'
        )

        # Manager B (Alexandria/Jeddah) attempts to change status of Region A visit
        self.client.force_login(self.manager_b)
        res = self.client.post(
            reverse('visit_action', args=[visit.pk, 'change_status']),
            {
                'approval_status': 'approved',
                'visit_status': 'finished',
            }
        )
        visit.refresh_from_db()
        self.assertEqual(visit.approval_status, 'pending')
        self.assertEqual(visit.status, 'started')

    def test_representative_cannot_self_approve_visit(self):
        """Representative cannot approve or change approval status on their own visit."""
        visit = Visit.objects.create(
            serial_num=9903,
            contact=self.contact_pharmacy_a,
            template=self.pharmacy_template,
            owner=self.rep_a1,
            created_by=self.rep_a1,
            date=timezone.now().date(),
            status='finished',
            approval_status='pending'
        )

        self.client.force_login(self.rep_a1)
        res = self.client.post(reverse('visit_action', args=[visit.pk, 'approve']))
        visit.refresh_from_db()
        self.assertEqual(visit.approval_status, 'pending')

    def test_unapproved_visit_cannot_be_sent_to_agenda(self):
        """A visit must be approved before sending it to the agenda."""
        visit = Visit.objects.create(
            serial_num=9904,
            contact=self.contact_pharmacy_a,
            template=self.pharmacy_template,
            owner=self.rep_a1,
            created_by=self.rep_a1,
            date=timezone.now().date(),
            status='started',
            approval_status='pending'
        )

        self.client.force_login(self.manager_a)
        res = self.client.post(reverse('visit_action', args=[visit.pk, 'send_to_agenda']))
        # Should redirect back to detail with an error message
        self.assertEqual(res.status_code, 302)
        self.assertFalse(PlannedVisitItem.objects.filter(visit=visit).exists())

    def test_approved_visit_can_be_sent_to_agenda(self):
        """Once approved by area manager, the visit is successfully sent to the agenda."""
        visit = Visit.objects.create(
            serial_num=9905,
            contact=self.contact_pharmacy_a,
            template=self.pharmacy_template,
            owner=self.rep_a1,
            created_by=self.rep_a1,
            date=timezone.now().date(),
            status='started',
            approval_status='approved',
            approved_by=self.manager_a,
            approved_at=timezone.now()
        )

        self.client.force_login(self.manager_a)
        res = self.client.post(reverse('visit_action', args=[visit.pk, 'send_to_agenda']))
        self.assertEqual(res.status_code, 302)
        self.assertIn('/agenda/', res.url)

        # Verify item added to PlannedVisitDay
        item = PlannedVisitItem.objects.filter(visit=visit).first()
        self.assertIsNotNone(item)
        self.assertEqual(item.plan_day.assignee, self.rep_a1)
        self.assertEqual(item.plan_day.date, visit.date)
        self.assertEqual(item.contact, self.contact_pharmacy_a)

        # Detail page now reflects is_in_agenda=True
        res_detail = self.client.get(reverse('visit_detail', args=[visit.pk]))
        self.assertTrue(res_detail.context['is_in_agenda'])

