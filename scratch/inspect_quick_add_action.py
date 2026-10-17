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

        print("Navigating to https://weapharma.bricks-rep.com/home ...")
        await page.goto("https://weapharma.bricks-rep.com/home", wait_until="networkidle")

        fab = await page.wait_for_selector('button.mdc-fab, button.mat-mdc-fab')
        await fab.click()
        await asyncio.sleep(1)

        # Inspect all buttons inside app-quick-add
        items = await page.evaluate('''() => {
            const btns = Array.from(document.querySelectorAll('app-quick-add button, app-quick-add a'));
            return btns.map(b => ({
                text: b.innerText.trim(),
                tag: b.tagName,
                onclick: b.getAttribute('onclick'),
                href: b.getAttribute('href')
            }));
        }''')
        print("Quick Add items:", json.dumps(items, ensure_ascii=False, indent=2))

        # Click the first item: "تسجيل زيارة خارج الخطة"
        print("Clicking 'تسجيل زيارة خارج الخطة'...")
        btn_visit = await page.query_selector('app-quick-add button:has-text("تسجيل زيارة خارج الخطة")')
        if btn_visit:
            await btn_visit.click()
            await asyncio.sleep(3)
            print("Current URL after click:", page.url)
            await page.screenshot(path="scratch/ref_audit/quick_add_visit_result.png")

            # Check if a dialog or page opened
            dialog_or_form = await page.evaluate('''() => {
                const dialog = document.querySelector('mat-dialog-container, .cdk-overlay-pane, form');
                return {
                    url: window.location.href,
                    title: document.querySelector('h1, h2, .title, mat-toolbar')?.innerText || '',
                    inputs: Array.from(document.querySelectorAll('input, select, mat-select, textarea')).map(i => ({
                        type: i.type || i.tagName,
                        name: i.name || i.getAttribute('formcontrolname') || '',
                        placeholder: i.placeholder || '',
                        aria: i.getAttribute('aria-label') || ''
                    }))
                };
            }''')
            print("Opened dialog or page:", json.dumps(dialog_or_form, ensure_ascii=False, indent=2))

        await browser.close()

if __name__ == '__main__':
    asyncio.run(main())
