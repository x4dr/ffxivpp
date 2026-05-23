from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any, cast

from flask import g, has_app_context

BASE_DIR = Path(__file__).resolve().parent.parent


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


def _table_has_col(table: str, col: str) -> bool:
    cols = get_db().execute(f"PRAGMA table_info({table!r})").fetchall()
    return any(r["name"] == col for r in cols)


def init_db() -> None:
    db = get_db()

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
        CREATE TABLE IF NOT EXISTS lodestone_links (
            discord_id TEXT NOT NULL,
            lodestone_id TEXT NOT NULL,
            character_name TEXT,
            fetched_at TEXT,
            PRIMARY KEY (discord_id, lodestone_id)
        );
        CREATE TABLE IF NOT EXISTS character_cache (
            lodestone_id TEXT PRIMARY KEY,
            data TEXT NOT NULL,
            fetched_at TEXT NOT NULL
        );
    """)

    needs_migrate = False
    try:
        needs_migrate = _table_has_col("people", "id")
    except sqlite3.OperationalError:
        pass

    if needs_migrate:
        old_rows = db.execute("SELECT name, jobs, discord_id FROM people ORDER BY id").fetchall()
        seen: dict[str, dict[str, Any]] = {}
        for r in old_rows:
            seen[r["name"]] = {"jobs": r["jobs"] or "", "discord_id": r["discord_id"]}

        db.executescript("""
            CREATE TABLE IF NOT EXISTS people_new (
                name TEXT PRIMARY KEY,
                jobs TEXT NOT NULL DEFAULT '',
                discord_id TEXT
            );
        """)
        for name, data in seen.items():
            db.execute(
                "INSERT OR REPLACE INTO people_new (name, jobs, discord_id) VALUES (?, ?, ?)",
                (name, data["jobs"], data["discord_id"]),
            )
        db.execute("DROP TABLE people")
        db.execute("ALTER TABLE people_new RENAME TO people")
        db.execute("""
            CREATE TABLE IF NOT EXISTS party_people (
                party_name TEXT NOT NULL REFERENCES parties(name) ON DELETE CASCADE,
                person_name TEXT NOT NULL REFERENCES people(name) ON DELETE CASCADE,
                PRIMARY KEY (party_name, person_name)
            )
        """)
        db.execute("INSERT OR IGNORE INTO parties (name) VALUES ('Default')")
        for name in seen:
            db.execute(
                "INSERT OR IGNORE INTO party_people (party_name, person_name) VALUES ('Default', ?)",
                (name,),
            )
        for r in db.execute("SELECT id, value FROM constraint_config").fetchall():
            db.execute(
                "INSERT OR REPLACE INTO party_constraints (party_name, key, value) VALUES ('Default', ?, ?)",
                (r["id"], r["value"]),
            )
        for r in db.execute("SELECT jobs FROM exclusions").fetchall():
            db.execute(
                "INSERT INTO party_exclusions (party_name, jobs) VALUES ('Default', ?)",
                (r["jobs"],),
            )
        db.execute("INSERT OR REPLACE INTO app_state (key, value) VALUES ('active_party', 'Default')")
    else:
        db.execute("""
            CREATE TABLE IF NOT EXISTS party_people (
                party_name TEXT NOT NULL REFERENCES parties(name) ON DELETE CASCADE,
                person_name TEXT NOT NULL REFERENCES people(name) ON DELETE CASCADE,
                PRIMARY KEY (party_name, person_name)
            )
        """)
        try:
            db.execute("CREATE TABLE IF NOT EXISTS people (name TEXT PRIMARY KEY, jobs TEXT NOT NULL DEFAULT '', discord_id TEXT)")
        except sqlite3.OperationalError:
            pass
        db.execute("INSERT OR IGNORE INTO parties (name) VALUES ('Default')")
        db.execute("INSERT OR IGNORE INTO app_state (key, value) VALUES ('active_party', 'Default')")

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
    row = get_db().execute("SELECT value FROM app_state WHERE key='active_party'").fetchone()
    return row["value"] if row else "Default"


def parties_list() -> list[str]:
    rows = get_db().execute("SELECT name FROM parties ORDER BY name").fetchall()
    return [r["name"] for r in rows]


def create_party(name: str) -> None:
    db = get_db()
    db.execute("INSERT INTO parties (name) VALUES (?)", (name,))
    cfg_rows = db.execute("SELECT key, value FROM party_constraints WHERE party_name='Default'").fetchall()
    for r in cfg_rows:
        db.execute("INSERT OR REPLACE INTO party_constraints (party_name, key, value) VALUES (?, ?, ?)", (name, r["key"], r["value"]))
    db.commit()


def delete_party(name: str) -> None:
    if name == "Default":
        return
    db = get_db()
    db.execute("DELETE FROM party_people WHERE party_name = ?", (name,))
    db.execute("DELETE FROM party_constraints WHERE party_name = ?", (name,))
    db.execute("DELETE FROM party_exclusions WHERE party_name = ?", (name,))
    db.execute("DELETE FROM parties WHERE name = ?", (name,))
    db.commit()


def switch_party(name: str) -> None:
    db = get_db()
    db.execute("INSERT OR REPLACE INTO app_state (key, value) VALUES ('active_party', ?)", (name,))
    db.commit()


# ── People (per-party) ───────────────────────────────────────────────────


def people_from_db(party_name: str | None = None) -> list[dict[str, Any]]:
    if party_name is None:
        party_name = active_party_name()
    rows = get_db().execute(
        """SELECT p.name, p.jobs, p.discord_id FROM people p
           JOIN party_people pp ON pp.person_name = p.name
           WHERE pp.party_name = ?""",
        (party_name,),
    ).fetchall()
    return [
        {"name": r["name"], "jobs": [j for j in (r["jobs"] or "").split(",") if j], "discord_id": r["discord_id"]}
        for r in rows
    ]


def people_to_db(data: list[dict[str, Any]], party_name: str | None = None) -> None:
    if party_name is None:
        party_name = active_party_name()
    db = get_db()
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


# ── People pool (global) ─────────────────────────────────────────────────


def people_pool() -> list[dict[str, Any]]:
    rows = get_db().execute("SELECT name, jobs, discord_id FROM people ORDER BY name").fetchall()
    return [
        {"name": r["name"], "jobs": [j for j in (r["jobs"] or "").split(",") if j], "discord_id": r["discord_id"]}
        for r in rows
    ]


def pool_save(data: list[dict[str, Any]]) -> None:
    """Replace the entire people pool (used by bot commands, no party scope)."""
    db = get_db()
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
    get_db().execute("INSERT OR IGNORE INTO party_people (party_name, person_name) VALUES (?, ?)", (party_name, person_name))
    get_db().commit()


def remove_person_from_party(person_name: str, party_name: str | None = None) -> None:
    if party_name is None:
        party_name = active_party_name()
    get_db().execute("DELETE FROM party_people WHERE party_name = ? AND person_name = ?", (party_name, person_name))
    get_db().commit()


# ── Constraints (per-party) ──────────────────────────────────────────────


def constraints_from_db(party_name: str | None = None) -> dict[str, Any]:
    if party_name is None:
        party_name = active_party_name()
    rows = get_db().execute(
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
    excl_rows = get_db().execute(
        "SELECT rowid, jobs FROM party_exclusions WHERE party_name = ? ORDER BY rowid", (party_name,)
    ).fetchall()
    out["exclusions"] = [r["jobs"].split(",") for r in excl_rows]
    return out


def constraints_to_db(data: dict[str, Any], party_name: str | None = None) -> None:
    if party_name is None:
        party_name = active_party_name()
    db = get_db()
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
    rows = get_db().execute("SELECT role_id FROM admin_roles WHERE guild_id = ?", (guild_id,)).fetchall()
    return {r["role_id"] for r in rows}


def add_role_id(guild_id: str, role_id: str) -> None:
    get_db().execute("INSERT OR IGNORE INTO admin_roles (guild_id, role_id) VALUES (?, ?)", (guild_id, role_id))
    get_db().commit()


def remove_role_id(guild_id: str, role_id: str) -> None:
    get_db().execute("DELETE FROM admin_roles WHERE guild_id = ? AND role_id = ?", (guild_id, role_id))
    get_db().commit()


# ── Bot owner ─────────────────────────────────────────────────────────────


def bot_owner_id() -> str | None:
    row = get_db().execute("SELECT value FROM app_state WHERE key='bot_owner_id'").fetchone()
    return row["value"] if row else None


# ── Lodestone ─────────────────────────────────────────────────────────────


def set_lodestone_link(discord_id: str, lodestone_id: str, character_name: str | None = None) -> None:
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    get_db().execute(
        "INSERT OR REPLACE INTO lodestone_links (discord_id, lodestone_id, character_name, fetched_at) VALUES (?, ?, ?, ?)",
        (discord_id, lodestone_id, character_name, now),
    )
    get_db().commit()


def get_lodestone_link(discord_id: str) -> dict[str, Any] | None:
    row = get_db().execute(
        "SELECT lodestone_id, character_name, fetched_at FROM lodestone_links WHERE discord_id = ?",
        (discord_id,),
    ).fetchone()
    if not row:
        return None
    return {"lodestone_id": row["lodestone_id"], "character_name": row["character_name"], "fetched_at": row["fetched_at"]}


def cache_character(lodestone_id: str, data: dict[str, Any]) -> None:
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    get_db().execute(
        "INSERT OR REPLACE INTO character_cache (lodestone_id, data, fetched_at) VALUES (?, ?, ?)",
        (lodestone_id, json.dumps(data), now),
    )
    get_db().commit()


def get_cached_character(lodestone_id: str) -> dict[str, Any] | None:
    row = get_db().execute(
        "SELECT data, fetched_at FROM character_cache WHERE lodestone_id = ?",
        (lodestone_id,),
    ).fetchone()
    if not row:
        return None
    return json.loads(row["data"])
