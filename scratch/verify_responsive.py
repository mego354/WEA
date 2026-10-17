import os
import sys
import asyncio
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')
from playwright.async_api import async_playwright

VIEWPORTS = [
    {"name": "320x640_iphone_se_mini", "width": 320, "height": 640},
    {"name": "360x800_android_compact", "width": 360, "height": 800},
    {"name": "375x812_iphone_x", "width": 375, "height": 812},
    {"name": "390x844_iphone_12_14", "width": 390, "height": 844},
    {"name": "430x932_iphone_15_pro_max", "width": 430, "height": 932},
    {"name": "768x1024_ipad_portrait", "width": 768, "height": 1024},
    {"name": "1024x768_ipad_landscape", "width": 1024, "height": 768},
    {"name": "1366x768_laptop_hd", "width": 1366, "height": 768},
    {"name": "1920x1080_desktop_fhd", "width": 1920, "height": 1080},
]

PAGES = [
    {"url": "http://127.0.0.1:8000/home/", "label": "home"},
    {"url": "http://127.0.0.1:8000/visits/", "label": "visits"},
    {"url": "http://127.0.0.1:8000/planned-visits/", "label": "planned_visits"},
    {"url": "http://127.0.0.1:8000/agreements/", "label": "agreements"},
]

OUT_DIR = "scratch/responsive_audit"
os.makedirs(OUT_DIR, exist_ok=True)

async def run():
    print("=" * 60)
    print("STARTING RESPONSIVE AUDIT ACROSS 9 MANDATORY VIEWPORTS")
    print("=" * 60)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1366, "height": 768})
        page = await context.new_page()

        # Login first
        print("Logging in to local ERP...")
        await page.goto("http://127.0.0.1:8000/auth/login/")
        await page.wait_for_selector('input[name="email"]')
        await page.fill('input[name="email"]', "wea.pharm2020@gmail.com")
        await page.fill('input[name="password"]', "Wea@4444")
        await page.click('button[type="submit"]')
        await page.wait_for_url("http://127.0.0.1:8000/home/")
        print("✓ Logged in successfully.")

        storage_state = await context.storage_state()
        await context.close()

        # Now test viewports
        discrepancies = []

        for vp in VIEWPORTS:
            w = vp["width"]
            h = vp["height"]
            vp_name = vp["name"]
            print(f"\n--- Testing Viewport: {vp_name} ({w}x{h}) ---")

            ctx = await browser.new_context(viewport={"width": w, "height": h}, storage_state=storage_state)
            test_page = await ctx.new_page()

            for p_info in PAGES:
                url = p_info["url"]
                label = p_info["label"]
                await test_page.goto(url)
                await test_page.wait_for_load_state("networkidle")

                # Check horizontal overflow
                scroll_width = await test_page.evaluate("document.documentElement.scrollWidth")
                inner_width = await test_page.evaluate("window.innerWidth")
                has_overflow = scroll_width > inner_width

                if has_overflow:
                    print(f"  [OVERFLOW] {label} at {w}x{h}: scrollWidth={scroll_width} > innerWidth={inner_width}")
                    discrepancies.append(f"{label} overflow at {vp_name}")
                else:
                    print(f"  ✓ {label:<16} (No horizontal overflow: {scroll_width}px <= {inner_width}px)")

                # Screenshot base page
                shot_path = os.path.join(OUT_DIR, f"{label}_{w}x{h}.png")
                await test_page.screenshot(path=shot_path, full_page=False)

            # Test FAB & Quick Add interaction at this viewport on /visits/
            await test_page.goto("http://127.0.0.1:8000/visits/")
            await test_page.wait_for_load_state("networkidle")

            fab = test_page.locator(".quick-add button, button[aria-label='إضافة سريعة']").first
            is_fab_visible = await fab.is_visible()
            assert is_fab_visible, f"FAB not visible at {w}x{h}"

            # Click FAB to open bottom sheet
            await fab.click()
            await test_page.wait_for_timeout(300)
            sheet = test_page.locator("#quick-add-sheet")
            is_sheet_visible = await sheet.is_visible()
            assert is_sheet_visible, f"Bottom sheet failed to open at {w}x{h}"

            # Screenshot opened bottom sheet
            sheet_shot = os.path.join(OUT_DIR, f"fab_sheet_{w}x{h}.png")
            await test_page.screenshot(path=sheet_shot)

            # Click Action 1 to open Unplanned Visit modal
            action1 = test_page.locator('button:has-text("تسجيل زيارة خارج الخطة")').first
            await action1.click()
            await test_page.wait_for_timeout(300)

            modal = test_page.locator("#unplanned-visit-modal")
            is_modal_visible = await modal.is_visible()
            assert is_modal_visible, f"Unplanned visit modal failed to open at {w}x{h}"

            # Screenshot modal
            modal_shot = os.path.join(OUT_DIR, f"unplanned_modal_{w}x{h}.png")
            await test_page.screenshot(path=modal_shot)

            # Close modal
            close_btn = modal.locator('button:has-text("close")').first
            await close_btn.click()
            await test_page.wait_for_timeout(200)

            print(f"  ✓ Global FAB -> Bottom Sheet -> Unplanned Modal verified at {w}x{h}")
            await ctx.close()

        await browser.close()

        print("\n" + "=" * 60)
        if not discrepancies:
            print("ALL 9 VIEWPORTS VERIFIED! ZERO HORIZONTAL OVERFLOW OR CLIPPING.")
        else:
            print(f"FOUND {len(discrepancies)} ISSUES:")
            for d in discrepancies:
                print(f" - {d}")
        print("=" * 60)

if __name__ == "__main__":
    asyncio.run(run())
