#!/usr/bin/env python3
"""Build data/voyages/submarines-real.json from community data sources.

Sources (fetched once, cached under .cache/voyages-src/):
  1. Loot DB (community-measured drop data, 128 sectors):
     https://raw.githubusercontent.com/saerielle/submersible-loot-db/main/export-items.json
  2. Sector adjacency (mermaid graphs per sea):
     https://paultraylor.net/charts/free-company-voyages
  3. Surveillance breakpoints (SubmarineTracker MapBreakpoints):
     https://raw.githubusercontent.com/Infiziert90/SubmarineTracker/master/SubmarineTracker/Data/Sectors.cs

Stdlib only. Usage:
  uv run python tools/build_voyage_pack.py            # build pack (uses cache)
  uv run python tools/build_voyage_pack.py --refresh  # force re-download
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from collections import defaultdict
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = REPO_ROOT / ".cache" / "voyages-src"
OUTPUT_PATH = REPO_ROOT / "data" / "voyages" / "submarines-real.json"

LOOT_URL = (
    "https://raw.githubusercontent.com/saerielle/submersible-loot-db/"
    "main/export-items.json"
)
ADJACENCY_URL = "https://paultraylor.net/charts/free-company-voyages"
BREAKPOINTS_URL = (
    "https://raw.githubusercontent.com/Infiziert90/SubmarineTracker/"
    "master/SubmarineTracker/Data/Sectors.cs"
)

# Canonical sea order/keys; base = numeric SubmarineExploration row id of the
# sea's first sector (ranges between bases are contiguous per game data).
SEAS = [
    ("Deep-Sea Site", "deepsea", 1),
    ("Sea of Ash", "ash", 32),
    ("Sea of Jade", "jade", 53),
    ("Sirensong Sea", "sirensong", 74),
    ("The Lilac Sea", "lilac", 95),
    ("South Indigo Deep", "southindigo", 116),
]

ROUTE_LEN_MAX = 5
ROUTE_LEN_MIN = 3
ROUTES_PER_SEA = 3
DURATION_MINUTES = 720
GAME_VERSION = "7.x"


def fetch(name: str, url: str, refresh: bool) -> str:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / name
    if path.is_file() and not refresh:
        return path.read_text(encoding="utf-8")
    print(f"downloading {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "ffxivpp-voyage-pack/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = resp.read().decode("utf-8")
    path.write_text(data, encoding="utf-8")
    return data


# --- source parsers -----------------------------------------------------------


def parse_loot(path: Path) -> dict[int, dict]:
    """Group loot rows by numeric SectorID -> {letter, name, tiers}."""
    rows = json.loads(path.read_text(encoding="utf-8"))
    sectors: dict[int, dict] = {}
    for row in rows:
        sid = int(row["SectorID"])
        sec = sectors.setdefault(sid, {"letter": row["Lettername"], "name": row["Sector name"], "tiers": {}})
        tier = sec["tiers"].setdefault(row["Loot tier"], [])
        qty_min = int(float(row["Normal min"]))
        qty_max = int(float(row["Normal max"]))
        for entry in tier:
            if entry["item"] == row["Item name"]:
                entry["qty"] = [min(entry["qty"][0], qty_min), max(entry["qty"][1], qty_max)]
                break
        else:
            tier.append({"item": row["Item name"], "qty": [qty_min, qty_max]})
    return sectors


def parse_breakpoints(path: Path) -> dict[int, tuple[int, int]]:
    """MapBreakpoints dict: sector id -> (T2, T3) surveillance thresholds."""
    text = path.read_text(encoding="utf-8")
    out: dict[int, tuple[int, int]] = {}
    for m in re.finditer(r"\{\s*(\d{1,3}),\s*new Breakpoint\((\d+),\s*(\d+)", text):
        out[int(m.group(1))] = (int(m.group(2)), int(m.group(3)))
    return out


def parse_adjacency(path: Path) -> dict[str, dict]:
    """Parse the submarine mermaid blocks -> per sea title:
    {letters: [letter...], names: {letter: name}, edges: [(letter, letter)]}.
    """
    html = path.read_text(encoding="utf-8")
    start = html.find('<h1 id="submarine">')
    if start < 0:
        raise SystemExit("adjacency page: submarine section not found")
    html = html[start:]
    seas: dict[str, dict] = {}
    block_re = re.compile(
        r'<h2 id="[^"]+">([^<]+)</h2>.*?<div class="mermaid">(.*?)</div>', re.S
    )
    node_re = re.compile(r"^\s*([A-Z]{1,2})\(([^)]*)\)", re.M)
    edge_re = re.compile(r"^\s*([A-Z]{1,2})\s*-->\s*([A-Z]{1,2})\s*$", re.M)
    start_edge_re = re.compile(r"^\s*Start\s*-->\s*([A-Z]{1,2})\s*$", re.M)
    for m in block_re.finditer(html):
        title, body = m.group(1).strip(), m.group(2)
        names = {ltr: name.strip() for ltr, name in node_re.findall(body)}
        edges = edge_re.findall(body)
        starts = start_edge_re.findall(body)
        seas[title] = {
            "letters": list(names),
            "names": names,
            "edges": edges,
            "starts": starts,
        }
    return seas


# --- pack assembly ------------------------------------------------------------


def build_thresholds(
    sid: int, loot_sec: dict, bp: tuple[int, int] | None
) -> list[dict]:
    """T1 = surveillance 0; T2/T3 gated by SubmarineTracker breakpoints."""
    thresholds = [{"min_surveillance": 0, "loot": sorted(loot_sec["tiers"].get("T1", []), key=lambda e: e["item"])}]
    if bp is not None:
        thresholds.append({"min_surveillance": bp[0], "loot": sorted(loot_sec["tiers"].get("T2", []), key=lambda e: e["item"])})
        thresholds.append({"min_surveillance": bp[1], "loot": sorted(loot_sec["tiers"].get("T3", []), key=lambda e: e["item"])})
    return thresholds


def derive_routes(title: str, sea: dict, warnings: list[str]) -> list[list[str]]:
    """Deterministic routes: walk adjacency from each entry point, first- and
    last-child tiebreaks, capped at ROUTES_PER_SEA paths of length
    ROUTE_LEN_MIN..ROUTE_LEN_MAX."""
    adj: dict[str, list[str]] = defaultdict(list)
    for a, b in sea["edges"]:
        adj[a].append(b)

    roots = sea["starts"] or [
        l for l in sea["letters"] if not any(b == l for a, b in sea["edges"])
    ]
    roots = [r for r in roots if r in adj or any(a == r for a, b in sea["edges"])]

    def walk(root: str, pick) -> list[str]:
        path = [root]
        while len(path) < ROUTE_LEN_MAX:
            kids = [k for k in adj.get(path[-1], []) if k not in path]
            if not kids:
                break
            path.append(pick(kids))
        return path

    seen: set[tuple[str, ...]] = set()
    paths: list[list[str]] = []
    tiebreaks = [lambda kids: kids[0], lambda kids: kids[-1]]
    for root in roots:
        for pick in tiebreaks:
            p = walk(root, pick)
            key = tuple(p)
            if key not in seen and len(p) >= ROUTE_LEN_MIN:
                seen.add(key)
                paths.append(p)
        if len(paths) >= ROUTES_PER_SEA:
            break
    # fallback: a sea whose graph is a pure chain yields one walk; also emit a
    # truncated 3-sector slice so the sea keeps >=2 usable routes.
    if paths and len(paths) < 2:
        short = paths[0][:ROUTE_LEN_MIN]
        if len(short) >= ROUTE_LEN_MIN:
            paths.append(short)

    unattached = [
        l
        for l in sea["letters"]
        if l not in adj and not any(b == l for a, b in sea["edges"])
    ]
    if unattached:
        warnings.append(
            f"{title}: sectors with no adjacency data (excluded from routes): "
            + ", ".join(unattached)
        )
    return paths[: max(ROUTES_PER_SEA, 2)]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--refresh", action="store_true", help="re-download cached sources")
    args = ap.parse_args()

    loot_path = CACHE_DIR / "loot.json"
    bp_path = CACHE_DIR / "Sectors.cs"
    adj_path = CACHE_DIR / "adjacency.html"
    fetch("loot.json", LOOT_URL, args.refresh)
    fetch("Sectors.cs", BREAKPOINTS_URL, args.refresh)
    fetch("adjacency.html", ADJACENCY_URL, args.refresh)
    loot = parse_loot(loot_path)
    bp = parse_breakpoints(bp_path)
    adjacency = parse_adjacency(adj_path)

    warnings: list[str] = []
    sectors: list[dict] = []
    routes: list[dict] = []
    sea_reports: list[str] = []

    bases = [base for _, _, base in SEAS] + [SEAS[-1][2] + 30]
    for (title, slug, base), hi in zip(SEAS, bases[1:]):
        if title not in adjacency:
            warnings.append(f"sea {title!r} missing from adjacency page")
            continue
        sea = adjacency[title]
        page_names = {l: n.casefold() for l, n in sea["names"].items()}

        sea_sids = sorted(s for s in loot if base <= s < hi)
        by_letter = {}
        for i, sid in enumerate(sea_sids):
            sec = loot[sid]
            letter = sec["letter"]
            by_letter[letter] = (sid, sec)
            if i != sid - base:
                warnings.append(f"{title} {letter}: positional offset mismatch (id {sid})")
            page = page_names.get(letter)
            if page and page != sec["name"].casefold():
                warnings.append(
                    f"{title} {letter}: name differs between sources "
                    f"(adjacency: {sea['names'][letter]!r}, loot db: {sec['name']!r}); "
                    "kept loot db name"
                )

        no_adjacency = [l for l in by_letter if l not in page_names]
        if no_adjacency:
            warnings.append(
                f"{title}: loot sectors missing from adjacency page (no routes): "
                + ", ".join(sorted(no_adjacency, key=lambda l: (len(l), l)))
            )

        sea_sectors = []
        for letter in sorted(by_letter, key=lambda l: (len(l), l)):
            sid, sec = by_letter[letter]
            thresholds = build_thresholds(sid, sec, bp.get(sid))
            sea_sectors.append(
                {
                    "id": f"{slug}-{letter}",
                    "name": sec["name"],
                    "distance": 0,
                    "surveillance_thresholds": thresholds,
                }
            )
        sectors.extend(sea_sectors)

        sea_routes = derive_routes(title, sea, warnings)
        for i, path in enumerate(sea_routes, 1):
            routes.append(
                {
                    "name": f"{title} Cruise {i}",
                    "ship": "submarine",
                    "sector_ids": [f"{slug}-{l}" for l in path],
                    "duration_minutes": DURATION_MINUTES,
                }
            )
        sea_reports.append(f"{title}: {len(sea_sectors)} sectors, {len(sea_routes)} routes")

    pack = {
        "meta": {
            "game_version": GAME_VERSION,
            "source": (
                f"Real submarine data; loot: {LOOT_URL}; adjacency: {ADJACENCY_URL}; "
                f"breakpoints: {BREAKPOINTS_URL}; retrieved {date.today().isoformat()}"
            ),
            "sources": [LOOT_URL, ADJACENCY_URL, BREAKPOINTS_URL],
            "retrieved": date.today().isoformat(),
        },
        "ships": {"submarine": {"base_range": 100}},
        "sectors": sectors,
        "routes": routes,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(pack, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    for w in warnings:
        print(f"WARNING: {w}", file=sys.stderr)
    for line in sea_reports:
        print(line)
    print(
        f"wrote {OUTPUT_PATH.relative_to(REPO_ROOT)}: "
        f"{len(sectors)} sectors, {len(routes)} routes, "
        f"{len({s['id'].split('-')[0] for s in sectors})} seas"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
