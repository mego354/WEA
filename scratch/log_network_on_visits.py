import asyncio
import json
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

        requests_log = []

        async def on_request(req):
            if "/api/" in req.url:
                print(f">> {req.method} {req.url}")
                requests_log.append({
                    "method": req.method,
                    "url": req.url,
                    "post_data": req.post_data
                })

        async def on_response(res):
            if "/api/" in res.url:
                try:
                    ct = res.headers.get("content-type", "")
                    if "json" in ct:
                        data = await res.json()
                        print(f"<< {res.status} {res.url}")
                        # find request
                        for r in requests_log:
                            if r["url"] == res.url:
                                r["status"] = res.status
                                r["response"] = data
                                break
                except Exception:
                    pass

        page.on("request", on_request)
        page.on("response", on_response)

        print("Navigating to /home ...")
        await page.goto("https://weapharma.bricks-rep.com/home", wait_until="domcontentloaded")
        await page.wait_for_selector('a[href="/home"]', timeout=15000)

        # Click on الأنشطة
        print("Clicking الأنشطة ...")
        activities_btn = await page.wait_for_selector('text="الأنشطة"')
        await activities_btn.click()
        await asyncio.sleep(2)

        # Click on الزيارات
        print("Clicking a[href='/visits'] ...")
        visits_btn = await page.wait_for_selector('a[href="/visits"]')
        await visits_btn.click()
        await asyncio.sleep(8)
        await page.screenshot(path="scratch/activities_inspection/visits_clicked_live.png")

        # Click on خطة الزيارات
        print("Clicking a[href='/planned-visits'] ...")
        pv_btn = await page.wait_for_selector('a[href="/planned-visits"]')
        await pv_btn.click()
        await asyncio.sleep(8)
        await page.screenshot(path="scratch/activities_inspection/planned_visits_clicked_live.png")

        # Click on الاتفاقيات
        print("Clicking a[href='/agreements'] ...")
        ag_btn = await page.wait_for_selector('a[href="/agreements"]')
        await ag_btn.click()
        await asyncio.sleep(8)
        await page.screenshot(path="scratch/activities_inspection/agreements_clicked_live.png")

        with open("scratch/activities_inspection/live_network_log.json", "w", encoding="utf-8") as f:
            json.dump(requests_log, f, ensure_ascii=False, indent=2)

        print("\nSaved network log to scratch/activities_inspection/live_network_log.json")
        await browser.close()

if __name__ == '__main__':
    asyncio.run(main())
