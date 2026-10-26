import asyncio
import json
import os
import sys
from playwright.async_api import async_playwright

sys.stdout.reconfigure(encoding='utf-8')

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        # Use existing auth state or login
        context = await browser.new_context(
            storage_state="scratch/auth_state.json" if os.path.exists("scratch/auth_state.json") else None,
            viewport={'width': 1440, 'height': 900}
        )
        page = await context.new_page()

        print("Navigating to https://weapharma.bricks-rep.com/home ...")
        await page.goto("https://weapharma.bricks-rep.com/home", wait_until="networkidle")

        # Check if login needed
        if "login" in page.url or "signin" in page.url or "auth" in page.url:
            print("Logging in...")
            await page.wait_for_selector('input[type="email"], input[name="email"], input[formcontrolname="email"]', timeout=10000)
            await page.fill('input[type="email"], input[name="email"], input[formcontrolname="email"]', "wea.pharm2020@gmail.com")
            await page.fill('input[type="password"], input[name="password"], input[formcontrolname="password"]', "Wea@4444")
            btn = await page.query_selector('button[type="submit"]')
            if btn: await btn.click()
            await page.wait_for_load_state("networkidle")
            await asyncio.sleep(3)
            await context.storage_state(path="scratch/auth_state.json")
            print("Logged in successfully.")

        os.makedirs("scratch/ref_audit", exist_ok=True)
        await page.screenshot(path="scratch/ref_audit/01_home.png")

        # 1. Inspect Sidebar under Activities
        print("Inspecting Sidebar...")
        # Check if Activities is expanded or needs clicking
        activities_menu = await page.evaluate('''() => {
            const items = [];
            document.querySelectorAll('mat-nav-list a, .nav-item, mat-expansion-panel').forEach(el => {
                items.push({
                    text: el.innerText.trim(),
                    tag: el.tagName,
                    href: el.getAttribute('href') || ''
                });
            });
            return items;
        }''')
        with open("scratch/ref_audit/sidebar_items.json", "w", encoding="utf-8") as f:
            json.dump(activities_menu, f, ensure_ascii=False, indent=2)

        # 2. Inspect Floating Action Button (+ button) on /home and other pages
        print("Inspecting Floating Plus Button...")
        fab_info = await page.evaluate('''() => {
            // Find all buttons that have 'add' or fab classes or fixed position at bottom
            const fabs = [];
            const allBtns = Array.from(document.querySelectorAll('button, a, div[role="button"], mat-fab, .mat-mdc-fab, .fab'));
            for (const b of allBtns) {
                const rect = b.getBoundingClientRect();
                const style = window.getComputedStyle(b);
                const isFixed = style.position === 'fixed' || style.position === 'absolute';
                const hasAdd = b.innerText.includes('add') || b.querySelector('.material-icons')?.innerText.includes('add') || b.querySelector('mat-icon')?.innerText.includes('add');
                if ((isFixed && (rect.bottom > window.innerHeight - 150)) || hasAdd || b.classList.contains('mat-mdc-fab')) {
                    fabs.push({
                        text: b.innerText.trim(),
                        html: b.outerHTML.slice(0, 300),
                        tag: b.tagName,
                        className: b.className,
                        rect: { top: rect.top, bottom: rect.bottom, left: rect.left, right: rect.right, width: rect.width, height: rect.height },
                        computedStyle: {
                            position: style.position,
                            bottom: style.bottom,
                            left: style.left,
                            right: style.right,
                            top: style.top,
                            backgroundColor: style.backgroundColor,
                            color: style.color,
                            borderRadius: style.borderRadius,
                            boxShadow: style.boxShadow,
                            zIndex: style.zIndex,
                            width: style.width,
                            height: style.height
                        }
                    });
                }
            }
            return fabs;
        }''')
        with open("scratch/ref_audit/fab_candidates_home.json", "w", encoding="utf-8") as f:
            json.dump(fab_info, f, ensure_ascii=False, indent=2)

        # Let's inspect pages: visits, planned-visits, agreements
        pages_to_check = [
            ("visits", "https://weapharma.bricks-rep.com/visits"),
            ("planned_visits", "https://weapharma.bricks-rep.com/planned-visits"),
            ("agreements", "https://weapharma.bricks-rep.com/agreements")
        ]

        for name, url in pages_to_check:
            print(f"Inspecting {name} ({url})...")
            await page.goto(url, wait_until="networkidle")
            await asyncio.sleep(3)
            await page.screenshot(path=f"scratch/ref_audit/{name}.png")

            # Check floating button on this page
            page_fab = await page.evaluate('''() => {
                const fabs = [];
                const allBtns = Array.from(document.querySelectorAll('button, a, div[role="button"], mat-fab, .mat-mdc-fab, .fab'));
                for (const b of allBtns) {
                    const rect = b.getBoundingClientRect();
                    const style = window.getComputedStyle(b);
                    const isFixed = style.position === 'fixed';
                    const hasAdd = b.innerText.includes('add') || (b.querySelector('mat-icon') && b.querySelector('mat-icon').innerText.includes('add'));
                    if (isFixed || hasAdd || b.classList.contains('mat-mdc-fab')) {
                        fabs.push({
                            text: b.innerText.trim(),
                            html: b.outerHTML.slice(0, 300),
                            className: b.className,
                            rect: { top: rect.top, bottom: rect.bottom, left: rect.left, right: rect.right, width: rect.width, height: rect.height },
                            computedStyle: {
                                position: style.position,
                                bottom: style.bottom,
                                left: style.left,
                                right: style.right,
                                top: style.top,
                                backgroundColor: style.backgroundColor,
                                color: style.color,
                                borderRadius: style.borderRadius,
                                boxShadow: style.boxShadow,
                                zIndex: style.zIndex
                            }
                        });
                    }
                }
                return fabs;
            }''')
            with open(f"scratch/ref_audit/{name}_fabs.json", "w", encoding="utf-8") as f:
                json.dump(page_fab, f, ensure_ascii=False, indent=2)

            # Check page header, actions, table headers
            page_details = await page.evaluate('''() => {
                const title = document.querySelector('h1, h2, .title, mat-toolbar')?.innerText || '';
                const tableHeaders = Array.from(document.querySelectorAll('th, mat-header-cell')).map(th => th.innerText.trim());
                const actionButtons = Array.from(document.querySelectorAll('button, a.btn, a.mat-button, a.mat-raised-button, a.mat-icon-button')).map(b => ({
                    text: b.innerText.trim(),
                    aria: b.getAttribute('aria-label') || '',
                    title: b.getAttribute('title') || '',
                    class: b.className
                }));
                const filterLabels = Array.from(document.querySelectorAll('mat-form-field label, .filter-label, .form-group label')).map(l => l.innerText.trim());
                return {
                    title,
                    tableHeaders,
                    actionButtons: actionButtons.slice(0, 30),
                    filterLabels
                };
            }''')
            with open(f"scratch/ref_audit/{name}_details.json", "w", encoding="utf-8") as f:
                json.dump(page_details, f, ensure_ascii=False, indent=2)

        print("Audit run finished successfully!")
        await browser.close()

if __name__ == '__main__':
    asyncio.run(main())
