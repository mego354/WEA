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

        # 1. Fetch geofence/settings and visits/settings via evaluate fetch
        await page.goto("https://weapharma.bricks-rep.com/home", wait_until="networkidle")

        settings_data = await page.evaluate('''async () => {
            const results = {};
            const endpoints = [
                '/api/v1/geofence/settings',
                '/api/v1/visits/settings',
                '/api/v1/users/current'
            ];
            for (const ep of endpoints) {
                try {
                    const res = await fetch(ep);
                    results[ep] = await res.json();
                } catch (e) {
                    results[ep] = { error: e.toString() };
                }
            }
            return results;
        }''')
        print("=== SETTINGS DATA ===")
        print(json.dumps(settings_data, ensure_ascii=False, indent=2))

        # 2. Inspect Settings menu subitems in sidebar
        print("=== EXPANDING SETTINGS MENU ===")
        settings_btn = await page.query_selector('//span[contains(text(), "إعدادات")] | //a[contains(., "إعدادات")] | //div[contains(text(), "إعدادات")]')
        if settings_btn:
            await settings_btn.click()
            await asyncio.sleep(1)

        subitems = await page.evaluate('''() => {
            return Array.from(document.querySelectorAll('a, mat-list-item, .nav-item, [routerlink]')).map(el => ({
                text: el.innerText.trim().replace(/\\n+/g, ' '),
                href: el.href || el.getAttribute('href') || el.getAttribute('routerlink')
            })).filter(x => x.text.length > 0 && x.text.length < 50);
        }''')
        print("=== SUBITEMS AFTER EXPANDING ===")
        print(json.dumps(subitems, ensure_ascii=False, indent=2))

        # 3. Inspect a Visit View
        print("=== INSPECTING VISIT VIEW ===")
        await page.goto("https://weapharma.bricks-rep.com/visits/view/81aaad0b-51d7-4f0e-98ec-a8507eab6042", wait_until="networkidle")
        await asyncio.sleep(2)

        visit_view_data = await page.evaluate('''() => {
            return {
                title: document.title,
                url: window.location.href,
                bodyText: document.body.innerText.slice(0, 3000),
                buttons: Array.from(document.querySelectorAll('button, a.btn, a.mat-mdc-button')).map(b => b.innerText.trim()),
                hasMap: !!document.querySelector('google-map, .map, [id*="map"], iframe[src*="google"], .leaflet-container'),
                mapElements: Array.from(document.querySelectorAll('google-map, .map, [id*="map"], iframe, img[src*="staticmap"]')).map(el => ({
                    tag: el.tagName,
                    src: el.src || el.getAttribute('src'),
                    className: el.className
                }))
            };
        }''')
        print("Visit View Info:")
        print(json.dumps(visit_view_data, ensure_ascii=False, indent=2))

        # 4. Inspect Contacts location info (open a contact view)
        print("=== INSPECTING CONTACT VIEW ===")
        await page.goto("https://weapharma.bricks-rep.com/contacts/d7cbf33a-d152-4d7e-bc40-93eeb5047264", wait_until="networkidle")
        await asyncio.sleep(2)

        contact_view_data = await page.evaluate('''() => {
            return {
                title: document.title,
                bodyText: document.body.innerText.slice(0, 3000),
                locationKeywords: Array.from(document.querySelectorAll('*')).filter(el => {
                    const t = el.innerText || '';
                    return (t.includes('موقع') || t.includes('GPS') || t.includes('إحداثيات') || t.includes('مكان') || t.includes('خريطة') || t.includes('العنوان')) && el.children.length === 0;
                }).map(el => el.innerText.trim()).slice(0, 20)
            };
        }''')
        print("Contact View Info:")
        print(json.dumps(contact_view_data, ensure_ascii=False, indent=2))

        await browser.close()

if __name__ == '__main__':
    asyncio.run(main())
