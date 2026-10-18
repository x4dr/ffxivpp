"""Icon proxy with a disk cache.

Icons are the one thing the public trainer asks the server for. They are game
art, not personal data, and proxying them means the browser does not depend on
xivapi's CORS policy or on a client-side cache.

An action's icon path is only reachable through xivapi, so a request fetches
the action row once and caches the PNG. A definitive 404 is cached too;
otherwise every page load retries the same dead id. Network errors are not
cached, because a timeout may pass.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from app.db import BASE_DIR

XIVAPI = "https://xivapi.com"
XIVAPI_V2 = "https://v2.xivapi.com"
USER_AGENT = "ffxivpp-trainer/0.1"


def _data_dir() -> Path:
    override = os.environ.get("TRAINER_DATA_DIR")
    if override:
        return Path(override).expanduser()
    return BASE_DIR / "data" / "trainer"


ICON_CACHE = _data_dir() / "icon_cache"
ITEM_INDEX = BASE_DIR / "static" / "trainer" / "data" / "item_index.json"


def item_icon_path(base_id: int) -> str | None:
    """Icon path for an item, from the bundled index."""
    try:
        with ITEM_INDEX.open(encoding="utf-8") as fh:
            items = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    entry = items.get(str(base_id))
    if not isinstance(entry, dict):
        return None
    icon = entry.get("icon")
    return icon if isinstance(icon, str) else None


def _mark_missing(name: str) -> None:
    try:
        ICON_CACHE.mkdir(parents=True, exist_ok=True)
        (ICON_CACHE / f"{name}.missing").touch()
    except OSError:
        pass


def icon_bytes(action_id: int) -> tuple[bytes, str] | None:
    """PNG bytes for an action id, cached on disk."""
    ICON_CACHE.mkdir(parents=True, exist_ok=True)
    cached = ICON_CACHE / f"{action_id}.png"
    if cached.exists():
        return cached.read_bytes(), "image/png"
    if (ICON_CACHE / f"{action_id}.missing").exists():
        return None

    try:
        req = urllib.request.Request(
            f"{XIVAPI}/action/{action_id}",
            headers={"Accept": "application/json", "User-Agent": USER_AGENT},
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            _mark_missing(str(action_id))
        return None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None

    path = data.get("IconHD") or data.get("Icon")
    if not path:
        _mark_missing(str(action_id))
        return None

    try:
        req = urllib.request.Request(
            XIVAPI + path, headers={"User-Agent": USER_AGENT}
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            blob = resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            _mark_missing(str(action_id))
        return None
    except (urllib.error.URLError, TimeoutError, OSError):
        return None

    try:
        cached.write_bytes(blob)
    except OSError:
        pass
    return blob, "image/png"


def item_icon_bytes(base_id: int, icon_path: str) -> tuple[bytes, str] | None:
    """PNG bytes for an item, through XIVAPI v2 and cached on disk.

    The cache key carries an item- prefix because an item id and an action id
    can be the same number.
    """
    ICON_CACHE.mkdir(parents=True, exist_ok=True)
    cached = ICON_CACHE / f"item-{base_id}.png"
    if cached.exists():
        return cached.read_bytes(), "image/png"
    if (ICON_CACHE / f"item-{base_id}.missing").exists():
        return None

    query = urllib.parse.urlencode({"path": icon_path, "format": "png"})
    try:
        req = urllib.request.Request(
            f"{XIVAPI_V2}/api/asset?{query}",
            headers={"Accept": "image/png", "User-Agent": USER_AGENT},
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            blob = resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            _mark_missing(f"item-{base_id}")
        return None
    except (urllib.error.URLError, TimeoutError, OSError):
        return None

    try:
        cached.write_bytes(blob)
    except OSError:
        pass
    return blob, "image/png"
