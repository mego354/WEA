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
        context = await browser.new_context(viewport={'width': 1600, 'height': 1000})
        page = await context.new_page()

        await page.goto("https://weapharma.bricks-rep.com/home", wait_until="networkidle")
        if "login" in page.url or "signin" in page.url or "auth" in page.url:
            await page.fill('input[type="email"], input[name="email"], input[formcontrolname="email"]', "wea.pharm2020@gmail.com")
            await page.fill('input[type="password"], input[name="password"], input[formcontrolname="password"]', "Wea@0000")
            btn = await page.query_selector('button[type="submit"]')
            if btn: await btn.click()
            await page.wait_for_load_state("networkidle")
            await asyncio.sleep(2)

        # 1. Inspect Filter drawer on /contacts
        await page.goto("https://weapharma.bricks-rep.com/contacts", wait_until="networkidle")
        await asyncio.sleep(2)
        # Find filter button in top left. Let's find button near search
        filter_btn = await page.query_selector('button:has(mat-icon:has-text("filter_list")), button:has(mat-icon:has-text("tune")), [class*="filter-btn"], button[matbadge]')
        if not filter_btn:
            # Let's find all buttons in top bar
            filter_btn = await page.query_selector('mat-icon:has-text("filter_list"), mat-icon:has-text("tune")')
        if filter_btn:
            print("Found filter icon/button, clicking...")
            await filter_btn.click()
            await asyncio.sleep(1.5)
            await page.screenshot(path="scratch/screenshots/03_filter_drawer_opened.png")

        # 2. Go to contact detail
        await page.goto("https://weapharma.bricks-rep.com/contacts/a7517dbe-6c74-402a-8408-a201e108b89f/overview", wait_until="networkidle")
        await asyncio.sleep(2)

        # Expand each accordion
        expand_icons = await page.query_selector_all('mat-icon:has-text("expand_more")')
        print(f"Found {len(expand_icons)} expand_more icons.")
        for idx, icon in enumerate(expand_icons):
            try:
                await icon.click()
                await asyncio.sleep(0.5)
            except Exception as e:
                print(f"Failed to click icon {idx}: {e}")

        await asyncio.sleep(1)
        await page.screenshot(path="scratch/screenshots/all_accordions_expanded.png")

        # Extract full HTML of the accordion sidebar
        sidebar_html = await page.evaluate("""() => {
            const side = document.querySelector('.sidebar, [class*="side"], [class*="info"], [class*="details"]') || document.body;
            return side.innerText;
        }""")
        with open("scratch/all_sidebar_text.txt", "w", encoding="utf-8") as f:
            f.write(sidebar_html)

        # 3. Open Edit page
        three_dots = await page.query_selector('button:has(mat-icon:has-text("more_vert"))')
        if three_dots:
            await three_dots.click()
            await asyncio.sleep(1)
            edit_item = await page.query_selector('button:has-text("تعديل")')
            if edit_item:
                print("Clicking 'تعديل'...")
                await edit_item.click()
                await page.wait_for_load_state("networkidle")
                await asyncio.sleep(2)
                print("Edit page URL:", page.url)
                await page.screenshot(path="scratch/screenshots/06_edit_page.png", full_page=True)

        await browser.close()
        print("Completed!")

if __name__ == '__main__':
    asyncio.run(main())
