"""Desktop adapter for the in-process SofiaApplication.

SAS-03C routes every ordinary Desktop capability through native application
services. The localhost client is retained only as a temporary, lazy voice
transport until SAS-03D replaces the realtime WebSocket path.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, Protocol
from uuid import UUID

from sofias_assistant.application.desktop_services import ApplicationValidationError
from sofias_assistant.client_app.api import (
    CoreApiClient,
    CoreValidationError,
    RealtimeVoiceConnection,
)


class ApplicationRuntime(Protocol):
    @property
    def desktop(self) -> Any: ...

    def call(self, coroutine: Any, *, timeout: float = 60.0) -> Any: ...

    def create_conversation(self) -> UUID: ...

    def stream_text(
        self,
        conversation_id: UUID,
        text: str,
        *,
        locality: str,
        cloud_context_eligible: bool,
    ) -> Iterator[dict[str, Any]]: ...

    def request_shutdown(self, runtime_session_id: UUID) -> bool: ...


class ApplicationCoreApiClient(CoreApiClient):
    """Compatibility-shaped Desktop client backed by native application services."""

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
        self._voice_client: CoreApiClient | None = None

    def _call(self, coroutine: Any, *, validated: bool = False) -> Any:
        try:
            return self._application.call(coroutine)
        except ApplicationValidationError as error:
            if validated:
                raise CoreValidationError(str(error)) from error
            raise

    def connect(self) -> dict[str, Any]:
        """Attach the Desktop directly to the in-process application."""

        self.session_id = self._application.desktop.session_id
        return self.sync()

    def sync(self) -> dict[str, Any]:
        return self._call(self._application.desktop.sync())

    def close(self) -> None:
        self.session_id = None
        if self._voice_client is not None:
            self._voice_client.close()
            self._voice_client = None
        close = getattr(self._http, "close", None)
        if close is not None:
            close()

    def create_conversation(self) -> UUID:
        return self._application.create_conversation()

    def list_conversations(
        self, *, limit: int = 50, cursor: str | None = None
    ) -> dict[str, Any]:
        return self._call(
            self._application.desktop.list_conversations(limit=limit, cursor=cursor),
            validated=True,
        )

    def list_conversation_turns(
        self,
        conversation_id: UUID,
        *,
        limit: int = 50,
        before_sequence: int | None = None,
    ) -> dict[str, Any]:
        return self._call(
            self._application.desktop.list_conversation_turns(
                conversation_id,
                limit=limit,
                before_sequence=before_sequence,
            ),
            validated=True,
        )

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

    def acknowledge(self, notification_id: UUID) -> bool:
        return bool(
            self._call(
                self._application.desktop.acknowledge(notification_id),
                validated=True,
            )
        )

    def get_confirmation(self, confirmation_id: UUID) -> dict[str, Any]:
        return self._call(
            self._application.desktop.get_confirmation(confirmation_id),
            validated=True,
        )

    def approve_confirmation(
        self, confirmation_id: UUID, *, lifetime: str = "ONE_SHOT"
    ) -> dict[str, Any]:
        return self._call(
            self._application.desktop.approve_confirmation(
                confirmation_id, lifetime=lifetime
            ),
            validated=True,
        )

    def deny_confirmation(self, confirmation_id: UUID) -> None:
        self._call(
            self._application.desktop.deny_confirmation(confirmation_id),
            validated=True,
        )

    def cancel_task(self, task_id: UUID) -> dict[str, Any]:
        return self._call(
            self._application.desktop.cancel_task(task_id),
            validated=True,
        )

    def request_runtime_shutdown(
        self, runtime_session_id: UUID, *, reason: str = "user_requested"
    ) -> bool:
        del reason
        return self._application.request_shutdown(runtime_session_id)

    def list_ai_providers(self) -> list[dict[str, Any]]:
        return self._call(self._application.desktop.list_ai_providers())

    def list_ai_models(self) -> list[dict[str, Any]]:
        return self._call(self._application.desktop.list_ai_models())

    def update_ai_provider(
        self, provider_id: str, patch: dict[str, Any]
    ) -> dict[str, Any]:
        return self._call(
            self._application.desktop.update_ai_provider(provider_id, patch),
            validated=True,
        )

    def refresh_ai_models(self, provider_id: str) -> list[dict[str, Any]]:
        return self._call(
            self._application.desktop.refresh_ai_models(provider_id),
            validated=True,
        )

    def list_ai_profiles(self) -> list[dict[str, Any]]:
        return self._call(self._application.desktop.list_ai_profiles())

    def get_ai_profile(self, key: str) -> dict[str, Any]:
        return self._call(
            self._application.desktop.get_ai_profile(key),
            validated=True,
        )

    def update_ai_profile(self, key: str, patch: dict[str, Any]) -> dict[str, Any]:
        return self._call(
            self._application.desktop.update_ai_profile(key, patch),
            validated=True,
        )

    def preview_ai_routing(self, request: dict[str, Any]) -> dict[str, Any]:
        return self._call(
            self._application.desktop.preview_ai_routing(request),
            validated=True,
        )

    def set_ai_provider_credential(
        self, provider_id: str, value: str
    ) -> dict[str, Any]:
        return self._call(
            self._application.desktop.set_ai_provider_credential(provider_id, value),
            validated=True,
        )

    def delete_ai_provider_credential(self, provider_id: str) -> dict[str, Any]:
        return self._call(
            self._application.desktop.delete_ai_provider_credential(provider_id),
            validated=True,
        )

    def get_memory_integration(self) -> dict[str, Any]:
        return self._call(self._application.desktop.get_memory_integration())

    def set_memory_credential(self, value: str) -> dict[str, Any]:
        return self._call(
            self._application.desktop.set_memory_credential(value),
            validated=True,
        )

    def delete_memory_credential(self) -> dict[str, Any]:
        return self._call(
            self._application.desktop.delete_memory_credential(),
            validated=True,
        )

    def realtime(self) -> RealtimeVoiceConnection:
        """Use the temporary localhost transport only for voice until SAS-03D."""

        if self._voice_client is None:
            voice_client = CoreApiClient(
                self.base_url,
                self._credential,
                timeout=self._timeout,
            )
            voice_client.connect()
            self._voice_client = voice_client
        return self._voice_client.realtime()
