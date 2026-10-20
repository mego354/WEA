import sys
sys.stdout.reconfigure(encoding='utf-8')
import asyncio
from playwright.async_api import async_playwright

async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        page.on('pageerror', lambda err: print(f"PAGE ERROR STACK:\n{err}\n{getattr(err, 'stack', 'No stack')}"))

        await page.goto('http://127.0.0.1:8080/auth/login/')
        await page.fill('input[name="email"]', 'wea.pharm2020@gmail.com')
        await page.fill('input[name="password"]', 'Wea@4444')
        await page.click('button[type="submit"]')
        await page.wait_for_load_state('networkidle')

        await page.click('.quick-add button')
        await page.wait_for_timeout(300)
        await page.click('button:has-text("تسجيل زيارة خارج الخطة")')
        await page.wait_for_timeout(300)

        search_input = page.locator('#unified-customer-search-input')
        await search_input.fill('ا')
        await page.wait_for_timeout(500)
        await page.locator('#unified-customer-results-list > div').first.click()
        await page.wait_for_timeout(500)

        await page.locator('#unified-modal-submit-btn').click()
        await page.wait_for_load_state('networkidle')
        print("Page URL after submit:", page.url)

        await browser.close()

if __name__ == '__main__':
    asyncio.run(run())
