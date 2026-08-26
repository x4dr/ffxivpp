"""Tests for bot.questboard: embed building and reminder loop logic."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

import pytest

os.environ.setdefault("DATABASE_PATH", "/tmp/.ffxivpp_bot_test.db")

from core import questdb  # noqa: E402
from core.quests import assign_node_ids  # noqa: E402


@pytest.fixture
def quest_id() -> int:
    return questdb.create_quest(
        title="Raid food run",
        description="",
        created_by="111",
        root_tree={
            "item_id": 0,
            "name": "popcorn",
            "qty_required": 300,
            "quality": "any",
            "children": [],
        },
    )


class TestEmbed:
    def test_build_embed_contains_status(self, quest_id: int) -> None:
        from bot.questboard import build_quest_embed

        embed = build_quest_embed(quest_id)
        assert embed is not None
        assert "[OPEN] Raid food run" in embed.title
        assert "popcorn" in (embed.description or "")
        assert str(quest_id) in (embed.footer.text or "")

    def test_build_embed_missing_quest(self) -> None:
        from bot.questboard import build_quest_embed

        assert build_quest_embed(999999) is None

    def test_fulfilled_color_flip(self, quest_id: int) -> None:
        from bot.questboard import build_quest_embed

        questdb.set_quest_status(quest_id, questdb.QUEST_FULFILLED, "111")
        embed = build_quest_embed(quest_id)
        assert embed is not None
        assert "[FULFILLED]" in embed.title


class TestTreeRebuild:
    def test_nested_children_rebuild(self, quest_id: int) -> None:
        """Stored trees with children rebuild into live nodes with ids."""
        from bot.questboard import _quest_tree_from_stored

        quest = questdb.get_quest(quest_id)
        assert quest is not None
        quest["tree"]["children"] = [
            {"item_id": 2, "name": "butter", "qty_required": 100, "children": []}
        ]
        root = _quest_tree_from_stored(quest["tree"])
        assign_node_ids(root)
        names = [c.name for c in root.children]
        assert names == ["butter"]


class TestReminderLoopData:
    def test_due_reminders_respects_weekday(self, db_session: Any, quest_id: int) -> None:  # noqa: ARG002
        questdb.upsert_reminder_optin(quest_id, "222", "weekly", 18, 0, weekday_utc=0)  # Monday
        # a Monday 18:00
        monday = datetime(2026, 8, 31, 18, 0, tzinfo=UTC)
        assert monday.weekday() == 0
        due = questdb.due_reminders(monday)
        assert any(d["person_id"] == "222" for d in due)
        # the following Tuesday same time -> not due
        tuesday = datetime(2026, 9, 1, 18, 0, tzinfo=UTC)
        assert not any(d["person_id"] == "222" for d in questdb.due_reminders(tuesday))

    def test_weekly_requires_weekday(self, quest_id: int) -> None:
        with pytest.raises(ValueError, match="weekday"):
            questdb.upsert_reminder_optin(quest_id, "222", "weekly", 9, 0)

    def test_daily_clears_weekday(self, quest_id: int) -> None:
        questdb.upsert_reminder_optin(quest_id, "222", "daily", 9, 15)
        from app.db import Session
        from core.questdb import ReminderOptIn

        try:
            row = (
                Session.query(ReminderOptIn)
                .filter_by(quest_id=quest_id, person_id="222")
                .first()
            )
            assert row is not None and row.weekday_utc == -1
        finally:
            Session.remove()
