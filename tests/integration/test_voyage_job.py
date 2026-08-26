"""Integration tests: voyage → quest ("job") link.

Covers the /quests/api/create payload extension (voyage_route/voyage_date),
the voyage page's "Open as job" affordance, and the quest detail voyage chip.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from core import questdb

PACKS = Path(__file__).resolve().parents[2] / "data" / "voyages"


@pytest.fixture
def voyage_pack(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point VOYAGE_DATA_DIR at an isolated dir holding only SAMPLE.json.

    load_pack() picks the newest *.json in the dir; the real-data pack committed
    alongside SAMPLE.json would otherwise win and 'Sample Loop' wouldn't exist.
    """
    pack_dir = tmp_path / "voyages"
    pack_dir.mkdir()
    (pack_dir / "SAMPLE.json").write_text((PACKS / "SAMPLE.json").read_text())
    monkeypatch.setenv("VOYAGE_DATA_DIR", str(pack_dir))


def _manual_root_tree() -> dict[str, Any]:
    return {
        "item_id": 0,
        "name": "Water Crystal",
        "qty_required": 20,
        "quality": "any",
        "children": [],
    }


class TestCreateApiVoyageFields:
    def test_create_with_voyage_fields_roundtrip(self, client, qb_auth) -> None:
        resp = client.post(
            "/quests/api/create",
            json={
                "title": "Voyage: Sample Loop",
                "item_name": "Nonexistent Item Xyz",  # wiki miss -> manual root
                "qty": 20,
                "voyage_route": "Sample Loop",
                "voyage_date": "2026-08-27",
            },
        )
        assert resp.status_code == 200
        qid = resp.get_json()["quest_id"]

        q = questdb.get_quest(qid)
        assert q is not None
        assert q["title"] == "Voyage: Sample Loop"
        assert q["tree"]["name"] == "Nonexistent Item Xyz"
        assert q["tree"]["qty_required"] == 20
        assert q["voyage_route"] == "Sample Loop"
        assert q["voyage_date"] == "2026-08-27"

    def test_create_without_voyage_fields_leaves_them_none(self, client, qb_auth) -> None:
        resp = client.post(
            "/quests/api/create",
            json={"title": "plain quest", "item_name": "Nonexistent Item Xyz", "qty": 1},
        )
        assert resp.status_code == 200
        qid = resp.get_json()["quest_id"]
        q = questdb.get_quest(qid)
        assert q is not None
        assert q["voyage_route"] is None
        assert q["voyage_date"] is None

    def test_empty_string_voyage_fields_stored_as_null(self, client, qb_auth) -> None:
        resp = client.post(
            "/quests/api/create",
            json={
                "title": "blank voyage fields",
                "item_name": "Nonexistent Item Xyz",
                "qty": 1,
                "voyage_route": "",
                "voyage_date": "",
            },
        )
        assert resp.status_code == 200
        q = questdb.get_quest(resp.get_json()["quest_id"])
        assert q is not None
        assert q["voyage_route"] is None
        assert q["voyage_date"] is None


class TestQuestDetailChip:
    def test_chip_renders_when_voyage_set(self, client, qb_auth) -> None:
        qid = questdb.create_quest(
            title="Voyage: Sample Loop",
            description="",
            created_by="12345",
            root_tree=_manual_root_tree(),
            voyage_route="Sample Loop",
            voyage_date="2026-08-27",
        )
        resp = client.get(f"/quests/{qid}")
        assert resp.status_code == 200
        assert b"Voyage: Sample Loop" in resp.data
        assert b"(2026-08-27)" in resp.data

    def test_no_chip_without_voyage(self, client, qb_auth) -> None:
        qid = questdb.create_quest(
            title="plain quest",
            description="",
            created_by="12345",
            root_tree=_manual_root_tree(),
        )
        resp = client.get(f"/quests/{qid}")
        assert resp.status_code == 200
        assert b"Voyage:" not in resp.data


class TestVoyagesPageJobButton:
    def test_prediction_card_offers_open_as_job(self, client, qb_auth, voyage_pack) -> None:
        resp = client.get("/voyages/?route=Sample+Loop")
        assert resp.status_code == 200
        assert b"Open as job" in resp.data
        # payload carries first loot item at its scaled max + voyage context
        assert b"Water Crystal" in resp.data
        assert b"Sample Loop" in resp.data

    def test_no_button_when_prediction_has_no_loot(
        self, client, qb_auth, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        import json

        pack = json.loads((PACKS / "SAMPLE.json").read_text())
        # gate all loot behind surveillance higher than the page default (80)
        for sector in pack["sectors"]:
            for band in sector["surveillance_thresholds"]:
                band["min_surveillance"] += 90
        monkeypatch.setenv("VOYAGE_DATA_DIR", str(tmp_path))
        (tmp_path / "locked.json").write_text(json.dumps(pack))

        resp = client.get("/voyages/")
        assert resp.status_code == 200
        assert b"Open as job" not in resp.data
