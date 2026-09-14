"""Immutable value objects for Core-owned context projection."""

from dataclasses import dataclass
from uuid import UUID

from sofias_assistant.ai.contracts import AIMessage
from sofias_assistant.memory.models import MemoryLifecycle, MemoryOriginKind, MemoryType


def _require_non_blank(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be blank")


@dataclass(frozen=True, slots=True)
class CoreSystemContext:
    """Explicitly injected Core-owned identity and system principles."""

    text: str
    cloud_context_eligible: bool

    def __post_init__(self) -> None:
        _require_non_blank(self.text, "text")
        if not isinstance(self.cloud_context_eligible, bool):
            raise ValueError("cloud_context_eligible must be a bool")


@dataclass(frozen=True, slots=True)
class MemoryContextItem:
    """Ephemeral, Assistant-owned recall result ready for context projection.

    Never a SQLite entity: MemoryOrchestrator resolves this per-operation from
    Sofias Memory and hands it to ContextBuilder, which never performs I/O
    itself. `content` is untrusted evidence, never authority (ADR-0011 §80).
    """

    memory_id: UUID
    memory_type: MemoryType
    scope: str
    content: str
    relevance: float
    is_current_truth: bool
    lifecycle: MemoryLifecycle
    origin_kind: MemoryOriginKind
    cloud_context_eligible: bool

    def __post_init__(self) -> None:
        if not isinstance(self.memory_id, UUID):
            raise ValueError("memory_id must be a UUID")
        if not isinstance(self.memory_type, MemoryType):
            raise ValueError("memory_type must be a MemoryType")
        _require_non_blank(self.scope, "scope")
        _require_non_blank(self.content, "content")
        if not isinstance(self.relevance, float):
            raise ValueError("relevance must be a float")
        if not isinstance(self.is_current_truth, bool):
            raise ValueError("is_current_truth must be a bool")
        if not isinstance(self.lifecycle, MemoryLifecycle):
            raise ValueError("lifecycle must be a MemoryLifecycle")
        if not isinstance(self.origin_kind, MemoryOriginKind):
            raise ValueError("origin_kind must be a MemoryOriginKind")
        if not isinstance(self.cloud_context_eligible, bool):
            raise ValueError("cloud_context_eligible must be a bool")


@dataclass(frozen=True, slots=True)
class ContextProjection:
    """Provider-independent messages selected by the Core for one operation."""

    messages: tuple[AIMessage, ...]
    cloud_context_eligible: bool

    def __post_init__(self) -> None:
        if not isinstance(self.messages, tuple) or not all(
            isinstance(message, AIMessage) for message in self.messages
        ):
            raise ValueError("messages must be a tuple of AIMessage values")
        if not self.messages:
            raise ValueError("messages must not be empty")
        if not isinstance(self.cloud_context_eligible, bool):
            raise ValueError("cloud_context_eligible must be a bool")
