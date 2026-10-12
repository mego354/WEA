import asyncio
import json
import os
from playwright.async_api import async_playwright

async def inspect_submenus():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={'width': 1600, 'height': 1000}, storage_state="scratch/auth_state.json")
        page = await context.new_page()

        await page.goto("https://weapharma.bricks-rep.com/home", wait_until="domcontentloaded")
        await asyncio.sleep(4)

        # Click on المنتجات
        print("Clicking on المنتجات ...")
        products_menu = await page.query_selector('a:has-text("المنتجات"), mat-mdc-list-item:has-text("المنتجات")')
        if products_menu:
            await products_menu.click()
            await asyncio.sleep(2)
            await page.screenshot(path="scratch/screenshots/01_products_expanded.png")

        # Click on المشتريات
        print("Clicking on المشتريات ...")
        purchases_menu = await page.query_selector('a:has-text("المشتريات"), mat-mdc-list-item:has-text("المشتريات")')
        if purchases_menu:
            await purchases_menu.click()
            await asyncio.sleep(2)
            await page.screenshot(path="scratch/screenshots/02_purchases_expanded.png")

        # Extract all links now visible in the navigation sidebar
        nav_links = await page.evaluate('''() => {
            const links = [];
            document.querySelectorAll('a[href], mat-mdc-list-item, .navigation-item, .sub-menu a, .mat-mdc-list-item').forEach(el => {
                const text = el.innerText ? el.innerText.trim().replace(/\\n/g, ' ') : '';
                const href = el.getAttribute('href') || (el.querySelector('a') ? el.querySelector('a').getAttribute('href') : '');
                if (text) {
                    links.push({ text, href, visible: el.offsetParent !== null });
                }
            });
            return links;
        }''')

        with open("scratch/expanded_nav_links.json", "w", encoding="utf-8") as f:
            json.dump(nav_links, f, ensure_ascii=False, indent=2)

        print("Extracted nav links count:", len(nav_links))
        await browser.close()

if __name__ == '__main__':
    asyncio.run(inspect_submenus())
