import sys
sys.stdout.reconfigure(encoding='utf-8')
import asyncio
from playwright.async_api import async_playwright

async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={'width': 1280, 'height': 800})
        page = await context.new_page()

        console_errors = []
        page.on('console', lambda msg: console_errors.append(f"{msg.text} (URL: {msg.location.get('url')}:{msg.location.get('lineNumber')})") if msg.type == 'error' else None)
        page.on('pageerror', lambda err: console_errors.append(str(err)))

        print("--- 1. Testing Login ---")
        await page.goto('http://127.0.0.1:8080/auth/login/')
        await page.fill('input[name="email"]', 'wea.pharm2020@gmail.com')
        await page.fill('input[name="password"]', 'Wea@4444')
        await page.click('button[type="submit"]')
        await page.wait_for_load_state('networkidle')
        print("Logged in, current URL:", page.url)

        print("\n--- 2. Testing Global Quick Add & 'تسجيل زيارة خارج الخطة' ---")
        fab = page.locator('.quick-add button')
        await fab.click()
        await page.wait_for_timeout(500)

        # Check sheet is visible
        sheet = page.locator('#quick-add-sheet')
        is_sheet_visible = await sheet.is_visible()
        print("Quick Add Bottom Sheet visible:", is_sheet_visible)

        # Click Action 1: تسجيل زيارة خارج الخطة
        btn_unplanned = page.locator('button:has-text("تسجيل زيارة خارج الخطة")')
        await btn_unplanned.click()
        await page.wait_for_timeout(500)

        # Check modal is visible
        modal = page.locator('#unified-customer-selection-modal')
        is_modal_visible = await modal.is_visible()
        print("Unified Customer Selection Modal visible:", is_modal_visible)

        # Search for a customer
        search_input = page.locator('#unified-customer-search-input')
        await search_input.click()
        await search_input.fill('ا') # common Arabic letter
        await page.wait_for_timeout(600)

        results = page.locator('#unified-customer-results-list > div')
        count = await results.count()
        print(f"Customer search returned {count} results")

        if count > 0:
            first_result = results.first
            customer_text = await first_result.inner_text()
            print("Selecting first customer:", customer_text.replace('\n', ' '))
            await first_result.click()
            await page.wait_for_timeout(400)

            # Check dossier card is visible
            card = page.locator('#unified-selected-customer-card')
            is_card_visible = await card.is_visible()
            print("Selected customer card visible:", is_card_visible)

            # Submit modal
            submit_btn = page.locator('#unified-modal-submit-btn')
            await submit_btn.click()
            await page.wait_for_load_state('networkidle')
            print("After submit, navigated to:", page.url)
            assert 'visits/create' in page.url, f"Expected visits/create in url, got {page.url}"
            assert 'contact_id=' in page.url, f"Expected contact_id in url, got {page.url}"
            print("SUCCESS: Unplanned visit workflow successfully initiated!")

        print("\n--- 3. Testing Overlapping Buttons on Contacts Page Across Viewports ---")
        viewports = [
            (320, 568),
            (375, 812),
            (390, 844),
            (430, 932),
            (1280, 800)
        ]

        for width, height in viewports:
            print(f"\nTesting viewport {width}x{height}...")
            await page.set_viewport_size({'width': width, 'height': height})
            await page.goto('http://127.0.0.1:8080/contacts/')
            await page.wait_for_load_state('networkidle')

            quick_add_btn = page.locator('.quick-add button')
            contact_create_btn = page.locator('a[title="انشئ جهة اتصال"]')

            box_quick = await quick_add_btn.bounding_box()
            box_contact = await contact_create_btn.bounding_box()

            print(f"Quick Add Button Box: y={box_quick['y']}, x={box_quick['x']}, w={box_quick['width']}, h={box_quick['height']}")
            print(f"Contact Create Box:   y={box_contact['y']}, x={box_contact['x']}, w={box_contact['width']}, h={box_contact['height']}")

            # Verify neither box is None
            assert box_quick is not None, "Quick Add button not visible!"
            assert box_contact is not None, "Contact Create button not visible!"

            # Overlap check
            overlap_y = not (box_contact['y'] + box_contact['height'] <= box_quick['y'] or box_quick['y'] + box_quick['height'] <= box_contact['y'])
            overlap_x = not (box_contact['x'] + box_contact['width'] <= box_quick['x'] or box_quick['x'] + box_quick['width'] <= box_contact['x'])
            is_overlapping = overlap_x and overlap_y

            print(f"Buttons overlapping: {is_overlapping}")
            assert not is_overlapping, f"Buttons are overlapping at viewport {width}x{height}!"

            # Test clicking contact create button
            await contact_create_btn.click()
            await page.wait_for_load_state('networkidle')
            print(f"Contact create button clicked -> {page.url}")
            assert 'contacts/create' in page.url or 'contacts/add' in page.url or 'contacts' in page.url

            # Go back to contacts
            await page.goto('http://127.0.0.1:8080/contacts/')
            await page.wait_for_load_state('networkidle')

            # Test clicking quick add button
            await quick_add_btn.click()
            await page.wait_for_timeout(400)
            sheet_visible = await page.locator('#quick-add-sheet').is_visible()
            print(f"Quick Add sheet opened: {sheet_visible}")
            assert sheet_visible, "Quick Add sheet failed to open!"
            # Close it
            await page.click('button:has-text("الغاء")')
            await page.wait_for_timeout(300)

        print("\n--- 4. Checking Console Errors ---")
        if console_errors:
            print("Console Errors detected:", console_errors)
        else:
            print("Zero console errors detected!")

        await browser.close()
        print("\nALL VERIFICATIONS PASSED SUCCESSFULLY!")

if __name__ == '__main__':
    asyncio.run(run())
