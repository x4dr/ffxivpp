import pytest
from playwright.sync_api import Page, expect

# Minimal UI health check: verifies page loads and no JS errors occur.
# Business logic is now covered by integration tests (test_api.py).

def test_dashboard_ui_health(page: Page, live_server):
    # Enable JS error detection
    page.on("pageerror", lambda err: pytest.fail(f"Uncaught JS Exception: {err}"))
    
    def on_console(msg):
        if msg.type == "error":
            pytest.fail(f"JS Console Error: {msg.text}")
    
    page.on("console", on_console)
    
    # Load dashboard
    page.goto(live_server.url() + "/party/Default", wait_until="domcontentloaded")
    
    # Simple UI check to ensure it rendered
    expect(page).to_have_title("FF14 Party Planner — Dashboard")
