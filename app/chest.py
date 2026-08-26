"""Chest snapshot ingestion: shared-secret API + diff/suggestion records.

Accepts normalized snapshots ({source, items: [{item_id|name, qty}]}) from the
watcher script, manual paste, or (later) the plugin. Never touches quest
state: diffs only produce suggestion events for officers to confirm
(docs/integrations-chest-plugin.md -- suggestion-only semantics).
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from typing import Any

from flask import Blueprint, Response, jsonify, make_response, render_template, request

from app.db import Session
from core.questdb import ChestSnapshot, Quest

bp = Blueprint("chest", __name__, url_prefix="/chest")


def ingest_snapshot(source: str, items: list[dict[str, Any]]) -> int:
    """Store a snapshot and generate fulfillment suggestions. Returns id."""
    if source not in ("allagan", "manual", "plugin"):
        raise ValueError(f"invalid snapshot source {source!r}")
    now = datetime.now(UTC).isoformat()
    try:
        snap = ChestSnapshot(source=source, data_json=json.dumps({"items": items}), fetched_at=now)
        Session.add(snap)
        Session.flush()
        snapshot_id = int(snap.id)
        Session.commit()
    finally:
        Session.remove()

    _generate_suggestions(snapshot_id, items)
    return snapshot_id


def _generate_suggestions(snapshot_id: int, items: list[dict[str, Any]]) -> None:
    """Match arrived quantities against open pledges; append suggestion events.

    Purely additive: writes quest_events of kind ``chest_suggestion``; a human
    must still confirm turn-ins. Name-based matching against stored trees.
    """
    by_name: dict[str, int] = {}
    for item in items:
        name = str(item.get("name", "")).strip().lower()
        if name:
            by_name[name] = by_name.get(name, 0) + int(item.get("qty", 0))

    try:
        open_quests = Session.query(Quest).filter_by(status="open").all()
        for quest in open_quests:
            matches: list[dict[str, Any]] = []

            def walk(node: dict[str, Any]) -> None:
                node_name = str(node.get("name", "")).strip().lower()
                if node_name in by_name:
                    matches.append(
                        {
                            "node": node_name,
                            "in_chest": by_name[node_name],
                            "required": node.get("qty_required"),
                        }
                    )
                for child in node.get("children", []):
                    walk(child)

            walk(json.loads(quest.tree_json))
            if not matches:
                continue
            seen: set[str] = set()
            unique: list[dict[str, Any]] = []
            for m in matches:
                node = str(m["node"])
                if node not in seen:
                    seen.add(node)
                    unique.append(m)
            from core.questdb import QuestEvent

            Session.add(
                QuestEvent(
                    quest_id=quest.id,
                    kind="chest_suggestion",
                    actor_id=f"chest:{source_for(snapshot_id)}",
                    payload_json=json.dumps({"snapshot_id": snapshot_id, "matches": unique}),
                    created_at=datetime.now(UTC).isoformat(),
                )
            )
        Session.commit()
    finally:
        Session.remove()


def source_for(snapshot_id: int) -> str:
    try:
        row = Session.query(ChestSnapshot).filter_by(id=snapshot_id).first()
        return row.source if row else "?"
    finally:
        Session.remove()


@bp.route("/api/ingest", methods=["POST"])
def api_ingest() -> Response:
    secret = os.environ.get("CHEST_INGEST_SECRET")
    provided = request.headers.get("X-Chest-Token", "")
    if not secret or provided != secret:
        return make_response(jsonify({"error": "unauthorized"}), 401)
    data = request.get_json(force=True)
    source = str(data.get("source", ""))
    items = data.get("items")
    if not isinstance(items, list):
        return make_response(jsonify({"error": "items array required"}), 400)
    try:
        snapshot_id = ingest_snapshot(source, items)
    except ValueError as exc:
        return make_response(jsonify({"error": str(exc)}), 400)
    return jsonify({"ok": True, "snapshot_id": snapshot_id})


@bp.route("/")
def paste_form() -> Response:
    discord = __import__("app.auth", fromlist=["get_discord"]).get_discord()
    if not getattr(discord, "authorized", False):
        from flask import redirect, url_for

        return make_response(redirect(url_for("auth.login")))
    return make_response(render_template("chest_paste.html"))
