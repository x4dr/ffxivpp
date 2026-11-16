"""Poll schedule persistence and poll formatting helpers.

Schedules keep their *local* weekday and time plus an IANA zone name, rather
than a precomputed UTC slot. A raid night is "Friday 18:00 Berlin", not
"Friday 17:00 UTC": converting at creation time would silently shift the
posted time by an hour when DST changes. The loop converts ``now`` into each
schedule's zone at scan time instead.

Models share the declarative ``Base`` from app.models so ``init_db()`` and the
test fixtures create them with everything else. Helpers follow app/db.py
conventions (scoped Session, try/finally remove).
"""

from __future__ import annotations

import json
import os
import re
from datetime import UTC, date, datetime, time, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Session
from app.models import Base

MIN_ANSWERS = 2
MAX_ANSWERS = 10
MAX_ANSWER_LENGTH = 55  # Discord's answer text limit
MAX_QUESTION_LENGTH = 300  # Discord's poll question limit
MAX_DURATION_HOURS = 768  # Discord's 32 day poll limit
PRESET_RAID = "raid"
PRESET_CUSTOM = "custom"
PRESETS = (PRESET_RAID, PRESET_CUSTOM)

WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


class PollSchedule(Base):
    """A recurring poll (or poll pair) posted to one channel on a weekly beat."""

    __tablename__ = "poll_schedules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[str] = mapped_column(String(32), nullable=False)
    channel_id: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    preset: Mapped[str] = mapped_column(String(20), nullable=False)
    question: Mapped[str] = mapped_column(Text, default="", nullable=False)
    options_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    multi: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    duration_hours: Mapped[int] = mapped_column(Integer, default=24, nullable=False)
    weekday_local: Mapped[int] = mapped_column(Integer, nullable=False)  # 0=Mon..6=Sun
    hour_local: Mapped[int] = mapped_column(Integer, nullable=False)
    minute_local: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    time_start_hour: Mapped[int] = mapped_column(Integer, default=16, nullable=False)
    time_slots: Mapped[int] = mapped_column(Integer, default=4, nullable=False)
    week_offset: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_posted_date: Mapped[str | None] = mapped_column(String(10))
    created_by: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[str] = mapped_column(String(32), nullable=False)


# --- timezone resolution ---------------------------------------------------


def _zone_candidates_from_localtime() -> list[str]:
    """IANA names implied by the /etc/localtime symlink, if it is one."""
    try:
        target = Path("/etc/localtime").resolve()
    except OSError:
        return []
    parts = target.parts
    if "zoneinfo" not in parts:
        return []
    index = parts.index("zoneinfo")
    name = "/".join(parts[index + 1 :])
    return [name] if name else []


def _zone_candidates_from_etc_timezone() -> list[str]:
    try:
        text = Path("/etc/timezone").read_text(encoding="utf-8")
    except OSError:
        return []
    return [line.strip() for line in text.splitlines() if line.strip()]


@lru_cache(maxsize=8)
def _load_zone(name: str) -> ZoneInfo:
    return ZoneInfo(name)


def local_timezone_name() -> str:
    """Best-effort IANA zone name for the machine the bot runs on."""
    candidates = [
        os.environ.get("TZ", "").strip().lstrip(":"),
        *_zone_candidates_from_etc_timezone(),
        *_zone_candidates_from_localtime(),
    ]
    for candidate in candidates:
        if not candidate:
            continue
        try:
            _load_zone(candidate)
        except (ZoneInfoNotFoundError, ValueError):
            continue
        return candidate
    return "UTC"


def resolve_timezone(name: str | None) -> ZoneInfo:
    """Resolve an IANA zone name, defaulting to the machine's zone.

    Raises:
        ValueError: if *name* is not a known IANA zone.
    """
    if not name:
        name = local_timezone_name()
    try:
        return _load_zone(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"Unknown timezone: {name}") from exc


# --- formatting helpers ----------------------------------------------------


def validate_question(question: str) -> str:
    """Return the stripped question, or raise if Discord would reject it."""
    text = question.strip()
    if not text:
        raise ValueError("The poll question cannot be empty.")
    if len(text) > MAX_QUESTION_LENGTH:
        raise ValueError(f"Question too long (max {MAX_QUESTION_LENGTH} characters).")
    return text


def parse_options(raw: str) -> list[str]:
    """Split a poll answer list separated by ``|`` or new lines.

    Raises:
        ValueError: on fewer than 2 answers, more than 10, or one that exceeds
            Discord's 55 character answer limit.
    """
    parts = re.split(r"[|\n]+", raw)
    texts = [part.strip() for part in parts if part.strip()]
    if len(texts) < MIN_ANSWERS:
        raise ValueError("Need at least 2 answers, separated by | or new lines.")
    if len(texts) > MAX_ANSWERS:
        raise ValueError(f"A Discord poll allows at most {MAX_ANSWERS} answers.")
    too_long = next((text for text in texts if len(text) > MAX_ANSWER_LENGTH), None)
    if too_long is not None:
        raise ValueError(
            f"Answer too long (max {MAX_ANSWER_LENGTH} characters): {too_long[:30]}..."
        )
    return texts


def parse_time_of_day(raw: str) -> tuple[int, int]:
    """Parse ``HH:MM`` (24h) into ``(hour, minute)``.

    Raises:
        ValueError: if the value is not a valid wall-clock time.
    """
    match = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", raw)
    if not match:
        raise ValueError("Time must look like HH:MM, e.g. 18:00")
    hour, minute = int(match.group(1)), int(match.group(2))
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError("Time must be between 00:00 and 23:59")
    return hour, minute


def week_start_for(anchor: date, offset: int = 0) -> date:
    """Monday of the upcoming week.

    A Monday stays on itself; any other day moves forward to the next Monday.
    ``offset`` adds whole weeks, so 1 is the week after the upcoming one.
    """
    upcoming = anchor + timedelta(days=(7 - anchor.weekday()) % 7)
    return upcoming + timedelta(days=7 * offset)


def raid_question(start: date, end: date) -> str:
    return (
        "Which day would work best for you to do a raid this week? "
        f"[{start.strftime('%d.%m.%Y')}-{end.strftime('%d.%m.%Y')}]"
    )


def _hour_label(hour: int) -> str:
    suffix = "am" if hour < 12 else "pm"
    return f"{hour % 12 or 12} {suffix}"


def slot_labels(start_hour: int, count: int, timezone: str, anchor: date) -> list[str]:
    """Labels like ``from 6 pm cest onwards`` for the time poll.

    The abbreviation is taken from noon of *anchor* so it reflects the week
    being asked about, not the day the poll was posted.
    """
    tz = resolve_timezone(timezone)
    probe = datetime.combine(anchor, time(12, 0), tzinfo=tz)
    suffix = (probe.tzname() or "utc").lower()
    return [
        f"from {_hour_label((start_hour + index) % 24)} {suffix} onwards"
        for index in range(count)
    ]


# --- persistence -----------------------------------------------------------


def _validate_schedule_fields(weekday_local: int, hour_local: int, minute_local: int) -> None:
    if not 0 <= weekday_local <= 6:
        raise ValueError("weekday must be 0 (Monday) through 6 (Sunday)")
    if not 0 <= hour_local <= 23:
        raise ValueError("hour must be 0 through 23")
    if not 0 <= minute_local <= 59:
        raise ValueError("minute must be 0 through 59")


def validate_duration(duration_hours: int) -> None:
    if not 1 <= duration_hours <= MAX_DURATION_HOURS:
        raise ValueError(
            f"duration_hours must be between 1 and {MAX_DURATION_HOURS} "
            "(168 = 1 week, 768 = 32 days)"
        )


def validate_raid_options(time_start_hour: int, time_slots: int, week_offset: int) -> None:
    """Validate the raid preset's own knobs."""
    if not 0 <= time_start_hour <= 23:
        raise ValueError("time_start_hour must be 0 through 23")
    if not 1 <= time_slots <= MAX_ANSWERS:
        raise ValueError(f"time_slots must be between 1 and {MAX_ANSWERS}")
    if week_offset < 0:
        raise ValueError("week_offset cannot be negative")


def _row_to_dict(row: PollSchedule) -> dict[str, Any]:
    return {
        "id": row.id,
        "guild_id": row.guild_id,
        "channel_id": row.channel_id,
        "name": row.name,
        "preset": row.preset,
        "question": row.question,
        "options": json.loads(row.options_json or "[]"),
        "multi": bool(row.multi),
        "duration_hours": row.duration_hours,
        "weekday_local": row.weekday_local,
        "hour_local": row.hour_local,
        "minute_local": row.minute_local,
        "timezone": row.timezone,
        "time_start_hour": row.time_start_hour,
        "time_slots": row.time_slots,
        "week_offset": row.week_offset,
        "last_posted_date": row.last_posted_date,
    }


def create_schedule(
    *,
    guild_id: str,
    channel_id: str,
    name: str,
    preset: str,
    weekday_local: int,
    hour_local: int,
    minute_local: int,
    timezone: str,
    created_by: str,
    question: str = "",
    options: list[str] | None = None,
    multi: bool = False,
    duration_hours: int = 24,
    time_start_hour: int = 16,
    time_slots: int = 4,
    week_offset: int = 0,
) -> int:
    """Insert a schedule and return its id.

    Raises:
        ValueError: on an unknown preset or out-of-range field.
    """
    if preset not in PRESETS:
        raise ValueError(f"Unknown preset: {preset}")
    _validate_schedule_fields(weekday_local, hour_local, minute_local)
    validate_duration(duration_hours)
    validate_raid_options(time_start_hour, time_slots, week_offset)
    resolve_timezone(timezone)
    if preset == PRESET_CUSTOM:
        question = validate_question(question)
        if options is None or len(options) < MIN_ANSWERS:
            raise ValueError("A custom schedule needs at least 2 answers.")
        if len(options) > MAX_ANSWERS:
            raise ValueError(f"A Discord poll allows at most {MAX_ANSWERS} answers.")
        if any(len(option) > MAX_ANSWER_LENGTH for option in options):
            raise ValueError(f"Answers must be at most {MAX_ANSWER_LENGTH} characters.")

    row = PollSchedule(
        guild_id=guild_id,
        channel_id=channel_id,
        name=name,
        preset=preset,
        question=question,
        options_json=json.dumps(options or []),
        multi=multi,
        duration_hours=duration_hours,
        weekday_local=weekday_local,
        hour_local=hour_local,
        minute_local=minute_local,
        timezone=timezone,
        time_start_hour=time_start_hour,
        time_slots=time_slots,
        week_offset=week_offset,
        created_by=created_by,
        created_at=datetime.now(UTC).isoformat(),
    )
    try:
        Session.add(row)
        Session.commit()
        return row.id
    finally:
        Session.remove()


def list_schedules(guild_id: str) -> list[dict[str, Any]]:
    try:
        rows = (
            Session.query(PollSchedule)
            .filter_by(guild_id=guild_id)
            .order_by(PollSchedule.weekday_local, PollSchedule.hour_local)
            .all()
        )
        return [_row_to_dict(row) for row in rows]
    finally:
        Session.remove()


def delete_schedule(schedule_id: int, guild_id: str) -> bool:
    try:
        row = (
            Session.query(PollSchedule)
            .filter_by(id=schedule_id, guild_id=guild_id)
            .first()
        )
        if row is None:
            return False
        Session.delete(row)
        Session.commit()
        return True
    finally:
        Session.remove()


def due_schedules(now_utc: datetime | None = None) -> list[dict[str, Any]]:
    """Schedules whose local weekday, hour and minute match *now_utc*.

    Entries already posted on their local date are skipped, so the 30 second
    loop posts at most once per schedule per day.
    """
    now = now_utc or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    try:
        rows = Session.query(PollSchedule).all()
        out: list[dict[str, Any]] = []
        for row in rows:
            local_now = now.astimezone(resolve_timezone(row.timezone))
            if local_now.weekday() != row.weekday_local:
                continue
            if (local_now.hour, local_now.minute) != (row.hour_local, row.minute_local):
                continue
            local_date = local_now.date().isoformat()
            if row.last_posted_date == local_date:
                continue
            entry = _row_to_dict(row)
            entry["local_date"] = local_date
            out.append(entry)
        return out
    finally:
        Session.remove()


def mark_posted(schedule_id: int, local_date: str) -> None:
    try:
        row = Session.query(PollSchedule).filter_by(id=schedule_id).first()
        if row is not None:
            row.last_posted_date = local_date
            Session.commit()
    finally:
        Session.remove()
