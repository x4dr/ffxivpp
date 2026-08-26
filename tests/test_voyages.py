"""Tests for core.voyages: validation, loading, deterministic prediction."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from core.voyages import (
    VoyageDataError,
    fleet_range,
    load_pack,
    predict_voyage,
    route_distance,
    validate_pack,
)

SAMPLE = Path(__file__).parent / ".." / "data" / "voyages" / "SAMPLE.json"


@pytest.fixture
def pack() -> dict[str, Any]:
    return json.loads(SAMPLE.read_text())


class TestValidation:
    def test_sample_pack_valid(self, pack: dict[str, Any]) -> None:
        validate_pack(pack)

    def test_missing_meta(self, pack: dict[str, Any]) -> None:
        del pack["meta"]
        with pytest.raises(VoyageDataError, match="game_version"):
            validate_pack(pack)

    def test_duplicate_sector_ids(self, pack: dict[str, Any]) -> None:
        pack["sectors"].append(dict(pack["sectors"][0]))
        with pytest.raises(VoyageDataError, match="duplicate sector id 'A'"):
            validate_pack(pack)

    def test_route_unknown_sector(self, pack: dict[str, Any]) -> None:
        pack["routes"][0]["sector_ids"].append("Z")
        with pytest.raises(VoyageDataError, match="unknown sectors \\['Z'\\]"):
            validate_pack(pack)

    def test_route_unknown_ship(self, pack: dict[str, Any]) -> None:
        pack["routes"][0]["ship"] = "canoe"
        with pytest.raises(VoyageDataError, match="unknown ship 'canoe'"):
            validate_pack(pack)

    def test_load_rejects_bad_json(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VOYAGE_DATA_DIR", str(tmp_path))
        (tmp_path / "broken.json").write_text("{not json")
        with pytest.raises(VoyageDataError, match="invalid JSON"):
            load_pack()

    def test_load_picks_newest(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VOYAGE_DATA_DIR", str(tmp_path))
        good = json.loads(SAMPLE.read_text())
        (tmp_path / "older.json").write_text(json.dumps(good))
        good["meta"]["game_version"] = "9.9"
        newer = tmp_path / "newer.json"
        newer.write_text(json.dumps(good))
        import os

        os.utime(tmp_path / "older.json", (1, 1))
        assert load_pack()["meta"]["game_version"] == "9.9"


class TestPrediction:
    def test_reachable_with_enough_range(self, pack: dict[str, Any]) -> None:
        out = predict_voyage(
            pack, "Sample Loop", ship="submarine", surveillance=90, retrieval=100, parts_bonus=20
        )
        # A(30) + B(45) = 75 <= 100 + 20
        assert out["reachable"] is True
        assert out["range_needed"] == 75

    def test_unreachable_when_too_far(self, pack: dict[str, Any]) -> None:
        out = predict_voyage(
            pack, "Sample Loop", ship="submarine", surveillance=90, retrieval=100, parts_bonus=0
        )
        # 75 > base 100? No -- reachable; use airship with negative bonus instead
        del out

        out2 = predict_voyage(
            pack,
            "Sample Loop",
            ship="airship",
            surveillance=90,
            retrieval=100,
            parts_bonus=-50,
        )
        assert out2["range_available"] == 46
        assert out2["reachable"] is False

    def test_surveillance_gates_loot(self, pack: dict[str, Any]) -> None:
        low = predict_voyage(
            pack, "Sample Loop", ship="submarine", surveillance=40, retrieval=100, parts_bonus=50
        )
        items_low = {entry["item"] for entry in low["loot"]}
        assert "Rare Coral" not in items_low
        assert "Iron Ore" not in items_low
        assert any(b.startswith("B") for b in low["locked_bands"])

        high = predict_voyage(
            pack, "Sample Loop", ship="submarine", surveillance=95, retrieval=100, parts_bonus=50
        )
        items_high = {entry["item"] for entry in high["loot"]}
        assert {"Water Crystal", "Rare Coral", "Iron Ore"} <= items_high
        # every loot row carries its sector id and threshold (regression: the
        # web page once rendered "(sector )" empty because these were missing)
        for entry in high["loot"]:
            assert entry["sector"] in {"A", "B"}
            assert isinstance(entry["threshold"], int)
        assert high["locked_bands"] == []

    def test_deterministic(self, pack: dict[str, Any]) -> None:
        args = {"ship": "submarine", "surveillance": 80, "retrieval": 120, "parts_bonus": 10}
        assert predict_voyage(pack, "Sample Loop", **args) == predict_voyage(
            pack, "Sample Loop", **args
        )

    def test_unknown_route_raises(self, pack: dict[str, Any]) -> None:
        with pytest.raises(VoyageDataError, match="unknown route"):
            route_distance(pack, "Nowhere")

    def test_fleet_range_unknown_ship(self, pack: dict[str, Any]) -> None:
        with pytest.raises(VoyageDataError, match="unknown ship 'ufo'"):
            fleet_range(pack, "ufo", 0)
