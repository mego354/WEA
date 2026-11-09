import asyncio
import sys
import os
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={'width': 1280, 'height': 900})
        page = await context.new_page()

        console_errors = []
        page.on('console', lambda msg: console_errors.append(f"[{msg.type}] {msg.text}") if msg.type in ('error', 'warning') and 'tailwindcss' not in msg.text else None)
        page.on('pageerror', lambda err: console_errors.append(f"[PAGE_ERROR] {str(err)}"))

        print("1. Logging in...")
        await page.goto('http://127.0.0.1:8002/login/', wait_until='domcontentloaded')
        await page.fill('input[name="email"]', 'superadmin_test')
        await page.fill('input[name="password"]', 'Wea@1234')
        await page.click('button[type="submit"]')
        await page.wait_for_timeout(2000)

        print("2. Navigating to /planned-visits/...")
        await page.goto('http://127.0.0.1:8002/planned-visits/', wait_until='domcontentloaded')
        await page.wait_for_timeout(1000)

        # Initial client count
        initial_cards = await page.locator('.drawer-client-card').count()
        print(f"Initial visible client cards: {initial_cards}")
        assert initial_cards > 0, "No client cards displayed initially"

        # 3. Filter by Governorate (Main Area): Area 560 (محافظة القاهرة)
        print("3. Testing Governorate (Main Area) Filter for Area 560...")
        main_area_select = page.locator('#filter_main_area')
        await main_area_select.select_option('560')
        await page.wait_for_timeout(1500)

        # Verify bricks dropdown cascaded to Cairo 560 bricks (مدينة نصر and المعادي)
        brick_select = page.locator('#filter_area')
        brick_options_text = await brick_select.evaluate("sel => Array.from(sel.options).map(o => o.text)")
        print(f"Cascaded Bricks for Area 560: {brick_options_text}")
        assert any('المعادي' in t for t in brick_options_text), "المعادي not found in cascaded bricks for Area 560"
        assert any('مدينة نصر' in t for t in brick_options_text), "مدينة نصر not found in cascaded bricks for Area 560"

        # Check client cards after Area 560 filter
        cairo_cards = await page.locator('.drawer-client-card').count()
        print(f"Visible client cards after Area 560 filter: {cairo_cards}")
        assert cairo_cards > 0, "No client cards found after filtering by Area 560"

        # 4. Filter by Brick: 562 (المعادي)
        print("4. Testing Brick Filter: المعادي (562)...")
        await brick_select.select_option('562')
        await page.wait_for_timeout(1500)

        # Verify only Maadi clients are visible
        maadi_cards = await page.locator('.drawer-client-card').count()
        print(f"Visible client cards after Maadi brick filter: {maadi_cards}")
        assert maadi_cards == 1, f"Expected exactly 1 client for Maadi, got {maadi_cards}"
        card_text = await page.locator('.drawer-client-card').nth(0).inner_text()
        print(f"Maadi card text: {card_text.replace(chr(10), ' ')}")
        assert 'المعادي' in card_text, "Card does not contain المعادي"

        # 5. Filter by Brick: 561 (مدينة نصر)
        print("5. Testing Brick Filter: مدينة نصر (561)...")
        await brick_select.select_option('561')
        await page.wait_for_timeout(1500)

        nasr_cards = await page.locator('.drawer-client-card').count()
        print(f"Visible client cards after Nasr City brick filter: {nasr_cards}")
        assert nasr_cards == 1, f"Expected exactly 1 client for Nasr City, got {nasr_cards}"
        nasr_card_text = await page.locator('.drawer-client-card').nth(0).inner_text()
        print(f"Nasr City card text: {nasr_card_text.replace(chr(10), ' ')}")
        assert 'مكرم عبيد' in nasr_card_text or 'مدينة نصر' in nasr_card_text

        # 6. Test Reset Filters Button (إلغاء)
        print("6. Testing Reset Filters...")
        reset_btn = page.locator('button:has-text("إلغاء")').nth(0)
        await reset_btn.click()
        await page.wait_for_timeout(1500)

        reset_cards = await page.locator('.drawer-client-card').count()
        print(f"Visible client cards after Reset: {reset_cards}")
        assert reset_cards == initial_cards, f"Expected {initial_cards} cards after reset, got {reset_cards}"

        # 7. Test Debounced Search
        print("7. Testing Debounced Search: مصدق...")
        search_input = page.locator('#filter_contact_search')
        await search_input.fill('مصدق')
        await page.wait_for_timeout(1500)

        search_cards = await page.locator('.drawer-client-card').count()
        print(f"Visible client cards after search 'مصدق': {search_cards}")
        assert search_cards == 1, f"Expected 1 card for 'مصدق', got {search_cards}"
        search_text = await page.locator('.drawer-client-card').nth(0).inner_text()
        print(f"Found card text: {search_text.replace(chr(10), ' ')}")
        assert 'مصدق' in search_text, "Expected 'مصدق' in card text"

        print("Errors recorded during test:", console_errors)
        assert len(console_errors) == 0, f"Found console errors: {console_errors}"
        print("ALL AREA AND BRICK FILTER BROWSER TESTS PASSED PERFECTLY!")

        await browser.close()

if __name__ == '__main__':
    asyncio.run(main())
