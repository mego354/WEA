import asyncio
import json
import os
import sys
from playwright.async_api import async_playwright

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={'width': 1600, 'height': 1000})
        page = await context.new_page()

        await page.goto("https://weapharma.bricks-rep.com/home", wait_until="networkidle")
        if "login" in page.url or "signin" in page.url or "auth" in page.url:
            await page.fill('input[type="email"], input[name="email"], input[formcontrolname="email"]', "wea.pharm2020@gmail.com")
            await page.fill('input[type="password"], input[name="password"], input[formcontrolname="password"]', "Wea@0000")
            btn = await page.query_selector('button[type="submit"]')
            if btn: await btn.click()
            await page.wait_for_load_state("networkidle")
            await asyncio.sleep(2)

        await page.goto("https://weapharma.bricks-rep.com/contacts/a7517dbe-6c74-402a-8408-a201e108b89f/overview", wait_until="networkidle")
        await asyncio.sleep(2)

        # 1. Inspect accordion headers and click them one by one
        sections = [
            "المعلومات الأساسية",
            "المعلومات الإضافية",
            "حساب العميل",
            "العناوين",
            "المسئولين",
            "طرق الاتصال",
            "الشركاء",
            "الفروع"
        ]

        section_details = {}

        for sec in sections:
            elem = await page.query_selector(f'div:has-text("{sec}"), span:has-text("{sec}"), h4:has-text("{sec}")')
            if elem:
                print(f"Clicking header: {sec}")
                await elem.click()
                await asyncio.sleep(1)
                await page.screenshot(path=f"scratch/screenshots/sec_{sec}.png")
                # get text in the section container
                text_content = await page.evaluate(f"""() => {{
                    const el = Array.from(document.querySelectorAll('*')).find(e => e.innerText && e.innerText.startsWith("{sec}"));
                    if (!el) return '';
                    const parent = el.closest('[class*="panel"], [class*="card"], [class*="item"], div') || el.parentElement;
                    return parent ? parent.innerText : '';
                }}""")
                section_details[sec] = text_content

        with open("scratch/accordion_sections_text.json", "w", encoding="utf-8") as f:
            json.dump(section_details, f, ensure_ascii=False, indent=2)

        # 2. Inspect Edit button click
        print("Clicking 3-dots to open menu...")
        three_dots_btn = await page.query_selector('button:has(mat-icon:has-text("more_vert"))')
        if three_dots_btn:
            await three_dots_btn.click()
            await asyncio.sleep(1)
            edit_btn = await page.query_selector('button:has-text("تعديل")')
            if edit_btn:
                print("Clicking Edit button in menu (view-only)...")
                await edit_btn.click()
                await page.wait_for_load_state("networkidle")
                await asyncio.sleep(3)
                print(f"Edit page URL: {page.url}")
                await page.screenshot(path="scratch/screenshots/06_contact_edit_real.png", full_page=False)

        await browser.close()
        print("Finished!")

if __name__ == '__main__':
    asyncio.run(main())
