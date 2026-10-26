import asyncio
import json
import os
import sys
from playwright.async_api import async_playwright

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

async def main():
    results = {}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={'width': 1600, 'height': 1000})
        page = await context.new_page()

        print("Logging in...")
        await page.goto("https://weapharma.bricks-rep.com/home", wait_until="networkidle")
        if "login" in page.url or "signin" in page.url or "auth" in page.url:
            await page.fill('input[type="email"], input[name="email"], input[formcontrolname="email"]', "wea.pharm2020@gmail.com")
            await page.fill('input[type="password"], input[name="password"], input[formcontrolname="password"]', "Wea@4444")
            btn = await page.query_selector('button[type="submit"]')
            if btn: await btn.click()
            await page.wait_for_load_state("networkidle")
            await asyncio.sleep(2)

        # 1. Detail page accordions inspection on contact [#16456]
        print("Navigating to contact [#16456] overview...")
        await page.goto("https://weapharma.bricks-rep.com/contacts/a7517dbe-6c74-402a-8408-a201e108b89f/overview", wait_until="networkidle")
        await asyncio.sleep(2)

        # Check 3-dots menu on detail page header
        three_dots_btn = await page.query_selector('button:has(mat-icon:has-text("more_vert"))')
        if three_dots_btn:
            print("Clicking 3-dots menu on detail header...")
            await three_dots_btn.click()
            await asyncio.sleep(1)
            await page.screenshot(path="scratch/screenshots/detail_3dots_menu.png")
            menu_items = await page.evaluate("() => Array.from(document.querySelectorAll('.mat-menu-content button, [role=\"menuitem\"]')).map(b => b.innerText.trim())")
            results["detail_3dots_menu"] = menu_items
            print("Detail 3-dots menu items:", menu_items)
            await page.keyboard.press("Escape")
            await asyncio.sleep(0.5)

        # Check 'Customer' dropdown button
        status_dropdown = await page.query_selector('button:has-text("Customer")')
        if status_dropdown:
            print("Clicking Customer dropdown button...")
            await status_dropdown.click()
            await asyncio.sleep(1)
            await page.screenshot(path="scratch/screenshots/detail_customer_dropdown.png")
            items = await page.evaluate("() => Array.from(document.querySelectorAll('.mat-menu-content button, [role=\"menuitem\"]')).map(b => b.innerText.trim())")
            results["customer_dropdown_items"] = items
            print("Customer dropdown items:", items)
            await page.keyboard.press("Escape")
            await asyncio.sleep(0.5)

        # Expand each accordion on the left side
        accordions = await page.query_selector_all('mat-expansion-panel, .mat-accordion .mat-expansion-panel, .accordion-item')
        print(f"Found {len(accordions)} expansion panels on detail page.")
        panel_data = {}
        for idx in range(len(accordions)):
            # re-query
            panels = await page.query_selector_all('mat-expansion-panel, .mat-accordion .mat-expansion-panel')
            if idx < len(panels):
                panel = panels[idx]
                header = await panel.query_selector('mat-expansion-panel-header')
                title = await header.inner_text() if header else f"panel_{idx}"
                title_clean = title.replace('\n', ' ').strip()
                print(f"Opening panel {idx}: {title_clean}")
                # check if expanded
                is_expanded = await panel.evaluate("p => p.classList.contains('mat-expanded')")
                if not is_expanded and header:
                    await header.click()
                    await asyncio.sleep(1)

                content = await panel.evaluate("""p => {
                    const body = p.querySelector('.mat-expansion-panel-body, .panel-body') || p;
                    return {
                        text: body.innerText.trim(),
                        keys_and_values: Array.from(body.querySelectorAll('tr, .row, dl, div > span')).map(e => e.innerText.trim()).filter(Boolean).slice(0, 20)
                    };
                }""")
                panel_data[title_clean] = content
                await page.screenshot(path=f"scratch/screenshots/accordion_{idx}_{title_clean[:10]}.png")

        results["accordions"] = panel_data

        # 2. Inspect Supplier Contacts
        print("Navigating to contacts list to find a supplier...")
        await page.goto("https://weapharma.bricks-rep.com/contacts", wait_until="networkidle")
        await asyncio.sleep(2)

        # Check row action on first row
        row_action = await page.query_selector('table tbody tr:first-child button, .mat-row:first-child button')
        if row_action:
            print("Clicking row action button...")
            await row_action.click()
            await asyncio.sleep(1)
            await page.screenshot(path="scratch/screenshots/list_row_action_menu.png")
            row_menu = await page.evaluate("() => Array.from(document.querySelectorAll('.mat-menu-content button, [role=\"menuitem\"]')).map(b => b.innerText.trim())")
            results["list_row_menu"] = row_menu
            print("List row menu:", row_menu)
            await page.keyboard.press("Escape")
            await asyncio.sleep(0.5)

        # Let's search or filter for supplier (مورد)
        # Search for supplier
        search_input = await page.query_selector('input[placeholder*="بحث"]')
        if search_input:
            print("Searching for 'مورد' or supplier name...")
            await search_input.fill("مورد")
            await search_input.press("Enter")
            await asyncio.sleep(3)
            await page.screenshot(path="scratch/screenshots/list_search_results.png")
            # If any results found, click first one
            first_vendor = await page.query_selector('table tbody tr:first-child a')
            if first_vendor:
                vendor_text = await first_vendor.inner_text()
                print(f"Found vendor row: {vendor_text}, clicking...")
                await first_vendor.click()
                await page.wait_for_load_state("networkidle")
                await asyncio.sleep(2)
                print("Vendor detail URL:", page.url)
                await page.screenshot(path="scratch/screenshots/vendor_detail.png")
                results["vendor_detail_url"] = page.url
                results["vendor_tabs"] = await page.evaluate("() => Array.from(document.querySelectorAll('.mat-tab-label, [role=\"tab\"]')).map(t => t.innerText.trim())")
                results["vendor_chips"] = await page.evaluate("() => Array.from(document.querySelectorAll('.mat-chip, [class*=\"chip\"], [class*=\"badge\"]')).map(c => c.innerText.trim())")
                print("Vendor tabs:", results["vendor_tabs"])
                print("Vendor chips:", results["vendor_chips"])

        with open("scratch/accordions_and_supplier_report.json", "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)

        print("Completed successfully!")
        await browser.close()

if __name__ == '__main__':
    asyncio.run(main())
