import asyncio
import sys
import os
import datetime
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from playwright.async_api import async_playwright

import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()
from activities.models import PlannedVisitDay, PlannedVisitItem

from asgiref.sync import sync_to_async

async def main():
    test_target_date = datetime.date.today() + datetime.timedelta(days=3)
    test_target_str = test_target_date.strftime('%Y-%m-%d')
    print(f"Target test date: {test_target_str}")

    # Clean up any pre-existing plan for this test date so the test is idempotent
    await sync_to_async(lambda: PlannedVisitDay.objects.filter(date=test_target_date).delete())()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={'width': 1280, 'height': 900})
        page = await context.new_page()

        console_errors = []
        page.on('console', lambda msg: console_errors.append(f"[{msg.type}] {msg.text}") if msg.type in ('error', 'warning') and 'tailwindcss' not in msg.text else None)
        page.on('pageerror', lambda err: console_errors.append(f"[PAGE_ERROR] {str(err)}"))
        page.on('dialog', lambda dialog: print(f"DIALOG: {dialog.type} - {dialog.message}") or dialog.accept())
        page.on('response', lambda resp: print(f"RESPONSE: {resp.url} -> {resp.status}") if 'bulk-add' in resp.url else None)

        print("1. Logging in...")
        await page.goto('http://127.0.0.1:8002/login/', wait_until='domcontentloaded')
        await page.fill('input[name="email"]', 'superadmin_test')
        await page.fill('input[name="password"]', 'Wea@1234')
        await page.click('button[type="submit"]')
        await page.wait_for_timeout(2000)

        print("2. Navigating to /planned-visits/...")
        await page.goto('http://127.0.0.1:8002/planned-visits/', wait_until='domcontentloaded')
        await page.wait_for_timeout(1000)

        # Test Select All
        print("Testing 'تحديد المعروض'...")
        btn_select_all = page.locator('button:has-text("تحديد المعروض")')
        await btn_select_all.click()
        await page.wait_for_timeout(1000)

        sel_count = await page.locator('#drawer-selected-count').inner_text()
        print(f"Count after Select All: {sel_count}")
        assert int(sel_count) > 0, "Select all failed to increment count"

        # Test Deselect All
        print("Testing 'إلغاء التحديد'...")
        btn_deselect_all = page.locator('button:has-text("إلغاء التحديد")')
        await btn_deselect_all.click()
        await page.wait_for_timeout(500)

        sel_count_zero = await page.locator('#drawer-selected-count').inner_text()
        print(f"Count after Deselect All: {sel_count_zero}")
        assert int(sel_count_zero) == 0, "Deselect all failed to reset count"

        # Set plan date to target test date
        print(f"Setting plan date to {test_target_str}...")
        date_input = page.locator('#drawer-bulk-date')
        await date_input.fill(test_target_str)
        await date_input.dispatch_event('change')
        await page.wait_for_timeout(500)

        # Select 1 client and create plan
        print("Selecting client 0...")
        checkboxes = page.locator('.drawer-client-checkbox')
        await checkboxes.nth(0).click()
        await page.wait_for_timeout(1000)

        type_selects = page.locator('.bulk-type-template-select')
        assert await type_selects.count() > 0, "No template dropdown appeared"

        # Choose template
        sel = type_selects.nth(0)
        opt_values = await sel.locator('option').evaluate_all('opts => opts.map(o => o.value)')
        for val in opt_values:
            if val:
                await sel.select_option(val)
                break

        await page.wait_for_timeout(500)
        submit_btn = page.locator('#drawer-bulk-submit-btn')
        is_disabled = await submit_btn.is_disabled()
        print(f"Submit button disabled state: {is_disabled}")
        assert not is_disabled, "Submit button should be enabled"

        # Submit plan
        print("Submitting bulk plan...")
        await submit_btn.click()
        await page.wait_for_timeout(4000)

        print("URL after submit:", page.url)
        assert f'#day-{test_target_str}' in page.url or '#day-' in page.url, f"Expected day anchor in URL, got {page.url}"

        # Verify that planned item was actually created in database
        persisted_count = await sync_to_async(lambda: PlannedVisitItem.objects.filter(plan_day__date=test_target_date).count())()
        print(f"Database verification: {persisted_count} planned items created for {test_target_str}")
        assert persisted_count > 0, f"Expected at least 1 persisted item in DB, found {persisted_count}"

        print("Errors recorded during test:", console_errors)
        assert len(console_errors) == 0, f"Found console errors: {console_errors}"
        print("ALL BROWSER TESTS PASSED PERFECTLY!")

        await browser.close()

if __name__ == '__main__':
    asyncio.run(main())

if __name__ == '__main__':
    asyncio.run(main())
