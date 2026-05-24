from unittest.mock import patch

from app.db import PersonModel, Session, add_person_to_party


def test_compute_stream_success(client, auto_auth):
    # Mock compute_parties_stream
    with patch("app.routes.compute_parties_stream") as mock_compute:
        mock_compute.return_value = [("complete", {"found": 1, "parties": []})]

        # Test requires user, and person in DB
        Session.add(PersonModel(name="TestPerson", jobs="pld"))
        Session.commit()
        add_person_to_party("TestPerson", "Default")

        response = client.get("/api/compute/stream?party_name=Default")
        assert response.status_code == 200
        assert response.mimetype == "text/event-stream"

        data = response.data.decode("utf-8")
        assert "event: complete" in data
        assert '"found": 1' in data

def test_compute_stream_no_people(client, auto_auth):
    response = client.get("/api/compute/stream?party_name=Default")
    assert response.status_code == 200
    assert '"found": 0' in response.data.decode("utf-8")

def test_compute_stream_illegal_job(client, auto_auth):
    Session.add(PersonModel(name="BadPerson", jobs="invalidjob"))
    Session.commit()
    add_person_to_party("BadPerson", "Default")

    response = client.get("/api/compute/stream?party_name=Default")
    assert response.status_code == 200
    assert '"error":' in response.data.decode("utf-8")
    assert "Illegal job" in response.data.decode("utf-8")
