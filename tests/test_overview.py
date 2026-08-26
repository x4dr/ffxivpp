"""Overview page (/): nav bar links, four surface cards, live counts."""

from __future__ import annotations

from pathlib import Path

from core import questdb

NAV_HREFS = ("/party/", "/quests/", "/voyages/", "/chest/")
SURFACE_IDS = (
    'id="surface-party"',
    'id="surface-quests"',
    'id="surface-voyages"',
    'id="surface-chest"',
)

MINIMAL_PACK = """{
  "meta": {"game_version": "7.3", "source": "test"},
  "ships": {"submarine": {"base_range": 100, "tank_capacity": 19}},
  "sectors": [{"id": "A", "name": "site a", "distance": 50,
               "surveillance_thresholds": []}],
  "routes": [{"name": "Test Loop", "ship": "submarine",
              "sector_ids": ["A"], "duration_minutes": 120}]
}
"""


def _seed_open_quest() -> None:
    questdb.create_quest(
        title="Raid food",
        description="",
        created_by="12345",
        root_tree={"item_id": 0, "name": "Coffee Biscuit", "qty_required": 5},
    )


def test_overview_renders_nav_and_cards(client, qb_auth) -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    for href in NAV_HREFS:
        assert f'href="{href}"' in html
    for sid in SURFACE_IDS:
        assert sid in html


def test_overview_live_counts(client, qb_auth) -> None:
    # Seeded DB: one party, zero quests.
    html = client.get("/").get_data(as_text=True)
    assert ">1 party<" in html
    assert ">0 open quests<" in html

    _seed_open_quest()
    html = client.get("/").get_data(as_text=True)
    assert ">1 open quest<" in html


def test_overview_counts_track_new_party(client, qb_auth) -> None:
    from app.db import create_party

    create_party("Sauvage")
    html = client.get("/").get_data(as_text=True)
    assert ">2 parties<" in html


def test_overview_voyages_degrade_without_pack(client, qb_auth, monkeypatch) -> None:
    monkeypatch.delenv("VOYAGE_DATA_DIR", raising=False)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "data pack unavailable" in resp.get_data(as_text=True)


def test_overview_shows_latest_route(client, qb_auth, tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "test-pack.json").write_text(MINIMAL_PACK, encoding="utf-8")
    monkeypatch.setenv("VOYAGE_DATA_DIR", str(tmp_path))
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert ">1 route</span>" in html
    assert "current: Test Loop" in html
