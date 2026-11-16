"""Tests for core.pollstore helpers and the poll builders in bot.polls."""

from __future__ import annotations

import os
from datetime import UTC, date, datetime
from typing import Any

import discord
import pytest

os.environ.setdefault("DATABASE_PATH", "/tmp/.ffxivpp_bot_test.db")

from core import pollstore  # noqa: E402


class TestParseOptions:
    def test_pipe_separated(self) -> None:
        assert pollstore.parse_options("a | b | c") == ["a", "b", "c"]

    def test_newline_separated(self) -> None:
        assert pollstore.parse_options("first\nsecond\nthird") == ["first", "second", "third"]

    def test_mixed_and_blank_lines_ignored(self) -> None:
        assert pollstore.parse_options("\n a | b \n\n c \n") == ["a", "b", "c"]

    def test_too_few_answers(self) -> None:
        with pytest.raises(ValueError, match="at least 2"):
            pollstore.parse_options("only one")

    def test_too_many_answers(self) -> None:
        with pytest.raises(ValueError, match="at most 10"):
            pollstore.parse_options("|".join(f"answer {i}" for i in range(11)))

    def test_answer_too_long(self) -> None:
        with pytest.raises(ValueError, match="too long"):
            pollstore.parse_options(f"a|{'x' * 56}")


class TestValidateQuestion:
    def test_strips_whitespace(self) -> None:
        assert pollstore.validate_question("  Pick a night  ") == "Pick a night"

    def test_rejects_empty(self) -> None:
        with pytest.raises(ValueError, match="cannot be empty"):
            pollstore.validate_question("   ")

    def test_rejects_too_long(self) -> None:
        with pytest.raises(ValueError, match="too long"):
            pollstore.validate_question("x" * 301)


class TestParseTimeOfDay:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [("18:00", (18, 0)), ("9:05", (9, 5)), ("00:30", (0, 30)), (" 23:59 ", (23, 59))],
    )
    def test_valid(self, raw: str, expected: tuple[int, int]) -> None:
        assert pollstore.parse_time_of_day(raw) == expected

    @pytest.mark.parametrize("raw", ["24:00", "18:60", "six", "18", "18:0"])
    def test_invalid(self, raw: str) -> None:
        with pytest.raises(ValueError):
            pollstore.parse_time_of_day(raw)


class TestWeekStart:
    def test_friday_asks_about_next_monday(self) -> None:
        assert pollstore.week_start_for(date(2026, 11, 13)) == date(2026, 11, 16)

    def test_monday_stays_on_itself(self) -> None:
        assert pollstore.week_start_for(date(2026, 11, 16)) == date(2026, 11, 16)

    def test_sunday_moves_to_next_day(self) -> None:
        assert pollstore.week_start_for(date(2026, 11, 22)) == date(2026, 11, 23)

    def test_offset_adds_whole_weeks(self) -> None:
        assert pollstore.week_start_for(date(2026, 11, 13), 1) == date(2026, 11, 23)


class TestLabels:
    def test_raid_question_matches_screenshot(self) -> None:
        question = pollstore.raid_question(date(2026, 11, 16), date(2026, 11, 22))
        assert question == (
            "Which day would work best for you to do a raid this week? "
            "[16.11.2026-22.11.2026]"
        )

    def test_slot_labels_use_winter_abbreviation(self) -> None:
        labels = pollstore.slot_labels(16, 4, "Europe/Berlin", date(2026, 11, 16))
        assert labels == [
            "from 4 pm cet onwards",
            "from 5 pm cet onwards",
            "from 6 pm cet onwards",
            "from 7 pm cet onwards",
        ]

    def test_slot_labels_use_summer_abbreviation(self) -> None:
        labels = pollstore.slot_labels(18, 2, "Europe/Berlin", date(2026, 7, 13))
        assert labels == ["from 6 pm cest onwards", "from 7 pm cest onwards"]

    def test_slot_labels_handle_am_hours(self) -> None:
        labels = pollstore.slot_labels(10, 2, "Europe/Berlin", date(2026, 11, 16))
        assert labels[0] == "from 10 am cet onwards"
        assert labels[1] == "from 11 am cet onwards"


class TestTimezones:
    def test_tz_environment_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TZ", "Europe/Berlin")
        assert pollstore.local_timezone_name() == "Europe/Berlin"

    def test_unknown_zone_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown timezone"):
            pollstore.resolve_timezone("Nowhere/Fictional")

    def test_create_schedule_rejects_unknown_zone(self) -> None:
        with pytest.raises(ValueError, match="Unknown timezone"):
            _create(timezone="Nowhere/Fictional")


def _create(**overrides: Any) -> int:
    base: dict[str, Any] = {
        "guild_id": "g1",
        "channel_id": "c1",
        "name": "Raid polls",
        "preset": pollstore.PRESET_RAID,
        "weekday_local": 4,  # Friday
        "hour_local": 18,
        "minute_local": 0,
        "timezone": "Europe/Berlin",
        "created_by": "u1",
    }
    base.update(overrides)
    return pollstore.create_schedule(**base)


class TestSchedules:
    def test_create_and_list(self) -> None:
        schedule_id = _create()
        entries = pollstore.list_schedules("g1")
        assert [entry["id"] for entry in entries] == [schedule_id]
        entry = entries[0]
        assert entry["preset"] == pollstore.PRESET_RAID
        assert entry["timezone"] == "Europe/Berlin"
        assert entry["weekday_local"] == 4
        assert entry["last_posted_date"] is None

    def test_list_is_scoped_to_guild(self) -> None:
        _create()
        assert pollstore.list_schedules("other-guild") == []

    def test_due_at_local_time(self) -> None:
        schedule_id = _create()
        # Friday 2026-11-20 18:00 Berlin (CET) is 17:00 UTC.
        due = pollstore.due_schedules(datetime(2026, 11, 20, 17, 0, tzinfo=UTC))
        assert [entry["id"] for entry in due] == [schedule_id]
        assert due[0]["local_date"] == "2026-11-20"

    def test_not_due_at_other_minute(self) -> None:
        _create()
        assert pollstore.due_schedules(datetime(2026, 11, 20, 17, 1, tzinfo=UTC)) == []

    def test_not_due_on_other_weekday(self) -> None:
        _create()
        assert pollstore.due_schedules(datetime(2026, 11, 19, 17, 0, tzinfo=UTC)) == []

    def test_schedule_follows_dst(self) -> None:
        _create()
        # Same wall clock, summer: 18:00 CEST is 16:00 UTC.
        summer = pollstore.due_schedules(datetime(2026, 7, 17, 16, 0, tzinfo=UTC))
        winter = pollstore.due_schedules(datetime(2027, 1, 15, 17, 0, tzinfo=UTC))
        assert len(summer) == 1
        assert len(winter) == 1

    def test_mark_posted_stops_repeat_for_that_day(self) -> None:
        schedule_id = _create()
        now = datetime(2026, 11, 20, 17, 0, tzinfo=UTC)
        entry = pollstore.due_schedules(now)[0]
        pollstore.mark_posted(schedule_id, str(entry["local_date"]))
        assert pollstore.due_schedules(now) == []

    def test_next_week_is_due_again(self) -> None:
        schedule_id = _create()
        now = datetime(2026, 11, 20, 17, 0, tzinfo=UTC)
        entry = pollstore.due_schedules(now)[0]
        pollstore.mark_posted(schedule_id, str(entry["local_date"]))
        next_week = pollstore.due_schedules(datetime(2026, 11, 27, 17, 0, tzinfo=UTC))
        assert [item["id"] for item in next_week] == [schedule_id]

    def test_delete_is_scoped_to_guild(self) -> None:
        schedule_id = _create()
        assert pollstore.delete_schedule(schedule_id, "other-guild") is False
        assert pollstore.delete_schedule(schedule_id, "g1") is True
        assert pollstore.list_schedules("g1") == []

    def test_custom_needs_options(self) -> None:
        with pytest.raises(ValueError, match="at least 2 answers"):
            _create(preset=pollstore.PRESET_CUSTOM, question="Pick one")

    def test_custom_needs_question(self) -> None:
        with pytest.raises(ValueError, match="cannot be empty"):
            _create(preset=pollstore.PRESET_CUSTOM, question=" ", options=["a", "b"])

    def test_custom_rejects_long_answer(self) -> None:
        with pytest.raises(ValueError, match="at most 55"):
            _create(preset=pollstore.PRESET_CUSTOM, question="Q", options=["a", "b" * 56])

    def test_rejects_out_of_range_fields(self) -> None:
        with pytest.raises(ValueError, match="weekday"):
            _create(weekday_local=7)
        with pytest.raises(ValueError, match="hour"):
            _create(hour_local=24)
        with pytest.raises(ValueError, match="duration_hours"):
            _create(duration_hours=0)
        with pytest.raises(ValueError, match="time_slots"):
            _create(time_slots=0)


class TestSchedulePosting:
    async def test_raid_schedule_posts_pair_and_marks_posted(self) -> None:
        from unittest.mock import AsyncMock, MagicMock

        from bot.polls import _post_scheduled

        _create(channel_id="1001")
        now = datetime(2026, 11, 20, 17, 0, tzinfo=UTC)
        entry = pollstore.due_schedules(now)[0]

        channel = MagicMock(spec=discord.TextChannel)
        channel.id = 1001
        channel.send = AsyncMock(return_value=object())

        await _post_scheduled(channel, entry)

        assert channel.send.await_count == 2
        first = channel.send.await_args_list[0].kwargs["poll"]
        assert "[23.11.2026-29.11.2026]" in first.question
        assert pollstore.due_schedules(now) == []
        assert pollstore.list_schedules("g1")[0]["last_posted_date"] == "2026-11-20"

    async def test_custom_schedule_posts_single_poll(self) -> None:
        from unittest.mock import AsyncMock, MagicMock

        from bot.polls import _post_scheduled

        _create(
            channel_id="1002",
            preset=pollstore.PRESET_CUSTOM,
            question="Which night?",
            options=["Friday", "Saturday"],
        )
        now = datetime(2026, 11, 20, 17, 0, tzinfo=UTC)
        entry = pollstore.due_schedules(now)[0]

        channel = MagicMock(spec=discord.TextChannel)
        channel.id = 1002
        channel.send = AsyncMock(return_value=object())

        await _post_scheduled(channel, entry)

        assert channel.send.await_count == 1
        poll = channel.send.await_args.kwargs["poll"]
        assert poll.question == "Which night?"
        assert [answer.text for answer in poll.answers] == ["Friday", "Saturday"]


class TestPollBuilders:
    def test_build_poll_carries_answers_and_flags(self) -> None:
        from bot.polls import build_poll

        poll = build_poll("Pick", ["a", "b"], multiple=True, duration_hours=12)
        assert [answer.text for answer in poll.answers] == ["a", "b"]
        assert poll.multiple is True
        assert poll.duration.total_seconds() == 12 * 3600

    async def test_raid_pair_posts_day_then_time(self) -> None:
        from bot.polls import post_raid_pair

        class FakeChannel:
            def __init__(self) -> None:
                self.polls: list[Any] = []

            async def send(self, *, poll: Any) -> Any:
                self.polls.append(poll)
                return object()

        channel = FakeChannel()
        await post_raid_pair(
            channel,  # type: ignore[arg-type]
            week_start=date(2026, 11, 16),
            timezone="Europe/Berlin",
        )
        assert len(channel.polls) == 2
        day_poll, time_poll = channel.polls
        assert "[16.11.2026-22.11.2026]" in day_poll.question
        assert [answer.text for answer in day_poll.answers] == list(pollstore.WEEKDAYS)
        assert day_poll.multiple is True
        assert time_poll.question == "What time would work best for you?"
        assert [answer.text for answer in time_poll.answers][0] == "from 4 pm cet onwards"
        assert time_poll.multiple is False
