"""Structural tests for the provider protocols without provider SDKs."""

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest

from sofias_assistant.ai import (
    AIMessage,
    AIMessageRole,
    AIRequest,
    AudioInputFrame,
    ModelIdentity,
    ProviderCompleted,
    ProviderResponseMetadata,
    ProviderStreamEvent,
    RealtimeInteractionId,
    RealtimeProvider,
    RealtimeProviderEvent,
    RealtimeProviderSession,
    RealtimeResponseCompleted,
    RealtimeSessionId,
    RealtimeSessionRequest,
    StructuredOutputProvider,
    StructuredOutputResult,
    StructuredOutputSpec,
    TextGenerationProvider,
    TextResponse,
    TextStreamingProvider,
)


class MinimalProvider:
    """A structural implementation with no SDK inheritance or network I/O."""

    async def generate_text(
        self, *, model: ModelIdentity, request: AIRequest
    ) -> TextResponse:
        return TextResponse(
            text="scripted",
            metadata=ProviderResponseMetadata(request.request_id, model),
        )

    async def generate_structured_output(
        self,
        *,
        model: ModelIdentity,
        request: AIRequest,
        spec: StructuredOutputSpec,
    ) -> StructuredOutputResult:
        return StructuredOutputResult(
            value={"name": spec.name},
            metadata=ProviderResponseMetadata(request.request_id, model),
        )

    async def _stream(
        self, *, model: ModelIdentity, request: AIRequest
    ) -> AsyncIterator[ProviderStreamEvent]:
        yield ProviderCompleted(ProviderResponseMetadata(request.request_id, model))

    def stream_text(
        self, *, model: ModelIdentity, request: AIRequest
    ) -> AsyncIterator[ProviderStreamEvent]:
        return self._stream(model=model, request=request)


class MinimalRealtimeSession:
    """Local structural stub for the specialized realtime protocol."""

    def __init__(self) -> None:
        self.active_interaction_id: RealtimeInteractionId | None = None
        self.completed_interaction_ids: list[RealtimeInteractionId] = []

    async def start_interaction(
        self, *, realtime_interaction_id: RealtimeInteractionId
    ) -> None:
        if self.active_interaction_id is not None:
            raise RuntimeError("an interaction is already active")
        self.active_interaction_id = realtime_interaction_id

    async def send_audio(self, *, frame: AudioInputFrame) -> None:
        assert self.active_interaction_id is not None
        assert frame.sequence >= 0

    async def commit_interaction(
        self, *, realtime_interaction_id: RealtimeInteractionId
    ) -> None:
        assert self.active_interaction_id == realtime_interaction_id
        self.completed_interaction_ids.append(realtime_interaction_id)
        self.active_interaction_id = None

    async def interrupt(
        self, *, realtime_interaction_id: RealtimeInteractionId
    ) -> None:
        assert self.active_interaction_id == realtime_interaction_id
        self.active_interaction_id = None

    async def _events(self) -> AsyncIterator[RealtimeProviderEvent]:
        yield RealtimeResponseCompleted(
            RealtimeSessionId(uuid4()), RealtimeInteractionId(uuid4()), 0
        )

    def events(self) -> AsyncIterator[RealtimeProviderEvent]:
        return self._events()

    async def close(self) -> None:
        return None


class MinimalRealtimeProvider:
    """Local structural stub with no provider SDK, network, or fake framework."""

    async def open_realtime_session(
        self, *, model: ModelIdentity, request: RealtimeSessionRequest
    ) -> RealtimeProviderSession:
        assert model
        assert request.realtime_session_id
        return MinimalRealtimeSession()


def test_specialized_protocols_are_structural() -> None:
    provider = MinimalProvider()

    generation_provider: TextGenerationProvider = provider
    streaming_provider: TextStreamingProvider = provider
    structured_provider: StructuredOutputProvider = provider

    assert generation_provider is provider
    assert streaming_provider is provider
    assert structured_provider is provider


def test_realtime_protocols_are_structural() -> None:
    provider = MinimalRealtimeProvider()
    session = MinimalRealtimeSession()

    realtime_provider: RealtimeProvider = provider
    realtime_session: RealtimeProviderSession = session

    assert realtime_provider is provider
    assert realtime_session is session


@pytest.mark.asyncio
async def test_realtime_session_protocol_supports_sequential_core_interactions() -> (
    None
):
    session = MinimalRealtimeSession()
    first_interaction_id = RealtimeInteractionId(uuid4())
    second_interaction_id = RealtimeInteractionId(uuid4())

    await session.start_interaction(realtime_interaction_id=first_interaction_id)
    await session.send_audio(frame=AudioInputFrame(sequence=0, audio=b"first"))
    await session.commit_interaction(realtime_interaction_id=first_interaction_id)
    await session.start_interaction(realtime_interaction_id=second_interaction_id)
    await session.send_audio(frame=AudioInputFrame(sequence=0, audio=b"second"))
    await session.commit_interaction(realtime_interaction_id=second_interaction_id)

    assert session.completed_interaction_ids == [
        first_interaction_id,
        second_interaction_id,
    ]


@pytest.mark.asyncio
async def test_streaming_protocol_is_consumable_with_async_for() -> None:
    provider = MinimalProvider()
    model = ModelIdentity("test-provider", "test-model")
    request = AIRequest(
        request_id=uuid4(), messages=(AIMessage(AIMessageRole.USER, "Hello"),)
    )

    events = [
        event async for event in provider.stream_text(model=model, request=request)
    ]

    assert len(events) == 1
    assert isinstance(events[0], ProviderCompleted)
