"""In-process runtime bridge for the source-first desktop path.

SAS-03A keeps the existing HTTP/WebSocket adapter alive temporarily for
dashboard/history/voice compatibility, but starts the Core inside the same OS
process and routes text Conversation calls directly to the Core runtime.
"""

from __future__ import annotations

import asyncio
import queue
import threading
from collections.abc import Iterator, Mapping
from typing import Any
from uuid import UUID

from sofias_assistant.ai.contracts import DataLocality
from sofias_assistant.client_app.api import CoreApiClient
from sofias_assistant.client_boundary.http_api import _conversation_event_to_record
from sofias_assistant.conversation.runtime import SendTextCommand
from sofias_assistant.core.core import SofiaCore
from sofias_assistant.host.runner import run

_STREAM_END = object()


class InProcessRuntimeHost:
    """Own one Sofia Core lifecycle on a dedicated asyncio thread."""

    def __init__(self, *, environment: Mapping[str, str] | None = None) -> None:
        self._environment = environment
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._stopped = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._shutdown_event: asyncio.Event | None = None
        self._error: BaseException | None = None
        self._access: Any | None = None
        self._core: SofiaCore | None = None

    @property
    def core(self) -> SofiaCore:
        core = self._core
        if core is None:
            raise RuntimeError("in-process Sofia Core is not ready")
        return core

    @property
    def access(self) -> Any:
        access = self._access
        if access is None:
            raise RuntimeError("in-process local client boundary is not ready")
        return access

    @property
    def runtime_session_id(self) -> UUID | None:
        return self.core.runtime_session_id

    def start(self, *, timeout: float = 30.0) -> None:
        if self._thread is not None:
            raise RuntimeError("in-process runtime host can only be started once")

        self._thread = threading.Thread(
            target=self._thread_main,
            name="sofia-in-process-runtime",
            daemon=True,
        )
        self._thread.start()

        # Poll both events so an early startup failure does not wait the whole timeout.
        elapsed = 0.0
        interval = 0.05
        while elapsed < timeout:
            if self._ready.wait(interval):
                return
            if self._stopped.is_set():
                break
            elapsed += interval
        if self._error is not None:
            raise RuntimeError("Sofia Core failed to start in-process") from self._error
        raise RuntimeError("Sofia Core did not become ready in time")

    def stop(self, *, timeout: float = 10.0) -> None:
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
        loop = self._loop
        if loop is None or self._stopped.is_set():
            raise RuntimeError("in-process Sofia runtime is not available")
        future = asyncio.run_coroutine_threadsafe(coroutine, loop)
        return future.result(timeout=timeout)

    def stream_text(
        self,
        conversation_id: UUID,
        text: str,
        *,
        locality: str,
        cloud_context_eligible: bool,
    ) -> Iterator[dict[str, Any]]:
        """Bridge the Core async stream to the synchronous Qt worker thread."""

        events: queue.Queue[object] = queue.Queue(maxsize=64)
        loop = self._loop
        if loop is None or self._stopped.is_set():
            raise RuntimeError("in-process Sofia runtime is not available")

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
                async for event in self.core.conversation_runtime.stream_text(command):
                    record = _conversation_event_to_record(event)
                    events.put(record.model_dump(mode="json"))
            except BaseException as error:
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

        def on_ready(access: Any, core: SofiaCore) -> None:
            self._access = access
            self._core = core
            self._ready.set()

        exit_code = await run(
            environment=self._environment,
            shutdown_event=self._shutdown_event,
            on_ready=on_ready,
            install_signal_handlers=False,
        )
        if exit_code != 0 and self._core is None:
            raise RuntimeError(f"in-process Core exited with code {exit_code}")


def run_source_desktop() -> int:
    """Run the source-first Desktop and Core inside one OS process."""

    from sofias_assistant.client_app.qt_app import create_application

    host = InProcessRuntimeHost()
    host.start()
    access = host.access
    base_url = f"http://{access.host}:{access.port}"
    credential = access.credential.reveal()

    def api_factory(url: str, token: str) -> CoreApiClient:
        return InProcessCoreApiClient(host, url, token)

    try:
        app, _window = create_application(
            base_url,
            credential,
            runtime_session_id=host.runtime_session_id,
            api_factory=api_factory,
        )
        return app.exec()
    finally:
        host.stop()


class InProcessCoreApiClient(CoreApiClient):
    """Transitional UI adapter: direct text path, HTTP for remaining surfaces."""

    def __init__(
        self,
        host: InProcessRuntimeHost,
        base_url: str,
        credential: str,
        *,
        timeout: float = 8.0,
        http_client: Any | None = None,
    ) -> None:
        super().__init__(
            base_url,
            credential,
            timeout=timeout,
            http_client=http_client,
        )
        self._host = host

    def create_conversation(self) -> UUID:
        conversation = self._host.call(
            self._host.core.conversation_runtime.create_conversation()
        )
        return conversation.id

    def stream_text(
        self,
        conversation_id: UUID,
        text: str,
        *,
        locality: str,
        cloud_context_eligible: bool,
    ) -> Iterator[dict[str, Any]]:
        yield from self._host.stream_text(
            conversation_id,
            text,
            locality=locality,
            cloud_context_eligible=cloud_context_eligible,
        )
