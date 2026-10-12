import asyncio
import os
import json
import sys

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from playwright.async_api import async_playwright

async def inspect_po():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={'width': 1600, 'height': 1000}, storage_state="scratch/auth_state.json")
        page = await context.new_page()

        print("Navigating to home ...")
        await page.goto("https://weapharma.bricks-rep.com/home", wait_until="domcontentloaded")
        await asyncio.sleep(3)

        # Click purchases
        print("Clicking purchases ...")
        purchases = await page.query_selector('a:has-text("المشتريات")')
        if purchases:
            await purchases.click()
            await asyncio.sleep(2)

        # Click orders
        print("Clicking orders ...")
        orders_link = await page.query_selector('a[href="/purchase-orders"]')
        if orders_link:
            await orders_link.click()
            await asyncio.sleep(5)
        else:
            await page.goto("https://weapharma.bricks-rep.com/purchase-orders", wait_until="domcontentloaded")
            await asyncio.sleep(5)

        print("Current URL:", page.url)
        await page.screenshot(path="scratch/screenshots/purchases/purchase_orders_clicked.png")

        content = await page.evaluate('''() => {
            return {
                title: document.title,
                h1: Array.from(document.querySelectorAll('h1, h2, .title, .page-title')).map(h => h.innerText.trim()),
                buttons: Array.from(document.querySelectorAll('button, a.btn, a.mat-mdc-button, a.mat-mdc-raised-button')).map(b => b.innerText.trim()),
                headers: Array.from(document.querySelectorAll('th, mat-header-cell, [role="columnheader"]')).map(th => th.innerText.trim()),
                rowsCount: document.querySelectorAll('tbody tr, mat-row').length,
                firstRowText: document.querySelector('tbody tr, mat-row')?.innerText?.trim()
            };
        }''')
        with open("scratch/po_inspection.json", "w", encoding="utf-8") as f:
            json.dump(content, f, ensure_ascii=False, indent=2)
        print("Saved scratch/po_inspection.json successfully!")
        await browser.close()

if __name__ == '__main__':
    asyncio.run(inspect_po())
