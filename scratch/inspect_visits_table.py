import asyncio
import json
import sys
from playwright.async_api import async_playwright

sys.stdout.reconfigure(encoding='utf-8')

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            storage_state="scratch/auth_state.json",
            viewport={'width': 1600, 'height': 1000}
        )
        page = await context.new_page()

        print("Navigating to https://weapharma.bricks-rep.com/visits ...")
        await page.goto("https://weapharma.bricks-rep.com/visits", wait_until="domcontentloaded")
        await asyncio.sleep(8)

        info = await page.evaluate('''() => {
            const ths = Array.from(document.querySelectorAll('th, mat-header-cell, [role="columnheader"], .table-header')).map(el => el.innerText.trim());
            const rows = Array.from(document.querySelectorAll('tr, mat-row, [role="row"]')).slice(1, 4).map(row => {
                return Array.from(row.querySelectorAll('td, mat-cell, [role="cell"], [role="gridcell"]')).map(cell => cell.innerText.trim().replace(/\\n+/g, ' '));
            });
            const filters = Array.from(document.querySelectorAll('.filter-item, mat-form-field, .form-group, [role="combobox"], input, select')).map(f => f.innerText.trim().replace(/\\n+/g, ' ') || f.placeholder || f.name).filter(Boolean);
            const buttons = Array.from(document.querySelectorAll('button, a.btn, a.button')).map(b => b.innerText.trim().replace(/\\n+/g, ' ') || b.getAttribute('aria-label')).filter(Boolean);

            return {
                title: document.querySelector('h1, h2, .page-title, .title')?.innerText || '',
                ths,
                rows,
                filters: filters.slice(0, 25),
                buttons: buttons.slice(0, 15)
            };
        }''')

        print("Title:", info['title'])
        print("Table Headers:", info['ths'])
        print("Sample Rows:", info['rows'])
        print("Filters:", info['filters'])
        print("Buttons:", info['buttons'])

        await browser.close()

if __name__ == '__main__':
    asyncio.run(main())
