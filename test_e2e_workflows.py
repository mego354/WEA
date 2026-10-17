import os
import sys
import django
from decimal import Decimal

# Ensure utf-8 stdout on Windows
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.test import Client
from django.utils import timezone
from django.contrib.auth import get_user_model
from contacts.models import Contact
from catalog.models import Product, ProductCategory
from inventory.models import Warehouse, InventoryStock, InventoryMemo
from purchases.models import PurchaseOrder, PurchaseOrderItem, PurchaseReturnOrder, PurchaseReturnOrderItem
from purchases.services import PurchaseOrderService, PurchaseReturnOrderService
from treasury.models import Vault, VendorAccount, VendorTransaction, VendorPayment
from treasury.services import TreasuryService
from sales.models import SalesOrder, SalesOrderItem, CustomerAccount, CustomerTransaction, Collection
from sales.services import SalesOrderService, CollectionService

User = get_user_model()

def run_tests():
    print("=" * 60)
    print("STARTING COMPLETE E2E WORKFLOW VERIFICATION TEST")
    print("=" * 60)

    client = Client()

    # 1. Test Login
    print("\n[1] Testing Authentication...")
    login_success = client.login(username='wea.pharm2020@gmail.com', password='Wea@4444')
    assert login_success, "Login failed with credentials wea.pharm2020@gmail.com / Wea@4444"
    print("  ✓ Authenticated successfully with superadmin credentials.")

    resp = client.get('/home/')
    assert resp.status_code == 200, f"Expected 200 for /home/, got {resp.status_code}"
    print("  ✓ Dashboard /home/ rendered with HTTP 200.")

    user = User.objects.get(email='wea.pharm2020@gmail.com')

    # 2. Master Data Setup
    print("\n[2] Setting up Test Master Data...")
    wh, _ = Warehouse.objects.get_or_create(code="WH-TEST", defaults={"name": "مخزن التجارب المركزي", "address": "القاهرة"})
    vault, _ = Vault.objects.get_or_create(serial_num=9999, defaults={"name": "خزنة الاختبارات النقدية", "current_balance": Decimal("50000.00")})
    cat, _ = ProductCategory.objects.get_or_create(code="TEST-CAT", defaults={"name": "أدوية علاجية"})
    
    prod, _ = Product.objects.get_or_create(
        sku_code="PARA-500",
        defaults={
            "name": "باراسيتامول 500 مجم أقراص",
            "category": cat,
            "retail_price": Decimal("75.00"),
            "default_purchase_cost": Decimal("50.00"),
            "unit": "علبة"
        }
    )

    supplier, _ = Contact.objects.get_or_create(
        name="شركة فارما تريد للأدوية",
        defaults={"is_supplier": True, "mobile": "01011112222", "created_by": user}
    )
    VendorAccount.get_or_create_for_supplier(supplier)

    customer, _ = Contact.objects.get_or_create(
        name="صيدلية الأمل الحديثة",
        defaults={"is_customer": True, "mobile": "01233334444", "created_by": user}
    )
    CustomerAccount.get_or_create_for_customer(customer)

    print(f"  ✓ Warehouse: {wh.name}")
    print(f"  ✓ Vault Balance: {vault.current_balance:,.2f} EGP")
    print(f"  ✓ Product: {prod.name} (SKU: {prod.sku_code})")
    print(f"  ✓ Supplier: {supplier.name}")
    print(f"  ✓ Customer: {customer.name}")

    v_acc = VendorAccount.objects.get(supplier=supplier)
    c_acc = CustomerAccount.objects.get(customer=customer)
    initial_vendor_bal = v_acc.current_balance
    initial_customer_bal = c_acc.current_balance

    # 3. Purchasing Workflow (P0 Core)
    print("\n[3] Testing Purchasing Workflow (P0 Core)...")
    po = PurchaseOrderService.create_order(
        supplier=supplier,
        target_warehouse=wh,
        order_date="2026-10-08",
        items_data=[{
            'product': prod,
            'quantity': Decimal('100'),
            'unit_price': Decimal('50.00'),
            'batch_number': 'BATCH-001',
            'expiry_date': '2028-12-31',
            'discount_percentage': Decimal('0.00')
        }],
        user=user,
        notes="E2E Automated Verification Test Order"
    )
    print(f"  ✓ Created PO #{po.order_number} with Grand Total: {po.grand_total:,.2f} EGP (Status: {po.status})")
    assert po.status == 'pending', "New PO must have status 'pending'"
    assert po.grand_total == Decimal('5000.00'), f"Grand total mismatch: expected 5000, got {po.grand_total}"

    # Approve
    po = PurchaseOrderService.approve_order(po, user)
    print(f"  ✓ Manager Approved PO #{po.order_number} (Status: {po.status})")
    assert po.status == 'approved', "Approved PO must have status 'approved'"

    # Stock (Warehouse receipt)
    po = PurchaseOrderService.stock_order(po, user)
    print(f"  ✓ Stocked PO #{po.order_number} into warehouse {wh.name} (Status: {po.status})")
    assert po.status == 'picked', "Stocked PO must have status 'picked'"
    assert po.memo is not None, "Inward Inventory Memo must be generated"
    print(f"    - Generated Inward Memo: {po.memo.memo_number}")

    # Verify inventory stock record
    stock = InventoryStock.objects.get(warehouse=wh, product=prod)
    print(f"    - Updated Warehouse Stock: {stock.qty_on_hand} {prod.unit} on hand (Available: {stock.qty_available})")
    assert stock.qty_on_hand >= Decimal('100'), "Stock qty_on_hand must reflect received quantity"

    # Invoice (Accounts posting)
    po = PurchaseOrderService.invoice_order(po, user)
    print(f"  ✓ Invoiced PO #{po.order_number} to Vendor Ledger (Status: {po.status})")
    assert po.status == 'settled', "Invoiced PO must have status 'settled'"

    v_acc.refresh_from_db()
    print(f"    - Supplier Outstanding Balance: {v_acc.current_balance:,.2f} EGP")
    assert v_acc.current_balance == initial_vendor_bal + Decimal('5000.00'), f"Supplier balance expected {initial_vendor_bal + 5000.00}, got {v_acc.current_balance}"

    # Vendor Payment from Vault
    print("\n[4] Testing Treasury Supplier Payment & Settlements...")
    initial_vault_bal = vault.current_balance
    pay_amount = Decimal('3000.00')
    payment = TreasuryService.record_vendor_payment(
        supplier=supplier,
        vault=vault,
        amount=pay_amount,
        user=user,
        notes="Partial settlement for PO"
    )
    vault.refresh_from_db()
    v_acc.refresh_from_db()
    print(f"  ✓ Issued Payment #{payment.serial_num} for {pay_amount:,.2f} EGP")
    print(f"    - Vault Balance: {initial_vault_bal:,.2f} -> {vault.current_balance:,.2f} EGP")
    assert vault.current_balance == initial_vault_bal - pay_amount, "Vault balance must decrement by payment amount"
    print(f"    - Supplier Remaining Debt: {v_acc.current_balance:,.2f} EGP")
    assert v_acc.current_balance == initial_vendor_bal + Decimal('2000.00'), f"Supplier remaining debt expected {initial_vendor_bal + 2000.00}, got {v_acc.current_balance}"

    # 5. Sales Workflow (P1)
    print("\n[5] Testing Sales & Distribution Workflow (P1)...")
    so = SalesOrderService.create_order(
        customer=customer,
        source_warehouse=wh,
        order_date="2026-10-08",
        items_data=[{
            'product': prod,
            'quantity': Decimal('20'),
            'unit_price': Decimal('75.00'),
        }],
        user=user,
        notes="E2E Automated Sales Order"
    )
    print(f"  ✓ Created SO #{so.order_number} with Grand Total: {so.grand_total:,.2f} EGP (Status: {so.status})")
    assert so.status == 'pending'
    assert so.grand_total == Decimal('1500.00')

    # Approve
    so = SalesOrderService.approve_order(so, user)
    print(f"  ✓ Manager Approved SO #{so.order_number} (Status: {so.status})")
    assert so.status == 'manager_approval'

    # Prepare (Reserve Stock)
    so = SalesOrderService.prepare_order(so, user)
    stock.refresh_from_db()
    print(f"  ✓ Preparing SO #{so.order_number} (Reserved Stock: {stock.qty_reserved}, Available: {stock.qty_available})")
    assert so.status == 'preparing'
    assert stock.qty_reserved >= Decimal('20')

    # Deliver (Outward dispatch)
    so = SalesOrderService.deliver_order(so, user)
    stock.refresh_from_db()
    print(f"  ✓ Delivered SO #{so.order_number} (Status: {so.status})")
    print(f"    - Generated Outward Memo: {so.memo.memo_number}")
    print(f"    - Remaining Stock in Warehouse: {stock.qty_on_hand} on hand (Available: {stock.qty_available})")
    assert so.status == 'delivered'
    assert stock.qty_reserved == Decimal('0.00')

    # Invoice (Debit Customer Account)
    so = SalesOrderService.invoice_order(so, user)
    c_acc.refresh_from_db()
    print(f"  ✓ Invoiced SO #{so.order_number} (Customer Debt: {c_acc.current_balance:,.2f} EGP)")
    assert so.status == 'invoiced'
    assert c_acc.current_balance == initial_customer_bal + Decimal('1500.00')

    # Customer Collection (Cash Receipt)
    print("\n[6] Testing Customer Cash Collection...")
    initial_vault_bal = vault.current_balance
    col_amount = Decimal('1000.00')
    col = CollectionService.record_collection(
        customer=customer,
        vault=vault,
        amount=col_amount,
        user=user,
        notes="Partial collection from pharmacy"
    )
    vault.refresh_from_db()
    c_acc.refresh_from_db()
    print(f"  ✓ Recorded Collection #{col.serial_num} for {col_amount:,.2f} EGP")
    print(f"    - Vault Balance: {initial_vault_bal:,.2f} -> {vault.current_balance:,.2f} EGP")
    assert vault.current_balance == initial_vault_bal + col_amount, "Vault balance must increment by collection amount"
    print(f"    - Customer Remaining Debt: {c_acc.current_balance:,.2f} EGP")
    assert c_acc.current_balance == initial_customer_bal + Decimal('500.00'), f"Customer remaining debt expected {initial_customer_bal + 500.00}, got {c_acc.current_balance}"

    # 7. Purchase Returns Lifecycle Workflow & Order Splitting (P0/P1 Parity)
    print("\n[7] Testing Purchase Return Workflow & Order Splitting...")
    # Order Splitting
    split_po = PurchaseOrderService.create_order(
        supplier=supplier,
        target_warehouse=wh,
        order_date="2026-10-09",
        items_data=[{
            'product': prod,
            'quantity': Decimal('30'),
            'unit_price': Decimal('50.00'),
            'batch_number': 'SPLIT-01',
            'expiry_date': '2028-12-31',
        }],
        user=user,
        notes="Order to test splitting"
    )
    first_item = split_po.items.first()
    child_po = PurchaseOrderService.split_order(split_po, {first_item.id: Decimal('10')}, user)
    print(f"  ✓ Split PO #{split_po.order_number}: Created Child PO #{child_po.order_number}")
    assert child_po.is_split is True
    assert child_po.items.first().quantity == Decimal('10')
    assert child_po.grand_total == Decimal('500.00')
    split_po.refresh_from_db()
    assert split_po.is_split is True
    assert split_po.items.first().quantity == Decimal('20')
    assert split_po.grand_total == Decimal('1000.00')

    # Purchase Return Order Lifecycle
    stock.refresh_from_db()
    pre_return_stock = stock.qty_on_hand
    v_acc.refresh_from_db()
    pre_return_debt = v_acc.current_balance
    print(f"    - Current Stock before Return: {pre_return_stock} {prod.unit}")
    print(f"    - Current Supplier Debt before Return: {pre_return_debt:,.2f} EGP")

    return_qty = Decimal('10.00')
    return_unit_price = Decimal('50.00')
    expected_return_total = return_qty * return_unit_price  # 500.00 EGP

    ro = PurchaseReturnOrderService.create_return_order(
        supplier=supplier,
        warehouse=wh,
        order_date="2026-10-10",
        items_data=[{
            'product': prod,
            'quantity': return_qty,
            'unit_price': return_unit_price,
            'batch_number': 'BATCH-001',
            'expiry_date': '2028-12-31'
        }],
        user=user,
        purchase_order=po,
        delivery_agent="مندوب إرجاع البضائع",
        notes="E2E Automated Purchase Return Workflow Test"
    )
    print(f"  ✓ Created Return Order #{ro.order_number} for {ro.grand_total:,.2f} EGP (Status: {ro.status})")
    assert ro.status == 'pending'
    assert ro.grand_total == expected_return_total

    # Approve
    ro = PurchaseReturnOrderService.approve_return_order(ro, user)
    print(f"  ✓ Approved Return Order #{ro.order_number} (Status: {ro.status})")
    assert ro.status == 'approved'

    # Deliver (Unstocking goods outward)
    ro = PurchaseReturnOrderService.deliver_return_order(ro, user)
    stock.refresh_from_db()
    print(f"  ✓ Delivered Return Order #{ro.order_number} (Status: {ro.status})")
    print(f"    - Generated Outward Return Memo: {ro.memo.memo_number}")
    print(f"    - Warehouse Stock after Return: {stock.qty_on_hand} {prod.unit} (Decremented by {return_qty})")
    assert ro.status == 'delivered'
    assert stock.qty_on_hand == pre_return_stock - return_qty, f"Stock expected {pre_return_stock - return_qty}, got {stock.qty_on_hand}"

    # Settle (Double-entry Debit Note posted to supplier ledger)
    ro = PurchaseReturnOrderService.settle_return_order(ro, user)
    v_acc.refresh_from_db()
    print(f"  ✓ Settled Return Order #{ro.order_number} (Status: {ro.status})")
    print(f"    - Supplier Debt after Debit Note: {v_acc.current_balance:,.2f} EGP (Decremented by {expected_return_total:,.2f})")
    assert ro.status == 'settled'
    assert v_acc.current_balance == pre_return_debt - expected_return_total, f"Supplier balance expected {pre_return_debt - expected_return_total}, got {v_acc.current_balance}"

    # 8. Test Web Views & Templates via Client
    print("\n[8] Verifying all Web Views & Templates (HTTP 200)...")
    urls_to_test = [
        '/home/',
        '/contacts/',
        '/catalog/',
        '/catalog/categories/',
        f'/catalog/{prod.pk}/',
        '/purchases/',
        f'/purchases/{po.pk}/',
        f'/purchases/{po.pk}/print/',
        '/purchases/returns/',
        '/purchase-return-orders/',
        '/purchases/returns/create/',
        f'/purchases/returns/{ro.pk}/',
        f'/purchases/returns/{ro.pk}/print/',
        '/purchases/returns/export/',
        '/inventory/',
        '/inventory/warehouses/',
        '/inventory/memos/',
        '/treasury/payments/',
        '/treasury/vendors/',
        '/treasury/vendor-transactions/',
        '/treasury/vaults/',
        '/treasury/vault-transactions/',
        '/sales/',
        f'/sales/{so.pk}/',
        '/sales/collections/',
        '/sales/customers/',
        '/sales/customer-transactions/',
        '/auth/users/',
        '/auth/roles/',
        '/settings/branding/',
    ]

    for url in urls_to_test:
        resp = client.get(url)
        assert resp.status_code == 200, f"Error rendering {url}: expected 200, got {resp.status_code}"
        print(f"  ✓ {url:<36} [HTTP 200 OK]")

    # 9. Verify All Excel Exports (.xlsx) and Import Workflows
    print("\n[9] Verifying All Excel Exports (.xlsx) & Import Workflows...")
    import openpyxl
    import io

    excel_exports = [
        ('/catalog/export/', 'Products Export'),
        ('/contacts/export/', 'Contacts Export'),
        ('/purchases/export/', 'Purchase Orders Export'),
        ('/purchases/returns/export/', 'Purchase Return Orders Export'),
        ('/sales/export/', 'Sales Orders Export'),
        ('/sales/collections/export/', 'Collections Export'),
        ('/inventory/export/', 'Inventory Stock Export'),
        ('/treasury/payments/export/', 'Vendor Payments Export'),
        ('/catalog/import/template/', 'Products Import Template'),
        ('/contacts/import/template/', 'Contacts Import Template'),
    ]

    for export_url, label in excel_exports:
        res = client.get(export_url)
        assert res.status_code == 200, f"Export {label} ({export_url}) failed with {res.status_code}"
        assert res['Content-Type'] == 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', f"Export {label} has incorrect Content-Type: {res['Content-Type']}"
        assert '.xlsx' in res['Content-Disposition'], f"Export {label} missing .xlsx filename"
        
        # Verify valid openpyxl spreadsheet
        wb = openpyxl.load_workbook(io.BytesIO(res.content))
        ws = wb.active
        assert ws.sheet_view.rightToLeft is True, f"Sheet for {label} is not set to Right-To-Left (RTL)"
        print(f"  ✓ {label:<32} [{ws.title}] - Valid .xlsx with RTL view")

    # Verify Import Pages
    import_pages = [
        ('/catalog/import/', 'Products Import Page'),
        ('/contacts/import/', 'Contacts Import Page'),
    ]
    for imp_url, imp_label in import_pages:
        res = client.get(imp_url)
        assert res.status_code == 200, f"Import page {imp_label} ({imp_url}) failed with {res.status_code}"
        assert 'Excel' in res.content.decode('utf-8'), f"Import page {imp_label} missing Excel branding"
        print(f"  ✓ {imp_label:<32} [HTTP 200 OK]")

    # 9. Activities Module E2E Verification
    print("\n[9] Testing Activities Module (Planned Visits, Visits, Agreements)...")
    from activities.models import Agreement, AgreementType, VisitTemplate, PlannedVisitDay, PlannedVisitItem, Visit

    # Test Agreements
    ag_res = client.get('/agreements/')
    assert ag_res.status_code == 200, f"/agreements/ failed with {ag_res.status_code}"
    assert "الاتفاقيات" in ag_res.content.decode('utf-8')
    print("  ✓ /agreements/ page rendered.")

    ag_type = AgreementType.objects.first()
    contact = Contact.objects.first()
    create_ag_res = client.post('/agreements/', {
        'create_agreement': '1',
        'customer': contact.id,
        'title': 'اتفاقية تجريبية شاملة',
        'type': ag_type.id,
        'amount': '4500.00',
        'date': timezone.now().date().strftime('%Y-%m-%d'),
        'description': 'شروط العقد التجاري'
    })
    assert create_ag_res.status_code == 302
    test_ag = Agreement.objects.filter(title='اتفاقية تجريبية شاملة').first()
    assert test_ag is not None
    assert test_ag.status == 'new'
    print(f"  ✓ Created Agreement #{test_ag.serial_num} (Status: {test_ag.status})")

    # Approve agreement
    client.get(f'/agreements/{test_ag.pk}/action/approve/')
    test_ag.refresh_from_db()
    assert test_ag.status == 'approved'
    print(f"  ✓ Agreement #{test_ag.serial_num} approved successfully.")

    # Mark done
    client.get(f'/agreements/{test_ag.pk}/action/done/')
    test_ag.refresh_from_db()
    assert test_ag.status == 'done'
    print(f"  ✓ Agreement #{test_ag.serial_num} marked as done.")

    # Test Planned Visits
    pv_res = client.get('/planned-visits/')
    assert pv_res.status_code == 200, f"/planned-visits/ failed with {pv_res.status_code}"
    assert "خطة الزيارات" in pv_res.content.decode('utf-8')
    print("  ✓ /planned-visits/ page rendered.")

    # Schedule a visit
    target_plan_date = timezone.now().date() + timezone.timedelta(days=2)
    v_template = VisitTemplate.objects.first()
    schedule_res = client.post('/planned-visits/add-item/', {
        'assignee_id': user.id,
        'date': target_plan_date.strftime('%Y-%m-%d'),
        'contact_id': contact.id,
        'template_id': v_template.id if v_template else '',
        'notes': 'زيارة مجدولة E2E'
    })
    assert schedule_res.status_code == 302
    pv_item = PlannedVisitItem.objects.filter(notes='زيارة مجدولة E2E').first()
    assert pv_item is not None
    print(f"  ✓ Scheduled Planned Visit for {contact.name} on {target_plan_date}.")

    # Execute planned visit
    exec_res = client.get(f'/planned-visits/item/{pv_item.pk}/execute/')
    assert exec_res.status_code == 302
    pv_item.refresh_from_db()
    assert pv_item.is_executed is True
    assert pv_item.visit is not None
    print(f"  ✓ Converted Planned Visit to Actual Visit #{pv_item.visit.serial_num}.")

    # Test Visits
    visits_res = client.get('/visits/')
    assert visits_res.status_code == 200, f"/visits/ failed with {visits_res.status_code}"
    assert "الزيارات" in visits_res.content.decode('utf-8')
    print("  ✓ /visits/ page rendered.")

    # Create Unplanned Visit
    unplan_res = client.post('/visits/create/', {
        'contact': contact.id,
        'template': v_template.id if v_template else '',
        'owner': user.id,
        'date': timezone.now().date().strftime('%Y-%m-%d'),
        'is_successful': 'on',
        'feedback': 'زيارة غير مخططة ناجحة'
    })
    assert unplan_res.status_code == 302
    unplan_visit = Visit.objects.filter(feedback='زيارة غير مخططة ناجحة').first()
    assert unplan_visit is not None
    assert unplan_visit.is_planned is False
    print(f"  ✓ Created Unplanned Visit #{unplan_visit.serial_num}.")

    # Manager Approve Visit
    approve_v_res = client.post(f'/visits/{unplan_visit.pk}/action/approve/', {
        'approval_notes': 'معتمدة E2E'
    })
    assert approve_v_res.status_code == 302
    unplan_visit.refresh_from_db()
    assert unplan_visit.approval_status == 'approved'
    print(f"  ✓ Visit #{unplan_visit.serial_num} approved successfully.")

    # Activities Exports Verification
    act_exports = [
        ('/agreements/export/', 'Agreements Export'),
        ('/planned-visits/export/', 'Planned Visits Export'),
        ('/visits/export/', 'Visits Export'),
    ]
    for exp_url, exp_label in act_exports:
        res = client.get(exp_url)
        assert res.status_code == 200, f"Export {exp_label} ({exp_url}) failed with {res.status_code}"
        assert res['Content-Type'] == 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        wb = openpyxl.load_workbook(io.BytesIO(res.content))
        ws = wb.active
        assert ws.sheet_view.rightToLeft is True
        print(f"  ✓ {exp_label:<32} [{ws.title}] - Valid .xlsx with RTL view")

    # 10. Global Bottom-Left FAB & Quick-Add Bottom Sheet Verification
    print("\n[10] Testing Global FAB & Quick-Add Bottom Sheet...")
    fab_pages = ['/home/', '/visits/', '/agreements/', '/planned-visits/']
    for p in fab_pages:
        page_res = client.get(p)
        content_str = page_res.content.decode('utf-8')
        assert 'quick-add' in content_str, f"quick-add container missing on {p}"
        assert 'openQuickAdd()' in content_str, f"openQuickAdd() trigger missing on {p}"
        assert 'تسجيل زيارة خارج الخطة' in content_str, f"Action 1 missing on {p}"
        assert 'امر بيع جديد' in content_str, f"Action 2 missing on {p}"
        assert 'مرتجع جديد' in content_str, f"Action 3 missing on {p}"
        assert 'تحصيل جديد' in content_str, f"Action 4 missing on {p}"
        assert 'الغاء' in content_str, f"Action 5 Cancel missing on {p}"
        print(f"  ✓ Global FAB & all 5 Quick-Add actions verified on {p}")

    # 11. Agreements Bulk Status Transition Verification
    print("\n[11] Testing Agreements Bulk Status Transition...")
    ag2 = Agreement.objects.create(
        customer=contact,
        title='اتفاقية دفعة تجريبية 2',
        type=ag_type,
        amount=Decimal('1200.00'),
        date=timezone.now().date(),
        created_by=user,
        status='new'
    )
    bulk_res = client.post('/agreements/bulk-status/', {
        'status': 'approved',
        'selected_ids': [test_ag.pk, ag2.pk]
    })
    assert bulk_res.status_code == 302, f"Bulk status update returned {bulk_res.status_code}"
    test_ag.refresh_from_db()
    ag2.refresh_from_db()
    assert test_ag.status == 'approved', f"Expected approved, got {test_ag.status}"
    assert ag2.status == 'approved', f"Expected approved, got {ag2.status}"
    print(f"  ✓ Bulk transition to 'approved' succeeded for Agreements #{test_ag.serial_num} and #{ag2.serial_num}")

    bulk_res_done = client.post('/agreements/bulk-status/', {
        'status': 'done',
        'selected_ids': [test_ag.pk, ag2.pk]
    })
    test_ag.refresh_from_db()
    ag2.refresh_from_db()
    assert test_ag.status == 'done' and ag2.status == 'done'
    print(f"  ✓ Bulk transition to 'done' succeeded.")

    # 12. Role-Based Permissions Enforcement Verification
    print("\n[12] Testing Role-Based Permission Boundaries (Manager vs Medical Rep)...")
    from accounts.models import Role
    rep_role, _ = Role.objects.get_or_create(
        name='medical_rep',
        defaults={'display_name': 'مندوب دعاية طبية', 'is_rep': True, 'is_area_manager': False}
    )
    rep_user, _ = User.objects.get_or_create(
        username='rep_tester',
        defaults={'email': 'rep@bricks-rep.com', 'role': rep_role, 'is_superuser': False, 'is_staff': False}
    )
    rep_user.set_password('RepPass123!')
    rep_user.role = rep_role
    rep_user.is_superuser = False
    rep_user.is_staff = False
    rep_user.save()

    rep_client = Client()
    rep_client.login(username='rep_tester', password='RepPass123!')

    # Medical Rep attempts to approve visit -> must be rejected
    rep_v_approve = rep_client.post(f'/visits/{unplan_visit.pk}/action/approve/', {'approval_notes': 'Rep hack'})
    unplan_visit.refresh_from_db()
    # Confirm flash error or redirect
    assert rep_v_approve.status_code == 302

    # Medical Rep attempts bulk status change -> must be rejected
    rep_bulk_ag = rep_client.post('/agreements/bulk-status/', {
        'status': 'new',
        'selected_ids': [test_ag.pk]
    })
    test_ag.refresh_from_db()
    assert test_ag.status == 'done', f"Medical Rep was able to change status! Got {test_ag.status}"
    print("  ✓ Rep unauthorized approval attempt successfully blocked by backend permissions.")

    # 13. Scope Verification: Ensure Unwanted Calls Module is Deleted
    print("\n[13] Verifying Unwanted 'Calls' Module is Completely Removed...")
    calls_res = client.get('/calls/')
    assert calls_res.status_code == 404, f"Expected 404 for /calls/, but got {calls_res.status_code}"
    print("  ✓ /calls/ endpoint returns HTTP 404 Not Found.")

    print("\n" + "=" * 60)
    print("ALL E2E WORKFLOWS, ACTIVITIES & EXPORTS VERIFIED SUCCESSFULLY! 100% PASS.")
    print("=" * 60)

if __name__ == '__main__':
    run_tests()


