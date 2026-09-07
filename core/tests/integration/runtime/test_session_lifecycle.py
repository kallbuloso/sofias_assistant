"""Integration tests for persistent runtime session lifecycle transitions."""

from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from sofias_assistant.config.models import AppPaths, RuntimeConfig
from sofias_assistant.persistence.models import RuntimeSession, RuntimeSessionStatus
from sofias_assistant.persistence.unit_of_work import SqlAlchemyUnitOfWork
from sofias_assistant.runtime import RuntimeSessionLifecycle, bootstrap_runtime


def runtime_config(tmp_path: Path) -> RuntimeConfig:
    return RuntimeConfig(paths=AppPaths(data_dir=tmp_path / "runtime-data"))


async def add_sessions(
    session_factory: async_sessionmaker,
    sessions: list[RuntimeSession],
) -> None:
    async with SqlAlchemyUnitOfWork(session_factory) as unit_of_work:
        for session in sessions:
            unit_of_work.runtime_sessions.add(session)
        await unit_of_work.commit()


async def persisted_sessions(
    session_factory: async_sessionmaker,
) -> dict[UUID, RuntimeSession]:
    async with SqlAlchemyUnitOfWork(session_factory) as unit_of_work:
        sessions = list(await unit_of_work.session.scalars(select(RuntimeSession)))
        unit_of_work.session.expunge_all()
    return {session.id: session for session in sessions}


@pytest.mark.asyncio
async def test_clean_first_start_creates_the_current_running_session(
    tmp_path: Path,
) -> None:
    resources = await bootstrap_runtime(runtime_config(tmp_path))
    started_at = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)
    lifecycle = RuntimeSessionLifecycle(
        resources.session_factory,
        application_version="0.1.0.dev0",
        clock=lambda: started_at,
    )
    try:
        current_session = await lifecycle.start()
        sessions = await persisted_sessions(resources.session_factory)

        assert set(sessions) == {current_session.id}
        assert current_session.status is RuntimeSessionStatus.RUNNING
        assert current_session.stopped_at is None
        assert current_session.application_version == "0.1.0.dev0"
        assert current_session.started_at == started_at
        assert current_session.started_at.tzinfo is UTC
        assert lifecycle.active_session_id == current_session.id
    finally:
        await resources.close()


@pytest.mark.asyncio
async def test_start_recovers_one_previous_running_session_without_stop_time(
    tmp_path: Path,
) -> None:
    resources = await bootstrap_runtime(runtime_config(tmp_path))
    previous_session = RuntimeSession(
        id=uuid4(),
        started_at=datetime(2026, 8, 31, 9, 0, tzinfo=UTC),
        status=RuntimeSessionStatus.RUNNING,
        application_version="previous",
    )
    await add_sessions(resources.session_factory, [previous_session])
    lifecycle = RuntimeSessionLifecycle(
        resources.session_factory,
        application_version="current",
        clock=lambda: datetime(2026, 9, 1, 9, 0, tzinfo=UTC),
    )
    try:
        current_session = await lifecycle.start()
        sessions = await persisted_sessions(resources.session_factory)
        recovered_session = sessions[previous_session.id]

        assert recovered_session.status is RuntimeSessionStatus.INTERRUPTED
        assert recovered_session.stopped_at is None
        assert sessions[current_session.id].status is RuntimeSessionStatus.RUNNING
        assert [
            session
            for session in sessions.values()
            if session.status is RuntimeSessionStatus.RUNNING
        ] == [sessions[current_session.id]]
    finally:
        await resources.close()


@pytest.mark.asyncio
async def test_start_recovers_all_previous_running_sessions(tmp_path: Path) -> None:
    resources = await bootstrap_runtime(runtime_config(tmp_path))
    previous_sessions = [
        RuntimeSession(
            id=uuid4(),
            started_at=datetime(2026, 8, 31, 9, index, tzinfo=UTC),
            status=RuntimeSessionStatus.RUNNING,
            application_version="previous",
        )
        for index in (0, 1, 2)
    ]
    await add_sessions(resources.session_factory, previous_sessions)
    lifecycle = RuntimeSessionLifecycle(
        resources.session_factory,
        application_version="current",
        clock=lambda: datetime(2026, 9, 1, 9, 0, tzinfo=UTC),
    )
    try:
        current_session = await lifecycle.start()
        sessions = await persisted_sessions(resources.session_factory)

        for previous_session in previous_sessions:
            recovered_session = sessions[previous_session.id]
            assert recovered_session.status is RuntimeSessionStatus.INTERRUPTED
            assert recovered_session.stopped_at is None
        assert {
            session.id
            for session in sessions.values()
            if session.status is RuntimeSessionStatus.RUNNING
        } == {current_session.id}
    finally:
        await resources.close()


@pytest.mark.asyncio
async def test_clean_stop_persists_stopped_at_in_utc(tmp_path: Path) -> None:
    resources = await bootstrap_runtime(runtime_config(tmp_path))
    started_at = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)
    stopped_at = datetime(2026, 9, 1, 9, 5, tzinfo=UTC)
    timestamps = iter((started_at, stopped_at))
    lifecycle = RuntimeSessionLifecycle(
        resources.session_factory,
        application_version="current",
        clock=lambda: next(timestamps),
    )
    try:
        current_session = await lifecycle.start()
        stopped_session = await lifecycle.stop()
        sessions = await persisted_sessions(resources.session_factory)

        assert stopped_session.id == current_session.id
        assert sessions[current_session.id].status is RuntimeSessionStatus.STOPPED
        persisted_stopped_at = sessions[current_session.id].stopped_at
        assert persisted_stopped_at == stopped_at
        assert persisted_stopped_at is not None
        assert persisted_stopped_at.tzinfo is UTC
        assert not [
            session
            for session in sessions.values()
            if session.status is RuntimeSessionStatus.RUNNING
        ]
        assert lifecycle.active_session_id is None
    finally:
        await resources.close()


@pytest.mark.asyncio
async def test_non_utc_aware_clock_is_normalized_to_utc(tmp_path: Path) -> None:
    resources = await bootstrap_runtime(runtime_config(tmp_path))
    non_utc_time = datetime(2026, 9, 1, 9, 0, tzinfo=timezone(timedelta(hours=-3)))
    lifecycle = RuntimeSessionLifecycle(
        resources.session_factory,
        application_version="current",
        clock=lambda: non_utc_time,
    )
    try:
        current_session = await lifecycle.start()

        assert current_session.started_at == datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
        assert current_session.started_at.tzinfo is UTC
    finally:
        await resources.close()


@pytest.mark.asyncio
async def test_naive_clock_is_rejected_without_recovering_existing_sessions(
    tmp_path: Path,
) -> None:
    resources = await bootstrap_runtime(runtime_config(tmp_path))
    previous_session = RuntimeSession(
        id=uuid4(),
        started_at=datetime(2026, 8, 31, 9, 0, tzinfo=UTC),
        status=RuntimeSessionStatus.RUNNING,
        application_version="previous",
    )
    await add_sessions(resources.session_factory, [previous_session])
    lifecycle = RuntimeSessionLifecycle(
        resources.session_factory,
        application_version="current",
        clock=lambda: datetime(2026, 9, 1, 9, 0),
    )
    try:
        with pytest.raises(ValueError, match="timezone-aware"):
            await lifecycle.start()

        sessions = await persisted_sessions(resources.session_factory)
        assert set(sessions) == {previous_session.id}
        assert sessions[previous_session.id].status is RuntimeSessionStatus.RUNNING
    finally:
        await resources.close()


@pytest.mark.asyncio
async def test_double_start_is_rejected_without_creating_a_second_session(
    tmp_path: Path,
) -> None:
    resources = await bootstrap_runtime(runtime_config(tmp_path))
    lifecycle = RuntimeSessionLifecycle(
        resources.session_factory,
        application_version="current",
        clock=lambda: datetime(2026, 9, 1, 9, 0, tzinfo=UTC),
    )
    try:
        current_session = await lifecycle.start()

        with pytest.raises(RuntimeError, match="already started"):
            await lifecycle.start()

        assert set(await persisted_sessions(resources.session_factory)) == {
            current_session.id
        }
    finally:
        await resources.close()


@pytest.mark.asyncio
async def test_stop_before_start_is_rejected_without_database_changes(
    tmp_path: Path,
) -> None:
    resources = await bootstrap_runtime(runtime_config(tmp_path))
    lifecycle = RuntimeSessionLifecycle(
        resources.session_factory,
        application_version="current",
        clock=lambda: datetime(2026, 9, 1, 9, 0, tzinfo=UTC),
    )
    try:
        with pytest.raises(RuntimeError, match="has not started"):
            await lifecycle.stop()

        assert await persisted_sessions(resources.session_factory) == {}
    finally:
        await resources.close()


@pytest.mark.asyncio
async def test_stop_twice_is_rejected_after_clean_stop(tmp_path: Path) -> None:
    resources = await bootstrap_runtime(runtime_config(tmp_path))
    timestamps = iter(
        (
            datetime(2026, 9, 1, 9, 0, tzinfo=UTC),
            datetime(2026, 9, 1, 9, 5, tzinfo=UTC),
        )
    )
    lifecycle = RuntimeSessionLifecycle(
        resources.session_factory,
        application_version="current",
        clock=lambda: next(timestamps),
    )
    try:
        current_session = await lifecycle.start()
        await lifecycle.stop()

        with pytest.raises(RuntimeError, match="has not started"):
            await lifecycle.stop()

        sessions = await persisted_sessions(resources.session_factory)
        assert sessions[current_session.id].status is RuntimeSessionStatus.STOPPED
    finally:
        await resources.close()


@pytest.mark.asyncio
async def test_lifecycle_instance_can_start_again_after_clean_stop(
    tmp_path: Path,
) -> None:
    resources = await bootstrap_runtime(runtime_config(tmp_path))
    timestamps = iter(
        (
            datetime(2026, 9, 1, 9, 0, tzinfo=UTC),
            datetime(2026, 9, 1, 9, 5, tzinfo=UTC),
            datetime(2026, 9, 1, 9, 10, tzinfo=UTC),
        )
    )
    lifecycle = RuntimeSessionLifecycle(
        resources.session_factory,
        application_version="current",
        clock=lambda: next(timestamps),
    )
    try:
        first_session = await lifecycle.start()
        await lifecycle.stop()
        second_session = await lifecycle.start()
        sessions = await persisted_sessions(resources.session_factory)

        assert first_session.id != second_session.id
        assert sessions[first_session.id].status is RuntimeSessionStatus.STOPPED
        assert sessions[second_session.id].status is RuntimeSessionStatus.RUNNING
    finally:
        await resources.close()


@pytest.mark.parametrize("application_version", ["", "   "])
def test_blank_application_version_is_rejected(application_version: str) -> None:
    with pytest.raises(ValueError, match="Application version must not be blank"):
        RuntimeSessionLifecycle(
            async_sessionmaker(), application_version=application_version
        )
