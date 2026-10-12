import asyncio
import json
import os
import sys

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from playwright.async_api import async_playwright

PAGES_TO_INSPECT = [
    {"name": "products_list", "url": "https://weapharma.bricks-rep.com/products"},
    {"name": "product_categories", "url": "https://weapharma.bricks-rep.com/product-categories"},
    {"name": "purchase_orders", "url": "https://weapharma.bricks-rep.com/purchase-orders"},
    {"name": "purchase_return_orders", "url": "https://weapharma.bricks-rep.com/purchase-return-orders"},
    {"name": "vendor_payments", "url": "https://weapharma.bricks-rep.com/vendor-payments"},
    {"name": "vendor_payment_requests", "url": "https://weapharma.bricks-rep.com/vendor-payment-requests"},
    {"name": "vendor_accounts", "url": "https://weapharma.bricks-rep.com/accounting/vendors"},
    {"name": "vendor_transactions", "url": "https://weapharma.bricks-rep.com/accounting/vendor-transactions"},
]

async def inspect_pages():
    os.makedirs("scratch/screenshots/products", exist_ok=True)
    os.makedirs("scratch/screenshots/purchases", exist_ok=True)
    report = {}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={'width': 1600, 'height': 1000}, storage_state="scratch/auth_state.json")
        page = await context.new_page()

        for item in PAGES_TO_INSPECT:
            pname = item["name"]
            purl = item["url"]
            print(f"Inspecting {pname} at {purl} ...")
            try:
                await page.goto(purl, wait_until="domcontentloaded", timeout=45000)
                await asyncio.sleep(4)
            except Exception as e:
                print(f"Error loading {purl}: {e}")

            folder = "products" if "product" in pname else "purchases"
            screenshot_path = f"scratch/screenshots/{folder}/{pname}.png"
            await page.screenshot(path=screenshot_path, full_page=False)

            # Extract page info
            data = await page.evaluate('''() => {
                const title = document.querySelector('h1, h2, .page-title, .title, mat-toolbar')?.innerText?.trim() || document.title;
                
                // Buttons and action items
                const buttons = Array.from(document.querySelectorAll('button, a.btn, a.mat-mdc-button, a.mat-mdc-raised-button, a.mat-mdc-fab'))
                    .map(b => b.innerText?.trim()?.replace(/\\s+/g, ' '))
                    .filter(Boolean);

                // Table headers
                const ths = Array.from(document.querySelectorAll('th, mat-header-cell, [role="columnheader"]'))
                    .map(th => th.innerText?.trim()?.replace(/\\s+/g, ' '))
                    .filter(Boolean);

                // Check first row cells
                const firstRow = Array.from(document.querySelectorAll('tbody tr:first-child td, mat-row:first-child mat-cell'))
                    .map(td => td.innerText?.trim()?.replace(/\\s+/g, ' '));

                // Extract all input / select placeholders or labels
                const filterInputs = Array.from(document.querySelectorAll('input, select, mat-select'))
                    .map(inp => inp.getAttribute('placeholder') || inp.getAttribute('aria-label') || inp.name || '')
                    .filter(Boolean);

                return {
                    url: window.location.href,
                    title,
                    buttons: Array.from(new Set(buttons)),
                    tableHeaders: ths,
                    firstRowSample: firstRow,
                    filterInputs: Array.from(new Set(filterInputs))
                };
            }''')
            data["screenshot"] = screenshot_path
            report[pname] = data
            print(f"Done {pname}: headers count={len(data['tableHeaders'])}, buttons={data['buttons'][:5]}")

        with open("scratch/inspected_pages_summary.json", "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        print("Completed inspection of all 8 pages!")
        await browser.close()

if __name__ == '__main__':
    asyncio.run(inspect_pages())
