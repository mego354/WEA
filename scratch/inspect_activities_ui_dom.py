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

        await page.goto("https://weapharma.bricks-rep.com/home", wait_until="domcontentloaded")
        await page.wait_for_selector('a[href="/home"]', timeout=15000)

        results = {}

        routes = [
            ("visits", "https://weapharma.bricks-rep.com/visits"),
            ("planned_visits", "https://weapharma.bricks-rep.com/planned-visits"),
            ("agreements", "https://weapharma.bricks-rep.com/agreements"),
            ("calls", "https://weapharma.bricks-rep.com/calls"),
        ]

        for key, url in routes:
            print(f"Inspecting {key} at {url}...")
            await page.goto(url, wait_until="domcontentloaded")
            await asyncio.sleep(5)

            info = await page.evaluate('''() => {
                const getTexts = sel => Array.from(document.querySelectorAll(sel)).map(e => e.innerText.trim()).filter(Boolean);
                
                const buttons = Array.from(document.querySelectorAll('button, a.btn, a.button')).map(b => ({
                    text: b.innerText.trim(),
                    aria: b.getAttribute('aria-label') || '',
                    classes: b.className
                })).filter(b => b.text || b.aria);

                const tableHeaders = Array.from(document.querySelectorAll('th, .mat-header-cell')).map(th => th.innerText.trim()).filter(Boolean);
                
                const filters = Array.from(document.querySelectorAll('.filter-item, mat-form-field, .form-group, [role="combobox"]')).map(f => f.innerText.trim().replace(/\\n+/g, ' ')).filter(Boolean);

                const title = document.querySelector('h1, h2, .page-title, .title')?.innerText || '';

                return {
                    title,
                    buttons,
                    tableHeaders,
                    filters: filters.slice(0, 20),
                    bodyTextPreview: document.body.innerText.slice(0, 500)
                };
            }''')
            results[key] = info

        with open('scratch/activities_ui_dom.json', 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)

        print("Saved scratch/activities_ui_dom.json")
        await browser.close()

if __name__ == '__main__':
    asyncio.run(main())
