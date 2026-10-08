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
from django.contrib.auth import get_user_model
from contacts.models import Contact
from catalog.models import Product, ProductCategory
from inventory.models import Warehouse, InventoryStock, InventoryMemo
from purchases.models import PurchaseOrder, PurchaseOrderItem
from purchases.services import PurchaseOrderService
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
    login_success = client.login(username='wea.pharm2020@gmail.com', password='Wea@0000')
    assert login_success, "Login failed with credentials wea.pharm2020@gmail.com / Wea@0000"
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

    # 7. Test Web Views & Templates via Client
    print("\n[7] Verifying all Web Views & Templates (HTTP 200)...")
    urls_to_test = [
        '/home/',
        '/contacts/',
        '/catalog/',
        '/catalog/categories/',
        '/purchases/',
        f'/purchases/{po.pk}/',
        f'/purchases/{po.pk}/print/',
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

    print("\n" + "=" * 60)
    print("ALL E2E WORKFLOWS AND PAGES VERIFIED SUCCESSFULLY! 100% PASS.")
    print("=" * 60)

if __name__ == '__main__':
    run_tests()
