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

async def inspect_products_deep():
    os.makedirs("scratch/screenshots/products", exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={'width': 1600, 'height': 1000}, storage_state="scratch/auth_state.json")
        page = await context.new_page()

        # 1. Go to Products
        print("Navigating to /products ...")
        await page.goto("https://weapharma.bricks-rep.com/products", wait_until="domcontentloaded")
        await asyncio.sleep(4)
        await page.screenshot(path="scratch/screenshots/products/01_products_list_full.png")

        # Extract rows data
        products_data = await page.evaluate('''() => {
            const rows = Array.from(document.querySelectorAll('tbody tr, mat-row'));
            const data = rows.map(r => {
                const cells = Array.from(r.querySelectorAll('td, mat-cell')).map(c => c.innerText.trim().replace(/\\s+/g, ' '));
                return cells;
            });
            return {
                rowCount: rows.length,
                rows: data.slice(0, 10),
                paginationText: document.querySelector('.mat-mdc-paginator-range-label, .paginator, .pagination')?.innerText?.trim()
            };
        }''')
        print(f"Products count: {products_data['rowCount']}, pagination: {products_data.get('paginationText')}")

        # 2. Click Filter button to open filter drawer
        print("Opening filter drawer on products...")
        filter_btn = await page.query_selector('button:has-text("filter_list"), button:has-text("فلتر")')
        if filter_btn:
            await filter_btn.click()
            await asyncio.sleep(2)
            await page.screenshot(path="scratch/screenshots/products/02_products_filter_drawer.png")
            filter_info = await page.evaluate('''() => {
                const drawer = document.querySelector('mat-drawer, mat-sidenav, .filter-drawer, .filters-container, [role="region"]');
                if (!drawer) return { text: document.body.innerText.substring(0, 500) };
                const labels = Array.from(drawer.querySelectorAll('label, mat-label, .mat-mdc-form-field-label')).map(l => l.innerText.trim());
                const inputs = Array.from(drawer.querySelectorAll('input, mat-select, select')).map(i => ({
                    tag: i.tagName,
                    placeholder: i.getAttribute('placeholder') || '',
                    name: i.getAttribute('name') || '',
                    ariaLabel: i.getAttribute('aria-label') || ''
                }));
                return { labels, inputs };
            }''')
            print("Filter Drawer info:", filter_info)
            # Close drawer by clicking backdrop or filter_btn
            backdrop = await page.query_selector('.mat-drawer-backdrop, .cdk-overlay-backdrop')
            if backdrop: await backdrop.click()
            await asyncio.sleep(1)

        # 3. Click "انشئ منتج" to inspect Create Product form / modal
        print("Clicking انشئ منتج ...")
        create_btn = await page.query_selector('button:has-text("انشئ منتج"), a:has-text("انشئ منتج")')
        if create_btn:
            await create_btn.click()
            await asyncio.sleep(3)
            print("Create product URL:", page.url)
            await page.screenshot(path="scratch/screenshots/products/03_create_product_form.png")

            form_info = await page.evaluate('''() => {
                const form = document.querySelector('form, mat-dialog-container, .create-form, .main-content');
                const fields = Array.from(document.querySelectorAll('mat-form-field, .form-group, .form-field')).map(f => {
                    const label = f.querySelector('label, mat-label')?.innerText?.trim();
                    const input = f.querySelector('input, textarea, mat-select, select');
                    return {
                        label,
                        type: input?.tagName,
                        placeholder: input?.getAttribute('placeholder') || '',
                        required: input?.hasAttribute('required') || false
                    };
                });
                const buttons = Array.from(document.querySelectorAll('button')).map(b => b.innerText.trim()).filter(Boolean);
                return { fields, buttons, bodyText: document.body.innerText.substring(0, 1500) };
            }''')
            with open("scratch/create_product_form.json", "w", encoding="utf-8") as f:
                json.dump(form_info, f, ensure_ascii=False, indent=2)

        # 4. If we were redirected or modal, let's navigate back to /products and click first product
        await page.goto("https://weapharma.bricks-rep.com/products", wait_until="domcontentloaded")
        await asyncio.sleep(3)

        first_product_link = await page.query_selector('tbody tr:first-child a, mat-row:first-child a, tbody tr:first-child td:first-child')
        if first_product_link:
            print("Clicking first product to view details...")
            await first_product_link.click()
            await asyncio.sleep(4)
            print("Product detail URL:", page.url)
            await page.screenshot(path="scratch/screenshots/products/04_product_detail.png")
            detail_info = await page.evaluate('''() => {
                const tabs = Array.from(document.querySelectorAll('[role="tab"], .mat-mdc-tab, .nav-tabs a')).map(t => t.innerText.trim());
                const sections = Array.from(document.querySelectorAll('mat-expansion-panel, .card, .section, .accordion')).map(s => {
                    return s.querySelector('mat-panel-title, .card-title, h3, h4')?.innerText?.trim();
                });
                return {
                    url: window.location.href,
                    title: document.querySelector('h1, h2, .title')?.innerText?.trim(),
                    tabs,
                    sections: sections.filter(Boolean),
                    bodyText: document.body.innerText.substring(0, 2000)
                };
            }''')
            with open("scratch/product_detail.json", "w", encoding="utf-8") as f:
                json.dump(detail_info, f, ensure_ascii=False, indent=2)

        # 5. Inspect /product-categories
        print("Navigating to /product-categories ...")
        await page.goto("https://weapharma.bricks-rep.com/product-categories", wait_until="domcontentloaded")
        await asyncio.sleep(3)
        await page.screenshot(path="scratch/screenshots/products/05_product_categories.png")

        # Click إنشاء تصنيف
        create_cat_btn = await page.query_selector('button:has-text("إنشاء تصنيف")')
        if create_cat_btn:
            await create_cat_btn.click()
            await asyncio.sleep(2)
            await page.screenshot(path="scratch/screenshots/products/06_create_category_modal.png")
            cat_form = await page.evaluate('''() => {
                return {
                    dialogText: document.querySelector('mat-dialog-container, .dialog, .modal')?.innerText?.trim(),
                    fields: Array.from(document.querySelectorAll('mat-dialog-container mat-form-field')).map(f => ({
                        label: f.querySelector('label, mat-label')?.innerText?.trim(),
                        placeholder: f.querySelector('input, textarea')?.getAttribute('placeholder')
                    }))
                };
            }''')
            with open("scratch/create_category_form.json", "w", encoding="utf-8") as f:
                json.dump(cat_form, f, ensure_ascii=False, indent=2)

        await browser.close()
        print("Completed products deep inspection!")

if __name__ == '__main__':
    asyncio.run(inspect_products_deep())
