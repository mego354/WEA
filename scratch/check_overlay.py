import asyncio
import os
import json

from playwright.async_api import async_playwright

async def check_overlay():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={'width': 1600, 'height': 1000}, storage_state="scratch/auth_state.json")
        page = await context.new_page()

        await page.goto("https://weapharma.bricks-rep.com/products", wait_until="domcontentloaded")
        await page.wait_for_selector('.ag-row', timeout=20000)
        await asyncio.sleep(2)

        # Click the more_vert button
        more_btn = await page.query_selector('.ag-row-first mat-icon, .ag-row-first [col-id="actions"]')
        if more_btn:
            await more_btn.click()
            await asyncio.sleep(1)
            overlay_text = await page.evaluate('''() => {
                const cdk = document.querySelector('.cdk-overlay-container');
                return {
                    text: cdk ? cdk.innerText : '',
                    buttons: cdk ? Array.from(cdk.querySelectorAll('button, a')).map(b => b.innerText.trim()) : []
                };
            }''')
            print("Overlay text:", overlay_text)
            with open("scratch/product_overlay.json", "w", encoding="utf-8") as f:
                json.dump(overlay_text, f, ensure_ascii=False, indent=2)

        await browser.close()

if __name__ == '__main__':
    asyncio.run(check_overlay())
