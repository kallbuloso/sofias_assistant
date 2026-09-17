"""Gate I16 - Seamless Desktop Runtime.

Vertical acceptance for SA-B038 (Core Supervision & Secure Attach), against
Architecture Review Amendment 0004 and the Desktop/Core Interaction Contract
v1.

Three layers of evidence:

  A. Core-side attach publication/cleanup lifecycle, driven through the real
     `sofias_assistant.host.runner.run` composition (same pattern as Gate
     I14), with a deterministic `InMemoryClientAttachStore` injected.
  B. The authenticated `/api/v1/runtime/identity` and
     `/api/v1/runtime/shutdown` HTTP contract, against the same real host.
  C. `DesktopCoreSupervisor` driving real, separate `sofia-core` OS processes
     through the real Windows Credential Manager (`WindowsClientAttachStore`),
     proving instance-key derivation, attach verification, duplicate-start
     safety, stale-record handling and bounded reconnect end to end.

A full packaged Windows human smoke (`SofiaAssistant.exe` launching a sibling
`SofiaCore.exe`, surviving Desktop quit, reattaching, and an explicit Stop
Sofia) was additionally performed manually against the built executables;
see the Gate I16 closure report for that evidence, since driving a real Qt
GUI window is out of scope for this automated suite.
"""

from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import sys
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from sofias_assistant.client_app.api import CoreApiClient, CoreApiError
from sofias_assistant.client_app.executable_locator import (
    CoreExecutableLocator,
    CoreExecutableNotFoundError,
)
from sofias_assistant.client_app.launcher import SubprocessCoreLauncher
from sofias_assistant.client_app.supervisor import (
    DesktopCoreSupervisor,
    SupervisorState,
)
from sofias_assistant.client_attach.models import CONTRACT_VERSION, ClientAttachRecord
from sofias_assistant.client_attach.store import (
    ClientAttachStore,
    InMemoryClientAttachStore,
)
from sofias_assistant.core.core import CoreState
from sofias_assistant.host import runner
from sofias_assistant.runtime.instance_ownership import instance_key_for_data_dir
from sofias_assistant.secrets.models import SecretValue
from tests.integration.core.test_core import FakeSecretStore, fake_ownership_factory

pytestmark = pytest.mark.integration

_WINDOWS_ONLY = pytest.mark.skipif(
    os.name != "nt", reason="WindowsClientAttachStore requires Windows"
)


# ---------------------------------------------------------------------------
# Layer A/B shared fakes and helpers (mirrors Gate I14's `_start_host`)
# ---------------------------------------------------------------------------


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _base_environment(
    tmp_path: Path, *, model: str = "gate-i16-model"
) -> dict[str, str]:
    return {
        "SOFIA_DATA_DIR": str(tmp_path / "core-data"),
        "SOFIA_CORE_PORT": str(_free_loopback_port()),
        "LLM_MODEL": model,
    }


class _RunningHost:
    def __init__(
        self,
        task: asyncio.Task[int],
        shutdown_event: asyncio.Event,
        access: Any,
        core: Any,
    ) -> None:
        self.task = task
        self.shutdown_event = shutdown_event
        self.access = access
        self.core = core

    async def stop(self) -> int:
        self.shutdown_event.set()
        return await self.task


async def _start_host(
    environment: Mapping[str, str],
    *,
    attach_store_factory: Any,
) -> _RunningHost:
    shutdown_event = asyncio.Event()
    ready: asyncio.Future[tuple[Any, Any]] = asyncio.get_running_loop().create_future()

    def on_ready(access: Any, core: Any) -> None:
        if not ready.done():
            ready.set_result((access, core))

    task = asyncio.create_task(
        runner.run(
            environment=environment,
            platform_secret_store_factory=FakeSecretStore,
            instance_ownership_factory=fake_ownership_factory,
            attach_store_factory=attach_store_factory,
            shutdown_event=shutdown_event,
            on_ready=on_ready,
            install_signal_handlers=False,
        )
    )
    waitable: set[asyncio.Future[Any]] = {task, ready}
    done, _pending = await asyncio.wait(waitable, return_when=asyncio.FIRST_COMPLETED)
    if task in done and not ready.done():
        exit_code = task.result()
        raise AssertionError(f"host failed to reach READY (exit code {exit_code})")
    access, core = await ready
    return _RunningHost(task, shutdown_event, access, core)


def _instance_key(environment: Mapping[str, str]) -> str:
    return instance_key_for_data_dir(Path(environment["SOFIA_DATA_DIR"]))


# ---------------------------------------------------------------------------
# A. Core-side attach publication/cleanup lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_attach_record_is_published_before_ready_and_matches_access(
    tmp_path: Path,
) -> None:
    store = InMemoryClientAttachStore()
    environment = _base_environment(tmp_path, model="attach-publish")
    host = await _start_host(environment, attach_store_factory=lambda: store)
    try:
        key = _instance_key(environment)
        record = store.read(key)
        assert record is not None
        assert record.instance_key == key
        assert record.host == host.access.host
        assert record.port == host.access.port
        assert record.credential.reveal() == host.access.credential.reveal()
        assert record.runtime_session_id == host.core.runtime_session_id
        assert record.contract_version == CONTRACT_VERSION
    finally:
        exit_code = await host.stop()
        assert exit_code == 0


@pytest.mark.asyncio
async def test_attach_record_is_removed_on_graceful_stop(tmp_path: Path) -> None:
    store = InMemoryClientAttachStore()
    environment = _base_environment(tmp_path, model="attach-cleanup")
    host = await _start_host(environment, attach_store_factory=lambda: store)
    key = _instance_key(environment)
    assert store.read(key) is not None

    exit_code = await host.stop()

    assert exit_code == 0
    assert store.read(key) is None


@pytest.mark.asyncio
async def test_attach_credential_never_appears_in_repr_or_exception_text(
    tmp_path: Path,
) -> None:
    store = InMemoryClientAttachStore()
    environment = _base_environment(tmp_path, model="attach-redaction")
    host = await _start_host(environment, attach_store_factory=lambda: store)
    try:
        key = _instance_key(environment)
        record = store.read(key)
        assert record is not None
        secret = record.credential.reveal()
        assert secret not in repr(record)
        assert secret not in str(record)
    finally:
        exit_code = await host.stop()
        assert exit_code == 0


class _RaisingAttachStore:
    """Attach store fake proving `publish()` failure fails Core closed."""

    def publish(self, instance_key: str, record: ClientAttachRecord) -> None:
        raise RuntimeError("protected store unavailable")

    def read(self, instance_key: str) -> ClientAttachRecord | None:
        return None

    def delete_if_current(self, instance_key: str, runtime_session_id: UUID) -> bool:
        return False


@pytest.mark.asyncio
async def test_attach_store_publish_failure_prevents_ready_and_cleans_up(
    tmp_path: Path,
) -> None:
    environment = _base_environment(tmp_path, model="attach-fail-closed")

    exit_code = await runner.run(
        environment=environment,
        platform_secret_store_factory=FakeSecretStore,
        instance_ownership_factory=fake_ownership_factory,
        attach_store_factory=_RaisingAttachStore,
        install_signal_handlers=False,
    )

    assert exit_code == 1


# ---------------------------------------------------------------------------
# B. Authenticated runtime identity / shutdown HTTP contract
# ---------------------------------------------------------------------------


def _sync_identity(base_url: str, credential: str) -> dict[str, Any]:
    client = CoreApiClient(base_url, credential)
    try:
        client.connect()
        return client.get_runtime_identity()
    finally:
        client.close()


def _sync_shutdown(base_url: str, credential: str, runtime_session_id: UUID) -> bool:
    client = CoreApiClient(base_url, credential)
    try:
        client.connect()
        return client.request_runtime_shutdown(
            runtime_session_id, reason="user_requested"
        )
    finally:
        client.close()


@pytest.mark.asyncio
async def test_runtime_identity_endpoint_returns_safe_matching_facts(
    tmp_path: Path,
) -> None:
    environment = _base_environment(tmp_path, model="identity-contract")
    host = await _start_host(
        environment, attach_store_factory=InMemoryClientAttachStore
    )
    try:
        base_url = f"http://{host.access.host}:{host.access.port}"
        identity = await asyncio.to_thread(
            _sync_identity, base_url, host.access.credential.reveal()
        )
        assert identity["instance_key"] == _instance_key(environment)
        assert identity["runtime_session_id"] == str(host.core.runtime_session_id)
        assert identity["protocol_version"] == 1
        assert identity["state"] == "running"
        assert "credential" not in identity
    finally:
        exit_code = await host.stop()
        assert exit_code == 0


@pytest.mark.asyncio
async def test_runtime_shutdown_with_correct_lifecycle_is_accepted(
    tmp_path: Path,
) -> None:
    environment = _base_environment(tmp_path, model="shutdown-accepted")
    host = await _start_host(
        environment, attach_store_factory=InMemoryClientAttachStore
    )
    base_url = f"http://{host.access.host}:{host.access.port}"
    runtime_session_id = host.core.runtime_session_id
    assert runtime_session_id is not None

    accepted = await asyncio.to_thread(
        _sync_shutdown,
        base_url,
        host.access.credential.reveal(),
        runtime_session_id,
    )

    assert accepted is True
    exit_code = await asyncio.wait_for(host.task, timeout=5)
    assert exit_code == 0
    assert host.core.state is CoreState.STOPPED


@pytest.mark.asyncio
async def test_runtime_shutdown_with_wrong_lifecycle_is_rejected(
    tmp_path: Path,
) -> None:
    environment = _base_environment(tmp_path, model="shutdown-rejected")
    host = await _start_host(
        environment, attach_store_factory=InMemoryClientAttachStore
    )
    try:
        base_url = f"http://{host.access.host}:{host.access.port}"

        accepted = await asyncio.to_thread(
            _sync_shutdown, base_url, host.access.credential.reveal(), uuid4()
        )

        assert accepted is False
        assert host.core.state is CoreState.RUNNING
    finally:
        exit_code = await host.stop()
        assert exit_code == 0


# ---------------------------------------------------------------------------
# C. DesktopCoreSupervisor against real, separate `sofia-core` OS processes
# ---------------------------------------------------------------------------


def _spawn_core_subprocess(
    data_dir: Path, *, port: int, model: str
) -> subprocess.Popen[bytes]:
    env = {
        **os.environ,
        "SOFIA_DATA_DIR": str(data_dir),
        "SOFIA_CORE_PORT": str(port),
        "LLM_MODEL": model,
    }
    creationflags = 0
    if sys.platform == "win32":
        creationflags = (
            subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        )
    return subprocess.Popen(  # noqa: S603
        [sys.executable, "-m", "sofias_assistant.host"],
        env=env,
        creationflags=creationflags,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _wait_for_record(
    store: ClientAttachStore, instance_key: str, timeout: float
) -> ClientAttachRecord:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        record = store.read(instance_key)
        if record is not None:
            return record
        time.sleep(0.2)
    raise AssertionError("attach record was not published in time")


def _terminate(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def _cleanup_record(store: ClientAttachStore, instance_key: str) -> None:
    """Best-effort test teardown: remove whatever record currently exists."""

    record = store.read(instance_key)
    if record is not None:
        store.delete_if_current(instance_key, record.runtime_session_id)


@pytest.fixture
def windows_attach_store() -> ClientAttachStore:
    from sofias_assistant.client_attach.windows_store import WindowsClientAttachStore

    return WindowsClientAttachStore()


@_WINDOWS_ONLY
def test_supervisor_attaches_to_an_already_running_real_core(
    tmp_path: Path, windows_attach_store: ClientAttachStore
) -> None:
    data_dir = tmp_path / "core-data"
    instance_key = instance_key_for_data_dir(data_dir)
    process = _spawn_core_subprocess(
        data_dir, port=_free_loopback_port(), model="already-running"
    )
    try:
        _wait_for_record(windows_attach_store, instance_key, timeout=20)

        class _NeverLaunch:
            def locate(self) -> tuple[Path, list[str]]:
                raise AssertionError("must not launch when Core is already running")

        supervisor = DesktopCoreSupervisor(
            instance_key=instance_key,
            attach_store=windows_attach_store,
            executable_locator=_NeverLaunch(),
            process_launcher=SubprocessCoreLauncher(),
        )

        state = supervisor.attach()

        assert state is SupervisorState.CORE_READY
    finally:
        _cleanup_record(windows_attach_store, instance_key)
        _terminate(process)


@_WINDOWS_ONLY
def test_supervisor_launches_absent_core_then_attaches(
    tmp_path: Path, windows_attach_store: ClientAttachStore
) -> None:
    data_dir = tmp_path / "core-data"
    instance_key = instance_key_for_data_dir(data_dir)
    port = _free_loopback_port()
    os.environ["SOFIA_DATA_DIR"] = str(data_dir)
    os.environ["SOFIA_CORE_PORT"] = str(port)
    os.environ["LLM_MODEL"] = "absent-then-launched"
    try:
        supervisor = DesktopCoreSupervisor(
            instance_key=instance_key,
            attach_store=windows_attach_store,
            executable_locator=CoreExecutableLocator(),
            process_launcher=SubprocessCoreLauncher(),
            launch_wait_seconds=25.0,
            launch_poll_interval_seconds=0.5,
        )

        state = supervisor.attach()

        assert state is SupervisorState.CORE_READY
    finally:
        record = windows_attach_store.read(instance_key)
        if record is not None:
            client = CoreApiClient(
                f"http://{record.host}:{record.port}", record.credential.reveal()
            )
            try:
                client.connect()
                client.request_runtime_shutdown(record.runtime_session_id)
            except CoreApiError:
                pass
            finally:
                client.close()
        for key in ("SOFIA_DATA_DIR", "SOFIA_CORE_PORT", "LLM_MODEL"):
            os.environ.pop(key, None)


@_WINDOWS_ONLY
def test_duplicate_core_start_is_avoided_by_single_instance_authority(
    tmp_path: Path, windows_attach_store: ClientAttachStore
) -> None:
    data_dir = tmp_path / "core-data"
    instance_key = instance_key_for_data_dir(data_dir)
    first = _spawn_core_subprocess(data_dir, port=_free_loopback_port(), model="race-a")
    try:
        first_record = _wait_for_record(windows_attach_store, instance_key, timeout=20)

        second = _spawn_core_subprocess(
            data_dir, port=_free_loopback_port(), model="race-b"
        )
        try:
            exit_code = second.wait(timeout=15)
            assert exit_code == 1
        finally:
            _terminate(second)

        # The winning Core's record is untouched by the loser.
        current_record = windows_attach_store.read(instance_key)
        assert current_record is not None
        assert current_record.runtime_session_id == first_record.runtime_session_id
    finally:
        _cleanup_record(windows_attach_store, instance_key)
        _terminate(first)


class _AlwaysFailLocator:
    """Locator stub proving no relaunch happens in a given assertion window."""

    def locate(self) -> tuple[Path, list[str]]:
        raise CoreExecutableNotFoundError("no relaunch for this test")


@_WINDOWS_ONLY
def test_stale_record_after_hard_kill_is_rejected_and_cleaned_up(
    tmp_path: Path, windows_attach_store: ClientAttachStore
) -> None:
    data_dir = tmp_path / "core-data"
    instance_key = instance_key_for_data_dir(data_dir)
    process = _spawn_core_subprocess(
        data_dir, port=_free_loopback_port(), model="hard-kill"
    )
    _wait_for_record(windows_attach_store, instance_key, timeout=20)
    process.kill()
    process.wait(timeout=10)

    supervisor = DesktopCoreSupervisor(
        instance_key=instance_key,
        attach_store=windows_attach_store,
        executable_locator=_AlwaysFailLocator(),
        process_launcher=SubprocessCoreLauncher(),
    )

    state = supervisor.attach()

    assert state is SupervisorState.CORE_FAILED
    # The exact stale observed record was removed via compare/delete.
    assert windows_attach_store.read(instance_key) is None


@_WINDOWS_ONLY
def test_wrong_instance_key_against_a_real_core_is_rejected(
    tmp_path: Path, windows_attach_store: ClientAttachStore
) -> None:
    data_dir = tmp_path / "core-data"
    instance_key = instance_key_for_data_dir(data_dir)
    process = _spawn_core_subprocess(
        data_dir, port=_free_loopback_port(), model="wrong-key"
    )
    try:
        record = _wait_for_record(windows_attach_store, instance_key, timeout=20)
        # Fabricate a record for an unrelated instance_key pointing at the
        # same real, reachable Core -- port-open must not be sufficient.
        unrelated_key = instance_key_for_data_dir(tmp_path / "unrelated-data")
        windows_attach_store.publish(
            unrelated_key,
            ClientAttachRecord(
                contract_version=CONTRACT_VERSION,
                instance_key=unrelated_key,
                runtime_session_id=record.runtime_session_id,
                host=record.host,
                port=record.port,
                credential=record.credential,
                application_version=record.application_version,
                created_at=record.created_at,
            ),
        )

        class _NeverLaunch:
            def locate(self) -> tuple[Path, list[str]]:
                raise AssertionError("must not relaunch in this assertion window")

        supervisor = DesktopCoreSupervisor(
            instance_key=unrelated_key,
            attach_store=windows_attach_store,
            executable_locator=_NeverLaunch(),
            process_launcher=SubprocessCoreLauncher(),
            launch_wait_seconds=0.0,
            launch_poll_interval_seconds=0.1,
        )

        with pytest.raises(AssertionError):
            supervisor.attach()

        # The mismatched fabricated record was removed via compare/delete.
        assert windows_attach_store.read(unrelated_key) is None
    finally:
        _cleanup_record(windows_attach_store, instance_key)
        _terminate(process)


@_WINDOWS_ONLY
def test_credential_rotates_across_core_restarts(
    tmp_path: Path, windows_attach_store: ClientAttachStore
) -> None:
    data_dir = tmp_path / "core-data"
    instance_key = instance_key_for_data_dir(data_dir)
    port = _free_loopback_port()
    first = _spawn_core_subprocess(data_dir, port=port, model="rotate-a")
    try:
        first_record = _wait_for_record(windows_attach_store, instance_key, timeout=20)
        client = CoreApiClient(
            f"http://{first_record.host}:{first_record.port}",
            first_record.credential.reveal(),
        )
        client.connect()
        client.request_runtime_shutdown(first_record.runtime_session_id)
        client.close()
        first.wait(timeout=10)
        deadline = time.monotonic() + 10
        while windows_attach_store.read(instance_key) is not None:
            if time.monotonic() > deadline:
                raise AssertionError("first Core's record was not cleaned up")
            time.sleep(0.2)

        second = _spawn_core_subprocess(
            data_dir, port=_free_loopback_port(), model="rotate-b"
        )
        try:
            second_record = _wait_for_record(
                windows_attach_store, instance_key, timeout=20
            )

            assert second_record.runtime_session_id != first_record.runtime_session_id
            assert second_record.credential.reveal() != first_record.credential.reveal()
        finally:
            _terminate(second)
    finally:
        _cleanup_record(windows_attach_store, instance_key)
        _terminate(first)


@_WINDOWS_ONLY
def test_old_lifecycle_cannot_delete_a_newer_records_windows_store(
    windows_attach_store: ClientAttachStore,
) -> None:
    """Concurrency invariant (Contract v1 SS58) proven directly at the store."""

    instance_key = "gate-i16-lifecycle-rotation-" + uuid4().hex
    old_record = ClientAttachRecord(
        contract_version=CONTRACT_VERSION,
        instance_key=instance_key,
        runtime_session_id=uuid4(),
        host="127.0.0.1",
        port=8989,
        credential=SecretValue("old-token"),
        application_version="0.1.0",
    )
    new_record = ClientAttachRecord(
        contract_version=CONTRACT_VERSION,
        instance_key=instance_key,
        runtime_session_id=uuid4(),
        host="127.0.0.1",
        port=8990,
        credential=SecretValue("new-token"),
        application_version="0.1.0",
    )
    try:
        windows_attach_store.publish(instance_key, old_record)
        windows_attach_store.publish(instance_key, new_record)

        deleted = windows_attach_store.delete_if_current(
            instance_key, old_record.runtime_session_id
        )

        assert deleted is False
        current = windows_attach_store.read(instance_key)
        assert current is not None
        assert current.runtime_session_id == new_record.runtime_session_id
    finally:
        _cleanup_record(windows_attach_store, instance_key)


@_WINDOWS_ONLY
def test_stop_sofia_gracefully_stops_a_real_core(
    tmp_path: Path, windows_attach_store: ClientAttachStore
) -> None:
    data_dir = tmp_path / "core-data"
    instance_key = instance_key_for_data_dir(data_dir)
    process = _spawn_core_subprocess(
        data_dir, port=_free_loopback_port(), model="stop-sofia"
    )
    try:
        _wait_for_record(windows_attach_store, instance_key, timeout=20)
        supervisor = DesktopCoreSupervisor(
            instance_key=instance_key,
            attach_store=windows_attach_store,
            executable_locator=CoreExecutableLocator(),
            process_launcher=SubprocessCoreLauncher(),
        )
        assert supervisor.attach() is SupervisorState.CORE_READY

        accepted = supervisor.request_stop_sofia(reason="user_requested")

        assert accepted is True
        assert supervisor.state is SupervisorState.CORE_STOPPED
        exit_code = process.wait(timeout=15)
        assert exit_code == 0
        assert windows_attach_store.read(instance_key) is None
    finally:
        _terminate(process)


@_WINDOWS_ONLY
def test_bounded_reconnect_after_a_real_crash_does_not_loop_forever(
    tmp_path: Path, windows_attach_store: ClientAttachStore
) -> None:
    data_dir = tmp_path / "core-data"
    instance_key = instance_key_for_data_dir(data_dir)
    process = _spawn_core_subprocess(
        data_dir, port=_free_loopback_port(), model="crash"
    )
    _wait_for_record(windows_attach_store, instance_key, timeout=20)
    supervisor = DesktopCoreSupervisor(
        instance_key=instance_key,
        attach_store=windows_attach_store,
        executable_locator=CoreExecutableLocator(),
        process_launcher=SubprocessCoreLauncher(),
        reconnect_attempts=2,
        reconnect_interval_seconds=0.5,
        launch_wait_seconds=0.0,
        launch_poll_interval_seconds=0.1,
    )
    try:
        assert supervisor.attach() is SupervisorState.CORE_READY
        process.kill()
        process.wait(timeout=10)
        supervisor.executable_locator = _AlwaysFailLocator()

        started = time.monotonic()
        state = supervisor.reconnect()
        elapsed = time.monotonic() - started

        assert state is SupervisorState.CORE_FAILED
        # Bounded: `reconnect_attempts` * interval, not an unbounded/hanging loop.
        assert elapsed < 30
        assert windows_attach_store.read(instance_key) is None
    finally:
        _cleanup_record(windows_attach_store, instance_key)
        _terminate(process)
