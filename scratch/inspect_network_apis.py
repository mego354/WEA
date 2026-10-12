import asyncio
import os
import json

from playwright.async_api import async_playwright

async def inspect_network():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={'width': 1600, 'height': 1000}, storage_state="scratch/auth_state.json")
        page = await context.new_page()

        api_calls = []

        async def handle_response(response):
            if "/api/" in response.url:
                try:
                    content_type = response.headers.get("content-type", "")
                    if "json" in content_type:
                        data = await response.json()
                        api_calls.append({
                            "url": response.url,
                            "status": response.status,
                            "method": response.request.method,
                            "data_preview": data if isinstance(data, list) else (list(data.keys()) if isinstance(data, dict) else str(data)[:200])
                        })
                except Exception:
                    pass

        page.on("response", handle_response)

        print("Navigating to /products ...")
        await page.goto("https://weapharma.bricks-rep.com/products", wait_until="domcontentloaded")
        await asyncio.sleep(4)

        print("Navigating to /purchase-orders ...")
        await page.goto("https://weapharma.bricks-rep.com/purchase-orders", wait_until="domcontentloaded")
        await asyncio.sleep(4)

        with open("scratch/api_calls.json", "w", encoding="utf-8") as f:
            json.dump(api_calls, f, ensure_ascii=False, indent=2)

        print(f"Captured {len(api_calls)} API calls!")
        await browser.close()

if __name__ == '__main__':
    asyncio.run(inspect_network())
