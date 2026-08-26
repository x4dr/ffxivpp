"""Voyage pages: fleet config + prediction view; "Open as job" quest link."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

from flask import Blueprint, Response, make_response, redirect, render_template, url_for

from app.auth import get_discord
from core.voyages import VoyageDataError, load_pack, predict_voyage

bp = Blueprint("voyages", __name__, url_prefix="/voyages")


def job_payload(prediction: dict[str, Any]) -> dict[str, Any] | None:
    """JSON body for POST /quests/api/create from a predicted voyage.

    Root item = first predicted loot entry at its scaled max quantity.
    None when the prediction yields no loot (nothing to open a job for).
    """
    loot = prediction.get("loot") or []
    if not loot:
        return None
    first = loot[0]
    return {
        "title": f"Voyage: {prediction['route']}",
        "item_name": str(first["item"]),
        "qty": int(first["qty_scaled"][-1]),
        "voyage_route": str(prediction["route"]),
        "voyage_date": datetime.now(UTC).date().isoformat(),
    }


@bp.route("/")
def index() -> Response:
    discord = get_discord()
    if not getattr(discord, "authorized", False):
        return make_response(redirect(url_for("auth.login")))
    try:
        pack = load_pack()
    except VoyageDataError as exc:
        return make_response(
            render_template(
                "voyages.html",
                error=f"Voyage data unavailable: {exc}. "
                f"Place a data pack in $VOYAGE_DATA_DIR (see docs/integrations-voyages.md).",
            ),
            200,
        )

    routes = pack.get("routes", [])
    selected = request_route(routes)
    surveillance = int(os.environ.get("SAMPLE_SURVEILLANCE", "80"))
    prediction = None
    if selected:
        ship = next((r["ship"] for r in routes if r["name"] == selected), "submarine")
        prediction = predict_voyage(
            pack, selected, ship=ship, surveillance=surveillance, retrieval=100, parts_bonus=0
        )
    return make_response(
        render_template(
            "voyages.html",
            meta=pack.get("meta", {}),
            routes=[r["name"] for r in routes],
            selected=selected,
            prediction=prediction,
            job=job_payload(prediction) if prediction else None,
            error=None,
        )
    )


def request_route(routes: list[dict[str, Any]]) -> str | None:
    from flask import request

    requested = request.args.get("route")
    if requested and any(r["name"] == requested for r in routes):
        return requested
    return routes[0]["name"] if routes else None
