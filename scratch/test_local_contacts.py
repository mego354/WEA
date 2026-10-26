import asyncio
import os
import sys
from playwright.async_api import async_playwright

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

async def main():
    os.makedirs("scratch/local_screenshots", exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={'width': 1440, 'height': 900})
        page = await context.new_page()

        print("1. Logging into local ERP...")
        await page.goto("http://127.0.0.1:8000/auth/login/", wait_until="domcontentloaded")
        await page.fill('input[name="email"]', "wea.pharm2020@gmail.com")
        await page.fill('input[name="password"]', "Wea@4444")
        await page.click('button[type="submit"]')
        await asyncio.sleep(2)
        print("Logged in, current URL:", page.url)

        # 2. Contacts List
        print("2. Opening /contacts/ ...")
        await page.goto("http://127.0.0.1:8000/contacts/", wait_until="domcontentloaded")
        await asyncio.sleep(1)
        await page.screenshot(path="scratch/local_screenshots/01_local_contacts_list.png", full_page=False)

        # 3. Open Filter Drawer
        print("3. Toggling Filter Drawer...")
        filter_btn = await page.query_selector('button[title*="فلتر"]')
        if filter_btn:
            await filter_btn.click()
            await asyncio.sleep(0.5)
            await page.screenshot(path="scratch/local_screenshots/02_local_filter_drawer.png", full_page=False)
            # Close drawer
            await page.click('#filterDrawer button')
            await asyncio.sleep(0.5)

        # 4. Open Contact Detail
        print("4. Opening first contact detail...")
        first_contact = await page.query_selector('table tbody tr:first-child a')
        if first_contact:
            contact_url = await first_contact.get_attribute('href')
            print("Navigating to:", contact_url)
            await first_contact.click()
            await asyncio.sleep(1)
            await page.screenshot(path="scratch/local_screenshots/03_local_contact_detail_overview.png", full_page=False)

            # Test adding a comment
            print("Testing adding a comment...")
            comment_input = await page.query_selector('textarea[name="comment"]')
            if comment_input:
                await comment_input.fill("ملاحظة تجريبية: تم التواصل مع العميل بنجاح.")
                await page.click('button:has-text("إرسال التعليق")')
                await asyncio.sleep(1)
                await page.screenshot(path="scratch/local_screenshots/03b_local_comment_added.png", full_page=False)

            # Test tabs
            tabs = ['activities', 'sales', 'attachments', 'todos', 'tasks']
            for t in tabs:
                tab_link = await page.query_selector(f'a[href*="tab={t}"]')
                if tab_link:
                    print(f"Opening tab {t}...")
                    await tab_link.click()
                    await asyncio.sleep(1)
                    await page.screenshot(path=f"scratch/local_screenshots/04_local_tab_{t}.png", full_page=False)

            # Test Todo creation in Todos tab
            new_todo_btn = await page.query_selector('button:has-text("اضف Todo جديد")')
            if new_todo_btn:
                await new_todo_btn.click()
                await asyncio.sleep(0.5)
                todo_input = await page.query_selector('input[placeholder*="عنوان المهمة"]')
                if todo_input:
                    await todo_input.fill("متابعة الدفعة المالية القادمة")
                    await page.click('#newTodoBox button[type="submit"]')
                    await asyncio.sleep(1)
                    await page.screenshot(path="scratch/local_screenshots/04b_local_todo_created.png", full_page=False)

            # 5. Open Edit Page
            print("5. Opening Contact Edit page...")
            edit_btn = await page.query_selector('a:has-text("تعديل")')
            if not edit_btn:
                # Open 3-dots
                more_btn = await page.query_selector('button:has(span:has-text("more_vert"))')
                if more_btn:
                    await more_btn.click()
                    await asyncio.sleep(0.5)
                    edit_btn = await page.query_selector('#headerActionsMenu a:has-text("تعديل")')
            if edit_btn:
                await edit_btn.click()
                await asyncio.sleep(1)
                await page.screenshot(path="scratch/local_screenshots/05_local_contact_edit.png", full_page=False)

        # 6. Open Create Page
        print("6. Opening Contact Create page...")
        await page.goto("http://127.0.0.1:8000/contacts/create/", wait_until="domcontentloaded")
        await asyncio.sleep(1)
        await page.screenshot(path="scratch/local_screenshots/06_local_contact_create.png", full_page=False)

        # 7. Test Export
        print("7. Testing contacts export...")
        await page.goto("http://127.0.0.1:8000/contacts/export/", wait_until="domcontentloaded")

        await browser.close()
        print("All local verification completed successfully!")

if __name__ == '__main__':
    asyncio.run(main())
