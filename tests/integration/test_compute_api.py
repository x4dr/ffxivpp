import pytest
from unittest.mock import MagicMock, patch
from app.db import Session, PersonModel, add_person_to_party

@pytest.fixture
def auth_mock():
    """Fixture to mock auth across tests."""
    with patch("app.auth.get_discord") as mock_get_discord:
        discord = MagicMock()
        discord.authorized = True
        discord.fetch_user.return_value.id = "12345"
        mock_get_discord.return_value = discord
        
        with patch("app.auth._bot_api") as mock_bot_api:
            mock_bot_api.return_value = {"owner_id": "12345"}
            yield

def test_compute_stream_success(client, auth_mock):
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

def test_compute_stream_no_people(client, auth_mock):
    response = client.get("/api/compute/stream?party_name=Default")
    assert response.status_code == 200
    assert '"found": 0' in response.data.decode("utf-8")

def test_compute_stream_illegal_job(client, auth_mock):
    Session.add(PersonModel(name="BadPerson", jobs="invalidjob"))
    Session.commit()
    add_person_to_party("BadPerson", "Default")
    
    response = client.get("/api/compute/stream?party_name=Default")
    assert response.status_code == 200
    assert '"error":' in response.data.decode("utf-8")
    assert "Illegal job" in response.data.decode("utf-8")
