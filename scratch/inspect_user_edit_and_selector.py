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

        print("=== Inspecting User Edit in /settings/users ===")
        await page.goto("https://weapharma.bricks-rep.com/settings/users", wait_until="networkidle")
        await asyncio.sleep(2)

        # Find edit button or click on the first user row
        edit_btn = await page.query_selector('tr.mat-mdc-row button:has-text("edit"), tr.mat-mdc-row [mattooltip*="تعديل"], tr.mat-mdc-row mat-icon:has-text("edit")')
        if not edit_btn:
            # Click the row itself
            edit_btn = await page.query_selector('tr.mat-mdc-row')
        
        if edit_btn:
            await edit_btn.click()
            await asyncio.sleep(2)

            user_form_info = await page.evaluate('''() => {
                const dialog = document.querySelector('mat-dialog-container, .cdk-overlay-pane:not(:empty)');
                const container = dialog || document.body;
                
                const tabs = Array.from(container.querySelectorAll('.mat-mdc-tab, [role="tab"]')).map(t => t.innerText.trim());
                
                const fields = Array.from(container.querySelectorAll('mat-form-field, mat-slide-toggle, mat-checkbox')).map(el => {
                    const label = el.querySelector('label, mat-label, .mdc-label')?.innerText?.trim() || el.innerText?.trim();
                    const input = el.querySelector('input, mat-select');
                    const checked = el.querySelector('input[type="checkbox"]')?.checked || el.getAttribute('aria-checked');
                    return {
                        label: label,
                        tag: input?.tagName,
                        type: input?.type,
                        checked: checked,
                        value: input?.value
                    };
                });

                return {
                    isDialog: !!dialog,
                    tabs: tabs,
                    fields: fields,
                    allText: container.innerText.slice(0, 3000)
                };
            }''')
            print("User Edit Form Details:", json.dumps(user_form_info, ensure_ascii=False, indent=2))

        # Also let's check customer selector in Quick Add again, inspect why options weren't captured or how it fetches customers
        print("=== Checking Customer Selector API Requests ===")
        customer_apis = []
        def on_req(request):
            if 'customer' in request.url.lower() or 'contact' in request.url.lower():
                customer_apis.append({
                    'url': request.url,
                    'method': request.method,
                    'post_data': request.post_data
                })
        page.on('request', on_req)

        await page.goto("https://weapharma.bricks-rep.com/home", wait_until="networkidle")
        fab = await page.wait_for_selector('button.mdc-fab, button.mat-mdc-fab')
        await fab.click()
        await asyncio.sleep(1)

        btn_visit = await page.query_selector('app-quick-add button:has-text("تسجيل زيارة خارج الخطة")')
        if btn_visit:
            await btn_visit.click()
            await asyncio.sleep(2)

            # Let's inspect the customer selection component in the dialog
            dialog_selector_details = await page.evaluate('''() => {
                const comp = document.querySelector('app-visit-create-customer-selection');
                if (!comp) return { found: false };
                return {
                    found: true,
                    html: comp.outerHTML.slice(0, 2000),
                    inputs: Array.from(comp.querySelectorAll('input, mat-select')).map(i => ({
                        tagName: i.tagName,
                        type: i.type,
                        placeholder: i.placeholder || i.getAttribute('placeholder'),
                        id: i.id,
                        classes: i.className
                    }))
                };
            }''')
            print("Customer Selection Component Details:", json.dumps(dialog_selector_details, ensure_ascii=False, indent=2))

            # Click mat-select trigger directly
            trigger = await page.query_selector('app-visit-create-customer-selection .mat-mdc-select-trigger, app-visit-create-customer-selection mat-select')
            if trigger:
                await trigger.click()
                await asyncio.sleep(2)
                
                # Check what overlay appeared
                overlay = await page.evaluate('''() => {
                    const searchBox = document.querySelector('.mat-mdc-select-panel input, .cdk-overlay-pane input');
                    const options = Array.from(document.querySelectorAll('.mat-mdc-option, [role="option"]')).map(o => o.innerText.replace(/\\n+/g, ' ').trim());
                    return {
                        hasSearchBox: !!searchBox,
                        searchBoxPlaceholder: searchBox ? searchBox.placeholder : null,
                        optionsCount: options.length,
                        firstOptions: options.slice(0, 10),
                        overlayHtml: document.querySelector('.cdk-overlay-pane:last-child')?.innerHTML?.slice(0, 1500)
                    };
                }''')
                print("Overlay on clicking customer select:", json.dumps(overlay, ensure_ascii=False, indent=2))

        print("=== Customer APIs recorded ===")
        print(json.dumps(customer_apis, ensure_ascii=False, indent=2))

        await browser.close()

if __name__ == '__main__':
    asyncio.run(main())
