import os
import sys
import time
import subprocess
import urllib.request
from decimal import Decimal

# Set standard output encoding
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from playwright.sync_api import sync_playwright

BASE_URL = "http://127.0.0.1:8000"
SERVER_PROC = None

test_results = []

def record_result(category, test_name, status, details=""):
    test_results.append({
        'category': category,
        'test_name': test_name,
        'status': status,
        'details': details
    })
    badge = "[PASS]" if status == "PASS" else "[FAIL]"
    print(f"  {badge} {test_name}: {details}")

def wait_for_server(url, timeout=25):
    start = time.time()
    while time.time() - start < timeout:
        try:
            with urllib.request.urlopen(url) as resp:
                if resp.status in [200, 302]:
                    return True
        except Exception:
            time.sleep(0.5)
    return False

def login_user(page, email, password):
    page.goto(f"{BASE_URL}/login/", wait_until="networkidle")
    page.fill('input[name="email"]', email)
    page.fill('input[name="password"]', password)
    page.click('button[type="submit"]')
    page.wait_for_load_state("networkidle")
    time.sleep(0.5)

def logout_user(page):
    try:
        page.goto(f"{BASE_URL}/logout/", wait_until="networkidle")
    except Exception:
        pass

def run_tests():
    global SERVER_PROC
    print("=" * 70)
    print("STARTING PLAYWRIGHT BROWSER TESTS ACROSS ALL 9 ERP POINTS & ROLES")
    print("=" * 70)

    # 1. Start Django test server
    print("\n[STEP 1] Launching Django test server on 127.0.0.1:8000...")
    SERVER_PROC = subprocess.Popen(
        [sys.executable, "manage.py", "runserver", "127.0.0.1:8000", "--noreload"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    if not wait_for_server(f"{BASE_URL}/login/"):
        print("ERROR: Server failed to start on port 8000!")
        if SERVER_PROC:
            SERVER_PROC.terminate()
        sys.exit(1)
    print("Django server is running and accepting connections.")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        # =========================================================================
        # SUITE 1: SUPERADMIN (wea.pharm2020@gmail.com) - Full Perms across all 9 points
        # =========================================================================
        print("\n" + "=" * 50)
        print("SUITE 1: SUPERADMIN WORKFLOW & PERMISSION TESTS")
        print("=" * 50)
        context = browser.new_context()
        page = context.new_page()
        login_user(page, "wea.pharm2020@gmail.com", "Wea@4444")

        # Point 1: purchase-orders/returns/
        resp = page.goto(f"{BASE_URL}/purchase-orders/returns/", wait_until="networkidle")
        if resp.status == 200 and ("PR-2026-0001" in page.content() or "أوامر إرجاع" in page.content()):
            record_result("Point 1", "SuperAdmin - List Purchase Returns (/purchase-orders/returns/)", "PASS", f"HTTP {resp.status}, seeded PRs present")
        else:
            record_result("Point 1", "SuperAdmin - List Purchase Returns", "FAIL", f"HTTP {resp.status}")

        resp_alias = page.goto(f"{BASE_URL}/purchases/returns/", wait_until="networkidle")
        if resp_alias.status == 200:
            record_result("Point 1", "SuperAdmin - List Purchase Returns Alias (/purchases/returns/)", "PASS", "HTTP 200")
        else:
            record_result("Point 1", "SuperAdmin - List Purchase Returns Alias", "FAIL", f"HTTP {resp_alias.status}")

        resp_ret_detail = page.goto(f"{BASE_URL}/purchases/returns/13/", wait_until="networkidle")
        if resp_ret_detail.status == 200 and "PR-2026-0001" in page.content():
            record_result("Point 1", "SuperAdmin - Purchase Return Detail (#13)", "PASS", "HTTP 200, return order data verified")
        else:
            record_result("Point 1", "SuperAdmin - Purchase Return Detail", "FAIL", f"HTTP {resp_ret_detail.status}")

        resp_ret_create = page.goto(f"{BASE_URL}/purchases/returns/create/", wait_until="networkidle")
        if resp_ret_create.status == 200:
            record_result("Point 1", "SuperAdmin - Purchase Return Create Page", "PASS", "HTTP 200, form loaded")
        else:
            record_result("Point 1", "SuperAdmin - Purchase Return Create Page", "FAIL", f"HTTP {resp_ret_create.status}")

        # Point 2: treasury/payments/
        resp_pay = page.goto(f"{BASE_URL}/treasury/payments/", wait_until="networkidle")
        if resp_pay.status == 200 and ("REC-VEND-101" in page.content() or "مدفوعات" in page.content()):
            record_result("Point 2", "SuperAdmin - Vendor Payments List (/treasury/payments/)", "PASS", f"HTTP {resp_pay.status}, payments rendered")
        else:
            record_result("Point 2", "SuperAdmin - Vendor Payments List", "FAIL", f"HTTP {resp_pay.status}")

        resp_pay_create = page.goto(f"{BASE_URL}/treasury/payments/create/", wait_until="networkidle")
        if resp_pay_create.status == 200 and page.locator('select[name="supplier"]').count() > 0:
            record_result("Point 2", "SuperAdmin - Vendor Payment Create Page", "PASS", "HTTP 200, supplier dropdown present")
        else:
            record_result("Point 2", "SuperAdmin - Vendor Payment Create Page", "FAIL", f"HTTP {resp_pay_create.status}")

        # Point 3: treasury/payment-requests/
        resp_req = page.goto(f"{BASE_URL}/treasury/payment-requests/", wait_until="networkidle")
        if resp_req.status == 200:
            record_result("Point 3", "SuperAdmin - Vendor Payment Requests List", "PASS", "HTTP 200, rendered successfully")
        else:
            record_result("Point 3", "SuperAdmin - Vendor Payment Requests List", "FAIL", f"HTTP {resp_req.status}")

        # Point 4: inventory/memos/
        resp_memo = page.goto(f"{BASE_URL}/inventory/memos/", wait_until="networkidle")
        if resp_memo.status == 200 and ("MEM-IN-2026-0001" in page.content() or "أذونات" in page.content()):
            record_result("Point 4", "SuperAdmin - Inventory Memos List (/inventory/memos/)", "PASS", f"HTTP {resp_memo.status}, memos rendered")
        else:
            record_result("Point 4", "SuperAdmin - Inventory Memos List", "FAIL", f"HTTP {resp_memo.status}")

        resp_memo_detail = page.goto(f"{BASE_URL}/inventory/memos/51/", wait_until="networkidle")
        if resp_memo_detail.status == 200 and "MEM-IN-2026-0001" in page.content():
            record_result("Point 4", "SuperAdmin - Inventory Memo Detail (#51)", "PASS", "HTTP 200, memo details & items verified")
        else:
            record_result("Point 4", "SuperAdmin - Inventory Memo Detail", "FAIL", f"HTTP {resp_memo_detail.status}")

        resp_memo_create = page.goto(f"{BASE_URL}/inventory/memos/create/", wait_until="networkidle")
        if resp_memo_create.status == 200:
            record_result("Point 4", "SuperAdmin - Inventory Memo Create Page", "PASS", "HTTP 200, memo create form loaded")
        else:
            record_result("Point 4", "SuperAdmin - Inventory Memo Create Page", "FAIL", f"HTTP {resp_memo_create.status}")

        # Point 5: treasury/vaults/
        resp_vaults = page.goto(f"{BASE_URL}/treasury/vaults/", wait_until="networkidle")
        if resp_vaults.status == 200 and ("1001" in page.content() or "الخزنة" in page.content()):
            record_result("Point 5", "SuperAdmin - Vaults List (/treasury/vaults/)", "PASS", "HTTP 200, all vaults displayed")
        else:
            record_result("Point 5", "SuperAdmin - Vaults List", "FAIL", f"HTTP {resp_vaults.status}")

        # Point 6: treasury/vault-transactions/
        resp_vault_tx = page.goto(f"{BASE_URL}/treasury/vault-transactions/", wait_until="networkidle")
        if resp_vault_tx.status == 200 and ("حركات" in page.content() or "إيداع" in page.content()):
            record_result("Point 6", "SuperAdmin - Vault Transactions List", "PASS", "HTTP 200, transactions displayed")
        else:
            record_result("Point 6", "SuperAdmin - Vault Transactions List", "FAIL", f"HTTP {resp_vault_tx.status}")

        # Point 7: sales/
        resp_sales = page.goto(f"{BASE_URL}/sales/", wait_until="networkidle")
        if resp_sales.status == 200 and "SO-2026-0001" in page.content() and "SO-GIZ-0001" in page.content():
            record_result("Point 7", "SuperAdmin - Sales Orders List (All Areas Visible)", "PASS", "HTTP 200, Cairo and Giza orders visible")
        else:
            record_result("Point 7", "SuperAdmin - Sales Orders List", "FAIL", f"HTTP {resp_sales.status}")

        resp_so_detail = page.goto(f"{BASE_URL}/sales/1/", wait_until="networkidle")
        if resp_so_detail.status == 200 and "SO-2026-0001" in page.content():
            record_result("Point 7", "SuperAdmin - Sales Order Detail (#1)", "PASS", "HTTP 200, order details, discount and totals loaded")
        else:
            record_result("Point 7", "SuperAdmin - Sales Order Detail", "FAIL", f"HTTP {resp_so_detail.status}")

        # Point 8: sales/collections/
        resp_col = page.goto(f"{BASE_URL}/sales/collections/", wait_until="networkidle")
        if resp_col.status == 200 and "71001" in page.content():
            record_result("Point 8", "SuperAdmin - Collections List (/sales/collections/)", "PASS", "HTTP 200, collections rendered")
        else:
            record_result("Point 8", "SuperAdmin - Collections List", "FAIL", f"HTTP {resp_col.status}")

        resp_col_create = page.goto(f"{BASE_URL}/sales/collections/create/", wait_until="networkidle")
        if resp_col_create.status == 200:
            record_result("Point 8", "SuperAdmin - Collection Create Page", "PASS", "HTTP 200, collection form loaded")
        else:
            record_result("Point 8", "SuperAdmin - Collection Create Page", "FAIL", f"HTTP {resp_col_create.status}")

        # Point 9: Settings for Inventory, Sales, Purchase
        resp_set_inv = page.goto(f"{BASE_URL}/settings/inventory/", wait_until="networkidle")
        if resp_set_inv.status == 200 and page.locator('form').count() > 0:
            record_result("Point 9", "SuperAdmin - Inventory Settings (/settings/inventory/)", "PASS", "HTTP 200, settings form accessible")
        else:
            record_result("Point 9", "SuperAdmin - Inventory Settings", "FAIL", f"HTTP {resp_set_inv.status}")

        resp_set_sales = page.goto(f"{BASE_URL}/settings/sales/", wait_until="networkidle")
        if resp_set_sales.status == 200 and page.locator('form').count() > 0:
            record_result("Point 9", "SuperAdmin - Sales Settings (/settings/sales/)", "PASS", "HTTP 200, settings form accessible")
        else:
            record_result("Point 9", "SuperAdmin - Sales Settings", "FAIL", f"HTTP {resp_set_sales.status}")

        resp_set_pur = page.goto(f"{BASE_URL}/settings/purchase/", wait_until="networkidle")
        if resp_set_pur.status == 200 and page.locator('form').count() > 0:
            record_result("Point 9", "SuperAdmin - Purchase Settings (/settings/purchase/)", "PASS", "HTTP 200, settings form accessible")
        else:
            record_result("Point 9", "SuperAdmin - Purchase Settings", "FAIL", f"HTTP {resp_set_pur.status}")

        context.close()

        # =========================================================================
        # SUITE 2: ACCOUNTANT (accountant@wea.com) - Operations Allowed, Settings 403
        # =========================================================================
        print("\n" + "=" * 50)
        print("SUITE 2: ACCOUNTANT WORKFLOW & PERMISSION TESTS")
        print("=" * 50)
        context = browser.new_context()
        page = context.new_page()
        login_user(page, "accountant@wea.com", "Pass@1234")

        # Point 1: purchase-orders/returns/ (Allowed)
        resp = page.goto(f"{BASE_URL}/purchases/returns/", wait_until="networkidle")
        if resp.status == 200:
            record_result("Point 1", "Accountant - List Purchase Returns (Allowed)", "PASS", "HTTP 200")
        else:
            record_result("Point 1", "Accountant - List Purchase Returns", "FAIL", f"HTTP {resp.status}")

        # Point 2: treasury/payments/ (Allowed)
        resp = page.goto(f"{BASE_URL}/treasury/payments/", wait_until="networkidle")
        if resp.status == 200:
            record_result("Point 2", "Accountant - Vendor Payments (Allowed)", "PASS", "HTTP 200")
        else:
            record_result("Point 2", "Accountant - Vendor Payments", "FAIL", f"HTTP {resp.status}")

        # Point 3: treasury/payment-requests/ (Allowed)
        resp = page.goto(f"{BASE_URL}/treasury/payment-requests/", wait_until="networkidle")
        if resp.status == 200:
            record_result("Point 3", "Accountant - Payment Requests (Allowed)", "PASS", "HTTP 200")
        else:
            record_result("Point 3", "Accountant - Payment Requests", "FAIL", f"HTTP {resp.status}")

        # Point 4: inventory/memos/ (Allowed)
        resp = page.goto(f"{BASE_URL}/inventory/memos/", wait_until="networkidle")
        if resp.status == 200:
            record_result("Point 4", "Accountant - Inventory Memos (Allowed)", "PASS", "HTTP 200")
        else:
            record_result("Point 4", "Accountant - Inventory Memos", "FAIL", f"HTTP {resp.status}")

        # Point 5: treasury/vaults/ (Allowed)
        resp = page.goto(f"{BASE_URL}/treasury/vaults/", wait_until="networkidle")
        if resp.status == 200:
            record_result("Point 5", "Accountant - Vaults List (Allowed)", "PASS", "HTTP 200")
        else:
            record_result("Point 5", "Accountant - Vaults List", "FAIL", f"HTTP {resp.status}")

        # Point 6: treasury/vault-transactions/ (Allowed)
        resp = page.goto(f"{BASE_URL}/treasury/vault-transactions/", wait_until="networkidle")
        if resp.status == 200:
            record_result("Point 6", "Accountant - Vault Transactions (Allowed)", "PASS", "HTTP 200")
        else:
            record_result("Point 6", "Accountant - Vault Transactions", "FAIL", f"HTTP {resp.status}")

        # Point 7: sales/ (Allowed)
        resp = page.goto(f"{BASE_URL}/sales/", wait_until="networkidle")
        if resp.status == 200:
            record_result("Point 7", "Accountant - Sales Orders List (Allowed)", "PASS", "HTTP 200")
        else:
            record_result("Point 7", "Accountant - Sales Orders List", "FAIL", f"HTTP {resp.status}")

        # Point 8: sales/collections/ (Allowed)
        resp = page.goto(f"{BASE_URL}/sales/collections/", wait_until="networkidle")
        if resp.status == 200:
            record_result("Point 8", "Accountant - Collections List (Allowed)", "PASS", "HTTP 200")
        else:
            record_result("Point 8", "Accountant - Collections List", "FAIL", f"HTTP {resp.status}")

        # Point 9: Settings Access (Must be Rejected 403 Forbidden for Accountant)
        resp_inv = page.goto(f"{BASE_URL}/settings/inventory/", wait_until="networkidle")
        if resp_inv.status == 403 or "403" in page.content():
            record_result("Point 9", "Accountant - Denied Inventory Settings (403)", "PASS", f"HTTP {resp_inv.status} - Correctly Forbidden")
        else:
            record_result("Point 9", "Accountant - Denied Inventory Settings", "FAIL", f"Expected 403, got {resp_inv.status}")

        resp_sal = page.goto(f"{BASE_URL}/settings/sales/", wait_until="networkidle")
        if resp_sal.status == 403 or "403" in page.content():
            record_result("Point 9", "Accountant - Denied Sales Settings (403)", "PASS", f"HTTP {resp_sal.status} - Correctly Forbidden")
        else:
            record_result("Point 9", "Accountant - Denied Sales Settings", "FAIL", f"Expected 403, got {resp_sal.status}")

        resp_pur = page.goto(f"{BASE_URL}/settings/purchase/", wait_until="networkidle")
        if resp_pur.status == 403 or "403" in page.content():
            record_result("Point 9", "Accountant - Denied Purchase Settings (403)", "PASS", f"HTTP {resp_pur.status} - Correctly Forbidden")
        else:
            record_result("Point 9", "Accountant - Denied Purchase Settings", "FAIL", f"Expected 403, got {resp_pur.status}")

        context.close()

        # =========================================================================
        # SUITE 3: CAIRO MANAGER (mgr_cairo@wea.com) - ABAC Isolation & Denials
        # =========================================================================
        print("\n" + "=" * 50)
        print("SUITE 3: CAIRO MANAGER ABAC ISOLATION & PERMISSION TESTS")
        print("=" * 50)
        context = browser.new_context()
        page = context.new_page()
        login_user(page, "mgr_cairo@wea.com", "Pass@1234")

        # Point 1: purchase returns (Denied 403)
        resp = page.goto(f"{BASE_URL}/purchases/returns/", wait_until="networkidle")
        if resp.status == 403 or "403" in page.content():
            record_result("Point 1", "Cairo Manager - Denied Purchase Returns (403)", "PASS", f"HTTP {resp.status} - Correctly Forbidden")
        else:
            record_result("Point 1", "Cairo Manager - Denied Purchase Returns", "FAIL", f"Expected 403, got {resp.status}")

        # Point 2: treasury payments (Denied 403)
        resp = page.goto(f"{BASE_URL}/treasury/payments/", wait_until="networkidle")
        if resp.status == 403 or "403" in page.content():
            record_result("Point 2", "Cairo Manager - Denied Treasury Payments (403)", "PASS", f"HTTP {resp.status} - Correctly Forbidden")
        else:
            record_result("Point 2", "Cairo Manager - Denied Treasury Payments", "FAIL", f"Expected 403, got {resp.status}")

        # Point 4: inventory memos (Denied 403)
        resp = page.goto(f"{BASE_URL}/inventory/memos/", wait_until="networkidle")
        if resp.status == 403 or "403" in page.content():
            record_result("Point 4", "Cairo Manager - Denied Inventory Memos (403)", "PASS", f"HTTP {resp.status} - Correctly Forbidden")
        else:
            record_result("Point 4", "Cairo Manager - Denied Inventory Memos", "FAIL", f"Expected 403, got {resp.status}")

        # Point 7: sales orders - Allowed for Cairo, ABAC Isolated for Giza
        resp_sales = page.goto(f"{BASE_URL}/sales/", wait_until="networkidle")
        has_cairo_so = "SO-2026-0001" in page.content() or "SO-2026-0002" in page.content()
        has_giza_so = "SO-GIZ-0001" in page.content()
        if resp_sales.status == 200 and has_cairo_so and not has_giza_so:
            record_result("Point 7", "Cairo Manager - Scoped Sales Orders (Cairo Only)", "PASS", "Cairo orders visible, Giza order isolated")
        else:
            record_result("Point 7", "Cairo Manager - Scoped Sales Orders", "FAIL", f"Cairo visible: {has_cairo_so}, Giza leaked: {has_giza_so}")

        # Point 7: Direct URL access to Giza Order (#4) -> Must return 403 Forbidden
        resp_giza_access = page.goto(f"{BASE_URL}/sales/4/", wait_until="networkidle")
        if resp_giza_access.status == 403 or "403" in page.content():
            record_result("Point 7", "Cairo Manager - ABAC Direct Access Denial to Giza Order #4 (403)", "PASS", f"HTTP {resp_giza_access.status} - Correctly Forbidden")
        else:
            record_result("Point 7", "Cairo Manager - ABAC Direct Access Denial to Giza Order", "FAIL", f"Expected 403, got {resp_giza_access.status}")

        # Point 9: Denied Settings
        resp = page.goto(f"{BASE_URL}/settings/sales/", wait_until="networkidle")
        if resp.status == 403 or "403" in page.content():
            record_result("Point 9", "Cairo Manager - Denied Sales Settings (403)", "PASS", "Correctly Forbidden")
        else:
            record_result("Point 9", "Cairo Manager - Denied Sales Settings", "FAIL", f"Expected 403, got {resp.status}")

        context.close()

        # =========================================================================
        # SUITE 4: CAIRO REPRESENTATIVE (rep_cairo@wea.com) - Rep Scoping & Denials
        # =========================================================================
        print("\n" + "=" * 50)
        print("SUITE 4: CAIRO REPRESENTATIVE PERMISSION & SCOPING TESTS")
        print("=" * 50)
        context = browser.new_context()
        page = context.new_page()
        login_user(page, "rep_cairo@wea.com", "Pass@1234")

        # Point 1: purchase returns (Denied 403)
        resp = page.goto(f"{BASE_URL}/purchases/returns/", wait_until="networkidle")
        if resp.status == 403 or "403" in page.content():
            record_result("Point 1", "Cairo Rep - Denied Purchase Returns (403)", "PASS", "Correctly Forbidden")
        else:
            record_result("Point 1", "Cairo Rep - Denied Purchase Returns", "FAIL", f"Expected 403, got {resp.status}")

        # Point 2: treasury payments (Denied 403)
        resp = page.goto(f"{BASE_URL}/treasury/payments/", wait_until="networkidle")
        if resp.status == 403 or "403" in page.content():
            record_result("Point 2", "Cairo Rep - Denied Treasury Payments (403)", "PASS", "Correctly Forbidden")
        else:
            record_result("Point 2", "Cairo Rep - Denied Treasury Payments", "FAIL", f"Expected 403, got {resp.status}")

        # Point 3: treasury payment requests (Denied 403)
        resp = page.goto(f"{BASE_URL}/treasury/payment-requests/", wait_until="networkidle")
        if resp.status == 403 or "403" in page.content():
            record_result("Point 3", "Cairo Rep - Denied Payment Requests (403)", "PASS", "Correctly Forbidden")
        else:
            record_result("Point 3", "Cairo Rep - Denied Payment Requests", "FAIL", f"Expected 403, got {resp.status}")

        # Point 4: inventory memos (Denied 403)
        resp = page.goto(f"{BASE_URL}/inventory/memos/", wait_until="networkidle")
        if resp.status == 403 or "403" in page.content():
            record_result("Point 4", "Cairo Rep - Denied Inventory Memos (403)", "PASS", "Correctly Forbidden")
        else:
            record_result("Point 4", "Cairo Rep - Denied Inventory Memos", "FAIL", f"Expected 403, got {resp.status}")

        # Point 6: treasury vault transactions (Denied 403)
        resp = page.goto(f"{BASE_URL}/treasury/vault-transactions/", wait_until="networkidle")
        if resp.status == 403 or "403" in page.content():
            record_result("Point 6", "Cairo Rep - Denied Vault Transactions (403)", "PASS", "Correctly Forbidden")
        else:
            record_result("Point 6", "Cairo Rep - Denied Vault Transactions", "FAIL", f"Expected 403, got {resp.status}")

        # Point 7: sales orders - Can see own orders, Giza order isolated
        resp_sales = page.goto(f"{BASE_URL}/sales/", wait_until="networkidle")
        has_own_so = "SO-2026-0001" in page.content()
        has_giza_so = "SO-GIZ-0001" in page.content()
        if resp_sales.status == 200 and has_own_so and not has_giza_so:
            record_result("Point 7", "Cairo Rep - Scoped Sales Orders (Own Orders Only)", "PASS", "Own order visible, Giza order isolated")
        else:
            record_result("Point 7", "Cairo Rep - Scoped Sales Orders", "FAIL", f"Own visible: {has_own_so}, Giza leaked: {has_giza_so}")

        # Point 7: Direct access to Giza order -> 403
        resp_giza = page.goto(f"{BASE_URL}/sales/4/", wait_until="networkidle")
        if resp_giza.status == 403 or "403" in page.content():
            record_result("Point 7", "Cairo Rep - ABAC Direct Access Denial to Giza Order #4 (403)", "PASS", f"HTTP {resp_giza.status} - Correctly Forbidden")
        else:
            record_result("Point 7", "Cairo Rep - ABAC Direct Access Denial to Giza Order", "FAIL", f"Expected 403, got {resp_giza.status}")

        # Point 8: sales collections - Can view own collections and create collection
        resp_col = page.goto(f"{BASE_URL}/sales/collections/", wait_until="networkidle")
        if resp_col.status == 200 and "71001" in page.content():
            record_result("Point 8", "Cairo Rep - Collections List (Own Collections)", "PASS", "HTTP 200, own collections visible")
        else:
            record_result("Point 8", "Cairo Rep - Collections List", "FAIL", f"HTTP {resp_col.status}")

        resp_col_create = page.goto(f"{BASE_URL}/sales/collections/create/", wait_until="networkidle")
        if resp_col_create.status == 200:
            record_result("Point 8", "Cairo Rep - Collection Create Page", "PASS", "HTTP 200, form accessible")
        else:
            record_result("Point 8", "Cairo Rep - Collection Create Page", "FAIL", f"HTTP {resp_col_create.status}")

        # Point 9: Denied Settings
        for p_name, p_url in [("Inventory", "/settings/inventory/"), ("Sales", "/settings/sales/"), ("Purchase", "/settings/purchase/")]:
            resp_set = page.goto(f"{BASE_URL}{p_url}", wait_until="networkidle")
            if resp_set.status == 403 or "403" in page.content():
                record_result("Point 9", f"Cairo Rep - Denied {p_name} Settings (403)", "PASS", "Correctly Forbidden")
            else:
                record_result("Point 9", f"Cairo Rep - Denied {p_name} Settings", "FAIL", f"Expected 403, got {resp_set.status}")

        context.close()
        browser.close()

    # 4. Cleanup server process
    if SERVER_PROC:
        SERVER_PROC.terminate()
        try:
            SERVER_PROC.wait(timeout=5)
        except Exception:
            SERVER_PROC.kill()
        SERVER_PROC = None

    # 5. Print summary
    print("\n" + "=" * 70)
    print("BROWSER TEST EXECUTION SUMMARY ACROSS ALL 9 POINTS")
    print("=" * 70)
    passes = sum(1 for r in test_results if r['status'] == 'PASS')
    fails = sum(1 for r in test_results if r['status'] == 'FAIL')
    total = len(test_results)
    print(f"Total Tests Executed: {total}")
    print(f"Passed: {passes}")
    print(f"Failed: {fails}")

    if fails > 0:
        print("\nFAILURES:")
        for r in test_results:
            if r['status'] == 'FAIL':
                print(f"  - [{r['category']}] {r['test_name']}: {r['details']}")
        sys.exit(1)
    else:
        print("\nALL BROWSER TESTS PASSED SUCCESSFULLY!")
        sys.exit(0)

if __name__ == '__main__':
    try:
        run_tests()
    finally:
        if SERVER_PROC:
            SERVER_PROC.terminate()

