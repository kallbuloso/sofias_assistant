"""Lifecycle owner for Sofia's Assistant foundation resources."""

from collections.abc import Callable
from enum import StrEnum
from uuid import UUID

from sofias_assistant.config.models import RuntimeConfig
from sofias_assistant.health.models import (
    ComponentHealth,
    HealthStatus,
    RuntimeHealthSnapshot,
)
from sofias_assistant.runtime.bootstrap import RuntimeResources, bootstrap_runtime
from sofias_assistant.runtime.session_lifecycle import RuntimeSessionLifecycle
from sofias_assistant.secrets.service import SecretService
from sofias_assistant.secrets.store import SecretStore
from sofias_assistant.secrets.windows_store import WindowsCredentialStore


class CoreState(StrEnum):
    """Lifecycle state of the SofiaCore composition owner."""

    CREATED = "created"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


class SofiaCore:
    """Compose and own the foundation resources for one Core lifecycle."""

    def __init__(
        self,
        config: RuntimeConfig,
        *,
        application_version: str,
        secret_store_factory: Callable[[], SecretStore] = WindowsCredentialStore,
    ) -> None:
        if not application_version.strip():
            raise ValueError("Application version must not be blank")

        self._config = config
        self._application_version = application_version
        self._secret_store_factory = secret_store_factory
        self._state = CoreState.CREATED
        self._resources: RuntimeResources | None = None
        self._session_lifecycle: RuntimeSessionLifecycle | None = None
        self._secret_service: SecretService | None = None
        self._health = RuntimeHealthSnapshot(())

    @property
    def state(self) -> CoreState:
        """Return the current Core lifecycle state."""

        return self._state

    @property
    def runtime_session_id(self) -> UUID | None:
        """Return the current persisted runtime session identity, when active."""

        if self._session_lifecycle is None:
            return None
        return self._session_lifecycle.active_session_id

    @property
    def health(self) -> RuntimeHealthSnapshot:
        """Return the current transport-neutral foundation health snapshot."""

        return self._health

    @property
    def secret_service(self) -> SecretService:
        """Return the composed SecretService only while the Core is running."""

        if self._state is not CoreState.RUNNING or self._secret_service is None:
            raise RuntimeError(
                "SecretService is only available while SofiaCore is running"
            )
        return self._secret_service

    async def start(self) -> None:
        """Compose foundation resources and persist the current runtime session."""

        if self._state is not CoreState.CREATED:
            raise RuntimeError("SofiaCore can only start from the created state")

        self._state = CoreState.STARTING
        try:
            self._secret_service = SecretService(self._secret_store_factory())
            self._resources = await bootstrap_runtime(self._config)
            self._session_lifecycle = RuntimeSessionLifecycle(
                self._resources.session_factory,
                application_version=self._application_version,
            )
            await self._session_lifecycle.start()
            self._health = RuntimeHealthSnapshot(
                (
                    ComponentHealth("operational-store", HealthStatus.HEALTHY),
                    ComponentHealth(
                        "secret-store",
                        HealthStatus.UNKNOWN,
                        "Backend configured; no active probe performed",
                    ),
                )
            )
            self._state = CoreState.RUNNING
        except BaseException:
            self._state = CoreState.FAILED
            await self._cleanup_failed_start()
            raise

    async def stop(self) -> None:
        """Stop the current runtime session and release owned resources."""

        if self._state is not CoreState.RUNNING:
            raise RuntimeError("SofiaCore can only stop from the running state")

        resources = self._resources
        lifecycle = self._session_lifecycle
        if resources is None or lifecycle is None:
            self._state = CoreState.FAILED
            self._clear_owned_references()
            raise RuntimeError("SofiaCore running state is missing owned resources")

        self._state = CoreState.STOPPING
        try:
            await lifecycle.stop()
        except BaseException:
            try:
                await resources.close()
            except BaseException:
                pass
            self._clear_owned_references()
            self._state = CoreState.FAILED
            raise

        try:
            await resources.close()
        except BaseException:
            self._clear_owned_references()
            self._state = CoreState.FAILED
            raise

        self._clear_owned_references()
        self._state = CoreState.STOPPED

    async def _cleanup_failed_start(self) -> None:
        lifecycle = self._session_lifecycle
        resources = self._resources

        if lifecycle is not None and lifecycle.active_session_id is not None:
            try:
                await lifecycle.stop()
            except BaseException:
                pass
        if resources is not None:
            try:
                await resources.close()
            except BaseException:
                pass
        self._clear_owned_references()

    def _clear_owned_references(self) -> None:
        self._resources = None
        self._session_lifecycle = None
        self._secret_service = None
        self._health = RuntimeHealthSnapshot(())
