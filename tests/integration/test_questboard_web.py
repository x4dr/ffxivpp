"""Integration tests for the questboard web blueprint."""

from __future__ import annotations

import pytest

from core import questdb


@pytest.fixture
def quest_id() -> int:
    return questdb.create_quest(
        title="300 popcorn",
        description="keep the chest stocked",
        created_by="111",
        root_tree={"item_id": 0, "name": "popcorn", "qty_required": 300, "quality": "any", "children": []},
    )


def test_board_requires_login(client) -> None:
    resp = client.get("/quests/")
    assert resp.status_code == 302  # redirect to login


def test_board_renders_with_quest(client, qb_auth, quest_id: int) -> None:
    resp = client.get("/quests/")
    assert resp.status_code == 200
    assert b"300 popcorn" in resp.data


def test_detail_renders_tree(client, qb_auth, quest_id: int) -> None:
    resp = client.get(f"/quests/{quest_id}")
    assert resp.status_code == 200
    assert b"popcorn" in resp.data
    assert b"n0" in resp.data


def test_detail_missing_404(client, qb_auth) -> None:
    assert client.get("/quests/99999").status_code == 404


def test_create_pledge_turnin_flow(client, qb_auth) -> None:
    # create a manual quest (wiki lookup will fail -> falls back to manual root)
    resp = client.post(
        "/quests/api/create",
        json={"title": "400 wheels", "item_name": "Nonexistent Item Xyz", "qty": 400},
    )
    assert resp.status_code == 200
    qid = resp.get_json()["quest_id"]

    # pledge on the root node
    resp = client.post(f"/quests/api/{qid}/pledge", json={"node_id": "n0", "qty": 400})
    assert resp.status_code == 200
    pledge_id = resp.get_json()["pledge_id"]

    # turn-in completes the quest automatically (root fully delivered)
    resp = client.post(f"/quests/api/{qid}/turnin", json={"pledge_id": pledge_id})
    assert resp.status_code == 200
    assert questdb.get_quest(qid)["status"] == questdb.QUEST_FULFILLED


def test_pledge_requires_auth(client) -> None:
    resp = client.post("/quests/api/1/pledge", json={"node_id": "n0", "qty": 1})
    assert resp.status_code == 401


def test_invalid_pledge_qty_400(client, qb_auth, quest_id: int) -> None:
    resp = client.post(f"/quests/api/{quest_id}/pledge", json={"node_id": "n0", "qty": 0})
    assert resp.status_code == 400


def test_unknown_node_404(client, qb_auth, quest_id: int) -> None:
    resp = client.post(f"/quests/api/{quest_id}/pledge", json={"node_id": "zz", "qty": 5})
    assert resp.status_code == 404


def test_withdraw_own_pledge(client, qb_auth, quest_id: int) -> None:
    pid = questdb.add_pledge(quest_id, "n0", "12345", 10, actor_id="12345")
    resp = client.post(f"/quests/api/pledge/{pid}/withdraw")
    assert resp.status_code == 200
    pledges, _t = questdb.quest_amounts(quest_id)
    assert pledges == {}


def test_cannot_withdraw_foreign_pledge(client, qb_auth, quest_id: int) -> None:
    pid = questdb.add_pledge(quest_id, "n0", "999", 10, actor_id="999")
    resp = client.post(f"/quests/api/pledge/{pid}/withdraw")
    assert resp.status_code == 400
