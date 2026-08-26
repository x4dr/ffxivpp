"""consolegameswiki recipe pipeline: fetch wikitext, parse recipes, cache.

Design (docs/integrations-wiki-tree.md):
* cache-first: ItemCatalog rows serve lookups; network only on miss.
* patch detection: the wiki "Patches" page lists game patches; the highest
  version becomes the catalog's ``game_version``. A change marks recipe
  caches stale (quests keep their stored trees -- re-expansion is manual).
* fetching is injected (``fetch_fn``) so tests never touch the network.
"""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.db import Session
from core.questdb import ItemCatalog

logger = logging.getLogger(__name__)

WIKI_API = "https://ffxiv.consolegameswiki.com/mediawiki/api.php"
USER_AGENT = "ffxivpp-questboard/0.1 (FFXIV free company tool; contact via repo)"
REQUEST_TIMEOUT = 15
MIN_REQUEST_INTERVAL = 1.1  # seconds between wiki hits (politeness)

FetchFn = Callable[[str], str]

_last_fetch: list[float] = [0.0]


@dataclass(frozen=True)
class ParsedRecipe:
    item_id: int
    name: str
    job: str | None
    level: int | None
    yield_qty: int
    ingredients: list[tuple[int, str, int]]


def _throttled_fetch(url: str) -> str:
    elapsed = time.monotonic() - _last_fetch[0]
    if elapsed < MIN_REQUEST_INTERVAL:
        time.sleep(MIN_REQUEST_INTERVAL - elapsed)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            return str(resp.read().decode("utf-8"))
    finally:
        _last_fetch[0] = time.monotonic()


def _api_get(params: dict[str, str], fetch_fn: FetchFn) -> str:
    url = WIKI_API + "?" + urllib.parse.urlencode(params)
    return fetch_fn(url)


# --- wikitext parsing ------------------------------------------------------


_FIELD_SPLIT = re.compile(r"^(?P<key>[a-z0-9-]+)\s*=\s*(?P<value>.*)$", re.DOTALL)
_INGREDIENT = re.compile(r"^ingredient\d+\s*$")


def _split_top_level_fields(body: str) -> list[str]:
    """Split template body (outer ``{{ }}`` removed) on top-level ``|``."""
    parts: list[str] = []
    depth = 1  # caller strips the template's own braces; we are inside it
    start = 0
    i = 0
    while i < len(body):
        two = body[i : i + 2]
        if two == "{{":
            depth += 1
            i += 2
            continue
        if two == "}}":
            depth -= 1
            i += 2
            continue
        if body[i] == "|" and depth == 1:
            parts.append(body[start:i])
            start = i + 1
        i += 1
    parts.append(body[start:])
    return parts


def _parse_infobox_template(wikitext: str) -> dict[str, str]:
    """Extract top-level ``| key = value`` fields from both infobox templates."""
    fields: dict[str, str] = {}
    for section in ("{{Item infobox", "{{Recipe"):
        idx = wikitext.find(section)
        if idx == -1:
            continue
        end = len(wikitext)
        depth = 0
        for pos in range(idx, len(wikitext) - 1):
            if wikitext[pos : pos + 2] == "{{":
                depth += 1
            elif wikitext[pos : pos + 2] == "}}":
                depth -= 1
                if depth == 0:
                    end = pos + 2
                    break
        body = wikitext[idx + len("{{") : end - len("}}")]
        for raw_field in _split_top_level_fields(body):
            m = _FIELD_SPLIT.match(raw_field.strip())
            if not m:
                continue
            key = m.group("key").strip()
            value = m.group("value").strip()
            if not value:
                continue
            if _INGREDIENT.match(key):
                # keep numbered ingredient keys distinct
                fields.setdefault(key, value)
            else:
                fields[key] = value
    return fields


_ID_GT = re.compile(r"^\d+$")


def parse_item_wikitext(wikitext: str, page_title: str) -> ParsedRecipe:
    """Parse an item page's wikitext into a :class:`ParsedRecipe`.

    Raises ValueError when the page has no craftable recipe or no numeric id.
    """
    fields = _parse_infobox_template(wikitext)
    raw_id = fields.get("id-gt", "").strip()
    if not _ID_GT.match(raw_id):
        raise ValueError(f"no numeric item id on page {page_title!r}")
    item_id = int(raw_id)
    if "yield" not in fields:
        raise ValueError(f"page {page_title!r} has no crafting recipe")

    ingredients: list[tuple[int, str, int]] = []
    for key in sorted(
        (k for k in fields if _INGREDIENT.match(k)),
        key=lambda k: int(k[len("ingredient") :]),
    ):
        value = fields[key]
        m = re.match(r"^(?P<qty>\d+)\s+(?P<name>.+)$", value)
        if m:
            ingredients.append((0, m.group("name").strip(), int(m.group("qty"))))
    return ParsedRecipe(
        item_id=item_id,
        name=fields.get("name", page_title).strip(),
        job=fields.get("class"),
        level=int(fields["level"]) if fields.get("level", "").isdigit() else None,
        yield_qty=int(fields.get("yield", "1")),
        ingredients=ingredients,
    )


# --- name -> id resolution + caching ---------------------------------------


def resolve_item(name: str, fetch_fn: FetchFn = _throttled_fetch) -> int:
    """Resolve an item name to its id via the wiki search API."""
    text = _api_get(
        {
            "action": "query",
            "list": "search",
            "srsearch": name,
            "srnamespace": "0",
            "srlimit": "5",
            "format": "json",
            "formatversion": "2",
        },
        fetch_fn,
    )
    data = json.loads(text)
    hits = data.get("query", {}).get("search", [])
    wanted = name.strip().lower()
    for hit in hits:
        if hit["title"].strip().lower() == wanted:
            return _id_for_page(hit["title"], fetch_fn)
    if hits:
        return _id_for_page(hits[0]["title"], fetch_fn)
    raise LookupError(f"item {name!r} not found on the wiki")


def _id_for_page(title: str, fetch_fn: FetchFn) -> int:
    wikitext = _fetch_wikitext(title, fetch_fn)
    parsed = parse_item_wikitext(wikitext, title)
    return parsed.item_id


def _fetch_wikitext(title: str, fetch_fn: FetchFn) -> str:
    text = _api_get(
        {
            "action": "parse",
            "page": title,
            "prop": "wikitext",
            "format": "json",
            "formatversion": "2",
        },
        fetch_fn,
    )
    data = json.loads(text)
    wikitext = data.get("parse", {}).get("wikitext")
    if wikitext is None:
        raise LookupError(f"wiki page {title!r} missing or unparseable")
    return str(wikitext)


def lookup_recipe(item_name: str, fetch_fn: FetchFn = _throttled_fetch) -> ParsedRecipe:
    """Cache-first recipe lookup by item name."""
    try:
        cached = cached_recipe(item_name)
    except Exception:  # noqa: BLE001 - cache problems must not break lookups
        cached = None
    if cached is not None:
        return cached
    title = urllib.parse.quote(item_name.strip().replace(" ", "_"))
    wikitext = _fetch_wikitext(urllib.parse.unquote(title), fetch_fn)
    parsed = parse_item_wikitext(wikitext, item_name)
    store_in_cache(parsed)
    return parsed


def cached_recipe(item_name: str) -> ParsedRecipe | None:
    row = (
        Session.query(ItemCatalog)
        .filter(ItemCatalog.name.ilike(item_name))
        .first()
    )
    if row is None or row.recipe_json is None:
        return None
    data: dict[str, Any] = json.loads(row.recipe_json)
    return ParsedRecipe(
        item_id=row.item_id,
        name=row.name,
        job=data.get("job"),
        level=data.get("level"),
        yield_qty=data.get("yield", 1),
        ingredients=[tuple(i) for i in data.get("ingredients", [])],  # type: ignore[misc]
    )


def store_in_cache(parsed: ParsedRecipe) -> None:
    try:
        Session.merge(
            ItemCatalog(
                item_id=parsed.item_id,
                name=parsed.name,
                recipe_json=json.dumps(
                    {
                        "job": parsed.job,
                        "level": parsed.level,
                        "yield": parsed.yield_qty,
                        "ingredients": [
                            [iid, name, qty] for iid, name, qty in parsed.ingredients
                        ],
                    }
                ),
                flags_json="{}",
                fetched_at=str(int(time.time())),
            )
        )
        Session.commit()
    finally:
        Session.remove()


# --- patch detection --------------------------------------------------------

_PATCH_VERSION = re.compile(r"Patch[_ ](\d+\.\d+)", re.IGNORECASE)


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def extract_latest_patch(wikitext: str) -> str | None:
    """Newest ``Patch X.Y`` version mentioned in *wikitext*, or None."""
    versions = set(_PATCH_VERSION.findall(wikitext))
    if not versions:
        return None
    return max(versions, key=_version_key)


def detect_latest_patch(fetch_fn: FetchFn = _throttled_fetch) -> str | None:
    """Return the newest game version listed on the wiki Patches page."""
    return extract_latest_patch(_fetch_wikitext("Patches", fetch_fn))


def check_and_mark_stale(fetch_fn: FetchFn = _throttled_fetch) -> bool:
    """Compare detected patch with cached one; mark all caches stale on change.

    Returns True when a new patch was detected and caches were invalidated.
    """
    latest = detect_latest_patch(fetch_fn)
    if latest is None:
        logger.info("patch detection found no versions; skipping")
        return False

    from app.db import AppState

    try:
        state = Session.query(AppState).filter_by(key="game_version").first()
        known = state.value if state else None
        if known == latest:
            return False
        Session.query(ItemCatalog).update({ItemCatalog.game_version: None})
        if state:
            state.value = latest
        else:
            Session.add(AppState(key="game_version", value=latest))
        Session.commit()
        logger.warning("new game patch %s detected; recipe cache invalidated", latest)
        return True
    finally:
        Session.remove()


__all__ = [
    "FetchFn",
    "ParsedRecipe",
    "cached_recipe",
    "check_and_mark_stale",
    "detect_latest_patch",
    "lookup_recipe",
    "parse_item_wikitext",
    "resolve_item",
    "store_in_cache",
]
