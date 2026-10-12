import asyncio
import os
import json
import sys

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from playwright.async_api import async_playwright

async def inspect_interactive():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={'width': 1600, 'height': 1000}, storage_state="scratch/auth_state.json")
        page = await context.new_page()

        # 1. Product row actions
        print("Navigating to /products ...")
        await page.goto("https://weapharma.bricks-rep.com/products", wait_until="domcontentloaded")
        await page.wait_for_selector('.ag-row', timeout=20000)
        await asyncio.sleep(2)

        # Click more_vert on the first row
        more_btn = await page.query_selector('.ag-row-first [col-id="actions"] button, .ag-row-first button, .ag-row-first mat-icon')
        if more_btn:
            print("Clicking more_btn...")
            await more_btn.click()
            await asyncio.sleep(2)
            await page.screenshot(path="scratch/screenshots/products/04_product_menu_open.png")
            menu_items = await page.evaluate('''() => {
                return Array.from(document.querySelectorAll('.mat-mdc-menu-item, [role="menuitem"]')).map(m => m.innerText.trim());
            }''')
            print("Product menu items:", menu_items)
            with open("scratch/product_menu_items.json", "w", encoding="utf-8") as f:
                json.dump(menu_items, f, ensure_ascii=False, indent=2)

        # 2. Inspect PO create contact select
        print("Navigating to /purchase-orders/create ...")
        await page.goto("https://weapharma.bricks-rep.com/purchase-orders/create", wait_until="domcontentloaded")
        await asyncio.sleep(4)
        contact_select = await page.query_selector('mat-select, [role="combobox"]')
        if contact_select:
            print("Clicking contact select...")
            await contact_select.click()
            await asyncio.sleep(2)
            await page.screenshot(path="scratch/screenshots/purchases/03_po_contact_dropdown.png")
            options = await page.evaluate('''() => {
                return Array.from(document.querySelectorAll('mat-option, [role="option"]')).map(o => o.innerText.trim()).slice(0, 10);
            }''')
            print("First 10 contact options:", options)

            # Click first option in read-only inspection to see the full PO creation form layout
            first_opt = await page.query_selector('mat-option, [role="option"]')
            if first_opt:
                print("Selecting first contact to reveal PO form fields...")
                await first_opt.click()
                await asyncio.sleep(4)
                await page.screenshot(path="scratch/screenshots/purchases/04_po_form_revealed.png")

                po_full_form = await page.evaluate('''() => {
                    const fields = Array.from(document.querySelectorAll('mat-form-field, .form-group, table, [role="table"]')).map(el => {
                        const label = el.querySelector('label, mat-label')?.innerText?.trim();
                        const placeholder = el.querySelector('input, textarea')?.getAttribute('placeholder');
                        const headers = Array.from(el.querySelectorAll('th, mat-header-cell')).map(th => th.innerText.trim());
                        return { tag: el.tagName, label, placeholder, headers: headers.filter(Boolean) };
                    });
                    const buttons = Array.from(document.querySelectorAll('button')).map(b => b.innerText.trim()).filter(Boolean);
                    return {
                        url: window.location.href,
                        fields: fields.filter(f => f.label || f.headers.length > 0),
                        buttons,
                        fullText: document.body.innerText.substring(0, 4000)
                    };
                }''')
                with open("scratch/po_full_form.json", "w", encoding="utf-8") as f:
                    json.dump(po_full_form, f, ensure_ascii=False, indent=2)

        await browser.close()
        print("Done interactive inspection!")

if __name__ == '__main__':
    asyncio.run(inspect_interactive())
