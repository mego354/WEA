import asyncio
import os
import json
import sys

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from playwright.async_api import async_playwright

async def fetch_via_browser():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(storage_state="scratch/auth_state.json")
        page = await context.new_page()

        await page.goto("https://weapharma.bricks-rep.com/home", wait_until="domcontentloaded")
        await asyncio.sleep(3)

        results = await page.evaluate('''async () => {
            let token = '';
            try {
                const stored = localStorage.getItem('CapacitorStorage.token');
                if (stored) {
                    token = JSON.parse(stored).jwt;
                }
            } catch(e) {}

            const headers = {
                'Authorization': token ? `Bearer ${token}` : '',
                'Content-Type': 'application/json'
            };

            const endpoints = [
                ["po_states", "/api/v1/purchaseOrders/wf/states"],
                ["products_list", "/api/v1/products?offset=0&limit=40"],
                ["product_categories", "/api/v1/productCategories?offset=0&limit=40"],
                ["products_filters", "/api/v1/filters/view/products-listing"],
                ["po_filters", "/api/v1/filters/view/purchase-orders-listing"],
            ];

            const out = {};
            for (const [key, path] of endpoints) {
                try {
                    const res = await fetch(path, { headers });
                    if (res.ok) {
                        out[key] = await res.json();
                    } else {
                        out[key] = `HTTP ${res.status}`;
                    }
                } catch (e) {
                    out[key] = `Error: ${e.message}`;
                }
            }
            return out;
        }''')

        with open("scratch/readonly_erp_metadata.json", "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)

        print("Fetched full metadata successfully!")
        await browser.close()

if __name__ == '__main__':
    asyncio.run(fetch_via_browser())
