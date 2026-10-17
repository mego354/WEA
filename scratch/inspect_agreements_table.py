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

        print("Navigating to https://weapharma.bricks-rep.com/agreements ...")
        await page.goto("https://weapharma.bricks-rep.com/agreements", wait_until="domcontentloaded")
        await asyncio.sleep(6)

        table_info = await page.evaluate('''() => {
            const ths = Array.from(document.querySelectorAll('th, mat-header-cell, [role="columnheader"]')).map(el => el.innerText.trim());
            const rows = Array.from(document.querySelectorAll('tr, mat-row, [role="row"]')).slice(1, 4).map(row => {
                return Array.from(row.querySelectorAll('td, mat-cell, [role="cell"], [role="gridcell"]')).map(cell => cell.innerText.trim().replace(/\\n+/g, ' '));
            });
            return { ths, rows };
        }''')

        print("Table Headers:", table_info['ths'])
        print("Sample Rows:", table_info['rows'])

        await browser.close()

if __name__ == '__main__':
    asyncio.run(main())
