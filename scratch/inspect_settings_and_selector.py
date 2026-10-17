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

        await page.goto("https://weapharma.bricks-rep.com/home", wait_until="networkidle")

        # 1. Get localStorage to find token and user info
        storage = await page.evaluate('''() => {
            const items = {};
            for (let i = 0; i < localStorage.length; i++) {
                const k = localStorage.key(i);
                items[k] = localStorage.getItem(k);
            }
            return items;
        }''')
        print("LocalStorage keys:", list(storage.keys()))

        # If token found, let's fetch backend APIs directly with headers
        token = None
        for k, v in storage.items():
            if 'token' in k.lower() or 'auth' in k.lower() or 'jwt' in k.lower():
                try:
                    val = json.loads(v)
                    token = val.get('token') or val.get('accessToken') or val.get('jwt') or val
                except:
                    token = v
                print(f"Candidate token key: {k}")

        # 2. Navigate directly to /settings/location
        print("=== NAVIGATING TO /settings/location ===")
        await page.goto("https://weapharma.bricks-rep.com/settings/location", wait_until="networkidle")
        await asyncio.sleep(2)
        loc_page_data = await page.evaluate('''() => {
            return {
                title: document.title,
                url: window.location.href,
                bodyText: document.body.innerText,
                inputs: Array.from(document.querySelectorAll('input, mat-slide-toggle, mat-select, mat-checkbox')).map(el => ({
                    tag: el.tagName,
                    type: el.type,
                    id: el.id,
                    name: el.name,
                    value: el.value,
                    checked: el.checked || el.getAttribute('aria-checked'),
                    labelText: el.closest('mat-slide-toggle, mat-checkbox, mat-form-field')?.innerText?.trim()
                }))
            };
        }''')
        print("Settings Location Page Data:", json.dumps(loc_page_data, ensure_ascii=False, indent=2))

        # 3. Navigate to /settings/users
        print("=== NAVIGATING TO /settings/users ===")
        await page.goto("https://weapharma.bricks-rep.com/settings/users", wait_until="networkidle")
        await asyncio.sleep(2)
        users_page_data = await page.evaluate('''() => {
            return {
                title: document.title,
                url: window.location.href,
                bodyText: document.body.innerText.slice(0, 1500),
                headers: Array.from(document.querySelectorAll('th, .mat-mdc-header-cell')).map(h => h.innerText.trim())
            };
        }''')
        print("Settings Users Page Data:", json.dumps(users_page_data, ensure_ascii=False, indent=2))

        # Click on a user row in /settings/users to see user edit dialog or page
        user_row = await page.query_selector('tr.mat-mdc-row, .mat-mdc-table tbody tr')
        if user_row:
            await user_row.click()
            await asyncio.sleep(2)
            user_dialog_or_page = await page.evaluate('''() => {
                const dialog = document.querySelector('mat-dialog-container, .cdk-overlay-pane:not(:empty)');
                if (dialog) {
                    return {
                        isDialog: true,
                        text: dialog.innerText,
                        toggles: Array.from(dialog.querySelectorAll('mat-slide-toggle, mat-checkbox, input')).map(el => ({
                            text: el.closest('mat-slide-toggle, mat-checkbox, mat-form-field')?.innerText?.trim(),
                            checked: el.checked || el.getAttribute('aria-checked')
                        }))
                    };
                }
                return {
                    isDialog: false,
                    url: window.location.href,
                    text: document.body.innerText.slice(0, 2000)
                };
            }''')
            print("User Edit Inspection:", json.dumps(user_dialog_or_page, ensure_ascii=False, indent=2))

        # 4. Navigate to /settings/visits
        print("=== NAVIGATING TO /settings/visits ===")
        await page.goto("https://weapharma.bricks-rep.com/settings/visits", wait_until="networkidle")
        await asyncio.sleep(2)
        visits_settings_data = await page.evaluate('''() => {
            return {
                title: document.title,
                bodyText: document.body.innerText,
                inputs: Array.from(document.querySelectorAll('input, mat-slide-toggle, mat-checkbox, mat-select')).map(el => ({
                    text: el.closest('mat-slide-toggle, mat-checkbox, mat-form-field')?.innerText?.trim(),
                    checked: el.checked || el.getAttribute('aria-checked'),
                    value: el.value
                }))
            };
        }''')
        print("Settings Visits Page Data:", json.dumps(visits_settings_data, ensure_ascii=False, indent=2))

        # 5. Check how customer selector works in Quick Add "تسجيل زيارة خارج الخطة"
        print("=== CHECKING CUSTOMER SELECTOR IN QUICK ADD ===")
        await page.goto("https://weapharma.bricks-rep.com/home", wait_until="networkidle")
        fab = await page.wait_for_selector('button.mdc-fab, button.mat-mdc-fab')
        await fab.click()
        await asyncio.sleep(1)

        btn_visit = await page.query_selector('app-quick-add button:has-text("تسجيل زيارة خارج الخطة")')
        if btn_visit:
            await btn_visit.click()
            await asyncio.sleep(2)

            # Click on mat-select or search field in dialog
            select_box = await page.query_selector('mat-dialog-container mat-select, mat-dialog-container .mat-mdc-select-trigger')
            if select_box:
                await select_box.click()
                await asyncio.sleep(1.5)

                options_info = await page.evaluate('''() => {
                    const options = Array.from(document.querySelectorAll('mat-option, .mat-mdc-option, [role="option"]')).map(opt => opt.innerText.replace(/\\n+/g, ' ').trim());
                    const panel = document.querySelector('.mat-mdc-select-panel, .cdk-overlay-pane');
                    return {
                        optionsCount: options.length,
                        optionsPreview: options.slice(0, 15),
                        panelText: panel ? panel.innerText.slice(0, 1000) : ''
                    };
                }''')
                print("Options Info on clicking select:", json.dumps(options_info, ensure_ascii=False, indent=2))

        await browser.close()

if __name__ == '__main__':
    asyncio.run(main())
