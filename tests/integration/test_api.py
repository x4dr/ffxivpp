from app.db import (
    PersonModel,
    Session,
    PartyPerson,
    active_party_name,
    constraints_from_db,
    people_from_db,
    people_pool,
)


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


def test_people_from_db_has_lodestone_field(client, auto_auth):
    from app.db import LodestoneLink

    p1 = PersonModel(name="WithLodestone", jobs="drk")
    p2 = PersonModel(name="WithoutLodestone", jobs="whm")
    Session.add(p1)
    Session.add(p2)
    Session.flush()

    Session.add(LodestoneLink(person_id=p1.id, lodestone_id="12345", character_name="With Stone"))
    Session.commit()

    Session.add(PartyPerson(party_name="Default", person_name="WithLodestone"))
    Session.add(PartyPerson(party_name="Default", person_name="WithoutLodestone"))
    Session.commit()

    people = people_from_db("Default")
    by_name = {p["name"]: p for p in people}

    assert by_name["WithLodestone"]["has_lodestone"] is True
    assert by_name["WithoutLodestone"]["has_lodestone"] is False


def test_people_pool_has_lodestone_field(client, auto_auth):
    from app.db import LodestoneLink

    p1 = PersonModel(name="PoolWith", jobs="drk")
    p2 = PersonModel(name="PoolWithout", jobs="whm")
    Session.add(p1)
    Session.add(p2)
    Session.flush()

    Session.add(LodestoneLink(person_id=p1.id, lodestone_id="67890", character_name="Pool Stone"))
    Session.commit()

    pool = people_pool()
    by_name = {p["name"]: p for p in pool}

    assert by_name["PoolWith"]["has_lodestone"] is True
    assert by_name["PoolWithout"]["has_lodestone"] is False


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
