"""HTTP surface for the trainer: static shell, icons, and optional saving.

Everything expensive happens in the browser. The routes below only serve the
page, proxy public game icons, and store a signed-in user's own copy.
"""

from __future__ import annotations

import base64
import binascii
import json
from typing import Any

from flask import Blueprint, Response, current_app, jsonify, make_response, request

from app.auth import get_discord
from app.trainer import icons, store

bp = Blueprint("trainer", __name__, url_prefix="/trainer")

KEYBIND_TYPE = 0x00650003
HOTBAR_TYPE = 0x00040002
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_SESSIONS_PER_SAVE = 200
MAX_ATTEMPTS_PER_SESSION = 1000
MAX_ATTEMPTS_PER_SAVE = 5000
MODS = frozenset({"SHIFT", "CTRL", "ALT"})
REASONS = frozenset({"OK", "WRONG_KEY", "MISSING_MOD", "EXTRA_MOD", "TIMEOUT"})
ICON_CACHE_HEADERS = {"Cache-Control": "public, max-age=31536000, immutable"}


def _current_user() -> dict[str, str] | None:
    """The signed-in Discord user, or None.

    The trainer itself is public: only saving requires this, and only the
    user's own row is ever touched.
    """
    discord = get_discord()
    if not discord.authorized:
        return None
    try:
        user = discord.fetch_user()
    except Exception:  # noqa: BLE001 - a broken OAuth session is "not signed in"
        return None
    user_id = str(user.id)
    name = getattr(user, "name", None) or user_id
    return {"id": user_id, "name": str(name)}


def _not_signed_in() -> tuple[Response, int]:
    return jsonify({"error": "not signed in"}), 401


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _loads(value: Any, fallback: Any) -> Any:
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


# ------------------------------------------------------------------- page


@bp.get("/")
@bp.get("/binds")
@bp.get("/hotbars")
@bp.get("/train")
@bp.get("/score")
def index() -> Response:
    """Every view is a real path, so URLs are shareable and survive a reload."""
    return current_app.send_static_file("trainer/index.html")


# ------------------------------------------------------------------ state


@bp.get("/api/state")
def get_state() -> Response | tuple[Response, int]:
    user = _current_user()
    if user is None:
        return _not_signed_in()

    store.ensure()
    user_id = user["id"]
    profile = store.load_profile(user_id)

    payload: dict[str, Any] = {
        "authenticated": True,
        "saved": profile is not None,
        "files": {},
        "selection": {},
        "order": {},
        "taught": {},
        "job_id": None,
        "stats": store.stats(user_id),
        "baseline_ms": store.baseline(user_id),
        "last_session": store.last_session(user_id),
        "saved_at": None,
    }

    if profile is not None:
        files: dict[str, Any] = payload["files"]
        if profile["keybind"]:
            files["keybind"] = {
                "name": profile["keybind_name"] or "KEYBIND.DAT",
                "b64": _b64(profile["keybind"]),
            }
        if profile["hotbar"]:
            files["hotbar"] = {
                "name": profile["hotbar_name"] or "HOTBAR.DAT",
                "b64": _b64(profile["hotbar"]),
            }
        payload["selection"] = _loads(profile["selection"], {})
        payload["order"] = _loads(profile["bar_order"], {})
        payload["taught"] = _loads(profile["taught"], {})
        payload["job_id"] = profile["job_id"]
        payload["saved_at"] = profile["updated_at"]

    return jsonify(payload)


# ------------------------------------------------------------------- save


@bp.post("/api/save")
def save() -> Response | tuple[Response, int]:
    user = _current_user()
    if user is None:
        return _not_signed_in()

    if request.content_length and request.content_length > 8 * 1024 * 1024:
        return jsonify({"error": "payload too large"}), 413

    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"error": "expected a JSON object"}), 400

    try:
        files = _files(body)
        selection = _int_lists(body.get("selection"), "selection")
        bar_order = _int_lists(body.get("order"), "order", preserve_order=True)
        taught = _taught(body.get("taught"))
        sessions = _sessions(body.get("sessions"))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    user_id = user["id"]
    store.ensure()
    keybind = files.get("keybind")
    hotbar = files.get("hotbar")
    store.save_profile(
        user_id,
        keybind=keybind[0] if keybind else None,
        keybind_name=keybind[1] if keybind else None,
        hotbar=hotbar[0] if hotbar else None,
        hotbar_name=hotbar[1] if hotbar else None,
        job_id=_job_id(body.get("job_id")),
        selection=selection,
        bar_order=bar_order,
        taught=taught,
    )
    saved = store.save_sessions(user_id, sessions)

    return jsonify(
        {
            "ok": True,
            "sessions_saved": saved,
            "stats": store.stats(user_id),
            "baseline_ms": store.baseline(user_id),
            "saved_at": store.now(),
        }
    )


def _files(body: dict[str, Any]) -> dict[str, tuple[bytes, str]]:
    """Decode and type-check the optional uploaded .DAT files."""
    out: dict[str, tuple[bytes, str]] = {}
    for kind, type_id in (("keybind", KEYBIND_TYPE), ("hotbar", HOTBAR_TYPE)):
        entry = body.get(kind)
        if entry is None:
            continue
        if not isinstance(entry, dict):
            raise ValueError(f"{kind}: expected an object")

        encoded = entry.get("b64")
        if not isinstance(encoded, str):
            raise ValueError(f"{kind}: b64 missing")
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError):
            raise ValueError(f"{kind}: not valid base64") from None

        if not raw:
            raise ValueError(f"{kind}: empty file")
        if len(raw) > MAX_FILE_BYTES:
            raise ValueError(f"{kind}: larger than {MAX_FILE_BYTES} bytes")
        if int.from_bytes(raw[:4], "little") != type_id:
            raise ValueError(f"{kind}: not the .DAT file this slot expects")

        name = entry.get("name")
        label = str(name)[:120] if isinstance(name, str) and name else "game file"
        out[kind] = (raw, label)
    return out


def _job_id(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 255:
        return value
    return None


def _int_lists(
    value: Any, field: str, *, preserve_order: bool = False
) -> dict[str, list[int]]:
    """Per-job bar picks or bar order: {job: [bar, ...]}.

    Bar order is meaningful: it is the order the rows are drawn in. Picks are
    sorted so equal selections compare equal.
    """
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{field}: expected an object")
    out: dict[str, list[int]] = {}
    for key, bars in list(value.items())[:100]:
        if not isinstance(bars, list):
            continue
        valid = [
            bar
            for bar in bars
            if isinstance(bar, int) and not isinstance(bar, bool) and 1 <= bar <= 10
        ]
        if preserve_order:
            out[str(key)[:16]] = list(dict.fromkeys(valid))
        else:
            out[str(key)[:16]] = sorted(set(valid))
    return out


def _taught(value: Any) -> dict[str, str]:
    """Bind name -> browser key code, for keys the importer could not name."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("taught: expected an object")
    out: dict[str, str] = {}
    for bind, code in list(value.items())[:500]:
        if not isinstance(bind, str) or not isinstance(code, str):
            continue
        if not bind or len(bind) > 64 or not code or len(code) > 40:
            continue
        out[bind] = code
    return out


def _sessions(value: Any) -> list[dict[str, Any]]:
    """Finished sessions with their attempts, cleaned to what is stored."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("sessions: expected a list")
    if len(value) > MAX_SESSIONS_PER_SAVE:
        raise ValueError(f"sessions: at most {MAX_SESSIONS_PER_SAVE} per save")

    out: list[dict[str, Any]] = []
    total_attempts = 0
    for raw in value:
        if not isinstance(raw, dict):
            continue
        client_id = raw.get("client_id")
        started_at = raw.get("started_at")
        if not isinstance(client_id, str) or not client_id or len(client_id) > 100:
            continue
        if not isinstance(started_at, str) or not started_at or len(started_at) > 40:
            continue

        try:
            duration_raw = raw.get("duration_s")
            if isinstance(duration_raw, bool) or not isinstance(duration_raw, (int, float)):
                continue
            duration = float(duration_raw)
        except (TypeError, ValueError):
            continue
        if not 1 <= duration <= 3600:
            continue

        raw_attempts = raw.get("attempts")
        if not isinstance(raw_attempts, list) or not raw_attempts:
            continue

        attempts = []
        for item in raw_attempts[:MAX_ATTEMPTS_PER_SESSION]:
            attempt = _attempt(item)
            if attempt is not None:
                attempts.append(attempt)
            if total_attempts + len(attempts) >= MAX_ATTEMPTS_PER_SAVE:
                break
        if not attempts:
            continue

        total_attempts += len(attempts)
        job_id = raw.get("job_id")
        job_label = raw.get("job_label")
        out.append(
            {
                "client_id": client_id,
                "job_id": _job_id(job_id),
                "job_label": str(job_label)[:20] if isinstance(job_label, str) else None,
                "started_at": started_at,
                "duration_s": duration,
                "attempts": attempts,
            }
        )
        if total_attempts >= MAX_ATTEMPTS_PER_SAVE:
            break
    return out


def _attempt(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    bind = item.get("bind")
    reason = item.get("reason")
    if not isinstance(bind, str) or not bind or len(bind) > 64:
        return None
    if reason not in REASONS:
        return None

    latency = item.get("latency_ms")
    if latency is not None and (
        not isinstance(latency, int)
        or isinstance(latency, bool)
        or not 0 <= latency <= 600_000
    ):
        return None

    mods = item.get("pressed_mods")
    pressed_mods = (
        [mod for mod in mods if isinstance(mod, str) and mod in MODS]
        if isinstance(mods, list)
        else []
    )
    code = item.get("pressed_code")
    name = item.get("name")
    label = item.get("label")
    at = item.get("at")

    return {
        "bind": bind,
        "name": str(name)[:120] if isinstance(name, str) else None,
        "label": str(label)[:120] if isinstance(label, str) else None,
        "correct": bool(item.get("correct")),
        "reason": reason,
        "latency_ms": latency,
        "pressed_code": code if isinstance(code, str) and len(code) <= 40 else None,
        "pressed_mods": pressed_mods,
        "at": str(at)[:40] if isinstance(at, str) else None,
    }


# ------------------------------------------------------------------ icons


def _icon_response(got: tuple[bytes, str] | None) -> Response | tuple[Response, int]:
    if got is None:
        return jsonify({"error": "no icon"}), 404
    blob, media_type = got
    response = make_response(blob)
    response.mimetype = media_type
    response.headers.update(ICON_CACHE_HEADERS)
    return response


@bp.get("/api/icon/<int:action_id>")
def get_icon(action_id: int) -> Response | tuple[Response, int]:
    return _icon_response(icons.icon_bytes(action_id))


@bp.get("/api/item-icon/<int:item_id>")
def get_item_icon(item_id: int) -> Response | tuple[Response, int]:
    icon_path = icons.item_icon_path(item_id)
    if icon_path is None:
        return jsonify({"error": "no such item"}), 404
    return _icon_response(icons.item_icon_bytes(item_id, icon_path))
