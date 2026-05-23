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
from app.db import (
    active_party_name,
    add_person_to_party,
    constraints_from_db,
    constraints_to_db,
    create_party,
    delete_party,
    get_lodestone_link,
    parties_list,
    people_from_db,
    people_pool,
    people_to_db,
    remove_person_from_party,
    switch_party,
)
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

    party_name = active_party_name()
    if request.method == "GET":
        rows = get_db().execute(
            "SELECT rowid, jobs FROM party_exclusions WHERE party_name = ? ORDER BY rowid",
            (party_name,),
        ).fetchall()
        return jsonify([r["jobs"].split(",") for r in rows])
    data = request.get_json(force=True)
    if not isinstance(data, list):
        return make_response(jsonify({"error": "expected array"}), 400)
    db = get_db()
    db.execute("DELETE FROM party_exclusions WHERE party_name = ?", (party_name,))
    for group in data:
        if isinstance(group, list) and group:
            db.execute("INSERT INTO party_exclusions (party_name, jobs) VALUES (?, ?)", (party_name, ",".join(group)))
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


@bp.route("/api/compute/stream")
def api_compute_stream() -> Response:
    raw = people_from_db()
    if not raw:
        def _noop() -> Generator[str, None, None]:
            yield "event: complete\ndata: " + json.dumps({"found": 0, "parties": []}) + "\n\n"
        return Response(stream_with_context(_noop()), mimetype="text/event-stream")

    people = [Person(p["name"], p["jobs"]) for p in raw]
    constraints = Constraints.from_dict(constraints_from_db())

    def _generate() -> Generator[str, None, None]:
        for event_type, data in compute_parties_stream(people, constraints):
            yield f"event: {event_type}\ndata: {json.dumps(data)}\n\n"

    return Response(stream_with_context(_generate()), mimetype="text/event-stream")


@bp.route("/api/members")
def api_members() -> Response:
    from app.auth import _bot_api, _guild_id

    guild_id = _guild_id()
    if not guild_id:
        return make_response(jsonify({"error": "no guild configured"}), 400)
    data = _bot_api("GET", f"/guilds/{guild_id}/members?limit=1000")
    if not data:
        return make_response(jsonify({"error": "failed to fetch members"}), 500)
    members = [
        {
            "id": m["user"]["id"],
            "name": m.get("nick") or m["user"].get("global_name") or m["user"]["username"],
        }
        for m in data if not m["user"]["bot"]
    ]
    return jsonify(members)


@bp.route("/api/parties", methods=["GET", "POST"])
def api_parties() -> Response:
    if request.method == "GET":
        return jsonify({
            "parties": parties_list(),
            "active": active_party_name(),
        })
    data = request.get_json(force=True)
    name = data.get("name", "").strip()
    if not name:
        return make_response(jsonify({"error": "name required"}), 400)
    create_party(name)
    return jsonify({"ok": True})


@bp.route("/api/parties/switch", methods=["POST"])
def api_parties_switch() -> Response:
    data = request.get_json(force=True)
    name = data.get("name", "").strip()
    if not name:
        return make_response(jsonify({"error": "name required"}), 400)
    switch_party(name)
    return jsonify({"ok": True})


@bp.route("/api/parties/delete", methods=["POST"])
def api_parties_delete() -> Response:
    data = request.get_json(force=True)
    name = data.get("name", "").strip()
    if not name:
        return make_response(jsonify({"error": "name required"}), 400)
    delete_party(name)
    return jsonify({"ok": True})


@bp.route("/api/people-pool")
def api_people_pool() -> Response:
    return jsonify(people_pool())


@bp.route("/api/people-pool/add", methods=["POST"])
def api_people_pool_add() -> Response:
    data = request.get_json(force=True)
    name = data.get("name", "").strip()
    if not name:
        return make_response(jsonify({"error": "name required"}), 400)
    add_person_to_party(name)
    return jsonify({"ok": True})


@bp.route("/api/people-pool/remove", methods=["POST"])
def api_people_pool_remove() -> Response:
    data = request.get_json(force=True)
    name = data.get("name", "").strip()
    if not name:
        return make_response(jsonify({"error": "name required"}), 400)
    remove_person_from_party(name)
    return jsonify({"ok": True})


@bp.route("/api/lodestone/<discord_id>")
def api_lodestone(discord_id: str) -> Response:
    link = get_lodestone_link(discord_id)
    if not link:
        return make_response(jsonify({"error": "no lodestone link"}), 404)
    from app.lodestone import fetch_character

    data = fetch_character(link["lodestone_id"])
    return jsonify(data)


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

    from app.db import get_character_data

    role_emoji = {"tank": "🛡️", "healer": "💚", "dps": "⚔️"}

    embed_fields = []
    for i, party in enumerate(parties):
        members = party.get("members", [])
        name_lines = []
        for m in members:
            # Try to get level
            char = get_character_data(m["name"])
            level = None
            if char:
                # Find the job in the cached character data
                job_map = char.get("jobs", {})
                jid = m["job"].lower()
                if jid in job_map:
                    level = job_map[jid].get("level")
            
            lvl_str = f" (lv.{level})" if level else ""
            name_lines.append(f"{role_emoji.get(m['role'], '▪')} **{m['name']}**{lvl_str} — {m['job']}")

        embed_fields.append({
            "name": f"Party {i + 1}  —  Score {party.get('score', '?')}",
            "value": "\n".join(name_lines),
            "inline": True,
        })

    embed = {
        "title": "Party Composition Vote",
        "color": 0x4a9eff,
        "fields": embed_fields,
    }

    answers = []
    for i, party in enumerate(parties):
        job_strs = [m["job"] for m in party.get("members", [])]
        score = party.get("score", "?")
        answers.append({
            "poll_media": {"text": f"Party {i + 1} [Score {score}] — {' / '.join(job_strs)}"},
        })

    payload = {
        "embeds": [embed],
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
