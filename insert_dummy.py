import os
os.environ["DATABASE_PATH"] = "test.db"
from app.db import init_db, Session, Party
from sqlalchemy.exc import IntegrityError

# Initialize and add a dummy entry
try:
    init_db()
    if not Session.query(Party).filter_by(name='DummyEntry').first():
        Session.add(Party(name='DummyEntry'))
        Session.commit()
        print("Dummy entry 'DummyEntry' added to test.db")
    else:
        print("Dummy entry already exists.")
except Exception as e:
    print(f"Error: {e}")
finally:
    Session.remove()
