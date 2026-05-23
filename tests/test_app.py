from __future__ import annotations

import os
import tempfile

import pytest

from app import create_app


@pytest.fixture
def client():
    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    os.environ["DATABASE_PATH"] = db_path
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        with app.app_context():
            from app.db import Base, Session, engine, init_db
            Base.metadata.drop_all(engine)
            init_db()
            yield c
            Session.remove()
    os.close(db_fd)
    os.unlink(db_path)
    del os.environ["DATABASE_PATH"]


def test_jobs_list(client):
    r = client.get("/api/jobs")
    assert r.status_code == 200
    data = r.get_json()
    assert isinstance(data, list)
    assert len(data) == 20


def test_people_empty(client):
    r = client.get("/api/people")
    assert r.status_code == 200
    assert r.get_json() == []


def test_people_post_and_get(client):
    payload = [{"name": "TestUser", "jobs": ["pld", "war"], "discord_id": "123"}]
    r = client.post("/api/people", json=payload)
    assert r.status_code == 200
    assert r.get_json() == {"ok": True}

    r = client.get("/api/people")
    data = r.get_json()
    assert len(data) == 1
    assert data[0]["name"] == "TestUser"
    assert data[0]["jobs"] == ["pld", "war"]
    assert data[0]["discord_id"] == "123"


def test_people_post_invalid(client):
    r = client.post("/api/people", json="not a list")
    assert r.status_code == 400


def test_constraints_defaults(client):
    r = client.get("/api/constraints")
    data = r.get_json()
    assert data["std_comp"] is True
    assert data["no_dupes"] is True
    assert data["min_selfish"] == 0
    assert data["max_selfish"] == 4
    assert data["min_utility"] == 0
    assert data["max_utility"] == 4


def test_constraints_put(client):
    r = client.put("/api/constraints", json={"std_comp": False, "heal_mix": True, "min_selfish": 2})
    assert r.status_code == 200

    r = client.get("/api/constraints")
    data = r.get_json()
    assert data["std_comp"] is False
    assert data["heal_mix"] is True
    assert data["min_selfish"] == 2


def test_compute_no_people(client):
    r = client.get("/api/compute/stream")
    assert r.status_code == 200


def test_compute_with_people(client):
    payload = [
        {"name": "A", "jobs": ["pld"]}, {"name": "B", "jobs": ["war"]},
        {"name": "C", "jobs": ["whm"]}, {"name": "D", "jobs": ["sch"]},
        {"name": "E", "jobs": ["mnk"]}, {"name": "F", "jobs": ["brd"]},
        {"name": "G", "jobs": ["blm"]}, {"name": "H", "jobs": ["nin"]},
    ]
    client.post("/api/people", json=payload)
    r = client.get("/api/compute/stream")
    assert r.status_code == 200


def test_index_redirect(client):
    r = client.get("/")
    assert r.status_code == 200
    assert b"Admin" in r.data
