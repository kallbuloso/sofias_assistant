"""DesktopCoreSupervisor (Amendment 0004 SS7; Interaction Contract v1 SS12/SS16).

Owns Core discovery/launch/attach/reconnect orchestration as one dedicated,
Qt-independent application boundary, so individual Qt widgets never
reimplement this logic. Widgets only consume `SupervisorState` and issue user
intents (`attach()`, `request_stop_sofia()`).

Synchronous by design: `CoreApiClient` is a blocking transport adapter meant
to run off the Qt UI thread (the existing `ClientWorker`/`QThread` pattern in
`client_app.qt_app`); the supervisor reuses that same threading model instead
of introducing a second (asyncio) concurrency model into the Desktop Client.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID

from sofias_assistant.client_app.api import CoreApiClient, CoreApiError
from sofias_assistant.client_app.executable_locator import (
    CoreExecutableNotFoundError,
    ExecutableLocator,
)
from sofias_assistant.client_app.launcher import ProcessLauncher
from sofias_assistant.client_attach.models import ClientAttachRecord
from sofias_assistant.client_attach.store import ClientAttachStore

_SUPPORTED_CONTRACT_VERSION = 1
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


class SupervisorClient(Protocol):
    """Structural contract the supervisor depends on (`CoreApiClient` satisfies it)."""

    def connect(self) -> dict[str, Any]: ...

    def get_runtime_identity(self) -> dict[str, Any]: ...

    def request_runtime_shutdown(
        self, runtime_session_id: UUID, *, reason: str
    ) -> bool: ...

    def close(self) -> None: ...


class SupervisorState(StrEnum):
    """Contract v1 SS16 application-state vocabulary; UI mapping preserves these."""

    CORE_NOT_FOUND = "CORE_NOT_FOUND"
    CORE_STARTING = "CORE_STARTING"
    CORE_READY = "CORE_READY"
    CORE_DEGRADED = "CORE_DEGRADED"
    CORE_RECONNECTING = "CORE_RECONNECTING"
    CORE_STOPPING = "CORE_STOPPING"
    CORE_STOPPED = "CORE_STOPPED"
    CORE_FAILED = "CORE_FAILED"


class DesktopCoreSupervisorError(RuntimeError):
    """Raised when an operation requires an attached Core and none is present."""


@dataclass(slots=True)
class DesktopCoreSupervisor:
    """Discover, launch, attach to and supervise one expected Core instance."""

    instance_key: str
    attach_store: ClientAttachStore
    executable_locator: ExecutableLocator
    process_launcher: ProcessLauncher
    client_factory: Callable[[str, str], SupervisorClient] = field(
        default=CoreApiClient
    )
    sleep: Callable[[float], None] = field(default=time.sleep)
    launch_wait_seconds: float = 15.0
    launch_poll_interval_seconds: float = 0.25
    reconnect_attempts: int = 3
    reconnect_interval_seconds: float = 1.0

    state: SupervisorState = field(default=SupervisorState.CORE_NOT_FOUND, init=False)
    _client: SupervisorClient | None = field(default=None, init=False, repr=False)
    _runtime_session_id: UUID | None = field(default=None, init=False)

    @property
    def client(self) -> SupervisorClient | None:
        """Return the currently attached authenticated client, if any."""

        return self._client

    def attach(self) -> SupervisorState:
        """Attach to an existing Core, or launch and attach one (Contract v1 SS12).

        Never issues a mutating request before verification completes. A
        stale record is removed only via exact compare/delete for the record
        this call actually observed (Contract v1 SS15).
        """

        record = self.attach_store.read(self.instance_key)
        if record is not None:
            if self._verify(record):
                return self.state
            self.attach_store.delete_if_current(
                self.instance_key, record.runtime_session_id
            )
        return self._launch_and_attach()

    def reconnect(self) -> SupervisorState:
        """Bounded reconnect after an unexpected connection loss (Contract v1 SS20).

        Never an unbounded loop: after `reconnect_attempts` bounded read-only
        attempts, it performs exactly one bounded relaunch attempt, then
        gives up to `CORE_FAILED` for human retry. A crashed Core never
        cleans up its own attach record, so "truly absent" is judged by
        verifiability, not by record presence: a stale unreachable record is
        removed via exact compare/delete before the single relaunch attempt,
        the same way `attach()` handles a stale record (Contract v1 SS15).
        """

        self.state = SupervisorState.CORE_RECONNECTING
        last_record: ClientAttachRecord | None = None
        for _ in range(self.reconnect_attempts):
            last_record = self.attach_store.read(self.instance_key)
            if last_record is not None and self._verify(last_record):
                return self.state
            self.sleep(self.reconnect_interval_seconds)

        if last_record is not None:
            self.attach_store.delete_if_current(
                self.instance_key, last_record.runtime_session_id
            )
        return self._launch_and_attach()

    def request_stop_sofia(self, *, reason: str = "user_requested") -> bool:
        """Request an explicit authenticated graceful Core shutdown.

        This is the only path that ever stops Core; ordinary window close and
        Quit Desktop must never call it (Contract v1 SS24).
        """

        client = self._client
        if client is None or self._runtime_session_id is None:
            raise DesktopCoreSupervisorError("not attached to a Core")
        self.state = SupervisorState.CORE_STOPPING
        try:
            accepted = client.request_runtime_shutdown(
                self._runtime_session_id, reason=reason
            )
        except CoreApiError:
            self.state = SupervisorState.CORE_DEGRADED
            return False
        self.state = (
            SupervisorState.CORE_STOPPED if accepted else SupervisorState.CORE_DEGRADED
        )
        return accepted

    def _launch_and_attach(self) -> SupervisorState:
        self.state = SupervisorState.CORE_STARTING
        try:
            executable, argv = self.executable_locator.locate()
        except CoreExecutableNotFoundError:
            self.state = SupervisorState.CORE_FAILED
            return self.state

        self.process_launcher.launch(executable, argv)

        ticks = max(
            1, int(self.launch_wait_seconds / self.launch_poll_interval_seconds)
        )
        for _ in range(ticks):
            self.sleep(self.launch_poll_interval_seconds)
            record = self.attach_store.read(self.instance_key)
            if record is not None and self._verify(record):
                return self.state
        self.state = SupervisorState.CORE_FAILED
        return self.state

    def _verify(self, record: ClientAttachRecord) -> bool:
        """Authenticate, open a session and verify identity (Contract v1 SS12/SS13)."""

        if record.contract_version != _SUPPORTED_CONTRACT_VERSION:
            return False
        if record.host not in _LOOPBACK_HOSTS:
            return False

        base_url = f"http://{record.host}:{record.port}"
        client = self.client_factory(base_url, record.credential.reveal())
        try:
            client.connect()
            identity = client.get_runtime_identity()
        except CoreApiError:
            client.close()
            return False

        if identity.get("instance_key") != self.instance_key or identity.get(
            "runtime_session_id"
        ) != str(record.runtime_session_id):
            client.close()
            return False

        previous = self._client
        self._client = client
        self._runtime_session_id = record.runtime_session_id
        self.state = SupervisorState.CORE_READY
        if previous is not None and previous is not client:
            previous.close()
        return True
