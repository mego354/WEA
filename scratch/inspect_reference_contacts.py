import asyncio
import json
import os
import sys
from playwright.async_api import async_playwright

# Set standard output encoding to utf-8
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

async def inspect():
    results = {}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        # Larger viewport to see more columns
        context = await browser.new_context(viewport={'width': 1600, 'height': 1000})
        page = await context.new_page()

        print("Navigating to https://weapharma.bricks-rep.com/home ...")
        await page.goto("https://weapharma.bricks-rep.com/home", wait_until="networkidle")

        current_url = page.url
        print(f"Current URL: {current_url}")
        if "login" in current_url or "signin" in current_url or "auth" in current_url:
            print("Logging in...")
            await page.fill('input[type="email"], input[name="email"], input[formcontrolname="email"]', "wea.pharm2020@gmail.com")
            await page.fill('input[type="password"], input[name="password"], input[formcontrolname="password"]', "Wea@0000")
            login_btn = await page.query_selector('button[type="submit"], button:has-text("تسجيل الدخول"), button:has-text("Login")')
            if login_btn:
                await login_btn.click()
            await page.wait_for_load_state("networkidle")
            await asyncio.sleep(3)
            print(f"URL after login: {page.url}")

        print("Navigating to /contacts ...")
        await page.goto("https://weapharma.bricks-rep.com/contacts", wait_until="networkidle")
        await asyncio.sleep(2)
        print(f"Contacts list URL: {page.url}")

        os.makedirs("scratch/screenshots", exist_ok=True)
        await page.screenshot(path="scratch/screenshots/01_contacts_list_full.png", full_page=False)

        # 1. Contacts List inspection
        table_headers = await page.evaluate("""() => {
            return Array.from(document.querySelectorAll('table th, .mat-header-cell, [role="columnheader"]'))
                .map(e => e.innerText.trim()).filter(Boolean);
        }""")
        print("Contacts list table headers:", table_headers)

        # Inspect table rows and cells in detail
        rows_data = await page.evaluate("""() => {
            return Array.from(document.querySelectorAll('table tbody tr, .mat-row')).slice(0, 5).map(r => {
                return Array.from(r.querySelectorAll('td, .mat-cell')).map(c => c.innerText.trim());
            });
        }""")
        print(f"Captured {len(rows_data)} rows sample data.")

        # Inspect pagination
        paginator_text = await page.evaluate("() => document.querySelector('.mat-paginator, .pagination, [class*=\"paginator\"]')?.innerText?.trim() || ''")
        print("Paginator text:", paginator_text)

        # Check Filter button
        # The filter icon at the top left has a badge '1'
        filter_btn = await page.query_selector('.filter-icon, [class*="filter"], [matbadge]')
        if filter_btn:
            print("Clicking filter icon/button...")
            await filter_btn.click()
            await asyncio.sleep(1.5)
            await page.screenshot(path="scratch/screenshots/03_filter_drawer.png")
            filter_info = await page.evaluate("""() => {
                const drawer = document.querySelector('.mat-drawer, .mat-sidenav, mat-dialog-container, .filter-drawer, .mat-bottom-sheet-container');
                if (!drawer) return null;
                return {
                    title: drawer.querySelector('h1, h2, h3, .title, .mat-drawer-title')?.innerText || '',
                    labels: Array.from(drawer.querySelectorAll('label, .mat-form-field-label, [class*="label"]')).map(l => l.innerText.trim()),
                    buttons: Array.from(drawer.querySelectorAll('button')).map(b => b.innerText.trim())
                };
            }""")
            print("Filter drawer info:", filter_info)
            results["filter_drawer"] = filter_info
            await page.keyboard.press("Escape")
            await asyncio.sleep(0.5)

        # Check gear icon (settings/columns)
        gear_btn = await page.query_selector('button:has(mat-icon:has-text("settings")), [mattooltip*="إعدادات"], [mattooltip*="اعمدة"], button:has-text("⚙")')
        if not gear_btn:
            # Try finding the teal settings icon on the left
            gear_btn = await page.query_selector('button:has(.mat-icon):not(:has-text("تصدير"))')
        if gear_btn:
            print("Clicking settings / column toggle button...")
            try:
                await gear_btn.click()
                await asyncio.sleep(1)
                await page.screenshot(path="scratch/screenshots/03b_table_settings.png")
                await page.keyboard.press("Escape")
                await asyncio.sleep(0.5)
            except Exception as e:
                print("Gear button click exception:", e)

        # 2. Inspect Contact Detail Page
        # Click on the first contact link (e.g. "[#16456] صيدلية سامي هلال")
        print("Looking for contact link in first row...")
        first_contact_link = await page.query_selector('table tbody tr:first-child a, .mat-row:first-child a')
        if not first_contact_link:
            first_contact_link = await page.query_selector('table tbody tr:first-child td:nth-child(2)')
        
        if first_contact_link:
            print("Clicking first contact link...")
            await first_contact_link.click()
            await page.wait_for_load_state("networkidle")
            await asyncio.sleep(2)
            print(f"Contact detail URL: {page.url}")
            await page.screenshot(path="scratch/screenshots/04_contact_detail_main.png", full_page=False)

            # Extract detail tabs
            tabs = await page.evaluate("""() => {
                return Array.from(document.querySelectorAll('.mat-tab-label, [role="tab"], .nav-tabs .nav-link'))
                    .map(e => e.innerText.trim()).filter(Boolean);
            }""")
            print("Found Detail Tabs:", tabs)
            results["detail_tabs"] = tabs

            # Extract header and summary cards on detail page
            detail_header_info = await page.evaluate("""() => {
                return {
                    title: document.querySelector('h1, h2, .page-title, [class*="header-title"]')?.innerText?.trim() || '',
                    actions: Array.from(document.querySelectorAll('.page-header button, .header-actions button, mat-toolbar button')).map(b => b.innerText.trim()).filter(Boolean),
                    cards: Array.from(document.querySelectorAll('.mat-card, .card, [class*="summary-card"], [class*="stats-card"]')).map(c => c.innerText.trim()),
                    chips: Array.from(document.querySelectorAll('.mat-chip, [class*="badge"], [class*="tag"], [class*="chip"]')).map(c => c.innerText.trim())
                };
            }""")
            results["detail_header"] = detail_header_info
            print("Detail header actions:", detail_header_info.get("actions"))
            print("Detail chips:", detail_header_info.get("chips"))

            # Loop through each tab
            tab_elements = await page.query_selector_all('.mat-tab-label, [role="tab"], .nav-tabs .nav-link')
            tabs_data = {}
            for i in range(len(tab_elements)):
                # re-query because dom may refresh
                tabs_now = await page.query_selector_all('.mat-tab-label, [role="tab"], .nav-tabs .nav-link')
                if i < len(tabs_now):
                    tab = tabs_now[i]
                    tab_name = await tab.inner_text()
                    tab_name_clean = tab_name.replace('\n', ' ').strip()
                    print(f"Inspecting Tab {i}: '{tab_name_clean}'...")
                    await tab.click()
                    await asyncio.sleep(2)
                    ss_file = f"scratch/screenshots/tab_{i}_{i:02d}.png"
                    await page.screenshot(path=ss_file, full_page=False)

                    # Extract content inside active tab body
                    tab_body_data = await page.evaluate("""() => {
                        const activeTab = document.querySelector('.mat-tab-body-active, [role="tabpanel"]:not([hidden]), .tab-pane.active') || document.body;
                        return {
                            subheaders: Array.from(activeTab.querySelectorAll('h3, h4, h5, .mat-subheader, .section-title')).map(h => h.innerText.trim()),
                            table_headers: Array.from(activeTab.querySelectorAll('table th, [role="columnheader"]')).map(th => th.innerText.trim()),
                            table_rows_count: activeTab.querySelectorAll('table tbody tr, .mat-row').length,
                            fields: Array.from(activeTab.querySelectorAll('.mat-form-field, .form-group, .row > div, dt, dd, .data-item')).map(f => f.innerText.trim()).filter(t => t.length > 0 && t.length < 100).slice(0, 40)
                        };
                    }""")
                    tabs_data[tab_name_clean] = tab_body_data
                    print(f"  Tab {tab_name_clean} subheaders: {tab_body_data.get('subheaders')}")
                    print(f"  Tab {tab_name_clean} table headers: {tab_body_data.get('table_headers')}")

            results["tabs_data"] = tabs_data

            # Check if there's an Edit button
            edit_btn = await page.query_selector('button:has-text("تعديل"), a:has-text("تعديل"), button:has-text("Edit"), a:has-text("Edit")')
            if edit_btn:
                print("Clicking Edit button (view-only)...")
                await edit_btn.click()
                await page.wait_for_load_state("networkidle")
                await asyncio.sleep(2)
                print(f"Edit page URL: {page.url}")
                await page.screenshot(path="scratch/screenshots/06_contact_edit.png", full_page=False)
                results["edit_page_url"] = page.url

        # Write results
        with open("scratch/inspection_results.json", "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print("All inspection completed successfully!")

        await browser.close()

if __name__ == '__main__':
    asyncio.run(inspect())
