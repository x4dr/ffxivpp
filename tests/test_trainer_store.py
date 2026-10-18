"""Store schema checks that do not need the HTTP layer."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.trainer import store

#: The profiles table before job_id existed. `init()` has to add the column.
OLD_PROFILES = """
CREATE TABLE profiles (
    user_id      TEXT PRIMARY KEY,
    keybind      BLOB,
    keybind_name TEXT,
    hotbar       BLOB,
    hotbar_name  TEXT,
    selection    TEXT NOT NULL DEFAULT '{}',
    bar_order    TEXT NOT NULL DEFAULT '{}',
    taught       TEXT NOT NULL DEFAULT '{}',
    updated_at   TEXT NOT NULL
);
"""


def test_init_adds_job_id_to_an_existing_profiles_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "trainer.db"
    monkeypatch.setenv("TRAINER_DB_PATH", str(path))
    with sqlite3.connect(path) as conn:
        conn.executescript(OLD_PROFILES)

    store.init()

    with sqlite3.connect(path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(profiles)")}
    assert "job_id" in columns


def _attempt(correct: bool, reason: str, latency: int) -> dict[str, object]:
    return {
        "bind": "HOTBAR_1_1",
        "correct": correct,
        "reason": reason,
        "latency_ms": latency,
    }


def test_median_baseline_ignores_wrong_attempts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "trainer.db"
    monkeypatch.setenv("TRAINER_DB_PATH", str(path))
    store.ensure()
    store.save_sessions(
        "u1",
        [
            {
                "client_id": "s1",
                "job_id": None,
                "job_label": None,
                "started_at": "2026-10-18T12:00:00",
                "duration_s": 30,
                "attempts": [
                    _attempt(True, "OK", 100),
                    _attempt(True, "OK", 300),
                    _attempt(True, "OK", 900),
                    _attempt(False, "TIMEOUT", 5000),
                ],
            }
        ],
    )

    assert store.baseline("u1") == 300.0
    assert store.baseline("nobody") == store.DEFAULT_BASELINE_MS
