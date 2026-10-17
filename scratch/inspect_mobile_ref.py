import asyncio
import json
import os
import sys
from playwright.async_api import async_playwright

sys.stdout.reconfigure(encoding='utf-8')

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        # Mobile viewport 390x844 (iPhone 12/13/14)
        context = await browser.new_context(
            storage_state="scratch/auth_state.json",
            viewport={'width': 390, 'height': 844},
            is_mobile=True,
            has_touch=True
        )
        page = await context.new_page()

        os.makedirs("scratch/ref_audit/mobile", exist_ok=True)

        pages = [
            ("home", "https://weapharma.bricks-rep.com/home"),
            ("visits", "https://weapharma.bricks-rep.com/visits"),
            ("planned_visits", "https://weapharma.bricks-rep.com/planned-visits"),
            ("agreements", "https://weapharma.bricks-rep.com/agreements"),
        ]

        for name, url in pages:
            print(f"Inspecting mobile for {name} ({url})...")
            await page.goto(url, wait_until="networkidle")
            await asyncio.sleep(3)
            await page.screenshot(path=f"scratch/ref_audit/mobile/{name}_390x844.png")

            # Check floating button location and bottom navigation
            ui_info = await page.evaluate('''() => {
                const fab = document.querySelector('button.mdc-fab, button.mat-mdc-fab');
                const bottomNav = document.querySelector('.bottom-nav, mat-bottom-nav, [role="navigation"]');
                const fabRect = fab ? fab.getBoundingClientRect() : null;
                const header = document.querySelector('mat-toolbar, .header, header');
                return {
                    fabPresent: !!fab,
                    fabRect,
                    bottomNavPresent: !!bottomNav,
                    headerText: header ? header.innerText.trim() : ''
                };
            }''')
            print(f"Mobile UI info for {name}:", json.dumps(ui_info, ensure_ascii=False, indent=2))

        await browser.close()
        print("Mobile inspection complete!")

if __name__ == '__main__':
    asyncio.run(main())
