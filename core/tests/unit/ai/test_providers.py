"""Structural tests for the provider protocols without provider SDKs."""

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest

from sofias_assistant.ai import (
    AIMessage,
    AIMessageRole,
    AIRequest,
    ModelIdentity,
    ProviderCompleted,
    ProviderResponseMetadata,
    ProviderStreamEvent,
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


def test_specialized_protocols_are_structural() -> None:
    provider = MinimalProvider()

    generation_provider: TextGenerationProvider = provider
    streaming_provider: TextStreamingProvider = provider
    structured_provider: StructuredOutputProvider = provider

    assert generation_provider is provider
    assert streaming_provider is provider
    assert structured_provider is provider


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
