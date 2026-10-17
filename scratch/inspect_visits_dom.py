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

        print("Inspecting /visits...")
        await page.goto("https://weapharma.bricks-rep.com/visits", wait_until="networkidle")
        await asyncio.sleep(4)

        # Inspect main content elements
        dom_info = await page.evaluate('''() => {
            const main = document.querySelector('main, .main-content, mat-sidenav-content, router-outlet + *');
            const tables = Array.from(document.querySelectorAll('table, mat-table, cdk-table, [role="grid"], [role="table"], .table')).map(t => ({
                tag: t.tagName,
                className: t.className,
                headers: Array.from(t.querySelectorAll('th, mat-header-cell, [role="columnheader"]')).map(h => h.innerText.trim()),
                rowsCount: t.querySelectorAll('tr, mat-row, cdk-row, [role="row"]').length
            }));

            const cards = Array.from(document.querySelectorAll('mat-card, .mat-mdc-card, .card, app-visit-card')).map(c => ({
                text: c.innerText.trim().slice(0, 300),
                className: c.className
            }));

            // Check if there is a table toggle button
            const toggleButtons = Array.from(document.querySelectorAll('mat-button-toggle, .mat-button-toggle, button')).map(b => ({
                text: b.innerText.trim(),
                aria: b.getAttribute('aria-label') || '',
                class: b.className
            })).filter(b => b.text.includes('table') || b.text.includes('view') || b.aria.includes('table') || b.text.includes('جدول'));

            return {
                tables,
                cardsCount: cards.length,
                sampleCard: cards[0],
                toggleButtons,
                mainText: (main ? main.innerText : document.body.innerText).slice(0, 1500)
            };
        }''')
        print("DOM Info /visits:", json.dumps(dom_info, ensure_ascii=False, indent=2))

        # Click table_chart if in card view
        btn_table = await page.query_selector('mat-button-toggle:has-text("table_chart"), button:has-text("table_chart")')
        if btn_table:
            print("Found table toggle, clicking it...")
            await btn_table.click()
            await asyncio.sleep(3)
            table_headers_after = await page.evaluate('''() => {
                return Array.from(document.querySelectorAll('th, mat-header-cell, [role="columnheader"]')).map(h => h.innerText.trim()).filter(Boolean);
            }''')
            print("Table headers after toggle:", table_headers_after)

        await browser.close()

if __name__ == '__main__':
    asyncio.run(main())
