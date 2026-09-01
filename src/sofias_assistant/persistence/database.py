"""Async SQLAlchemy engine factory for the Operational Store."""

from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.ext.asyncio import create_async_engine as sqlalchemy_create_async_engine

SQLITE_BUSY_TIMEOUT_MS = 5_000


def create_async_engine(database_url: str) -> AsyncEngine:
    """Create an async engine for an explicitly supplied database URL."""
    engine = sqlalchemy_create_async_engine(database_url)

    if engine.dialect.name == "sqlite":
        _configure_sqlite_pragmas(engine)

    return engine


def _configure_sqlite_pragmas(engine: AsyncEngine) -> None:
    @event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_pragmas(dbapi_connection: Any, _: Any) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys = ON")
            cursor.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}")
        finally:
            cursor.close()
