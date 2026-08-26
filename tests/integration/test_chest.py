"""Tests for chest snapshot ingestion and suggestion events."""

from __future__ import annotations

import pytest

from app.chest import ingest_snapshot
from core import questdb


@pytest.fixture
def popcorn_quest() -> int:
    return questdb.create_quest(
        title="Popcorn stock",
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


def test_ingest_rejects_bad_source() -> None:
    with pytest.raises(ValueError, match="invalid snapshot source"):
        ingest_snapshot("telepathy", [])


def test_ingest_creates_suggestion_event(popcorn_quest: int) -> None:
    sid = ingest_snapshot("manual", [{"name": "popcorn", "qty": 120}])
    assert sid >= 1
    events = questdb.quest_events(popcorn_quest)
    kinds = [e["kind"] for e in events]
    assert kinds[-1] == "chest_suggestion"
    payload = events[-1]["payload"]
    assert payload["snapshot_id"] == sid
    assert payload["matches"][0]["node"] == "popcorn"
    assert payload["matches"][0]["in_chest"] == 120


def test_ingest_no_match_no_event(popcorn_quest: int) -> None:
    before = len(questdb.quest_events(popcorn_quest))
    ingest_snapshot("allagan", [{"name": "unrelated thing", "qty": 5}])
    assert len(questdb.quest_events(popcorn_quest)) == before


def test_suggestion_never_marks_turnin(popcorn_quest: int) -> None:
    """Suggestion-only semantics: pledges/turn-ins untouched by ingestion."""
    pid = questdb.add_pledge(popcorn_quest, "n0", "222", 300, actor_id="222")
    ingest_snapshot("plugin", [{"name": "popcorn", "qty": 300}])
    _pledges, turned = questdb.quest_amounts(popcorn_quest)
    assert turned == {"n0": 0}
    del pid


def test_api_requires_secret(client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHEST_INGEST_SECRET", "s3cret")
    resp = client.post("/chest/api/ingest", json={"source": "manual", "items": []})
    assert resp.status_code == 401
    resp = client.post(
        "/chest/api/ingest",
        json={"source": "manual", "items": [{"name": "x", "qty": 1}]},
        headers={"X-Chest-Token": "wrong"},
    )
    assert resp.status_code == 401


def test_api_accepts_valid_snapshot(
    client, auto_auth, popcorn_quest: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CHEST_INGEST_SECRET", "s3cret")
    resp = client.post(
        "/chest/api/ingest",
        json={"source": "manual", "items": [{"name": "popcorn", "qty": 50}]},
        headers={"X-Chest-Token": "s3cret"},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    events = questdb.quest_events(popcorn_quest)
    assert any(e["kind"] == "chest_suggestion" for e in events)
