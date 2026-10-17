import asyncio
import json
import os
import sys
from playwright.async_api import async_playwright

sys.stdout.reconfigure(encoding='utf-8')

async def inspect_fab_on_page(page, page_name, url):
    print(f"\n--- Inspecting FAB on {page_name} ({url}) ---")
    await page.goto(url, wait_until="networkidle")
    await asyncio.sleep(2)

    # Find the FAB button (has mat-fab or mdc-fab and text add)
    fab = await page.query_selector('button.mdc-fab, button.mat-mdc-fab, button[mat-fab]')
    if not fab:
        print("No mat-fab found!")
        return

    # Get parent container HTML and styles
    container_info = await page.evaluate('''() => {
        const fab = document.querySelector('button.mdc-fab, button.mat-mdc-fab, button[mat-fab]');
        if (!fab) return null;
        const parent = fab.parentElement;
        return {
            fabHtml: fab.outerHTML,
            parentTag: parent.tagName,
            parentClass: parent.className,
            parentHtml: parent.outerHTML.slice(0, 500),
            parentStyle: window.getComputedStyle(parent).cssText
        };
    }''')
    print("Container info:", json.dumps(container_info, ensure_ascii=False, indent=2))

    # Take screenshot before click
    await page.screenshot(path=f"scratch/ref_audit/{page_name}_before_fab_click.png")

    # Click the FAB
    print("Clicking FAB...")
    await fab.click()
    await asyncio.sleep(1.5)

    # Take screenshot after click
    await page.screenshot(path=f"scratch/ref_audit/{page_name}_after_fab_click.png")

    # Check what appeared (menus, overlays, speed dial items, modals, dialogs)
    menu_info = await page.evaluate('''() => {
        const res = {};
        
        // Speed dial or children in parent
        const fab = document.querySelector('button.mdc-fab, button.mat-mdc-fab, button[mat-fab]');
        const parent = fab ? fab.parentElement : null;
        res.parentAfterClick = parent ? parent.outerHTML : '';

        // Check for any opened overlay / menu / dialog / bottom-sheet
        const overlays = Array.from(document.querySelectorAll('.cdk-overlay-pane, mat-dialog-container, mat-menu-panel, mat-bottom-sheet-container, .cdk-overlay-container *')).map(el => ({
            tag: el.tagName,
            className: el.className,
            text: el.innerText ? el.innerText.trim() : '',
            html: el.outerHTML.slice(0, 400)
        }));
        res.overlays = overlays;

        // Check for all visible buttons or list items that have text
        const activeItems = Array.from(document.querySelectorAll('.mat-mdc-menu-item, mat-list-item, button, a')).filter(el => {
            const rect = el.getBoundingClientRect();
            return rect.width > 0 && rect.height > 0 && el.innerText.trim();
        }).map(el => ({
            text: el.innerText.trim(),
            tag: el.tagName,
            className: el.className,
            href: el.getAttribute('href') || ''
        }));
        res.activeItemsNearBottom = activeItems.filter(i => {
            // let's see speed-dial or menu items
            return true;
        });

        return res;
    }''')
    with open(f"scratch/ref_audit/{page_name}_fab_opened.json", "w", encoding="utf-8") as f:
        json.dump(menu_info, f, ensure_ascii=False, indent=2)

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            storage_state="scratch/auth_state.json",
            viewport={'width': 1440, 'height': 900}
        )
        page = await context.new_page()

        await inspect_fab_on_page(page, "home", "https://weapharma.bricks-rep.com/home")
        await inspect_fab_on_page(page, "visits", "https://weapharma.bricks-rep.com/visits")
        await inspect_fab_on_page(page, "planned_visits", "https://weapharma.bricks-rep.com/planned-visits")
        await inspect_fab_on_page(page, "agreements", "https://weapharma.bricks-rep.com/agreements")

        await browser.close()

if __name__ == '__main__':
    asyncio.run(main())
