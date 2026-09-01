"""Async SQLAlchemy engine factory for the Operational Store."""

from typing import Any

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.ext.asyncio import create_async_engine as sqlalchemy_create_async_engine

SQLITE_BUSY_TIMEOUT_MS = 5_000
SQLITE_JOURNAL_MODE_WAL = "wal"


def create_async_engine(database_url: str) -> AsyncEngine:
    """Create an async engine for an explicitly supplied database URL."""
    engine = sqlalchemy_create_async_engine(database_url)

    if engine.dialect.name == "sqlite":
        _configure_sqlite_pragmas(engine)

    return engine


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create independent async sessions bound to an explicit engine."""
    return async_sessionmaker(engine, expire_on_commit=False)


async def enable_sqlite_file_wal(engine: AsyncEngine) -> None:
    """Enable and verify WAL once for a file-backed SQLite database."""

    if engine.dialect.name != "sqlite":
        raise ValueError("WAL initialization requires a SQLite engine")
    if engine.url.database in {None, ":memory:"}:
        raise ValueError("WAL initialization requires a file-backed SQLite database")

    async with engine.connect() as connection:
        journal_mode = await connection.scalar(text("PRAGMA journal_mode=WAL"))

    if str(journal_mode).lower() != SQLITE_JOURNAL_MODE_WAL:
        raise RuntimeError("SQLite did not enable WAL journal mode")


def _configure_sqlite_pragmas(engine: AsyncEngine) -> None:
    @event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_pragmas(dbapi_connection: Any, _: Any) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys = ON")
            cursor.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}")
        finally:
            cursor.close()
