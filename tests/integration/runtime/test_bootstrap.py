"""Integration tests for Operational Store runtime bootstrap."""

from pathlib import Path

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession

from sofias_assistant.config.models import AppPaths, RuntimeConfig
from sofias_assistant.persistence.database import SQLITE_BUSY_TIMEOUT_MS
from sofias_assistant.runtime import bootstrap_runtime

HEAD_REVISION = "0002_conversation_operational_schema"
EXPECTED_TABLES = {
    "alembic_version",
    "application_settings",
    "conversations",
    "runtime_sessions",
    "turns",
}


def runtime_config(tmp_path: Path) -> RuntimeConfig:
    return RuntimeConfig(paths=AppPaths(data_dir=tmp_path / "runtime-data"))


@pytest.mark.asyncio
async def test_bootstrap_materializes_paths_migrates_and_configures_sqlite(
    tmp_path: Path,
) -> None:
    config = runtime_config(tmp_path)
    assert not config.paths.data_dir.exists()

    resources = await bootstrap_runtime(config)
    try:
        assert config.paths.data_dir.is_dir()
        assert config.paths.logs_dir.is_dir()
        assert config.paths.operational_database.is_file()

        async with resources.engine.connect() as connection:
            table_names = await connection.run_sync(
                lambda sync_connection: set(inspect(sync_connection).get_table_names())
            )
            revision = await connection.scalar(
                text("SELECT version_num FROM alembic_version")
            )
            journal_mode = await connection.scalar(text("PRAGMA journal_mode"))
            foreign_keys = await connection.scalar(text("PRAGMA foreign_keys"))
            busy_timeout = await connection.scalar(text("PRAGMA busy_timeout"))

        assert EXPECTED_TABLES <= table_names
        assert revision == HEAD_REVISION
        assert str(journal_mode).lower() == "wal"
        assert foreign_keys == 1
        assert busy_timeout == SQLITE_BUSY_TIMEOUT_MS

        async with resources.session_factory() as session:
            assert isinstance(session, AsyncSession)
            assert await session.scalar(text("SELECT 1")) == 1
    finally:
        await resources.close()


@pytest.mark.asyncio
async def test_runtime_resources_close_without_error(tmp_path: Path) -> None:
    resources = await bootstrap_runtime(runtime_config(tmp_path))

    await resources.close()


@pytest.mark.asyncio
async def test_repeated_bootstrap_keeps_schema_and_wal_at_head(tmp_path: Path) -> None:
    config = runtime_config(tmp_path)
    first_resources = await bootstrap_runtime(config)
    await first_resources.close()

    second_resources = await bootstrap_runtime(config)
    try:
        async with second_resources.engine.connect() as connection:
            revision = await connection.scalar(
                text("SELECT version_num FROM alembic_version")
            )
            journal_mode = await connection.scalar(text("PRAGMA journal_mode"))

        assert revision == HEAD_REVISION
        assert str(journal_mode).lower() == "wal"
    finally:
        await second_resources.close()
