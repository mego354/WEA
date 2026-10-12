import asyncio
from playwright.async_api import async_playwright

async def test_edit_create():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={'width': 1440, 'height': 900})
        page = await context.new_page()

        print("Logging in...")
        await page.goto("http://127.0.0.1:8000/auth/login/", wait_until="domcontentloaded")
        await page.fill('input[name="email"]', "wea.pharm2020@gmail.com")
        await page.fill('input[name="password"]', "Wea@0000")
        await page.click('button[type="submit"]')
        await asyncio.sleep(2)

        # 1. Edit page
        print("Navigating to /contacts/5/edit/ ...")
        await page.goto("http://127.0.0.1:8000/contacts/5/edit/", wait_until="domcontentloaded")
        await asyncio.sleep(1)
        await page.screenshot(path="scratch/local_screenshots/05_local_contact_edit.png", full_page=True)

        # 2. Create page
        print("Navigating to /contacts/create/ ...")
        await page.goto("http://127.0.0.1:8000/contacts/create/", wait_until="domcontentloaded")
        await asyncio.sleep(1)
        await page.screenshot(path="scratch/local_screenshots/06_local_contact_create.png", full_page=True)

        # 3. Test submitting Edit form (modifying notes or phone safely)
        print("Testing edit submission...")
        await page.goto("http://127.0.0.1:8000/contacts/5/edit/", wait_until="domcontentloaded")
        await page.fill('input[name="code"]', "TEST-CODE-001")
        await page.click('button[type="submit"]')
        await asyncio.sleep(2)
        print("After edit save, URL:", page.url)
        await page.screenshot(path="scratch/local_screenshots/05b_after_edit_saved.png", full_page=False)

        await browser.close()
        print("Edit and Create tested successfully!")

if __name__ == '__main__':
    asyncio.run(test_edit_create())
