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
        context = None
        if os.path.exists("scratch/auth_state.json"):
            context = await browser.new_context(
                storage_state="scratch/auth_state.json",
                viewport={'width': 1600, 'height': 1000}
            )
        else:
            context = await browser.new_context(viewport={'width': 1600, 'height': 1000})

        page = await context.new_page()

        api_requests = []
        page.on("request", lambda req: api_requests.append({
            "url": req.url,
            "method": req.method,
            "headers": dict(req.headers)
        }) if "/api/" in req.url else None)

        print("Navigating to https://weapharma.bricks-rep.com/home ...")
        await page.goto("https://weapharma.bricks-rep.com/home", wait_until="networkidle")

        # Check if redirected to login
        if "login" in page.url or "signin" in page.url or "auth" in page.url:
            print("Logging in...")
            await page.wait_for_selector('input[type="email"], input[name="email"], input[formcontrolname="email"]')
            await page.fill('input[type="email"], input[name="email"], input[formcontrolname="email"]', "wea.pharm2020@gmail.com")
            await page.fill('input[type="password"], input[name="password"], input[formcontrolname="password"]', "Wea@0000")
            btn = await page.query_selector('button[type="submit"]')
            if btn:
                await btn.click()
            await page.wait_for_load_state("networkidle")
            await asyncio.sleep(3)
            await context.storage_state(path="scratch/auth_state.json")
            print("Logged in and updated auth_state.json. Current URL:", page.url)

        # Inspect sidebar
        await page.wait_for_selector('nav, .navigation, mat-nav-list, aside', timeout=10000)
        await page.screenshot(path="scratch/home_loaded.png")
        print("Captured home_loaded.png")

        # Find "الأنشطة" element
        activities_elem = None
        items = await page.query_selector_all('a, button, mat-list-item, .navigation-item')
        for item in items:
            txt = (await item.inner_text()).strip()
            if "الأنشطة" in txt:
                activities_elem = item
                print("Found Activities item:", txt)
                break

        if activities_elem:
            await activities_elem.click()
            await asyncio.sleep(2)
            await page.screenshot(path="scratch/activities_clicked.png")
            print("Clicked Activities item. Captured activities_clicked.png")

        # Extract all visible links now in the sidebar / navigation
        nav_links = await page.evaluate('''() => {
            const links = [];
            document.querySelectorAll('a, button, mat-list-item, .navigation-item, .sub-item').forEach(el => {
                const text = el.innerText ? el.innerText.trim() : '';
                const href = el.getAttribute('href') || '';
                if (text || href) {
                    links.push({
                        text: text.replace(/\\s+/g, ' '),
                        href: href,
                        tag: el.tagName,
                        classes: el.className
                    });
                }
            });
            return links;
        }''')

        with open("scratch/nav_links_after_activities.json", "w", encoding="utf-8") as f:
            json.dump(nav_links, f, ensure_ascii=False, indent=2)

        print(f"Dumped {len(nav_links)} nav items to scratch/nav_links_after_activities.json")

        await browser.close()

if __name__ == '__main__':
    asyncio.run(main())
