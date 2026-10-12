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

async def inspect_product_row():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={'width': 1600, 'height': 1000}, storage_state="scratch/auth_state.json")
        page = await context.new_page()

        await page.goto("https://weapharma.bricks-rep.com/products", wait_until="domcontentloaded")
        await asyncio.sleep(4)

        # Inspect cell elements
        cell_info = await page.evaluate('''() => {
            const firstRow = document.querySelector('.ag-row-first');
            if (!firstRow) return null;
            return {
                html: firstRow.innerHTML,
                cells: Array.from(firstRow.querySelectorAll('.ag-cell')).map(c => ({
                    colId: c.getAttribute('col-id'),
                    text: c.innerText.trim(),
                    hasLink: !!c.querySelector('a'),
                    linkHref: c.querySelector('a')?.getAttribute('href')
                }))
            };
        }''')
        with open("scratch/product_cells.json", "w", encoding="utf-8") as f:
            json.dump(cell_info, f, ensure_ascii=False, indent=2)

        # Let's try clicking the more_vert button in the first row
        more_btn = await page.query_selector('.ag-row-first button, .ag-row-first mat-icon:has-text("more_vert"), .ag-row-first [col-id="actions"]')
        if more_btn:
            print("Clicking more_vert on first row...")
            await more_btn.click()
            await asyncio.sleep(2)
            await page.screenshot(path="scratch/screenshots/products/04_product_row_menu.png")
            menu_items = await page.evaluate('''() => {
                return Array.from(document.querySelectorAll('.mat-mdc-menu-item, [role="menuitem"]')).map(m => m.innerText.trim());
            }''')
            print("Row menu items:", menu_items)
            with open("scratch/product_row_menu.json", "w", encoding="utf-8") as f:
                json.dump(menu_items, f, ensure_ascii=False, indent=2)

        # Also let's try double clicking or clicking on the name cell
        name_cell = await page.query_selector('.ag-row-first [col-id="name"]')
        if name_cell:
            print("Clicking name cell...")
            await name_cell.click()
            await asyncio.sleep(2)
            print("After click URL:", page.url)
            if "/products/" in page.url and page.url != "https://weapharma.bricks-rep.com/products":
                await page.screenshot(path="scratch/screenshots/products/05_product_detail.png")

        await browser.close()

if __name__ == '__main__':
    asyncio.run(inspect_product_row())
