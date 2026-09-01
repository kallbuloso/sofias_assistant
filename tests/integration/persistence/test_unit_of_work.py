"""Integration tests for the transaction boundary."""

from asyncio import to_thread
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from sofias_assistant.persistence.database import (
    create_async_engine,
    create_session_factory,
)
from sofias_assistant.persistence.migration_runner import upgrade_to_head
from sofias_assistant.persistence.models import (
    ApplicationSetting,
    RuntimeSession,
    RuntimeSessionStatus,
)
from sofias_assistant.persistence.unit_of_work import SqlAlchemyUnitOfWork


def database_url(tmp_path: Path) -> str:
    return f"sqlite+aiosqlite:///{(tmp_path / 'operational.sqlite').as_posix()}"


@pytest.mark.asyncio
async def test_session_factory_creates_independent_sessions(tmp_path: Path) -> None:
    engine = create_async_engine(database_url(tmp_path))
    factory = create_session_factory(engine)
    try:
        first, second = factory(), factory()
        assert isinstance(first, AsyncSession)
        assert first is not second
        assert factory.kw["expire_on_commit"] is False
        await first.close()
        await second.close()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_unit_of_work_commit_queries_and_atomic_repositories(
    tmp_path: Path,
) -> None:
    url = database_url(tmp_path)
    await to_thread(upgrade_to_head, url)
    engine = create_async_engine(url)
    factory = create_session_factory(engine)
    session_id = uuid4()
    try:
        async with SqlAlchemyUnitOfWork(factory) as uow:
            uow.runtime_sessions.add(
                RuntimeSession(
                    id=session_id,
                    started_at=datetime.now(UTC),
                    status=RuntimeSessionStatus.RUNNING,
                    application_version="test",
                )
            )
            uow.application_settings.add(
                ApplicationSetting(
                    key="theme", value_json='"dark"', updated_at=datetime.now(UTC)
                )
            )
            await uow.commit()
        async with SqlAlchemyUnitOfWork(factory) as uow:
            assert (await uow.runtime_sessions.get_by_id(session_id)) is not None
            assert (await uow.application_settings.get_by_key("theme")) is not None
            assert {
                item.id
                for item in await uow.runtime_sessions.list_by_status(
                    RuntimeSessionStatus.RUNNING
                )
            } == {session_id}
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_no_commit_exception_and_flush_do_not_persist(tmp_path: Path) -> None:
    url = database_url(tmp_path)
    await to_thread(upgrade_to_head, url)
    engine = create_async_engine(url)
    factory = create_session_factory(engine)
    ids = [uuid4(), uuid4(), uuid4()]
    try:
        async with SqlAlchemyUnitOfWork(factory) as uow:
            uow.runtime_sessions.add(
                RuntimeSession(
                    id=ids[0],
                    started_at=datetime.now(UTC),
                    status=RuntimeSessionStatus.RUNNING,
                    application_version="test",
                )
            )
        with pytest.raises(ValueError):
            async with SqlAlchemyUnitOfWork(factory) as uow:
                uow.runtime_sessions.add(
                    RuntimeSession(
                        id=ids[1],
                        started_at=datetime.now(UTC),
                        status=RuntimeSessionStatus.RUNNING,
                        application_version="test",
                    )
                )
                await uow.flush()
                raise ValueError("rollback")
        async with SqlAlchemyUnitOfWork(factory) as uow:
            uow.runtime_sessions.add(
                RuntimeSession(
                    id=ids[2],
                    started_at=datetime.now(UTC),
                    status=RuntimeSessionStatus.STOPPED,
                    application_version="test",
                )
            )
            await uow.flush()
        async with SqlAlchemyUnitOfWork(factory) as uow:
            persisted = [
                await uow.runtime_sessions.get_by_id(item_id) for item_id in ids
            ]
            assert persisted == [None, None, None]
    finally:
        await engine.dispose()
