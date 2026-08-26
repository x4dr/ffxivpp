"""Questboard persistence: models and DB helpers.

Models live here but share the declarative ``Base`` from app.models so
``init_db()`` / test fixtures create them together with everything else.
Helpers follow app/db.py conventions (scoped Session, try/finally remove).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Session
from app.models import Base

QUEST_OPEN = "open"
QUEST_FULFILLED = "fulfilled"
QUEST_CANCELLED = "cancelled"


class Quest(Base):
    __tablename__ = "quests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default=QUEST_OPEN, nullable=False)
    created_by: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[str] = mapped_column(String(32), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(32), nullable=False)
    deadline: Mapped[str | None] = mapped_column(String(32), nullable=True)
    tree_json: Mapped[str] = mapped_column(Text, nullable=False)
    discord_thread_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    discord_message_id: Mapped[str | None] = mapped_column(String(32), nullable=True)

    pledges_rel: Mapped[list[QuestPledge]] = relationship(
        back_populates="quest", cascade="all, delete-orphan"
    )
    events_rel: Mapped[list[QuestEvent]] = relationship(
        back_populates="quest", cascade="all, delete-orphan", order_by="QuestEvent.id"
    )


class QuestPledge(Base):
    __tablename__ = "quest_pledges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    quest_id: Mapped[int] = mapped_column(
        ForeignKey("quests.id", ondelete="CASCADE"), nullable=False
    )
    node_id: Mapped[str] = mapped_column(String(16), nullable=False)
    person_id: Mapped[str] = mapped_column(String(32), nullable=False)
    qty: Mapped[int] = mapped_column(Integer, nullable=False)
    pledged_at: Mapped[str] = mapped_column(String(32), nullable=False)
    turned_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    turned_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
    withdrawn: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    quest: Mapped[Quest] = relationship(back_populates="pledges_rel")


class QuestEvent(Base):
    __tablename__ = "quest_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    quest_id: Mapped[int] = mapped_column(
        ForeignKey("quests.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(32), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    created_at: Mapped[str] = mapped_column(String(32), nullable=False)

    quest: Mapped[Quest] = relationship(back_populates="events_rel")


class ReminderOptIn(Base):
    __tablename__ = "quest_reminder_optins"

    quest_id: Mapped[int] = mapped_column(
        ForeignKey("quests.id", ondelete="CASCADE"), primary_key=True
    )
    person_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    frequency: Mapped[str] = mapped_column(String(10), nullable=False)  # daily|weekly
    hour_utc: Mapped[int] = mapped_column(Integer, nullable=False)
    minute_utc: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    weekday_utc: Mapped[int] = mapped_column(
        Integer, default=-1, nullable=False
    )  # 0=Mon..6=Sun, -1=daily


class ItemCatalog(Base):
    __tablename__ = "item_catalog"

    item_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    recipe_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    flags_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    game_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    fetched_at: Mapped[str] = mapped_column(String(32), nullable=False)


class ChestSnapshot(Base):
    __tablename__ = "chest_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(20), nullable=False)  # allagan|manual|plugin
    data_json: Mapped[str] = mapped_column(Text, nullable=False)
    fetched_at: Mapped[str] = mapped_column(String(32), nullable=False)


# --- helpers ---------------------------------------------------------------


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _touch(quest: Quest) -> None:
    quest.updated_at = _now()


def log_event(quest_id: int, kind: str, actor_id: str, **payload: Any) -> None:
    try:
        Session.add(
            QuestEvent(
                quest_id=quest_id,
                kind=kind,
                actor_id=actor_id,
                payload_json=json.dumps(payload),
                created_at=_now(),
            )
        )
        Session.commit()
    finally:
        Session.remove()


def create_quest(
    title: str,
    description: str,
    created_by: str,
    root_tree: dict[str, Any],
    deadline: str | None = None,
) -> int:
    """Insert a quest with a serialized requirement tree; returns its id."""
    now = _now()
    try:
        quest = Quest(
            title=title,
            description=description,
            status=QUEST_OPEN,
            created_by=created_by,
            created_at=now,
            updated_at=now,
            deadline=deadline,
            tree_json=json.dumps(root_tree),
        )
        Session.add(quest)
        Session.flush()
        qid = int(quest.id)
        Session.add(
            QuestEvent(
                quest_id=qid, kind="created", actor_id=created_by, payload_json="{}", created_at=now
            )
        )
        Session.commit()
        return qid
    finally:
        Session.remove()


def get_quest(quest_id: int) -> dict[str, Any] | None:
    try:
        q = Session.query(Quest).filter_by(id=quest_id).first()
        if not q:
            return None
        return {
            "id": q.id,
            "title": q.title,
            "description": q.description,
            "status": q.status,
            "created_by": q.created_by,
            "created_at": q.created_at,
            "updated_at": q.updated_at,
            "deadline": q.deadline,
            "tree": json.loads(q.tree_json),
            "discord_thread_id": q.discord_thread_id,
            "discord_message_id": q.discord_message_id,
        }
    finally:
        Session.remove()


def list_quests(statuses: list[str] | None = None) -> list[dict[str, Any]]:
    try:
        query = Session.query(Quest).order_by(Quest.updated_at.desc())
        if statuses:
            query = query.filter(Quest.status.in_(statuses))
        return [
            {
                "id": q.id,
                "title": q.title,
                "status": q.status,
                "created_by": q.created_by,
                "updated_at": q.updated_at,
                "deadline": q.deadline,
            }
            for q in query.all()
        ]
    finally:
        Session.remove()


def set_quest_status(quest_id: int, status: str, actor_id: str) -> bool:
    if status not in (QUEST_OPEN, QUEST_FULFILLED, QUEST_CANCELLED):
        raise ValueError(f"invalid status {status!r}")
    try:
        q = Session.query(Quest).filter_by(id=quest_id).first()
        if not q:
            return False
        old = q.status
        q.status = status
        _touch(q)
        Session.add(
            QuestEvent(
                quest_id=quest_id,
                kind="status_changed",
                actor_id=actor_id,
                payload_json=json.dumps({"from": old, "to": status}),
                created_at=_now(),
            )
        )
        Session.commit()
        return True
    finally:
        Session.remove()


def _stored_tree_node_ids(tree_data: dict[str, Any]) -> set[str]:
    """Recompute positional node ids exactly like core.quests.assign_node_ids."""
    ids: set[str] = set()
    counter = 0

    def walk(node: dict[str, Any]) -> None:
        nonlocal counter
        ids.add(f"n{counter}")
        counter += 1
        for child in node.get("children", []):
            walk(child)

    walk(tree_data)
    return ids


def add_pledge(quest_id: int, node_id: str, person_id: str, qty: int, actor_id: str) -> int:
    """Add pledge rows; returns the pledge id. Amounts stored verbatim.

    Raises KeyError when the quest or *node_id* does not exist in its tree.
    """
    if qty < 1:
        raise ValueError("pledge quantity must be >= 1")
    try:
        q = Session.query(Quest).filter_by(id=quest_id).first()
        if not q:
            raise KeyError(f"quest {quest_id} not found")
        import json

        valid_ids = _stored_tree_node_ids(json.loads(q.tree_json))
        if node_id not in valid_ids:
            raise KeyError(f"node {node_id!r} not in quest tree")
        pledge = QuestPledge(
            quest_id=quest_id,
            node_id=node_id,
            person_id=person_id,
            qty=qty,
            pledged_at=_now(),
        )
        Session.add(pledge)
        Session.flush()
        pid = int(pledge.id)
        _touch(q)
        log_event(quest_id, "pledge_added", actor_id, node=node_id, qty=qty, pledge_id=pid)
        return pid
    finally:
        Session.remove()


def withdraw_pledge(pledge_id: int, person_id: str) -> bool:
    """Withdraw own pledge. Officers go through remove_pledge_for_officer."""
    try:
        p = Session.query(QuestPledge).filter_by(id=pledge_id).first()
        if not p or p.person_id != person_id or p.withdrawn:
            return False
        p.withdrawn = True
        q = Session.query(Quest).filter_by(id=p.quest_id).first()
        if q:
            _touch(q)
        log_event(p.quest_id, "pledge_withdrawn", person_id, pledge_id=pledge_id)
        return True
    finally:
        Session.remove()


def mark_turned_in(pledge_id: int, person_id: str, qty: int | None = None) -> bool:
    """Record a turn-in on a pledge (own pledges only; partial allowed)."""
    try:
        p = Session.query(QuestPledge).filter_by(id=pledge_id).first()
        if not p or p.person_id != person_id or p.withdrawn:
            return False
        amount = p.qty if qty is None else min(qty, p.qty - p.turned_qty)
        if amount <= 0:
            return False
        p.turned_qty += amount
        was_open = p.turned_at
        p.turned_at = _now()
        q = Session.query(Quest).filter_by(id=p.quest_id).first()
        if q:
            _touch(q)
        log_event(
            p.quest_id,
            "turn_in",
            person_id,
            pledge_id=pledge_id,
            node=p.node_id,
            qty=amount,
            complete=(p.turned_qty >= p.qty),
        )
        del was_open
        return True
    finally:
        Session.remove()


def quest_amounts(quest_id: int) -> tuple[dict[str, int], dict[str, int]]:
    """Summed active pledges and turn-ins per node id for one quest."""
    try:
        rows = (
            Session.query(QuestPledge)
            .filter_by(quest_id=quest_id, withdrawn=False)
            .all()
        )
        pledges: dict[str, int] = {}
        turned: dict[str, int] = {}
        for p in rows:
            pledges[p.node_id] = pledges.get(p.node_id, 0) + p.qty
            turned[p.node_id] = turned.get(p.node_id, 0) + p.turned_qty
        return pledges, turned
    finally:
        Session.remove()


def quest_events(quest_id: int) -> list[dict[str, Any]]:
    try:
        events = (
            Session.query(QuestEvent)
            .filter_by(quest_id=quest_id)
            .order_by(QuestEvent.id.asc())
            .all()
        )
        return [
            {
                "id": e.id,
                "kind": e.kind,
                "actor_id": e.actor_id,
                "payload": json.loads(e.payload_json),
                "created_at": e.created_at,
            }
            for e in events
        ]
    finally:
        Session.remove()


def upsert_reminder_optin(
    quest_id: int,
    person_id: str,
    frequency: str,
    hour_utc: int,
    minute_utc: int = 0,
    weekday_utc: int = -1,
) -> None:
    if frequency not in ("daily", "weekly"):
        raise ValueError(f"invalid reminder frequency {frequency!r}")
    if not 0 <= hour_utc <= 23 or not 0 <= minute_utc <= 59:
        raise ValueError("reminder time out of range")
    if frequency == "weekly" and not 0 <= weekday_utc <= 6:
        raise ValueError("weekly reminders need weekday_utc 0-6 (Mon..Sun)")
    try:
        row = (
            Session.query(ReminderOptIn)
            .filter_by(quest_id=quest_id, person_id=person_id)
            .first()
        )
        if row:
            row.frequency = frequency
            row.hour_utc = hour_utc
            row.minute_utc = minute_utc
            row.weekday_utc = weekday_utc if frequency == "weekly" else -1
        else:
            Session.add(
                ReminderOptIn(
                    quest_id=quest_id,
                    person_id=person_id,
                    frequency=frequency,
                    hour_utc=hour_utc,
                    minute_utc=minute_utc,
                    weekday_utc=weekday_utc if frequency == "weekly" else -1,
                )
            )
        Session.commit()
    finally:
        Session.remove()


def due_reminders(now_utc: datetime | None = None) -> list[dict[str, Any]]:
    """Reminder opt-ins whose chosen time matches now (minute precision)."""
    now = now_utc or datetime.now(UTC)
    try:
        rows = Session.query(ReminderOptIn).filter_by(hour_utc=now.hour).all()
        out: list[dict[str, Any]] = []
        for r in rows:
            if r.minute_utc != now.minute:
                continue
            if r.frequency == "weekly" and r.weekday_utc != now.weekday():
                continue
            out.append(
                {
                    "quest_id": r.quest_id,
                    "person_id": r.person_id,
                    "frequency": r.frequency,
                }
            )
        return out
    finally:
        Session.remove()
