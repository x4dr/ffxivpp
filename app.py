"""FF14 Party Planner — Flask API server."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from flask import Flask, Response, g, jsonify, request, send_from_directory

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "party.db"
SCHEMA_PATH = BASE_DIR / "schema.sql"


@dataclass(frozen=True)
class Job:
    id: str
    name: str
    role: str
    sub: str


JOBS = [
    Job("pld", "PLD", "tank", "tank"),
    Job("war", "WAR", "tank", "tank"),
    Job("drk", "DRK", "tank", "tank"),
    Job("gnb", "GNB", "tank", "tank"),
    Job("whm", "WHM", "healer", "pure"),
    Job("sch", "SCH", "healer", "shield"),
    Job("ast", "AST", "healer", "pure"),
    Job("sge", "SGE", "healer", "shield"),
    Job("mnk", "MNK", "dps", "melee"),
    Job("drg", "DRG", "dps", "melee"),
    Job("nin", "NIN", "dps", "melee"),
    Job("sam", "SAM", "dps", "melee"),
    Job("vpr", "VPR", "dps", "melee"),
    Job("brd", "BRD", "dps", "pranged"),
    Job("mch", "MCH", "dps", "pranged"),
    Job("dnc", "DNC", "dps", "pranged"),
    Job("blm", "BLM", "dps", "caster"),
    Job("smn", "SMN", "dps", "caster"),
    Job("rdm", "RDM", "dps", "caster"),
    Job("pct", "PCT", "dps", "caster"),
]
JOBS_BY_ID = {j.id: j for j in JOBS}


@dataclass
class Person:
    name: str
    jobs: list[str] = field(default_factory=list)


@dataclass
class Assignment:
    name: str
    job: str
    role: str


@dataclass
class Constraints:
    std_comp: bool = True
    no_dupes: bool = True
    heal_mix: bool = False
    max_melee: int = 4
    max_pranged: int = 4
    max_caster: int = 4
    min_melee: int = 0
    min_pranged: int = 0
    min_caster: int = 0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Constraints:
        return cls(
            std_comp=bool(data.get("std_comp", True)),
            no_dupes=bool(data.get("no_dupes", True)),
            heal_mix=bool(data.get("heal_mix", False)),
            max_melee=int(data.get("max_melee", 4)),
            max_pranged=int(data.get("max_pranged", 4)),
            max_caster=int(data.get("max_caster", 4)),
            min_melee=int(data.get("min_melee", 0)),
            min_pranged=int(data.get("min_pranged", 0)),
            min_caster=int(data.get("min_caster", 0)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "std_comp": self.std_comp,
            "no_dupes": self.no_dupes,
            "heal_mix": self.heal_mix,
            "max_melee": self.max_melee,
            "max_pranged": self.max_pranged,
            "max_caster": self.max_caster,
            "min_melee": self.min_melee,
            "min_pranged": self.min_pranged,
            "min_caster": self.min_caster,
        }


def compute_parties(people: list[Person], constraints: Constraints) -> list[list[Assignment]]:
    results: list[list[Assignment]] = []

    def valid(assignments: list[Job]) -> bool:
        c = constraints
        n_tank = sum(1 for j in assignments if j.role == "tank")
        n_healer = sum(1 for j in assignments if j.role == "healer")
        n_dps = sum(1 for j in assignments if j.role == "dps")
        if c.std_comp and (n_tank != 2 or n_healer != 2 or n_dps != 4):
            return False
        if c.no_dupes and len({j.id for j in assignments}) != len(assignments):
            return False
        if c.heal_mix:
            pure = sum(1 for j in assignments if j.sub == "pure")
            shield = sum(1 for j in assignments if j.sub == "shield")
            if pure != 1 or shield != 1:
                return False
        n_melee = sum(1 for j in assignments if j.sub == "melee")
        n_pranged = sum(1 for j in assignments if j.sub == "pranged")
        n_caster = sum(1 for j in assignments if j.sub == "caster")
        return (
            c.min_melee <= n_melee <= c.max_melee
            and c.min_pranged <= n_pranged <= c.max_pranged
            and c.min_caster <= n_caster <= c.max_caster
        )

    def dfs(idx: int, assigned: list[Job]) -> None:
        if idx == len(people):
            if valid(assigned):
                results.append([
                    Assignment(name=people[i].name, job=j.name, role=j.role)
                    for i, j in enumerate(assigned)
                ])
            return
        p = people[idx]
        if not p.jobs:
            return
        for jid in p.jobs:
            job = JOBS_BY_ID.get(jid)
            if job is None:
                continue
            assigned.append(job)
            dfs(idx + 1, assigned)
            assigned.pop()

    dfs(0, [])
    return results


# ── Database helpers ──────────────────────────────────────────────────


def _init_db() -> None:
    with open(SCHEMA_PATH) as f:
        get_db().executescript(f.read())
    get_db().commit()


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = sqlite3.connect(str(DB_PATH))
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL")
    return g.db


def close_db(_e: Any = None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def _people_from_db() -> list[dict[str, Any]]:
    rows = get_db().execute("SELECT name, jobs FROM people").fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append({"name": r["name"], "jobs": [j for j in r["jobs"].split(",") if j]})
    return out


def _people_to_db(data: list[dict[str, Any]]) -> None:
    db = get_db()
    db.execute("DELETE FROM people")
    for entry in data:
        name = entry.get("name", "")
        jobs = ",".join(entry.get("jobs", []))
        db.execute("INSERT INTO people (name, jobs) VALUES (?, ?)", (name, jobs))
    db.commit()


def _constraints_from_db() -> dict[str, Any]:
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
    return out


def _constraints_to_db(data: dict[str, Any]) -> None:
    db = get_db()
    for k, v in data.items():
        store = str(v).lower() if isinstance(v, bool) else str(v)
        db.execute(
            "INSERT OR REPLACE INTO constraint_config (id, value) VALUES (?, ?)",
            (k, store),
        )
    db.commit()


# ── Flask app ─────────────────────────────────────────────────────────

app = Flask(__name__)
app.teardown_appcontext(close_db)

with app.app_context():
    if not DB_PATH.exists():
        _init_db()


@app.route("/api/jobs")
def api_jobs() -> Response:
    return jsonify([{"id": j.id, "name": j.name, "role": j.role, "sub": j.sub} for j in JOBS])


@app.route("/api/people", methods=["GET", "POST"])
def api_people() -> Response:
    if request.method == "GET":
        return jsonify(_people_from_db())
    data = request.get_json(force=True)
    if not isinstance(data, list):
        return jsonify({"error": "expected array of {name, jobs}"}), 400
    _people_to_db(data)
    return jsonify({"ok": True})


@app.route("/api/constraints", methods=["GET", "PUT"])
def api_constraints() -> Response:
    if request.method == "GET":
        return jsonify(_constraints_from_db())
    data = request.get_json(force=True)
    if not isinstance(data, dict):
        return jsonify({"error": "expected object"}), 400
    _constraints_to_db(data)
    return jsonify({"ok": True})


@app.route("/api/compute", methods=["POST"])
def api_compute() -> Response:
    raw = _people_from_db()
    if not raw:
        return jsonify({"error": "no people configured"}), 400
    people = [Person(p["name"], p["jobs"]) for p in raw]
    constraints = Constraints.from_dict(_constraints_from_db())
    parties = compute_parties(people, constraints)
    return jsonify({
        "count": len(parties),
        "parties": [
            [{"name": a.name, "job": a.job, "role": a.role} for a in party]
            for party in parties[:2000]
        ],
    })


@app.route("/admin")
def admin() -> Response:
    return send_from_directory("static", "admin.html")


@app.route("/")
def index() -> Response:
    return '<a href="/admin">Go to Admin</a>'


def main() -> None:
    app.run(host="0.0.0.0", port=8080, debug=True)


if __name__ == "__main__":
    main()
