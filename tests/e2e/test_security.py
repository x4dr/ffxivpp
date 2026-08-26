import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent.parent))

import os
import subprocess
import time

import httpx
import pytest


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
    # (pre-redirect: follow_redirects=False so we assert the 302 itself)
    with httpx.Client() as client:
        response = client.get(f"{no_auth_server}/party/Default", follow_redirects=False)
        admin_response = client.get(f"{no_auth_server}/api/channels", follow_redirects=False)
    assert response.status_code == 302
    assert "/auth/login" in response.headers.get("location", "")
    assert admin_response.status_code == 302
    assert "/auth/login" in admin_response.headers.get("location", "")


@pytest.fixture(scope="session")
def mock_auth_server():
    # Same harness as no_auth_server, but with mock auth ENABLED.
    # The subprocess env is pinned explicitly (TEST_MOCK_AUTH="1") so the
    # server's behaviour cannot depend on fork timing or shell environment.
    # DISCORD_BOT_TOKEN/GUILD_ID are stripped so check_access() can never hit
    # the real Discord API; FLASK_ENV is deliberately NOT "testing" so
    # init_db() leaves bot_owner_id unset and mock user 12345 is non-admin.
    db_path = "test_e2e_mock_auth.db"
    port = 7113
    env = os.environ.copy()
    env["FLASK_APP"] = "app"
    env["DATABASE_PATH"] = db_path
    env["TEST_MOCK_AUTH"] = "1"
    env["PORT"] = str(port)
    env.pop("DISCORD_BOT_TOKEN", None)
    env.pop("GUILD_ID", None)
    env["PYTHONUNBUFFERED"] = "1"

    process = subprocess.Popen(
        [".venv/bin/python3", "app.py"],
        env=env,
        stdout=None,
        stderr=None
    )

    url = f"http://127.0.0.1:{port}"

    try:
        wait_for_server(url)

        yield url
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        for leftover in (db_path, f"{db_path}-wal", f"{db_path}-shm"):
            if os.path.exists(leftover):
                os.remove(leftover)


def test_non_admin_cannot_access_admin_features(mock_auth_server: str):
    # Mock auth authenticates every request as user 12345, who is NOT the bot
    # owner here, so @require_admin must answer 403 directly. Pre-redirect:
    # follow_redirects=False keeps any redirect from masking this assertion.
    with httpx.Client() as client:
        response = client.get(f"{mock_auth_server}/api/channels", follow_redirects=False)
    assert response.status_code == 403
