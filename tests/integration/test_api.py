import pytest
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.append(str(Path(__file__).parent.parent.parent.resolve()))

from app import create_app
from app.db import Base, engine, Session

@pytest.fixture
def app():
    config_override = {
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "BYPASS_AUTH": "1",
        "GUILD_ID": "298197955951984640",
    }
    app = create_app(config_override)
    Base.metadata.create_all(engine)
    yield app
    Base.metadata.drop_all(engine)

@pytest.fixture
def client(app):
    """A test client for the app."""
    return app.test_client()

def test_party_switching_api(client):
    # Test switching party
    # Bypass auth via environment for this test case specifically if needed,
    # or ensure setup matches requirements.
    # The error 403 suggests check_access() is returning False.
    # Ensure bypass is actually working in the test context.
    import os
    os.environ["BYPASS_AUTH"] = "1"
    
    response = client.post("/api/parties/switch", json={"name": "NewParty"})
    assert response.status_code == 200
    
    # Verify active party was updated
    from app.db import active_party_name
    assert active_party_name() == "NewParty"

def test_add_person_api(client):
    import os
    os.environ["BYPASS_AUTH"] = "1"
    
    # We must add the person to the Person table first because of foreign keys
    from app.db import Session, PersonModel
    Session.add(PersonModel(name="NewPerson", jobs="pld"))
    Session.commit()
    
    response = client.post("/api/people-pool/add", json={"name": "NewPerson", "party_name": "Default"})
    assert response.status_code == 200
    
    # Verify person added to DB
    from app.db import people_from_db
    people = people_from_db("Default")
    assert any(p["name"] == "NewPerson" for p in people)

def test_save_constraints_api(client):
    import os
    os.environ["BYPASS_AUTH"] = "1"
    
    # Test saving constraints
    data = {
        "party_name": "Default",
        "std_comp": False,
        "no_dupes": True
    }
    # Method is PUT for constraints
    response = client.put("/api/constraints", json=data)
    assert response.status_code == 200
    
    # Verify constraints in DB
    from app.db import constraints_from_db
    c = constraints_from_db("Default")
    assert c["std_comp"] is False
    assert c["no_dupes"] is True
