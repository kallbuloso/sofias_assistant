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
    CoreApiError,
    CoreValidationError,
)


class ApplicationRuntime(Protocol):
    @property
    def desktop(self) -> Any: ...

    @property
    def voice(self) -> Any: ...

    def call(self, coroutine: Any, *, timeout: float = 60.0) -> Any: ...

    def stream_voice_events(
        self, session_id: UUID
    ) -> Iterator[dict[str, object]]: ...

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

    def realtime(self) -> "NativeRealtimeVoiceConnection":
        """Return a native in-process realtime voice connection."""

        return NativeRealtimeVoiceConnection(self._application)


class NativeRealtimeVoiceConnection:
    """Synchronous Qt-facing facade over SofiaApplication's native voice service."""

    def __init__(self, application: ApplicationRuntime) -> None:
        self._application = application
        self.session_id: UUID | None = None
        self.interaction_id: UUID | None = None
        self.committed = False

    def open(
        self,
        conversation_id: UUID,
        *,
        locality: str,
        cloud_context_eligible: bool,
    ) -> None:
        try:
            self.session_id = self._application.call(
                self._application.voice.open(
                    conversation_id,
                    locality=locality,
                    cloud_context_eligible=cloud_context_eligible,
                )
            )
        except Exception as error:
            raise CoreApiError("Realtime session could not be opened") from error

    def start(self) -> UUID:
        session_id = self._require_open()
        try:
            interaction_id = self._application.call(
                self._application.voice.start(session_id)
            )
        except Exception as error:
            raise CoreApiError("Realtime interaction could not be started") from error
        self.interaction_id = interaction_id
        self.committed = False
        return interaction_id

    def send_audio(self, audio: bytes) -> None:
        session_id = self._require_open()
        if self.interaction_id is None or self.committed:
            raise CoreApiError("Realtime input is not active")
        try:
            self._application.call(
                self._application.voice.send_audio(session_id, audio),
                timeout=15.0,
            )
        except Exception as error:
            raise CoreApiError("Realtime audio could not be sent") from error

    def commit(self) -> None:
        session_id = self._require_open()
        if self.interaction_id is None:
            raise CoreApiError("Realtime interaction is not active")
        try:
            self._application.call(self._application.voice.commit(session_id))
        except Exception as error:
            raise CoreApiError("Realtime input could not be committed") from error
        self.committed = True

    def interrupt(self) -> None:
        session_id = self._require_open()
        interaction_id = self.interaction_id
        if interaction_id is None or not self.committed:
            raise CoreApiError("Realtime response is not active")
        try:
            self._application.call(
                self._application.voice.interrupt(session_id, interaction_id)
            )
        except Exception as error:
            raise CoreApiError("Realtime response could not be interrupted") from error
        self.committed = False

    def stop(self) -> None:
        session_id = self.session_id
        if session_id is None:
            return
        interaction_id = self.interaction_id
        try:
            if interaction_id is not None and not self.committed:
                self._application.call(
                    self._application.voice.cancel(session_id, interaction_id)
                )
            self._application.call(self._application.voice.close(session_id))
        except Exception:
            pass
        finally:
            self.session_id = None
            self.interaction_id = None
            self.committed = False

    def pump_events(self) -> Iterator[dict[str, Any]]:
        session_id = self._require_open()
        for event in self._application.stream_voice_events(session_id):
            yield dict(event)

    def _require_open(self) -> UUID:
        if self.session_id is None:
            raise CoreApiError("Realtime session is not open")
        return self.session_id
