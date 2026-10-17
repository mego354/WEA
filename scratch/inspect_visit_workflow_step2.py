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

        api_responses = {}
        async def on_response(response):
            if 'contacts/list' in response.url or 'visits' in response.url:
                try:
                    text = await response.text()
                    api_responses[response.url] = text[:2000]
                except:
                    pass
        page.on('response', on_response)

        print("=== Opening Quick Add Customer Selection ===")
        await page.goto("https://weapharma.bricks-rep.com/home", wait_until="networkidle")
        fab = await page.wait_for_selector('button.mdc-fab, button.mat-mdc-fab')
        await fab.click()
        await asyncio.sleep(1)

        btn_visit = await page.query_selector('app-quick-add button:has-text("تسجيل زيارة خارج الخطة")')
        await btn_visit.click()
        await asyncio.sleep(2)

        # Open select
        trigger = await page.query_selector('app-visit-create-customer-selection .mat-mdc-select-trigger, app-visit-create-customer-selection mat-select')
        await trigger.click()
        await asyncio.sleep(1.5)

        # Click second option (first customer)
        options = await page.query_selector_all('mat-option, .mat-mdc-option')
        if len(options) > 1:
            print("Clicking option:", await options[1].inner_text())
            await options[1].click()
            await asyncio.sleep(2)

            # Observe dialog or next step
            next_state = await page.evaluate('''() => {
                const dialog = document.querySelector('mat-dialog-container');
                const overlay = document.querySelector('.cdk-overlay-pane');
                return {
                    url: window.location.href,
                    dialogText: dialog ? dialog.innerText : null,
                    dialogHtml: dialog ? dialog.outerHTML.slice(0, 3000) : null,
                    buttons: Array.from(document.querySelectorAll('button')).map(b => b.innerText.trim()).filter(Boolean)
                };
            }''')
            print("State after customer selection:", json.dumps(next_state, ensure_ascii=False, indent=2))

            # Look for "بدء الزيارة" or "التالي" or template selection
            action_btn = await page.query_selector('button:has-text("بدء"), button:has-text("تسجيل"), button:has-text("التالي"), button:has-text("متابعة")')
            if action_btn:
                print("Found action button:", await action_btn.inner_text())
                await action_btn.click()
                await asyncio.sleep(3)
                print("State after clicking action button:", await page.evaluate('() => ({ url: window.location.href, text: document.body.innerText.slice(0, 2000) })'))

        print("=== Captured API Responses ===")
        for k, v in list(api_responses.items())[:5]:
            print(f"URL: {k}\nSnippet: {v[:500]}\n---")

        await browser.close()

if __name__ == '__main__':
    asyncio.run(main())
