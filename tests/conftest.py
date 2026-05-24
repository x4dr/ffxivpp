import pytest
import os
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.append(str(Path(__file__).parent.parent.parent.resolve()))

from app import create_app
from app.db import Base, engine, Session

@pytest.fixture(scope="session")
def app():
    """Session-wide test Flask application."""
    config_override = {
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "GUILD_ID": "298197955951984640",
    }

    
    os.environ["GUILD_ID"] = "298197955951984640"
    
    app = create_app(config_override)
    
    # Create database tables
    Base.metadata.create_all(engine)
    
    yield app
    
    # Teardown
    Base.metadata.drop_all(engine)

@pytest.fixture(autouse=True)
def db_session(app):
    """
    Creates a new database session for a test,
    with all changes rolled back at the end.
    """
    connection = engine.connect()
    transaction = connection.begin()
    
    # This setup relies on the fact that app/db.py uses a scoped_session.
    # We must explicitly bind the Session to the connection.
    old_session = Session
    Session.configure(bind=connection)
    
    yield Session
    
    transaction.rollback()
    connection.close()
    Session.remove()
    Session.configure(bind=engine)

@pytest.fixture
def client(app):
    """A test client for the app."""
    return app.test_client()



