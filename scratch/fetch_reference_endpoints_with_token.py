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

        await page.goto("https://weapharma.bricks-rep.com/home", wait_until="networkidle")

        token_raw = await page.evaluate('''() => {
            return localStorage.getItem('CapacitorStorage.token');
        }''')
        print("Token raw snippet:", str(token_raw)[:40] if token_raw else "None")

        # Now fetch from inside the page context so all cookies and auth headers are automatically attached by Angular's http interceptor or fetch
        results = await page.evaluate('''async () => {
            const token = localStorage.getItem('CapacitorStorage.token');
            const headers = {
                'Content-Type': 'application/json'
            };
            if (token) {
                let parsed = JSON.parse(token);
                let cleanToken = parsed.jwt || parsed.token || parsed;
                headers['Authorization'] = 'Bearer ' + cleanToken;
            }

            const data = {};
            const getEndpoints = [
                '/api/v1/geofence/settings',
                '/api/v1/visits/settings',
                '/api/v1/users/current',
            ];
            for (const ep of getEndpoints) {
                try {
                    const r = await fetch(ep, { headers });
                    data[ep] = await r.json();
                } catch(e) {
                    data[ep] = { error: e.toString() };
                }
            }

            // Post template list
            try {
                const r = await fetch('/api/v1/visits/templates/list', {
                    method: 'POST',
                    headers,
                    body: JSON.stringify({ "limit": 50, "offset": 0 })
                });
                data['/api/v1/visits/templates/list'] = await r.json();
            } catch(e) {
                data['/api/v1/visits/templates/list'] = { error: e.toString() };
            }

            // Post contacts list
            try {
                const r = await fetch('/api/v1/visits/contacts/list', {
                    method: 'POST',
                    headers,
                    body: JSON.stringify({ "pagination":{}, "limit": 10, "offset": 0, "q": "", "preloads": { "contact": true } })
                });
                data['/api/v1/visits/contacts/list'] = await r.json();
            } catch(e) {
                data['/api/v1/visits/contacts/list'] = { error: e.toString() };
            }

            return data;
        }''')

        print("=== FETCH RESULTS WITH TOKEN ===")
        # Print geofence settings
        print("GEOFENCE SETTINGS:")
        print(json.dumps(results.get('/api/v1/geofence/settings'), ensure_ascii=False, indent=2))

        # Print visits settings
        print("VISITS SETTINGS:")
        print(json.dumps(results.get('/api/v1/visits/settings'), ensure_ascii=False, indent=2))

        # Print templates list
        print("TEMPLATES LIST:")
        print(json.dumps(results.get('/api/v1/visits/templates/list'), ensure_ascii=False, indent=2))

        # Print users current
        print("USERS CURRENT:")
        print(json.dumps(results.get('/api/v1/users/current'), ensure_ascii=False, indent=2))

        # Print contacts sample
        print("CONTACTS SAMPLE:")
        print(json.dumps(results.get('/api/v1/visits/contacts/list'), ensure_ascii=False, indent=2))

        await browser.close()

if __name__ == '__main__':
    asyncio.run(main())
