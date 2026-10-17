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
            viewport={'width': 1440, 'height': 900}
        )
        page = await context.new_page()
        await page.goto("https://weapharma.bricks-rep.com/home", wait_until="networkidle")

        fab = await page.wait_for_selector('button.mdc-fab, button.mat-mdc-fab')
        await fab.click()
        await asyncio.sleep(1)

        btn_visit = await page.query_selector('app-quick-add button:has-text("تسجيل زيارة خارج الخطة")')
        if btn_visit:
            await btn_visit.click()
            await asyncio.sleep(2)

            info = await page.evaluate('''() => {
                const dialog = document.querySelector('mat-dialog-container, .cdk-overlay-pane:not(:empty)');
                if (!dialog) return { found: false, body: document.body.innerText.slice(0, 500) };
                return {
                    found: true,
                    dialogHtml: dialog.outerHTML.slice(0, 2000),
                    dialogText: dialog.innerText
                };
            }''')
            print("Dialog info:", json.dumps(info, ensure_ascii=False, indent=2))

        await browser.close()

if __name__ == '__main__':
    asyncio.run(main())
