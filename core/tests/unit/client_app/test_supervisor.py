"""Unit tests for `DesktopCoreSupervisor` state transitions and attach algorithm."""

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from sofias_assistant.client_app.api import CoreApiError
from sofias_assistant.client_app.executable_locator import (
    CoreExecutableNotFoundError,
    ExecutableLocator,
)
from sofias_assistant.client_app.supervisor import (
    DesktopCoreSupervisor,
    DesktopCoreSupervisorError,
    SupervisorClient,
    SupervisorState,
)
from sofias_assistant.client_attach.models import CONTRACT_VERSION, ClientAttachRecord
from sofias_assistant.client_attach.store import InMemoryClientAttachStore
from sofias_assistant.secrets.models import SecretValue

_INSTANCE_KEY = "a" * 64


def _record(
    *,
    instance_key: str = _INSTANCE_KEY,
    runtime_session_id: UUID | None = None,
    contract_version: int = CONTRACT_VERSION,
    host: str = "127.0.0.1",
) -> ClientAttachRecord:
    return ClientAttachRecord(
        contract_version=contract_version,
        instance_key=instance_key,
        runtime_session_id=runtime_session_id or uuid4(),
        host=host,
        port=8989,
        credential=SecretValue("attach-token"),
        application_version="0.1.0",
        created_at=datetime.now(UTC),
    )


class FakeAttachedClient:
    """Stand-in for `CoreApiClient` exposing only what the supervisor calls."""

    def __init__(
        self,
        base_url: str,
        credential: str,
        *,
        identity: dict[str, object] | None = None,
        fail_connect: bool = False,
        shutdown_result: bool | Exception = True,
    ) -> None:
        self.base_url = base_url
        self.credential = credential
        self._identity = identity or {}
        self._fail_connect = fail_connect
        self.shutdown_result = shutdown_result
        self.closed = False
        self.shutdown_calls: list[tuple[UUID, str]] = []

    def connect(self) -> dict[str, object]:
        if self._fail_connect:
            raise CoreApiError("connection failed")
        return {}

    def get_runtime_identity(self) -> dict[str, object]:
        return self._identity

    def request_runtime_shutdown(
        self, runtime_session_id: UUID, *, reason: str
    ) -> bool:
        self.shutdown_calls.append((runtime_session_id, reason))
        if isinstance(self.shutdown_result, Exception):
            raise self.shutdown_result
        return self.shutdown_result

    def close(self) -> None:
        self.closed = True


def _default_client_factory(base_url: str, credential: str) -> SupervisorClient:
    return FakeAttachedClient(base_url, credential, fail_connect=True)


class FakeExecutableLocator:
    def __init__(self, target: tuple[Path, list[str]] | Exception) -> None:
        self._target = target

    def locate(self) -> tuple[Path, list[str]]:
        if isinstance(self._target, Exception):
            raise self._target
        return self._target


class FakeProcessLauncher:
    def __init__(self) -> None:
        self.calls: list[tuple[Path, list[str]]] = []

    def launch(self, executable: Path, argv: list[str]) -> int | None:
        self.calls.append((executable, argv))
        return 999


def _matching_identity(record: ClientAttachRecord) -> dict[str, object]:
    return {
        "instance_key": record.instance_key,
        "runtime_session_id": str(record.runtime_session_id),
        "application_version": record.application_version,
        "protocol_version": 1,
        "state": "running",
    }


def _supervisor(
    *,
    attach_store: InMemoryClientAttachStore | None = None,
    client_factory: Callable[[str, str], SupervisorClient] | None = None,
    locator: ExecutableLocator | None = None,
    launcher: FakeProcessLauncher | None = None,
) -> DesktopCoreSupervisor:
    return DesktopCoreSupervisor(
        instance_key=_INSTANCE_KEY,
        attach_store=attach_store or InMemoryClientAttachStore(),
        executable_locator=locator or FakeExecutableLocator((Path("core.exe"), [])),
        process_launcher=launcher or FakeProcessLauncher(),
        client_factory=client_factory or _default_client_factory,
        sleep=lambda _seconds: None,
        launch_wait_seconds=1.0,
        launch_poll_interval_seconds=0.1,
        reconnect_attempts=2,
        reconnect_interval_seconds=0.0,
    )


def test_initial_state_is_core_not_found() -> None:
    supervisor = _supervisor()

    assert supervisor.state is SupervisorState.CORE_NOT_FOUND


def test_attach_to_an_existing_valid_record_succeeds() -> None:
    store = InMemoryClientAttachStore()
    record = _record()
    store.publish(_INSTANCE_KEY, record)
    client_factory = lambda base_url, credential: FakeAttachedClient(  # noqa: E731
        base_url, credential, identity=_matching_identity(record)
    )
    supervisor = _supervisor(attach_store=store, client_factory=client_factory)

    state = supervisor.attach()

    assert state is SupervisorState.CORE_READY
    assert supervisor.client is not None


def test_absent_record_launches_core_then_attaches() -> None:
    store = InMemoryClientAttachStore()
    record = _record()
    launcher = FakeProcessLauncher()

    calls = {"n": 0}

    def client_factory(base_url: str, credential: str) -> FakeAttachedClient:
        calls["n"] += 1
        if calls["n"] < 2:
            return FakeAttachedClient(base_url, credential, fail_connect=True)
        return FakeAttachedClient(
            base_url, credential, identity=_matching_identity(record)
        )

    def launch(executable: Path, argv: list[str]) -> int | None:
        launcher.calls.append((executable, argv))
        store.publish(_INSTANCE_KEY, record)
        return 1234

    launcher.launch = launch  # type: ignore[method-assign]
    supervisor = _supervisor(
        attach_store=store, client_factory=client_factory, launcher=launcher
    )

    state = supervisor.attach()

    assert state is SupervisorState.CORE_READY
    assert len(launcher.calls) == 1


def test_unrelated_service_on_expected_port_is_rejected() -> None:
    store = InMemoryClientAttachStore()
    record = _record()
    store.publish(_INSTANCE_KEY, record)
    client_factory = lambda base_url, credential: FakeAttachedClient(  # noqa: E731
        base_url, credential, fail_connect=True
    )
    launcher = FakeProcessLauncher()
    supervisor = _supervisor(
        attach_store=store, client_factory=client_factory, launcher=launcher
    )

    state = supervisor.attach()

    assert state is SupervisorState.CORE_FAILED
    # The stale record is not deleted merely because the endpoint refused a
    # connection; deletion only removes the exact stale record and this
    # exercise still attempted a relaunch, which is allowed by the algorithm.
    assert len(launcher.calls) == 1


def test_wrong_instance_key_is_rejected() -> None:
    store = InMemoryClientAttachStore()
    record = _record()
    store.publish(_INSTANCE_KEY, record)
    identity = _matching_identity(record)
    identity["instance_key"] = "wrong" * 12 + "x" * 4
    client_factory = lambda base_url, credential: FakeAttachedClient(  # noqa: E731
        base_url, credential, identity=identity
    )
    supervisor = _supervisor(attach_store=store, client_factory=client_factory)

    state = supervisor.attach()

    assert state is SupervisorState.CORE_FAILED
    # The stale observed record was removed via compare/delete.
    assert store.read(_INSTANCE_KEY) is None


def test_wrong_runtime_session_id_is_rejected() -> None:
    store = InMemoryClientAttachStore()
    record = _record()
    store.publish(_INSTANCE_KEY, record)
    identity = _matching_identity(record)
    identity["runtime_session_id"] = str(uuid4())
    client_factory = lambda base_url, credential: FakeAttachedClient(  # noqa: E731
        base_url, credential, identity=identity
    )
    supervisor = _supervisor(attach_store=store, client_factory=client_factory)

    state = supervisor.attach()

    assert state is SupervisorState.CORE_FAILED
    assert store.read(_INSTANCE_KEY) is None


def test_executable_not_found_results_in_core_failed() -> None:
    store = InMemoryClientAttachStore()
    supervisor = _supervisor(
        attach_store=store,
        locator=FakeExecutableLocator(CoreExecutableNotFoundError("missing")),
    )

    state = supervisor.attach()

    assert state is SupervisorState.CORE_FAILED


def test_reconnect_succeeds_when_record_reappears() -> None:
    store = InMemoryClientAttachStore()
    record = _record()
    client_factory = lambda base_url, credential: FakeAttachedClient(  # noqa: E731
        base_url, credential, identity=_matching_identity(record)
    )
    supervisor = _supervisor(attach_store=store, client_factory=client_factory)
    supervisor.state = SupervisorState.CORE_READY
    store.publish(_INSTANCE_KEY, record)

    state = supervisor.reconnect()

    assert state is SupervisorState.CORE_READY


def test_reconnect_is_bounded_and_reaches_core_failed() -> None:
    sleeps: list[float] = []
    store = InMemoryClientAttachStore()
    record = _record()
    store.publish(_INSTANCE_KEY, record)
    client_factory = lambda base_url, credential: FakeAttachedClient(  # noqa: E731
        base_url, credential, fail_connect=True
    )
    launcher = FakeProcessLauncher()
    supervisor = DesktopCoreSupervisor(
        instance_key=_INSTANCE_KEY,
        attach_store=store,
        executable_locator=FakeExecutableLocator((Path("core.exe"), [])),
        process_launcher=launcher,
        client_factory=client_factory,
        sleep=sleeps.append,
        launch_wait_seconds=0.2,
        launch_poll_interval_seconds=0.1,
        reconnect_attempts=3,
        reconnect_interval_seconds=0.5,
    )

    state = supervisor.reconnect()

    # Bounded: exactly `reconnect_attempts` read-only sleeps, no infinite loop.
    assert sleeps.count(0.5) == 3
    assert state is SupervisorState.CORE_FAILED
    # A crashed Core never cleans up its own record; after bounded read-only
    # attempts fail, the stale record is removed and exactly one bounded
    # relaunch is attempted (Contract v1 SS20) -- which also fails here
    # because the fake launcher never publishes a replacement record.
    assert len(launcher.calls) == 1
    assert store.read(_INSTANCE_KEY) is None


def test_reconnect_relaunches_once_when_record_is_truly_absent() -> None:
    store = InMemoryClientAttachStore()
    client_factory = lambda base_url, credential: FakeAttachedClient(  # noqa: E731
        base_url, credential, fail_connect=True
    )
    launcher = FakeProcessLauncher()
    supervisor = DesktopCoreSupervisor(
        instance_key=_INSTANCE_KEY,
        attach_store=store,
        executable_locator=FakeExecutableLocator((Path("core.exe"), [])),
        process_launcher=launcher,
        client_factory=client_factory,
        sleep=lambda _seconds: None,
        launch_wait_seconds=0.2,
        launch_poll_interval_seconds=0.1,
        reconnect_attempts=2,
        reconnect_interval_seconds=0.0,
    )

    state = supervisor.reconnect()

    assert state is SupervisorState.CORE_FAILED
    assert len(launcher.calls) == 1


def test_no_infinite_reconnect_loop() -> None:
    call_count = {"n": 0}

    def counting_sleep(_seconds: float) -> None:
        call_count["n"] += 1
        if call_count["n"] > 1000:
            raise AssertionError("reconnect loop did not terminate")

    store = InMemoryClientAttachStore()
    client_factory = lambda base_url, credential: FakeAttachedClient(  # noqa: E731
        base_url, credential, fail_connect=True
    )
    supervisor = DesktopCoreSupervisor(
        instance_key=_INSTANCE_KEY,
        attach_store=store,
        executable_locator=FakeExecutableLocator(
            CoreExecutableNotFoundError("missing")
        ),
        process_launcher=FakeProcessLauncher(),
        client_factory=client_factory,
        sleep=counting_sleep,
        reconnect_attempts=3,
        reconnect_interval_seconds=0.01,
    )

    state = supervisor.reconnect()

    assert state is SupervisorState.CORE_FAILED
    assert call_count["n"] == 3


def test_request_stop_sofia_without_attachment_raises() -> None:
    supervisor = _supervisor()

    with pytest.raises(DesktopCoreSupervisorError):
        supervisor.request_stop_sofia()


def test_request_stop_sofia_accepted_transitions_to_core_stopped() -> None:
    store = InMemoryClientAttachStore()
    record = _record()
    store.publish(_INSTANCE_KEY, record)
    attached_client = FakeAttachedClient(
        "http://127.0.0.1:8989", "token", identity=_matching_identity(record)
    )
    supervisor = _supervisor(
        attach_store=store, client_factory=lambda *_: attached_client
    )
    supervisor.attach()

    accepted = supervisor.request_stop_sofia(reason="user_requested")

    assert accepted is True
    assert supervisor.state is SupervisorState.CORE_STOPPED
    assert attached_client.shutdown_calls == [
        (record.runtime_session_id, "user_requested")
    ]


def test_request_stop_sofia_lifecycle_mismatch_degrades_instead_of_crashing() -> None:
    store = InMemoryClientAttachStore()
    record = _record()
    store.publish(_INSTANCE_KEY, record)
    attached_client = FakeAttachedClient(
        "http://127.0.0.1:8989",
        "token",
        identity=_matching_identity(record),
        shutdown_result=False,
    )
    supervisor = _supervisor(
        attach_store=store, client_factory=lambda *_: attached_client
    )
    supervisor.attach()

    accepted = supervisor.request_stop_sofia()

    assert accepted is False
    assert supervisor.state is SupervisorState.CORE_DEGRADED
