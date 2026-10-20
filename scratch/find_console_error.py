import sys
sys.stdout.reconfigure(encoding='utf-8')
import asyncio
from playwright.async_api import async_playwright

async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        def on_console(msg):
            if msg.type == 'error':
                print(f"[CONSOLE ERROR on {page.url}]: {msg.text} (location: {msg.location})")
        page.on('console', on_console)
        page.on('pageerror', lambda err: print(f"[PAGE ERROR on {page.url}]: {err}"))

        await page.goto('http://127.0.0.1:8080/auth/login/')
        await page.fill('input[name="email"]', 'wea.pharm2020@gmail.com')
        await page.fill('input[name="password"]', 'Wea@4444')
        await page.click('button[type="submit"]')
        await page.wait_for_load_state('networkidle')

        await page.goto('http://127.0.0.1:8080/contacts/')
        await page.wait_for_load_state('networkidle')

        await page.goto('http://127.0.0.1:8080/visits/create/')
        await page.wait_for_load_state('networkidle')

        await browser.close()

if __name__ == '__main__':
    asyncio.run(run())
