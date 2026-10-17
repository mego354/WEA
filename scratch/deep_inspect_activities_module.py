import asyncio
import json
import os
import sys
from playwright.async_api import async_playwright

if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

os.makedirs("scratch/activities_inspection", exist_ok=True)

async def inspect():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            storage_state="scratch/auth_state.json" if os.path.exists("scratch/auth_state.json") else None,
            viewport={'width': 1600, 'height': 1000}
        )
        page = await context.new_page()

        captured_apis = []

        async def handle_response(response):
            url = response.url
            if "/api/" in url and response.request.method in ["GET", "POST"]:
                try:
                    ct = response.headers.get("content-type", "")
                    if "json" in ct:
                        data = await response.json()
                        captured_apis.append({
                            "url": url,
                            "method": response.request.method,
                            "status": response.status,
                            "post_data": response.request.post_data,
                            "response": data
                        })
                except Exception:
                    pass

        page.on("response", handle_response)

        # Initial check login
        print("Checking session at https://weapharma.bricks-rep.com/home ...")
        await page.goto("https://weapharma.bricks-rep.com/home", wait_until="domcontentloaded")
        await asyncio.sleep(4)

        if "login" in page.url or "signin" in page.url or "auth" in page.url:
            print("Session expired, logging in...")
            await page.fill('input[type="email"], input[name="email"], input[formcontrolname="email"]', "wea.pharm2020@gmail.com")
            await page.fill('input[type="password"], input[name="password"], input[formcontrolname="password"]', "Wea@0000")
            btn = await page.query_selector('button[type="submit"]')
            if btn: await btn.click()
            await asyncio.sleep(4)
            await context.storage_state(path="scratch/auth_state.json")
            print("Logged in successfully.")

        modules = [
            ("visits", "https://weapharma.bricks-rep.com/visits"),
            ("planned_visits", "https://weapharma.bricks-rep.com/planned-visits"),
            ("agreements", "https://weapharma.bricks-rep.com/agreements"),
            ("calls", "https://weapharma.bricks-rep.com/calls")
        ]

        inspection_report = {}

        for mod_name, mod_url in modules:
            print(f"\n==========================================")
            print(f"Inspecting {mod_name}: {mod_url}")
            print(f"==========================================")
            await page.goto(mod_url, wait_until="domcontentloaded")
            await asyncio.sleep(5)

            # Capture screenshot
            screenshot_path = f"scratch/activities_inspection/{mod_name}_list.png"
            await page.screenshot(path=screenshot_path)
            print(f"Captured {screenshot_path}")

            # Extract basic page details
            page_info = await page.evaluate('''() => {
                const title = document.querySelector('h1, h2, .page-title, .title')?.innerText || document.title;
                const breadcrumbs = Array.from(document.querySelectorAll('.breadcrumb, .breadcrumbs, [aria-label="breadcrumb"] *')).map(e => e.innerText.trim()).filter(Boolean);
                
                // Extract table headers
                const ths = Array.from(document.querySelectorAll('th, .table-header, .mat-header-cell')).map(th => th.innerText.trim()).filter(Boolean);
                
                // Extract tabs or filter pills
                const tabs = Array.from(document.querySelectorAll('.mat-tab-label, .tab, .filter-chip, [role="tab"], .mat-button-toggle')).map(t => t.innerText.trim()).filter(Boolean);

                // Extract action buttons
                const buttons = Array.from(document.querySelectorAll('button, a.btn, a.button')).map(b => ({
                    text: b.innerText.trim().replace(/\\s+/g, ' '),
                    ariaLabel: b.getAttribute('aria-label') || '',
                    title: b.getAttribute('title') || '',
                    classes: b.className
                })).filter(b => b.text || b.ariaLabel || b.title);

                // Extract first 5 row samples
                const rows = Array.from(document.querySelectorAll('tbody tr, .mat-row')).slice(0, 5).map(row => {
                    return Array.from(row.querySelectorAll('td, .mat-cell')).map(c => c.innerText.trim());
                });

                // Extract filter fields / inputs
                const inputs = Array.from(document.querySelectorAll('input, select, mat-select')).map(i => ({
                    name: i.getAttribute('name') || i.getAttribute('formcontrolname') || '',
                    placeholder: i.getAttribute('placeholder') || '',
                    type: i.getAttribute('type') || i.tagName
                })).filter(i => i.name || i.placeholder);

                return {
                    url: window.location.href,
                    title,
                    breadcrumbs,
                    tableHeaders: ths,
                    tabs,
                    buttons: buttons.slice(0, 25),
                    rowsSample: rows,
                    filters: inputs.slice(0, 20)
                };
            }''')

            inspection_report[mod_name] = page_info
            print(f"Page Title: {page_info['title']}")
            print(f"Table Headers: {page_info['tableHeaders']}")
            print(f"Tabs: {page_info['tabs']}")
            print(f"Rows count: {len(page_info['rowsSample'])}")

            # Check if there is a create button or create link
            create_btn = await page.query_selector('button:has-text("اضف"), button:has-text("انشئ"), button:has-text("إنشاء"), a:has-text("اضف"), a:has-text("انشئ"), button[aria-label*="add"], button:has(.material-symbols-outlined:has-text("add")), button:has(mat-icon:has-text("add"))')
            if create_btn:
                btn_txt = (await create_btn.inner_text()).strip()
                print(f"Found Create Button in {mod_name}: '{btn_txt}'")
                try:
                    await create_btn.click()
                    await asyncio.sleep(3)
                    await page.screenshot(path=f"scratch/activities_inspection/{mod_name}_create_form.png")
                    print(f"Captured create form screenshot: scratch/activities_inspection/{mod_name}_create_form.png")

                    # Extract form fields (WITHOUT SUBMITTING!)
                    form_details = await page.evaluate('''() => {
                        const modalTitle = document.querySelector('.mat-dialog-title, .modal-title, h2, h3')?.innerText || '';
                        const formFields = Array.from(document.querySelectorAll('mat-form-field, .form-group, .field, mat-select, input, textarea')).map(f => {
                            const label = f.querySelector('label, mat-label')?.innerText || '';
                            const input = f.querySelector('input, select, textarea, mat-select') || f;
                            return {
                                label: label.trim(),
                                name: input.getAttribute('name') || input.getAttribute('formcontrolname') || '',
                                placeholder: input.getAttribute('placeholder') || '',
                                type: input.getAttribute('type') || input.tagName,
                                required: f.innerText.includes('*') || input.hasAttribute('required')
                            };
                        }).filter(f => f.label || f.name);

                        return {
                            modalTitle,
                            formFields
                        };
                    }''')
                    inspection_report[f"{mod_name}_create_form"] = form_details

                    # Press Escape or click cancel to close modal without submitting
                    close_btn = await page.query_selector('button:has-text("إلغاء"), button:has-text("الغاء"), button:has-text("cancel"), button[aria-label="close"], button:has(mat-icon:has-text("close")), .close-button')
                    if close_btn:
                        await close_btn.click()
                    else:
                        await page.keyboard.press("Escape")
                    await asyncio.sleep(2)
                except Exception as ex:
                    print(f"Error opening create form for {mod_name}: {ex}")

            # Check if there is an existing record to click and inspect detail view
            first_row_link = await page.query_selector('tbody tr:first-child a, tbody tr:first-child, .mat-row:first-child')
            if first_row_link:
                try:
                    # Let's inspect detail URL or click
                    # Look for action button or link
                    detail_link = await page.query_selector('tbody tr:first-child a[href*="/"], tbody tr:first-child td:nth-child(2)')
                    if detail_link:
                        # Check href
                        href = await detail_link.get_attribute("href")
                        print(f"First row in {mod_name} href: {href}")
                        if href and not href.startswith("javascript"):
                            await page.goto(f"https://weapharma.bricks-rep.com{href}" if href.startswith("/") else href, wait_until="domcontentloaded")
                            await asyncio.sleep(4)
                            await page.screenshot(path=f"scratch/activities_inspection/{mod_name}_detail.png")
                            print(f"Captured {mod_name}_detail.png at {page.url}")

                            # Extract detail page structure
                            detail_data = await page.evaluate('''() => {
                                const title = document.querySelector('h1, h2, .title, .dossier-title')?.innerText || '';
                                const tabs = Array.from(document.querySelectorAll('.mat-tab-label, [role="tab"], .tab')).map(t => t.innerText.trim()).filter(Boolean);
                                const cards = Array.from(document.querySelectorAll('.card, mat-card, .section, .block')).map(c => {
                                    const header = c.querySelector('.card-header, mat-card-header, h3, h4')?.innerText || '';
                                    return {
                                        header: header.trim(),
                                        text: c.innerText.slice(0, 300)
                                    };
                                }).filter(c => c.header || c.text);
                                return {
                                    url: window.location.href,
                                    title,
                                    tabs,
                                    cards
                                };
                            }''')
                            inspection_report[f"{mod_name}_detail"] = detail_data
                except Exception as ex:
                    print(f"Error inspecting detail for {mod_name}: {ex}")

        # Save all captured API responses
        with open("scratch/activities_inspection/captured_apis.json", "w", encoding="utf-8") as f:
            json.dump(captured_apis, f, ensure_ascii=False, indent=2)

        with open("scratch/activities_inspection/modules_summary.json", "w", encoding="utf-8") as f:
            json.dump(inspection_report, f, ensure_ascii=False, indent=2)

        print("\nCompleted deep inspection. Summary written to scratch/activities_inspection/modules_summary.json")
        await browser.close()

if __name__ == '__main__':
    asyncio.run(inspect())
