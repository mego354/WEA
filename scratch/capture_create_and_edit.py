import asyncio
import os
import sys
from playwright.async_api import async_playwright

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            storage_state="scratch/auth_state.json",
            viewport={'width': 1600, 'height': 1200}
        )
        page = await context.new_page()

        print("Navigating to /contacts/create with domcontentloaded ...")
        await page.goto("https://weapharma.bricks-rep.com/contacts/create", wait_until="domcontentloaded")
        await asyncio.sleep(4)
        print("Create page URL:", page.url)
        await page.screenshot(path="scratch/screenshots/07_contact_create_page.png", full_page=True)

        print("Navigating to contact detail...")
        await page.goto("https://weapharma.bricks-rep.com/contacts/a7517dbe-6c74-402a-8408-a201e108b89f/overview", wait_until="domcontentloaded")
        await asyncio.sleep(3)

        # Click 3-dots
        three_dots = await page.query_selector('button:has(mat-icon:has-text("more_vert"))')
        if three_dots:
            await three_dots.click()
            await asyncio.sleep(1)
            edit_btn = await page.query_selector('.mat-menu-content button:has-text("تعديل")')
            if edit_btn:
                print("Clicking Edit button in menu...")
                await edit_btn.click()
                await asyncio.sleep(4)
                print("Edit page URL:", page.url)
                await page.screenshot(path="scratch/screenshots/06_contact_edit_page.png", full_page=True)

        await browser.close()
        print("Done!")

if __name__ == '__main__':
    asyncio.run(main())
