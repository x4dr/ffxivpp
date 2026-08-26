"""Tests for core.wiki using the real Baked Eggplant wikitext fixture."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from core import wiki
from core.questdb import ItemCatalog

FIXTURE = Path(__file__).parent / "fixtures" / "baked_eggplant.wikitext"


@pytest.fixture
def wikitext() -> str:
    return FIXTURE.read_text()


class TestParse:
    def test_baked_eggplant_recipe(self, wikitext: str) -> None:
        parsed = wiki.parse_item_wikitext(wikitext, "Baked Eggplant")
        assert parsed.item_id == 39872
        assert parsed.name == "Baked Eggplant"
        assert parsed.job == "Culinarian"
        assert parsed.level == 90
        assert parsed.yield_qty == 3
        by_name = {name: qty for _iid, name, qty in parsed.ingredients}
        assert by_name["Dark Eggplant"] == 1
        assert by_name["Garlean Cheese"] == 2
        assert by_name["Earthbreak Aethersand"] >= 1
        # all ingredients get a zero placeholder id until resolved
        assert all(iid == 0 for iid, _n, _q in parsed.ingredients)

    def test_non_craftable_raises(self) -> None:
        plain = "{{Item infobox\n| name = Cobblestone\n| id-gt = 5\n}}\nNo recipe here."
        with pytest.raises(ValueError, match="no crafting recipe"):
            wiki.parse_item_wikitext(plain, "Cobblestone")

    def test_missing_id_raises(self) -> None:
        with pytest.raises(ValueError, match="no numeric item id"):
            wiki.parse_item_wikitext("{{Item infobox\n| name = X\n}}", "X")


class TestPatchDetection:
    def test_detects_highest_version(self) -> None:
        page = (
            "* [[Patch 7.0]]\n* [[Patch 7.31]]\n"
            "* [[Patch 6.58]]\n* [[Patch_8.0]]\n* Patch 10.19 notes\n"
        )
        assert wiki.extract_latest_patch(page) == "10.19"

    def test_no_patches_returns_none(self) -> None:
        assert wiki.extract_latest_patch("nothing here") is None

    def test_patch_change_invalidates_cache(self, db_session: Any) -> None:  # noqa: ARG002
        from app.db import AppState, Session

        Session.merge(
            ItemCatalog(item_id=1, name="Old Item", game_version="7.3",
                        fetched_at="0", recipe_json=None, flags_json="{}")
        )
        Session.add(AppState(key="game_version", value="7.3"))
        Session.commit()

        page = json.dumps({"parse": {"wikitext": "* [[Patch 7.4]]\n"}})
        changed = wiki.check_and_mark_stale(lambda _url: page)
        assert changed is True
        row = Session.query(ItemCatalog).filter_by(item_id=1).first()
        assert row is not None and row.game_version is None
        state = Session.query(AppState).filter_by(key="game_version").first()
        assert state is not None and state.value == "7.4"

        # same patch again -> no-op
        assert wiki.check_and_mark_stale(lambda _url: page) is False


class TestCacheFirstLookup:
    def test_cached_hit_skips_network(self, db_session: Any) -> None:  # noqa: ARG002
        from app.db import Session

        Session.merge(
            ItemCatalog(
                item_id=39872,
                name="Baked Eggplant",
                game_version="7.3",
                fetched_at="0",
                flags_json="{}",
                recipe_json=json.dumps(
                    {"job": "Culinarian", "level": 90, "yield": 3,
                     "ingredients": [[0, "Dark Eggplant", 1]]}
                ),
            )
        )
        Session.commit()

        def boom(_url: str) -> str:
            raise AssertionError("network must not be touched on cache hit")

        parsed = wiki.lookup_recipe("baked eggplant", fetch_fn=boom)
        assert parsed.item_id == 39872
        assert parsed.yield_qty == 3

    def test_miss_fetches_and_stores(self, db_session: Any, wikitext: str) -> None:  # noqa: ARG002
        calls: list[str] = []

        def fake_fetch(url: str) -> str:
            calls.append(url)
            return json.dumps({"parse": {"wikitext": wikitext}})

        parsed = wiki.lookup_recipe("Baked Eggplant", fetch_fn=fake_fetch)
        assert parsed.item_id == 39872
        assert len(calls) == 1
        from app.db import Session

        row = Session.query(ItemCatalog).filter_by(item_id=39872).first()
        assert row is not None  # stored for next time
