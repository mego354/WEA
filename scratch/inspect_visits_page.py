import asyncio
import json
import os
import sys
from playwright.async_api import async_playwright

if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            storage_state="scratch/auth_state.json",
            viewport={'width': 1600, 'height': 1000}
        )
        page = await context.new_page()

        apis = []
        async def on_res(res):
            if "/api/" in res.url:
                try:
                    if "json" in res.headers.get("content-type", ""):
                        apis.append({
                            "url": res.url,
                            "method": res.request.method,
                            "status": res.status,
                            "body": await res.json()
                        })
                except Exception:
                    pass

        page.on("response", on_res)

        print("Navigating to https://weapharma.bricks-rep.com/home ...")
        await page.goto("https://weapharma.bricks-rep.com/home", wait_until="domcontentloaded")
        
        # Wait for home dashboard content or sidebar
        await page.wait_for_selector('a[href="/home"], .navigation-item', timeout=15000)
        print("Home loaded. Current URL:", page.url)

        # Expand Activities menu
        print("Expanding Activities...")
        activities_btn = await page.wait_for_selector('text="الأنشطة"')
        await activities_btn.click()
        await asyncio.sleep(2)

        # Now click الزيارات
        print("Clicking الزيارات...")
        visits_link = await page.wait_for_selector('a[href="/visits"]')
        await visits_link.click()

        # Wait for visits page to load
        print("Waiting for /visits content...")
        await asyncio.sleep(6)
        await page.screenshot(path="scratch/activities_inspection/visits_actual.png")
        print("Captured scratch/activities_inspection/visits_actual.png")

        # Now click خطة الزيارات
        print("Clicking خطة الزيارات...")
        planned_link = await page.wait_for_selector('a[href="/planned-visits"]')
        await planned_link.click()
        await asyncio.sleep(6)
        await page.screenshot(path="scratch/activities_inspection/planned_visits_actual.png")
        print("Captured scratch/activities_inspection/planned_visits_actual.png")

        # Now click الاتفاقيات
        print("Clicking الاتفاقيات...")
        agreements_link = await page.wait_for_selector('a[href="/agreements"]')
        await agreements_link.click()
        await asyncio.sleep(6)
        await page.screenshot(path="scratch/activities_inspection/agreements_actual.png")
        print("Captured scratch/activities_inspection/agreements_actual.png")

        # Save all captured APIs
        with open("scratch/activities_inspection/apis_collected.json", "w", encoding="utf-8") as f:
            json.dump(apis, f, ensure_ascii=False, indent=2)

        print(f"Captured {len(apis)} API responses.")
        await browser.close()

if __name__ == '__main__':
    asyncio.run(main())
