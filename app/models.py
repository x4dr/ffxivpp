from dataclasses import dataclass
from typing import Any, List, Optional
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy import ForeignKey, String, Integer, Text

# --- Dataclasses for Compute ---
@dataclass
class Job:
    id: str
    name: str
    role: str
    sub: str
    dps_type: Optional[str] = None

@dataclass
class Person:
    name: str
    jobs: List[str]
    discord_id: Optional[str] = None

@dataclass
class Assignment:
    name: str
    job: str
    role: str

@dataclass
class Constraints:
    std_comp: bool = True
    no_dupes: bool = True
    heal_mix: bool = False
    max_melee: int = 4
    max_pranged: int = 4
    max_caster: int = 4
    min_melee: int = 0
    min_pranged: int = 0
    min_caster: int = 0
    min_selfish: int = 0
    max_selfish: int = 4
    min_utility: int = 0
    max_utility: int = 4
    min_gear_level: int = 0
    exclusions: List[List[str]] = None  # type: ignore

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Constraints":
        return cls(
            std_comp=d.get("std_comp", True),
            no_dupes=d.get("no_dupes", True),
            heal_mix=d.get("heal_mix", False),
            max_melee=d.get("max_melee", 4),
            max_pranged=d.get("max_pranged", 4),
            max_caster=d.get("max_caster", 4),
            min_melee=d.get("min_melee", 0),
            min_pranged=d.get("min_pranged", 0),
            min_caster=d.get("min_caster", 0),
            min_selfish=d.get("min_selfish", 0),
            max_selfish=d.get("max_selfish", 4),
            min_utility=d.get("min_utility", 0),
            max_utility=d.get("max_utility", 4),
            min_gear_level=d.get("min_gear_level", 0),
            exclusions=d.get("exclusions", []),
        )

# --- SQLAlchemy Models ---
class Base(DeclarativeBase):
    pass

class Party(Base):
    __tablename__ = "parties"
    name: Mapped[str] = mapped_column(String, primary_key=True)
    home_channel_id: Mapped[Optional[str]] = mapped_column(Text)
    home_message_id: Mapped[Optional[str]] = mapped_column(Text)
    members: Mapped[List["PartyPerson"]] = relationship("PartyPerson", back_populates="party", cascade="all, delete-orphan")

class PersonModel(Base):
    __tablename__ = "people"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    jobs: Mapped[str] = mapped_column(Text, default='')
    discord_id: Mapped[Optional[str]] = mapped_column(String)
    lodestone: Mapped[Optional["LodestoneLink"]] = relationship("LodestoneLink", back_populates="person", uselist=False, cascade="all, delete-orphan")
    
class PartyPerson(Base):
    __tablename__ = "party_people"
    party_name: Mapped[str] = mapped_column(ForeignKey("parties.name", ondelete="CASCADE"), primary_key=True)
    person_name: Mapped[str] = mapped_column(ForeignKey("people.name", ondelete="CASCADE"), primary_key=True)
    
    party: Mapped["Party"] = relationship("Party", back_populates="members")
    person: Mapped["PersonModel"] = relationship("PersonModel", backref="party_associations")

class PartyConstraint(Base):
    __tablename__ = "party_constraints"
    party_name: Mapped[str] = mapped_column(ForeignKey("parties.name", ondelete="CASCADE"), primary_key=True)
    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)

class PartyExclusion(Base):
    __tablename__ = "party_exclusions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    party_name: Mapped[str] = mapped_column(ForeignKey("parties.name", ondelete="CASCADE"), nullable=False)
    jobs: Mapped[str] = mapped_column(Text, nullable=False)

class AppState(Base):
    __tablename__ = "app_state"
    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)

class AdminRole(Base):
    __tablename__ = "admin_roles"
    guild_id: Mapped[str] = mapped_column(String, primary_key=True)
    role_id: Mapped[str] = mapped_column(String, primary_key=True)

class LodestoneLink(Base):
    __tablename__ = "lodestone_links"
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id", ondelete="CASCADE"), primary_key=True)
    lodestone_id: Mapped[str] = mapped_column(String, primary_key=True)
    character_name: Mapped[Optional[str]] = mapped_column(String)
    fetched_at: Mapped[Optional[str]] = mapped_column(String)
    person: Mapped["PersonModel"] = relationship("PersonModel", back_populates="lodestone")

class CharacterCache(Base):
    __tablename__ = "character_cache"
    lodestone_id: Mapped[str] = mapped_column(String, primary_key=True)
    data: Mapped[str] = mapped_column(Text, nullable=False)
    fetched_at: Mapped[str] = mapped_column(String, nullable=False)

class ScraperTask(Base):
    __tablename__ = "scraper_tasks"
    lodestone_id: Mapped[str] = mapped_column(String, primary_key=True)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
