"""Tests for core.questdb: quest/pledge/event persistence and helpers."""

from __future__ import annotations

import pytest

from core import questdb
from core.quests import QUALITY_HQ, assign_node_ids, build_tree, node_statuses


def wheel_tree() -> dict:
    root = build_tree(
        1,
        "wheel",
        400,
        lambda i: {1: [(2, "log", 5), (3, "ore", 2)]}.get(i),
        quality=QUALITY_HQ,
    )
    assign_node_ids(root)
    return {
        "item_id": root.item_id,
        "name": root.name,
        "qty_required": root.qty_required,
        "quality": root.quality,
        "children": [
            {"item_id": c.item_id, "name": c.name, "qty_required": c.qty_required}
            for c in root.children
        ],
    }


@pytest.fixture
def quest_id() -> int:
    return questdb.create_quest(
        title="400 wheels for the raid",
        description="food wheels",
        created_by="111",
        root_tree=wheel_tree(),
    )


class TestQuestCrud:
    def test_create_and_get(self, quest_id: int) -> None:
        q = questdb.get_quest(quest_id)
        assert q is not None
        assert q["title"] == "400 wheels for the raid"
        assert q["status"] == questdb.QUEST_OPEN
        assert q["tree"]["children"][0]["qty_required"] == 2000
        events = questdb.quest_events(quest_id)
        assert [e["kind"] for e in events] == ["created"]

    def test_get_missing_returns_none(self) -> None:
        assert questdb.get_quest(99999) is None

    def test_list_filters_by_status(self, quest_id: int) -> None:
        assert len(questdb.list_quests()) >= 1
        assert questdb.list_quests([questdb.QUEST_FULFILLED]) == []

    def test_status_transition_logged(self, quest_id: int) -> None:
        assert questdb.set_quest_status(quest_id, questdb.QUEST_FULFILLED, "42")
        q = questdb.get_quest(quest_id)
        assert q is not None and q["status"] == questdb.QUEST_FULFILLED
        kinds = [e["kind"] for e in questdb.quest_events(quest_id)]
        assert kinds[-1] == "status_changed"

    def test_invalid_status_rejected(self, quest_id: int) -> None:
        with pytest.raises(ValueError, match="invalid status"):
            questdb.set_quest_status(quest_id, "banana", "42")


class TestPledgesAndTurnins:
    def test_pledge_then_turnin_flow(self, quest_id: int) -> None:
        pid = questdb.add_pledge(quest_id, "n1", "222", 1000, actor_id="222")
        pledges, turned = questdb.quest_amounts(quest_id)
        assert pledges == {"n1": 1000}
        assert turned == {"n1": 0}

        assert questdb.mark_turned_in(pid, "222") is True
        pledges, turned = questdb.quest_amounts(quest_id)
        assert turned == {"n1": 1000}

    def test_partial_turnin_accumulates(self, quest_id: int) -> None:
        pid = questdb.add_pledge(quest_id, "n1", "222", 1000, actor_id="222")
        assert questdb.mark_turned_in(pid, "222", qty=400) is True
        assert questdb.mark_turned_in(pid, "222", qty=400) is True
        _p, turned = questdb.quest_amounts(quest_id)
        assert turned == {"n1": 800}

    def test_over_turnin_clamped_to_pledge(self, quest_id: int) -> None:
        pid = questdb.add_pledge(quest_id, "n0", "222", 10, actor_id="222")
        assert questdb.mark_turned_in(pid, "222", qty=99) is True
        _p, turned = questdb.quest_amounts(quest_id)
        assert turned == {"n0": 10}

    def test_cannot_mark_someone_elses_pledge(self, quest_id: int) -> None:
        pid = questdb.add_pledge(quest_id, "n1", "222", 5, actor_id="222")
        assert questdb.mark_turned_in(pid, "333") is False

    def test_withdraw_removes_from_amounts(self, quest_id: int) -> None:
        pid = questdb.add_pledge(quest_id, "n1", "222", 5, actor_id="222")
        assert questdb.withdraw_pledge(pid, "222") is True
        assert questdb.withdraw_pledge(pid, "222") is False  # already withdrawn
        pledges, _turned = questdb.quest_amounts(quest_id)
        assert pledges == {}

    def test_negative_pledge_rejected(self, quest_id: int) -> None:
        with pytest.raises(ValueError, match=">= 1"):
            questdb.add_pledge(quest_id, "n1", "222", 0, actor_id="222")

    def test_substitution_end_to_end(self, quest_id: int) -> None:
        """Full integration of tree + db: turning in all wheels zeroes logs."""
        from core.quests import assign_node_ids as ani
        from core.quests import build_tree as bt

        q = questdb.get_quest(quest_id)
        assert q is not None
        # rebuild the live tree object from stored json shape
        root = bt(1, "wheel", 400, lambda i: {1: [(2, "log", 5), (3, "ore", 2)]}.get(i))
        ani(root)
        pid = questdb.add_pledge(quest_id, "n0", "222", 400, actor_id="222")
        questdb.mark_turned_in(pid, "222")
        pledges, turned = questdb.quest_amounts(quest_id)
        statuses = node_statuses(root, pledges, turned)
        assert all(s.fulfilled for s in statuses.values())


class TestReminders:
    def test_optin_validation(self, quest_id: int) -> None:
        with pytest.raises(ValueError, match="frequency"):
            questdb.upsert_reminder_optin(quest_id, "222", "hourly", 9)
        with pytest.raises(ValueError, match="range"):
            questdb.upsert_reminder_optin(quest_id, "222", "daily", 25)

    def test_upsert_and_due_query(self, quest_id: int) -> None:
        from datetime import UTC, datetime

        questdb.upsert_reminder_optin(quest_id, "222", "daily", 7, 30)
        questdb.upsert_reminder_optin(quest_id, "222", "weekly", 8, 0, weekday_utc=0)  # upsert
        monday = datetime(2026, 8, 31, 8, 0, tzinfo=UTC)  # a Monday
        due = questdb.due_reminders(monday)
        assert len(due) == 1
        assert due[0]["person_id"] == "222"
        assert due[0]["frequency"] == "weekly"
