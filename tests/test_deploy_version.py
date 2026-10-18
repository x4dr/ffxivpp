"""The deploy workflow needs a public, read-only way to see what is running."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_version_endpoint_is_public(client) -> None:
    response = client.get("/deploy/version")

    assert response.status_code == 200
    commit = response.get_json()["commit"]
    expected = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    assert commit == expected
