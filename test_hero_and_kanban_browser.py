import os
import sys
import time
import subprocess
import urllib.request

if sys.platform == 'win32' and __name__ == '__main__':
    import io
    if hasattr(sys.stdout, 'buffer'):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

BASE_URL = "http://127.0.0.1:8000"
SERVER_PROC = None

def ensure_server():
    global SERVER_PROC
    try:
        with urllib.request.urlopen(f"{BASE_URL}/login/", timeout=3) as resp:
            if resp.status in [200, 302]:
                print(f"[SERVER] Django server is already running at {BASE_URL}")
                return
    except Exception:
        pass

    print("[SERVER] Starting Django test server on port 8000...")
    SERVER_PROC = subprocess.Popen(
        [sys.executable, "manage.py", "runserver", "127.0.0.1:8000", "--noreload"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    start = time.time()
    while time.time() - start < 20:
        try:
            with urllib.request.urlopen(f"{BASE_URL}/login/", timeout=1) as resp:
                if resp.status in [200, 302]:
                    print("[SERVER] Server started successfully.")
                    return
        except Exception:
            time.sleep(0.5)
    raise RuntimeError("Could not start Django test server.")

def run_tests():
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    import django
    django.setup()

    from accounts.models import User
    from contacts.models import Contact
    from master_data.models import Area
    from playwright.sync_api import sync_playwright

    ensure_server()

    # Ensure admin user exists and password is set
    admin = User.objects.filter(is_superuser=True).first()
    if not admin:
        admin = User.objects.create_superuser('admin_e2e', 'admin_e2e@wea.com', 'AdminPass123!')
    else:
        admin.set_password('AdminPass123!')
        admin.save()

    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1280, 'height': 800})
        page = context.new_page()

        print("\n--- 1. AUTHENTICATION ---")
        page.goto(f"{BASE_URL}/login/", wait_until="networkidle")
        page.fill('input[name="email"]', admin.email)
        page.fill('input[name="password"]', 'AdminPass123!')
        page.click('button[type="submit"]')
        page.wait_for_load_state("networkidle")
        print(f"Logged in successfully. Current URL: {page.url}")

        print("\n--- 2. HERO SECTION RESPONSIVENESS AUDIT ---")
        pages_to_test = [
            ("Users Settings", f"{BASE_URL}/settings/users/"),
            ("Users List", f"{BASE_URL}/users/"),
            ("Inventory Settings", f"{BASE_URL}/settings/inventory/"),
            ("Sales Settings", f"{BASE_URL}/settings/sales/"),
            ("Purchase Settings", f"{BASE_URL}/settings/purchase/"),
            ("Areas Settings", f"{BASE_URL}/settings/areas/"),
            ("Branding Settings", f"{BASE_URL}/settings/branding/"),
            ("Expenses Settings", f"{BASE_URL}/settings/expenses/"),
            ("Data Sync Settings", f"{BASE_URL}/settings/sync-data/"),
            ("Vault Deposit", f"{BASE_URL}/treasury/deposit/"),
        ]

        viewports = [
            ("320px (Ultra-narrow Mobile)", 320, 568),
            ("375px (iPhone SE/Mini)", 375, 667),
            ("390px (iPhone 12/13/14)", 390, 844),
            ("430px (iPhone Pro Max)", 430, 932),
            ("1024px (Tablet/Small Desktop)", 1024, 768),
        ]

        hero_pass_count = 0
        hero_total_count = 0

        for page_name, url in pages_to_test:
            for vp_name, width, height in viewports:
                page.set_viewport_size({'width': width, 'height': height})
                page.goto(url, wait_until="domcontentloaded")
                
                # Check horizontal overflow
                overflow_info = page.evaluate("""
                    () => {
                        const docWidth = document.documentElement.scrollWidth;
                        const bodyWidth = document.body.scrollWidth;
                        const clientWidth = document.documentElement.clientWidth;
                        const windowWidth = window.innerWidth;
                        const maxScroll = Math.max(docWidth, bodyWidth);
                        const hasOverflow = maxScroll > windowWidth + 1; // 1px tolerance for subpixel rounding
                        return {
                            hasOverflow,
                            maxScroll,
                            windowWidth,
                            clientWidth
                        };
                    }
                """)

                hero_total_count += 1
                if not overflow_info['hasOverflow']:
                    hero_pass_count += 1
                    status = "PASS"
                else:
                    status = "FAIL"
                    print(f"  [OVERFLOW] {page_name} at {vp_name}: scrollWidth={overflow_info['maxScroll']}px > viewport={overflow_info['windowWidth']}px")

                results.append({
                    'category': 'Hero Responsiveness',
                    'test': f"{page_name} @ {vp_name}",
                    'status': status,
                    'details': f"scrollWidth={overflow_info['maxScroll']}px vs viewport={overflow_info['windowWidth']}px"
                })

        print(f"Hero Responsiveness Tests: {hero_pass_count}/{hero_total_count} PASSED")

        print("\n--- 3. CONTACTS KANBAN VIEW AUDIT ---")

        # Test 3.1: Case insensitive query parameter ?view=Kanban
        page.set_viewport_size({'width': 1280, 'height': 800})
        page.goto(f"{BASE_URL}/contacts/?view=Kanban", wait_until="domcontentloaded")

        kanban_container = page.locator("#kanban-container")
        kanban_visible = kanban_container.is_visible()
        print(f"  ?view=Kanban visible: {kanban_visible}")
        results.append({
            'category': 'Contacts Kanban',
            'test': 'Kanban Container Display (?view=Kanban)',
            'status': 'PASS' if kanban_visible else 'FAIL',
            'details': 'Container #kanban-container rendered and visible'
        })

        # Test 3.2: Verify 5 Canonical Columns
        expected_columns = ['lead', 'customer', 'active', 'supplier', 'inactive']
        col_statuses = []
        for col_id in expected_columns:
            col_loc = page.locator(f'#kanban-col-{col_id}')
            count_loc = page.locator(f'#kanban-col-{col_id} .kanban-col-count')
            count = count_loc.inner_text().strip() if count_loc.is_visible() else "N/A"
            exists = col_loc.count() > 0
            col_statuses.append((col_id, exists, count))
            print(f"  Column [{col_id}]: exists={exists}, count={count}")

        all_cols_exist = all(status[1] for status in col_statuses)
        results.append({
            'category': 'Contacts Kanban',
            'test': 'All 5 Canonical Pipeline Columns Present',
            'status': 'PASS' if all_cols_exist else 'FAIL',
            'details': ', '.join([f"{c[0]}: {c[2]}" for c in col_statuses])
        })

        # Test 3.3: Mobile Switcher Tabs at 375px
        page.set_viewport_size({'width': 375, 'height': 667})
        page.goto(f"{BASE_URL}/contacts/?view=Kanban", wait_until="domcontentloaded")

        lead_tab = page.locator("#kanban-tab-lead")
        supplier_tab = page.locator("#kanban-tab-supplier")
        tab_visible = lead_tab.is_visible()
        print(f"  Mobile tab switcher visible at 375px: {tab_visible}")

        # Click supplier tab
        supplier_tab.click()
        time.sleep(0.3)
        supplier_col_visible = page.locator("#kanban-col-supplier").is_visible()
        lead_col_hidden = not page.locator("#kanban-col-lead").is_visible()
        mobile_switch_works = supplier_col_visible and lead_col_hidden
        print(f"  Switching to Supplier column on mobile: visible={supplier_col_visible}, lead_hidden={lead_col_hidden}")
        results.append({
            'category': 'Contacts Kanban',
            'test': 'Mobile Column Tabs Switching',
            'status': 'PASS' if mobile_switch_works else 'FAIL',
            'details': 'Tapping tab correctly switches active column on small screens'
        })

        # Test 3.4: Filter Query Parameter Preservation across View Modes
        page.set_viewport_size({'width': 1280, 'height': 800})
        page.goto(f"{BASE_URL}/contacts/?view=Kanban&relation=customer&search=test", wait_until="domcontentloaded")

        # Check view switcher links
        cards_btn_href = page.locator('a.view-toggle-btn[title="بطاقات"]').get_attribute('href')
        table_btn_href = page.locator('a.view-toggle-btn[title="جدول"]').get_attribute('href')
        print(f"  Cards toggle href: {cards_btn_href}")
        print(f"  Table toggle href: {table_btn_href}")

        filters_preserved = (
            'relation=customer' in (cards_btn_href or '') and
            'relation=customer' in (table_btn_href or '') and
            'search=' in (cards_btn_href or '') and
            'search=' in (table_btn_href or '')
        )
        results.append({
            'category': 'Contacts Kanban',
            'test': 'Filter Querystring Preservation Across Views',
            'status': 'PASS' if filters_preserved else 'FAIL',
            'details': f"Cards href: {cards_btn_href}, Table href: {table_btn_href}"
        })

        # Test 3.5: Contact Status Update via Quick Select
        page.goto(f"{BASE_URL}/contacts/?view=kanban", wait_until="domcontentloaded")
        page.wait_for_load_state("networkidle")

        # Find first card in any column
        first_card = page.locator('.kanban-card').first
        if first_card.count() > 0:
            contact_id = first_card.get_attribute('data-contact-id')
            current_stage = first_card.get_attribute('data-current-stage')
            target_stage = 'active' if current_stage != 'active' else 'customer'
            print(f"  Testing status transition for contact #{contact_id} from {current_stage} -> {target_stage}")
            
            # Select target stage
            select_loc = first_card.locator('select')
            select_loc.select_option(value=target_stage)
            time.sleep(1.0) # Wait for fetch and DOM relocation

            # Verify card moved to target column dropzone
            target_dropzone_card = page.locator(f'.kanban-dropzone[data-stage="{target_stage}"] #contact-card-{contact_id}')
            moved_successfully = target_dropzone_card.count() > 0
            print(f"  Card relocated to dropzone [{target_stage}]: {moved_successfully}")
            results.append({
                'category': 'Contacts Kanban',
                'test': 'Live Contact Stage Update & DOM Relocation',
                'status': 'PASS' if moved_successfully else 'FAIL',
                'details': f"Moved contact #{contact_id} from {current_stage} to {target_stage} successfully"
            })

        browser.close()

    print("\n" + "=" * 70)
    print("FINAL BROWSER TEST SUMMARY")
    print("=" * 70)
    all_passed = True
    for r in results:
        badge = "[PASS]" if r['status'] == 'PASS' else "[FAIL]"
        if r['status'] != 'PASS':
            all_passed = False
        print(f"{badge} {r['category']} - {r['test']}: {r['details']}")
    print("=" * 70)
    if all_passed:
        print("ALL TESTS PASSED SUCCESSFULLY!")
    else:
        print("SOME TESTS FAILED.")
        sys.exit(1)

if __name__ == "__main__":
    try:
        run_tests()
    finally:
        if SERVER_PROC:
            SERVER_PROC.terminate()
