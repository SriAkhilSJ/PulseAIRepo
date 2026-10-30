#!/usr/bin/env python3
"""Capture Desktop Workbench with Crusor Agentic UI Panel Open."""
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

REPO_ROOT = Path(__file__).resolve().parents[1]
SCREENSHOT_PATH = REPO_ROOT / "screenshots" / "desktop_agentic_ui.png"
SCREENSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)


def capture_desktop_ui():
    print("[Desktop Agentic UI] Connecting Playwright to http://localhost:8080...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1920, "height": 1080})
        page = context.new_page()

        print("[Desktop Agentic UI] Loading VS Code Workbench...")
        page.goto("http://localhost:8080", wait_until="networkidle", timeout=60000)

        # Wait for the workbench container to appear
        print("[Desktop Agentic UI] Waiting for workbench shell...")
        page.wait_for_selector(".monaco-workbench", timeout=30000)
        time.sleep(3)

        # Open Command Palette via F1
        print("[Desktop Agentic UI] Opening Command Palette to focus Crusor Agent...")
        page.keyboard.press("F1")
        time.sleep(1)

        # Type Crusor: Open Agent
        page.keyboard.type("Crusor: Open Agent", delay=20)
        time.sleep(1)
        page.keyboard.press("Enter")
        time.sleep(3)

        # Also ensure auxiliary bar is toggled open via shortcut or command if needed
        # Check if auxiliary bar is visible
        aux_bar = page.locator(".part.auxiliarybar")
        if aux_bar.count() > 0:
            print("  [INFO] Auxiliary bar detected in DOM")

        # Capture the screenshot
        print(f"[Desktop Agentic UI] Capturing screenshot to {SCREENSHOT_PATH}...")
        page.screenshot(path=str(SCREENSHOT_PATH), full_page=False)
        print("  [PASS] Full Desktop + Agentic UI Screenshot captured successfully!")

        browser.close()


if __name__ == "__main__":
    capture_desktop_ui()
