"""Structural provider protocols for normalized AI contracts."""

from collections.abc import AsyncIterator
from typing import Protocol

from sofias_assistant.ai.contracts import (
    AIRequest,
    ModelIdentity,
    ProviderStreamEvent,
    StructuredOutputResult,
    StructuredOutputSpec,
    TextResponse,
)


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
