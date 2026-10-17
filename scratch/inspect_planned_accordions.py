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

        print("Inspecting /planned-visits with previous date range to find planned days...")
        # Navigate to planned-visits
        await page.goto("https://weapharma.bricks-rep.com/planned-visits", wait_until="networkidle")
        await asyncio.sleep(3)

        # Look at the rep dropdown or select a rep
        reps = await page.evaluate('''() => {
            const selects = Array.from(document.querySelectorAll('mat-select, select')).map(s => s.innerText.trim());
            return selects;
        }''')
        print("Selects on planned-visits:", reps)

        # Inspect day accordion structure
        accordion_sample = await page.evaluate('''() => {
            const panels = Array.from(document.querySelectorAll('mat-expansion-panel')).map(p => ({
                header: p.querySelector('mat-expansion-panel-header')?.innerText.trim(),
                expanded: p.classList.contains('mat-expanded'),
                content: p.querySelector('.mat-expansion-panel-content')?.innerText.trim().slice(0, 300)
            }));
            return panels.slice(0, 5);
        }''')
        print("Accordions sample:", json.dumps(accordion_sample, ensure_ascii=False, indent=2))

        await browser.close()

if __name__ == '__main__':
    asyncio.run(main())
