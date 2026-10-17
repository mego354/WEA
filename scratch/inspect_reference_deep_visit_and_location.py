import asyncio
import json
import sys
from playwright.async_api import async_playwright

sys.stdout.reconfigure(encoding='utf-8')

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            storage_state="scratch/auth_state.json",
            viewport={'width': 1440, 'height': 900}
        )
        page = await context.new_page()

        # Listen to API requests to see all network calls
        api_calls = []
        def on_response(response):
            if 'api' in response.url or 'bricks' in response.url:
                if any(x in response.url for x in ['customer', 'contact', 'visit', 'place', 'location', 'user', 'setting', 'config']):
                    api_calls.append({
                        'url': response.url,
                        'status': response.status,
                        'method': response.request.method
                    })
        page.on('response', on_response)

        print("--- Navigating to /home ---")
        await page.goto("https://weapharma.bricks-rep.com/home", wait_until="networkidle")

        # 1. Inspect Quick Add "تسجيل زيارة خارج الخطة"
        print("--- Inspecting Quick Add / Visit Create Customer Selection ---")
        fab = await page.wait_for_selector('button.mdc-fab, button.mat-mdc-fab')
        await fab.click()
        await asyncio.sleep(1)

        btn_visit = await page.query_selector('app-quick-add button:has-text("تسجيل زيارة خارج الخطة")')
        if btn_visit:
            await btn_visit.click()
            await asyncio.sleep(2)

            # Check the dialog content and form elements
            dialog_dom = await page.evaluate('''() => {
                const dialog = document.querySelector('mat-dialog-container, .cdk-overlay-pane:not(:empty)');
                if (!dialog) return { found: false };
                
                const inputs = Array.from(dialog.querySelectorAll('input, select, mat-select, button')).map(el => ({
                    tag: el.tagName,
                    type: el.type,
                    placeholder: el.placeholder || el.getAttribute('placeholder'),
                    text: el.innerText.trim(),
                    classes: el.className
                }));

                const customerItems = Array.from(dialog.querySelectorAll('.customer-item, mat-list-item, .mat-mdc-list-item, [role="listitem"], tr, .list-item')).map(el => ({
                    text: el.innerText.trim(),
                    classes: el.className
                }));

                return {
                    found: true,
                    title: dialog.querySelector('.page-title, h1, h2, h3')?.innerText,
                    inputs: inputs,
                    customerItems: customerItems.slice(0, 10),
                    fullText: dialog.innerText,
                    htmlSnippet: dialog.innerHTML.slice(0, 3000)
                };
            }''')
            print("Dialog Inspection:", json.dumps(dialog_dom, ensure_ascii=False, indent=2))

            # Try typing in search input if found
            search_input = await page.query_selector('mat-dialog-container input[type="text"], mat-dialog-container input[placeholder*="بحث"]')
            if search_input:
                print("Typing search query in customer selection...")
                await search_input.fill("صيدلية")
                await asyncio.sleep(2)
                search_results = await page.evaluate('''() => {
                    const dialog = document.querySelector('mat-dialog-container');
                    const items = Array.from(dialog.querySelectorAll('mat-list-item, .mat-mdc-list-item, .customer-row, tr, [role="option"], .ng-star-inserted')).filter(el => el.innerText.length > 5);
                    return items.slice(0, 10).map(el => el.innerText.replace(/\\n+/g, ' '));
                }''')
                print("Search results after typing 'صيدلية':", json.dumps(search_results, ensure_ascii=False, indent=2))

        # Close dialog if open
        close_btn = await page.query_selector('mat-dialog-container button:has-text("close"), mat-dialog-container [mat-dialog-close], mat-dialog-container button.mdc-icon-button')
        if close_btn:
            await close_btn.click()
            await asyncio.sleep(1)

        # 2. Inspect Visits page (/visits)
        print("--- Navigating to /visits ---")
        await page.goto("https://weapharma.bricks-rep.com/visits", wait_until="networkidle")
        await asyncio.sleep(2)

        # Look for create visit button on /visits
        visits_page_info = await page.evaluate('''() => {
            const buttons = Array.from(document.querySelectorAll('button, a')).map(b => ({
                text: b.innerText.trim(),
                href: b.href || b.getAttribute('href'),
                classes: b.className
            })).filter(b => b.text.includes('زيارة') || b.text.includes('إضافة') || b.text.includes('تسجيل') || b.text.includes('create') || b.text.includes('new'));
            
            // Check table headers for location/coordinates
            const headers = Array.from(document.querySelectorAll('th, .mat-mdc-header-cell')).map(h => h.innerText.trim());

            return {
                createButtons: buttons,
                headers: headers
            };
        }''')
        print("Visits Page Info:", json.dumps(visits_page_info, ensure_ascii=False, indent=2))

        # Click the first visit row to see visit details and location info
        first_visit_row = await page.query_selector('tr.mat-mdc-row, .mat-mdc-table tbody tr')
        if first_visit_row:
            await first_visit_row.click()
            await asyncio.sleep(2)
            print("Current URL after clicking visit row:", page.url)
            visit_detail_dom = await page.evaluate('''() => {
                return {
                    url: window.location.href,
                    text: document.body.innerText.slice(0, 2000),
                    hasMap: !!document.querySelector('google-map, .map, [id*="map"], iframe[src*="google"], .leaflet-container'),
                    locationKeywords: Array.from(document.querySelectorAll('*')).filter(el => {
                        const t = el.innerText || '';
                        return (t.includes('موقع') || t.includes('GPS') || t.includes('إحداثيات') || t.includes('مكان') || t.includes('تحقق') || t.includes('خريطة')) && el.children.length === 0;
                    }).map(el => el.innerText.trim()).slice(0, 15)
                };
            }''')
            print("Visit Detail Info:", json.dumps(visit_detail_dom, ensure_ascii=False, indent=2))

        # 3. Inspect Navigation links (sidebar / menu) to find Places, Contacts, Users
        print("--- Checking All Sidebar / Navigation Links ---")
        nav_items = await page.evaluate('''() => {
            return Array.from(document.querySelectorAll('a, mat-list-item, .nav-item, [routerlink]')).map(el => ({
                text: el.innerText.trim().replace(/\\n+/g, ' '),
                href: el.href || el.getAttribute('href') || el.getAttribute('routerlink')
            })).filter(x => x.text.length > 0 && x.text.length < 50);
        }''')
        print("Nav items:", json.dumps(nav_items, ensure_ascii=False, indent=2))

        # Check API calls collected
        print("--- API Calls Recorded ---")
        print(json.dumps(api_calls[:30], indent=2))

        await browser.close()

if __name__ == '__main__':
    asyncio.run(main())
