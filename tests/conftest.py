import os
import sys
from pathlib import Path

import pytest

# Add project root to sys.path
sys.path.append(str(Path(__file__).parent.parent.parent.resolve()))

# DATABASE_PATH must be set before any app.db import to prevent a RuntimeError
# from _get_database_url().  We set it to a harmless path; the real test engine
# is installed below via set_engine_for_tests("sqlite://") so no file is created.
os.environ["DATABASE_PATH"] = "/tmp/.ffxivpp_test_init.db"

from app import create_app
from app.db import (
    Base,
    Session,
    get_engine,
    reset_engine,
    set_engine_for_tests,
)


@pytest.fixture(scope="session")
def app():
    """Session-wide test Flask application backed by an in-memory SQLite database."""
    config_override = {
        "TESTING": True,
        "GUILD_ID": "298197955951984640",
    }

    os.environ["GUILD_ID"] = "298197955951984640"

    set_engine_for_tests("sqlite://")

    app = create_app(config_override)

    Base.metadata.create_all(get_engine())

    yield app

    Base.metadata.drop_all(get_engine())
    reset_engine()


def _clean_db() -> None:
    """Remove all application data, then re-seed base state.

    Ordering respects foreign-key dependencies (children first).
    """
    from app.db import (
        AdminRole,
        AppState,
        CharacterCache,
        LodestoneLink,
        Party,
        PartyConstraint,
        PartyExclusion,
        PartyPerson,
        PersonModel,
        ScraperTask,
    )
    tables = [
        PartyPerson,
        PartyConstraint,
        PartyExclusion,
        LodestoneLink,
        PersonModel,
        Party,
        AppState,
        AdminRole,
        CharacterCache,
        ScraperTask,
    ]
    for tbl in tables:
        Session.query(tbl).delete()
    Session.commit()
    from app.db import init_db
    init_db()


@pytest.fixture(autouse=True)
def db_session(app):
    """Provide a clean database session for each test.

    Truncates all tables before each test and re-seeds the base state
    (Default party, active party).  This guarantees full test isolation
    without relying on savepoints or nested transactions.
    """
    Session.configure(bind=get_engine())
    _clean_db()
    yield Session
    Session.remove()


@pytest.fixture
def client(app):
    """A test client for the app."""
    return app.test_client()


@pytest.fixture
def auto_auth():
    """Bypass Discord OAuth for endpoint tests that require authentication."""
    from unittest.mock import MagicMock, patch

    with (
        patch("app.auth.get_discord") as mock_get_discord,
        patch("app.auth._bot_api") as mock_bot_api,
    ):
        discord = MagicMock()
        discord.authorized = True
        discord.fetch_user.return_value.id = "12345"
        mock_get_discord.return_value = discord
        mock_bot_api.return_value = {"owner_id": "12345"}
        yield
