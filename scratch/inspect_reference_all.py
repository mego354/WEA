import asyncio
import json
import os
import sys

# Ensure UTF-8 output
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from playwright.async_api import async_playwright

async def inspect_reference_all():
    os.makedirs("scratch/screenshots/products", exist_ok=True)
    os.makedirs("scratch/screenshots/purchases", exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={'width': 1600, 'height': 1000}, storage_state="scratch/auth_state.json")
        page = await context.new_page()

        await page.goto("https://weapharma.bricks-rep.com/home", wait_until="domcontentloaded")
        await asyncio.sleep(4)

        # 1. Expand Products (المنتجات)
        # Find all navigation items in sidebar
        nav_elements = await page.query_selector_all('.navigation-item, mat-mdc-list-item, a')
        for el in nav_elements:
            txt = await el.inner_text()
            if "المنتجات" in txt:
                print("Found products menu item, clicking...")
                await el.click()
                await asyncio.sleep(2)
                break

        # 2. Expand Purchases (المشتريات)
        nav_elements = await page.query_selector_all('.navigation-item, mat-mdc-list-item, a')
        for el in nav_elements:
            txt = await el.inner_text()
            if "المشتريات" in txt:
                print("Found purchases menu item, clicking...")
                await el.click()
                await asyncio.sleep(2)
                break

        await page.screenshot(path="scratch/screenshots/sidebar_expanded.png")

        # Extract all visible sidebar links and sub-items
        sub_items = await page.evaluate('''() => {
            const results = [];
            document.querySelectorAll('a, mat-mdc-list-item').forEach(el => {
                const text = el.innerText ? el.innerText.trim().replace(/\\s+/g, ' ') : '';
                const href = el.getAttribute('href') || (el.querySelector('a') ? el.querySelector('a').getAttribute('href') : '');
                if (text && (href || el.tagName === 'A')) {
                    results.push({ text, href, classes: el.className });
                }
            });
            return results;
        }''')

        with open("scratch/all_nav_items.json", "w", encoding="utf-8") as f:
            json.dump(sub_items, f, ensure_ascii=False, indent=2)

        print(f"Captured {len(sub_items)} items to scratch/all_nav_items.json")
        await browser.close()

if __name__ == '__main__':
    asyncio.run(inspect_reference_all())
