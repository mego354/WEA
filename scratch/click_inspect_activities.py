import asyncio
import json
import os
import sys
from playwright.async_api import async_playwright

if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

os.makedirs("scratch/activities_inspection", exist_ok=True)

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            storage_state="scratch/auth_state.json",
            viewport={'width': 1600, 'height': 1000}
        )
        page = await context.new_page()

        captured_apis = []

        async def on_response(response):
            url = response.url
            if "/api/" in url:
                try:
                    ct = response.headers.get("content-type", "")
                    if "json" in ct:
                        body = await response.json()
                        captured_apis.append({
                            "url": url,
                            "method": response.request.method,
                            "status": response.status,
                            "post_data": response.request.post_data,
                            "response": body
                        })
                except Exception:
                    pass

        page.on("response", on_response)

        print("Navigating to https://weapharma.bricks-rep.com/home ...")
        await page.goto("https://weapharma.bricks-rep.com/home", wait_until="domcontentloaded")
        await asyncio.sleep(4)

        # Open Activities in sidebar
        items = await page.query_selector_all('a, button, mat-list-item, .navigation-item')
        for item in items:
            txt = (await item.inner_text()).strip()
            if "الأنشطة" in txt:
                print("Clicking Activities in sidebar...")
                await item.click()
                await asyncio.sleep(2)
                break

        submenus = [
            ("visits", "الزيارات"),
            ("planned_visits", "خطة الزيارات"),
            ("agreements", "الاتفاقيات"),
            ("calls", "المكالمات")
        ]

        results = {}

        for key, name in submenus:
            print(f"\nClicking on submenu: {name} ...")
            # Find submenu item
            sub_el = await page.query_selector(f'a:has-text("{name}"), mat-list-item:has-text("{name}"), .navigation-item:has-text("{name}")')
            if not sub_el:
                # Try finding in all links
                all_links = await page.query_selector_all('a, mat-list-item')
                for l in all_links:
                    t = (await l.inner_text()).strip()
                    if name in t:
                        sub_el = l
                        break

            if sub_el:
                await sub_el.click()
                print(f"Clicked {name}. Waiting for content...")
                await asyncio.sleep(6) # Give Angular time to load data
                await page.screenshot(path=f"scratch/activities_inspection/{key}_screen.png")
                print(f"Captured scratch/activities_inspection/{key}_screen.png (URL: {page.url})")

                # Extract detailed structure of this view
                view_info = await page.evaluate('''() => {
                    // Extract headers / title / breadcrumbs
                    const title = document.querySelector('h1, h2, .title, .page-title, .page-header-title')?.innerText || '';
                    
                    // Table headers
                    const ths = Array.from(document.querySelectorAll('th, .mat-header-cell, .table-head, .header-cell')).map(th => th.innerText.trim()).filter(Boolean);
                    
                    // Filter chips / Tabs
                    const filterChips = Array.from(document.querySelectorAll('.filter-chip, .mat-chip, .chip, [role="tab"], .mat-tab-label')).map(c => c.innerText.trim().replace(/\\s+/g, ' ')).filter(Boolean);

                    // Action buttons
                    const actionButtons = Array.from(document.querySelectorAll('button, a.btn, a.button, a.action-btn')).map(b => ({
                        text: b.innerText.trim().replace(/\\s+/g, ' '),
                        aria: b.getAttribute('aria-label') || '',
                        title: b.getAttribute('title') || '',
                        icon: b.querySelector('mat-icon, .material-symbols-outlined, i')?.innerText || ''
                    })).filter(b => b.text || b.aria || b.title || b.icon);

                    // Row sample data (up to 10 rows)
                    const rows = Array.from(document.querySelectorAll('tbody tr, .mat-row')).slice(0, 10).map(r => {
                        return Array.from(r.querySelectorAll('td, .mat-cell')).map(c => c.innerText.trim());
                    });

                    // Modals or cards if any
                    const emptyState = document.querySelector('.empty-state, .no-data, .not-found')?.innerText || '';

                    return {
                        url: window.location.href,
                        title,
                        filterChips,
                        tableHeaders: ths,
                        actionButtons: actionButtons.slice(0, 20),
                        rowCount: document.querySelectorAll('tbody tr, .mat-row').length,
                        sampleRows: rows,
                        emptyState
                    };
                }''')

                results[key] = view_info
                print(f"Info for {key}:", json.dumps(view_info, ensure_ascii=False, indent=2))

                # Check if there is an Add / Create button
                add_btn = await page.query_selector('button:has-text("اضف"), button:has-text("انشئ"), button:has-text("جديد"), button:has-text("إضافة"), button:has(mat-icon:has-text("add")), button[aria-label*="اضف"], button[aria-label*="انشئ"]')
                if add_btn:
                    add_txt = (await add_btn.inner_text()).strip()
                    print(f"Found add button for {key}: '{add_txt}'")
                    try:
                        await add_btn.click()
                        await asyncio.sleep(4)
                        await page.screenshot(path=f"scratch/activities_inspection/{key}_add_modal.png")
                        print(f"Captured scratch/activities_inspection/{key}_add_modal.png")

                        # Extract form inputs in modal/page (WITHOUT SUBMITTING!)
                        form_data = await page.evaluate('''() => {
                            const modalTitle = document.querySelector('.mat-dialog-title, .modal-header, h2, h3, .dialog-title')?.innerText || '';
                            const fields = Array.from(document.querySelectorAll('mat-form-field, .form-group, .field-container')).map(f => {
                                const label = f.querySelector('label, mat-label')?.innerText || '';
                                const input = f.querySelector('input, select, textarea, mat-select');
                                return {
                                    label: label.trim(),
                                    name: input ? (input.getAttribute('name') || input.getAttribute('formcontrolname') || '') : '',
                                    placeholder: input ? (input.getAttribute('placeholder') || '') : '',
                                    type: input ? (input.getAttribute('type') || input.tagName) : '',
                                    options: Array.from(f.querySelectorAll('option, mat-option')).map(o => o.innerText.trim()).filter(Boolean)
                                };
                            }).filter(f => f.label || f.name);

                            return {
                                modalTitle,
                                fieldCount: fields.length,
                                fields
                            };
                        }''')
                        results[f"{key}_form"] = form_data
                        print(f"Form for {key}: {form_data['modalTitle']}, {form_data['fieldCount']} fields")

                        # Close modal safely
                        close_btn = await page.query_selector('button:has-text("إلغاء"), button:has-text("الغاء"), button:has(mat-icon:has-text("close")), .close-btn, [aria-label="Close"]')
                        if close_btn:
                            await close_btn.click()
                        else:
                            await page.keyboard.press("Escape")
                        await asyncio.sleep(2)
                    except Exception as e:
                        print(f"Error checking add modal for {key}: {e}")
            else:
                print(f"Could not find submenu element for {name}!")

        # Save all results and captured APIs
        with open("scratch/activities_inspection/activities_detailed_results.json", "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)

        with open("scratch/activities_inspection/all_captured_apis.json", "w", encoding="utf-8") as f:
            json.dump(captured_apis, f, ensure_ascii=False, indent=2)

        print("\nAll inspection complete! Saved to scratch/activities_inspection/")
        await browser.close()

if __name__ == '__main__':
    asyncio.run(main())
