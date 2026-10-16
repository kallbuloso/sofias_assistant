"""Canonical Python application composition root.

SofiaApplication owns the runtime lifecycle for normal Desktop use. The legacy
loopback boundary remains only as a temporary compatibility adapter while the
Desktop surfaces are migrated to direct application services in SAS-03B+.
"""

from __future__ import annotations

import asyncio
import os
import queue
import threading
import traceback
from collections.abc import Iterator, Mapping
from importlib.metadata import version
from typing import Any
from uuid import UUID

from sofias_assistant.ai.contracts import DataLocality
from sofias_assistant.application.conversation import ConversationService
from sofias_assistant.client_boundary.boundary import (
    LocalClientAccess,
    LocalClientBoundary,
)
from sofias_assistant.config.loader import resolve_environment
from sofias_assistant.conversation.runtime import SendTextCommand
from sofias_assistant.core.core import SofiaCore
from sofias_assistant.health.models import ComponentHealth, HealthStatus
from sofias_assistant.host.composition import (
    build_conversation_dependencies_factory,
    build_runtime_config,
    build_secret_store_factory,
    create_app_factory,
)
from sofias_assistant.host.config import (
    ProductionRuntimeConfig,
    load_production_runtime_config,
)
from sofias_assistant.host.secret_bridge import (
    LLM_API_KEY_ENVIRONMENT_VARIABLE,
    provider_api_key_ref,
)
from sofias_assistant.runtime.instance_ownership import instance_key_for_data_dir
from sofias_assistant.runtime.shutdown import RuntimeShutdownSignal

_STREAM_END = object()


def _application_version() -> str:
    try:
        return version("sofias-assistant")
    except Exception:
        return "0.0.0"


class SofiaApplication:
    """Own Sofia's normal Desktop lifecycle inside one Python application."""

    def __init__(self, *, environment: Mapping[str, str] | None = None) -> None:
        self._environment = environment
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._stopped = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._shutdown_event: asyncio.Event | None = None
        self._error: BaseException | None = None

        self._config: ProductionRuntimeConfig | None = None
        self._core: SofiaCore | None = None
        self._boundary: LocalClientBoundary | None = None
        self._access: LocalClientAccess | None = None
        self._conversation: ConversationService | None = None

    @property
    def core(self) -> SofiaCore:
        core = self._core
        if core is None:
            raise RuntimeError("SofiaApplication is not running")
        return core

    @property
    def compatibility_access(self) -> LocalClientAccess:
        access = self._access
        if access is None:
            raise RuntimeError("Desktop compatibility adapter is not running")
        return access

    @property
    def runtime_session_id(self) -> UUID | None:
        return self.core.runtime_session_id

    @property
    def conversation(self) -> ConversationService:
        service = self._conversation
        if service is None:
            raise RuntimeError("Conversation service is not available")
        return service

    def start(self, *, timeout: float = 30.0) -> None:
        """Start the application runtime and wait until Desktop services are ready."""

        if self._thread is not None:
            raise RuntimeError("SofiaApplication can only be started once")

        self._thread = threading.Thread(
            target=self._thread_main,
            name="sofia-application-runtime",
            daemon=True,
        )
        self._thread.start()

        elapsed = 0.0
        interval = 0.05
        while elapsed < timeout:
            if self._ready.wait(interval):
                if self._error is not None:
                    raise RuntimeError("SofiaApplication failed to start") from self._error
                if self._core is not None and self._access is not None:
                    return
            if self._stopped.is_set():
                break
            elapsed += interval

        if self._error is not None:
            raise RuntimeError("SofiaApplication failed to start") from self._error
        raise RuntimeError("SofiaApplication did not become ready in time")

    def stop(self, *, timeout: float = 10.0) -> None:
        """Request graceful application shutdown and wait for owned resources."""

        loop = self._loop
        shutdown_event = self._shutdown_event
        thread = self._thread
        if loop is None or shutdown_event is None or thread is None:
            return
        if not self._stopped.is_set():
            loop.call_soon_threadsafe(shutdown_event.set)
            thread.join(timeout)
        self._thread = None

    def call(self, coroutine: Any, *, timeout: float = 60.0) -> Any:
        """Run one application coroutine on the owned runtime loop."""

        loop = self._loop
        if loop is None or self._stopped.is_set():
            raise RuntimeError("SofiaApplication runtime is not available")
        future = asyncio.run_coroutine_threadsafe(coroutine, loop)
        return future.result(timeout=timeout)

    def create_conversation(self) -> UUID:
        """Create one Conversation through the application service."""
        return self.call(self.conversation.create_conversation_id())

    def stream_text(
        self,
        conversation_id: UUID,
        text: str,
        *,
        locality: str,
        cloud_context_eligible: bool,
    ) -> Iterator[dict[str, Any]]:
        """Expose the current direct Conversation path to the Desktop worker."""

        events: queue.Queue[object] = queue.Queue()
        loop = self._loop
        if loop is None or self._stopped.is_set():
            raise RuntimeError("SofiaApplication runtime is not available")

        try:
            parsed_locality = DataLocality(locality)
        except ValueError as error:
            raise ValueError(f"Unknown locality: {locality}") from error

        command = SendTextCommand(
            conversation_id=conversation_id,
            text=text,
            locality=parsed_locality,
            cloud_context_eligible=cloud_context_eligible,
        )

        async def produce() -> None:
            try:
                async for event in self.conversation.stream_text(command):
                    events.put(event)
            except BaseException as error:
                traceback.print_exc()
                events.put(error)
            finally:
                events.put(_STREAM_END)

        asyncio.run_coroutine_threadsafe(produce(), loop)

        while True:
            item = events.get()
            if item is _STREAM_END:
                break
            if isinstance(item, BaseException):
                raise item
            assert isinstance(item, dict)
            yield item

    def _thread_main(self) -> None:
        try:
            asyncio.run(self._run())
        except BaseException as error:
            self._error = error
        finally:
            self._stopped.set()
            self._ready.set()

    async def _run(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._shutdown_event = asyncio.Event()

        real_environment = os.environ if self._environment is None else self._environment
        config = load_production_runtime_config(environment=real_environment)
        resolved_environment = resolve_environment(environment=real_environment)

        application_version = _application_version()
        instance_key = instance_key_for_data_dir(config.data_dir)
        secret_store_factory = build_secret_store_factory(
            environment=resolved_environment,
            llm_provider_id=config.llm.provider_id,
        )

        core = SofiaCore(
            build_runtime_config(config),
            application_version=application_version,
            secret_store_factory=secret_store_factory,
            conversation_dependencies_factory=build_conversation_dependencies_factory(
                config.llm
            ),
        )
        self._config = config
        self._core = core

        await core.start()
        self._conversation = ConversationService(core.conversation_runtime)
        boundary: LocalClientBoundary | None = None
        try:
            await self._report_ai_readiness(core, config)
            shutdown_signal = RuntimeShutdownSignal(
                event=self._shutdown_event,
                runtime_session_id_provider=lambda: core.runtime_session_id,
            )
            boundary = LocalClientBoundary(
                port=config.core_host.port,
                app_factory=create_app_factory(
                    core,
                    instance_key=instance_key,
                    application_version=application_version,
                    shutdown_signal=shutdown_signal,
                ),
            )
            access = await boundary.start()
            self._boundary = boundary
            self._access = access
            self._ready.set()

            await self._shutdown_event.wait()
        finally:
            if boundary is not None and self._access is not None:
                try:
                    await boundary.stop()
                finally:
                    self._access = None
                    self._boundary = None
            try:
                await core.stop()
            finally:
                self._conversation = None

    async def _report_ai_readiness(
        self, core: SofiaCore, config: ProductionRuntimeConfig
    ) -> None:
        await core.update_health(
            ComponentHealth(
                "llm-provider",
                HealthStatus.HEALTHY,
                f"canonical provider={config.llm.provider_id} model={config.llm.model_id}",
            )
        )
        secret_configured = (
            core.secret_service.get(provider_api_key_ref(config.llm.provider_id))
            is not None
        )
        await core.update_health(
            ComponentHealth(
                "llm-provider-credential",
                HealthStatus.HEALTHY if secret_configured else HealthStatus.DEGRADED,
                "configured"
                if secret_configured
                else f"{LLM_API_KEY_ENVIRONMENT_VARIABLE} missing",
            )
        )


def run_desktop() -> int:
    """Run the canonical Python Desktop application."""

    from sofias_assistant.application.client_adapter import ApplicationCoreApiClient
    from sofias_assistant.client_app.qt_app import create_application

    runtime = SofiaApplication()
    runtime.start()
    access = runtime.compatibility_access
    base_url = f"http://{access.host}:{access.port}"
    credential = access.credential.reveal()

    def api_factory(url: str, token: str) -> ApplicationCoreApiClient:
        return ApplicationCoreApiClient(runtime, url, token)

    try:
        qt_app, _window = create_application(
            base_url,
            credential,
            runtime_session_id=runtime.runtime_session_id,
            api_factory=api_factory,
        )
        try:
            return qt_app.exec()
        except KeyboardInterrupt:
            return 0
    finally:
        runtime.stop()
