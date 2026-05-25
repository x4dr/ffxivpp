import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent.parent))

import pytest
import subprocess
import time
import os
import httpx
from playwright.sync_api import Page


@pytest.fixture(scope="session")
def no_auth_server():
    # Setup test database
    db_path = "test_e2e_no_auth.db"
    os.environ["DATABASE_PATH"] = db_path
    os.environ["TEST_MOCK_AUTH"] = "0"
    os.environ["PORT"] = "7112"
    
    # Start the server
    port = 7112 # Different port
    env = os.environ.copy()
    env["FLASK_APP"] = "app"
    env["FLASK_ENV"] = "testing"
    env["PYTHONUNBUFFERED"] = "1"
    
    # Start server as a subprocess
    process = subprocess.Popen(
        [".venv/bin/python3", "app.py"],
        env=env,
        stdout=None,
        stderr=None
    )
    
    # Wait for server to start
    url = f"http://127.0.0.1:{port}"
    
    def wait_for_server(url: str) -> None:
        with httpx.Client() as client:
            for _ in range(10):
                try:
                    client.get(url)
                    break
                except httpx.ConnectError:
                    time.sleep(1)
            else:
                raise RuntimeError("Server did not start")
    
    try:
        wait_for_server(url)
    except Exception:
        process.kill()
        raise
    
    yield url
    
    # Teardown
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
    if os.path.exists(db_path):
        os.remove(db_path)


def test_unauthenticated_redirect(no_auth_server: str):
    # Verify that unauthenticated users are redirected to /auth/login
    with httpx.Client() as client:
        response = client.get(f"{no_auth_server}/party/Default", follow_redirects=False)
    assert response.status_code == 302
    assert "/auth/login" in response.headers.get("location", "")

def test_non_admin_cannot_access_admin_features(page: Page, live_server):
    # Use the existing live_server (with TEST_MOCK_AUTH="1")
    # Set bot_owner_id to something else so the mock user 12345 is not admin
    set_bot_owner_id("99999")
    
    page.goto(f"{live_server.url()}/party/Default")
    
    # Try to delete a party (admin feature)
    # The UI might not show the button, but we can try to hit the API directly
    # or check if the button is present.
    # Since I don't see a delete button in the overview, I'll check if I can access an admin-only route.
    # Actually, let's try to access /api/channels which is @require_admin
    
    response = page.request.get(f"{live_server.url()}/api/channels")
    assert response.status == 403