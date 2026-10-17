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

        # 1. Inspect templates in visit registration dialog
        print("=== Inspecting Templates in Customer Selection Dialog ===")
        await page.goto("https://weapharma.bricks-rep.com/home", wait_until="networkidle")
        fab = await page.wait_for_selector('button.mdc-fab, button.mat-mdc-fab')
        await fab.click()
        await asyncio.sleep(1)

        btn_visit = await page.query_selector('app-quick-add button:has-text("تسجيل زيارة خارج الخطة")')
        await btn_visit.click()
        await asyncio.sleep(2)

        # Select customer
        trigger = await page.query_selector('app-visit-create-customer-selection .mat-mdc-select-trigger, app-visit-create-customer-selection mat-select')
        await trigger.click()
        await asyncio.sleep(1)
        options = await page.query_selector_all('mat-option, .mat-mdc-option')
        if len(options) > 1:
            await options[1].click()
            await asyncio.sleep(1.5)

            # Click template select
            template_select = await page.query_selector('//mat-select[contains(., "اختر قالب الزيارة")] | //mat-form-field[contains(., "قالب")]//mat-select')
            if template_select:
                await template_select.click()
                await asyncio.sleep(1)
                template_options = await page.evaluate('''() => {
                    return Array.from(document.querySelectorAll('.mat-mdc-option, [role="option"]')).map(o => o.innerText.trim());
                }''')
                print("Visit Templates available:", json.dumps(template_options, ensure_ascii=False, indent=2))

        # Close dialog
        close_btn = await page.query_selector('mat-dialog-container button:has-text("close"), mat-dialog-container [mat-dialog-close]')
        if close_btn:
            await close_btn.click()
            await asyncio.sleep(1)

        # 2. Inspect Contact Detail for "تسجيل زيارة" action
        print("=== Checking Contact Detail Visit Actions ===")
        await page.goto("https://weapharma.bricks-rep.com/contacts/d7cbf33a-d152-4d7e-bc40-93eeb5047264", wait_until="networkidle")
        await asyncio.sleep(2)
        contact_actions = await page.evaluate('''() => {
            const btns = Array.from(document.querySelectorAll('button, a')).map(b => ({
                text: b.innerText.trim(),
                classes: b.className,
                icon: b.querySelector('mat-icon')?.innerText?.trim()
            })).filter(b => b.text.includes('زيارة') || b.text.includes('اضف') || b.text.includes('تسجيل') || b.icon === 'add');
            return btns;
        }''')
        print("Contact Action Buttons:", json.dumps(contact_actions, ensure_ascii=False, indent=2))

        # Check 'الأنشطة' tab on contact detail
        activities_tab = await page.query_selector('//div[contains(@class, "mat-mdc-tab")]//span[contains(text(), "الأنشطة")] | //div[role="tab"][contains(., "الأنشطة")]')
        if activities_tab:
            await activities_tab.click()
            await asyncio.sleep(1.5)
            tab_content = await page.evaluate('''() => {
                return {
                    text: document.querySelector('.mat-mdc-tab-body-active, mat-tab-body')?.innerText?.slice(0, 1000)
                };
            }''')
            print("Contact Activities Tab:", json.dumps(tab_content, ensure_ascii=False, indent=2))

        # 3. Inspect /settings/users and user permissions/roles for Location Verification
        print("=== Checking Roles / Permissions for Location Settings ===")
        await page.goto("https://weapharma.bricks-rep.com/settings/roles", wait_until="networkidle")
        await asyncio.sleep(2)
        roles_data = await page.evaluate('''() => {
            return {
                title: document.title,
                bodyText: document.body.innerText.slice(0, 2000),
                roles: Array.from(document.querySelectorAll('tr, .role-card, mat-list-item')).map(r => r.innerText.trim().replace(/\\n+/g, ' ')).filter(Boolean)
            };
        }''')
        print("Roles page:", json.dumps(roles_data, ensure_ascii=False, indent=2))

        await browser.close()

if __name__ == '__main__':
    asyncio.run(main())
