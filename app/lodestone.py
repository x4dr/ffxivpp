from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import requests as http
from bs4 import BeautifulSoup as BS

from app.db import cache_character, get_cached_character, get_db

logger = logging.getLogger(__name__)

CACHE_TTL = timedelta(hours=3)
RATE_LIMIT_SEC = 10

_last_fetch: float = 0.0


def _wait_rate_limit() -> None:
    global _last_fetch
    now = time.monotonic()
    elapsed = now - _last_fetch
    if elapsed < RATE_LIMIT_SEC:
        time.sleep(RATE_LIMIT_SEC - elapsed)
    _last_fetch = time.monotonic()


# ── Job ID mapping (Lodestone English job name → our job ID) ──────────

LODESTONE_TO_ID: dict[str, str] = {
    "paladin": "pld", "warrior": "war", "dark knight": "drk", "gunbreaker": "gnb",
    "white mage": "whm", "scholar": "sch", "astrologian": "ast", "sage": "sge",
    "monk": "mnk", "dragoon": "drg", "ninja": "nin", "samurai": "sam", "viper": "vpr",
    "bard": "brd", "machinist": "mch", "dancer": "dnc",
    "black mage": "blm", "summoner": "smn", "red mage": "rdm", "pictomancer": "pct",
    "carpenter": "crp", "blacksmith": "bsm", "armorer": "arm", "goldsmith": "gsm",
    "leatherworker": "lw", "weaver": "wvr", "alchemist": "alc", "culinarian": "cul",
    "miner": "min", "botanist": "bot", "fisher": "fs",
}


def _normalise_job_name(raw: str) -> str:
    name = raw.strip().lower().replace("\u2019", "'").replace("'", "")
    return name.split(" / ")[0].split("/")[0].strip()


# ── Character fetch ───────────────────────────────────────────────────


def fetch_character(lodestone_id: str) -> dict[str, Any]:
    cached = get_cached_character(lodestone_id)
    if cached:
        fetched_at = cached.get("fetched_at", "") or ""
        if fetched_at:
            try:
                ts = datetime.fromisoformat(fetched_at)
                if datetime.now(timezone.utc) - ts < CACHE_TTL:
                    return cached
            except ValueError:
                pass

    data = _try_xivapi(lodestone_id)
    if data:
        cache_character(lodestone_id, data)
        return data

    data = _scrape_lodestone(lodestone_id)
    if data:
        cache_character(lodestone_id, data)
        return data

    return {"error": "Could not fetch character data."}


def _try_xivapi(lodestone_id: str) -> dict[str, Any] | None:
    _wait_rate_limit()
    try:
        resp = http.get(
            f"https://xivapi.com/character/{lodestone_id}?data=AC",
            timeout=15,
            headers={"User-Agent": "FF14PartyPlanner/1.0"},
        )
        if resp.status_code != 200:
            logger.warning("XIVAPI returned %s for %s", resp.status_code, lodestone_id)
            return None
        body = resp.json()
        char = body.get("Character")
        if not char:
            return None

        char_name = char.get("Name", "Unknown")
        jobs: dict[str, dict[str, Any]] = {}
        for cj in char.get("ClassJobs") or []:
            jn = cj.get("Job", {}).get("Name") or cj.get("UnlockedState", {}).get("Name", "")
            jid = LODESTONE_TO_ID.get(_normalise_job_name(jn))
            level = cj.get("Level", 0)
            ilvl = cj.get("ItemLevel", 0)
            if jid:
                jobs[jid] = {"level": level, "ilvl": ilvl}

        gear = char.get("GearSet", {}) or {}
        gear_items: dict[str, Any] = {}
        for slot, item in (gear.get("Gear") or {}).items():
            gear_items[slot] = {
                "name": item.get("Name", "?"),
                "ilvl": item.get("ILvl", 0),
                "category": item.get("ItemCategory", {}).get("Name", ""),
            }

        avg_ilvl = (gear.get("ItemLevel") or 0) or None

        data = {
            "lodestone_id": lodestone_id,
            "name": char_name,
            "server": char.get("Server", ""),
            "portrait": char.get("Portrait", ""),
            "avg_ilvl": avg_ilvl,
            "jobs": jobs,
            "gear": gear_items,
            "source": "xivapi",
        }
        return data
    except Exception as e:
        logger.warning("XIVAPI error for %s: %s", lodestone_id, e)
        return None


def _scrape_lodestone(lodestone_id: str) -> dict[str, Any] | None:
    _wait_rate_limit()
    url = f"https://eu.finalfantasyxiv.com/lodestone/character/{lodestone_id}/"
    try:
        resp = http.get(
            url,
            timeout=15,
            headers={"User-Agent": "Mozilla/5.0 (compatible; FF14PartyPlanner/1.0)"},
        )
        if resp.status_code != 200:
            logger.warning("Lodestone returned %s for %s", resp.status_code, lodestone_id)
            return None
        soup = BS(resp.text, "html.parser")

        name_el = soup.select_one(".frame__chara__name")
        char_name = name_el.text.strip() if name_el else "Unknown"

        world_el = soup.select_one(".frame__chara__world")
        server = world_el.text.strip() if world_el else ""

        portrait_el = soup.select_one(".character__detail__image img")
        portrait = portrait_el.get("src", "") if portrait_el else ""

        # Average item level — search near the name/header area
        avg_ilvl: int | None = None
        for el in soup.select("[class*=average] [class*=level], .character__average__level__value"):
            txt = el.text.strip()
            if txt.isdigit():
                avg_ilvl = int(txt)
                break
        if avg_ilvl is None:
            for tag in soup.find_all(string=re.compile(r"[Aa]verage.*[Ii]tem.*[Ll]evel|[Ii]tem.*[Ll]evel.*[0-9]{3}")):
                m = re.search(r"([0-9]{3,4})", tag)
                if m:
                    avg_ilvl = int(m.group(1))
                    break

        # Class/job levels
        jobs: dict[str, dict[str, Any]] = {}
        for level_box in soup.select(".character__level"):
            items = level_box.select(".character__level__list li")
            for li in items:
                img = li.select_one("img")
                if not img:
                    continue
                raw = img.get("data-tooltip") or img.get("alt") or ""
                jid = LODESTONE_TO_ID.get(_normalise_job_name(raw.split("/")[0].strip()))
                if not jid:
                    continue
                lv_text = li.get_text(strip=True)
                level = 0
                if lv_text.isdigit():
                    level = int(lv_text)
                if level > 0:
                    if jid not in jobs or level > jobs[jid].get("level", 0):
                        jobs[jid] = {"level": level, "ilvl": None}

        data = {
            "lodestone_id": lodestone_id,
            "name": char_name,
            "server": server,
            "portrait": portrait,
            "avg_ilvl": avg_ilvl,
            "jobs": jobs,
            "gear": {},
            "source": "lodestone",
        }
        return data
    except Exception as e:
        logger.warning("Lodestone scrape error for %s: %s", lodestone_id, e)
        return None
