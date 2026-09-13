"""Deterministic fake providers for offline correctness tests."""

from __future__ import annotations

from collections.abc import Callable

from sofias_assistant.ai.contracts import (
    AIRequest,
    ModelIdentity,
    ProviderResponseMetadata,
    TextResponse,
    ToolCallProposal,
    VisionRequest,
    VisionResponse,
)


class FakeVisionProvider:
    """Return a deterministic observation without network or model credentials."""

    def __init__(self, responder: Callable[[VisionRequest], str] | None = None) -> None:
        self._responder = responder or (
            lambda request: f"Observed image: {request.prompt}"
        )
        self.requests: list[VisionRequest] = []

    async def generate_vision(
        self, *, model: ModelIdentity, request: VisionRequest
    ) -> VisionResponse:
        self.requests.append(request)
        return VisionResponse(
            text=self._responder(request),
            metadata=ProviderResponseMetadata(request.request_id, model),
        )


class FakeAgentProvider:
    """Deterministic text/tool provider for offline Agent loop correctness."""

    def __init__(
        self,
        responder: Callable[[AIRequest, int], tuple[str, tuple[ToolCallProposal, ...]]],
    ) -> None:
        self._responder = responder
        self.requests: list[AIRequest] = []

    async def generate_text(
        self, *, model: ModelIdentity, request: AIRequest
    ) -> TextResponse:
        self.requests.append(request)
        text, tool_calls = self._responder(request, len(self.requests))
        return TextResponse(
            text=text,
            tool_calls=tool_calls,
            metadata=ProviderResponseMetadata(request.request_id, model),
        )
