"""Per-day SQLite database for the live dashboard.

Separate from ``data/kp_cricket.db`` (historical backfill). One file per calendar
day: ``data/live/live_YYYY-MM-DD.db`` with the same ORM schema.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from db.session import Base

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_LIVE_DIR = _PROJECT_ROOT / "data" / "live"


def day_db_path(day: date | datetime | str) -> Path:
    if isinstance(day, datetime):
        day = day.date()
    if isinstance(day, str):
        day = date.fromisoformat(day[:10])
    _LIVE_DIR.mkdir(parents=True, exist_ok=True)
    return _LIVE_DIR / f"live_{day.isoformat()}.db"


def day_database_url(day: date | datetime | str) -> str:
    return f"sqlite:///{day_db_path(day).as_posix()}"


@lru_cache(maxsize=8)
def get_day_engine(day_iso: str):
    engine = create_engine(
        day_database_url(day_iso),
        echo=False,
        future=True,
        connect_args={"check_same_thread": False},
    )
    from db import models  # noqa: F401

    Base.metadata.create_all(engine)
    return engine


def get_day_session_factory(day: date | datetime | str) -> sessionmaker:
    day_iso = day.isoformat() if isinstance(day, date) else str(day)[:10]
    engine = get_day_engine(day_iso)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


@contextmanager
def day_session(day: date | datetime | str) -> Iterator[Session]:
    factory = get_day_session_factory(day)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
