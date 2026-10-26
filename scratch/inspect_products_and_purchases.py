import asyncio
import json
import os
from playwright.async_api import async_playwright

async def inspect_products_and_purchases():
    os.makedirs("scratch/screenshots/products", exist_ok=True)
    os.makedirs("scratch/screenshots/purchases", exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        # Use storage state if available
        state_path = "scratch/auth_state.json" if os.path.exists("scratch/auth_state.json") else None
        context = await browser.new_context(viewport={'width': 1600, 'height': 1000}, storage_state=state_path)
        page = await context.new_page()

        print("Navigating to https://weapharma.bricks-rep.com/home ...")
        try:
            await page.goto("https://weapharma.bricks-rep.com/home", wait_until="domcontentloaded", timeout=60000)
            await asyncio.sleep(4)
        except Exception as e:
            print(f"Error navigating: {e}")

        # If on login page, log in
        if "login" in page.url or "signin" in page.url or "auth" in page.url:
            print("Logging in...")
            await page.wait_for_selector('input[type="email"], input[name="email"], input[formcontrolname="email"]')
            await page.fill('input[type="email"], input[name="email"], input[formcontrolname="email"]', "wea.pharm2020@gmail.com")
            await page.fill('input[type="password"], input[name="password"], input[formcontrolname="password"]', "Wea@4444")
            btn = await page.query_selector('button[type="submit"]')
            if btn: await btn.click()
            await asyncio.sleep(5)
            await context.storage_state(path="scratch/auth_state.json")
            print("Saved storage state.")

        print("Current URL:", page.url)
        await page.screenshot(path="scratch/screenshots/00_home.png")

        # Explore sidebar menus
        sidebar_items = await page.evaluate('''() => {
            const items = [];
            document.querySelectorAll('a, button, mat-list-item, .nav-item, [role="button"]').forEach(el => {
                const text = el.innerText ? el.innerText.trim() : '';
                const href = el.getAttribute('href') || '';
                if (text || href) {
                    items.push({ text: text.replace(/\\n/g, ' '), href, tag: el.tagName, class: el.className });
                }
            });
            return items;
        }''')
        with open("scratch/sidebar_items.json", "w", encoding="utf-8") as f:
            json.dump(sidebar_items, f, ensure_ascii=False, indent=2)

        # Let's find elements for المنتجات and المشتريات
        menu_info = await page.evaluate('''() => {
            const results = [];
            // Look for menu links or buttons containing المنتجات or المشتريات
            const elements = Array.from(document.querySelectorAll('*'));
            for (const el of elements) {
                if (el.children.length === 0 && (el.textContent.includes('المنتجات') || el.textContent.includes('المشتريات'))) {
                    results.push({
                        text: el.textContent.trim(),
                        parentTag: el.parentElement ? el.parentElement.tagName : '',
                        parentHref: el.parentElement ? el.parentElement.getAttribute('href') : '',
                        parentClass: el.parentElement ? el.parentElement.className : '',
                        grandParentTag: el.parentElement && el.parentElement.parentElement ? el.parentElement.parentElement.tagName : '',
                        grandParentHref: el.parentElement && el.parentElement.parentElement ? el.parentElement.parentElement.getAttribute('href') : '',
                    });
                }
            }
            return results;
        }''')
        print("Menu matches:", json.dumps(menu_info, ensure_ascii=False, indent=2))

        await browser.close()

if __name__ == '__main__':
    asyncio.run(inspect_products_and_purchases())
