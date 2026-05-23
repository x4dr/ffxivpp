from __future__ import annotations

import logging
import os
from collections.abc import Callable
from functools import wraps
from typing import Any

import requests
from flask import (
    Blueprint,
    Response,
    current_app,
    make_response,
    redirect,
    request,
    session,
    url_for,
)
from flask_discord import DiscordOAuth2Session  # type: ignore[import-untyped]
from oauthlib.oauth2 import MismatchingStateError

from app.db import get_role_ids

logger = logging.getLogger(__name__)

bp = Blueprint("auth", __name__, url_prefix="/auth")


def get_discord() -> DiscordOAuth2Session:
    return DiscordOAuth2Session(current_app)


def _guild_id() -> str | None:
    return os.environ.get("GUILD_ID")


def _bot_token() -> str | None:
    return os.environ.get("DISCORD_BOT_TOKEN")


def _bot_api(method: str, path: str, json: dict[str, Any] | None = None) -> dict[str, Any] | None:
    token = _bot_token()
    if not token:
        return None
    r = requests.request(
        method,
        f"https://discord.com/api/v10{path}",
        headers={"Authorization": f"Bot {token}"},
        json=json,
        timeout=10,
    )
    return r.json() if r.status_code == 200 else None


def check_access() -> bool:
    discord = get_discord()
    if not discord.authorized:
        return False
    user = discord.fetch_user()
    user_id = str(user.id)
    guild_id = _guild_id()

    if not guild_id:
        return False

    guild = _bot_api("GET", f"/guilds/{guild_id}")
    if guild and guild.get("owner_id") == user_id:
        return True

    member = _bot_api("GET", f"/guilds/{guild_id}/members/{user_id}")
    if not member:
        return False
    member_roles = set(member["roles"])
    allowed = get_role_ids(guild_id)
    return bool(allowed and member_roles & allowed)


def require_admin(f: Callable[..., Response]) -> Callable[..., Response]:
    @wraps(f)
    def decorated(*args: Any, **kwargs: Any) -> Response:
        discord = get_discord()
        if not discord.authorized:
            return redirect(url_for("auth.login"))  # type: ignore[return-value]
        if not check_access():
            return make_response("Not authorized", 403)
        return f(*args, **kwargs)

    return decorated


@bp.route("/login")
def login() -> Response:
    return get_discord().create_session(scope=["identify", "guilds"])  # type: ignore[no-any-return]


@bp.route("/callback")
def callback() -> Response:
    url_state = request.values.get("state", "MISSING")
    session_state = session.get("DISCORD_OAUTH2_STATE", "MISSING")
    logger.info("OAuth callback — url_state=%s session_state=%s secret_key=%s...",
                url_state[:20], session_state[:20], current_app.secret_key[:10])
    try:
        get_discord().callback()
    except MismatchingStateError:
        logger.error("State mismatch — url=%s session=%s",
                     url_state[:30], session_state[:30])
        return make_response("OAuth state mismatch. Your session may have expired. "
                            "Please <a href='/auth/login'>log in again</a>.", 400)
    if check_access():
        return redirect(url_for("api.admin"))  # type: ignore[return-value]
    return make_response("You are not authorized to access the admin panel.", 403)


@bp.route("/logout")
def logout() -> Response:
    get_discord().revoke()
    return redirect(url_for("api.index"))  # type: ignore[return-value]
