from __future__ import annotations

from collections.abc import Generator
from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from config.settings import get_settings
from database.base import Base


def _is_sqlite(database_url: str) -> bool:
    return database_url.startswith("sqlite")


def _engine_kwargs(database_url: str) -> dict[str, Any]:
    if _is_sqlite(database_url):
        return {"connect_args": {"check_same_thread": False, "timeout": 30}}
    return {}


def _configure_sqlite_connection(dbapi_connection, _connection_record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


settings = get_settings()

engine = create_engine(settings.database_url, future=True, **_engine_kwargs(settings.database_url))


if _is_sqlite(settings.database_url):
    event.listens_for(engine, "connect")(_configure_sqlite_connection)


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def create_database() -> None:
    from database import models  # noqa: F401

    Base.metadata.create_all(bind=engine)


def get_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
