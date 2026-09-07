"""Tests for the Operational Store persistence foundation."""

from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from sofias_assistant.persistence.database import (
    SQLITE_BUSY_TIMEOUT_MS,
    create_async_engine,
)
from sofias_assistant.persistence.models import Base


@pytest.mark.asyncio
async def test_file_based_engine_does_not_create_a_database_before_connecting(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "operational.sqlite"
    database_url = f"sqlite+aiosqlite:///{database_path.as_posix()}"

    assert not database_path.exists()

    engine = create_async_engine(database_url)
    try:
        assert not database_path.exists()
    finally:
        await engine.dispose()


def test_base_metadata_contains_mapped_operational_tables() -> None:
    assert set(Base.metadata.tables) == {
        "application_settings",
        "conversations",
        "runtime_sessions",
        "turns",
    }


@pytest.mark.asyncio
async def test_sqlite_engine_enables_required_pragmas() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    try:
        assert isinstance(engine, AsyncEngine)

        async with engine.connect() as connection:
            foreign_keys = await connection.scalar(text("PRAGMA foreign_keys"))
            busy_timeout = await connection.scalar(text("PRAGMA busy_timeout"))

        assert foreign_keys == 1
        assert busy_timeout == SQLITE_BUSY_TIMEOUT_MS
    finally:
        await engine.dispose()
