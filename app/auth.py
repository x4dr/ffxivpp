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

from app.db import bot_owner_id, get_role_ids

for _lib in ("requests_oauthlib", "oauthlib", "urllib3"):
    logging.getLogger(_lib).setLevel(logging.WARNING)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

bp = Blueprint("auth", __name__, url_prefix="/auth")


def get_discord() -> DiscordOAuth2Session:
    if os.environ.get("TEST_MOCK_AUTH") == "1":
        class MockUser:
            id = "12345"
        class MockDiscord:
            authorized = True
            def fetch_user(self) -> MockUser:
                return MockUser()
            def create_session(self, scope: list[str]) -> None:
                return None
            def callback(self) -> None:
                return None
            def revoke(self) -> None:
                return None
        return MockDiscord() # type: ignore
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
    print(f"DEBUG: check_access discord.authorized={discord.authorized}")
    if not discord.authorized:
        logger.info("check_access: Not authorized (no session)")
        return False
    user = discord.fetch_user()
    user_id = str(user.id)
    guild_id = _guild_id()
    print(f"DEBUG: check_access user_id={user_id}, guild_id={guild_id}, bot_owner={bot_owner_id()}")
    logger.info("check_access: Checking user_id=%s, guild_id=%s", user_id, guild_id)

    if bot_owner_id() == user_id:
        logger.info("check_access: User is bot owner")
        return True

    if not guild_id:
        logger.info("check_access: No guild_id defined")
        return False

    guild = _bot_api("GET", f"/guilds/{guild_id}")
    if guild:
        logger.info("check_access: Guild API response: owner_id=%s", guild.get("owner_id"))
        if guild.get("owner_id") == user_id:
            logger.info("check_access: User is guild owner")
            return True
    else:
        logger.info("check_access: Guild API failed")

    member = _bot_api("GET", f"/guilds/{guild_id}/members/{user_id}")
    if not member:
        logger.info("check_access: Member lookup failed or user not in guild")
        return False

    member_roles = set(member["roles"])
    allowed = get_role_ids(guild_id)
    logger.info("check_access: Member roles=%s, allowed_roles=%s", member_roles, allowed)

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


def check_party_access(party_name: str) -> bool:
    print(f"DEBUG: check_party_access checking party={party_name}")
    is_access = check_access()
    print(f"DEBUG: check_access returned {is_access}")
    if is_access:
        return True
    discord = get_discord()
    print(f"DEBUG: discord.authorized={discord.authorized}")
    if not discord.authorized:
        return False
    user = discord.fetch_user()
    from app.db import check_party_member
    is_member = check_party_member(str(user.id), party_name)
    print(f"DEBUG: user={user.id}, is_member={is_member}")
    return is_member


def require_party_member(f: Callable[..., Response]) -> Callable[..., Response]:
    @wraps(f)
    def decorated(*args: Any, **kwargs: Any) -> Response:
        # Check kwargs (from route path), then query args, then JSON body
        party_name = kwargs.get("party_name") or request.args.get("party_name")
        if not party_name:
            data = request.get_json(silent=True)
            if isinstance(data, dict):
                party_name = data.get("party_name")
        
        # Fallback to active party from DB if not provided
        if not party_name:
            from app.db import active_party_name
            party_name = active_party_name()
        
        logger.info("require_party_member: found party_name=%s", party_name)
        
        discord = get_discord()
        if not discord.authorized:
            return redirect(url_for("auth.login"))  # type: ignore[return-value]
        if not party_name or not check_party_access(party_name):
            return make_response("Not authorized", 403)
            
        # Pass party_name to the function if it expects it
        if "party_name" in kwargs:
            return f(*args, **kwargs)
        return f(party_name=party_name, *args, **kwargs)

    return decorated


@bp.route("/login")
def login() -> Response:
    return get_discord().create_session(scope=["identify", "guilds"])  # type: ignore[no-any-return]


@bp.route("/callback")
def callback() -> Response:
    url_state = request.values.get("state", "MISSING")
    session_state = session.get("DISCORD_OAUTH2_STATE", "MISSING")
    logger.info("OAuth callback — url_state=%s session_state=%s",
                url_state[:20], session_state[:20])
    try:
        get_discord().callback()
    except MismatchingStateError:
        logger.error("State mismatch — url=%s session=%s",
                     url_state[:30], session_state[:30])
        return make_response("OAuth state mismatch. Your session may have expired. "
                            "Please <a href='/auth/login'>log in again</a>.", 400)
    if check_access():
        return redirect(url_for("api.party_overview", party_name="Default"))  # type: ignore[return-value]
    return make_response("You are not authorized to access the Party Planner Dashboard.", 403)


@bp.route("/logout")
def logout() -> Response:
    get_discord().revoke()
    return redirect(url_for("api.index"))  # type: ignore[return-value]
