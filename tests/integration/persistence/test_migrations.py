"""Integration tests for Alembic Operational Store migrations."""

import sqlite3
from asyncio import to_thread
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import StatementError
from sqlalchemy.ext.asyncio import async_sessionmaker

from sofias_assistant.persistence.database import (
    SQLITE_BUSY_TIMEOUT_MS,
    create_async_engine,
)
from sofias_assistant.persistence.migration_runner import (
    downgrade_to_base,
    upgrade_to_head,
)
from sofias_assistant.persistence.models import (
    ApplicationSetting,
    RuntimeSession,
    RuntimeSessionStatus,
)

HEAD_REVISION = "0001_initial_operational_schema"
DOMAIN_TABLES = {"runtime_sessions", "application_settings"}


def database_url(tmp_path: Path) -> str:
    return f"sqlite+aiosqlite:///{(tmp_path / 'operational.sqlite').as_posix()}"


def table_names(database_url: str) -> set[str]:
    path = database_url.removeprefix("sqlite+aiosqlite:///")
    with sqlite3.connect(path) as connection:
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    return {row[0] for row in rows}


def test_upgrade_to_head_is_idempotent(tmp_path: Path) -> None:
    url = database_url(tmp_path)
    upgrade_to_head(url)
    upgrade_to_head(url)

    assert DOMAIN_TABLES <= table_names(url)
    assert "alembic_version" in table_names(url)
    path = url.removeprefix("sqlite+aiosqlite:///")
    with sqlite3.connect(path) as connection:
        revision = connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone()[0]
    assert revision == HEAD_REVISION


def test_downgrade_to_base_then_upgrade_to_head(tmp_path: Path) -> None:
    url = database_url(tmp_path)
    upgrade_to_head(url)
    downgrade_to_base(url)
    assert not (DOMAIN_TABLES & table_names(url))

    upgrade_to_head(url)
    assert DOMAIN_TABLES <= table_names(url)


@pytest.mark.asyncio
async def test_models_roundtrip_uuid_utc_datetime_settings_and_sqlite_pragmas(
    tmp_path: Path,
) -> None:
    url = database_url(tmp_path)
    await to_thread(upgrade_to_head, url)
    engine = create_async_engine(url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    session_id = uuid4()
    started_at = datetime(2026, 8, 31, 9, 0, tzinfo=timezone(timedelta(hours=-3)))

    try:
        async with session_factory() as session:
            session.add(
                RuntimeSession(
                    id=session_id,
                    started_at=started_at,
                    status=RuntimeSessionStatus.RUNNING,
                    application_version="0.1.0.dev0",
                )
            )
            session.add(
                ApplicationSetting(
                    key="theme", value_json='"dark"', updated_at=started_at
                )
            )
            await session.commit()

            runtime_session = await session.get(RuntimeSession, session_id)
            setting = await session.get(ApplicationSetting, "theme")
            assert runtime_session is not None
            assert setting is not None
            assert runtime_session.id == session_id
            assert runtime_session.started_at == datetime(
                2026, 8, 31, 12, 0, tzinfo=UTC
            )
            assert setting.value_json == '"dark"'
            assert setting.updated_at == datetime(2026, 8, 31, 12, 0, tzinfo=UTC)

            session.add(
                RuntimeSession(
                    id=uuid4(),
                    started_at=datetime(2026, 8, 31, 12, 0),
                    status=RuntimeSessionStatus.RUNNING,
                    application_version="0.1.0.dev0",
                )
            )
            with pytest.raises(StatementError, match="timezone-aware"):
                await session.commit()
            await session.rollback()

        async with engine.connect() as connection:
            assert await connection.scalar(text("PRAGMA foreign_keys")) == 1
            assert (
                await connection.scalar(text("PRAGMA busy_timeout"))
                == SQLITE_BUSY_TIMEOUT_MS
            )
    finally:
        await engine.dispose()
