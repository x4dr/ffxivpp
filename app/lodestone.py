from __future__ import annotations

import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime, timedelta
from typing import Any

import requests as http
from bs4 import BeautifulSoup as BS

from app.db import cache_character, get_cached_character

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
                ts = datetime.fromisoformat(fetched_at).replace(tzinfo=UTC)
                if datetime.now(UTC) - ts < CACHE_TTL:
                    return cached
            except ValueError:
                pass

    data = _scrape_lodestone(lodestone_id)
    if data:
        cache_character(lodestone_id, data)
        return data

    return {"error": "Could not fetch character data."}


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

        # Class/job levels
        jobs: dict[str, dict[str, Any]] = {}
        for level_box in soup.select(".character__level"):
            for li in level_box.select(".character__level__list li"):
                img = li.select_one("img")
                if not img:
                    continue
                raw = img.get("data-tooltip") or img.get("alt") or ""
                jid = LODESTONE_TO_ID.get(_normalise_job_name(raw.split("/")[0].strip()))
                if not jid:
                    continue
                lv_text = li.get_text(strip=True)
                level = int(lv_text) if lv_text.isdigit() else 0
                if level > 0 and (jid not in jobs or level > jobs[jid].get("level", 0)):
                    jobs[jid] = {"level": level, "ilvl": None}

        # Average item level — fetch equipment tooltips in parallel for valid slots
        GEAR_SLOTS = [0, 1, 2, 3, 4, 6, 7, 8, 9, 10, 11, 12]
        avg_ilvl = None
        ilvls = []
        tip_urls = [f"{url}equipment/tooltip/{s}" for s in GEAR_SLOTS]
        with ThreadPoolExecutor(max_workers=8) as pool:
            fut_map = {
                pool.submit(http.get, u, timeout=10, headers={"User-Agent": "Mozilla/5.0"}): u
                for u in tip_urls
            }
            for fut in as_completed(fut_map):
                try:
                    resp2 = fut.result()
                    if resp2.status_code == 200:
                        tsoup = BS(resp2.text, "html.parser")
                        lvl_el = tsoup.select_one(".db-tooltip__item__level")
                        if lvl_el:
                            m = re.search(r"(\d+)", lvl_el.text)
                            if m:
                                ilvls.append(int(m.group(1)))
                except Exception:
                    continue
        if ilvls:
            avg_ilvl = round(sum(ilvls) / len(ilvls))

        return {
            "lodestone_id": lodestone_id,
            "name": char_name,
            "server": server,
            "portrait": portrait,
            "avg_ilvl": avg_ilvl,
            "jobs": jobs,
            "gear": {},
            "source": "lodestone",
        }
    except Exception as e:
        logger.warning("Lodestone scrape error for %s: %s", lodestone_id, e)
        return None
