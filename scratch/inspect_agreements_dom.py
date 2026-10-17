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

        print("Inspecting /agreements...")
        await page.goto("https://weapharma.bricks-rep.com/agreements", wait_until="networkidle")
        await asyncio.sleep(4)

        # Inspect AG grid or table on agreements
        ag_info = await page.evaluate('''() => {
            const agHeaders = Array.from(document.querySelectorAll('.ag-header-cell-text, th, mat-header-cell')).map(h => h.innerText.trim()).filter(Boolean);
            const rows = Array.from(document.querySelectorAll('.ag-row, tr')).slice(0, 3).map(r => {
                return Array.from(r.querySelectorAll('.ag-cell, td')).map(c => c.innerText.trim());
            });
            const summaryCards = Array.from(document.querySelectorAll('.summary, .statistic, mat-card, .kpi, app-statistic-card')).map(c => c.innerText.trim());
            const buttons = Array.from(document.querySelectorAll('button, a')).map(b => b.innerText.trim()).filter(Boolean);

            return {
                agHeaders,
                sampleRows: rows,
                summaryCards,
                buttons: buttons.slice(0, 40)
            };
        }''')
        print("Agreements info:", json.dumps(ag_info, ensure_ascii=False, indent=2))

        # Check if clicking a row opens a drawer, dialog, or navigates
        row = await page.query_selector('.ag-row, tbody tr')
        if row:
            print("Clicking first row of agreements...")
            await row.click()
            await asyncio.sleep(2)
            await page.screenshot(path="scratch/ref_audit/agreements_row_clicked.png")
            row_click_res = await page.evaluate('''() => {
                return {
                    url: window.location.href,
                    openedPanels: Array.from(document.querySelectorAll('mat-sidenav, mat-dialog-container, .cdk-overlay-pane, router-outlet + *')).map(el => el.innerText.slice(0, 500))
                };
            }''')
            print("Row click result:", json.dumps(row_click_res, ensure_ascii=False, indent=2))

        await browser.close()

if __name__ == '__main__':
    asyncio.run(main())
