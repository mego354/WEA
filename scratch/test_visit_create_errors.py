import sys
sys.stdout.reconfigure(encoding='utf-8')
from playwright.sync_api import sync_playwright

def test():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        errors = []
        page.on('console', lambda msg: errors.append(f"CONSOLE {msg.type}: {msg.text}") if msg.type in ['error', 'warning'] else None)
        page.on('pageerror', lambda err: errors.append(f"PAGEERROR: {err}"))
        
        page.goto('http://127.0.0.1:8080/auth/login/')
        page.fill('input[name="email"]', 'wea.pharm2020@gmail.com')
        page.fill('input[name="password"]', 'Wea@4444')
        page.click('button[type="submit"]')
        page.wait_for_load_state('networkidle')
        
        page.goto('http://127.0.0.1:8080/visits/create/?contact_id=8884')
        page.wait_for_load_state('networkidle')
        
        print("Page title:", page.title())
        print("Errors encountered:", len(errors))
        for e in errors:
            print("  ", e)
        browser.close()

if __name__ == '__main__':
    test()
