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

async def inspect_products_and_pos():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={'width': 1600, 'height': 1000}, storage_state="scratch/auth_state.json")
        page = await context.new_page()

        # 1. Inspect Products Cards / Table
        print("Navigating to /products ...")
        await page.goto("https://weapharma.bricks-rep.com/products", wait_until="domcontentloaded")
        await asyncio.sleep(4)

        products_items = await page.evaluate('''() => {
            // Find all cards or rows
            const items = [];
            // Check cards
            document.querySelectorAll('mat-card, .product-card, .card, [role="row"], tr').forEach(el => {
                const text = el.innerText ? el.innerText.trim().replace(/\\s+/g, ' ') : '';
                if (text && text.length > 5) {
                    items.push({ text, tag: el.tagName, class: el.className });
                }
            });
            return items;
        }''')
        with open("scratch/products_items.json", "w", encoding="utf-8") as f:
            json.dump(products_items, f, ensure_ascii=False, indent=2)

        # Click on the first product card or row to open its details
        first_product = await page.query_selector('mat-card, .product-card, tbody tr, mat-row')
        if first_product:
            print("Clicking first product item...")
            await first_product.click()
            await asyncio.sleep(4)
            print("Product detail URL:", page.url)
            await page.screenshot(path="scratch/screenshots/products/product_detail_opened.png")
            detail_info = await page.evaluate('''() => {
                return {
                    url: window.location.href,
                    title: document.querySelector('h1, h2, .title')?.innerText?.trim(),
                    bodyText: document.body.innerText.substring(0, 3000),
                    tabs: Array.from(document.querySelectorAll('[role="tab"], .mat-mdc-tab')).map(t => t.innerText.trim()),
                    buttons: Array.from(document.querySelectorAll('button')).map(b => b.innerText.trim()).filter(Boolean)
                };
            }''')
            with open("scratch/product_detail_info.json", "w", encoding="utf-8") as f:
                json.dump(detail_info, f, ensure_ascii=False, indent=2)

        # 2. Inspect Purchase Orders Creation
        print("Navigating to /purchase-orders ...")
        await page.goto("https://weapharma.bricks-rep.com/purchase-orders", wait_until="domcontentloaded")
        await asyncio.sleep(4)

        # Click "أمر مشتريات جديد"
        po_create_btn = await page.query_selector('button:has-text("أمر مشتريات جديد"), a:has-text("أمر مشتريات جديد")')
        if po_create_btn:
            print("Clicking أمر مشتريات جديد ...")
            await po_create_btn.click()
            await asyncio.sleep(4)
            print("PO create URL:", page.url)
            await page.screenshot(path="scratch/screenshots/purchases/01_create_purchase_order.png")

            po_form_info = await page.evaluate('''() => {
                const labels = Array.from(document.querySelectorAll('mat-form-field, .form-group, .form-field')).map(f => {
                    return {
                        label: f.querySelector('label, mat-label')?.innerText?.trim(),
                        inputTag: f.querySelector('input, mat-select, textarea')?.tagName,
                        placeholder: f.querySelector('input, textarea')?.getAttribute('placeholder')
                    };
                });
                return {
                    url: window.location.href,
                    title: document.querySelector('h1, h2, .title')?.innerText?.trim(),
                    fields: labels,
                    buttons: Array.from(document.querySelectorAll('button')).map(b => b.innerText.trim()).filter(Boolean),
                    bodyText: document.body.innerText.substring(0, 3000)
                };
            }''')
            with open("scratch/create_po_form.json", "w", encoding="utf-8") as f:
                json.dump(po_form_info, f, ensure_ascii=False, indent=2)

        # 3. Check Vendor Payments create form
        print("Navigating to /vendor-payments ...")
        await page.goto("https://weapharma.bricks-rep.com/vendor-payments", wait_until="domcontentloaded")
        await asyncio.sleep(4)

        # Click "مدفوعة جديدة"
        pay_btn = await page.query_selector('button:has-text("مدفوعة جديدة"), a:has-text("مدفوعة جديدة")')
        if pay_btn:
            print("Clicking مدفوعة جديدة ...")
            await pay_btn.click()
            await asyncio.sleep(3)
            print("Payment create URL:", page.url)
            await page.screenshot(path="scratch/screenshots/purchases/02_create_vendor_payment.png")

            pay_form = await page.evaluate('''() => {
                return {
                    url: window.location.href,
                    title: document.querySelector('h1, h2, .title, mat-dialog-title')?.innerText?.trim(),
                    bodyText: document.body.innerText.substring(0, 2000),
                    fields: Array.from(document.querySelectorAll('mat-form-field')).map(f => ({
                        label: f.querySelector('label, mat-label')?.innerText?.trim(),
                        tag: f.querySelector('input, mat-select, textarea')?.tagName
                    }))
                };
            }''')
            with open("scratch/create_vendor_payment.json", "w", encoding="utf-8") as f:
                json.dump(pay_form, f, ensure_ascii=False, indent=2)

        await browser.close()
        print("Completed deep inspection of products and POs!")

if __name__ == '__main__':
    asyncio.run(inspect_products_and_pos())
