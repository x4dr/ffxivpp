from app.db import Session, engine
from app.models import PersonModel, PartyPerson, Party, LodestoneLink
from sqlalchemy.orm import Session as SQLAlchemySession

def migrate():
    data = [
        {"name": "Damian Blake", "jobs": "drk,gnb", "discord_id": "387309386843815947", "parties": ["Default"], "lodestone_id": None},
        {"name": "Lookei Lionheart", "jobs": "vpr,sam", "discord_id": "111117588553060352", "parties": ["Default"], "lodestone_id": "32267141"},
        {"name": "Luneli Lainosi", "jobs": "sge,whm,dnc", "discord_id": "393428399353364503", "parties": ["Default"], "lodestone_id": "28630035"},
        {"name": "Maric", "jobs": "pld,whm,drg,blm", "discord_id": "217068793543917569", "parties": ["Default", "testparty"], "lodestone_id": "54185648"},
        {"name": "Naghia Gil", "jobs": "pct,vpr", "discord_id": "158302672414441481", "parties": ["Default"], "lodestone_id": "59662524"},
        {"name": "Rayne Blake", "jobs": "rdm,nin", "discord_id": "176308138042064897", "parties": ["Default"], "lodestone_id": None},
        {"name": "Vey Bramble", "jobs": "dnc,nin", "discord_id": "229632496625516544", "parties": ["Default"], "lodestone_id": "59874367"},
        {"name": "saga salem", "jobs": "sge", "discord_id": "906214878367326251", "parties": ["Default"], "lodestone_id": "54185676"},
    ]

    session: SQLAlchemySession = Session()
    try:
        # Ensure parties exist
        all_parties = set()
        for d in data:
            all_parties.update(d["parties"])
        
        for p_name in all_parties:
            if not session.query(Party).filter_by(name=p_name).first():
                session.add(Party(name=p_name))
        
        for d in data:
            person = PersonModel(name=d["name"], jobs=d["jobs"], discord_id=d["discord_id"])
            session.add(person)
            session.flush() # Populate ID

            for p_name in d["parties"]:
                session.add(PartyPerson(party_name=p_name, person_name=person.name))
            
            if d["lodestone_id"]:
                session.add(LodestoneLink(person_id=person.id, lodestone_id=d["lodestone_id"]))
        
        session.commit()
        print("Data migration successful.")
    except Exception as e:
        session.rollback()
        print(f"Migration failed: {e}")
    finally:
        session.close()

if __name__ == "__main__":
    migrate()
