from __future__ import annotations

import os
from pathlib import Path
from typing import Any, cast
from sqlalchemy import create_engine, event, select, delete
from sqlalchemy.orm import sessionmaker, scoped_session, joinedload
from app.models import (
    Base,
    Party,
    PersonModel,
    PartyPerson,
    PartyConstraint,
    PartyExclusion,
    AppState,
    AdminRole,
    LodestoneLink,
    CharacterCache,
    ScraperTask,
)

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
    if not Session.query(AppState).filter_by(key='active_party').first():
        Session.add(AppState(key='active_party', value='Default'))
    Session.commit()
    Session.remove()

def close_db(e: Any = None) -> None:
    Session.remove()

# --- People / Party ---

def people_from_db(party_name: str) -> list[dict[str, Any]]:
    try:
        people = Session.query(PersonModel).join(PartyPerson).filter(PartyPerson.party_name == party_name).order_by(PersonModel.name).all()
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

def people_to_db(people_data: list[dict[str, Any]], party_name: str) -> None:
    try:
        Session.query(PartyPerson).filter_by(party_name=party_name).delete()
        for p in people_data:
            person = Session.query(PersonModel).filter_by(name=p["name"]).first()
            if not person:
                person = PersonModel(name=p["name"], jobs=",".join(p["jobs"]), discord_id=p.get("discord_id"))
                Session.add(person)
            else:
                person.jobs = ",".join(p["jobs"])
                person.discord_id = p.get("discord_id")
            Session.add(PartyPerson(party_name=party_name, person_name=person.name))
        Session.commit()
    finally:
        Session.remove()

def people_pool() -> list[dict[str, Any]]:
    try:
        people = Session.query(PersonModel).order_by(PersonModel.name).all()
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

def pool_save(people_data: list[dict[str, Any]]) -> None:
    try:
        for p in people_data:
            person = Session.query(PersonModel).filter_by(name=p["name"]).first()
            if not person:
                Session.add(PersonModel(name=p["name"], jobs=",".join(p["jobs"]), discord_id=p.get("discord_id")))
            else:
                person.jobs = ",".join(p["jobs"])
                person.discord_id = p.get("discord_id")
        Session.commit()
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

def check_party_member(discord_id: str, party_name: str) -> bool:
    try:
        member = Session.query(PartyPerson).join(PersonModel).filter(PersonModel.discord_id == discord_id, PartyPerson.party_name == party_name).first()
        return member is not None
    finally:
        Session.remove()

# --- Constraints ---

def constraints_from_db(party_name: str) -> dict[str, Any]:
    try:
        constraints = Session.query(PartyConstraint).filter_by(party_name=party_name).all()
        # Ensure values are converted to appropriate types for JSON
        out = {}
        for c in constraints:
            val = c.value
            if val == "True": val = True
            elif val == "False": val = False
            elif val.isdigit(): val = int(val)
            out[c.key] = val
            
        excl = Session.query(PartyExclusion).filter_by(party_name=party_name).all()
        out["exclusions"] = [e.jobs.split(",") for e in excl]
        return out
    finally:
        Session.remove()

def constraints_to_db(data: dict[str, Any], party_name: str) -> None:
    try:
        Session.query(PartyConstraint).filter_by(party_name=party_name).delete()
        for k, v in data.items():
            if k == "exclusions":
                continue
            Session.add(PartyConstraint(party_name=party_name, key=k, value=str(v)))
        Session.query(PartyExclusion).filter_by(party_name=party_name).delete()
        for group in data.get("exclusions", []):
            Session.add(PartyExclusion(party_name=party_name, jobs=",".join(group)))
        Session.commit()
    finally:
        Session.remove()

# --- Admin / App State ---

def get_role_ids(guild_id: str) -> set[str]:
    try:
        roles = Session.query(AdminRole).filter_by(guild_id=guild_id).all()
        return {r.role_id for r in roles}
    finally:
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

def bot_owner_id() -> str | None:
    try:
        state = Session.query(AppState).filter_by(key='bot_owner_id').first()
        return state.value if state else None
    finally:
        Session.remove()

# --- Lodestone / Scraper ---

def cache_character(lodestone_id: str, data: dict[str, Any]) -> None:
    import json
    from datetime import datetime
    try:
        Session.merge(CharacterCache(lodestone_id=lodestone_id, data=json.dumps(data), fetched_at=datetime.now().isoformat()))
        Session.commit()
    finally:
        Session.remove()

def get_cached_character(lodestone_id: str) -> dict[str, Any] | None:
    import json
    try:
        row = Session.query(CharacterCache).filter_by(lodestone_id=lodestone_id).first()
        if not row: return None
        data = json.loads(row.data)
        data["fetched_at"] = row.fetched_at
        return data
    finally:
        Session.remove()

def get_character_data(person_name: str) -> dict[str, Any] | None:
    import json
    try:
        person = Session.query(PersonModel).filter_by(name=person_name).first()
        if not person or not person.lodestone: return None
        cache = Session.query(CharacterCache).filter_by(lodestone_id=person.lodestone.lodestone_id).first()
        if not cache: return None
        data = json.loads(cache.data)
        data["character_name"] = person.lodestone.character_name
        return data
    finally:
        Session.remove()

def add_scraper_task(lodestone_id: str, priority: int = 1) -> None:
    from datetime import datetime
    try:
        Session.merge(ScraperTask(lodestone_id=lodestone_id, priority=priority, created_at=datetime.now().isoformat()))
        Session.commit()
    finally:
        Session.remove()

def get_next_scraper_task() -> dict[str, Any] | None:
    try:
        task = Session.query(ScraperTask).order_by(ScraperTask.priority.desc(), ScraperTask.created_at.asc()).first()
        return {"lodestone_id": task.lodestone_id, "priority": task.priority} if task else None
    finally:
        Session.remove()

def delete_scraper_task(lodestone_id: str) -> None:
    try:
        Session.query(ScraperTask).filter_by(lodestone_id=lodestone_id).delete()
        Session.commit()
    finally:
        Session.remove()

def get_lodestone_link(person_id: int) -> dict[str, Any] | None:
    try:
        link = Session.query(LodestoneLink).filter_by(person_id=person_id).first()
        return {"lodestone_id": link.lodestone_id, "character_name": link.character_name, "fetched_at": link.fetched_at} if link else None
    finally:
        Session.remove()

def set_lodestone_link(person_id: int, lodestone_id: str, character_name: str | None = None) -> None:
    from datetime import datetime
    try:
        Session.merge(LodestoneLink(person_id=person_id, lodestone_id=lodestone_id, character_name=character_name, fetched_at=datetime.now().isoformat()))
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

# --- Parties ---

def create_party(name: str) -> None:
    try:
        Session.add(Party(name=name))
        Session.commit()
    finally:
        Session.remove()

def active_party_name() -> str:
    try:
        state = Session.query(AppState).filter_by(key='active_party').first()
        return state.value if state else "Default"
    finally:
        Session.remove()

def switch_party(name: str) -> None:
    try:
        state = Session.query(AppState).filter_by(key='active_party').first()
        if state: state.value = name
        else: Session.add(AppState(key='active_party', value=name))
        Session.commit()
    finally:
        Session.remove()

def get_parties_details() -> list[dict[str, Any]]:
    try:
        parties = Session.query(Party).all()
        return [{"name": p.name, "home_channel_id": p.home_channel_id} for p in parties]
    finally:
        Session.remove()

def get_party_members(party_name: str) -> list[dict[str, Any]]:
    try:
        results = Session.query(PartyPerson).options(joinedload(PartyPerson.person).joinedload(PersonModel.lodestone)).filter_by(party_name=party_name).all()
        members = []
        for pp in results:
            char_data = None
            if pp.person.lodestone:
                cache = Session.query(CharacterCache).filter_by(lodestone_id=pp.person.lodestone.lodestone_id).first()
                if cache: char_data = {"fetched_at": cache.fetched_at}
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

def get_parties_for_lodestone_id(lodestone_id: str) -> list[dict[str, Any]]:
    try:
        results = Session.query(PartyPerson).join(PartyPerson.person).join(PersonModel.lodestone).filter(LodestoneLink.lodestone_id == lodestone_id).all()
        party_names = {r.party_name for r in results}
        parties = Session.query(Party).filter(Party.name.in_(party_names)).all()
        output = []
        for p in parties:
            if p.home_channel_id and p.home_message_id:
                output.append({'channel_id': p.home_channel_id, 'message_id': p.home_message_id, 'name': p.name})
        return output
    finally:
        Session.remove()
