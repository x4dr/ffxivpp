from __future__ import annotations

import json
import os
import sqlite3
import time
import logging
import contextlib
from pathlib import Path
from typing import Any, cast, Generator

from flask import g, has_app_context

# Configure basic logging for database duration tracking
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Track connection start times by connection ID
_conn_start_times: dict[int, float] = {}

BASE_DIR = Path(__file__).resolve().parent.parent


def _db_path() -> str:
    return os.environ.get("DATABASE_PATH", str(BASE_DIR / "party.db"))


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path(), timeout=3)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    # Set busy timeout to 3 seconds
    conn.execute("PRAGMA busy_timeout = 3000")
    
    # Store start time in global dictionary using connection ID as key
    _conn_start_times[id(conn)] = time.time()
    logger.debug(f"Database connection opened: {id(conn)}")
    return conn


@contextlib.contextmanager
def db_connection() -> Generator[sqlite3.Connection, None, None]:
    conn = _connect()
    try:
        yield conn
    finally:
        close_db(conn=conn)


def get_db() -> sqlite3.Connection:
    if has_app_context():
        if "db" not in g:
            g.db = _connect()
        return cast(sqlite3.Connection, g.db)
    return _connect()


def close_db(e: Any = None, conn: sqlite3.Connection | None = None) -> None:
    if conn is not None:
        start_time = _conn_start_times.pop(id(conn), time.time())
        duration = time.time() - start_time
        if duration > 1.0:
            logger.warning(f"Database connection {id(conn)} held for {duration:.4f}s")
        else:
            logger.debug(f"Database connection {id(conn)} closed after {duration:.4f}s")
        conn.close()
        return

    if has_app_context():
        db = g.pop("db", None)
        if db is not None:
            db.close()
            logger.debug("Flask DB connection closed")


def _table_has_col(table: str, col: str) -> bool:
    cols = get_db().execute(f"PRAGMA table_info({table!r})").fetchall()
    return any(r["name"] == col for r in cols)


def init_db() -> None:
    with db_connection() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS parties (
                name TEXT PRIMARY KEY
            );
            CREATE TABLE IF NOT EXISTS party_constraints (
                party_name TEXT NOT NULL REFERENCES parties(name) ON DELETE CASCADE,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                PRIMARY KEY (party_name, key)
            );
            CREATE TABLE IF NOT EXISTS party_exclusions (
                party_name TEXT NOT NULL REFERENCES parties(name) ON DELETE CASCADE,
                jobs TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS app_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS admin_roles (
                guild_id TEXT NOT NULL,
                role_id TEXT NOT NULL,
                PRIMARY KEY (guild_id, role_id)
            );
            CREATE TABLE IF NOT EXISTS people (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                jobs TEXT NOT NULL DEFAULT '',
                discord_id TEXT
            );
            CREATE TABLE IF NOT EXISTS lodestone_links (
                person_id INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
                lodestone_id TEXT NOT NULL,
                character_name TEXT,
                fetched_at TEXT,
                PRIMARY KEY (person_id, lodestone_id)
            );
            CREATE TABLE IF NOT EXISTS character_cache (
                lodestone_id TEXT PRIMARY KEY,
                data TEXT NOT NULL,
                fetched_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS party_people (
                party_name TEXT NOT NULL REFERENCES parties(name) ON DELETE CASCADE,
                person_name TEXT NOT NULL REFERENCES people(name) ON DELETE CASCADE,
                PRIMARY KEY (party_name, person_name)
            );
            INSERT OR IGNORE INTO parties (name) VALUES ('Default');
            INSERT OR IGNORE INTO app_state (key, value) VALUES ('active_party', 'Default');
        """)
        
        if not _table_has_col("parties", "home_channel_id"):
            db.execute("ALTER TABLE parties ADD COLUMN home_channel_id TEXT")
        if not _table_has_col("parties", "home_message_id"):
            db.execute("ALTER TABLE parties ADD COLUMN home_message_id TEXT")


        default_cfg = [
            ("std_comp", "true"),
            ("no_dupes", "true"),
            ("heal_mix", "false"),
            ("max_melee", "4"),
            ("max_pranged", "4"),
            ("max_caster", "4"),
            ("min_melee", "0"),
            ("min_pranged", "0"),
            ("min_caster", "0"),
            ("min_selfish", "0"),
            ("max_selfish", "4"),
            ("min_utility", "0"),
            ("max_utility", "4"),
        ]
        for k, v in default_cfg:
            db.execute(
                "INSERT OR IGNORE INTO party_constraints (party_name, key, value) VALUES ('Default', ?, ?)",
                (k, v),
            )

        db.commit()


# ── Party management ─────────────────────────────────────────────────────


def active_party_name() -> str:
    with db_connection() as db:
        row = db.execute("SELECT value FROM app_state WHERE key='active_party'").fetchone()
        return row["value"] if row else "Default"


def parties_list() -> list[str]:
    with db_connection() as db:
        rows = db.execute("SELECT name FROM parties ORDER BY name").fetchall()
        return [r["name"] for r in rows]


def get_parties_details() -> list[dict[str, Any]]:
    with db_connection() as db:
        rows = db.execute("SELECT name, home_channel_id FROM parties ORDER BY name").fetchall()
        return [{"name": r["name"], "home_channel_id": r["home_channel_id"]} for r in rows]


def create_party(name: str) -> None:
    with db_connection() as db:
        db.execute("INSERT INTO parties (name) VALUES (?)", (name,))
        cfg_rows = db.execute("SELECT key, value FROM party_constraints WHERE party_name='Default'").fetchall()
        for r in cfg_rows:
            db.execute("INSERT OR REPLACE INTO party_constraints (party_name, key, value) VALUES (?, ?, ?)", (name, r["key"], r["value"]))
        db.commit()


def delete_party(name: str) -> None:
    if name == "Default":
        return
    with db_connection() as db:
        db.execute("DELETE FROM party_people WHERE party_name = ?", (name,))
        db.execute("DELETE FROM party_constraints WHERE party_name = ?", (name,))
        db.execute("DELETE FROM party_exclusions WHERE party_name = ?", (name,))
        db.execute("DELETE FROM parties WHERE name = ?", (name,))
        db.commit()


def switch_party(name: str) -> None:
    with db_connection() as db:
        db.execute("INSERT OR REPLACE INTO app_state (key, value) VALUES ('active_party', ?)", (name,))
        db.commit()


# ── People (per-party) ───────────────────────────────────────────────────


def people_from_db(party_name: str | None = None) -> list[dict[str, Any]]:
    if party_name is None:
        party_name = active_party_name()
    with db_connection() as db:
        rows = db.execute(
            """SELECT p.id, p.name, p.jobs, p.discord_id, l.lodestone_id FROM people p
               JOIN party_people pp ON pp.person_name = p.name
               LEFT JOIN lodestone_links l ON p.id = l.person_id
               WHERE pp.party_name = ?""",
            (party_name,),
        ).fetchall()
        return [
            {"id": r["id"], "name": r["name"], "jobs": [j for j in (r["jobs"] or "").split(",") if j], "discord_id": r["discord_id"], "has_lodestone": r["lodestone_id"] is not None}
            for r in rows
        ]


def people_pool() -> list[dict[str, Any]]:
    with db_connection() as db:
        rows = db.execute("SELECT p.id, p.name, p.jobs, p.discord_id, l.lodestone_id FROM people p LEFT JOIN lodestone_links l ON p.id = l.person_id ORDER BY p.name").fetchall()
        return [
            {"id": r["id"], "name": r["name"], "jobs": [j for j in (r["jobs"] or "").split(",") if j], "discord_id": r["discord_id"], "has_lodestone": r["lodestone_id"] is not None}
            for r in rows
        ]


def people_to_db(data: list[dict[str, Any]], party_name: str | None = None) -> None:
    if party_name is None:
        party_name = active_party_name()
    with db_connection() as db:
        db.execute("DELETE FROM party_people WHERE party_name = ?", (party_name,))
        for entry in data:
            name = entry.get("name", "")
            if not name:
                continue
            jobs = ",".join(entry.get("jobs", []))
            discord_id = entry.get("discord_id")
            db.execute("INSERT OR REPLACE INTO people (name, jobs, discord_id) VALUES (?, ?, ?)", (name, jobs, discord_id))
            db.execute("INSERT OR IGNORE INTO party_people (party_name, person_name) VALUES (?, ?)", (party_name, name))
        db.commit()


def pool_save(data: list[dict[str, Any]]) -> None:
    """Replace the entire people pool (used by bot commands, no party scope)."""
    with db_connection() as db:
        db.execute("DELETE FROM people")
        for entry in data:
            name = entry.get("name", "")
            if not name:
                continue
            jobs = ",".join(entry.get("jobs", []))
            discord_id = entry.get("discord_id")
            db.execute("INSERT INTO people (name, jobs, discord_id) VALUES (?, ?, ?)", (name, jobs, discord_id))
        db.commit()


def add_person_to_party(person_name: str, party_name: str | None = None) -> None:
    if party_name is None:
        party_name = active_party_name()
    with db_connection() as db:
        db.execute("INSERT OR IGNORE INTO party_people (party_name, person_name) VALUES (?, ?)", (party_name, person_name))
        db.commit()


def remove_person_from_party(person_name: str, party_name: str | None = None) -> None:
    if party_name is None:
        party_name = active_party_name()
    with db_connection() as db:
        db.execute("DELETE FROM party_people WHERE party_name = ? AND person_name = ?", (party_name, person_name))
        db.commit()



def get_party_members(party_name: str) -> list[dict[str, Any]]:
    with db_connection() as db:
        rows = db.execute(
            """SELECT p.id, p.name, p.jobs, l.lodestone_id, l.character_name, c.fetched_at 
               FROM people p
               JOIN party_people pp ON pp.person_name = p.name
               LEFT JOIN lodestone_links l ON p.id = l.person_id
               LEFT JOIN character_cache c ON l.lodestone_id = c.lodestone_id
               WHERE pp.party_name = ?""",
            (party_name,),
        ).fetchall()
        return [
            {
                "id": r["id"],
                "name": r["name"],
                "jobs": [j for j in (r["jobs"] or "").split(",") if j],
                "lodestone_id": r["lodestone_id"],
                "character_name": r["character_name"],
                "fetched_at": r["fetched_at"]
            }
            for r in rows
        ]


# ── Constraints (per-party) ──────────────────────────────────────────────


def constraints_from_db(party_name: str | None = None) -> dict[str, Any]:
    if party_name is None:
        party_name = active_party_name()
    with db_connection() as db:
        rows = db.execute(
            "SELECT key, value FROM party_constraints WHERE party_name = ?", (party_name,)
        ).fetchall()
        out: dict[str, Any] = {}
        for r in rows:
            raw = r["value"].lower()
            if raw == "true":
                out[r["key"]] = True
            elif raw == "false":
                out[r["key"]] = False
            else:
                try:
                    out[r["key"]] = int(raw)
                except ValueError:
                    out[r["key"]] = raw
        excl_rows = db.execute(
            "SELECT rowid, jobs FROM party_exclusions WHERE party_name = ? ORDER BY rowid", (party_name,)
        ).fetchall()
        out["exclusions"] = [r["jobs"].split(",") for r in excl_rows]
        return out


def constraints_to_db(data: dict[str, Any], party_name: str | None = None) -> None:
    if party_name is None:
        party_name = active_party_name()
    with db_connection() as db:
        db.execute("DELETE FROM party_constraints WHERE party_name = ?", (party_name,))
        for k, v in data.items():
            if k == "exclusions":
                continue
            store = str(v).lower() if isinstance(v, bool) else str(v)
            db.execute("INSERT INTO party_constraints (party_name, key, value) VALUES (?, ?, ?)", (party_name, k, store))
        db.execute("DELETE FROM party_exclusions WHERE party_name = ?", (party_name,))
        for group in data.get("exclusions", []):
            db.execute("INSERT INTO party_exclusions (party_name, jobs) VALUES (?, ?)", (party_name, ",".join(group)))
        db.commit()


# ── Admin roles ──────────────────────────────────────────────────────────


def get_role_ids(guild_id: str) -> set[str]:
    with db_connection() as db:
        rows = db.execute("SELECT role_id FROM admin_roles WHERE guild_id = ?", (guild_id,)).fetchall()
        return {r["role_id"] for r in rows}


def add_role_id(guild_id: str, role_id: str) -> None:
    with db_connection() as db:
        db.execute("INSERT OR IGNORE INTO admin_roles (guild_id, role_id) VALUES (?, ?)", (guild_id, role_id))
        db.commit()


def remove_role_id(guild_id: str, role_id: str) -> None:
    with db_connection() as db:
        db.execute("DELETE FROM admin_roles WHERE guild_id = ? AND role_id = ?", (guild_id, role_id))
        db.commit()


def bot_owner_id() -> str | None:
    with db_connection() as db:
        row = db.execute("SELECT value FROM app_state WHERE key='bot_owner_id'").fetchone()
        return row["value"] if row else None


def set_lodestone_link(person_id: int, lodestone_id: str, character_name: str | None = None) -> None:
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    with db_connection() as db:
        db.execute(
            "INSERT INTO lodestone_links (person_id, lodestone_id, character_name, fetched_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(person_id, lodestone_id) DO UPDATE SET character_name = excluded.character_name",
            (person_id, lodestone_id, character_name, now),
        )
        db.commit()


def update_lodestone_fetched_at(lodestone_id: str) -> None:
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    with db_connection() as db:
        db.execute(
            "UPDATE lodestone_links SET fetched_at = ? WHERE lodestone_id = ?",
            (now, lodestone_id),
        )
        db.commit()


def get_lodestone_link(person_id: int) -> dict[str, Any] | None:
    with db_connection() as db:
        row = db.execute(
            "SELECT lodestone_id, character_name, fetched_at FROM lodestone_links WHERE person_id = ?",
            (person_id,),
        ).fetchone()
        if not row:
            return None
        return {"lodestone_id": row["lodestone_id"], "character_name": row["character_name"], "fetched_at": row["fetched_at"]}


def cache_character(lodestone_id: str, data: dict[str, Any]) -> None:
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    with db_connection() as db:
        db.execute(
            "INSERT OR REPLACE INTO character_cache (lodestone_id, data, fetched_at) VALUES (?, ?, ?)",
            (lodestone_id, json.dumps(data), now),
        )
        db.commit()


def get_cached_character(lodestone_id: str) -> dict[str, Any] | None:
    with db_connection() as db:
        row = db.execute(
            "SELECT data, fetched_at FROM character_cache WHERE lodestone_id = ?",
            (lodestone_id,),
        ).fetchone()
        if not row:
            return None
        data = json.loads(row["data"])
        data["fetched_at"] = row["fetched_at"]
        return data


def get_character_data(person_name: str) -> dict[str, Any] | None:
    db = get_db()
    row = db.execute(
        """SELECT l.lodestone_id, c.data, l.character_name FROM people p
           JOIN lodestone_links l ON p.id = l.person_id
           JOIN character_cache c ON l.lodestone_id = c.lodestone_id
           WHERE p.name = ?""",
        (person_name,),
    ).fetchone()
    if not has_app_context():
        close_db(conn=db)
    if not row:
        return None
    data = json.loads(row["data"])
    data["character_name"] = row["character_name"]
    return data
