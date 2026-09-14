"""Seam turning raw evidence text into normalized MemoryCandidate content.

Gate I6 does not perform blanket per-Turn extraction: extraction only runs
under an explicit Remember/Supersede intent, and its output is always a
proposal Memory Policy still evaluates. `FakeMemoryCandidateExtractor` is
deterministic for tests; `StructuredOutputMemoryCandidateExtractor` shows how
a production implementation can reuse the Core's existing STRUCTURED_OUTPUT
capability without ever treating LLM output as authority.
"""

from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

from sofias_assistant.ai.contracts import (
    AIMessage,
    AIMessageRole,
    AIRequest,
    JsonObject,
    ModelIdentity,
    StructuredOutputSpec,
)
from sofias_assistant.ai.providers import StructuredOutputProvider

_EXTRACTION_INSTRUCTIONS = (
    "Normalize the following user-provided text into one concise, factual "
    "memory statement. Do not add information that is not present in the "
    "text. Respond only with the requested JSON object."
)

_EXTRACTION_SCHEMA: JsonObject = {
    "type": "object",
    "properties": {"content": {"type": "string"}},
    "required": ["content"],
    "additionalProperties": False,
}


class PassthroughMemoryCandidateExtractor:
    """Zero-configuration default: trims whitespace, adds no AI dependency.

    A safe Core composition default when no `StructuredOutputProvider` is
    wired in; callers that want AI-assisted normalization inject
    `StructuredOutputMemoryCandidateExtractor` instead.
    """

    async def extract(self, *, text: str) -> str:
        normalized = text.strip()
        if not normalized:
            raise ValueError("extracted memory content must not be blank")
        return normalized


class FakeMemoryCandidateExtractor:
    """Deterministic, offline candidate content normalization for tests."""

    def __init__(self, normalizer: Callable[[str], str] | None = None) -> None:
        self._normalizer = normalizer or (lambda text: text.strip())
        self.requests: list[str] = []

    async def extract(self, *, text: str) -> str:
        self.requests.append(text)
        normalized = self._normalizer(text)
        if not normalized.strip():
            raise ValueError("extracted memory content must not be blank")
        return normalized


class StructuredOutputMemoryCandidateExtractor:
    """Production-capable extractor built on the Core's STRUCTURED_OUTPUT provider.

    The provider's output is a normalization proposal only; it never bypasses
    Memory Policy and never determines PROFILE/SEMANTIC classification, which
    remains an explicit caller/Policy concern.
    """

    def __init__(
        self, *, provider: StructuredOutputProvider, model: ModelIdentity
    ) -> None:
        self._provider = provider
        self._model = model

    async def extract(self, *, text: str) -> str:
        request = AIRequest(
            request_id=uuid4(),
            messages=(
                AIMessage(role=AIMessageRole.SYSTEM, text=_EXTRACTION_INSTRUCTIONS),
                AIMessage(role=AIMessageRole.USER, text=text),
            ),
        )
        spec = StructuredOutputSpec(
            name="memory_candidate_content", schema=_EXTRACTION_SCHEMA
        )
        result = await self._provider.generate_structured_output(
            model=self._model, request=request, spec=spec
        )
        value = result.value
        content_field = value.get("content") if isinstance(value, dict) else None
        if not isinstance(content_field, str):
            raise ValueError("structured extraction returned an invalid shape")
        content = content_field.strip()
        if not content:
            raise ValueError("extracted memory content must not be blank")
        return content
