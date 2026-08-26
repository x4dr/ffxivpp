"""Questboard web routes (Flask blueprint).

Read-mostly pages + JSON actions, following the conventions of app/routes.py.
Auth: existing check_access() for officer actions; any authenticated guild
member may create quests and pledge/turn-in their own contributions
(docs/questboard.md permissions).
"""

from __future__ import annotations

import json
from typing import Any

from flask import (
    Blueprint,
    Response,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    url_for,
)

from app.auth import check_access, get_discord, require_admin
from core import questdb
from core.quests import (
    RequirementNode,
    assign_node_ids,
    build_tree,
    flatten_requirements,
    node_statuses,
    quest_complete,
)
from core.wiki import lookup_recipe

bp = Blueprint("questboard", __name__, url_prefix="/quests")


@bp.app_template_filter("dt")
def friendly_dt(value: Any, seconds: bool = False) -> str:
    """ISO timestamp -> 'YYYY-MM-DD HH:MM[SS]'; returns input unchanged if unparsable."""
    from datetime import datetime

    text = str(value)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return text
    return parsed.strftime("%Y-%m-%d %H:%M:%S" if seconds else "%Y-%m-%d %H:%M")


def _current_user() -> tuple[str, bool]:
    """Return (discord_user_id, is_officer). Unauthenticated -> ("", False)."""
    discord = get_discord()
    if not discord.authorized:
        return "", False
    user = discord.fetch_user()
    return str(user.id), check_access()


def _tree_from_stored(tree_data: dict[str, Any]) -> RequirementNode:
    """Rebuild a live RequirementNode tree from stored quest JSON."""
    root = build_tree(
        int(tree_data["item_id"]),
        str(tree_data["name"]),
        int(tree_data["qty_required"]),
        lambda _i: None,
        quality=str(tree_data.get("quality", "any")),
    )
    _apply_children(root, tree_data.get("children", []))
    return root


def _apply_children(node: RequirementNode, children: list[dict[str, Any]]) -> None:
    for child in children:
        c = RequirementNode(
            item_id=int(child["item_id"]),
            name=str(child["name"]),
            qty_required=int(child["qty_required"]),
            quality=str(child.get("quality", "any")),
            source=str(child.get("source", "auto")),
        )
        _apply_children(c, child.get("children", []))
        node.children.append(c)


def _serialize_tree(root: RequirementNode) -> dict[str, Any]:
    out: dict[str, Any] = {
        "item_id": root.item_id,
        "name": root.name,
        "qty_required": root.qty_required,
        "quality": root.quality,
        "children": [
            {
                "item_id": c.item_id,
                "name": c.name,
                "qty_required": c.qty_required,
                "quality": c.quality,
                "source": c.source,
                "children": _serialize_tree(c)["children"],
            }
            for c in root.children
        ],
    }
    return out


@bp.route("/")
def board() -> Response:
    user_id, is_officer = _current_user()
    if not user_id:
        return make_response(redirect(url_for("auth.login")))
    quests = questdb.list_quests([questdb.QUEST_OPEN])
    summaries = []
    for q in quests:
        full = questdb.get_quest(q["id"])
        if not full:
            continue
        root = _tree_from_stored(full["tree"])
        assign_node_ids(root)
        pledges, turned = questdb.quest_amounts(q["id"])
        statuses = list(node_statuses(root, pledges, turned).values())
        done = sum(1 for s in statuses if s.fulfilled)
        summaries.append(
            {
                **q,
                "nodes_total": len(statuses),
                "nodes_fulfilled": done,
                "shopping_list": flatten_requirements(root, pledges, turned)[:5],
            }
        )
    return make_response(
        render_template("questboard.html", quests=summaries, is_officer=is_officer)
    )


@bp.route("/<int:quest_id>")
def detail(quest_id: int) -> Response:
    user_id, is_officer = _current_user()
    if not user_id:
        return make_response(redirect(url_for("auth.login")))
    quest = questdb.get_quest(quest_id)
    if not quest:
        return make_response("Quest not found", 404)
    root = _tree_from_stored(quest["tree"])
    assign_node_ids(root)
    pledges, turned = questdb.quest_amounts(quest_id)
    statuses = node_statuses(root, pledges, turned)
    my_pledges = [
        {"pledge_id": p.id, "node_id": p.node_id, "qty": p.qty, "turned_qty": p.turned_qty}
        for p in _raw_pledges(quest_id)
        if p.person_id == user_id and not p.withdrawn
    ]
    return make_response(
        render_template(
            "quest_detail.html",
            quest=quest,
            statuses=list(statuses.values()),
            events=questdb.quest_events(quest_id),
            my_pledges=my_pledges,
            complete=quest_complete(root, turned),
            is_officer=is_officer,
        )
    )


def _raw_pledges(quest_id: int) -> list[questdb.QuestPledge]:
    from app.db import Session

    try:
        return Session.query(questdb.QuestPledge).filter_by(quest_id=quest_id).all()
    finally:
        Session.remove()


# --- JSON API --------------------------------------------------------------


@bp.route("/api/create", methods=["POST"])
def api_create() -> Response:
    user_id, is_officer = _current_user()
    if not user_id:
        return make_response(jsonify({"error": "not authenticated"}), 401)
    data = request.get_json(force=True)
    title = str(data.get("title", "")).strip()
    if not title:
        return make_response(jsonify({"error": "title required"}), 400)
    item_name = str(data.get("item_name", "")).strip()
    qty = int(data.get("qty", 1))
    quality = str(data.get("quality", "any"))
    manual_items: list[dict[str, Any]] = data.get("manual_items", []) or []

    def recipe_lookup(item_id: int) -> None:
        # name-based catalog: only used through explicit expansion below
        return None

    try:
        parsed = lookup_recipe(item_name)
        root = build_tree(parsed.item_id, parsed.name, qty, lambda _i: None, quality=quality)

        scale = qty / max(1, parsed.yield_qty)
        for iid, name, ing_qty in parsed.ingredients:
            root.children.append(
                RequirementNode(item_id=iid, name=name, qty_required=int(ing_qty * scale),
                                quality=quality, source="auto")
            )
    except (LookupError, ValueError):
        # fall back to fully manual root when the wiki cannot resolve it
        if not manual_items and not item_name:
            return make_response(jsonify({"error": "item could not be resolved"}), 400)

        root = RequirementNode(item_id=0, name=item_name or title, qty_required=max(1, qty),
                               quality=quality, source="root")
    for m in manual_items:
        root.children.append(
            RequirementNode(item_id=int(m.get("item_id", 0)), name=str(m["name"]),
                            qty_required=int(m.get("qty", 1)),
                            quality=str(m.get("quality", "any")), source="manual")
        )
    assign_node_ids(root)
    qid = questdb.create_quest(
        title=title,
        description=str(data.get("description", "")),
        created_by=user_id,
        root_tree=json.loads(json.dumps(_serialize_tree(root))),
        deadline=data.get("deadline"),
    )
    del is_officer, recipe_lookup
    return jsonify({"ok": True, "quest_id": qid})


@bp.route("/api/<int:quest_id>/pledge", methods=["POST"])
def api_pledge(quest_id: int) -> Response:
    user_id, _is_officer = _current_user()
    if not user_id:
        return make_response(jsonify({"error": "not authenticated"}), 401)
    data = request.get_json(force=True)
    try:
        pid = questdb.add_pledge(
            quest_id=quest_id,
            node_id=str(data.get("node_id", "")),
            person_id=user_id,
            qty=int(data.get("qty", 0)),
            actor_id=user_id,
        )
    except ValueError as exc:
        return make_response(jsonify({"error": str(exc)}), 400)
    except KeyError as exc:
        return make_response(jsonify({"error": f"unknown quest or node: {exc}"}), 404)
    return jsonify({"ok": True, "pledge_id": pid})


@bp.route("/api/<int:quest_id>/turnin", methods=["POST"])
def api_turnin(quest_id: int) -> Response:
    user_id, _is_officer = _current_user()
    if not user_id:
        return make_response(jsonify({"error": "not authenticated"}), 401)
    data = request.get_json(force=True)
    qty = data.get("qty")
    ok = questdb.mark_turned_in(int(data["pledge_id"]), user_id, int(qty) if qty else None)
    if not ok:
        return make_response(jsonify({"error": "cannot turn in that pledge"}), 400)

    # auto-fulfil: flip status when everything required has arrived
    quest = questdb.get_quest(quest_id)
    if quest and quest["status"] == questdb.QUEST_OPEN:
        root = _tree_from_stored(quest["tree"])
        assign_node_ids(root)
        _pledges, turned = questdb.quest_amounts(quest_id)
        if quest_complete(root, turned):
            questdb.set_quest_status(quest_id, questdb.QUEST_FULFILLED, user_id)
    return jsonify({"ok": True})


@bp.route("/api/pledge/<int:pledge_id>/withdraw", methods=["POST"])
def api_withdraw(pledge_id: int) -> Response:
    user_id, _is_officer = _current_user()
    if not user_id:
        return make_response(jsonify({"error": "not authenticated"}), 401)
    ok = questdb.withdraw_pledge(pledge_id, user_id)
    if not ok:
        return make_response(jsonify({"error": "cannot withdraw that pledge"}), 400)
    return jsonify({"ok": True})


@bp.route("/api/<int:quest_id>/status", methods=["POST"])
@require_admin
def api_status(quest_id: int) -> Response:
    user_id, _officer = _current_user()
    data = request.get_json(force=True)
    try:
        ok = questdb.set_quest_status(quest_id, str(data.get("status", "")), user_id or "")
    except ValueError as exc:
        return make_response(jsonify({"error": str(exc)}), 400)
    if not ok:
        return make_response(jsonify({"error": "quest not found"}), 404)
    return jsonify({"ok": True})
