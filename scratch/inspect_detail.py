import asyncio
import json
import os
import sys
from playwright.async_api import async_playwright

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

async def main():
    results = {}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={'width': 1600, 'height': 1000})
        page = await context.new_page()

        print("Navigating to login / home...")
        await page.goto("https://weapharma.bricks-rep.com/home", wait_until="networkidle")
        if "login" in page.url or "signin" in page.url or "auth" in page.url:
            await page.fill('input[type="email"], input[name="email"], input[formcontrolname="email"]', "wea.pharm2020@gmail.com")
            await page.fill('input[type="password"], input[name="password"], input[formcontrolname="password"]', "Wea@0000")
            btn = await page.query_selector('button[type="submit"]')
            if btn: await btn.click()
            await page.wait_for_load_state("networkidle")
            await asyncio.sleep(3)

        print("Navigating to /contacts...")
        await page.goto("https://weapharma.bricks-rep.com/contacts", wait_until="networkidle")
        await asyncio.sleep(2)

        # 1. Let's inspect the filter element and view buttons
        top_elements = await page.evaluate("""() => {
            return Array.from(document.querySelectorAll('button, a, input, [mattooltip], .filter-icon')).map(e => ({
                tag: e.tagName,
                class: e.className,
                text: e.innerText?.trim() || '',
                title: e.getAttribute('title') || e.getAttribute('mattooltip') || '',
                id: e.id,
                rect: e.getBoundingClientRect()
            })).filter(e => e.rect.width > 0 && e.rect.height > 0);
        }""")
        with open("scratch/top_elements.json", "w", encoding="utf-8") as f:
            json.dump(top_elements, f, ensure_ascii=False, indent=2)

        # 2. Click the first contact link
        print("Finding link for first contact...")
        # The link text contains [#16456]
        contact_link = await page.query_selector('a:has-text("[#16456]"), a:has-text("صيدلية سامي هلال"), span:has-text("صيدلية سامي هلال")')
        if not contact_link:
            # Let's find any link inside the table
            contact_link = await page.query_selector('table a, .mat-row a')

        if contact_link:
            print("Found contact link, clicking...")
            await contact_link.click()
            await page.wait_for_load_state("networkidle")
            await asyncio.sleep(3)
            print("Contact Detail URL:", page.url)
            await page.screenshot(path="scratch/screenshots/04_contact_detail_full.png", full_page=False)

            # Extract detail tabs
            tabs = await page.evaluate("""() => {
                return Array.from(document.querySelectorAll('.mat-tab-label, [role="tab"], .nav-link, button.tab')).map(t => t.innerText.trim());
            }""")
            print("Tabs on detail page:", tabs)
            results["detail_url"] = page.url
            results["detail_tabs"] = tabs

            # Extract detail page structure
            detail_data = await page.evaluate("""() => {
                return {
                    title: document.querySelector('h1, h2, h3, .title, [class*="header"]')?.innerText?.trim() || '',
                    all_cards: Array.from(document.querySelectorAll('.mat-card, .card, [class*="card"]')).map(c => c.innerText.trim()),
                    buttons: Array.from(document.querySelectorAll('button, a.btn')).map(b => b.innerText.trim()).filter(Boolean)
                };
            }""")
            results["detail_data"] = detail_data
            print("Detail Data buttons:", detail_data.get("buttons"))

            # Inspect and screenshot each tab
            tab_buttons = await page.query_selector_all('.mat-tab-label, [role="tab"]')
            print(f"Iterating through {len(tab_buttons)} tabs...")
            for idx in range(len(tab_buttons)):
                # re-select
                tbs = await page.query_selector_all('.mat-tab-label, [role="tab"]')
                if idx < len(tbs):
                    tb = tbs[idx]
                    txt = (await tb.inner_text()).replace('\n', ' ').strip()
                    print(f"Tab {idx}: {txt}")
                    await tb.click()
                    await asyncio.sleep(2)
                    await page.screenshot(path=f"scratch/screenshots/05_tab_{idx}.png", full_page=False)

            # Check if there is an Edit button or action
            edit_btn = await page.query_selector('button:has-text("تعديل"), a:has-text("تعديل"), button:has(mat-icon:has-text("edit"))')
            if edit_btn:
                print("Clicking Edit button (view-only)...")
                await edit_btn.click()
                await page.wait_for_load_state("networkidle")
                await asyncio.sleep(2)
                print("Edit page URL:", page.url)
                await page.screenshot(path="scratch/screenshots/06_contact_edit.png", full_page=False)
                results["edit_page_url"] = page.url

        with open("scratch/detail_inspection.json", "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)

        await browser.close()
        print("Inspection script completed successfully!")

if __name__ == '__main__':
    asyncio.run(main())
