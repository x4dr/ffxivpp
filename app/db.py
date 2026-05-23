from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any, cast

from flask import g, has_app_context

BASE_DIR = Path(__file__).resolve().parent.parent
SCHEMA_PATH = BASE_DIR / "schema.sql"


def _db_path() -> str:
    return os.environ.get("DATABASE_PATH", str(BASE_DIR / "party.db"))


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def get_db() -> sqlite3.Connection:
    if has_app_context():
        if "db" not in g:
            g.db = _connect()
        return cast(sqlite3.Connection, g.db)
    return _connect()


def close_db(_e: Any = None) -> None:
    if has_app_context():
        db = g.pop("db", None)
        if db is not None:
            db.close()


def init_db() -> None:
    with open(SCHEMA_PATH) as f:
        get_db().executescript(f.read())
    for migration in (
        "ALTER TABLE people ADD COLUMN discord_id TEXT",
        "CREATE TABLE IF NOT EXISTS exclusions (id INTEGER PRIMARY KEY AUTOINCREMENT, jobs TEXT NOT NULL)",
    ):
        try:
            get_db().execute(migration)
        except sqlite3.OperationalError:
            pass
    get_db().commit()


def people_from_db() -> list[dict[str, Any]]:
    rows = get_db().execute("SELECT name, jobs, discord_id FROM people").fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append({
            "name": r["name"],
            "jobs": [j for j in r["jobs"].split(",") if j],
            "discord_id": r["discord_id"],
        })
    return out


def people_to_db(data: list[dict[str, Any]]) -> None:
    db = get_db()
    db.execute("DELETE FROM people")
    for entry in data:
        name = entry.get("name", "")
        jobs = ",".join(entry.get("jobs", []))
        discord_id = entry.get("discord_id")
        db.execute(
            "INSERT INTO people (name, jobs, discord_id) VALUES (?, ?, ?)",
            (name, jobs, discord_id),
        )
    db.commit()


def constraints_from_db() -> dict[str, Any]:
    rows = get_db().execute("SELECT id, value FROM constraint_config").fetchall()
    out: dict[str, Any] = {}
    for r in rows:
        raw = r["value"].lower()
        if raw == "true":
            out[r["id"]] = True
        elif raw == "false":
            out[r["id"]] = False
        else:
            try:
                out[r["id"]] = int(raw)
            except ValueError:
                out[r["id"]] = raw
    excl_rows = get_db().execute("SELECT jobs FROM exclusions ORDER BY id").fetchall()
    out["exclusions"] = [r["jobs"].split(",") for r in excl_rows]
    return out


def constraints_to_db(data: dict[str, Any]) -> None:
    db = get_db()
    for k, v in data.items():
        store = str(v).lower() if isinstance(v, bool) else str(v)
        db.execute(
            "INSERT OR REPLACE INTO constraint_config (id, value) VALUES (?, ?)",
            (k, store),
        )
    db.commit()


def get_role_ids(guild_id: str) -> set[str]:
    rows = get_db().execute(
        "SELECT role_id FROM admin_roles WHERE guild_id = ?", (guild_id,)
    ).fetchall()
    return {r["role_id"] for r in rows}


def add_role_id(guild_id: str, role_id: str) -> None:
    get_db().execute(
        "INSERT OR IGNORE INTO admin_roles (guild_id, role_id) VALUES (?, ?)",
        (guild_id, role_id),
    )
    get_db().commit()


def remove_role_id(guild_id: str, role_id: str) -> None:
    get_db().execute(
        "DELETE FROM admin_roles WHERE guild_id = ? AND role_id = ?",
        (guild_id, role_id),
    )
    get_db().commit()
