"""Canonical Python application composition root.

SofiaApplication owns the complete runtime lifecycle for normal Desktop use.
Desktop capabilities, including realtime voice, use native in-process
application services. No localhost HTTP/WebSocket boundary is composed for the
canonical Desktop runtime.
"""

from __future__ import annotations

import asyncio
import os
import queue
import signal
import threading
import traceback
from collections.abc import Iterator, Mapping
from importlib.metadata import version
from typing import Any
from uuid import UUID, uuid4

from sofias_assistant.ai.contracts import DataLocality
from sofias_assistant.application.conversation import ConversationService
from sofias_assistant.application.desktop_services import DesktopServices
from sofias_assistant.application.voice import VoiceService
from sofias_assistant.config.loader import resolve_environment
from sofias_assistant.conversation.runtime import SendTextCommand
from sofias_assistant.core.core import SofiaCore
from sofias_assistant.health.models import ComponentHealth, HealthStatus
from sofias_assistant.host.composition import (
    build_conversation_dependencies_factory,
    build_runtime_config,
    build_secret_store_factory,
)
from sofias_assistant.host.config import (
    ProductionRuntimeConfig,
    load_production_runtime_config,
)
from sofias_assistant.host.secret_bridge import (
    LLM_API_KEY_ENVIRONMENT_VARIABLE,
    provider_api_key_ref,
)

_STREAM_END = object()
_VOICE_STREAM_END = object()


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
        self._conversation: ConversationService | None = None
        self._desktop: DesktopServices | None = None
        self._voice: VoiceService | None = None

    @property
    def core(self) -> SofiaCore:
        core = self._core
        if core is None:
            raise RuntimeError("SofiaApplication is not running")
        return core

    @property
    def runtime_session_id(self) -> UUID | None:
        return self.core.runtime_session_id

    @property
    def conversation(self) -> ConversationService:
        service = self._conversation
        if service is None:
            raise RuntimeError("Conversation service is not available")
        return service

    @property
    def desktop(self) -> DesktopServices:
        service = self._desktop
        if service is None:
            raise RuntimeError("Desktop application services are not available")
        return service

    @property
    def voice(self) -> VoiceService:
        service = self._voice
        if service is None:
            raise RuntimeError("Voice application service is not available")
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
                if self._core is not None:
                    return
            if self._stopped.is_set():
                break
            elapsed += interval

        if self._error is not None:
            raise RuntimeError("SofiaApplication failed to start") from self._error
        raise RuntimeError("SofiaApplication did not become ready in time")

    def request_shutdown(self, runtime_session_id: UUID) -> bool:
        """Request this exact runtime lifecycle to stop without localhost transport."""

        if runtime_session_id != self.runtime_session_id:
            return False
        loop = self._loop
        shutdown_event = self._shutdown_event
        if loop is None or shutdown_event is None or self._stopped.is_set():
            return False
        loop.call_soon_threadsafe(shutdown_event.set)
        return True

    def stop(self, *, timeout: float = 10.0) -> None:
        """Request graceful application shutdown and wait for owned resources."""

        thread = self._thread
        if thread is None:
            return

        loop = self._loop
        shutdown_event = self._shutdown_event
        if (
            loop is not None
            and shutdown_event is not None
            and not self._stopped.is_set()
        ):
            loop.call_soon_threadsafe(shutdown_event.set)

        if thread.is_alive():
            thread.join(timeout)
        if thread.is_alive():
            raise RuntimeError("SofiaApplication did not stop within the timeout")

        self._thread = None
        self._loop = None
        self._shutdown_event = None

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

    def stream_voice_events(self, session_id: UUID) -> Iterator[dict[str, object]]:
        """Bridge native realtime events from the application loop to Qt."""

        events: queue.Queue[object] = queue.Queue()
        loop = self._loop
        if loop is None or self._stopped.is_set():
            raise RuntimeError("SofiaApplication runtime is not available")

        async def produce() -> None:
            try:
                async for event in self.voice.events(session_id):
                    events.put(event)
            except BaseException as error:
                traceback.print_exc()
                events.put(error)
            finally:
                events.put(_VOICE_STREAM_END)

        asyncio.run_coroutine_threadsafe(produce(), loop)

        while True:
            item = events.get()
            if item is _VOICE_STREAM_END:
                return
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
        self._desktop = DesktopServices(core, session_id=uuid4())
        self._voice = VoiceService(core.realtime_conversation_runtime)
        try:
            await self._report_ai_readiness(core, config)
            self._ready.set()
            await self._shutdown_event.wait()
        finally:
            try:
                await core.stop()
            finally:
                self._conversation = None
                self._desktop = None
                self._voice = None
                self._core = None

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

    def api_factory() -> ApplicationCoreApiClient:
        return ApplicationCoreApiClient(runtime)

    try:
        qt_app, window = create_application(api_factory=api_factory)

        previous_sigint = signal.getsignal(signal.SIGINT)

        def request_quit_from_sigint(_signum: int, _frame: Any) -> None:
            # Do not raise KeyboardInterrupt inside an arbitrary PySide slot.
            # Queue the same graceful shutdown used by X and tray Quit.
            from PySide6.QtCore import QTimer

            QTimer.singleShot(0, window._quit)

        signal.signal(signal.SIGINT, request_quit_from_sigint)
        try:
            return qt_app.exec()
        finally:
            signal.signal(signal.SIGINT, previous_sigint)
    finally:
        runtime.stop()
