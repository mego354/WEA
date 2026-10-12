import asyncio
import json
import os
import sys
from playwright.async_api import async_playwright

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={'width': 1600, 'height': 1200})
        page = await context.new_page()

        print("Logging in...")
        await page.goto("https://weapharma.bricks-rep.com/home", wait_until="networkidle")
        if "login" in page.url or "signin" in page.url or "auth" in page.url:
            await page.fill('input[type="email"]', "wea.pharm2020@gmail.com")
            await page.fill('input[type="password"]', "Wea@0000")
            btn = await page.query_selector('button[type="submit"]')
            if btn: await btn.click()
            await page.wait_for_load_state("networkidle")
            await asyncio.sleep(2)

        # 1. Expand 'المعلومات الإضافية', 'حساب العميل', 'العناوين'
        await page.goto("https://weapharma.bricks-rep.com/contacts/a7517dbe-6c74-402a-8408-a201e108b89f/overview", wait_until="networkidle")
        await asyncio.sleep(2)

        for name in ["المعلومات الإضافية", "حساب العميل", "العناوين"]:
            el = await page.query_selector(f'text="{name}"')
            if el:
                await el.click()
                await asyncio.sleep(0.8)

        await page.screenshot(path="scratch/screenshots/sidebar_expanded_top.png")

        # 2. Test edit page navigation or click
        three_dots = await page.query_selector('button:has(mat-icon:has-text("more_vert"))')
        if three_dots:
            await three_dots.click()
            await asyncio.sleep(1)
            # Click the edit button
            edit_btn = await page.query_selector('.mat-menu-panel button:has-text("تعديل")')
            if edit_btn:
                print("Clicking edit button...")
                await edit_btn.click()
                await page.wait_for_load_state("networkidle")
                await asyncio.sleep(3)
                print("Navigated to URL:", page.url)
                await page.screenshot(path="scratch/screenshots/06_contact_edit_page.png", full_page=True)

        # Also let's check create page
        print("Navigating to /contacts/create...")
        await page.goto("https://weapharma.bricks-rep.com/contacts/create", wait_until="networkidle")
        await asyncio.sleep(2)
        print("Create page URL:", page.url)
        await page.screenshot(path="scratch/screenshots/07_contact_create_page.png", full_page=True)

        await browser.close()
        print("All done!")

if __name__ == '__main__':
    asyncio.run(main())
