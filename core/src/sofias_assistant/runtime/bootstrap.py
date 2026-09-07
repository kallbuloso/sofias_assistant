"""Explicit bootstrap for a usable Operational Store runtime boundary."""

from asyncio import to_thread
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from sofias_assistant.config.models import RuntimeConfig
from sofias_assistant.persistence.database import (
    create_async_engine,
    create_session_factory,
    enable_sqlite_file_wal,
)
from sofias_assistant.persistence.migration_runner import upgrade_to_head


@dataclass(frozen=True, slots=True)
class RuntimeResources:
    """Lifecycle-owned persistence resources created by runtime bootstrap."""

    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]

    async def close(self) -> None:
        """Release the long-lived runtime database engine."""

        await self.engine.dispose()


async def bootstrap_runtime(config: RuntimeConfig) -> RuntimeResources:
    """Materialize configured paths and initialize a migrated Operational Store."""

    _materialize_runtime_paths(config)
    database_url = operational_database_url(config.paths.operational_database)
    await to_thread(upgrade_to_head, database_url)

    engine = create_async_engine(database_url)
    try:
        await enable_sqlite_file_wal(engine)
        session_factory = create_session_factory(engine)
    except BaseException:
        await engine.dispose()
        raise

    return RuntimeResources(engine=engine, session_factory=session_factory)


def operational_database_url(database_path: Path) -> str:
    """Build an async SQLite URL from an explicit operational database path."""

    return str(URL.create("sqlite+aiosqlite", database=database_path.as_posix()))


def _materialize_runtime_paths(config: RuntimeConfig) -> None:
    config.paths.data_dir.mkdir(parents=True, exist_ok=True)
    config.paths.logs_dir.mkdir(parents=True, exist_ok=True)
