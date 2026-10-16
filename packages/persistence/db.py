"""Engine / session management."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from packages.config import get_settings

_override_url: str | None = None


def set_database_url(url: str | None) -> None:
    """Used by tests to point the whole app at the test database."""
    global _override_url
    _override_url = url
    get_engine.cache_clear()
    get_sessionmaker.cache_clear()


@lru_cache
def get_engine() -> Engine:
    url = _override_url or get_settings().database_url
    return create_engine(url, pool_pre_ping=True, pool_size=10, max_overflow=10, future=True)


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)


@contextmanager
def session_scope() -> Iterator[Session]:
    session = get_sessionmaker()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency."""
    session = get_sessionmaker()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def ping() -> bool:
    with get_engine().connect() as conn:
        return conn.execute(text("select 1")).scalar() == 1
