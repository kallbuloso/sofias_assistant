"""Structural provider protocols for normalized AI contracts."""

from collections.abc import AsyncIterator
from typing import Protocol

from sofias_assistant.ai.contracts import (
    AIRequest,
    AudioInputFrame,
    ModelIdentity,
    ProviderStreamEvent,
    RealtimeInteractionId,
    RealtimeProviderEvent,
    RealtimeSessionRequest,
    StructuredOutputResult,
    StructuredOutputSpec,
    TextResponse,
)


class RealtimeProviderSession(Protocol):
    """Provider-bound realtime session using only normalized Core contracts."""

    async def start_interaction(
        self, *, realtime_interaction_id: RealtimeInteractionId
    ) -> None: ...

    async def send_audio(self, *, frame: AudioInputFrame) -> None: ...

    async def commit_interaction(
        self, *, realtime_interaction_id: RealtimeInteractionId
    ) -> None: ...

    async def interrupt(
        self, *, realtime_interaction_id: RealtimeInteractionId
    ) -> None: ...

    def events(self) -> AsyncIterator[RealtimeProviderEvent]: ...

    async def close(self) -> None: ...


class RealtimeProvider(Protocol):
    """Opens a provider-specific session from a Core-owned realtime request."""

    async def open_realtime_session(
        self, *, model: ModelIdentity, request: RealtimeSessionRequest
    ) -> RealtimeProviderSession: ...


class TextGenerationProvider(Protocol):
    """Generates one normalized non-streaming text response."""

    async def generate_text(
        self, *, model: ModelIdentity, request: AIRequest
    ) -> TextResponse: ...


class TextStreamingProvider(Protocol):
    """Streams normalized events directly consumable with ``async for``."""

    def stream_text(
        self, *, model: ModelIdentity, request: AIRequest
    ) -> AsyncIterator[ProviderStreamEvent]: ...


class StructuredOutputProvider(Protocol):
    """Generates a normalized structured result for an explicit specification."""

    async def generate_structured_output(
        self,
        *,
        model: ModelIdentity,
        request: AIRequest,
        spec: StructuredOutputSpec,
    ) -> StructuredOutputResult: ...
