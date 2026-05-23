from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Generator
from pathlib import Path

from flask import (
    Blueprint,
    Response,
    jsonify,
    make_response,
    request,
    send_from_directory,
    stream_with_context,
)

from app.auth import get_discord, require_admin
from app.compute import JOBS, compute_parties, compute_parties_stream
from app.db import constraints_from_db, constraints_to_db, people_from_db, people_to_db
from app.models import Constraints, Person

bp = Blueprint("api", __name__)
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@bp.route("/api/me")
def api_me() -> Response:
    from app.auth import _bot_api, _guild_id

    discord_obj = get_discord()
    if not discord_obj.authorized:
        return make_response(jsonify({"error": "not authenticated"}), 401)
    user = discord_obj.fetch_user()
    user_id = str(user.id)
    guild_id = _guild_id()
    name = user._payload.get("global_name") or user.name  # fallback

    if guild_id:
        member = _bot_api("GET", f"/guilds/{guild_id}/members/{user_id}")
        if member:
            name = member.get("nick") or member.get("user", {}).get("global_name") or name

    return jsonify({"id": user_id, "name": name, "avatar": user.avatar_url})


@bp.route("/api/jobs")
def api_jobs() -> Response:
    return jsonify([{"id": j.id, "name": j.name, "role": j.role, "sub": j.sub, "dps_type": j.dps_type} for j in JOBS])


@bp.route("/api/people", methods=["GET", "POST"])
def api_people() -> Response:
    if request.method == "GET":
        return jsonify(people_from_db())
    data = request.get_json(force=True)
    if not isinstance(data, list):
        return make_response(jsonify({"error": "expected array of {name, jobs}"}), 400)
    people_to_db(data)
    return jsonify({"ok": True})


@bp.route("/api/constraints", methods=["GET", "PUT"])
def api_constraints() -> Response:
    if request.method == "GET":
        return jsonify(constraints_from_db())
    data = request.get_json(force=True)
    if not isinstance(data, dict):
        return make_response(jsonify({"error": "expected object"}), 400)
    constraints_to_db(data)
    return jsonify({"ok": True})


@bp.route("/api/exclusions", methods=["GET", "PUT"])
def api_exclusions() -> Response:
    from app.db import get_db

    if request.method == "GET":
        rows = get_db().execute("SELECT jobs FROM exclusions ORDER BY id").fetchall()
        return jsonify([r["jobs"].split(",") for r in rows])
    data = request.get_json(force=True)
    if not isinstance(data, list):
        return make_response(jsonify({"error": "expected array"}), 400)
    db = get_db()
    db.execute("DELETE FROM exclusions")
    for group in data:
        if isinstance(group, list) and group:
            db.execute("INSERT INTO exclusions (jobs) VALUES (?)", (",".join(group),))
    db.commit()
    return jsonify({"ok": True})


@bp.route("/api/compute", methods=["POST"])
def api_compute() -> Response:
    raw = people_from_db()
    if not raw:
        return make_response(jsonify({"error": "no people configured"}), 400)
    people = [Person(p["name"], p["jobs"]) for p in raw]
    constraints = Constraints.from_dict(constraints_from_db())
    parties = compute_parties(people, constraints)
    return jsonify({
        "count": len(parties),
        "parties": [
            [{"name": a.name, "job": a.job, "role": a.role} for a in party]
            for party in parties[:2000]
        ],
    })


REPO_DIR = Path(__file__).resolve().parent.parent


@bp.route("/api/channels")
def api_channels() -> Response:
    from app.auth import _bot_api, _guild_id

    guild_id = _guild_id()
    if not guild_id:
        return make_response(jsonify({"error": "no guild configured"}), 400)
    data = _bot_api("GET", f"/guilds/{guild_id}/channels")
    if not data:
        return make_response(jsonify({"error": "failed to fetch channels"}), 500)
    channels = [
        {"id": c["id"], "name": c["name"]}
        for c in data if c.get("type") == 0
    ]
    return jsonify(channels)


@bp.route("/api/polls", methods=["POST"])
def api_polls() -> Response:
    from app.auth import _bot_api

    body = request.get_json(force=True)
    channel_id = body.get("channel_id")
    parties = body.get("parties", [])
    if not channel_id or not parties:
        return make_response(jsonify({"error": "channel_id and parties required"}), 400)
    if len(parties) > 10:
        return make_response(jsonify({"error": "max 10 parties per poll"}), 400)

    answers = []
    for i, party in enumerate(parties):
        job_strs = [m["job"] for m in party["members"]]
        answers.append({
            "poll_media": {"text": f"Party {i + 1}: {' / '.join(job_strs)}"},
        })

    payload = {
        "poll": {
            "question": {"text": "Which party composition?"},
            "answers": answers,
            "duration": 24,
            "allow_multiselect": False,
            "layout_type": 1,
        },
    }

    result = _bot_api("POST", f"/channels/{channel_id}/messages", payload)
    if result:
        return jsonify({"ok": True})
    return make_response(jsonify({"error": "failed to post poll"}), 500)


@bp.route("/webhook/deploy", methods=["POST"])
def webhook_deploy() -> Response:
    secret = request.headers.get("X-Deploy-Secret", "")
    expected = os.environ.get("DEPLOY_SECRET", "")
    if not expected or secret != expected:
        return make_response(jsonify({"error": "unauthorized"}), 401)

    logs: list[str] = []
    try:
        result = subprocess.run(
            ["git", "pull"],
            capture_output=True, text=True, timeout=60, cwd=REPO_DIR,
        )
        logs.append(f"git pull: {result.stdout.strip()}")
        if result.returncode != 0:
            logs.append(f"stderr: {result.stderr.strip()}")
            return jsonify({"ok": False, "logs": logs})
    except subprocess.TimeoutExpired:
        return jsonify({"ok": False, "logs": [*logs, "git pull timed out"]})

    for svc in ("ffxiv-flask", "ffxiv-bot"):
        try:
            subprocess.run(
                ["sudo", "systemctl", "restart", svc],
                capture_output=True, text=True, timeout=30,
            )
            logs.append(f"{svc} restarted")
        except subprocess.TimeoutExpired:
            logs.append(f"{svc} restart timed out")

    return jsonify({"ok": True, "logs": logs})


@bp.route("/admin")
@require_admin
def admin() -> Response:
    return send_from_directory(str(STATIC_DIR), "admin.html")


@bp.route("/")
def index() -> Response:
    return make_response('<a href="/admin">Go to Admin</a>')
