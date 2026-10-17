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

        for route in ['/places', '/locations', '/settings/places', '/settings/location', '/settings/areas']:
            url = f"https://weapharma.bricks-rep.com{route}"
            resp = await page.goto(url, wait_until="networkidle")
            await asyncio.sleep(1)
            title = await page.title()
            final_url = page.url
            body_snippet = (await page.evaluate('() => document.body.innerText')).strip()[:300].replace('\n', ' ')
            print(f"Route: {route} -> Status: {resp.status if resp else 'N/A'}, Final URL: {final_url}, Title: {title}")
            print(f"   Snippet: {body_snippet}\n")

        await browser.close()

if __name__ == '__main__':
    asyncio.run(main())
