import asyncio, sys
sys.stdout.reconfigure(encoding='utf-8')
from playwright.async_api import async_playwright

async def test_responsive():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        for w, h, name in [(375, 812, 'mobile'), (768, 1024, 'tablet'), (1280, 800, 'laptop')]:
            context = await browser.new_context(viewport={'width': w, 'height': h})
            page = await context.new_page()
            await page.goto('http://127.0.0.1:8080/auth/login/', wait_until='networkidle')
            await page.fill('input[name="email"]', 'wea.pharm2020@gmail.com')
            await page.fill('input[name="password"]', 'Wea@4444')
            await page.click('button[type="submit"]')
            await page.wait_for_load_state('networkidle')

            await page.goto('http://127.0.0.1:8080/home/', wait_until='networkidle')
            await asyncio.sleep(1)
            await page.screenshot(path=f'scratch/home_{name}.png')
            print(f'Captured scratch/home_{name}.png ({w}x{h})')
        await browser.close()

if __name__ == '__main__':
    asyncio.run(test_responsive())
