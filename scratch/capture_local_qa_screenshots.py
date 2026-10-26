import os
import sys
import time
from playwright.sync_api import sync_playwright

def run():
    out_dir = r"c:\D\Cooding\GENERAL\new\ERP\scratch\screenshots"
    os.makedirs(out_dir, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1400, "height": 900})
        page = context.new_page()

        # Login
        print("Logging in to local ERP...")
        page.goto("http://127.0.0.1:8000/auth/login/")
        page.fill("input[name='email']", "wea.pharm2020@gmail.com")
        page.fill("input[name='password']", "Wea@4444")
        page.click("button[type='submit']")
        page.wait_for_load_state("networkidle")
        time.sleep(1)

        # 1. Products List
        print("Capturing Local Products List...")
        page.goto("http://127.0.0.1:8000/products/")
        page.wait_for_load_state("networkidle")
        page.screenshot(path=os.path.join(out_dir, "local_01_products_list.png"))

        # 2. Products Filter Drawer
        print("Capturing Local Products Filter Drawer...")
        filter_btn = page.query_selector("button:has-text('فلتر'), button:has-text('الفلاتر')")
        if filter_btn:
            filter_btn.click()
            time.sleep(0.5)
            page.screenshot(path=os.path.join(out_dir, "local_02_products_filter_drawer.png"))

        # 3. Create Product Form
        print("Capturing Local Create Product Form...")
        page.goto("http://127.0.0.1:8000/products/create/")
        page.wait_for_load_state("networkidle")
        page.screenshot(path=os.path.join(out_dir, "local_03_create_product_form.png"))

        # 4. Product Categories
        print("Capturing Local Product Categories...")
        page.goto("http://127.0.0.1:8000/product-categories/")
        page.wait_for_load_state("networkidle")
        page.screenshot(path=os.path.join(out_dir, "local_04_product_categories.png"))

        # 5. Purchase Orders List
        print("Capturing Local Purchase Orders List...")
        page.goto("http://127.0.0.1:8000/purchase-orders/")
        page.wait_for_load_state("networkidle")
        page.screenshot(path=os.path.join(out_dir, "local_05_purchase_orders_list.png"))

        # 6. Purchase Orders Filter Drawer
        print("Capturing Local Purchase Orders Filter Drawer...")
        po_filter_btn = page.query_selector("button:has-text('فلتر'), button:has-text('الفلاتر')")
        if po_filter_btn:
            po_filter_btn.click()
            time.sleep(0.5)
            page.screenshot(path=os.path.join(out_dir, "local_06_po_filter_drawer.png"))

        # 7. Purchase Order Detail (Order #1 or #2)
        print("Capturing Local Purchase Order Detail...")
        page.goto("http://127.0.0.1:8000/purchase-orders/2/")
        page.wait_for_load_state("networkidle")
        page.screenshot(path=os.path.join(out_dir, "local_07_po_detail.png"))

        # 8. Create Purchase Order Form
        print("Capturing Local Create Purchase Order Form...")
        page.goto("http://127.0.0.1:8000/purchase-orders/create/")
        page.wait_for_load_state("networkidle")
        page.screenshot(path=os.path.join(out_dir, "local_08_create_po.png"))

        # 9. Purchase Return Orders
        print("Capturing Local Purchase Return Orders...")
        page.goto("http://127.0.0.1:8000/purchase-return-orders/")
        page.wait_for_load_state("networkidle")
        page.screenshot(path=os.path.join(out_dir, "local_09_purchase_return_orders.png"))

        # 10. Vendor Payments
        print("Capturing Local Vendor Payments...")
        page.goto("http://127.0.0.1:8000/vendor-payments/")
        page.wait_for_load_state("networkidle")
        page.screenshot(path=os.path.join(out_dir, "local_10_vendor_payments.png"))

        browser.close()
        print("QA Screenshots successfully captured!")

if __name__ == "__main__":
    run()
