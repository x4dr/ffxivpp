"""End-to-end auth behaviour against a real server process.

The subprocess needs the same secrets and database setup the app expects in
production, but CI has no `.env`. Everything is supplied explicitly here so the
tests cannot depend on the developer's environment.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
SECRET = "test-secret-key"


def wait_for_server(url: str) -> None:
    with httpx.Client(timeout=0.5) as client:
        for _ in range(10):
            try:
                client.get(url)
                break
            except httpx.ConnectError:
                time.sleep(1)
        else:
            raise RuntimeError(f"Server did not start at {url}")


def _start(env: dict[str, str]) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [sys.executable, "app.py"],
        cwd=ROOT,
        env=env,
    )


def _stop(process: subprocess.Popen[bytes]) -> None:
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


@pytest.fixture(scope="session")
def no_auth_server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    port = 7112
    db_path = tmp_path_factory.mktemp("e2e_no_auth") / "server.db"

    env = os.environ.copy()
    env.update(
        {
            "FLASK_APP": "app",
            "FLASK_ENV": "testing",
            "PYTHONUNBUFFERED": "1",
            "DATABASE_PATH": str(db_path),
            "TEST_MOCK_AUTH": "0",
            "PORT": str(port),
            "FLASK_SECRET_KEY": SECRET,
        }
    )

    process = _start(env)
    url = f"http://127.0.0.1:{port}"
    try:
        wait_for_server(url)
        yield url
    finally:
        _stop(process)


def test_unauthenticated_redirect(no_auth_server: str) -> None:
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
def mock_auth_server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    # Same harness as no_auth_server, but with mock auth ENABLED.
    # DISCORD_BOT_TOKEN/GUILD_ID are stripped so check_access() can never hit
    # the real Discord API; FLASK_ENV is deliberately NOT "testing" so init_db()
    # leaves bot_owner_id unset and mock user 12345 is non-admin.
    port = 7113
    db_path = tmp_path_factory.mktemp("e2e_mock_auth") / "server.db"

    env = os.environ.copy()
    env.update(
        {
            "FLASK_APP": "app",
            "PYTHONUNBUFFERED": "1",
            "DATABASE_PATH": str(db_path),
            "TEST_MOCK_AUTH": "1",
            "PORT": str(port),
            "FLASK_SECRET_KEY": SECRET,
        }
    )
    env.pop("FLASK_ENV", None)
    env.pop("DISCORD_BOT_TOKEN", None)
    env.pop("GUILD_ID", None)

    process = _start(env)
    url = f"http://127.0.0.1:{port}"
    try:
        wait_for_server(url)
        yield url
    finally:
        _stop(process)


def test_non_admin_cannot_access_admin_features(mock_auth_server: str) -> None:
    # Mock auth authenticates every request as user 12345, who is NOT the bot
    # owner here, so @require_admin must answer 403 directly. Pre-redirect:
    # follow_redirects=False keeps any redirect from masking this assertion.
    with httpx.Client() as client:
        response = client.get(f"{mock_auth_server}/api/channels", follow_redirects=False)
    assert response.status_code == 403
