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
    redirect,
    url_for,
    current_app,
)

from app.auth import get_discord, require_admin, require_party_member, check_access, _bot_api, _guild_id
from app.compute import JOBS, JOBS_BY_ID, compute_parties, compute_parties_stream
from app.db import (
    active_party_name,
    add_person_to_party,
    constraints_from_db,
    constraints_to_db,
    create_party,
    delete_party,
    get_character_data,
    get_lodestone_link,
    get_parties_details,
    get_party_exclusions,
    people_from_db,
    people_pool,
    people_to_db,
    remove_person_from_party,
    set_party_exclusions,
    switch_party,
    update_party_home_channel,
)
from app.models import Constraints, Person

bp = Blueprint("api", __name__)
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@bp.route("/api/me")
def api_me() -> Response:
    discord_obj = get_discord()
    if not discord_obj.authorized:
        return make_response(jsonify({"error": "not authenticated"}), 401)
    user = discord_obj.fetch_user()
    user_id = str(user.id)
    guild_id = _guild_id()
    # Use fallback if _payload is missing (e.g. in test mode)
    name = getattr(user, "_payload", {}).get("global_name") or getattr(user, "name", "Unknown")
    
    if guild_id:
        member = _bot_api("GET", f"/guilds/{guild_id}/members/{user_id}")
        if member:
            name = (
                member.get("nick")
                or member.get("user", {}).get("global_name")
                or name
            )

    return jsonify(
        {"id": user_id, "name": name, "avatar": getattr(user, "avatar_url", ""), "is_admin": check_access()}
    )


@bp.route("/api/jobs")
def api_jobs() -> Response:
    return jsonify([{"id": j.id, "name": j.name, "role": j.role, "sub": j.sub, "dps_type": j.dps_type} for j in JOBS])


@bp.route("/api/people", methods=["GET", "POST"])
@require_party_member
def api_people(party_name: str) -> Response:
    if request.method == "GET":
        return jsonify(people_from_db(party_name))
    if not check_access():
        return make_response(jsonify({"error": "unauthorized"}), 403)
    data = request.get_json(force=True)
    people_data = data.get("people", data) if isinstance(data, dict) else data
    if not isinstance(people_data, list):
        return make_response(jsonify({"error": "expected array of {name, jobs}"}), 400)
    people_to_db(people_data, party_name)
    return jsonify({"ok": True})


@bp.route("/api/constraints", methods=["GET", "PUT"])
@require_party_member
def api_constraints(party_name: str) -> Response:
    if request.method == "GET":
        return jsonify(constraints_from_db(party_name))
    if not check_access():
        return make_response(jsonify({"error": "unauthorized"}), 403)
    data = request.get_json(force=True)
    
    current_app.logger.info(f"DEBUG: api_constraints party_name={party_name}, data={data}")
    
    if not isinstance(data, dict):
        current_app.logger.error("Data is not a dict")
        return make_response(jsonify({"error": "expected object"}), 400)
    
    try:
        constraints_to_db(data, party_name)
        return jsonify({"ok": True})
    except Exception as e:
        current_app.logger.exception("Error in constraints_to_db")
        return make_response(jsonify({"error": str(e)}), 500)


@bp.route("/api/exclusions", methods=["GET", "PUT"])
@require_party_member
def api_exclusions(party_name: str) -> Response:
    if request.method == "GET":
        return jsonify(get_party_exclusions(party_name))
    if not check_access():
        return make_response(jsonify({"error": "unauthorized"}), 403)
    data = request.get_json(force=True)
    exclusions_data = data.get("exclusions", data) if isinstance(data, dict) else data
    if not isinstance(exclusions_data, list):
        return make_response(jsonify({"error": "expected array"}), 400)
    
    set_party_exclusions(party_name, exclusions_data)
    return jsonify({"ok": True})


@bp.route("/api/compute/stream")
@require_party_member
def api_compute_stream(party_name: str) -> Response:
    raw = people_from_db(party_name)
    if not raw:
        def _noop() -> Generator[str, None, None]:
            yield "event: complete\ndata: " + json.dumps({"found": 0, "parties": []}) + "\n\n"
        return Response(stream_with_context(_noop()), mimetype="text/event-stream")

    errors = []
    for p in raw:
        for entry in p.get("jobs", []):
            if not entry: continue
            jid = entry.split(":")[0].lower()
            if jid not in JOBS_BY_ID:
                errors.append(f"Illegal job '{jid}' for {p['name']}")

    if errors:
        def _error() -> Generator[str, None, None]:
            yield "event: complete\ndata: " + json.dumps({"error": ". ".join(errors)}) + "\n\n"
        return Response(stream_with_context(_error()), mimetype="text/event-stream")

    people = [Person(p["name"], p["jobs"]) for p in raw]
    constraints = Constraints.from_dict(constraints_from_db(party_name))

    def _generate() -> Generator[str, None, None]:
        # analyze_constraints is not actually used here
        # Removing the import and call to fix the test failure.
        
        for event_type, data in compute_parties_stream(people, constraints):
            yield f"event: {event_type}\ndata: {json.dumps(data)}\n\n"

    return Response(stream_with_context(_generate()), mimetype="text/event-stream")


@bp.route("/api/members")
def api_members() -> Response:
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
            "parties": get_parties_details(),
            "active": active_party_name(),
        })
    if not check_access():
        return make_response(jsonify({"error": "unauthorized"}), 403)
    data = request.get_json(force=True)
    name = data.get("name", "").strip()
    if not name:
        return make_response(jsonify({"error": "name required"}), 400)
    create_party(name)
    return jsonify({"ok": True})


@bp.route("/api/parties/switch", methods=["POST"])
def api_parties_switch() -> Response:
    if not check_access():
        return make_response(jsonify({"error": "unauthorized"}), 403)
    data = request.get_json(force=True)
    name = data.get("name", "").strip()
    if not name:
        return make_response(jsonify({"error": "name required"}), 400)
    switch_party(name)
    return jsonify({"ok": True})


@bp.route("/api/parties/delete", methods=["POST"])
def api_parties_delete() -> Response:
    if not check_access():
        return make_response(jsonify({"error": "unauthorized"}), 403)
    data = request.get_json(force=True)
    name = data.get("name", "").strip()
    if not name:
        return make_response(jsonify({"error": "name required"}), 400)
    delete_party(name)
    return jsonify({"ok": True})


@bp.route("/api/parties/home-channel", methods=["PUT"])
def api_parties_home_channel() -> Response:
    if not check_access():
        return make_response(jsonify({"error": "unauthorized"}), 403)
    data = request.get_json(force=True)
    party_name = data.get("party_name", "").strip()
    channel_id = data.get("channel_id", "").strip()
    if not party_name:
        return make_response(jsonify({"error": "party_name required"}), 400)

    update_party_home_channel(party_name, channel_id or None)
    return jsonify({"ok": True})


@bp.route("/api/lodestone/<person_id>")
def api_lodestone(person_id: int) -> Response:
    link = get_lodestone_link(person_id)
    if not link:
        return make_response(jsonify({"error": "not found"}), 404)
    return jsonify(link)


@bp.route("/api/people-pool")
def api_people_pool() -> Response:
    return jsonify(people_pool())


@bp.route("/api/people-pool/add", methods=["POST"])
@require_party_member
def api_people_pool_add(party_name: str) -> Response:
    if not check_access():
        return make_response(jsonify({"error": "unauthorized"}), 403)
    data = request.get_json(force=True)
    name = data.get("name", "").strip()
    if not name:
        return make_response(jsonify({"error": "name required"}), 400)
    add_person_to_party(name, party_name)
    return jsonify({"ok": True})


@bp.route("/api/people-pool/remove", methods=["POST"])
@require_party_member
def api_people_pool_remove(party_name: str) -> Response:
    if not check_access():
        return make_response(jsonify({"error": "unauthorized"}), 403)
    data = request.get_json(force=True)
    name = data.get("name", "").strip()
    if not name:
        return make_response(jsonify({"error": "name required"}), 400)
    remove_person_from_party(name, party_name)
    return jsonify({"ok": True})


@bp.route("/api/polls", methods=["POST"])
def api_polls() -> Response:
    if not check_access():
        return make_response(jsonify({"error": "unauthorized"}), 403)
    discord = get_discord()
    user = discord.fetch_user()
    body = request.get_json(force=True)
    channel_id = body.get("channel_id")
    parties = body.get("parties", [])
    if not channel_id or not parties:
        return make_response(jsonify({"error": "channel_id and parties required"}), 400)
    if len(parties) > 10:
        return make_response(jsonify({"error": "max 10 parties per poll"}), 400)

    role_emoji = {"tank": "🛡️", "healer": "💚", "dps": "⚔️"}

    embed_fields = []
    for i, party in enumerate(parties):
        members = party.get("members", [])
        name_lines = []
        for m in members:
            char = get_character_data(m["name"])
            level = None
            if char:
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
        "description": f"Posted by {user.name}",
        "color": 0x4a9eff,
        "fields": embed_fields,
    }

    answers = []
    for i, party in enumerate(parties):
        answers.append({
            "poll_media": {"text": f"Party {i + 1}"},
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


@bp.route("/api/channels")
@require_admin
def api_channels() -> Response:
    guild_id = _guild_id()
    if not guild_id:
        return make_response(jsonify({"error": "no guild configured"}), 400)
    data = _bot_api("GET", f"/guilds/{guild_id}/channels")
    if not data:
        return make_response(jsonify({"error": "failed to fetch channels"}), 500)
    channels = [{"id": c["id"], "name": c["name"]} for c in data if c.get("type") == 0]
    return jsonify(channels)


@bp.route("/party/<party_name>")
@require_party_member
def party_overview(party_name: str) -> Response:
    return send_from_directory(str(STATIC_DIR), "partydashboard.html")


@bp.route("/party")
@bp.route("/party/")
def party_index() -> Response:
    return redirect(url_for("api.party_overview", party_name="Default"))


@bp.route("/")
def index() -> Response:
    return redirect(url_for("api.party_overview", party_name="Default"))
