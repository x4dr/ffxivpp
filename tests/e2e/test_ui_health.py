import pytest
from playwright.sync_api import Page

# Minimal UI health check: verifies the public page loads and no JS errors occur.
# Business logic is covered by integration tests (test_api.py).


def test_landing_ui_health(page: Page, live_server) -> None:
    # Only fail on actual JS exceptions (crashes), not console log noise.
    page.on("pageerror", lambda err: pytest.fail(f"Uncaught JS Exception: {err}"))

    page.goto(live_server.url() + "/", wait_until="domcontentloaded")

    assert page.locator("h1").is_visible()
