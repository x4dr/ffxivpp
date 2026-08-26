"""Questboard web routes (Flask blueprint).

Read-mostly pages + JSON actions, following the conventions of app/routes.py.
Auth: existing check_access() for officer actions; any authenticated guild
member may create quests and pledge/turn-in their own contributions
(docs/questboard.md permissions).
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.parse
import urllib.request
from collections.abc import Generator
from datetime import date
from typing import Any

from flask import (
    Blueprint,
    Response,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    stream_with_context,
    url_for,
)

from app.auth import check_access, get_discord, require_admin
from app.db import Session
from core import questdb
from core.questdb import ItemCatalog
from core.quests import (
    RequirementNode,
    assign_node_ids,
    build_tree,
    flatten_requirements,
    node_statuses,
    quest_complete,
)
from core.wiki import lookup_recipe

logger = logging.getLogger(__name__)

bp = Blueprint("questboard", __name__, url_prefix="/quests")

# --- module config ----------------------------------------------------------

UNIVERSALIS_BASE = "https://universalis.app/api/v2"
UNIVERSALIS_TIMEOUT = 10
USER_AGENT = "ffxivpp-questboard/0.1 (FFXIV free company tool; contact via repo)"
PRICE_TTL_SECONDS = 300.0  # 5 minutes, in-memory only (no persistence)
STREAM_POLL_SECONDS = 1.0  # SSE loop granularity (documented limitation)
WEB_REMINDER_DEFAULTS: dict[str, Any] = {"frequency": "daily", "hour_utc": 18, "minute_utc": 0}

# (expires_at_epoch, payload_or_None) keyed by (server, lowercased item name).
_price_cache: dict[tuple[str, str], tuple[float, dict[str, Any] | None]] = {}


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
            my_reminder=questdb.get_reminder_optin(quest_id, user_id),
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
    voyage_route = data.get("voyage_route")
    voyage_date = data.get("voyage_date")
    qid = questdb.create_quest(
        title=title,
        description=str(data.get("description", "")),
        created_by=user_id,
        root_tree=json.loads(json.dumps(_serialize_tree(root))),
        deadline=data.get("deadline"),
        voyage_route=str(voyage_route)[:200] if voyage_route else None,
        voyage_date=str(voyage_date)[:32] if voyage_date else None,
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


@bp.route("/api/<int:quest_id>/reexpand", methods=["POST"])
@require_admin
def api_reexpand(quest_id: int) -> Response:
    """Re-run recipe expansion on the root item; merge missing children only.

    Additive merge: existing children keep their order so positional node ids
    (and therefore live pledges) stay valid; newly discovered ingredients are
    appended after them.
    """
    user_id, _officer = _current_user()
    quest = questdb.get_quest(quest_id)
    if not quest:
        return make_response(jsonify({"error": "quest not found"}), 404)
    tree = quest["tree"]
    try:
        parsed = lookup_recipe(str(tree.get("name", "")))
    except Exception as exc:  # noqa: BLE001 - degrade gracefully on any wiki failure
        logger.warning("re-expand %s: recipe lookup failed: %s", quest_id, exc)
        parsed = None

    # The wiki must describe the SAME item as the stored root. Manual roots
    # carry item_id=0 and are identified by name alone; resolvable roots must
    # match on id or we would silently graft someone else's recipe on.
    identity_ok = parsed is not None and (
        int(tree.get("item_id", 0)) == 0
        or int(tree.get("item_id", 0)) == parsed.item_id
    )
    added = 0
    if identity_ok and parsed is not None:
        scale = int(tree.get("qty_required", 1)) / max(1, parsed.yield_qty)
        existing = {
            str(c.get("name", "")).strip().lower() for c in tree.get("children", [])
        }
        for ing_id, ing_name, ing_qty in parsed.ingredients:
            if str(ing_name).strip().lower() in existing:
                continue
            tree.setdefault("children", []).append(
                {
                    "item_id": int(ing_id),
                    "name": str(ing_name),
                    "qty_required": max(1, int(ing_qty * scale)),
                    "quality": str(tree.get("quality", "any")),
                    "source": "auto",
                    "children": [],
                }
            )
            added += 1
    if added == 0:
        return jsonify({"ok": True, "added": 0, "note": "nothing new to merge"})
    ok = questdb.update_quest_tree(
        quest_id, json.loads(json.dumps(tree)), user_id or "", added_nodes=added
    )
    if not ok:
        return make_response(jsonify({"error": "quest not found"}), 404)
    return jsonify({"ok": True, "added": added})


def _sse_events(
    poll_seconds: float = STREAM_POLL_SECONDS, max_events: int | None = None
) -> Generator[str, None, None]:
    """Emit a 'quest-changed' event whenever the global change version moves.

    Limitation: one global signal for all quests; clients reload their view.
    The loop polls once per *poll_seconds* -- mutations surface with up to one
    interval of latency. *max_events* caps emission (test hook only).
    """
    # Anchor the baseline when the generator starts iterating (i.e., when the
    # client connects / the response body is first pulled), NOT lazily at the
    # first post-yield resume -- otherwise any mutation landing in between
    # would be silently swallowed and never signalled.
    seen = questdb.change_version()
    yield f"retry: {int(STREAM_POLL_SECONDS * 3000)}\n\n"
    emitted = 0
    while max_events is None or emitted < max_events:
        time.sleep(poll_seconds)
        current = questdb.change_version()
        if current == seen:
            continue
        seen = current
        emitted += 1
        yield f"event: quest-changed\ndata: {json.dumps({'version': current})}\n\n"


@bp.route("/api/stream")
def api_stream() -> Response:
    if not _current_user()[0]:
        return make_response(jsonify({"error": "not authenticated"}), 401)
    return Response(stream_with_context(_sse_events()), mimetype="text/event-stream")


# --- Universalis price hints -------------------------------------------------


def _universalis_json(path: str) -> dict[str, Any]:
    url = UNIVERSALIS_BASE + path
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=UNIVERSALIS_TIMEOUT) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"universalis returned non-object payload for {path}")
    return payload


def _resolve_item_id(name: str) -> int | None:
    """Item id via the local item_catalog first, then the wiki recipe cache/net.

    Reuses core.wiki's cache-first ``lookup_recipe`` (same resolver quest
    creation uses) rather than any external search endpoint.
    """
    try:
        row = Session.query(ItemCatalog).filter(ItemCatalog.name.ilike(name)).first()
        if row:
            return int(row.item_id)
    finally:
        Session.remove()
    try:
        return int(lookup_recipe(name).item_id)
    except Exception as exc:  # noqa: BLE001 - log-and-degrade policy
        logger.warning("item id resolution failed for %r: %s", name, exc)
        return None


def _market_entry(raw: dict[str, Any], item_id: int) -> dict[str, Any]:
    """Normalize Universalis v2 responses (DC-wide 'items' map vs flat single-world)."""
    items = raw.get("items")
    if isinstance(items, dict):
        entry = items.get(str(item_id)) or {}
        return entry if isinstance(entry, dict) else {}
    return raw


def _price_for(server: str, item_name: str) -> dict[str, Any] | None:
    """DC-wide price summary or None. Cached in memory for PRICE_TTL_SECONDS."""
    key = (server, item_name.strip().lower())
    cached = _price_cache.get(key)
    now = time.monotonic()
    if cached and cached[0] > now:
        return cached[1]

    result: dict[str, Any] | None = None
    item_id = _resolve_item_id(item_name)
    if item_id is not None:
        market_path = f"/{urllib.parse.quote(server)}/{item_id}"
        try:
            entry = _market_entry(_universalis_json(market_path), item_id)
            result = {
                "item_id": item_id,
                "name": item_name,
                "server": server,
                "min_listing_nq": entry.get("minListingNQ", entry.get("minPriceNQ")),
                "min_listing_hq": entry.get("minListingHQ", entry.get("minPriceHQ")),
                "nq_sale_velocity": entry.get("nqSaleVelocity", entry.get("regularSaleVelocity")),
            }
        except Exception as exc:  # noqa: BLE001 - log-and-degrade policy
            logger.warning("universalis price fetch failed for %r: %s", item_name, exc)
    else:
        logger.info("no item id resolved for %r; degrading to no price hint", item_name)

    _price_cache[key] = (now + PRICE_TTL_SECONDS, result)
    return result


@bp.route("/api/price/<item_name>")
def api_price(item_name: str) -> Response:
    if not _current_user()[0]:
        return make_response(jsonify({"error": "not authenticated"}), 401)
    server = os.environ.get("DC_SERVER", "Alpha")
    return jsonify({"ok": True, "price": _price_for(server, item_name)})


# --- reminders + deadline ----------------------------------------------------


@bp.route("/api/<int:quest_id>/remind", methods=["POST"])
def api_remind(quest_id: int) -> Response:
    """Toggle the caller's reminder opt-in for this quest."""
    user_id, _is_officer = _current_user()
    if not user_id:
        return make_response(jsonify({"error": "not authenticated"}), 401)
    if not questdb.get_quest(quest_id):
        return make_response(jsonify({"error": "quest not found"}), 404)
    if questdb.get_reminder_optin(quest_id, user_id):
        questdb.remove_reminder_optin(quest_id, user_id)
        return jsonify({"ok": True, "opted_in": False})
    data = request.get_json(silent=True) or {}
    frequency = str(data.get("frequency", WEB_REMINDER_DEFAULTS["frequency"]))
    hour = int(data.get("hour_utc", WEB_REMINDER_DEFAULTS["hour_utc"]))
    minute = int(data.get("minute_utc", WEB_REMINDER_DEFAULTS["minute_utc"]))
    try:
        if data.get("weekday_utc") is not None:
            questdb.upsert_reminder_optin(
                quest_id, user_id, frequency, hour, minute, weekday_utc=int(data["weekday_utc"])
            )
        else:
            questdb.upsert_reminder_optin(quest_id, user_id, frequency, hour, minute)
    except (TypeError, ValueError) as exc:
        return make_response(jsonify({"error": str(exc)}), 400)
    reminder = questdb.get_reminder_optin(quest_id, user_id)
    return jsonify({"ok": True, "opted_in": True, "reminder": reminder})


@bp.route("/api/<int:quest_id>/deadline", methods=["POST"])
@require_admin
def api_deadline(quest_id: int) -> Response:
    user_id, _officer = _current_user()
    data = request.get_json(force=True)
    raw_deadline = data.get("deadline")
    deadline: str | None = None
    if raw_deadline is not None:
        raw_text = str(raw_deadline).strip()
        try:
            date.fromisoformat(raw_text)
        except ValueError as exc:
            return make_response(
                jsonify({"error": f"deadline must be ISO YYYY-MM-DD or null: {exc}"}), 400
            )
        deadline = raw_text
    ok = questdb.set_quest_deadline(quest_id, deadline, user_id or "")
    if not ok:
        return make_response(jsonify({"error": "quest not found"}), 404)
    return jsonify({"ok": True, "deadline": deadline})
