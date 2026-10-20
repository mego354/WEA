import asyncio, sys
sys.stdout.reconfigure(encoding='utf-8')
from playwright.async_api import async_playwright

async def verify_home():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        # Login or use cookie
        context = await browser.new_context(viewport={'width': 1600, 'height': 1200})
        page = await context.new_page()

        console_errors = []
        page.on('console', lambda msg: console_errors.append(msg.text) if msg.type == 'error' else None)

        print("Navigating to http://127.0.0.1:8080/auth/login/ ...")
        await page.goto("http://127.0.0.1:8080/auth/login/", wait_until="networkidle")
        await page.fill('input[name="email"]', "wea.pharm2020@gmail.com")
        await page.fill('input[name="password"]', "Wea@4444")
        await page.click('button[type="submit"]')
        await page.wait_for_load_state("networkidle")
        await asyncio.sleep(1)

        print("Navigating to http://127.0.0.1:8080/home/ ...")
        await page.goto("http://127.0.0.1:8080/home/", wait_until="networkidle")
        await asyncio.sleep(2)

        # Check title and elements
        title = await page.title()
        print("Page title:", title)

        # Take screenshot 1
        await page.screenshot(path="scratch/local_home_screen1.png")
        print("Captured scratch/local_home_screen1.png")

        # Scroll down and capture charts
        await page.mouse.wheel(0, 700)
        await asyncio.sleep(1)
        await page.screenshot(path="scratch/local_home_screen2.png")
        print("Captured scratch/local_home_screen2.png")

        # Check console errors
        print("Console errors count:", len(console_errors))
        for err in console_errors:
            print("  Error:", err)

        # Also test with ?period=all
        print("Testing ?period=all ...")
        await page.goto("http://127.0.0.1:8080/home/?period=all", wait_until="networkidle")
        await asyncio.sleep(1)
        await page.screenshot(path="scratch/local_home_all_time.png")
        print("Captured scratch/local_home_all_time.png")

        await browser.close()

if __name__ == '__main__':
    asyncio.run(verify_home())
