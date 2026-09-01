"""Integration tests for SofiaCore foundation lifecycle composition."""

from datetime import UTC
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import select

from sofias_assistant.config.models import AppPaths, RuntimeConfig
from sofias_assistant.core import CoreState, SofiaCore
from sofias_assistant.health import HealthStatus
from sofias_assistant.persistence.database import (
    create_async_engine,
    create_session_factory,
)
from sofias_assistant.persistence.models import RuntimeSession, RuntimeSessionStatus
from sofias_assistant.persistence.unit_of_work import SqlAlchemyUnitOfWork
from sofias_assistant.runtime import operational_database_url
from sofias_assistant.secrets.models import SecretRef, SecretValue


class FakeSecretStore:
    """In-memory test backend that never accesses Windows Credential Manager."""

    def __init__(self) -> None:
        self._values: dict[str, SecretValue] = {}

    def get(self, ref: SecretRef) -> SecretValue | None:
        return self._values.get(ref.identifier)

    def set(self, ref: SecretRef, value: SecretValue) -> None:
        self._values[ref.identifier] = value

    def delete(self, ref: SecretRef) -> bool:
        return self._values.pop(ref.identifier, None) is not None


class RecordingSecretStoreFactory:
    """Test factory that records lazy SecretStore construction."""

    def __init__(self) -> None:
        self.calls = 0
        self.store = FakeSecretStore()

    def __call__(self) -> FakeSecretStore:
        self.calls += 1
        return self.store


def runtime_config(tmp_path: Path) -> RuntimeConfig:
    return RuntimeConfig(paths=AppPaths(data_dir=tmp_path / "core-data"))


async def persisted_sessions(database_path: Path) -> dict[UUID, RuntimeSession]:
    engine = create_async_engine(operational_database_url(database_path))
    session_factory = create_session_factory(engine)
    try:
        async with SqlAlchemyUnitOfWork(session_factory) as unit_of_work:
            sessions = list(await unit_of_work.session.scalars(select(RuntimeSession)))
            unit_of_work.session.expunge_all()
        return {session.id: session for session in sessions}
    finally:
        await engine.dispose()


def test_construction_is_side_effect_free(tmp_path: Path) -> None:
    config = runtime_config(tmp_path)
    factory = RecordingSecretStoreFactory()

    core = SofiaCore(
        config,
        application_version="0.1.0.dev0",
        secret_store_factory=factory,
    )

    assert core.state is CoreState.CREATED
    assert core.runtime_session_id is None
    assert core.health.components == ()
    assert core.health.status is HealthStatus.UNKNOWN
    assert not config.paths.data_dir.exists()
    assert factory.calls == 0
    with pytest.raises(RuntimeError, match="only available"):
        _ = core.secret_service


@pytest.mark.asyncio
async def test_successful_start_composes_foundation_resources(tmp_path: Path) -> None:
    config = runtime_config(tmp_path)
    factory = RecordingSecretStoreFactory()
    core = SofiaCore(
        config,
        application_version="0.1.0.dev0",
        secret_store_factory=factory,
    )
    try:
        await core.start()
        sessions = await persisted_sessions(config.paths.operational_database)

        assert core.state is CoreState.RUNNING
        assert config.paths.data_dir.is_dir()
        assert config.paths.operational_database.is_file()
        assert core.runtime_session_id is not None
        assert set(sessions) == {core.runtime_session_id}
        assert sessions[core.runtime_session_id].status is RuntimeSessionStatus.RUNNING
        assert factory.calls == 1
        assert core.secret_service is not None
    finally:
        if core.state is CoreState.RUNNING:
            await core.stop()


@pytest.mark.asyncio
async def test_running_health_snapshot_is_ordered_and_unknown(tmp_path: Path) -> None:
    core = SofiaCore(
        runtime_config(tmp_path),
        application_version="0.1.0.dev0",
        secret_store_factory=RecordingSecretStoreFactory(),
    )
    try:
        await core.start()

        assert tuple(
            (component.name, component.status, component.detail)
            for component in core.health.components
        ) == (
            ("operational-store", HealthStatus.HEALTHY, None),
            (
                "secret-store",
                HealthStatus.UNKNOWN,
                "Backend configured; no active probe performed",
            ),
        )
        assert core.health.status is HealthStatus.UNKNOWN
    finally:
        if core.state is CoreState.RUNNING:
            await core.stop()


@pytest.mark.asyncio
async def test_secret_service_uses_the_injected_store(tmp_path: Path) -> None:
    factory = RecordingSecretStoreFactory()
    core = SofiaCore(
        runtime_config(tmp_path),
        application_version="0.1.0.dev0",
        secret_store_factory=factory,
    )
    ref = SecretRef("test/core")
    value = SecretValue("test-value")
    try:
        await core.start()
        core.secret_service.set(ref, value)

        retrieved = core.secret_service.get(ref)
        assert retrieved is not None
        assert retrieved.reveal() == value.reveal()
        assert core.secret_service.delete(ref) is True
        assert core.secret_service.get(ref) is None
        assert factory.calls == 1
    finally:
        if core.state is CoreState.RUNNING:
            await core.stop()


@pytest.mark.asyncio
async def test_clean_stop_releases_core_owned_resources(tmp_path: Path) -> None:
    config = runtime_config(tmp_path)
    core = SofiaCore(
        config,
        application_version="0.1.0.dev0",
        secret_store_factory=RecordingSecretStoreFactory(),
    )

    await core.start()
    session_id = core.runtime_session_id
    await core.stop()
    sessions = await persisted_sessions(config.paths.operational_database)

    assert session_id is not None
    assert core.state is CoreState.STOPPED
    assert core.runtime_session_id is None
    assert sessions[session_id].status is RuntimeSessionStatus.STOPPED
    stopped_at = sessions[session_id].stopped_at
    assert stopped_at is not None
    assert stopped_at.tzinfo is UTC
    assert core.health.components == ()
    assert core.health.status is HealthStatus.UNKNOWN
    with pytest.raises(RuntimeError, match="only available"):
        _ = core.secret_service


@pytest.mark.asyncio
async def test_invalid_start_transitions_are_rejected(tmp_path: Path) -> None:
    core = SofiaCore(
        runtime_config(tmp_path),
        application_version="0.1.0.dev0",
        secret_store_factory=RecordingSecretStoreFactory(),
    )

    await core.start()
    try:
        with pytest.raises(RuntimeError, match="only start from the created"):
            await core.start()

        await core.stop()
        with pytest.raises(RuntimeError, match="only start from the created"):
            await core.start()
    finally:
        if core.state is CoreState.RUNNING:
            await core.stop()


@pytest.mark.asyncio
async def test_stop_before_start_has_no_side_effects(tmp_path: Path) -> None:
    config = runtime_config(tmp_path)
    core = SofiaCore(
        config,
        application_version="0.1.0.dev0",
        secret_store_factory=RecordingSecretStoreFactory(),
    )

    with pytest.raises(RuntimeError, match="only stop from the running"):
        await core.stop()

    assert core.state is CoreState.CREATED
    assert not config.paths.data_dir.exists()


@pytest.mark.asyncio
async def test_stop_twice_keeps_the_core_stopped(tmp_path: Path) -> None:
    core = SofiaCore(
        runtime_config(tmp_path),
        application_version="0.1.0.dev0",
        secret_store_factory=RecordingSecretStoreFactory(),
    )

    await core.start()
    await core.stop()

    with pytest.raises(RuntimeError, match="only stop from the running"):
        await core.stop()

    assert core.state is CoreState.STOPPED


@pytest.mark.parametrize("application_version", ["", "   "])
def test_blank_application_version_is_rejected(
    tmp_path: Path, application_version: str
) -> None:
    config = runtime_config(tmp_path)
    factory = RecordingSecretStoreFactory()

    with pytest.raises(ValueError, match="Application version must not be blank"):
        SofiaCore(
            config,
            application_version=application_version,
            secret_store_factory=factory,
        )

    assert not config.paths.data_dir.exists()
    assert factory.calls == 0


@pytest.mark.asyncio
async def test_secret_backend_construction_failure_preserves_original_error(
    tmp_path: Path,
) -> None:
    config = runtime_config(tmp_path)
    original_error = RuntimeError("secret backend failure")

    def failing_factory() -> FakeSecretStore:
        raise original_error

    core = SofiaCore(
        config,
        application_version="0.1.0.dev0",
        secret_store_factory=failing_factory,
    )

    with pytest.raises(RuntimeError) as error:
        await core.start()

    assert error.value is original_error
    assert core.state is CoreState.FAILED
    assert not config.paths.data_dir.exists()
    assert core.health.components == ()
    with pytest.raises(RuntimeError, match="only available"):
        _ = core.secret_service


@pytest.mark.asyncio
async def test_bootstrap_failure_clears_composed_services(tmp_path: Path) -> None:
    data_dir = tmp_path / "not-a-directory"
    data_dir.write_text("not a directory")
    config = RuntimeConfig(paths=AppPaths(data_dir=data_dir))
    core = SofiaCore(
        config,
        application_version="0.1.0.dev0",
        secret_store_factory=RecordingSecretStoreFactory(),
    )

    with pytest.raises(FileExistsError):
        await core.start()

    assert core.state is CoreState.FAILED
    assert core.health.components == ()
    with pytest.raises(RuntimeError, match="only available"):
        _ = core.secret_service
