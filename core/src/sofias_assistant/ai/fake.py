"""Deterministic fake providers for offline correctness tests."""

from __future__ import annotations

from collections.abc import Callable

from sofias_assistant.ai.contracts import (
    ModelIdentity,
    ProviderResponseMetadata,
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
