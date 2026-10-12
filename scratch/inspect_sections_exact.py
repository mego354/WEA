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
        context = await browser.new_context(
            storage_state="scratch/auth_state.json",
            viewport={'width': 1600, 'height': 1200}
        )
        page = await context.new_page()

        print("1. Opening contact detail overview...")
        await page.goto("https://weapharma.bricks-rep.com/contacts/a7517dbe-6c74-402a-8408-a201e108b89f/overview", wait_until="networkidle")
        await asyncio.sleep(2)

        # Inspect the accordion DOM elements directly
        # Let's see what panels exist and expand all of them via JS
        panels_info = await page.evaluate("""() => {
            // Find all headers containing expand_more or expand_less
            const items = Array.from(document.querySelectorAll('*')).filter(e => {
                return e.children.length > 0 && Array.from(e.children).some(c => c.tagName === 'MAT-ICON' && (c.innerText.includes('expand_more') || c.innerText.includes('expand_less')));
            });
            // Click them all to expand
            items.forEach(it => {
                const icon = it.querySelector('mat-icon');
                if (icon && icon.innerText.includes('expand_more')) {
                    it.click();
                }
            });
            return items.map(it => it.innerText.replace(/expand_more|expand_less/g, '').trim());
        }""")
        print("Clicked expansion items:", panels_info)
        await asyncio.sleep(2)

        # Now capture the entire sidebar text
        sidebar_text = await page.evaluate("""() => {
            // find container of these headers
            const el = Array.from(document.querySelectorAll('div')).find(d => d.innerText && d.innerText.includes('المعلومات الأساسية') && d.innerText.includes('حساب العميل'));
            return el ? el.innerText : document.body.innerText;
        }""")
        results["sidebar_text"] = sidebar_text
        with open("scratch/full_sidebar_text.txt", "w", encoding="utf-8") as f:
            f.write(sidebar_text)

        await page.screenshot(path="scratch/screenshots/detail_all_sections_expanded.png")

        # 2. Click 3-dots and click edit
        three_dots = await page.query_selector('button:has(mat-icon:has-text("more_vert"))')
        if three_dots:
            await three_dots.click()
            await asyncio.sleep(1)
            # Find edit button in menu
            edit_item = await page.query_selector('.mat-menu-content button:has-text("تعديل")')
            if edit_item:
                print("Clicking Edit button...")
                await edit_item.click()
                await page.wait_for_load_state("networkidle")
                await asyncio.sleep(3)
                print("Edit page URL:", page.url)
                results["edit_page_url"] = page.url
                await page.screenshot(path="scratch/screenshots/06_edit_page.png", full_page=True)

        # 3. Open Create page
        print("Navigating to /contacts/create...")
        await page.goto("https://weapharma.bricks-rep.com/contacts/create", wait_until="networkidle")
        await asyncio.sleep(2)
        print("Create page URL:", page.url)
        results["create_page_url"] = page.url
        await page.screenshot(path="scratch/screenshots/07_create_page.png", full_page=True)

        # 4. Find and open a Supplier (مورد) contact
        print("Finding a supplier contact in contacts list...")
        # Open contacts with filter for vendor if possible, or search
        # Let's search contacts or look for relation vendor
        await page.goto("https://weapharma.bricks-rep.com/contacts?tableStateQ=pageIndex__0&cardsStateQ=pageIndex__0&gridStateQ=pageIndex__0&sfql=inactive__false", wait_until="networkidle")
        await asyncio.sleep(2)

        # Open filter drawer
        filter_btn = await page.query_selector('button:has(mat-icon:has-text("filter_list")), [class*="filter-btn"]')
        if filter_btn:
            await filter_btn.click()
            await asyncio.sleep(1)
            # Find "علاقة العمل" dropdown
            relation_select = await page.query_selector('mat-select[placeholder*="علاقة العمل"], mat-form-field:has-text("علاقة العمل") mat-select')
            if relation_select:
                print("Clicking relation select...")
                await relation_select.click()
                await asyncio.sleep(1)
                # Select "مورد"
                vendor_option = await page.query_selector('.mat-option:has-text("مورد"), [role="option"]:has-text("مورد")')
                if vendor_option:
                    await vendor_option.click()
                    await asyncio.sleep(1)
                    # Apply filter
                    apply_btn = await page.query_selector('button:has-text("تطبيق"), button:has-text("بحث"), button:has-text("Apply")')
                    if apply_btn:
                        await apply_btn.click()
                        await page.wait_for_load_state("networkidle")
                        await asyncio.sleep(2)
                        await page.screenshot(path="scratch/screenshots/vendor_filter_results.png")
                        first_row_link = await page.query_selector('table tbody tr:first-child a')
                        if first_row_link:
                            await first_row_link.click()
                            await page.wait_for_load_state("networkidle")
                            await asyncio.sleep(2)
                            print("Supplier detail URL:", page.url)
                            results["supplier_detail_url"] = page.url
                            results["supplier_tabs"] = await page.evaluate("() => Array.from(document.querySelectorAll('.mat-tab-label, [role=\"tab\"]')).map(t => t.innerText.trim())")
                            await page.screenshot(path="scratch/screenshots/supplier_detail.png")

        with open("scratch/deep_inspection_summary.json", "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)

        print("Finished deep inspection successfully!")
        await browser.close()

if __name__ == '__main__':
    asyncio.run(main())
