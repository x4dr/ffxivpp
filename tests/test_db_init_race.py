"""Two gunicorn workers booting at once must not race on schema creation.

The failure this guards against is "table quest_pledges already exists": each
worker ran create_all at the same moment and one lost the race. The init lock
makes the second worker wait, then find the schema already complete.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_two_workers_can_boot_at_once(tmp_path: Path) -> None:
    env = os.environ.copy()
    env.update(
        {
            "DATABASE_PATH": str(tmp_path / "race.db"),
            "FLASK_SECRET_KEY": "test-secret-key",
            "FLASK_ENV": "testing",
            "PYTHONUNBUFFERED": "1",
        }
    )
    code = "from app import create_app; create_app({'TESTING': True})"
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", code],
            cwd=ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        for _ in range(2)
    ]

    try:
        outputs = [process.communicate(timeout=4)[0] for process in processes]
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait()

    for process, output in zip(processes, outputs, strict=True):
        assert process.returncode == 0, output
