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

async def fetch_metadata():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(storage_state="scratch/auth_state.json")
        page = await context.new_page()

        # Let's read-only fetch states, filters, and schema
        endpoints = [
            ("po_states", "https://weapharma.bricks-rep.com/api/v1/purchaseOrders/wf/states"),
            ("products_list", "https://weapharma.bricks-rep.com/api/v1/products?offset=0&limit=40"),
            ("product_categories", "https://weapharma.bricks-rep.com/api/v1/product-categories?offset=0&limit=40"),
            ("products_filters", "https://weapharma.bricks-rep.com/api/v1/filters/view/products-listing"),
            ("po_filters", "https://weapharma.bricks-rep.com/api/v1/filters/view/purchase-orders-listing"),
            ("po_aggregate", "https://weapharma.bricks-rep.com/api/v1/purchaseOrders/aggregate"),
        ]

        results = {}
        for key, url in endpoints:
            try:
                resp = await context.request.get(url)
                if resp.status == 200:
                    results[key] = await resp.json()
                else:
                    results[key] = f"Status {resp.status}"
            except Exception as e:
                results[key] = f"Error: {e}"

        with open("scratch/readonly_erp_metadata.json", "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)

        print("Saved scratch/readonly_erp_metadata.json successfully!")
        await browser.close()

if __name__ == '__main__':
    asyncio.run(fetch_metadata())
