"""Voyage data loading, validation, and deterministic prediction.

Data packs are versioned JSON files placed by the operator into
``VOYAGE_DATA_DIR`` (never committed to git -- see
docs/integrations-voyages.md). Schema:

    {
      "meta": {"game_version": "7.3", "source": "community pack vN"},
      "ships": {
        "submarine": {"base_range": 100, "tank_capacity": 19},
        "airship":   {"base_range": 96,  "tank_capacity": null}
      },
      "sectors": [
        {"id": "U", "name": "deep-sea site 6", "distance": 105,
         "surveillance_thresholds": [
           {"min_surveillance": 90, "loot": [{"item": "Birch Log", "qty": [3, 8]}]}
         ]}
      ],
      "routes": [
        {"name": "Deep-sea Site Loop", "ship": "submarine",
         "sector_ids": ["A", "B", "C", "D"], "duration_minutes": 720}
      ]
    }

Prediction is a pure function of (fleet config, route, sector table):
reachable = sum(distance) <= range; loot = union of sector loot gated by the
fleet's surveillance stat. Deterministic, heavily unit-tested, no I/O here.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

DATA_DIR_ENV = "VOYAGE_DATA_DIR"


class VoyageDataError(Exception):
    """Raised for missing/invalid/mismatched voyage data packs."""


def data_dir() -> Path:
    configured = os.environ.get(DATA_DIR_ENV)
    if not configured:
        raise VoyageDataError(f"{DATA_DIR_ENV} is not set")
    path = Path(configured)
    if not path.is_dir():
        raise VoyageDataError(f"{DATA_DIR_ENV} points to missing dir {path}")
    return path


def validate_pack(pack: dict[str, Any]) -> None:
    """Schema-validate a voyage pack; raises VoyageDataError with details."""
    meta = pack.get("meta")
    if not isinstance(meta, dict) or "game_version" not in meta:
        raise VoyageDataError("pack.meta.game_version missing")
    ships = pack.get("ships")
    if not isinstance(ships, dict) or not ships:
        raise VoyageDataError("pack.ships missing or empty")
    sectors = pack.get("sectors")
    if not isinstance(sectors, list) or not sectors:
        raise VoyageDataError("pack.sectors missing or empty")
    ids: set[str] = set()
    for sector in sectors:
        sid = sector.get("id")
        if not sid:
            raise VoyageDataError("sector without id")
        if sid in ids:
            raise VoyageDataError(f"duplicate sector id {sid!r}")
        ids.add(sid)
        if not isinstance(sector.get("distance"), int) or sector["distance"] < 0:
            raise VoyageDataError(f"sector {sid}: distance must be int >= 0")
    routes = pack.get("routes")
    if isinstance(routes, list):
        for route in routes:
            unknown = set(route.get("sector_ids", [])) - ids
            if unknown:
                raise VoyageDataError(
                    f"route {route.get('name')!r} references unknown sectors {sorted(unknown)}"
                )
            if route.get("ship") not in ships:
                raise VoyageDataError(
                    f"route {route.get('name')!r} uses unknown ship {route.get('ship')!r}"
                )


def load_pack(filename: str | None = None) -> dict[str, Any]:
    """Load and validate a pack from VOYAGE_DATA_DIR (newest *.json by default)."""
    base = data_dir()
    if filename:
        path = base / filename
    else:
        candidates = sorted(base.glob("*.json"), key=lambda p: p.stat().st_mtime)
        if not candidates:
            raise VoyageDataError(f"no .json data packs in {base}")
        path = candidates[-1]
    try:
        pack: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise VoyageDataError(f"invalid JSON in {path.name}: {exc}") from exc
    validate_pack(pack)
    return pack


# --- pure prediction ---------------------------------------------------------


def fleet_range(pack: dict[str, Any], ship: str, parts_bonus: int) -> int:
    ship_def = pack["ships"].get(ship)
    if not ship_def:
        raise VoyageDataError(f"unknown ship {ship!r}")
    return int(ship_def.get("base_range", 0)) + int(parts_bonus)


def route_distance(pack: dict[str, Any], route_name: str) -> int:
    sector_by_id = {s["id"]: s for s in pack["sectors"]}
    route = next((r for r in pack.get("routes", []) if r["name"] == route_name), None)
    if route is None:
        raise VoyageDataError(f"unknown route {route_name!r}")
    return sum(sector_by_id[sid]["distance"] for sid in route["sector_ids"])


def predict_voyage(
    pack: dict[str, Any],
    route_name: str,
    *,
    ship: str,
    surveillance: int,
    retrieval: int,
    parts_bonus: int,
) -> dict[str, Any]:
    """Deterministic prediction: reachability, duration, gated loot table."""
    route = next((r for r in pack.get("routes", []) if r["name"] == route_name), None)
    if route is None:
        raise VoyageDataError(f"unknown route {route_name!r}")
    sector_by_id = {s["id"]: s for s in pack["sectors"]}
    distance = route_distance(pack, route_name)
    reach = fleet_range(pack, ship, parts_bonus)

    loot: list[dict[str, Any]] = []
    locked: list[str] = []
    for sid in route["sector_ids"]:
        sector = sector_by_id[sid]
        for band in sector.get("surveillance_thresholds", []):
            if surveillance >= band["min_surveillance"]:
                for item in band["loot"]:
                    scaled = dict(item)
                    qty = item.get("qty", [1, 1])
                    scaled["qty_scaled"] = [
                        max(1, q * retrieval // 100) if retrieval else q for q in qty
                    ]
                    loot.append(scaled)
            else:
                locked.append(f"{sid} ({band['min_surveillance']}+)")
    return {
        "route": route_name,
        "ship": ship,
        "reachable": distance <= reach,
        "range_needed": distance,
        "range_available": reach,
        "duration_minutes": route.get("duration_minutes"),
        "surveillance": surveillance,
        "loot": loot,
        "locked_bands": locked,
    }
