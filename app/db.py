import os
from pathlib import Path
from typing import Any, Optional, cast
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker, scoped_session
from app.models import Base, Party, Person, PartyPerson, AppState, LodestoneLink, CharacterCache, PartyConstraint, AdminRole, ScraperTask

BASE_DIR = Path(__file__).resolve().parent.parent
DATABASE_URL = f"sqlite:///{os.environ.get('DATABASE_PATH', str(BASE_DIR / 'party.db'))}"

engine = create_engine(
    DATABASE_URL, 
    connect_args={"check_same_thread": False},
    echo=False
)

@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()

session_factory = sessionmaker(bind=engine)
Session = scoped_session(session_factory)

def init_db():
    Base.metadata.create_all(engine)
    if not Session.query(Party).filter_by(name='Default').first():
        Session.add(Party(name='Default'))
        Session.commit()

def close_db(e: Any = None) -> None:
    Session.remove()

def add_role_id(guild_id: str, role_id: str) -> None:
    try:
        Session.add(AdminRole(guild_id=guild_id, role_id=role_id))
        Session.commit()
    finally:
        Session.remove()

def remove_role_id(guild_id: str, role_id: str) -> None:
    try:
        Session.query(AdminRole).filter_by(guild_id=guild_id, role_id=role_id).delete()
        Session.commit()
    finally:
        Session.remove()

def cache_character(lodestone_id: str, data: dict[str, Any]) -> None:
    from datetime import datetime
    import json
    now = datetime.now().isoformat()
    # Use merge to insert or update
    try:
        Session.merge(CharacterCache(lodestone_id=lodestone_id, data=json.dumps(data), fetched_at=now))
        Session.commit()
    finally:
        Session.remove()

def get_cached_character(lodestone_id: str) -> dict[str, Any] | None:
    import json
    try:
        row = Session.query(CharacterCache).filter_by(lodestone_id=lodestone_id).first()
        if not row:
            return None
        data = json.loads(row.data)
        data["fetched_at"] = row.fetched_at
        return data
    finally:
        Session.remove()

def people_pool() -> list[dict[str, Any]]:
    try:
        people = Session.query(Person).order_by(Person.name).all()
        return [
            {
                "id": p.id,
                "name": p.name,
                "jobs": [j for j in (p.jobs or "").split(",") if j],
                "discord_id": p.discord_id,
            }
            for p in people
        ]
    finally:
        Session.remove()

def add_person_to_party(person_name: str, party_name: str) -> None:
    try:
        if not Session.query(PartyPerson).filter_by(party_name=party_name, person_name=person_name).first():
            Session.add(PartyPerson(party_name=party_name, person_name=person_name))
            Session.commit()
    finally:
        Session.remove()

def remove_person_from_party(person_name: str, party_name: str) -> None:
    try:
        Session.query(PartyPerson).filter_by(party_name=party_name, person_name=person_name).delete()
        Session.commit()
    finally:
        Session.remove()

def active_party_name() -> str:
    try:
        row = Session.query(AppState).filter_by(key='active_party').first()
        return row.value if row else "Default"
    finally:
        Session.remove()

def create_party(name: str) -> None:
    try:
        Session.add(Party(name=name))
        Session.commit()
    finally:
        Session.remove()

def delete_party(name: str) -> None:
    if name == "Default":
        return
    try:
        Session.query(PartyPerson).filter_by(party_name=name).delete()
        Session.query(Party).filter_by(name=name).delete()
        Session.commit()
    finally:
        Session.remove()

def add_scraper_task(lodestone_id: str, priority: int = 0) -> None:
    from datetime import datetime
    try:
        Session.merge(ScraperTask(lodestone_id=lodestone_id, priority=priority, created_at=datetime.now().isoformat()))
        Session.commit()
    finally:
        Session.remove()

def get_next_scraper_task() -> dict[str, Any] | None:
    try:
        task = Session.query(ScraperTask).order_by(ScraperTask.priority.desc(), ScraperTask.created_at.asc()).first()
        if not task:
            return None
        return {'lodestone_id': task.lodestone_id, 'priority': task.priority}
    finally:
        Session.remove()

def delete_scraper_task(lodestone_id: str) -> None:
    try:
        Session.query(ScraperTask).filter_by(lodestone_id=lodestone_id).delete()
        Session.commit()
    finally:
        Session.remove()

def set_lodestone_link(person_id: int, lodestone_id: str, character_name: str) -> None:
    from datetime import datetime
    try:
        Session.merge(LodestoneLink(
            person_id=person_id, 
            lodestone_id=lodestone_id, 
            character_name=character_name,
            fetched_at=datetime.now().isoformat()
        ))
        Session.commit()
    finally:
        Session.remove()

def update_lodestone_fetched_at(lodestone_id: str) -> None:
    from datetime import datetime
    try:
        link = Session.query(LodestoneLink).filter_by(lodestone_id=lodestone_id).first()
        if link:
            link.fetched_at = datetime.now().isoformat()
            Session.commit()
    finally:
        Session.remove()

def get_lodestone_link(person_id: int) -> dict[str, Any] | None:
    try:
        link = Session.query(LodestoneLink).filter_by(person_id=person_id).first()
        if not link:
            return None
        return {'person_id': link.person_id, 'lodestone_id': link.lodestone_id}
    finally:
        Session.remove()

from sqlalchemy.orm import sessionmaker, scoped_session, joinedload
from app.models import Base, Party, Person, PartyPerson, AppState, LodestoneLink, CharacterCache, PartyConstraint

def get_parties_for_lodestone_id(lodestone_id: str) -> list[dict[str, Any]]:
    # Find all PartyPerson entries linked to this person, and map to party
    try:
        results = (
            Session.query(PartyPerson)
            .join(PartyPerson.person)
            .join(Person.lodestone)
            .filter(LodestoneLink.lodestone_id == lodestone_id)
            .all()
        )
        
        # We also need the channel/message info from the Party table
        # but the PartyPerson model only has party_name. 
        # We need to query the Party table for each party_name.
        party_names = {r.party_name for r in results}
        parties = Session.query(Party).filter(Party.name.in_(party_names)).all()
        party_map = {p.name: p for p in parties}
        
        output = []
        for r in results:
            p = party_map.get(r.party_name)
            if p and p.home_channel_id and p.home_message_id:
                output.append({
                    'name': p.name,
                    'channel_id': p.home_channel_id,
                    'message_id': p.home_message_id
                })
        return output
    finally:
        Session.remove()

def people_from_db(party_name: str) -> list[dict[str, Any]]:
    try:
        people = Session.query(Person).join(PartyPerson).filter(PartyPerson.party_name == party_name).order_by(Person.name).all()
        return [
            {
                "id": p.id,
                "name": p.name,
                "jobs": [j for j in (p.jobs or "").split(",") if j],
                "discord_id": p.discord_id,
            }
            for p in people
        ]
    finally:
        Session.remove()

def constraints_from_db(party_name: str) -> dict[str, Any]:
    try:
        constraints = Session.query(PartyConstraint).filter_by(party_name=party_name).all()
        return {c.key: c.value for c in constraints}
    finally:
        Session.remove()

def constraints_to_db(data: dict[str, Any], party_name: str) -> None:
    try:
        Session.query(PartyConstraint).filter_by(party_name=party_name).delete()
        for key, value in data.items():
            Session.add(PartyConstraint(party_name=party_name, key=key, value=str(value)))
        Session.commit()
    finally:
        Session.remove()

def switch_party(name: str) -> None:
    try:
        state = Session.query(AppState).filter_by(key='active_party').first()
        if state:
            state.value = name
        else:
            Session.add(AppState(key='active_party', value=name))
        Session.commit()
    finally:
        Session.remove()

def get_party_members(party_name: str) -> list[dict[str, Any]]:
    # Use joinedload to fetch person and lodestone data in one query
    try:
        results = (
            Session.query(PartyPerson)
            .options(
                joinedload(PartyPerson.person)
                .joinedload(Person.lodestone)
            )
            .filter_by(party_name=party_name)
            .all()
        )
        
        # We also need character cache data, which can be fetched based on lodestone_id
        lodestone_ids = [r.person.lodestone.lodestone_id for r in results if r.person.lodestone]
        cache_map = {}
        if lodestone_ids:
            cache_data = Session.query(CharacterCache).filter(CharacterCache.lodestone_id.in_(lodestone_ids)).all()
            cache_map = {c.lodestone_id: {"data": c.data, "fetched_at": c.fetched_at} for c in cache_data}
        
        members = []
        for pp in results:
            char_data = None
            if pp.person.lodestone:
                char_data = cache_map.get(pp.person.lodestone.lodestone_id)
                
            members.append({
                "id": pp.person.id,
                "name": pp.person.name,
                "jobs": [j for j in (pp.person.jobs or "").split(",") if j],
                "lodestone_id": pp.person.lodestone.lodestone_id if pp.person.lodestone else None,
                "character_name": pp.person.lodestone.character_name if pp.person.lodestone else None,
                "fetched_at": char_data["fetched_at"] if char_data else None
            })
        return members
    finally:
        Session.remove()

def pool_save(people_data: list[dict[str, Any]]) -> None:
    try:
        Session.query(Person).delete()
        for p in people_data:
            Session.add(Person(
                name=p["name"],
                jobs=",".join(p["jobs"]),
                discord_id=p.get("discord_id")
            ))
        Session.commit()
    finally:
        Session.remove()
