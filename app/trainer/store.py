"""Per-user storage for the keybind trainer.

A separate SQLite file from the party/quest database: the trainer is public and
optional, its writes should not travel through the party engine's sessions, and
a reset of one should not touch the other. Every row is keyed by Discord user
id, so one member's uploads, bar choice and history cannot reach another's.
"""

from __future__ import annotations

import json
import os
import sqlite3
import statistics
import time
from contextlib import closing
from pathlib import Path
from typing import Any

from app.db import BASE_DIR

# Latency a session falls back on before there is any history to compare to.
DEFAULT_BASELINE_MS = 700.0

SCHEMA = """
CREATE TABLE IF NOT EXISTS profiles (
    user_id      TEXT PRIMARY KEY,
    keybind      BLOB,
    keybind_name TEXT,
    hotbar       BLOB,
    hotbar_name  TEXT,
    job_id       INTEGER,
    selection    TEXT NOT NULL DEFAULT '{}',
    bar_order    TEXT NOT NULL DEFAULT '{}',
    taught       TEXT NOT NULL DEFAULT '{}',
    updated_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id          INTEGER PRIMARY KEY,
    user_id     TEXT    NOT NULL,
    client_id   TEXT    NOT NULL,
    job_id      INTEGER,
    job_label   TEXT,
    started_at  TEXT    NOT NULL,
    duration_s  REAL    NOT NULL,
    saved_at    TEXT    NOT NULL,
    UNIQUE (user_id, client_id)
);

CREATE TABLE IF NOT EXISTS attempts (
    id           INTEGER PRIMARY KEY,
    session_id   INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    bind         TEXT    NOT NULL,
    name         TEXT,
    label        TEXT,
    correct      INTEGER NOT NULL,
    reason       TEXT    NOT NULL,
    latency_ms   INTEGER,
    pressed_code TEXT,
    pressed_mods TEXT,
    at           TEXT
);

CREATE INDEX IF NOT EXISTS attempts_by_session ON attempts(session_id);
CREATE INDEX IF NOT EXISTS sessions_by_user ON sessions(user_id);
"""


def db_path() -> Path:
    """Where the trainer keeps its own SQLite file.

    TRAINER_DB_PATH exists so tests (and a deployment that wants the data
    elsewhere) do not have to write into the source tree.
    """
    override = os.environ.get("TRAINER_DB_PATH")
    if override:
        return Path(override).expanduser()
    return BASE_DIR / "data" / "trainer.db"


def connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init() -> None:
    with closing(connect()) as conn, conn:
        conn.executescript(SCHEMA)
        # CREATE TABLE IF NOT EXISTS never adds a column to a table that
        # already exists, so new columns need their own step.
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(profiles)")}
        if "job_id" not in columns:
            try:
                conn.execute("ALTER TABLE profiles ADD COLUMN job_id INTEGER")
            except sqlite3.OperationalError:
                # Another worker added it between the check and the ALTER.
                pass


_initialized: Path | None = None


def ensure() -> None:
    """Create the tables once per database path.

    Called by the endpoints instead of at import time so a test that points
    TRAINER_DB_PATH at a temp file gets its own schema, and importing the app
    never writes to the real one.
    """
    global _initialized
    path = db_path()
    if _initialized != path:
        init()
        _initialized = path


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


# --------------------------------------------------------------- profiles


def save_profile(
    user_id: str,
    *,
    keybind: bytes | None,
    keybind_name: str | None,
    hotbar: bytes | None,
    hotbar_name: str | None,
    job_id: int | None,
    selection: dict[str, Any],
    bar_order: dict[str, Any],
    taught: dict[str, Any],
) -> None:
    """Upsert the user's saved copy.

    Files that were not sent this time keep their previous value, so saving a
    session without re-uploading the DATs cannot wipe the layout.
    """
    with closing(connect()) as conn, conn:
        conn.execute(
            """INSERT INTO profiles
                   (user_id, keybind, keybind_name, hotbar, hotbar_name,
                    job_id, selection, bar_order, taught, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(user_id) DO UPDATE SET
                   keybind      = COALESCE(excluded.keybind, profiles.keybind),
                   keybind_name = COALESCE(excluded.keybind_name, profiles.keybind_name),
                   hotbar       = COALESCE(excluded.hotbar, profiles.hotbar),
                   hotbar_name  = COALESCE(excluded.hotbar_name, profiles.hotbar_name),
                   job_id       = COALESCE(excluded.job_id, profiles.job_id),
                   selection    = excluded.selection,
                   bar_order    = excluded.bar_order,
                   taught       = excluded.taught,
                   updated_at   = excluded.updated_at""",
            (
                user_id,
                keybind,
                keybind_name,
                hotbar,
                hotbar_name,
                job_id,
                json.dumps(selection),
                json.dumps(bar_order),
                json.dumps(taught),
                now(),
            ),
        )


def load_profile(user_id: str) -> sqlite3.Row | None:
    with closing(connect()) as conn:
        row: sqlite3.Row | None = conn.execute(
            "SELECT * FROM profiles WHERE user_id = ?", (user_id,)
        ).fetchone()
        return row


# --------------------------------------------------------------- sessions


def save_sessions(user_id: str, sessions: list[dict[str, Any]]) -> int:
    """Insert finished sessions, ignoring client ids already stored.

    Returns how many sessions were new. The client id is the idempotency key,
    so a retry after a flaky connection cannot double-count latency stats.
    """
    saved = 0
    saved_at = now()
    with closing(connect()) as conn, conn:
        for session in sessions:
            cur = conn.execute(
                """INSERT OR IGNORE INTO sessions
                       (user_id, client_id, job_id, job_label, started_at,
                        duration_s, saved_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (
                    user_id,
                    session["client_id"],
                    session.get("job_id"),
                    session.get("job_label"),
                    session["started_at"],
                    session["duration_s"],
                    saved_at,
                ),
            )
            if cur.rowcount == 0:
                continue
            session_id = cur.lastrowid
            conn.executemany(
                """INSERT INTO attempts
                       (session_id, bind, name, label, correct, reason,
                        latency_ms, pressed_code, pressed_mods, at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                [
                    (
                        session_id,
                        attempt["bind"],
                        attempt.get("name"),
                        attempt.get("label"),
                        int(bool(attempt.get("correct"))),
                        attempt["reason"],
                        attempt.get("latency_ms"),
                        attempt.get("pressed_code"),
                        json.dumps(attempt.get("pressed_mods") or []),
                        attempt.get("at"),
                    )
                    for attempt in session.get("attempts", [])
                ],
            )
            saved += 1
    return saved


def stats(user_id: str) -> dict[str, dict[str, Any]]:
    """Lifetime per-bind counters for one user, in the client's shape."""
    with closing(connect()) as conn:
        rows = conn.execute(
            """SELECT a.bind AS bind,
                      COUNT(*) AS attempts,
                      SUM(CASE WHEN a.correct = 1 THEN 1 ELSE 0 END) AS correct,
                      SUM(CASE WHEN a.correct = 0 THEN 1 ELSE 0 END) AS errors,
                      AVG(CASE WHEN a.correct = 1 THEN a.latency_ms END) AS avg_latency
               FROM attempts a JOIN sessions s ON s.id = a.session_id
               WHERE s.user_id = ?
               GROUP BY a.bind""",
            (user_id,),
        ).fetchall()
    return {
        str(row["bind"]): {
            "attempts": int(row["attempts"] or 0),
            "correct": int(row["correct"] or 0),
            "errors": int(row["errors"] or 0),
            "avg_latency": row["avg_latency"],
        }
        for row in rows
    }


def baseline(user_id: str) -> float:
    """Median latency over this user's correct attempts.

    The PoC said median in its docstring and computed AVG in SQL; the card
    weighting wants a target that one slow outlier cannot drag, so this is the
    median it always claimed to be.
    """
    with closing(connect()) as conn:
        rows = conn.execute(
            """SELECT a.latency_ms AS latency
               FROM attempts a JOIN sessions s ON s.id = a.session_id
               WHERE s.user_id = ? AND a.correct = 1 AND a.latency_ms IS NOT NULL""",
            (user_id,),
        ).fetchall()
    values = [float(row["latency"]) for row in rows]
    if not values:
        return DEFAULT_BASELINE_MS
    return max(150.0, float(statistics.median(values)))


def last_session(user_id: str) -> dict[str, Any] | None:
    """The most recent finished session with its attempts.

    The client recomputes the scorecard, so the server does not duplicate the
    scoring rules.
    """
    with closing(connect()) as conn:
        session = conn.execute(
            "SELECT * FROM sessions WHERE user_id = ? ORDER BY id DESC LIMIT 1",
            (user_id,),
        ).fetchone()
        if session is None:
            return None
        rows = conn.execute(
            """SELECT bind, name, label, correct, reason, latency_ms,
                      pressed_code, pressed_mods, at
               FROM attempts WHERE session_id = ? ORDER BY id""",
            (session["id"],),
        ).fetchall()

    attempts = []
    for row in rows:
        attempt = dict(row)
        attempt["correct"] = bool(attempt["correct"])
        attempt["pressed_mods"] = json.loads(attempt["pressed_mods"] or "[]")
        attempts.append(attempt)

    return {
        "job_id": session["job_id"],
        "job_label": session["job_label"],
        "started_at": session["started_at"],
        "duration_s": session["duration_s"],
        "attempts": attempts,
    }
