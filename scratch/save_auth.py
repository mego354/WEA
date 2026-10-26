import asyncio
from playwright.async_api import async_playwright

async def login_and_save():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={'width': 1600, 'height': 1000})
        page = await context.new_page()

        print("Navigating to https://weapharma.bricks-rep.com/home ...")
        await page.goto("https://weapharma.bricks-rep.com/home", wait_until="networkidle")
        if "login" in page.url or "signin" in page.url or "auth" in page.url:
            await page.wait_for_selector('input[type="email"], input[name="email"], input[formcontrolname="email"]')
            await page.fill('input[type="email"], input[name="email"], input[formcontrolname="email"]', "wea.pharm2020@gmail.com")
            await page.fill('input[type="password"], input[name="password"], input[formcontrolname="password"]', "Wea@4444")
            btn = await page.query_selector('button[type="submit"]')
            if btn: await btn.click()
            await page.wait_for_load_state("networkidle")
            await asyncio.sleep(3)

        await context.storage_state(path="scratch/auth_state.json")
        print("Logged in and saved auth_state.json!")
        await browser.close()

if __name__ == '__main__':
    asyncio.run(login_and_save())
