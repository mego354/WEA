import asyncio
import json
import os
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

        # 1. Inspect Visits
        print("--- Inspecting /visits in depth ---")
        await page.goto("https://weapharma.bricks-rep.com/visits", wait_until="networkidle")
        await asyncio.sleep(3)

        # Get all table column headers and sample row
        visits_data = await page.evaluate('''() => {
            const headers = Array.from(document.querySelectorAll('th, mat-header-cell')).map(th => th.innerText.trim()).filter(Boolean);
            const firstRowCells = Array.from(document.querySelectorAll('tr.mat-mdc-row, tr.mat-row, tbody tr')).slice(0, 1).map(row => {
                return Array.from(row.querySelectorAll('td, mat-cell')).map(td => ({
                    text: td.innerText.trim(),
                    html: td.innerHTML.slice(0, 200)
                }));
            });
            const filters = Array.from(document.querySelectorAll('mat-form-field, .filter-item')).map(f => f.innerText.trim().replace(/\\s+/g, ' '));
            const buttons = Array.from(document.querySelectorAll('button, a')).filter(b => {
                const rect = b.getBoundingClientRect();
                return rect.width > 0 && rect.height > 0 && b.innerText.trim();
            }).map(b => b.innerText.trim());

            return {
                headers,
                firstRowCells,
                filters,
                buttons: buttons.slice(0, 30)
            };
        }''')
        with open("scratch/ref_audit/visits_deep.json", "w", encoding="utf-8") as f:
            json.dump(visits_data, f, ensure_ascii=False, indent=2)

        # Inspect row click on visits
        first_row = await page.query_selector('tr.mat-mdc-row, tbody tr')
        if first_row:
            print("Clicking first row in visits to see detail view...")
            await first_row.click()
            await asyncio.sleep(3)
            await page.screenshot(path="scratch/ref_audit/visits_row_click.png")
            visit_detail_info = await page.evaluate('''() => {
                return {
                    url: window.location.href,
                    bodyText: document.body.innerText.slice(0, 2000),
                    sections: Array.from(document.querySelectorAll('mat-card, .card, .section, mat-tab-group, mat-expansion-panel')).map(s => s.innerText.trim().slice(0, 300))
                };
            }''')
            with open("scratch/ref_audit/visit_detail_deep.json", "w", encoding="utf-8") as f:
                json.dump(visit_detail_info, f, ensure_ascii=False, indent=2)

        # 2. Inspect Agreements
        print("--- Inspecting /agreements in depth ---")
        await page.goto("https://weapharma.bricks-rep.com/agreements", wait_until="networkidle")
        await asyncio.sleep(3)

        agreements_data = await page.evaluate('''() => {
            const headers = Array.from(document.querySelectorAll('th, mat-header-cell')).map(th => th.innerText.trim()).filter(Boolean);
            const firstRowCells = Array.from(document.querySelectorAll('tr.mat-mdc-row, tr.mat-row, tbody tr')).slice(0, 1).map(row => {
                return Array.from(row.querySelectorAll('td, mat-cell')).map(td => ({
                    text: td.innerText.trim(),
                    html: td.innerHTML.slice(0, 200)
                }));
            });
            const summaryCards = Array.from(document.querySelectorAll('.kpi, .statistic, .summary, mat-card')).map(c => c.innerText.trim());
            const filters = Array.from(document.querySelectorAll('mat-form-field, .filter-item')).map(f => f.innerText.trim().replace(/\\s+/g, ' '));
            return {
                headers,
                firstRowCells,
                summaryCards,
                filters
            };
        }''')
        with open("scratch/ref_audit/agreements_deep.json", "w", encoding="utf-8") as f:
            json.dump(agreements_data, f, ensure_ascii=False, indent=2)

        # Inspect first row in agreements
        first_row_ag = await page.query_selector('tr.mat-mdc-row, tbody tr')
        if first_row_ag:
            print("Clicking first row in agreements...")
            await first_row_ag.click()
            await asyncio.sleep(3)
            await page.screenshot(path="scratch/ref_audit/agreement_row_click.png")
            ag_detail_info = await page.evaluate('''() => {
                return {
                    url: window.location.href,
                    bodyText: document.body.innerText.slice(0, 2000),
                    sections: Array.from(document.querySelectorAll('mat-card, .card, .section, mat-tab-group, mat-expansion-panel')).map(s => s.innerText.trim().slice(0, 300))
                };
            }''')
            with open("scratch/ref_audit/agreement_detail_deep.json", "w", encoding="utf-8") as f:
                json.dump(ag_detail_info, f, ensure_ascii=False, indent=2)

        # 3. Inspect Planned Visits
        print("--- Inspecting /planned-visits in depth ---")
        await page.goto("https://weapharma.bricks-rep.com/planned-visits", wait_until="networkidle")
        await asyncio.sleep(3)

        planned_visits_data = await page.evaluate('''() => {
            const bodyText = document.body.innerText.slice(0, 3000);
            const controls = Array.from(document.querySelectorAll('mat-form-field, button, mat-expansion-panel')).map(el => ({
                tag: el.tagName,
                text: el.innerText.trim().replace(/\\s+/g, ' ')
            }));
            return {
                bodyText,
                controls: controls.slice(0, 50)
            };
        }''')
        with open("scratch/ref_audit/planned_visits_deep.json", "w", encoding="utf-8") as f:
            json.dump(planned_visits_data, f, ensure_ascii=False, indent=2)

        await browser.close()
        print("Inspection script completed successfully!")

if __name__ == '__main__':
    asyncio.run(main())
