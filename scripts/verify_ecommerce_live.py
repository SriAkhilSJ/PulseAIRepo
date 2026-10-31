import subprocess
import sys
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

proc = subprocess.Popen([sys.executable, "app.py"], cwd="PulseAIRepo/showcase/agent_ecommerce")
time.sleep(2)

try:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        
        # 1. Storefront
        page = browser.new_page(viewport={"width": 1366, "height": 900})
        page.goto("http://localhost:8000/")
        page.wait_for_timeout(1000)
        
        print("STOREFRONT TITLE:", page.title())
        
        # Click Add to Cart on first product
        add_btn = page.locator(".add-btn").first
        if add_btn.count() > 0:
            add_btn.click()
            page.wait_for_timeout(500)
            print("CLICKED ADD TO CART")
        
        # Take storefront screenshot
        shot1 = Path("C:/Users/Administrator/.gemini/antigravity/brain/ee8f77bc-5bd3-4f26-a1de-860b32763663/screenshot_ecommerce_v4_storefront.png")
        page.screenshot(path=str(shot1), full_page=True)
        print("STOREFRONT SCREENSHOT:", shot1, "SIZE:", shot1.stat().st_size)
        
        # 2. Admin Hub
        page_admin = browser.new_page(viewport={"width": 1366, "height": 900})
        page_admin.goto("http://localhost:8000/admin.html")
        page_admin.wait_for_timeout(1000)
        print("ADMIN TITLE:", page_admin.title())
        
        shot2 = Path("C:/Users/Administrator/.gemini/antigravity/brain/ee8f77bc-5bd3-4f26-a1de-860b32763663/screenshot_ecommerce_v4_admin.png")
        page_admin.screenshot(path=str(shot2), full_page=True)
        print("ADMIN SCREENSHOT:", shot2, "SIZE:", shot2.stat().st_size)
        
        browser.close()
finally:
    proc.terminate()

print("VERIFICATION COMPLETE!")
