import asyncio
import sys
sys.stdout.reconfigure(encoding='utf-8')
from playwright.async_api import async_playwright

async def inspect():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        # Use saved auth state
        context = await browser.new_context(
            storage_state="scratch/auth_state.json",
            viewport={'width': 1600, 'height': 1200}
        )
        page = await context.new_page()

        print("Navigating to https://weapharma.bricks-rep.com/home ...")
        await page.goto("https://weapharma.bricks-rep.com/home", wait_until="networkidle")
        await asyncio.sleep(2)

        # Check if redirected to login
        if "login" in page.url:
            print("Session expired, logging in...")
            await page.fill('input[type="email"], input[name="email"], input[formcontrolname="email"]', "wea.pharm2020@gmail.com")
            await page.fill('input[type="password"], input[name="password"], input[formcontrolname="password"]', "Wea@4444")
            btn = await page.query_selector('button[type="submit"]')
            if btn: await btn.click()
            await page.wait_for_load_state("networkidle")
            await asyncio.sleep(3)
            await context.storage_state(path="scratch/auth_state.json")

        print("Current URL:", page.url)
        # Take full page screenshot
        await page.screenshot(path="scratch/ref_home_fullpage.png", full_page=True)
        print("Captured full page screenshot to scratch/ref_home_fullpage.png")

        # Extract text of all dashboard cards and widgets
        cards = await page.evaluate("""() => {
            const elements = [];
            // Query cards and sections
            document.querySelectorAll('mat-card, .mat-card, .dashboard-card, .kpi-card, div[class*="card"]').forEach(el => {
                if (el.innerText.trim()) {
                    elements.push({
                        tag: el.tagName,
                        classes: el.className,
                        text: el.innerText.trim()
                    });
                }
            });
            return {
                title: document.title,
                bodyText: document.body.innerText,
                cards: elements
            };
        }""")

        import json
        with open("scratch/ref_home_dom.json", "w", encoding="utf-8") as f:
            json.dump(cards, f, ensure_ascii=False, indent=2)

        print("Dumped DOM details to scratch/ref_home_dom.json")
        await browser.close()

if __name__ == '__main__':
    asyncio.run(inspect())
