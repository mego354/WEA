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

async def fetch_more():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(storage_state="scratch/auth_state.json")
        page = await context.new_page()

        await page.goto("https://weapharma.bricks-rep.com/home", wait_until="domcontentloaded")
        await asyncio.sleep(2)

        results = await page.evaluate('''async () => {
            let token = '';
            try {
                const stored = localStorage.getItem('CapacitorStorage.token');
                if (stored) token = JSON.parse(stored).jwt;
            } catch(e) {}

            const headers = {
                'Authorization': token ? `Bearer ${token}` : '',
                'Content-Type': 'application/json'
            };

            const endpoints = [
                ["po_list_get", "GET", "/api/v1/purchaseOrders?offset=0&limit=40"],
                ["po_list_post", "POST", "/api/v1/purchaseOrders/list", {}],
                ["po_returns", "GET", "/api/v1/purchaseReturnOrders?offset=0&limit=40"],
                ["categories", "GET", "/api/v1/categories?offset=0&limit=40"],
                ["payments", "GET", "/api/v1/vendorPayments?offset=0&limit=40"],
                ["payment_requests", "GET", "/api/v1/vendorPaymentRequests?offset=0&limit=40"],
                ["vendor_accounts", "GET", "/api/v1/accounting/vendors?offset=0&limit=40"],
            ];

            const out = {};
            for (const item of endpoints) {
                const [key, method, path, body] = item;
                try {
                    const opts = { method, headers };
                    if (body) opts.body = JSON.stringify(body);
                    const res = await fetch(path, opts);
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

        with open("scratch/purchases_raw_data.json", "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)

        print("Done fetch_more!")
        await browser.close()

if __name__ == '__main__':
    asyncio.run(fetch_more())
