"""Engine and session factory (SQLAlchemy 2.0, synchronous).

Only services open and close transactions. Repositories receive a Session and never commit.
"""

from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


@lru_cache
def get_engine() -> Engine:
    # Explicit isolation pin (not the database default): the assessment fingerprint re-check relies on READ COMMITTED.
    return create_engine(get_settings().database_url, pool_pre_ping=True, future=True, isolation_level="READ COMMITTED")


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def new_session() -> Session:
    return get_session_factory()()


def session_scope() -> Iterator[Session]:
    """FastAPI-style dependency body: one session per request, always closed."""
    session = new_session()
    try:
        yield session
    finally:
        session.close()
