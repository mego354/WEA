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

async def inspect_po_detail():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={'width': 1600, 'height': 1000}, storage_state="scratch/auth_state.json")
        page = await context.new_page()

        po_id = "a571c874-33bf-4923-afd5-e5cc8fdfffd1"
        url = f"https://weapharma.bricks-rep.com/purchase-orders/{po_id}"
        print(f"Navigating to {url} ...")
        await page.goto(url, wait_until="domcontentloaded")
        await asyncio.sleep(5)

        await page.screenshot(path="scratch/screenshots/purchases/05_po_detail_full.png", full_page=True)

        detail_data = await page.evaluate('''() => {
            return {
                url: window.location.href,
                title: document.title,
                pageTitle: document.querySelector('h1, h2, .title, .page-title')?.innerText?.trim(),
                buttons: Array.from(document.querySelectorAll('button, a.btn, a.mat-mdc-button, a.mat-mdc-raised-button'))
                    .map(b => b.innerText?.trim()?.replace(/\\s+/g, ' ')).filter(Boolean),
                sections: Array.from(document.querySelectorAll('.card, mat-card, .section, mat-expansion-panel'))
                    .map(s => s.innerText?.substring(0, 500)?.replace(/\\s+/g, ' ')),
                tables: Array.from(document.querySelectorAll('table, mat-table, [role="table"]')).map(t => {
                    const headers = Array.from(t.querySelectorAll('th, mat-header-cell')).map(th => th.innerText.trim());
                    const rows = Array.from(t.querySelectorAll('tbody tr, mat-row')).map(r => {
                        return Array.from(r.querySelectorAll('td, mat-cell')).map(c => c.innerText.trim().replace(/\\s+/g, ' '));
                    });
                    return { headers, rows };
                }),
                fullText: document.body.innerText.substring(0, 4000)
            };
        }''')

        with open("scratch/po_detail_data.json", "w", encoding="utf-8") as f:
            json.dump(detail_data, f, ensure_ascii=False, indent=2)

        print("Saved scratch/po_detail_data.json successfully!")
        await browser.close()

if __name__ == '__main__':
    asyncio.run(inspect_po_detail())
