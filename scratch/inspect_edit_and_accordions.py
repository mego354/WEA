import asyncio
import json
import os
import sys
from playwright.async_api import async_playwright

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

async def main():
    results = {}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={'width': 1600, 'height': 1000})
        page = await context.new_page()

        print("Logging in...")
        await page.goto("https://weapharma.bricks-rep.com/home", wait_until="networkidle")
        if "login" in page.url or "signin" in page.url or "auth" in page.url:
            await page.fill('input[type="email"], input[name="email"], input[formcontrolname="email"]', "wea.pharm2020@gmail.com")
            await page.fill('input[type="password"], input[name="password"], input[formcontrolname="password"]', "Wea@4444")
            btn = await page.query_selector('button[type="submit"]')
            if btn: await btn.click()
            await page.wait_for_load_state("networkidle")
            await asyncio.sleep(2)

        # 1. Edit page inspection
        print("Navigating to contact detail...")
        await page.goto("https://weapharma.bricks-rep.com/contacts/a7517dbe-6c74-402a-8408-a201e108b89f/overview", wait_until="networkidle")
        await asyncio.sleep(2)

        three_dots = await page.query_selector('button:has(mat-icon:has-text("more_vert"))')
        if three_dots:
            print("Opening 3-dots menu...")
            await three_dots.click()
            await asyncio.sleep(1)
            edit_item = await page.query_selector('button:has-text("تعديل")')
            if edit_item:
                print("Clicking 'تعديل'...")
                await edit_item.click()
                await page.wait_for_load_state("networkidle")
                await asyncio.sleep(3)
                print("Edit page URL:", page.url)
                results["edit_page_url"] = page.url
                await page.screenshot(path="scratch/screenshots/06_edit_page.png", full_page=True)

                # Extract edit form fields
                edit_fields = await page.evaluate("""() => {
                    return Array.from(document.querySelectorAll('mat-form-field, .form-group, input, select, textarea')).map(el => {
                        const label = el.querySelector('label, .mat-form-field-label')?.innerText?.trim() || '';
                        const val = el.querySelector('input, select, textarea')?.value || '';
                        const placeholder = el.querySelector('input, select, textarea')?.placeholder || '';
                        return { label, val, placeholder };
                    }).filter(f => f.label || f.placeholder || f.val);
                }""")
                results["edit_fields"] = edit_fields

        # 2. Inspect accordions by clicking each one carefully via page.click on text
        print("Returning to detail overview to inspect accordion bodies...")
        await page.goto("https://weapharma.bricks-rep.com/contacts/a7517dbe-6c74-402a-8408-a201e108b89f/overview", wait_until="networkidle")
        await asyncio.sleep(2)

        # Let's inspect the DOM of the accordion container
        sections_data = await page.evaluate("""() => {
            const panels = Array.from(document.querySelectorAll('.mat-expansion-panel, [class*="expansion"], [class*="accordion"] > *'));
            return panels.map(p => ({
                header: p.querySelector('[class*="header"], [class*="title"]')?.innerText?.trim() || '',
                body: p.querySelector('[class*="body"], [class*="content"]')?.innerText?.trim() || ''
            }));
        }""")
        results["initial_panels"] = sections_data
        print(f"Found {len(sections_data)} initial panels:", [p["header"] for p in sections_data])

        # Let's click the headers:
        header_names = [
            "المعلومات الإضافية",
            "حساب العميل",
            "العناوين",
            "المسئولين",
            "طرق الاتصال",
            "الشركاء",
            "الفروع"
        ]

        accordion_contents = {}
        for h_name in header_names:
            print(f"Clicking header: '{h_name}'...")
            header_el = await page.query_selector(f'text="{h_name}"')
            if header_el:
                await header_el.click()
                await asyncio.sleep(1)
                body_text = await page.evaluate(f"""() => {{
                    const el = Array.from(document.querySelectorAll('*')).find(e => e.innerText && e.innerText.trim() === "{h_name}");
                    if (!el) return '';
                    let parent = el.parentElement;
                    while (parent && !parent.classList.contains('mat-expansion-panel') && parent.tagName !== 'DIV') {{
                        parent = parent.parentElement;
                    }}
                    return parent ? parent.innerText : '';
                }}""")
                accordion_contents[h_name] = body_text

        results["accordion_contents"] = accordion_contents
        await page.screenshot(path="scratch/screenshots/detail_all_open.png", full_page=True)

        with open("scratch/edit_and_accordions_report.json", "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)

        print("Inspection script completed successfully!")
        await browser.close()

if __name__ == '__main__':
    asyncio.run(main())
