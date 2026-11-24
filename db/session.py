"""Database engine/session management.

Local-first (SQLite) but cloud-ready: the connection string comes from the
DATABASE_URL environment variable, so switching to PostgreSQL later is a
config change, not a code change.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

load_dotenv()

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_SQLITE = f"sqlite:///{(_PROJECT_ROOT / 'data' / 'kp_cricket.db').as_posix()}"

DATABASE_URL = os.getenv("DATABASE_URL", _DEFAULT_SQLITE)

# check_same_thread=False lets the live poller share the connection across the
# polling loop; harmless for the single-writer SQLite use case.
_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, echo=False, future=True, connect_args=_connect_args)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def init_db() -> None:
    """Create all tables that do not yet exist."""
    # Import models so they register on Base.metadata before create_all.
    from db import models  # noqa: F401

    # Ensure the SQLite data directory exists.
    if DATABASE_URL.startswith("sqlite"):
        (_PROJECT_ROOT / "data").mkdir(parents=True, exist_ok=True)

    Base.metadata.create_all(engine)


@contextmanager
def get_session():
    """Provide a transactional session scope."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
