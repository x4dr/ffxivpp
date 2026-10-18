"""The trainer's server side: public page, optional save, per-user isolation."""

from __future__ import annotations

import base64
import io
import json
import struct
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.trainer import icons, store
from app.trainer.views import HOTBAR_TYPE, KEYBIND_TYPE

KEYBIND_BYTES = (
    struct.pack("<III", KEYBIND_TYPE, 4096, 0)
    + bytes(5)
    + bytes(4096)
    + bytes(15)
)
HOTBAR_BYTES = (
    struct.pack("<III", HOTBAR_TYPE, 4096, 0)
    + bytes(5)
    + bytes(4096)
    + bytes(15)
)


def _user(user_id: str = "12345", name: str = "maric") -> MagicMock:
    discord = MagicMock()
    discord.authorized = True
    discord.fetch_user.return_value.id = user_id
    discord.fetch_user.return_value.name = name
    return discord


@pytest.fixture
def trainer_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the trainer store at a temp file; its schema is created on use."""
    path = tmp_path / "trainer.db"
    monkeypatch.setenv("TRAINER_DB_PATH", str(path))
    store.ensure()
    return path


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "keybind": {"name": "KEYBIND.DAT", "b64": _b64(KEYBIND_BYTES)},
        "hotbar": {"name": "HOTBAR.DAT", "b64": _b64(HOTBAR_BYTES)},
        "selection": {"28": [1, 2]},
        "order": {"28": [2, 1]},
        "job_id": 28,
        "taught": {"HOTBAR_9_1": "Numpad5"},
        "sessions": [
            {
                "client_id": "session-1",
                "job_id": 28,
                "job_label": "SCH",
                "started_at": "2026-10-18T12:00:00",
                "duration_s": 30.0,
                "attempts": [
                    {
                        "bind": "HOTBAR_1_3",
                        "name": "Adloquium",
                        "label": "Bar 1 · slot 3",
                        "correct": True,
                        "reason": "OK",
                        "latency_ms": 200,
                        "pressed_code": "Digit3",
                        "pressed_mods": [],
                        "at": "2026-10-18T12:00:01",
                    },
                    {
                        "bind": "HOTBAR_1_3",
                        "name": "Adloquium",
                        "label": "Bar 1 · slot 3",
                        "correct": False,
                        "reason": "WRONG_KEY",
                        "latency_ms": 400,
                        "pressed_code": "Digit4",
                        "pressed_mods": ["SHIFT"],
                        "at": "2026-10-18T12:00:03",
                    },
                ],
            }
        ],
    }
    payload.update(overrides)
    return payload


@pytest.mark.parametrize(
    "path",
    ["/trainer/", "/trainer/binds", "/trainer/hotbars", "/trainer/train", "/trainer/score"],
)
def test_every_view_is_public(client, path: str) -> None:
    r = client.get(path)
    assert r.status_code == 200
    assert b"FFXIV Keybind Trainer" in r.data


def test_state_requires_a_login(client, trainer_db: Path) -> None:
    discord = MagicMock()
    discord.authorized = False
    with patch("app.trainer.views.get_discord", return_value=discord):
        r = client.get("/trainer/api/state")
    assert r.status_code == 401


def test_save_and_load_round_trip(client, trainer_db: Path) -> None:
    with patch("app.trainer.views.get_discord", return_value=_user()):
        saved = client.post("/trainer/api/save", json=_payload())
        assert saved.status_code == 200, saved.get_data(as_text=True)
        assert saved.get_json()["sessions_saved"] == 1

        state = client.get("/trainer/api/state")
        assert state.status_code == 200
        data = state.get_json()

    assert data["saved"] is True
    assert data["selection"] == {"28": [1, 2]}
    assert data["order"] == {"28": [2, 1]}
    assert data["job_id"] == 28
    assert data["taught"] == {"HOTBAR_9_1": "Numpad5"}
    assert data["files"]["keybind"]["b64"] == _b64(KEYBIND_BYTES)
    assert data["files"]["hotbar"]["b64"] == _b64(HOTBAR_BYTES)
    assert data["stats"]["HOTBAR_1_3"] == {
        "attempts": 2,
        "correct": 1,
        "errors": 1,
        "avg_latency": 200.0,
    }
    assert data["baseline_ms"] == 200.0
    assert len(data["last_session"]["attempts"]) == 2
    assert data["last_session"]["attempts"][1]["pressed_mods"] == ["SHIFT"]


def test_one_users_data_is_invisible_to_another(client, trainer_db: Path) -> None:
    with patch("app.trainer.views.get_discord", return_value=_user("111")):
        assert client.post("/trainer/api/save", json=_payload()).status_code == 200

    with patch("app.trainer.views.get_discord", return_value=_user("222")):
        data = client.get("/trainer/api/state").get_json()
        assert data["saved"] is False
        assert data["files"] == {}
        assert data["stats"] == {}
        assert data["last_session"] is None


def test_re_saving_a_session_does_not_double_count(client, trainer_db: Path) -> None:
    with patch("app.trainer.views.get_discord", return_value=_user()):
        client.post("/trainer/api/save", json=_payload())
        again = client.post("/trainer/api/save", json=_payload())
        data = client.get("/trainer/api/state").get_json()

    assert again.get_json()["sessions_saved"] == 0
    assert data["stats"]["HOTBAR_1_3"]["attempts"] == 2


def test_saving_without_files_keeps_the_stored_ones(client, trainer_db: Path) -> None:
    with patch("app.trainer.views.get_discord", return_value=_user()):
        client.post("/trainer/api/save", json=_payload())
        client.post(
            "/trainer/api/save",
            json={"keybind": None, "hotbar": None, "selection": {"28": [1]}, "sessions": []},
        )
        data = client.get("/trainer/api/state").get_json()

    assert data["files"]["keybind"]["b64"] == _b64(KEYBIND_BYTES)
    assert data["selection"] == {"28": [1]}


def test_a_file_of_the_wrong_type_is_rejected(client, trainer_db: Path) -> None:
    with patch("app.trainer.views.get_discord", return_value=_user()):
        r = client.post(
            "/trainer/api/save",
            json={"keybind": {"name": "x", "b64": _b64(HOTBAR_BYTES)}},
        )
    assert r.status_code == 400
    assert "not the .DAT file" in r.get_json()["error"]


def test_oversized_files_are_rejected(client, trainer_db: Path) -> None:
    blob = struct.pack("<I", KEYBIND_TYPE) + bytes(2 * 1024 * 1024)
    with patch("app.trainer.views.get_discord", return_value=_user()):
        r = client.post(
            "/trainer/api/save",
            json={"keybind": {"name": "x", "b64": _b64(blob)}},
        )
    assert r.status_code == 400


def test_malformed_bars_and_attempts_are_dropped(client, trainer_db: Path) -> None:
    payload = _payload(
        selection={"28": [0, 1, 99, "2", 3]},
        job_id="not a block",
        taught={"HOTBAR_1_1": 5, "HOTBAR_1_2": "KeyB"},
        sessions=[
            {
                "client_id": "bad",
                "started_at": "2026-10-18T12:00:00",
                "duration_s": 30,
                "attempts": [
                    {"bind": "HOTBAR_1_1", "reason": "NOPE", "correct": True},
                    {"bind": "HOTBAR_1_2", "reason": "OK", "correct": True, "latency_ms": 100},
                ],
            }
        ],
    )
    with patch("app.trainer.views.get_discord", return_value=_user()):
        r = client.post("/trainer/api/save", json=payload)
        data = client.get("/trainer/api/state").get_json()

    assert r.status_code == 200
    assert data["selection"] == {"28": [1, 3]}
    assert data["job_id"] is None
    assert data["taught"] == {"HOTBAR_1_2": "KeyB"}
    assert data["stats"]["HOTBAR_1_2"]["attempts"] == 1
    assert "HOTBAR_1_1" not in data["stats"]


# ------------------------------------------------------------------ icons


def test_a_cached_icon_does_not_touch_the_network(
    client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(icons, "ICON_CACHE", tmp_path)
    (tmp_path / "42.png").write_bytes(b"\x89PNG\r\n")

    def fail(*args: object, **kwargs: object) -> None:
        raise AssertionError("should have used the cached file")

    monkeypatch.setattr(icons.urllib.request, "urlopen", fail)
    r = client.get("/trainer/api/icon/42")
    assert r.status_code == 200
    assert r.data == b"\x89PNG\r\n"
    assert r.headers["Cache-Control"].startswith("public, max-age")


def test_a_definitive_miss_is_remembered(
    client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(icons, "ICON_CACHE", tmp_path)
    calls: list[str] = []

    def missing(url: str, **kwargs: object) -> None:
        calls.append(url)
        raise urllib.error.HTTPError(url, 404, "not found", {}, io.BytesIO(b""))

    monkeypatch.setattr(icons.urllib.request, "urlopen", missing)

    assert client.get("/trainer/api/icon/123").status_code == 404
    assert client.get("/trainer/api/icon/123").status_code == 404
    assert len(calls) == 1
    assert (tmp_path / "123.missing").exists()


def test_a_network_error_is_not_remembered(
    client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(icons, "ICON_CACHE", tmp_path)

    def offline(url: str, **kwargs: object) -> None:
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(icons.urllib.request, "urlopen", offline)
    assert client.get("/trainer/api/icon/7").status_code == 404
    assert not (tmp_path / "7.missing").exists()


def test_item_icons_use_their_own_cache_key(
    client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(icons, "ICON_CACHE", tmp_path)
    index = tmp_path / "item_index.json"
    index.write_text(
        json.dumps({"49238": {"name": "draught", "icon": "ui/icon/x.tex"}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(icons, "ITEM_INDEX", index)
    (tmp_path / "item-49238.png").write_bytes(b"\x89PNG-item")

    r = client.get("/trainer/api/item-icon/49238")
    assert r.status_code == 200
    assert r.data == b"\x89PNG-item"


def test_item_icon_for_an_unlisted_item_is_a_404(
    client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    index = tmp_path / "item_index.json"
    index.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(icons, "ITEM_INDEX", index)
    assert client.get("/trainer/api/item-icon/1").status_code == 404
