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
        await page.goto("https://weapharma.bricks-rep.com/agreements", wait_until="networkidle")
        await asyncio.sleep(3)

        # Inspect double click on first row or clicking the '#' link
        link = await page.query_selector('.ag-cell a, .ag-cell:has-text("#222")')
        if link:
            print("Found agreement link, clicking it...")
            await link.click()
            await asyncio.sleep(3)
            print("URL after link click:", page.url)
            await page.screenshot(path="scratch/ref_audit/agreement_detail_page.png")
            content = await page.evaluate('''() => {
                return {
                    url: window.location.href,
                    title: document.querySelector('.page-title, h1, h2, mat-toolbar')?.innerText || '',
                    body: document.body.innerText.slice(0, 2000),
                    inputs: Array.from(document.querySelectorAll('input, select, textarea, mat-select')).map(i => ({
                        tag: i.tagName,
                        value: i.value || i.innerText.trim(),
                        name: i.name || i.getAttribute('formcontrolname') || ''
                    }))
                };
            }''')
            print("Agreement detail content:", json.dumps(content, ensure_ascii=False, indent=2))

        # Check 'تغيير الحالة' button that appeared when row was selected
        row = await page.query_selector('.ag-row')
        if row:
            await row.click()
            await asyncio.sleep(1)
            btn_status = await page.query_selector('button:has-text("تغيير الحالة")')
            if btn_status:
                print("Clicking 'تغيير الحالة'...")
                await btn_status.click()
                await asyncio.sleep(1)
                menu_or_dialog = await page.evaluate('''() => {
                    const overlay = document.querySelector('.cdk-overlay-pane, mat-menu-panel, mat-dialog-container');
                    return overlay ? overlay.innerText : 'None';
                }''')
                print("'تغيير الحالة' opened:", menu_or_dialog)

        await browser.close()

if __name__ == '__main__':
    asyncio.run(main())
