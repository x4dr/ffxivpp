from app.db import PersonModel, Session, active_party_name, constraints_from_db, people_from_db


def test_party_switching_api(client, auto_auth):
    response = client.post("/api/parties/switch", json={"name": "NewParty"})
    assert response.status_code == 200
    assert active_party_name() == "NewParty"


def test_add_person_api(client, auto_auth):
    Session.add(PersonModel(name="NewPerson", jobs="pld"))
    Session.commit()

    response = client.post("/api/people-pool/add", json={"name": "NewPerson", "party_name": "Default"})
    assert response.status_code == 200

    people = people_from_db("Default")
    assert any(p["name"] == "NewPerson" for p in people)


def test_save_constraints_api(client, auto_auth):
    data = {
        "party_name": "Default",
        "std_comp": False,
        "no_dupes": True,
    }
    response = client.put("/api/constraints", json=data)
    assert response.status_code == 200

    c = constraints_from_db("Default")
    assert c["std_comp"] is False
    assert c["no_dupes"] is True
