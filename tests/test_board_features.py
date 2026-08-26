"""Tests for board features: re-expand, SSE stream, price hints, reminders,
deadline editing (scratch/2026-08-27-boardfeat-task.md task list).

No test touches the network: wiki lookups are faked at ``app.questboard``'s
imported symbol and Universalis at ``app.questboard._universalis_json``.
"""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.questboard import STREAM_POLL_SECONDS, _sse_events, api_stream
from core import questdb


@pytest.fixture
def officer(qb_auth, monkeypatch: pytest.MonkeyPatch):  # noqa: ANN001 - conftest fixture
    """Officer context: authenticated user whose check_access() is True.

    Patches check_access in BOTH namespaces: app.auth (where require_admin's
    decorator resolves it) and app.questboard (imported into _current_user).
    """
    monkeypatch.setattr("app.auth.check_access", lambda: True)
    monkeypatch.setattr("app.questboard.check_access", lambda: True)
    yield


@pytest.fixture
def unauthed(monkeypatch: pytest.MonkeyPatch):
    """Make every auth path report unauthorized."""
    monkeypatch.delenv("TEST_MOCK_AUTH", raising=False)
    discord = MagicMock()
    discord.authorized = False
    # questboard's _current_user resolves get_discord through its own namespace
    monkeypatch.setattr("app.questboard.get_discord", lambda: discord)
    yield


@pytest.fixture
def non_officer(monkeypatch: pytest.MonkeyPatch):
    """Authenticated guild member WITHOUT officer rights."""
    monkeypatch.setenv("TEST_MOCK_AUTH", "1")
    monkeypatch.setattr("app.auth.check_access", lambda: False)
    monkeypatch.setattr("app.questboard.check_access", lambda: False)
    yield


def base_tree() -> dict[str, Any]:
    return {
        "item_id": 555,
        "name": "wheel",
        "qty_required": 400,
        "quality": "any",
        "children": [
            {
                "item_id": 1,
                "name": "log",
                "qty_required": 2000,
                "quality": "any",
                "source": "auto",
                "children": [],
            }
        ],
    }


@pytest.fixture
def quest_with_tree() -> int:
    return questdb.create_quest(
        title="re-expand me",
        description="",
        created_by="111",
        root_tree=base_tree(),
    )


# --- task 1: re-expand ------------------------------------------------------


class TestReexpand:
    def _fake_parsed(self):
        from core.wiki import ParsedRecipe

        return ParsedRecipe(
            item_id=555,
            name="wheel",
            job=None,
            level=None,
            yield_qty=10,
            ingredients=[(0, "ore", 5), (0, "coal", 2)],
        )

    def test_merge_appends_only_missing_children(
        self, client, officer, quest_with_tree, monkeypatch
    ) -> None:
        parsed = self._fake_parsed()
        monkeypatch.setattr("app.questboard.lookup_recipe", lambda _name: parsed)
        resp = client.post(f"/quests/api/{quest_with_tree}/reexpand", json={})
        assert resp.status_code == 200
        assert resp.json["added"] == 2
        quest = questdb.get_quest(quest_with_tree)
        names = [c["name"] for c in quest["tree"]["children"]]
        assert names == ["log", "ore", "coal"]  # existing kept + appended, order stable

    def test_pledges_survive_reexpand(
        self, client, officer, quest_with_tree, monkeypatch
    ) -> None:
        questdb.add_pledge(quest_with_tree, "n1", "222", 500, actor_id="222")
        parsed = self._fake_parsed()
        monkeypatch.setattr("app.questboard.lookup_recipe", lambda _name: parsed)
        client.post(f"/quests/api/{quest_with_tree}/reexpand", json={})

        from app.questboard import _tree_from_stored
        from core.quests import assign_node_ids, node_statuses

        quest = questdb.get_quest(quest_with_tree)
        root = _tree_from_stored(quest["tree"])
        assign_node_ids(root)
        pledges, turned = questdb.quest_amounts(quest_with_tree)
        statuses = node_statuses(root, pledges, turned)
        log = next(s for s in statuses.values() if s.name == "log")
        assert log.pledged == 500
        coal = next(s for s in statuses.values() if s.name == "coal")
        assert coal.open_to_pledge == coal.required

    def test_second_run_adds_nothing(
        self, client, officer, quest_with_tree, monkeypatch
    ) -> None:
        parsed = self._fake_parsed()
        monkeypatch.setattr("app.questboard.lookup_recipe", lambda _name: parsed)
        client.post(f"/quests/api/{quest_with_tree}/reexpand", json={})
        resp2 = client.post(f"/quests/api/{quest_with_tree}/reexpand", json={})
        assert resp2.json["added"] == 0

    def test_wiki_failure_degrades(
        self, client, officer, quest_with_tree, monkeypatch
    ) -> None:
        def boom(_name):
            raise LookupError("wiki down")

        monkeypatch.setattr("app.questboard.lookup_recipe", boom)
        resp = client.post(f"/quests/api/{quest_with_tree}/reexpand", json={})
        assert resp.status_code == 200
        assert resp.json["added"] == 0

    def test_unknown_quest_404(self, client, officer) -> None:
        assert client.post("/quests/api/99999/reexpand", json={}).status_code == 404

    def test_requires_officer(self, client, non_officer, quest_with_tree) -> None:
        resp = client.post(f"/quests/api/{quest_with_tree}/reexpand", json={})
        assert resp.status_code == 403

    def test_manual_root_expanded_by_name(
        self, client, officer, monkeypatch
    ) -> None:
        """item_id=0 manual roots may be retroactively expanded via their name."""
        from core.wiki import ParsedRecipe

        qid = questdb.create_quest(
            title="manual",
            description="",
            created_by="111",
            root_tree={
                "item_id": 0,
                "name": "wheel",
                "qty_required": 10,
                "quality": "any",
                "children": [],
            },
        )
        parsed = ParsedRecipe(
            item_id=555,
            name="wheel",
            job=None,
            level=None,
            yield_qty=5,
            ingredients=[(0, "ore", 2)],
        )
        monkeypatch.setattr("app.questboard.lookup_recipe", lambda _n: parsed)
        resp = client.post(f"/quests/api/{qid}/reexpand", json={})
        assert resp.json["added"] == 1
        children = questdb.get_quest(qid)["tree"]["children"]
        assert [(c["name"], c["qty_required"]) for c in children] == [("ore", 4)]

    def test_id_mismatch_not_merged(self, client, officer, monkeypatch) -> None:
        """A resolved item whose id differs from a NON-zero stored id is skipped."""
        from core.wiki import ParsedRecipe

        qid = questdb.create_quest(
            title="other item",
            description="",
            created_by="111",
            root_tree=base_tree(),  # item_id 555, name 'wheel'
        )
        other = ParsedRecipe(
            item_id=999,
            name="wheel",
            job=None,
            level=None,
            yield_qty=5,
            ingredients=[(0, "coal", 2)],
        )
        monkeypatch.setattr("app.questboard.lookup_recipe", lambda _n: other)
        assert client.post(f"/quests/api/{qid}/reexpand", json={}).json["added"] == 0
        # tree untouched
        assert len(questdb.get_quest(qid)["tree"]["children"]) == 1

    def test_logged_event(self, client, officer, quest_with_tree, monkeypatch) -> None:
        parsed = self._fake_parsed()
        monkeypatch.setattr("app.questboard.lookup_recipe", lambda _name: parsed)
        client.post(f"/quests/api/{quest_with_tree}/reexpand", json={})
        kinds = [e["kind"] for e in questdb.quest_events(quest_with_tree)]
        assert "tree_reexpanded" in kinds


# --- task 2: SSE stream -----------------------------------------------------


class TestSseStream:
    def test_change_version_bumps_on_mutations(self, quest_with_tree) -> None:
        before = questdb.change_version()
        qid = questdb.create_quest(title="t", description="", created_by="1", root_tree=base_tree())
        pid = questdb.add_pledge(qid, "n0", "222", 3, actor_id="222")
        assert questdb.withdraw_pledge(pid, "222")
        assert questdb.mark_turned_in(pid, "222") is False  # withdrawn -> no bump
        assert questdb.set_quest_status(qid, questdb.QUEST_FULFILLED, "1")
        assert questdb.update_quest_tree(qid, base_tree(), "1", added_nodes=0)
        assert questdb.set_quest_deadline(qid, "2026-09-01", "1")
        assert questdb.change_version() >= before + 4

    def test_generator_emits_event_after_mutation(self, quest_with_tree) -> None:
        gen = _sse_events(poll_seconds=0.01, max_events=1)
        first = next(gen)
        assert first == f"retry: {int(STREAM_POLL_SECONDS * 3000)}\n\n"
        questdb.add_pledge(quest_with_tree, "n1", "222", 5, actor_id="222")
        event = next(gen)
        assert "event: quest-changed" in event
        assert '"version"' in event.split("data: ")[1]

    def test_endpoint_gating(self, app, officer) -> None:  # noqa: ARG002
        with app.test_request_context("/quests/api/stream"):
            assert api_stream().mimetype == "text/event-stream"

    def test_stream_requires_auth(self, app, unauthed) -> None:
        with app.test_request_context("/quests/api/stream"):
            assert api_stream().status_code == 401

    def test_board_page_subscribes(self, client, officer, quest_with_tree) -> None:
        html = client.get("/quests/").get_data(as_text=True)
        assert "EventSource('/quests/api/stream')" in html
        assert "quest-changed" in html


# --- task 3: universalis price hints ----------------------------------------


class FakeUniversalis:
    """Stands in for app.questboard._universalis_json (network boundary)."""

    def __init__(self, shape: str = "dc") -> None:
        self.calls: list[str] = []
        self.shape = shape

    def __call__(self, path: str) -> dict[str, Any]:
        self.calls.append(path)
        item_id = path.rsplit("/", 1)[-1]
        entry: dict[str, Any] = {"minListingNQ": 123, "minListingHQ": 456}
        if self.shape == "flat":
            entry.update(itemID=int(item_id))
            return entry
        return {"items": {item_id: entry}}


class TestPriceEndpoint:
    def test_proxy_shape_and_caching(self, client, officer, monkeypatch) -> None:
        from app import questboard

        questboard._price_cache.clear()
        fake = FakeUniversalis()
        monkeypatch.setattr(questboard, "_universalis_json", fake)
        monkeypatch.setattr(questboard, "_resolve_item_id", lambda _n: 42)

        first = client.get("/quests/api/price/Iron%20Ore")
        assert first.status_code == 200
        price = first.json["price"]
        assert price["item_id"] == 42
        assert price["min_listing_nq"] == 123
        assert price["server"] == "Alpha"  # DC_SERVER default

        second = client.get("/quests/api/price/Iron%20Ore")
        assert second.json["price"] == price
        assert fake.calls == ["/Alpha/42"]  # cached: no second market hit

    def test_flat_single_world_shape_supported(self, client, officer, monkeypatch) -> None:
        from app import questboard

        questboard._price_cache.clear()
        monkeypatch.setattr(questboard, "_universalis_json", FakeUniversalis(shape="flat"))
        monkeypatch.setattr(questboard, "_resolve_item_id", lambda _n: 42)
        price = client.get("/quests/api/price/Iron%20Ore").json["price"]
        assert price["min_listing_nq"] == 123

    def test_resolution_uses_catalog_then_wiki(self, client, officer, monkeypatch) -> None:
        from app import questboard
        from app.db import Session
        from core.questdb import ItemCatalog

        try:
            Session.merge(
                ItemCatalog(item_id=7, name="Cobalt Ore", flags_json="{}", fetched_at="0")
            )
            Session.commit()
        finally:
            Session.remove()

        calls: list[str] = []

        def fail_lookup(name: str):
            calls.append(name)
            raise LookupError("not on the wiki")

        monkeypatch.setattr(questboard, "_universalis_json", FakeUniversalis())
        monkeypatch.setattr(questboard, "lookup_recipe", fail_lookup)

        # catalog hit: wiki never consulted
        assert client.get("/quests/api/price/cobalt%20ore").json["price"]["item_id"] == 7
        assert calls == []

        # catalog miss: wiki resolver used; failure degrades to no hint
        assert client.get("/quests/api/price/Grey%20Item").json["price"] is None
        assert calls == ["Grey Item"]

    def test_ttl_expiry_refetches(self, client, officer, monkeypatch) -> None:
        from app import questboard

        questboard._price_cache.clear()
        fake = FakeUniversalis()
        monkeypatch.setattr(questboard, "_universalis_json", fake)
        monkeypatch.setattr(questboard, "_resolve_item_id", lambda _n: 42)
        client.get("/quests/api/price/Iron%20Ore")
        assert fake.calls.count("/Alpha/42") == 1

        key = ("Alpha", "iron ore")
        _expires, payload = questboard._price_cache[key]
        questboard._price_cache[key] = (time.monotonic() - 0.01, payload)
        client.get("/quests/api/price/Iron%20Ore")
        assert fake.calls.count("/Alpha/42") == 2

    def test_degrades_to_none_on_universalis_failure(
        self, client, officer, monkeypatch
    ) -> None:
        from app import questboard

        questboard._price_cache.clear()

        def broken(_path: str) -> dict[str, Any]:
            raise OSError("network down")

        monkeypatch.setattr(questboard, "_universalis_json", broken)
        monkeypatch.setattr(questboard, "_resolve_item_id", lambda _n: 42)
        resp = client.get("/quests/api/price/Iron%20Ore")
        assert resp.status_code == 200
        assert resp.json["ok"] is True
        assert resp.json["price"] is None

    def test_dc_server_env_override(self, client, officer, monkeypatch) -> None:
        from app import questboard

        questboard._price_cache.clear()
        fake = FakeUniversalis()
        monkeypatch.setattr(questboard, "_universalis_json", fake)
        monkeypatch.setattr(questboard, "_resolve_item_id", lambda _n: 42)
        monkeypatch.setenv("DC_SERVER", "Phoenix")
        price = client.get("/quests/api/price/Iron%20Ore").json["price"]
        assert price["server"] == "Phoenix"
        assert "/Phoenix/42" in fake.calls[-1]

    def test_price_requires_auth(self, client, unauthed) -> None:
        assert client.get("/quests/api/price/wheel").status_code == 401

    def test_detail_page_has_price_chips(self, client, officer, quest_with_tree) -> None:
        html = client.get(f"/quests/{quest_with_tree}").get_data(as_text=True)
        assert "price-hint" in html
        assert 'data-item-name="wheel"' in html


# --- task 4: reminder toggle -------------------------------------------------


class TestReminderToggle:
    def test_toggle_on_then_off(self, client, officer) -> None:
        qid = questdb.create_quest(
            title="remindme", description="", created_by="111", root_tree=base_tree()
        )
        on = client.post(f"/quests/api/{qid}/remind", json={})
        assert on.status_code == 200
        assert on.json["opted_in"] is True
        reminder = questdb.get_reminder_optin(qid, "12345")
        assert reminder is not None
        assert (reminder["frequency"], reminder["hour_utc"]) == ("daily", 18)

        off = client.post(f"/quests/api/{qid}/remind", json={})
        assert off.json["opted_in"] is False
        assert questdb.get_reminder_optin(qid, "12345") is None

    def test_explicit_schedule_honoured(self, client, officer) -> None:
        qid = questdb.create_quest(
            title="weekly", description="", created_by="111", root_tree=base_tree()
        )
        body = {"frequency": "weekly", "hour_utc": 9, "minute_utc": 30, "weekday_utc": 2}
        client.post(f"/quests/api/{qid}/remind", json=body)
        reminder = questdb.get_reminder_optin(qid, "12345")
        assert reminder is not None
        assert reminder["weekday_utc"] == 2

    def test_invalid_frequency_400(self, client, officer) -> None:
        qid = questdb.create_quest(
            title="badfreq", description="", created_by="111", root_tree=base_tree()
        )
        resp = client.post(f"/quests/api/{qid}/remind", json={"frequency": "hourly"})
        assert resp.status_code == 400

    def test_unknown_quest_404(self, client, officer) -> None:
        assert client.post("/quests/api/99999/remind", json={}).status_code == 404

    def test_detail_shows_state(self, client, officer) -> None:
        qid = questdb.create_quest(
            title="state", description="", created_by="111", root_tree=base_tree()
        )
        html_before = client.get(f"/quests/{qid}").get_data(as_text=True)
        assert "checked" not in html_before.split("remind-toggle")[1].split(">")[0]
        client.post(f"/quests/api/{qid}/remind", json={})
        html_after = client.get(f"/quests/{qid}").get_data(as_text=True)
        opt_in_fragment = html_after.split('id="remind-toggle"')[1][:60]
        assert "checked" in opt_in_fragment


# --- task 5: deadline edit ---------------------------------------------------


class TestDeadlineEdit:
    def test_set_and_clear(self, client, officer) -> None:
        qid = questdb.create_quest(
            title="due", description="", created_by="111", root_tree=base_tree()
        )
        resp = client.post(f"/quests/api/{qid}/deadline", json={"deadline": "2026-09-01"})
        assert resp.status_code == 200
        assert questdb.get_quest(qid)["deadline"] == "2026-09-01"

        clear = client.post(f"/quests/api/{qid}/deadline", json={"deadline": None})
        assert clear.status_code == 200
        assert questdb.get_quest(qid)["deadline"] is None

    def test_invalid_date_400(self, client, officer) -> None:
        qid = questdb.create_quest(
            title="baddate", description="", created_by="111", root_tree=base_tree()
        )
        resp = client.post(f"/quests/api/{qid}/deadline", json={"deadline": "next tuesday"})
        assert resp.status_code == 400

    def test_unknown_quest_404(self, client, officer) -> None:
        assert (
            client.post("/quests/api/99999/deadline", json={"deadline": "2026-09-01"}).status_code
            == 404
        )

    def test_event_logged(self, client, officer) -> None:
        qid = questdb.create_quest(
            title="dueev", description="", created_by="111", root_tree=base_tree()
        )
        client.post(f"/quests/api/{qid}/deadline", json={"deadline": "2026-09-02"})
        kinds = [e["kind"] for e in questdb.quest_events(qid)]
        assert kinds[-1] == "deadline_changed"

    def test_officer_card_ui(self, client, officer) -> None:
        qid = questdb.create_quest(
            title="ui", description="", created_by="111", root_tree=base_tree()
        )
        html = client.get(f"/quests/{qid}").get_data(as_text=True)
        assert 'id="deadline-input"' in html
        assert "Re-expand recipe" in html
