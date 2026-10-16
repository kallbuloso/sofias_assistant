"""Transitional Desktop adapter for the in-process SofiaApplication.

Only surfaces not yet migrated to application services use the compatibility
HTTP boundary. Conversation creation and text streaming are direct.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, Protocol
from uuid import UUID

from sofias_assistant.client_app.api import CoreApiClient

class ApplicationRuntime(Protocol):
    core: Any

    def call(self, coroutine: Any, *, timeout: float = 60.0) -> Any: ...

    def stream_text(
        self,
        conversation_id: UUID,
        text: str,
        *,
        locality: str,
        cloud_context_eligible: bool,
    ) -> Iterator[dict[str, Any]]: ...


class ApplicationCoreApiClient(CoreApiClient):
    """Bridge the existing Desktop service to SofiaApplication during migration."""

    def __init__(
        self,
        application: ApplicationRuntime,
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
        self._application = application

    def close(self) -> None:
        """Close Desktop transport state without a shutdown-time HTTP round trip.

        The canonical Desktop and runtime share one application lifecycle. The
        temporary compatibility boundary is torn down by SofiaApplication, so
        deleting the client session over HTTP during Qt shutdown is unnecessary
        and can keep the worker thread alive until the HTTP timeout expires.
        """

        self.session_id = None
        close = getattr(self._http, "close", None)
        if close is not None:
            close()

    def create_conversation(self) -> UUID:
        conversation = self._application.call(
            self._application.core.conversation_runtime.create_conversation()
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
        yield from self._application.stream_text(
            conversation_id,
            text,
            locality=locality,
            cloud_context_eligible=cloud_context_eligible,
        )
